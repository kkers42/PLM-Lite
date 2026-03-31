r"""PLM Lite v2.0 — Configuration.

Resolution order for each setting:
  1. Environment variable  (e.g. PLMLITE_WATCH_PATH)
  2. plmlite.ini config file (path from PLMLITE_CONFIG env var, or ./plmlite.ini)
  3. Hardcoded default

Multi-watch section format in plmlite.ini:
    [watch.nx]
    path = /data/NXFiles
    extensions = .prt,.asm

    [watch.step]
    path = /data/NXFiles
    extensions = .step,.stp,.jt

Backwards compatible: if no [watch.X] sections found, the old-style
watch_path / file_extensions keys are used as a single watch config.
"""

import configparser
import os
import sys
from pathlib import Path
from typing import Dict, List


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


_DEFAULT_WATCH_PATH      = r"\\server\share\datasets"
_DEFAULT_BACKUP_PATH     = r"\\server\share\datasets\backups"
_DEFAULT_DB_PATH         = str(_exe_dir() / "pdm.db")
_DEFAULT_MAX_VERSIONS    = 3
_DEFAULT_FILE_EXTENSIONS = [".prt", ".asm", ".drw"]


def _load_config_file() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    config_path = os.environ.get("PLMLITE_CONFIG", "plmlite.ini")
    cfg.read(config_path)
    return cfg


def _get(cfg: configparser.ConfigParser, key: str, env_var: str,
         default: str) -> str:
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
FILE_EXTENSIONS: List[str] = [e.strip() for e in _ext_raw.split(",") if e.strip()]


def get_watch_configs() -> List[Dict]:
    """Return list of {path, extensions} dicts.

    Reads all [watch.X] sections from plmlite.ini. Falls back to the
    legacy watch_path / file_extensions keys if no [watch.X] sections exist.
    """
    configs: List[Dict] = []
    for section in _cfg.sections():
        if section.lower().startswith("watch."):
            path = _cfg.get(section, "path", fallback="").strip()
            ext_raw = _cfg.get(section, "extensions",
                               fallback=",".join(_DEFAULT_FILE_EXTENSIONS))
            if path:
                exts = [e.strip() for e in ext_raw.split(",") if e.strip()]
                configs.append({"name": section, "path": path, "extensions": exts})

    if not configs:
        # Backwards compat: single watch path from old-style keys
        configs.append({
            "name": "watch.default",
            "path": str(WATCH_PATH),
            "extensions": FILE_EXTENSIONS,
        })
    return configs


def get_config() -> dict:
    """Return all resolved config values (for display/debugging)."""
    return {
        "WATCH_PATH":       str(WATCH_PATH),
        "BACKUP_PATH":      str(BACKUP_PATH),
        "DB_PATH":          str(DB_PATH),
        "MAX_VERSIONS":     MAX_VERSIONS,
        "FILE_EXTENSIONS":  FILE_EXTENSIONS,
        "WATCH_CONFIGS":    get_watch_configs(),
    }


def validate_paths() -> List[str]:
    """Return warning strings for paths that do not exist. Does not raise."""
    warnings = []
    for wc in get_watch_configs():
        p = Path(wc["path"])
        if not p.exists():
            warnings.append(f"Watch path does not exist: {p}")
    if not BACKUP_PATH.parent.exists():
        warnings.append(f"BACKUP_PATH parent does not exist: {BACKUP_PATH.parent}")
    if not DB_PATH.parent.exists():
        warnings.append(f"DB_PATH parent does not exist: {DB_PATH.parent}")
    return warnings
