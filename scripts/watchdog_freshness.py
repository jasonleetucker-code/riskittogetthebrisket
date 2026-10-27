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
  0 — every source is within threshold, or every stale one is either
      soft (inside its escalation window) or an ACKNOWLEDGED FETCH OUTAGE
      that the built board proves casts no vote (reported as DEGRADED —
      see :func:`split_acknowledged_outages`)
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
    unprovisioned = set(unprovisioned_private_sources())

    for src_key, entry in _SOURCE_CSV_PATHS.items():
        csv_rel = entry if isinstance(entry, str) else (entry or {}).get("path")
        if not csv_rel or src_key in unprovisioned:
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
        basis = "stamp"
        if last_epoch is None:
            try:
                last_epoch = csv_path.stat().st_mtime
            except OSError:
                continue
            # A checkout resets file mtimes to "now", so on a runner this age
            # is the checkout's, not the vendor fetch's.  Reported, so a
            # fresh-looking age that measured nothing is named as such.
            basis = "csv_mtime"
        elif last_epoch - now_epoch > _FUTURE_STAMP_TOLERANCE_SECONDS:
            # A stamp ahead of this clock is a wrong clock, not a fresh fetch.
            basis = "stamp_clock_skew"
        age_hours = max(0.0, (now_epoch - last_epoch) / 3600.0)
        out[src_key] = {
            "lastFetched": datetime.fromtimestamp(last_epoch, tz=timezone.utc).isoformat(
                timespec="seconds"
            ),
            "ageHours": round(age_hours, 2),
            "basis": basis,
        }
    return out


#: Precision slack for runner/box clock drift; beyond it a future stamp is skew.
_FUTURE_STAMP_TOLERANCE_SECONDS = 600.0


def unmeasured_age_sources(freshness: dict[str, dict]) -> dict[str, str]:
    """``{source: basis}`` for rows whose age is NOT a measured fetch time.

    ``classify_freshness`` still buckets them on that age (unchanged exit
    behaviour); this only stops a fresh-looking age that measured nothing from
    reading as verified.
    """
    return {
        src: str(info.get("basis"))
        for src, info in freshness.items()
        if isinstance(info, dict) and info.get("basis") not in (None, "stamp")
    }


def unprovisioned_private_sources() -> list[str]:
    """Private, box-local sources this host was never meant to carry.

    A source whose ``_SOURCE_CSV_PATHS`` entry declares a ``private_marker``
    (Signals' authenticated values, owner addendum 2026-10-03) is collected
    only on the production box, into a gitignored store.  Where its collector
    has never run — a GitHub runner above all — there is nothing to be fresh
    or stale: it is NOT PROVISIONED, reported as such, and never "unmeasurable"
    (which would turn every scheduled refresh red for lacking private data).
    One owner decides: ``data_contract.private_source_availability``.  A
    provisioned host with no stamp and no CSV is still unmeasurable.
    """
    from src.api.data_contract import (  # noqa: PLC0415
        PRIVATE_SOURCE_NOT_PROVISIONED,
        private_source_availability,
    )

    return sorted(
        k
        for k, v in private_source_availability(_REPO_ROOT).items()
        if v["state"] == PRIVATE_SOURCE_NOT_PROVISIONED
    )


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
    unprovisioned = set(unprovisioned_private_sources())
    for src_key, entry in _SOURCE_CSV_PATHS.items():
        csv_rel = entry if isinstance(entry, str) else (entry or {}).get("path")
        if not csv_rel or src_key in unprovisioned:
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
        # An entry with no numeric age has NO known age.  Defaulting it to
        # 0h read "unknown" as "fetched just now" (missing is never zero);
        # fail closed instead: an unknowable age is past every threshold.
        raw_age = info.get("ageHours")
        age = float(raw_age) if isinstance(raw_age, (int, float)) else float("inf")
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


def split_seasonally_inactive(
    freshness: dict[str, dict],
    thresholds: dict[str, float],
    *,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """``(remaining, verified_inactive, lapsed_inactive)``.

    A source in a DECLARED seasonal window (``config/sources/
    seasonal_policy_v1.json``; owner decision 2026-10-03) whose fetcher
    re-verified the expected-empty signature within the source's NORMAL
    staleness threshold is removed from the freshness population and
    reported as seasonally inactive — it is not a stale source, and it casts
    no vote.  One that is inactive but NOT re-verified within that threshold
    stays in ``remaining`` and is classified exactly as before (hard-stale on
    its old success stamp): a declared window is never an unmonitored
    source.  Undeclared sources are untouched — fail closed.

    Policy and state belong to ``src/sources/seasonal_policy.py``; this
    function only applies them, and ``classify_freshness``'s 3-tuple is left
    unchanged for its call sites.
    """
    from src.sources.seasonal_policy import watchdog_seasonal_split

    verified, lapsed = watchdog_seasonal_split(
        state_dir if state_dir is not None else _REPO_ROOT / "data" / "scrape_state",
        now or datetime.now(tz=timezone.utc),
        lambda key: resolve_threshold(key, thresholds),
    )
    remaining = {k: v for k, v in freshness.items() if k not in verified}
    return remaining, verified, lapsed


# ── Acknowledged fetch outages (2026-10-16, #1726) ─────────────────────────
#
# A stale ``_last_success`` stamp is a FETCH failure by construction: every
# fetcher re-stamps on every successful run whether or not the vendor
# published anything (config/source_staleness.json's first comment;
# tests/api/test_freshness_budget_not_laxer_than_alerts.py).  So this
# watchdog never sees "vendor stopped publishing" — that is CONTENT
# staleness, owned by the freshness weighting (src/sources/freshness.py) and
# reported by scripts/check_source_health.py — and nothing here may relabel a
# fetch failure as one.
#
# What it CAN do is stop one known, owner-tracked fetch outage from turning
# the whole data job permanently red, which made every other failure
# invisible.  An entry in ``acknowledgedFetchOutages`` downgrades exactly
# that source from FAIL to DEGRADED, and only while ALL of:
#
#   * the entry is well-formed: an ``issue`` reference, ``acknowledgedAt``
#     and ``expiresAt`` timestamps, a span of at most
#     ``ACK_MAX_SPAN_DAYS`` (an acknowledgement is a dated promise to fix,
#     never a permanent exemption), and ``now`` inside that window;
#   * the board this run built proves the source CASTS NO VOTE:
#     ``sourceWeighting.sources[key]`` (the contract's own per-source
#     vote census) has ``votingRows == 0`` and ``excludedRows >= 1`` — it
#     is on the board and the pipeline withholds it on every row.
#
# Anything else stays a hard failure, with the refusal reason named: a
# missing/expired/over-long entry, an unbuildable board, a source the
# census does not describe, and above all a stale source that STILL VOTES.
# Exact source keys only — an acknowledgement never covers a vendor family.
# This touches only this job's exit code: the live alert engine
# (src/api/source_health_alerts.py), the on-site banner and the contract's
# own warnings keep reporting the outage unchanged.

ACK_MAX_SPAN_DAYS = 14


def load_acknowledged_fetch_outages(path: Path | None = None) -> dict[str, dict]:
    """``acknowledgedFetchOutages`` from ``config/source_staleness.json``.

    Returned raw (validation is :func:`acknowledgement_refusal`'s job, so a
    malformed entry surfaces as a NAMED refusal instead of vanishing here).
    A missing or unreadable file acknowledges nothing — fail closed.
    """
    import json  # noqa: PLC0415

    path = path or (_REPO_ROOT / "config" / "source_staleness.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("acknowledgedFetchOutages") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {str(k): v for k, v in entries.items() if not str(k).startswith("_")}


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None  # an ambiguous clock is not a deadline
    return parsed.astimezone(timezone.utc)


def acknowledgement_refusal(entry: object, now: datetime) -> str | None:
    """``None`` when ``entry`` is an ACTIVE acknowledgement, else why not."""
    if not isinstance(entry, dict):
        return "acknowledgement_malformed"
    if not str(entry.get("issue") or "").strip():
        return "acknowledgement_missing_issue"
    acknowledged = _parse_utc(entry.get("acknowledgedAt"))
    expires = _parse_utc(entry.get("expiresAt"))
    if acknowledged is None or expires is None:
        return "acknowledgement_missing_or_unzoned_dates"
    if expires <= acknowledged:
        return "acknowledgement_expires_before_it_starts"
    if (expires - acknowledged).total_seconds() > ACK_MAX_SPAN_DAYS * 86400:
        return f"acknowledgement_span_exceeds_{ACK_MAX_SPAN_DAYS}d"
    if now < acknowledged:
        return "acknowledgement_not_yet_active"
    if now >= expires:
        return "acknowledgement_expired"
    return None


def board_vote_census() -> dict[str, dict] | None:
    """Per-source vote census of the board this run built, or ``None``.

    Builds the contract exactly as ``scripts/watchdog_contract_coverage.py``
    does (same export precedence, same builder) and returns its
    ``sourceWeighting.sources`` — the pipeline's own record of how many rows
    each source voted on and how many it was withheld from.  No second
    freshness rule: the watchdog reads the weighting's verdict, it does not
    re-derive it.  ``None`` (any failure) means no acknowledgement can be
    honoured — fail closed.
    """
    import json  # noqa: PLC0415

    try:
        from scripts.watchdog_contract_coverage import _find_latest_export  # noqa: PLC0415
        from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

        export = _find_latest_export()
        if export is None:
            return None
        with export.open("r", encoding="utf-8") as f:
            contract = build_api_data_contract(json.load(f))
    except Exception:  # noqa: BLE001 — unbuildable board = no evidence
        return None
    sources = ((contract or {}).get("sourceWeighting") or {}).get("sources")
    return sources if isinstance(sources, dict) else None


def _row_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def split_acknowledged_outages(
    hard_stale: list[tuple[str, float, float, str]],
    acknowledgements: dict[str, dict],
    vote_census: dict[str, dict] | None,
    now: datetime,
) -> tuple[
    list[tuple[str, float, float, str]],
    list[tuple[str, float, float, str, dict, dict]],
    dict[str, str],
]:
    """``(still_hard, degraded, refusals)`` — pure, IO-free.

    ``degraded`` rows are ``(src, age, threshold, lastFetched, ack, census)``.
    ``refusals`` names, for every stale source that HAD an acknowledgement
    but stays fatal, why it was not honoured.  A stale source with no entry
    is untouched — this function can only ever narrow a failure that an
    owner wrote down AND the board proves inert.
    """
    still_hard: list[tuple[str, float, float, str]] = []
    degraded: list[tuple[str, float, float, str, dict, dict]] = []
    refusals: dict[str, str] = {}
    for row in hard_stale:
        src = row[0]
        if src not in acknowledgements:
            still_hard.append(row)
            continue
        ack = acknowledgements[src]
        reason = acknowledgement_refusal(ack, now)
        census = None
        if reason is None:
            if vote_census is None:
                reason = "board_vote_census_unavailable"
            else:
                census = vote_census.get(src)
                voting = _row_count((census or {}).get("votingRows"))
                withheld = _row_count((census or {}).get("excludedRows"))
                if not isinstance(census, dict) or census.get("role") != "model_input":
                    reason = "source_not_in_board_vote_census"
                elif voting is None or withheld is None:
                    reason = "board_vote_census_has_no_row_counts"
                elif voting > 0:
                    reason = f"stale_source_still_votes_on_{voting}_rows"
                elif withheld < 1:
                    reason = "source_absent_from_board_not_withheld"
        if reason is not None:
            refusals[src] = reason
            still_hard.append(row)
        else:
            degraded.append((*row, dict(ack), dict(census or {})))
    return still_hard, degraded, refusals


def degraded_line(row: tuple[str, float, float, str, dict, dict]) -> str:
    """One ``degraded:`` log line — grepped into the failure issue."""
    src, age, threshold, last, ack, census = row
    return (
        f"degraded: {src} — acknowledged FETCH outage ({ack.get('issue')}, expires "
        f"{ack.get('expiresAt')}); last fetched {last} ({age:.1f}h ago, threshold "
        f"{threshold:.1f}h); withheld from voting on {census.get('excludedRows')} "
        f"row(s), voting on {census.get('votingRows')}"
    )


def main() -> int:
    thresholds = load_thresholds()
    soft_sources = load_soft_sources()
    soft_escalate_hours = load_soft_escalation_hours()
    freshness = _read_freshness()
    unmeasurable = unmeasurable_sources()
    freshness, seasonal_inactive, seasonal_lapsed = split_seasonally_inactive(freshness, thresholds)

    if not freshness and not seasonal_inactive:
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
    acknowledgements = load_acknowledged_fetch_outages()
    degraded: list[tuple[str, float, float, str, dict, dict]] = []
    ack_refusals: dict[str, str] = {}
    if any(row[0] in acknowledgements for row in hard_stale):
        # Built only when an acknowledgement could apply, so the healthy
        # path costs nothing extra.
        hard_stale, degraded, ack_refusals = split_acknowledged_outages(
            hard_stale,
            acknowledgements,
            board_vote_census(),
            datetime.now(tz=timezone.utc),
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
        for src, reason in sorted(ack_refusals.items()):
            summary_lines.append(f"- `{src}`: acknowledgement NOT honoured — `{reason}`")
        if ack_refusals:
            summary_lines.append("")
    if degraded:
        summary_lines.append(
            "### DEGRADED — acknowledged fetch outages (withheld from voting, non-fatal until expiry)"
        )
        summary_lines.append("")
        summary_lines.append(
            "_The FETCH is failing (this is not a vendor publication gap).  Non-fatal only "
            "because an owner-tracked entry in config/source_staleness.json "
            "``acknowledgedFetchOutages`` covers it AND this run's board shows it casting "
            "no vote.  Fails again at expiry, or the moment it votes._"
        )
        summary_lines.append("")
        summary_lines.append(
            "| source | age (h) | threshold (h) | last fetched | issue | expires | "
            "voting rows | withheld rows |"
        )
        summary_lines.append("|---|---|---|---|---|---|---|---|")
        for src, age, threshold, last, ack, census in degraded:
            summary_lines.append(
                f"| `{src}` | {age:.1f} | {threshold:.1f} | {last} | {ack.get('issue')} "
                f"| {ack.get('expiresAt')} | {census.get('votingRows')} "
                f"| {census.get('excludedRows')} |"
            )
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
    if seasonal_inactive:
        summary_lines.append("### Seasonally inactive sources (declared window, non-fatal)")
        summary_lines.append("")
        summary_lines.append(
            "_Declared between-phases empty board (config/sources/seasonal_policy_v1.json), "
            "re-verified within threshold.  No current vote; reactivates on the first "
            "valid non-empty board._"
        )
        summary_lines.append("")
        summary_lines.append("| source | inactive since | last verified | verified (h ago) |")
        summary_lines.append("|---|---|---|---|")
        for src, info in sorted(seasonal_inactive.items()):
            summary_lines.append(
                f"| `{src}` | {info.get('since')} | {info.get('lastInactiveVerifiedAt')} "
                f"| {info.get('verificationAgeHours')} |"
            )
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

    for row in degraded:
        src, age, _threshold, last, ack, census = row
        print(
            f"::warning title=DEGRADED (acknowledged fetch outage): {src}::Fetch has "
            f"failed since {last} ({age:.1f}h).  Non-fatal only until "
            f"{ack.get('expiresAt')} under {ack.get('issue')}, and only because this "
            f"run's board withholds it on {census.get('excludedRows')} row(s) and it "
            f"votes on none.  Fix the fetcher; do not extend the acknowledgement "
            f"without an owner decision."
        )
        print(degraded_line(row))

    for src, info in sorted(seasonal_inactive.items()):
        print(
            f"::notice title=Seasonally inactive source: {src}::Declared seasonal "
            f"window ({info.get('policyId')}); inactive since {info.get('since')}, "
            f"re-verified {info.get('verificationAgeHours')}h ago.  No current vote."
        )
    for src, info in sorted(seasonal_lapsed.items()):
        print(
            f"::warning title=Seasonal inactivity not re-verified: {src}::Recorded "
            f"seasonally inactive since {info.get('since')}, but the expected-empty "
            f"board was last re-verified at {info.get('lastInactiveVerifiedAt')} "
            f"(threshold {info.get('thresholdHours')}h).  Classified on its normal "
            f"freshness instead."
        )

    for src in unprovisioned_private_sources():
        print(
            f"::notice title=Private source not provisioned: {src}::Box-local private "
            f"source (gitignored store); its collector has never run on this host, so "
            f"it is absent by design here: not fresh, not stale, not unmeasurable."
        )

    unmeasured_age = unmeasured_age_sources(freshness)
    for src, basis in sorted(unmeasured_age.items()):
        why = (
            "no parseable _last_success stamp; the age is the CSV file's mtime, which a "
            "checkout resets"
            if basis == "csv_mtime"
            else "its _last_success stamp is dated in the future (clock skew)"
        )
        print(
            f"::warning title=Source age NOT MEASURED: {src}::{why}.  Classified on that "
            f"age, but it is not a measured fetch time -- treat its freshness as unverified."
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
        if seasonal_inactive:
            soft_note += f", {len(seasonal_inactive)} seasonally inactive (declared)"
        if degraded:
            soft_note += (
                f", {len(degraded)} DEGRADED (acknowledged fetch outage, withheld "
                f"from voting): {', '.join(r[0] for r in degraded)}"
            )
        if unmeasured_age:
            soft_note += (
                f", {len(unmeasured_age)} with an UNMEASURED age: "
                f"{', '.join(sorted(unmeasured_age))}"
            )
        not_provisioned = unprovisioned_private_sources()
        if not_provisioned:
            soft_note += (
                f", {len(not_provisioned)} private source(s) NOT PROVISIONED here "
                f"(not measured): {', '.join(not_provisioned)}"
            )
        print(f"ok: {len(fresh)} sources fresh, 0 hard-stale, 0 unmeasurable{soft_note}")
        return 0

    for src, age, threshold, last in hard_stale:
        refusal = ack_refusals.get(src)
        print(
            f"::error title=Stale source: {src}::Last fetched {last} "
            f"({age:.1f}h ago, threshold {threshold:.1f}h).  "
            f"Investigate the fetcher run for this source in the "
            f"'Run scraper' step above."
            + (f"  Acknowledgement NOT honoured: {refusal}." if refusal else "")
        )
    print(
        f"\nfail: {len(hard_stale)} stale source(s), {len(unmeasurable)} unmeasurable, "
        f"{len(fresh)} fresh"
        f"{f', {len(soft_stale)} soft-stale' if soft_stale else ''}"
        f"{f', {len(degraded)} degraded' if degraded else ''}.  "
        f"Stale: {', '.join(s for s, *_ in hard_stale) or 'none'}"
        f"{'.  Unmeasurable: ' + ', '.join(unmeasurable) if unmeasurable else ''}"
        f"{'.  Acknowledgement refused: ' + ', '.join(f'{k} ({v})' for k, v in sorted(ack_refusals.items())) if ack_refusals else ''}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
