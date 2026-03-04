"""
PLM Lite V1.1.0 — FastAPI application entry point
"""
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import get_current_user, optional_user
from . import config
from .database import Database
from .routers import (
    admin_router,
    auth_router,
    cache_router,
    documents_router,
    parts_router,
    relationships_router,
    users_router,
)

_STATIC = Path(__file__).parent.parent / "static"


app = FastAPI(title="PLM Lite", version="1.1.0", docs_url="/api/docs", redoc_url=None)

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
app.include_router(cache_router.router)


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


# ── Feature flags (used by frontend) ─────────────────────────────────────────

@app.get("/api/features")
async def features():
    return {
        "open_inplace": bool(config.FILES_UNC_ROOT),
        "mapped_drive": config.FILES_MAPPED_DRIVE or None,
    }


# ── PLM Open protocol handler installer ──────────────────────────────────────

@app.get("/plmopen-handler.reg")
async def plmopen_reg():
    """
    Download once per workstation and double-click to install.
    Registers plmopen:// as a Windows URI scheme handler.
    Strips the plmopen:// prefix then passes the bare network path
    to 'start', which opens it in NX via the .prt file association.
    """
    reg_content = r"""Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\plmopen]
@="PLM Lite Open in CAD"
"URL Protocol"=""

[HKEY_CLASSES_ROOT\plmopen\DefaultIcon]
@="shell32.dll,3"

[HKEY_CLASSES_ROOT\plmopen\shell]

[HKEY_CLASSES_ROOT\plmopen\shell\open]

[HKEY_CLASSES_ROOT\plmopen\shell\open\command]
@="cmd.exe /v:on /c \"set P=%1& set P=!P:plmopen://=! & start \"\" \"!P!\""
"""
    return PlainTextResponse(
        content=reg_content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="plmopen-handler.reg"'},
    )


# ── Setup backdoor ───────────────────────────────────────────────────────────
# Emergency admin page — accessible at /setup?pw=<ADMIN_PASSWORD>
# Lets you view and change user roles without needing a working login.

from fastapi.responses import HTMLResponse

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(pw: str = ""):
    if pw != config.ADMIN_PASSWORD:
        return HTMLResponse("<h2>Access denied. Add ?pw=YOUR_ADMIN_PASSWORD to the URL.</h2>", status_code=403)
    db = Database()
    users = db.list_users()
    roles = db.list_roles()
    role_opts = "".join(f'<option value="{r["id"]}">{r["name"]}</option>' for r in roles)
    rows = ""
    for u in users:
        selected_opts = "".join(
            f'<option value="{r["id"]}"{"selected" if r["id"]==u.get("role_id") else ""}>{r["name"]}</option>'
            for r in roles
        )
        rows += f"""<tr>
            <td>{u["id"]}</td><td>{u["username"]}</td><td>{u.get("email") or ""}</td>
            <td><form method="post" action="/setup/set-role?pw={pw}" style="display:inline">
                <input type="hidden" name="user_id" value="{u["id"]}">
                <select name="role_id">{selected_opts}</select>
                <button type="submit">Save</button>
            </form></td>
            <td>{"Yes" if u.get("is_active") else "No"}</td>
        </tr>"""
    return HTMLResponse(f"""<!DOCTYPE html><html><head><title>PLM Setup</title>
    <style>body{{font-family:sans-serif;padding:2rem}}table{{border-collapse:collapse;width:100%}}
    th,td{{border:1px solid #ccc;padding:8px;text-align:left}}th{{background:#f0f0f0}}</style></head>
    <body><h1>PLM Lite — Setup / User Management</h1>
    <p style="color:#888">Bookmark this URL to return: <code>/setup?pw={pw}</code></p>
    <table><thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th>Active</th></tr></thead>
    <tbody>{rows}</tbody></table></body></html>""")


@app.post("/setup/set-role", response_class=HTMLResponse)
async def setup_set_role(request: Request, pw: str = ""):
    if pw != config.ADMIN_PASSWORD:
        return HTMLResponse("Access denied", status_code=403)
    form = await request.form()
    user_id = int(form.get("user_id", 0))
    role_id = int(form.get("role_id", 0))
    db = Database()
    db.update_user(user_id, {"role_id": role_id})
    from fastapi.responses import RedirectResponse as RR
    return RR(url=f"/setup?pw={pw}", status_code=303)


# ── Static files ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
