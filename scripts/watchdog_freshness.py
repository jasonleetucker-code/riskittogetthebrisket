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

from src.api.source_health_alerts import (  # noqa: E402
    DEFAULT_SOFT_ESCALATION_HOURS,
    is_soft_source,
    load_soft_escalation_hours,
    load_soft_sources,
    load_thresholds,
    resolve_threshold,
)


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


def unmeasurable_sources() -> list[str]:
    """Registered sources with NO stamp and NO CSV — we cannot say anything.

    :func:`_read_freshness` prefers the ``_last_success`` stamp, falls back to
    the CSV mtime, and when NEITHER exists ``continue``s — dropping the source
    from the population entirely.  It is then not fresh, not soft-stale and not
    hard-stale: it is unaccounted for, and the run prints "N sources fresh, 0
    hard-stale" without ever naming it.

    Measured 2026-08-18 (audit F-11) by injecting one evidence-less registry
    key: the watchdog reported ``22 fresh / 0 hard-stale`` and exited **0**.
    ``main()``'s ``if not freshness`` guard catches only the TOTAL wipe, never a
    partial one.

    That is MISSING IS NEVER ZERO at the freshness layer — the same denominator
    rule ``src/api/confidence.py`` applies to coverage: the population is what
    COULD have been observed, so silence is permanent missing evidence rather
    than a smaller population.  Deleting evidence must never promote health.

    This reports UNKNOWN and nothing more.  It deliberately invents no age, no
    threshold and no staleness verdict: whether stale evidence still counts as a
    full-weight vote is census item S-6 and is an owner decision, explicitly out
    of scope here.

    Kept separate from :func:`classify_freshness` rather than added as a fourth
    bucket because that function's 3-tuple is unpacked at eight call sites; a
    named fourth state consumed where it matters is the smaller correct change.
    """
    from src.api.data_contract import _SOURCE_CSV_PATHS

    state_dir = _REPO_ROOT / "data" / "scrape_state"
    out: list[str] = []
    for src_key, entry in _SOURCE_CSV_PATHS.items():
        csv_rel = entry if isinstance(entry, str) else (entry or {}).get("path")
        if not csv_rel:
            continue
        has_stamp = (state_dir / f"{src_key}_last_success").exists()
        has_csv = (_REPO_ROOT / csv_rel).exists()
        if not has_stamp and not has_csv:
            out.append(str(src_key))
    return sorted(out)


def classify_freshness(
    freshness: dict[str, dict],
    thresholds: dict[str, float],
    soft_sources: set[str],
    soft_escalate_hours: float = DEFAULT_SOFT_ESCALATION_HOURS,
) -> tuple[
    list[tuple[str, float, float, str]],
    list[tuple[str, float, float, str]],
    list[tuple[str, float, float]],
]:
    """Pure split into ``(hard_stale, soft_stale, fresh)``.

    A stale source goes to ``soft_stale`` (reported, non-fatal) when it
    is operator-flagged soft in ``config/source_staleness.json``;
    otherwise to ``hard_stale`` (fails the workflow).

    **Soft is a delay, not an exemption.**  Past
    ``soft_escalate_hours`` a soft source hard-fails like any other.
    Without that cap the flag silently converts to "this source is
    unmonitored" — a lapsed cookie and a dead vendor look identical
    forever.  Pass a non-positive value to opt out deliberately.

    Kept IO-free so the policy is unit-testable.
    """
    hard_stale: list[tuple[str, float, float, str]] = []
    soft_stale: list[tuple[str, float, float, str]] = []
    fresh: list[tuple[str, float, float]] = []
    for src, info in sorted(freshness.items()):
        age = float(info.get("ageHours", 0.0))
        threshold = resolve_threshold(src, thresholds)
        if age > threshold:
            row = (src, age, threshold, str(info.get("lastFetched", "")))
            escalated = soft_escalate_hours > 0 and age > soft_escalate_hours
            if is_soft_source(src, soft_sources) and not escalated:
                soft_stale.append(row)
            else:
                hard_stale.append(row)
        else:
            fresh.append((src, age, threshold))
    return hard_stale, soft_stale, fresh


def main() -> int:
    thresholds = load_thresholds()
    soft_sources = load_soft_sources()
    soft_escalate_hours = load_soft_escalation_hours()
    freshness = _read_freshness()
    unmeasurable = unmeasurable_sources()

    if not freshness:
        # No sources registered at all = catastrophic regression in the
        # ranking registry.  Fail loud.
        print(
            "::error title=Source registry empty::No sources could be read from "
            "_SOURCE_CSV_PATHS.  The data contract registry is broken."
        )
        return 1

    hard_stale, soft_stale, fresh = classify_freshness(
        freshness, thresholds, soft_sources, soft_escalate_hours
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_lines: list[str] = ["## Source freshness watchdog", ""]
    if hard_stale:
        summary_lines.append("### Stale sources (exceeded threshold)")
        summary_lines.append("")
        summary_lines.append("| source | age (h) | threshold (h) | last fetched |")
        summary_lines.append("|---|---|---|---|")
        for src, age, threshold, last in hard_stale:
            summary_lines.append(f"| `{src}` | {age:.1f} | {threshold:.1f} | {last} |")
        summary_lines.append("")
    if soft_stale:
        summary_lines.append("### Soft-stale sources (reported, non-fatal)")
        summary_lines.append("")
        summary_lines.append(
            "_Operator-flagged soft (e.g. manual-cookie auth) — surfaced "
            "but does not fail the run.  Re-mint / fix the fetcher to clear._"
        )
        summary_lines.append("")
        summary_lines.append("| source | age (h) | threshold (h) | last fetched |")
        summary_lines.append("|---|---|---|---|")
        for src, age, threshold, last in soft_stale:
            summary_lines.append(f"| `{src}` | {age:.1f} | {threshold:.1f} | {last} |")
        summary_lines.append("")
    if unmeasurable:
        summary_lines.append("### Unmeasurable sources (no stamp AND no CSV)")
        summary_lines.append("")
        summary_lines.append(
            "_Registered, but we have no evidence at all about them.  Not fresh, "
            "not stale — UNKNOWN.  Deleting evidence must not promote health._"
        )
        summary_lines.append("")
        summary_lines.append("| source |")
        summary_lines.append("|---|")
        for src in unmeasurable:
            summary_lines.append(f"| `{src}` |")
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

    # Soft-stale sources are surfaced as warnings (visible on the run
    # page, but non-fatal) so a known manual-auth lapse stays visible
    # without turning every 2h run red.
    for src, age, threshold, last in soft_stale:
        print(
            f"::warning title=Soft-stale source: {src}::Last fetched "
            f"{last} ({age:.1f}h ago, threshold {threshold:.1f}h).  "
            f"Operator-flagged soft (manual auth) — non-fatal, but "
            f"re-mint / fix the fetcher to clear it."
        )

    for src in unmeasurable:
        print(
            f"::error title=Unmeasurable source: {src}::Registered in the ranking "
            f"source map, but has neither a data/scrape_state/{src}_last_success "
            f"stamp nor its CSV.  We have no evidence about it at all — this is "
            f"UNKNOWN, not fresh.  Restore the fetcher or de-register the source."
        )

    # The counts appear on BOTH exit paths so an unmeasurable source can never
    # be silent — the defect this reports is precisely a source vanishing from
    # the report rather than being named in it.
    if not hard_stale and not unmeasurable:
        soft_note = f", {len(soft_stale)} soft-stale (non-fatal)" if soft_stale else ""
        print(f"ok: {len(fresh)} sources fresh, 0 hard-stale, 0 unmeasurable{soft_note}")
        return 0

    for src, age, threshold, last in hard_stale:
        print(
            f"::error title=Stale source: {src}::Last fetched {last} "
            f"({age:.1f}h ago, threshold {threshold:.1f}h).  "
            f"Investigate the fetcher run for this source in the "
            f"'Run scraper' step above."
        )
    print(
        f"\nfail: {len(hard_stale)} stale source(s), {len(unmeasurable)} unmeasurable, "
        f"{len(fresh)} fresh"
        f"{f', {len(soft_stale)} soft-stale' if soft_stale else ''}.  "
        f"Stale: {', '.join(s for s, *_ in hard_stale) or 'none'}"
        f"{'.  Unmeasurable: ' + ', '.join(unmeasurable) if unmeasurable else ''}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
