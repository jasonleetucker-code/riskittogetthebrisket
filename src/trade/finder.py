"""
Trade Finder Engine
===================
Finds trades where:
  - Our model values favor my side (I receive more board value than I give)
  - KTC values show the opponent WINNING on market numbers (strictly positive gain)
  - The result is "board arbitrage" — good for me on our numbers,
    clearly appealing to them on market numbers.

Works against the live production data payload (players dict with
_rawComposite / _canonicalSiteValues fields).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from src.utils.name_clean import normalize_position as _norm_pos  # noqa: F401 — re-exported via _norm_pos shim below for back-compat
from src.utils.pick_labels import pick_anchor_key, resolve_pick_name

# ── Thresholds ──────────────────────────────────────────────────────────
#
# WS-J F-6 / audit finding K — RE-DERIVED 2026-07-27 when this engine
# moved off the raw scraper composite onto ``rankDerivedValue``.
#
# These were tuned against composite-scale numbers.  Porting them
# unchanged would have silently tightened every absolute gate, because
# the board sits BELOW the composite: measured over the 803 assets
# carrying both values on one held-constant payload, the median
# board/composite ratio is k = 0.875 (p10 0.775, p90 1.056).  A gate
# left at 800 would therefore admit ~14% fewer assets than it used to,
# which is a silent behaviour change wearing a "no code change" costume.
#
# Method: scale by the measured k, then round.  Percentile-matching was
# tried first and REJECTED — it is degenerate at the low end here.
# MIN_ASSET_VALUE=800 sits at the 99.25th percentile of the paired pool
# and JUNK_THRESHOLD=400 at the 100th, so matching percentiles maps both
# onto ~900 and collapses two gates that exist to do different jobs.
# It also conflates the scale change with a population change: the
# composite prices 1077 assets and the board 812.
#
# ``MIN_MARKET_VALUE`` is deliberately NOT rescaled.  It gates retail
# market values (KTC / IDPTradeCalc), which this migration does not
# touch.  Scaling it would have been the easy mistake.
MIN_ASSET_VALUE = 700  # was 800 on the composite scale
MIN_MARKET_VALUE = 500  # UNCHANGED — gates market values, not board values
MIN_KTC_VALUE = MIN_MARKET_VALUE  # Deprecated alias
MAX_BOARD_LOSS = -175  # was -200
MAX_RESULTS = 40  # Cap returned results
JUNK_THRESHOLD = 350  # was 400
MULTI_FOR_ONE_MIN_RATIO = 0.55  # 2-for-1 give side must be >= 55% of receive model value

# The measured level offset between the two value scales, kept as a
# named constant so the threshold derivation above is reproducible
# rather than a set of magic numbers.  Regenerate with
# ``scripts/measure_engine_value_divergence.py``.
BOARD_TO_COMPOSITE_K = 0.875

# ``MIN_ASSET_VALUE`` expressed back on the COMPOSITE scale (800 —
# the pre-migration value, recovered by inverting k).  Needed because
# one filter necessarily runs on composite-scale numbers: counting the
# assets the board declined to price means looking at rows that have
# NO board value, so their only value is the composite one.  Gating
# those with the board-scale 700 compared two different scales and
# over-counted (202 vs 189 on the live payload) — see the
# ``assetsUnpricedByBoard`` note in ``find_trades``.
_MIN_ASSET_VALUE_COMPOSITE_SCALE = round(MIN_ASSET_VALUE / BOARD_TO_COMPOSITE_K)

# Single-source haircut for the LEGACY composite path only.
#
# It existed because ``_SINGLE_SOURCE_VALUE_RETENTION`` (0.30) is applied
# to ``rankDerivedValue`` and never reached the composite this engine
# used to read — so without it, single-source assets were undiscounted
# here.  An earlier reading of F-6 called the two a stacked double
# haircut and proposed deleting this constant; that was wrong, and
# deleting it then would have introduced a live distortion via a "fix".
#
# On the migrated path it is genuinely redundant: the retention arrives
# baked into the board value.  So it is retained ONLY for the fallback
# branch and named to say so.  ``SINGLE_SOURCE_DISCOUNT`` remains as a
# deprecated alias for the pinning test.
_LEGACY_SINGLE_SOURCE_DISCOUNT = 0.88
SINGLE_SOURCE_DISCOUNT = _LEGACY_SINGLE_SOURCE_DISCOUNT  # deprecated alias

# ── Market quality gates ───────────────────────────────────────────────
EXCLUDED_POSITIONS = {"K", "PK", "DST", "DEF"}  # No real market support
PARTIAL_MARKET_ARBITRAGE_CAP = 8.0  # Hard ceiling on partial-coverage arbitrage score

# ``PARTIAL_MARKET_MAX_RANK`` used to live here.  It was already dead:
# WS-J F-7 collapsed the if/else that consulted it (both branches
# computed ``full + partial``), leaving the constant exported but never
# read.  An exported constant nothing reads is a promise the code does
# not keep, so it is removed rather than left as scenery.
# ``MAX_PACKAGE_SIZE`` is removed for the same reason: package shapes
# are fixed by ``_generate_1for1`` / ``_generate_2for1`` /
# ``_generate_1for2`` and bounded by a literal ``[:30]`` slice, never by
# that constant.

# Deprecated alias — kept so external callers/tests importing the old
# name keep working.  Remove once no caller references it.
PARTIAL_KTC_ARBITRAGE_CAP = PARTIAL_MARKET_ARBITRAGE_CAP

# ── Per-market quality gate ────────────────────────────────────────────
# Hard filter: only assets ranked inside the top-N **of their own
# market** are eligible.  Set to 0 to disable.
#
# WS-J F-3: this used to rank every asset against KTC and keep the top
# N.  KTC publishes no IDP players at all — I verified that none of
# Hutchinson / Parsons / Garrett / Carter / Verse / Campbell appear on
# its 500-row board — so every defender scored ``ktc_value = None`` and
# was silently dropped.  In a league with nine IDP starters the engine
# returned offense-only results and reported ``ktcTopNFilter: 150`` as
# though a uniform gate had run.
#
# The fix anchors each asset on the market its counterparty would
# actually consult and ranks it against that market's own population:
#
#   offense + picks → ``ktcSfTep`` (fallback legacy ``ktc``)
#   IDP             → ``idpTradeCalc``
#
# This mirrors ``angle.py::_market_source_for``, which has routed
# per-player market values correctly since it was written.
#
# Summing the two markets in the opponent-appeal arithmetic is sound:
# IDPTradeCalc is a full-roster calculator publishing offense, IDP and
# picks on ONE native 0-9999 scale, and its offensive half is
# empirically interchangeable with KTC's — of KTC's 500 rows, 475 also
# appear on the IDPTC board with a median value ratio of 1.000
# (p10 0.888, p90 1.054, measured 2026-07-26).  Both boards top out at
# 9999, so there is no rescaling to apply between them.
MARKET_TOP_N_FILTER = 150

# Deprecated alias — the gate is per-market now, not KTC-only.
KTC_TOP_N_FILTER = MARKET_TOP_N_FILTER

# Canonical site keys per market, in preference order.
OFFENSE_MARKET_KEYS = ("ktcSfTep", "ktc")
IDP_MARKET_KEYS = ("idpTradeCalc",)

# ── Hardening-pass thresholds ────────────────────────────────────────────
ELITE_THRESHOLD = 6600  # was 7500 on the composite scale; see the F-6 note above
ELITE_MULTI_MIN_RATIO = 0.65  # Tighter ratio for elite targets in multi-for-one
PACKAGE_ANCHOR_MIN_PCT = 0.35  # Best give piece must be ≥35% of best receive piece
CONFIDENCE_SOURCE_BASELINE = 5  # Expected source count for full confidence

# Max returned trades any single give-side asset may appear in.
#
# The sibling engine already learned this: ``suggestions.py`` carries
# ``MAX_GIVE_PLAYER_APPEARANCES = 2`` ("Breece Hall fatigue — seeing the
# same outgoing player 7 times"), lowered from 3 after an audit found
# 52.5% of its suggestions repetitive.  This engine had no such cap and
# no dominance test, so 40 returned trades for one team were built from
# 4 distinct give-side assets, one of which appeared in 20 of them
# (W09-F012).  That is 40 variations of 4 ideas, not 40 ideas.
#
# 3 rather than suggestions.py's 2 because this list is longer (40 in
# one bucket against 8 per category over 4 categories) and because a
# genuinely mispriced asset SHOULD show up more than once — the cap
# exists to stop a single asset owning the list, not to hide it.  It is
# a soft cap: if honouring it would return a short list, the skipped
# trades are appended in rank order rather than withheld.
MAX_GIVE_ASSET_APPEARANCES = 3
ROSTER_SURPLUS_THRESHOLD = 4  # ≥4 at a position = surplus (light fit bonus)
ROSTER_WEAK_THRESHOLD = 1  # ≤1 at a position = weakness (light fit bonus)

IDP_POSITIONS = {"DL", "LB", "DB"}


@dataclass
class Asset:
    """A tradeable asset with our model value and its retail market value.

    ``market_value`` is the value the counterparty would see on the
    board they actually consult: KTC for offense and picks, IDPTradeCalc
    for IDP.  ``market_source`` records which board was read so the UI
    and the metadata can be honest about it.
    """

    name: str
    position: str
    team: str
    model_value: int  # Our board's value
    market_value: int | None  # Retail market value (None = no coverage)
    is_pick: bool = False
    source_count: int = 0  # Number of valuation sources
    market_rank: int | None = None  # 1-based rank WITHIN this asset's market
    offense_only_model_value: int | None = None  # model_value excluding IDP sources
    market_source: str | None = None  # "ktcSfTep" | "ktc" | "idpTradeCalc"

    @property
    def has_market(self) -> bool:
        return self.market_value is not None and self.market_value > 0

    # ── Deprecated aliases ───────────────────────────────────────────
    # Pre-WS-J these were named ``ktc_*`` even for IDP assets, which was
    # only ever accurate because IDP assets never survived the gate.
    @property
    def ktc_value(self) -> int | None:
        return self.market_value

    @property
    def ktc_rank(self) -> int | None:
        return self.market_rank

    @property
    def has_ktc(self) -> bool:
        return self.has_market


# Local ``_norm_pos`` was a thin wrapper around ``POSITION_ALIASES``;
# it's now imported directly from ``src.utils.name_clean`` (alias
# ``_norm_pos``) so every trade engine uses the same null-tolerant
# normalization.  Audit S2.


@dataclass
class TradeCandidate:
    """A scored trade proposal."""

    give: list[Asset]
    receive: list[Asset]
    give_model_total: int = 0
    receive_model_total: int = 0
    give_ktc_total: int = 0
    receive_ktc_total: int = 0
    board_delta: int = 0  # positive = good for me on our board
    ktc_delta: int = 0  # positive = opponent gives more KTC than they get
    opponent_ktc_appeal: float = 0.0  # how favorable for opponent on KTC (positive = they like it)
    arbitrage_score: float = 0.0  # composite ranking score
    ktc_coverage: str = "full"  # full / partial / none
    confidence_score: float = 1.0  # 0-1, source coverage × KTC coverage

    # ── Explainability fields ────────────────────────────────────────────
    confidence_tier: str = "high"  # "high" / "moderate" / "low"
    edge_label: str = ""  # "Strong Edge" / "Moderate Edge" / "Slight Edge"
    summary: str = ""  # Human-readable one-liner
    ranking_factors: dict = field(default_factory=dict)  # Score component breakdown
    flags: list[str] = field(default_factory=list)  # Active guards/bonuses

    def package_shape(self) -> str:
        """"1-for-2", "1-for-1", … — the shape a manager actually proposes.

        One definition, used by ``to_dict``'s ``packageSize`` and by the
        shape-balanced fill in :func:`find_trades`.
        """
        return f"{len(self.give)}-for-{len(self.receive)}"

    def markets_used(self) -> list[str]:
        """Which retail markets priced the assets in this trade.

        ``ktc`` and ``ktcSfTep`` are the same publisher's board and
        collapse to one entry; ``idpTradeCalc`` is a different one.
        """
        seen: set[str] = set()
        for a in (*self.give, *self.receive):
            if not a.market_source:
                continue
            seen.add("idpTradeCalc" if a.market_source in IDP_MARKET_KEYS else "ktc")
        return sorted(seen)

    def to_dict(self) -> dict[str, Any]:
        def _asset_dict(a: Asset) -> dict[str, Any]:
            # ONE CONCEPT, ONE NAME (W29-F001).  ``modelValue`` is always
            # the canonical board value — ``/arbitrage`` renders it under
            # the literal label "board", and ``boardDelta`` is summed
            # from it.  It used to be silently replaced by
            # ``offense_only_model_value`` (a different board) on any
            # trade with no IDP leg, with the real board value shunted
            # into ``modelValueFull`` — so the number labelled "board"
            # was not the board, and the lens could not move it.
            d: dict[str, Any] = {
                "name": a.name,
                "position": a.position,
                "team": a.team,
                "modelValue": a.model_value,
                "ktcValue": a.ktc_value,
                "ktcRank": a.ktc_rank,
            }
            if a.offense_only_model_value is not None:
                # The IDP-disabled board, for comparison only.
                d["offenseOnlyModelValue"] = a.offense_only_model_value
            return d

        return {
            "give": [_asset_dict(a) for a in self.give],
            "receive": [_asset_dict(a) for a in self.receive],
            "giveModelTotal": self.give_model_total,
            "receiveModelTotal": self.receive_model_total,
            "giveKtcTotal": self.give_ktc_total,
            "receiveKtcTotal": self.receive_ktc_total,
            "boardDelta": self.board_delta,
            "ktcDelta": self.ktc_delta,
            "opponentKtcAppeal": round(self.opponent_ktc_appeal, 3),
            "arbitrageScore": round(self.arbitrage_score, 2),
            "ktcCoverage": self.ktc_coverage,
            # T4-2: which markets this trade's delta actually spans.
            #
            # ``ktcDelta`` sums ``ktcValue`` across every asset, and the
            # per-market gate prices offense and picks on KTC but IDP on
            # IDPTradeCalc.  A mixed trade's delta therefore adds two
            # publishers' numbers together, and nothing in the payload
            # said so.
            #
            # The sum is defensible — the two boards are directly
            # comparable, both topping out at 9999, with a median
            # cross-board value ratio of 1.000 measured over the 475
            # players they share (CLAUDE.md, 2026-07-26).  But the p10-p90
            # is 0.888-1.054, so per-player disagreement of +/-10% is
            # normal, and a mixed-market delta smaller than that is not
            # distinguishable from the two boards simply disagreeing.
            # A reader cannot apply that caveat without knowing it
            # applies.
            "marketsUsed": self.markets_used(),
            "mixedMarket": len(self.markets_used()) > 1,
            "confidenceScore": round(self.confidence_score, 2),
            "confidenceTier": self.confidence_tier,
            "edgeLabel": self.edge_label,
            "summary": self.summary,
            "rankingFactors": self.ranking_factors,
            "flags": list(self.flags),
            "packageSize": self.package_shape(),
        }


# ── Explainability helpers ────────────────────────────────────────────────


def _confidence_tier(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "moderate"
    return "low"


def _edge_label(board_gain_pct: float) -> str:
    if board_gain_pct >= 0.25:
        return "Strong Edge"
    if board_gain_pct >= 0.10:
        return "Moderate Edge"
    return "Slight Edge"


def _opp_appeal_phrase(appeal: float) -> str:
    if appeal > 0:
        return f"opponent gains {appeal:.0%} on KTC"
    return f"opponent gives up {abs(appeal):.0%} on KTC"


def _build_summary(
    board_delta: int,
    board_gain_pct: float,
    opp_appeal: float,
    coverage: str,
    confidence_tier: str,
    edge_label: str,
    pkg_size_str: str,
) -> str:
    # The verb and the sign both follow the number.  This used to read
    # "you gain {delta} (+{pct})" unconditionally, so a -100 delta
    # rendered as "you gain -100 board value (+-2%)".
    verb = "you gain" if board_delta >= 0 else "you give up"
    # The percentage names its own denominator.  It is the delta over
    # the LARGER side (W09-F002); an unlabelled percentage next to an
    # absolute delta reads as "of what you gave up", which is what it
    # used to be and no longer is.
    parts = [
        f"{edge_label}: {verb} {abs(board_delta):,} board value "
        f"({board_gain_pct:+.0%} of the larger side)",
    ]
    # Only claim KTC opponent appeal when coverage is full
    if coverage == "full":
        parts.append(_opp_appeal_phrase(opp_appeal))
    elif coverage == "partial":
        parts.append("partial KTC — opponent view estimated only")
    else:
        parts.append("no KTC data — opponent view unavailable")
    parts.append(f"{confidence_tier} confidence")
    return ". ".join(parts) + f". ({pkg_size_str})"


def board_values_from_contract(contract: dict[str, Any]) -> dict[str, int]:
    """Map ``legacyRef``/``canonicalName`` → ``rankDerivedValue``.

    The canonical board — the same values ``/rankings`` shows and every
    other trade engine reads (``suggestions.py``, ``angle.py``,
    ``waiver.py``, ``monte_carlo.py``).

    Keyed on both ``legacyRef`` and ``canonicalName`` because the
    ``players`` dict this pool is built from is keyed by the legacy
    scraper name, which is not always the canonical one.
    """
    out: dict[str, int] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        value = _int_or_none(row.get("rankDerivedValue"))
        if value is None or value < 1:
            continue
        for key in ("legacyRef", "canonicalName", "displayName"):
            name = row.get(key)
            if isinstance(name, str) and name:
                out.setdefault(name, value)
    return out


def offense_only_values_from_contract(contract: dict[str, Any]) -> dict[str, int]:
    """Map ``legacyRef``/``canonicalName`` → ``offenseOnlyRankDerivedValue``.

    A SECOND board on the same 0-9999 scale — the IDP-disabled re-run of
    ``_compute_unified_rankings``.  Published for comparison; never
    substituted for the canonical value.

    Read from ``playersArray`` rather than from the legacy ``players``
    dict's ``_offenseOnlyFinalAdjusted`` mirror, and that is the whole
    point of this function.  ``src/league_intel/overlay.py`` applies the
    league-adjusted lens to ``playersArray`` rows only — it deliberately
    leaves the legacy dict alone — so a value read from the mirror is
    always the UNADJUSTED market number, whatever the response says its
    ``valuationMode`` is (W29-F002).  Keyed exactly like
    :func:`board_values_from_contract`.
    """
    out: dict[str, int] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        value = _int_or_none(row.get("offenseOnlyRankDerivedValue"))
        if value is None or value < 1:
            continue
        for key in ("legacyRef", "canonicalName", "displayName"):
            name = row.get(key)
            if isinstance(name, str) and name:
                out.setdefault(name, value)
    return out


def positions_from_contract(contract: dict[str, Any]) -> dict[str, str]:
    """Map ``legacyRef``/``canonicalName``/``displayName`` → ``position``.

    WHY THIS IS NEEDED AT ALL
    =========================
    ``build_asset_pool`` routes each asset to the retail board its
    counterparty would consult — ``idpTradeCalc`` for IDP, ``ktcSfTep``
    for everything else — by reading ``pdata["position"]`` off the
    legacy ``players`` dict.

    That dict has **no ``position`` key**.  Measured on the pinned
    2026-07-30 contract: 0 of 1093 entries carry one.  So
    ``_norm_pos("")`` was falsy for every asset, ``pos in
    IDP_POSITIONS`` was never true, and every asset — defenders
    included — routed to the KTC board.  KTC publishes no IDP, so every
    defender scored ``market_value = None`` and was dropped before
    scoring.  In an IDP league the arbitrage finder silently returned
    offense-only results.

    This is the SAME defect class WS-J F-3 fixed once already: that
    round introduced the per-market gate so IDP would stop being
    measured against a board that does not cover it.  The gate was
    correct; the key it switched on was never populated, so the fix
    could not take effect and nothing said so.

    Keyed exactly like :func:`board_values_from_contract` — on all three
    name fields — because the ``players`` dict is keyed by the legacy
    scraper name, which is not always the canonical one.  Sharing the
    keying is deliberate: an asset that resolves a board value must
    resolve a position from the same row, or the two lookups would
    disagree about which player they mean.
    """
    out: dict[str, str] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        position = row.get("position")
        if not isinstance(position, str) or not position:
            continue
        for key in ("legacyRef", "canonicalName", "displayName"):
            name = row.get(key)
            if isinstance(name, str) and name:
                out.setdefault(name, position)
    return out


def source_counts_from_contract(contract: dict[str, Any]) -> dict[str, int]:
    """Map ``legacyRef``/``canonicalName``/``displayName`` → blend count.

    How many sources actually voted on this asset, post-Hampel, read
    from the contract's ``effectiveSourceRanks``.

    ``build_asset_pool`` took this from the legacy dict's ``_sites``,
    which is the SCRAPER's site count, not the board's blend count.  On
    the live payload ``_sites`` takes only the values 1 (526 rows), 2
    (110), 3 (438) and null (18) — a maximum of 3 — while
    ``effectiveSourceRanks`` runs to 16.  Against
    ``CONFIDENCE_SOURCE_BASELINE = 5`` that capped
    ``source_confidence`` at ``3/5 = 0.60``, so the total confidence
    score could never reach the 0.75 ``high`` tier: across 480 returned
    trades over 12 teams the tier appeared zero times, and a tier that
    is structurally unreachable is not a tier (W09-F008).

    Baselining down to ``_sites``' actual range would have hidden it —
    the number was wrong, not the threshold.

    Keyed exactly like :func:`board_values_from_contract`, for the same
    reason: an asset that resolves a board value must resolve its blend
    count from the same row.
    """
    out: dict[str, int] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        effective = row.get("effectiveSourceRanks")
        if not isinstance(effective, dict):
            continue
        count = len(effective)
        if count < 1:
            # Zero voters is not "unknown" and not "one" — leave it
            # unmapped so the caller's own absent-value path runs.
            continue
        for key in ("legacyRef", "canonicalName", "displayName"):
            name = row.get(key)
            if isinstance(name, str) and name:
                out.setdefault(name, count)
    return out


def pick_market_keys_from_contract(contract: dict[str, Any] | None) -> set[str] | None:
    """Pick keys a retail market ACTUALLY published, from ``pickAnchors``.

    ``pickAnchors`` is the contract's per-market pick board — the only
    published evidence for "did KTC / IDPTradeCalc price this pick?".
    Returns lowercased keys across every market, or ``None`` when the
    contract carries no anchors at all (older fixtures), which leaves
    the guard in :func:`build_asset_pool` disabled.

    Why this exists: the scraper's pick ingestion extrapolates a
    source's values into years the source never published — a 2029
    first's ``ktc`` and ``idpTradeCalc`` numbers on the 2026-08-04
    payload are byte-identical copies of the 2028 first's (4578 /
    4551).  Our board correctly applies another year of discount, so
    every 2029 pick shows a board/market ratio of 0.527 against ~1.00
    for 2026-2028 and 0.946 for players.  That is not an arbitrage
    signal, it is one fabricated number being compared with one real
    one — and it swamped this engine: once picks became resolvable on a
    roster at all, 478 of the 480 trades returned across 12 teams
    contained a 2029 pick, every one of them scored off that gap.
    ``pickAnchors`` covers 2026-2028 only, so it says plainly which
    pick prices are observations.
    """
    anchors = (contract or {}).get("pickAnchors")
    if not isinstance(anchors, dict) or not anchors:
        return None
    keys: set[str] = set()
    for market_map in anchors.values():
        if isinstance(market_map, dict):
            keys.update(str(k).strip().lower() for k in market_map)
    return keys or None


def build_asset_pool(
    players: dict[str, Any],
    *,
    market_top_n: int | None = None,
    ktc_top_n: int | None = None,
    board_values: dict[str, int] | None = None,
    offense_only_values: dict[str, int] | None = None,
    positions: dict[str, str] | None = None,
    pick_market_keys: set[str] | None = None,
    source_counts: dict[str, int] | None = None,
) -> list[Asset]:
    """Convert raw players dict into Asset objects with model + market values.

    Each asset is anchored on the retail board its counterparty would
    actually consult — KTC for offense and picks, IDPTradeCalc for IDP —
    and ranked against that market's own population.  See
    :data:`MARKET_TOP_N_FILTER` for why the gate is per-market.

    Args:
        players: Raw players dict from the live data payload.
        market_top_n: Only include assets ranked inside the top N **of
            their own market**. Set to 0 to disable.
        ktc_top_n: Deprecated alias for ``market_top_n``.
        board_values: ``name -> rankDerivedValue`` from the canonical
            contract.  When supplied, the model value comes from the
            board and assets absent from it are DROPPED — see below.

    The ``board_values`` path is the F-6 migration (audit finding K).
    Without it this function falls back to the raw scraper composite,
    which is what the engine used to read: a parallel board the user
    never sees, so the "arbitrage" was measured against the wrong
    baseline.  The fallback is retained for fixtures and for callers
    that hold only a raw payload; ``find_trades`` always passes the
    board when a contract is available.

    **Dropping is the point, not a side effect.** 282 assets on the
    live 2026-07-29 payload carry a composite value but no
    ``rankDerivedValue`` (189 of them clearing the composite-scale
    equivalent of ``MIN_ASSET_VALUE`` — see
    ``_MIN_ASSET_VALUE_COMPOSITE_SCALE``). They are assets the
    canonical board declines to price. Trading them was never
    defensible — the finder was pricing them off a board nothing else
    consults — so they leave the universe, and ``find_trades`` reports
    how many left rather than letting the pool quietly shrink.
    """
    if market_top_n is None:
        market_top_n = MARKET_TOP_N_FILTER if ktc_top_n is None else ktc_top_n
    pool: list[Asset] = []
    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue

        # The number of sources that voted on this asset's BOARD value,
        # from the contract when we have it.  ``_sites`` is the
        # scraper's site count and tops out at 3 — see
        # ``source_counts_from_contract`` for why that made the ``high``
        # confidence tier unreachable (W09-F008).  It stays as the
        # fallback for callers holding only a raw payload.
        source_count = 0
        if source_counts is not None:
            source_count = _int_or_none(source_counts.get(name)) or 0
        if source_count < 1:
            source_count = _int_or_none(pdata.get("_sites")) or 0

        if board_values is not None:
            # F-6: the canonical board.  No single-source haircut here —
            # ``_SINGLE_SOURCE_VALUE_RETENTION`` (0.30) is already baked
            # into ``rankDerivedValue`` by the pipeline.  The local 0.88
            # ``SINGLE_SOURCE_DISCOUNT`` existed only to substitute for a
            # retention that never reached this engine, and is deleted
            # with the migration rather than retuned.
            model = board_values.get(name)
            if model is None or model < 1:
                continue
            # Offense-only board value.  ``_offenseOnlyFinalAdjusted`` is
            # mirrored from ``offenseOnlyRankDerivedValue`` — the output of
            # the IDP-disabled run of ``_compute_unified_rankings``
            # (data_contract.py) — so it is on the BOARD scale, the same
            # scale as ``model`` here.  ``_score_trade`` substitutes one
            # for the other inside a single subtraction, so sharing a
            # scale is the correctness requirement, and it is met.
            #
            # Corrected 2026-07-29 audit: this branch previously forced
            # ``oo_raw = None`` on the reasoning that "the board has no
            # offense-only variant".  It does — measured over 522 assets
            # carrying both, median ``_offenseOnlyFinalAdjusted /
            # rankDerivedValue`` = 0.994 (p10 0.893, p90 1.015), i.e. the
            # same scale.  The composite, by contrast, runs 1.131× the
            # board.  So the two branches had their scales exactly
            # backwards: the offense-only feature was dead on the live
            # path, and the fallback below was the one mixing scales.
            #
            # Read from the CONTRACT when the caller supplied it.  The
            # legacy dict's ``_offenseOnlyFinalAdjusted`` mirror is
            # never touched by the league-adjusted overlay, which
            # rewrites ``playersArray`` rows only — so reading the
            # mirror under ``valuationMode: leagueAdjusted`` returns the
            # unadjusted market number (W29-F002).  The mirror stays as
            # the fallback for callers holding a raw payload.
            if offense_only_values is not None:
                oo_raw = offense_only_values.get(name)
            else:
                oo_raw = _int_or_none(pdata.get("_offenseOnlyFinalAdjusted"))
        else:
            # Legacy path: raw scraper composite.
            model = _int_or_none(pdata.get("_finalAdjusted"))
            if model is None:
                model = _int_or_none(pdata.get("_rawComposite"))
            if model is None:
                model = _int_or_none(pdata.get("_rawMarketValue"))
            if model is None:
                model = _int_or_none(pdata.get("_composite"))
            if model is None or model < 1:
                continue

            # No offense-only value on this path.  The only producer of
            # ``_offenseOnlyFinalAdjusted`` is the contract builder, which
            # mirrors the BOARD-scale ``offenseOnlyRankDerivedValue`` into
            # it — while ``model`` here is the COMPOSITE-scale scraper
            # value, measured at 1.131× the board.  ``_score_trade``
            # substitutes one for the other inside one subtraction, so
            # reading it here understated every all-offense give/receive
            # leg by ~12% whenever a caller passed a contract-built
            # players dict without the contract itself.  Degrading to
            # "unavailable" is the honest behaviour on this path — the
            # rationale that used to sit on the board branch above.
            oo_raw = None

            if source_count == 1:
                model = int(model * _LEGACY_SINGLE_SOURCE_DISCOUNT)

        # Position comes from the contract when we have it: the legacy
        # ``players`` dict carries no ``position`` key at all (0 of 1093
        # rows on the live payload), which silently routed every IDP
        # asset to the KTC board and dropped it.  See
        # ``positions_from_contract``.
        pos = _norm_pos((positions or {}).get(name) or pdata.get("position", "") or "")

        # Retail market value, read from the board the counterparty
        # would actually consult for this position (WS-J F-3).  IDP
        # rows read IDPTradeCalc; everything else reads KTC's TE+ board
        # (``ktcSfTep``), the canonical KTC retail signal as of
        # 2026-04-28 when standard ``ktc`` was retired from the blend,
        # falling back to standard ``ktc`` for fixtures that predate
        # the supersession.
        market_keys = IDP_MARKET_KEYS if pos in IDP_POSITIONS else OFFENSE_MARKET_KEYS
        csv = pdata.get("_canonicalSiteValues")
        market_value: int | None = None
        market_source: str | None = None
        for key in market_keys:
            if isinstance(csv, dict):
                market_value = _int_or_none(csv.get(key))
            if market_value is None:
                market_value = _int_or_none(pdata.get(key))
            if market_value is not None:
                market_source = key
                break

        team = pdata.get("team", "") or ""
        is_pick = bool(
            pos == "PICK"
            or name.startswith("20")
            or " pick " in name.lower()
            or " round " in name.lower()
        )
        if is_pick:
            pos = "PICK"
            # A pick whose "market value" is not a market OBSERVATION
            # cannot be arbitraged against.  See
            # ``pick_market_keys_from_contract`` — the ingestion path
            # copies a source's nearest published year onto years it
            # never priced, and this engine's whole premise is the gap
            # between our board and a real retail number.  Withdraw the
            # market value rather than invent an edge from it; the pick
            # keeps its board value everywhere else.
            if (
                pick_market_keys is not None
                and market_value is not None
                and pick_anchor_key(name).lower() not in pick_market_keys
            ):
                market_value = None
                market_source = None

        # Exclude positions without meaningful KTC support
        if pos in EXCLUDED_POSITIONS:
            continue

        pool.append(
            Asset(
                name=name,
                position=pos,
                team=team if isinstance(team, str) else "",
                model_value=model,
                market_value=market_value,
                is_pick=is_pick,
                source_count=source_count,
                offense_only_model_value=oo_raw if oo_raw is not None and oo_raw >= 1 else None,
                market_source=market_source,
            )
        )

    # ── Rank within each market, then apply the top-N cut per market ──
    # Ranking every asset in one list would bury IDP entirely: offense
    # runs to 9999 while the best defender sits near 6400, so a single
    # global top-150 removes every IDP player (WS-J F-3).  Each market
    # ranks its own population from 1.
    by_market: dict[str, list[Asset]] = {}
    for a in pool:
        if not a.has_market or a.market_source is None:
            continue
        by_market.setdefault(a.market_source, []).append(a)

    # ``ktcSfTep`` and legacy ``ktc`` are the same board — rank them as
    # one population so a fixture mixing both doesn't split the cut.
    offense_assets = [a for key in OFFENSE_MARKET_KEYS for a in by_market.get(key, [])]
    market_groups: dict[str, list[Asset]] = {"offense": offense_assets}
    for key in IDP_MARKET_KEYS:
        market_groups.setdefault("idp", []).extend(by_market.get(key, []))

    eligible_names: set[str] = set()
    for group in market_groups.values():
        group.sort(key=lambda a: -(a.market_value or 0))
        for i, a in enumerate(group):
            a.market_rank = i + 1
        if market_top_n > 0:
            eligible_names.update(a.name for a in group if a.market_rank <= market_top_n)

    if market_top_n > 0:
        pool = [a for a in pool if a.name in eligible_names]

    return pool


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def _resolve_roster(
    team_name: str,
    sleeper_teams: list[dict[str, Any]],
    pool_by_name: dict[str, Asset],
    pick_aliases: Any = None,
) -> list[Asset]:
    """Resolve a Sleeper team name to a list of Asset objects.

    A Sleeper team dict carries its roster in TWO sibling keys:
    ``players`` (display names) and ``picks`` (pick labels such as
    "2026 1st" / "2026 1.04 (own)").  This function read only
    ``players``, so every pick a team owned was invisible to the
    engine — 25 picks sat in the gated asset pool and 0 appeared in
    any of the 480 trades returned across all 12 teams, even though
    player-plus-pick and pick-for-player are the two most common
    dynasty trade shapes.  Audit finding W09-F003.

    Pick labels are resolved through the shared
    ``src/utils/pick_labels`` resolver — the Python port of the
    frontend's ``resolvePickRow`` — so this engine joins picks the
    same way every other surface does instead of inventing a tenth
    regex.  A label the board cannot price simply does not resolve;
    nothing is substituted for it.

    Duplicates collapse.  A team holding eight 2027 firsts holds eight
    picks that resolve to ONE board row ("2027 Mid 1st"), because the
    board prices a tier, not an owner.  Emitting the same Asset eight
    times would let the generators build "2027 Mid 1st + 2027 Mid 1st"
    packages out of a single priced row, so the roster is de-duplicated
    by asset name.  Distinguishing those eight picks by their original
    owner needs a per-owner price the board does not publish (see the
    R8 note in docs/master-site-audit/REPAIR_ROADMAP.md).
    """
    for t in sleeper_teams:
        if t.get("name") == team_name:
            result: list[Asset] = []
            seen: set[str] = set()

            def _append(asset: Asset | None) -> None:
                if asset is None or asset.name in seen:
                    return
                seen.add(asset.name)
                result.append(asset)

            for pname in t.get("players") or []:
                key = str(pname).strip()
                asset = pool_by_name.get(key)
                if asset is None:
                    # Try case-insensitive
                    for k, v in pool_by_name.items():
                        if k.lower() == key.lower():
                            asset = v
                            break
                _append(asset)

            for label in t.get("picks") or []:
                resolved = resolve_pick_name(label, pool_by_name.keys(), pick_aliases)
                if resolved is not None:
                    _append(pool_by_name.get(resolved))

            return result
    return []


def _score_trade(give: list[Asset], receive: list[Asset]) -> TradeCandidate | None:
    """Score a candidate trade. Returns None if the trade is nonsensical."""
    if not give or not receive:
        return None

    # No duplicate/self-trade
    give_names = {a.name for a in give}
    receive_names = {a.name for a in receive}
    if give_names & receive_names:
        return None

    # ── Outgoing market gate ─────────────────────────────────────────
    # Every outgoing asset MUST have a usable market value on its own
    # board.  Without it we cannot prove the deal looks plausible to the
    # opponent, so offering an unpriced player for an elite return is
    # nonsense.
    for a in give:
        if not a.has_market or a.market_value < MIN_MARKET_VALUE:  # type: ignore[operator]
            return None

    # ── Receive-side market gate ──────────────────────────────────────
    # At least one receive asset must carry a market value so the
    # opponent-appeal calculation is grounded in real market data.
    if not any(a.has_market for a in receive):
        return None

    # NOTE (WS-J F-3): an "IDP dilution guard" used to sit here,
    # rejecting any side where IDP assets *without KTC* were half or
    # more of the package, on the grounds that they distorted the
    # KTC-based appeal calculation.  Its premise no longer exists: IDP
    # assets are now anchored on IDPTradeCalc, so they carry a real
    # market value like any other asset and distort nothing.  The guard
    # was also unreachable in production — the KTC-only top-N filter had
    # already removed every IDP asset before scoring ran — so it was
    # documenting a world the filter had deleted.  Removed rather than
    # left as dead code.

    # Every leg is scored on ONE board: the canonical one, the same one
    # ``metadata.valueSource`` names and ``/arbitrage`` labels "board".
    # This used to swap the whole subtraction onto the offense-only
    # board whenever neither side carried an IDP asset — a different
    # board for the arithmetic than for the label, and one the
    # league-adjusted lens never reached (W29-F002, W09-F006).
    give_model = sum(a.model_value for a in give)
    recv_model = sum(a.model_value for a in receive)
    board_delta = recv_model - give_model

    # NOT "must be positive" — this admits a band of small BOARD LOSSES
    # down to ``MAX_BOARD_LOSS`` so a near-even trade with strong
    # opponent appeal can still be scored and compared.  The comment
    # here used to claim positivity, contradicting the line it annotated.
    #
    # Nothing in that band reaches a caller: ``find_trades`` filters on
    # ``board_delta > 0`` before returning.  Two gates, deliberately —
    # scoring a candidate and recommending it are different questions.
    # If the output filter is ever relaxed, ``_build_summary`` must stop
    # hard-coding a ``+`` sign first (see below), or a loss ships
    # described as a gain.
    if board_delta < MAX_BOARD_LOSS:
        return None

    # ── Multi-for-one fire sale guard ────────────────────────────────
    # Prevent suggesting two roster fillers for an elite target.
    # When giving more pieces than receiving, the give side's total model
    # value must be a meaningful fraction of the receive side.
    flags: list[str] = []

    if len(give) > len(receive):
        if give_model < recv_model * MULTI_FOR_ONE_MIN_RATIO:
            return None
        # ── Elite target protection (tighter ratio) ──────────────────
        max_recv = max(a.model_value for a in receive)
        if max_recv >= ELITE_THRESHOLD:
            if give_model < recv_model * ELITE_MULTI_MIN_RATIO:
                return None
            flags.append("elite_target")
        # ── Package anchor quality ───────────────────────────────────
        # At least one give piece must be a real starter-quality asset,
        # not just two bench stashes that happen to sum high enough.
        max_give = max(a.model_value for a in give)
        if max_give < max_recv * PACKAGE_ANCHOR_MIN_PCT:
            return None
        flags.append("anchor_verified")

    # KTC scoring
    give_market_assets = [a for a in give if a.has_market]
    recv_market_assets = [a for a in receive if a.has_market]
    all_have_market = len(give_market_assets) == len(give) and len(recv_market_assets) == len(
        receive
    )
    any_have_market = bool(give_market_assets) or bool(recv_market_assets)

    # Partial coverage is reachable only when the per-market top-N gate
    # is disabled (``market_top_n=0``); with the gate on, every pooled
    # asset carries a market value by construction.
    if not any_have_market:
        # No market data on either side — cannot evaluate plausibility
        return None
    elif all_have_market:
        coverage = "full"
        give_ktc = sum(a.market_value for a in give)  # type: ignore[arg-type]
        recv_ktc = sum(a.market_value for a in receive)  # type: ignore[arg-type]
        # Opponent gives recv_ktc to get give_ktc back
        # Opponent appeal = (what they get - what they give) / what they give
        opp_appeal = (give_ktc - recv_ktc) / max(recv_ktc, 1)
        flags.append("full_market")
    else:
        coverage = "partial"
        give_ktc = sum(a.market_value or 0 for a in give)
        recv_ktc = sum(a.market_value or 0 for a in receive)
        opp_appeal = (give_ktc - recv_ktc) / max(recv_ktc, 1) if recv_ktc > 0 else 0.0
        flags.append("partial_market")

    # The opponent must STRICTLY WIN on KTC — no break-even, no loss.
    if opp_appeal <= 0:
        return None

    # Filter out junk trades: at least one meaningful asset on each side
    if all(a.model_value < JUNK_THRESHOLD for a in give):
        return None
    if all(a.model_value < JUNK_THRESHOLD for a in receive):
        return None

    # Arbitrage score: how much we gain on our board while the opponent
    # sees a fair/favorable deal on KTC.
    # Higher = better arbitrage.
    # Normalized against the LARGER side, not the give side.  Dividing
    # a difference by one of its two operands is not a rate of gain — it
    # is a lopsidedness score, and it is unbounded: shrink the give side
    # and ``f_board_edge = board_gain_norm * 50`` grows without limit
    # against a flat ``-(pkg_size - 2) * 3`` counterweight.  Measured on
    # the live payload that produced 480 returned trades across 12
    # teams of which 480 were 1-for-2; the first 1-for-1 sat at rank 43
    # of 5,733 qualified candidates (W09-F002).
    #
    # ``board_delta / max(give, recv)`` is bounded by 1.0 — "you gained
    # the entire receive side" — which is what the 0.25 / 0.10
    # ``_edge_label`` thresholds were always read as meaning.  For an
    # accepted trade (delta > 0) the larger side IS the receive side, so
    # this reads "the gain as a fraction of what came back".  The
    # ``max`` is written out rather than assumed because ``_score_trade``
    # also scores the small-loss band above.
    board_gain_norm = board_delta / max(give_model, recv_model, 1)
    ktc_delta = give_ktc - recv_ktc  # positive = opponent gets more KTC than they give

    # Core arbitrage: we win on model, opponent wins on KTC
    f_board_edge = board_gain_norm * 50
    f_ktc_appeal = opp_appeal * 30
    f_positive_bonus = (1.0 if board_delta > 0 else 0.0) * 10
    arbitrage = f_board_edge + f_ktc_appeal + f_positive_bonus

    # Partial coverage: severe demotion — these cannot compete with full-KTC trades
    if coverage == "partial":
        arbitrage *= 0.3
        arbitrage = min(arbitrage, PARTIAL_MARKET_ARBITRAGE_CAP)

    # ── Confidence factor (source coverage × KTC coverage) ───────────
    all_assets = give + receive
    source_counts = [a.source_count for a in all_assets if a.source_count > 0]
    if source_counts:
        avg_sources = sum(source_counts) / len(source_counts)
        source_confidence = min(1.0, avg_sources / CONFIDENCE_SOURCE_BASELINE)
    else:
        # Unknown source counts — assume reasonable
        avg_sources = None
        source_confidence = 1.0
    ktc_confidence = 1.0 if coverage == "full" else 0.7
    confidence = source_confidence * ktc_confidence

    # Apply confidence as a soft multiplier (floor at 0.7 to avoid killing trades)
    f_confidence_mult = 0.7 + 0.3 * confidence
    arbitrage *= f_confidence_mult

    # ── Absolute-value bonus ────────────────────────────────────────
    # Larger, more impactful trades rank above trivially small ones
    # with similar edge percentages.
    value_moved = min(give_model, recv_model)
    f_value_scale = min(1.0, value_moved / 5000) * 5
    arbitrage += f_value_scale

    # Penalize larger packages (simplicity bonus)
    pkg_size = len(give) + len(receive)
    f_simplicity = -(pkg_size - 2) * 3
    arbitrage += f_simplicity

    # ── Build explainability fields ──────────────────────────────────
    conf_tier = _confidence_tier(confidence)
    flags.append(f"{conf_tier}_confidence")
    edge_lbl = _edge_label(board_gain_norm)
    pkg_size_str = f"{len(give)}-for-{len(receive)}"
    summary = _build_summary(
        board_delta,
        board_gain_norm,
        opp_appeal,
        coverage,
        conf_tier,
        edge_lbl,
        pkg_size_str,
    )
    ranking_factors = {
        "boardEdge": round(f_board_edge, 2),
        "ktcAppeal": round(f_ktc_appeal, 2),
        "positiveBonus": round(f_positive_bonus, 2),
        "confidenceMultiplier": round(f_confidence_mult, 3),
        "valueScale": round(f_value_scale, 2),
        "simplicityPenalty": round(f_simplicity, 2),
        "rosterFitBonus": 0.0,  # populated in find_trades if applicable
        # The number the confidence tier is derived FROM, so a reader
        # can see whether "high" means well-blended or merely
        # saturated: once the count is the board's real blend count
        # (W09-F008) most top-150 assets clear the baseline of 5
        # comfortably, and a tier that is nearly always its top value
        # discriminates about as poorly as one that could never reach
        # it.  ``None`` when no asset carried a count — that is
        # "unmeasured", and it is exactly the case where
        # ``source_confidence`` falls back to 1.0.
        "avgSourceCount": round(avg_sources, 2) if avg_sources is not None else None,
    }

    tc = TradeCandidate(
        give=give,
        receive=receive,
        give_model_total=give_model,
        receive_model_total=recv_model,
        give_ktc_total=give_ktc,
        receive_ktc_total=recv_ktc,
        board_delta=board_delta,
        ktc_delta=ktc_delta,
        opponent_ktc_appeal=opp_appeal,
        arbitrage_score=arbitrage,
        ktc_coverage=coverage,
        confidence_score=confidence,
        confidence_tier=conf_tier,
        edge_label=edge_lbl,
        summary=summary,
        ranking_factors=ranking_factors,
        flags=flags,
    )
    return tc


def _generate_1for1(
    my_assets: list[Asset],
    opp_assets: list[Asset],
) -> list[TradeCandidate]:
    """Generate all viable 1-for-1 trades."""
    results: list[TradeCandidate] = []
    for mine in my_assets:
        if mine.model_value < MIN_ASSET_VALUE:
            continue
        for theirs in opp_assets:
            if theirs.model_value < MIN_ASSET_VALUE:
                continue
            tc = _score_trade([mine], [theirs])
            if tc is not None:
                results.append(tc)
    return results


def _generate_2for1(
    my_assets: list[Asset],
    opp_assets: list[Asset],
) -> list[TradeCandidate]:
    """Generate viable 2-for-1 trades (I give 2, get 1)."""
    results: list[TradeCandidate] = []
    # Limit combinations for performance
    my_tradeable = [a for a in my_assets if a.model_value >= MIN_ASSET_VALUE]
    opp_tradeable = [a for a in opp_assets if a.model_value >= MIN_ASSET_VALUE]
    if len(my_tradeable) < 2:
        return results

    for pair in combinations(my_tradeable[:30], 2):
        for theirs in opp_tradeable[:30]:
            tc = _score_trade(list(pair), [theirs])
            if tc is not None:
                results.append(tc)
    return results


def _generate_1for2(
    my_assets: list[Asset],
    opp_assets: list[Asset],
) -> list[TradeCandidate]:
    """Generate viable 1-for-2 trades (I give 1, get 2)."""
    results: list[TradeCandidate] = []
    my_tradeable = [a for a in my_assets if a.model_value >= MIN_ASSET_VALUE]
    opp_tradeable = [a for a in opp_assets if a.model_value >= MIN_ASSET_VALUE]
    if len(opp_tradeable) < 2:
        return results

    for mine in my_tradeable[:30]:
        for pair in combinations(opp_tradeable[:30], 2):
            tc = _score_trade([mine], list(pair))
            if tc is not None:
                results.append(tc)
    return results


def _prune_dominated(trades: list[TradeCandidate]) -> list[TradeCandidate]:
    """Drop packages another package strictly beats.

    A trade is dominated when some OTHER trade offers the same give side
    for a receive side that contains everything this one receives and
    more, and scores better.  Accepting the dominated one is strictly
    worse by the engine's own arithmetic, so listing it consumes a slot
    to show the reader a trade they should never take.

    ``_deduplicate`` collapses only exact repeats — same assets, different
    enumeration order — which is a different thing and stays.

    Input order is irrelevant; the comparison is on score, so this is
    safe to run before or after ranking.
    """
    by_give: dict[tuple[str, ...], list[TradeCandidate]] = {}
    for tc in trades:
        by_give.setdefault(tuple(sorted(a.name for a in tc.give)), []).append(tc)

    dominated: set[int] = set()
    for group in by_give.values():
        if len(group) < 2:
            continue
        recv_sets = [frozenset(a.name for a in tc.receive) for tc in group]
        for i, tc in enumerate(group):
            for j, other in enumerate(group):
                if i == j:
                    continue
                if other.arbitrage_score <= tc.arbitrage_score:
                    continue
                if recv_sets[i] < recv_sets[j]:
                    dominated.add(id(tc))
                    break
    return [tc for tc in trades if id(tc) not in dominated]


def _fill_by_shape(
    ranked: list[TradeCandidate],
    max_results: int,
    *,
    max_give_appearances: int = MAX_GIVE_ASSET_APPEARANCES,
) -> list[TradeCandidate]:
    """Fill the returned list round-robin over package shapes.

    A straight ``ranked[:max_results]`` returns the arg-max over a
    candidate space the generators build in wildly unequal sizes:
    ``_generate_1for2`` enumerates my assets × opponent PAIRS, so on the
    live payload one team qualified 5,540 1-for-2 packages against 178
    1-for-1 and 15 2-for-1.  The maximum of a 31×-larger sample is
    higher almost by construction, so every one of the 480 trades
    returned across 12 teams was a 1-for-2 and the other two shapes — the
    two most common shapes in real dynasty trading — were unreachable
    from the UI (W09-F002).

    Rank order is preserved exactly WITHIN each shape; what changes is
    only how many slots each shape gets.  Shapes are visited
    most-populous first so the dominant shape still leads the list, and
    a shape that runs out simply stops contributing — the list is never
    padded and never short while candidates remain.

    ``metadata.qualifiedByShape`` / ``returnedByShape`` publish both
    sides of this, the same "say what was there and what you served"
    posture as ``marketCoverage``.

    The same walk enforces ``MAX_GIVE_ASSET_APPEARANCES``: a trade whose
    give side is already at the cap is set aside, not dropped.  If the
    cap would leave the list short, the set-aside trades are appended in
    rank order — a short list of diverse ideas is worse than a full one,
    and withholding a real trade to satisfy a diversity rule would be
    the engine lying about what it found.
    """
    if max_results <= 0:
        return []
    by_shape: dict[str, list[TradeCandidate]] = {}
    for t in ranked:
        by_shape.setdefault(t.package_shape(), []).append(t)
    # Most-populous shape first, name as the tiebreak so the order is
    # deterministic for equal populations.
    order = sorted(by_shape, key=lambda k: (-len(by_shape[k]), k))
    cursors = dict.fromkeys(by_shape, 0)
    out: list[TradeCandidate] = []
    deferred: list[TradeCandidate] = []
    appearances: dict[str, int] = {}

    def _at_cap(tc: TradeCandidate) -> bool:
        if max_give_appearances <= 0:
            return False
        return any(appearances.get(a.name, 0) >= max_give_appearances for a in tc.give)

    while len(out) < max_results:
        progressed = False
        for shape in order:
            if len(out) >= max_results:
                break
            candidates = by_shape[shape]
            i = cursors[shape]
            # Advance past anything this shape can no longer contribute,
            # so one over-used asset does not stall its whole shape.
            while i < len(candidates) and _at_cap(candidates[i]):
                deferred.append(candidates[i])
                i += 1
            cursors[shape] = i
            if i < len(candidates):
                tc = candidates[i]
                out.append(tc)
                for a in tc.give:
                    appearances[a.name] = appearances.get(a.name, 0) + 1
                cursors[shape] = i + 1
                progressed = True
        if not progressed:
            break

    for tc in deferred:
        if len(out) >= max_results:
            break
        out.append(tc)
    return out


def _deduplicate(trades: list[TradeCandidate]) -> list[TradeCandidate]:
    """Remove duplicate trade packages (same assets, different order)."""
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    result: list[TradeCandidate] = []
    for tc in trades:
        key = (
            tuple(sorted(a.name for a in tc.give)),
            tuple(sorted(a.name for a in tc.receive)),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(tc)
    return result


def find_trades(
    players: dict[str, Any],
    my_team: str,
    opponent_teams: list[str],
    sleeper_teams: list[dict[str, Any]],
    *,
    max_results: int = MAX_RESULTS,
    market_top_n: int | None = None,
    ktc_top_n: int | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Find board-arbitrage trades.

    Parameters
    ----------
    players : dict
        Raw players dict from the live data payload.
    my_team : str
        Name of my Sleeper team.
    opponent_teams : list[str]
        Names of opponent teams to trade with.
    sleeper_teams : list[dict]
        Full Sleeper teams array from the data payload.
    max_results : int
        Maximum number of results to return.
    ktc_top_n : int
        Only include players ranked in the KTC top N. Set to 0 to disable.

    Returns
    -------
    dict with trades, metadata, and any warnings.
    """
    if market_top_n is None:
        market_top_n = MARKET_TOP_N_FILTER if ktc_top_n is None else ktc_top_n

    # F-6 (audit finding K): value assets off the canonical board when a
    # contract is available.  ``contract`` may be the same object the
    # ``players`` dict came from — ``/api/data`` carries both — so a
    # caller holding the live contract can pass it for both arguments.
    board_values = board_values_from_contract(contract) if contract else None
    offense_only_values = offense_only_values_from_contract(contract) if contract else None
    # The legacy ``players`` dict has no ``position`` key, so without
    # this every IDP asset routes to the KTC board and is dropped.
    positions = positions_from_contract(contract) if contract else None
    pick_market_keys = pick_market_keys_from_contract(contract)
    # The board's blend count, not the scraper's site count (W09-F008).
    source_counts = source_counts_from_contract(contract) if contract else None
    pool = build_asset_pool(
        players,
        market_top_n=market_top_n,
        board_values=board_values,
        offense_only_values=offense_only_values,
        positions=positions,
        source_counts=source_counts,
        pick_market_keys=pick_market_keys,
    )
    # Picks no retail market priced, so this engine cannot arbitrage
    # them.  Counted and named rather than silently missing, same
    # posture as ``assetsUnpricedByBoard``.
    picks_without_market: list[str] = []
    if pick_market_keys is not None:
        picks_without_market = sorted(
            {
                str(name)
                for name, pdata in players.items()
                if isinstance(pdata, dict)
                and _norm_pos((positions or {}).get(name) or "") == "PICK"
                and pick_anchor_key(name).lower() not in pick_market_keys
            }
        )

    # How many assets the board declined to price.  Surfaced rather than
    # left to be inferred from a smaller pool: migrating to the canonical
    # board removes assets from this engine's universe, and a silently
    # shorter list reads as "nothing available" instead of "not priced".
    # NOTE ON SCALE: these rows have no board value by definition, so the
    # only value available for the "would this asset have mattered?"
    # filter is the COMPOSITE one — and it must therefore be gated with
    # the composite-scale threshold, not the board-scale
    # ``MIN_ASSET_VALUE``.  Fixed 2026-07-29 audit: the board-scale 700
    # was being applied to composite numbers, reporting 202 where the
    # docstring on ``build_asset_pool`` (and the intent) say 189.
    unpriced_by_board = 0
    if board_values is not None:
        unpriced_by_board = sum(
            1
            for name, pdata in players.items()
            if isinstance(pdata, dict)
            and name not in board_values
            and (_int_or_none(pdata.get("_finalAdjusted")) or 0) >= _MIN_ASSET_VALUE_COMPOSITE_SCALE
        )

    pool_by_name: dict[str, Asset] = {}
    for a in pool:
        pool_by_name[a.name] = a

    # ``pickAliases`` redirects a generic tier label onto the
    # slot-specific row the current-year board actually prices; without
    # it every current-class pick resolves to an unpriced generic.
    pick_aliases = (contract or {}).get("pickAliases")

    my_roster = _resolve_roster(my_team, sleeper_teams, pool_by_name, pick_aliases)
    if not my_roster:
        return {
            "error": f"Could not resolve team '{my_team}' or roster is empty.",
            "trades": [],
            "metadata": {},
        }

    my_names = {a.name for a in my_roster}
    all_trades: list[TradeCandidate] = []
    opponents_analyzed = 0
    warnings: list[str] = []

    if unpriced_by_board:
        warnings.append(
            f"{unpriced_by_board} assets carry a scraper value above "
            f"{_MIN_ASSET_VALUE_COMPOSITE_SCALE} but no canonical board value, "
            "so they are not tradeable here. They are unpriced, not worthless."
        )

    # Track market coverage, per market.  Reporting one blended number
    # hid the offense-only regression (WS-J F-3): a pool with zero IDP
    # assets still showed 100% coverage because the missing rows had
    # already been filtered out upstream.
    market_coverage: dict[str, int] = {key: 0 for key in (*OFFENSE_MARKET_KEYS, *IDP_MARKET_KEYS)}
    for a in pool:
        if a.has_market and a.market_source:
            market_coverage[a.market_source] = market_coverage.get(a.market_source, 0) + 1

    market_coverage_count = sum(1 for a in pool if a.has_market)
    market_coverage_pct = market_coverage_count / max(len(pool), 1)
    if market_coverage_pct < 0.5:
        warnings.append(
            f"Market coverage is low ({market_coverage_pct:.0%} of assets). "
            "Some trades may have partial or no market scoring."
        )

    # An IDP league whose pool contains no priced IDP assets is the
    # exact failure this engine used to hit silently.  Say so.
    #
    # This check read ``p["position"]`` off the legacy ``players`` dict —
    # the SAME absent key that caused the failure it was written to
    # announce.  ``league_has_idp`` was therefore permanently False and
    # the warning could never fire, while ``marketCoveragePercent``
    # reported 100% because the unpriced defenders had already been
    # dropped from the pool upstream.  A detector that reads the broken
    # input is not a detector.
    _positions = positions or {}
    league_has_idp = any(
        _norm_pos(_positions.get(name) or str((p or {}).get("position", "")) or "") in IDP_POSITIONS
        for name, p in players.items()
        if isinstance(p, dict)
    )
    idp_priced = sum(market_coverage.get(key, 0) for key in IDP_MARKET_KEYS)
    if league_has_idp and idp_priced == 0:
        warnings.append(
            "No IDP asset carries an IDPTradeCalc value, so this result is "
            "offense-only. IDP trades cannot be evaluated without IDP market data."
        )

    for opp_name in opponent_teams:
        if opp_name == my_team:
            continue
        opp_roster = _resolve_roster(opp_name, sleeper_teams, pool_by_name, pick_aliases)
        if not opp_roster:
            warnings.append(f"Could not resolve opponent team '{opp_name}'.")
            continue

        # Exclude any assets that are on my team from opponent pool
        opp_filtered = [a for a in opp_roster if a.name not in my_names]
        if not opp_filtered:
            continue
        opponents_analyzed += 1

        # Generate candidates for each trade shape
        all_trades.extend(_generate_1for1(my_roster, opp_filtered))
        all_trades.extend(_generate_2for1(my_roster, opp_filtered))
        all_trades.extend(_generate_1for2(my_roster, opp_filtered))

    # Deduplicate
    all_trades = _deduplicate(all_trades)
    # Same give side, a receive side another package strictly contains,
    # and a worse score: nothing a reader should ever choose (W09-F012).
    pre_dominance = len(all_trades)
    all_trades = _prune_dominated(all_trades)
    dominated_pruned = pre_dominance - len(all_trades)

    # ── Light roster-fit adjustment ──────────────────────────────────
    # Slightly reward trades that shed surplus positions or fill weak ones.
    my_pos_counts: dict[str, int] = {}
    for a in my_roster:
        if a.position:
            my_pos_counts[a.position] = my_pos_counts.get(a.position, 0) + 1

    for tc in all_trades:
        fit_bonus = 0.0
        fit_reasons: list[str] = []
        for a in tc.give:
            if my_pos_counts.get(a.position, 0) >= ROSTER_SURPLUS_THRESHOLD:
                fit_bonus += 1.0
                fit_reasons.append(f"sheds {a.position} surplus")
        for a in tc.receive:
            if my_pos_counts.get(a.position, 0) <= ROSTER_WEAK_THRESHOLD:
                fit_bonus += 1.5
                fit_reasons.append(f"fills {a.position} need")
        if fit_bonus > 0:
            tc.arbitrage_score += fit_bonus
            tc.flags.append("roster_fit")
            tc.ranking_factors["rosterFitBonus"] = round(fit_bonus, 2)
            tc.summary += " Roster fit: " + ", ".join(fit_reasons) + "."

    # Rank
    all_trades.sort(key=lambda t: t.arbitrage_score, reverse=True)

    # Keep only positive-arbitrage trades with positive board delta
    ranked = [t for t in all_trades if t.arbitrage_score > 0 and t.board_delta > 0]

    # ── Enforce full-coverage priority in top results ────────────────
    # Partial-coverage trades sort after every full-coverage trade so
    # premium recommendation slots stay with trustworthy ones.
    #
    # WS-J F-7: this was an if/else whose two branches were byte
    # identical (both ``full + partial``), gated on
    # ``len(full) >= PARTIAL_MARKET_MAX_RANK`` — a condition that could
    # not change the outcome.  Collapsed to the single expression both
    # arms already computed.
    full_cov = [t for t in ranked if t.ktc_coverage == "full"]
    partial_cov = [t for t in ranked if t.ktc_coverage != "full"]
    ranked = full_cov + partial_cov

    qualified_by_shape: dict[str, int] = {}
    for t in ranked:
        shape = t.package_shape()
        qualified_by_shape[shape] = qualified_by_shape.get(shape, 0) + 1

    capped = _fill_by_shape(ranked, max_results)
    returned_by_shape: dict[str, int] = {}
    for t in capped:
        shape = t.package_shape()
        returned_by_shape[shape] = returned_by_shape.get(shape, 0) + 1

    return {
        "trades": [t.to_dict() for t in capped],
        "metadata": {
            "myTeam": my_team,
            "opponentTeams": opponent_teams,
            "opponentsAnalyzed": opponents_analyzed,
            "myRosterSize": len(my_roster),
            "totalCandidatesEvaluated": len(all_trades),
            "totalQualified": len(ranked),
            "returned": len(capped),
            "assetPoolSize": len(pool),
            # F-6: which value scale this run used, and what it cost.
            "valueSource": "rankDerivedValue" if board_values is not None else "rawComposite",
            "assetsUnpricedByBoard": unpriced_by_board,
            # Picks no retail market published a price for.  They keep
            # their board value everywhere else; they are simply not
            # arbitrageable, because there is no market number to
            # arbitrage against.
            "picksWithoutMarketAnchor": len(picks_without_market),
            "picksWithoutMarketAnchorNames": picks_without_market,
            # What the candidate space held, and what was served from
            # it, per package shape.  A shape missing from
            # ``returnedByShape`` while present in ``qualifiedByShape``
            # is a slot-allocation fact, not an absence of candidates.
            "qualifiedByShape": qualified_by_shape,
            "returnedByShape": returned_by_shape,
            # Diversity controls, stated so a reader can tell a thin
            # list from a capped one.
            "dominatedPruned": dominated_pruned,
            "maxGiveAssetAppearances": MAX_GIVE_ASSET_APPEARANCES,
            "distinctGiveAssetsReturned": len(
                {a.name for t in capped for a in t.give}
            ),
            # The gain each trade's ``boardEdge`` is a fraction OF.
            # Named because it changed: it was the give side alone,
            # which is a lopsidedness score rather than a rate of gain
            # (W09-F002).
            "boardGainBasis": "largerSide",
            "marketTopNFilter": market_top_n,
            "marketCoverage": market_coverage,
            "marketCoveragePercent": round(market_coverage_pct * 100, 1),
            # How many returned trades span both retail markets. Zero
            # and "we never checked" are different states, so this is
            # stamped unconditionally rather than only when non-zero.
            "mixedMarketTrades": sum(1 for t in capped if len(t.markets_used()) > 1),
            # Deprecated aliases — the gate is per-market now.
            "ktcTopNFilter": market_top_n,
            "ktcCoveragePercent": round(market_coverage_pct * 100, 1),
        },
        "warnings": warnings,
    }
