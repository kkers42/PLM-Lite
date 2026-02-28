"""
PLM Lite V1.0 — Configuration
All settings loaded from .env via python-dotenv.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Auth ─────────────────────────────────────────────────────────────────────
AUTH_MODE: str = os.getenv("AUTH_MODE", "local").lower()  # "google" | "local" | "windows"
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production-use-openssl-rand-hex-32")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

# Google OAuth (only needed when AUTH_MODE=google)
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8080")

# ── Storage ──────────────────────────────────────────────────────────────────
FILES_ROOT: Path = Path(os.getenv("FILES_ROOT", "/srv/plm/files"))
DB_PATH: Path = Path(os.getenv("DB_PATH", "/srv/plm/plm.db"))

# ── File versioning ──────────────────────────────────────────────────────────
MAX_FILE_VERSIONS: int = int(os.getenv("MAX_FILE_VERSIONS", "3"))

CAD_EXTENSIONS: set[str] = set(
    ext.strip().lower()
    for ext in os.getenv(
        "CAD_EXTENSIONS",
        ".prt,.asm,.drw,.stl,.3mf,.obj,.step,.stp,.sldprt,.sldasm,.ipt,.iam",
    ).split(",")
    if ext.strip()
)

# ── Network open-in-place ────────────────────────────────────────────────────
# UNC root that Windows clients use to open CAD files directly.
# E.g. \\192.168.1.37\plm-files  — must be a Windows share of the same
# directory that FILES_ROOT points to inside the container.
# Leave blank to disable the "Open" button.
FILES_UNC_ROOT: str = os.getenv("FILES_UNC_ROOT", "")

# ── Misc ─────────────────────────────────────────────────────────────────────
# Comma-separated email whitelist for Google OAuth mode. Empty = allow all.
ALLOWED_EMAILS: list[str] = [
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", "").split(",")
    if e.strip()
]


def is_cad_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in CAD_EXTENSIONS


def google_redirect_uri() -> str:
    base = APP_BASE_URL.rstrip("/")
    return f"{base}/auth/google/callback"
