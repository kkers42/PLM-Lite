"""
PLM Lite V1.0 — Auth routes
Supports AUTH_MODE=google, local, and windows
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ..auth import (
    exchange_google_code,
    get_current_user,
    get_windows_username,
    google_auth_url,
    hash_password,
    make_cookie_kwargs,
    token_for_user,
    verify_local_credentials,
    windows_username_to_plm_user,
)
from .. import config
from ..database import Database
from ..models import LoginRequest, MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google")
async def google_login():
    if config.AUTH_MODE != "google":
        raise HTTPException(400, "Google OAuth not enabled")
    return RedirectResponse(url=google_auth_url())


@router.get("/google/callback")
async def google_callback(code: str, response: Response):
    if config.AUTH_MODE != "google":
        raise HTTPException(400, "Google OAuth not enabled")
    try:
        info = await exchange_google_code(code)
    except Exception:
        raise HTTPException(400, "Failed to authenticate with Google")

    email = info.get("email", "").lower()
    if not email:
        raise HTTPException(400, "No email returned from Google")

    if config.ALLOWED_EMAILS and email not in config.ALLOWED_EMAILS:
        raise HTTPException(403, "Your email is not authorized")

    name = info.get("name") or email.split("@")[0]
    db = Database()
    user = db.upsert_oauth_user(email=email, username=name)

    token = token_for_user(user)
    base = config.APP_BASE_URL.rstrip("/")
    redir = RedirectResponse(url=f"{base}/app", status_code=302)
    redir.set_cookie(value=token, **make_cookie_kwargs())
    return redir


# ── Windows identity login ────────────────────────────────────────────────────

@router.post("/windows")
async def windows_login(body: dict, response: Response):
    """
    Called by the login page when AUTH_MODE=windows.
    Client submits their Windows username (no password — trusted LAN).
    Server provisions/looks up the user and issues a JWT cookie.
    This correctly maps Suzie on Station B and Suzie on Station C to the same account.
    """
    if config.AUTH_MODE != "windows":
        raise HTTPException(400, "Windows auth not enabled")

    win_user = (body.get("username") or "").strip()
    if not win_user:
        raise HTTPException(400, "Username is required")

    user = windows_username_to_plm_user(win_user)
    if not user:
        raise HTTPException(403, "Your account has been disabled. Contact your administrator.")

    token = token_for_user(user)
    response.set_cookie(value=token, **make_cookie_kwargs())
    return {
        "message": "ok",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role_name": user.get("role_name"),
            "can_admin": bool(user.get("can_admin", 0)),
        },
    }


@router.post("/login")
async def local_login(body: LoginRequest, response: Response):
    if config.AUTH_MODE != "local":
        raise HTTPException(400, "Local login not enabled")
    user = verify_local_credentials(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = token_for_user(user)
    response.set_cookie(value=token, **make_cookie_kwargs())
    return {
        "message": "ok",
        "must_change_password": bool(user.get("must_change_password", 0)),
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role_name": user.get("role_name"),
            "can_admin": bool(user.get("can_admin", 0)),
        },
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("plm_session", path="/")
    return MessageResponse(message="Logged out")


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email"),
        "role_name": user.get("role_name"),
        "can_admin": bool(user.get("can_admin", 0)),
        "can_write": bool(user.get("can_write", 1)),
        "can_release": bool(user.get("can_release", 1)),
        "can_checkout": bool(user.get("can_checkout", 1)),
        "can_upload": bool(user.get("can_upload", 1)),
        "must_change_password": bool(user.get("must_change_password", 0)),
        "auth_mode": config.AUTH_MODE,
    }


@router.post("/change-password")
async def change_password(body: dict, user: dict = Depends(get_current_user)):
    new_pw = body.get("new_password", "")
    if len(new_pw) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    db = Database()
    db.update_user_password(user["id"], hash_password(new_pw), must_change=0)
    return MessageResponse(message="Password changed")
