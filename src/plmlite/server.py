"""PLM Lite v2.1.0 — FastAPI web server.

Serves the TC8-themed frontend from src/plmlite/static/ and exposes a JSON
API backed by the existing Database, checkout, and watcher modules.

Windows auto-login: username is read from os.environ['USERNAME'] — no auth
form is shown, since this server runs locally on a Windows workstation.

Start with:
    python -m uvicorn plmlite.server:app --host 0.0.0.0 --port 8080
or via the convenience launcher:
    start_server.bat
"""

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .database import Database, CheckoutError
from .watcher import FileWatcher

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
APP_HTML   = STATIC_DIR / "app.html"

app = FastAPI(title="PLM Lite", version="2.1.0")
db  = Database()

_username: str = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
_watcher: Optional[FileWatcher]  = None
_watcher_thread: Optional[threading.Thread] = None


# ── Startup / shutdown ───────────────────────────────────────────────────────

@app.on_event("startup")
def startup() -> None:
    global _watcher, _watcher_thread
    db.initialize()
    db.upsert_user(_username)

    try:
        _watcher = FileWatcher(db_path=config.DB_PATH)
        _watcher_thread = threading.Thread(target=_watcher.start, daemon=True)
        _watcher_thread.start()
        logger.info("Watcher started on %s", config.WATCH_PATH)
    except Exception as e:
        logger.warning("Watcher failed to start: %s", e)
    logger.info("PLM Lite v2.1 started as %s", _username)


# ── Static files & app shell ─────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=RedirectResponse, include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/app")


@app.get("/app", response_class=HTMLResponse, include_in_schema=False)
def get_app() -> HTMLResponse:
    return HTMLResponse(APP_HTML.read_text(encoding="utf-8"))


# ── Current user ─────────────────────────────────────────────────────────────

@app.get("/api/me")
def get_me() -> dict:
    users = db.list_users()
    user  = next((u for u in users if u["username"] == _username), None)
    if not user:
        db.upsert_user(_username)
        users = db.list_users()
        user  = next((u for u in users if u["username"] == _username), None)
    return {
        "id":       user["id"] if user else 0,
        "username": _username,
        "role":     user["role"] if user else "admin",
    }


# ── Items (Parts) ─────────────────────────────────────────────────────────────

def _latest_rev(item_pk: int) -> Optional[dict]:
    revs = db.get_revisions(item_pk)
    return revs[-1] if revs else None


def _item_checkout(item_pk: int) -> Optional[str]:
    """Return username of whoever has any dataset in the latest rev checked out."""
    rev = _latest_rev(item_pk)
    if not rev:
        return None
    for ds in db.get_datasets(rev["id"]):
        if ds.get("checked_out_by"):
            return ds["checked_out_by"]
    return None


def _item_summary(item: dict) -> dict:
    rev = _latest_rev(item["id"])
    return {
        "id":               item["id"],
        "item_id":          item["item_id"],
        "name":             item["name"],
        "description":      item.get("description", ""),
        "status":           item["status"],
        "type_name":        item.get("type_name", ""),
        "latest_rev":       rev["revision"] if rev else "—",
        "latest_rev_id":    rev["id"] if rev else None,
        "latest_rev_status":rev["status"] if rev else None,
        "checked_out_by":   _item_checkout(item["id"]),
        "creator":          item.get("creator", ""),
        "created_at":       item.get("created_at", ""),
    }


@app.get("/api/items")
def list_items(
    search:            str  = "",
    status:            str  = "",
    checked_out_only:  bool = False,
    page:              int  = 1,
    per_page:          int  = 50,
) -> dict:
    all_items = db.list_items(status_filter=status or None)
    if search:
        sl = search.lower()
        all_items = [i for i in all_items
                     if sl in i["item_id"].lower() or sl in i["name"].lower()]
    summaries = [_item_summary(i) for i in all_items]
    if checked_out_only:
        summaries = [s for s in summaries if s["checked_out_by"]]
    total = len(summaries)
    start = (page - 1) * per_page
    return {"items": summaries[start:start + per_page], "total": total,
            "page": page, "per_page": per_page}


@app.get("/api/items/{item_id}")
def get_item(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    return _item_summary(item)


class NewItemBody(BaseModel):
    name:        str
    description: str = ""
    item_type:   str = "Mechanical Part"


@app.post("/api/items", status_code=201)
def create_item(body: NewItemBody) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    itype = (db.get_item_type_by_name(body.item_type)
             or db.get_item_type_by_name("Mechanical Part"))
    itype_id = itype["id"] if itype else 1
    new_id   = db.next_item_id()
    item_pk  = db.create_item(new_id, body.name.strip(), body.description, itype_id, _username)
    rev_lbl  = db.next_revision(item_pk, "alpha")
    db.create_revision(item_pk, rev_lbl, "alpha", _username)
    db.write_audit("create", "item", new_id, _username, f"Created via web UI: {body.name}")
    return {"item_id": new_id, "message": f"Item {new_id} created"}


class UpdateItemBody(BaseModel):
    name:        Optional[str] = None
    description: Optional[str] = None


@app.put("/api/items/{item_id}")
def update_item(item_id: str, body: UpdateItemBody) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    with db._connect() as conn:
        if body.name is not None:
            conn.execute("UPDATE items SET name=? WHERE item_id=?",
                         (body.name.strip(), item_id))
        if body.description is not None:
            conn.execute("UPDATE items SET description=? WHERE item_id=?",
                         (body.description, item_id))
        conn.commit()
    db.write_audit("update", "item", item_id, _username, "Updated via web UI")
    return {"message": "Updated"}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    with db._connect() as conn:
        conn.execute("DELETE FROM items WHERE item_id=?", (item_id,))
        conn.commit()
    db.write_audit("delete", "item", item_id, _username, "Deleted via web UI")
    return {"message": "Deleted"}


def _get_item_row(item_id: str) -> dict:
    row = db.get_item(item_id)
    if not row:
        raise HTTPException(404, f"Item {item_id} not found")
    return row


@app.patch("/api/items/{item_id}")
def patch_item(item_id: str, body: dict = Body(...)):
    row = _get_item_row(item_id)
    # Handle type change
    if 'item_type' in body:
        with db._connect() as conn:
            t = conn.execute("SELECT id FROM item_types WHERE name=?", (body['item_type'],)).fetchone()
            if t:
                conn.execute("UPDATE items SET item_type_id=? WHERE id=?", (t['id'], row['id']))
    db.update_item(row['id'],
                   name=body.get('name'),
                   description=body.get('description'),
                   item_id=body.get('item_id'))
    return {"message": "Updated"}


@app.get("/api/items/{item_id}/attributes")
def get_attrs(item_id: str):
    row = _get_item_row(item_id)
    return db.get_attributes(row['id'])


@app.post("/api/items/{item_id}/attributes")
def set_attr(item_id: str, body: dict = Body(...)):
    row = _get_item_row(item_id)
    db.set_attribute(row['id'], body['key'], body.get('value', ''))
    return {"message": "Saved"}


@app.delete("/api/items/{item_id}/attributes/{key}")
def del_attr(item_id: str, key: str):
    row = _get_item_row(item_id)
    db.delete_attribute(row['id'], key)
    return {"message": "Deleted"}


@app.patch("/api/items/{item_id}/revisions/{rev_id}")
def patch_revision(item_id: str, rev_id: int, body: dict = Body(...)):
    db.update_revision_description(rev_id, body.get('change_description', ''))
    return {"message": "Saved"}


# ── Item-level checkout / checkin / release ──────────────────────────────────

@app.post("/api/items/{item_id}/checkout")
def checkout_item(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision exists for this item")
    datasets = db.get_datasets(rev["id"])
    if not datasets:
        raise HTTPException(400, "No datasets to check out (add files via watcher first)")
    errors = []
    for ds in datasets:
        try:
            db.checkout_dataset(ds["id"], _username,
                                station_name=os.environ.get("COMPUTERNAME", ""),
                                lock_file_path="")
        except CheckoutError as e:
            errors.append(str(e))
    if errors:
        raise HTTPException(409, "; ".join(errors))
    db.write_audit("checkout", "item", item_id, _username, "Checked out via web UI")
    return {"message": "Checked out"}


@app.post("/api/items/{item_id}/checkin")
def checkin_item(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision found")
    for ds in db.get_datasets(rev["id"]):
        try:
            db.checkin_dataset(ds["id"], _username)
        except CheckoutError:
            pass  # already checked in or owned by someone else — skip
    db.write_audit("checkin", "item", item_id, _username, "Checked in via web UI")
    return {"message": "Checked in"}


@app.post("/api/items/{item_id}/release")
def release_item(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision found")
    db.release_revision(rev["id"], _username)
    db.set_item_status(item["id"], "released")
    db.write_audit("release", "item", item_id, _username,
                   f"Released revision {rev['revision']} via web UI")
    return {"message": f"Item {item_id} released"}


# ── Revisions ────────────────────────────────────────────────────────────────

@app.get("/api/items/{item_id}/revisions")
def list_revisions(item_id: str) -> list:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    return db.get_revisions(item["id"])


@app.post("/api/items/{item_id}/revisions", status_code=201)
def new_revision(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev_lbl = db.next_revision(item["id"], "alpha")
    rev_pk  = db.create_revision(item["id"], rev_lbl, "alpha", _username)
    db.write_audit("new_revision", "item_revision", str(rev_pk), _username,
                   f"New revision {rev_lbl} for {item_id}")
    return {"revision": rev_lbl, "id": rev_pk}


# ── Datasets ─────────────────────────────────────────────────────────────────

@app.get("/api/items/{item_id}/datasets")
def list_datasets(item_id: str) -> list:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        return []
    return db.get_datasets(rev["id"])


@app.get("/api/items/{item_id}/datasets/{ds_id}/open")
def open_dataset(item_id: str, ds_id: int) -> dict:
    """Open a file in its registered Windows application via os.startfile()."""
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    ds = None
    for rev in db.get_revisions(item["id"]):
        for d in db.get_datasets(rev["id"]):
            if d["id"] == ds_id:
                ds = d
                break
        if ds:
            break
    if not ds:
        raise HTTPException(404, "Dataset not found")
    path = Path(ds["stored_path"])
    if not path.exists():
        raise HTTPException(404, f"File not found on disk: {ds['stored_path']}")
    os.startfile(str(path))
    db.write_audit("open", "dataset", str(ds_id), _username,
                   f"Opened via web UI: {ds['filename']}")
    return {"message": f"Opening {path.name}"}


# ── BOM ──────────────────────────────────────────────────────────────────────

def _build_bom(item_pk: int, visited: set) -> dict:
    with db._connect() as conn:
        cur = conn.execute(
            "SELECT id, item_id, name, status FROM items WHERE id=?",
            (item_pk,)
        )
        row = cur.fetchone()
        item = dict(row) if row else None
    if not item:
        return {}
    visited.add(item_pk)
    children = []
    for c in db.get_children(item_pk):
        if c["id"] not in visited:
            child_node = _build_bom(c["id"], set(visited))
            if child_node:
                child_node["quantity"] = c.get("quantity", 1)
                children.append(child_node)
    return {
        "id":       item["id"],
        "item_id":  item["item_id"],
        "name":     item["name"],
        "status":   item["status"],
        "children": children,
    }


@app.get("/api/items/{item_id}/bom")
def get_bom(item_id: str) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    return _build_bom(item["id"], set())


@app.get("/api/items/{item_id}/where-used")
def where_used(item_id: str) -> list:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    return [
        {"id": p["id"], "item_id": p["item_id"], "name": p["name"], "status": p["status"]}
        for p in db.get_parents(item["id"])
    ]


# ── Relationships ─────────────────────────────────────────────────────────────

class RelBody(BaseModel):
    parent_item_id: int
    child_item_id:  int
    quantity:       int = 1


@app.post("/api/relationships", status_code=201)
def add_relationship(body: RelBody) -> dict:
    if body.parent_item_id == body.child_item_id:
        raise HTTPException(400, "Parent and child cannot be the same item")
    db.add_relationship(body.parent_item_id, body.child_item_id, body.quantity, _username)
    db.write_audit("add_relationship", "item", str(body.parent_item_id), _username,
                   f"Added child pk {body.child_item_id} qty={body.quantity}")
    return {"message": "Relationship added"}


# ── All datasets (for Documents panel) ───────────────────────────────────────

@app.get("/api/datasets")
def list_all_datasets(search: str = "") -> list:
    with db._connect() as conn:
        cur = conn.execute(
            """SELECT d.id, d.filename, d.file_type, d.stored_path,
                      d.file_size, d.added_at,
                      u.username  AS adder,
                      i.item_id, i.name AS item_name,
                      r.revision,
                      cu.username AS checked_out_by
               FROM datasets d
               JOIN item_revisions r ON r.id = d.revision_id
               JOIN items i          ON i.id = r.item_id
               JOIN users u          ON u.id = d.added_by
               LEFT JOIN checkouts c  ON c.dataset_id = d.id
               LEFT JOIN users cu     ON cu.id = c.checked_out_by
               ORDER BY d.filename"""
        )
        rows = [dict(r) for r in cur.fetchall()]
    if search:
        sl = search.lower()
        rows = [r for r in rows
                if sl in r["filename"].lower() or sl in r["item_id"].lower()
                or sl in (r["item_name"] or "").lower()]
    return rows


# ── Users ─────────────────────────────────────────────────────────────────────

@app.get("/api/users")
def list_users() -> list:
    return db.list_users()


class NewUserBody(BaseModel):
    username: str
    role:     str = "user"


@app.post("/api/users", status_code=201)
def create_user(body: NewUserBody) -> dict:
    if not body.username.strip():
        raise HTTPException(400, "username is required")
    if body.role not in ("admin", "user", "readonly"):
        raise HTTPException(400, "role must be admin, user, or readonly")
    db.upsert_user(body.username.strip(), body.role)
    return {"message": f"User {body.username} created/updated"}


@app.put("/api/users/{user_id}")
def update_user(user_id: int, body: dict) -> dict:
    role = body.get("role")
    if role and role not in ("admin", "user", "readonly"):
        raise HTTPException(400, "invalid role")
    with db._connect() as conn:
        if role:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        conn.commit()
    return {"message": "Updated"}


# ── Audit log ─────────────────────────────────────────────────────────────────

@app.get("/api/audit")
def get_audit(item_id: Optional[str] = None) -> list:
    if item_id:
        return db.get_audit_log_for_item(item_id)
    return db.get_audit_log()


# ── Server status ─────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status() -> dict:
    return {
        "version":        "2.1.0",
        "username":       _username,
        "watcher_running": _watcher_thread is not None and _watcher_thread.is_alive(),
        "db_path":        str(config.DB_PATH),
        "watch_configs":  config.get_watch_configs(),
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

def run() -> None:
    """Launched by `plmlite-server` console script."""
    import uvicorn
    uvicorn.run("plmlite.server:app", host="0.0.0.0", port=8080, log_level="info")
