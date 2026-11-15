"""Identity for the ESPN injury feed: ESPN athlete id -> Sleeper id, or a counted refusal.

No new matcher lives here.  It composes the two rungs the injury consumers
already use, both owned elsewhere:

1. **exact ESPN id** -- :class:`src.nfl_data.injury_history.EspnIdResolver`
   (the canonical owner ``src.identity.resolution.resolve_canonical_v2`` called
   with the ESPN id alone; an id two Sleeper players share is REFUSED, never
   resolved to whichever is first).
2. **exact name** -- ``resolve_canonical_v2(name, position, team)``, the same
   ladder ``src.nfl_data.injury_return_evidence`` uses when the id rung misses.
   Only its exact rungs (``Resolution.is_exact``) are accepted: a guarded-fuzzy
   or initial-expansion answer is a guess and is refused
   (``fuzzy_match_refused``), as is any ambiguity.  And a name hit is further
   refused when the directory CONTRADICTS it: the matched Sleeper player already
   carries an ``espn_id`` that is not this entry's
   (``name_match_has_other_espn_id``).  The id rung missed, so the entry's id is
   not the one Sleeper has for that player -- a same-name homonym (a lone
   candidate resolves under ``exact_clean:name`` whatever his team) or a
   same-name player on another team.  An EMPTY directory ``espn_id`` is not a
   contradiction: Sleeper's field is sparse, which is why rung 2 exists.

Why rung 2 exists: Sleeper's own ``espn_id`` is sparsely populated -- on the
2026-09-26 directory only 59 of the 274 players on the 2026-10-26 report resolve
by id alone (22%), the rest are active players whose ``espn_id`` is null.  With
rung 2, 272 of 274 resolve (59 by id, 213 by exact name+team/position) and 2 are
refused (no candidate).  Measured, not assumed; see the PR for the method.  (That
measurement predates the ``name_match_has_other_espn_id`` refusal below; the full
800-row payload is not in the repo to re-run it, so read the 213 name hits as an
upper bound.)

Every entry ends ``resolved`` (with the method named) or refused with a stable
reason that is COUNTED -- never dropped silently and never guessed.  Two ESPN
ids resolving to one Sleeper id are both refused
(``sleeper_id_claimed_by_multiple_espn_ids``): one player cannot be two reports.

:func:`identity_error` is the alarm: too large a refused share means the
directory, the id source or the matcher is broken, not that 40% of the league's
injured players are unknowable.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.nfl_data.injury_feed import InjuryEntry

#: Share of injury entries that may stay unresolved before the run is called
#: broken.  Measured 2 of 274 (0.7%) on the 2026-10-26 report against the
#: 2026-09-26 directory with both rungs; 20% is ~27x that rate -- room for rookies
#: and fresh signings a day-old Sleeper dump has not caught up on -- while a
#: missing directory or a broken id source (~100% unresolved) trips it at once.
#: Below :data:`MIN_ENTRIES_FOR_FRACTION` a ratio is noise.
MAX_UNRESOLVED_FRACTION = 0.20
MIN_ENTRIES_FOR_FRACTION = 20

REASON_NO_DIRECTORY = "no_sleeper_directory"
REASON_ID_SHARED = "espn_id_shared_by_multiple_sleeper_players"
REASON_NO_NAME = "no_name"
REASON_NO_CANDIDATE = "no_candidate"
REASON_AMBIGUOUS = "ambiguous"
REASON_FUZZY_REFUSED = "fuzzy_match_refused"
REASON_NAME_MATCH_OTHER_ESPN_ID = "name_match_has_other_espn_id"
REASON_SLEEPER_CLAIMED_TWICE = "sleeper_id_claimed_by_multiple_espn_ids"


@dataclass
class IdentityReport:
    considered: int = 0
    resolved: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    unresolved_by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def unresolved(self) -> int:
        return self.considered - self.resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "resolved": self.resolved,
            "unresolved": self.unresolved,
            "byMethod": dict(sorted(self.by_method.items())),
            "unresolvedByReason": dict(sorted(self.unresolved_by_reason.items())),
        }


def _resolve_one(entry: InjuryEntry, resolver: Any) -> tuple[str | None, str, str | None]:
    """``(sleeper_id, method, refusal_reason)`` for one entry."""
    by_id = resolver.resolve(entry.espn_athlete_id)
    if by_id.get("status") == "resolved":
        return str(by_id["sleeperId"]), "espn_id", None
    reason = str(by_id.get("reason") or "")
    if reason in (REASON_NO_DIRECTORY, REASON_ID_SHARED):
        return None, "", reason
    # The id is simply absent from the directory: try the exact-name rungs.
    index = getattr(resolver, "index", None)
    if index is None:
        return None, "", REASON_NO_DIRECTORY
    if not entry.full_name:
        return None, "", REASON_NO_NAME
    from src.identity.resolution import resolve_canonical_v2  # noqa: PLC0415
    from src.playerctx.normalize import normalize_team_code  # noqa: PLC0415

    res = resolve_canonical_v2(
        index,
        name=entry.full_name,
        position=entry.position or None,
        team=normalize_team_code(entry.team_abbrev) or None,
    )
    if res.resolved:
        if not res.is_exact:
            return None, "", REASON_FUZZY_REFUSED
        # A name is weaker evidence than an id.  If the directory already pins
        # this Sleeper player to a DIFFERENT ESPN athlete, this entry is someone
        # else who shares the name.  (An empty ``espn_id`` is unknown, not
        # different.)
        other = _espn_id_of(resolver, res.sleeper_id)
        if other and other != entry.espn_athlete_id:
            return None, "", REASON_NAME_MATCH_OTHER_ESPN_ID
        return str(res.sleeper_id), f"name:{res.method.split(':')[0]}", None
    return None, "", str(res.reason or REASON_NO_CANDIDATE)


def _espn_id_of(resolver: Any, sleeper_id: Any) -> str:
    """The resolver's own record of a player's ESPN id (``""`` = none recorded)."""
    return str(resolver.espn_id_of(sleeper_id) or "").strip()


def resolve_entries(
    entries: Sequence[InjuryEntry], *, resolver: Any
) -> tuple[list[InjuryEntry], IdentityReport]:
    """The entries that resolved (each stamped with its ``sleeper_id``), in order,
    plus the report.  ``resolver`` is an ``EspnIdResolver`` (or anything with
    ``resolve(espn_id)``, ``espn_id_of(sleeper_id)`` and an ``index`` attribute)."""
    report = IdentityReport(considered=len(entries))
    methods: Counter[str] = Counter()
    refusals: Counter[str] = Counter()
    staged: list[tuple[InjuryEntry, str]] = []
    for entry in entries:
        sleeper_id, method, reason = _resolve_one(entry, resolver)
        if sleeper_id is None:
            refusals[reason or REASON_NO_CANDIDATE] += 1
            continue
        staged.append((dataclasses.replace(entry, sleeper_id=sleeper_id), method))

    # One player is one report: refuse every entry of a Sleeper id claimed twice.
    claims = Counter(e.sleeper_id for e, _ in staged)
    resolved: list[InjuryEntry] = []
    for entry, method in staged:
        if claims[entry.sleeper_id] > 1:
            refusals[REASON_SLEEPER_CLAIMED_TWICE] += 1
            continue
        methods[method] += 1
        resolved.append(entry)

    report.resolved = len(resolved)
    report.by_method = dict(methods)
    report.unresolved_by_reason = dict(refusals)
    return resolved, report


def identity_error(report: IdentityReport) -> str | None:
    """Why the identity step is unusable, or ``None`` when it is fine.

    Same vocabulary as ``injury_feed.payload_shape_error``: a short stable code
    plus counts.  ``no_entry_resolved`` fires for any non-empty population;
    the fraction rule only over :data:`MIN_ENTRIES_FOR_FRACTION` or more.
    """
    if report.considered == 0:
        return None
    reasons = ",".join(f"{r}:{n}" for r, n in sorted(report.unresolved_by_reason.items()))
    if report.resolved == 0:
        return f"no_entry_resolved:{report.considered},reasons={reasons or 'none'}"
    if (
        report.considered >= MIN_ENTRIES_FOR_FRACTION
        and report.unresolved / report.considered > MAX_UNRESOLVED_FRACTION
    ):
        pct = int(MAX_UNRESOLVED_FRACTION * 100)
        return (
            f"unresolved_above_{pct}pct:{report.unresolved}/{report.considered},"
            f"reasons={reasons or 'none'}"
        )
    return None
