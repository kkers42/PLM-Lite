"""PLM Lite v2.0 -- Desktop GUI (tkinter + ttk, Teamcenter 8 light theme).

Screens via top chrome + sidebar navigation:
  Parts       -- item list (left) + tabbed detail (right)
  Structure   -- item list (left) + BOM treeview (right)
  Documents   -- all datasets flat view
  Watcher     -- status banner, start/stop, live log feed
  Checkouts   -- active checkouts table
  Settings    -- watch paths config, user management, audit log
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

from . import config
from .checkout import CheckoutError, checkin_file, checkout_file
from .database import Database

# ------------------------------------------------------------------
# Palette -- Teamcenter 8 light theme
# ------------------------------------------------------------------
BG_OUTER    = "#dce3ea"
BG_SURFACE  = "#f0f2f4"
BG_SURFACE2 = "#e4e8ec"
BG_SURFACE3 = "#c8d0d8"

TC_NAVY     = "#1c2b3a"
TC_NAVY_DK  = "#152130"
TC_NAVY_HOV = "#243547"
TC_BLUE     = "#2e6da4"
TC_BLUE_LT  = "#d6e8f7"
TC_BLUE_BTN = "#3a7fc1"

TEXT        = "#1a1a1a"
TEXT_INV    = "#e8edf2"
MUTED       = "#5a6472"
BORDER      = "#b8c2cc"

DANGER      = "#c0392b"
SUCCESS     = "#1a6e38"
WARNING     = "#b8620a"

ROW_EVEN    = "#eef1f4"
ROW_ODD     = BG_SURFACE
CO_MINE_BG  = TC_BLUE_LT
CO_OTHER_BG = "#fdf0e0"

FONT        = ("Segoe UI", 12)
FONT_SMALL  = ("Segoe UI", 11)
FONT_BOLD   = ("Segoe UI", 11, "bold")
FONT_TITLE  = ("Segoe UI", 11, "bold")
FONT_MONO   = ("Courier New", 11)

STATUS_COLOR = {
    "in_work":  MUTED,
    "released": SUCCESS,
    "locked":   WARNING,
    "obsolete": DANGER,
}

_NAV_ITEMS = [
    ("parts",     "[]",  "Parts"),
    ("structure", "[+]", "Structure / BOM"),
    ("documents", "[D]", "Documents"),
    ("watcher",   "[>]", "Watcher"),
    ("checkouts", "[C]", "Checkouts"),
    ("settings",  "[*]", "Admin / Settings"),
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
# TTK style setup
# ------------------------------------------------------------------

_STYLE_DONE = False


def _apply_styles():
    global _STYLE_DONE
    if _STYLE_DONE:
        return
    s = ttk.Style()
    s.theme_use("clam")

    s.configure("TC.Treeview",
                background=BG_SURFACE, foreground=TEXT,
                fieldbackground=BG_SURFACE,
                rowheight=26, font=FONT_SMALL, borderwidth=0)
    s.configure("TC.Treeview.Heading",
                background=BG_SURFACE2, foreground="#2a3a4a",
                font=FONT_BOLD, relief="flat", borderwidth=1)
    s.map("TC.Treeview",
          background=[("selected", TC_BLUE_LT)],
          foreground=[("selected", TC_NAVY_DK)])
    s.map("TC.Treeview.Heading",
          background=[("active", BG_SURFACE3)])

    s.configure("TC.Vertical.TScrollbar",
                background=BG_SURFACE2, troughcolor=BG_SURFACE3,
                borderwidth=0, arrowcolor=MUTED)

    _STYLE_DONE = True


# ------------------------------------------------------------------
# Widget helpers
# ------------------------------------------------------------------

def _make_tree(parent, columns: list, height=14, show="headings") -> ttk.Treeview:
    _apply_styles()
    col_ids = [c[0] for c in columns]
    tree = ttk.Treeview(parent, style="TC.Treeview",
                        columns=col_ids, show=show, height=height)
    for cid, label, width in columns:
        tree.heading(cid, text=label)
        tree.column(cid, width=width, anchor="w")
    if show != "headings":
        tree.heading("#0", text="")
        tree.column("#0", width=20, stretch=False)
    tree.tag_configure("even",      background=ROW_EVEN)
    tree.tag_configure("odd",       background=ROW_ODD)
    tree.tag_configure("co_mine",   background=CO_MINE_BG)
    tree.tag_configure("co_other",  background=CO_OTHER_BG)
    tree.tag_configure("released",  foreground=SUCCESS)
    tree.tag_configure("locked",    foreground=WARNING)
    tree.tag_configure("obsolete",  foreground=DANGER)
    tree.tag_configure("rev_node",  foreground=TC_BLUE)
    tree.tag_configure("ds_node",   foreground=MUTED)
    tree.tag_configure("item_node", foreground=TC_NAVY_DK)
    return tree


def _attach_vscroll(parent, tree: ttk.Treeview) -> ttk.Scrollbar:
    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview,
                       style="TC.Vertical.TScrollbar")
    tree.configure(yscrollcommand=sb.set)
    return sb


def _btn(parent, text, cmd, bg=BG_SURFACE2, fg=TEXT, **kw):
    return tk.Button(parent, text=text, command=cmd,
                     bg=bg, fg=fg, relief="raised", bd=1,
                     font=FONT_SMALL, padx=6, pady=2,
                     activebackground=BG_SURFACE3, activeforeground=TEXT,
                     cursor="hand2", **kw)


def _btn_primary(parent, text, cmd, **kw):
    return _btn(parent, text, cmd, bg=TC_BLUE_BTN, fg="#ffffff",
                activebackground=TC_BLUE, **kw)


def _btn_danger(parent, text, cmd, **kw):
    return _btn(parent, text, cmd, bg=DANGER, fg="#ffffff",
                activebackground="#a02020", **kw)


def _btn_success(parent, text, cmd, **kw):
    return _btn(parent, text, cmd, bg=SUCCESS, fg="#ffffff",
                activebackground="#145c28", **kw)


def _btn_warning(parent, text, cmd, **kw):
    return _btn(parent, text, cmd, bg=WARNING, fg="#ffffff",
                activebackground="#8a4800", **kw)


def _panel_titlebar(parent, text: str):
    """Dark blue title bar, packed into parent."""
    bar = tk.Frame(parent, bg="#2b5070", height=24)
    bar.pack(fill="x", side="top")
    bar.pack_propagate(False)
    tk.Label(bar, text=text.upper(), font=FONT_BOLD,
             fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)
    return bar


def _toolbar(parent):
    """Toolbar frame packed into parent, returns inner frame for content."""
    tb = tk.Frame(parent, bg=BG_SURFACE2, height=34)
    tb.pack(fill="x", side="top")
    tb.pack_propagate(False)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", side="top")
    return tb


def _hsep(parent):
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", side="top")


# ------------------------------------------------------------------
# Main application window
# ------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        _apply_styles()

        self.title(f"PLM Lite v{_VERSION}")
        self.geometry("1300x820")
        self.configure(bg=TC_NAVY)

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

        self._nav_btns: dict = {}
        self._screens: dict = {}
        self._active_screen: str = "parts"

        self._build_layout()
        self._show_screen("parts")
        self.after(500, self._poll_log_queue)

    # ==================================================================
    # Layout skeleton
    # ==================================================================

    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # ---- Top chrome bar (36px, TC_NAVY) ----
        chrome = tk.Frame(self, bg=TC_NAVY, height=36)
        chrome.grid(row=0, column=0, columnspan=2, sticky="ew")
        chrome.grid_propagate(False)
        chrome.grid_columnconfigure(1, weight=1)

        logo_f = tk.Frame(chrome, bg=TC_NAVY)
        logo_f.grid(row=0, column=0, padx=(10, 0), sticky="w")
        tk.Label(logo_f, text="PLM Lite", font=("Segoe UI", 14, "bold"),
                 fg="#ffffff", bg=TC_NAVY).pack(side="left")
        tk.Label(logo_f, text=f" v{_VERSION}", font=("Segoe UI", 10),
                 fg="#7ab8e8", bg=TC_NAVY).pack(side="left")

        menu_f = tk.Frame(chrome, bg=TC_NAVY)
        menu_f.grid(row=0, column=1, sticky="w", padx=14)
        for label, screen in [("Parts", "parts"), ("Structure", "structure"),
                               ("Documents", "documents"), ("Admin", "settings")]:
            lbl = tk.Label(menu_f, text=label, font=FONT_SMALL,
                           fg=TEXT_INV, bg=TC_NAVY, padx=10, pady=4, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, s=screen: self._show_screen(s))
            lbl.bind("<Enter>", lambda e, w=lbl: w.configure(bg=TC_NAVY_HOV))
            lbl.bind("<Leave>", lambda e, w=lbl: w.configure(bg=TC_NAVY))

        user_f = tk.Frame(chrome, bg=TC_NAVY)
        user_f.grid(row=0, column=2, padx=10, sticky="e")
        tk.Label(user_f, text=self.username, font=("Segoe UI", 10),
                 fg="#a8c8e8", bg=TC_NAVY).pack(side="left", padx=(0, 4))
        tk.Label(user_f, text="user", font=("Segoe UI", 9),
                 fg="#c0d8ee", bg=TC_NAVY, padx=6, pady=1,
                 relief="solid", bd=1).pack(side="left", padx=4)
        tk.Button(user_f, text="Sign Out", font=("Segoe UI", 10),
                  fg="#a8c8e8", bg=TC_NAVY, relief="solid", bd=1,
                  padx=8, pady=1, cursor="hand2",
                  activebackground=TC_NAVY_HOV, activeforeground="#fff",
                  command=lambda: None).pack(side="left", padx=4)

        # chrome bottom border
        tk.Frame(self, bg="#0d1924", height=2).grid(
            row=0, column=0, columnspan=2, sticky="sew")

        # ---- Sidebar (190px, TC_NAVY) ----
        sidebar = tk.Frame(self, bg=TC_NAVY, width=190)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(49, weight=1)

        tk.Label(sidebar, text="NAVIGATION", font=("Segoe UI", 9, "bold"),
                 fg="#6a8aaa", bg=TC_NAVY).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        for i, (key, icon, label) in enumerate(_NAV_ITEMS):
            self._make_nav_btn(sidebar, key, icon, label, i + 1)

        tk.Label(sidebar, text=f"  {self.username}", font=FONT_SMALL,
                 fg="#6a8aaa", bg=TC_NAVY, anchor="w").grid(
            row=50, column=0, sticky="ew", padx=8, pady=12)

        # sidebar right border
        tk.Frame(self, bg="#0d1924", width=2).grid(row=1, column=0, sticky="nse")

        # ---- Content area ----
        self._content = tk.Frame(self, bg=BG_SURFACE)
        self._content.grid(row=1, column=1, sticky="nsew")
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
        frame = tk.Frame(sidebar, bg=TC_NAVY, height=32)
        frame.grid(row=row, column=0, sticky="ew")
        frame.grid_propagate(False)
        frame.grid_columnconfigure(1, weight=1)

        bar = tk.Frame(frame, width=3, bg=TC_NAVY)
        bar.grid(row=0, column=0, sticky="ns")

        lbl = tk.Label(frame, text=f" {icon}  {label}",
                       font=FONT_SMALL, fg="#c0d4e8", bg=TC_NAVY,
                       anchor="w", cursor="hand2")
        lbl.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        def on_enter(e):
            if self._active_screen != key:
                lbl.configure(bg=TC_NAVY_HOV, fg="#ffffff")
                frame.configure(bg=TC_NAVY_HOV)

        def on_leave(e):
            if self._active_screen != key:
                lbl.configure(bg=TC_NAVY, fg="#c0d4e8")
                frame.configure(bg=TC_NAVY)

        def on_click(e):
            self._show_screen(key)

        for w in (lbl, frame, bar):
            w.bind("<Button-1>", on_click)
        lbl.bind("<Enter>", on_enter)
        lbl.bind("<Leave>", on_leave)

        self._nav_btns[key] = (bar, lbl, frame)

    def _show_screen(self, key: str):
        self._active_screen = key
        for k, (bar, lbl, frame) in self._nav_btns.items():
            if k == key:
                bar.configure(bg="#7ab8e8")
                lbl.configure(fg="#ffffff", bg="#1e3a5c", font=FONT_BOLD)
                frame.configure(bg="#1e3a5c")
            else:
                bar.configure(bg=TC_NAVY)
                lbl.configure(fg="#c0d4e8", bg=TC_NAVY, font=FONT_SMALL)
                frame.configure(bg=TC_NAVY)
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

    def _build_parts_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=BG_SURFACE)

        _panel_titlebar(f, "Parts -- Master List")

        tb = _toolbar(f)
        self._parts_search_var = tk.StringVar()
        self._parts_search_var.trace_add("write", lambda *_: self._refresh_parts_list())
        tk.Entry(tb, textvariable=self._parts_search_var, width=30,
                 font=FONT_SMALL, relief="solid", bd=1,
                 bg="#ffffff").pack(side="left", padx=6, pady=6)

        self._parts_status_var = tk.StringVar(value="All")
        st_cb = ttk.Combobox(tb, textvariable=self._parts_status_var,
                              values=["All", "in_work", "released", "locked", "obsolete"],
                              width=12, font=FONT_SMALL, state="readonly")
        st_cb.pack(side="left", padx=4, pady=6)
        st_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_parts_list())

        tk.Frame(tb, width=1, bg=BORDER).pack(side="left", fill="y", pady=4, padx=4)
        _btn_primary(tb, "+ New Item", self._dialog_new_item).pack(side="left", padx=4)

        # Split pane fills remaining space
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=BG_SURFACE3,
                              sashwidth=4, sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True)

        # Left: item list
        left = tk.Frame(pane, bg=BG_SURFACE)
        pane.add(left, minsize=200, width=400)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)

        list_f = tk.Frame(left, bg=BG_SURFACE)
        list_f.grid(row=0, column=0, columnspan=2, sticky="nsew")
        list_f.grid_columnconfigure(0, weight=1)
        list_f.grid_rowconfigure(0, weight=1)

        pcols = [
            ("item_id", "Item ID",  90),
            ("name",    "Name",    170),
            ("type",    "Type",     80),
            ("status",  "Status",   75),
            ("rev",     "Rev",      40),
        ]
        self._parts_tree = _make_tree(list_f, pcols, height=30)
        sb = _attach_vscroll(list_f, self._parts_tree)
        self._parts_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._parts_tree.bind("<<TreeviewSelect>>", self._on_parts_select)

        # Right separator strip
        tk.Frame(left, bg="#8a97a4", width=2).grid(row=0, column=2, sticky="ns")

        # Right: detail pane
        right = tk.Frame(pane, bg=BG_SURFACE)
        pane.add(right, minsize=400)
        self._build_detail_pane(right)

        return f

    def _refresh_parts_list(self):
        query = self._parts_search_var.get().lower() if hasattr(self, "_parts_search_var") else ""
        sf = self._parts_status_var.get() if hasattr(self, "_parts_status_var") else "All"
        for row in self._parts_tree.get_children():
            self._parts_tree.delete(row)
        i = 0
        for r in self.db.list_items():
            if query and query not in r["item_id"].lower() and query not in r["name"].lower():
                continue
            if sf != "All" and r["status"] != sf:
                continue
            revs = self.db.get_revisions(r["id"])
            latest_rev = revs[-1]["revision"] if revs else "-"
            status = r["status"]
            tag = status if status in ("released", "locked", "obsolete") else (
                "even" if i % 2 == 0 else "odd")
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

    # ---- Detail pane ----

    def _build_detail_pane(self, parent: tk.Frame):
        # Empty state overlay (hidden once item selected)
        self._detail_empty = tk.Frame(parent, bg=BG_SURFACE)
        self._detail_empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Label(self._detail_empty, text="Select an item to view details",
                 font=FONT_SMALL, fg=MUTED, bg=BG_SURFACE).place(relx=0.5, rely=0.5,
                                                                   anchor="center")

        # Detail header
        self._detail_header = tk.Frame(parent, bg=BG_SURFACE2)
        self._detail_header.pack(fill="x", side="top")

        row1 = tk.Frame(self._detail_header, bg=BG_SURFACE2)
        row1.pack(fill="x", padx=12, pady=(8, 2))

        self._detail_id_lbl = tk.Label(row1, text="--",
                                       font=("Courier New", 14, "bold"),
                                       fg=TC_NAVY_DK, bg=BG_SURFACE2)
        self._detail_id_lbl.pack(side="left")

        self._detail_rev_frame = tk.Frame(row1, bg=BG_SURFACE2)
        self._detail_rev_frame.pack(side="left", padx=6)

        self._detail_status_frame = tk.Frame(row1, bg=BG_SURFACE2)
        self._detail_status_frame.pack(side="left", padx=2)

        row2 = tk.Frame(self._detail_header, bg=BG_SURFACE2)
        row2.pack(fill="x", padx=12, pady=(0, 8))
        self._detail_name_lbl = tk.Label(row2, text="", font=FONT_SMALL,
                                         fg=MUTED, bg=BG_SURFACE2)
        self._detail_name_lbl.pack(side="left")

        _hsep(parent)

        # Action bar
        self._action_bar = tk.Frame(parent, bg=BG_SURFACE3, height=32)
        self._action_bar.pack(fill="x", side="top")
        self._action_bar.pack_propagate(False)

        self._ds_checkout_btn = _btn_primary(self._action_bar, "Checkout",
                                             self._action_checkout_dataset)
        self._ds_checkout_btn.pack(side="left", padx=4, pady=4)
        self._ds_checkin_btn = _btn(self._action_bar, "Checkin",
                                    self._action_checkin_dataset)
        self._ds_checkin_btn.pack(side="left", padx=2, pady=4)
        tk.Frame(self._action_bar, width=1, bg=BORDER).pack(side="left", fill="y", pady=4)
        _btn_success(self._action_bar, "Release Rev",
                     self._action_release_revision).pack(side="left", padx=4, pady=4)
        _btn_warning(self._action_bar, "Lock Rev",
                     self._action_lock_revision).pack(side="left", padx=2, pady=4)
        _btn(self._action_bar, "New Revision",
             self._dialog_new_revision).pack(side="left", padx=2, pady=4)
        tk.Frame(self._action_bar, width=1, bg=BORDER).pack(side="left", fill="y", pady=4)
        _btn(self._action_bar, "Add Dataset",
             self._dialog_add_dataset).pack(side="left", padx=4, pady=4)
        _btn(self._action_bar, "Open Folder",
             self._action_open_folder).pack(side="left", padx=2, pady=4)
        self._ds_status_lbl = tk.Label(self._action_bar, text="", font=FONT_SMALL,
                                       fg=MUTED, bg=BG_SURFACE3)
        self._ds_status_lbl.pack(side="right", padx=8)

        _hsep(parent)

        # Revision selector
        rev_bar = tk.Frame(parent, bg=BG_SURFACE2, height=30)
        rev_bar.pack(fill="x", side="top")
        rev_bar.pack_propagate(False)
        tk.Label(rev_bar, text="Revision:", font=FONT_BOLD,
                 fg=TEXT, bg=BG_SURFACE2).pack(side="left", padx=(8, 4), pady=4)
        self._rev_combo_var = tk.StringVar()
        self._rev_combo = ttk.Combobox(rev_bar, textvariable=self._rev_combo_var,
                                       values=["--"], width=22, font=FONT_SMALL,
                                       state="readonly")
        self._rev_combo.pack(side="left", padx=4, pady=4)
        self._rev_combo.bind("<<ComboboxSelected>>", self._on_rev_combo_change)

        _hsep(parent)

        # Inner tabs bar
        tabs_bar = tk.Frame(parent, bg=BG_SURFACE3)
        tabs_bar.pack(fill="x", side="top")
        self._inner_tab_labels: dict = {}
        self._inner_tab_frames: dict = {}
        self._active_inner_tab = "details"
        for tab_key, tab_text in [("details", "DETAILS"), ("attributes", "ATTRIBUTES"),
                                   ("revisions", "REVISIONS"), ("documents", "DOCUMENTS")]:
            lbl = tk.Label(tabs_bar, text=tab_text, font=FONT_BOLD,
                           fg=MUTED, bg=BG_SURFACE3,
                           padx=14, pady=5, cursor="hand2")
            lbl.pack(side="left")
            tk.Frame(tabs_bar, width=1, bg=BORDER).pack(side="left", fill="y")
            lbl.bind("<Button-1>", lambda e, k=tab_key: self._switch_inner_tab(k))
            self._inner_tab_labels[tab_key] = lbl

        _hsep(parent)

        # Tab content container
        tab_container = tk.Frame(parent, bg=BG_SURFACE)
        tab_container.pack(fill="both", expand=True)
        tab_container.grid_columnconfigure(0, weight=1)
        tab_container.grid_rowconfigure(0, weight=1)

        for tab_key in ("details", "attributes", "revisions", "documents"):
            tf = tk.Frame(tab_container, bg=BG_SURFACE)
            tf.grid(row=0, column=0, sticky="nsew")
            tf.grid_remove()
            self._inner_tab_frames[tab_key] = tf

        self._build_details_tab(self._inner_tab_frames["details"])
        self._build_attributes_tab(self._inner_tab_frames["attributes"])
        self._build_revisions_tab(self._inner_tab_frames["revisions"])
        self._build_documents_tab(self._inner_tab_frames["documents"])
        self._switch_inner_tab("details")

    def _switch_inner_tab(self, key: str):
        self._active_inner_tab = key
        for k, lbl in self._inner_tab_labels.items():
            if k == key:
                lbl.configure(fg=TC_NAVY_DK, bg=BG_SURFACE, font=FONT_BOLD)
            else:
                lbl.configure(fg=MUTED, bg=BG_SURFACE3, font=FONT_BOLD)
        for k, tf in self._inner_tab_frames.items():
            if k == key:
                tf.grid()
            else:
                tf.grid_remove()

    def _build_details_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)

        self._details_vals: dict = {}
        fields_left = [("Part Number", "item_id"), ("Name", "name"),
                       ("Created By", "creator"), ("Status", "status")]
        fields_right = [("Revision", "_rev_label"), ("Type", "type_name"),
                        ("Created At", "created_at"), ("", "")]

        for row_i, ((ll, lk), (rl, rk)) in enumerate(zip(fields_left, fields_right)):
            for col, (lbl_txt, field_key) in enumerate([(ll, lk), (rl, rk)]):
                if not lbl_txt:
                    continue
                padx = (16, 8) if col == 0 else (8, 16)
                tk.Label(parent, text=lbl_txt.upper(),
                         font=("Segoe UI", 9, "bold"), fg=MUTED, bg=BG_SURFACE,
                         anchor="w").grid(row=row_i * 2, column=col, sticky="w",
                                          padx=padx, pady=(10, 0))
                val = tk.Label(parent, text="--", font=FONT_SMALL,
                               fg=TEXT, bg=BG_SURFACE, anchor="w")
                val.grid(row=row_i * 2 + 1, column=col, sticky="ew",
                         padx=padx, pady=(0, 4))
                self._details_vals[field_key] = val

        # Description full width
        base_row = len(fields_left) * 2
        tk.Label(parent, text="DESCRIPTION", font=("Segoe UI", 9, "bold"),
                 fg=MUTED, bg=BG_SURFACE, anchor="w").grid(
            row=base_row, column=0, columnspan=2, sticky="w", padx=16, pady=(10, 0))
        desc_val = tk.Label(parent, text="--", font=FONT_SMALL, fg=TEXT, bg=BG_SURFACE,
                            anchor="w", justify="left", wraplength=380)
        desc_val.grid(row=base_row + 1, column=0, columnspan=2, sticky="ew",
                      padx=16, pady=(0, 4))
        self._details_vals["description"] = desc_val

    def _build_attributes_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        f = tk.Frame(parent, bg=BG_SURFACE)
        f.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)

        attr_cols = [("attribute", "Attribute", 150), ("value", "Value", 320)]
        self._attr_tree = _make_tree(f, attr_cols, height=12)
        sb = _attach_vscroll(f, self._attr_tree)
        self._attr_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

    def _build_revisions_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        f = tk.Frame(parent, bg=BG_SURFACE)
        f.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)

        rev_cols = [("rev",    "Rev",     50), ("type",   "Type",    90),
                    ("status", "Status",  90), ("by",     "By",     110),
                    ("at",     "Created", 150)]
        self._revs_tree = _make_tree(f, rev_cols, height=12)
        sb = _attach_vscroll(f, self._revs_tree)
        self._revs_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

    def _build_documents_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        f = tk.Frame(parent, bg=BG_SURFACE)
        f.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)

        ds_cols = [("filename", "Filename",       200),
                   ("type",     "Type",            55),
                   ("size",     "Size",            65),
                   ("by",       "Added by",        95),
                   ("checkout", "Checked out by", 145),
                   ("since",    "Since",          120)]
        self._ds_tree = _make_tree(f, ds_cols, height=14)
        sb = _attach_vscroll(f, self._ds_tree)
        self._ds_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._ds_tree.bind("<<TreeviewSelect>>", self._on_dataset_select)
        # keep old reference alias for _refresh_datasets
        self._doc_tab_tree = self._ds_tree

    def _load_item_detail(self, item: dict):
        self._detail_empty.lower()  # push empty state behind real content

        self._detail_id_lbl.configure(text=item["item_id"])
        self._detail_name_lbl.configure(text=item["name"])

        # Status chip
        for w in self._detail_status_frame.winfo_children():
            w.destroy()
        _chip_cfg = {
            "in_work":  ("#eaecee", "#4a5560", "In Work"),
            "released": ("#e2f2e8", "#0e5c22", "Released"),
            "locked":   ("#fdf3e2", "#7a4200", "Locked"),
            "obsolete": ("#fdecea", "#8e1e18", "Obsolete"),
        }
        cbg, cfg, ctxt = _chip_cfg.get(item["status"],
                                        ("#eaecee", "#4a5560", item["status"]))
        tk.Label(self._detail_status_frame, text=ctxt,
                 font=("Segoe UI", 9, "bold"), fg=cfg, bg=cbg,
                 padx=4, pady=1, relief="solid", bd=1).pack()

        revs = self.db.get_revisions(item["id"])
        self._revs_cache = revs

        rev_labels = [f"{r['revision']}  ({r['status']})" for r in revs]
        if rev_labels:
            self._rev_combo.configure(values=rev_labels)
            self._rev_combo.set(rev_labels[-1])
            self._selected_rev = revs[-1]
            self._refresh_datasets(revs[-1]["id"])

            for w in self._detail_rev_frame.winfo_children():
                w.destroy()
            tk.Label(self._detail_rev_frame,
                     text=f"Rev {revs[-1]['revision']}",
                     font=("Segoe UI", 9, "bold"), fg="#2e6da4", bg="#d6e8f7",
                     padx=4, pady=1, relief="solid", bd=1).pack()
        else:
            self._rev_combo.configure(values=["No revisions"])
            self._rev_combo.set("No revisions")
            self._selected_rev = {}
            self._clear_datasets()
            for w in self._detail_rev_frame.winfo_children():
                w.destroy()

        # Details tab
        self._details_vals.get("item_id") and self._details_vals["item_id"].configure(
            text=item["item_id"])
        self._details_vals.get("name") and self._details_vals["name"].configure(
            text=item["name"])
        self._details_vals.get("type_name") and self._details_vals["type_name"].configure(
            text=item["type_name"])
        self._details_vals.get("creator") and self._details_vals["creator"].configure(
            text=item["creator"])
        self._details_vals.get("created_at") and self._details_vals["created_at"].configure(
            text=item["created_at"])
        self._details_vals.get("description") and self._details_vals["description"].configure(
            text=item.get("description") or "--")
        if "status" in self._details_vals:
            self._details_vals["status"].configure(
                text=item["status"],
                fg=STATUS_COLOR.get(item["status"], TEXT))
        if "_rev_label" in self._details_vals:
            self._details_vals["_rev_label"].configure(
                text=revs[-1]["revision"] if revs else "--")

        # Attributes tab
        for row in self._attr_tree.get_children():
            self._attr_tree.delete(row)
        for attr, val in [("Part Number", item["item_id"]),
                          ("Name", item["name"]),
                          ("Description", item.get("description") or "--"),
                          ("Item Type", item["type_name"]),
                          ("Status", item["status"]),
                          ("Created By", item["creator"]),
                          ("Created At", item["created_at"])]:
            self._attr_tree.insert("", "end", values=(attr, val))

        # Revisions tab
        for row in self._revs_tree.get_children():
            self._revs_tree.delete(row)
        for i, r in enumerate(revs):
            tag = "even" if i % 2 == 0 else "odd"
            self._revs_tree.insert("", "end", tags=(tag,),
                values=(r["revision"], r["revision_type"], r["status"],
                        r.get("creator", ""), r.get("created_at", "")))

    def _on_rev_combo_change(self, _event):
        choice = self._rev_combo_var.get()
        for r in self._revs_cache:
            if f"{r['revision']}  ({r['status']})" == choice:
                self._selected_rev = r
                self._refresh_datasets(r["id"])
                return

    def _refresh_datasets(self, revision_id: int):
        self._clear_datasets()
        datasets = self.db.get_datasets(revision_id)
        self._datasets_cache = datasets
        for i, d in enumerate(datasets):
            size_str = f"{d['file_size'] // 1024} KB" if d["file_size"] else "0 KB"
            who = d.get("checked_out_by") or ""
            since = d.get("checked_out_at") or "--"
            if who == self.username:
                tag = "co_mine"
            elif who:
                tag = "co_other"
            else:
                tag = "even" if i % 2 == 0 else "odd"
            self._ds_tree.insert("", "end", iid=str(d["id"]), tags=(tag,),
                values=(d["filename"], d["file_type"], size_str,
                        d["adder"], who or "--", since))
        self._selected_dataset = {}
        self._update_checkout_ui(None)

    def _clear_datasets(self):
        for row in self._ds_tree.get_children():
            self._ds_tree.delete(row)
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
            self._ds_status_lbl.configure(text="", fg=MUTED)
            self._ds_checkout_btn.configure(state="normal")
            self._ds_checkin_btn.configure(state="disabled")
            return
        who = ds.get("checked_out_by")
        if not who:
            self._ds_status_lbl.configure(text="Available", fg=SUCCESS)
            self._ds_checkout_btn.configure(state="normal")
            self._ds_checkin_btn.configure(state="disabled")
        elif who == self.username:
            self._ds_status_lbl.configure(
                text=f"Checked out by you  ({ds.get('station_name', '')})",
                fg=WARNING)
            self._ds_checkout_btn.configure(state="disabled")
            self._ds_checkin_btn.configure(state="normal")
        else:
            self._ds_status_lbl.configure(
                text=f"Locked by {who} since {ds.get('checked_out_at', '')}",
                fg=DANGER)
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

    def _build_structure_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=BG_SURFACE)

        _panel_titlebar(f, "Structure Manager -- BOM / Where Used")

        tb = _toolbar(f)
        self._struct_search_var = tk.StringVar()
        tk.Entry(tb, textvariable=self._struct_search_var, width=28,
                 font=FONT_SMALL, relief="solid", bd=1,
                 bg="#ffffff").pack(side="left", padx=6, pady=6)
        tk.Frame(tb, width=1, bg=BORDER).pack(side="left", fill="y", pady=4, padx=4)
        _btn(tb, "Where Used", lambda: None).pack(side="left", padx=4)
        _btn(tb, "Export BOM", lambda: None).pack(side="left", padx=2)

        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=BG_SURFACE3,
                              sashwidth=4, sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True)

        left = tk.Frame(pane, bg=BG_SURFACE)
        pane.add(left, minsize=200, width=340)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)

        list_f = tk.Frame(left, bg=BG_SURFACE)
        list_f.grid(row=0, column=0, sticky="nsew")
        list_f.grid_columnconfigure(0, weight=1)
        list_f.grid_rowconfigure(0, weight=1)
        scols = [("item_id", "Item ID", 90), ("name", "Name", 180), ("status", "Status", 70)]
        self._struct_tree = _make_tree(list_f, scols, height=30)
        sb = _attach_vscroll(list_f, self._struct_tree)
        self._struct_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._struct_tree.bind("<<TreeviewSelect>>", self._on_struct_select)

        right = tk.Frame(pane, bg=BG_SURFACE)
        pane.add(right, minsize=400)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        bom_f = tk.Frame(right, bg=BG_SURFACE)
        bom_f.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        bom_f.grid_columnconfigure(0, weight=1)
        bom_f.grid_rowconfigure(0, weight=1)

        bom_cols = [("name", "Name", 220), ("type", "Type", 80),
                    ("rev", "Rev", 60), ("status", "Status", 80), ("qty", "Qty", 40)]
        self._bom_tree = ttk.Treeview(bom_f, style="TC.Treeview",
                                      columns=[c[0] for c in bom_cols],
                                      show="tree headings", height=30)
        self._bom_tree.heading("#0", text="")
        self._bom_tree.column("#0", width=20, stretch=False)
        for cid, label, width in bom_cols:
            self._bom_tree.heading(cid, text=label)
            self._bom_tree.column(cid, width=width, anchor="w")
        self._bom_tree.tag_configure("item_node", foreground=TC_NAVY_DK)
        self._bom_tree.tag_configure("rev_node",  foreground=TC_BLUE)
        self._bom_tree.tag_configure("ds_node",   foreground=MUTED)
        sb2 = _attach_vscroll(bom_f, self._bom_tree)
        self._bom_tree.grid(row=0, column=0, sticky="nsew")
        sb2.grid(row=0, column=1, sticky="ns")

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
                self._bom_tree.insert(rev_node, "end",
                    values=(ds["filename"], ds["file_type"], "", "", "1"),
                    tags=("ds_node",))

    # ==================================================================
    # Screen: Documents (all datasets flat)
    # ==================================================================

    def _build_documents_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=BG_SURFACE)

        _panel_titlebar(f, "Document Library")

        tb = _toolbar(f)
        self._docs_search_var = tk.StringVar()
        self._docs_search_var.trace_add("write", lambda *_: self._refresh_documents())
        tk.Entry(tb, textvariable=self._docs_search_var, width=28,
                 font=FONT_SMALL, relief="solid", bd=1,
                 bg="#ffffff").pack(side="left", padx=6, pady=6)
        self._docs_type_var = tk.StringVar(value="All Types")
        tc = ttk.Combobox(tb, textvariable=self._docs_type_var,
                          values=["All Types", ".prt", ".asm", ".dwg", ".sldprt",
                                  ".sldasm", ".pdf", ".docx", ".xlsx", ".txt", ".csv"],
                          width=12, font=FONT_SMALL, state="readonly")
        tc.pack(side="left", padx=4, pady=6)
        tc.bind("<<ComboboxSelected>>", lambda _: self._refresh_documents())
        tk.Frame(tb, width=1, bg=BORDER).pack(side="left", fill="y", pady=4, padx=4)
        _btn(tb, "Refresh", self._refresh_documents).pack(side="left", padx=4)

        docs_f = tk.Frame(f, bg=BG_SURFACE)
        docs_f.pack(fill="both", expand=True)
        docs_f.grid_columnconfigure(0, weight=1)
        docs_f.grid_rowconfigure(0, weight=1)

        all_cols = [("item_id",  "Item ID",   90), ("rev",      "Rev",       50),
                    ("filename", "Filename",  230), ("type",     "Type",      60),
                    ("size",     "Size",       70), ("added_by", "Added by", 100),
                    ("added_at", "Added at",  150)]
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

    def _build_watcher_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=BG_SURFACE)

        _panel_titlebar(f, "File Watcher")

        # Status banner
        self._watcher_banner = tk.Frame(f, bg="#8e1e18", height=40)
        self._watcher_banner.pack(fill="x", side="top")
        self._watcher_banner.pack_propagate(False)

        self._watcher_dot = tk.Label(self._watcher_banner, text="  STOPPED",
                                     font=FONT_BOLD, fg="#fde8e8", bg="#8e1e18")
        self._watcher_dot.pack(side="left", padx=12)

        btn_area = tk.Frame(self._watcher_banner, bg="#8e1e18")
        btn_area.pack(side="right", padx=8, pady=6)
        self._watcher_stop_btn = _btn_danger(btn_area, "Stop", self._stop_watcher)
        self._watcher_stop_btn.pack(side="right", padx=4)
        self._watcher_stop_btn.configure(state="disabled")
        self._watcher_start_btn = _btn_primary(btn_area, "Start", self._start_watcher)
        self._watcher_start_btn.pack(side="right", padx=4)

        # Watch paths card
        paths_card = tk.Frame(f, bg=BG_SURFACE2, relief="solid", bd=1)
        paths_card.pack(fill="x", padx=8, pady=6, side="top")
        watch_configs = config.get_watch_configs()
        if not watch_configs:
            tk.Label(paths_card, text="No watch paths configured.",
                     font=FONT_SMALL, fg=MUTED, bg=BG_SURFACE2
                     ).pack(padx=12, pady=8, anchor="w")
        for wc in watch_configs:
            wrow = tk.Frame(paths_card, bg=BG_SURFACE2)
            wrow.pack(fill="x", padx=8, pady=3)
            tk.Label(wrow, text=f"[{wc['name']}]  {wc['path']}",
                     font=FONT_MONO, fg=TC_NAVY_DK, bg=BG_SURFACE2).pack(side="left")
            for ext in wc["extensions"]:
                tk.Label(wrow, text=f" {ext} ", font=FONT_SMALL,
                         fg=TC_BLUE, bg=BG_SURFACE2).pack(side="left", padx=2)

        # Log area
        log_f = tk.Frame(f, bg=BG_SURFACE)
        log_f.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        log_f.grid_columnconfigure(0, weight=1)
        log_f.grid_rowconfigure(0, weight=1)
        self._watcher_log = tk.Text(log_f, font=FONT_MONO, bg=BG_SURFACE, fg=TEXT,
                                    state="disabled", relief="solid", bd=1, wrap="none")
        log_sb = ttk.Scrollbar(log_f, orient="vertical",
                               command=self._watcher_log.yview,
                               style="TC.Vertical.TScrollbar")
        self._watcher_log.configure(yscrollcommand=log_sb.set)
        self._watcher_log.grid(row=0, column=0, sticky="nsew")
        log_sb.grid(row=0, column=1, sticky="ns")

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
            fg="#d8fde8", bg="#1a6e38")
        self._watcher_banner.configure(bg="#1a6e38")
        self._watcher_start_btn.configure(state="disabled")
        self._watcher_stop_btn.configure(state="normal")

    def _stop_watcher(self):
        if self._watcher_obj:
            self._watcher_obj.stop()
            self._watcher_obj = None
        self._watcher_dot.configure(text="  STOPPED", fg="#fde8e8", bg="#8e1e18")
        self._watcher_banner.configure(bg="#8e1e18")
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

    def _build_checkouts_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=BG_SURFACE)

        _panel_titlebar(f, "Active Checkouts")

        tb = _toolbar(f)
        _btn(tb, "Refresh", self._refresh_checkouts).pack(side="left", padx=6, pady=6)
        tk.Frame(tb, width=1, bg=BORDER).pack(side="left", fill="y", pady=4, padx=4)
        _btn(tb, "Checkin (mine)", self._action_checkin_mine).pack(side="left", padx=4)
        _btn_danger(tb, "Force Checkin (admin)",
                    self._action_force_checkin).pack(side="left", padx=4)

        co_f = tk.Frame(f, bg=BG_SURFACE)
        co_f.pack(fill="both", expand=True)
        co_f.grid_columnconfigure(0, weight=1)
        co_f.grid_rowconfigure(0, weight=1)

        cols = [("who",      "Checked out by", 140), ("item_rev", "Item / Rev",     130),
                ("filename", "Filename",        230), ("station",  "Station",        120),
                ("at",       "Since",           160)]
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
            from .checkout import LOCK_SUFFIX
            lock = Path(row["stored_path"]).with_suffix(
                Path(row["stored_path"]).suffix + LOCK_SUFFIX)
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
    # Screen: Settings / Admin
    # ==================================================================

    def _build_settings_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=BG_SURFACE)

        _panel_titlebar(f, "Administration")

        # Scrollable content
        canvas = tk.Canvas(f, bg=BG_SURFACE, highlightthickness=0)
        vsb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview,
                            style="TC.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG_SURFACE)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_resize(e):
            canvas.itemconfig(inner_window, width=e.width)

        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_canvas_resize)

        # Watch Paths
        tk.Label(inner, text="Watch Paths", font=FONT_BOLD,
                 fg=TC_NAVY_DK, bg=BG_SURFACE).pack(anchor="w", padx=16, pady=(12, 4))
        paths_card = tk.Frame(inner, bg=BG_SURFACE2, relief="solid", bd=1)
        paths_card.pack(fill="x", padx=16, pady=4)
        c = config.get_config()
        for wc in c.get("WATCH_CONFIGS", []):
            txt = f"[{wc['name']}]  {wc['path']}  ({', '.join(wc['extensions'])})"
            tk.Label(paths_card, text=txt, font=FONT_MONO,
                     fg=TC_NAVY_DK, bg=BG_SURFACE2).pack(anchor="w", padx=12, pady=5)
        if not c.get("WATCH_CONFIGS"):
            tk.Label(paths_card, text="No watch configs.", font=FONT_SMALL,
                     fg=MUTED, bg=BG_SURFACE2).pack(padx=12, pady=8)

        # Configuration
        tk.Label(inner, text="Configuration", font=FONT_BOLD,
                 fg=TC_NAVY_DK, bg=BG_SURFACE).pack(anchor="w", padx=16, pady=(16, 4))
        cfg_card = tk.Frame(inner, bg=BG_SURFACE2, relief="solid", bd=1)
        cfg_card.pack(fill="x", padx=16, pady=4)
        cfg_card.grid_columnconfigure(1, weight=1)
        for i, (lbl_txt, val_key) in enumerate([("Database path:", "DB_PATH"),
                                                  ("Backup path:",   "BACKUP_PATH"),
                                                  ("Max versions:",  "MAX_VERSIONS")]):
            tk.Label(cfg_card, text=lbl_txt, font=FONT_BOLD,
                     fg=MUTED, bg=BG_SURFACE2).grid(row=i, column=0, sticky="w",
                                                      padx=12, pady=4)
            tk.Label(cfg_card, text=str(c.get(val_key, "")), font=FONT_MONO,
                     fg=TC_NAVY_DK, bg=BG_SURFACE2).grid(row=i, column=1, sticky="w",
                                                           padx=8, pady=4)

        # Users
        tk.Label(inner, text="Users", font=FONT_BOLD,
                 fg=TC_NAVY_DK, bg=BG_SURFACE).pack(anchor="w", padx=16, pady=(16, 4))
        users_outer = tk.Frame(inner, bg=BG_SURFACE2, relief="solid", bd=1)
        users_outer.pack(fill="x", padx=16, pady=4)

        ubtn_row = tk.Frame(users_outer, bg=BG_SURFACE2)
        ubtn_row.pack(fill="x", padx=8, pady=(8, 4))
        _btn_primary(ubtn_row, "+ Add User", self._dialog_add_user).pack(side="left", padx=4)
        _btn(ubtn_row, "Refresh", self._refresh_users).pack(side="left", padx=4)

        user_f = tk.Frame(users_outer, bg=BG_SURFACE2)
        user_f.pack(fill="x", padx=8, pady=(0, 8))
        user_f.grid_columnconfigure(0, weight=1)
        user_cols = [("username", "Username", 160), ("role", "Role", 100),
                     ("created", "Created", 160)]
        self._users_tree = _make_tree(user_f, user_cols, height=6)
        self._users_tree.grid(row=0, column=0, sticky="ew")
        _attach_vscroll(user_f, self._users_tree).grid(row=0, column=1, sticky="ns")

        # Audit Log
        tk.Label(inner, text="Audit Log", font=FONT_BOLD,
                 fg=TC_NAVY_DK, bg=BG_SURFACE).pack(anchor="w", padx=16, pady=(16, 4))
        audit_outer = tk.Frame(inner, bg=BG_SURFACE)
        audit_outer.pack(fill="x", padx=16, pady=(0, 16))
        audit_outer.grid_columnconfigure(0, weight=1)
        audit_cols = [("time",   "Time",   130), ("user",   "User",   100),
                      ("action", "Action", 110), ("entity", "Entity", 110),
                      ("detail", "Detail", 300)]
        self._audit_tree = _make_tree(audit_outer, audit_cols, height=10)
        self._audit_tree.grid(row=0, column=0, sticky="ew")
        _attach_vscroll(audit_outer, self._audit_tree).grid(row=0, column=1, sticky="ns")

        self._refresh_users()
        self._refresh_audit()
        return f

    def _refresh_users(self):
        for row in self._users_tree.get_children():
            self._users_tree.delete(row)
        for i, u in enumerate(self.db.list_users()):
            tag = "even" if i % 2 == 0 else "odd"
            self._users_tree.insert("", "end", tags=(tag,),
                values=(u["username"], u["role"], u["created_at"]))

    def _refresh_audit(self):
        for row in self._audit_tree.get_children():
            self._audit_tree.delete(row)
        try:
            logs = self.db.list_audit_log()
        except Exception:
            return
        for i, r in enumerate(logs):
            tag = "even" if i % 2 == 0 else "odd"
            self._audit_tree.insert("", "end", tags=(tag,),
                values=(r.get("created_at", ""), r.get("username", ""),
                        r.get("action", ""), r.get("entity_type", ""),
                        r.get("detail", "")))

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

class _ItemDialog(tk.Toplevel):
    def __init__(self, parent, db: Database):
        super().__init__(parent)
        self.db = db
        self.title("New Item")
        self.geometry("420x260")
        self.configure(bg=BG_SURFACE)
        self.grab_set()
        self.resizable(False, False)

        hdr = tk.Frame(self, bg="#2b5070", height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="NEW ITEM", font=FONT_BOLD,
                 fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)

        frm = tk.Frame(self, bg=BG_SURFACE)
        frm.pack(fill="x", padx=20, pady=12)
        frm.grid_columnconfigure(1, weight=1)

        tk.Label(frm, text="Name:", font=FONT_SMALL, fg=TEXT,
                 bg=BG_SURFACE).grid(row=0, column=0, sticky="w", pady=6)
        self._name = tk.Entry(frm, width=32, font=FONT_SMALL,
                              relief="solid", bd=1, bg="#ffffff")
        self._name.grid(row=0, column=1, pady=6, padx=8, sticky="ew")

        tk.Label(frm, text="Type:", font=FONT_SMALL, fg=TEXT,
                 bg=BG_SURFACE).grid(row=1, column=0, sticky="w", pady=6)
        types = [t["name"] for t in db.list_item_types()]
        self._type_var = tk.StringVar(value=types[0] if types else "")
        ttk.Combobox(frm, textvariable=self._type_var, values=types,
                     width=28, font=FONT_SMALL, state="readonly").grid(
            row=1, column=1, pady=6, padx=8, sticky="ew")

        tk.Label(frm, text="Description:", font=FONT_SMALL, fg=TEXT,
                 bg=BG_SURFACE).grid(row=2, column=0, sticky="w", pady=6)
        self._desc = tk.Entry(frm, width=32, font=FONT_SMALL,
                              relief="solid", bd=1, bg="#ffffff")
        self._desc.grid(row=2, column=1, pady=6, padx=8, sticky="ew")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")
        btn_row = tk.Frame(self, bg=BG_SURFACE2)
        btn_row.pack(fill="x", side="bottom")
        _btn_primary(btn_row, "Create", self._on_create).pack(side="right", padx=8, pady=6)
        _btn(btn_row, "Cancel", self.destroy).pack(side="right", padx=4, pady=6)

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


class _RevisionDialog(tk.Toplevel):
    def __init__(self, parent, db: Database, item: dict):
        super().__init__(parent)
        self.db = db
        self.item = item
        self.title(f"New Revision -- {item['item_id']}")
        self.geometry("360x170")
        self.configure(bg=BG_SURFACE)
        self.grab_set()
        self.resizable(False, False)

        hdr = tk.Frame(self, bg="#2b5070", height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"NEW REVISION -- {item['item_id']}", font=FONT_BOLD,
                 fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)

        frm = tk.Frame(self, bg=BG_SURFACE)
        frm.pack(fill="x", padx=20, pady=16)
        frm.grid_columnconfigure(1, weight=1)

        tk.Label(frm, text="Type:", font=FONT_SMALL, fg=TEXT,
                 bg=BG_SURFACE).grid(row=0, column=0, sticky="w", pady=6)
        self._type_var = tk.StringVar(value="alpha")
        ttk.Combobox(frm, textvariable=self._type_var, values=["alpha", "numeric"],
                     width=20, font=FONT_SMALL, state="readonly").grid(
            row=0, column=1, padx=8, sticky="ew")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")
        btn_row = tk.Frame(self, bg=BG_SURFACE2)
        btn_row.pack(fill="x", side="bottom")
        _btn_primary(btn_row, "Create", self._on_create).pack(side="right", padx=8, pady=6)
        _btn(btn_row, "Cancel", self.destroy).pack(side="right", padx=4, pady=6)

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
