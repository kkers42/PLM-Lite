"""PLM Lite v2.0 -- Desktop GUI (CustomTkinter, dark theme, web-app style layout).

6 screens via sidebar navigation (grouped):
  LIBRARY
    Parts       -- item list (left) + tabbed detail: Details/Attributes/Documents (right)
    Structure   -- item list (left) + BOM treeview (right)
    Documents   -- all datasets flat view with type/filename filters
  SYSTEM
    Watcher     -- status banner, start/stop, live log feed
    Checkouts   -- active checkouts table with checkin/force-checkin
    Settings    -- watch paths config, user management
"""

import getpass
import logging
import queue
import socket
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk

from . import config
from .checkout import CheckoutError, checkin_file, checkout_file
from .database import Database

# ------------------------------------------------------------------
# Palette
# ------------------------------------------------------------------
BG          = "#1e1e2e"
SIDEBAR_BG  = "#181825"
CARD        = "#252535"
CARD2       = "#313244"
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
CO_MINE_BG  = "#1e3a1e"
CO_OTHER_BG = "#3a1e1e"

FONT_BODY  = ("Segoe UI", 12)
FONT_BOLD  = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_MONO  = ("Consolas", 11)
FONT_SMALL = ("Segoe UI", 10)

STATUS_COLOR = {
    "in_work":  "#94a3b8",
    "released": OK_FG,
    "locked":   WARN_FG,
    "obsolete": ERR_FG,
}

# (key, icon, label, group)
_NAV_ITEMS = [
    ("parts",     "\u22ef", "Parts",     "LIBRARY"),
    ("structure", "\u25a4", "Structure", "LIBRARY"),
    ("documents", "\u25a1", "Documents", "LIBRARY"),
    ("watcher",   "\u25b6", "Watcher",   "SYSTEM"),
    ("checkouts", "\u2714", "Checkouts", "SYSTEM"),
    ("settings",  "\u2699", "Settings",  "SYSTEM"),
]

_VERSION = "2.0.1"

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
# Treeview / widget helpers
# ------------------------------------------------------------------

_TREE_STYLE_DONE = False


def _apply_tree_style():
    global _TREE_STYLE_DONE
    if _TREE_STYLE_DONE:
        return
    s = ttk.Style()
    s.theme_use("clam")
    s.configure("Dark.Treeview",
                background=BG, foreground=FG, fieldbackground=BG,
                rowheight=26, font=FONT_BODY)
    s.configure("Dark.Treeview.Heading",
                background=TREE_HDR, foreground=FG, font=FONT_BOLD, relief="flat")
    s.map("Dark.Treeview",
          background=[("selected", ACCENT)],
          foreground=[("selected", "#ffffff")])
    _TREE_STYLE_DONE = True


def _make_tree(parent, columns: list, height=14, show="headings") -> ttk.Treeview:
    _apply_tree_style()
    col_ids = [c[0] for c in columns]
    tree = ttk.Treeview(parent, style="Dark.Treeview",
                        columns=col_ids, show=show, height=height)
    for cid, label, width in columns:
        tree.heading(cid, text=label)
        tree.column(cid, width=width, anchor="w")
    if show != "headings":
        tree.heading("#0", text="")
        tree.column("#0", width=20, stretch=False)
    tree.tag_configure("even",     background=ROW_EVEN)
    tree.tag_configure("odd",      background=ROW_ODD)
    tree.tag_configure("co_mine",  background=CO_MINE_BG)
    tree.tag_configure("co_other", background=CO_OTHER_BG)
    tree.tag_configure("released", foreground=OK_FG,   background=ROW_EVEN)
    tree.tag_configure("locked",   foreground=WARN_FG, background=ROW_ODD)
    tree.tag_configure("obsolete", foreground=ERR_FG,  background=ROW_ODD)
    tree.tag_configure("rev_node", foreground="#89b4fa")
    tree.tag_configure("ds_node",  foreground=FG_MUTED)
    return tree


def _attach_vscroll(parent: tk.Frame, tree: ttk.Treeview) -> ttk.Scrollbar:
    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    return sb


def _btn(parent, text, cmd, width=130, fg_color=ACCENT, hover=ACCENT_H, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, width=width,
                         fg_color=fg_color, hover_color=hover, font=FONT_BODY, **kw)


def _lbl(parent, text, font=FONT_BODY, color=FG, **kw):
    return ctk.CTkLabel(parent, text=text, font=font, text_color=color, **kw)


# ------------------------------------------------------------------
# Main application window
# ------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"PLM Lite v{_VERSION}")
        self.geometry("1300x820")
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
        self._revs_cache: list = []
        self._datasets_cache: list = []

        self._nav_btns: dict = {}   # key -> (tk.Frame bar, CTkButton btn)
        self._screens: dict = {}

        self._build_layout()
        self._show_screen("parts")
        self.after(500, self._poll_log_queue)

    # ==================================================================
    # Layout skeleton
    # ==================================================================

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- Sidebar ----
        sidebar = ctk.CTkFrame(self, width=220, fg_color=SIDEBAR_BG, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(50, weight=1)

        _lbl(sidebar, "PLM Lite", font=("Segoe UI", 18, "bold"), color=ACCENT
             ).grid(row=0, column=0, padx=16, pady=(20, 2), sticky="w")
        _lbl(sidebar, f"v{_VERSION}", font=FONT_SMALL, color=FG_MUTED
             ).grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")

        row_idx = 2
        prev_group = None
        for key, icon, label, group in _NAV_ITEMS:
            if group != prev_group:
                _lbl(sidebar, group, font=("Segoe UI", 9, "bold"), color=FG_MUTED
                     ).grid(row=row_idx, column=0, padx=16, pady=(12, 2), sticky="w")
                row_idx += 1
                prev_group = group
            self._make_nav_btn(sidebar, key, icon, label, row_idx)
            row_idx += 1

        _lbl(sidebar, f"  {self.username}", font=FONT_SMALL, color=FG_MUTED, anchor="w"
             ).grid(row=51, column=0, padx=8, pady=12, sticky="ew")

        # ---- Content area ----
        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._screens = {
            "parts":     self._build_parts_screen(),
            "structure": self._build_structure_screen(),
            "documents": self._build_documents_screen(),
            "watcher":   self._build_watcher_screen(),
            "checkouts": self._build_checkouts_screen(),
            "settings":  self._build_settings_screen(),
        }

    def _make_nav_btn(self, sidebar, key: str, icon: str, label: str, row: int):
        """Sidebar nav item: 4 px accent-bar strip + full-width button."""
        item_frame = tk.Frame(sidebar, bg=SIDEBAR_BG, height=38)
        item_frame.grid(row=row, column=0, sticky="ew", pady=1)
        item_frame.grid_columnconfigure(1, weight=1)
        item_frame.grid_propagate(False)

        bar = tk.Frame(item_frame, width=4, bg=SIDEBAR_BG)
        bar.grid(row=0, column=0, sticky="ns")

        btn = ctk.CTkButton(
            item_frame,
            text=f"  {icon}  {label}",
            anchor="w",
            fg_color="transparent",
            hover_color=CARD2,
            text_color=FG_MUTED,
            font=FONT_BODY,
            corner_radius=0,
            height=36,
            command=lambda k=key: self._show_screen(k),
        )
        btn.grid(row=0, column=1, sticky="ew")
        self._nav_btns[key] = (bar, btn)

    def _show_screen(self, key: str):
        for k, (bar, btn) in self._nav_btns.items():
            if k == key:
                bar.configure(bg=ACCENT)
                btn.configure(text_color="#ffffff", fg_color=CARD)
            else:
                bar.configure(bg=SIDEBAR_BG)
                btn.configure(text_color=FG_MUTED, fg_color="transparent")
        for screen in self._screens.values():
            screen.grid_remove()
        self._screens[key].grid(row=0, column=0, sticky="nsew")
        if key == "parts":
            self._refresh_parts_list()
        elif key == "structure":
            self._refresh_struct_list()
        elif key == "documents":
            self._refresh_documents()
        elif key == "checkouts":
            self._refresh_checkouts()

    # ==================================================================
    # Screen: Parts
    # ==================================================================

    def _build_parts_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        self._screen_title_bar(f, "Parts", row=0)

        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=BG,
                              sashwidth=5, sashrelief="flat", bd=0, relief="flat")
        pane.grid(row=1, column=0, sticky="nsew")

        # ---- Left: item list ----
        left = tk.Frame(pane, bg=BG)
        pane.add(left, minsize=200, width=370)

        ltb = tk.Frame(left, bg=BG)
        ltb.pack(fill="x", padx=8, pady=(8, 4))
        _btn(ltb, "+ New Item", self._dialog_new_item, width=110).pack(side="left", padx=2)
        _btn(ltb, "Refresh", self._refresh_parts_list, width=80,
             fg_color=CARD2, hover="#3a3a5e").pack(side="left", padx=2)
        self._parts_search_var = tk.StringVar()
        self._parts_search_var.trace_add("write", lambda *_: self._refresh_parts_list())
        ctk.CTkEntry(ltb, textvariable=self._parts_search_var,
                     placeholder_text="Search...", width=110,
                     font=FONT_BODY, fg_color=CARD2).pack(side="right", padx=4)

        list_f = tk.Frame(left, bg=BG)
        list_f.pack(fill="both", expand=True, padx=8, pady=4)
        pcols = [
            ("item_id", "Item ID",  80),
            ("name",    "Name",    155),
            ("type",    "Type",     80),
            ("status",  "Status",   70),
            ("rev",     "Rev",      40),
        ]
        self._parts_tree = _make_tree(list_f, pcols, height=30)
        sb = _attach_vscroll(list_f, self._parts_tree)
        self._parts_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._parts_tree.bind("<<TreeviewSelect>>", self._on_parts_select)

        # ---- Right: tabbed detail ----
        right = tk.Frame(pane, bg=BG)
        pane.add(right, minsize=400)
        self._build_detail_pane(right)

        return f

    def _refresh_parts_list(self):
        query = self._parts_search_var.get().lower() if hasattr(self, "_parts_search_var") else ""
        for row in self._parts_tree.get_children():
            self._parts_tree.delete(row)
        i = 0
        for r in self.db.list_items():
            if query and query not in r["item_id"].lower() and query not in r["name"].lower():
                continue
            revs = self.db.get_revisions(r["id"])
            latest_rev = revs[-1]["revision"] if revs else "-"
            status = r["status"]
            if status in ("released", "locked", "obsolete"):
                tag = status
            else:
                tag = "even" if i % 2 == 0 else "odd"
            self._parts_tree.insert("", "end", iid=r["item_id"], tags=(tag,),
                values=(r["item_id"], r["name"], r["type_name"], status, latest_rev))
            i += 1

    def _on_parts_select(self, _event):
        sel = self._parts_tree.selection()
        if not sel:
            return
        item = self.db.get_item(sel[0])
        if item:
            self._selected_item = item
            self._load_item_detail(item)

    # ---- Detail pane (right side of Parts screen) ----

    def _build_detail_pane(self, parent: tk.Frame):
        # Header card
        hdr = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
        hdr.pack(fill="x", padx=12, pady=(12, 4))
        hdr.grid_columnconfigure(1, weight=1)

        self._detail_id_lbl = ctk.CTkLabel(hdr, text="—",
                                           font=("Segoe UI", 18, "bold"),
                                           text_color=ACCENT)
        self._detail_id_lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))

        self._detail_name_lbl = _lbl(hdr, "Select an item", font=FONT_TITLE)
        self._detail_name_lbl.grid(row=0, column=1, sticky="w", padx=8, pady=(10, 2))

        self._detail_meta_lbl = _lbl(hdr, "", font=FONT_SMALL, color=FG_MUTED)
        self._detail_meta_lbl.grid(row=1, column=0, columnspan=3, sticky="w",
                                   padx=12, pady=(0, 4))

        act_row = ctk.CTkFrame(hdr, fg_color=CARD)
        act_row.grid(row=2, column=0, columnspan=3, sticky="e", padx=12, pady=(0, 10))
        _btn(act_row, "Release Rev", self._action_release_revision,
             width=100, fg_color="#2a6e2a", hover="#1e5a1e").pack(side="left", padx=3)
        _btn(act_row, "Lock Rev", self._action_lock_revision,
             width=85, fg_color="#7a4f00", hover="#5a3a00").pack(side="left", padx=3)
        _btn(act_row, "New Revision", self._dialog_new_revision, width=115).pack(side="left", padx=3)

        # Revision selector
        rev_row = ctk.CTkFrame(parent, fg_color=BG)
        rev_row.pack(fill="x", padx=12, pady=6)
        _lbl(rev_row, "Revision:", font=FONT_BOLD).pack(side="left")
        self._rev_combo = ctk.CTkOptionMenu(
            rev_row, values=["—"], width=220, font=FONT_BODY,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_H,
            command=self._on_rev_combo_change)
        self._rev_combo.pack(side="left", padx=8)

        # Tab view
        self._detail_tabs = ctk.CTkTabview(
            parent, fg_color=CARD, corner_radius=8,
            segmented_button_fg_color=CARD2,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_color=CARD2,
            segmented_button_unselected_hover_color=CARD2)
        self._detail_tabs.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._detail_tabs.add("DETAILS")
        self._detail_tabs.add("ATTRIBUTES")
        self._detail_tabs.add("DOCUMENTS")

        self._build_details_tab(self._detail_tabs.tab("DETAILS"))
        self._build_attributes_tab(self._detail_tabs.tab("ATTRIBUTES"))
        self._build_documents_tab(self._detail_tabs.tab("DOCUMENTS"))

    def _build_details_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        tb = ctk.CTkFrame(parent, fg_color=CARD)
        tb.grid(row=0, column=0, sticky="ew", pady=(4, 2))
        self._ds_status_lbl = _lbl(tb, "", color=FG_MUTED)
        self._ds_status_lbl.pack(side="left", padx=8)
        _btn(tb, "Add Dataset", self._dialog_add_dataset, width=110).pack(side="right", padx=3)
        self._ds_checkin_btn = _btn(tb, "Checkin", self._action_checkin_dataset,
                                    width=80, fg_color=CARD2, hover=CARD2)
        self._ds_checkin_btn.pack(side="right", padx=3)
        self._ds_checkout_btn = _btn(tb, "Checkout", self._action_checkout_dataset, width=90)
        self._ds_checkout_btn.pack(side="right", padx=3)
        _btn(tb, "Open Folder", self._action_open_folder,
             width=105, fg_color=CARD2, hover="#3a3a5e").pack(side="right", padx=3)

        ds_f = tk.Frame(parent, bg=BG)
        ds_f.grid(row=1, column=0, sticky="nsew", pady=4)
        ds_cols = [
            ("filename", "Filename",       195),
            ("type",     "Type",            55),
            ("size",     "Size",            65),
            ("by",       "Added by",        95),
            ("checkout", "Checked out by", 145),
            ("since",    "Since",          120),
        ]
        self._ds_tree = _make_tree(ds_f, ds_cols, height=14)
        sb = _attach_vscroll(ds_f, self._ds_tree)
        self._ds_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._ds_tree.bind("<<TreeviewSelect>>", self._on_dataset_select)

    def _build_attributes_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD2, corner_radius=6)
        card.pack(fill="x", padx=8, pady=8)
        card.grid_columnconfigure(1, weight=1)
        self._attr_labels: dict = {}
        for i, attr in enumerate(["Part Number", "Name", "Description", "Type",
                                   "Status", "Created by", "Created at"]):
            _lbl(card, attr + ":", font=FONT_BOLD, color=FG_MUTED).grid(
                row=i, column=0, sticky="w", padx=(12, 8), pady=5)
            v = _lbl(card, "—")
            v.grid(row=i, column=1, sticky="w", padx=8, pady=5)
            self._attr_labels[attr] = v

    def _build_documents_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        tb = ctk.CTkFrame(parent, fg_color=CARD)
        tb.grid(row=0, column=0, sticky="ew", pady=(4, 2))
        _btn(tb, "Add Document", self._dialog_add_dataset, width=120).pack(side="right", padx=3)

        doc_f = tk.Frame(parent, bg=BG)
        doc_f.grid(row=1, column=0, sticky="nsew", pady=4)
        doc_cols = [
            ("filename", "Filename",       195),
            ("type",     "Type",            55),
            ("size",     "Size",            65),
            ("by",       "Added by",        95),
            ("checkout", "Checked out by", 145),
        ]
        self._doc_tab_tree = _make_tree(doc_f, doc_cols, height=14)
        sb = _attach_vscroll(doc_f, self._doc_tab_tree)
        self._doc_tab_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _load_item_detail(self, item: dict):
        self._detail_id_lbl.configure(text=item["item_id"])
        self._detail_name_lbl.configure(text=item["name"])
        sc = STATUS_COLOR.get(item["status"], FG_MUTED)
        self._detail_meta_lbl.configure(
            text=(f"Type: {item['type_name']}   Status: {item['status']}   "
                  f"Created by: {item['creator']}   at {item['created_at']}"),
            text_color=sc)

        revs = self.db.get_revisions(item["id"])
        self._revs_cache = revs
        rev_labels = [f"{r['revision']}  ({r['status']})" for r in revs]
        if rev_labels:
            self._rev_combo.configure(values=rev_labels)
            self._rev_combo.set(rev_labels[-1])
            self._selected_rev = revs[-1]
            self._refresh_datasets(revs[-1]["id"])
        else:
            self._rev_combo.configure(values=["No revisions"])
            self._rev_combo.set("No revisions")
            self._selected_rev = {}
            self._clear_datasets()

        self._attr_labels["Part Number"].configure(text=item["item_id"])
        self._attr_labels["Name"].configure(text=item["name"])
        self._attr_labels["Description"].configure(text=item.get("description") or "—")
        self._attr_labels["Type"].configure(text=item["type_name"])
        self._attr_labels["Status"].configure(
            text=item["status"], text_color=STATUS_COLOR.get(item["status"], FG))
        self._attr_labels["Created by"].configure(text=item["creator"])
        self._attr_labels["Created at"].configure(text=item["created_at"])

    def _on_rev_combo_change(self, choice: str):
        for r in self._revs_cache:
            if f"{r['revision']}  ({r['status']})" == choice:
                self._selected_rev = r
                self._refresh_datasets(r["id"])
                return

    def _refresh_datasets(self, revision_id: int):
        self._clear_datasets()
        datasets = self.db.get_datasets(revision_id)
        self._datasets_cache = datasets
        doc_exts = {".pdf", ".docx", ".xlsx", ".txt", ".pptx", ".doc", ".xls", ".csv"}
        for i, d in enumerate(datasets):
            size_str = f"{d['file_size'] // 1024} KB" if d["file_size"] else "0 KB"
            who = d.get("checked_out_by") or ""
            since = d.get("checked_out_at") or "—"
            if who == self.username:
                tag = "co_mine"
            elif who:
                tag = "co_other"
            else:
                tag = "even" if i % 2 == 0 else "odd"
            self._ds_tree.insert("", "end", iid=str(d["id"]), tags=(tag,),
                values=(d["filename"], d["file_type"], size_str,
                        d["adder"], who or "—", since))
            ext = Path(d["filename"]).suffix.lower()
            if ext in doc_exts:
                self._doc_tab_tree.insert("", "end", iid=f"doc_{d['id']}", tags=(tag,),
                    values=(d["filename"], d["file_type"], size_str, d["adder"], who or "—"))
        self._selected_dataset = {}
        self._update_checkout_ui(None)

    def _clear_datasets(self):
        for row in self._ds_tree.get_children():
            self._ds_tree.delete(row)
        for row in self._doc_tab_tree.get_children():
            self._doc_tab_tree.delete(row)
        self._datasets_cache = []

    def _on_dataset_select(self, _event):
        sel = self._ds_tree.selection()
        if not sel:
            return
        ds_id = int(sel[0])
        ds = next((d for d in self._datasets_cache if d["id"] == ds_id), None)
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
                text=f"Checked out by you  ({ds.get('station_name', '')})",
                text_color=WARN_FG)
            self._ds_checkout_btn.configure(state="disabled")
            self._ds_checkin_btn.configure(state="normal")
        else:
            self._ds_status_lbl.configure(
                text=f"Locked by {who} since {ds.get('checked_out_at', '')}",
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

    def _action_open_folder(self):
        ds = self._selected_dataset
        if not ds:
            messagebox.showwarning("Open Folder", "Select a dataset first.")
            return
        folder = Path(ds.get("stored_path", "")).parent
        try:
            subprocess.Popen(["explorer", str(folder)])
        except Exception as e:
            messagebox.showerror("Open Folder", str(e))

    def _dialog_new_revision(self):
        if not self._selected_item:
            messagebox.showwarning("New Revision", "Select an item first.")
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

    def _dialog_new_item(self):
        dlg = _ItemDialog(self, self.db)
        self.wait_window(dlg)
        self._refresh_parts_list()

    # ==================================================================
    # Screen: Structure / BOM
    # ==================================================================

    def _build_structure_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        self._screen_title_bar(f, "Structure / BOM", row=0)

        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=BG,
                              sashwidth=5, sashrelief="flat", bd=0, relief="flat")
        pane.grid(row=1, column=0, sticky="nsew")

        # Left: item list
        left = tk.Frame(pane, bg=BG)
        pane.add(left, minsize=200, width=340)

        ltb = tk.Frame(left, bg=BG)
        ltb.pack(fill="x", padx=8, pady=(8, 4))
        _btn(ltb, "Refresh", self._refresh_struct_list, width=80,
             fg_color=CARD2, hover="#3a3a5e").pack(side="left", padx=2)

        list_f = tk.Frame(left, bg=BG)
        list_f.pack(fill="both", expand=True, padx=8, pady=4)
        scols = [
            ("item_id", "Item ID",  80),
            ("name",    "Name",    175),
            ("status",  "Status",   65),
        ]
        self._struct_tree = _make_tree(list_f, scols, height=30)
        sb = _attach_vscroll(list_f, self._struct_tree)
        self._struct_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._struct_tree.bind("<<TreeviewSelect>>", self._on_struct_select)

        # Right: BOM treeview
        right = tk.Frame(pane, bg=BG)
        pane.add(right, minsize=400)

        rhdr = tk.Frame(right, bg=BG)
        rhdr.pack(fill="x", padx=8, pady=(8, 4))
        _lbl(rhdr, "Item Structure", font=FONT_BOLD).pack(side="left")

        bom_f = tk.Frame(right, bg=BG)
        bom_f.pack(fill="both", expand=True, padx=8, pady=4)
        _apply_tree_style()
        bom_cols = [
            ("name",   "Name",   220),
            ("type",   "Type",    80),
            ("rev",    "Rev",     60),
            ("status", "Status",  80),
            ("qty",    "Qty",     40),
        ]
        self._bom_tree = ttk.Treeview(bom_f, style="Dark.Treeview",
                                      columns=[c[0] for c in bom_cols],
                                      show="tree headings", height=30)
        self._bom_tree.heading("#0", text="")
        self._bom_tree.column("#0", width=20, stretch=False)
        for cid, label, width in bom_cols:
            self._bom_tree.heading(cid, text=label)
            self._bom_tree.column(cid, width=width, anchor="w")
        self._bom_tree.tag_configure("item_node", foreground=FG)
        self._bom_tree.tag_configure("rev_node",  foreground="#89b4fa")
        self._bom_tree.tag_configure("ds_node",   foreground=FG_MUTED)
        sb2 = ttk.Scrollbar(bom_f, orient="vertical", command=self._bom_tree.yview)
        self._bom_tree.configure(yscrollcommand=sb2.set)
        self._bom_tree.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        return f

    def _refresh_struct_list(self):
        for row in self._struct_tree.get_children():
            self._struct_tree.delete(row)
        for i, r in enumerate(self.db.list_items()):
            tag = "even" if i % 2 == 0 else "odd"
            self._struct_tree.insert("", "end", iid=r["item_id"], tags=(tag,),
                values=(r["item_id"], r["name"], r["status"]))
        self._clear_bom()

    def _clear_bom(self):
        for row in self._bom_tree.get_children():
            self._bom_tree.delete(row)
        self._bom_tree.insert("", "end",
            values=("Select an item to view structure", "", "", "", ""),
            tags=("ds_node",))

    def _on_struct_select(self, _event):
        sel = self._struct_tree.selection()
        if not sel:
            return
        item = self.db.get_item(sel[0])
        if item:
            self._load_bom(item)

    def _load_bom(self, item: dict):
        for row in self._bom_tree.get_children():
            self._bom_tree.delete(row)
        root = self._bom_tree.insert("", "end",
            values=(item["item_id"], item["type_name"], "", item["status"], "1"),
            tags=("item_node",), open=True)
        revs = self.db.get_revisions(item["id"])
        if not revs:
            self._bom_tree.insert(root, "end",
                values=("No revisions", "", "", "", ""), tags=("ds_node",))
            return
        for rev in revs:
            rev_node = self._bom_tree.insert(root, "end",
                values=(f"Rev {rev['revision']}", rev["revision_type"],
                        rev["revision"], rev["status"], ""),
                tags=("rev_node",), open=True)
            datasets = self.db.get_datasets(rev["id"])
            if not datasets:
                self._bom_tree.insert(rev_node, "end",
                    values=("No datasets", "", "", "", ""), tags=("ds_node",))
                continue
            for ds in datasets:
                size_str = f"{ds['file_size'] // 1024} KB" if ds["file_size"] else "0 KB"
                self._bom_tree.insert(rev_node, "end",
                    values=(ds["filename"], ds["file_type"], "", size_str, "1"),
                    tags=("ds_node",))

    # ==================================================================
    # Screen: Documents (all datasets, flat)
    # ==================================================================

    def _build_documents_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        self._screen_title_bar(f, "Documents", row=0)

        # Filter bar
        fbar = ctk.CTkFrame(f, fg_color=CARD, corner_radius=6)
        fbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        _lbl(fbar, "Type:").pack(side="left", padx=(12, 4), pady=8)
        self._docs_type_var = tk.StringVar(value="All Types")
        ctk.CTkOptionMenu(fbar, variable=self._docs_type_var,
                          values=["All Types", ".prt", ".asm", ".dwg", ".sldprt", ".sldasm",
                                  ".pdf", ".docx", ".xlsx", ".txt", ".csv"],
                          width=135, font=FONT_BODY,
                          command=lambda _: self._refresh_documents()
                          ).pack(side="left", padx=4, pady=8)
        self._docs_search_var = tk.StringVar()
        self._docs_search_var.trace_add("write", lambda *_: self._refresh_documents())
        ctk.CTkEntry(fbar, textvariable=self._docs_search_var,
                     placeholder_text="Search filename...", width=200,
                     font=FONT_BODY, fg_color=CARD2
                     ).pack(side="left", padx=4, pady=8)
        _btn(fbar, "Refresh", self._refresh_documents,
             width=80, fg_color=CARD2, hover="#3a3a5e").pack(side="right", padx=8, pady=8)

        # Table
        docs_f = tk.Frame(f, bg=BG)
        docs_f.grid(row=2, column=0, sticky="nsew", padx=12, pady=4)
        docs_f.grid_columnconfigure(0, weight=1)
        docs_f.grid_rowconfigure(0, weight=1)
        all_cols = [
            ("item_id",  "Item ID",   90),
            ("rev",      "Rev",       50),
            ("filename", "Filename", 230),
            ("type",     "Type",      60),
            ("size",     "Size",      70),
            ("added_by", "Added by", 100),
            ("added_at", "Added at", 150),
        ]
        self._all_docs_tree = _make_tree(docs_f, all_cols, height=30)
        self._all_docs_tree.grid(row=0, column=0, sticky="nsew")
        _attach_vscroll(docs_f, self._all_docs_tree).grid(row=0, column=1, sticky="ns")

        return f

    def _refresh_documents(self):
        for row in self._all_docs_tree.get_children():
            self._all_docs_tree.delete(row)
        type_filter = self._docs_type_var.get() if hasattr(self, "_docs_type_var") else "All Types"
        search = self._docs_search_var.get().lower() if hasattr(self, "_docs_search_var") else ""
        i = 0
        for item in self.db.list_items():
            for rev in self.db.get_revisions(item["id"]):
                for ds in self.db.get_datasets(rev["id"]):
                    ext = Path(ds["filename"]).suffix.lower()
                    if type_filter != "All Types" and ext != type_filter:
                        continue
                    if search and search not in ds["filename"].lower():
                        continue
                    size_str = f"{ds['file_size'] // 1024} KB" if ds["file_size"] else "0 KB"
                    added_at = ds.get("added_at") or ds.get("created_at") or ""
                    tag = "even" if i % 2 == 0 else "odd"
                    self._all_docs_tree.insert("", "end", tags=(tag,),
                        values=(item["item_id"], rev["revision"], ds["filename"],
                                ds["file_type"], size_str, ds["adder"], added_at))
                    i += 1

    # ==================================================================
    # Screen: Watcher
    # ==================================================================

    def _build_watcher_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(3, weight=1)

        self._screen_title_bar(f, "Watcher", row=0)

        # Status banner
        banner = ctk.CTkFrame(f, fg_color="#3a0000", corner_radius=6)
        banner.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        banner.grid_columnconfigure(1, weight=1)
        self._watcher_banner = banner
        self._watcher_dot = _lbl(banner, "  STOPPED", font=FONT_BOLD, color=ERR_FG)
        self._watcher_dot.grid(row=0, column=0, sticky="w", padx=12, pady=10)
        wbtn_row = ctk.CTkFrame(banner, fg_color="transparent")
        wbtn_row.grid(row=0, column=2, sticky="e", padx=12, pady=6)
        self._watcher_stop_btn = _btn(wbtn_row, "Stop", self._stop_watcher, width=70,
                                      fg_color="#7a0000", hover="#5a0000", state="disabled")
        self._watcher_stop_btn.pack(side="right", padx=4)
        self._watcher_start_btn = _btn(wbtn_row, "Start", self._start_watcher, width=90)
        self._watcher_start_btn.pack(side="right", padx=4)

        # Watch paths card
        paths_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=6)
        paths_card.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        watch_configs = config.get_watch_configs()
        if not watch_configs:
            _lbl(paths_card, "No watch paths configured.", font=FONT_SMALL, color=FG_MUTED
                 ).pack(padx=12, pady=8, anchor="w")
        for wc in watch_configs:
            wrow = ctk.CTkFrame(paths_card, fg_color="transparent")
            wrow.pack(fill="x", padx=8, pady=3)
            _lbl(wrow, f"[{wc['name']}]  {wc['path']}", font=FONT_MONO).pack(side="left")
            for ext in wc["extensions"]:
                _lbl(wrow, f" {ext} ", font=FONT_SMALL, color=ACCENT).pack(side="left", padx=2)

        # Log area
        self._watcher_log = ctk.CTkTextbox(f, font=FONT_MONO,
                                           fg_color=CARD, text_color=FG,
                                           state="disabled")
        self._watcher_log.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 12))

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
        n = len(wcs)
        self._watcher_dot.configure(
            text=f"  RUNNING - watching {n} path{'s' if n != 1 else ''}",
            text_color=OK_FG)
        self._watcher_banner.configure(fg_color="#003a00")
        self._watcher_start_btn.configure(state="disabled")
        self._watcher_stop_btn.configure(state="normal")

    def _stop_watcher(self):
        if self._watcher_obj:
            self._watcher_obj.stop()
            self._watcher_obj = None
        self._watcher_dot.configure(text="  STOPPED", text_color=ERR_FG)
        self._watcher_banner.configure(fg_color="#3a0000")
        self._watcher_start_btn.configure(state="normal")
        self._watcher_stop_btn.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                msg, _ = self._log_q.get_nowait()
                self._watcher_log.configure(state="normal")
                self._watcher_log.insert("end", msg + "\n")
                self._watcher_log.see("end")
                self._watcher_log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(300, self._poll_log_queue)

    # ==================================================================
    # Screen: Checkouts
    # ==================================================================

    def _build_checkouts_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        # Title + action buttons in same header row
        hdr = ctk.CTkFrame(f, fg_color=BG, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        tk.Frame(hdr, width=3, bg=ACCENT).grid(row=0, column=0, sticky="ns", padx=(12, 8), pady=8)
        _lbl(hdr, "Active Checkouts", font=FONT_TITLE).grid(row=0, column=1, sticky="w", pady=12)
        act = ctk.CTkFrame(hdr, fg_color=BG)
        act.grid(row=0, column=2, sticky="e", padx=12, pady=8)
        _btn(act, "Force Checkin", self._action_force_checkin,
             width=130, fg_color="#7a0000", hover="#5a0000").pack(side="right", padx=4)
        _btn(act, "Checkin", self._action_checkin_mine, width=90).pack(side="right", padx=4)
        _btn(act, "Refresh", self._refresh_checkouts,
             width=80, fg_color=CARD2, hover="#3a3a5e").pack(side="right", padx=4)

        co_f = tk.Frame(f, bg=BG)
        co_f.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        co_f.grid_columnconfigure(0, weight=1)
        co_f.grid_rowconfigure(0, weight=1)
        cols = [
            ("who",      "Checked out by", 140),
            ("item_rev", "Item / Rev",     130),
            ("filename", "Filename",       230),
            ("station",  "Station",        120),
            ("at",       "Since",          160),
        ]
        self._co_tree = _make_tree(co_f, cols, height=24)
        self._co_tree.grid(row=0, column=0, sticky="nsew")
        _attach_vscroll(co_f, self._co_tree).grid(row=0, column=1, sticky="ns")
        return f

    def _refresh_checkouts(self):
        for row in self._co_tree.get_children():
            self._co_tree.delete(row)
        for i, r in enumerate(self.db.list_checkouts()):
            item_rev = f"{r.get('item_id', '?')}/{r.get('revision', '?')}"
            tag = "co_mine" if r["who"] == self.username else "co_other"
            self._co_tree.insert("", "end", iid=str(r["id"]), tags=(tag,),
                values=(r["who"], item_rev, r["filename"],
                        r.get("station_name", ""), r["checked_out_at"]))

    def _action_checkin_mine(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Checkin", "Select a checkout row first.")
            return
        co_id = int(sel[0])
        row = next((r for r in self.db.list_checkouts() if r["id"] == co_id), None)
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
        row = next((r for r in self.db.list_checkouts() if r["id"] == co_id), None)
        if not row:
            return
        if not messagebox.askyesno("Force Checkin",
                                   f"Force checkin '{row['filename']}' "
                                   f"(checked out by {row['who']})?"):
            return
        try:
            from .checkout import _lock_path
            lock = _lock_path(Path(row["stored_path"]))
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
    # Screen: Settings
    # ==================================================================

    def _build_settings_screen(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
        f.grid_columnconfigure(0, weight=1)

        self._screen_title_bar(f, "Settings", row=0)

        # Watch Paths section
        _lbl(f, "Watch Paths", font=FONT_BOLD).grid(
            row=1, column=0, sticky="w", padx=16, pady=(8, 4))
        paths_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8)
        paths_card.grid(row=2, column=0, sticky="ew", padx=16, pady=4)
        c = config.get_config()
        for i, wc in enumerate(c.get("WATCH_CONFIGS", [])):
            txt = f"[{wc['name']}]  {wc['path']}  ({', '.join(wc['extensions'])})"
            _lbl(paths_card, txt, font=FONT_MONO).grid(
                row=i, column=0, sticky="w", padx=12, pady=5)

        # System config
        _lbl(f, "Configuration", font=FONT_BOLD).grid(
            row=3, column=0, sticky="w", padx=16, pady=(16, 4))
        cfg_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8)
        cfg_card.grid(row=4, column=0, sticky="ew", padx=16, pady=4)
        cfg_card.grid_columnconfigure(1, weight=1)

        for i, (lbl_txt, val_key) in enumerate([
            ("Database path:", "DB_PATH"),
            ("Backup path:",   "BACKUP_PATH"),
            ("Max versions:",  "MAX_VERSIONS"),
        ]):
            _lbl(cfg_card, lbl_txt, font=FONT_BOLD, color=FG_MUTED).grid(
                row=i, column=0, sticky="w", padx=12, pady=4)
            _lbl(cfg_card, str(c.get(val_key, "")), font=FONT_MONO).grid(
                row=i, column=1, sticky="w", padx=8, pady=4)

        # Users section
        _lbl(f, "Users", font=FONT_BOLD).grid(
            row=5, column=0, sticky="w", padx=16, pady=(16, 4))
        users_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8)
        users_card.grid(row=6, column=0, sticky="ew", padx=16, pady=4)
        users_card.grid_columnconfigure(0, weight=1)

        user_cols = [("username", "Username", 160), ("role", "Role", 100),
                     ("created", "Created", 160)]
        self._users_tree = _make_tree(users_card, user_cols, height=6)
        self._users_tree.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        ubtn_row = ctk.CTkFrame(users_card, fg_color=CARD)
        ubtn_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        _btn(ubtn_row, "Add User", self._dialog_add_user, width=100).pack(side="left", padx=4)
        _btn(ubtn_row, "Refresh", self._refresh_users,
             width=90, fg_color=CARD2, hover="#3a3a5e").pack(side="left", padx=4)

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

    # ==================================================================
    # Shared helpers
    # ==================================================================

    def _screen_title_bar(self, parent, title: str, row: int):
        """Standard orange-bar + title header, placed at `row` in parent grid."""
        hdr = ctk.CTkFrame(parent, fg_color=BG, height=44)
        hdr.grid(row=row, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        tk.Frame(hdr, width=3, bg=ACCENT).grid(row=0, column=0, sticky="ns", padx=(12, 8), pady=6)
        _lbl(hdr, title, font=FONT_TITLE).grid(row=0, column=1, sticky="w", pady=10)


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

        _lbl(self, "New Item", font=FONT_TITLE).pack(pady=(16, 8))

        frm = ctk.CTkFrame(self, fg_color=BG)
        frm.pack(fill="x", padx=20)

        _lbl(frm, "Name:", color=FG).grid(row=0, column=0, sticky="w", pady=4)
        self._name = ctk.CTkEntry(frm, width=260, font=FONT_BODY)
        self._name.grid(row=0, column=1, pady=4, padx=8)

        _lbl(frm, "Type:", color=FG).grid(row=1, column=0, sticky="w", pady=4)
        types = [t["name"] for t in db.list_item_types()]
        self._type_var = ctk.StringVar(value=types[0] if types else "")
        ctk.CTkOptionMenu(frm, values=types, variable=self._type_var,
                          width=260, font=FONT_BODY).grid(row=1, column=1, pady=4, padx=8)

        _lbl(frm, "Description:", color=FG).grid(row=2, column=0, sticky="w", pady=4)
        self._desc = ctk.CTkEntry(frm, width=260, font=FONT_BODY)
        self._desc.grid(row=2, column=1, pady=4, padx=8)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.pack(pady=16)
        _btn(btn_row, "Create", self._on_create, width=100).pack(side="left", padx=8)
        _btn(btn_row, "Cancel", self.destroy, width=80,
             fg_color=CARD2, hover=CARD2).pack(side="left", padx=8)

    def _on_create(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning("Validation", "Name is required.", parent=self)
            return
        itype = self.db.get_item_type_by_name(self._type_var.get())
        if not itype:
            return
        new_id = self.db.next_item_id()
        username = getpass.getuser()
        self.db.create_item(new_id, name, self._desc.get().strip(), itype["id"], username)
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

        _lbl(self, f"New Revision for {item['item_id']}", font=FONT_TITLE).pack(pady=(16, 8))

        frm = ctk.CTkFrame(self, fg_color=BG)
        frm.pack(fill="x", padx=20)
        _lbl(frm, "Type:", color=FG).grid(row=0, column=0, sticky="w", pady=4)
        self._type_var = ctk.StringVar(value="alpha")
        ctk.CTkOptionMenu(frm, values=["alpha", "numeric"],
                          variable=self._type_var, width=180,
                          font=FONT_BODY).grid(row=0, column=1, padx=8)

        btn_row = ctk.CTkFrame(self, fg_color=BG)
        btn_row.pack(pady=16)
        _btn(btn_row, "Create", self._on_create, width=100).pack(side="left", padx=8)
        _btn(btn_row, "Cancel", self.destroy, width=80,
             fg_color=CARD2, hover=CARD2).pack(side="left", padx=8)

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
