"""Source-freshness watchdog — fails the scheduled-refresh workflow when
any registered source is older than its configured staleness threshold.

Runs as the LAST step of ``.github/workflows/scheduled-refresh.yml`` so
that a silent fetcher failure (one fetcher dies, the rest succeed, the
commit goes through) still trips the run red.  Without this guard, a
broken fetcher can sit unnoticed until a human spots the stale banner
on the live site — exactly the failure mode the operator flagged.

Reuses ``server._per_source_freshness`` so the watchdog reads the
exact same stamp-or-mtime signal the live alert engine reads, and
``src.api.source_health_alerts.resolve_threshold`` so per-source
thresholds match the live policy.  No parallel logic to drift.

Exit codes:
  0 — every source is within threshold
  1 — at least one source is stale; the workflow step turns red and
      the workflow's failure-handler step opens an issue

Output:
  Human-readable summary on stdout
  GitHub Actions error annotations (``::error::``) per stale source
  so the run page surfaces them in the UI
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow ``python scripts/watchdog_freshness.py`` from repo root by
# making the repo root importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.api.source_health_alerts import load_thresholds, resolve_threshold  # noqa: E402


def _read_freshness() -> dict[str, dict]:
    """Mirror ``server._per_source_freshness`` without importing the
    full FastAPI app (which would pull every adapter at import time).

    Stamp content beats CSV mtime — the same preference order the
    live API uses — so the watchdog catches the cases where the stamp
    is being written correctly but the CSV file is unchanged (monthly
    vendors) and vice versa.
    """
    from src.api.data_contract import _SOURCE_CSV_PATHS

    state_dir = _REPO_ROOT / "data" / "scrape_state"
    out: dict[str, dict] = {}
    now_epoch = datetime.now(tz=timezone.utc).timestamp()

    for src_key, entry in _SOURCE_CSV_PATHS.items():
        csv_rel = entry if isinstance(entry, str) else (entry or {}).get("path")
        if not csv_rel:
            continue
        csv_path = _REPO_ROOT / csv_rel
        stamp_path = state_dir / f"{src_key}_last_success"
        last_epoch: float | None = None
        try:
            stamp_text = stamp_path.read_text().strip()
        except OSError:
            stamp_text = ""
        if stamp_text:
            try:
                last_epoch = float(stamp_text)
            except ValueError:
                last_epoch = None
        if last_epoch is None:
            try:
                last_epoch = csv_path.stat().st_mtime
            except OSError:
                continue
        age_hours = max(0.0, (now_epoch - last_epoch) / 3600.0)
        out[src_key] = {
            "lastFetched": datetime.fromtimestamp(last_epoch, tz=timezone.utc).isoformat(
                timespec="seconds"
            ),
            "ageHours": round(age_hours, 2),
        }
    return out


def main() -> int:
    thresholds = load_thresholds()
    freshness = _read_freshness()

    if not freshness:
        # No sources registered at all = catastrophic regression in the
        # ranking registry.  Fail loud.
        print("::error title=Source registry empty::No sources could be read from "
              "_SOURCE_CSV_PATHS.  The data contract registry is broken.")
        return 1

    stale: list[tuple[str, float, float, str]] = []
    fresh: list[tuple[str, float, float]] = []
    for src, info in sorted(freshness.items()):
        age = float(info.get("ageHours", 0.0))
        threshold = resolve_threshold(src, thresholds)
        if age > threshold:
            stale.append((src, age, threshold, str(info.get("lastFetched", ""))))
        else:
            fresh.append((src, age, threshold))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_lines: list[str] = ["## Source freshness watchdog", ""]
    if stale:
        summary_lines.append("### Stale sources (exceeded threshold)")
        summary_lines.append("")
        summary_lines.append("| source | age (h) | threshold (h) | last fetched |")
        summary_lines.append("|---|---|---|---|")
        for src, age, threshold, last in stale:
            summary_lines.append(f"| `{src}` | {age:.1f} | {threshold:.1f} | {last} |")
        summary_lines.append("")
    summary_lines.append("### Fresh sources")
    summary_lines.append("")
    summary_lines.append("| source | age (h) | threshold (h) |")
    summary_lines.append("|---|---|---|")
    for src, age, threshold in fresh:
        summary_lines.append(f"| `{src}` | {age:.1f} | {threshold:.1f} |")

    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n".join(summary_lines) + "\n")
        except OSError:
            pass

    if not stale:
        print(f"ok: {len(fresh)} sources fresh, 0 stale")
        return 0

    for src, age, threshold, last in stale:
        print(
            f"::error title=Stale source: {src}::Last fetched {last} "
            f"({age:.1f}h ago, threshold {threshold:.1f}h).  "
            f"Investigate the fetcher run for this source in the "
            f"'Run scraper' step above."
        )
    print(
        f"\nfail: {len(stale)} stale source(s), {len(fresh)} fresh.  "
        f"Stale: {', '.join(s for s, *_ in stale)}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
