#Requires -Version 5.1
<#
.SYNOPSIS
    PLM Lite — Client Installer
    Run this on each engineer's Windows PC.

.DESCRIPTION
    1. Verifies Python 3.10+ is installed
    2. Clones or updates the PLM Lite repository
    3. Installs Python dependencies (pip install -e .)
    4. Prompts for vault path and DB path (from IT / server install summary)
    5. Prompts for local temp directory (default C:\Users\{you}\PLMTemp)
    6. Writes plmlite.ini
    7. Creates a desktop shortcut that launches the GUI

.NOTES
    Run from PowerShell as a normal user.
    Re-running is safe — existing plmlite.ini is only overwritten if confirmed.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL = "https://github.com/kkers42/PLM-Lite.git"
$BANNER   = @"

  ╔══════════════════════════════════════════╗
  ║        PLM Lite — Client Installer       ║
  ╚══════════════════════════════════════════╝

"@

Write-Host $BANNER -ForegroundColor Cyan

# ── Helpers ───────────────────────────────────────────────────────────────────

function Prompt-Default([string]$msg, [string]$default) {
    $display = if ($default) { "$msg [$default]" } else { $msg }
    $val = Read-Host $display
    if ([string]::IsNullOrWhiteSpace($val)) { return $default }
    return $val.Trim()
}

function Check-Python {
    Write-Host "Checking Python..." -ForegroundColor Yellow
    try {
        $ver = & python --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
                Write-Host "ERROR: Python 3.10+ required. Found: $ver" -ForegroundColor Red
                exit 1
            }
            Write-Host "  OK — $ver" -ForegroundColor Green
        } else {
            Write-Host "ERROR: Could not determine Python version." -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "ERROR: Python not found. Install from https://python.org" -ForegroundColor Red
        exit 1
    }
}

function Get-Or-Clone-Repo([string]$installDir) {
    if (Test-Path (Join-Path $installDir ".git")) {
        Write-Host "Repository found at $installDir — pulling latest..." -ForegroundColor Yellow
        Push-Location $installDir
        & git pull
        Pop-Location
    } else {
        Write-Host "Cloning PLM Lite from GitHub..." -ForegroundColor Yellow
        & git clone $REPO_URL $installDir
    }
}

function Install-Dependencies([string]$installDir) {
    Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
    Push-Location $installDir
    & python -m pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: pip install failed." -ForegroundColor Red
        Pop-Location; exit 1
    }
    Pop-Location
    Write-Host "  OK" -ForegroundColor Green
}

function Write-Config([string]$installDir, [string]$vaultPath,
                       [string]$dbPath, [string]$tempPath, [string]$revRule) {
    $iniPath = Join-Path $installDir "plmlite.ini"
    if (Test-Path $iniPath) {
        $overwrite = Prompt-Default "plmlite.ini already exists. Overwrite? (y/n)" "n"
        if ($overwrite -ne "y") {
            Write-Host "  Keeping existing plmlite.ini" -ForegroundColor Yellow
            return
        }
    }
    $content = @"
[plmlite]
vault_path        = $vaultPath
db_path           = $dbPath
assembly_rev_rule = $revRule
"@
    Set-Content -Path $iniPath -Value $content -Encoding UTF8
    Write-Host "  Written: $iniPath" -ForegroundColor Green

    # Also write TEMP_BASE_PATH as env var hint in a small .env-style comment
    # The actual override is via environment variable PLMLITE_TEMP_BASE_PATH
    if ($tempPath -ne "$env:USERPROFILE\PLMTemp") {
        [System.Environment]::SetEnvironmentVariable(
            "PLMLITE_TEMP_BASE_PATH", $tempPath, "User")
        Write-Host "  Temp path set in user environment: PLMLITE_TEMP_BASE_PATH=$tempPath" -ForegroundColor Green
    }
}

function Create-Shortcut([string]$installDir) {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "PLM Lite.lnk"

    $batPath = Join-Path $installDir "start_gui.bat"

    # Write the bat file (idempotent)
    $batContent = @"
@echo off
set "DIR=%~dp0"
cd /d "%DIR%"
python -c "import sys; sys.path.insert(0, 'src'); from plmlite.gui import launch; launch()"
"@
    Set-Content -Path $batPath -Value $batContent -Encoding ASCII

    # Create the .lnk shortcut
    $wsh = New-Object -ComObject WScript.Shell
    $sc  = $wsh.CreateShortcut($shortcutPath)
    $sc.TargetPath       = $batPath
    $sc.WorkingDirectory = $installDir
    $sc.Description      = "PLM Lite — CAD Data Management"

    # Use icon from repo if it exists, otherwise fall back to a system icon
    $iconPath = Join-Path $installDir "src\plmlite\icon.ico"
    if (Test-Path $iconPath) {
        $sc.IconLocation = $iconPath
    } else {
        $sc.IconLocation = "C:\Windows\System32\shell32.dll,13"
    }

    $sc.Save()
    Write-Host "  Desktop shortcut created: $shortcutPath" -ForegroundColor Green
}

# ── Main ──────────────────────────────────────────────────────────────────────

Check-Python

Write-Host "── Install Location ──────────────────────────────────────────" -ForegroundColor Cyan
$defaultInstall = "C:\PLMLite"
$installDir = Prompt-Default "Where should PLM Lite be installed?" $defaultInstall
$installDir = $installDir.TrimEnd('\')

Get-Or-Clone-Repo $installDir
Install-Dependencies $installDir

Write-Host ""
Write-Host "── Server Paths ──────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Enter the paths IT gave you from the server install." -ForegroundColor DarkGray
Write-Host "  These must point to the shared drive everyone uses." -ForegroundColor DarkGray
Write-Host ""

$vaultPath = Prompt-Default "Vault path (from IT)"  "K:\NXFiles"
$dbPath    = Prompt-Default "Database path (from IT)" "K:\plmlite.db"

Write-Host ""
Write-Host "── Local Temp Directory ──────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Where NX files are copied when you check them out." -ForegroundColor DarkGray
Write-Host "  This is LOCAL to this machine — keep it on a fast local drive." -ForegroundColor DarkGray
Write-Host ""

$defaultTemp = "$env:USERPROFILE\PLMTemp"
$tempPath = Prompt-Default "Local temp directory" $defaultTemp

$revRule = Prompt-Default "Assembly rev rule (latest_working / latest_released / latest_created)" "latest_working"

# Create temp directory
if (-not (Test-Path $tempPath)) {
    New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
    Write-Host "Created temp directory: $tempPath" -ForegroundColor Green
}

Write-Config $installDir $vaultPath $dbPath $tempPath $revRule
Create-Shortcut $installDir

Write-Host ""
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Client install complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Vault:    $vaultPath" -ForegroundColor White
Write-Host "  Database: $dbPath" -ForegroundColor White
Write-Host "  Temp:     $tempPath" -ForegroundColor White
Write-Host ""
Write-Host "  A 'PLM Lite' shortcut has been added to your desktop." -ForegroundColor Cyan
Write-Host "  Double-click it to launch the GUI." -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Green
