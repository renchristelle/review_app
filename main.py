"""Review App — FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from review_app.auth import verify_session_token
from review_app.config import load_config
from review_app.langfuse_reader import LangfuseReader
from review_app.router import router

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app() -> FastAPI:
    cfg = load_config()
    reader = LangfuseReader(
        public_key=cfg.langfuse_public_key,
        secret_key=cfg.langfuse_secret_key,
        host=cfg.langfuse_host,
        allowed_run_names=cfg.test_run_names,
    )

    app = FastAPI(title="Review Fiches Hôtels")
    app.state.config = cfg
    app.state.reader = reader
    app.state.templates = templates

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        # Laisser passer /login et les assets statiques
        if path.startswith("/login") or path.startswith("/static"):
            return await call_next(request)

        session = request.cookies.get("session")
        if not session or not verify_session_token(cfg.app_secret, cfg.app_username, session):
            next_url = path
            if request.url.query:
                next_url += f"?{request.url.query}"
            return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

        return await call_next(request)

    # Mount static AVANT le router pour éviter que /{run_name} n'intercepte /static/*
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)

    return app


app = create_app()
