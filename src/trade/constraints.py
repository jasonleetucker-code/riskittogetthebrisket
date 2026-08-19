"""Recommendation constraints — the ONE owner (C3-CON-01 / V1-130).

What this answers
─────────────────
"May this asset be put on the OUTGOING side of a trade this system is
recommending?" — and, for temporary refinement, "must it be?".

Binding spec: ``docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md``
§2-§4 and §6.  Owner rows 1.5 / 2.10 / 2.11.  Scope note from the V1 completion
contract: **the OWNER is V1-required; the wider constraint feature set is not.**
So this module resolves and applies constraints.  It does not build the UI, the
promote-to-permanent action, or the refinement-context lifecycle.

A constraint is NOT a valuation rule
────────────────────────────────────
This is the distinction the spec spends its §2.2 on, and it is the one a future
change is most likely to break.  A protected player:

* keeps his ordinary canonical value — nothing here reads or writes
  ``rankDerivedValue``;
* stays a valid INCOMING acquisition target;
* is unaffected for a different user, or the same user in a different league;
* is still fully analysable in the manual Trade Calculator, which is
  free-form what-if and deliberately unconstrained.

Only *automatically generated recommendations* are constrained, and only on the
side the user is giving away.

Applied DURING generation
─────────────────────────
§6 is explicit: reject forbidden state and generate only feasible packages —
never "generate everything, then hide the forbidden ones", which wastes the
search budget and can return the wrong *best* result because the real best was
filtered out after ranking.  So this produces predicates the canonical
substrate (``src/packages``) consumes as eligibility, not a post-filter.

Fail-closed, and what that means precisely
──────────────────────────────────────────
Two different unknowns, both resolved AGAINST proposing a trade:

* **The constraint set could not be resolved at all** (store unreadable, user
  unknown).  ``resolution_failed`` is set and ``may_send`` answers ``False``
  for everything.  A recommender must then return an honest no-result rather
  than an unconstrained list — "we could not check your untouchables" and "you
  have none" must never render the same.
* **A player's NFL team is unknown** while NFL-team protection is active.  He
  is treated as PROTECTED.  Measured on the 2026-08-18 board: 4 non-pick
  players carry no ``team``.  The alternative — assuming he is not on the
  protected team — is a fabricated fact in the direction that proposes trading
  someone the user told us not to trade.

Draft picks are never NFL-team-protected: a pick has no NFL team, and treating
its absent ``team`` as unknown-therefore-protected would block every pick from
every generated package. Individual protection still applies to a pick if a
user names one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "ConstraintResolutionError",
    "TradeConstraints",
    "constraint_key",
    "resolve_constraints",
]


def constraint_key(value: Any) -> str:
    """Identity a constraint is expressed in: normalised display name.

    Deliberately the NAME rather than a Sleeper id.  A user marks "Justin
    Jefferson" untouchable; the rule has to survive that player appearing in a
    roster list, a board row and a generated package, which carry different id
    fields and sometimes none.  Where a caller has a canonical id it may key on
    that too — :meth:`TradeConstraints.may_send` checks every key it is given.
    """

    return str(value or "").strip().lower()


class ConstraintResolutionError(RuntimeError):
    """Raised only by callers that want resolution failure to be loud.

    :func:`resolve_constraints` itself never raises — it returns a fail-closed
    :class:`TradeConstraints`, because a recommender degrading to "no results,
    and here is why" is better than one degrading to a traceback.
    """


@dataclass(frozen=True)
class TradeConstraints:
    """The resolved answer for one (user, league, refinement context)."""

    #: Persistent individual protections, by :func:`constraint_key`.
    protected_outgoing: frozenset[str] = frozenset()
    #: NFL team abbreviations protected on the outgoing side (e.g. ``{"MIN"}``).
    protected_nfl_teams: frozenset[str] = frozenset()
    #: Temporary EXCLUDE — must not appear outgoing in the next regeneration.
    excluded_outgoing: frozenset[str] = frozenset()
    #: Temporary LOCK — must appear outgoing in the next regeneration.
    locked_outgoing: frozenset[str] = frozenset()
    #: True when the constraint set could not be established.  Everything is
    #: refused while this is set; see the module docstring.
    resolution_failed: bool = False
    #: Machine-readable reasons, for a caller rendering an honest no-result.
    notes: tuple[str, ...] = ()
    #: ``constraint_key -> NFL team``, for dynamic team-rule resolution.
    _team_by_key: Mapping[str, str] = field(default_factory=dict, repr=False)

    @property
    def active(self) -> bool:
        """Whether anything at all constrains generation."""

        return bool(
            self.resolution_failed
            or self.protected_outgoing
            or self.protected_nfl_teams
            or self.excluded_outgoing
            or self.locked_outgoing
        )

    def _keys_for(self, asset: Any) -> tuple[frozenset[str], bool, str | None]:
        """``(identity keys, is_pick, nfl_team)`` for one asset."""

        if isinstance(asset, Mapping):
            names = (asset.get("name"), asset.get("displayName"), asset.get("canonicalName"))
            ids = (asset.get("assetId"), asset.get("playerId"), asset.get("player_id"))
            position = asset.get("position") or asset.get("pos") or asset.get("basePos")
            asset_class = asset.get("assetClass")
            team = asset.get("team") or asset.get("nflTeam")
        else:
            names = (
                getattr(asset, "name", None),
                getattr(asset, "canonical_name", None),
            )
            ids = (getattr(asset, "asset_id", None), getattr(asset, "player_id", None))
            position = getattr(asset, "position", None)
            asset_class = getattr(asset, "asset_class", None)
            team = getattr(asset, "team", None) or getattr(asset, "nfl_team", None)

        keys = frozenset(k for k in (constraint_key(v) for v in (*names, *ids)) if k)
        is_pick = str(position or "").strip().upper() == "PICK" or (
            str(asset_class or "").strip().lower() == "pick"
        )
        resolved_team = str(team or "").strip().upper() or None
        if resolved_team is None:
            # Fall back to the board-derived index, so a caller's asset object
            # that carries no team still resolves the RULE dynamically rather
            # than being judged on what it happens to expose.
            for key in keys:
                found = self._team_by_key.get(key)
                if found:
                    resolved_team = found
                    break
        return keys, is_pick, resolved_team

    def may_send(self, asset: Any) -> bool:
        """May this asset be placed on the OUTGOING side of a recommendation?"""

        return self.block_reason(asset) is None

    def block_reason(self, asset: Any) -> str | None:
        """Why this asset may not be sent, or ``None`` if it may.

        The reason is returned rather than a bare bool so a surface can say
        *"withheld: you protect MIN players"* instead of silently returning a
        shorter list — the same posture roster capacity takes.
        """

        if self.resolution_failed:
            return "constraints_unresolved"

        keys, is_pick, team = self._keys_for(asset)
        if keys & self.protected_outgoing:
            return "protected_individual"
        if keys & self.excluded_outgoing:
            return "excluded_temporary"
        if self.protected_nfl_teams and not is_pick:
            if team is None:
                # UNKNOWN team while a team rule is active: fail closed.
                return "protected_nfl_team_unknown"
            if team in self.protected_nfl_teams:
                return "protected_nfl_team"
        return None

    def required_outgoing(self) -> frozenset[str]:
        """Keys a regenerated package MUST include on the outgoing side (LOCK)."""

        return self.locked_outgoing

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "resolutionFailed": self.resolution_failed,
            "protectedOutgoing": sorted(self.protected_outgoing),
            "protectedNflTeams": sorted(self.protected_nfl_teams),
            "excludedOutgoing": sorted(self.excluded_outgoing),
            "lockedOutgoing": sorted(self.locked_outgoing),
            "notes": list(self.notes),
        }


#: The fail-closed constant.  Everything is refused.
UNRESOLVED = TradeConstraints(
    resolution_failed=True,
    notes=("recommendation constraints could not be resolved",),
)


def _team_index(contract: Mapping[str, Any] | None) -> dict[str, str]:
    """``constraint_key -> NFL team`` from the canonical board.

    Team identity is read from the board every time rather than stored with the
    rule, which is what makes §2.2's dynamic requirement hold: a player who
    joins the protected team becomes protected, and one who leaves stops being
    protected by the TEAM rule, with no stored state to migrate.
    """

    rows = (contract or {}).get("playersArray") if isinstance(contract, Mapping) else None
    out: dict[str, str] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        team = str(row.get("team") or "").strip().upper()
        if not team:
            continue
        for candidate in (row.get("displayName"), row.get("canonicalName"), row.get("playerId")):
            key = constraint_key(candidate)
            if key:
                out.setdefault(key, team)
    return out


def _as_key_set(values: Iterable[Any] | None) -> frozenset[str]:
    return frozenset(k for k in (constraint_key(v) for v in (values or ())) if k)


def resolve_constraints(
    *,
    contract: Mapping[str, Any] | None = None,
    persistent: Mapping[str, Any] | None = None,
    refinement: Mapping[str, Any] | None = None,
) -> TradeConstraints:
    """Resolve one (user, league, refinement context) into constraints.

    ``persistent`` is the stored per-(user, league) protection block; the
    storage service that produces it is outside V1-130's owner scope, so this
    takes it as data rather than reaching for it.  ``None`` means *no
    protections configured*, which is a legitimate answer and NOT a failure —
    failure is when the caller could not determine it, and the caller signals
    that by passing :data:`UNRESOLVED` along instead of calling this.

    Never raises.  §6 step 4 says "reject contradictory/forbidden state", and
    the rejection here is a fail-closed result with a note.
    """

    notes: list[str] = []

    protected = _as_key_set((persistent or {}).get("untouchables"))
    teams = frozenset(
        t for t in (str(x).strip().upper() for x in ((persistent or {}).get("nflTeams") or [])) if t
    )
    locked = _as_key_set((refinement or {}).get("lock"))
    excluded = _as_key_set((refinement or {}).get("exclude"))

    # §3.3 — LOCK and EXCLUDE are mutually exclusive for the same player.
    both = locked & excluded
    if both:
        # Contradictory state.  Resolve toward NOT proposing him: an EXCLUDE the
        # user set is a refusal, and honouring the LOCK instead would force a
        # player into a package the user just said to keep out of it.
        locked -= both
        notes.append(
            f"{len(both)} player(s) had LOCK and EXCLUDE set at once; EXCLUDE wins and the "
            "LOCK was dropped"
        )

    # §3.3 — persistent protection outranks temporary refinement.  A LOCK
    # cannot force a protected player into a recommendation.
    forced = locked & protected
    if forced:
        locked -= forced
        notes.append(
            f"{len(forced)} LOCK(ed) player(s) are persistently protected; the protection "
            "outranks the temporary lock"
        )

    return TradeConstraints(
        protected_outgoing=protected,
        protected_nfl_teams=teams,
        excluded_outgoing=excluded,
        locked_outgoing=locked,
        resolution_failed=False,
        notes=tuple(notes),
        _team_by_key=_team_index(contract) if teams else {},
    )


def partition_sendable(
    assets: Sequence[Any],
    constraints: TradeConstraints | None,
) -> tuple[list[Any], list[tuple[Any, str]]]:
    """Split an outgoing pool into ``(sendable, [(asset, reason), ...])``.

    The blocked half is RETURNED rather than dropped so a caller can say why a
    list is short.  Consumers apply this to the pool BEFORE enumeration — §6.
    """

    if constraints is None or not constraints.active:
        return list(assets), []
    sendable: list[Any] = []
    blocked: list[tuple[Any, str]] = []
    for asset in assets:
        reason = constraints.block_reason(asset)
        if reason is None:
            sendable.append(asset)
        else:
            blocked.append((asset, reason))
    return sendable, blocked
