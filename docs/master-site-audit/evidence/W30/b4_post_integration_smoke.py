#!/usr/bin/env python3
"""B4 post-integration smoke — is the shipped half still behaviour-preserving?

Run after merging current ``main`` into the B4 branch. This is **not** a
re-measurement of W30-F023 and deliberately produces no candidate numbers.

Why it cannot be one
--------------------

The merge rewrote ``exports/latest/dynasty_data_2026-08-11.json`` IN PLACE:
same filename, different scrape, different content. The committed B4
evidence is pinned to sha256 ``8fb6ede274171aee…`` of that exact path, and
that path no longer hashes to it. So every B4 figure — 421/5,146, 254
served rows, the A/B/C/D table, the corridor before/after — is attached to
an input this tree no longer contains.

Re-running ``b4_tail_measure.py`` here would overwrite those reports with
numbers from a different experiment under the same filenames, which is the
precise substitution a pin exists to prevent. The B4 evidence is therefore
**historical** and is left alone.

What this checks instead
------------------------

Six properties, all of which must hold on the integrated tree regardless of
which board is on disk, because the shipped change is behaviour-preserving
by construction:

1. the tail owner reproduces the pre-B4 rule exactly, in every universe;
2. no production value changes vs the pre-B4 canonical functions;
3. ``valueContributionPath`` matches the branch actually taken;
4. the B4 tripwires are still xfail, never XPASS;
5. the B3 corridor characterization is untouched;
6. audit/status gates are clean.

This script owns (1), (2) and (3) — the ones that need a board build and
so cannot be expressed as unit tests. (4), (5) and (6) already have real
suites and are deliberately NOT re-implemented here; re-checking them in a
second place would be a copy that can pass while the real gate fails. The
commands are printed at the end of a run.

The pre-B4 functions are **extracted from git**, never hand-copied. A
hand-copy would drift from what actually shipped and would then be
comparing the new code against a reconstruction of itself.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent

#: The commit the B4 branch forked from — the last tree in which the four
#: independent tail clamps were still four.
PRE_B4_REF = "a89a07ea34d598553b560d5c120d6eb99a8d628c"

#: What the B4 evidence is pinned to. Recorded so this script can state
#: plainly whether the board on disk is that one.
B4_PINNED_BOARD_SHA256 = "8fb6ede274171aeeea5b01d1b88cd49c391133dfb83490c213b38bce2f4cee36"


def _git_show(path: str, ref: str = PRE_B4_REF) -> str:
    out = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def pre_b4_functions() -> tuple:
    """``(rank_to_percentile, percentile_to_value)`` as they shipped pre-B4.

    Executed from the git blob rather than transcribed. The whole point of
    the comparison is "does the refactor change behaviour", and a
    transcription can silently answer "no" by being wrong in the same
    direction as the new code.
    """
    src = _git_show("src/canonical/player_valuation.py")
    ns: dict = {}
    exec(compile(src, "<pre-b4 player_valuation>", "exec"), ns)  # noqa: S102
    return ns["rank_to_percentile"], ns["percentile_to_value"]


def board_sha() -> tuple[str, int, str]:
    board = ROOT / "exports/latest/dynasty_data_2026-08-11.json"
    if not board.is_file():
        candidates = sorted((ROOT / "exports/latest").glob("dynasty_data_*.json"), reverse=True)
        board = candidates[0]
    raw = board.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw), str(board.relative_to(ROOT))


def check_1_owner_reproduces_the_old_rule() -> dict:
    """The tail owner must equal ``min(1.0, p)`` in EVERY universe.

    Not only at the live N=500. The pre-B4 clamp was relative to the
    caller's declared reference population, and the fit and holdout tooling
    pass their own; a boundary expressed as an absolute rank would have
    changed their behaviour while leaving the live board alone.
    """
    from src.canonical.player_valuation import percentile_to_value, rank_to_percentile
    from src.canonical.rank_coordinates import RANK_POOL_SHARED_MARKET, curve_for_pool
    from src.canonical.tail_policy import TAIL_SATURATION_RANK

    old_r2p, old_p2v = pre_b4_functions()
    c, s = curve_for_pool(RANK_POOL_SHARED_MARKET)

    mismatches = []
    checked = 0
    for reference_n in (2, 3, 100, 370, 400, 499, 500, 501, 800, 903, 5000):
        for rank in (0, 1, 2, 50, 250, 499, 500, 501, 800, 877, 903, 5000, 99999):
            got = rank_to_percentile(rank, reference_n=reference_n)
            want = old_r2p(rank, reference_n=reference_n)
            checked += 1
            if got != want:
                mismatches.append(("rank_to_percentile", reference_n, rank, want, got))
    for p in (0.0, 0.25, 0.5, 0.9999, 1.0, 1.0001, 1.5, 1.8076, 5.0, -0.3):
        got = percentile_to_value(p, midpoint=c, slope=s)
        want = old_p2v(p, midpoint=c, slope=s)
        checked += 1
        if got != want:
            mismatches.append(("percentile_to_value", None, p, want, got))

    return {
        "tailSaturationRank": TAIL_SATURATION_RANK,
        "casesChecked": checked,
        "mismatches": mismatches,
        "ok": TAIL_SATURATION_RANK is None and not mismatches,
    }


def _build(patched: bool) -> list[dict]:
    """Build the board, optionally with the pre-B4 canonical functions.

    ``data_contract`` imports both functions inside
    ``_compute_unified_rankings``, so patching the module attributes is
    what the serving path actually resolves.
    """
    from src.api.data_contract import build_api_data_contract
    from src.canonical import player_valuation as pv

    _, _, rel = board_sha()
    raw = json.loads((ROOT / rel).read_bytes())

    saved = (pv.rank_to_percentile, pv.percentile_to_value)
    if patched:
        pv.rank_to_percentile, pv.percentile_to_value = pre_b4_functions()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(raw)
        return contract.get("playersArray") or []
    finally:
        pv.rank_to_percentile, pv.percentile_to_value = saved


def check_2_no_production_value_change() -> dict:
    """Whole-board A/B against the pre-B4 functions on the CURRENT data.

    Check 1 proves the functions agree pointwise; this proves the pipeline
    that consumes them agrees end-to-end, which is the claim a reader
    actually cares about.
    """
    new_rows = _build(patched=False)
    old_rows = _build(patched=True)

    def sig(rows):
        return {
            str(r.get("displayName")): (
                r.get("rankDerivedValue"),
                r.get("canonicalConsensusRank"),
            )
            for r in rows
        }

    a, b = sig(new_rows), sig(old_rows)
    diffs = [(k, b.get(k), v) for k, v in a.items() if b.get(k) != v]
    return {
        "rowsNew": len(new_rows),
        "rowsOld": len(old_rows),
        "rowsCompared": len(a),
        "differingRows": len(diffs),
        "examples": diffs[:5],
        "ok": len(a) == len(b) and not diffs,
    }


def check_3_contribution_path_is_honest() -> dict:
    """Recompute each value-based row's path and compare to the stamp.

    Independent of the stamping expression: derived from the raw value,
    the declared range and the suppression state, which are the three
    conditions the serving branch actually tests. This is the regression
    for the defect where the stamp was re-derived from a different
    question than the branch asked.
    """
    from src.api.data_contract import (
        _VALUE_BASED_SOURCES,
        _VALUE_SOURCE_DECLARED_MAX,
    )

    rows = _build(patched=False)
    wrong = []
    checked = 0
    fallbacks = 0
    for r in rows:
        site = r.get("canonicalSiteValues") or {}
        for key in _VALUE_BASED_SOURCES:
            meta = (r.get("sourceRankMeta") or {}).get(key)
            if not isinstance(meta, dict) or not isinstance(meta.get("effectiveRank"), int):
                continue
            checked += 1
            raw = site.get(key)
            try:
                f = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                f = 0.0
            ceiling = _VALUE_SOURCE_DECLARED_MAX.get(key)
            in_range = ceiling is None or (0.0 <= f <= ceiling)
            expect_direct = in_range and f > 0.0
            got = meta.get("valueContributionPath")
            if not expect_direct:
                fallbacks += 1
            # A row can still be on the Hill path for a reason this check
            # cannot see (whole-source suppression), so only the
            # value_direct direction is asserted: a row whose own value is
            # good MUST NOT be stamped rank_hill unless its source was
            # suppressed, and a row whose value is bad MUST NOT be stamped
            # value_direct at all.
            if not expect_direct and got == "value_direct":
                wrong.append((r.get("displayName"), key, raw, got))
            if expect_direct and got == "rank_hill" and not meta.get("valueDirectFallbackReason"):
                wrong.append((r.get("displayName"), key, raw, "rank_hill without a reason"))
    return {
        "valueDirectObservationsChecked": checked,
        "rowsRequiringFallback": fallbacks,
        "stampMismatches": wrong[:10],
        "ok": not wrong,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if not args.report:
        ap.error("pass --report")

    sha, size, rel = board_sha()
    print("== B4 post-integration smoke ==")
    print(
        f"  HEAD         {subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()[:9]}"
    )
    print(f"  board        {rel}")
    print(f"  sha256       {sha[:16]}…  {size} B")
    is_pin = sha == B4_PINNED_BOARD_SHA256
    print(f"  is the B4 pin? {is_pin}")
    if not is_pin:
        print("    -> the integrated tree carries a DIFFERENT board at the same path.")
        print("       The B4 evidence stays attached to its own pin and is NOT recomputed;")
        print("       nothing below is a W30-F023 measurement.")

    results = {
        "boardOnDisk": {"path": rel, "sha256": sha, "bytes": size, "isB4Pin": is_pin},
        "check1_ownerReproducesPreB4Rule": check_1_owner_reproduces_the_old_rule(),
        "check2_noProductionValueChange": check_2_no_production_value_change(),
        "check3_contributionPathIsHonest": check_3_contribution_path_is_honest(),
    }

    print("\n== 1. tail owner reproduces the pre-B4 rule (functions from git, not copied) ==")
    r = results["check1_ownerReproducesPreB4Rule"]
    print(
        f"  TAIL_SATURATION_RANK={r['tailSaturationRank']}  cases={r['casesChecked']}  "
        f"mismatches={len(r['mismatches'])}  -> {'OK' if r['ok'] else 'FAIL'}"
    )
    for m in r["mismatches"][:5]:
        print(f"    {m}")

    print("\n== 2. no production value change, whole board, current data ==")
    r = results["check2_noProductionValueChange"]
    print(
        f"  rows={r['rowsCompared']}  differing={r['differingRows']}  "
        f"-> {'OK' if r['ok'] else 'FAIL'}"
    )
    for e in r["examples"]:
        print(f"    {e}")

    print("\n== 3. valueContributionPath matches the branch actually taken ==")
    r = results["check3_contributionPathIsHonest"]
    print(
        f"  value-source observations={r['valueDirectObservationsChecked']}  "
        f"needing fallback={r['rowsRequiringFallback']}  "
        f"mismatches={len(r['stampMismatches'])}  -> {'OK' if r['ok'] else 'FAIL'}"
    )
    for m in r["stampMismatches"]:
        print(f"    {m}")

    ok = all(v["ok"] for k, v in results.items() if k.startswith("check"))
    results["allChecksPassed"] = ok
    (OUT / "b4_post_integration_smoke.json").write_text(json.dumps(results, indent=1, default=str))
    print(f"\nwrote {OUT / 'b4_post_integration_smoke.json'}")
    print(f"\n== {'ALL CHECKS PASSED' if ok else 'SMOKE FAILED'} ==")
    print("  Checks 4 (tripwires still xfail), 5 (B3 corridor characterization) and")
    print("  6 (audit/status) are owned by the real suites:")
    print("    pytest tests/canonical/test_percentile_tail_policy.py   -> 17 passed, 8 xfailed")
    print("    pytest tests/api/test_market_corridor_characterization.py")
    print("    scripts/audit_status.py ; scripts/check_decision_coercions.py")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
