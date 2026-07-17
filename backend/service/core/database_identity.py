"""Stable database identity shared with Electron.

Algorithm: resolve symlinks/junctions with non-strict realpath, normalize separators,
then lowercase on Windows before hashing the UTF-8 canonical path with SHA-256.
"""
from __future__ import annotations

import hashlib
import os


def canonical_database_path(database_path: str | os.PathLike[str]) -> str:
    """Return the cross-runtime canonical database path used for identity hashing."""
    resolved = os.path.realpath(os.fspath(database_path))
    normalized = resolved.replace("\\", "/")
    return normalized.lower() if os.name == "nt" else normalized


def compute_database_identity(database_path: str | os.PathLike[str]) -> str:
    """Hash the canonical UTF-8 path using SHA-256."""
    return hashlib.sha256(canonical_database_path(database_path).encode("utf-8")).hexdigest()
