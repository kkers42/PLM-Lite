"""
PLM Lite V1.0 — FastAPI application entry point
"""
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import get_current_user, optional_user
from . import config
from .database import Database
from .routers import (
    admin_router,
    auth_router,
    documents_router,
    parts_router,
    relationships_router,
    users_router,
)

_STATIC = Path(__file__).parent.parent / "static"

app = FastAPI(title="PLM Lite", version="1.0.0", docs_url="/api/docs", redoc_url=None)

# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    db = Database()
    db.initialize()


# ── Include routers ──────────────────────────────────────────────────────────

app.include_router(auth_router.router)
app.include_router(parts_router.router)
app.include_router(relationships_router.router)
app.include_router(documents_router.router)
app.include_router(users_router.router)
app.include_router(admin_router.router)


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root(user: dict = Depends(optional_user)):
    if user:
        return RedirectResponse(url="/app")
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page():
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/app")
async def app_page(user: dict = Depends(get_current_user)):
    return FileResponse(str(_STATIC / "app.html"))


# ── Auth mode discovery (used by login page JS) ───────────────────────────────

@app.get("/api/auth-mode")
async def auth_mode():
    return {"mode": config.AUTH_MODE}


# ── Static files ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
