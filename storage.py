"""Stockage CSV des votes, commentaires et likes — thread-safe via threading.Lock."""

from __future__ import annotations

import csv
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RUBRIQUES = [
    "descriptif",
    "localisation",
    "mode_acces",
    "tourisme_responsable",
    "chambre",
    "service",
    "restaurant",
    "activite_gratuite",
    "activite_avec_participation",
    "enfants",
]

_VOTES_FIELDS = ["run_name", "trace_id", "hotel_name", "reviewer", "rubrique", "vote", "saved_at"]
_COMMENTS_FIELDS = [
    "comment_id",
    "run_name",
    "trace_id",
    "rubrique",
    "reviewer",
    "text",
    "created_at",
]
_LIKES_FIELDS = ["reviewer", "comment_id"]

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers bas niveau
# ---------------------------------------------------------------------------


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append(path: Path, row: dict, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------


@dataclass
class VoteRow:
    vote: str  # "ok" | "ko"


def save_vote(
    votes_path: Path,
    run_name: str,
    trace_id: str,
    hotel_name: str,
    reviewer: str,
    rubrique: str,
    vote: str,
) -> None:
    """Upsert d'un vote pour le triplet (reviewer, trace_id, rubrique)."""
    new_row = {
        "run_name": run_name,
        "trace_id": trace_id,
        "hotel_name": hotel_name,
        "reviewer": reviewer,
        "rubrique": rubrique,
        "vote": vote,
        "saved_at": datetime.now(UTC).isoformat(),
    }
    with _lock:
        rows = _read(votes_path)
        updated = False
        for i, row in enumerate(rows):
            if (
                row["reviewer"] == reviewer
                and row["trace_id"] == trace_id
                and row["rubrique"] == rubrique
            ):
                rows[i] = new_row
                updated = True
                break
        if not updated:
            rows.append(new_row)
        _write(votes_path, rows, _VOTES_FIELDS)


def get_votes_for_hotel(
    votes_path: Path, run_name: str, trace_id: str
) -> dict[str, dict[str, str]]:
    """Retourne {rubrique: {reviewer: vote}} pour tous les reviewers d'un hôtel."""
    result: dict[str, dict[str, str]] = {}
    for row in _read(votes_path):
        if row.get("run_name") != run_name or row.get("trace_id") != trace_id:
            continue
        rub = row["rubrique"]
        rev = row["reviewer"]
        result.setdefault(rub, {})[rev] = row["vote"]
    return result


def get_votes(votes_path: Path, run_name: str, reviewer: str) -> dict[str, dict[str, VoteRow]]:
    """Retourne {trace_id: {rubrique: VoteRow}} pour un reviewer — utilisé pour la progression."""
    result: dict[str, dict[str, VoteRow]] = {}
    for row in _read(votes_path):
        if row.get("run_name") != run_name or row.get("reviewer") != reviewer:
            continue
        result.setdefault(row["trace_id"], {})[row["rubrique"]] = VoteRow(vote=row["vote"])
    return result


def get_all_progress(votes_path: Path, run_name: str, trace_ids: list[str]) -> dict[str, dict]:
    """Retourne {reviewer: {completed, total}} pour le dashboard."""
    data: dict[str, dict[str, set]] = {}
    for row in _read(votes_path):
        if row.get("run_name") != run_name:
            continue
        data.setdefault(row["reviewer"], {}).setdefault(row["trace_id"], set()).add(row["rubrique"])

    total = len(trace_ids)
    return {
        reviewer: {
            "completed": sum(
                1 for tid in trace_ids if len(hotel_map.get(tid, set())) >= len(RUBRIQUES)
            ),
            "total": total,
        }
        for reviewer, hotel_map in data.items()
    }


# ---------------------------------------------------------------------------
# Commentaires
# ---------------------------------------------------------------------------


@dataclass
class Comment:
    comment_id: str
    reviewer: str
    text: str
    created_at: str
    likes: list[str] = field(default_factory=list)  # reviewers qui ont liké


def add_comment(
    comments_path: Path,
    run_name: str,
    trace_id: str,
    rubrique: str,
    reviewer: str,
    text: str,
) -> str:
    """Append un nouveau commentaire. Retourne le comment_id généré."""
    comment_id = str(uuid.uuid4())
    row = {
        "comment_id": comment_id,
        "run_name": run_name,
        "trace_id": trace_id,
        "rubrique": rubrique,
        "reviewer": reviewer,
        "text": text,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with _lock:
        _append(comments_path, row, _COMMENTS_FIELDS)
    return comment_id


def get_comments_for_hotel(
    comments_path: Path, likes_path: Path, run_name: str, trace_id: str
) -> dict[str, list[Comment]]:
    """Retourne {rubrique: [Comment, ...]} trié par created_at ASC."""
    # Index likes par comment_id
    likes_index: dict[str, list[str]] = {}
    for row in _read(likes_path):
        likes_index.setdefault(row["comment_id"], []).append(row["reviewer"])

    result: dict[str, list[Comment]] = {}
    for row in _read(comments_path):
        if row.get("run_name") != run_name or row.get("trace_id") != trace_id:
            continue
        rub = row["rubrique"]
        cid = row["comment_id"]
        result.setdefault(rub, []).append(
            Comment(
                comment_id=cid,
                reviewer=row["reviewer"],
                text=row["text"],
                created_at=row["created_at"],
                likes=likes_index.get(cid, []),
            )
        )

    # Tri ASC par created_at
    for comments in result.values():
        comments.sort(key=lambda c: c.created_at)
    return result


# ---------------------------------------------------------------------------
# Likes
# ---------------------------------------------------------------------------


def toggle_like(likes_path: Path, reviewer: str, comment_id: str) -> tuple[bool, list[str]]:
    """Toggle le like d'un reviewer sur un commentaire.

    Retourne (liked: bool, likers: list[str]) après l'opération.
    """
    with _lock:
        rows = _read(likes_path)
        existing = next(
            (
                i
                for i, r in enumerate(rows)
                if r["reviewer"] == reviewer and r["comment_id"] == comment_id
            ),
            None,
        )
        if existing is not None:
            rows.pop(existing)
            liked = False
        else:
            rows.append({"reviewer": reviewer, "comment_id": comment_id})
            liked = True
        _write(likes_path, rows, _LIKES_FIELDS)
        likers = [r["reviewer"] for r in rows if r["comment_id"] == comment_id]
    return liked, likers
