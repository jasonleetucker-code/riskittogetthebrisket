"""AL-P3 — archive the KTC format variants every scrape already receives.

WHAT IS BEING THROWN AWAY TODAY
───────────────────────────────
KTC's public ``/dynasty-rankings`` page ships ONE ``playersArray`` (since
2026-10 parsed from the inline ``<script id="ktc-players">`` element). Every
player object carries BOTH quarterback formats, each with KTC's whole
TE-premium ladder and all three Value Source modes:

    oneQBValues / superflexValues: {
        value, rank, positionalRank, overallTier,            # Off, Crowdsourced
        vftValue, vftRank, vftPositionalRank, vftOverallTier,  # Off, Tradesourced
        blendValue, blendRank, blendPositionalRank, blendOverallTier,  # Crowd+Trades
        tep:   { same twelve fields },   # TE+   (level 1)
        tepp:  { same twelve fields },   # TE++  (level 2)
        teppp: { same twelve fields },   # TE+++ (level 3)
        ...history arrays, trends, ADP, liquidity...
    }

Measured 2026-10-01 against the live page: 500 rows, every one of the 24
(format x level x mode) value fields populated, and the 500-row population
is the same under ``sf=true`` and ``sf=false``. ``src/sources/ktc_value_sources``
keeps Superflex Off + Superflex TE++ for the three modes (and writes only the
TE++ value/rank to CSV). Everything else — Superflex TE+ / TE+++, the whole
1QB ladder, and every positional rank and tier — is dropped.

THIS MODULE
───────────
Reads the eight (format x TEP-level) boards out of the page that is ALREADY
loaded, in ONE extra in-page ``page.evaluate``. That is a read of a JavaScript
variable, not a network request: no navigation, no reload, no fetch, no new
endpoint. It hands each board to the existing archive owner,
``src/source_archive`` (append-only SQLite, ``data/source_archive/boards.sqlite``,
gitignored, box-local). This module owns only the KTC field map; it stores
nothing itself.

BOUNDARIES (CLAUDE.md "Source-domain boundaries", multi-format archive)
──────────────────────────────────────────────────────────────────────
* **Archiving is not authorization to price.** Nothing here writes a CSV,
  touches ``CSVs/site_raw``, ``FULL_DATA``, ``_RANKING_SOURCES`` or any
  weight, and ``src/api/data_contract`` does not import this module or the
  archive (pinned by tests).
* **One provider, one family.** KTC applies Off / TE+ / TE++ / TE+++
  algorithmically from one base crowd value, and 1QB/SF are the same crowd
  under two quarterback rules. All eight boards carry
  ``provider_family = "ktc"`` and share one ``run_id`` — paired calibration
  states of one opinion, never eight votes.
* **Missing is never zero.** A non-positive or non-numeric value is absent;
  a rank below 1 is absent; a format/level block KTC stops shipping is
  reported as skipped, never archived as an empty or zero board.
* **It can never hurt the scrape.** :func:`archive_variants_safely` is the
  only entry point the scraper calls. It is time-bounded, catches every
  ``Exception``, logs, and returns a summary; it never raises into
  ``scrape_ktc`` and never mutates the capture the scraper already made.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

log = logging.getLogger(__name__)

PROVIDER = "ktc"
#: The B10-style correlation group for every archived KTC variant.  One
#: family: see the module docstring.
PROVIDER_FAMILY = "ktc"
#: Where the observation came from.  The ``#playersArray`` fragment names the
#: in-page structure, so a future capture from a different KTC surface (e.g.
#: an intercepted JSON API) is a different endpoint, not a silent merge.
ENDPOINT = "keeptradecut.com/dynasty-rankings#playersArray"
GAME_TYPE = "DYNASTY"
VALUE_UNIT = "ktc_native_0_9999"

#: (format key, playersArray group).  Order is the wire order of the
#: projection; changing it changes the cell layout, so the projection echoes
#: it back and the parser refuses a mismatch.
KTC_FORMAT_GROUPS: tuple[tuple[str, str], ...] = (
    ("1qb", "oneQBValues"),
    ("sf", "superflexValues"),
)

#: (level key, nested block or None for the group's own top level, numeric
#: level, KTC's visible label).
KTC_TEP_LEVELS: tuple[tuple[str, str | None, int, str], ...] = (
    ("off", None, 0, "Off"),
    ("tep", "tep", 1, "TE+"),
    ("tepp", "tepp", 2, "TE++"),
    ("teppp", "teppp", 3, "TE+++"),
)

#: The three KTC Value Source modes and the native field names each uses.
#: ``crowd`` is the board's primary ``value`` (KTC's base crowd value, the
#: one TE premium is algorithmically applied from); the other two travel in
#: each row's ``native`` dict under explicit names.
KTC_MODE_FIELDS: tuple[tuple[str, tuple[str, str, str, str]], ...] = (
    ("crowd", ("value", "rank", "positionalRank", "overallTier")),
    ("trades", ("vftValue", "vftRank", "vftPositionalRank", "vftOverallTier")),
    (
        "crowd_trades",
        ("blendValue", "blendRank", "blendPositionalRank", "blendOverallTier"),
    ),
)

#: Flat per-variant field order on the wire.
CELL_FIELDS: tuple[str, ...] = tuple(f for _mode, fields in KTC_MODE_FIELDS for f in fields)

#: ``1qb_off`` ... ``sf_teppp`` in wire order.
VARIANT_KEYS: tuple[str, ...] = tuple(
    f"{fmt}_{level}" for fmt, _group in KTC_FORMAT_GROUPS for level, *_ in KTC_TEP_LEVELS
)

#: A board with fewer priced rows than this is partial and is NOT archived —
#: the same 100-row floor ``ktc_value_sources`` applies to the selected board.
MIN_PRICED_ROWS = 100

#: Upper bound on the one in-page read.  The selected-board capture has
#: already succeeded when this runs, so the page is loaded; anything slower
#: than this is a wedged page, and the scrape must not wait on evidence.
EVALUATE_TIMEOUT_SECONDS = 20.0

#: Env switch.  Default ON on the production box; ``0``/``false``/``off``
#: disables.  On a GitHub Actions runner the default is OFF: the runner is
#: ephemeral and ``data/source_archive`` is gitignored and not force-added by
#: ``scheduled-refresh.yml``, so an archive written there preserves nothing.
ENV_SWITCH = "RISKIT_KTC_FORMAT_ARCHIVE"

#: Cadence switch.  ``daily`` (default): the first run of each UTC date that
#: archives the whole ladder wins and later runs that day are skipped BEFORE
#: any in-page read.  ``every_run``: archive on every scrape (~1.5 MB per run
#: measured on the 2026-10-01 live payload, so ~18 MB/day at the 2-hour
#: cadence versus ~1.5 MB/day daily).  Daily matches the canonical temporal
#: ledger's daily fidelity and is ample for the evidence this exists for
#: (paired same-cycle format calibration); the switch exists so going finer
#: is an operator setting, not a code change.
CADENCE_SWITCH = "RISKIT_KTC_FORMAT_ARCHIVE_CADENCE"


# One in-page read.  Projects ONLY the 96 numeric cells per row (8 variants
# x 12 fields) plus identity — never the ``history`` / ``vftHistory`` /
# ``blendHistory`` arrays, which are what made whole-object transfer
# expensive (#1391).  Read-only: it never writes to the page.
_PROJECTION_JS = r"""
() => {
  const isRecord = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  const GROUPS = %(groups)s;
  const LEVELS = %(levels)s;
  const FIELDS = %(fields)s;
  const scalar = (v, inner) => {
    if (isRecord(v)) v = v[inner];
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (typeof v === 'string' && v.trim() !== '') {
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    }
    return null;
  };
  let players = [];
  if (typeof playersArray !== 'undefined' && Array.isArray(playersArray)) {
    players = playersArray;
  } else if (Array.isArray(window.playersArray)) {
    players = window.playersArray;
  }
  const rows = [];
  for (const p of players) {
    if (!isRecord(p)) continue;
    const cells = [];
    for (const group of GROUPS) {
      const g = isRecord(p[group]) ? p[group] : null;
      for (const level of LEVELS) {
        const block = g === null ? null : (level === null ? g : (isRecord(g[level]) ? g[level] : null));
        for (const f of FIELDS) {
          const inner = f.endsWith('Value') || f === 'value' ? 'value' : 'rank';
          cells.push(block === null ? null : scalar(block[f], inner));
        }
      }
    }
    // The vendor id and the vendor name are preserved side by side as
    // source-native evidence (ArchivedRow.source_player_id / source_name),
    // exactly as ktc_value_sources does.  No id -> identity resolution
    // happens here; that has one owner, src/sources/ktc_identity.py.
    const vendorId = p.playerID ?? null;
    const vendorName = p.playerName || p.name || null;
    rows.push([vendorId, vendorName, p.position ?? null, cells]);
  }
  return {groups: GROUPS, levels: LEVELS, fields: FIELDS, rows};
}
""" % {
    "groups": json.dumps([group for _fmt, group in KTC_FORMAT_GROUPS]),
    "levels": json.dumps([block for _lvl, block, _n, _label in KTC_TEP_LEVELS]),
    "fields": json.dumps(list(CELL_FIELDS)),
}


class KtcFormatArchiveError(ValueError):
    """The in-page projection did not have the shape this module reads."""


def _value(v: Any) -> float | None:
    """Positive finite value, else missing.  Zero is never a value here."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    out = float(v)
    if out != out or out in (float("inf"), float("-inf")) or out <= 0:
        return None
    return out


def _rank(v: Any) -> int | None:
    """Integral rank >= 1, else missing.  There is no rank zero."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v < 1 or float(v) != int(v):
        return None
    return int(v)


def _tier(v: Any) -> str | None:
    rank = _rank(v)
    return None if rank is None else str(rank)


async def project_format_variants(page: Any) -> dict[str, Any]:
    """The single in-page read.  No navigation, no network."""
    projection = await page.evaluate(_PROJECTION_JS)
    if not isinstance(projection, Mapping):
        raise KtcFormatArchiveError(f"projection is {type(projection).__name__}, not an object")
    return dict(projection)


def payload_hash(projection: Mapping[str, Any]) -> str:
    """sha256 of the projection exactly as transferred (canonical JSON)."""
    blob = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_layout(projection: Mapping[str, Any]) -> list[Any]:
    expected = (
        [group for _fmt, group in KTC_FORMAT_GROUPS],
        [block for _lvl, block, _n, _label in KTC_TEP_LEVELS],
        list(CELL_FIELDS),
    )
    observed = (
        list(projection.get("groups") or []),
        list(projection.get("levels") or []),
        list(projection.get("fields") or []),
    )
    if observed != expected:
        raise KtcFormatArchiveError(f"projection layout changed: {observed!r}")
    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise KtcFormatArchiveError("projection carries no row list")
    return rows


def boards_from_projection(
    projection: Mapping[str, Any],
    *,
    run_id: str,
    captured_at: str,
    page_url: str,
    selected_capture_hashes: Mapping[str, str] | None = None,
) -> tuple[list[Any], dict[str, str]]:
    """Pure: projection -> (``ArchivedBoard`` list, ``{variant: skip reason}``).

    One board per (format, TEP level) that clears :data:`MIN_PRICED_ROWS`
    Crowdsourced values.  ``rows`` is the Crowdsourced value per name (the
    archive's float-per-name v1 shape); ``records`` carries every observed
    field for all three Value Source modes, explicitly named.
    """
    from src.source_archive.records import ArchivedRow
    from src.source_archive.store import ArchivedBoard

    raw_rows = _validate_layout(projection)
    digest = payload_hash(projection)
    width = len(CELL_FIELDS)
    expected_cells = width * len(VARIANT_KEYS)

    per_variant: dict[str, list[ArchivedRow]] = {key: [] for key in VARIANT_KEYS}
    values: dict[str, dict[str, float]] = {key: {} for key in VARIANT_KEYS}
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) != 4:
            continue
        raw_id, raw_name, raw_pos, cells = raw
        name = str(raw_name or "").strip()
        if not name or not isinstance(cells, list) or len(cells) != expected_cells:
            continue
        player_id = None if raw_id in (None, "") else str(raw_id).strip() or None
        position = None if raw_pos is None else (str(raw_pos).strip() or None)
        for v_index, variant in enumerate(VARIANT_KEYS):
            cell = cells[v_index * width : (v_index + 1) * width]
            native: dict[str, Any] = {}
            primary: dict[str, Any] = {}
            for m_index, (mode, fields) in enumerate(KTC_MODE_FIELDS):
                base = m_index * 4
                value = _value(cell[base])
                rank = _rank(cell[base + 1])
                pos_rank = _rank(cell[base + 2])
                tier = _tier(cell[base + 3])
                if mode == "crowd":
                    primary = {
                        "value": value,
                        "overall_rank": rank,
                        "positional_rank": pos_rank,
                        "tier": tier,
                    }
                    continue
                # ``native`` keys are KTC's OWN field names (vftValue,
                # blendRank, ...) — source-native, never our vocabulary.
                for field_name, observed in zip(fields, (value, rank, pos_rank, tier)):
                    if observed is not None:
                        native[field_name] = observed
            if primary.get("value") is None and not native:
                continue  # nothing observed for this row on this variant
            per_variant[variant].append(
                ArchivedRow(
                    source_name=name,
                    source_player_id=player_id,
                    source_position=position,
                    overall_rank=primary.get("overall_rank"),
                    positional_rank=primary.get("positional_rank"),
                    tier=primary.get("tier"),
                    value=primary.get("value"),
                    value_unit=VALUE_UNIT if primary.get("value") is not None else None,
                    native=native,
                )
            )
            if primary.get("value") is not None:
                # First observation wins on a name collision; the records
                # keep both, keyed by the vendor id.
                values[variant].setdefault(name, float(primary["value"]))

    boards: list[Any] = []
    skipped: dict[str, str] = {}
    labels = {
        f"{fmt}_{lvl}": (fmt, n, lbl)
        for fmt, _g in KTC_FORMAT_GROUPS
        for lvl, _b, n, lbl in KTC_TEP_LEVELS
    }
    for variant in VARIANT_KEYS:
        priced = len(values[variant])
        if priced < MIN_PRICED_ROWS:
            skipped[variant] = f"partial:priced={priced}<{MIN_PRICED_ROWS}"
            continue
        fmt, level, level_label = labels[variant]
        boards.append(
            ArchivedBoard(
                provider=PROVIDER,
                provider_family=PROVIDER_FAMILY,
                endpoint=ENDPOINT,
                format_key=variant,
                game_type=GAME_TYPE,
                run_id=run_id,
                rows=values[variant],
                captured_at=captured_at,
                records=tuple(per_variant[variant]),
                provenance={
                    "provider": "KeepTradeCut",
                    "variantLabel": f"{'Superflex' if fmt == 'sf' else '1QB'} {level_label}",
                    "qbFormat": "superflex" if fmt == "sf" else "1qb",
                    "tePremium": level_label,
                    "tePremiumLevel": level,
                    "primaryValueSource": "crowd",
                    "nativeValueSources": [m for m, _f in KTC_MODE_FIELDS],
                    "pageUrl": page_url,
                    "fetchedAt": captured_at,
                    "payloadHash": digest,
                    "payloadRows": len(raw_rows),
                    "pricedRows": priced,
                    "extraRequests": 0,
                    "productionEligible": False,
                    "selectedCaptureHashes": dict(selected_capture_hashes or {}),
                    "capturedBy": "src/sources/ktc_format_archive.py (AL-P3)",
                },
            )
        )
    return boards, skipped


def archive_projection(
    projection: Mapping[str, Any],
    *,
    run_id: str,
    captured_at: str,
    page_url: str,
    selected_capture_hashes: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Cut the boards and append them to the archive.  Raises on failure."""
    from src.source_archive.store import ARCHIVE_ELIGIBLE, archive_board

    boards, skipped = boards_from_projection(
        projection,
        run_id=run_id,
        captured_at=captured_at,
        page_url=page_url,
        selected_capture_hashes=selected_capture_hashes,
    )
    summary: dict[str, Any] = {
        "runId": run_id,
        "payloadHash": payload_hash(projection),
        "archived": [],
        "unchanged": [],
        "conflicts": [],
        "skipped": dict(skipped),
    }
    for board in boards:
        if f"{PROVIDER}:{board.format_key}" not in ARCHIVE_ELIGIBLE:
            summary["skipped"][board.format_key] = "not_archive_eligible"
            continue
        result = archive_board(board, path=path)
        if result.get("archived"):
            summary["archived"].append(board.format_key)
        elif result.get("unchanged"):
            summary["unchanged"].append(board.format_key)
        else:
            summary["conflicts"].append(board.format_key)
    return summary


def cadence(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = str(env.get(CADENCE_SWITCH, "")).strip().lower()
    return "every_run" if raw in {"every_run", "every-run", "all"} else "daily"


def already_archived_today(captured_at: str, *, path: Path | None = None) -> bool:
    """True when every variant is already preserved for ``captured_at``'s date.

    A run that archived only part of the ladder (e.g. one variant partial)
    does not count, so a later run the same day can still complete it.
    """
    from src.source_archive.store import archived_format_keys

    have = archived_format_keys(
        provider=PROVIDER, endpoint=ENDPOINT, captured_date=captured_at[:10], path=path
    )
    return set(VARIANT_KEYS).issubset(have)


def archive_enabled(environ: Mapping[str, str] | None = None) -> tuple[bool, str]:
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "")).strip().lower()
    if raw in {"0", "false", "off", "no"}:
        return False, f"disabled:{ENV_SWITCH}={raw}"
    if raw in {"1", "true", "on", "yes"}:
        return True, "enabled:explicit"
    if str(env.get("GITHUB_ACTIONS", "")).strip().lower() == "true":
        return False, "disabled:ephemeral_ci_runner"
    return True, "enabled:default"


async def archive_variants_safely(
    page: Any,
    *,
    run_id: str | None = None,
    captured_at: str | None = None,
    selected_capture_hashes: Mapping[str, str] | None = None,
    path: Path | None = None,
    timeout_s: float = EVALUATE_TIMEOUT_SECONDS,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The scraper's only entry point.  NEVER raises an ``Exception``.

    Returns ``{"ok": bool, ...}``; failures are logged and returned, so the
    selected-board capture and every CSV the scrape writes are untouched
    whatever happens here.  (``asyncio.CancelledError`` is a
    ``BaseException`` and still propagates, as cancellation must.)
    """
    try:
        enabled, why = archive_enabled(environ)
        if not enabled:
            return {"ok": True, "skippedRun": why}
        when = captured_at or datetime.now(timezone.utc).isoformat()
        rid = run_id or f"ktc:{when}"
        if cadence(environ) == "daily" and already_archived_today(when, path=path):
            # Decided BEFORE the in-page read: a skipped run transfers nothing.
            return {"ok": True, "skippedRun": "already_archived_today", "runId": rid}
        projection = await asyncio.wait_for(project_format_variants(page), timeout=timeout_s)
        summary = archive_projection(
            projection,
            run_id=rid,
            captured_at=when,
            page_url=str(getattr(page, "url", "") or ""),
            selected_capture_hashes=selected_capture_hashes,
            path=path,
        )
        # Drop the only large structure before returning (#1391 posture).
        del projection
        summary["ok"] = True
        return summary
    except Exception as exc:  # noqa: BLE001 — evidence capture must not fail a scrape
        log.warning("KTC format-variant archive failed (scrape unaffected): %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def selected_hashes(captures: Mapping[str, Any]) -> dict[str, str]:
    """``{value_source: content_hash}`` of the scraper's own selected capture.

    Recorded so an archived variant board can be tied back to the exact
    selected-board capture of the same cycle.  Never raises.
    """
    out: dict[str, str] = {}
    try:
        for source, capture in captures.items():
            digest = getattr(capture, "content_hash", None)
            if digest:
                out[str(source)] = str(digest)
    except Exception:  # noqa: BLE001
        return {}
    return out


__all__: Sequence[str] = (
    "CELL_FIELDS",
    "ENDPOINT",
    "KTC_FORMAT_GROUPS",
    "KTC_MODE_FIELDS",
    "KTC_TEP_LEVELS",
    "KtcFormatArchiveError",
    "PROVIDER_FAMILY",
    "VARIANT_KEYS",
    "already_archived_today",
    "archive_enabled",
    "cadence",
    "archive_projection",
    "archive_variants_safely",
    "boards_from_projection",
    "payload_hash",
    "project_format_variants",
    "selected_hashes",
)
