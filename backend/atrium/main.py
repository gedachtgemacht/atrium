"""App factory. Run with: uvicorn atrium.main:app --no-access-log"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agents.config import load_agents
from .agents.runner import sync_agents
from .config import Settings, get_settings
from .db import Database
from .llm.client import LLMClient
from .rooms.notes import FakeTranscriber, NotesService, WhisperTranscriber
from .rooms.presence import Presence
from .state import AppState

log = logging.getLogger("atrium")


def build_state(settings: Settings, provider=None, transcriber=None) -> AppState:
    db = Database(settings.database_url)
    state = AppState(settings=settings, db=db, llm=LLMClient(db.sessions, settings, provider), agents=load_agents(settings.agents_dir))
    state.presence = Presence()
    if transcriber is None:
        transcriber = FakeTranscriber() if settings.whisper_model == "fake" else WhisperTranscriber(settings.whisper_model, settings.whisper_language)
    state.notes = NotesService(state, transcriber)
    return state


async def _abort_stale_runs(state: AppState) -> None:
    from sqlalchemy import update

    from .db import utcnow
    from .models import AgentRun

    async with state.db.sessions() as s:
        await s.execute(update(AgentRun).where(AgentRun.status == "running").values(status="aborted", finished_at=utcnow()))
        await s.commit()


async def _retention_loop(state: AppState) -> None:
    from .api.admin import apply_retention

    while True:
        try:
            await apply_retention(state)
        except Exception:
            log.exception("retention failed")
        await asyncio.sleep(24 * 3600)


def create_app(settings: Settings | None = None, *, provider=None, transcriber=None, background: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = build_state(settings, provider, transcriber)
        app.state.atrium = state
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        async with state.db.sessions() as s:
            await sync_agents(state, s)
        from .api.ws import load_rooms

        await load_rooms(state)
        await _abort_stale_runs(state)
        retention = asyncio.create_task(_retention_loop(state)) if background else None
        yield
        if retention:
            retention.cancel()
        await state.tasks.shutdown()
        await state.db.dispose()

    app = FastAPI(title="Atrium", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")

    from .api import admin, auth, channels, work, ws
    from .guest import routes as guest_routes

    for r in (auth.router, auth.me_router, channels.router, work.router, admin.router, guest_routes.router, ws.router):
        app.include_router(r)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws: wss:; media-src 'self' blob:; frame-ancestors 'self'",
        )
        return resp

    dist = settings.frontend_dist
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    if (dist / "fonts").exists():
        app.mount("/fonts", StaticFiles(directory=dist / "fonts"), name="fonts")

    @app.get("/g/{rest:path}", include_in_schema=False)
    async def guest_app(rest: str):
        if rest.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        page = dist / "guest.html"
        return FileResponse(page) if page.exists() else JSONResponse({"detail": "Frontend not built"}, status_code=503)

    @app.get("/{rest:path}", include_in_schema=False)
    async def internal_app(rest: str):
        if rest.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        static = dist / rest
        if rest and static.is_file() and static.resolve().is_relative_to(dist.resolve()):
            return FileResponse(static)
        page = dist / "index.html"
        return FileResponse(page) if page.exists() else JSONResponse({"detail": "Frontend not built"}, status_code=503)

    return app


app = create_app()
