# PLMLITE

> Lightweight, open-source Product Lifecycle Management for **Siemens NX12 CAD datasets** on a Windows network share.

Designed for small engineering teams (1–5 people) who need automatic version tracking,
check-in/check-out, and change logging — without the cost or complexity of a full PDM
system like Teamcenter.

PLMLITE ships as both a **desktop GUI** (dark Ubuntu/GNOME-style) and a **CLI tool**.
Both use the same SQLite database stored directly on your network share.

---

## Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Installation](#installation)
  - [Option A — Pre-built Windows .exe (recommended)](#option-a--pre-built-windows-exe-recommended)
  - [Option B — From source](#option-b--from-source)
- [Configuration](#configuration)
- [Using the GUI](#using-the-gui)
- [Using the CLI](#using-the-cli)
- [Building the .exe yourself](#building-the-exe-yourself)
- [Running Tests](#running-tests)
- [Limitations](#limitations)
- [License](#license)

---

## Features

| Feature | GUI | CLI |
|---|:---:|:---:|
| Monitor network share for NX12 file saves | ✓ | ✓ |
| Auto-backup on every save (timestamped copies) | ✓ | ✓ |
| Keep last N versions, auto-delete older ones | ✓ | ✓ |
| Log Windows username + timestamp of every save | ✓ | ✓ |
| Check-out / check-in (advisory soft lock) | ✓ | ✓ |
| Lifecycle state tracking (design → review → released → archived) | ✓ | ✓ |
| Live activity feed while watching | ✓ | ✓ |
| Settings form with Browse dialogs | ✓ | — |
| Standalone Windows .exe, no Python required | ✓ | ✓ |

---

## Screenshots

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⬡ PLMLITE PDM                                            _ □ ✕    │
├──────────────┬──────────────────────────────────────────────────────┤
│  PDM         │  Tracked Files                       ↺ Refresh      │
│              │  ┌────────────────────────────────────────────────┐  │
│  📁 Files ◀  │  │ Filename       State     Ver  Checked Out By   │  │
│  📊 Watcher  │  │ part_001.prt   ● released  3   —               │  │
│  🔒 Checkouts│  │ assembly.asm   ● review    2   JSMITH           │  │
│  ⚙  Settings │  │ bracket_lh.prt ● design    1   —               │  │
│  ℹ  About    │  └────────────────────────────────────────────────┘  │
│              │  ─────────────────────────────────────────────────── │
│  ────────    │  Version history — part_001.prt                      │
│  ● Watching  │  Ver  Saved By   Saved At             Size           │
│  JSMITH      │   3   JSMITH    2026-02-24 14:32:01   842 KB         │
│              │   2   JSMITH    2026-02-24 11:15:44   841 KB         │
│              │   1   AJONAS    2026-02-23 09:03:12   835 KB         │
│              │                                                      │
│              │  [Checkout]  [Checkin]  [Set State ▾]                │
└──────────────┴──────────────────────────────────────────────────────┘
```

---

## Installation

### Option A — Pre-built Windows .exe (recommended)

No Python installation required.

1. Go to the [**Actions**](https://github.com/kkers42/PLM-Lite/actions) tab on GitHub
2. Click the latest successful **Build Windows Executables** run
3. Under **Artifacts**, download:
   - `plmlite-gui-windows` → extract `plmlite-gui.exe` — the desktop GUI
   - `plmlite-cli-windows` → extract `plmlite.exe` — the command-line tool
4. Place the `.exe` file(s) on each engineer's machine, or on a shared drive

For tagged releases (e.g. `v0.1.0`), both executables are also attached to the
[**Releases**](https://github.com/kkers42/PLM-Lite/releases) page.

> **Quick start after download:**
> 1. Create `plmlite.ini` next to the `.exe` (see [Configuration](#configuration))
> 2. Double-click `plmlite-gui.exe`
> 3. Click **Settings**, set your network share paths, click **Save to plmlite.ini**
> 4. Click **Watcher → Start Watching**

---

### Option B — From source

Requirements: **Python 3.10+**, **pip**, **git**

```bash
# 1. Clone the repository
git clone https://github.com/kkers42/PLM-Lite.git
cd PLMLITE

# 2. Install the package (installs watchdog and customtkinter automatically)
pip install -e .

# 3. Launch the GUI
plmlite-gui

# Or use the CLI
plmlite --help
```

To also install dev/test tools:

```bash
pip install -e ".[test,dev]"
```

---

## Configuration

PLMLITE reads settings in this priority order:

1. **Environment variables** (highest priority — useful for scripting)
2. **`plmlite.ini`** in the current working directory, or at the path set in `PLMLITE_CONFIG`
3. **Built-in defaults** (placeholder server paths — change before first use)

### plmlite.ini

Create `plmlite.ini` in the same folder as the `.exe` (or your working directory):

```ini
[plmlite]
watch_path      = R:\Engineering\Datasets
backup_path     = R:\Engineering\Datasets\backups
db_path         = R:\Engineering\Datasets\pdm.db
max_versions    = 3
file_extensions = .prt,.asm,.drw
```

> **Use mapped drive letters** (e.g. `R:\Datasets`) rather than raw UNC paths
> (`\\server\share\Datasets`). The Windows file-change API (`ReadDirectoryChangesW`)
> works reliably only with drive letters.

The **Settings screen** in the GUI can create/edit this file for you — no manual
editing required.

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `PLMLITE_CONFIG` | Path to a custom `.ini` file | `./plmlite.ini` |
| `PLMLITE_WATCH_PATH` | Folder to monitor | `\\server\share\datasets` |
| `PLMLITE_BACKUP_PATH` | Folder for backup copies | `…\backups` |
| `PLMLITE_DB_PATH` | Path to the SQLite database | `…\pdm.db` |
| `PLMLITE_MAX_VERSIONS` | Versions to keep per file | `3` |
| `PLMLITE_FILE_EXTENSIONS` | Comma-separated extensions | `.prt,.asm,.drw` |

---

## Using the GUI

Launch with:
```
plmlite-gui
```
or double-click `plmlite-gui.exe`.

### Files screen

Browse all tracked NX files. Each row shows the filename, lifecycle state (colour-coded),
current version number, and who (if anyone) has it checked out.

Click a row to see the full version history in the bottom panel — every save event with
who made it, when, and the file size.

Action buttons on the selected file:
- **Checkout** — marks the file as checked out under your Windows username
- **Checkin** — releases the checkout
- **Set State ▾** — dropdown to change lifecycle state (design / review / released / archived)

### Watcher screen

Click **▶ Start Watching** to begin monitoring your `WATCH_PATH`. The activity log
shows every file save in real time:

```
[14:32:01]  v3  part_001.prt  JSMITH  842 KB
[14:28:15]  v2  part_001.prt  JSMITH  841 KB
[09:03:12]  v1  bracket_lh.prt  AJONAS  312 KB
```

Click **■ Stop Watching** to halt. The watcher status dot in the sidebar turns green
while running.

### Checkouts screen

Shows all files currently checked out. Select a row and click **Checkin Selected** to
release the lock (useful if someone forgot to check in before leaving).

### Settings screen

Edit all configuration paths and options. Use **Browse…** to navigate to folders.
Click **Test Paths** to verify the paths exist before saving.
Click **Save to plmlite.ini** to write the config file. A restart is required for
changes to take effect.

### About screen

Shows version, license, and links to the project repository and issue tracker.

---

## Using the CLI

The CLI is useful for scripting, scheduled tasks, or headless servers.

```
plmlite <command> [args]
```

| Command | Description |
|---|---|
| `plmlite config` | Show resolved configuration |
| `plmlite watch` | Start file watcher (blocks, Ctrl+C to stop) |
| `plmlite history <filename>` | Show version history for a file |
| `plmlite list-checkouts` | List all currently checked-out files |
| `plmlite checkout <filename>` | Check out a file under your username |
| `plmlite checkin <filename>` | Check in a file |
| `plmlite state <filepath>` | Show lifecycle state |
| `plmlite set <filepath> <state>` | Set lifecycle state |
| `plmlite parse <filepath>` | Show file metadata |

### Examples

```bash
# Show current config (check paths are correct before first run)
plmlite config

# Start watching — leave this running in the background
plmlite watch

# Who saved what and when
plmlite history assembly_top.asm

# Check out before editing
plmlite checkout bracket_lh.prt

# Release after saving
plmlite checkin bracket_lh.prt

# Mark a file as approved
plmlite set "R:\Datasets\part_001.prt" released

# See all checked-out files across the team
plmlite list-checkouts
```

---

## Building the .exe yourself

Requirements: `pip install pyinstaller` (included in `.[dev]`)

### CLI executable

```bash
pyinstaller --onefile --name plmlite --console \
  --collect-submodules watchdog \
  --add-data "schema.sql;." \
  src/plmlite/main.py
# Output: dist/plmlite.exe
```

### GUI executable

```bash
pyinstaller --onefile --name plmlite-gui --windowed \
  --collect-submodules watchdog \
  --collect-data customtkinter \
  --add-data "schema.sql;." \
  src/plmlite/gui.py
# Output: dist/plmlite-gui.exe
```

`--windowed` suppresses the console window for the GUI build.
`--collect-data customtkinter` bundles the CustomTkinter theme assets.

### GitHub Actions (automatic)

The workflow at [.github/workflows/build.yml](.github/workflows/build.yml) runs both
builds automatically on every push to `main` and uploads the `.exe` files as artifacts.

To create a versioned GitHub Release, push a tag:

```bash
git tag v0.1.0
git push --tags
```

Both executables will be attached to the release.

---

## Running Tests

```bash
pip install -e ".[test]"
pytest
```

---

## Limitations

- **One watcher at a time.** SQLite on a network share does not support concurrent
  writes. Only run `plmlite watch` (or the Watcher screen) on **one machine at a time**.
  Read-only CLI commands (`history`, `list-checkouts`, `state`) are safe from any machine.
- **Soft locks only.** Check-out/check-in is advisory — it does not prevent NX from
  opening or saving files.
- **Not a Teamcenter replacement.** PLMLITE has no formal approval workflows, BOM
  management, or NX PDM hook integration. It is a pragmatic file-system-level tracker
  for teams of 1–5 people.
- **NX file parsing is a stub.** The `parse` command returns basic OS metadata.
  Real NX attribute extraction requires the NX Open API.
- **Windows only.** The file watcher uses `ReadDirectoryChangesW` (Windows API).
  The CLI runs on any OS but the watcher will not function on Linux/macOS.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## About

**PLMLITE v0.1.0**
Built with Python, watchdog, CustomTkinter, and SQLite.
Open source under the MIT License.

[GitHub Repository](https://github.com/kkers42/PLM-Lite) ·
[Report an Issue](https://github.com/kkers42/PLM-Lite/issues)
