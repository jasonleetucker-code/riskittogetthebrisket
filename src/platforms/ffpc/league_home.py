"""FFPC ``LeagueHome.aspx`` transaction-cell normalization.

Public FFPC league pages render one transaction row per participating team.
The row's ``Action`` cell can contain several newline/``<br>`` separated
movements such as ``Received ... from ...`` and ``Traded ... to ...``.
This module expands those human-readable statements into source-neutral
movement fields without using authenticated pages or write endpoints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag

_ACTION_START = re.compile(
    r"(?=\b(?:Received|Acquired|Traded|Sent|Dropped|Released|Added|Claimed|Signed)\b)",
    re.IGNORECASE,
)
_PLAYER_LABEL = re.compile(
    r"^(?P<last>.+?),\s*(?P<first>.+?)\s+(?P<team>[A-Z]{2,3})\s+\((?P<position>[A-Z/]+)\)$"
)
_ROUND_PICK = re.compile(
    r"^(?P<season>20\d{2})\s+(?P<round>[1-7])(?:st|nd|rd|th)?\s+Round\s+Draft\s+Pick$",
    re.IGNORECASE,
)
_SLOT_PICK = re.compile(
    r"^(?P<season>20\d{2})\s+Draft\s+Pick\s+(?P<round>[1-7])\.(?P<slot>\d{1,2})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAction:
    transaction_type: str
    action: str
    asset_label: str
    counterparty: str | None = None
    faab_bid: int | None = None


@dataclass(frozen=True)
class ParsedAssetLabel:
    display_name: str
    asset_type: str = "player"
    nfl_team: str | None = None
    position: str | None = None
    pick_season: str | None = None
    pick_round: str | None = None
    pick_owner_or_slot: str | None = None


def _cell_text(value: Any) -> str:
    if isinstance(value, Tag):
        # Preserve explicit row separators while avoiding CSS-class coupling.
        soup = BeautifulSoup(str(value), "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for block in soup.find_all(["li", "p"]):
            block.insert_after("\n")
        text = soup.get_text(" ", strip=False)
    else:
        text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def split_action_statements(value: Any) -> list[str]:
    """Return one normalized movement statement per public action line."""
    raw = _cell_text(value)
    if not raw:
        return []
    lines: list[str] = []
    for physical_line in raw.splitlines() or [raw]:
        normalized = re.sub(r"\s+", " ", physical_line).strip()
        if not normalized:
            continue
        # Some FFPC layouts concatenate statements without ``<br>``.
        pieces = [part.strip() for part in _ACTION_START.split(normalized) if part.strip()]
        lines.extend(pieces or [normalized])
    return lines


def parse_action_statement(statement: str) -> ParsedAction | None:
    """Parse one FFPC public transaction sentence conservatively."""
    text = re.sub(r"\s+", " ", str(statement or "")).strip()
    if not text:
        return None

    match = re.match(r"^(?:Received|Acquired)\s+(.+?)\s+from\s+(.+)$", text, re.I)
    if match:
        return ParsedAction("trade", "add", match.group(1).strip(), match.group(2).strip())

    match = re.match(r"^(?:Traded|Sent)\s+(.+?)\s+to\s+(.+)$", text, re.I)
    if match:
        return ParsedAction("trade", "drop", match.group(1).strip(), match.group(2).strip())

    match = re.match(r"^(?:Dropped|Released)\s+(.+)$", text, re.I)
    if match:
        return ParsedAction("free_agent", "drop", match.group(1).strip())

    match = re.match(
        r"^(?:Added|Claimed|Signed)\s+(.+?)(?:\s+(?:for|at)\s+\$?(\d+))?$",
        text,
        re.I,
    )
    if match:
        bid = int(match.group(2)) if match.group(2) else None
        return ParsedAction("waiver" if bid is not None else "free_agent", "add", match.group(1).strip(), faab_bid=bid)
    return None


def parse_asset_label(label: str) -> ParsedAssetLabel:
    """Normalize FFPC's ``Last, First TEAM (POS)`` and pick labels."""
    raw = re.sub(r"\s+", " ", str(label or "")).strip()
    round_pick = _ROUND_PICK.match(raw)
    if round_pick:
        return ParsedAssetLabel(
            display_name=raw,
            asset_type="pick",
            pick_season=round_pick.group("season"),
            pick_round=round_pick.group("round"),
        )

    slot_pick = _SLOT_PICK.match(raw)
    if slot_pick:
        slot = int(slot_pick.group("slot"))
        return ParsedAssetLabel(
            display_name=raw,
            asset_type="pick",
            pick_season=slot_pick.group("season"),
            pick_round=slot_pick.group("round"),
            pick_owner_or_slot=f"slot-{slot}",
        )

    player = _PLAYER_LABEL.match(raw)
    if player:
        first = player.group("first").strip()
        last = player.group("last").strip()
        return ParsedAssetLabel(
            display_name=f"{first} {last}",
            nfl_team=player.group("team").upper(),
            position=player.group("position").upper(),
        )

    return ParsedAssetLabel(display_name=raw)
