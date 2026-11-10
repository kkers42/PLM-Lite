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

## Publish a STEP attachment as a 3D PDF (optional demo)

The Linux Docker deployment can optionally generate interactive, tessellated 3D PDFs
for single-solid STEP files. It uses FreeCAD to tessellate the part and the
Asymptote PRC writer from libPRC to encode the mesh. The original STEP remains
the source for CAD and manufacturing.

1. Build the optional converter into the image with
   `docker compose build --build-arg INSTALL_STEP_PDF=1 plm`.
2. Add `STEP_PDF_CONVERTER=/opt/plm-step-pdf/run` to your VPS `.env`.
3. Start the rebuilt container with `docker compose up -d --no-build plm`.
4. Create an unlocked test part and attach
   [demo-bracket.step](tests/fixtures/demo-bracket.step). In the part's Documents
   tab, click **Publish 3D PDF** and download the PDF.
5. Open the PDF in desktop Acrobat Reader. Enable 3D for this document, then
   rotate and zoom the bracket. Click **Publish 3D PDF** again and verify only
   one derived attachment exists for the same STEP bytes and revision.

The web app stores the PDF alongside the part's other attachments and records
the revision, source attachment ID, and source SHA-256 in the document
description. The app's attachment list is part-level and continues to show
earlier publications after a revision bump.

Publishing requires upload permission and an unlocked part. The endpoint
limits STEP files to 16 MiB and times out after 45 seconds. The bundled option
handles one solid and publishes mesh geometry for visual review.

An alternative converter can be configured by absolute executable path. It
receives two arguments, a local STEP input and PDF output, and must exit
successfully with a PDF containing an embedded PRC or U3D model. FreeCAD and the
Asymptote PRC library are separate dependencies. The optional image includes the
PRC library's corresponding source and license notices under
`/opt/plm-step-pdf`.

With the converter configured locally, run
`python -m unittest discover -s tests`. The real conversion test uses
`STEP_PDF_TEST_CONVERTER` as the executable path.
