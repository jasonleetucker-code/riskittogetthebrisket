"""Minimal context bundles: load only named canonical sources with provenance."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class ContextDocument:
    identifier: str
    version: str
    content: str

def bundle(documents: Iterable[ContextDocument]) -> dict[str, object]:
    rows = sorted(documents, key=lambda item: item.identifier)
    payload = "\n".join(f"{row.identifier}@{row.version}\n{row.content}" for row in rows)
    return {"fingerprint": hashlib.sha256(payload.encode()).hexdigest(), "documents": [{"identifier": row.identifier, "version": row.version} for row in rows], "document_count": len(rows)}
