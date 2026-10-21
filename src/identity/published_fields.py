"""What a vendor row publishes about WHO it is: position family and team (identity owner).

Pure normalization of identity evidence, shared by the upstream capture
prerequisites of outlier-integrity V2.1 (§3.7):

* ``vendor_ids`` (the append-only vendor-id -> Sleeper-id map) needs "does the
  position this row published name a family the directory player holds, and is it
  the same team" to accept a VERIFIED-JOIN observation;
* the capture-evidence collector and the U3 fetchers write the position / team
  cells these helpers read back.

Nothing here decides a join, a value or a vote.  It answers two questions about
fields a source itself published, and **abstains on anything it cannot read**:

* a blank or unknown position belongs to NO family (``None`` from
  :func:`families_compatible`) - no evidence is never a mismatch;
* a blank, free-agent (``FA``) or unrecognised team is ``None`` from
  :func:`team_evidence` - no evidence is never a different team.

The position-family table is the one REGISTERED in the V2.1 preregistration
(``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md`` §3.2, R4: "the
registered position-family table (fixed now)").  It is copied verbatim and must
not be tuned here; changing it is a preregistration amendment.

Reconciliation note: the V2.1 detection branch (PR #1884) defines the same
table and team normalizer inside ``resolution.py`` for Layer A.  When that
branch lands it should import these instead of keeping a second copy
(ONE CONCEPT, ONE CANONICAL OWNER); the behaviour is intentionally identical and
pinned by ``tests/identity/test_published_fields.py``.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from typing import Any

#: R4: the registered position-family table.  EDGE sits in both DL and LB.
POSITION_FAMILIES: dict[str, frozenset[str]] = {
    "QB": frozenset({"QB"}),
    "RB": frozenset({"RB", "FB", "HB"}),
    "WR": frozenset({"WR"}),
    "TE": frozenset({"TE"}),
    "K": frozenset({"K", "PK"}),
    "DL": frozenset({"DL", "DE", "DT", "NT", "IDL", "EDGE"}),
    "LB": frozenset({"LB", "ILB", "OLB", "MLB", "EDGE"}),
    "DB": frozenset({"DB", "CB", "S", "FS", "SS"}),
}
#: R4: allowed drift between families (one person listed at either).
ALLOWED_DRIFT: frozenset[frozenset[str]] = frozenset(
    {frozenset({"DL", "LB"}), frozenset({"LB", "DB"}), frozenset({"RB", "FB"})}
)

#: Long-form team spellings the scraper's team set carries
#: (``name_clean.NFL_TEAM_CODES``) that the NFL team owner
#: (``playerctx.normalize.normalize_team_code``) does not fold.
_TEAM_LONG_FORMS = {"GBP": "GB", "KCC": "KC", "NEP": "NE", "TBB": "TB"}


def position_families(position: object) -> frozenset[str]:
    """The registered families of one published position.  An unknown or blank
    position belongs to no family: no evidence, never a mismatch."""
    return _families_of_raw(str(position or "").strip().upper())


@functools.lru_cache(maxsize=512)
def _families_of_raw(raw: str) -> frozenset[str]:
    """Pure on the normalized string (the table is a constant)."""
    if not raw:
        return frozenset()
    return frozenset(f for f, members in POSITION_FAMILIES.items() if raw in members)


def families_compatible(
    entry_position: object,
    row_positions: Iterable[object],
    alt_positions: Iterable[object] = (),
) -> bool | None:
    """``True`` when the published position names a family the row's player holds
    (or an allowed drift: DL <-> LB, LB <-> DB, RB <-> FB); ``False`` otherwise;
    ``None`` when either side carries no family (no evidence)."""
    entry = position_families(entry_position)
    row: set[str] = set()
    for p in [*row_positions, *alt_positions]:
        row |= position_families(p)
    if not entry or not row:
        return None
    if entry & row:
        return True
    return any(frozenset({a, b}) in ALLOWED_DRIFT for a in entry for b in row)


def team_evidence(team: object) -> str | None:
    """A comparable NFL team code, or ``None`` when the field is no evidence.

    Folds provider spellings through the NFL owner
    (``playerctx.normalize.normalize_team_code``) and the scraper's long forms;
    a free agent (``FA``), a blank or an unrecognised code is NOT evidence of a
    team - missing is never a mismatch.
    """
    return _team_evidence_of_raw(str(team or "").strip().upper())


@functools.lru_cache(maxsize=512)
def _team_evidence_of_raw(raw: str) -> str | None:
    from src.playerctx.normalize import normalize_team_code  # noqa: PLC0415
    from src.utils.name_clean import NFL_TEAM_CODES  # noqa: PLC0415

    if not raw:
        return None
    code = _TEAM_LONG_FORMS.get(raw, normalize_team_code(raw))
    code = _TEAM_LONG_FORMS.get(code, code)
    if code == "FA" or code not in NFL_TEAM_CODES:
        return None
    return code


# ── CSV header vocabulary (shared by the vendor-id recorder) ───────────
#
# Header tokens (casefolded, separators dropped) a source's OWN identity fields
# are read from.  Conservative: a column carrying extra words
# (``sleeper_id_source``) never matches, because attaching the wrong id is a
# confident wrong match.
POSITION_TOKENS: frozenset[str] = frozenset({"position", "pos", "fantasyposition"})
TEAM_TOKENS: frozenset[str] = frozenset({"team", "nflteam"})
VENDOR_ID_TOKENS: frozenset[str] = frozenset({"playerid", "ktcid", "vendorid"})
SLEEPER_ID_TOKENS: frozenset[str] = frozenset({"sleeperid", "sleeperplayerid"})


def normalize_header_token(column: object) -> str:
    """Casefold a CSV header and drop separators (``"Sleeper Id"`` ->
    ``"sleeperid"``).  Identical to ``data_contract._normalize_header_token``;
    parity is pinned by ``tests/identity/test_published_fields.py``."""
    s = str(column or "").strip().lower()
    return "".join(ch for ch in s if ch.isalnum())


def pick_by_tokens(csvrow: dict[str, Any], tokens: frozenset[str]) -> str:
    """First non-empty cell whose header normalizes into ``tokens`` (row key
    order, so a CSV carrying two accepted spellings resolves deterministically).
    ``""`` when no such cell exists."""
    if not isinstance(csvrow, dict):
        return ""
    for key, value in csvrow.items():
        if value in (None, ""):
            continue
        if normalize_header_token(key) in tokens:
            return str(value)
    return ""
