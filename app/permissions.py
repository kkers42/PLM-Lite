"""
PLM Lite V1.0 — Permission enforcement
Usage:
    @router.post("/parts", dependencies=[Depends(require_ability("write"))])
    async def create_part(...):
        ...
"""
from fastapi import Depends, HTTPException, status
from .auth import get_current_user


def require_ability(ability: str):
    """Returns a FastAPI dependency that enforces a role ability flag."""
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if not user.get("is_active", 0):
            raise HTTPException(status_code=403, detail="Account disabled")
        key = f"can_{ability}"
        if not user.get(key, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role does not have '{ability}' permission",
            )
        return user
    return _check


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("can_admin", 0):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
