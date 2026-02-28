"""
PLM Lite — standalone entry point for PyInstaller exe.
Runs uvicorn on port 8080, opens browser, serves from bundled static/.
"""
import sys
import os
from pathlib import Path

# ── Resolve base path (works both frozen and dev) ────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

# Tell the app where static files and schema are
os.environ.setdefault("PLM_BASE_DIR", str(BASE_DIR))

# Default local config if no .env present
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("SECRET_KEY", "plm-local-dev-secret-change-me")
os.environ.setdefault("FILES_ROOT", str(Path.home() / "plm_files"))
os.environ.setdefault("DB_PATH",    str(Path.home() / "plm.db"))

import threading
import webbrowser
import time
import uvicorn

def open_browser():
    time.sleep(2)
    webbrowser.open("http://localhost:8080/login")

def main():
    print("=" * 50)
    print("  PLM Lite v1.0 — Local Server")
    print(f"  URL:  http://localhost:8080")
    print(f"  DB:   {os.environ['DB_PATH']}")
    print(f"  Files:{os.environ['FILES_ROOT']}")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )

if __name__ == "__main__":
    main()
