r"""PLM Lite v2.2 — Configuration.

Resolution order for each setting:
  1. Environment variable  (e.g. PLMLITE_VAULT_PATH)
  2. plmlite.ini config file (path from PLMLITE_CONFIG env var, or ./plmlite.ini)
  3. Hardcoded default
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


_DEFAULT_VAULT_PATH   = r"K:\NXFiles"
_DEFAULT_DB_PATH      = str(_exe_dir() / "pdm.db")


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

VAULT_PATH: Path = Path(
    _get(_cfg, "vault_path", "PLMLITE_VAULT_PATH", _DEFAULT_VAULT_PATH)
)
DB_PATH: Path = Path(
    _get(_cfg, "db_path", "PLMLITE_DB_PATH", _DEFAULT_DB_PATH)
)

# Windows-side path for the vault — used by the local agent to open files.
# When the server runs on Linux but clients are Windows, set this to the
# Windows UNC or mapped-drive path that points to the same vault.
# e.g.  vault_windows_path = K:\NXFiles
VAULT_WINDOWS_PATH: str = _get(_cfg, "vault_windows_path", "PLMLITE_VAULT_WINDOWS_PATH", "")

# Per-user temp directory base: C:\Users\{username}\PLMTemp\
# Each OS user on any machine gets their own temp space.
TEMP_BASE_PATH: Path = Path(
    os.environ.get("USERPROFILE", os.path.expanduser("~"))
) / "PLMTemp"

# Assembly revision rule — which revision of child components to load into temp
# Options: "latest_created" | "latest_working" | "latest_released"
ASSEMBLY_REV_RULE: str = _get(_cfg, "assembly_rev_rule", "PLMLITE_ASSEMBLY_REV_RULE", "latest_working")

# Legacy — kept for backwards compat with any remaining references
WATCH_PATH: Path  = VAULT_PATH
BACKUP_PATH: Path = VAULT_PATH / "_backups"
MAX_VERSIONS: int = 10
FILE_EXTENSIONS: List[str] = [".prt", ".asm", ".drw", ".sldprt", ".sldasm"]


def get_watch_configs() -> List[Dict]:
    """Legacy stub — returns empty list (watcher no longer auto-creates items)."""
    return []


def get_config() -> dict:
    """Return all resolved config values (for display/debugging)."""
    return {
        "VAULT_PATH":      str(VAULT_PATH),
        "DB_PATH":         str(DB_PATH),
        "TEMP_BASE_PATH":  str(TEMP_BASE_PATH),
    }


def validate_paths() -> List[str]:
    warnings = []
    if not VAULT_PATH.exists():
        warnings.append(f"VAULT_PATH does not exist: {VAULT_PATH}")
    if not DB_PATH.parent.exists():
        warnings.append(f"DB_PATH parent does not exist: {DB_PATH.parent}")
    return warnings
