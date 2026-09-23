"""Parse one source board into its MEANINGFUL content, and judge its validity.

Shared by the source-dataset state owner (:mod:`src.sources.dataset_state`)
and the advisory CI report (``scripts/check_source_health.py``), so "which
columns carry a source's valuation" and "is this board structurally sane"
have one definition.

Meaningful content is the source's player/pick identity plus its published
value and/or rank.  Nothing else enters a fingerprint: not IDs, teams, ages,
ADP, projections, markup, page timestamps or tracking noise.  Two boards that
differ only in those are the SAME dataset.

Health is about DATA VALIDITY, never fetch age.  A board can be:

* ``HEALTHY``  — parsed, enough named rows, numeric signal present;
* ``DEGRADED`` — parsed but suspicious (duplicate explosion, zero/missing
  explosion, row count collapsed against the source's own history);
* ``FAILED``   — not a usable board at all (HTML / CAPTCHA / challenge /
  login page, no recognizable columns, empty).

A FAILED board never becomes a new observation — the dataset-state owner
keeps the last valid one.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from src.identity.picks import is_pick_name

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"

NAME_ALIASES: frozenset[str] = frozenset({"name", "player", "player_name", "playername"})
RANK_ALIASES: frozenset[str] = frozenset(
    {"avg", "rank", "overall_rank", "overallrank", "originalrank", "effectiverank"}
)
VALUE_ALIASES: frozenset[str] = frozenset(
    {"value", "trade_value", "tradevalue", "3d value +", "boone_value", "boonevalue"}
)

SUBSET_PLAYERS = "players"
SUBSET_PICKS = "picks"

# Markers of a page that is not a data board.  Any of these in the first
# bytes of a "CSV" means an HTML error / bot-challenge / login page was
# written where a board should be.
_NON_DATA_MARKERS: tuple[str, ...] = (
    "<!doctype",
    "<html",
    "<head",
    "<body",
    "cf-challenge",
    "cf-browser-verification",
    "just a moment...",
    "attention required",
    "captcha",
    "please log in",
    "sign in to continue",
    "access denied",
)

# A board whose named-row count falls below this share of its own rolling
# median is not a legitimate smaller board — it is a partial scrape.
ROW_COLLAPSE_FRACTION = 0.5
# Duplicate / zero / non-numeric shares above which a board is suspicious.
DUPLICATE_FRACTION_LIMIT = 0.10
ZERO_FRACTION_LIMIT = 0.25
NUMERIC_COVERAGE_MIN = 0.80
NAME_COVERAGE_MIN = 0.95


def _token(text: object) -> str:
    return str(text or "").strip().lower()


def _num(raw: object) -> float | None:
    text = str(raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


@dataclass
class ParsedBoard:
    """One source board reduced to its meaningful content."""

    #: ``{subset: {row_key: "value|rank"}}`` — the canonical content map.
    rows: dict[str, dict[str, str]] = field(
        default_factory=lambda: {SUBSET_PLAYERS: {}, SUBSET_PICKS: {}}
    )
    header: list[str] = field(default_factory=list)
    row_count: int = 0
    named_rows: int = 0
    numeric_rows: int = 0
    zero_rows: int = 0
    duplicate_names: int = 0
    health: str = HEALTHY
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def subset_rows(self, subset: str) -> dict[str, str]:
        return self.rows.get(subset) or {}


def looks_like_non_data(text: str) -> str | None:
    """Return the marker when ``text`` is an HTML / challenge / login page."""
    head = text[:4096].lower()
    for marker in _NON_DATA_MARKERS:
        if marker in head:
            return marker
    return None


def parse_board(text: str, *, signal: str = "value") -> ParsedBoard:
    """Reduce CSV ``text`` to its meaningful content plus structural health.

    ``signal`` is the column the source VOTES on (``value`` or ``rank``);
    every recognized value/rank column is fingerprinted, because a vendor
    republishing values under an unchanged rank order is still a new
    publication.
    """
    board = ParsedBoard()
    marker = looks_like_non_data(text)
    if marker is not None:
        board.health = FAILED
        board.errors.append(f"non-data page content ({marker!r})")
        return board
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        board.header = list(reader.fieldnames or [])
        rows = list(reader)
    except csv.Error as exc:
        board.health = FAILED
        board.errors.append(f"csv unreadable: {exc}")
        return board

    name_cols = [c for c in board.header if _token(c) in NAME_ALIASES]
    rank_cols = [c for c in board.header if _token(c) in RANK_ALIASES]
    value_cols = [c for c in board.header if _token(c) in VALUE_ALIASES]
    content_cols = value_cols + rank_cols
    if not name_cols:
        board.health = FAILED
        board.errors.append(f"no recognized name column in header {board.header!r}")
        return board
    signal_cols = rank_cols if signal == "rank" else value_cols
    if not signal_cols:
        board.health = FAILED
        board.errors.append(f"no recognized {signal} column in header {board.header!r}")
        return board

    board.row_count = len(rows)
    seen: dict[str, int] = {}
    for row in rows:
        name = ""
        for col in name_cols:
            name = str(row.get(col) or "").strip()
            if name:
                break
        if not name:
            continue
        board.named_rows += 1
        signal_value = None
        for col in signal_cols:
            signal_value = _num(row.get(col))
            if signal_value is not None:
                break
        if signal_value is None:
            continue
        board.numeric_rows += 1
        if signal_value == 0:
            board.zero_rows += 1
        base_key = re.sub(r"\s+", " ", name.casefold())
        occurrence = seen.get(base_key, 0)
        seen[base_key] = occurrence + 1
        if occurrence:
            board.duplicate_names += 1
        row_key = base_key if not occurrence else f"{base_key}#{occurrence + 1}"
        content = "|".join(
            "" if _num(row.get(c)) is None else repr(_num(row.get(c))) for c in content_cols
        )
        subset = SUBSET_PICKS if is_pick_name(name) else SUBSET_PLAYERS
        board.rows[subset][row_key] = content

    if board.row_count == 0 or board.numeric_rows == 0:
        board.health = FAILED
        board.errors.append("board carries no numeric rows")
        return board
    if board.named_rows < max(1, int(board.row_count * NAME_COVERAGE_MIN)):
        board.errors.append(f"name coverage degraded: {board.named_rows}/{board.row_count}")
    if board.numeric_rows < max(1, int(board.row_count * NUMERIC_COVERAGE_MIN)):
        board.errors.append(f"numeric coverage degraded: {board.numeric_rows}/{board.row_count}")
    if board.duplicate_names > board.row_count * DUPLICATE_FRACTION_LIMIT:
        board.errors.append(f"duplicate-name explosion: {board.duplicate_names}")
    elif board.duplicate_names:
        board.warnings.append(f"{board.duplicate_names} duplicate name occurrence(s)")
    if signal != "rank" and board.zero_rows > board.numeric_rows * ZERO_FRACTION_LIMIT:
        board.errors.append(f"zero-value explosion: {board.zero_rows}/{board.numeric_rows}")
    if board.errors:
        board.health = DEGRADED
    return board


def assess_row_count(board: ParsedBoard, rolling_median: float | None) -> None:
    """Flag a board whose size collapsed against the source's OWN history.

    Source-aware on purpose: a board that is small by design (a 50-row
    rookie list) is compared with itself, never with a global floor.
    """
    if board.health == FAILED or not rolling_median or rolling_median <= 0:
        return
    total = sum(len(v) for v in board.rows.values())
    if total < rolling_median * ROW_COLLAPSE_FRACTION:
        board.errors.append(
            f"row-count collapse: {total} vs own rolling median {rolling_median:.0f}"
        )
        board.health = DEGRADED
