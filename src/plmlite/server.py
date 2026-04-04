"""PLM Lite v2.2 — FastAPI web server with username/password auth and RBAC.

Session cookies authenticate every /api/* request.
Built-in roles: admin (all perms), user (most perms), readonly (read-only).
Custom roles stored in role_permissions table.

Start with:
    python -m uvicorn plmlite.server:app --host 0.0.0.0 --port 8080
or via the convenience launcher:
    start_server.bat
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from typing import List as _List
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .parser import parse_nx_file
from .checkout import (
    checkout_file,
    checkin_file,
    copy_children_to_temp,
    disk_save,
    save_as_new_revision,
    cleanup_user_temp,
    get_temp_dir,
)
from .database import Database, CheckoutError
from .watcher import FileWatcher

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
APP_HTML   = STATIC_DIR / "app.html"
LOGIN_HTML = STATIC_DIR / "login.html"

SESSION_COOKIE = "plm_session"

app = FastAPI(title="PLM Lite", version="2.2.0")
db  = Database()

# Kept for the watcher process (starts before any request context exists)
_username: str = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
_watcher: Optional[FileWatcher] = None


# ── Startup / shutdown ───────────────────────────────────────────────────────

@app.on_event("startup")
def startup() -> None:
    global _watcher
    db.initialize()

    # Ensure backdoor admin account
    db.upsert_user("admin", "admin")
    admin_user = db._get_user_by_username("admin")
    if admin_user and not admin_user.get("password_hash"):
        db.set_password(admin_user["id"], "password123")

    # Ensure watcher user exists
    db.upsert_user(_username)

    try:
        _watcher = FileWatcher(db_path=str(config.DB_PATH))
        _watcher.start()
        logger.info("FileWatcher started")
    except Exception as exc:
        logger.warning("Watcher failed to start: %s", exc)

    logger.info("PLM Lite v2.2 started as %s", _username)


@app.on_event("shutdown")
def shutdown() -> None:
    if _watcher:
        _watcher.stop()


# ── Auth helpers ─────────────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Not authenticated")
    user = db.get_session_user(token)
    if not user:
        raise HTTPException(401, "Session expired")
    return user


def require_permission(perm: str) -> Callable:
    def checker(user: dict = Depends(get_current_user)) -> dict:
        perms = db.get_role_permissions(user["role"])
        if perm not in perms:
            raise HTTPException(403, f"Permission denied: {perm}")
        return user
    return checker


# ── Static files & app shell ─────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=RedirectResponse, include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/app")


@app.get("/app", include_in_schema=False)
def get_app(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not db.get_session_user(token):
        return RedirectResponse(url="/login")
    return HTMLResponse(APP_HTML.read_text(encoding="utf-8"))


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def get_login() -> HTMLResponse:
    return HTMLResponse(LOGIN_HTML.read_text(encoding="utf-8"))


# ── Auth routes ───────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def auth_login(body: LoginBody, response: Response) -> dict:
    user = db.verify_password(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = db.create_session(user["id"])
    response.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="lax", max_age=86400 * 30,
    )
    perms = list(db.get_role_permissions(user["role"]))
    return {
        "id":          user["id"],
        "username":    user["username"],
        "role":        user["role"],
        "permissions": perms,
    }


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"message": "Logged out"}


# ── Current user ─────────────────────────────────────────────────────────────

@app.get("/api/me")
def get_me(user: dict = Depends(get_current_user)) -> dict:
    perms = list(db.get_role_permissions(user["role"]))
    return {
        "id":          user["id"],
        "username":    user["username"],
        "role":        user["role"],
        "permissions": perms,
    }


@app.get("/api/me/temp")
def get_my_temp(user: dict = Depends(get_current_user)) -> list:
    username = user["username"]
    files = db.get_temp_files_for_user(username)
    result = []
    for tf in files:
        ds_id    = tf.get("dataset_id")
        modified = _watcher.get_modified_status(ds_id) if (_watcher and ds_id) else False
        result.append({**tf, "modified": modified})
    return result


@app.delete("/api/me/temp")
def clear_my_temp(force: bool = Query(False),
                  user: dict = Depends(get_current_user)) -> dict:
    return cleanup_user_temp(user["username"], db, force=force)


@app.post("/api/me/logout")
def me_logout(user: dict = Depends(get_current_user)) -> dict:
    """Force-clean temp files and clear the in-memory watcher state."""
    cleanup_user_temp(user["username"], db, force=True)
    return {"message": "Logged out and temp cleared"}


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password:     str


@app.post("/api/me/password")
def change_my_password(body: ChangePasswordBody,
                       user: dict = Depends(get_current_user)) -> dict:
    if not db.verify_password(user["username"], body.current_password):
        raise HTTPException(400, "Current password is incorrect")
    db.set_password(user["id"], body.new_password)
    return {"message": "Password changed"}


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
        "id":                item["id"],
        "item_id":           item["item_id"],
        "name":              item["name"],
        "description":       item.get("description", ""),
        "status":            item["status"],
        "type_name":         item.get("type_name", ""),
        "latest_rev":        rev["revision"] if rev else "—",
        "latest_rev_id":     rev["id"] if rev else None,
        "latest_rev_status": rev["status"] if rev else None,
        "checked_out_by":    _item_checkout(item["id"]),
        "creator":           item.get("creator", ""),
        "created_at":        item.get("created_at", ""),
    }


@app.get("/api/items")
def list_items(
    search:           str  = "",
    status:           str  = "",
    checked_out_only: bool = False,
    page:             int  = 1,
    per_page:         int  = 50,
    user: dict = Depends(get_current_user),
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
def get_item(item_id: str, user: dict = Depends(get_current_user)) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    return _item_summary(item)


class NewItemBody(BaseModel):
    name:        str
    description: str = ""
    item_type:   str = "Mechanical Part"


@app.post("/api/items", status_code=201)
def create_item(body: NewItemBody,
                user: dict = Depends(require_permission("parts.create"))) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    itype    = (db.get_item_type_by_name(body.item_type)
                or db.get_item_type_by_name("Mechanical Part"))
    itype_id = itype["id"] if itype else 1
    new_id   = db.next_item_id()
    item_pk  = db.create_item(new_id, body.name.strip(), body.description, itype_id, user["username"])
    rev_lbl  = db.next_revision(item_pk, "alpha")
    db.create_revision(item_pk, rev_lbl, "alpha", user["username"])
    db.write_audit("create", "item", new_id, user["username"], f"Created via web UI: {body.name}")
    return {"item_id": new_id, "message": f"Item {new_id} created"}


class UpdateItemBody(BaseModel):
    name:        Optional[str] = None
    description: Optional[str] = None


@app.put("/api/items/{item_id}")
def update_item(item_id: str, body: UpdateItemBody,
                user: dict = Depends(require_permission("parts.edit"))) -> dict:
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
    db.write_audit("update", "item", item_id, user["username"], "Updated via web UI")
    return {"message": "Updated"}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str,
                user: dict = Depends(require_permission("parts.delete"))) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    if _item_checkout(item["id"]):
        raise HTTPException(409, f"Item {item_id} is checked out — check in before deleting")
    try:
        with db._connect() as conn:
            conn.execute("DELETE FROM items WHERE item_id=?", (item_id,))
            conn.commit()
    except Exception as exc:
        raise HTTPException(500, f"Delete failed: {exc}")
    db.write_audit("delete", "item", item_id, user["username"], "Deleted via web UI")
    return {"message": "Deleted"}


def _get_item_row(item_id: str) -> dict:
    row = db.get_item(item_id)
    if not row:
        raise HTTPException(404, f"Item {item_id} not found")
    return row


@app.patch("/api/items/{item_id}")
def patch_item(item_id: str, body: dict = Body(...),
               user: dict = Depends(require_permission("parts.edit"))):
    row = _get_item_row(item_id)
    if "item_type" in body:
        with db._connect() as conn:
            t = conn.execute(
                "SELECT id FROM item_types WHERE name=?", (body["item_type"],)
            ).fetchone()
            if t:
                conn.execute(
                    "UPDATE items SET item_type_id=? WHERE id=?", (t["id"], row["id"])
                )
                conn.commit()
    db.update_item(row["id"],
                   name=body.get("name"),
                   description=body.get("description"),
                   item_id=body.get("item_id"))
    return {"message": "Updated"}


@app.get("/api/items/{item_id}/attributes")
def get_attrs(item_id: str, user: dict = Depends(get_current_user)):
    row = _get_item_row(item_id)
    return db.get_attributes(row["id"])


@app.post("/api/items/{item_id}/attributes")
def set_attr(item_id: str, body: dict = Body(...),
             user: dict = Depends(require_permission("parts.edit"))):
    row = _get_item_row(item_id)
    db.set_attribute(row["id"], body["key"], body.get("value", ""))
    return {"message": "Saved"}


@app.delete("/api/items/{item_id}/attributes/{key}")
def del_attr(item_id: str, key: str,
             user: dict = Depends(require_permission("parts.edit"))):
    row = _get_item_row(item_id)
    db.delete_attribute(row["id"], key)
    return {"message": "Deleted"}


# ── Revisions ────────────────────────────────────────────────────────────────

@app.get("/api/items/{item_id}/revisions")
def list_revisions(item_id: str, user: dict = Depends(get_current_user)) -> list:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    return db.get_revisions(item["id"])


@app.post("/api/items/{item_id}/revisions", status_code=201)
def new_revision(item_id: str,
                 user: dict = Depends(require_permission("revisions.create"))) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev_lbl = db.next_revision(item["id"], "alpha")
    rev_pk  = db.create_revision(item["id"], rev_lbl, "alpha", user["username"])
    db.write_audit("new_revision", "item_revision", str(rev_pk), user["username"],
                   f"New revision {rev_lbl} for {item_id}")
    return {"revision": rev_lbl, "id": rev_pk}


@app.patch("/api/items/{item_id}/revisions/{rev_id}")
def patch_revision(item_id: str, rev_id: int, body: dict = Body(...),
                   user: dict = Depends(get_current_user)):
    if "change_description" in body:
        db.update_revision_description(rev_id, body["change_description"])
    if "status" in body:
        new_status = body["status"]
        if new_status not in ("in_work", "released", "locked"):
            raise HTTPException(400, "status must be in_work, released, or locked")
        if new_status in ("released", "locked"):
            perms = db.get_role_permissions(user["role"])
            if "revisions.lock" not in perms and "revisions.release" not in perms:
                raise HTTPException(403, "Permission denied: revisions.lock/release")
        released_by = user["username"] if new_status == "released" else None
        db.update_revision_status(rev_id, new_status, released_by)
        if new_status == "released":
            item = db.get_item(item_id)
            if item:
                db.set_item_status(item["id"], "released")
    return {"message": "Saved"}


# ── Item-level checkout / checkin / release ──────────────────────────────────

@app.post("/api/items/{item_id}/checkout")
def checkout_item(item_id: str,
                  user: dict = Depends(require_permission("datasets.checkout"))) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision exists for this item")
    datasets = db.get_datasets(rev["id"])
    if not datasets:
        raise HTTPException(400, "No datasets to check out")

    username = user["username"]
    errors = []
    checked_out_ds_ids: set = set()
    temp_paths = []

    for ds in datasets:
        try:
            tp = checkout_file(ds, item["item_id"], rev["revision"], username, db)
            checked_out_ds_ids.add(ds["id"])
            temp_paths.append(str(tp))
        except CheckoutError as exc:
            errors.append(str(exc))

    if errors:
        raise HTTPException(409, "; ".join(errors))

    for ds in datasets:
        _sync_relationships(item["id"], Path(ds["stored_path"]), username)

    copy_children_to_temp(item["id"], username, db, checked_out_ds_ids)

    db.write_audit("checkout", "item", item_id, username, "Checked out via web UI")
    return {"message": "Checked out", "temp_paths": temp_paths}


@app.post("/api/items/{item_id}/checkin")
def checkin_item(item_id: str, user: dict = Depends(get_current_user)) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision found")
    username = user["username"]
    perms = db.get_role_permissions(user["role"])
    can_checkin_any = "datasets.checkin_any" in perms
    errors = []
    for ds in db.get_datasets(rev["id"]):
        co = db.get_checkout(ds["id"])
        # Use the owner's username so checkin_file validation passes.
        # Admins (checkin_any) can check in on behalf of whoever has it locked.
        checkin_as = co["who"] if (co and can_checkin_any) else username
        try:
            checkin_file(ds, item["item_id"], rev["revision"], checkin_as, db)
        except CheckoutError as exc:
            errors.append(str(exc))
    if errors:
        raise HTTPException(409, "; ".join(errors))
    db.write_audit("checkin", "item", item_id, username,
                   "Checked in via web UI" + (" (admin override)" if can_checkin_any else ""))
    return {"message": "Checked in"}


@app.post("/api/items/{item_id}/release")
def release_item(item_id: str,
                 user: dict = Depends(require_permission("revisions.release"))) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision found")
    db.release_revision(rev["id"], user["username"])
    db.set_item_status(item["id"], "released")
    db.write_audit("release", "item", item_id, user["username"],
                   f"Released revision {rev['revision']} via web UI")
    return {"message": f"Item {item_id} released"}


# ── Per-dataset checkout / checkin / disk-save / save-as-new-revision ────────

def _resolve_dataset(ds_id: int):
    """Return dataset+context dict or raise 404."""
    with db._connect() as conn:
        row = conn.execute(
            """SELECT d.id, d.filename, d.file_type, d.stored_path, d.file_size,
                      i.item_id AS item_id_str,
                      r.revision, r.id AS rev_id, r.revision_type,
                      i.id AS item_pk,
                      cu.username AS checked_out_by, co.temp_path
               FROM datasets d
               JOIN item_revisions r ON r.id = d.revision_id
               JOIN items i          ON i.id = r.item_id
               LEFT JOIN checkouts co ON co.dataset_id = d.id
               LEFT JOIN users cu     ON cu.id = co.checked_out_by
               WHERE d.id = ?""",
            (ds_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, f"Dataset {ds_id} not found")
    return dict(row)


@app.post("/api/datasets/{ds_id}/checkout")
def checkout_dataset_route(ds_id: int,
                           user: dict = Depends(require_permission("datasets.checkout"))) -> dict:
    info = _resolve_dataset(ds_id)
    ds = {"id": info["id"], "filename": info["filename"],
          "file_type": info["file_type"], "stored_path": info["stored_path"]}
    try:
        tp = checkout_file(ds, info["item_id_str"], info["revision"], user["username"], db)
    except CheckoutError as exc:
        raise HTTPException(409, str(exc))

    _sync_relationships(info["item_pk"], Path(info["stored_path"]), user["username"])
    copy_children_to_temp(info["item_pk"], user["username"], db, {ds_id})

    return {"message": "Checked out", "temp_path": str(tp)}


@app.post("/api/datasets/{ds_id}/checkin")
def checkin_dataset_route(ds_id: int, user: dict = Depends(get_current_user)) -> dict:
    info = _resolve_dataset(ds_id)
    perms = db.get_role_permissions(user["role"])
    owner = info.get("checked_out_by")
    is_mine = owner == user["username"]
    if not is_mine and "datasets.checkin_any" not in perms:
        if "datasets.checkin_own" not in perms:
            raise HTTPException(403, "Permission denied: datasets.checkin_own")
        raise HTTPException(403, "Cannot check in a file checked out by another user")
    ds = {"id": info["id"], "filename": info["filename"],
          "file_type": info["file_type"], "stored_path": info["stored_path"]}
    # Pass the owner's username so checkin_file validation passes
    checkin_username = owner if (not is_mine and "datasets.checkin_any" in perms) else user["username"]
    try:
        checkin_file(ds, info["item_id_str"], info["revision"], checkin_username, db)
    except CheckoutError as exc:
        raise HTTPException(409, str(exc))
    return {"message": "Checked in"}


@app.post("/api/datasets/{ds_id}/disk-save")
def disk_save_route(ds_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Copy temp → vault without releasing the checkout."""
    info = _resolve_dataset(ds_id)
    ds = {"id": info["id"], "filename": info["filename"],
          "file_type": info["file_type"], "stored_path": info["stored_path"]}
    try:
        disk_save(ds, info["item_id_str"], info["revision"], user["username"], db)
    except CheckoutError as exc:
        raise HTTPException(409, str(exc))
    return {"message": "Saved to vault (checkout retained)"}


class SaveAsNewRevBody(BaseModel):
    change_description: str = ""
    revision_type:      Optional[str] = None


@app.post("/api/datasets/{ds_id}/save-as-new-revision", status_code=201)
def save_as_new_revision_route(ds_id: int, body: SaveAsNewRevBody,
                                user: dict = Depends(get_current_user)) -> dict:
    """Save temp file as a new revision; old checkout is released, new one is opened."""
    info = _resolve_dataset(ds_id)
    ds = {"id": info["id"], "filename": info["filename"],
          "file_type": info["file_type"], "stored_path": info["stored_path"]}
    with db._connect() as conn:
        item_row = conn.execute(
            "SELECT id, item_id, name, description, status FROM items WHERE id=?",
            (info["item_pk"],)
        ).fetchone()
    if not item_row:
        raise HTTPException(404, "Parent item not found")
    item        = dict(item_row)
    current_rev = {"id": info["rev_id"], "revision": info["revision"],
                   "revision_type": info["revision_type"]}
    try:
        result = save_as_new_revision(
            ds, item, current_rev, user["username"], db,
            change_description=body.change_description,
            revision_type=body.revision_type,
        )
    except CheckoutError as exc:
        raise HTTPException(409, str(exc))
    return result


# ── Datasets ─────────────────────────────────────────────────────────────────

@app.get("/api/items/{item_id}/datasets")
def list_datasets(item_id: str, user: dict = Depends(get_current_user)) -> list:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    rev = _latest_rev(item["id"])
    if not rev:
        return []
    datasets = db.get_datasets(rev["id"])
    result = []
    for ds in datasets:
        modified = _watcher.get_modified_status(ds["id"]) if _watcher else False
        result.append({**ds, "modified": modified})
    return result


@app.get("/api/items/{item_id}/datasets/{ds_id}/open")
def open_dataset(item_id: str, ds_id: int,
                 user: dict = Depends(get_current_user)) -> dict:
    """Open file in registered Windows application."""
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

    username = user["username"]
    co = db.get_checkout(ds_id)
    if co and co["who"] == username and co.get("temp_path"):
        open_path = Path(co["temp_path"])
    else:
        open_path = Path(ds["stored_path"])

    if not open_path.exists():
        raise HTTPException(404, f"File not found on disk: {open_path}")

    os.startfile(str(open_path))
    db.write_audit("open", "dataset", str(ds_id), username,
                   f"Opened via web UI: {ds['filename']}")
    return {"message": f"Opening {open_path.name}"}


# ── BOM ──────────────────────────────────────────────────────────────────────

def _build_bom(item_pk: int, visited: set) -> dict:
    with db._connect() as conn:
        row = conn.execute(
            "SELECT id, item_id, name, status FROM items WHERE id=?", (item_pk,)
        ).fetchone()
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
def get_bom(item_id: str, user: dict = Depends(get_current_user)) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404)
    return _build_bom(item["id"], set())


@app.get("/api/items/{item_id}/where-used")
def where_used(item_id: str, user: dict = Depends(get_current_user)) -> list:
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
def add_relationship(body: RelBody,
                     user: dict = Depends(require_permission("bom.edit"))) -> dict:
    if body.parent_item_id == body.child_item_id:
        raise HTTPException(400, "Parent and child cannot be the same item")
    db.add_relationship(body.parent_item_id, body.child_item_id, body.quantity, user["username"])
    db.write_audit("add_relationship", "item", str(body.parent_item_id), user["username"],
                   f"Added child pk {body.child_item_id} qty={body.quantity}")
    return {"message": "Relationship added"}


# ── Parser helper — auto-link assembly children ──────────────────────────────

def _sync_relationships(item_pk: int, vault_path: Path, username: str) -> int:
    """Parse a CAD file and create DB relationships for any children already in DB."""
    ext = vault_path.suffix.lower()
    if ext not in {".prt", ".asm", ".sldprt", ".sldasm", ".step", ".stp"}:
        return 0
    try:
        result = parse_nx_file(str(vault_path))
    except Exception:
        return 0
    created = 0
    for comp_filename in result.get("components", []):
        child = db.get_item_by_filename(comp_filename)
        if child and child["id"] != item_pk:
            try:
                db.add_relationship(item_pk, child["id"], quantity=1, added_by=username)
                created += 1
                logger.info("Auto-linked %s → %s", vault_path.name, comp_filename)
            except Exception:
                pass
    return created


# ── Attach file to item (upload into vault) ──────────────────────────────────

@app.post("/api/items/{item_id}/datasets", status_code=201)
async def attach_file(item_id: str, file: UploadFile = File(...),
                      user: dict = Depends(require_permission("datasets.upload"))) -> dict:
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    rev = _latest_rev(item["id"])
    if not rev:
        raise HTTPException(400, "No revision exists — create a revision first")

    filename  = Path(file.filename).name
    vault_dir = config.VAULT_PATH / rev["revision"]
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_path = vault_dir / filename

    if vault_path.exists():
        raise HTTPException(409, f"{filename} already exists in revision {rev['revision']} — rename the file or delete the existing dataset first")

    contents = await file.read()
    vault_path.write_bytes(contents)

    try:
        import stat as _stat
        vault_path.chmod(vault_path.stat().st_mode & ~_stat.S_IWRITE & ~_stat.S_IWGRP & ~_stat.S_IWOTH)
    except OSError:
        pass

    ds_pk = db.add_dataset(
        rev["id"], filename, Path(filename).suffix.lower(),
        str(vault_path), len(contents), user["username"],
    )
    db.write_audit("attach", "dataset", str(ds_pk), user["username"],
                   f"Attached {filename} to {item_id} rev {rev['revision']}")

    linked = _sync_relationships(item["id"], vault_path, user["username"])

    return {"message": f"{filename} attached" + (f" ({linked} relationships linked)" if linked else ""),
            "dataset_id": ds_pk}


# ── All datasets (for Documents panel) ───────────────────────────────────────

@app.get("/api/datasets")
def list_all_datasets(search: str = "",
                      user: dict = Depends(get_current_user)) -> list:
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
def list_users(user: dict = Depends(get_current_user)) -> list:
    return db.list_users()


class NewUserBody(BaseModel):
    username: str
    password: str = ""
    role:     str = "user"


@app.post("/api/users", status_code=201)
def create_user(body: NewUserBody,
                user: dict = Depends(require_permission("users.manage"))) -> dict:
    if not body.username.strip():
        raise HTTPException(400, "username is required")
    uid = db.upsert_user(body.username.strip(), body.role)
    if body.password:
        db.set_password(uid, body.password)
    return {"message": f"User {body.username} created/updated", "id": uid}


class SetUserPasswordBody(BaseModel):
    password: str


@app.post("/api/users/{user_id}/password")
def set_user_password(user_id: int, body: SetUserPasswordBody,
                      user: dict = Depends(require_permission("users.manage"))) -> dict:
    if not body.password:
        raise HTTPException(400, "password is required")
    db.set_password(user_id, body.password)
    return {"message": "Password set"}


@app.put("/api/users/{user_id}")
def update_user(user_id: int, body: dict,
                user: dict = Depends(require_permission("users.manage"))) -> dict:
    role = body.get("role")
    if role:
        with db._connect() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            conn.commit()
    return {"message": "Updated"}


@app.post("/api/users/{user_id}/force-checkin")
def force_checkin_user(user_id: int,
                       user: dict = Depends(require_permission("datasets.checkin_any"))) -> dict:
    """Force check-in all datasets checked out by a user (admin only)."""
    target = db._get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    count = db.force_checkin_all_by_user(user_id)
    db.write_audit("force_checkin_all", "user", str(user_id), user["username"],
                   f"Force checked in {count} items for {target['username']}")
    return {"message": f"Force checked in {count} items for {target['username']}", "count": count}


# ── Roles ─────────────────────────────────────────────────────────────────────

@app.get("/api/roles")
def list_roles_route(user: dict = Depends(get_current_user)) -> list:
    roles = db.list_roles()
    result = []
    for r in roles:
        perms = db.get_role_permissions(r)
        result.append({"name": r, "permissions": list(perms),
                       "builtin": r in ("admin", "user", "readonly")})
    return result


class NewRoleBody(BaseModel):
    name: str


@app.post("/api/roles", status_code=201)
def create_role(body: NewRoleBody,
                user: dict = Depends(require_permission("users.manage"))) -> dict:
    if body.name in ("admin", "user", "readonly"):
        raise HTTPException(400, "Cannot create built-in role")
    return {"message": f"Role {body.name} ready", "name": body.name}


class RolePermissionsBody(BaseModel):
    permissions: list


@app.put("/api/roles/{role_name}")
def update_role_permissions(role_name: str, body: RolePermissionsBody,
                             user: dict = Depends(require_permission("users.manage"))) -> dict:
    if role_name in ("admin", "user", "readonly"):
        raise HTTPException(400, "Cannot modify built-in role permissions")
    all_perms = set(Database._ADMIN_PERMS)
    for perm in all_perms:
        db.set_role_permission(role_name, perm, perm in body.permissions)
    return {"message": "Role permissions updated"}


# ── Audit log ─────────────────────────────────────────────────────────────────

@app.get("/api/audit")
def get_audit(item_id: Optional[str] = None,
              user: dict = Depends(get_current_user)) -> list:
    if item_id:
        return db.get_audit_log_for_item(item_id)
    return db.get_audit_log()


# ── Server status ─────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status(user: dict = Depends(get_current_user)) -> dict:
    return {
        "version":         "2.2.0",
        "username":        user["username"],
        "watcher_running": _watcher is not None and (
            _watcher._thread is not None and _watcher._thread.is_alive()
        ),
        "db_path":         str(config.DB_PATH),
        "vault_path":      str(config.VAULT_PATH),
        "temp_base_path":  str(config.TEMP_BASE_PATH),
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

def run() -> None:
    """Launched by `plmlite-server` console script."""
    import uvicorn
    uvicorn.run("plmlite.server:app", host="0.0.0.0", port=8080, log_level="info")
