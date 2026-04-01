"""NX binary file parser -- extracts component references from assembly .prt files.

NX stores component filenames as readable ASCII/UTF-8 strings inside the binary
.prt format. A regex scan is sufficient to extract them without the NX Open API.

Supports: .prt, .asm, .sldprt, .sldasm (binary scan)
          .step, .stp (text-based STEP format)
"""

import os
import re
from pathlib import Path
from typing import List

_ASSEMBLY_EXTS = {".prt", ".asm", ".sldprt", ".sldasm"}
_STEP_EXTS     = {".step", ".stp"}

# Match CAD filenames embedded in binary data
_CAD_FILENAME_RE = re.compile(
    rb'([\w][\w\-. ]{0,60}\.(?:prt|asm|sldprt|sldasm|step|stp|jt|stl))',
    re.IGNORECASE,
)

# STEP AP214/AP242 next-assembly reference
_STEP_NEXT_ASSEMBLY_RE = re.compile(
    r"NEXT_ASSEMBLY_USAGE_OCCURENCE\s*\([^,]*,[^,]*,[^,]*,'([^']+)'",
    re.IGNORECASE,
)


def parse_nx_file(filepath: str) -> dict:
    """Return metadata and component references for a CAD file.

    Returns:
        {
            "filename":   str,
            "size":       int,
            "components": [str, ...]   # referenced component filenames
        }
    Raises FileNotFoundError if the file does not exist.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"NX file not found: {filepath}")

    ext = path.suffix.lower()
    size = path.stat().st_size

    if ext in _STEP_EXTS:
        components = _parse_step(path)
    elif ext in _ASSEMBLY_EXTS:
        components = _parse_binary_cad(path)
    else:
        components = []

    # Remove self-reference
    components = [c for c in components if c.lower() != path.name.lower()]

    return {
        "filename":   path.name,
        "size":       size,
        "components": components,
    }


def _parse_binary_cad(path: Path) -> List[str]:
    """Scan binary CAD file for embedded component filename strings."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    found = set()
    for m in _CAD_FILENAME_RE.finditer(data):
        try:
            name = m.group(1).decode("utf-8", errors="replace").strip()
            if len(name) >= 3 and "." in name and not name.startswith("."):
                found.add(name)
        except Exception:
            pass
    return sorted(found)


def _parse_step(path: Path) -> List[str]:
    """Extract referenced filenames from a STEP AP214/AP242 text file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []

    found = set()
    for m in _STEP_NEXT_ASSEMBLY_RE.finditer(text):
        name = m.group(1).strip()
        if name:
            found.add(name)
    return sorted(found)
