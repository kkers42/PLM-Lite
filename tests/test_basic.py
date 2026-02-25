import os
import tempfile

from plmlite import parser, lifecycle


def test_parse_nonexistent(tmp_path):
    fake = tmp_path / "nonexistent.prt"
    try:
        parser.parse_nx_file(str(fake))
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_lifecycle_manager():
    mgr = lifecycle.LifecycleManager()
    mgr.set_state("part1", lifecycle.LifecycleState.DESIGN)
    assert mgr.get_state("part1") == lifecycle.LifecycleState.DESIGN
    assert mgr.get_state("unknown") is None
