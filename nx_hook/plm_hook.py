"""
PLM Lite V1.1.0 — NX Open Hook
Place this file in your NX 12 startup journals folder:
  C:\\Users\\{user}\\AppData\\Local\\Siemens\\NX 12.0\\startup\\

NX will execute it automatically on startup.
The hook silently does nothing if the PLM agent is not running.
"""
import urllib.request
import urllib.error
import json
import os
import socket

_AGENT_URL = "http://127.0.0.1:27370"
_STATION   = socket.gethostname()


def _post(path, body):
    """POST JSON to the local workstation agent. Silently ignores errors."""
    try:
        data = json.dumps(body).encode("utf-8")
        req  = urllib.request.Request(
            _AGENT_URL + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        # Agent not running or unreachable — fail silently
        return None


def _get_user_id():
    """Try to read PLM_USER_ID from environment (set by plmopen:// handler or login)."""
    try:
        return int(os.environ.get("PLM_USER_ID", "0")) or None
    except Exception:
        return None


def _get_nx_version():
    """Return NX version string if available."""
    try:
        import NXOpen
        session = NXOpen.Session.GetSession()
        return str(session.GetEnvironmentVariableValue("UGII_VERSION"))
    except Exception:
        return "NX12"


# ── Callbacks ─────────────────────────────────────────────────────────────────

def on_startup():
    """Called once when NX starts. Registers this session with PLM."""
    _post("/ping", {
        "nx_version":   _get_nx_version(),
        "station_name": _STATION,
        "user_id":      _get_user_id(),
    })


def on_file_open(file_path):
    """Called when a part file is opened. Sends a ping to keep session alive."""
    _post("/ping", {
        "nx_version":   _get_nx_version(),
        "station_name": _STATION,
        "user_id":      _get_user_id(),
    })


def on_file_save(file_path):
    """
    Called when a part file is saved.
    If the part is checked out by the current user, offers checkin.
    """
    if not file_path:
        return

    part_name = os.path.splitext(os.path.basename(file_path))[0]

    # Post checkin — the agent will look up the part and checkin if checked out
    # by this user. It does nothing if the part is not checked out by this user.
    _post("/checkin", {
        "part_number": part_name,
        "user_id":     _get_user_id(),
    })


# ── NX Open registration ──────────────────────────────────────────────────────

def register_hooks():
    """Register NX Open event callbacks."""
    try:
        import NXOpen
        import NXOpen.UI

        session = NXOpen.Session.GetSession()

        # Register file open callback
        session.Parts.PartOpened += lambda sender, args: on_file_open(
            args.Part.FullPath if args.Part else ""
        )

        # Register file save callback
        session.Parts.PartSaved += lambda sender, args: on_file_save(
            args.Part.FullPath if args.Part else ""
        )

        # Ping on startup
        on_startup()

    except ImportError:
        # NXOpen not available (e.g. running outside NX) — skip silently
        pass
    except Exception:
        # Any NX error — fail silently, never block NX startup
        pass


# NX executes this file on startup — run registration immediately
register_hooks()
