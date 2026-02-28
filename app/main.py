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


# ── Windows NTLM Middleware ───────────────────────────────────────────────────
# Only loaded when AUTH_MODE=windows — requires pywin32 on Windows

if config.AUTH_MODE == "windows":
    try:
        import sspi
        import win32security

        class NTLMMiddleware:
            """
            Simple SSPI/NTLM middleware for local Windows deployments.
            Performs the NTLM 3-way handshake and stores the resolved
            DOMAIN\\username in request.state.windows_user.
            """
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return

                from starlette.requests import Request as StarletteRequest
                from starlette.responses import Response as StarletteResponse
                import base64

                request = StarletteRequest(scope, receive)

                # Skip NTLM for static files and already-authed cookie requests
                path = scope.get("path", "")
                if path.startswith("/static") or request.cookies.get("plm_session"):
                    await self.app(scope, receive, send)
                    return

                # Only enforce NTLM on /auth/windows
                if path != "/auth/windows":
                    await self.app(scope, receive, send)
                    return

                auth_header = request.headers.get("Authorization", "")

                if not auth_header.startswith("NTLM ") and not auth_header.startswith("Negotiate "):
                    # Step 1: challenge browser
                    response = StarletteResponse(
                        status_code=401,
                        headers={"WWW-Authenticate": "NTLM"},
                    )
                    await response(scope, receive, send)
                    return

                try:
                    scheme, token_b64 = auth_header.split(" ", 1)
                    token_bytes = base64.b64decode(token_b64)

                    pkg = "NTLM"
                    sa = sspi.ServerAuth(pkg)
                    err, out_token = sa.authorize(token_bytes)

                    if err == 0:
                        # Authenticated
                        username = win32security.GetUserNameEx(win32security.NameSamCompatible)
                        scope.setdefault("state", {})["windows_user"] = username
                        # Attach to request.state via scope
                        if not hasattr(request, "state"):
                            from starlette.datastructures import State
                            request._state = State()
                        request.state.windows_user = username
                        await self.app(scope, receive, send)
                    else:
                        # Step 2: send server challenge
                        import base64
                        challenge_b64 = base64.b64encode(out_token).decode()
                        response = StarletteResponse(
                            status_code=401,
                            headers={"WWW-Authenticate": f"NTLM {challenge_b64}"},
                        )
                        await response(scope, receive, send)
                except Exception:
                    response = StarletteResponse(status_code=401,
                                                 headers={"WWW-Authenticate": "NTLM"})
                    await response(scope, receive, send)

    except ImportError:
        NTLMMiddleware = None  # type: ignore

app = FastAPI(title="PLM Lite", version="1.0.0", docs_url="/api/docs", redoc_url=None)

if config.AUTH_MODE == "windows" and NTLMMiddleware:
    app.add_middleware(NTLMMiddleware)

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
async def app_page():
    return FileResponse(str(_STATIC / "app.html"))


# ── Auth mode discovery (used by login page JS) ───────────────────────────────

@app.get("/api/auth-mode")
async def auth_mode():
    return {"mode": config.AUTH_MODE}


# ── Static files ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
