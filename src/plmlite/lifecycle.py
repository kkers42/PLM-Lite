"""Lifecycle management for NX12 CAD datasets."""

from enum import Enum


class LifecycleState(Enum):
    DESIGN = "design"
    REVIEW = "review"
    RELEASED = "released"
    ARCHIVED = "archived"


class LifecycleManager:
    def __init__(self):
        # simple in-memory store for demonstration
        self._states = {}

    def set_state(self, part_id: str, state: LifecycleState):
        """Set the lifecycle state for a given part."""
        self._states[part_id] = state

    def get_state(self, part_id: str) -> LifecycleState:
        """Retrieve the lifecycle state for a given part."""
        return self._states.get(part_id)
