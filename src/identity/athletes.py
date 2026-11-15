"""Sport-aware athlete identity (DFS-§9-03) — an extension of the canonical identity owner.

Why this exists
---------------
Everything else in ``src/identity/`` answers "which NFL player is this?":
:class:`~src.identity.resolution.SleeperDirectoryIndex` indexes Sleeper's
``/v1/players/nfl`` dump and :func:`~src.identity.resolution.resolve_canonical_v2`
resolves against it.  The DFS section also covers NBA and NHL (and MMA), where
the same NAME routinely belongs to a different human — an NBA "Jaylen Williams"
is not an NFL one, and must never resolve to one because the only directory on
hand happens to be the NFL's.

Rules this module owns (and every consumer inherits):

* **Every athlete identity key carries its sport.**  ``athlete:<sport>:<namespace>:<native id>``
  — two providers' ids, or two sports' ids, can never collide into one person.
* **A directory answers only for its own sport.**  Resolving an NBA name
  against the NFL directory is refused with ``sport_mismatch``; asking for a
  sport no directory is wired for is refused with ``no_directory_for_sport``.
  Both are explicit UNRESOLVED states — never a best guess, never first-wins.
* **Team codes are per sport.**  ``WSH`` is the Wizards in the NBA and the
  Capitals in the NHL; each sport has its own canonical code table with the
  provider spellings it accepts.  An unknown code is ``None`` (unresolved),
  never passed through as if it were canonical.

NFL resolution is unchanged: :func:`resolve_athlete` delegates to
``resolve_canonical_v2`` with the same index and signals.  No NBA/NHL player
directory is wired today, so NBA/NHL athletes stay PROVIDER-SCOPED (their key
names the provider that published them) and that is stated, not hidden.
"""

from __future__ import annotations

import re
from typing import Any

from src.identity.resolution import (
    CANONICAL_V2,
    UNRESOLVED,
    Resolution,
    SleeperDirectoryIndex,
    resolve_canonical_v2,
)

SPORTS = ("nfl", "nba", "nhl", "mma")

REASON_SPORT_MISMATCH = "sport_mismatch"
REASON_NO_DIRECTORY_FOR_SPORT = "no_directory_for_sport"
REASON_UNKNOWN_SPORT = "unknown_sport"

#: Why an athlete of this sport is provider-scoped (no canonical directory yet).
PROVIDER_SCOPED_REASON = {
    "nba": "No permitted NBA player directory is wired into the identity owner.",
    "nhl": "No permitted NHL player directory is wired into the identity owner.",
    "mma": "No permitted MMA fighter directory is wired into the identity owner.",
}

_TOKEN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._\-]{0,63}$")


class AthleteIdentityError(ValueError):
    """A malformed identity request (unknown sport, unsafe token) — a caller bug."""


def canonical_sport(sport: Any) -> str:
    s = str(sport or "").strip().lower()
    if s not in SPORTS:
        raise AthleteIdentityError(f"unknown sport {sport!r}; expected one of {SPORTS}")
    return s


def _token(value: Any, what: str) -> str:
    s = str(value or "").strip()
    if not _TOKEN.match(s):
        raise AthleteIdentityError(f"unsafe {what} {value!r}")
    return s


def athlete_key(sport: str, namespace: str, native_id: Any) -> str:
    """``athlete:<sport>:<namespace>:<native id>`` — the sport is part of the key."""
    return (
        f"athlete:{canonical_sport(sport)}:{_token(namespace, 'namespace')}:"
        f"{_token(native_id, 'native id')}"
    )


def parse_athlete_key(key: Any) -> tuple[str, str, str] | None:
    parts = str(key or "").split(":")
    if len(parts) != 4 or parts[0] != "athlete" or parts[1] not in SPORTS:
        return None
    return parts[1], parts[2], parts[3]


def sport_scoped_token(sport: str, native_id: Any) -> str:
    """``<sport>-<native id>`` — for id spaces (e.g. DFS synthetic player ids) that
    must stay unique across sports without carrying the full key."""
    return f"{canonical_sport(sport)}-{_token(native_id, 'native id')}"


# ── teams ────────────────────────────────────────────────────────────────

_NBA = {
    "ATL": (),
    "BOS": (),
    "BKN": ("BRK", "BKO", "NJN"),
    "CHA": ("CHO", "CHH"),
    "CHI": (),
    "CLE": (),
    "DAL": (),
    "DEN": (),
    "DET": (),
    "GSW": ("GS", "GOS"),
    "HOU": (),
    "IND": (),
    "LAC": (),
    "LAL": (),
    "MEM": (),
    "MIA": (),
    "MIL": (),
    "MIN": (),
    "NOP": ("NO", "NOR"),
    "NYK": ("NY",),
    "OKC": (),
    "ORL": (),
    "PHI": (),
    "PHX": ("PHO",),
    "POR": (),
    "SAC": (),
    "SAS": ("SA",),
    "TOR": (),
    "UTA": ("UTAH", "UTH"),
    "WAS": ("WSH",),
}
_NHL = {
    "ANA": (),
    "BOS": (),
    "BUF": (),
    "CGY": ("CAL",),
    "CAR": (),
    "CHI": (),
    "COL": (),
    "CBJ": ("CLB", "CLS"),
    "DAL": (),
    "DET": (),
    "EDM": (),
    "FLA": ("FLO",),
    "LAK": ("LA",),
    "MIN": (),
    "MTL": ("MON",),
    "NSH": ("NAS",),
    "NJD": ("NJ",),
    "NYI": (),
    "NYR": (),
    "OTT": (),
    "PHI": (),
    "PIT": (),
    "SJS": ("SJ",),
    "SEA": (),
    "STL": (),
    "TBL": ("TB",),
    "TOR": (),
    "UTA": ("UTAH", "UTM"),
    "VAN": (),
    "VGK": ("VEG", "LV"),
    "WSH": ("WAS",),
    "WPG": ("WIN",),
}


def _table(spec: dict[str, tuple[str, ...]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for code, aliases in spec.items():
        out[code] = code
        for a in aliases:
            out[a] = code
    return out


_TEAM_TABLES = {"nba": _table(_NBA), "nhl": _table(_NHL)}


def canonical_team(sport: str, code: Any) -> str | None:
    """The sport's canonical team code for a provider spelling, or None when the
    code is unknown for that sport.  NFL delegates to the NFL owner
    (``src.playerctx.normalize.normalize_team_code``)."""
    s = canonical_sport(sport)
    raw = str(code or "").strip().upper()
    if not raw:
        return None
    if s == "nfl":
        from src.playerctx.normalize import normalize_team_code

        return normalize_team_code(raw) or None
    table = _TEAM_TABLES.get(s)
    if table is None:
        return None
    return table.get(raw)


def teams(sport: str) -> frozenset[str]:
    return frozenset(_TEAM_TABLES.get(canonical_sport(sport), {}).values())


# ── resolution ───────────────────────────────────────────────────────────


def _refused(reason: str) -> Resolution:
    return Resolution(status=UNRESOLVED, policy=CANONICAL_V2, method="none", reason=reason)


def resolve_athlete(
    sport: str,
    index: SleeperDirectoryIndex | None,
    *,
    name: str | None = None,
    position: str | None = None,
    team: str | None = None,
) -> Resolution:
    """Resolve an athlete WITHIN ITS SPORT.

    ``index`` must be a directory for ``sport`` (its ``sport`` attribute); any
    other directory is refused with ``sport_mismatch``.  With no directory for
    the sport the answer is ``no_directory_for_sport``.  For NFL with the NFL
    directory this is exactly ``resolve_canonical_v2``.
    """
    try:
        s = canonical_sport(sport)
    except AthleteIdentityError:
        return _refused(REASON_UNKNOWN_SPORT)
    if index is None:
        return _refused(REASON_NO_DIRECTORY_FOR_SPORT)
    if getattr(index, "sport", None) != s:
        return _refused(REASON_SPORT_MISMATCH)
    return resolve_canonical_v2(index, name=name, position=position, team=team)
