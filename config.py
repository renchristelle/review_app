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


def _parse_test_run_names(raw_value) -> frozenset[str] | None:
    """Lit test_run_name depuis le YAML (str ou liste). Vide / absent → pas de filtre."""
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        parts = [raw_value.strip()] if raw_value.strip() else []
    elif isinstance(raw_value, list):
        parts = [str(x).strip() for x in raw_value if str(x).strip()]
    else:
        parts = []
    return frozenset(parts) if parts else None


@dataclass
class AppConfig:
    reviewers: list[str]
    test_run_names: frozenset[str] | None
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


def load_config() -> AppConfig:
    cfg_path = Path(__file__).parent / "config.yaml"
    with cfg_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    reviews_dir = ROOT / "data" / "reviews"
    return AppConfig(
        reviewers=raw.get("reviewers", []),
        test_run_names=_parse_test_run_names(raw.get("test_run_name")),
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
