# PLM Lite

> Lightweight, open-source Product Lifecycle Management for **Siemens NX CAD datasets** on a Windows network share.

Designed for small engineering teams (1–10 people) who need version control, check-in/check-out, BOM management, and lifecycle tracking — without the cost or complexity of Teamcenter or a full PDM server.

**v3.0.0** introduces a fully rewritten desktop GUI, multi-machine support, automatic BOM sync from NX part files, a local temp-dir checkout workflow, and a background watcher that auto-pushes saves back to the vault.

---

## Contents

- [Features](#features)
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Using the GUI](#using-the-gui)
  - [Parts](#parts-screen)
  - [My Files](#my-files-screen)
  - [BOM Tree](#bom-tree-screen)
  - [Settings](#settings-screen)
- [Multi-Machine Setup](#multi-machine-setup)
- [Building the .exe](#building-the-exe)
- [Limitations](#limitations)
- [License](#license)

---

## Features

- **Check-out / Check-in** — advisory soft locks with username tracking
- **Vault storage** — files stored in `{vault}/{revision}/{filename}`, immutable once released
- **Temp-dir workflow** — checked-out files are copied to `C:\Users\{user}\PLMTemp\` for editing; NX opens the local copy
- **Auto-push on save** — background TempWatcher detects NX saves and pushes changed files back to the vault automatically
- **BOM / Assembly relationships** — automatically synced from NX part file binary data on attach, check-in, and save
- **BOM Tree screen** — search by part name or number, browse full assembly tree with where-used
- **Revision management** — free-text revision labels (A, B, C, 01, REV1…), lifecycle states (in_work / released / obsolete)
- **Assembly Rev Rule** — configurable rule for which child revision to load into temp (latest working / latest released / latest created)
- **Role-based access** — admin / user / readonly roles with permission enforcement
- **Admin unlock** — admins can unlock a released revision to push corrections
- **Multi-user / multi-machine** — each user runs the GUI on their own machine; all users share one vault on a network drive
- **SQLite database** — single file on the network share, no server required
- **Dark desktop GUI** — CustomTkinter, Ubuntu/GNOME-style dark theme

---

## How It Works

```
Network Share (K:\NXFiles\)          Local Machine
──────────────────────────           ─────────────────────────────
K:\NXFiles\                          C:\Users\josh\PLMTemp\
  A\                                   TST0001.prt   ← writable (checked out by me)
    TST0001.prt  (vault, read-only)     TST0002.prt   ← read-only (checked out by other)
    TST0002.prt                         TST0003.prt   ← read-only (not checked out)
  B\
    TST0001.prt
K:\plmlite.db    ← shared SQLite DB
```

1. User opens an assembly in the GUI → PLM Lite copies it and all children to `PLMTemp\`
2. NX opens the local copy — always fast, always writable for the checked-out file
3. User saves in NX → TempWatcher detects the timestamp change → auto-copies back to vault
4. BOM relationships are parsed from the NX binary and written to the database automatically

---

## Requirements

- **Windows 10/11** (each engineer's machine)
- **Python 3.10+** (or use the pre-built `.exe`)
- **Network share** with a mapped drive letter (e.g. `K:\`) — Samba, Windows share, or NAS
- **Siemens NX** (any version that produces `.prt` / `.asm` files)

---

## Quick Start

### From source

```bash
git clone https://github.com/kkers42/PLM-Lite.git
cd PLM-Lite
pip install -e .
```

Create `plmlite.ini` next to the project (or in `r:\PLMLITE DEV\`):

```ini
[plmlite]
vault_path = K:\NXFiles
db_path    = K:\plmlite.db
```

Launch the GUI:

```bash
# Windows — double-click or run:
start_gui.bat
```

Or from Python directly:

```bash
python -c "import sys; sys.path.insert(0, 'src'); from plmlite.gui import launch; launch()"
```

### Pre-built .exe

Download `plmlite-gui.exe` from the [Releases](https://github.com/kkers42/PLM-Lite/releases) page or from the latest [Actions](https://github.com/kkers42/PLM-Lite/actions) artifact. Place `plmlite-gui.exe` and `plmlite.ini` in the same folder on each machine, then double-click to launch.

---

## Installation (IT Setup)

### Server — run once on the vault host

The server installer sets up the shared vault directory, initializes the database, and creates the first admin user.

**Windows (PowerShell):**
```powershell
git clone https://github.com/kkers42/PLM-Lite.git
cd PLM-Lite
.\install_server.ps1
```

**Linux / macOS:**
```bash
git clone https://github.com/kkers42/PLM-Lite.git
cd PLM-Lite
chmod +x install_server.sh
./install_server.sh
```

The script prompts for:
- Install location
- Vault path — the shared drive all PCs will access (e.g. `K:\NXFiles`)
- Database path (e.g. `K:\plmlite.db`)
- Admin username + password

At the end it prints the two paths IT needs to hand out to engineers.

---

### Client — run on each engineer's Windows PC

```powershell
git clone https://github.com/kkers42/PLM-Lite.git
cd PLM-Lite
.\install_client.ps1
```

The script prompts for:
- Install location (default `C:\PLMLite`)
- Vault path *(from IT)*
- Database path *(from IT)*
- Local temp directory (default `C:\Users\{you}\PLMTemp`)

It writes `plmlite.ini` and creates a **PLM Lite** shortcut on the desktop. Double-click it to launch.

**What IT tells engineers:**
> "Run `install_client.ps1`. When asked for the vault path enter `K:\NXFiles`, for the database path enter `K:\plmlite.db`. Leave everything else as the default."

---

### Build from Source

If you prefer not to use the installer scripts you can set up manually — it is the same steps the scripts automate:

**Requirements:** Python 3.10+, git

```bash
# 1. Clone
git clone https://github.com/kkers42/PLM-Lite.git
cd PLM-Lite

# 2. Install dependencies
pip install -e .

# 3. Create plmlite.ini
```

```ini
[plmlite]
vault_path        = K:\NXFiles
db_path           = K:\plmlite.db
assembly_rev_rule = latest_working
```

```bash
# 4. Launch
start_gui.bat                          # Windows — double-click or run from terminal
python -c "import sys; sys.path.insert(0, 'src'); from plmlite.gui import launch; launch()"
```

To initialize the database and create the first admin user (server only, run once):

```python
python -c "
import sys; sys.path.insert(0, 'src')
from plmlite.database import Database
db = Database('K:/plmlite.db')
db.initialize()
db.create_user('admin', 'yourpassword', 'admin')
print('Done')
"
```

---

## Configuration

Settings resolve in this order: **environment variable → plmlite.ini → built-in default**

### plmlite.ini

```ini
[plmlite]
vault_path         = K:\NXFiles
db_path            = K:\plmlite.db

; Optional — Windows path for the vault when running the server on Linux
vault_windows_path = K:\NXFiles

; Which child revision to load when opening an assembly
; Options: latest_working (default) | latest_released | latest_created
assembly_rev_rule  = latest_working
```

### Environment variables

| Variable | Description |
|---|---|
| `PLMLITE_VAULT_PATH` | Root of the vault (where NX files are stored) |
| `PLMLITE_DB_PATH` | Path to `plmlite.db` |
| `PLMLITE_VAULT_WINDOWS_PATH` | Windows-side vault path (Linux server only) |
| `PLMLITE_ASSEMBLY_REV_RULE` | `latest_working` / `latest_released` / `latest_created` |
| `PLMLITE_CONFIG` | Path to a custom `.ini` file |

> **Use mapped drive letters** (`K:\NXFiles`) not UNC paths (`\\server\NXFiles`). The Windows file-change API requires drive letters.

---

## Using the GUI

Launch → log in with your username and password → the main window opens.

### Parts Screen

Browse all items (parts, assemblies, drawings) in the database.

- **New Item** — create a part/assembly record with item ID, name, description
- **+ Revision** — add a new revision with a free-text label (A, B, 01, REV1…)
- **Attach File** — upload an NX file to the current revision; BOM relationships auto-sync
- **Open** — copies the file (and all assembly children) to your `PLMTemp\` folder and opens it in NX
  - If the file is already checked out by you: opens your existing writable copy
  - If checked out by someone else: opens a read-only copy
  - If not checked out: auto-checks it out and opens a writable copy
- **Checkout / Checkin** — toggle button; checks out or checks in the selected revision
- **Lock / Unlock** — marks a revision as released (locked) or unlocks it (admin only)
- **Edit / Delete** — modify item metadata or remove an item entirely

**Detail tabs** (bottom panel):
- **Datasets** — attached NX files for the selected revision
- **Structure** — BOM children (double-click to jump to that part)
- **Where Used** — assemblies that reference this part
- **History** — check-out/check-in log
- **Attributes** — key/value metadata

### My Files Screen

Shows all files you currently have checked out and their local temp paths. The background TempWatcher monitors these files — when NX saves a file, it is automatically pushed back to the vault. The status bar shows the last auto-save event.

### BOM Tree Screen

Search for an assembly by **part name or number** (live suggestions as you type). Select a result to load the full BOM tree on the left and a where-used list on the right. Double-click any node to jump to that item in the Parts screen.

### Settings Screen

- **Vault Path / DB Path** — configure where files and the database live
- **Assembly Rev Rule** — choose which child revisions are loaded when opening an assembly
- Changes are written to `plmlite.ini` and take effect immediately

---

## Multi-Machine Setup

Each engineer runs PLM Lite on their own Windows machine. All machines point to the same vault on a network share.

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Josh's PC   │   │  Bob's PC    │   │  Alice's PC  │
│  plmlite-gui │   │  plmlite-gui │   │  plmlite-gui │
│  PLMTemp\    │   │  PLMTemp\    │   │  PLMTemp\    │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │
       └──────────────────┴──────────────────┘
                          │
                   ┌──────▼───────┐
                   │  K:\ (NAS)   │
                   │  NXFiles\    │
                   │  plmlite.db  │
                   └──────────────┘
```

**Setup steps for each machine:**

1. Map the network share to a drive letter (e.g. `K:\`)
2. Copy `plmlite-gui.exe` (or clone the repo) to any local folder
3. Create `plmlite.ini` pointing to `K:\NXFiles` and `K:\plmlite.db`
4. Launch and log in — each user has their own account in the database

**Admin setup (first time):**

```python
# Run once to create the DB and first admin user:
python -c "
import sys; sys.path.insert(0, 'src')
from plmlite.database import Database
db = Database('K:/plmlite.db')
db.create_user('admin', 'password', 'admin')
"
```

---

## Building the .exe

Requirements: `pip install pyinstaller`

### GUI executable

```bash
pyinstaller --onefile --name plmlite-gui --windowed \
  --collect-submodules watchdog \
  --collect-data customtkinter \
  --add-data "schema.sql;." \
  src/plmlite/gui.py
# Output: dist/plmlite-gui.exe
```

### GitHub Actions (automatic)

The workflow at [.github/workflows/build.yml](.github/workflows/build.yml) builds `plmlite-gui.exe` automatically on every push to `main` and uploads it as a build artifact.

To create a versioned release:

```bash
git tag v3.0.0
git push origin v3.0.0
```

---

## Limitations

- **Soft locks only.** Check-out/check-in is advisory — NX does not enforce it at the file system level. Engineers must follow the workflow.
- **One DB writer at a time.** SQLite on a network share handles concurrent reads fine, but avoid running two instances that both write heavily at the same moment. In practice this is not a problem since each user writes only on check-out/check-in events.
- **Windows only.** The temp-watcher and file-open workflow targets Windows. The vault itself can live on any file server (Samba, NAS, Windows share).
- **NX BOM parsing is heuristic.** Component filenames are extracted from the NX binary by scanning for known byte patterns — not via NX Open API. It works reliably for standard NX12+ part/assembly files but may miss components in unusual configurations.
- **Not a Teamcenter replacement.** No formal approval workflows, ECO tracking, or NX PDM hook integration. Built for teams of 1–10 who need pragmatic version control without enterprise overhead.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

**PLM Lite v3.0.0** · Python + CustomTkinter + SQLite · [GitHub](https://github.com/kkers42/PLM-Lite) · [Issues](https://github.com/kkers42/PLM-Lite/issues)
