"""Parsed candidates -> board assets, through the canonical identity owners.

Players resolve through ``src.identity.resolution.resolve_canonical_v2`` (the
ladder that REFUSES rather than guesses: explicit ``ambiguous`` /
``no_candidate`` states) and then join to the live board by Sleeper id.  Picks
are parsed by ``src.identity.picks`` upstream and join to the board by the
market reference's canonical board-row name.

Fail-closed rules (owner decisions):

* never invent an id — a sleeperId only comes from the directory or the board;
* never substitute silently — an ambiguous name is ``needs_confirmation`` with
  the on-board candidates listed, and a near-miss is ``unresolved`` with
  ``suggestions``; neither is ever auto-selected, and the highest-valued
  candidate is never preferred (values are not read here at all);
* never drop silently — every candidate comes back with a status and, when
  not resolved, a reason.

The screenshot supplies identities only.  No value is read from it, and none
is read from the board here either: pricing happens later, on the canonical
board, by the calculator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.identity.picks import MarketPickRef, slot_tier
from src.identity.resolution import (
    REASON_AMBIGUOUS,
    REASON_EMPTY_INPUT,
    REASON_NO_CANDIDATE,
    RESOLVED,
    resolve_canonical_v2,
    suggest_player_candidates,
)
from src.trade.screenshot_import.parse import KIND_PICK, KIND_PLAYER, NOTE_PICK_OWNER, ParsedItem
from src.utils.name_clean import canonical_position_group, normalize_player_name

STATUS_RESOLVED = "resolved"
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
STATUS_UNRESOLVED = "unresolved"

REASON_NOT_ON_BOARD = "not_on_board"
REASON_NO_MATCH = "no_match"
REASON_RETIRED_PICK_CLASS = "retired_pick_class"
REASON_DIRECTORY_UNAVAILABLE = "identity_directory_unavailable"
REASON_BOARD_UNAVAILABLE = "board_unavailable"

MAX_CANDIDATES = 5
MAX_SUGGESTIONS = 3


@dataclass
class ResolvedItem:
    raw: str
    kind: str
    status: str
    board_name: str | None = None
    sleeper_id: str | None = None
    candidates: list[dict] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
    hints: dict = field(default_factory=lambda: {"position": None, "team": None})
    reason: str | None = None
    notes: tuple[str, ...] = ()


class BoardIndex:
    """Read-only lookups over the live contract's ``playersArray``."""

    def __init__(self, contract: Mapping[str, Any] | None):
        self.available = isinstance(contract, Mapping) and isinstance(
            contract.get("playersArray"), list
        )
        rows = list(contract.get("playersArray") or []) if self.available else []
        self.by_pid: dict[str, dict] = {}
        self.by_name: dict[str, dict] = {}
        self.no_pid_by_norm: dict[str, list[dict]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("displayName") or "").strip()
            if not name:
                continue
            self.by_name.setdefault(name, row)
            pid = str(row.get("playerId") or "").strip()
            if pid:
                self.by_pid.setdefault(pid, row)
            elif str(row.get("assetClass") or "") != "pick":
                keys = {
                    normalize_player_name(name),
                    normalize_player_name(str(row.get("canonicalName") or "")),
                }
                for key in keys - {""}:
                    self.no_pid_by_norm.setdefault(key, []).append(row)
        cdy = contract.get("currentDraftYear") if self.available else None
        self.current_draft_year: int | None = cdy if isinstance(cdy, int) else None
        lifecycle = (contract.get("pickClassLifecycle") if self.available else None) or {}
        retired = lifecycle.get("retiredYears") if isinstance(lifecycle, Mapping) else None
        self.retired_years: frozenset[int] = frozenset(
            int(y) for y in (retired or []) if isinstance(y, int)
        )

    def candidate(self, row: Mapping[str, Any], *, directory_team: str | None = None) -> dict:
        pid = str(row.get("playerId") or "").strip()
        return {
            "sleeperId": pid or None,
            "boardName": str(row.get("displayName")),
            "position": (str(row.get("position") or "").strip() or None),
            "team": (str(row.get("team") or "").strip() or directory_team or None),
        }


def _hint_group_ok(row: Mapping[str, Any], position: str | None) -> bool:
    if not position:
        return True
    row_pos = str(row.get("position") or "").strip()
    if not row_pos:
        return True
    return canonical_position_group(row_pos) == canonical_position_group(position)


def _directory_team(identity_ctx: Any, sleeper_id: str) -> str | None:
    index = getattr(identity_ctx, "index", None)
    cand = index.by_sleeper_id.get(str(sleeper_id)) if index is not None else None
    return (cand.team or None) if cand is not None else None


def _resolve_player(item: ParsedItem, identity_ctx: Any, board: BoardIndex) -> ResolvedItem:
    hints = dict(item.hints)
    out = ResolvedItem(raw=item.raw, kind=KIND_PLAYER, status=STATUS_UNRESOLVED, hints=hints)
    name = item.name or ""
    position, team = hints.get("position"), hints.get("team")

    def _exact_board_fallback() -> bool:
        rows = [
            r
            for r in board.no_pid_by_norm.get(normalize_player_name(name), [])
            if _hint_group_ok(r, position)
        ]
        if len(rows) == 1:
            out.status = STATUS_RESOLVED
            out.board_name = str(rows[0].get("displayName"))
            out.reason = None
            return True
        if len(rows) > 1:
            out.status = STATUS_NEEDS_CONFIRMATION
            out.reason = REASON_AMBIGUOUS
            out.candidates = [board.candidate(r) for r in rows[:MAX_CANDIDATES]]
            return True
        return False

    index = getattr(identity_ctx, "index", None)
    if index is None:
        if not _exact_board_fallback():
            out.reason = REASON_DIRECTORY_UNAVAILABLE
        return out

    res = resolve_canonical_v2(index, name=name, position=position, team=team)
    if res.status == RESOLVED and res.sleeper_id:
        out.sleeper_id = res.sleeper_id
        row = board.by_pid.get(res.sleeper_id)
        if row is not None:
            out.status = STATUS_RESOLVED
            out.board_name = str(row.get("displayName"))
        else:
            out.reason = REASON_NOT_ON_BOARD
        return out

    if res.reason == REASON_AMBIGUOUS:
        cands = []
        for sid in res.candidate_ids:
            row = board.by_pid.get(sid)
            if row is not None:
                cands.append(
                    board.candidate(row, directory_team=_directory_team(identity_ctx, sid))
                )
        cands.sort(key=lambda c: (c["boardName"], c["sleeperId"] or ""))
        if cands:
            out.status = STATUS_NEEDS_CONFIRMATION
            out.reason = REASON_AMBIGUOUS
            out.candidates = cands[:MAX_CANDIDATES]
        else:
            out.reason = REASON_NOT_ON_BOARD
        return out

    if res.reason == REASON_EMPTY_INPUT:
        out.reason = REASON_EMPTY_INPUT
        return out

    # no_candidate (or any other refusal): exact board-name match on rows
    # the board carries without a playerId, then suggestions.
    if res.reason == REASON_NO_CANDIDATE and _exact_board_fallback():
        return out
    out.reason = REASON_NO_MATCH if res.reason == REASON_NO_CANDIDATE else res.reason
    sugg = []
    for s in suggest_player_candidates(index, name, position=position, team=team, limit=10):
        row = board.by_pid.get(s.sleeper_id)
        if row is not None:
            sugg.append(board.candidate(row, directory_team=s.team or None))
        if len(sugg) >= MAX_SUGGESTIONS:
            break
    out.suggestions = sugg
    return out


def _resolve_pick(item: ParsedItem, board: BoardIndex) -> ResolvedItem:
    out = ResolvedItem(
        raw=item.raw,
        kind=KIND_PICK,
        status=STATUS_UNRESOLVED,
        hints={"position": None, "team": None},
        notes=tuple(item.notes),
    )
    ref = item.market_ref
    if ref is None:
        out.reason = item.reason or "unparseable_pick"
        return out
    if ref.year in board.retired_years or (
        board.current_draft_year is not None and ref.year < board.current_draft_year
    ):
        out.reason = REASON_RETIRED_PICK_CLASS
        return out
    name = ref.board_row_name()
    if name is not None and name in board.by_name:
        out.status = STATUS_RESOLVED
        out.board_name = name
        if NOTE_PICK_OWNER in item.notes:
            out.reason = NOTE_PICK_OWNER
        return out
    out.reason = REASON_NOT_ON_BOARD
    # Coarser grades the board DOES carry, as suggestions only — the
    # screenshot's grade is never silently downgraded.
    coarser: list[MarketPickRef] = []
    if ref.grade != "generic":
        coarser.append(MarketPickRef(year=ref.year, round_num=ref.round_num))
    if ref.grade == "slot":
        tier = slot_tier(ref.slot)
        if tier:
            coarser.append(MarketPickRef(year=ref.year, round_num=ref.round_num, tier=tier))
    if ref.grade == "generic":
        for tier in ("early", "mid", "late"):
            coarser.append(MarketPickRef(year=ref.year, round_num=ref.round_num, tier=tier))
    for cref in coarser:
        cname = cref.board_row_name()
        if cname and cname in board.by_name and len(out.suggestions) < MAX_SUGGESTIONS:
            out.suggestions.append(
                {"sleeperId": None, "boardName": cname, "position": None, "team": None}
            )
    return out


def resolve_items(
    items: Sequence[ParsedItem], *, identity_ctx: Any, contract: Mapping[str, Any] | None
) -> list[ResolvedItem]:
    """Resolve every parsed candidate, in order.  One output per input."""
    board = BoardIndex(contract)
    out: list[ResolvedItem] = []
    for item in items:
        if not board.available:
            out.append(
                ResolvedItem(
                    raw=item.raw,
                    kind=item.kind,
                    status=STATUS_UNRESOLVED,
                    hints=dict(item.hints),
                    reason=REASON_BOARD_UNAVAILABLE,
                    notes=tuple(item.notes),
                )
            )
        elif item.kind == KIND_PICK:
            out.append(_resolve_pick(item, board))
        else:
            out.append(_resolve_player(item, identity_ctx, board))
    return out
