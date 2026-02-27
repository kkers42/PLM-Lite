"""
PLM Lite V1.0 — User management routes (admin only)
"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import hash_password
from ..database import Database
from ..models import MessageResponse, PasswordReset, UserCreate, UserUpdate
from ..permissions import require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


def _db() -> Database:
    return Database()


@router.get("")
async def list_users(admin: dict = Depends(require_admin)):
    return _db().list_users()


@router.post("", status_code=201)
async def create_user(body: UserCreate, admin: dict = Depends(require_admin)):
    db = _db()
    if db.get_user_by_username(body.username):
        raise HTTPException(409, "Username already exists")
    pw_hash = hash_password(body.password)
    return db.create_user(body.username, pw_hash, body.email, body.role_id)


@router.put("/{user_id}")
async def update_user(user_id: int, body: UserUpdate, admin: dict = Depends(require_admin)):
    db = _db()
    if not db.get_user(user_id):
        raise HTTPException(404, "User not found")
    db.update_user(user_id, body.role_id, body.is_active)
    return db.get_user(user_id)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: int, body: PasswordReset, admin: dict = Depends(require_admin)):
    db = _db()
    if not db.get_user(user_id):
        raise HTTPException(404, "User not found")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    db.update_user_password(user_id, hash_password(body.new_password), must_change=1)
    return MessageResponse(message="Password reset — user must change on next login")
