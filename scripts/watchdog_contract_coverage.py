"""Contract-coverage watchdog — fails the scheduled-refresh workflow when
a registered ranking source is *fresh* (its CSV was fetched within
threshold) yet is **absent from the built contract** the server will
serve.

This is the sibling of ``scripts/watchdog_freshness.py``.  Freshness
answers "did the fetcher run recently?".  Coverage answers "did that
fetched data actually make it into the board?".  They are different
failure modes:

  * A fetcher dies         → freshness watchdog turns the run red.
  * A fetcher succeeds, the CSV is committed, but the source never
    appears in the served board (registry/enrich/timing regression)
    → only THIS watchdog catches it.

The second mode is exactly the one the operator hit: ``otcffbSf.csv``
was fetched and committed, but the served board carried zero OTCFFB
coverage, so isolating OTCFFB on the rankings page produced fallback
behaviour with no error anywhere.  Nothing asserted that a registered
source actually lands in the contract.  Now something does.

Method: build the contract the same way ``server._prime_latest_payload``
does (newest ``dynasty_data_*.json`` → ``build_api_data_contract`` →
``_enrich_from_source_csvs``), then count, per source, how many
``playersArray`` rows carry that key in ``sourceRankMeta`` (membership
there == "this source contributed to the blend", independent of
value/rank signal type).  A registered source that is fresh but covers
fewer than ``_MIN_COVERAGE`` players is reported.

Why gate on freshness: a stale source is already the freshness
watchdog's responsibility; double-reporting it here would just add
noise.  This guard's unique signal is *fresh-but-absent*.

Why ``_MIN_COVERAGE = 5``: the smallest legitimately-sparse registered
source observed in a healthy build is the DLF rookie-IDP board at ~27
covered players.  A floor of 5 trips only on the genuine
absent/near-absent regression and leaves wide margin against the
smallest real source, so it will not flake.

Exit codes:
  0 — every fresh registered source has real coverage
  1 — at least one fresh registered source is missing from the board,
      or the contract could not be built / no export was found

Output: human-readable stdout, GitHub Actions ``::error::``
annotations per offending source, and a step-summary table.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow ``python scripts/watchdog_contract_coverage.py`` from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.api.data_contract import (  # noqa: E402
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    build_api_data_contract,
)
from src.api.source_health_alerts import (  # noqa: E402
    load_thresholds,
    resolve_threshold,
)

# Reuse the freshness watchdog's stamp-or-mtime reader verbatim so the
# two watchdogs agree byte-for-byte on which sources are "fresh".
from scripts.watchdog_freshness import _read_freshness  # noqa: E402

# A fresh registered source covering fewer than this many players in
# the built contract is treated as absent.  See module docstring for
# the justification of this floor.
_MIN_COVERAGE = 5


def _find_latest_export() -> Path | None:
    """Newest ``dynasty_data_*.json`` the server would prime from.

    Mirrors ``server.py``'s real disk-bootstrap precedence — a strict
    first-non-empty-wins, not a global newest-across-all-locations:

      1. ``data/`` (``server.DATA_DIR``) — what ``load_from_disk`` and
         ``_latest_cached_contract_from_disk`` read FIRST; the live
         runtime source the deployed server actually primes from.
      2. ``exports/latest/`` — the git-committed snapshot.  PR-CI
         never runs a scrape, so ``data/`` is empty there and this is
         the only artifact present; it is also what
         ``tests/api/test_player_identity_regression.py`` and the
         project docs treat as "the file the live server reads".
      3. repo root (``server.BASE_DIR``) — ``load_from_disk``'s
         documented fallback for standalone scraper runs.

    Earlier revisions checked ``exports/latest`` before ``data/`` (or
    pooled locations and took a global max).  Both are wrong: the
    server reads ``data/`` first, so a ``data/``-only snapshot must
    win, and a stray repo-root file must never shadow the prioritized
    artifact — otherwise the watchdog validates the wrong contract or
    false-fails the workflow when a valid board exists only under
    ``data/``.  Within the chosen directory the newest filename wins
    (the date is embedded in the name); mtime breaks ties.
    """
    for base in (
        _REPO_ROOT / "data",
        _REPO_ROOT / "exports" / "latest",
        _REPO_ROOT,
    ):
        if not base.is_dir():
            continue
        found = list(base.glob("dynasty_data_*.json"))
        if found:
            return sorted(found, key=lambda p: (p.name, p.stat().st_mtime))[-1]
    return None


def _source_coverage(contract: dict) -> dict[str, int]:
    """# of playersArray rows whose ``sourceRankMeta`` carries each key.

    Membership in ``sourceRankMeta`` means the source contributed a
    rank/value to that row's blend — the same signal the value-chain
    UI surfaces — so it is the precise "did this source land on the
    board" measure, independent of whether the source is value- or
    rank-based.
    """
    cov: dict[str, int] = {}
    for row in contract.get("playersArray") or []:
        for key in row.get("sourceRankMeta") or {}:
            cov[key] = cov.get(key, 0) + 1
    return cov


def _csv_nonempty(source_key: str) -> bool:
    """True when the source's CSV exists and has at least one data row.

    A source whose CSV is genuinely empty has nothing to contribute and
    must not be reported here — that is the fetcher's / freshness
    watchdog's concern, not a coverage regression.
    """
    cfg = _SOURCE_CSV_PATHS.get(source_key)
    csv_rel = cfg if isinstance(cfg, str) else (cfg or {}).get("path")
    if not csv_rel:
        return False
    csv_path = _REPO_ROOT / csv_rel
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            # header + >=1 data row
            return sum(1 for _ in zip(range(2), f)) >= 2
    except OSError:
        return False


def evaluate_coverage(
    contract: dict,
    freshness: dict[str, dict],
    thresholds: dict,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]], list[str]]:
    """Pure decision core (kept IO-free so it is unit-testable).

    Returns ``(violations, ok, skipped)`` where:
      * violations — [(source_key, coverage)] fresh + CSV-non-empty
        registered sources below ``_MIN_COVERAGE`` (the regression).
      * ok         — [(source_key, coverage)] healthy registered
        sources.
      * skipped    — source keys not evaluated because they are stale
        (owned by the freshness watchdog) or have an empty/missing CSV.
    """
    return evaluate_coverage_map(_source_coverage(contract), freshness, thresholds)


def evaluate_coverage_map(
    cov: dict[str, int],
    freshness: dict[str, dict],
    thresholds: dict,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]], list[str]]:
    """Same decision core as :func:`evaluate_coverage` but driven by a
    pre-computed ``{sourceKey: playerCount}`` map instead of a contract.

    Lets the live deploy-gate / health check feed the SERVED board's
    ``served_source_coverage`` (from ``/api/status``) through the
    identical fresh-but-absent logic the CI watchdog uses — one
    decision core, so the pre-merge and runtime gates can never drift.
    """
    registered = [str(s.get("key") or "") for s in _RANKING_SOURCES]

    violations: list[tuple[str, int]] = []
    ok: list[tuple[str, int]] = []
    skipped: list[str] = []

    for key in sorted(k for k in registered if k):
        info = freshness.get(key)
        threshold = resolve_threshold(key, thresholds)
        is_fresh = info is not None and float(info.get("ageHours", 0.0)) <= threshold
        if not is_fresh or not _csv_nonempty(key):
            # Stale → freshness watchdog already owns it.
            # Empty/missing CSV → nothing to land; not a coverage bug.
            skipped.append(key)
            continue
        c = int(cov.get(key, 0))
        if c < _MIN_COVERAGE:
            violations.append((key, c))
        else:
            ok.append((key, c))
    return violations, ok, skipped


def _write_summary(
    violations: list[tuple[str, int]],
    ok: list[tuple[str, int]],
    skipped: list[str],
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## Contract coverage watchdog", ""]
    if violations:
        lines += [
            "### Fresh sources MISSING from the built board",
            "",
            "| source | players covered | floor |",
            "|---|---|---|",
        ]
        lines += [f"| `{k}` | {c} | {_MIN_COVERAGE} |" for k, c in violations]
        lines.append("")
    lines += [
        "### Healthy sources",
        "",
        "| source | players covered |",
        "|---|---|",
    ]
    lines += [f"| `{k}` | {c} |" for k, c in ok]
    if skipped:
        lines += ["", f"_Skipped (stale or empty CSV): {', '.join(skipped)}_"]
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def main() -> int:
    export = _find_latest_export()
    if export is None:
        print(
            "::error title=No contract export::No dynasty_data_*.json "
            "found under exports/latest/ — the scrape never produced a "
            "board, so coverage cannot be verified."
        )
        return 1

    try:
        with export.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        contract = build_api_data_contract(raw)
    except Exception as exc:  # noqa: BLE001 — any failure here is fatal
        print(
            f"::error title=Contract build failed::Could not build the "
            f"contract from {export.name}: {exc!r}.  The served board "
            f"would be broken."
        )
        return 1

    freshness = _read_freshness()
    thresholds = load_thresholds()
    violations, ok, skipped = evaluate_coverage(contract, freshness, thresholds)

    _write_summary(violations, ok, skipped)

    if not violations:
        print(
            f"ok: {len(ok)} registered source(s) covered, "
            f"0 fresh-but-absent ({len(skipped)} skipped: stale/empty)"
        )
        return 0

    for key, c in violations:
        print(
            f"::error title=Source absent from board: {key}::"
            f"{key} is fresh (CSV fetched within threshold) but only "
            f"{c} player(s) carry it in the built contract "
            f"(floor {_MIN_COVERAGE}).  The fetched CSV is not reaching "
            f"the served board — check the registry / "
            f"_enrich_from_source_csvs / prime-payload timing, NOT the "
            f"fetcher (the freshness watchdog would have caught a dead "
            f"fetcher)."
        )
    print(
        f"\nfail: {len(violations)} fresh source(s) missing from the "
        f"board: {', '.join(k for k, _ in violations)}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
