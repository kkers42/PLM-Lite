r"""Configuration settings for PLMLITE.

Resolution order for each setting:
  1. Environment variable (e.g. PLMLITE_WATCH_PATH)
  2. plmlite.ini config file (path from PLMLITE_CONFIG env var, or ./plmlite.ini)
  3. Hardcoded default

Example plmlite.ini:
    [plmlite]
    watch_path = \\SERVER\Datasets
    backup_path = \\SERVER\Datasets\backups
    db_path = \\SERVER\Datasets\pdm.db
    max_versions = 3
    file_extensions = .prt,.asm,.drw
"""

import configparser
import os
import sys
from pathlib import Path


def _exe_dir() -> Path:
    """Return the directory containing the running exe (frozen) or cwd (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


_DEFAULT_WATCH_PATH = r"\\server\share\datasets"
_DEFAULT_BACKUP_PATH = r"\\server\share\datasets\backups"
_DEFAULT_DB_PATH = str(_exe_dir() / "pdm.db")
_DEFAULT_MAX_VERSIONS = 3
_DEFAULT_FILE_EXTENSIONS = [".prt", ".asm", ".drw"]


def _load_config_file() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    config_path = os.environ.get("PLMLITE_CONFIG", "plmlite.ini")
    cfg.read(config_path)
    return cfg


def _get(cfg: configparser.ConfigParser, key: str, env_var: str, default: str) -> str:
    if env_var in os.environ:
        return os.environ[env_var]
    if cfg.has_option("plmlite", key):
        return cfg.get("plmlite", key)
    return default


_cfg = _load_config_file()

WATCH_PATH: Path = Path(
    _get(_cfg, "watch_path", "PLMLITE_WATCH_PATH", _DEFAULT_WATCH_PATH)
)

BACKUP_PATH: Path = Path(
    _get(_cfg, "backup_path", "PLMLITE_BACKUP_PATH", _DEFAULT_BACKUP_PATH)
)

DB_PATH: Path = Path(
    _get(_cfg, "db_path", "PLMLITE_DB_PATH", _DEFAULT_DB_PATH)
)

MAX_VERSIONS: int = int(
    _get(_cfg, "max_versions", "PLMLITE_MAX_VERSIONS", str(_DEFAULT_MAX_VERSIONS))
)

_ext_raw = _get(
    _cfg, "file_extensions", "PLMLITE_FILE_EXTENSIONS",
    ",".join(_DEFAULT_FILE_EXTENSIONS),
)
FILE_EXTENSIONS: list[str] = [e.strip() for e in _ext_raw.split(",") if e.strip()]


def get_config() -> dict:
    """Return all resolved config values as a dict (for display/debugging)."""
    return {
        "WATCH_PATH": str(WATCH_PATH),
        "BACKUP_PATH": str(BACKUP_PATH),
        "DB_PATH": str(DB_PATH),
        "MAX_VERSIONS": MAX_VERSIONS,
        "FILE_EXTENSIONS": FILE_EXTENSIONS,
    }


def validate_paths() -> list[str]:
    """Return warning strings for paths that don't exist. Does not raise."""
    warnings = []
    if not WATCH_PATH.exists():
        warnings.append(f"WATCH_PATH does not exist: {WATCH_PATH}")
    if not BACKUP_PATH.parent.exists():
        warnings.append(f"BACKUP_PATH parent does not exist: {BACKUP_PATH.parent}")
    if not DB_PATH.parent.exists():
        warnings.append(f"DB_PATH parent does not exist: {DB_PATH.parent}")
    return warnings
