"""
PLM Lite Local Agent — runs on each workstation, localhost only.

Receives open/checkout-copy requests from the browser and executes
them in the local Windows session (os.startfile, shutil.copy, etc.)

Start:  python -m plmlite.agent
Port:   127.0.0.1:9090  (localhost only — never exposed to network)
"""

import os
import shutil
import sys
from pathlib import Path

# When run directly as a script (python agent.py), ensure src/ is on path
_src = Path(__file__).parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

AGENT_PORT = 9090

app = FastAPI(title="PLM Lite Local Agent", docs_url=None, redoc_url=None)

# Allow requests from any PLM server origin (Atlas, localhost, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


TEMP_DIR = Path(os.environ.get("USERPROFILE", Path.home())) / "PLMTemp"


class OpenRequest(BaseModel):
    path: str


class CheckoutOpenRequest(BaseModel):
    vault_path: str   # Windows path e.g. K:\NXFiles\A\TST0001.prt
    filename: str


@app.get("/ping")
def ping():
    """Health check — browser uses this to detect whether agent is running."""
    return {"status": "ok", "user": os.environ.get("USERNAME", "unknown")}


@app.post("/open")
def open_file(req: OpenRequest):
    """Open a file in its registered Windows application (local session)."""
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(404, f"File not found: {p}")
    try:
        os.startfile(str(p))
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"message": f"Opening {p.name}"}


@app.post("/checkout-open")
def checkout_open(req: CheckoutOpenRequest):
    """Copy vault file to local temp (writable) and open it."""
    import stat as _stat
    vault = Path(req.vault_path)
    if not vault.exists():
        raise HTTPException(404, f"Vault file not found: {vault}")

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp = TEMP_DIR / req.filename

    # Strip read-only if temp already exists
    if temp.exists():
        temp.chmod(temp.stat().st_mode | _stat.S_IWRITE)

    shutil.copy2(str(vault), str(temp))

    # Make temp writable
    temp.chmod(temp.stat().st_mode | _stat.S_IWRITE)

    try:
        os.startfile(str(temp))
    except Exception as exc:
        raise HTTPException(500, str(exc))

    return {"message": f"Opening {temp.name}", "temp_path": str(temp)}


@app.post("/checkin-copy")
def checkin_copy(req: CheckoutOpenRequest):
    """Copy local temp file back to vault path for checkin."""
    import stat as _stat
    temp = TEMP_DIR / req.filename
    if not temp.exists():
        raise HTTPException(404, f"Temp file not found: {temp}")

    vault = Path(req.vault_path)
    vault.parent.mkdir(parents=True, exist_ok=True)

    # Strip read-only on vault
    if vault.exists():
        vault.chmod(vault.stat().st_mode | _stat.S_IWRITE)

    shutil.copy2(str(temp), str(vault))

    # Restore vault read-only
    vault.chmod(vault.stat().st_mode & ~_stat.S_IWRITE)

    # Delete temp
    try:
        temp.unlink()
    except OSError:
        pass

    return {"message": f"Checked in {req.filename}"}


def run():
    """Entry point for plmlite-agent script and PyInstaller exe."""
    # Only bind to localhost — never expose to network
    uvicorn.run(app, host="127.0.0.1", port=AGENT_PORT, log_level="info")


if __name__ == "__main__":
    run()
