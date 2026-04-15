"""Routes de la review app."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from review_app import storage
from review_app.auth import make_session_token

router = APIRouter()

RUBRIQUES_LABELS = {
    "commercial": "Suivi commercial",
    "pro": "Pro",
    "perso": "Perso",
    "health": "Santé",
    "languages": "Langues",
    "security": "Sécurité",
    "air": "Aérien",
    "car": "Transport / Voiture",
    "housing": "Hébergement",
    "rythme": "Rythme",
    "activities": "Activités",
    "good_to_know_travel": "Bon à savoir",
    "needs": "Comment lui faire plaisir",
}


def _templates(request: Request):
    return request.app.state.templates


def _cfg(request: Request):
    return request.app.state.config


def _reader(request: Request):
    return request.app.state.reader


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    return _templates(request).TemplateResponse(
        request, "login.html", {"next": next, "error": None}
    )


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    next_url = str(form.get("next", "/"))

    cfg = _cfg(request)
    if username == cfg.app_username and password == cfg.app_password:
        token = make_session_token(cfg.app_secret, username)
        response = RedirectResponse(url=next_url, status_code=303)
        response.set_cookie("session", token, httponly=True, max_age=7 * 24 * 3600, samesite="lax")
        return response

    return _templates(request).TemplateResponse(
        request,
        "login.html",
        {"next": next_url, "error": "Identifiant ou mot de passe incorrect."},
        status_code=401,
    )


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, reviewer: str | None = Cookie(default=None)):
    runs = _reader(request).list_runs()
    cfg = _cfg(request)

    progress_by_run = {}
    for run in runs:
        run_name = run["name"]
        traces = _reader(request).get_run_traces(run_name)
        trace_ids = [t.trace_id for t in traces]
        progress_by_run[run_name] = storage.get_all_progress(
            cfg.votes_csv_path, run_name, trace_ids
        )

    return _templates(request).TemplateResponse(
        request,
        "dashboard.html",
        {
            "runs": runs,
            "progress_by_run": progress_by_run,
            "reviewers": cfg.reviewers,
            "current_reviewer": reviewer or "",
        },
    )


# ---------------------------------------------------------------------------
# Liste des hôtels d'un run
# ---------------------------------------------------------------------------


@router.get("/{run_name}", response_class=HTMLResponse)
async def hotel_list(
    request: Request,
    run_name: str,
    reviewer: str | None = None,
    filter: str = "all",
    reviewer_cookie: str | None = Cookie(alias="reviewer", default=None),
):
    effective_reviewer = reviewer or reviewer_cookie or ""
    cfg = _cfg(request)
    traces = _reader(request).get_run_traces(run_name)

    votes = storage.get_votes(cfg.votes_csv_path, run_name, effective_reviewer)

    all_complete = [len(votes.get(t.trace_id, {})) >= len(storage.RUBRIQUES) for t in traces]
    counts = {
        "all": len(traces),
        "todo": sum(1 for c in all_complete if not c),
        "done": sum(1 for c in all_complete if c),
    }

    hotels = []
    for t, complete in zip(traces, all_complete, strict=False):
        nb_voted = len(votes.get(t.trace_id, {}))
        hotels.append(
            {
                "trace_id": t.trace_id,
                "label": t.label,
                "nb_voted": nb_voted,
                "total": len(storage.RUBRIQUES),
                "complete": complete,
            }
        )

    if filter == "todo":
        hotels = [h for h in hotels if not h["complete"]]
    elif filter == "done":
        hotels = [h for h in hotels if h["complete"]]

    return _templates(request).TemplateResponse(
        request,
        "list.html",
        {
            "run_name": run_name,
            "hotels": hotels,
            "current_reviewer": effective_reviewer,
            "reviewers": cfg.reviewers,
            "filter": filter,
            "counts": counts,
        },
    )


# ---------------------------------------------------------------------------
# Page de notation d'un hôtel
# ---------------------------------------------------------------------------


@router.get("/{run_name}/{trace_id}", response_class=HTMLResponse)
async def review_hotel(
    request: Request,
    run_name: str,
    trace_id: str,
    reviewer: str | None = None,
    reviewer_cookie: str | None = Cookie(alias="reviewer", default=None),
):
    effective_reviewer = reviewer or reviewer_cookie or ""
    cfg = _cfg(request)

    try:
        detail = _reader(request).get_trace_detail(trace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Tous les votes de tous les reviewers pour cet hôtel
    all_votes = storage.get_votes_for_hotel(cfg.votes_csv_path, run_name, trace_id)
    # Mon vote courant : sous-ensemble de all_votes
    my_vote = {
        rub: voters[effective_reviewer]
        for rub, voters in all_votes.items()
        if effective_reviewer in voters
    }

    # Commentaires + likes
    comments_by_rubrique = storage.get_comments_for_hotel(
        cfg.comments_csv_path, cfg.likes_csv_path, run_name, trace_id
    )
    # Sérialiser en dict pour Jinja2 / tojson
    comments_json = {
        rub: [asdict(c) for c in comments] for rub, comments in comments_by_rubrique.items()
    }

    # Navigation précédent / suivant
    traces = _reader(request).get_run_traces(run_name)
    trace_ids = [t.trace_id for t in traces]
    idx = trace_ids.index(trace_id) if trace_id in trace_ids else 0
    prev_id = trace_ids[idx - 1] if idx > 0 else None
    next_id = trace_ids[idx + 1] if idx < len(trace_ids) - 1 else None

    judge_scores = {s.name: s for s in detail.scores}
    rubriques = list(RUBRIQUES_LABELS.items())

    return _templates(request).TemplateResponse(
        request,
        "review.html",
        {
            "run_name": run_name,
            "trace_id": trace_id,
            "detail": detail,
            "all_votes": all_votes,
            "my_vote": my_vote,
            "comments_by_rubrique": comments_json,
            "judge_scores": judge_scores,
            "rubriques": rubriques,
            "current_reviewer": effective_reviewer,
            "reviewers": cfg.reviewers,
            "fiche_index": idx + 1,
            "fiche_total": len(trace_ids),
            "prev_id": prev_id,
            "next_id": next_id,
        },
    )


# ---------------------------------------------------------------------------
# Vote (auto-save)
# ---------------------------------------------------------------------------


class VotePayload(BaseModel):
    run_name: str
    trace_id: str
    label: str
    reviewer: str
    rubrique: str
    vote: str  # "ok" | "ko"


@router.post("/vote", status_code=204)
async def save_vote(request: Request, payload: VotePayload, response: Response):
    cfg = _cfg(request)
    if not payload.reviewer or payload.reviewer not in cfg.reviewers:
        raise HTTPException(status_code=403, detail="Reviewer non reconnu. Sélectionnez votre nom.")
    storage.save_vote(
        votes_path=cfg.votes_csv_path,
        run_name=payload.run_name,
        trace_id=payload.trace_id,
        hotel_name=payload.label,
        reviewer=payload.reviewer,
        rubrique=payload.rubrique,
        vote=payload.vote,
    )
    response.set_cookie("reviewer", payload.reviewer, max_age=7 * 24 * 3600)


# ---------------------------------------------------------------------------
# Commentaire
# ---------------------------------------------------------------------------


class CommentPayload(BaseModel):
    run_name: str
    trace_id: str
    rubrique: str
    reviewer: str
    text: str


@router.post("/comment", status_code=201)
async def post_comment(request: Request, payload: CommentPayload):
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Le commentaire ne peut pas être vide.")
    cfg = _cfg(request)
    if not payload.reviewer or payload.reviewer not in cfg.reviewers:
        raise HTTPException(status_code=403, detail="Reviewer non reconnu. Sélectionnez votre nom.")
    comment_id = storage.add_comment(
        comments_path=cfg.comments_csv_path,
        run_name=payload.run_name,
        trace_id=payload.trace_id,
        rubrique=payload.rubrique,
        reviewer=payload.reviewer,
        text=payload.text.strip(),
    )
    from datetime import datetime

    return JSONResponse(
        {
            "comment_id": comment_id,
            "reviewer": payload.reviewer,
            "text": payload.text.strip(),
            "created_at": datetime.now(UTC).isoformat(),
            "likes": [],
        },
        status_code=201,
    )


# ---------------------------------------------------------------------------
# Like
# ---------------------------------------------------------------------------


class LikePayload(BaseModel):
    reviewer: str
    comment_id: str


@router.post("/like")
async def toggle_like(request: Request, payload: LikePayload):
    cfg = _cfg(request)
    if not payload.reviewer or payload.reviewer not in cfg.reviewers:
        raise HTTPException(status_code=403, detail="Reviewer non reconnu. Sélectionnez votre nom.")
    liked, likers = storage.toggle_like(
        likes_path=cfg.likes_csv_path,
        reviewer=payload.reviewer,
        comment_id=payload.comment_id,
    )
    return {"liked": liked, "count": len(likers), "likers": likers}


# ---------------------------------------------------------------------------
# Cookie reviewer
# ---------------------------------------------------------------------------


@router.post("/set-reviewer")
async def set_reviewer(request: Request):
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    form = await request.form()
    reviewer = str(form.get("reviewer", ""))
    redirect_to = str(form.get("redirect_to", "/"))

    # Remove ?reviewer= from redirect URL so the new cookie takes effect
    parsed = urlparse(redirect_to)
    params = {
        k: v[0]
        for k, v in parse_qs(parsed.query, keep_blank_values=True).items()
        if k != "reviewer"
    }
    redirect_to = urlunparse(parsed._replace(query=urlencode(params)))

    response = RedirectResponse(url=redirect_to, status_code=303)
    response.set_cookie("reviewer", reviewer, max_age=7 * 24 * 3600)
    return response
