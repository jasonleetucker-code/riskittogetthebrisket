"""Shared utilities for pipeline scripts.

Consolidates helpers that were duplicated across 5+ scripts:
- _repo_root(): find the repository root from any script location
- _latest(): find the newest file matching a glob pattern
- _normalize_name(): minimal player name normalization for cross-system matching
"""
from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    """Return the repository root (parent of scripts/)."""
    return Path(__file__).resolve().parents[1]


def _latest(directory: Path, pattern: str) -> Path | None:
    """Return the newest file matching *pattern* in *directory*, or None."""
    files = sorted(directory.glob(pattern), reverse=True)
    return files[0] if files else None


def _normalize_name(name: str) -> str:
    """Minimal player name normalization for cross-system matching.

    Strips suffixes (Jr., Sr., II–V), punctuation, and lowercases.
    """
    n = name.strip()
    for sfx in (" Jr.", " Sr.", " II", " III", " IV", " V"):
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
    return n.lower().replace(".", "").replace("'", "").replace("\u2019", "")
