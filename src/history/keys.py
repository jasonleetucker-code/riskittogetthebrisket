"""Canonical asset keys for temporal history.

One namespace, three grades, zero collisions:

* ``player:<sleeperId>`` — a player with resolved platform identity.
  Stable through team changes, display-name changes and position
  reclassification, which is exactly what a historical series needs.
* ``name:<canonical_player_key>`` — a player the identity pipeline
  could not resolve to a platform id on that day.  Explicitly a lower
  identity grade: the key survives team changes but not display-name
  changes.  Writers count these (``unresolved`` in ingest summaries)
  rather than hiding them.
* ``mpick:<year>:r<N>[:s<slot>|:t<tier>]`` — a market pick reference,
  minted by the C1-U3 pick-identity owner (``src/identity/picks``).
  History NEVER keys a pick by its display label.

The three prefixes are disjoint, so a player's history can never
resolve as a pick's or vice versa — the collision class the retired
``rankChange`` snapshot (bare ``canonicalName``, no namespace) allowed
is unrepresentable here.

League picks (owned assets, ``pick:<leagueKey>:...``) are deliberately
NOT a history namespace: sources price MARKET references, so history is
recorded against them.  A consumer holding a league pick resolves it to
its market ref with ``picks.market_resolution()`` (a pure function of
state and the clock) and queries that — ownership changes and the
generic→exact slot transition therefore never fork a history series.
"""

from __future__ import annotations

from typing import Any

from src.identity.picks import parse_board_pick_name, parse_market_pick_id
from src.utils.name_clean import (  # noqa: F401 — canonical_position_group re-exported for ingest callers
    canonical_player_key,
    canonical_position_group,
    resolve_canonical_name,
)

PLAYER_PREFIX = "player:"
NAME_PREFIX = "name:"
PICK_PREFIX = "mpick:"

ASSET_CLASS_OFFENSE = "offense"
ASSET_CLASS_IDP = "idp"
ASSET_CLASS_PICK = "pick"

_VALID_ASSET_CLASSES = frozenset({ASSET_CLASS_OFFENSE, ASSET_CLASS_IDP, ASSET_CLASS_PICK})


def is_valid_asset_key(key: str) -> bool:
    """Structural validity — used by store-level fail-closed checks."""
    if not isinstance(key, str) or not key:
        return False
    if key.startswith(PLAYER_PREFIX):
        return len(key) > len(PLAYER_PREFIX)
    if key.startswith(NAME_PREFIX):
        return len(key) > len(NAME_PREFIX)
    if key.startswith(PICK_PREFIX):
        return parse_market_pick_id(key) is not None
    return False


def pick_asset_key(name: Any) -> str | None:
    """Market-pick key for a board row name, via the C1-U3 owner.

    Returns ``None`` when the name does not parse as a pick — the
    caller records the row as unresolved rather than guessing.
    """
    if not name:
        return None
    ref = parse_board_pick_name(str(name))
    return ref.canonical_id if ref is not None else None


def player_asset_key(
    player_id: Any,
    name: Any,
    position: Any,
) -> str | None:
    """Player key: platform id first, identity-grade name fallback."""
    pid = str(player_id or "").strip()
    if pid:
        return f"{PLAYER_PREFIX}{pid}"
    ck = canonical_player_key(str(name), str(position) if position else None) if name else ""
    if not ck:
        return None
    return f"{NAME_PREFIX}{ck}"


def name_key_for_class(name: Any, asset_class: str) -> str | None:
    """Name-grade player key when only an asset class is known.

    Produces the same ``name:<canonical>::<GROUP>`` shape
    :func:`player_asset_key` falls back to, mapping the coarse asset
    class straight to the C1-U2 position group (offense → OFFENSE,
    idp → IDP, anything else → the unknown group ``*``).
    """
    cname = resolve_canonical_name(str(name)) if name else ""
    if not cname:
        return None
    group = {ASSET_CLASS_OFFENSE: "OFFENSE", ASSET_CLASS_IDP: "IDP"}.get(asset_class, "*")
    return f"{NAME_PREFIX}{cname}::{group}"


def asset_key_for_contract_row(row: dict[str, Any]) -> tuple[str, str] | None:
    """``(asset_key, asset_class)`` for a canonical-contract row.

    Pick rows key through the pick-identity owner; a pick row whose
    name the owner cannot parse returns ``None`` (counted, never
    guessed).  Player rows key by platform id, else by the C1-U2
    position-aware canonical name key.
    """
    name = row.get("canonicalName") or row.get("displayName")
    asset_class = str(row.get("assetClass") or "").strip().lower()
    position = row.get("position")

    if asset_class == ASSET_CLASS_PICK or (not asset_class and pick_asset_key(name)):
        key = pick_asset_key(name)
        return (key, ASSET_CLASS_PICK) if key else None

    if asset_class not in _VALID_ASSET_CLASSES:
        # Fall back to position-group classification — the same
        # taxonomy ``canonical_player_key`` itself uses.
        group = canonical_position_group(str(position) if position else None)
        if group == "IDP":
            asset_class = ASSET_CLASS_IDP
        elif group == "OFFENSE":
            asset_class = ASSET_CLASS_OFFENSE
        else:
            return None

    key = player_asset_key(row.get("playerId"), name, position)
    return (key, asset_class) if key else None
