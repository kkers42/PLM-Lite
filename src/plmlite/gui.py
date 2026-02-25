"""PLMLITE Desktop GUI — CustomTkinter dark theme, Ubuntu/GNOME Teamcenter feel."""

import configparser
import getpass
import logging
import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from . import config
from .database import Database
from .lifecycle import LifecycleState

# ── Palette ───────────────────────────────────────────────────────────────────
BG          = "#1e1e2e"
SIDEBAR_BG  = "#181825"
CARD        = "#313244"
ACCENT      = "#E95420"   # Ubuntu orange
ACCENT_HOVER= "#C7451A"
FG          = "#cdd6f4"
FG_MUTED    = "#6c7086"
ROW_EVEN    = "#252535"
ROW_ODD     = "#1e1e2e"
ROW_CHECKED = "#2d2038"
TREE_HDR    = "#313244"

STATE_FG = {
    "design":   "#94a3b8",
    "review":   "#f9e2af",
    "released": "#a6e3a1",
    "archived": "#f38ba8",
}

FONT_BODY  = ("Segoe UI", 12)
FONT_BOLD  = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_MONO  = ("Consolas", 11)

NAV_ITEMS = [
    ("files",     "📁  Files"),
    ("watcher",   "📊  Watcher"),
    ("checkouts", "🔒  Checkouts"),
    ("settings",  "⚙   Settings"),
    ("about",     "ℹ   About"),
]

_VERSION = "0.1.0"
_REPO_URL = "https://github.com/yourusername/PLMLITE"
_ISSUES_URL = "https://github.com/yourusername/PLMLITE/issues"


# ── Log handler that feeds the GUI queue ──────────────────────────────────────
class GUILogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._q.put_nowait((self.format(record), record.levelno >= logging.ERROR))
        except queue.Full:
            pass


# ── Styled Treeview helper ────────────────────────────────────────────────────
def _style_treeview(tree: ttk.Treeview, columns: list[tuple]) -> None:
    """Apply dark styling to a ttk.Treeview and configure columns."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Dark.Treeview",
        background=BG,
        foreground=FG,
        fieldbackground=BG,
        rowheight=26,
        font=FONT_BODY,
        borderwidth=0,
    )
    style.configure(
        "Dark.Treeview.Heading",
        background=TREE_HDR,
        foreground=FG,
        font=FONT_BOLD,
        relief="flat",
        borderwidth=0,
    )
    style.map("Dark.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
    tree.configure(style="Dark.Treeview", show="headings")
    for col_id, heading, width, anchor in columns:
        tree.heading(col_id, text=heading)
        tree.column(col_id, width=width, anchor=anchor, minwidth=40)
    tree.tag_configure("checked_out", background=ROW_CHECKED)
    tree.tag_configure("even", background=ROW_EVEN)
    tree.tag_configure("odd", background=ROW_ODD)


def _scrolled_tree(parent, columns: list[tuple]) -> tuple[ttk.Treeview, ctk.CTkFrame]:
    """Return (Treeview, container_frame) with a vertical scrollbar."""
    frame = ctk.CTkFrame(parent, fg_color=BG, corner_radius=8)
    vsb = ttk.Scrollbar(frame, orient="vertical")
    vsb.pack(side="right", fill="y")
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], yscrollcommand=vsb.set)
    vsb.configure(command=tree.yview)
    _style_treeview(tree, columns)
    tree.pack(side="left", fill="both", expand=True)
    return tree, frame


# ══════════════════════════════════════════════════════════════════════════════
# Screen 1 — Files + History
# ══════════════════════════════════════════════════════════════════════════════
class FilesFrame(ctk.CTkFrame):
    def __init__(self, master, db: Database, app: "PLMLITEApp"):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.db  = db
        self.app = app
        self._selected_file: dict | None = None
        self._build()

    def _build(self) -> None:
        # ── header row ──
        hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(hdr, text="Tracked Files", font=FONT_TITLE, text_color=FG).pack(side="left")
        ctk.CTkButton(
            hdr, text="↺  Refresh", width=100, height=30,
            fg_color=CARD, hover_color=ACCENT, text_color=FG,
            font=FONT_BODY, command=self.refresh,
        ).pack(side="right")

        # ── file table (top half) ──
        file_cols = [
            ("filename",       "Filename",       220, "w"),
            ("state",          "State",           90, "center"),
            ("current_version","Ver",             50, "center"),
            ("checked_out_by", "Checked Out By", 140, "w"),
            ("created_at",     "First Seen",     150, "center"),
        ]
        self._file_tree, tree_frame = _scrolled_tree(self, file_cols)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=4)
        self._file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

        # ── divider ──
        ctk.CTkFrame(self, fg_color=CARD, height=2, corner_radius=0).pack(fill="x", padx=16, pady=6)

        # ── history panel (bottom half) ──
        hist_hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hist_hdr.pack(fill="x", padx=16, pady=(0, 4))
        self._hist_label = ctk.CTkLabel(
            hist_hdr, text="Select a file to view history",
            font=FONT_BOLD, text_color=FG_MUTED,
        )
        self._hist_label.pack(side="left")

        # action buttons
        btn_row = ctk.CTkFrame(hist_hdr, fg_color=BG, corner_radius=0)
        btn_row.pack(side="right")
        self._btn_checkout = ctk.CTkButton(
            btn_row, text="Checkout", width=90, height=28,
            fg_color=CARD, hover_color=ACCENT, text_color=FG,
            font=FONT_BODY, command=self._checkout, state="disabled",
        )
        self._btn_checkout.pack(side="left", padx=(0, 6))
        self._btn_checkin = ctk.CTkButton(
            btn_row, text="Checkin", width=90, height=28,
            fg_color=CARD, hover_color=ACCENT, text_color=FG,
            font=FONT_BODY, command=self._checkin, state="disabled",
        )
        self._btn_checkin.pack(side="left", padx=(0, 6))
        self._state_var = ctk.StringVar(value="Set State")
        self._state_menu = ctk.CTkOptionMenu(
            btn_row,
            values=["design", "review", "released", "archived"],
            variable=self._state_var,
            command=self._set_state,
            width=120, height=28,
            fg_color=CARD, button_color=CARD, button_hover_color=ACCENT,
            text_color=FG, font=FONT_BODY,
            state="disabled",
        )
        self._state_menu.pack(side="left")

        hist_cols = [
            ("version_num", "Ver",      50, "center"),
            ("saved_by",    "Saved By", 140, "w"),
            ("saved_at",    "Saved At", 170, "center"),
            ("file_size",   "Size",      80, "e"),
        ]
        self._hist_tree, hist_frame = _scrolled_tree(self, hist_cols)
        hist_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._action_status = ctk.CTkLabel(
            self, text="", font=FONT_BODY, text_color=FG_MUTED,
        )
        self._action_status.pack(anchor="w", padx=20, pady=(0, 8))

        self.refresh()

    def refresh(self) -> None:
        for item in self._file_tree.get_children():
            self._file_tree.delete(item)
        try:
            files = self.db.list_files()
        except Exception:
            files = []
        for i, f in enumerate(files):
            state = f.get("lifecycle_state") or "design"
            state_disp = f"● {state}"
            co_by = f.get("checked_out_by") or ""
            tags = ["checked_out"] if co_by else [("even" if i % 2 == 0 else "odd")]
            self._file_tree.insert(
                "", "end",
                iid=str(f["id"]),
                values=(
                    f["filename"],
                    state_disp,
                    f.get("current_version", 1),
                    co_by,
                    str(f.get("created_at", ""))[:16],
                ),
                tags=tags,
            )
            # colour the state cell tag (apply per-row via tag_configure trick)
            colour = STATE_FG.get(state, FG_MUTED)
            self._file_tree.tag_configure(f"state_{state}", foreground=colour)

    def _on_file_select(self, _event) -> None:
        sel = self._file_tree.selection()
        if not sel:
            return
        file_id = int(sel[0])
        try:
            row = self.db.get_file_by_path(
                next(f["filepath"] for f in self.db.list_files() if f["id"] == file_id)
            )
            if row is None:
                return
        except Exception:
            return
        self._selected_file = row
        fname = row["filename"]
        self._hist_label.configure(text=f"Version history — {fname}", text_color=FG)

        for item in self._hist_tree.get_children():
            self._hist_tree.delete(item)
        versions = self.db.get_version_history(file_id)
        for i, v in enumerate(versions):
            size_str = f"{v['file_size'] // 1024} KB" if v.get("file_size") else "—"
            self._hist_tree.insert(
                "", "end",
                values=(
                    v["version_num"],
                    v.get("saved_by") or "—",
                    str(v.get("saved_at", ""))[:19],
                    size_str,
                ),
                tags=["even" if i % 2 == 0 else "odd"],
            )

        for btn in (self._btn_checkout, self._btn_checkin, self._state_menu):
            btn.configure(state="normal")
        current_state = row.get("lifecycle_state") or "design"
        self._state_var.set(current_state)
        self._action_status.configure(text="")

    def _checkout(self) -> None:
        if not self._selected_file:
            return
        username = getpass.getuser()
        ok = self.db.checkout_file(self._selected_file["id"], username)
        if ok:
            self._action_status.configure(
                text=f"✓ Checked out to {username}", text_color=STATE_FG["released"]
            )
        else:
            self._action_status.configure(
                text=f"✗ Already checked out by {self._selected_file.get('checked_out_by', '?')}",
                text_color=STATE_FG["archived"],
            )
        self.refresh()

    def _checkin(self) -> None:
        if not self._selected_file:
            return
        self.db.checkin_file(self._selected_file["id"])
        self._action_status.configure(
            text=f"✓ Checked in: {self._selected_file['filename']}",
            text_color=STATE_FG["released"],
        )
        self.refresh()

    def _set_state(self, state_str: str) -> None:
        if not self._selected_file or state_str == "Set State":
            return
        self.db.set_lifecycle_state(self._selected_file["id"], state_str)
        self._action_status.configure(
            text=f"✓ State set to '{state_str}'", text_color=STATE_FG["review"]
        )
        self.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# Screen 2 — Watcher Dashboard
# ══════════════════════════════════════════════════════════════════════════════
class WatcherFrame(ctk.CTkFrame):
    def __init__(self, master, app: "PLMLITEApp"):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self._build()

    def _build(self) -> None:
        # ── header ──
        hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(hdr, text="Watcher Dashboard", font=FONT_TITLE, text_color=FG).pack(side="left")

        # ── control bar ──
        ctrl = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        ctrl.pack(fill="x", padx=16, pady=(0, 10))

        self._toggle_btn = ctk.CTkButton(
            ctrl, text="▶  Start Watching",
            width=180, height=40,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff", font=("Segoe UI", 13, "bold"),
            command=self._toggle,
        )
        self._toggle_btn.pack(side="left", padx=14, pady=10)

        self._status_badge = ctk.CTkLabel(
            ctrl, text="○  STOPPED",
            font=("Segoe UI", 12, "bold"), text_color=FG_MUTED,
        )
        self._status_badge.pack(side="left", padx=10)

        cfg = config.get_config()
        ctk.CTkLabel(
            ctrl, text=f"Watch path:  {cfg['WATCH_PATH']}",
            font=FONT_BODY, text_color=FG_MUTED,
        ).pack(side="left", padx=20)

        ctk.CTkButton(
            ctrl, text="Clear", width=70, height=30,
            fg_color=BG, hover_color=CARD, text_color=FG_MUTED,
            font=FONT_BODY, command=self.clear_log,
        ).pack(side="right", padx=14, pady=10)

        # ── log area ──
        self._log = ctk.CTkTextbox(
            self,
            fg_color="#11111b",
            text_color=FG,
            font=FONT_MONO,
            corner_radius=8,
            wrap="none",
            state="disabled",
        )
        self._log.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self.append_log("PLMLITE Watcher ready. Press Start to begin monitoring.")

    def _toggle(self) -> None:
        if self.app._watcher_thread and self.app._watcher_thread.is_alive():
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        from .watcher import FileWatcher
        self.app._watcher = FileWatcher()

        # attach GUI log handler to the watcher's logger
        handler = GUILogHandler(self.app.log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        watcher_logger = logging.getLogger("plmlite.watcher")
        watcher_logger.addHandler(handler)
        watcher_logger.setLevel(logging.DEBUG)
        self.app._log_handler = handler

        self.app._watcher_thread = threading.Thread(
            target=self.app._watcher.start, daemon=True
        )
        self.app._watcher_thread.start()

        self._toggle_btn.configure(text="■  Stop Watching", fg_color="#d62828", hover_color="#9b1919")
        self._status_badge.configure(text="●  RUNNING", text_color=STATE_FG["released"])
        self.app._update_watcher_status(running=True)
        self.append_log(f"▶ Started watching {config.WATCH_PATH}")

    def _stop(self) -> None:
        if self.app._watcher:
            self.app._watcher.stop()
            self.app._watcher = None
        if self.app._watcher_thread:
            self.app._watcher_thread.join(timeout=3)
            self.app._watcher_thread = None
        if hasattr(self.app, "_log_handler") and self.app._log_handler:
            logging.getLogger("plmlite.watcher").removeHandler(self.app._log_handler)
            self.app._log_handler = None

        self._toggle_btn.configure(text="▶  Start Watching", fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self._status_badge.configure(text="○  STOPPED", text_color=FG_MUTED)
        self.app._update_watcher_status(running=False)
        self.append_log("■ Watcher stopped.")

    def append_log(self, line: str, error: bool = False) -> None:
        self._log.configure(state="normal")
        tag = "error" if error else "normal"
        self._log.insert("0.0", line + "\n")   # prepend newest at top
        if error:
            self._log.tag_config("error", foreground=STATE_FG["archived"])
        self._log.configure(state="disabled")

    def clear_log(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("0.0", "end")
        self._log.configure(state="disabled")


# ══════════════════════════════════════════════════════════════════════════════
# Screen 3 — Checkout Manager
# ══════════════════════════════════════════════════════════════════════════════
class CheckoutsFrame(ctk.CTkFrame):
    def __init__(self, master, db: Database):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.db = db
        self._build()

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(hdr, text="Checked-Out Files", font=FONT_TITLE, text_color=FG).pack(side="left")
        ctk.CTkButton(
            hdr, text="↺  Refresh", width=100, height=30,
            fg_color=CARD, hover_color=ACCENT, text_color=FG,
            font=FONT_BODY, command=self.refresh,
        ).pack(side="right")

        cols = [
            ("filename",       "Filename",        200, "w"),
            ("checked_out_by", "Checked Out By",  150, "w"),
            ("checked_out_at", "Checked Out At",  170, "center"),
            ("filepath",       "Full Path",        340, "w"),
        ]
        self._tree, tree_frame = _scrolled_tree(self, cols)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=4)

        btn_row = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        btn_row.pack(fill="x", padx=16, pady=(4, 12))
        self._checkin_btn = ctk.CTkButton(
            btn_row, text="Checkin Selected", width=160, height=34,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#ffffff",
            font=FONT_BOLD, command=self._checkin_selected, state="disabled",
        )
        self._checkin_btn.pack(side="left")
        self._status_lbl = ctk.CTkLabel(
            btn_row, text="", font=FONT_BODY, text_color=FG_MUTED,
        )
        self._status_lbl.pack(side="left", padx=14)

        self._tree.bind("<<TreeviewSelect>>", lambda _: self._checkin_btn.configure(state="normal"))
        self.refresh()

    def refresh(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)
        try:
            checkouts = self.db.list_checkouts()
        except Exception:
            checkouts = []
        if not checkouts:
            self._tree.insert("", "end", values=("No files currently checked out.", "", "", ""))
            self._checkin_btn.configure(state="disabled")
            return
        for i, f in enumerate(checkouts):
            self._tree.insert(
                "", "end", iid=str(f["id"]),
                values=(
                    f["filename"],
                    f.get("checked_out_by", ""),
                    str(f.get("checked_out_at", ""))[:19],
                    f.get("filepath", ""),
                ),
                tags=["even" if i % 2 == 0 else "odd"],
            )
        self._checkin_btn.configure(state="disabled")

    def _checkin_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        file_id = int(sel[0])
        self.db.checkin_file(file_id)
        self._status_lbl.configure(text="✓ Checked in", text_color=STATE_FG["released"])
        self.refresh()


# ══════════════════════════════════════════════════════════════════════════════
# Screen 4 — Settings
# ══════════════════════════════════════════════════════════════════════════════
class SettingsFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Configuration", font=FONT_TITLE, text_color=FG).pack(
            anchor="w", padx=16, pady=(14, 8)
        )

        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        card.pack(fill="x", padx=16, pady=(0, 10))

        cfg = config.get_config()
        self._fields: dict[str, ctk.CTkEntry] = {}

        field_defs = [
            ("watch_path",       "Watch Path",        str(cfg["WATCH_PATH"]),       "dir"),
            ("backup_path",      "Backup Path",       str(cfg["BACKUP_PATH"]),      "dir"),
            ("db_path",          "Database Path",     str(cfg["DB_PATH"]),          "file"),
            ("max_versions",     "Max Versions",      str(cfg["MAX_VERSIONS"]),     None),
            ("file_extensions",  "File Extensions",   ", ".join(cfg["FILE_EXTENSIONS"]), None),
        ]

        for row_idx, (key, label, default, browse_type) in enumerate(field_defs):
            row = ctk.CTkFrame(card, fg_color=CARD, corner_radius=0)
            row.pack(fill="x", padx=16, pady=6)
            ctk.CTkLabel(row, text=label, width=140, anchor="w", font=FONT_BODY, text_color=FG).pack(side="left")
            entry = ctk.CTkEntry(
                row, font=FONT_BODY,
                fg_color=BG, text_color=FG, border_color=CARD,
                width=380,
            )
            entry.insert(0, default)
            entry.pack(side="left", padx=(0, 8))
            self._fields[key] = entry
            if browse_type == "dir":
                ctk.CTkButton(
                    row, text="Browse…", width=80, height=28,
                    fg_color=BG, hover_color=ACCENT, text_color=FG,
                    font=FONT_BODY,
                    command=lambda e=entry: self._browse_dir(e),
                ).pack(side="left")
            elif browse_type == "file":
                ctk.CTkButton(
                    row, text="Browse…", width=80, height=28,
                    fg_color=BG, hover_color=ACCENT, text_color=FG,
                    font=FONT_BODY,
                    command=lambda e=entry: self._browse_file(e),
                ).pack(side="left")

        # action buttons
        btn_row = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        btn_row.pack(fill="x", padx=16, pady=8)

        ctk.CTkButton(
            btn_row, text="Save to plmlite.ini", width=170, height=34,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#ffffff",
            font=FONT_BOLD, command=self._save_ini,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Test Paths", width=110, height=34,
            fg_color=CARD, hover_color=ACCENT, text_color=FG,
            font=FONT_BODY, command=self._test_paths,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Reset Defaults", width=130, height=34,
            fg_color=CARD, hover_color=ACCENT, text_color=FG,
            font=FONT_BODY, command=self._reset_defaults,
        ).pack(side="left")

        self._status_lbl = ctk.CTkLabel(
            self, text="", font=FONT_BODY, text_color=FG_MUTED, wraplength=700, justify="left",
        )
        self._status_lbl.pack(anchor="w", padx=16, pady=(4, 0))

        # ini hint
        ctk.CTkLabel(
            self,
            text="plmlite.ini will be written to the current working directory.\n"
                 "Restart PLMLITE after saving for changes to take effect.",
            font=("Segoe UI", 11), text_color=FG_MUTED, justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 0))

    def _browse_dir(self, entry: ctk.CTkEntry) -> None:
        path = filedialog.askdirectory(title="Select folder")
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _browse_file(self, entry: ctk.CTkEntry) -> None:
        path = filedialog.asksaveasfilename(
            title="Database file location",
            defaultextension=".db",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _test_paths(self) -> None:
        # Temporarily override config values with what's in the fields, test, then restore
        watch  = Path(self._fields["watch_path"].get())
        backup = Path(self._fields["backup_path"].get())
        db     = Path(self._fields["db_path"].get())
        warnings = []
        if not watch.exists():
            warnings.append(f"✗ Watch path not found: {watch}")
        else:
            warnings.append(f"✓ Watch path OK: {watch}")
        if not backup.parent.exists():
            warnings.append(f"✗ Backup parent not found: {backup.parent}")
        else:
            warnings.append(f"✓ Backup path OK: {backup}")
        if not db.parent.exists():
            warnings.append(f"✗ Database parent not found: {db.parent}")
        else:
            warnings.append(f"✓ Database path OK: {db}")
        self._status_lbl.configure(text="\n".join(warnings), text_color=FG)

    def _save_ini(self) -> None:
        ini = configparser.ConfigParser()
        ini["plmlite"] = {
            "watch_path":      self._fields["watch_path"].get(),
            "backup_path":     self._fields["backup_path"].get(),
            "db_path":         self._fields["db_path"].get(),
            "max_versions":    self._fields["max_versions"].get(),
            "file_extensions": self._fields["file_extensions"].get(),
        }
        try:
            with open("plmlite.ini", "w") as f:
                ini.write(f)
            self._status_lbl.configure(
                text="✓ Saved to plmlite.ini — restart PLMLITE for changes to take effect.",
                text_color=STATE_FG["released"],
            )
        except OSError as e:
            self._status_lbl.configure(text=f"✗ Save failed: {e}", text_color=STATE_FG["archived"])

    def _reset_defaults(self) -> None:
        cfg = config.get_config()
        defaults = {
            "watch_path":      str(cfg["WATCH_PATH"]),
            "backup_path":     str(cfg["BACKUP_PATH"]),
            "db_path":         str(cfg["DB_PATH"]),
            "max_versions":    str(cfg["MAX_VERSIONS"]),
            "file_extensions": ", ".join(cfg["FILE_EXTENSIONS"]),
        }
        for key, val in defaults.items():
            e = self._fields[key]
            e.delete(0, "end")
            e.insert(0, val)
        self._status_lbl.configure(text="Fields reset to current config values.", text_color=FG_MUTED)


# ══════════════════════════════════════════════════════════════════════════════
# Screen 5 — About
# ══════════════════════════════════════════════════════════════════════════════
class AboutFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self._build()

    def _build(self) -> None:
        # Centre everything in a card
        outer = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(outer, fg_color=CARD, corner_radius=16, width=560)
        card.grid(row=0, column=0, padx=40, pady=40, sticky="n")
        card.grid_propagate(False)

        # Logo / title block
        ctk.CTkLabel(
            card,
            text="⬡",
            font=("Segoe UI", 52),
            text_color=ACCENT,
        ).pack(pady=(32, 0))

        ctk.CTkLabel(
            card,
            text="PLMLITE",
            font=("Segoe UI", 28, "bold"),
            text_color=FG,
        ).pack()

        ctk.CTkLabel(
            card,
            text=f"Version {_VERSION}",
            font=("Segoe UI", 13),
            text_color=FG_MUTED,
        ).pack(pady=(2, 0))

        # Divider
        ctk.CTkFrame(card, fg_color=SIDEBAR_BG, height=2, corner_radius=0).pack(
            fill="x", padx=32, pady=20
        )

        # Description
        ctk.CTkLabel(
            card,
            text=(
                "Lightweight Product Lifecycle Management\n"
                "for Siemens NX12 CAD datasets on Windows network shares.\n\n"
                "Built for small engineering teams who need version tracking,\n"
                "check-in/check-out, and change logging — without the cost\n"
                "or complexity of a full PDM system like Teamcenter."
            ),
            font=FONT_BODY,
            text_color=FG,
            justify="center",
        ).pack(padx=32)

        # Divider
        ctk.CTkFrame(card, fg_color=SIDEBAR_BG, height=2, corner_radius=0).pack(
            fill="x", padx=32, pady=20
        )

        # Tech stack
        ctk.CTkLabel(
            card,
            text="Built with",
            font=FONT_BOLD,
            text_color=FG_MUTED,
        ).pack()
        ctk.CTkLabel(
            card,
            text="Python 3.10+  ·  CustomTkinter  ·  watchdog  ·  SQLite",
            font=("Segoe UI", 11),
            text_color=FG_MUTED,
        ).pack(pady=(4, 0))

        # License
        ctk.CTkLabel(
            card,
            text="Released under the MIT License",
            font=("Segoe UI", 11),
            text_color=FG_MUTED,
        ).pack(pady=(4, 0))

        # Divider
        ctk.CTkFrame(card, fg_color=SIDEBAR_BG, height=2, corner_radius=0).pack(
            fill="x", padx=32, pady=20
        )

        # Link buttons
        btn_row = ctk.CTkFrame(card, fg_color=CARD, corner_radius=0)
        btn_row.pack(pady=(0, 32))

        ctk.CTkButton(
            btn_row,
            text="⎋  GitHub Repository",
            width=180, height=34,
            fg_color=BG, hover_color=SIDEBAR_BG, text_color=FG,
            font=FONT_BODY,
            command=lambda: self._open_url(_REPO_URL),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="🐛  Report an Issue",
            width=160, height=34,
            fg_color=BG, hover_color=SIDEBAR_BG, text_color=FG,
            font=FONT_BODY,
            command=lambda: self._open_url(_ISSUES_URL),
        ).pack(side="left")

    @staticmethod
    def _open_url(url: str) -> None:
        import webbrowser
        webbrowser.open(url)


# ══════════════════════════════════════════════════════════════════════════════
# Main Application
# ══════════════════════════════════════════════════════════════════════════════
class PLMLITEApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("PLMLITE PDM")
        self.geometry("1100x700")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        # State
        self.db = Database()
        self.db.initialize()
        self.log_queue: queue.Queue = queue.Queue()
        self._watcher = None
        self._watcher_thread: threading.Thread | None = None
        self._log_handler: GUILogHandler | None = None

        self._frames: dict = {}
        self._nav_btns: dict = {}
        self._active_frame = None

        self._build_layout()
        self.show_frame("files")
        self.after(300, self._poll_log_queue)

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_layout(self) -> None:
        # root grid: sidebar | content
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # sidebar
        self._sidebar = ctk.CTkFrame(self, fg_color=SIDEBAR_BG, width=180, corner_radius=0)
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_propagate(False)

        # content area
        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_frames()

    def _build_sidebar(self) -> None:
        # App title
        title_frame = ctk.CTkFrame(self._sidebar, fg_color=SIDEBAR_BG, corner_radius=0)
        title_frame.pack(fill="x", pady=(16, 20), padx=10)
        ctk.CTkLabel(
            title_frame, text="⬡ PLMLITE", font=("Segoe UI", 16, "bold"),
            text_color=ACCENT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame, text="PDM", font=("Segoe UI", 10),
            text_color=FG_MUTED,
        ).pack(anchor="w")

        # Nav buttons
        for key, label in NAV_ITEMS:
            btn = ctk.CTkButton(
                self._sidebar,
                text=label,
                anchor="w",
                height=38,
                corner_radius=6,
                fg_color=SIDEBAR_BG,
                hover_color=CARD,
                text_color=FG,
                font=FONT_BODY,
                command=lambda k=key: self.show_frame(k),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = btn

        # Spacer
        ctk.CTkFrame(self._sidebar, fg_color=SIDEBAR_BG, height=1).pack(fill="x", expand=True)

        # Status footer
        footer = ctk.CTkFrame(self._sidebar, fg_color=SIDEBAR_BG, corner_radius=0)
        footer.pack(fill="x", padx=10, pady=14)
        self._status_dot = ctk.CTkLabel(footer, text="○  Stopped", font=FONT_BODY, text_color=FG_MUTED)
        self._status_dot.pack(anchor="w")
        ctk.CTkLabel(
            footer, text=getpass.getuser(),
            font=FONT_BODY, text_color=FG_MUTED,
        ).pack(anchor="w")

    def _build_frames(self) -> None:
        self._frames["files"]     = FilesFrame(self._content, self.db, self)
        self._frames["watcher"]   = WatcherFrame(self._content, self)
        self._frames["checkouts"] = CheckoutsFrame(self._content, self.db)
        self._frames["settings"]  = SettingsFrame(self._content)
        self._frames["about"]     = AboutFrame(self._content)
        for frame in self._frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

    # ── Navigation ────────────────────────────────────────────────────────────
    def show_frame(self, name: str) -> None:
        frame = self._frames.get(name)
        if frame is None:
            return
        frame.tkraise()
        self._active_frame = name

        # Refresh data when switching to these screens
        if name == "files":
            frame.refresh()
        elif name == "checkouts":
            frame.refresh()

        # Update nav button highlight
        for key, btn in self._nav_btns.items():
            if key == name:
                btn.configure(fg_color=CARD, text_color=ACCENT)
            else:
                btn.configure(fg_color=SIDEBAR_BG, text_color=FG)

    # ── Watcher status ────────────────────────────────────────────────────────
    def _update_watcher_status(self, running: bool) -> None:
        if running:
            self._status_dot.configure(text="●  Watching", text_color=STATE_FG["released"])
        else:
            self._status_dot.configure(text="○  Stopped", text_color=FG_MUTED)

    # ── Log queue polling ─────────────────────────────────────────────────────
    def _poll_log_queue(self) -> None:
        watcher_frame: WatcherFrame = self._frames.get("watcher")
        if watcher_frame:
            try:
                while True:
                    line, is_error = self.log_queue.get_nowait()
                    watcher_frame.append_log(line, error=is_error)
            except queue.Empty:
                pass
        self.after(300, self._poll_log_queue)


# ── Entry point ───────────────────────────────────────────────────────────────
def launch() -> None:
    """Called by the `plmlite-gui` console script."""
    app = PLMLITEApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
