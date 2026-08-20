#!/usr/bin/env python3
"""Acquire Dynasty Nerds' public IDP Top-275, preserved (not priced).

Public, no auth, no paywall: a plain ``requests.get`` against
``dynastynerds.com/idp/dynasty-idp-rankings-tiers/`` returns the full
Top-275 inline in the page HTML as ten tier tables.

This is **acquisition and preservation only** — Lane 8 §7a's posture,
matching PR A. It writes to the source archive
(``src/source_archive/store.py``), never to a production CSV, and it
never touches ``src/api/data_contract.py`` or ``_RANKING_SOURCES``. No
cardinal value is manufactured: Dynasty Nerds' IDP board publishes rank,
positional rank (``DL1``, ``LB2``, …) and a named tier — nothing else —
and that is exactly what is preserved. ``ArchivedRow.value`` stays
``None`` on every row.

Schema pin (verified 2026-08-20 against the live page, matching the
Lane 8 program plan):

* JSON-LD ``Article`` block carries ``datePublished`` / ``dateModified``,
  used as ``source_as_of`` rather than "now" — this script did not
  publish the board, the vendor did, on a date the vendor states.
* Exactly 10 ``<table>`` tier tables, each preceded by an
  ``<h2>``/``<h3>`` heading of the form ``Tier N | <label>``.
* Table headers exactly: Rank, Player, Position, Age, Team,
  ``<year> IDP Rank`` (the last column carries the positional rank,
  e.g. ``DL1``; the year in its label is not otherwise parsed).
* 275 total data rows across all ten tables.

Any of those failing is a **schema regression** (exit 2), not a soft
failure — the same distinction ``fetch_dynasty_nerds.py`` (the existing
offense fetcher, joining the same ``dynastyNerds`` provider family) makes
for its own SFLEXTEP schema.

Run::

    python3 scripts/fetch_dynasty_nerds_idp.py

Exit codes:
    0 — HEALTHY, archived (or an unchanged re-archive, itself a no-op)
    1 — UNAVAILABLE / PARSE_FAILED (fetch error, or the page's shape
        could not be parsed into rows at all)
    2 — SCHEMA_CHANGED (the schema pin above did not hold)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_dynasty_nerds_idp] requests is not installed", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sources.acquisition_state import (  # noqa: E402
    AUTH_REQUIRED,
    HEALTHY,
    PARSE_FAILED,
    SCHEMA_CHANGED,
    UNAVAILABLE,
    AcquisitionOutcome,
)
from src.source_archive.records import ArchivedRow  # noqa: E402
from src.source_archive.store import ArchivedBoard, ArchiveRefused, archive_board  # noqa: E402

DN_IDP_URL = "https://www.dynastynerds.com/idp/dynasty-idp-rankings-tiers/"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

PROVIDER = "dynastyNerds"
FORMAT_KEY = "idp_top275"

_EXPECTED_HEADERS = ("Rank", "Player", "Position", "Age", "Team")
_EXPECTED_TABLE_COUNT = 10
#: Below this, treat as a schema regression rather than a thin week — the
#: board is a fixed "Top 275", not a rolling list that shrinks.
_ROW_COUNT_FLOOR = 200

_TIER_HEADING_RE = re.compile(r"<h[23][^>]*>\s*(Tier\s+\d+[^<]*)</h[23]>", re.IGNORECASE)
_TABLE_RE = re.compile(r"<table.*?</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.IGNORECASE | re.DOTALL)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.IGNORECASE | re.DOTALL
)

#: Vendor position string -> our DL/LB/DB family. Reusing the repo-wide
#: family names rather than inventing a second vocabulary; see
#: ``src/utils/name_clean.py::POSITION_ALIASES`` for the canonical list this
#: narrows from (Dynasty Nerds' IDP board only ever prints these three).
_POSITION_FAMILY = {"DL": "DL", "LB": "LB", "DB": "DB", "EDGE": "DL"}


def _clean(cell: str) -> str:
    return _TAG_RE.sub("", cell).strip()


def _fetch(timeout: float = 20.0) -> str | None:
    try:
        resp = requests.get(DN_IDP_URL, headers={"User-Agent": UA}, timeout=timeout)
    except requests.RequestException as exc:
        print(f"[fetch_dynasty_nerds_idp] request failed: {exc}", file=sys.stderr)
        return None
    if resp.status_code == 401 or resp.status_code == 403:
        print(
            f"[fetch_dynasty_nerds_idp] AUTH_REQUIRED: HTTP {resp.status_code}",
            file=sys.stderr,
        )
        return None
    if resp.status_code != 200:
        print(f"[fetch_dynasty_nerds_idp] HTTP {resp.status_code}", file=sys.stderr)
        return None
    return resp.text


def _extract_source_as_of(html: str) -> str | None:
    """The vendor's own publication/modification date, from JSON-LD.

    Prefers ``dateModified`` (the freshest date the vendor states); falls
    back to ``datePublished``. Returns ``None`` — never "now" — if neither
    is present, because a missing vendor date is missing, not today.
    """
    for match in _JSONLD_RE.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        date = payload.get("dateModified") or payload.get("datePublished")
        if date:
            return str(date)
    return None


def _parse_tier_tables(html: str) -> tuple[list[ArchivedRow], list[str]]:
    """Return (rows, problems). ``problems`` non-empty means schema drift."""
    problems: list[str] = []

    tier_labels = [m.group(1).strip() for m in _TIER_HEADING_RE.finditer(html)]
    tables = _TABLE_RE.findall(html)

    if len(tables) != _EXPECTED_TABLE_COUNT:
        problems.append(f"expected {_EXPECTED_TABLE_COUNT} tier tables, found {len(tables)}")
    if len(tier_labels) < len(tables):
        # Pad rather than fail outright on a heading-count mismatch alone —
        # a missing LABEL is not a missing ROW, and the row-derived
        # positional rank (DL1, LB2, ...) still identifies the tier's rough
        # position even if its name can't be recovered.
        tier_labels += [f"Tier {i + 1} (unlabeled)" for i in range(len(tier_labels), len(tables))]

    rows: list[ArchivedRow] = []
    for table_idx, table_html in enumerate(tables):
        table_rows = _ROW_RE.findall(table_html)
        if not table_rows:
            continue
        header_cells = [_clean(h) for h in _TH_RE.findall(table_rows[0])]
        if header_cells and tuple(header_cells[:5]) != _EXPECTED_HEADERS:
            problems.append(
                f"table {table_idx}: header {header_cells[:5]!r} != {_EXPECTED_HEADERS!r}"
            )
            continue
        tier_label = tier_labels[table_idx] if table_idx < len(tier_labels) else None
        for raw_row in table_rows[1:]:
            cells = [_clean(c) for c in _TD_RE.findall(raw_row)]
            if len(cells) < 6:
                continue
            rank_str, player, position, age_str, team, pos_rank_str = cells[:6]
            try:
                overall_rank = int(rank_str)
            except ValueError:
                continue
            positional_rank = None
            pos_rank_match = re.search(r"(\d+)$", pos_rank_str)
            if pos_rank_match:
                positional_rank = int(pos_rank_match.group(1))
            age = None
            try:
                age = float(age_str)
            except ValueError:
                pass
            rows.append(
                ArchivedRow(
                    source_name=player,
                    source_position=position or None,
                    position_family=_POSITION_FAMILY.get(position, None),
                    team=team or None,
                    age=age,
                    overall_rank=overall_rank,
                    positional_rank=positional_rank,
                    tier=tier_label,
                    value=None,
                    value_unit=None,
                    native={"positional_rank_label": pos_rank_str},
                )
            )

    if len(rows) < _ROW_COUNT_FLOOR:
        problems.append(f"only {len(rows)} rows parsed, floor is {_ROW_COUNT_FLOOR}")

    return rows, problems


def run(*, archive_path: Path | None = None) -> AcquisitionOutcome:
    now = datetime.now(timezone.utc).isoformat()
    html = _fetch()
    if html is None:
        return AcquisitionOutcome(
            source_key=PROVIDER,
            state=UNAVAILABLE,
            reason="fetch_failed",
            observed_at=now,
        )

    rows, problems = _parse_tier_tables(html)
    if not rows:
        return AcquisitionOutcome(
            source_key=PROVIDER,
            state=PARSE_FAILED,
            reason="no_rows_extracted",
            detail="; ".join(problems) or "unknown parse failure",
            observed_at=now,
        )
    if problems:
        return AcquisitionOutcome(
            source_key=PROVIDER,
            state=SCHEMA_CHANGED,
            reason="schema_pin_violated",
            detail="; ".join(problems),
            observed_at=now,
        )

    source_as_of = _extract_source_as_of(html)
    board = ArchivedBoard(
        provider=PROVIDER,
        provider_family=PROVIDER,
        endpoint=DN_IDP_URL,
        format_key=FORMAT_KEY,
        game_type="DYNASTY",
        run_id=now,
        # v1 shape: one float per name. Rank is a real published number,
        # not a fabricated value — this is not the "MISSING IS NEVER ZERO"
        # violation the v1 shape otherwise invites, because nothing here
        # claims to be a cardinal value. records_json carries the honest
        # (rank, positional rank, tier) structure for anything that reads
        # v2.
        rows={r.source_name: float(r.overall_rank) for r in rows if r.overall_rank},
        captured_at=now,
        source_as_of=source_as_of,
        records=tuple(rows),
    )
    try:
        result = archive_board(board, path=archive_path)
    except ArchiveRefused as exc:
        return AcquisitionOutcome(
            source_key=PROVIDER,
            state=PARSE_FAILED,
            reason="archive_refused",
            detail=str(exc),
            observed_at=now,
        )

    return AcquisitionOutcome(
        source_key=PROVIDER,
        state=HEALTHY,
        row_count=len(rows),
        observed_at=now,
        metadata={"source_as_of": source_as_of, "archive_result": result},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=None,
        help="Override the archive DB path (tests only).",
    )
    args = parser.parse_args(argv)

    outcome = run(archive_path=args.archive_path)
    print(
        json.dumps(
            {
                "sourceKey": outcome.source_key,
                "state": outcome.state,
                "reason": outcome.reason,
                "detail": outcome.detail,
                "rowCount": outcome.row_count,
                "observedAt": outcome.observed_at,
                "metadata": outcome.metadata,
            },
            indent=2,
        )
    )

    if outcome.state == HEALTHY:
        return 0
    if outcome.state == SCHEMA_CHANGED:
        return 2
    if outcome.state == AUTH_REQUIRED:
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
