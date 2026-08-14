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
            d: dict[str, Any] = {
                "name": a.name,
                "position": a.position,
                "team": a.team,
                "modelValue": a.model_value,
                "ktcValue": a.ktc_value,
                "ktcRank": a.ktc_rank,
            }
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
            "packageSize": f"{len(self.give)}-for-{len(self.receive)}",
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
    parts = [
        f"{edge_label}: {verb} {abs(board_delta):,} board value " f"({board_gain_pct:+.0%})",
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


def build_asset_pool(
    players: dict[str, Any],
    *,
    market_top_n: int | None = None,
    ktc_top_n: int | None = None,
    board_values: dict[str, int] | None = None,
    positions: dict[str, str] | None = None,
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
) -> list[Asset]:
    """Resolve a Sleeper team name to a list of Asset objects."""
    for t in sleeper_teams:
        if t.get("name") == team_name:
            players = t.get("players") or []
            result = []
            for pname in players:
                key = pname.strip()
                asset = pool_by_name.get(key)
                if asset is None:
                    # Try case-insensitive
                    for k, v in pool_by_name.items():
                        if k.lower() == key.lower():
                            asset = v
                            break
                if asset is not None:
                    result.append(asset)
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

    # One canonical value per asset.  ``_mv`` used to substitute a
    # second, IDP-disabled board whenever neither side held a defender
    # (W29-F001), so an asset's model value depended on the composition
    # of the trade it appeared in.
    def _mv(a: Asset) -> int:
        return a.model_value

    give_model = sum(_mv(a) for a in give)
    recv_model = sum(_mv(a) for a in receive)
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
        max_recv = max(_mv(a) for a in receive)
        if max_recv >= ELITE_THRESHOLD:
            if give_model < recv_model * ELITE_MULTI_MIN_RATIO:
                return None
            flags.append("elite_target")
        # ── Package anchor quality ───────────────────────────────────
        # At least one give piece must be a real starter-quality asset,
        # not just two bench stashes that happen to sum high enough.
        max_give = max(_mv(a) for a in give)
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
    if all(_mv(a) < JUNK_THRESHOLD for a in give):
        return None
    if all(_mv(a) < JUNK_THRESHOLD for a in receive):
        return None

    # Arbitrage score: how much we gain on our board while the opponent
    # sees a fair/favorable deal on KTC.
    # Higher = better arbitrage.
    board_gain_norm = board_delta / max(give_model, 1)
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
    # The legacy ``players`` dict has no ``position`` key, so without
    # this every IDP asset routes to the KTC board and is dropped.
    positions = positions_from_contract(contract) if contract else None
    pool = build_asset_pool(
        players,
        market_top_n=market_top_n,
        board_values=board_values,
        positions=positions,
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

    my_roster = _resolve_roster(my_team, sleeper_teams, pool_by_name)
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
        opp_roster = _resolve_roster(opp_name, sleeper_teams, pool_by_name)
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

    capped = ranked[:max_results]

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
