"""External-league FAAB comparability — the one owner.

Scope
─────
This module answers two questions about an observation that came from
**somebody else's league**:

1. *What is this bid worth on our budget scale?* — the percent-of-original
   -budget normalization of ``docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14``
   §3.  A $40 bid in a $200 league is 20%, which is $20 on a $100 scale.
2. *Is this league's waiver market comparable to ours at all?* — §5 and §7.

It owns neither of the numbers it is used to compute.  The objective FAAB
ceiling is decided by ``src/trade/faab_engine.py`` **before** any external
observation is read and is structurally unable to move; everything here feeds
the market layer, which prices how CONTESTED a claim will be.  A hype cycle can
say a claim is expensive.  It can never say the player is worth more.

Why this exists rather than a predicate in the fetch script
──────────────────────────────────────────────────────────
The crowd feed is a ~5-day rolling window that must be ACCUMULATED, so the
persisted ledger outlives any single fetch.  If comparability were decided at
fetch time only, tightening the policy would require throwing the ledger away
and waiting months to rebuild it.  Instead the fetcher stores the league's
FORMAT EVIDENCE and both sides call ``classify`` — the fetcher to avoid storing
rows it already knows are incomparable, the reader to re-apply current policy to
rows stored under an older one.

Measured evidence behind the exclusions (live feed, 2026-08-18, 200 rows / 86
leagues, gated to ``dynasty_main``: 12 teams, superflex, TEP, 2 TE starters):

  admitted by the old superflex+TEP+teams gate   n=106  median 0.65% of budget
    …of which rostersPerPlayer > 1               n= 39  median 0.20%
    …of which total budget < $10                 n=  7  median 0.00% (100% zero)
  single-copy only                               n= 67  median 1.00%

A multi-copy league (MyFantasyLeague's ``rostersPerPlayer`` 2-4: the same
player may sit on several rosters at once) has no waiver scarcity, so its
claims clear near nothing — a 5x drag on the clearing-price estimate, from 37%
of the sample, through a field nothing parsed.  A league whose entire FAAB
budget is $1 cannot express a price at all, only "claimed / did not".

Full record: ``docs/faab-external-market-comparability.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Slot names that prove a league starts INDIVIDUAL defensive players.  A
# ``Def`` / ``DST`` slot is a TEAM defense and proves the opposite — measured,
# every non-offense slot in the live feed is one of those.  Getting this
# backwards would let offense-only leagues price linebackers.
_IDP_SLOT_NAMES = {
    "DL", "DE", "DT", "EDGE", "LB", "ILB", "OLB", "DB", "CB", "S", "SS", "FS",
    "IDP", "IDP_FLEX", "DP", "IL",
}
_TEAM_DEFENSE_SLOT_NAMES = {"DEF", "DST", "D/ST", "D", "TEAM DEF", "TEAMDEF"}

#: Position families this population can only price if it contains IDP leagues.
IDP_POSITION_FAMILIES = {"DL", "LB", "DB"}

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_UNVERIFIED = "unverified"
EXCLUDED = "excluded"

#: Dynasty status of the KTC waiver database is a claim made by the SOURCE (the
#: feed is published at /dynasty/waiver-database), not a per-league fact we can
#: verify from the row: ``dynastyPlatformType`` is 1 on every row measured and
#: identifies the platform, not the format.  Recorded so a consumer can see
#: which kind of evidence it is holding rather than inferring dynasty from a
#: URL fragment.  Spec §5 requires dynasty; this names how it is established.
DYNASTY_PROVENANCE_SOURCE_LEVEL = "source_level_claim:ktc_dynasty_waiver_database"


# ── Budget normalization (spec §3) ─────────────────────────────────


def normalized_bid_share(bid: Any, original_budget: Any) -> float | None:
    """``bid / originalStartingBudget`` as a 0-1 share, or ``None``.

    ``None`` — never 0.0, and never an assumed $100 denominator — when the
    original budget is absent, unparseable or non-positive.  MISSING IS NEVER
    ZERO: a season whose budget we do not know contributes no percentage, it
    does not contribute a percentage of zero.  ``src/trade/faab_history.py``
    already refuses such a season on the own-league side; this is the same rule
    for external evidence.

    A **$0 bid is a real observation** and returns 0.0.  Uncontested claims are
    the modal outcome and dropping them is what made the legacy analytics read
    a quiet wire as a contested one.
    """
    try:
        budget = float(original_budget)
        amount = float(bid)
    except (TypeError, ValueError):
        return None
    if budget <= 0 or amount < 0:
        return None
    return amount / budget


def equivalent_on_budget(share: float | None, target_budget: Any) -> float | None:
    """Express a normalized share on the target league's budget scale.

    ``equivalent_on_budget(0.20, 100)`` → ``20.0`` — i.e. $40 of a $200 budget
    is $20 on the current $100 one.  ``None`` propagates: an unknown share
    cannot be converted, and an unknown target budget has no scale.
    """
    if share is None:
        return None
    try:
        budget = float(target_budget)
    except (TypeError, ValueError):
        return None
    if budget <= 0:
        return None
    return share * budget


# ── Format evidence ────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceFormat:
    """One external league's format, as far as the feed states it.

    Every field is ``None`` when the source did not say.  ``None`` is not
    ``False``: a missing ``qBs`` key does not make a league 1QB, and if the
    vendor renames a key the caller must be able to tell a parse failure from a
    market of 1QB leagues.
    """

    superflex: bool | None = None
    tep_level: int | None = None
    is_2te: bool | None = None
    teams: int | None = None
    rosters_per_player: int | None = None
    has_idp_slots: bool | None = None
    original_budget: float | None = None
    league_id: str = ""

    @property
    def tep(self) -> bool | None:
        """TEP on/off, collapsed from the level.  Kept distinct from
        ``tep_level``: TE+ and TE+++ are both "TEP on" but are not the same
        market, which is why the level is carried separately."""
        if self.tep_level is None:
            return None
        return self.tep_level > 0


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lineup_has_idp(lineup: Any) -> bool | None:
    """Whether the league starts individual defensive players.

    ``None`` when the lineup block is unreadable — an unstated lineup is not a
    statement that the league is offense-only.
    """
    if not isinstance(lineup, dict):
        return None
    positions = lineup.get("position")
    if not isinstance(positions, list) or not positions:
        return None
    seen = False
    for slot in positions:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("name") or "").strip().upper()
        if not name:
            continue
        seen = True
        if name in _IDP_SLOT_NAMES:
            return True
        if name in _TEAM_DEFENSE_SLOT_NAMES:
            continue
    return False if seen else None


def source_format_from_settings(settings: Any) -> SourceFormat:
    """Parse one KTC waiver row's ``settings`` block into format evidence.

    Tolerant of both the raw vendor shape (``qBs`` / ``totalBlindBidWaiverAmount``
    / ``leagueStartingLineup``) and the shape this repo persists
    (``superflex`` / ``budget`` / ``hasIdpSlots``), so a stored row and a freshly
    fetched one classify identically.
    """
    if not isinstance(settings, dict):
        return SourceFormat()

    if "superflex" in settings:
        superflex = settings.get("superflex")
        superflex = None if superflex is None else bool(superflex)
    else:
        qbs = _as_int(settings.get("qBs"))
        superflex = None if qbs is None else qbs >= 2

    tep_level = _as_int(settings.get("tepLevel"))
    if tep_level is None:
        tep_level = _as_int(settings.get("tep"))

    raw_2te = settings.get("is2TE")
    if raw_2te is None:
        raw_2te = settings.get("is2te")
    is_2te = None if raw_2te is None else bool(raw_2te)

    rpp = _as_int(settings.get("rostersPerPlayer"))

    has_idp = settings.get("hasIdpSlots")
    if has_idp is None:
        has_idp = _lineup_has_idp(settings.get("leagueStartingLineup"))
    elif has_idp is not None:
        has_idp = bool(has_idp)

    budget = _as_float(settings.get("originalBudget"))
    if budget is None:
        budget = _as_float(settings.get("budget"))
    if budget is None:
        budget = _as_float(settings.get("totalBlindBidWaiverAmount"))

    return SourceFormat(
        superflex=superflex,
        tep_level=tep_level,
        is_2te=is_2te,
        teams=_as_int(settings.get("teams")),
        rosters_per_player=rpp,
        has_idp_slots=has_idp,
        original_budget=budget,
        league_id=str(settings.get("leagueId") or settings.get("id") or ""),
    )


@dataclass(frozen=True)
class TargetFormat:
    """The league we are trying to price a waiver claim FOR.

    Derived from that league's own canonical settings, never hardcoded to
    Brisket — spec §7 requires comparator relevance to come from the target
    league when the product later serves someone else's dynasty league.
    """

    teams: int = 12
    superflex: bool = False
    tep: bool = False
    is_2te: bool = False
    tep_level: int | None = None
    idp: bool = False
    original_budget: float | None = None
    league_key: str = ""

    @classmethod
    def from_roster_settings(
        cls,
        settings: dict[str, Any] | None,
        *,
        league_key: str = "",
        scoring_profile: str = "",
        idp_enabled: bool | None = None,
        original_budget: float | None = None,
    ) -> "TargetFormat":
        settings = settings or {}
        starters = settings.get("starters") or {}
        te_starters = _as_int(starters.get("TE")) or 0
        superflex = bool(starters.get("SFLEX") or starters.get("SUPER_FLEX"))
        # TEP is a SCORING property, so it is read from the scoring profile
        # label; the starter block only says how many TEs must start.  Both are
        # kept because they answer different questions (§7 names them
        # separately: "TE premium AND two mandatory TE starters").
        tep = "tep" in str(scoring_profile or "").lower() or te_starters >= 2
        idp = bool(
            idp_enabled
            if idp_enabled is not None
            else any(_as_int(starters.get(k)) for k in ("DL", "LB", "DB", "IDP_FLEX"))
        )
        return cls(
            teams=_as_int(settings.get("teamCount")) or 12,
            superflex=superflex,
            tep=tep,
            is_2te=te_starters >= 2,
            tep_level=None,
            idp=idp,
            original_budget=original_budget,
            league_key=str(league_key or ""),
        )

    @classmethod
    def from_registry(cls, league_key: str) -> "TargetFormat":
        """Read the target league out of the canonical registry."""
        from src.api import league_registry  # noqa: PLC0415 — optional at import time

        cfg = league_registry.get_league_by_key(league_key)
        return cls.from_roster_settings(
            league_registry.get_league_roster_settings(league_key),
            league_key=league_key,
            scoring_profile=getattr(cfg, "scoring_profile", "") or "",
            idp_enabled=getattr(cfg, "idp_enabled", None),
        )


# ── Policy ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ComparabilityPolicy:
    """Thresholds, all config-supplied.

    Defaults are kept equal to ``config/trade/faab.json::crowdComparability``
    and ``tests/trade/test_faab_config_parity.py`` fails if they drift — the
    same treatment the engine's own fallbacks get.
    """

    min_original_budget: float = 10.0
    team_count_tolerance: int = 2
    tep_severity_gap: int = 2
    allow_multi_copy_leagues: bool = False
    max_file_age_days: float = 7.0
    min_claims_for_tier: int = 3

    @classmethod
    def from_config(cls, config: Any = None) -> "ComparabilityPolicy":
        """Build from a ``FaabConfig``-like object or a plain dict."""
        if config is None:
            return cls()
        if hasattr(config, "num"):
            return cls(
                min_original_budget=config.num("crowdComparability", "minOriginalBudget", 10.0),
                team_count_tolerance=int(
                    config.num("crowdComparability", "teamCountTolerance", 2)
                ),
                tep_severity_gap=int(config.num("crowdComparability", "tepSeverityGap", 2)),
                allow_multi_copy_leagues=bool(
                    config.get("crowdComparability", "allowMultiCopyLeagues", False)
                ),
                max_file_age_days=config.num("crowdComparability", "maxFileAgeDays", 7.0),
                min_claims_for_tier=int(config.num("crowdComparability", "minClaimsForTier", 3)),
            )
        raw = config if isinstance(config, dict) else {}
        block = raw.get("crowdComparability") if "crowdComparability" in raw else raw
        block = block if isinstance(block, dict) else {}
        base = cls()
        return cls(
            min_original_budget=_as_float(block.get("minOriginalBudget"))
            or base.min_original_budget,
            team_count_tolerance=_as_int(block.get("teamCountTolerance"))
            if block.get("teamCountTolerance") is not None
            else base.team_count_tolerance,
            tep_severity_gap=_as_int(block.get("tepSeverityGap"))
            if block.get("tepSeverityGap") is not None
            else base.tep_severity_gap,
            allow_multi_copy_leagues=bool(
                block.get("allowMultiCopyLeagues", base.allow_multi_copy_leagues)
            ),
            max_file_age_days=_as_float(block.get("maxFileAgeDays")) or base.max_file_age_days,
            min_claims_for_tier=_as_int(block.get("minClaimsForTier"))
            if block.get("minClaimsForTier") is not None
            else base.min_claims_for_tier,
        )


@dataclass(frozen=True)
class Comparability:
    """The verdict on one external observation."""

    tier: str
    excluded: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "excluded": self.excluded, "reasons": list(self.reasons)}


def classify(
    source: SourceFormat,
    target: TargetFormat,
    *,
    policy: ComparabilityPolicy | None = None,
) -> Comparability:
    """Is this external league's waiver price meaningful for the target?

    Hard exclusions FAIL CLOSED — a format we cannot read is excluded rather
    than assumed to match, per spec §5 ("Unknown dynasty status is not
    permission to assume dynasty").  Soft mismatches DEMOTE A TIER and change
    no number: the owner spec says tier weights are evidence-gated, and there is
    no outcome data to fit them yet, so the tier is reported for the future
    empirical validation and for the explanation surface.
    """
    pol = policy or ComparabilityPolicy()
    hard: list[str] = []

    # Budget — the denominator of every normalized share.
    if source.original_budget is None or source.original_budget <= 0:
        hard.append("budget_unknown")
    elif source.original_budget < pol.min_original_budget:
        # A league whose entire FAAB is a couple of dollars cannot express a
        # price, only "claimed / did not".  Measured: 7 such rows, every one
        # 0.00% of budget.
        hard.append("degenerate_budget")

    # Roster exclusivity.  Multi-copy leagues have no waiver scarcity and
    # clear ~5x cheaper; an unstated value is not evidence of exclusivity.
    if not pol.allow_multi_copy_leagues:
        if source.rosters_per_player is None:
            hard.append("roster_exclusivity_unknown")
        elif source.rosters_per_player > 1:
            hard.append("multi_copy_league")

    # Superflex — the single biggest driver of QB waiver demand.
    if source.superflex is None:
        hard.append("superflex_unknown")
    elif bool(source.superflex) != bool(target.superflex):
        hard.append("superflex_mismatch")

    # TE premium, on/off.
    if source.tep is None:
        hard.append("tep_unknown")
    elif bool(source.tep) != bool(target.tep):
        hard.append("tep_mismatch")

    # Team count — how many rivals split the same finite pool.
    if source.teams is None:
        hard.append("team_count_unknown")
    elif abs(int(source.teams) - int(target.teams)) > pol.team_count_tolerance:
        hard.append("team_count_mismatch")

    if hard:
        return Comparability(tier=EXCLUDED, excluded=True, reasons=tuple(hard))

    soft: list[str] = []
    if source.is_2te is None:
        soft.append("two_te_unknown")
    elif bool(source.is_2te) != bool(target.is_2te):
        soft.append("two_te_mismatch")

    if (
        target.tep_level is not None
        and source.tep_level is not None
        and abs(int(source.tep_level) - int(target.tep_level)) >= pol.tep_severity_gap
    ):
        soft.append("tep_severity_gap")

    if source.teams is not None and int(source.teams) != int(target.teams):
        soft.append("team_count_offset")

    if not soft:
        tier = TIER_A
    elif len(soft) == 1:
        tier = TIER_B
    else:
        tier = TIER_C
    return Comparability(tier=tier, excluded=False, reasons=tuple(soft))


# ── Population capability (spec §7) ────────────────────────────────


def is_idp_position(position: Any) -> bool:
    """Whether this position needs IDP-league evidence to be priced."""
    from src.utils.name_clean import normalize_position_family  # noqa: PLC0415

    if not position:
        return False
    return normalize_position_family(str(position)) in IDP_POSITION_FAMILIES


def population_prices_position(position: Any, *, any_idp_source: bool) -> bool:
    """Can this crowd population legitimately price a claim at ``position``?

    Measured on the live feed: **zero** of 86 leagues start an individual
    defensive player (every non-offense slot observed is a team ``Def``).  So a
    median drawn from that population is offense-only evidence, and spec §7
    forbids using it for an IDP asset.  Derived from what the retained rows
    actually contain rather than hardcoded, so it self-corrects the day KTC
    carries an IDP league.
    """
    if not is_idp_position(position):
        return True
    return bool(any_idp_source)
