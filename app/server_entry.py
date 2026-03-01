"""
PLM Lite — Windows executable entry point (PyInstaller)

When frozen by PyInstaller, sys._MEIPASS contains the temp directory where
bundled files are extracted. We patch the working directory so that
schema.sql, static/, etc. are found correctly.
"""
import sys
import os

# When running as a PyInstaller bundle, set the working directory to
# the extracted bundle root so relative paths resolve correctly.
if getattr(sys, 'frozen', False):
    os.chdir(sys._MEIPASS)

import uvicorn

if __name__ == '__main__':
    # Load .env from the directory the exe lives in (not _MEIPASS)
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
    env_path = os.path.join(exe_dir, '.env')
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)

    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8080'))

    print(f"\n  PLM Lite is running at http://localhost:{port}")
    print(f"  Log in as admin / admin123  (change the password!)")
    print(f"  Press Ctrl+C to stop.\n")

    uvicorn.run('app.main:app', host=host, port=port, log_level='info')
