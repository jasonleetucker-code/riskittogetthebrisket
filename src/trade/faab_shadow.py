"""Shadow-comparison log for the Live Waiver Opportunity layer.

Full design record: ``docs/faab-live-opportunity-model.md``.

Champion/challenger, not evaluation-as-activation (CLAUDE.md: "nothing
self-promotes").  While ``waiver_live_opportunity`` is shadow-only, the
live FAAB response keeps using the canonical-only value; this module is
where the road-not-taken (the opportunity-adjusted value) gets recorded
so a later, human-reviewed promotion decision has real forward-looking
cases to look at — the honest alternative to a retroactive backtest
that directive Part VII's own data-availability limit rules out for
this specific signal (no historical role/event snapshots exist to
replay).

Append-only, one file per league (``data/faab/shadow_comparisons_
<leagueKey>.json``) — mirrors the idempotent-append posture
``src/history/store.py`` already establishes for the temporal ledger,
at the lighter flat-file weight `src/playerctx/store.py` uses for its
own history ring, since this data is diagnostic rather than a decision
input.  Bounded (oldest entries drop off) so the file cannot grow
without limit on an always-on shadow flag.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHADOW_DIR = REPO_ROOT / "data" / "faab"

# Bounded ring — diagnostic record, not a decision input, so unlimited
# growth is not worth guarding against with anything fancier than a cap.
_MAX_ENTRIES = 5000


def _path_for(league_key: str) -> Path:
    safe_key = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(league_key))
    return _SHADOW_DIR / f"shadow_comparisons_{safe_key or 'unknown'}.json"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_comparisons(league_key: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    """Every retained comparison for one league, oldest first.  ``[]``
    on missing/corrupt file — never raises into a request path."""
    target = path or _path_for(league_key)
    if not target.exists():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("shadow comparison log unreadable, treating as empty: %s", exc)
        return []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def record_comparison(
    *,
    league_key: str,
    player_name: str,
    canonical_value: float,
    opportunity_result: dict[str, Any],
    path: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Append one canonical-vs-opportunity comparison.

    ``opportunity_result`` is the dict returned by
    ``src.trade.faab_opportunity.opportunity_value`` — recorded
    verbatim (axes included) so a later review can see WHY the two
    values diverged, not just that they did.
    """
    target = path or _path_for(league_key)
    entries = load_comparisons(league_key, path=target)
    ts = now or datetime.now(timezone.utc)

    entries.append(
        {
            "recordedAt": ts.isoformat(),
            "leagueKey": league_key,
            "playerName": player_name,
            "canonicalValue": round(float(canonical_value), 1),
            "opportunityValue": round(float(opportunity_result.get("value", canonical_value)), 1),
            "shortTermSurplus": opportunity_result.get("shortTermSurplus"),
            "retention": opportunity_result.get("retention"),
            "hasEvidence": opportunity_result.get("hasEvidence"),
            "availability": opportunity_result.get("availability"),
            "axes": opportunity_result.get("axes"),
        }
    )
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]

    _atomic_write_json(target, entries)
    return target
