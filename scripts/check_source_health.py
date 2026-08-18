#!/usr/bin/env python3
"""The source-health lane — external data availability, in one place.

WHY THIS LANE EXISTS
────────────────────
On 2026-08-16 a single KTC scrape timed out (300 s against a 39-run
baseline of ~18.8 s).  Three things then happened, and only the first
was correct:

1. ``validate_api_data_contract`` returned ``ok: False`` on
   ``partial_run_critical:KTC``.  Right answer.
2. A deterministic unit test that asserted ``ok is True`` as a
   *precondition* went red, so a provider timeout failed the "pure
   logic" hard gate on every open pull request.  Wrong consumer.
3. That accidental failure was, in practice, the ONLY thing preventing a
   source-degraded payload from being deployed — because the real
   contract gate had been looking for its input in two gitignored
   directories and silently skipping since the day it was written.

This script is the honest version of (3): one place that asks "is the
data we have good enough", separate from "is our code correct".  It is
advisory on pull requests (a provider outage is not evidence about a
diff) and the ``--lane full`` contract check blocks the deploy.

WHAT IT REPORTS
───────────────
* **contract source-health errors** — the ``sourceHealthErrors``
  partition of ``validate_api_data_contract`` (timed-out critical
  source, a registered source contributing nothing, pick markets below
  floor).
* **fetch freshness** — reused verbatim from the canonical watchdog
  (``scripts/watchdog_freshness``) and its policy file
  (``config/source_staleness.json``).  No second freshness rule.
* **content staleness** — NEW, and the gap ``config/source_staleness.json``
  already names in its own comment: a stamp proves a fetch SUCCEEDED, not
  that the vendor published anything.  Measured from the tracked export
  archive: how long a source's raw CSV has been byte-identical.
  Motivating case (C1-U6 follow-up 7): ``idpTradeCalc`` fetches fresh
  every 2 h, and is one of only two families pricing picks — while its
  pick rows have not moved since 2026-07-14.  "Fresh" and "still telling
  us something" are different claims and now read differently.

Nothing here fabricates a value, promotes stale data to fresh, or
silences a signal: a degraded source stays degraded and stays visible.

Exit codes:
  0 — no source-health condition open
  1 — at least one open (contract error, hard-stale fetch, or content
      staleness past threshold)
  2 — the check could not run (no payload found)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.watchdog_freshness import (  # noqa: E402
    _read_freshness,
    classify_freshness,
    unmeasurable_sources,
)
from src.api.source_health_alerts import (  # noqa: E402
    load_soft_escalation_hours,
    load_soft_sources,
    load_thresholds,
)
from src.identity.picks import is_pick_name  # noqa: E402

#: Fallback content-staleness budget in DAYS, used only when
#: ``config/source_staleness.json`` carries no ``contentStaleness`` block.
#: An observability threshold, not a valuation parameter — it decides what
#: gets reported, never what anything is worth.
_DEFAULT_CONTENT_STALE_DAYS = 14.0

_ARCHIVE_STAMP_RE = re.compile(r"(\d{8})_(\d{6})")


def _load_content_policy(path: Path | None = None) -> tuple[float, dict[str, float]]:
    """``(default_days, per_source_days)`` from the shared policy file."""
    if path is None:
        path = _REPO_ROOT / "config" / "source_staleness.json"
    default_days = _DEFAULT_CONTENT_STALE_DAYS
    per_source: dict[str, float] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default_days, per_source
    block = raw.get("contentStaleness") if isinstance(raw, dict) else None
    if isinstance(block, dict):
        try:
            default_days = float(block.get("defaultDays", default_days))
        except (TypeError, ValueError):
            pass
        by_source = block.get("bySource")
        if isinstance(by_source, dict):
            for key, value in by_source.items():
                try:
                    per_source[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
    return default_days, per_source


def _archive_stamp_to_dt(name: str) -> datetime | None:
    match = _ARCHIVE_STAMP_RE.search(name)
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def measure_content_staleness(repo_root: Path | None = None) -> dict[str, dict]:
    """Days since each source's raw CSV content last changed.

    Read-only over the tracked ``exports/archive/*.zip`` evidence lane —
    it introduces no new writer and no new state file.  A source whose
    content changes on essentially every run (``ktcSfTep``: 164 changes
    across 165 archives) is distinguishable from one that does not
    (``idpTradeCalc``: 6).

    ``lastChangedAt`` is ``None`` when the source appears in only one
    archive: one observation cannot establish a change interval, and
    "unknown" must not read as "fresh".
    """
    root = repo_root or _REPO_ROOT
    archives = sorted((root / "exports" / "archive").glob("*.zip"))
    last_hash: dict[str, str] = {}
    last_change: dict[str, datetime] = {}
    last_pick_hash: dict[str, str] = {}
    last_pick_change: dict[str, datetime] = {}
    seen_count: dict[str, int] = {}
    newest: datetime | None = None

    for archive in archives:
        stamp = _archive_stamp_to_dt(archive.name)
        if stamp is None:
            continue
        newest = stamp if newest is None or stamp > newest else newest
        try:
            with zipfile.ZipFile(archive) as zf:
                for member in zf.namelist():
                    if not member.endswith(".csv") or "site_raw/" not in member:
                        continue
                    src_key = member.rsplit("/", 1)[-1][: -len(".csv")]
                    raw = zf.read(member)
                    digest = hashlib.sha256(raw).hexdigest()
                    seen_count[src_key] = seen_count.get(src_key, 0) + 1
                    if last_hash.get(src_key) != digest:
                        last_hash[src_key] = digest
                        last_change[src_key] = stamp
                    # Pick rows measured SEPARATELY.  A vendor can refresh
                    # its player board weekly while its pick tiers sit
                    # frozen — which is exactly idpTradeCalc, one of only
                    # two families that price picks at all.  A whole-file
                    # hash cannot see that, and "the file changed" would
                    # read as "the pick market moved".
                    pick_rows = [
                        line
                        for line in raw.decode("utf-8", "replace").splitlines()
                        if is_pick_name(line.split(",", 1)[0])
                    ]
                    if pick_rows:
                        pick_digest = hashlib.sha256("\n".join(pick_rows).encode()).hexdigest()
                        if last_pick_hash.get(src_key) != pick_digest:
                            last_pick_hash[src_key] = pick_digest
                            last_pick_change[src_key] = stamp
        except (OSError, zipfile.BadZipFile):
            continue

    reference = newest or datetime.now(tz=timezone.utc)

    def _days(changed_at: datetime | None, single: bool) -> float | None:
        if changed_at is None or single:
            return None
        return round((reference - changed_at).days, 2)

    out: dict[str, dict] = {}
    for src_key, changed_at in sorted(last_change.items()):
        # One observation cannot establish a change interval, and
        # "unknown" must not read as "fresh".
        single = seen_count.get(src_key, 0) < 2
        pick_changed = last_pick_change.get(src_key)
        out[src_key] = {
            "lastChangedAt": None if single else changed_at.isoformat(timespec="seconds"),
            "daysSinceChange": _days(changed_at, single),
            "pickRowsLastChangedAt": (
                None
                if (single or pick_changed is None)
                else pick_changed.isoformat(timespec="seconds")
            ),
            "daysSincePickChange": _days(pick_changed, single),
            "archivesObserved": seen_count.get(src_key, 0),
        }
    return out


def _load_contract_source_health(repo_root: Path) -> tuple[list[str], list[str], str]:
    """``(source_health_errors, warnings, payload_path)`` from the payload."""
    from src.api.data_contract import build_api_data_contract, validate_api_data_contract

    candidates: list[Path] = []
    for folder in (repo_root / "exports" / "latest", repo_root / "data", repo_root):
        if folder.exists():
            candidates.extend(sorted(folder.glob("dynasty_data_*.json")))
    if not candidates:
        raise FileNotFoundError("no dynasty_data_*.json payload found")
    payload_path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    report = validate_api_data_contract(build_api_data_contract(payload))
    return (
        list(report.get("sourceHealthErrors") or []),
        list(report.get("warnings") or []),
        str(payload_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON")
    parser.add_argument(
        "--skip-content",
        action="store_true",
        help="Skip the archive content-staleness scan (it reads ~165 zips).",
    )
    args = parser.parse_args()
    repo_root = Path(args.repo).resolve()

    try:
        contract_errors, contract_warnings, payload_path = _load_contract_source_health(repo_root)
    except FileNotFoundError as exc:
        print(f"::error title=Source health::cannot run: {exc}")
        return 2

    thresholds = load_thresholds()
    hard_stale, soft_stale, fresh = classify_freshness(
        _read_freshness(), thresholds, load_soft_sources(), load_soft_escalation_hours()
    )
    # Audit F-11.  This script reuses the watchdog's freshness rule verbatim
    # ("no second freshness rule"), so it inherited the watchdog's hole: a
    # registered source with neither a stamp nor a CSV leaves the population
    # entirely and is reported by nobody.  Advisory here, so it is named rather
    # than fatal — but it must be NAMED.
    unmeasurable = unmeasurable_sources()

    content: dict[str, dict] = {}
    content_stale: list[tuple[str, float, float]] = []
    if not args.skip_content:
        default_days, per_source = _load_content_policy()
        content = measure_content_staleness(repo_root)
        for src_key, info in content.items():
            budget = per_source.get(src_key, default_days)
            for field, label in (("daysSinceChange", "board"), ("daysSincePickChange", "picks")):
                days = info.get(field)
                if days is None:
                    continue
                if float(days) > budget:
                    content_stale.append((f"{src_key} ({label})", float(days), budget))

    report = {
        "payload": payload_path,
        "contractSourceHealthErrors": contract_errors,
        "hardStale": [
            {"source": s, "ageHours": a, "thresholdHours": t} for s, a, t, _ in hard_stale
        ],
        "softStale": [
            {"source": s, "ageHours": a, "thresholdHours": t} for s, a, t, _ in soft_stale
        ],
        "freshCount": len(fresh),
        "unmeasurable": unmeasurable,
        "contentStaleness": content,
        "contentStale": [
            {"source": s, "daysSinceChange": d, "budgetDays": b} for s, d, b in content_stale
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"[source-health] payload={payload_path}")
        print(
            f"[source-health] contract source-health errors: {len(contract_errors)} · "
            f"fetch: {len(fresh)} fresh / {len(soft_stale)} soft-stale / "
            f"{len(hard_stale)} stale / {len(unmeasurable)} unmeasurable · "
            f"content-stale: {len(content_stale)}"
        )
        for msg in contract_errors:
            print(f"::error title=Source health (contract)::{msg}")
        for src_key in unmeasurable:
            print(
                f"::warning title=Unmeasurable source::{src_key} has neither a "
                f"_last_success stamp nor its CSV — UNKNOWN, not fresh"
            )
        for src_key, age, threshold, last in hard_stale:
            print(
                f"::error title=Stale source::{src_key} last fetched {last} "
                f"({age:.1f}h > {threshold:.1f}h)"
            )
        for src_key, age, threshold, last in soft_stale:
            print(
                f"::warning title=Soft-stale source::{src_key} last fetched {last} "
                f"({age:.1f}h > {threshold:.1f}h)"
            )
        for src_key, days, budget in content_stale:
            print(
                f"::warning title=Content unchanged::{src_key} raw CSV byte-identical for "
                f"{days:.0f} days (budget {budget:.0f}d) — the FETCH is fresh; the vendor "
                f"has published nothing new"
            )
        for msg in contract_warnings[:10]:
            print(f"[source-health][warn] {msg}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["## Source health", ""]
        lines.append(f"- contract source-health errors: **{len(contract_errors)}**")
        lines.append(f"- stale fetches: **{len(hard_stale)}** (soft: {len(soft_stale)})")
        lines.append(f"- content unchanged past budget: **{len(content_stale)}**")
        for msg in contract_errors:
            lines.append(f"  - `{msg}`")
        for src_key, days, budget in content_stale:
            lines.append(f"  - `{src_key}` unchanged {days:.0f}d (budget {budget:.0f}d)")
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    return 1 if (contract_errors or hard_stale or content_stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
