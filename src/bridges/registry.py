"""Load the declared bridge registry.  Declaration only — confers nothing.

The file this reads (``config/bridges/bridges_v1.json``) says which vendors
claim to carry cross-position information, which registry keys hold each half,
which provider family they belong to, and what evidence settles whether their
two halves are the same quantity.

It does **not** say whether a bridge works.  That is measured from the board
(:func:`src.bridges.descriptor.measure_capability`) and decided by
:func:`src.bridges.assess.assess_bridges`.  The separation is the point: the
flag this replaces, ``is_backbone``, could be moved onto a source that cannot
seed a ladder — satisfying the guard while leaving the board exactly as broken
(``tests/consensus_edge/test_fair_value.py::TestTheGuardIsACapabilityNotAFlag``).

Loading is cached on the file's mtime and size, matching
``_load_source_row_floors`` in ``data_contract``, so an operator edit is picked
up without a restart and a hot path does not re-read the file per request.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from src.bridges.descriptor import BridgeDescriptor
from src.utils.config_loader import repo_root

__all__ = ["BRIDGE_CONFIG_PATH", "load_bridge_descriptors"]

BRIDGE_CONFIG_PATH: Path = repo_root() / "config" / "bridges" / "bridges_v1.json"

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"stamp": None, "descriptors": ()}


def _descriptor_from(entry: dict[str, Any]) -> BridgeDescriptor:
    return BridgeDescriptor(
        bridge_key=str(entry.get("bridgeKey") or ""),
        display_name=str(entry.get("displayName") or entry.get("bridgeKey") or ""),
        family=str(entry.get("family") or ""),
        kind=str(entry.get("kind") or ""),
        offense_keys=tuple(str(k) for k in (entry.get("offenseKeys") or ())),
        idp_keys=tuple(str(k) for k in (entry.get("idpKeys") or ())),
        comparability=str(entry.get("comparability") or "PENDING"),
        comparability_evidence=str(entry.get("comparabilityEvidence") or ""),
        notes=str(entry.get("notes") or ""),
    )


def load_bridge_descriptors(path: Path | None = None) -> tuple[BridgeDescriptor, ...]:
    """Declared bridges, in file order.

    File order is load-bearing: it decides which member of a provider family is
    counted when two are declared, so the answer comes from the registry rather
    than from whatever order the board's rows happened to arrive in.

    A malformed entry raises rather than being skipped.  A silently dropped
    bridge would look exactly like a bridge that was never declared, and the
    whole point of this layer is that absence is explicable.
    """
    target = path or BRIDGE_CONFIG_PATH
    try:
        stat = target.stat()
        stamp = (str(target), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ()

    with _LOCK:
        if _CACHE["stamp"] == stamp:
            return tuple(_CACHE["descriptors"])

    try:
        raw = json.loads(target.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{target}: bridge registry is unreadable: {exc}") from exc

    entries = raw.get("bridges")
    if not isinstance(entries, list):
        raise ValueError(f"{target}: bridge registry has no 'bridges' list")

    descriptors = tuple(_descriptor_from(e) for e in entries if isinstance(e, dict))

    seen: set[str] = set()
    for d in descriptors:
        if d.bridge_key in seen:
            raise ValueError(f"{target}: duplicate bridgeKey {d.bridge_key!r}")
        seen.add(d.bridge_key)

    with _LOCK:
        _CACHE["stamp"] = stamp
        _CACHE["descriptors"] = descriptors
    return descriptors
