"""Launcher script — run directly so PYTHONPATH space issue is bypassed."""
import sys
import os
from pathlib import Path

# Ensure src is on path regardless of how this script is invoked
src = Path(__file__).parent / "src"
sys.path.insert(0, str(src))

import uvicorn
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
uvicorn.run("plmlite.server:app", host="0.0.0.0", port=port)
