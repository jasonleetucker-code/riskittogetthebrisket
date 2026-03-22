from __future__ import annotations

import re
import unicodedata

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def normalize_player_name(name: str | None) -> str:
    if not name:
        return ""
    s = _ascii_fold(name).lower().strip()
    s = s.replace("&", " and ")
    s = _SUFFIX_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_team(team: str | None) -> str:
    if not team:
        return ""
    return _ascii_fold(team).upper().strip()


def normalize_position_family(pos: str | None) -> str:
    if not pos:
        return ""
    p = _ascii_fold(pos).upper().strip()

    # Handle Sleeper-style dual positions (DL/LB, DB/LB) BEFORE splitting.
    # Always prefer DL or DB over LB for IDP dual-eligible players.
    if "/" in p:
        parts = [s.strip() for s in p.split("/")]
        for preferred in ("DL", "DE", "DT", "EDGE", "DB", "CB", "S", "SS", "FS"):
            if preferred in parts:
                return normalize_position_family(preferred)
        # No preferred found — fall through with first part
        p = parts[0]

    p = p.replace("(", " ").replace(")", " ")
    p = re.sub(r"[^A-Z0-9]+", " ", p).strip()
    tokens = p.split()
    if not tokens:
        return ""
    t = tokens[0]
    if t.startswith("QB"):
        return "QB"
    if t.startswith("RB"):
        return "RB"
    if t.startswith("WR"):
        return "WR"
    if t.startswith("TE"):
        return "TE"
    if t in {"DE", "DT", "DL", "EDGE"}:
        return "DL"
    if t in {"LB", "ILB", "OLB"}:
        return "LB"
    if t in {"S", "SS", "FS", "CB", "DB"}:
        return "DB"
    return t

