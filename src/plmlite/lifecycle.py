"""Lifecycle management for NX12 CAD datasets."""

from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .database import Database


class LifecycleState(Enum):
    DESIGN = "design"
    REVIEW = "review"
    RELEASED = "released"
    ARCHIVED = "archived"


class LifecycleManager:
    def __init__(self, db: Optional["Database"] = None):
        """
        If db is None, falls back to an in-memory store (preserves backward
        compatibility with existing tests that don't pass a db instance).
        """
        self._db = db
        self._states: dict = {}

    def set_state(self, part_id: str, state: LifecycleState) -> None:
        """Set the lifecycle state for a given part.

        part_id is treated as a filepath when a database is provided.
        """
        if self._db is not None:
            file_row = self._db.get_file_by_path(part_id)
            if file_row:
                self._db.set_lifecycle_state(file_row["id"], state.value)
                return
        self._states[part_id] = state

    def get_state(self, part_id: str) -> Optional[LifecycleState]:
        """Retrieve the lifecycle state for a given part."""
        if self._db is not None:
            file_row = self._db.get_file_by_path(part_id)
            if file_row and file_row.get("lifecycle_state"):
                try:
                    return LifecycleState(file_row["lifecycle_state"])
                except ValueError:
                    pass
        return self._states.get(part_id)
