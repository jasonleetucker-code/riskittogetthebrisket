from __future__ import annotations

import re
import unicodedata

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v|dr)\b\.?", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


# ── Canonical position aliases ──────────────────────────────────────────
# Single source of truth for mapping raw position strings to league-standard
# position families. All modules should import from here.
POSITION_ALIASES: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
    "K": "K",
    "P": "K",
    "PICK": "PICK",
}


# ── Nickname map ────────────────────────────────────────────────────────
# Common nickname → formal first-name expansions for fuzzy matching.
NICKNAME_MAP: dict[str, str] = {
    "cam": "cameron",
    "tj": "t j",
    "cj": "c j",
    "dj": "d j",
    "aj": "a j",
    "jt": "j t",
    "dk": "d k",
    "kj": "k j",
    "pj": "p j",
    "rj": "r j",
}


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _collapse_initials(s: str) -> str:
    """Collapse adjacent single-letter words into a single token.

    'a j brown' → 'aj brown'
    't j hockenson' → 'tj hockenson'
    'd k metcalf' → 'dk metcalf'

    This ensures 'T.J. Hockenson' (→ 't j hockenson') matches
    'TJ Hockenson' (→ 'tj hockenson').
    """
    parts = s.split()
    result = []
    i = 0
    while i < len(parts):
        if len(parts[i]) == 1 and parts[i].isalpha():
            # Collect consecutive single-letter words
            initials = parts[i]
            while i + 1 < len(parts) and len(parts[i + 1]) == 1 and parts[i + 1].isalpha():
                i += 1
                initials += parts[i]
            result.append(initials)
        else:
            result.append(parts[i])
        i += 1
    return " ".join(result)


def normalize_player_name(name: str | None) -> str:
    if not name:
        return ""
    s = _ascii_fold(name).lower().strip()
    s = s.replace("&", " and ")
    s = _SUFFIX_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    s = _collapse_initials(s)
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
    # Strip trailing rank digits (e.g. "LB1" → "LB", "DL70" → "DL")
    # DLF IDP CSVs use formats like "LB1", "LB67" for positional rank.
    t_base = re.sub(r"\d+$", "", t) or t
    if t_base in POSITION_ALIASES:
        return POSITION_ALIASES[t_base]
    # startsWith fallback for compound tokens (e.g. "QBWR")
    for prefix in ("QB", "RB", "WR", "TE"):
        if t_base.startswith(prefix):
            return prefix
    return t
