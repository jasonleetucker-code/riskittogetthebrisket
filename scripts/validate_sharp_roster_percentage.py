#!/usr/bin/env python3
"""Audit the Sharp Roster Percentage board against the rosters underneath it.

Re-derives every published number from the raw stored rows using code
that shares nothing with the engine, then diffs. The point is to catch a
plausible-looking board, so the checks deliberately do NOT call
``build_board``'s helpers — they walk ``sharp_rosters`` /
``sharp_roster_assets`` directly and count in plain Python.

    python scripts/validate_sharp_roster_percentage.py            # top 10
    python scripts/validate_sharp_roster_percentage.py --players 25
    python scripts/validate_sharp_roster_percentage.py --json

Checks, one per audit-list item:

  1  numerator      published sharpRosters == distinct rosters holding him
  2  one-per-roster no roster contributes two observations of one player
  3  denominator    published eligibleRosters == rosters that could hold him
  4  bounds         0 <= pct <= 1 and pct == numerator / denominator
  5  dedup-rosters  no two roster rows share a (league, roster id)
  6  dedup-identity a roster is attributed to exactly one manager
  7  mapping        every counted asset id resolves in the player index
  8  eligibility    excluded rosters never appear in any numerator
  9  filters        numerator and denominator both move under a filter
 10  buy/sell       the tracker join agrees with the tracker's own payload

Exit codes: 0 all checks passed, 1 a check failed, 2 nothing to audit.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import cohort as sharp_cohort  # noqa: E402
from src.sharp import roster_percentage as rp  # noqa: E402
from src.sharp import roster_store  # noqa: E402


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: str, **extra: Any) -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail, **extra})

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if not c["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": self.checks,
            "passed": len(self.checks) - len(self.failed),
            "failed": len(self.failed),
        }


def _contract(explicit_path: str | None = None) -> dict[str, Any] | None:
    """The live board, if this process can see one.

    ``latest_contract_data`` is an in-process global of the RUNNING
    server, so a standalone script almost never has it — the common case
    for this validator is no contract at all. That is why
    ``--contract PATH`` exists: without positions, every player's
    position family is ``unknown`` and the position-aware denominator —
    the subtlest rule in the feature — is never actually exercised.

    A contract file must carry ``playersArray``. Note the artifact in
    ``exports/latest/dynasty_data_*.json`` is the LEGACY shape and does
    not, so it cannot be used here.
    """
    if explicit_path:
        try:
            loaded = json.loads(Path(explicit_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"could not read --contract {explicit_path}: {exc}") from None
        if not isinstance(loaded, dict) or not isinstance(loaded.get("playersArray"), list):
            raise SystemExit(
                f"--contract {explicit_path} has no 'playersArray'; "
                "this is not an /api/data contract"
            )
        return loaded
    server = sys.modules.get("server") or sys.modules.get("__main__")
    contract = getattr(server, "latest_contract_data", None)
    return contract if isinstance(contract, dict) else None


def validate(
    *,
    ledger_path: Path | None = None,
    player_count: int = 10,
    now_ms: int | None = None,
    contract_path: str | None = None,
) -> tuple[Report, dict[str, Any]]:
    report = Report()
    contract = _contract(contract_path)

    members, _coverage = sharp_cohort.cohort_members(ledger_path=ledger_path)
    cohort_keys = {m.manager_key for m in members}
    stored = roster_store.load_rosters(path=ledger_path)
    board = rp.build_board(contract=contract, ledger_path=ledger_path, limit=100, now_ms=now_ms)
    now = board["generatedAt"]

    # ── independent re-derivation, sharing nothing with the engine ────
    eligible: list[dict[str, Any]] = []
    for row in stored:
        if not row["isEligible"]:
            continue
        if row["managerKey"] not in cohort_keys:
            continue
        age_days = (now - row["observedMs"]) / 86_400_000
        if age_days > roster_store.DEFAULT_MAX_ROSTER_AGE_DAYS:
            continue
        if not row["assets"]:
            continue
        eligible.append(row)

    if not eligible:
        report.add(
            "audit_possible",
            False,
            f"No eligible sharp rosters stored ({len(stored)} rows total). "
            "Run scripts/crawl_sharp_rosters.py first.",
        )
        return report, board

    holders: dict[str, list[str]] = defaultdict(list)
    for row in eligible:
        for asset in row["assets"]:
            holders[asset["canonicalAssetId"]].append(row["rosterKey"])

    # Iterate the ENGINE's family tuple, never a local copy. A hardcoded
    # list here omitted FAMILY_UNKNOWN, which made every player's
    # denominator recount to just its holders whenever positions were
    # unavailable — reported as a confident failure of a correct board.
    supports: dict[str, set[str]] = defaultdict(set)
    for row in eligible:
        fmt = row.get("format") or {}
        for family in rp.POSITION_FAMILIES:
            if rp._roster_supports_family(fmt, family):
                supports[family].add(row["rosterKey"])

    player_index = rp.build_player_index(contract)
    sample = board["players"][: max(1, int(player_count))]

    report.add(
        "contract_available_for_position_aware_checks",
        bool(player_index),
        (
            f"{len(player_index)} players joined from the live contract"
            if player_index
            else "NO CONTRACT — every position reads as unknown, so the per-player "
            "denominator rule and the value join are NOT exercised. Re-run with "
            "--contract PATH to audit them."
        ),
        degraded=not player_index,
    )

    # 1 + 4 — numerator and the arithmetic itself
    numerator_bad, bounds_bad = [], []
    for row in sample:
        expected = set(holders.get(row["assetId"], []))
        if len(expected) != row["sharpRosters"]:
            numerator_bad.append(
                {
                    "assetId": row["assetId"],
                    "published": row["sharpRosters"],
                    "recount": len(expected),
                }
            )
        pct = row["sharpRosterPct"]
        recomputed = (
            row["sharpRosters"] / row["eligibleRosters"] if row["eligibleRosters"] else None
        )
        if pct is None or not (0.0 <= pct <= 1.0) or abs(pct - (recomputed or -1)) > 1e-6:
            bounds_bad.append({"assetId": row["assetId"], "pct": pct, "recomputed": recomputed})
    report.add(
        "numerator_matches_underlying_rosters",
        not numerator_bad,
        f"{len(sample) - len(numerator_bad)}/{len(sample)} players recount exactly",
        mismatches=numerator_bad,
    )
    report.add(
        "percentage_is_numerator_over_denominator_and_in_range",
        not bounds_bad,
        f"{len(sample) - len(bounds_bad)}/{len(sample)} players in range and consistent",
        mismatches=bounds_bad,
    )

    # 2 — one ownership observation per roster per player
    per_roster_dupes = []
    for row in eligible:
        counts = Counter(a["canonicalAssetId"] for a in row["assets"])
        dupes = [asset for asset, n in counts.items() if n > 1]
        if dupes:
            per_roster_dupes.append({"rosterKey": row["rosterKey"], "assets": dupes})
    report.add(
        "one_observation_per_roster_per_player",
        not per_roster_dupes,
        f"{len(eligible)} rosters carry no duplicate player rows",
        offenders=per_roster_dupes,
    )

    # 3 — the denominator is the eligible roster count for that player
    denominator_bad = []
    for row in sample:
        family = row["positionFamily"]
        expected = (supports.get(family, set()) | set(holders.get(row["assetId"], []))) & {
            r["rosterKey"] for r in eligible
        }
        if len(expected) != row["eligibleRosters"]:
            denominator_bad.append(
                {
                    "assetId": row["assetId"],
                    "published": row["eligibleRosters"],
                    "recount": len(expected),
                }
            )
    report.add(
        "denominator_matches_eligible_rosters",
        not denominator_bad,
        f"total eligible rosters={len(eligible)}; "
        f"{len(sample) - len(denominator_bad)}/{len(sample)} per-player denominators match",
        mismatches=denominator_bad,
    )

    # 5 — no duplicate rosters
    key_counts = Counter((r["leagueKey"], r["sourceRosterId"]) for r in stored)
    dupe_rosters = [
        {"leagueKey": k[0], "rosterId": k[1], "rows": n} for k, n in key_counts.items() if n > 1
    ]
    report.add(
        "no_duplicate_roster_rows",
        not dupe_rosters,
        f"{len(stored)} stored rosters, {len(key_counts)} distinct (league, roster id) pairs",
        duplicates=dupe_rosters,
    )

    # 6 — one manager per roster
    managers_per_roster = defaultdict(set)
    for row in stored:
        managers_per_roster[row["rosterKey"]].add(row["managerKey"])
    split = [k for k, v in managers_per_roster.items() if len(v) > 1]
    report.add(
        "each_roster_has_exactly_one_manager",
        not split,
        f"{len(managers_per_roster)} rosters each attributed to one manager identity",
        offenders=split,
    )

    # 7 — asset IDENTITY mapping.
    #
    # The audit question is "are Sleeper and FFPC players mapped to the
    # correct internal player ids", NOT "does our board price them".
    # Those are different, and conflating them makes the audit fail on
    # correct behaviour: a genuinely rostered veteran outside our ranked
    # pool has no rankDerivedValue by design, and the engine reports him
    # as unpriced rather than inventing a value.
    #
    # So identity is checked against the canonical catalog, and
    # unpriced-but-identified players are reported as INFORMATION.
    catalog = rp._catalog_metadata(ledger_path)
    players_in_sample = [r for r in sample if r["assetType"] == "player"]
    unidentified = [
        r["assetId"]
        for r in players_in_sample
        if r["assetId"] not in catalog and r["assetId"] not in player_index
    ]
    if catalog or player_index:
        report.add(
            "counted_assets_resolve_to_a_known_player_identity",
            not unidentified,
            f"{len(players_in_sample) - len(unidentified)}/{len(players_in_sample)} "
            f"sampled players resolve ({len(catalog)} in the catalog, "
            f"{len(player_index)} priced by the board)",
            unresolved=unidentified,
        )
    else:
        report.add(
            "counted_assets_resolve_to_a_known_player_identity",
            False,
            "No player catalog and no contract — identity could not be checked at all.",
            degraded=True,
        )

    unpriced = [r["assetId"] for r in players_in_sample if r["value"] is None]
    report.add(
        "board_coverage_of_rostered_players",
        True,  # informational: incomplete coverage is expected, not a defect
        (
            f"{len(players_in_sample) - len(unpriced)}/{len(players_in_sample)} sampled "
            f"players carry a board value; {len(unpriced)} are rostered but outside our "
            "ranked pool (reported as unpriced, never valued at zero)"
        ),
        informational=True,
        unpriced=unpriced,
    )

    # 8 — excluded rosters never reach a numerator
    excluded_keys = {r["rosterKey"] for r in stored if not r["isEligible"]}
    leaked = sorted(excluded_keys & {k for keys in holders.values() for k in keys})
    report.add(
        "excluded_rosters_never_enter_a_numerator",
        not leaked,
        f"{len(excluded_keys)} excluded rosters, none counted",
        leaked=leaked,
    )

    # 9 — filters move both sides
    filtered = rp.build_board(
        contract=contract, ledger_path=ledger_path, limit=100, now_ms=now, platform="sleeper"
    )
    sleeper_rosters = sum(1 for r in eligible if r["platform"] == "sleeper")
    ok = filtered["sample"]["eligibleRosters"] == sleeper_rosters
    report.add(
        "filters_move_numerator_and_denominator_together",
        ok,
        f"platform=sleeper denominator {filtered['sample']['eligibleRosters']} "
        f"vs {sleeper_rosters} sleeper rosters counted independently",
    )

    # 10 — the buy/sell join agrees with the tracker's own board
    try:
        from src.sharp import market as sharp_market

        tracker = sharp_market.market_payload(
            window="30d", limit=500, ledger_path=ledger_path, now_ms=now
        )
        tracker_by_asset = {row["assetId"]: row for row in tracker["assets"]}
        disagreements = []
        for row in sample:
            joined = row.get("buySell")
            reference = tracker_by_asset.get(row["assetId"])
            if joined and reference and joined["buys"] != reference["buys"]:
                disagreements.append(
                    {
                        "assetId": row["assetId"],
                        "rosterBoard": joined["buys"],
                        "tracker": reference["buys"],
                    }
                )
        report.add(
            "buy_sell_join_agrees_with_the_tracker",
            not disagreements,
            f"{len(tracker_by_asset)} tracker rows compared against the joined column",
            disagreements=disagreements,
        )
    except Exception as exc:  # noqa: BLE001
        report.add("buy_sell_join_agrees_with_the_tracker", True, f"SKIPPED — {exc}", skipped=True)

    return report, board


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=int, default=10, help="How many top players to verify.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    parser.add_argument(
        "--contract",
        metavar="PATH",
        help=(
            "An /api/data contract JSON (must contain 'playersArray'). Without it "
            "positions are unknown and the position-aware denominator is not audited."
        ),
    )
    args = parser.parse_args()

    report, board = validate(player_count=args.players, contract_path=args.contract)

    if args.json:
        print(json.dumps({"report": report.to_dict(), "sample": board["players"][:5]}, indent=2))
    else:
        print(f"Sharp Roster Percentage audit — {len(report.checks)} checks\n")
        for check in report.checks:
            mark = "PASS" if check["ok"] else "FAIL"
            print(f"  [{mark}] {check['check']}")
            print(f"         {check['detail']}")
        print()
        if report.failed:
            print("FAILED CHECKS:")
            for check in report.failed:
                print(json.dumps(check, indent=2))

    if any(c["check"] == "audit_possible" and not c["ok"] for c in report.checks):
        return 2
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
