"""One answer to "is each retained evidence stream actually landing?".

The C1A tranche's hardest problem is not writing recorders.  It is that
a recorder which stops is **silent** — the B-1 pattern this repo has
already measured once, where nine timer pairs shipped, two were
installed, and the deploy reported success the whole time.  Four of the
eight retention rows are flagged PARTIAL or PROOF-REQUIRED for exactly
that reason: the mechanism exists and nothing observes it.

So this module probes all eight, from the host that would hold the
evidence, and reports one state per stream.

STATES, AND WHY THERE ARE FOUR
──────────────────────────────
``ok``       observed inside its freshness budget.
``stale``    the store exists and has content, but the newest
             observation is older than the budget.  Something ran once
             and has stopped.
``missing``  the store does not exist at all.  Nothing has ever run.
``unknown``  the probe could not answer — an unreadable file, a
             corrupt store, a budget that cannot be evaluated because
             the stream carries no timestamp.

``missing`` and ``unknown`` are deliberately distinct from a store that
exists and holds zero rows, and none of the four is ever reported as
``ok``.  **Missing is never zero**: "the recorder never ran", "the
recorder ran and found nothing", and "I could not tell" have different
fixes, and collapsing them is how a dead stream reads as a healthy one.

NOT A DECISION INPUT
────────────────────
Operators, the CLI (``scripts/retention_health.py``) and CI read this.
No valuation, trade, ranking or FAAB path may — see the package
docstring.

WHERE TO RUN IT
───────────────
On the production host.  Every one of these stores lives under
``data/``, which is gitignored, so a CI runner's checkout genuinely has
none of them and would honestly report ``missing`` for all eight.  That
is a true statement about the runner and a useless one about
production, which is why the CI wiring probes over SSH exactly as
``.github/workflows/scoring-snapshot-diagnostics.yml`` already does.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

# Freshness budgets, in hours.  Each is derived from the cadence of the
# thing that writes it, not invented: a stream is stale when it has
# missed enough runs that a single blip cannot explain it.
SCRAPE_CADENCE_H = 2.0
# The repo's existing staleness rule -- SCRAPE_INTERVAL_HOURS * 3, the
# same budget data_contract and the scoring gate already use.
SCRAPE_BUDGET_H = SCRAPE_CADENCE_H * 3
DAILY_BUDGET_H = 24.0 * 2
WEEKLY_BUDGET_H = 24.0 * 7 * 2

STATE_OK = "ok"
STATE_STALE = "stale"
STATE_MISSING = "missing"
STATE_UNKNOWN = "unknown"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Date-only stamps ("2026-08-15") are what rank_history keys on.
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def age_hours(stamp: Any) -> float | None:
    parsed = _parse_iso(stamp)
    if parsed is None:
        return None
    return (_now() - parsed).total_seconds() / 3600.0


# Dated artifact names, most specific first:
#   identity_report_20260420T194828Z.json
#   identity_resolution_2026-04-20.json  /  playerctx_2026-08-10.json
_NAME_STAMPS = (
    re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
)


def stamp_from_name(name: str) -> str | None:
    """The observation time an artifact carries in its own filename.

    Preferred over ``mtime`` wherever it exists, and the reason is a
    failure mode this tranche is specifically about: mtime is a property
    of the FILE, not of the observation.  A deploy, an rsync, a restore
    from backup or a container rebuild all rewrite it, and every one of
    those would make a collector that halted in April look like it ran
    this morning — "stale = current", arrived at by accident.  The date
    in the name was written by whatever produced the artifact and
    survives all of it.
    """
    for pattern in _NAME_STAMPS:
        m = pattern.search(name or "")
        if not m:
            continue
        parts = m.groups()
        if len(parts) == 6:
            y, mo, d, h, mi, s = parts
            return f"{y}-{mo}-{d}T{h}:{mi}:{s}+00:00"
        y, mo, d = parts
        return f"{y}-{mo}-{d}T00:00:00+00:00"
    return None


def artifact_stamp(path: Path) -> tuple[str | None, str]:
    """``(iso stamp, source)`` for a dated artifact.

    ``source`` is reported so an operator reading a stale warning can
    tell whether the age came from the artifact's own name or from a
    filesystem timestamp that a redeploy may have rewritten.
    """
    from_name = stamp_from_name(path.name)
    if from_name:
        return from_name, "filename"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), "mtime"
    except OSError:
        return None, "unavailable"


def _newest_dated(files: list[Path]) -> tuple[Path | None, str | None, str]:
    """The newest artifact by its own stamp, not by mtime."""
    best: tuple[str, Path, str] | None = None
    for f in files:
        stamp, source = artifact_stamp(f)
        if stamp is None:
            continue
        if best is None or stamp > best[0]:
            best = (stamp, f, source)
    if best is None:
        return None, None, "unavailable"
    return best[1], best[0], best[2]


def _grade(
    *,
    present: bool,
    last_observed: Any,
    budget_h: float,
    rows: int | None = None,
) -> tuple[str, float | None]:
    """The one place a state is decided, so all eight agree."""
    if not present:
        return STATE_MISSING, None
    if rows is not None and rows <= 0:
        # The store exists but holds nothing.  Not ``ok`` -- an empty
        # store is the absence of evidence, never evidence of absence.
        return STATE_UNKNOWN, None
    age = age_hours(last_observed)
    if age is None:
        return STATE_UNKNOWN, None
    return (STATE_OK if age <= budget_h else STATE_STALE), age


def _stream(
    stream_id: str,
    title: str,
    *,
    state: str,
    budget_h: float,
    last_observed: Any = None,
    age_h: float | None = None,
    primary_store: str = "",
    privacy: str = "internal",
    detail: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": stream_id,
        "title": title,
        "state": state,
        "primaryStore": primary_store,
        "privacyClass": privacy,
        "lastObservedAt": last_observed,
        "ageHours": round(age_h, 2) if isinstance(age_h, float) else None,
        "budgetHours": budget_h,
        "detail": detail,
    }
    if extra:
        out.update(extra)
    return out


# ── C1-RET-01: KTC crowd-FAAB rolling window ─────────────────────────


def _probe_crowd_faab(data_dir: Path) -> dict[str, Any]:
    faab_dir = data_dir / "faab"
    files = sorted(faab_dir.glob("crowd_history_*.json")) if faab_dir.is_dir() else []
    if not files:
        return _stream(
            "C1-RET-01",
            "KTC crowd-FAAB rolling window",
            state=STATE_MISSING,
            budget_h=SCRAPE_BUDGET_H,
            primary_store=str(faab_dir / "crowd_history_<leagueKey>.json"),
            detail=(
                "no accumulator file on disk. The KTC waiver feed is a ~5-day "
                "rolling window, so every day this is absent is a day of crowd "
                "evidence that cannot be re-fetched."
            ),
        )

    newest_stamp: str | None = None
    total_rows = 0
    unreadable: list[str] = []
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable.append(f.name)
            continue
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            total_rows += len(rows)
        stamp = payload.get("updatedAt") if isinstance(payload, dict) else None
        if not stamp:
            try:
                stamp = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
            except OSError:
                stamp = None
        if stamp and (newest_stamp is None or str(stamp) > newest_stamp):
            newest_stamp = str(stamp)

    if unreadable and not newest_stamp:
        return _stream(
            "C1-RET-01",
            "KTC crowd-FAAB rolling window",
            state=STATE_UNKNOWN,
            budget_h=SCRAPE_BUDGET_H,
            primary_store=str(faab_dir),
            detail=f"accumulator files present but unreadable: {', '.join(unreadable)}",
        )

    state, age = _grade(
        present=True,
        last_observed=newest_stamp,
        budget_h=SCRAPE_BUDGET_H,
        rows=total_rows,
    )
    return _stream(
        "C1-RET-01",
        "KTC crowd-FAAB rolling window",
        state=state,
        budget_h=SCRAPE_BUDGET_H,
        last_observed=newest_stamp,
        age_h=age,
        primary_store=str(faab_dir),
        detail=f"{len(files)} accumulator file(s), {total_rows} deduped row(s)",
        extra={"files": len(files), "rows": total_rows},
    )


# ── C1-RET-02: canonical board history ───────────────────────────────


def _probe_board_history(data_dir: Path) -> dict[str, Any]:
    db = data_dir / "board_history.sqlite"
    if not db.exists():
        return _stream(
            "C1-RET-02",
            "Canonical board history recorder",
            state=STATE_MISSING,
            budget_h=DAILY_BUDGET_H,
            primary_store=str(db),
            detail=(
                "no board history database. board_store.py: 'every day it is "
                "not running is a day of evidence that cannot be recovered "
                "later'."
            ),
        )
    try:
        from src.snapshots import board_store  # noqa: PLC0415

        cov = board_store.coverage(db)
    except Exception as exc:  # noqa: BLE001
        return _stream(
            "C1-RET-02",
            "Canonical board history recorder",
            state=STATE_UNKNOWN,
            budget_h=DAILY_BUDGET_H,
            primary_store=str(db),
            detail=f"database present but unreadable: {exc}",
        )

    state, age = _grade(
        present=True,
        last_observed=cov.get("lastDate"),
        budget_h=DAILY_BUDGET_H,
        rows=int(cov.get("rows") or 0),
    )
    return _stream(
        "C1-RET-02",
        "Canonical board history recorder",
        state=state,
        budget_h=DAILY_BUDGET_H,
        last_observed=cov.get("lastDate"),
        age_h=age,
        primary_store=str(db),
        detail=f"{cov.get('rows', 0)} row(s) across {cov.get('dates', 0)} date(s)",
        extra={"rows": cov.get("rows"), "dates": cov.get("dates")},
    )


# ── C1-RET-03: rank_history.jsonl ────────────────────────────────────


def _probe_rank_history(data_dir: Path) -> dict[str, Any]:
    log = data_dir / "rank_history.jsonl"
    if not log.exists():
        return _stream(
            "C1-RET-03",
            "Rank history log",
            state=STATE_MISSING,
            budget_h=DAILY_BUDGET_H,
            primary_store=str(log),
            detail="no rank-history log on disk; nothing has been appended",
        )
    try:
        from src.api import rank_history  # noqa: PLC0415

        cov = rank_history.coverage(path=log)
    except Exception as exc:  # noqa: BLE001
        return _stream(
            "C1-RET-03",
            "Rank history log",
            state=STATE_UNKNOWN,
            budget_h=DAILY_BUDGET_H,
            primary_store=str(log),
            detail=f"log present but unreadable: {exc}",
        )

    last = cov.get("lastDate") or cov.get("last_date")
    state, age = _grade(
        present=True,
        last_observed=last,
        budget_h=DAILY_BUDGET_H,
        rows=int(cov.get("snapshots") or 0),
    )
    stale_days = cov.get("staleDays")
    missing_days = cov.get("missingDays")
    detail = f"{cov.get('snapshots', 0)} snapshot(s)"
    if isinstance(missing_days, list):
        detail += f", {len(missing_days)} missing day(s)"
    elif missing_days is not None:
        detail += f", missingDays={missing_days}"
    if stale_days is not None:
        detail += f", staleDays={stale_days}"
    return _stream(
        "C1-RET-03",
        "Rank history log",
        state=state,
        budget_h=DAILY_BUDGET_H,
        last_observed=last,
        age_h=age,
        primary_store=str(log),
        detail=detail,
        extra={"snapshots": cov.get("snapshots"), "staleDays": stale_days},
    )


# ── C1-RET-04 / C1-RET-05: the new evidence store ────────────────────


def _probe_scoring_cards(data_dir: Path) -> dict[str, Any]:
    from src.retention import evidence_store  # noqa: PLC0415

    db = data_dir / "retention" / "evidence.sqlite"
    cov = evidence_store.coverage(path=db)
    if not cov.get("present"):
        return _stream(
            "C1-RET-04",
            "Scoring card history",
            state=STATE_MISSING,
            budget_h=SCRAPE_BUDGET_H,
            primary_store=str(db),
            detail=(
                "no evidence store. Without it write_scoring_snapshot's "
                "tmp.replace() destroys the previous card on every refresh."
            ),
        )
    cards = cov.get("scoringCards") or {}
    state, age = _grade(
        present=True,
        last_observed=cards.get("lastObservedAt"),
        budget_h=SCRAPE_BUDGET_H,
        rows=int(cards.get("intervals") or 0),
    )
    return _stream(
        "C1-RET-04",
        "Scoring card history",
        state=state,
        budget_h=SCRAPE_BUDGET_H,
        last_observed=cards.get("lastObservedAt"),
        age_h=age,
        primary_store=str(db),
        detail=(
            f"{cards.get('intervals', 0)} observed interval(s) "
            f"across {cards.get('leagues', 0)} league(s)"
        ),
        extra={"intervals": cards.get("intervals"), "leagues": cards.get("leagues")},
    )


def _probe_trending(data_dir: Path) -> dict[str, Any]:
    from src.retention import evidence_store  # noqa: PLC0415

    db = data_dir / "retention" / "evidence.sqlite"
    cov = evidence_store.coverage(path=db)
    if not cov.get("present"):
        return _stream(
            "C1-RET-05",
            "Sleeper trending-adds series",
            state=STATE_MISSING,
            budget_h=SCRAPE_BUDGET_H,
            primary_store=str(db),
            detail=(
                "no evidence store. The adapter's TTL cache persists nothing, "
                "so the waiver-heat series does not exist."
            ),
        )
    trend = cov.get("trending") or {}
    state, age = _grade(
        present=True,
        last_observed=trend.get("lastObservedAt"),
        budget_h=SCRAPE_BUDGET_H,
        rows=int(trend.get("observations") or 0),
    )
    return _stream(
        "C1-RET-05",
        "Sleeper trending-adds series",
        state=state,
        budget_h=SCRAPE_BUDGET_H,
        last_observed=trend.get("lastObservedAt"),
        age_h=age,
        primary_store=str(db),
        detail=(
            f"{trend.get('observations', 0)} observation(s) "
            f"across {trend.get('snapshots', 0)} snapshot(s)"
        ),
        extra={"observations": trend.get("observations"), "snapshots": trend.get("snapshots")},
    )


# ── C1-RET-06: own-league transaction ledger (PRIVATE) ───────────────


def _probe_league_events(data_dir: Path) -> dict[str, Any]:
    from src.retention import league_events  # noqa: PLC0415

    db = data_dir / "retention" / "league_events.sqlite"
    cov = league_events.transaction_coverage(path=db)
    if not cov.get("present"):
        return _stream(
            "C1-RET-06",
            "Own-league transaction ledger",
            state=STATE_MISSING,
            budget_h=DAILY_BUDGET_H,
            primary_store=str(db),
            privacy="private",
            detail=(
                "no ledger. The live path is a 365-day rolling window that "
                "emits no transaction_id, so events leaving the window are "
                "unrecoverable."
            ),
        )
    state, age = _grade(
        present=True,
        last_observed=cov.get("lastSeenAt"),
        budget_h=DAILY_BUDGET_H,
        rows=int(cov.get("transactions") or 0),
    )
    return _stream(
        "C1-RET-06",
        "Own-league transaction ledger",
        state=state,
        budget_h=DAILY_BUDGET_H,
        last_observed=cov.get("lastSeenAt"),
        age_h=age,
        primary_store=str(db),
        privacy="private",
        detail=(
            f"{cov.get('transactions', 0)} transaction(s), "
            f"{cov.get('trades', 0)} trade(s), {cov.get('leagues', 0)} league(s)"
        ),
        extra={"transactions": cov.get("transactions"), "trades": cov.get("trades")},
    )


# ── C1-RET-07: per-source raw ingest + identity reports ──────────────


def _probe_identity_reports(data_dir: Path) -> dict[str, Any]:
    ident_dir = data_dir / "identity"
    patterns = ("identity_resolution_*.json", "identity_report_*.json")
    files: list[Path] = []
    if ident_dir.is_dir():
        for pattern in patterns:
            files.extend(ident_dir.glob(pattern))
    if not files:
        return _stream(
            "C1-RET-07",
            "Identity resolution reports",
            state=STATE_MISSING,
            budget_h=DAILY_BUDGET_H,
            primary_store=str(ident_dir),
            detail="no identity report artifacts on disk",
        )
    newest, stamp, stamp_source = _newest_dated(files)
    state, age = _grade(present=True, last_observed=stamp, budget_h=DAILY_BUDGET_H, rows=len(files))
    return _stream(
        "C1-RET-07",
        "Identity resolution reports",
        state=state,
        budget_h=DAILY_BUDGET_H,
        last_observed=stamp,
        age_h=age,
        primary_store=str(ident_dir),
        detail=(
            f"{len(files)} artifact(s); newest {newest.name if newest else '(undated)'}. "
            "/api/scaffold/identity serves the newest file, so a halted "
            "collector presents an old report as current unless the response "
            "is labelled."
        ),
        extra={
            "artifacts": len(files),
            "newest": newest.name if newest else None,
            "stampSource": stamp_source,
        },
    )


# ── C1-RET-08: playerctx history snapshots ───────────────────────────


def _probe_playerctx_history(data_dir: Path) -> dict[str, Any]:
    hist = data_dir / "playerctx" / "history"
    files = sorted(hist.glob("*.json*")) if hist.is_dir() else []
    if not files:
        return _stream(
            "C1-RET-08",
            "playerctx history snapshots",
            state=STATE_MISSING,
            budget_h=WEEKLY_BUDGET_H,
            primary_store=str(hist),
            detail=(
                "no dated snapshots. Producer, pusher and weekly timer are all "
                "wired; the measured failure is the deploy key, and "
                "playerctx_history_push.sh exits 0 without it by design."
            ),
        )
    newest, stamp, stamp_source = _newest_dated(files)
    state, age = _grade(
        present=True, last_observed=stamp, budget_h=WEEKLY_BUDGET_H, rows=len(files)
    )
    return _stream(
        "C1-RET-08",
        "playerctx history snapshots",
        state=state,
        budget_h=WEEKLY_BUDGET_H,
        last_observed=stamp,
        age_h=age,
        primary_store=str(hist),
        detail=f"{len(files)} snapshot(s); newest {newest.name if newest else '(undated)'}",
        extra={
            "snapshots": len(files),
            "newest": newest.name if newest else None,
            "stampSource": stamp_source,
        },
    )


_PROBES = (
    _probe_crowd_faab,
    _probe_board_history,
    _probe_rank_history,
    _probe_scoring_cards,
    _probe_trending,
    _probe_league_events,
    _probe_identity_reports,
    _probe_playerctx_history,
)


def retention_health(*, data_dir: Path | None = None) -> dict[str, Any]:
    """Probe every C1A retention stream.  Never raises.

    A probe that fails is reported as ``unknown`` for its own stream —
    one broken store must not blind the operator to the other seven.
    """
    root = data_dir or DATA_DIR
    streams: list[dict[str, Any]] = []
    for probe in _PROBES:
        try:
            streams.append(probe(root))
        except Exception as exc:  # noqa: BLE001
            streams.append(
                _stream(
                    getattr(probe, "__name__", "unknown"),
                    "probe failed",
                    state=STATE_UNKNOWN,
                    budget_h=0.0,
                    detail=f"probe raised: {exc}",
                )
            )

    counts = {
        STATE_OK: 0,
        STATE_STALE: 0,
        STATE_MISSING: 0,
        STATE_UNKNOWN: 0,
    }
    for s in streams:
        counts[s.get("state", STATE_UNKNOWN)] = counts.get(s.get("state", STATE_UNKNOWN), 0) + 1

    return {
        "checkedAt": _now().isoformat(),
        "dataDir": str(root),
        "streams": streams,
        "counts": counts,
        # The whole surface is healthy only when EVERY stream is ok.
        # An aggregate that averaged would let five healthy streams hide
        # three dead ones, which is the failure this module exists for.
        "allOk": all(s.get("state") == STATE_OK for s in streams),
    }
