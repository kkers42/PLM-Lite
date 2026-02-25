"""PyInstaller entry point for plmlite-gui.exe — uses absolute imports."""
import sys
import os

# Ensure the bundled package is on the path when running as a frozen exe
if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)

from plmlite.gui import launch

if __name__ == "__main__":
    launch()
