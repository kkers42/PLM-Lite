"""PLM Lite v2.0 -- Desktop GUI (CustomTkinter, dark theme).

5 screens via sidebar:
  1. Items       -- table of all items; right panel shows Item Detail on selection
  2. Item Detail -- item metadata, revisions, datasets, checkout/checkin
  3. Checkouts   -- active checkouts table
  4. Watcher     -- live log, start/stop
  5. Settings    -- watch paths, user management (admin), db path
"""

import getpass
import logging
import queue
import socket
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, simpledialog

import customtkinter as ctk

from . import config
from .database import Database
from .checkout import checkout_file, checkin_file, CheckoutError

# ------------------------------------------------------------------
# Palette
# ------------------------------------------------------------------
BG          = "#1e1e2e"
SIDEBAR_BG  = "#181825"
CARD        = "#313244"
ACCENT      = "#E95420"
ACCENT_H    = "#C7451A"
FG          = "#cdd6f4"
FG_MUTED    = "#6c7086"
ROW_EVEN    = "#252535"
ROW_ODD     = "#1e1e2e"
TREE_HDR    = "#313244"
ERR_FG      = "#f38ba8"
OK_FG       = "#a6e3a1"
WARN_FG     = "#f9e2af"

FONT_BODY  = ("Segoe UI", 12)
FONT_BOLD  = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_MONO  = ("Consolas", 11)

STATUS_COLOR = {
    "in_work":  "#94a3b8",
    "released": OK_FG,
    "locked":   WARN_FG,
    "obsolete": ERR_FG,
    "active":   "#89b4fa",
}

_VERSION = "2.0.0"


# ------------------------------------------------------------------
# Logging -> GUI queue bridge
# ------------------------------------------------------------------
class GUILogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def emit(self, record):
        try:
            self._q.put_nowait((self.format(record), record.levelno >= logging.WARNING))
        except queue.Full:
            pass


# ------------------------------------------------------------------
# Styled Treeview helper
# ------------------------------------------------------------------
def _make_tree(parent, columns: list, height=14) -> ttk.Treeview:
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview",
                    background=BG, foreground=FG, fieldbackground=BG,
                    rowheight=26, font=FONT_BODY)
    style.configure("Dark.Treeview.Heading",
                    background=TREE_HDR, foreground=FG, font=FONT_BOLD,
                    relief="flat")
    style.map("Dark.Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "#ffffff")])

    col_ids = [c[0] for c in columns]
    tree = ttk.Treeview(parent, style="Dark.Treeview",
                        columns=col_ids, show="headings", height=height)
    for cid, label, width in columns:
        tree.heading(cid, text=label)
        tree.column(cid, width=width, anchor="w")
    tree.tag_configure("even", background=ROW_EVEN)
    tree.tag_configure("odd",  background=ROW_ODD)
    return tree


def _tree_scroll(parent, tree) -> ttk.Scrollbar:
    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    return sb


def _btn(parent, text, cmd, width=130, fg_color=ACCENT, hover=ACCENT_H, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, width=width,
                         fg_color=fg_color, hover_color=hover,
                         font=FONT_BODY, **kw)


# ------------------------------------------------------------------
# Main application window
# ------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"PLM Lite v{_VERSION}")
        self.geometry("1200x750")
        self.configure(fg_color=BG)

        self.db = Database()
        self.db.initialize()
        self.username = getpass.getuser()
        self.db.upsert_user(self.username)

        self._log_q: queue.Queue = queue.Queue(maxsize=500)
        self._watcher_thread = None
        self._watcher_obj = None
        self._selected_item: dict = {}
        self._selected_rev: dict = {}
        self._selected_dataset: dict = {}

        self._build_layout()
        self._show_screen("items")
        self.after(500, self._poll_log_queue)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self._sidebar = ctk.CTkFrame(self, width=180, fg_color=SIDEBAR_BG, corner_radius=0)
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_rowconfigure(20, weight=1)

        ctk.CTkLabel(self._sidebar, text="PLM Lite", font=("Segoe UI", 16, "bold"),
                     text_color=ACCENT).grid(row=0, column=0, padx=16, pady=(18, 12))

        self._nav_btns = {}
        nav_items = [
            ("items",      "Items"),
            ("detail",     "Item Detail"),
            ("checkouts",  "Checkouts"),
            ("watcher",    "Watcher"),
            ("settings",   "Settings"),
        ]
        for i, (key, label) in enumerate(nav_items, start=1):
            btn = ctk.CTkButton(
                self._sidebar, text=label, width=160, height=34,
                fg_color="transparent", hover_color=CARD,
                text_color=FG, anchor="w", font=FONT_BODY,
                command=lambda k=key: self._show_screen(k),
            )
            btn.grid(row=i, column=0, padx=10, pady=2)
            self._nav_btns[key] = btn

        # User label at bottom
        self._user_lbl = ctk.CTkLabel(self._sidebar,
                                      text=f"User: {self.username}",
                                      font=("Segoe UI", 10), text_color=FG_MUTED)
        self._user_lbl.grid(row=21, column=0, padx=10, pady=10, sticky="s")

        # Main content area
        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        # Build all screens
        self._screens = {
            "items":     self._build_items_screen(),
            "detail":    self._build_detail_screen(),
            "checkouts": self._build_checkouts_screen(),
            "watcher":   self._build_watcher_screen(),
            "settings":  self._build_settings_screen(),
        }

    def _show_screen(self, key: str):
        for k, frame in self._screens.items():
            frame.grid_remove()
        self._screens[key].grid(row=0, column=0, sticky="nsew")
        for k, btn in self._nav_btns.items():
            btn.configure(fg_color=ACCENT if k == key else "transparent")
        if key == "items":
            self._refresh_items()
        elif key == "checkouts":
            self._refresh_checkouts()
        elif key == "detail" and self._selected_item:
            self._load_item_detail(self._selected_item)

    # ==================================================================
    # Screen: Items
    # ==================================================================
    def _build_items_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        # Toolbar
        tb = ctk.CTkFrame(f, fg_color=BG)
        tb.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(tb, text="Items", font=FONT_TITLE, text_color=FG).pack(side="left")
        _btn(tb, "New Item", self._dialog_new_item, width=100).pack(side="right", padx=4)
        _btn(tb, "Refresh", self._refresh_items, width=90,
             fg_color=CARD, hover=CARD).pack(side="right", padx=4)

        # Table
        cols = [
            ("item_id", "Item ID",    90),
            ("name",    "Name",       220),
            ("type",    "Type",       150),
            ("status",  "Status",     90),
            ("rev",     "Latest Rev", 80),
            ("creator", "Created by", 120),
        ]
        tree_f = ctk.CTkFrame(f, fg_color=BG)
        tree_f.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        tree_f.grid_columnconfigure(0, weight=1)
        tree_f.grid_rowconfigure(0, weight=1)

        self._items_tree = _make_tree(tree_f, cols, height=22)
        self._items_tree.grid(row=0, column=0, sticky="nsew")
        _tree_scroll(tree_f, self._items_tree).grid(row=0, column=1, sticky="ns")
        self._items_tree.bind("<Double-1>", self._on_item_double_click)
        return f

    def _refresh_items(self):
        for row in self._items_tree.get_children():
            self._items_tree.delete(row)
        rows = self.db.list_items()
        for i, r in enumerate(rows):
            revs = self.db.get_revisions(r["id"])
            latest_rev = revs[-1]["revision"] if revs else "-"
            tag = "even" if i % 2 == 0 else "odd"
            self._items_tree.insert("", "end", iid=r["item_id"], tags=(tag,),
                values=(r["item_id"], r["name"], r["type_name"],
                        r["status"], latest_rev, r["creator"]))

    def _on_item_double_click(self, _event):
        sel = self._items_tree.selection()
        if not sel:
            return
        item_id = sel[0]
        item = self.db.get_item(item_id)
        if item:
            self._selected_item = item
            self._load_item_detail(item)
            self._show_screen("detail")

    def _dialog_new_item(self):
        dlg = _ItemDialog(self, self.db)
        self.wait_window(dlg)
        self._refresh_items()

    # ==================================================================
    # Screen: Item Detail
    # ==================================================================
    def _build_detail_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)
        f.grid_rowconfigure(4, weight=1)

        # Header
        hdr = ctk.CTkFrame(f, fg_color=BG)
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        self._detail_title = ctk.CTkLabel(hdr, text="Item Detail",
                                          font=FONT_TITLE, text_color=FG)
        self._detail_title.pack(side="left")
        _btn(hdr, "< Back", lambda: self._show_screen("items"),
             width=80, fg_color=CARD, hover=CARD).pack(side="right", padx=4)

        # Meta info
        self._detail_meta = ctk.CTkLabel(f, text="", font=FONT_BODY,
                                         text_color=FG_MUTED, justify="left")
        self._detail_meta.grid(row=1, column=0, sticky="w", padx=16, pady=2)

        # Revision toolbar + table
        rev_tb = ctk.CTkFrame(f, fg_color=BG)
        rev_tb.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 0))
        rev_tb.grid_columnconfigure(0, weight=1)
        rev_tb.grid_rowconfigure(1, weight=1)

        rev_hdr = ctk.CTkFrame(rev_tb, fg_color=BG)
        rev_hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(rev_hdr, text="Revisions", font=FONT_BOLD,
                     text_color=FG).pack(side="left")
        _btn(rev_hdr, "New Revision", self._dialog_new_revision,
             width=110).pack(side="right", padx=2)
        _btn(rev_hdr, "Release", self._action_release_revision,
             width=80, fg_color="#2a6e2a", hover="#1e5a1e").pack(side="right", padx=2)
        _btn(rev_hdr, "Lock", self._action_lock_revision,
             width=70, fg_color="#7a4f00", hover="#5a3a00").pack(side="right", padx=2)

        rev_cols = [
            ("rev",      "Revision", 80),
            ("type",     "Type",     80),
            ("status",   "Status",   90),
            ("creator",  "Created by", 130),
            ("created",  "Created at", 160),
        ]
        rev_tree_f = ctk.CTkFrame(rev_tb, fg_color=BG)
        rev_tree_f.grid(row=1, column=0, sticky="nsew", pady=4)
        rev_tree_f.grid_columnconfigure(0, weight=1)
        self._rev_tree = _make_tree(rev_tree_f, rev_cols, height=6)
        self._rev_tree.grid(row=0, column=0, sticky="nsew")
        _tree_scroll(rev_tree_f, self._rev_tree).grid(row=0, column=1, sticky="ns")
        self._rev_tree.bind("<<TreeviewSelect>>", self._on_revision_select)

        # Dataset toolbar + table
        ds_tb = ctk.CTkFrame(f, fg_color=BG)
        ds_tb.grid(row=4, column=0, sticky="nsew", padx=12, pady=(4, 8))
        ds_tb.grid_columnconfigure(0, weight=1)
        ds_tb.grid_rowconfigure(1, weight=1)

        ds_hdr = ctk.CTkFrame(ds_tb, fg_color=BG)
        ds_hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(ds_hdr, text="Datasets", font=FONT_BOLD,
                     text_color=FG).pack(side="left")
        _btn(ds_hdr, "Add Dataset", self._dialog_add_dataset,
             width=110).pack(side="right", padx=2)
        self._ds_checkin_btn = _btn(ds_hdr, "Checkin", self._action_checkin_dataset,
                                    width=80, fg_color=CARD, hover=CARD)
        self._ds_checkin_btn.pack(side="right", padx=2)
        self._ds_checkout_btn = _btn(ds_hdr, "Checkout", self._action_checkout_dataset,
                                     width=90)
        self._ds_checkout_btn.pack(side="right", padx=2)

        self._ds_status_lbl = ctk.CTkLabel(ds_hdr, text="", font=FONT_BODY,
                                           text_color=FG_MUTED)
        self._ds_status_lbl.pack(side="right", padx=8)

        ds_cols = [
            ("id",       "ID",       40),
            ("filename", "Filename", 230),
            ("type",     "Type",     60),
            ("size",     "Size",     80),
            ("by",       "Added by", 110),
            ("checkout", "Checked out by", 160),
        ]
        ds_tree_f = ctk.CTkFrame(ds_tb, fg_color=BG)
        ds_tree_f.grid(row=1, column=0, sticky="nsew", pady=4)
        ds_tree_f.grid_columnconfigure(0, weight=1)
        self._ds_tree = _make_tree(ds_tree_f, ds_cols, height=8)
        self._ds_tree.grid(row=0, column=0, sticky="nsew")
        _tree_scroll(ds_tree_f, self._ds_tree).grid(row=0, column=1, sticky="ns")
        self._ds_tree.bind("<<TreeviewSelect>>", self._on_dataset_select)

        return f

    def _load_item_detail(self, item: dict):
        self._detail_title.configure(
            text=f"{item['item_id']} -- {item['name']}"
        )
        self._detail_meta.configure(
            text=(f"Type: {item['type_name']}   Status: {item['status']}   "
                  f"Created by: {item['creator']}   at {item['created_at']}")
        )
        # Revisions
        for row in self._rev_tree.get_children():
            self._rev_tree.delete(row)
        revs = self.db.get_revisions(item["id"])
        for i, r in enumerate(revs):
            tag = "even" if i % 2 == 0 else "odd"
            self._rev_tree.insert("", "end", iid=str(r["id"]), tags=(tag,),
                values=(r["revision"], r["revision_type"], r["status"],
                        r["creator"], r["created_at"]))
        # Clear datasets until revision is selected
        for row in self._ds_tree.get_children():
            self._ds_tree.delete(row)
        self._selected_rev = {}
        self._selected_dataset = {}

    def _on_revision_select(self, _event):
        sel = self._rev_tree.selection()
        if not sel:
            return
        rev_id = int(sel[0])
        revs = self.db.get_revisions(self._selected_item.get("id", 0))
        rev = next((r for r in revs if r["id"] == rev_id), None)
        if rev:
            self._selected_rev = rev
            self._refresh_datasets(rev_id)

    def _refresh_datasets(self, revision_id: int):
        for row in self._ds_tree.get_children():
            self._ds_tree.delete(row)
        datasets = self.db.get_datasets(revision_id)
        for i, d in enumerate(datasets):
            size_str = f"{d['file_size']//1024} KB" if d["file_size"] else "0 KB"
            who = d.get("checked_out_by") or "-"
            tag = "even" if i % 2 == 0 else "odd"
            self._ds_tree.insert("", "end", iid=str(d["id"]), tags=(tag,),
                values=(d["id"], d["filename"], d["file_type"], size_str,
                        d["adder"], who))
        self._selected_dataset = {}
        self._update_checkout_ui(None)

    def _on_dataset_select(self, _event):
        sel = self._ds_tree.selection()
        if not sel:
            return
        ds_id = int(sel[0])
        if not self._selected_rev:
            return
        datasets = self.db.get_datasets(self._selected_rev["id"])
        ds = next((d for d in datasets if d["id"] == ds_id), None)
        if ds:
            self._selected_dataset = ds
            self._update_checkout_ui(ds)

    def _update_checkout_ui(self, ds):
        if not ds:
            self._ds_status_lbl.configure(text="", text_color=FG_MUTED)
            self._ds_checkout_btn.configure(state="normal")
            self._ds_checkin_btn.configure(state="disabled")
            return
        who = ds.get("checked_out_by")
        if not who:
            self._ds_status_lbl.configure(text="Available", text_color=OK_FG)
            self._ds_checkout_btn.configure(state="normal")
            self._ds_checkin_btn.configure(state="disabled")
        elif who == self.username:
            self._ds_status_lbl.configure(
                text=f"Checked out by you  ({ds.get('station_name','')})",
                text_color=WARN_FG)
            self._ds_checkout_btn.configure(state="disabled")
            self._ds_checkin_btn.configure(state="normal")
        else:
            self._ds_status_lbl.configure(
                text=f"Locked by {who} since {ds.get('checked_out_at','')}",
                text_color=ERR_FG)
            self._ds_checkout_btn.configure(state="disabled")
            self._ds_checkin_btn.configure(state="disabled")

    def _action_checkout_dataset(self):
        ds = self._selected_dataset
        if not ds:
            messagebox.showwarning("Checkout", "Select a dataset first.")
            return
        try:
            checkout_file(
                Path(ds["stored_path"]), self.username, self.db,
                station=socket.gethostname(),
                dataset_id=ds["id"],
                item_id=self._selected_item.get("item_id", ""),
                revision=self._selected_rev.get("revision", ""),
            )
            messagebox.showinfo("Checkout", f"Checked out '{ds['filename']}' to you.")
            self._refresh_datasets(self._selected_rev["id"])
        except (CheckoutError, Exception) as e:
            messagebox.showerror("Checkout Error", str(e))

    def _action_checkin_dataset(self):
        ds = self._selected_dataset
        if not ds:
            messagebox.showwarning("Checkin", "Select a dataset first.")
            return
        try:
            checkin_file(Path(ds["stored_path"]), self.username, self.db)
            messagebox.showinfo("Checkin", f"Checked in '{ds['filename']}'.")
            self._refresh_datasets(self._selected_rev["id"])
        except (CheckoutError, Exception) as e:
            messagebox.showerror("Checkin Error", str(e))

    def _dialog_new_revision(self):
        if not self._selected_item:
            messagebox.showwarning("New Revision", "Open an item first.")
            return
        dlg = _RevisionDialog(self, self.db, self._selected_item)
        self.wait_window(dlg)
        self._load_item_detail(self._selected_item)

    def _action_release_revision(self):
        if not self._selected_rev:
            messagebox.showwarning("Release", "Select a revision first.")
            return
        rev = self._selected_rev
        if not messagebox.askyesno("Release Revision",
                                   f"Release {self._selected_item['item_id']}/{rev['revision']}?"):
            return
        self.db.release_revision(rev["id"], self.username)
        self.db.write_audit("release", "item_revision", str(rev["id"]), self.username,
                            f"Released {self._selected_item['item_id']}/{rev['revision']}")
        self._load_item_detail(self._selected_item)

    def _action_lock_revision(self):
        if not self._selected_rev:
            messagebox.showwarning("Lock", "Select a revision first.")
            return
        rev = self._selected_rev
        if not messagebox.askyesno("Lock Revision",
                                   f"Lock {self._selected_item['item_id']}/{rev['revision']}?"):
            return
        self.db.lock_revision(rev["id"], self.username)
        self.db.write_audit("lock", "item_revision", str(rev["id"]), self.username,
                            f"Locked {self._selected_item['item_id']}/{rev['revision']}")
        self._load_item_detail(self._selected_item)

    def _dialog_add_dataset(self):
        if not self._selected_rev:
            messagebox.showwarning("Add Dataset", "Select a revision first.")
            return
        filepath = filedialog.askopenfilename(title="Select file to add as dataset")
        if not filepath:
            return
        p = Path(filepath)
        size = p.stat().st_size if p.exists() else 0
        ds_id = self.db.add_dataset(
            self._selected_rev["id"], p.name, p.suffix.lower(),
            str(p), size, self.username,
        )
        self.db.write_audit("add_dataset", "dataset", str(ds_id), self.username,
                            f"Added {p.name}")
        self._refresh_datasets(self._selected_rev["id"])

    # ==================================================================
    # Screen: Checkouts
    # ==================================================================
    def _build_checkouts_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        tb = ctk.CTkFrame(f, fg_color=BG)
        tb.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(tb, text="Active Checkouts", font=FONT_TITLE,
                     text_color=FG).pack(side="left")
        _btn(tb, "Force Checkin", self._action_force_checkin,
             width=120, fg_color="#7a0000", hover="#5a0000").pack(side="right", padx=4)
        _btn(tb, "Checkin Mine", self._action_checkin_mine,
             width=110).pack(side="right", padx=4)
        _btn(tb, "Refresh", self._refresh_checkouts, width=90,
             fg_color=CARD, hover=CARD).pack(side="right", padx=4)

        cols = [
            ("who",       "Checked out by", 140),
            ("item_rev",  "Item / Rev",      130),
            ("filename",  "Filename",        220),
            ("station",   "Station",         120),
            ("at",        "Since",           160),
        ]
        tree_f = ctk.CTkFrame(f, fg_color=BG)
        tree_f.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        tree_f.grid_columnconfigure(0, weight=1)
        tree_f.grid_rowconfigure(0, weight=1)
        self._co_tree = _make_tree(tree_f, cols, height=22)
        self._co_tree.grid(row=0, column=0, sticky="nsew")
        _tree_scroll(tree_f, self._co_tree).grid(row=0, column=1, sticky="ns")
        return f

    def _refresh_checkouts(self):
        for row in self._co_tree.get_children():
            self._co_tree.delete(row)
        rows = self.db.list_checkouts()
        for i, r in enumerate(rows):
            item_rev = f"{r.get('item_id','?')}/{r.get('revision','?')}"
            tag = "even" if i % 2 == 0 else "odd"
            self._co_tree.insert("", "end", iid=str(r["id"]), tags=(tag,),
                values=(r["who"], item_rev, r["filename"],
                        r.get("station_name", ""), r["checked_out_at"]))

    def _action_checkin_mine(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Checkin", "Select a checkout row first.")
            return
        co_id = int(sel[0])
        rows = self.db.list_checkouts()
        row = next((r for r in rows if r["id"] == co_id), None)
        if not row:
            return
        if row["who"] != self.username:
            messagebox.showerror("Checkin", f"That file is checked out by {row['who']}.")
            return
        try:
            checkin_file(Path(row["stored_path"]), self.username, self.db)
            self._refresh_checkouts()
        except Exception as e:
            messagebox.showerror("Checkin Error", str(e))

    def _action_force_checkin(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Force Checkin", "Select a checkout row first.")
            return
        co_id = int(sel[0])
        rows = self.db.list_checkouts()
        row = next((r for r in rows if r["id"] == co_id), None)
        if not row:
            return
        if not messagebox.askyesno("Force Checkin",
                                   f"Force checkin '{row['filename']}' "
                                   f"(checked out by {row['who']})?"):
            return
        # Force: delete checkout record directly, remove lock file
        try:
            from pathlib import Path as _P
            from .checkout import _lock_path
            lock = _lock_path(_P(row["stored_path"]))
            if lock.exists():
                lock.unlink()
            self.db.checkin_dataset(row["dataset_id"], row["who"])
            self.db.write_audit("force_checkin", "dataset", str(row["dataset_id"]),
                                self.username,
                                f"Force checkin of {row['filename']} from {row['who']}")
            self._refresh_checkouts()
        except Exception as e:
            messagebox.showerror("Force Checkin Error", str(e))

    # ==================================================================
    # Screen: Watcher
    # ==================================================================
    def _build_watcher_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        tb = ctk.CTkFrame(f, fg_color=BG)
        tb.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(tb, text="Watcher", font=FONT_TITLE, text_color=FG).pack(side="left")
        self._watcher_status_lbl = ctk.CTkLabel(tb, text="Stopped",
                                                 font=FONT_BODY, text_color=ERR_FG)
        self._watcher_status_lbl.pack(side="left", padx=12)
        self._watcher_stop_btn = _btn(tb, "Stop", self._stop_watcher, width=80,
                                      fg_color="#7a0000", hover="#5a0000", state="disabled")
        self._watcher_stop_btn.pack(side="right", padx=4)
        self._watcher_start_btn = _btn(tb, "Start Watching", self._start_watcher, width=130)
        self._watcher_start_btn.pack(side="right", padx=4)

        # Watch path info
        paths_f = ctk.CTkFrame(f, fg_color=CARD, corner_radius=6)
        paths_f.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        watch_configs = config.get_watch_configs()
        for wc in watch_configs:
            txt = f"  [{wc['name']}]  {wc['path']}  ({', '.join(wc['extensions'])})"
            ctk.CTkLabel(paths_f, text=txt, font=FONT_MONO,
                         text_color=FG_MUTED).pack(anchor="w", padx=8, pady=2)

        # Log area
        self._watcher_log = ctk.CTkTextbox(f, font=FONT_MONO,
                                           fg_color=CARD, text_color=FG,
                                           state="disabled")
        self._watcher_log.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 12))

        # Set up logging handler
        handler = GUILogHandler(self._log_q)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                                               "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        return f

    def _start_watcher(self):
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        from .watcher import FileWatcher
        wcs = config.get_watch_configs()

        def run():
            self._watcher_obj = FileWatcher(wcs, db_path=config.DB_PATH)
            self._watcher_obj.start()

        self._watcher_thread = threading.Thread(target=run, daemon=True)
        self._watcher_thread.start()
        self._watcher_status_lbl.configure(text="Watching", text_color=OK_FG)
        self._watcher_start_btn.configure(state="disabled")
        self._watcher_stop_btn.configure(state="normal")

    def _stop_watcher(self):
        if self._watcher_obj:
            self._watcher_obj.stop()
            self._watcher_obj = None
        self._watcher_status_lbl.configure(text="Stopped", text_color=ERR_FG)
        self._watcher_start_btn.configure(state="normal")
        self._watcher_stop_btn.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                msg, is_warn = self._log_q.get_nowait()
                self._watcher_log.configure(state="normal")
                self._watcher_log.insert("end", msg + "\n")
                self._watcher_log.see("end")
                self._watcher_log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(300, self._poll_log_queue)

    # ==================================================================
    # Screen: Settings
    # ==================================================================
    def _build_settings_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(f, text="Settings", font=FONT_TITLE,
                     text_color=FG).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8)
        card.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        card.grid_columnconfigure(1, weight=1)

        def row(lbl, val, r):
            ctk.CTkLabel(card, text=lbl, font=FONT_BOLD,
                         text_color=FG_MUTED).grid(row=r, column=0, sticky="w", padx=12, pady=4)
            ctk.CTkLabel(card, text=str(val), font=FONT_BODY,
                         text_color=FG).grid(row=r, column=1, sticky="w", padx=12, pady=4)

        c = config.get_config()
        row("Database path:", c["DB_PATH"], 0)
        row("Backup path:",   c["BACKUP_PATH"], 1)
        row("Max versions:",  c["MAX_VERSIONS"], 2)

        ctk.CTkLabel(card, text="Watch configs:", font=FONT_BOLD,
                     text_color=FG_MUTED).grid(row=3, column=0, sticky="nw", padx=12, pady=4)
        for i, wc in enumerate(c["WATCH_CONFIGS"]):
            txt = f"[{wc['name']}]  {wc['path']}  ({', '.join(wc['extensions'])})"
            ctk.CTkLabel(card, text=txt, font=FONT_MONO,
                         text_color=FG).grid(row=3+i, column=1, sticky="w", padx=12, pady=2)

        # Users (admin view)
        ctk.CTkLabel(f, text="Users", font=FONT_BOLD,
                     text_color=FG).grid(row=2, column=0, sticky="w", padx=16, pady=(16, 4))

        users_f = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8)
        users_f.grid(row=3, column=0, sticky="ew", padx=16, pady=4)
        users_f.grid_columnconfigure(0, weight=1)

        user_cols = [("username", "Username", 160), ("role", "Role", 100),
                     ("created", "Created", 160)]
        self._users_tree = _make_tree(users_f, user_cols, height=6)
        self._users_tree.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        btn_row = ctk.CTkFrame(users_f, fg_color=CARD)
        btn_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        _btn(btn_row, "Add User", self._dialog_add_user, width=100).pack(side="left", padx=4)
        _btn(btn_row, "Refresh", self._refresh_users, width=90,
             fg_color=CARD, hover="#3a3a5e").pack(side="left", padx=4)

        self._refresh_users()
        return f

    def _refresh_users(self):
        for row in self._users_tree.get_children():
            self._users_tree.delete(row)
        for i, u in enumerate(self.db.list_users()):
            tag = "even" if i % 2 == 0 else "odd"
            self._users_tree.insert("", "end", tags=(tag,),
                values=(u["username"], u["role"], u["created_at"]))

    def _dialog_add_user(self):
        uname = simpledialog.askstring("Add User", "Username:", parent=self)
        if not uname:
            return
        role = simpledialog.askstring("Add User", "Role (admin/user/readonly):",
                                      initialvalue="user", parent=self)
        if role not in ("admin", "user", "readonly"):
            role = "user"
        self.db.upsert_user(uname, role)
        self._refresh_users()


# ------------------------------------------------------------------
# Dialogs
# ------------------------------------------------------------------
class _ItemDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: Database):
        super().__init__(parent)
        self.db = db
        self.title("New Item")
        self.geometry("420x280")
        self.configure(fg_color=BG)
        self.grab_set()

        ctk.CTkLabel(self, text="New Item", font=FONT_TITLE,
                     text_color=FG).pack(pady=(16, 8))

        frm = ctk.CTkFrame(self, fg_color=BG)
        frm.pack(fill="x", padx=20)

        ctk.CTkLabel(frm, text="Name:", font=FONT_BODY, text_color=FG).grid(
            row=0, column=0, sticky="w", pady=4)
        self._name = ctk.CTkEntry(frm, width=260, font=FONT_BODY)
        self._name.grid(row=0, column=1, pady=4, padx=8)

        ctk.CTkLabel(frm, text="Type:", font=FONT_BODY, text_color=FG).grid(
            row=1, column=0, sticky="w", pady=4)
        types = [t["name"] for t in db.list_item_types()]
        self._type_var = ctk.StringVar(value=types[0] if types else "")
        self._type_menu = ctk.CTkOptionMenu(frm, values=types, variable=self._type_var,
                                            width=260, font=FONT_BODY)
        self._type_menu.grid(row=1, column=1, pady=4, padx=8)

        ctk.CTkLabel(frm, text="Description:", font=FONT_BODY, text_color=FG).grid(
            row=2, column=0, sticky="w", pady=4)
        self._desc = ctk.CTkEntry(frm, width=260, font=FONT_BODY)
        self._desc.grid(row=2, column=1, pady=4, padx=8)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.pack(pady=16)
        _btn(btn_row, "Create", self._on_create, width=100).pack(side="left", padx=8)
        _btn(btn_row, "Cancel", self.destroy, width=80,
             fg_color=CARD, hover=CARD).pack(side="left", padx=8)

    def _on_create(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning("Validation", "Name is required.", parent=self)
            return
        item_type_name = self._type_var.get()
        itype = self.db.get_item_type_by_name(item_type_name)
        if not itype:
            return
        new_id = self.db.next_item_id()
        username = getpass.getuser()
        self.db.create_item(new_id, name, self._desc.get().strip(),
                            itype["id"], username)
        self.db.write_audit("create", "item", new_id, username, f"Created: {name}")
        self.destroy()


class _RevisionDialog(ctk.CTkToplevel):
    def __init__(self, parent, db: Database, item: dict):
        super().__init__(parent)
        self.db = db
        self.item = item
        self.title(f"New Revision -- {item['item_id']}")
        self.geometry("360x200")
        self.configure(fg_color=BG)
        self.grab_set()

        ctk.CTkLabel(self, text=f"New Revision for {item['item_id']}",
                     font=FONT_TITLE, text_color=FG).pack(pady=(16, 8))

        frm = ctk.CTkFrame(self, fg_color=BG)
        frm.pack(fill="x", padx=20)
        ctk.CTkLabel(frm, text="Type:", font=FONT_BODY, text_color=FG).grid(
            row=0, column=0, sticky="w", pady=4)
        self._type_var = ctk.StringVar(value="alpha")
        ctk.CTkOptionMenu(frm, values=["alpha", "numeric"],
                          variable=self._type_var, width=180,
                          font=FONT_BODY).grid(row=0, column=1, padx=8)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.pack(pady=16)
        _btn(btn_row, "Create", self._on_create, width=100).pack(side="left", padx=8)
        _btn(btn_row, "Cancel", self.destroy, width=80,
             fg_color=CARD, hover=CARD).pack(side="left", padx=8)

    def _on_create(self):
        rev_type = self._type_var.get()
        username = getpass.getuser()
        rev_label = self.db.next_revision(self.item["id"], rev_type)
        pk = self.db.create_revision(self.item["id"], rev_label, rev_type, username)
        self.db.write_audit("create_revision", "item_revision", str(pk), username,
                            f"{self.item['item_id']} rev {rev_label}")
        self.destroy()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def launch():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    launch()
