@echo off
set "DIR=%~dp0"
cd /d "%DIR%"
python -c "import sys; sys.path.insert(0, 'src'); from plmlite.gui import launch; launch()"
pause
