"""
PLM Lite — Windows executable entry point (PyInstaller)
"""
import sys
import os

if getattr(sys, 'frozen', False):
    # Add bundle root to sys.path so 'import app' resolves
    sys.path.insert(0, sys._MEIPASS)
    os.chdir(sys._MEIPASS)

exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

# Load .env from exe directory before importing the app
env_path = os.path.join(exe_dir, '.env')
if os.path.exists(env_path):
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)

# Default data paths relative to exe directory if not set
if not os.environ.get('FILES_ROOT'):
    os.environ['FILES_ROOT'] = os.path.join(exe_dir, 'data', 'files')
if not os.environ.get('DB_PATH'):
    os.environ['DB_PATH'] = os.path.join(exe_dir, 'data', 'plm.db')

import uvicorn
from app.main import app as plm_app  # must come after path/env setup

if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8080'))
    auth_mode = os.getenv('AUTH_MODE', 'windows')

    print(f"\n  PLM Lite is running at http://localhost:{port}")
    if auth_mode == 'windows':
        print(f"  Sign in with your Windows username — no password needed.")
        print(f"  First person to log in becomes Admin automatically.")
    else:
        print(f"  Log in as admin / admin123  (change the password!)")
    print(f"  Press Ctrl+C to stop.\n")

    uvicorn.run(plm_app, host=host, port=port, log_level='info')
