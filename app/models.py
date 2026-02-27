"""
PLM Lite V1.0 — Pydantic request/response models
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    can_release: Optional[int] = None
    can_view: Optional[int] = None
    can_write: Optional[int] = None
    can_upload: Optional[int] = None
    can_checkout: Optional[int] = None
    can_admin: Optional[int] = None
    is_active: int = 1
    must_change_password: int = 0


# ── Roles ─────────────────────────────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: str
    can_release: int = 1
    can_view: int = 1
    can_write: int = 1
    can_upload: int = 1
    can_checkout: int = 1
    can_admin: int = 0


class RoleUpdate(RoleCreate):
    pass


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role_id: Optional[int] = None


class UserUpdate(BaseModel):
    role_id: Optional[int] = None
    is_active: int = 1


class PasswordReset(BaseModel):
    new_password: str


# ── Parts ─────────────────────────────────────────────────────────────────────

class PartCreate(BaseModel):
    part_number: str
    part_name: str
    part_revision: str = "A"
    description: str = ""
    part_level: str = ""

    @field_validator("part_number")
    @classmethod
    def pn_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Part number cannot be empty")
        return v.strip().upper()


class PartUpdate(BaseModel):
    part_name: str
    description: str = ""
    part_level: str = ""


class RevisionCreate(BaseModel):
    description: str = ""


class AttributeSet(BaseModel):
    key: str
    value: str
    order: int = 0


# ── Relationships ─────────────────────────────────────────────────────────────

class RelationshipCreate(BaseModel):
    parent_part_id: int
    child_part_id: int
    quantity: float = 1.0
    relationship_type: str = "assembly"
    notes: str = ""

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Quantity must be > 0")
        return v


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentAttach(BaseModel):
    description: str = ""


# ── Generic responses ─────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class CheckoutRequest(BaseModel):
    station: str = ""
