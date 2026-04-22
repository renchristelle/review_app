"""Configuration de la review app — charge .env et config.yaml."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent

# Charge .env si présent
_env_file = ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class AppConfig:
    reviewers: list[str]
    reviewer_sessions: dict[str, frozenset[str]]
    test_run_names: frozenset[str] | None
    judge_reviewers: frozenset[str]
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str
    votes_csv_path: Path
    comments_csv_path: Path
    likes_csv_path: Path
    app_username: str
    app_password: str
    app_secret: str

    @property
    def reviews_csv_path(self) -> Path:
        """Alias pour compatibilité avec le code existant."""
        return self.votes_csv_path

    def allowed_sessions_for(self, reviewer: str) -> frozenset[str]:
        """Retourne les sessions autorisées pour un reviewer. Vide = pas de restriction."""
        return self.reviewer_sessions.get(reviewer, frozenset())

    def can_see_judge_scores(self, reviewer: str) -> bool:
        return reviewer in self.judge_reviewers


def load_config() -> AppConfig:
    cfg_path = Path(__file__).parent / "config.yaml"
    with cfg_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    reviewer_names: list[str] = []
    reviewer_sessions: dict[str, frozenset[str]] = {}

    for item in raw.get("reviewers", []):
        if isinstance(item, dict):
            name = str(item["name"]).strip()
            sessions = frozenset(str(s).strip() for s in (item.get("sessions") or []) if str(s).strip())
        else:
            name = str(item).strip()
            sessions = frozenset()
        reviewer_names.append(name)
        reviewer_sessions[name] = sessions

    # Union de toutes les sessions pour le filtre global Langfuse
    all_sessions = frozenset().union(*reviewer_sessions.values()) if reviewer_sessions else frozenset()
    test_run_names = all_sessions if all_sessions else None

    judge_reviewers = frozenset(str(r).strip() for r in raw.get("judge_reviewers", []))

    reviews_dir = ROOT / "data" / "reviews"
    return AppConfig(
        reviewers=reviewer_names,
        reviewer_sessions=reviewer_sessions,
        test_run_names=test_run_names,
        judge_reviewers=judge_reviewers,
        langfuse_public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        langfuse_secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        langfuse_host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        votes_csv_path=reviews_dir / "votes.csv",
        comments_csv_path=reviews_dir / "comments.csv",
        likes_csv_path=reviews_dir / "likes.csv",
        app_username=os.environ.get("APP_USERNAME", "admin"),
        app_password=os.environ["APP_PASSWORD"],
        app_secret=os.environ.get("APP_SECRET", "change-me-in-production"),
    )
