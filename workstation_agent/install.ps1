# PLM Lite V1.1.0 — Workstation Agent Installer
# Run as the user (no admin required for HKCU registry)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 -PlmUrl http://192.168.1.37:8070

param(
    [string]$PlmUrl = "http://localhost:8070",
    [string]$InstallDir = "C:\PLMAgent"
)

$ErrorActionPreference = "Stop"

Write-Host "PLM Lite Workstation Agent Installer" -ForegroundColor Cyan
Write-Host "Install dir : $InstallDir"
Write-Host "PLM URL     : $PlmUrl"
Write-Host ""

# ── 1. Create install directory ───────────────────────────────────────────────
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
    Write-Host "Created $InstallDir" -ForegroundColor Green
}

# ── 2. Copy files ─────────────────────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$scriptDir\agent.py"          "$InstallDir\agent.py"          -Force
Copy-Item "$scriptDir\requirements.txt"  "$InstallDir\requirements.txt"  -Force
Write-Host "Copied agent files" -ForegroundColor Green

# ── 3. Write config file ──────────────────────────────────────────────────────
$envFile = "$InstallDir\plmagent.env"
@"
PLM_BASE_URL=$PlmUrl
PLM_JWT=
"@ | Set-Content $envFile
Write-Host "Created $envFile (set PLM_JWT after first login)" -ForegroundColor Yellow

# ── 4. Install Python dependencies ───────────────────────────────────────────
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
pip install -r "$InstallDir\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warning "pip install failed. Ensure Python 3.10+ is in PATH."
}

# ── 5. Create launcher batch file ────────────────────────────────────────────
$launcher = "$InstallDir\start-agent.bat"
@"
@echo off
cd /d "$InstallDir"
for /f "tokens=1,2 delims==" %%a in (plmagent.env) do set %%a=%%b
python agent.py
pause
"@ | Set-Content $launcher
Write-Host "Created launcher: $launcher" -ForegroundColor Green

# ── 6. Register plmopen:// URI scheme in HKCU ────────────────────────────────
$regBase = "HKCU:\SOFTWARE\Classes\plmopen"
New-Item -Path $regBase -Force | Out-Null
Set-ItemProperty -Path $regBase -Name "(Default)" -Value "PLM Lite Open in CAD"
Set-ItemProperty -Path $regBase -Name "URL Protocol" -Value ""

New-Item -Path "$regBase\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$regBase\DefaultIcon" -Name "(Default)" -Value "shell32.dll,3"

New-Item -Path "$regBase\shell\open\command" -Force | Out-Null
$cmd = "cmd.exe /v:on /c `"set P=%1& set P=!P:plmopen://=! & start `"`" `"!P!`"`""
Set-ItemProperty -Path "$regBase\shell\open\command" -Name "(Default)" -Value $cmd

Write-Host "Registered plmopen:// URI scheme in HKCU" -ForegroundColor Green

# ── 7. Create Start Menu shortcut ────────────────────────────────────────────
$startMenu = [Environment]::GetFolderPath("StartMenu") + "\Programs"
$shortcutPath = "$startMenu\PLM Agent.lnk"
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath  = $launcher
$shortcut.WorkingDirectory = $InstallDir
$shortcut.Description = "PLM Lite Workstation Agent"
$shortcut.Save()
Write-Host "Created Start Menu shortcut: PLM Agent" -ForegroundColor Green

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Edit $envFile and set PLM_JWT to your login token"
Write-Host "  2. Launch 'PLM Agent' from Start Menu (or run start-agent.bat)"
Write-Host "  3. Copy nx_hook\plm_hook.py to your NX startup journals folder"
