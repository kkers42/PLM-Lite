"""PLM Lite v3.0.0 — Desktop GUI (CustomTkinter, dark theme).

Screens:
  Parts      — item list + tabbed detail (files, revisions, details)
  My Files   — checked-out temp files, disk-save, checkin
  Admin      — users, roles, audit log, watcher (admin only)
  Settings   — config paths, version info
"""

import logging
import os
import queue
import shutil
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk

from . import config
from .checkout import (CheckoutError, checkin_file, checkout_file,
                       cleanup_user_temp, copy_children_to_temp, disk_save)
from .database import Database

# ------------------------------------------------------------------
# Theme
# ------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_VERSION = "3.0.0"

# Raw color constants (used where CTk doesn't provide a widget)
C_BG        = "#1a1f2e"
C_SURFACE   = "#242938"
C_SURFACE2  = "#2e3347"
C_SURFACE3  = "#383d52"
C_NAVY      = "#1c2b3a"
C_BLUE      = "#3a7fc1"
C_BLUE_HOV  = "#2e6da4"
C_BLUE_LT   = "#1e3a5c"
C_TEXT      = "#e2e8f0"
C_MUTED     = "#8892a4"
C_BORDER    = "#3a4060"
C_DANGER    = "#e05252"
C_SUCCESS   = "#4ade80"
C_WARNING   = "#fbbf24"
C_ROW_EVEN  = "#242938"
C_ROW_ODD   = "#2a2f44"
C_SEL       = "#1e3a5c"

FONT        = ("Segoe UI", 12)
FONT_SMALL  = ("Segoe UI", 11)
FONT_BOLD   = ("Segoe UI", 11, "bold")
FONT_TITLE  = ("Segoe UI", 13, "bold")
FONT_MONO   = ("Courier New", 11)

STATUS_COLOR = {
    "in_work":  C_MUTED,
    "released": C_SUCCESS,
    "locked":   C_WARNING,
    "obsolete": C_DANGER,
}

# ------------------------------------------------------------------
# TTK style (for Treeview — CTk doesn't have one)
# ------------------------------------------------------------------
_STYLE_DONE = False

def _apply_ttk_styles():
    global _STYLE_DONE
    if _STYLE_DONE:
        return
    s = ttk.Style()
    s.theme_use("clam")
    s.configure("Dark.Treeview",
                background=C_SURFACE, foreground=C_TEXT,
                fieldbackground=C_SURFACE,
                rowheight=28, font=FONT_SMALL, borderwidth=0)
    s.configure("Dark.Treeview.Heading",
                background=C_SURFACE2, foreground="#a0aec0",
                font=FONT_BOLD, relief="flat", borderwidth=0)
    s.map("Dark.Treeview",
          background=[("selected", C_SEL)],
          foreground=[("selected", "#ffffff")])
    s.map("Dark.Treeview.Heading",
          background=[("active", C_SURFACE3)])
    s.configure("Dark.Vertical.TScrollbar",
                background=C_SURFACE2, troughcolor=C_SURFACE3,
                borderwidth=0, arrowcolor=C_MUTED)
    _STYLE_DONE = True


def _make_tree(parent, columns: list, height=14) -> ttk.Treeview:
    _apply_ttk_styles()
    col_ids = [c[0] for c in columns]
    tree = ttk.Treeview(parent, style="Dark.Treeview",
                        columns=col_ids, show="headings", height=height)
    for cid, label, width in columns:
        tree.heading(cid, text=label)
        tree.column(cid, width=width, anchor="w", minwidth=40)
    tree.tag_configure("even",     background=C_ROW_EVEN, foreground=C_TEXT)
    tree.tag_configure("odd",      background=C_ROW_ODD,  foreground=C_TEXT)
    tree.tag_configure("released", background=C_ROW_EVEN, foreground=C_SUCCESS)
    tree.tag_configure("locked",   background=C_ROW_EVEN, foreground=C_WARNING)
    tree.tag_configure("obsolete", background=C_ROW_EVEN, foreground=C_DANGER)
    tree.tag_configure("co_mine",  background="#1a2e4a",   foreground="#7ab8e8")
    tree.tag_configure("co_other", background="#2e2010",   foreground=C_WARNING)
    return tree


def _attach_vscroll(parent, tree):
    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview,
                       style="Dark.Vertical.TScrollbar")
    tree.configure(yscrollcommand=sb.set)
    return sb


# ------------------------------------------------------------------
# Logging bridge
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
# LoginWindow
# ------------------------------------------------------------------
class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.authenticated_user = None
        self.title("PLM Lite — Sign In")
        self.geometry("360x300")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self._center()
        self._build()

    def _center(self):
        self.update_idletasks()
        w, h = 360, 300
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=C_NAVY, corner_radius=0, height=70)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="PLM Lite",
                     font=ctk.CTkFont("Segoe UI", 22, "bold"),
                     text_color="#ffffff").pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(hdr, text=f"v{_VERSION}",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color="#7ab8e8").pack(side="left")

        # Card
        card = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=10)
        card.pack(fill="both", expand=True, padx=24, pady=16)

        ctk.CTkLabel(card, text="Sign In",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C_TEXT).pack(pady=(16, 8))

        self._user_var = ctk.StringVar()
        self._pass_var = ctk.StringVar()

        ctk.CTkEntry(card, textvariable=self._user_var,
                     placeholder_text="Username",
                     width=260, height=36).pack(pady=4)

        pw = ctk.CTkEntry(card, textvariable=self._pass_var,
                          placeholder_text="Password",
                          show="*", width=260, height=36)
        pw.pack(pady=4)
        pw.bind("<Return>", lambda _: self._do_login())

        self._err_lbl = ctk.CTkLabel(card, text="",
                                     font=ctk.CTkFont("Segoe UI", 10),
                                     text_color=C_DANGER)
        self._err_lbl.pack()

        ctk.CTkButton(card, text="Sign In", width=260, height=36,
                      command=self._do_login,
                      fg_color=C_BLUE, hover_color=C_BLUE_HOV).pack(pady=8)

    def _do_login(self):
        username = self._user_var.get().strip()
        password = self._pass_var.get()
        if not username or not password:
            self._err_lbl.configure(text="Enter username and password.")
            return
        try:
            db = Database()
            db.initialize()
            user = db.verify_password(username, password)
        except Exception as e:
            self._err_lbl.configure(text=f"Error: {e}")
            return
        if user is None:
            self._err_lbl.configure(text="Invalid username or password.")
            return
        self.authenticated_user = user
        self.destroy()


# ------------------------------------------------------------------
# Main Application
# ------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self, user: dict):
        super().__init__()
        self.user     = user
        self.username = user["username"]
        self.role     = user["role"]

        self.db = Database()
        self.db.initialize()
        self.perms = self.db.get_role_permissions(self.role)

        self._log_q: queue.Queue = queue.Queue(maxsize=500)
        self._watcher_thread = None
        self._watcher_obj    = None

        self._selected_item:    dict = {}
        self._selected_rev:     dict = {}
        self._selected_dataset: dict = {}
        self._revs_cache:  list = []
        self._datasets_cache: list = []

        self._active_screen = "parts"
        self._nav_btns: dict = {}
        self._screens:  dict = {}

        self.title(f"PLM Lite v{_VERSION}  —  {self.username}")
        self.geometry("1360x860")
        self.configure(fg_color=C_BG)

        _apply_ttk_styles()
        self._build_layout()
        self._show_screen("parts")
        self.after(400, self._poll_log_queue)

    # ==================================================================
    # Layout skeleton
    # ==================================================================

    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Chrome bar
        chrome = ctk.CTkFrame(self, fg_color=C_NAVY, corner_radius=0, height=40)
        chrome.grid(row=0, column=0, columnspan=2, sticky="ew")
        chrome.grid_propagate(False)
        chrome.grid_columnconfigure(1, weight=1)

        logo_f = ctk.CTkFrame(chrome, fg_color="transparent")
        logo_f.grid(row=0, column=0, padx=(14, 0), sticky="w")
        ctk.CTkLabel(logo_f, text="PLM Lite",
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color="#ffffff").pack(side="left")
        ctk.CTkLabel(logo_f, text=f" v{_VERSION}",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color="#7ab8e8").pack(side="left")

        # Nav labels in chrome
        nav_f = ctk.CTkFrame(chrome, fg_color="transparent")
        nav_f.grid(row=0, column=1, sticky="w", padx=10)
        nav_screens = [("Parts", "parts"), ("My Files", "myfiles"),
                       ("Settings", "settings")]
        if "users.manage" in self.perms:
            nav_screens.append(("Admin", "admin"))
        for label, screen in nav_screens:
            lbl = tk.Label(nav_f, text=label, font=FONT_SMALL,
                           fg="#c0d4e8", bg=C_NAVY, padx=10, pady=6, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, s=screen: self._show_screen(s))
            lbl.bind("<Enter>", lambda e, w=lbl: w.configure(bg="#243547"))
            lbl.bind("<Leave>", lambda e, w=lbl: w.configure(bg=C_NAVY))

        # User info + sign out
        user_f = ctk.CTkFrame(chrome, fg_color="transparent")
        user_f.grid(row=0, column=2, padx=10, sticky="e")
        ctk.CTkLabel(user_f, text=self.username,
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color="#a8c8e8").pack(side="left", padx=(0, 4))
        role_badge = tk.Label(user_f, text=self.role,
                              font=("Segoe UI", 9), fg="#c0d8ee", bg=C_NAVY,
                              relief="solid", bd=1, padx=6, pady=1)
        role_badge.pack(side="left", padx=4)
        ctk.CTkButton(user_f, text="Sign Out", width=80, height=26,
                      fg_color="transparent", border_width=1,
                      border_color="#6a8aaa", text_color="#a8c8e8",
                      hover_color=C_BLUE_LT,
                      command=self._sign_out).pack(side="left", padx=6)

        # Chrome bottom border
        tk.Frame(self, bg="#0d1924", height=2).grid(
            row=0, column=0, columnspan=2, sticky="sew")

        # Sidebar
        sidebar = ctk.CTkFrame(self, fg_color=C_NAVY, corner_radius=0, width=180)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(49, weight=1)

        tk.Label(sidebar, text="NAVIGATION",
                 font=("Segoe UI", 9, "bold"),
                 fg="#6a8aaa", bg=C_NAVY).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        nav_items = [
            ("parts",    "◈", "Parts"),
            ("myfiles",  "⊡", "My Files"),
            ("settings", "⚙", "Settings"),
        ]
        if "users.manage" in self.perms:
            nav_items.append(("admin", "⊞", "Admin"))

        for i, (key, icon, label) in enumerate(nav_items):
            self._make_nav_btn(sidebar, key, icon, label, i + 1)

        # Sidebar bottom: username + DB status
        tk.Label(sidebar, text=f"  {self.username}",
                 font=FONT_SMALL, fg="#6a8aaa", bg=C_NAVY, anchor="w").grid(
            row=50, column=0, sticky="ew", padx=8, pady=8)

        # Sidebar right border
        tk.Frame(self, bg="#0d1924", width=2).grid(row=1, column=0, sticky="nse")

        # Content area
        self._content = tk.Frame(self, bg=C_BG)
        self._content.grid(row=1, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        # Build all screens
        self._screens = {
            "parts":    self._build_parts_screen(),
            "myfiles":  self._build_myfiles_screen(),
            "settings": self._build_settings_screen(),
            "admin":    self._build_admin_screen(),
        }

        # Status bar
        sbar = tk.Frame(self, bg=C_NAVY, height=22)
        sbar.grid(row=2, column=0, columnspan=2, sticky="ew")
        sbar.grid_propagate(False)
        db_ok = config.DB_PATH.exists()
        dot_color = C_SUCCESS if db_ok else C_DANGER
        tk.Label(sbar, text="●", fg=dot_color, bg=C_NAVY,
                 font=("Segoe UI", 10)).pack(side="left", padx=(8, 2))
        tk.Label(sbar, text=f"db  ·  {self.username}  ·  {self.role}  ·  PLM Lite v{_VERSION}",
                 font=("Segoe UI", 9), fg=C_MUTED, bg=C_NAVY).pack(side="left")

    def _make_nav_btn(self, sidebar, key: str, icon: str, label: str, row: int):
        frame = tk.Frame(sidebar, bg=C_NAVY, height=34)
        frame.grid(row=row, column=0, sticky="ew")
        frame.grid_propagate(False)
        frame.grid_columnconfigure(1, weight=1)

        bar = tk.Frame(frame, width=3, bg=C_NAVY)
        bar.grid(row=0, column=0, sticky="ns")

        lbl = tk.Label(frame, text=f"  {icon}  {label}",
                       font=FONT_SMALL, fg="#c0d4e8", bg=C_NAVY,
                       anchor="w", cursor="hand2")
        lbl.grid(row=0, column=1, sticky="ew")

        def on_enter(e):
            if self._active_screen != key:
                lbl.configure(bg="#243547", fg="#ffffff")
                frame.configure(bg="#243547")
        def on_leave(e):
            if self._active_screen != key:
                lbl.configure(bg=C_NAVY, fg="#c0d4e8")
                frame.configure(bg=C_NAVY)
        def on_click(e):
            self._show_screen(key)

        for w in (lbl, frame, bar):
            w.bind("<Button-1>", on_click)
        lbl.bind("<Enter>", on_enter)
        lbl.bind("<Leave>", on_leave)
        self._nav_btns[key] = (bar, lbl, frame)

    def _show_screen(self, key: str):
        if key not in self._screens:
            return
        self._active_screen = key
        for k, (bar, lbl, frame) in self._nav_btns.items():
            if k == key:
                bar.configure(bg="#7ab8e8")
                lbl.configure(fg="#ffffff", bg=C_BLUE_LT, font=FONT_BOLD)
                frame.configure(bg=C_BLUE_LT)
            else:
                bar.configure(bg=C_NAVY)
                lbl.configure(fg="#c0d4e8", bg=C_NAVY, font=FONT_SMALL)
                frame.configure(bg=C_NAVY)
        for screen in self._screens.values():
            screen.grid_remove()
        self._screens[key].grid(row=0, column=0, sticky="nsew")
        if key == "parts":
            self._refresh_parts_list()
        elif key == "myfiles":
            self._refresh_myfiles()
        elif key == "admin":
            self._refresh_users()

    # ==================================================================
    # Threading helper
    # ==================================================================

    def _run_async(self, fn, *args, on_done=None, on_error=None):
        def worker():
            try:
                result = fn(*args)
                if on_done:
                    self.after(0, lambda: on_done(result))
            except Exception as e:
                if on_error:
                    self.after(0, lambda: on_error(e))
                else:
                    self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    # ==================================================================
    # Screen: Parts
    # ==================================================================

    def _build_parts_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=C_BG)

        # Title bar
        tbar = tk.Frame(f, bg="#2b5070", height=26)
        tbar.pack(fill="x", side="top")
        tbar.pack_propagate(False)
        tk.Label(tbar, text="PARTS — MASTER LIST", font=FONT_BOLD,
                 fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)

        # Toolbar
        tb = tk.Frame(f, bg=C_SURFACE2, height=38)
        tb.pack(fill="x", side="top")
        tb.pack_propagate(False)
        tk.Frame(f, bg=C_BORDER, height=1).pack(fill="x", side="top")

        self._parts_search_var = tk.StringVar()
        self._parts_search_var.trace_add("write", lambda *_: self._refresh_parts_list())
        tk.Entry(tb, textvariable=self._parts_search_var, width=28,
                 font=FONT_SMALL, relief="flat", bd=0,
                 bg=C_SURFACE3, fg=C_TEXT, insertbackground=C_TEXT).pack(
            side="left", padx=8, pady=7, ipady=3)

        self._parts_status_var = tk.StringVar(value="All")
        st_cb = ttk.Combobox(tb, textvariable=self._parts_status_var,
                              values=["All", "in_work", "released", "locked", "obsolete"],
                              width=10, font=FONT_SMALL, state="readonly")
        st_cb.pack(side="left", padx=4, pady=7)
        st_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_parts_list())

        self._parts_co_only = tk.BooleanVar(value=False)
        tk.Checkbutton(tb, text="Checked Out Only", variable=self._parts_co_only,
                       bg=C_SURFACE2, fg=C_TEXT, selectcolor=C_SURFACE3,
                       activebackground=C_SURFACE2, activeforeground=C_TEXT,
                       font=FONT_SMALL,
                       command=self._refresh_parts_list).pack(side="left", padx=8)

        tk.Frame(tb, width=1, bg=C_BORDER).pack(side="left", fill="y", pady=4)

        if "parts.create" in self.perms:
            tk.Button(tb, text="+ New Item", command=self._dialog_new_item,
                      bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                      padx=8, pady=2, cursor="hand2",
                      activebackground=C_BLUE_HOV).pack(side="left", padx=6)

        # Split pane
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=C_BORDER,
                              sashwidth=4, sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True)

        # Left: item list
        left = tk.Frame(pane, bg=C_BG)
        pane.add(left, minsize=200, width=420)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)

        pcols = [
            ("item_id", "Item ID",  95),
            ("name",    "Name",    175),
            ("type",    "Type",     80),
            ("status",  "Status",   75),
            ("rev",     "Rev",      40),
            ("co_by",   "Chk'd Out", 90),
        ]
        self._parts_tree = _make_tree(left, pcols, height=30)
        sb = _attach_vscroll(left, self._parts_tree)
        self._parts_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._parts_tree.bind("<<TreeviewSelect>>", self._on_parts_select)

        # Right: detail pane
        right = tk.Frame(pane, bg=C_BG)
        pane.add(right, minsize=420)
        self._build_detail_pane(right)

        return f

    def _refresh_parts_list(self):
        if not hasattr(self, "_parts_tree"):
            return
        query  = self._parts_search_var.get().lower() if hasattr(self, "_parts_search_var") else ""
        sf     = self._parts_status_var.get() if hasattr(self, "_parts_status_var") else "All"
        co_only = self._parts_co_only.get() if hasattr(self, "_parts_co_only") else False

        def fetch():
            items = self.db.list_items()
            result = []
            for r in items:
                if query and query not in r["item_id"].lower() and query not in r["name"].lower():
                    continue
                if sf != "All" and r["status"] != sf:
                    continue
                revs = self.db.get_revisions(r["id"])
                latest_rev  = revs[-1]["revision"] if revs else "-"
                latest_rev_id = revs[-1]["id"] if revs else None
                co_by = ""
                if latest_rev_id:
                    for ds in self.db.get_datasets(latest_rev_id):
                        co = self.db.get_checkout(ds["id"])
                        if co:
                            co_by = co["who"]
                            break
                if co_only and not co_by:
                    continue
                result.append({
                    "item_id": r["item_id"], "name": r["name"],
                    "type": r.get("type_name", ""), "status": r["status"],
                    "rev": latest_rev, "co_by": co_by,
                })
            return result

        def populate(rows):
            for row in self._parts_tree.get_children():
                self._parts_tree.delete(row)
            for i, r in enumerate(rows):
                co_by = r["co_by"]
                if co_by == self.username:
                    tag = "co_mine"
                elif co_by:
                    tag = "co_other"
                else:
                    status = r["status"]
                    tag = status if status in ("released", "locked", "obsolete") else (
                        "even" if i % 2 == 0 else "odd")
                self._parts_tree.insert("", "end", iid=r["item_id"], tags=(tag,),
                    values=(r["item_id"], r["name"], r["type"],
                            r["status"], r["rev"], co_by))

        self._run_async(fetch, on_done=populate)

    def _on_parts_select(self, _event):
        sel = self._parts_tree.selection()
        if not sel:
            return
        def load():
            item = self.db.get_item(sel[0])
            if not item:
                return None
            revs = self.db.get_revisions(item["id"])
            return item, revs
        def on_done(result):
            if not result:
                return
            item, revs = result
            self._selected_item = item
            self._revs_cache = revs
            self._detail_empty.place_forget()
            self._load_item_header(item)
            self._populate_rev_combo(revs)
            if revs:
                self._selected_rev = revs[-1]
                self._rev_combo_var.set(revs[-1]["revision"])
                self._refresh_datasets(revs[-1]["id"])
            else:
                self._selected_rev = {}
                self._clear_datasets()
        self._run_async(load, on_done=on_done)

    # ---- Detail pane ----

    def _build_detail_pane(self, parent: tk.Frame):
        # Empty state
        self._detail_empty = tk.Frame(parent, bg=C_BG)
        self._detail_empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Label(self._detail_empty, text="Select an item",
                 font=FONT_SMALL, fg=C_MUTED, bg=C_BG).place(relx=0.5, rely=0.5, anchor="center")

        # Header
        self._detail_header = tk.Frame(parent, bg=C_SURFACE)
        self._detail_header.pack(fill="x", side="top")

        row1 = tk.Frame(self._detail_header, bg=C_SURFACE)
        row1.pack(fill="x", padx=12, pady=(8, 2))
        self._detail_id_lbl = tk.Label(row1, text="--",
                                       font=("Courier New", 14, "bold"),
                                       fg="#7ab8e8", bg=C_SURFACE)
        self._detail_id_lbl.pack(side="left")
        self._detail_status_lbl = tk.Label(row1, text="",
                                           font=FONT_SMALL, fg=C_MUTED, bg=C_SURFACE)
        self._detail_status_lbl.pack(side="left", padx=8)

        row2 = tk.Frame(self._detail_header, bg=C_SURFACE)
        row2.pack(fill="x", padx=12, pady=(0, 8))
        self._detail_name_lbl = tk.Label(row2, text="",
                                         font=FONT_SMALL, fg=C_MUTED, bg=C_SURFACE)
        self._detail_name_lbl.pack(side="left")

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill="x")

        # Action bar
        self._action_bar = tk.Frame(parent, bg=C_SURFACE2, height=36)
        self._action_bar.pack(fill="x", side="top")
        self._action_bar.pack_propagate(False)
        self._build_action_bar()

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill="x")

        # Revision bar
        rev_bar = tk.Frame(parent, bg=C_SURFACE2, height=32)
        rev_bar.pack(fill="x", side="top")
        rev_bar.pack_propagate(False)
        tk.Label(rev_bar, text="Revision:", font=FONT_BOLD,
                 fg=C_TEXT, bg=C_SURFACE2).pack(side="left", padx=(10, 4), pady=4)
        self._rev_combo_var = tk.StringVar()
        self._rev_combo = ttk.Combobox(rev_bar, textvariable=self._rev_combo_var,
                                       values=["--"], width=18, font=FONT_SMALL,
                                       state="readonly")
        self._rev_combo.pack(side="left", padx=4, pady=4)
        self._rev_combo.bind("<<ComboboxSelected>>", self._on_rev_combo_change)

        self._rev_status_lbl = tk.Label(rev_bar, text="",
                                        font=FONT_SMALL, fg=C_MUTED, bg=C_SURFACE2)
        self._rev_status_lbl.pack(side="left", padx=8)

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill="x")

        # Inner tabs
        tabs_bar = tk.Frame(parent, bg=C_SURFACE3)
        tabs_bar.pack(fill="x", side="top")
        self._inner_tab_labels: dict = {}
        self._inner_tab_frames: dict = {}
        self._active_inner_tab = "files"

        inner_tabs = [("files", "FILES"), ("revisions", "REVISIONS"), ("details", "DETAILS")]
        for tab_key, tab_text in inner_tabs:
            lbl = tk.Label(tabs_bar, text=tab_text, font=FONT_BOLD,
                           fg=C_MUTED, bg=C_SURFACE3, padx=14, pady=5, cursor="hand2")
            lbl.pack(side="left")
            tk.Frame(tabs_bar, width=1, bg=C_BORDER).pack(side="left", fill="y")
            lbl.bind("<Button-1>", lambda e, k=tab_key: self._switch_inner_tab(k))
            self._inner_tab_labels[tab_key] = lbl

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill="x")

        tab_container = tk.Frame(parent, bg=C_BG)
        tab_container.pack(fill="both", expand=True)
        tab_container.grid_columnconfigure(0, weight=1)
        tab_container.grid_rowconfigure(0, weight=1)

        for tab_key in ("files", "revisions", "details"):
            tf = tk.Frame(tab_container, bg=C_BG)
            tf.grid(row=0, column=0, sticky="nsew")
            tf.grid_remove()
            self._inner_tab_frames[tab_key] = tf

        self._build_files_tab(self._inner_tab_frames["files"])
        self._build_revisions_tab(self._inner_tab_frames["revisions"])
        self._build_details_tab(self._inner_tab_frames["details"])
        self._switch_inner_tab("files")

    def _build_action_bar(self):
        ab = self._action_bar
        # Checkout
        if "datasets.checkout" in self.perms:
            self._btn_checkout = tk.Button(ab, text="🔒 Checkout",
                command=self._action_checkout,
                bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                padx=6, pady=2, cursor="hand2", activebackground=C_BLUE_HOV)
            self._btn_checkout.pack(side="left", padx=4, pady=4)
        else:
            self._btn_checkout = None

        # Checkin
        if "datasets.checkin_own" in self.perms or "datasets.checkin_any" in self.perms:
            self._btn_checkin = tk.Button(ab, text="🔓 Check In",
                command=self._action_checkin,
                bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                padx=6, pady=2, cursor="hand2", activebackground=C_SURFACE2)
            self._btn_checkin.pack(side="left", padx=2, pady=4)
        else:
            self._btn_checkin = None

        # Open
        tk.Button(ab, text="▶ Open", command=self._action_open,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=6, pady=2, cursor="hand2",
                  activebackground=C_SURFACE2).pack(side="left", padx=2, pady=4)

        tk.Frame(ab, width=1, bg=C_BORDER).pack(side="left", fill="y", pady=4)

        # Release / Lock
        if "revisions.release" in self.perms:
            tk.Button(ab, text="✓ Release", command=self._action_release_revision,
                      bg="#1a5c38", fg="#fff", relief="flat", font=FONT_SMALL,
                      padx=6, pady=2, cursor="hand2",
                      activebackground="#145c28").pack(side="left", padx=4, pady=4)
            tk.Button(ab, text="⊘ Lock", command=self._action_lock_revision,
                      bg="#7a5c00", fg="#fff", relief="flat", font=FONT_SMALL,
                      padx=6, pady=2, cursor="hand2",
                      activebackground="#5a4400").pack(side="left", padx=2, pady=4)

        # New Revision
        if "revisions.create" in self.perms:
            tk.Button(ab, text="+ Revision", command=self._dialog_new_revision,
                      bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                      padx=6, pady=2, cursor="hand2",
                      activebackground=C_SURFACE2).pack(side="left", padx=2, pady=4)

        tk.Frame(ab, width=1, bg=C_BORDER).pack(side="left", fill="y", pady=4)

        # Attach
        if "datasets.upload" in self.perms:
            tk.Button(ab, text="📎 Attach", command=self._action_attach,
                      bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                      padx=6, pady=2, cursor="hand2",
                      activebackground=C_SURFACE2).pack(side="left", padx=4, pady=4)

        # Delete item
        if "parts.delete" in self.perms:
            tk.Button(ab, text="🗑 Delete", command=self._action_delete_item,
                      bg=C_DANGER, fg="#fff", relief="flat", font=FONT_SMALL,
                      padx=6, pady=2, cursor="hand2",
                      activebackground="#a02020").pack(side="right", padx=4, pady=4)

        self._action_status_lbl = tk.Label(ab, text="", font=FONT_SMALL,
                                           fg=C_MUTED, bg=C_SURFACE2)
        self._action_status_lbl.pack(side="right", padx=8)

    def _switch_inner_tab(self, key: str):
        self._active_inner_tab = key
        for k, lbl in self._inner_tab_labels.items():
            if k == key:
                lbl.configure(fg="#ffffff", bg=C_BLUE_LT)
            else:
                lbl.configure(fg=C_MUTED, bg=C_SURFACE3)
        for k, tf in self._inner_tab_frames.items():
            if k == key:
                tf.grid()
            else:
                tf.grid_remove()

    # ---- Files tab ----

    def _build_files_tab(self, parent: tk.Frame):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        fcols = [
            ("filename",   "Filename",    200),
            ("file_type",  "Type",         60),
            ("size",       "Size",         70),
            ("added_by",   "Added By",    100),
            ("co_by",      "Checked Out",  110),
            ("modified",   "Status",        80),
        ]
        self._files_tree = _make_tree(parent, fcols, height=12)
        sb = _attach_vscroll(parent, self._files_tree)
        self._files_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._files_tree.bind("<<TreeviewSelect>>", self._on_file_select)
        self._files_tree.bind("<Double-Button-1>", lambda e: self._action_open())

    def _build_revisions_tab(self, parent: tk.Frame):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        rcols = [
            ("revision",    "Revision",  80),
            ("status",      "Status",    80),
            ("type",        "Type",      80),
            ("created_by",  "By",       100),
            ("created_at",  "Date",     130),
            ("description", "Notes",    220),
        ]
        self._revs_tree = _make_tree(parent, rcols, height=12)
        sb = _attach_vscroll(parent, self._revs_tree)
        self._revs_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

    def _build_details_tab(self, parent: tk.Frame):
        sf = tk.Frame(parent, bg=C_BG)
        sf.pack(fill="both", expand=True, padx=16, pady=12)

        fields = [("Item ID", "_det_item_id"), ("Name", "_det_name"),
                  ("Description", "_det_desc"), ("Type", "_det_type"),
                  ("Status", "_det_status"), ("Created By", "_det_created_by"),
                  ("Created At", "_det_created_at")]
        for label, attr in fields:
            row = tk.Frame(sf, bg=C_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{label}:", font=FONT_BOLD,
                     fg=C_MUTED, bg=C_BG, width=14, anchor="e").pack(side="left")
            lbl = tk.Label(row, text="—", font=FONT_SMALL,
                           fg=C_TEXT, bg=C_BG, anchor="w")
            lbl.pack(side="left", padx=8)
            setattr(self, attr, lbl)

    # ---- Load helpers ----

    def _load_item_header(self, item: dict):
        self._detail_id_lbl.configure(text=item["item_id"])
        self._detail_name_lbl.configure(text=item.get("name", ""))
        status = item.get("status", "")
        self._detail_status_lbl.configure(text=status,
                                          fg=STATUS_COLOR.get(status, C_MUTED))
        # Details tab
        for attr, key in [("_det_item_id", "item_id"), ("_det_name", "name"),
                           ("_det_desc", "description"), ("_det_type", "type_name"),
                           ("_det_status", "status"), ("_det_created_by", "created_by"),
                           ("_det_created_at", "created_at")]:
            if hasattr(self, attr):
                getattr(self, attr).configure(text=str(item.get(key, "—") or "—"))

    def _populate_rev_combo(self, revs: list):
        values = [r["revision"] for r in revs] if revs else ["—"]
        self._rev_combo.configure(values=values)
        # Revisions tab
        for row in self._revs_tree.get_children():
            self._revs_tree.delete(row)
        for i, r in enumerate(revs):
            tag = r.get("status", "")
            if tag not in ("released", "locked", "obsolete"):
                tag = "even" if i % 2 == 0 else "odd"
            self._revs_tree.insert("", "end", tags=(tag,),
                values=(r["revision"], r.get("status", ""),
                        r.get("revision_type", ""), r.get("created_by", ""),
                        str(r.get("created_at", ""))[:16],
                        r.get("change_description", "")))

    def _on_rev_combo_change(self, _event=None):
        chosen = self._rev_combo_var.get()
        rev = next((r for r in self._revs_cache if r["revision"] == chosen), None)
        if rev:
            self._selected_rev = rev
            status = rev.get("status", "")
            self._rev_status_lbl.configure(text=status,
                                           fg=STATUS_COLOR.get(status, C_MUTED))
            self._refresh_datasets(rev["id"])

    def _refresh_datasets(self, rev_id: int):
        def fetch():
            return self.db.get_datasets(rev_id)
        def populate(datasets):
            self._datasets_cache = datasets
            for row in self._files_tree.get_children():
                self._files_tree.delete(row)
            for i, ds in enumerate(datasets):
                co = self.db.get_checkout(ds["id"])
                co_by = co["who"] if co else ""
                # Modified badge
                modified = ""
                if co and co_by == self.username:
                    temp = Path(config.TEMP_BASE_PATH) / ds["filename"]
                    vault = Path(ds.get("stored_path", ""))
                    try:
                        if temp.exists() and vault.exists():
                            modified = "● Modified" if temp.stat().st_mtime > vault.stat().st_mtime else "Saved"
                        elif temp.exists():
                            modified = "● In Temp"
                    except OSError:
                        pass
                size_kb = f"{ds.get('file_size', 0) // 1024} KB"
                if co_by == self.username:
                    tag = "co_mine"
                elif co_by:
                    tag = "co_other"
                else:
                    tag = "even" if i % 2 == 0 else "odd"
                self._files_tree.insert("", "end", iid=str(ds["id"]), tags=(tag,),
                    values=(ds["filename"], ds.get("file_type", ""),
                            size_kb, ds.get("adder", ""), co_by, modified))
        self._run_async(fetch, on_done=populate)

    def _clear_datasets(self):
        for row in self._files_tree.get_children():
            self._files_tree.delete(row)
        self._datasets_cache = []

    def _on_file_select(self, _event):
        sel = self._files_tree.selection()
        if not sel:
            return
        ds_id = int(sel[0])
        ds = next((d for d in self._datasets_cache if d["id"] == ds_id), None)
        if ds:
            self._selected_dataset = ds

    def _get_selected_dataset(self):
        sel = self._files_tree.selection()
        if not sel:
            messagebox.showwarning("Select File", "Select a dataset first.")
            return None
        ds_id = int(sel[0])
        return next((d for d in self._datasets_cache if d["id"] == ds_id), None)

    # ---- Actions ----

    def _action_checkout(self):
        ds = self._get_selected_dataset()
        if not ds or not self._selected_item or not self._selected_rev:
            return

        def do():
            checkout_file(
                ds,
                self._selected_item["item_id"],
                self._selected_rev["revision"],
                self.username, self.db,
            )
            copy_children_to_temp(
                self._selected_item["id"], self.username, self.db, {ds["id"]}
            )
        def on_done(_):
            self._refresh_datasets(self._selected_rev["id"])
            self._refresh_parts_list()
            messagebox.showinfo("Checked Out",
                f"{ds['filename']} checked out to:\n{config.TEMP_BASE_PATH}")
        def on_err(e):
            messagebox.showerror("Checkout Failed", str(e))

        self._run_async(do, on_done=on_done, on_error=on_err)

    def _action_checkin(self):
        ds = self._get_selected_dataset()
        if not ds or not self._selected_item or not self._selected_rev:
            return
        co = self.db.get_checkout(ds["id"])
        if not co:
            messagebox.showwarning("Checkin", "File is not checked out.")
            return
        is_mine = co["who"] == self.username
        can_any = "datasets.checkin_any" in self.perms
        if not is_mine and not can_any:
            messagebox.showerror("Permission", f"File is checked out by {co['who']}.")
            return
        username_to_use = co["who"] if (not is_mine and can_any) else self.username

        def do():
            checkin_file(ds, self._selected_item["item_id"],
                         self._selected_rev["revision"], username_to_use, self.db)
        def on_done(_):
            self._refresh_datasets(self._selected_rev["id"])
            self._refresh_parts_list()
            messagebox.showinfo("Checked In", f"{ds['filename']} checked in.")
        def on_err(e):
            messagebox.showerror("Checkin Failed", str(e))

        self._run_async(do, on_done=on_done, on_error=on_err)

    def _action_open(self):
        ds = self._get_selected_dataset()
        if not ds:
            return
        co = self.db.get_checkout(ds["id"])
        if co and co["who"] == self.username:
            # Open writable temp copy
            path = Path(config.TEMP_BASE_PATH) / ds["filename"]
            if not path.exists():
                # Re-copy from vault
                vault = Path(ds["stored_path"])
                if vault.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(vault), str(path))
                    import stat as _stat
                    path.chmod(path.stat().st_mode | _stat.S_IWRITE)
                else:
                    messagebox.showerror("Open", f"Vault file not found:\n{vault}")
                    return
        else:
            # Open vault copy (read-only)
            path = Path(ds["stored_path"])
            if not path.exists():
                messagebox.showerror("Open", f"File not found:\n{path}")
                return
        try:
            os.startfile(str(path))
        except Exception as e:
            messagebox.showerror("Open Failed", str(e))

    def _action_attach(self):
        if not self._selected_rev:
            messagebox.showwarning("Attach", "Select an item and revision first.")
            return
        filepath = filedialog.askopenfilename(title="Select file to attach")
        if not filepath:
            return
        p = Path(filepath)
        vault_dir = config.VAULT_PATH / self._selected_rev["revision"]
        vault_dest = vault_dir / p.name

        # Check for conflict
        if vault_dest.exists():
            if not messagebox.askyesno("Conflict",
                    f"{p.name} already exists in revision {self._selected_rev['revision']}.\nOverwrite?"):
                return

        def do():
            vault_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(p), str(vault_dest))
            import stat as _stat
            try:
                vault_dest.chmod(vault_dest.stat().st_mode & ~_stat.S_IWRITE & ~_stat.S_IWGRP & ~_stat.S_IWOTH)
            except OSError:
                pass
            ds_id = self.db.add_dataset(
                self._selected_rev["id"], p.name, p.suffix.lower(),
                str(vault_dest), vault_dest.stat().st_size, self.username)
            self.db.write_audit("add_dataset", "dataset", str(ds_id),
                                self.username, f"Attached {p.name}")
            return ds_id
        def on_done(_):
            self._refresh_datasets(self._selected_rev["id"])
            messagebox.showinfo("Attached", f"{p.name} attached.")
        def on_err(e):
            messagebox.showerror("Attach Failed", str(e))

        self._run_async(do, on_done=on_done, on_error=on_err)

    def _action_release_revision(self):
        if not self._selected_rev:
            messagebox.showwarning("Release", "Select a revision first.")
            return
        if not messagebox.askyesno("Release Revision",
                f"Release revision {self._selected_rev['revision']}?"):
            return
        def do():
            self.db.release_revision(self._selected_rev["id"], self.username)
            self.db.write_audit("release", "item_revision",
                                str(self._selected_rev["id"]), self.username,
                                f"Released {self._selected_rev['revision']}")
        def on_done(_):
            self._on_parts_select(None)
            messagebox.showinfo("Released", f"Revision {self._selected_rev['revision']} released.")
        self._run_async(do, on_done=on_done)

    def _action_lock_revision(self):
        if not self._selected_rev:
            messagebox.showwarning("Lock", "Select a revision first.")
            return
        if not messagebox.askyesno("Lock Revision",
                f"Lock revision {self._selected_rev['revision']}?"):
            return
        def do():
            self.db.lock_revision(self._selected_rev["id"], self.username)
        def on_done(_):
            self._on_parts_select(None)
        self._run_async(do, on_done=on_done)

    def _action_delete_item(self):
        if not self._selected_item:
            return
        iid = self._selected_item["item_id"]
        if not messagebox.askyesno("Delete Item",
                f"Permanently delete {iid} and all its datasets?\nThis cannot be undone."):
            return
        def do():
            self.db.delete_item(self._selected_item["id"])
            self.db.write_audit("delete", "item", iid, self.username, f"Deleted {iid}")
        def on_done(_):
            self._selected_item = {}
            self._selected_rev  = {}
            self._detail_empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._refresh_parts_list()
        self._run_async(do, on_done=on_done)

    # ---- Dialogs ----

    def _dialog_new_item(self):
        dlg = _NewItemDialog(self, self.db, self.username)
        self.wait_window(dlg)
        if dlg.created:
            self._refresh_parts_list()

    def _dialog_new_revision(self):
        if not self._selected_item:
            messagebox.showwarning("New Revision", "Select an item first.")
            return
        dlg = _NewRevisionDialog(self, self.db, self._selected_item, self.username)
        self.wait_window(dlg)
        if dlg.created:
            self._on_parts_select(None)

    # ==================================================================
    # Screen: My Files
    # ==================================================================

    def _build_myfiles_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=C_BG)

        tbar = tk.Frame(f, bg="#2b5070", height=26)
        tbar.pack(fill="x", side="top")
        tbar.pack_propagate(False)
        tk.Label(tbar, text="MY FILES — CHECKED OUT & TEMP COPIES",
                 font=FONT_BOLD, fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)

        tb = tk.Frame(f, bg=C_SURFACE2, height=38)
        tb.pack(fill="x", side="top")
        tb.pack_propagate(False)
        tk.Frame(f, bg=C_BORDER, height=1).pack(fill="x", side="top")

        tk.Button(tb, text="↻ Refresh", command=self._refresh_myfiles,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=6, pady=6)
        tk.Button(tb, text="🗑 Clean Up All Temp Files", command=self._action_cleanup_temp,
                  bg=C_DANGER, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=8, pady=2, cursor="hand2",
                  activebackground="#a02020").pack(side="left", padx=4, pady=6)

        # Checked-out section
        tk.Label(f, text="  CHECKED OUT (writable)",
                 font=FONT_BOLD, fg="#7ab8e8", bg=C_BG,
                 anchor="w").pack(fill="x", padx=8, pady=(10, 2))

        co_frame = tk.Frame(f, bg=C_BG)
        co_frame.pack(fill="both", expand=True, padx=4)
        co_frame.grid_columnconfigure(0, weight=1)
        co_frame.grid_rowconfigure(0, weight=1)

        co_cols = [
            ("filename",  "File",       180),
            ("item_id",   "Item",        90),
            ("revision",  "Rev",         50),
            ("item_name", "Part Name",  160),
            ("modified",  "Status",      90),
            ("temp_path", "Temp Path",  260),
        ]
        self._co_tree = _make_tree(co_frame, co_cols, height=9)
        sb = _attach_vscroll(co_frame, self._co_tree)
        self._co_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        # Action buttons for checked-out
        co_btn_bar = tk.Frame(f, bg=C_SURFACE2, height=34)
        co_btn_bar.pack(fill="x", side="top")
        co_btn_bar.pack_propagate(False)
        tk.Button(co_btn_bar, text="▶ Open",
                  command=self._myfiles_open,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=6, pady=2, cursor="hand2").pack(side="left", padx=4, pady=4)
        tk.Button(co_btn_bar, text="💾 Save to Vault",
                  command=self._myfiles_disksave,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=6, pady=2, cursor="hand2").pack(side="left", padx=2, pady=4)
        tk.Button(co_btn_bar, text="🔓 Check In",
                  command=self._myfiles_checkin,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=6, pady=2, cursor="hand2",
                  activebackground=C_BLUE_HOV).pack(side="left", padx=2, pady=4)
        tk.Button(co_btn_bar, text="📂 New Revision",
                  command=self._myfiles_new_revision,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=6, pady=2, cursor="hand2").pack(side="left", padx=2, pady=4)

        tk.Frame(f, bg=C_BORDER, height=1).pack(fill="x")

        # Read-only children section
        tk.Label(f, text="  READ-ONLY CHILD COPIES",
                 font=FONT_BOLD, fg=C_MUTED, bg=C_BG,
                 anchor="w").pack(fill="x", padx=8, pady=(8, 2))

        ro_frame = tk.Frame(f, bg=C_BG)
        ro_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        ro_frame.grid_columnconfigure(0, weight=1)
        ro_frame.grid_rowconfigure(0, weight=1)

        ro_cols = [
            ("filename",  "File",      180),
            ("item_id",   "Item",       90),
            ("revision",  "Rev",        50),
            ("item_name", "Part Name", 200),
            ("temp_path", "Temp Path", 260),
        ]
        self._ro_tree = _make_tree(ro_frame, ro_cols, height=5)
        sb2 = _attach_vscroll(ro_frame, self._ro_tree)
        self._ro_tree.grid(row=0, column=0, sticky="nsew")
        sb2.grid(row=0, column=1, sticky="ns")

        return f

    def _refresh_myfiles(self):
        def fetch():
            return self.db.get_temp_files_for_user(self.username)
        def populate(rows):
            for row in self._co_tree.get_children():
                self._co_tree.delete(row)
            for row in self._ro_tree.get_children():
                self._ro_tree.delete(row)
            for i, tf in enumerate(rows):
                tag = "even" if i % 2 == 0 else "odd"
                temp = Path(tf.get("temp_path", ""))
                vault = Path(tf.get("stored_path", ""))
                modified = ""
                try:
                    if temp.exists() and vault.exists():
                        modified = "● Modified" if temp.stat().st_mtime > vault.stat().st_mtime else "Saved"
                    elif temp.exists():
                        modified = "In Temp"
                except OSError:
                    pass

                row_vals_co = (
                    tf.get("filename", ""), tf.get("item_id", ""),
                    tf.get("revision", ""), tf.get("item_name", ""),
                    modified, str(temp),
                )
                row_vals_ro = (
                    tf.get("filename", ""), tf.get("item_id", ""),
                    tf.get("revision", ""), tf.get("item_name", ""),
                    str(temp),
                )
                if tf.get("is_checked_out"):
                    self._co_tree.insert("", "end", iid=str(tf["id"]),
                                         tags=(tag,), values=row_vals_co)
                else:
                    self._ro_tree.insert("", "end", iid=str(tf["id"]),
                                         tags=(tag,), values=row_vals_ro)
        self._run_async(fetch, on_done=populate)

    def _myfiles_get_selected_tf(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Select a checked-out file first.")
            return None
        return sel[0]

    def _myfiles_open(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Open", "Select a file first.")
            return
        vals = self._co_tree.item(sel[0], "values")
        # values: filename, item_id, rev, item_name, modified, temp_path
        temp_path = Path(vals[5]) if len(vals) > 5 else None
        if temp_path and temp_path.exists():
            try:
                os.startfile(str(temp_path))
            except Exception as e:
                messagebox.showerror("Open Failed", str(e))
        else:
            messagebox.showerror("Open", f"Temp file not found:\n{temp_path}")

    def _myfiles_disksave(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Save", "Select a file first.")
            return
        vals = self._co_tree.item(sel[0], "values")
        filename = vals[0]
        item_id  = vals[1]
        revision = vals[2]
        ds = self._ds_from_filename_rev(filename, item_id, revision)
        if not ds:
            messagebox.showerror("Save", f"Could not find dataset for {filename}")
            return
        def do():
            disk_save(ds, item_id, revision, self.username, self.db)
        def on_done(_):
            self._refresh_myfiles()
            messagebox.showinfo("Saved", f"{filename} saved to vault (checkout retained).")
        def on_err(e):
            messagebox.showerror("Save Failed", str(e))
        self._run_async(do, on_done=on_done, on_error=on_err)

    def _myfiles_checkin(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("Check In", "Select a file first.")
            return
        vals = self._co_tree.item(sel[0], "values")
        filename = vals[0]
        item_id  = vals[1]
        revision = vals[2]
        ds = self._ds_from_filename_rev(filename, item_id, revision)
        if not ds:
            messagebox.showerror("Check In", f"Could not find dataset for {filename}")
            return
        def do():
            checkin_file(ds, item_id, revision, self.username, self.db)
        def on_done(_):
            self._refresh_myfiles()
            self._refresh_parts_list()
            messagebox.showinfo("Checked In", f"{filename} checked in.")
        def on_err(e):
            messagebox.showerror("Checkin Failed", str(e))
        self._run_async(do, on_done=on_done, on_error=on_err)

    def _myfiles_new_revision(self):
        sel = self._co_tree.selection()
        if not sel:
            messagebox.showwarning("New Revision", "Select a file first.")
            return
        vals = self._co_tree.item(sel[0], "values")
        filename = vals[0]
        item_id  = vals[1]
        revision = vals[2]
        ds = self._ds_from_filename_rev(filename, item_id, revision)
        if not ds:
            return
        item = self.db.get_item(item_id)
        if not item:
            return
        revs = self.db.get_revisions(item["id"])
        rev = next((r for r in revs if r["revision"] == revision), None)
        if not rev:
            return
        dlg = _SaveAsNewRevisionDialog(self, self.db, ds, item, rev, self.username)
        self.wait_window(dlg)
        if dlg.saved:
            self._refresh_myfiles()
            self._refresh_parts_list()

    def _ds_from_filename_rev(self, filename: str, item_id: str, revision: str):
        item = self.db.get_item(item_id)
        if not item:
            return None
        for rev in self.db.get_revisions(item["id"]):
            if rev["revision"] == revision:
                for ds in self.db.get_datasets(rev["id"]):
                    if ds["filename"] == filename:
                        return ds
        return None

    def _action_cleanup_temp(self):
        if not messagebox.askyesno("Clean Up",
                "Delete all temp files?\nUnsaved changes will be checked first."):
            return
        def do():
            return cleanup_user_temp(self.username, self.db, force=False)
        def on_done(result):
            if result.get("has_unsaved"):
                files = "\n".join(result.get("checked_out_files", []))
                if messagebox.askyesno("Unsaved Changes",
                        f"These files have unsaved changes:\n{files}\n\nForce delete?"):
                    def force_do():
                        return cleanup_user_temp(self.username, self.db, force=True)
                    self._run_async(force_do, on_done=lambda _: self._refresh_myfiles())
            else:
                self._refresh_myfiles()
                messagebox.showinfo("Cleaned Up", "All temp files removed.")
        self._run_async(do, on_done=on_done)

    # ==================================================================
    # Screen: Admin
    # ==================================================================

    def _build_admin_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=C_BG)

        tbar = tk.Frame(f, bg="#2b5070", height=26)
        tbar.pack(fill="x", side="top")
        tbar.pack_propagate(False)
        tk.Label(tbar, text="ADMINISTRATION",
                 font=FONT_BOLD, fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)

        # Sub-tab bar
        sub_tab_bar = tk.Frame(f, bg=C_SURFACE3)
        sub_tab_bar.pack(fill="x", side="top")
        self._admin_sub_tabs: dict = {}
        self._admin_sub_frames: dict = {}
        self._active_admin_tab = "users"

        for key, text in [("users", "USERS"), ("audit", "AUDIT LOG"), ("watcher", "WATCHER")]:
            lbl = tk.Label(sub_tab_bar, text=text, font=FONT_BOLD,
                           fg=C_MUTED, bg=C_SURFACE3, padx=14, pady=5, cursor="hand2")
            lbl.pack(side="left")
            tk.Frame(sub_tab_bar, width=1, bg=C_BORDER).pack(side="left", fill="y")
            lbl.bind("<Button-1>", lambda e, k=key: self._switch_admin_tab(k))
            self._admin_sub_tabs[key] = lbl

        tk.Frame(f, bg=C_BORDER, height=1).pack(fill="x")

        content = tk.Frame(f, bg=C_BG)
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        for key in ("users", "audit", "watcher"):
            tf = tk.Frame(content, bg=C_BG)
            tf.grid(row=0, column=0, sticky="nsew")
            tf.grid_remove()
            self._admin_sub_frames[key] = tf

        self._build_admin_users(self._admin_sub_frames["users"])
        self._build_admin_audit(self._admin_sub_frames["audit"])
        self._build_admin_watcher(self._admin_sub_frames["watcher"])
        self._switch_admin_tab("users")

        return f

    def _switch_admin_tab(self, key: str):
        self._active_admin_tab = key
        for k, lbl in self._admin_sub_tabs.items():
            lbl.configure(fg="#ffffff" if k == key else C_MUTED,
                          bg=C_BLUE_LT if k == key else C_SURFACE3)
        for k, tf in self._admin_sub_frames.items():
            if k == key:
                tf.grid()
            else:
                tf.grid_remove()
        if key == "audit":
            self._refresh_audit()

    def _build_admin_users(self, parent: tk.Frame):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        tb = tk.Frame(parent, bg=C_SURFACE2, height=36)
        tb.grid(row=0, column=0, columnspan=2, sticky="ew")
        tb.grid_propagate(False)
        tk.Button(tb, text="+ Add User", command=self._dialog_add_user,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=8, pady=6)
        tk.Button(tb, text="↻ Refresh", command=self._refresh_users,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=6, pady=2, cursor="hand2").pack(side="left", padx=4)

        ucols = [
            ("username",    "Username",   160),
            ("role",        "Role",        90),
            ("created_at",  "Created",    130),
            ("last_seen",   "Last Active", 130),
        ]
        uf = tk.Frame(parent, bg=C_BG)
        uf.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        uf.grid_columnconfigure(0, weight=1)
        uf.grid_rowconfigure(0, weight=1)

        self._users_tree = _make_tree(uf, ucols, height=16)
        sb = _attach_vscroll(uf, self._users_tree)
        self._users_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._users_tree.bind("<Double-Button-1>", self._on_user_dblclick)

        # Right-click menu
        self._users_menu = tk.Menu(self, tearoff=0, bg=C_SURFACE, fg=C_TEXT)
        self._users_menu.add_command(label="Set Password", command=self._action_set_password)
        self._users_menu.add_command(label="Change Role",  command=self._action_change_role)
        self._users_tree.bind("<Button-3>", self._show_users_menu)

    def _build_admin_audit(self, parent: tk.Frame):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        acols = [
            ("timestamp",   "Time",       140),
            ("username",    "User",        90),
            ("action",      "Action",      90),
            ("entity_type", "Entity",      80),
            ("entity_id",   "ID",          80),
            ("details",     "Details",    300),
        ]
        af = tk.Frame(parent, bg=C_BG)
        af.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        af.grid_columnconfigure(0, weight=1)
        af.grid_rowconfigure(0, weight=1)

        self._audit_tree = _make_tree(af, acols, height=22)
        sb = _attach_vscroll(af, self._audit_tree)
        self._audit_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

    def _build_admin_watcher(self, parent: tk.Frame):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        tb = tk.Frame(parent, bg=C_SURFACE2, height=36)
        tb.grid(row=0, column=0, sticky="ew")
        tb.grid_propagate(False)

        self._watcher_status_lbl = tk.Label(tb, text="● Stopped",
                                            font=FONT_BOLD, fg=C_DANGER, bg=C_SURFACE2)
        self._watcher_status_lbl.pack(side="left", padx=12, pady=6)

        self._watcher_start_btn = tk.Button(tb, text="▶ Start Watcher",
            command=self._start_watcher,
            bg=C_SUCCESS, fg="#000", relief="flat", font=FONT_SMALL,
            padx=8, pady=2, cursor="hand2")
        self._watcher_start_btn.pack(side="left", padx=4)

        self._watcher_stop_btn = tk.Button(tb, text="■ Stop Watcher",
            command=self._stop_watcher, state="disabled",
            bg=C_DANGER, fg="#fff", relief="flat", font=FONT_SMALL,
            padx=8, pady=2, cursor="hand2")
        self._watcher_stop_btn.pack(side="left", padx=4)

        tk.Label(tb, text=f"Vault: {config.VAULT_PATH}",
                 font=FONT_SMALL, fg=C_MUTED, bg=C_SURFACE2).pack(side="left", padx=16)

        log_f = tk.Frame(parent, bg=C_BG)
        log_f.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        log_f.grid_columnconfigure(0, weight=1)
        log_f.grid_rowconfigure(0, weight=1)

        self._log_text = tk.Text(log_f, bg="#0d1117", fg="#c9d1d9",
                                 font=FONT_MONO, state="disabled",
                                 relief="flat", bd=0, wrap="none")
        log_sb = ttk.Scrollbar(log_f, orient="vertical", command=self._log_text.yview,
                               style="Dark.Vertical.TScrollbar")
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.grid(row=0, column=0, sticky="nsew")
        log_sb.grid(row=0, column=1, sticky="ns")
        self._log_text.tag_configure("warn", foreground=C_WARNING)

    def _refresh_users(self):
        if not hasattr(self, "_users_tree"):
            return
        def fetch():
            return self.db.list_users()
        def populate(users):
            for row in self._users_tree.get_children():
                self._users_tree.delete(row)
            for i, u in enumerate(users):
                tag = "even" if i % 2 == 0 else "odd"
                self._users_tree.insert("", "end", iid=str(u["id"]), tags=(tag,),
                    values=(u["username"], u["role"],
                            str(u.get("created_at", ""))[:16],
                            str(u.get("last_seen", ""))[:16]))
        self._run_async(fetch, on_done=populate)

    def _refresh_audit(self):
        if not hasattr(self, "_audit_tree"):
            return
        def fetch():
            return self.db.get_audit_log()
        def populate(rows):
            for row in self._audit_tree.get_children():
                self._audit_tree.delete(row)
            for i, r in enumerate(rows):
                tag = "even" if i % 2 == 0 else "odd"
                self._audit_tree.insert("", "end", tags=(tag,),
                    values=(str(r.get("timestamp", ""))[:16],
                            r.get("username", ""), r.get("action", ""),
                            r.get("entity_type", ""), r.get("entity_id", ""),
                            r.get("details", "")))
        self._run_async(fetch, on_done=populate)

    def _on_user_dblclick(self, _event):
        self._action_set_password()

    def _show_users_menu(self, event):
        sel = self._users_tree.identify_row(event.y)
        if sel:
            self._users_tree.selection_set(sel)
            self._users_menu.post(event.x_root, event.y_root)

    def _action_set_password(self):
        sel = self._users_tree.selection()
        if not sel:
            return
        vals = self._users_tree.item(sel[0], "values")
        username = vals[0]
        new_pw = simpledialog.askstring("Set Password",
                                        f"New password for {username}:",
                                        show="*", parent=self)
        if not new_pw:
            return
        user_id = int(sel[0])
        def do():
            self.db.set_password(user_id, new_pw)
        self._run_async(do, on_done=lambda _: messagebox.showinfo(
            "Password Set", f"Password updated for {username}."))

    def _action_change_role(self):
        sel = self._users_tree.selection()
        if not sel:
            return
        vals = self._users_tree.item(sel[0], "values")
        username = vals[0]
        new_role = simpledialog.askstring("Change Role",
                                          f"New role for {username} (admin/user/readonly):",
                                          parent=self)
        if not new_role or new_role not in ("admin", "user", "readonly"):
            messagebox.showerror("Invalid Role", "Role must be admin, user, or readonly.")
            return
        def do():
            self.db.upsert_user(username, new_role)
        self._run_async(do, on_done=lambda _: (self._refresh_users(),
                                               messagebox.showinfo("Role Changed",
                                               f"{username} → {new_role}")))

    def _dialog_add_user(self):
        dlg = _AddUserDialog(self, self.db)
        self.wait_window(dlg)
        if dlg.created:
            self._refresh_users()

    # Watcher
    def _start_watcher(self):
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        try:
            from .watcher import FileWatcher
        except ImportError:
            messagebox.showerror("Watcher", "Watcher module not available.")
            return

        log_handler = GUILogHandler(self._log_q)
        log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                                    datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(log_handler)

        self._watcher_obj = FileWatcher(self.db)
        def run():
            self._watcher_obj.start()
        self._watcher_thread = threading.Thread(target=run, daemon=True)
        self._watcher_thread.start()
        self._watcher_status_lbl.configure(text="● Running", fg=C_SUCCESS)
        self._watcher_start_btn.configure(state="disabled")
        self._watcher_stop_btn.configure(state="normal")

    def _stop_watcher(self):
        if self._watcher_obj:
            try:
                self._watcher_obj.stop()
            except Exception:
                pass
            self._watcher_obj = None
        self._watcher_status_lbl.configure(text="● Stopped", fg=C_DANGER)
        self._watcher_start_btn.configure(state="normal")
        self._watcher_stop_btn.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                msg, is_warn = self._log_q.get_nowait()
                if hasattr(self, "_log_text"):
                    self._log_text.configure(state="normal")
                    self._log_text.insert("end", msg + "\n", "warn" if is_warn else "")
                    self._log_text.see("end")
                    self._log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(400, self._poll_log_queue)

    # ==================================================================
    # Screen: Settings
    # ==================================================================

    def _build_settings_screen(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=C_BG)

        tbar = tk.Frame(f, bg="#2b5070", height=26)
        tbar.pack(fill="x", side="top")
        tbar.pack_propagate(False)
        tk.Label(tbar, text="SETTINGS", font=FONT_BOLD,
                 fg="#e0eaf4", bg="#2b5070").pack(side="left", padx=10)

        card = tk.Frame(f, bg=C_SURFACE, bd=0)
        card.pack(fill="x", padx=24, pady=20)

        tk.Label(card, text="Configuration",
                 font=FONT_TITLE, fg="#7ab8e8", bg=C_SURFACE).pack(anchor="w", padx=16, pady=(12, 4))

        cfg = config.get_config()
        fields = [
            ("Vault Path",     cfg.get("VAULT_PATH", "—")),
            ("Database Path",  cfg.get("DB_PATH", "—")),
            ("Temp Path",      cfg.get("TEMP_BASE_PATH", "—")),
        ]
        for label, value in fields:
            row = tk.Frame(card, bg=C_SURFACE)
            row.pack(fill="x", padx=16, pady=4)
            tk.Label(row, text=f"{label}:", font=FONT_BOLD,
                     fg=C_MUTED, bg=C_SURFACE, width=16, anchor="e").pack(side="left")
            tk.Label(row, text=value, font=FONT_MONO,
                     fg=C_TEXT, bg=C_SURFACE, anchor="w").pack(side="left", padx=8)

        # Warnings
        warnings = config.validate_paths()
        if warnings:
            wcard = tk.Frame(f, bg="#3a1a1a", bd=0)
            wcard.pack(fill="x", padx=24, pady=4)
            tk.Label(wcard, text="⚠ Path Warnings",
                     font=FONT_BOLD, fg=C_WARNING, bg="#3a1a1a").pack(anchor="w", padx=16, pady=(8, 2))
            for w in warnings:
                tk.Label(wcard, text=f"  • {w}", font=FONT_SMALL,
                         fg=C_WARNING, bg="#3a1a1a").pack(anchor="w", padx=16, pady=2)
            tk.Frame(wcard, height=8, bg="#3a1a1a").pack()

        # Change password
        pw_card = tk.Frame(f, bg=C_SURFACE)
        pw_card.pack(fill="x", padx=24, pady=8)
        tk.Label(pw_card, text="Change Password",
                 font=FONT_TITLE, fg="#7ab8e8", bg=C_SURFACE).pack(anchor="w", padx=16, pady=(12, 4))

        pw_row = tk.Frame(pw_card, bg=C_SURFACE)
        pw_row.pack(fill="x", padx=16, pady=4)
        tk.Label(pw_row, text="New Password:", font=FONT_BOLD,
                 fg=C_MUTED, bg=C_SURFACE, width=16, anchor="e").pack(side="left")
        self._new_pw_var = tk.StringVar()
        tk.Entry(pw_row, textvariable=self._new_pw_var, show="*", width=24,
                 font=FONT_SMALL, bg=C_SURFACE3, fg=C_TEXT,
                 insertbackground=C_TEXT, relief="flat").pack(side="left", padx=8)
        tk.Button(pw_row, text="Update",
                  command=self._action_change_own_password,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=8, cursor="hand2").pack(side="left", padx=4)

        tk.Frame(pw_card, height=8, bg=C_SURFACE).pack()

        tk.Label(f, text=f"PLM Lite v{_VERSION}  ·  MIT License",
                 font=FONT_SMALL, fg=C_MUTED, bg=C_BG).pack(anchor="w", padx=24, pady=8)

        return f

    def _action_change_own_password(self):
        new_pw = self._new_pw_var.get()
        if not new_pw:
            messagebox.showwarning("Password", "Enter a new password.")
            return
        def do():
            self.db.set_password(self.user["id"], new_pw)
        def on_done(_):
            self._new_pw_var.set("")
            messagebox.showinfo("Password Updated", "Your password has been changed.")
        self._run_async(do, on_done=on_done)

    # ==================================================================
    # Sign Out
    # ==================================================================

    def _sign_out(self):
        if self._watcher_obj:
            self._stop_watcher()
        self.destroy()
        login = LoginWindow()
        login.mainloop()
        if login.authenticated_user:
            app = App(login.authenticated_user)
            app.mainloop()


# ==================================================================
# Dialogs
# ==================================================================

class _NewItemDialog(tk.Toplevel):
    def __init__(self, master, db: Database, username: str):
        super().__init__(master)
        self.db = db
        self.username = username
        self.created = False
        self.title("New Item")
        self.geometry("420x280")
        self.resizable(False, False)
        self.configure(bg=C_BG)
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Create New Item", font=FONT_TITLE,
                 fg="#7ab8e8", bg=C_BG).pack(pady=(16, 8))

        form = tk.Frame(self, bg=C_BG)
        form.pack(fill="x", padx=24)

        self._name_var = tk.StringVar()
        self._desc_var = tk.StringVar()
        self._type_var = tk.StringVar(value="Part")

        for label, var, is_combo in [
            ("Name *",     self._name_var, False),
            ("Description", self._desc_var, False),
            ("Type",        self._type_var, True),
        ]:
            row = tk.Frame(form, bg=C_BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=FONT_SMALL, fg=C_MUTED, bg=C_BG,
                     width=14, anchor="e").pack(side="left")
            if is_combo:
                ttk.Combobox(row, textvariable=var,
                             values=["Part", "Assembly", "Drawing", "Document"],
                             width=22, font=FONT_SMALL, state="readonly").pack(side="left", padx=8)
            else:
                tk.Entry(row, textvariable=var, width=24,
                         font=FONT_SMALL, bg=C_SURFACE3, fg=C_TEXT,
                         insertbackground=C_TEXT, relief="flat").pack(side="left", padx=8)

        btn_row = tk.Frame(self, bg=C_BG)
        btn_row.pack(pady=16)
        tk.Button(btn_row, text="Create", command=self._do_create,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left")

    def _do_create(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Required", "Name is required.", parent=self)
            return
        type_map = {"Part": 1, "Assembly": 2, "Drawing": 3, "Document": 4}
        type_id = type_map.get(self._type_var.get(), 1)
        item_id = self.db.next_item_id()
        self.db.create_item(item_id, name, self._desc_var.get(), type_id, self.username)
        self.db.create_revision(
            self.db.get_item(item_id)["id"], "A", "alpha", self.username)
        self.db.write_audit("create", "item", item_id, self.username, f"Created {name}")
        self.created = True
        self.destroy()


class _NewRevisionDialog(tk.Toplevel):
    def __init__(self, master, db: Database, item: dict, username: str):
        super().__init__(master)
        self.db = db
        self.item = item
        self.username = username
        self.created = False
        self.title("New Revision")
        self.geometry("400x240")
        self.resizable(False, False)
        self.configure(bg=C_BG)
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text=f"New Revision — {self.item['item_id']}",
                 font=FONT_TITLE, fg="#7ab8e8", bg=C_BG).pack(pady=(16, 8))

        form = tk.Frame(self, bg=C_BG)
        form.pack(fill="x", padx=24)

        self._type_var = tk.StringVar(value="alpha")
        self._desc_var = tk.StringVar()

        for label, widget_fn in [
            ("Revision Type", lambda r: ttk.Combobox(r, textvariable=self._type_var,
                values=["alpha", "numeric"], width=14, state="readonly")),
            ("Change Notes",  lambda r: tk.Entry(r, textvariable=self._desc_var,
                width=24, font=FONT_SMALL, bg=C_SURFACE3, fg=C_TEXT,
                insertbackground=C_TEXT, relief="flat")),
        ]:
            row = tk.Frame(form, bg=C_BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=FONT_SMALL, fg=C_MUTED, bg=C_BG,
                     width=14, anchor="e").pack(side="left")
            widget_fn(row).pack(side="left", padx=8)

        btn_row = tk.Frame(self, bg=C_BG)
        btn_row.pack(pady=16)
        tk.Button(btn_row, text="Create", command=self._do_create,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left")

    def _do_create(self):
        rtype = self._type_var.get()
        label = self.db.next_revision(self.item["id"], rtype)
        rev_pk = self.db.create_revision(self.item["id"], label, rtype, self.username)
        if self._desc_var.get():
            self.db.update_revision_description(rev_pk, self._desc_var.get())
        self.db.write_audit("create_revision", "item_revision", str(rev_pk),
                            self.username, f"Created revision {label}")
        self.created = True
        self.destroy()


class _AddUserDialog(tk.Toplevel):
    def __init__(self, master, db: Database):
        super().__init__(master)
        self.db = db
        self.created = False
        self.title("Add User")
        self.geometry("380x260")
        self.resizable(False, False)
        self.configure(bg=C_BG)
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Add New User", font=FONT_TITLE,
                 fg="#7ab8e8", bg=C_BG).pack(pady=(16, 8))

        form = tk.Frame(self, bg=C_BG)
        form.pack(fill="x", padx=24)

        self._uname_var = tk.StringVar()
        self._role_var  = tk.StringVar(value="user")
        self._pw_var    = tk.StringVar()

        for label, var, is_combo, show in [
            ("Username *", self._uname_var, False, ""),
            ("Role",       self._role_var,  True,  ""),
            ("Password *", self._pw_var,    False, "*"),
        ]:
            row = tk.Frame(form, bg=C_BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=FONT_SMALL, fg=C_MUTED, bg=C_BG,
                     width=12, anchor="e").pack(side="left")
            if is_combo:
                ttk.Combobox(row, textvariable=var,
                             values=["admin", "user", "readonly"],
                             width=16, state="readonly").pack(side="left", padx=8)
            else:
                tk.Entry(row, textvariable=var, width=20, show=show,
                         font=FONT_SMALL, bg=C_SURFACE3, fg=C_TEXT,
                         insertbackground=C_TEXT, relief="flat").pack(side="left", padx=8)

        self._err_lbl = tk.Label(self, text="", font=FONT_SMALL,
                                 fg=C_DANGER, bg=C_BG)
        self._err_lbl.pack()

        btn_row = tk.Frame(self, bg=C_BG)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Create", command=self._do_create,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left")

    def _do_create(self):
        username = self._uname_var.get().strip()
        password = self._pw_var.get()
        role     = self._role_var.get()
        if not username or not password:
            self._err_lbl.configure(text="Username and password required.")
            return
        try:
            uid = self.db.upsert_user(username, role)
            self.db.set_password(uid, password)
            self.created = True
            self.destroy()
        except Exception as e:
            self._err_lbl.configure(text=str(e))


class _SaveAsNewRevisionDialog(tk.Toplevel):
    def __init__(self, master, db: Database, dataset: dict, item: dict,
                 current_rev: dict, username: str):
        super().__init__(master)
        self.db = db
        self.dataset = dataset
        self.item = item
        self.current_rev = current_rev
        self.username = username
        self.saved = False
        self.title("Save as New Revision")
        self.geometry("400x220")
        self.resizable(False, False)
        self.configure(bg=C_BG)
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text=f"Save as New Revision — {self.dataset['filename']}",
                 font=FONT_TITLE, fg="#7ab8e8", bg=C_BG).pack(pady=(16, 8))

        form = tk.Frame(self, bg=C_BG)
        form.pack(fill="x", padx=24)

        self._type_var = tk.StringVar(value=self.current_rev.get("revision_type", "alpha"))
        self._desc_var = tk.StringVar()

        for label, widget_fn in [
            ("Revision Type", lambda r: ttk.Combobox(r, textvariable=self._type_var,
                values=["alpha", "numeric"], width=14, state="readonly")),
            ("Change Notes",  lambda r: tk.Entry(r, textvariable=self._desc_var,
                width=24, font=FONT_SMALL, bg=C_SURFACE3, fg=C_TEXT,
                insertbackground=C_TEXT, relief="flat")),
        ]:
            row = tk.Frame(form, bg=C_BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=FONT_SMALL, fg=C_MUTED, bg=C_BG,
                     width=14, anchor="e").pack(side="left")
            widget_fn(row).pack(side="left", padx=8)

        btn_row = tk.Frame(self, bg=C_BG)
        btn_row.pack(pady=16)
        tk.Button(btn_row, text="Save as New Rev", command=self._do_save,
                  bg=C_BLUE, fg="#fff", relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  bg=C_SURFACE3, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=12, cursor="hand2").pack(side="left")

    def _do_save(self):
        from .checkout import save_as_new_revision
        try:
            save_as_new_revision(
                self.dataset, self.item, self.current_rev,
                self.username, self.db,
                change_description=self._desc_var.get(),
                revision_type=self._type_var.get(),
            )
            self.saved = True
            self.destroy()
        except CheckoutError as e:
            messagebox.showerror("Save Failed", str(e), parent=self)


# ==================================================================
# Entry point
# ==================================================================

def launch():
    login = LoginWindow()
    login.mainloop()
    if login.authenticated_user:
        app = App(login.authenticated_user)
        app.mainloop()
