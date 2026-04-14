"""Lecture des données Langfuse pour la review app.

Les traces d'évaluation ont metadata.run_name mais pas de lien dataset run formel.
On interroge donc les traces directement et on filtre côté client.

Utilise LangfuseAPI (SDK v4) à la place de l'ancien Langfuse qui n'expose plus
fetch_traces / fetch_trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langfuse.api import LangfuseAPI


def _extract_provider_text(inp: dict, provider_name: str) -> str:
    """Extrait le texte concaténé d'un provider depuis le format providers[] (nouveau format)."""
    for provider in inp.get("providers") or []:
        if provider.get("name") == provider_name:
            return "\n".join(
                d["value"] for d in provider.get("descriptions", []) if d.get("value", "").strip()
            )
    return ""


@dataclass
class TraceSummary:
    """Résumé d'une trace pour la liste des hôtels."""

    trace_id: str
    run_name: str
    hotel_name: str
    ville: str
    pays: str


@dataclass
class JudgeScore:
    name: str  # "fidelite" | "qualite_redactionnelle" | "completude"
    value: float  # 1–5
    comment: str


@dataclass
class TraceDetail:
    """Détail complet d'une trace pour la page de notation."""

    trace_id: str
    hotel_name: str
    ville: str
    pays: str
    description_booking: str
    description_expedia: str
    # 10 rubriques générées
    descriptif: str
    localisation: str
    mode_acces: str
    tourisme_responsable: str
    chambre: str
    service: str
    restaurant: str
    activite_gratuite: str
    activite_avec_participation: str
    enfants: str
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
            inp = t.input or {}
            result.append(
                TraceSummary(
                    trace_id=t.id,
                    run_name=run_name,
                    hotel_name=inp.get("name") or inp.get("nom_hotel") or t.id[:8],
                    ville=inp.get("ville") or "",
                    pays=inp.get("pays") or "",
                )
            )
        return result

    def get_trace_detail(self, trace_id: str) -> TraceDetail:
        """Retourne le détail complet d'une trace (input, output, scores).

        Lève ValueError si la trace n'existe pas dans le projet Langfuse.
        """
        try:
            raw = self._lf.trace.get(trace_id)
        except Exception as e:
            raise ValueError(f"Trace introuvable dans Langfuse : {trace_id}") from e
        inp = raw.input or {}
        out = raw.output or {}

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
            hotel_name=inp.get("name") or inp.get("nom_hotel") or trace_id[:8],
            ville=inp.get("ville") or "",
            pays=inp.get("pays") or "",
            description_booking=_extract_provider_text(inp, "BOW")
            or inp.get("description_booking")
            or "",
            description_expedia=_extract_provider_text(inp, "RXE")
            or inp.get("description_expedia")
            or "",
            descriptif=out.get("descriptif") or "",
            localisation=out.get("localisation") or "",
            mode_acces=out.get("mode_acces") or "",
            tourisme_responsable=out.get("tourisme_responsable") or "",
            chambre=out.get("chambre") or "",
            service=out.get("service") or "",
            restaurant=out.get("restaurant") or "",
            activite_gratuite=out.get("activite_gratuite") or "",
            activite_avec_participation=out.get("activite_avec_participation") or "",
            enfants=out.get("enfants") or "",
            scores=scores,
        )

    def _fetch_all_eval_traces(self):
        """Pagine toutes les traces d'évaluation (metadata.run_name présent)."""
        page, all_traces = 1, []
        while True:
            resp = self._lf.trace.list(name="eval-generate", page=page, limit=50)
            batch = resp.data or []
            all_traces.extend(batch)
            if len(batch) < 50:
                break
            page += 1

        # Garder les traces avec run_name ; restreindre aux runs listés dans config si défini
        out = [t for t in all_traces if (t.metadata or {}).get("run_name")]
        if self._allowed_run_names is not None:
            out = [t for t in out if (t.metadata or {}).get("run_name") in self._allowed_run_names]
        return out
