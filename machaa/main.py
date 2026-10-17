"""FastAPI application for the local MACHAA dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from machaa import __version__
from machaa.api.routes import router
from machaa.config import Settings
from machaa.core.service import TaskService
from machaa.webinfo import asset_version, build_label

WEB_DIR = Path(__file__).resolve().parent / "web"
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}


def create_app(settings: Settings | None = None, browser_factory=None) -> FastAPI:
    """Build the app. Tests pass a temporary data directory and a fake browser."""

    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    service = TaskService(settings, browser_factory)
    app = FastAPI(title="MACHAA", version=__version__)
    app.state.settings = settings
    app.state.service = service

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.get("/")
    def dashboard() -> HTMLResponse:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("__ASSET_VERSION__", asset_version()).replace("__BUILD_LABEL__", build_label())
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")
    return app


def main() -> None:
    """Start the local server. Docker and the start scripts call this."""

    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    uvicorn.run(
        "machaa.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
