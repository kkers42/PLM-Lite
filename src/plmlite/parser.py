"""Parsing utilities for NX12 CAD datasets."""

import os


def parse_nx_file(filepath: str) -> dict:
    """Placeholder function to parse NX12 CAD file and extract metadata.

    This function doesn't implement real parsing yet. It returns a dummy
    dictionary for demonstration purposes.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"NX file not found: {filepath}")
    
    # TODO: implement parsing logic using NX library or file format spec
    return {
        "filename": os.path.basename(filepath),
        "size": os.path.getsize(filepath),
        "metadata": {},
    }
