"""
PLM Lite V1.0 — Tri-mode auth
AUTH_MODE=google:   Google OAuth 2.0 + JWT cookie
AUTH_MODE=local:    bcrypt username/password + JWT cookie
AUTH_MODE=windows:  Windows NTLM/Negotiate — no login page, auto-maps DOMAIN\\user
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
import bcrypt as _bcrypt_lib

from . import config


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _create_token(user: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "email": user.get("email", ""),
        "role_id": user.get("role_id"),
        "can_admin": bool(user.get("can_admin", 0)),
        "exp": expire,
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    return jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])


def make_cookie_kwargs() -> dict:
    return dict(
        key="plm_session",
        path="/",
        httponly=True,
        samesite="lax",
        secure=config.APP_BASE_URL.startswith("https"),
        max_age=config.JWT_EXPIRE_HOURS * 3600,
    )


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    """FastAPI dependency — raises 401 if not authenticated."""
    token = request.cookies.get("plm_session")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = _decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    # Refresh full user record from DB for up-to-date role/abilities
    from .database import Database
    db = Database()
    user = db.get_user(int(payload["sub"]))
    if not user or not user.get("is_active", 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    db.touch_user(user["id"])
    return user


def optional_user(request: Request) -> Optional[dict]:
    try:
        return get_current_user(request)
    except HTTPException:
        return None


# ── Local auth ─────────────────────────────────────────────────────────────────

def verify_local_credentials(username: str, password: str) -> Optional[dict]:
    from .database import Database
    db = Database()
    user = db.get_user_by_username(username)
    if not user:
        return None
    if not user.get("password_hash"):
        return None
    if not _bcrypt_lib.checkpw(password.encode(), user["password_hash"].encode()):
        return None
    if not user.get("is_active", 0):
        return None
    return user


def hash_password(password: str) -> str:
    return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()


# ── Google OAuth ──────────────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_auth_url() -> str:
    import urllib.parse
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_google_code(code: str) -> dict:
    """Exchange authorization code for userinfo dict."""
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": config.google_redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
        info_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        info_resp.raise_for_status()
        return info_resp.json()


def token_for_user(user: dict) -> str:
    return _create_token(user)


# ── Windows NTLM / Negotiate auth ────────────────────────────────────────────

def get_windows_username(request: Request) -> Optional[str]:
    """
    Extract the authenticated Windows username from the NTLM/Negotiate
    Authorization header that IIS / the SSPI middleware has already validated.

    When running behind the built-in SSPI middleware (sspilib / pywin32),
    the validated identity is stored in request.state.windows_user as
    'DOMAIN\\username'.  Falls back to parsing a Basic header so the same
    code works in dev without full NTLM negotiation.
    """
    # Set by the NTLMMiddleware in main.py after successful handshake
    win_user: Optional[str] = getattr(request.state, "windows_user", None)
    if win_user:
        return win_user
    return None


def windows_username_to_plm_user(windows_user: str) -> Optional[dict]:
    """
    Given 'DOMAIN\\Suzie' (or just 'Suzie'), upsert a PLM user and return it.
    The PLM username is the bare username (lowercase), email is left blank.
    """
    from .database import Database
    # Strip domain prefix
    bare = windows_user.split("\\")[-1].split("/")[-1].lower()
    db = Database()
    user = db.get_user_by_username(bare)
    if not user:
        # Auto-provision — gets Engineer role (all abilities) per spec default
        user = db.upsert_windows_user(username=bare, windows_identity=windows_user)
    if not user or not user.get("is_active", 0):
        return None
    db.touch_user(user["id"])
    return user
