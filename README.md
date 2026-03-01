# ⚙️ PLM Lite

**A free, open-source Product Lifecycle Management system for engineering teams.**
Track parts, manage CAD files, build BOMs, and control revisions — without the Teamcenter price tag.

**MIT License · Self-hosted · No subscriptions · No cloud required**

---

## ⬇️ Download (Windows — No programming required)

👉 **[Download Latest Release](https://github.com/kkers42/PLM-Lite/releases/latest)**

1. Download `PLM-Lite-vX.X.X-windows.zip`
2. Extract the zip to any folder (e.g. `C:\PLM-Lite\`)
3. Double-click **`start.bat`**
4. Your browser opens automatically to `http://localhost:8080`
5. Log in as **`admin`** / **`admin123`** — change the password right away

That's it. No Python, no Docker, no install wizard.

> **Network use:** To let your whole team connect, run PLM Lite on a shared PC or server and have teammates open `http://YOUR-PC-IP:8080` in their browser.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Parts Master** | Part Number, Name, Revision, Description, Part Level, 10+ custom attributes |
| **Assembly BOM** | Build parent/child relationships, view recursive indented BOM tree |
| **Where-Used** | Find every assembly a part is used in |
| **BOM Export** | Download Excel (.xlsx) with full indented BOM |
| **Check-In / Check-Out** | Advisory locks — prevents two engineers editing the same part |
| **Release Control** | Prototype → Released (locks part; reversible by authorized role) |
| **Revision History** | Snapshot the part record on every revision bump (A → B → C…) |
| **File Attachments** | Attach any file to a part record (CAD, PDFs, drawings, specs) |
| **CAD Versioning** | Keeps last 3 versions of CAD files with timestamped backups |
| **CAD Open-in-Place** | Open NX/SolidWorks files directly from the server (no download needed) |
| **Role-Based Access** | Admin / Engineer / Viewer — create custom roles with per-ability flags |
| **Audit Log** | Every action logged with user, timestamp, and detail |
| **Auth options** | Local username/password (self-hosted) or Google OAuth (cloud) |

---

## 🖥️ Live Demo

Try it now (no account needed — sign in with Google):
**[https://3dprintdudes.io/plm](https://3dprintdudes.io/plm)**

---

## 🐳 Docker (for IT / server deployment)

```bash
git clone https://github.com/kkers42/PLM-Lite.git
cd PLM-Lite

cp .env.example .env
# Edit .env — set AUTH_MODE, file paths, SECRET_KEY

docker compose -f docker-compose.local.yml up -d
```

Open `http://localhost:8080` — log in as `admin` / `admin123`.

---

## ⚙️ Configuration (.env)

| Setting | Default | Description |
|---|---|---|
| `AUTH_MODE` | `local` | `local`, `google`, or `windows` |
| `SECRET_KEY` | *(set this!)* | Random secret for JWT signing |
| `DB_PATH` | `./plm.db` | Path to SQLite database file |
| `FILES_ROOT` | `./data/files` | Where uploaded files are stored |
| `PORT` | `8080` | Port to listen on |

Copy `.env.example` → `.env` and fill in at minimum `SECRET_KEY` (any long random string).

---

## 🔑 Default Login

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin (full control) |

**Change this password immediately after first login** (Admin → Users → Edit).

---

## 🗂️ File Organization

CAD files are auto-sorted into folders by type:

```
files/
├── NX/           ← .prt .asm .drw
├── STL/          ← .stl
├── STEP/         ← .step .stp
├── SOLIDWORKS/   ← .sldprt .sldasm
├── INVENTOR/     ← .ipt .iam
├── PDF/
├── Temp/         ← files moved here on version restore
└── ...
```

CAD files keep the last **3 versions** with `_MMDD_HHMM` timestamp suffixes.

---

## 🔌 NX / CAD Open-in-Place (Windows)

To open CAD files directly in NX (or SolidWorks, Inventor, etc.) without downloading:

1. Map the PLM files folder as a network drive (e.g. `Z:\`)
2. Download and run `plmopen-handler.reg` from the app (one-time per workstation)
3. Click **Open** on any CAD file in the Documents panel — it launches in your CAD software directly from the server

---

## 🛠️ Tech Stack

- **Backend**: FastAPI, Python 3.12, SQLite (WAL mode)
- **Frontend**: Vanilla HTML / CSS / JavaScript (no frameworks, no build step)
- **Auth**: Google OAuth 2.0 + JWT cookies, or bcrypt local credentials
- **Excel export**: openpyxl
- **Deployment**: PyInstaller (Windows .exe), Docker + Traefik (server)

---

## 🤝 Contributing

Issues and PRs welcome. If you use NX, SolidWorks, or another CAD system and want to test the open-in-place workflow, please open an issue — that feedback is especially valuable.

---

*PLM Lite is not affiliated with Siemens, PTC, Dassault, or any commercial PLM vendor.*
