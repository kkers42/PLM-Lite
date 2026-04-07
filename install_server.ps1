#Requires -Version 5.1
<#
.SYNOPSIS
    PLM Lite — Server Installer
    Run this ONCE on the machine that will host the vault and database.
    (Can be Atlas, a NAS, or any Windows machine with a shared drive.)

.DESCRIPTION
    1. Verifies Python 3.10+ is installed
    2. Clones or updates the PLM Lite repository
    3. Installs Python dependencies (pip install -e .)
    4. Prompts for vault path, DB path, and first admin credentials
    5. Creates the vault directory structure
    6. Initializes the SQLite database (schema + seed data)
    7. Creates the first admin user
    8. Writes plmlite.ini

.NOTES
    Run from PowerShell as a normal user (no admin rights required unless
    the vault path is on a restricted drive).

    Re-running this script is safe — it will not overwrite an existing DB
    or existing plmlite.ini unless you confirm.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL = "https://github.com/kkers42/PLM-Lite.git"
$BANNER   = @"

  ╔══════════════════════════════════════════╗
  ║        PLM Lite — Server Installer       ║
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

function Prompt-Password([string]$msg) {
    $ss = Read-Host $msg -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ss))
    return $plain
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

function Init-Database([string]$installDir, [string]$dbPath,
                        [string]$adminUser, [string]$adminPass) {
    Write-Host "Initializing database at $dbPath ..." -ForegroundColor Yellow
    $script = @"
import sys, os
sys.path.insert(0, os.path.join(r'$installDir', 'src'))
from plmlite.database import Database
db = Database(r'$dbPath')
db.initialize()
existing = db.get_user(r'$adminUser')
if existing:
    print('  Admin user already exists — skipping user creation.')
else:
    db.create_user(r'$adminUser', r'$adminPass', 'admin')
    print('  Admin user created.')
print('  Database ready.')
"@
    & python -c $script
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Database initialization failed." -ForegroundColor Red
        exit 1
    }
}

function Write-Config([string]$installDir, [string]$vaultPath,
                       [string]$dbPath, [string]$revRule) {
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
Write-Host "── Vault & Database Paths ────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  The vault stores all NX/CAD files. Put this on a shared drive" -ForegroundColor DarkGray
Write-Host "  that all engineer PCs can access (mapped drive or UNC path)." -ForegroundColor DarkGray
Write-Host ""

$vaultPath = Prompt-Default "Vault path (shared drive)" "K:\NXFiles"
$dbPath    = Prompt-Default "Database path" ($vaultPath.TrimEnd('\') + "\..\plmlite.db" | Resolve-Path -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path -ErrorAction SilentlyContinue)
if ([string]::IsNullOrWhiteSpace($dbPath)) {
    # Resolve-Path failed (path doesn't exist yet) — build it manually
    $dbPath = (Split-Path $vaultPath -Parent) + "\plmlite.db"
}
$revRule = Prompt-Default "Assembly rev rule (latest_working / latest_released / latest_created)" "latest_working"

Write-Host ""
Write-Host "── First Admin User ──────────────────────────────────────────" -ForegroundColor Cyan
$adminUser = Prompt-Default "Admin username" "admin"
$adminPass = Prompt-Password "Admin password"
$adminPass2 = Prompt-Password "Confirm password"
if ($adminPass -ne $adminPass2) {
    Write-Host "ERROR: Passwords do not match." -ForegroundColor Red
    exit 1
}

# Create vault directory
if (-not (Test-Path $vaultPath)) {
    Write-Host "Creating vault directory: $vaultPath" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $vaultPath -Force | Out-Null
    Write-Host "  OK" -ForegroundColor Green
} else {
    Write-Host "Vault directory already exists: $vaultPath" -ForegroundColor Green
}

# Create DB parent directory if needed
$dbParent = Split-Path $dbPath -Parent
if (-not (Test-Path $dbParent)) {
    New-Item -ItemType Directory -Path $dbParent -Force | Out-Null
}

Write-Config $installDir $vaultPath $dbPath $revRule
Init-Database $installDir $dbPath $adminUser $adminPass

Write-Host ""
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Server install complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Vault:    $vaultPath" -ForegroundColor White
Write-Host "  Database: $dbPath" -ForegroundColor White
Write-Host "  Admin:    $adminUser" -ForegroundColor White
Write-Host ""
Write-Host "  Next: run install_client.ps1 on each engineer's PC." -ForegroundColor Cyan
Write-Host "  Give them these paths:" -ForegroundColor Cyan
Write-Host "    Vault path: $vaultPath" -ForegroundColor White
Write-Host "    DB path:    $dbPath" -ForegroundColor White
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Green
