#!/usr/bin/env python3
"""C1-ID-01 ownership harness: is the canonical owner deciding identity?

The acceptance evidence for manifest row ``C1-ID-01`` (execution map
C1-U2).  Its job changed when the unit cut over, and deliberately so:

* **Before the cutover** it answered "does the canonical engine reproduce
  the legacy matchers on the live corpus?" — the zero-divergence prod
  gate.  That gate passed (scraper 2,016/2,016 over a full production
  refresh cycle; contract 24,024/24,024) and the legacy paths were
  deleted.
* **After the cutover** there is no legacy answer left to compare
  against, so the harness asserts the property the deletion bought:
  **both sites report the canonical owner as their decider.**  A harness
  that kept looking for a comparison would report "no data" forever and
  a reader could mistake that for "nothing to see".

Sites measured:

* ``contract_csv_join`` — rebuilds the live contract from
  ``exports/latest`` + ``CSVs/site_raw`` and reads its ``identityJoin``
  stamp (owner, policy, decision counts).
* ``scraper_sleeper_attach`` — reads the artifact the production scraper
  writes every cycle at ``data/scrape_state/identity_dual_read.json``.
  This harness cannot run the scraper inside a request; the artifact IS
  the evidence, produced where the resolution happens.  Absent artifact →
  reported honestly (exit 2 under ``--require-scraper-artifact``, the
  prod-gate mode).  It also carries the standing ``v2WouldChange`` gap.
* optionally, with ``--directory PATH`` (a Sleeper ``/v1/players/nfl``
  dump): the W06-F006 false-merge sweep under CANONICAL_V2 (must be 0)
  and the served-vs-V2 delta — the measured cost of the deferred semantic
  step, reported and never asserted, because V2 is not authorized to
  serve (see the design doc §9).

Both shapes are still accepted: a pre-cutover artifact (``v1Diverge``)
is validated as a divergence gate, a post-cutover one (``servedBy``) as
an ownership assertion.  Old evidence stays readable.

Exit codes (playerctx convention): 0 = all measured gates green ·
1 = a gate failed · 2 = required evidence missing ("no data" must never
read as "passed").
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
    # Post-cutover shape: the build stamps who decided its joins.
    summary = contract.get("identityJoin")
    if isinstance(summary, dict) and summary.get("decisions"):
        ok = summary.get(
            "decidedBy"
        ) == "src.identity.resolution.match_row_to_source_entry" and bool(
            summary.get("legacyCascadeRetired")
        )
        return ok, summary
    # Pre-cutover shape, kept readable so historical evidence still verifies.
    tally = contract.get("identityDualRead")
    if isinstance(tally, dict) and tally.get("calls"):
        return tally.get("v1Diverge") == 0, tally
    return False, {"error": "contract build reported no identity-join evidence"}


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
    if not payload.get("calls"):
        return False, {"error": "artifact records no resolution decisions"}
    if payload.get("servedBy"):
        # Post-cutover: assert ownership, not agreement.
        ok = payload.get("servedBy") == "src.identity.resolution" and bool(
            payload.get("legacyLadderRetired")
        )
        return ok, payload
    # Pre-cutover divergence gate.
    return payload.get("v1Diverge") == 0, payload


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
            f"served-vs-V2 board delta: {d['differ']} of {d['boardNames']} names "
            "(the deferred semantic step's measured cost — informational; V2 is not "
            "authorized to serve, see the design doc §9)"
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
