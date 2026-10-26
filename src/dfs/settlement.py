"""Settlement: what each of the owner's entries actually won, and the net.

Reuses the ONE payout owner (``src/dfs/contests.py``: ``prize_at`` /
``tied_payout``); nothing here prices a rank on its own.  Rank and tie size come
from the FULL field's scores (``pointsCounts``), not the file's Rank column —
which is only cross-checked, and a disagreement is reported.

Honest states, in order of how much they block:

* a field score that could not be read → rank is unknowable → settlement
  ``unavailable`` (never ranked as if that entry did not exist);
* a tie across paid places with an unknown tie rule → that entry's payout is
  ``unavailable`` (no split is assumed) — while a tie entirely outside the paid
  places is an exact $0 whatever the rule;
* a non-cash prize (ticket) is reported apart, never counted as cash;
* any unavailable payout makes the NET unknown — never a partial sum shown as
  the answer.

Evidence only: settlement records what happened; it trains nothing.
"""

from __future__ import annotations

from typing import Any

from src.dfs.contests import Contest, prize_at, tied_payout


def _span_has_noncash(contest: Contest, first: int, last: int) -> bool:
    return any(
        b.kind != "cash" and b.min_rank <= last and b.max_rank >= first for b in contest.ladder
    )


def settle(
    contest: Contest,
    points_counts: list[tuple[float, int]],
    owner_entries: list[dict[str, Any]],
    *,
    unscored_entries: int = 0,
) -> dict[str, Any]:
    fee = contest.entry_fee_cents
    base = {"contestName": contest.name, "entryFeeCents": fee, "entries": len(owner_entries)}
    if not owner_entries:
        return {**base, "state": "no_owner_entries", "note": "None of your entries were found."}
    if unscored_entries:
        return {
            **base,
            "state": "unavailable",
            "reason": f"{unscored_entries} field entr(y/ies) had no readable score, so ranks cannot be known.",
        }
    above: dict[float, int] = {}
    running = 0
    for pts, n in sorted(points_counts, key=lambda kv: -kv[0]):
        above[pts] = running
        running += n
    field_size = running
    count = dict(points_counts)
    rows: list[dict[str, Any]] = []
    for e in owner_entries:
        pts = e.get("points")
        if pts is None or pts not in count:
            rows.append({**e, "payout": {"state": "unavailable", "reason": "score not readable"}})
            continue
        first, tied = above[pts] + 1, count[pts]
        last = first + tied - 1
        if _span_has_noncash(contest, first, last):
            payout: dict[str, Any] = {
                "state": "noncash",
                "reason": "A ticket / non-cash prize sits in this finishing range; its cash is not counted.",
            }
        elif all(prize_at(contest.ladder, r) == 0 for r in range(first, last + 1)):
            payout = {
                "state": "exact",
                "eachCents": 0,
                "exact": "0",
            }  # unpaid whatever the tie rule
        else:
            payout = tied_payout(contest.ladder, first, tied, contest.tie_rule)
        rank_check = (
            None
            if e.get("platformRank") is None
            else ("agrees" if int(e["platformRank"]) == first else "disagrees")
        )
        rows.append(
            {**e, "rank": first, "tiedWith": tied - 1, "rankCheck": rank_check, "payout": payout}
        )
    exact = [r["payout"]["eachCents"] for r in rows if r["payout"].get("state") == "exact"]
    blocked = [r for r in rows if r["payout"].get("state") != "exact"]
    fees = fee * len(rows)
    declared = contest.current_entries or contest.capacity
    return {
        **base,
        "state": "complete" if not blocked else "partial",
        "fieldSize": field_size,
        "declaredFieldSize": declared,
        # A results file with fewer entries than the contest had would rank
        # everyone too high; the check is reported, not corrected.
        "fieldSizeCheck": None
        if declared is None
        else ("agrees" if declared == field_size else "disagrees"),
        "feesCents": fees,
        "knownWinningsCents": sum(exact),
        # A net over an unknown payout is not a net.
        "netCents": sum(exact) - fees if not blocked else None,
        "roi": round((sum(exact) - fees) / fees, 4) if not blocked and fees else None,
        "entriesWithUnknownPayout": len(blocked),
        "rankDisagreements": sum(1 for r in rows if r.get("rankCheck") == "disagrees"),
        "rows": rows[:500],
    }
