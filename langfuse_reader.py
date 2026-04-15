"""Lecture des données Langfuse pour la review app — fiches client restructuration.

Les traces ont metadata.run_name et le nom "enrich-client-record".
On interroge les traces directement et on filtre côté client.

Utilise LangfuseAPI (SDK v4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langfuse.api import LangfuseAPI


def _client_record(inp: dict) -> dict:
    """Extrait les champs de la fiche client depuis l'input de la trace.

    Langfuse @observe capture les arguments : l'input peut être
    {"client_record": {...}} ou directement les champs à plat.
    """
    if "client_record" in inp:
        cr = inp["client_record"]
        return cr if isinstance(cr, dict) else {}
    return inp


def _make_label(trace_id: str) -> str:
    """Construit un libellé lisible pour identifier la fiche client."""
    return f"Fiche_{trace_id}"


@dataclass
class TraceSummary:
    """Résumé d'une trace pour la liste des fiches."""

    trace_id: str
    run_name: str
    label: str  # identifiant lisible de la fiche client


@dataclass
class JudgeScore:
    name: str
    value: float
    comment: str


@dataclass
class TraceDetail:
    """Détail complet d'une trace pour la page de notation."""

    trace_id: str
    label: str
    # Fiche originale (input)
    meteo_input: str
    person_input: str
    travel_input: str
    needs_input: str
    # Fiche enrichie (output)
    meteo: str
    person: str
    travel: str
    needs: str
    # Scores juge
    scores: list[JudgeScore] = field(default_factory=list)


class LangfuseReader:
    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str,
        *,
        allowed_run_names: frozenset[str] | None = None,
    ) -> None:
        self._lf = LangfuseAPI(
            base_url=host,
            username=public_key,
            password=secret_key,
        )
        self._allowed_run_names = allowed_run_names

    def list_runs(self) -> list[dict]:
        """Retourne les runs uniques triés par nom, avec le nombre de traces."""
        traces = self._fetch_all_eval_traces()
        runs: dict[str, list] = {}
        for t in traces:
            run_name = (t.metadata or {}).get("run_name")
            if run_name:
                runs.setdefault(run_name, []).append(t)
        return [
            {"name": name, "count": len(ts)}
            for name, ts in sorted(runs.items(), key=lambda x: x[0])
        ]

    def get_run_traces(self, run_name: str) -> list[TraceSummary]:
        """Retourne les traces d'un run donné."""
        traces = self._fetch_all_eval_traces()
        result = []
        for t in traces:
            if (t.metadata or {}).get("run_name") != run_name:
                continue
            result.append(
                TraceSummary(
                    trace_id=t.id,
                    run_name=run_name,
                    label=_make_label(t.id),
                )
            )
        return result

    def get_trace_detail(self, trace_id: str) -> TraceDetail:
        """Retourne le détail complet d'une trace (input, output, scores).

        Lève ValueError si la trace n'existe pas dans Langfuse.
        """
        try:
            raw = self._lf.trace.get(trace_id)
        except Exception as e:
            raise ValueError(f"Trace introuvable dans Langfuse : {trace_id}") from e

        inp = raw.input or {}
        out = raw.output or {}
        cr = _client_record(inp)

        scores = []
        for s in raw.scores or []:
            scores.append(
                JudgeScore(
                    name=s.name,
                    value=float(s.value),
                    comment=s.comment or "",
                )
            )

        return TraceDetail(
            trace_id=trace_id,
            label=_make_label(trace_id),
            # Input : fiche originale
            meteo_input=cr.get("meteo") or "",
            person_input=cr.get("person") or "",
            travel_input=cr.get("travel") or "",
            needs_input=cr.get("needs") or "",
            # Output : fiche enrichie
            meteo=out.get("meteo") or "",
            person=out.get("person") or "",
            travel=out.get("travel") or "",
            needs=out.get("needs") or "",
            scores=scores,
        )

    def _fetch_all_eval_traces(self):
        """Pagine toutes les traces d'évaluation (metadata.run_name présent)."""
        page, all_traces = 1, []
        while True:
            resp = self._lf.trace.list(
                name="enrich-client-record-dev", page=page, limit=50
            )
            batch = resp.data or []
            all_traces.extend(batch)
            if len(batch) < 50:
                break
            page += 1

        out = [t for t in all_traces if (t.metadata or {}).get("run_name")]
        if self._allowed_run_names is not None:
            out = [
                t
                for t in out
                if (t.metadata or {}).get("run_name") in self._allowed_run_names
            ]
        return out
