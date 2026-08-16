#!/usr/bin/env python3
"""C1-ID-01 parity harness: legacy matchers vs the canonical identity engine.

The acceptance evidence for manifest row ``C1-ID-01`` (execution map
C1-U2).  One command answers "does the canonical engine reproduce the
legacy matchers on the live corpus, and what would the repaired
CANONICAL_V2 semantics change?"

Sites measured:

* ``contract_csv_join`` — rebuilds the live contract from
  ``exports/latest`` + ``CSVs/site_raw`` and reads the build's own
  dual-read tally (every (row, source) join decision compared).
* ``scraper_sleeper_attach`` — reads the artifact the production scraper
  writes every cycle at ``data/scrape_state/identity_dual_read.json``.
  This harness cannot run the scraper's run()-scope ladder itself; the
  artifact IS the evidence, produced where the ladder lives.  Absent
  artifact → reported honestly (exit 2 under ``--require-scraper-artifact``,
  the prod-gate mode).
* optionally, with ``--directory PATH`` (a Sleeper ``/v1/players/nfl``
  dump): the W06-F006 false-merge sweep under CANONICAL_V2 (must be 0)
  and the V1-vs-V2 board delta (the measured cost of the future semantic
  cutover — reported, never asserted, because that step is owner-gated).

Exit codes (playerctx convention): 0 = all measured gates green ·
1 = divergence found · 2 = required evidence missing ("no data" must
never read as "passed").
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCRAPER_ARTIFACT = REPO / "data" / "scrape_state" / "identity_dual_read.json"


def check_contract_join() -> tuple[bool, dict]:
    from src.api.data_contract import build_api_data_contract

    boards = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if not boards:
        return False, {"error": "no exports/latest/dynasty_data_*.json board to build from"}
    raw = json.loads(boards[0].read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(raw)
    tally = contract.get("identityDualRead")
    if not isinstance(tally, dict) or not tally.get("calls"):
        return False, {"error": "contract build produced no identityDualRead tally"}
    ok = tally.get("v1Diverge") == 0
    return ok, tally


def check_scraper_artifact() -> tuple[bool | None, dict]:
    if not SCRAPER_ARTIFACT.exists():
        return None, {
            "error": (
                "data/scrape_state/identity_dual_read.json not present — the artifact is "
                "written by each scrape cycle; on a dev checkout it appears after the next "
                "scheduled-refresh commit"
            )
        }
    try:
        payload = json.loads(SCRAPER_ARTIFACT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, {"error": f"artifact unreadable: {exc}"}
    ok = payload.get("v1Diverge") == 0 and bool(payload.get("calls"))
    return ok, payload


def sweep_directory(directory_path: Path) -> dict:
    from src.identity import resolution as R
    from src.identity.name_primitives import clean_name

    directory = json.loads(directory_path.read_text(encoding="utf-8"))
    if "players" in directory and isinstance(directory.get("players"), dict):
        directory = directory["players"]
    idx = R.build_sleeper_index(directory)

    # W06-F006: the 11 measured false-merge pairs must all die under V2.
    pairs_path = REPO / "docs/master-site-audit/evidence/W06/fuzzy-false-merges.json"
    f006 = {"pairs": 0, "falseMerges": 0, "detail": []}
    if pairs_path.exists():
        for src_name, wrong_name, pos, _score, _method in json.loads(pairs_path.read_text()):
            f006["pairs"] += 1
            wrong_ids = {c.sleeper_id for c in idx.by_clean.get(clean_name(wrong_name), [])}
            got = R.resolve_canonical_v2(idx, name=src_name, position=pos or None)
            hit = bool(got.resolved and got.sleeper_id in wrong_ids)
            if hit:
                f006["falseMerges"] += 1
                f006["detail"].append({"input": src_name, "wrong": wrong_name})

    # V1-vs-V2 delta over the live board vocabulary: the measured cost of
    # the future (owner-gated) semantic step.
    delta = {"boardNames": 0, "differ": 0, "examples": []}
    boards = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if boards:
        players = json.loads(boards[0].read_bytes()).get("players") or {}
        for nm, pdata in players.items():
            pos = str((pdata or {}).get("position") or "")
            v1 = R.resolve_scraper_attach_v1(idx, nm, preferred_pos=pos)
            v2 = R.resolve_canonical_v2(idx, name=nm, position=pos or None)
            delta["boardNames"] += 1
            a = v1.sleeper_id if v1.resolved else None
            b = v2.sleeper_id if v2.resolved else None
            if a != b:
                delta["differ"] += 1
                if len(delta["examples"]) < 40:
                    delta["examples"].append(
                        {"name": nm, "pos": pos, "v1": a, "v2": b, "v2Reason": v2.reason}
                    )
    return {"f006": f006, "v1VsV2": delta}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--require-scraper-artifact",
        action="store_true",
        help="prod-gate mode: a missing scraper dual-read artifact is a failure (exit 2)",
    )
    ap.add_argument(
        "--directory",
        type=Path,
        default=None,
        help="optional Sleeper /v1/players/nfl dump for the V2 sweep",
    )
    args = ap.parse_args()

    failures = 0
    missing = 0

    ok, tally = check_contract_join()
    print("== contract_csv_join ==")
    print(json.dumps({k: v for k, v in tally.items() if k != "v1Examples"}, indent=1))
    if tally.get("v1Examples"):
        print("divergence examples:", json.dumps(tally["v1Examples"][:10], indent=1))
    if not ok:
        failures += 1

    print("\n== scraper_sleeper_attach ==")
    ok_a, payload = check_scraper_artifact()
    if ok_a is None:
        print(payload["error"])
        if args.require_scraper_artifact:
            missing += 1
    else:
        print(
            json.dumps(
                {k: v for k, v in payload.items() if k not in ("v1Examples", "v2Examples")},
                indent=1,
            )
        )
        if payload.get("v1Examples"):
            print("v1 divergence examples:", json.dumps(payload["v1Examples"][:10], indent=1))
        if not ok_a:
            failures += 1

    if args.directory:
        print("\n== CANONICAL_V2 sweep ==")
        sweep = sweep_directory(args.directory)
        print(json.dumps(sweep["f006"], indent=1))
        d = sweep["v1VsV2"]
        print(
            f"V1-vs-V2 board delta: {d['differ']} of {d['boardNames']} names "
            "(the owner-gated semantic step's measured cost — informational)"
        )
        for ex in d["examples"][:15]:
            print(
                f"  {ex['name']:<26} pos={ex['pos']:<4} v1={ex['v1']} v2={ex['v2']} ({ex['v2Reason']})"
            )
        if sweep["f006"]["falseMerges"]:
            failures += 1

    print(
        f"\nRESULT: failures={failures} missing-evidence={missing} "
        f"-> exit {(1 if failures else (2 if missing else 0))}"
    )
    return 1 if failures else (2 if missing else 0)


if __name__ == "__main__":
    raise SystemExit(main())
