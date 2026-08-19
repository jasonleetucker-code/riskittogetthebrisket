#!/usr/bin/env python3
"""Accumulate cross-league FAAB bids from KTC's public waiver database.

KTC publishes real waiver claims from other people's dynasty leagues,
each row carrying the winning bid, the league's ORIGINAL budget, and
the league's format.  That is a second, independent read on what a
waiver claim actually costs — our own Sleeper history says what THIS
league pays, and this says what comparable leagues pay for the same
player right now.

    python scripts/fetch_crowd_faab.py
    python scripts/fetch_crowd_faab.py --league dynasty_main --dry-run

Exit codes: 0 ok · 1 error · 2 nothing fetched.

WHY THIS ACCUMULATES
────────────────────
The feed is a ROLLING WINDOW — measured 2026-08-04 it served 200 rows
spanning five days across 83 leagues.  A single fetch is a snapshot,
not a history, so each run merges into
``data/faab/crowd_history_<leagueKey>.json``, deduped by the KTC row
id (stable across fetches).  Run it on the scrape cadence and a real
sample builds over a season.

WHAT THIS IS NOT
────────────────
It is an anonymous crowd of MyFantasyLeague managers, NOT a panel of
experts, and no expert or ranking source in our pipeline is attached
to a league at all.  It is also used only to price the MARKET — how
contested a claim will be — never to price the PLAYER.  Our board owns
player value; letting a hype cycle bid up our own valuation is exactly
the double-count the FAAB engine exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources.ktc_identity import parse_ktc_identity  # noqa: E402
from src.trade import faab_comparability as FC  # noqa: E402
from src.trade.faab_engine import FaabConfig  # noqa: E402
from src.trade.faab_history import (  # noqa: E402
    build_crowd_market,
    load_crowd_history,
    merge_crowd_rows,
    save_crowd_history,
)

WAIVER_DB_URL = "https://keeptradecut.com/dynasty/waiver-database"
_TIMEOUT = 30
_UA = "Mozilla/5.0 (compatible; riskittogetthebrisket/1.0)"


def fetch_rows() -> list[dict[str, Any]]:
    """Pull and parse the inline ``var waivers`` array.

    The rows are embedded in the page HTML, not served over an XHR —
    which is why the Playwright scraper's response-interception path
    always timed out and shipped an empty crowd block.  A plain HTTP
    GET is enough and needs no browser.

    The ``sf`` / ``tep`` query params are deliberately omitted: measured
    2026-08-04, they do not filter this payload (``sf=0&tep=0`` and
    ``sf=1&tep=2`` return byte-identical rows).  They drive the rendered
    DOM only, so format filtering happens below.
    """
    req = urllib.request.Request(WAIVER_DB_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        html = resp.read().decode("utf-8", errors="replace")

    waivers = re.search(r"var\s+waivers\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not waivers:
        return []
    rows = json.loads(waivers.group(1))

    # Identity comes from the ONE owner, not a second inline regex here.
    # This used to read ``playersArray`` (the 500-row value board) and
    # ``continue`` past anything it could not resolve, which silently
    # discarded 47 of 192 real claims per fetch.  The owner prefers
    # ``allPlayerSearchValues`` (~1,997 rows) and resolves all of them.
    identity = parse_ktc_identity(html)
    if not identity.players:
        # No identity observed is NOT an empty market — refuse rather
        # than emit rows whose player is unknown.
        raise RuntimeError("KTC identity map is empty; refusing to emit unjoinable rows")

    out: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        settings = row.get("settings") or {}
        try:
            budget = float(settings.get("totalBlindBidWaiverAmount") or 0)
            bid = float(row.get("blindBid") or 0)
        except (TypeError, ValueError):
            continue
        if budget <= 0 or bid < 0:
            continue

        # The claimed asset must be a PLAYER.  A pick or a FAAB amount in
        # this position is a real thing the feed carries, not a failure —
        # but it is not a waiver price for a player, so it is counted and
        # excluded rather than dropped without trace.
        picked = identity.classify(row.get("pickedUpPlayer"))
        if not picked.is_player:
            skipped[picked.reason or picked.kind] = skipped.get(picked.reason or picked.kind, 0) + 1
            continue
        added = picked.name

        # KTC uses -1 for "no drop"; ~half of all claims are no-drop.
        # An unresolved drop is None (unknown), which is what the storage
        # layer already means by a missing drop — never a fabricated name.
        dropped_asset = identity.classify(row.get("droppedPlayer"))
        dropped = dropped_asset.name if dropped_asset.is_player else None

        share = FC.normalized_bid_share(bid, budget)
        out.append(
            {
                "id": row.get("id"),
                "date": row.get("date"),
                "added": added,
                "dropped": dropped,
                # Raw bid AND raw starting budget are preserved alongside the
                # normalized values so any consumer can audit the conversion
                # (owner spec section 3).
                "bid": bid,
                "budget": budget,
                "bidPct": round(100.0 * bid / budget, 3),
                "normalizedBidShare": None if share is None else round(share, 6),
                "settings": {
                    "leagueId": str(settings.get("id") or ""),
                    "teams": settings.get("teams"),
                    # ``None`` means the vendor did not tell us, which is
                    # NOT the same statement as "1QB" or "no TEP".  If
                    # KTC renames a key, the old code turned every league
                    # in the feed into a 1QB non-TEP league and the
                    # comparable count fell to zero — reported as an
                    # empty market rather than as a broken parse.
                    "superflex": _superflex_of(settings),
                    "tep": settings.get("tep") if "tep" in settings else None,
                    # KTC publishes tep as 0/1/2/3 (Off / TE+ / TE++ /
                    # TE+++).  The boolean above answers "TEP at all"; the
                    # level answers "how much", and TE+ is not TE+++.
                    "tepLevel": settings.get("tep") if "tep" in settings else None,
                    # Two mandatory TE starters — named separately from TEP
                    # by the owner spec, because they are separate settings
                    # and either one on its own changes TE waiver demand.
                    "is2TE": settings.get("is2TE") if "is2TE" in settings else None,
                    # Roster EXCLUSIVITY.  > 1 means the same player may sit
                    # on several rosters at once, so the league has no waiver
                    # scarcity and its claims clear near nothing.  Measured
                    # 2026-08-18: such leagues were 37% of everything the old
                    # gate admitted, at a 5x lower median.
                    "rostersPerPlayer": (
                        settings.get("rostersPerPlayer") if "rostersPerPlayer" in settings else None
                    ),
                    # Whether the league starts INDIVIDUAL defenders.  A team
                    # ``Def`` slot is not IDP, and the distinction decides
                    # whether this row may ever price a linebacker.
                    "hasIdpSlots": FC.source_format_from_settings(settings).has_idp_slots,
                    "originalBudget": budget,
                    "ppr": settings.get("ppr"),
                    "platform": settings.get("dynastyPlatformType"),
                },
            }
        )
    if skipped:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(skipped.items()))
        print(f"  identity: {len(out)} rows kept · excluded {detail}", file=sys.stderr)

    # A feed nobody can classify is a PARSE failure, not an empty market.
    # Without this, a renamed settings key silently drops every league out
    # of every format bucket and the run reports "0 comparable" as health.
    unformattable = sum(
        1 for r in out if r["settings"]["superflex"] is None or r["settings"]["tep"] is None
    )
    if out and unformattable == len(out):
        raise RuntimeError(
            f"all {len(out)} crowd rows have an unreadable format "
            "(superflex/tep settings keys missing) — refusing to report an empty market"
        )
    # Same posture for roster exclusivity, which is now a hard gate: if the
    # vendor renames ``rostersPerPlayer`` every row fails closed and the run
    # would report "0 comparable" as though the market were quiet.  A universal
    # parse failure is a FAILURE, not an empty market.
    if out and all(r["settings"]["rostersPerPlayer"] is None for r in out):
        raise RuntimeError(
            f"all {len(out)} crowd rows lack rostersPerPlayer — the roster-exclusivity "
            "gate cannot be applied; refusing to report an empty market"
        )
    if unformattable:
        print(f"  format: {unformattable} of {len(out)} rows unclassifiable", file=sys.stderr)
    return out


def _superflex_of(settings: dict[str, Any]) -> bool | None:
    """Whether this crowd league is superflex, or ``None`` if unstated."""
    if "qBs" not in settings:
        return None
    try:
        return int(settings["qBs"]) >= 2
    except (TypeError, ValueError):
        return None


def league_budget_for(league_key: str) -> float | None:
    """The target league's ORIGINAL FAAB budget, for the $-equivalent display.

    Read from the FAAB config's ``leagueRules.defaultBudget``, which is the
    same documented fallback the engine uses when Sleeper's live settings are
    not to hand.  ``None`` rather than a guess when it is unreadable: an
    unknown budget has no scale, so the equivalent is simply omitted instead of
    being quoted against an invented one.  It affects the display column only —
    every stored percentage is already budget-neutral.
    """
    try:
        value = float(FaabConfig().get("leagueRules", "defaultBudget", 0) or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def classify_rows(
    rows: list[dict[str, Any]],
    target: FC.TargetFormat,
    *,
    policy: FC.ComparabilityPolicy,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """``(kept, exclusion census)`` for one target league.

    The verdict comes from ``src.trade.faab_comparability`` — the one owner of
    "is this external league's waiver price meaningful here".  This script
    stores evidence and applies the verdict; it decides nothing itself, so a
    later policy change re-classifies the accumulated ledger on read without a
    refetch.
    """
    kept: list[dict[str, Any]] = []
    census: dict[str, int] = {}
    for row in rows:
        fmt = FC.source_format_from_settings(row.get("settings"))
        verdict = FC.classify(fmt, target, policy=policy)
        if verdict.excluded:
            for reason in verdict.reasons or ("excluded",):
                census[reason] = census.get(reason, 0) + 1
            continue
        stamped = dict(row)
        stamped["comparability"] = verdict.to_dict()
        stamped["dynastyProvenance"] = FC.DYNASTY_PROVENANCE_SOURCE_LEVEL
        equiv = FC.equivalent_on_budget(row.get("normalizedBidShare"), target.original_budget)
        if equiv is not None:
            stamped["equivalentOnTargetBudget"] = round(equiv, 2)
        kept.append(stamped)
    return kept, census


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default=None, help="only this league key")
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args()

    try:
        from src.api import league_registry

        leagues = [
            cfg
            for cfg in league_registry.active_leagues()
            if not args.league or cfg.key == args.league
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"error: league registry unreadable: {exc}", file=sys.stderr)
        return 1
    if not leagues:
        print("error: no matching active leagues", file=sys.stderr)
        return 2

    try:
        rows = fetch_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"error: crowd fetch failed: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("error: no rows parsed from the waiver database", file=sys.stderr)
        return 2
    print(f"fetched {len(rows)} crowd claims")

    now_iso = datetime.now(timezone.utc).isoformat()
    policy = FC.ComparabilityPolicy.from_config(FaabConfig())
    for cfg in leagues:
        # The comparator profile comes from the TARGET league's own canonical
        # settings, never a hardcoded Brisket shape — the product is expected
        # to serve other people's dynasty leagues later (owner spec section 7).
        target = FC.TargetFormat.from_league_config(
            cfg,
            roster_settings=league_registry.get_league_roster_settings(cfg.key) or {},
            original_budget=league_budget_for(cfg.key),
        )

        keep, census = classify_rows(rows, target, policy=policy)
        print(
            f"→ {cfg.key}: {len(keep)} of {len(rows)} comparable "
            f"({target.teams}tm superflex={target.superflex} tep={target.tep} "
            f"2TE={target.is_2te} idp={target.idp})"
        )
        if census:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(census.items(), key=lambda kv: -kv[1]))
            print(f"   excluded: {detail}")
        if not keep:
            continue

        merged = merge_crowd_rows(load_crowd_history(cfg.key), keep, now_iso=now_iso)
        market = build_crowd_market(merged, target=target, now_iso=now_iso, policy=policy)
        index = market.index
        print(
            f"   +{merged['addedLastRun']} new · {len(merged['rows'])} total rows · "
            f"{len(index)} players priced · tiers {market.tier_counts} · "
            f"state {market.state}"
        )
        if not market.prices_idp and target.idp:
            # Named, not silently absorbed: this league starts IDP and the
            # external population contains no IDP league, so crowd evidence
            # will be refused for defenders downstream.
            print(
                "   note: no IDP league in the retained population — "
                "crowd evidence will not price DL/LB/DB claims"
            )
        if args.dry_run:
            top = sorted(index.items(), key=lambda kv: -kv[1]["medianPct"])[:8]
            for key, v in top:
                print(f"     {key:24s} median {v['medianPct']:>5.1f}%  ({v['claims']} claims)")
            continue
        print(f"   wrote {save_crowd_history(cfg.key, merged)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
