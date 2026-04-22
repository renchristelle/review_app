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

    Langfuse @observe capture les arguments sous plusieurs formes possibles :
    - {"args": [{...champs...}], "kwargs": {}}  ← cas le plus courant
    - {"client_record": {...}}
    - directement les champs à plat
    """
    # Cas {"args": [{...}], "kwargs": {}}
    if "args" in inp and isinstance(inp["args"], list) and inp["args"]:
        first = inp["args"][0]
        if isinstance(first, dict):
            return first
    # Cas {"client_record": {...}}
    if "client_record" in inp:
        cr = inp["client_record"]
        return cr if isinstance(cr, dict) else {}
    return inp


def _fmt_list(items: list | None) -> str:
    """Convertit une liste de strings en texte bullet '- item\\n'."""
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items)


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
    demands_input: list = field(default_factory=list)
    # Sous-rubriques enrichies (MergeModelOutput)
    commercial: str = ""
    pro: str = ""
    perso: str = ""
    health: str = ""
    languages: str = ""
    security: str = ""
    air: str = ""
    car: str = ""
    housing: str = ""
    rythme: str = ""
    activities: str = ""
    good_to_know_travel: str = ""
    needs: str = ""
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
        cr = _client_record(inp)

        scores = self._fetch_scores(trace_id)

        merge = self._get_merge_output(trace_id)

        return TraceDetail(
            trace_id=trace_id,
            label=_make_label(trace_id),
            # Input : fiche originale
            meteo_input=cr.get("meteo") or "",
            person_input=cr.get("person") or "",
            travel_input=cr.get("travel") or "",
            needs_input=cr.get("needs") or "",
            demands_input=cr.get("demands") or [],
            # Sous-rubriques depuis le MergeModelOutput
            commercial=merge.get("commercial", ""),
            pro=merge.get("pro", ""),
            perso=merge.get("perso", ""),
            health=merge.get("health", ""),
            languages=merge.get("languages", ""),
            security=merge.get("security", ""),
            air=merge.get("air", ""),
            car=merge.get("car", ""),
            housing=merge.get("housing", ""),
            rythme=merge.get("rythme", ""),
            activities=merge.get("activities", ""),
            good_to_know_travel=merge.get("good_to_know_travel", ""),
            needs=merge.get("needs", ""),
            scores=scores,
        )

    def _fetch_scores(self, trace_id: str) -> list[JudgeScore]:
        """Récupère les scores via l'endpoint dédié pour avoir les commentaires."""
        try:
            resp = self._lf.score.get_many(trace_id=trace_id, limit=50)
            raw_scores = resp.data or []
        except Exception:
            return []
        return [
            JudgeScore(
                name=s.name,
                value=float(s.value),
                comment=s.comment or "",
            )
            for s in raw_scores
            if s.value is not None
        ]

    def _get_merge_output(self, trace_id: str) -> dict[str, str]:
        """Extrait le MergeModelOutput depuis les observations Langfuse.

        Stratégie : trouver le PydanticToolsParser qui n'est pas descendant
        des spans nommés 'client-record-enrichment' ou 'demands-extraction',
        et dont l'output contient 'commercial' mais pas 'actuality'.

        Retourne un dict {sous_rubrique: texte_formaté}.
        """
        import json

        try:
            obs_resp = self._lf.observations.get_many(
                trace_id=trace_id, fields="basic,io", limit=100
            )
            obs = obs_resp.data or []
        except Exception:
            return {}

        # Identifier les spans des deux enrichissements parallèles
        named_ids = {
            o.id
            for o in obs
            if o.name in ("client-record-enrichment", "demands-extraction")
        }

        # Construire l'ensemble de tous leurs descendants
        def _descendants(parent_id: str) -> set[str]:
            result: set[str] = set()
            for o in obs:
                if o.parent_observation_id == parent_id:
                    result.add(o.id)
                    result |= _descendants(o.id)
            return result

        excluded = set(named_ids)
        for nid in named_ids:
            excluded |= _descendants(nid)

        # Chercher le PydanticToolsParser du merge (hors descendants exclus)
        for o in obs:
            if o.type != "CHAIN" or o.name != "PydanticToolsParser":
                continue
            if o.id in excluded:
                continue
            raw_out = o.output
            if raw_out is None:
                continue
            if isinstance(raw_out, str):
                try:
                    data = json.loads(raw_out)
                except json.JSONDecodeError:
                    continue
            else:
                data = raw_out
            if not isinstance(data, dict):
                continue
            if "commercial" not in data or "actuality" in data:
                continue
            # Convertir chaque liste en texte formaté bullet
            return {k: _fmt_list(v) for k, v in data.items()}

        return {}

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
