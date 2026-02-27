# PLM Lite V1.0

A lightweight web-based Product Lifecycle Management system built with FastAPI and vanilla JS.

**MIT License — Open Source**

---

## Features

- **Parts management** — Part Number, Name, Revision, Description, Part Level, 10+ custom Attributes
- **Assembly relationships** — Build parent/child trees, recursive BOM view, Where-Used query
- **BOM export** — Download Excel (.xlsx) with indented BOM
- **Check-in / Check-out** — Advisory locks tied to logged-in user
- **Release status** — Prototype → Released (locks part from editing; reversible by role)
- **Revision history** — Snapshot part on each revision bump (A → B → C…)
- **File attachments** — Attach any file to a part record
- **CAD file versioning** — Keeps last 3 versions of CAD files with `_MMDD_HHMM` backups
- **Dual auth** — Google OAuth (VPS) or local username/password (self-hosted)
- **Roles** — Admin, Engineer, Viewer (default); create custom roles with per-ability flags
- **Audit log** — Every create/update/release/checkout action is recorded

---

## Quick Start (Local / Self-Hosted)

### Requirements
- Python 3.12+
- OR Docker

### Bare Python

```bash
git clone https://github.com/kkers42/PLM-Lite-Web.git
cd PLM-Lite-Web

pip install -r requirements.txt

cp .env.example .env
# Edit .env: set AUTH_MODE=local, FILES_ROOT, DB_PATH

uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080` and log in as `admin` / `admin123`.
**Change the password immediately.**

### Docker (self-hosted)

```bash
cp .env.example .env
# Edit .env as needed

docker compose -f docker-compose.local.yml up -d
```

---

## VPS Deployment (3dprintdudes.io/plm)

See `docker-compose.yml` — joins the existing `stl-hub_web` Traefik network.

```bash
# On the VPS
cp .env.example .env
# Set AUTH_MODE=google, GOOGLE_CLIENT_ID/SECRET, APP_BASE_URL=https://3dprintdudes.io/plm

docker compose up -d --build
```

Google OAuth redirect URI to add in Google Cloud Console:
```
https://3dprintdudes.io/plm/auth/google/callback
```

---

## File Organization

Uploaded files are auto-organized by extension:
```
FILES_ROOT/
├── NX/           ← .prt, .asm, .drw
├── STL/          ← .stl
├── STEP/         ← .step, .stp
├── SOLIDWORKS/   ← .sldprt, .sldasm
├── INVENTOR/     ← .ipt, .iam
├── PDF/          ← .pdf
├── Temp/         ← Files moved here on version restore
└── ...
```

CAD files get versioned: `part_v1.prt` → backup `part_v1_0127_1430.prt` (MMDD_HHMM).
Max 3 backups per file. Non-CAD files (`.docx`, `.pptx`, etc.) are stored as-is.

---

## Default Credentials (local mode)

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Admin |

**Change the password on first login.**

---

## Tech Stack

- **Backend**: FastAPI, Python 3.12, SQLite (WAL mode)
- **Frontend**: Vanilla HTML/CSS/JavaScript (no frameworks)
- **Auth**: Google OAuth 2.0 + JWT cookies OR bcrypt local credentials
- **Files**: aiofiles for async I/O
- **Excel**: openpyxl
- **Deployment**: Docker + Traefik (VPS) or bare uvicorn (self-hosted)
