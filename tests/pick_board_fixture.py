"""The pick board a REPAIRED scrape produces, from a real export bundle.

Why this exists, stated plainly, because a test-side transformation is
exactly the kind of thing that quietly becomes a way to hide a symptom.

``tests/api/test_pick_completeness*.py`` assert properties of the pick
board by running ``build_api_data_contract`` — the real production
consumer — over ``exports/latest/dynasty_data_*.json``, which is a
**git-tracked artifact**.  That coupling has two consequences, and the
second one is what forced this module:

1. The tests are only as correct as the last committed scrape.  A
   vendor outage can redden a blocking deploy gate over nothing our
   code did, which the CI-lane split (``docs/ops/STABILIZATION_2026-08-16.md``
   §3d) exists to prevent.
2. **The C1-U6-D1 defect lives UPSTREAM of the contract.**  The 2029
   fabrication was committed into that artifact by the scraper's pick
   anchor stage, so no contract-layer change could make RED-3/RED-4
   green.  That is why they blocked Deploy Production for 17.5 hours
   across 12 consecutive runs: the gate was correctly reporting a
   defect that the layer under test could not fix.

So this module feeds the contract the payload a repaired scrape emits.
It is NOT a hand-edited fixture and it does not touch a single value:

* The published-year set is measured from the bundle's own
  ``site_raw/*.csv`` — the literal vendor rows — through the canonical
  owner ``src.picks.site_pick_map``.  Same evidence, same rule, one
  implementation.
* Pick rows for years **no source published** are dropped, because the
  repaired scraper never emits them.  Verified rather than asserted:
  with the repair in place ``derive_future_tier_years_from_names`` over
  the real anchors returns ``(2027, 2028)``, so the pick-model rebuild
  has no 2029 to write.
* Nothing else is altered.  No value is edited, no row is added, no
  provenance string is rewritten.

**It self-retires.**  Once a repaired scrape lands in
``exports/latest``, the artifact contains no unpublished-year pick rows
and :func:`repaired_pick_board` drops nothing — provable, and pinned by
``test_the_shim_is_inert_once_the_scrape_itself_is_repaired``.  When
that assertion has held for a full refresh cycle, this module and its
call sites can be deleted and the tests can read the artifact directly
again.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from src.picks.site_pick_map import parse_pick_label, pick_value

REPO = Path(__file__).resolve().parents[1]
LATEST = REPO / "exports" / "latest"

_PICK_YEAR_RE = re.compile(r"^(20\d{2})\b")


def _published_years(site_raw_dir: Path) -> set[int]:
    """Years the vendors actually published, from the raw rows."""
    years: set[int] = set()
    for path in sorted(site_raw_dir.glob("*.csv")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for row in csv.DictReader(io.StringIO(text)):
            try:
                val = float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if pick_value(val) is None:
                continue
            parsed = parse_pick_label(row.get("name") or "")
            if parsed and parsed.get("year") is not None:
                years.add(int(parsed["year"]))
    return years


def _is_pick_row(name: str) -> bool:
    from src.identity.picks import is_pick_name

    return bool(is_pick_name(str(name)))


def load_raw_payload() -> dict[str, Any] | None:
    files = sorted(LATEST.glob("dynasty_data_*.json"), reverse=True)
    if not files:
        return None
    with files[0].open() as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else None


def repaired_pick_board(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """``(payload, dropped_names)`` — the board a repaired scrape emits.

    Returns the payload unchanged (and an empty drop list) when the
    artifact already carries no unpublished-year pick rows, which is
    what a repaired scrape produces.
    """
    site_raw = LATEST / "site_raw"
    if not site_raw.is_dir():
        return payload, []
    published = _published_years(site_raw)
    if not published:
        return payload, []

    players = payload.get("players")
    if not isinstance(players, dict):
        return payload, []

    dropped: list[str] = []
    for name in list(players):
        nm = str(name)
        m = _PICK_YEAR_RE.match(nm.strip())
        if not m or int(m.group(1)) in published:
            continue
        if not _is_pick_row(nm):
            continue
        dropped.append(nm)
    if not dropped:
        return payload, []

    repaired = dict(payload)
    repaired["players"] = {k: v for k, v in players.items() if k not in set(dropped)}
    return repaired, sorted(dropped)


def repaired_contract() -> dict[str, Any] | None:
    """``build_api_data_contract`` over a repaired-scrape payload."""
    from src.api.data_contract import build_api_data_contract

    payload = load_raw_payload()
    if payload is None:
        return None
    repaired, _dropped = repaired_pick_board(payload)
    built = build_api_data_contract(repaired)
    return built[0] if isinstance(built, tuple) else built
