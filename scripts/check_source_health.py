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
import csv
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


def measure_registered_source_integrity(
    repo_root: Path,
    *,
    sources: list[dict] | None = None,
    source_paths: dict[str, object] | None = None,
    floors: dict[str, int] | None = None,
) -> dict[str, dict[str, object]]:
    """Audit structural and semantic truth for every registered dynasty source."""
    if sources is None or source_paths is None or floors is None:
        from src.api.data_contract import (
            _RANKING_SOURCES,
            _SOURCE_CSV_PATHS,
            _load_source_row_floors,
        )

        if sources is None:
            sources = list(_RANKING_SOURCES)
        if source_paths is None:
            source_paths = dict(_SOURCE_CSV_PATHS)
        if floors is None:
            floors = _load_source_row_floors()

    name_aliases = {"name", "player", "player_name", "playername"}
    rank_aliases = {"avg", "rank", "overall_rank", "overallrank", "effectiverank"}
    value_aliases = {
        "value",
        "trade_value",
        "tradevalue",
        "3d value +",
        "boone_value",
        "boonevalue",
    }

    def _token(text: object) -> str:
        return str(text or "").strip().lower()

    out: dict[str, dict[str, object]] = {}
    for source in sources:
        key = str(source.get("key") or "")
        if not key:
            continue
        cfg = source_paths.get(key)
        if isinstance(cfg, str):
            rel_path = cfg
            signal = "value"
        elif isinstance(cfg, dict):
            rel_path = str(cfg.get("path") or "")
            signal = str(cfg.get("signal") or "value").lower()
        else:
            rel_path = ""
            signal = "unknown"

        path = repo_root / rel_path if rel_path else None
        errors: list[str] = []
        warnings: list[str] = []
        header: list[str] = []
        row_count = 0
        named_rows = 0
        signal_rows = 0
        zero_signal_rows = 0
        duplicate_names: list[str] = []
        content_hash: str | None = None
        sample_names: list[str] = []

        if not rel_path:
            errors.append("registered source has no canonical CSV path")
        elif path is None or not path.exists():
            errors.append("source CSV missing")
        else:
            try:
                raw = path.read_bytes()
                content_hash = hashlib.sha256(raw).hexdigest()
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    header = list(reader.fieldnames or [])
                    rows = list(reader)
            except (OSError, UnicodeError, csv.Error) as exc:
                errors.append(f"source CSV unreadable: {exc}")
                rows = []
            row_count = len(rows)

            name_columns = [name for name in header if _token(name) in name_aliases]
            rank_columns = [name for name in header if _token(name) in rank_aliases]
            value_columns = [name for name in header if _token(name) in value_aliases]
            if not name_columns:
                errors.append(f"no recognized player/name column in header {header!r}")
            if signal == "rank" and not rank_columns:
                errors.append(f"rank source has no recognized rank column in header {header!r}")
            if signal == "value" and not value_columns:
                errors.append(f"value source has no recognized value column in header {header!r}")

            seen_names: set[str] = set()
            duplicate_set: set[str] = set()
            for row in rows:
                name = ""
                for column in name_columns:
                    value = str(row.get(column) or "").strip()
                    if value:
                        name = value
                        break
                if name:
                    named_rows += 1
                    name_key = name.casefold()
                    if name_key in seen_names:
                        duplicate_set.add(name)
                    seen_names.add(name_key)

                columns = rank_columns if signal == "rank" else value_columns
                numeric: float | None = None
                for column in columns:
                    raw_value = str(row.get(column) or "").strip().replace(",", "")
                    if not raw_value:
                        continue
                    try:
                        numeric = float(raw_value)
                    except ValueError:
                        continue
                    break
                if numeric is not None:
                    signal_rows += 1
                    if numeric == 0:
                        zero_signal_rows += 1
                    if signal == "rank" and numeric <= 0:
                        errors.append(f"non-positive rank observed: {numeric}")
                        break
                    if key == "ktcCrowdTradesSfTep" and not 0 < numeric <= 9999:
                        errors.append(f"KTC combined value outside 0-9999: {numeric}")
                        break

            duplicate_names = sorted(duplicate_set)[:20]
            if duplicate_names:
                warnings.append(
                    f"{len(duplicate_set)} exact duplicate name(s); identity owner must disambiguate"
                )
            if row_count and named_rows < max(1, int(row_count * 0.95)):
                errors.append(f"name coverage degraded: {named_rows}/{row_count}")
            if row_count and signal_rows < max(1, int(row_count * 0.80)):
                errors.append(f"numeric {signal} coverage degraded: {signal_rows}/{row_count}")

            floor = floors.get(key)
            if floor is not None and row_count < int(floor):
                errors.append(f"row coverage {row_count} below floor {int(floor)}")

            if rows and name_columns:
                indexes = sorted({0, len(rows) // 2, len(rows) - 1})
                for row_index in indexes:
                    row = rows[row_index]
                    for column in name_columns:
                        value = str(row.get(column) or "").strip()
                        if value:
                            sample_names.append(value)
                            break

        game_type = source.get("game_type")
        game_evidence = str(source.get("game_type_evidence") or "").strip()
        if game_type != "DYNASTY":
            errors.append(f"semantic game_type is {game_type!r}, expected DYNASTY")
        if not game_evidence:
            errors.append("dynasty semantic evidence missing")

        out[key] = {
            "state": "HEALTHY" if not errors else "DEGRADED",
            "path": rel_path or None,
            "signal": signal,
            "scope": source.get("scope"),
            "extraScopes": source.get("extra_scopes") or [],
            "correlationGroup": source.get("correlation_group"),
            "isRetail": bool(source.get("is_retail")),
            "isTepPremium": source.get("is_tep_premium"),
            "gameType": game_type,
            "gameTypeEvidence": game_evidence,
            "rowCount": row_count,
            "rowFloor": floors.get(key),
            "namedRows": named_rows,
            "numericSignalRows": signal_rows,
            "zeroSignalRows": zero_signal_rows,
            "header": header,
            "contentHash": content_hash,
            "sampleNames": sample_names,
            "duplicateNames": duplicate_names,
            "errors": errors,
            "warnings": warnings,
        }

    return out


def measure_ktc_semantic_integrity(repo_root: Path) -> dict[str, object]:
    """Verify KTC's selected source/format provenance independently of freshness.

    Fetch freshness can be perfectly green while the browser successfully
    scraped the wrong KTC mode.  The September-2026 source launch proved that
    failure class in production, so semantic configuration is measured from
    the capture sidecar written by the KTC adapter rather than inferred from a
    recently-written CSV.
    """
    provenance_path = repo_root / "data" / "scrape_state" / "ktc_value_sources.json"
    if not provenance_path.exists():
        return {
            "category": "semantic_configuration",
            "state": "UNAVAILABLE",
            "measurable": False,
            "path": str(provenance_path),
            "errors": ["KTC three-source provenance has not been captured yet"],
            "coverageErrors": [],
            "parserErrors": [],
        }

    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "category": "parser_drift",
            "state": "PARSE_FAILED",
            "measurable": True,
            "path": str(provenance_path),
            "errors": [],
            "coverageErrors": [],
            "parserErrors": [f"KTC provenance is unreadable: {exc}"],
        }

    semantic_errors: list[str] = []
    coverage_errors: list[str] = []
    parser_errors: list[str] = []

    if payload.get("canonicalMarketSource") != "crowd_trades":
        semantic_errors.append(
            "canonical KTC market source is not crowd_trades "
            f"({payload.get('canonicalMarketSource')!r})"
        )

    fmt = payload.get("operatorFormat") or {}
    expected_format = {
        "gameType": "DYNASTY",
        "superflex": True,
        "tePremium": "TE++",
        "tePremiumLevel": 2,
    }
    for key, expected in expected_format.items():
        if fmt.get(key) != expected:
            semantic_errors.append(
                f"KTC operator format {key}={fmt.get(key)!r}; expected {expected!r}"
            )

    captures = payload.get("captures") or {}
    from src.sources.ktc_value_sources import (
        KTC_CONTROL_VALUES,
        KTC_SOURCE_MIN_PRICED,
        KTC_VALUE_SOURCES,
        classify_control_label,
    )

    for source in KTC_VALUE_SOURCES:
        capture = captures.get(source)
        if not isinstance(capture, dict):
            parser_errors.append(f"KTC capture missing source mode {source}")
            continue
        selected_label = str(capture.get("selectedLabel") or "")
        if classify_control_label(selected_label) != source:
            semantic_errors.append(
                f"KTC {source} selectedLabel={selected_label!r} no longer maps to that source"
            )
        if str(capture.get("selectedControlValue") or "") != KTC_CONTROL_VALUES[source]:
            semantic_errors.append(
                f"KTC {source} control value={capture.get('selectedControlValue')!r}; "
                f"expected {KTC_CONTROL_VALUES[source]!r}"
            )
        if capture.get("superflex") is not True:
            semantic_errors.append(f"KTC {source} is not proven Superflex")
        if capture.get("tePremium") != "TE++" or capture.get("tePremiumLevel") != 2:
            semantic_errors.append(f"KTC {source} is not proven TE++ level 2")
        try:
            rows = int(capture.get("rowCount"))
            priced = int(capture.get("pricedCount"))
        except (TypeError, ValueError):
            parser_errors.append(f"KTC {source} row/priced counts are not numeric")
        else:
            floor = int(KTC_SOURCE_MIN_PRICED[source])
            if rows < floor or priced < floor:
                coverage_errors.append(
                    f"KTC {source} coverage degraded: rows={rows}, priced={priced}, floor={floor}"
                )
        if not str(capture.get("contentHash") or "").strip():
            parser_errors.append(f"KTC {source} has no content hash")

    hashes = {
        str(capture.get("contentHash"))
        for capture in captures.values()
        if isinstance(capture, dict) and capture.get("contentHash")
    }
    if len(captures) >= 3 and len(hashes) < 2:
        parser_errors.append(
            "KTC source selector produced byte-equivalent boards for all three modes"
        )

    state = "HEALTHY"
    category = "semantic_configuration"
    if parser_errors:
        state = "SCHEMA_CHANGED"
        category = "parser_drift"
    elif semantic_errors:
        state = "SCHEMA_CHANGED"
        category = "semantic_configuration"
    elif coverage_errors:
        state = "PARTIAL"
        category = "coverage_degraded"

    return {
        "category": category,
        "state": state,
        "measurable": True,
        "path": str(provenance_path),
        "errors": semantic_errors,
        "coverageErrors": coverage_errors,
        "parserErrors": parser_errors,
    }


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

    registered_integrity = measure_registered_source_integrity(repo_root)
    registered_degraded = {
        key: value for key, value in registered_integrity.items() if value.get("errors")
    }

    ktc_semantic = measure_ktc_semantic_integrity(repo_root)
    # Before the new KTC combined source is activated, a missing provenance
    # sidecar is an honest UNKNOWN rather than a code failure. Once the
    # combined key is the voting source, semantic proof becomes deploy-blocking.
    try:
        from src.api.data_contract import _RANKING_SOURCES

        ktc_semantic_required = any(
            str(source.get("key") or "") == "ktcCrowdTradesSfTep" for source in _RANKING_SOURCES
        )
    except Exception:
        ktc_semantic_required = False

    ktc_semantic_blocking = bool(
        ktc_semantic.get("measurable")
        and (
            ktc_semantic.get("errors")
            or ktc_semantic.get("coverageErrors")
            or ktc_semantic.get("parserErrors")
        )
    ) or (ktc_semantic_required and not ktc_semantic.get("measurable"))

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
        "registeredSourceIntegrity": registered_integrity,
        "semanticIntegrity": {"ktc": ktc_semantic},
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
            f"content-stale: {len(content_stale)} · "
            f"registered integrity: {len(registered_integrity) - len(registered_degraded)} healthy / "
            f"{len(registered_degraded)} degraded · "
            f"KTC semantic: {ktc_semantic.get('state')}"
        )
        for source_key, item in sorted(registered_degraded.items()):
            for msg in item.get("errors") or []:
                print(f"::error title=Source integrity {source_key}::{msg}")
        if not ktc_semantic.get("measurable"):
            print(
                "::warning title=KTC semantic integrity unmeasurable::"
                "three-source provenance has not been captured yet"
            )
        for msg in ktc_semantic.get("errors") or []:
            print(f"::error title=KTC semantic configuration::{msg}")
        for msg in ktc_semantic.get("coverageErrors") or []:
            print(f"::error title=KTC coverage degraded::{msg}")
        for msg in ktc_semantic.get("parserErrors") or []:
            print(f"::error title=KTC parser drift::{msg}")
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
        lines.append(
            f"- KTC semantic integrity: **{ktc_semantic.get('state')}** "
            f"({ktc_semantic.get('category')})"
        )
        for msg in contract_errors:
            lines.append(f"  - `{msg}`")
        for src_key, days, budget in content_stale:
            lines.append(f"  - `{src_key}` unchanged {days:.0f}d (budget {budget:.0f}d)")
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    return (
        1
        if (
            contract_errors
            or hard_stale
            or content_stale
            or registered_degraded
            or ktc_semantic_blocking
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
