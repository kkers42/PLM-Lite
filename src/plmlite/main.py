"""Entry point for PLMLITE.

Allows running as:
    python src/plmlite/main.py
or as a PyInstaller .exe entry point.
"""

from .cli import main

if __name__ == "__main__":
    main()
