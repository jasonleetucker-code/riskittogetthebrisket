"""Angle finder — player-specific trade-target arbitrage.

Given a user-owned player (or package of players), find players or
player-packages on other teams where the trade leans in the user's
favour under their own league's calibrated rankings but looks
fair-or-worse to the counterparty on the market index their position
indexes. Lets the user pitch trades that their leaguemates will
accept (the market they consult says "even") while actually gaining
value in their league-specific calibrated board.

Market anchor is per-position:
  * Offense (QB/RB/WR/TE), picks, everything else → KTC
  * IDP (DL/LB/DB) → IDP Trade Calculator

IDP leaguemates evaluate IDP trades on IDPTC, not KTC. A trade
between two DLs that looks 5% over-market on KTC is irrelevant — the
counterparty looks at IDPTC. So each player's "market value" is
drawn from the source their position indexes.

``find_angles`` handles the single-player pivot. ``find_angle_packages``
extends to multi-player offers: give it a list of your players and it
returns multi-player counter-packages whose size is within ±1 of your
offer (e.g. offering 4 players → returns 3-, 4-, and 5-player
counter-offers). Same arbitrage math; combinations are evaluated per
opposing team with the candidate pool clamped to each team's top-N
players by your calibrated value so the search stays fast.

Per-PLAYER routing was never the bug; per-PACKAGE totalling was
──────────────────────────────────────────────────────────────────
:func:`_market_source_for` has always sent each player to the right
board.  What used to happen next was::

    market_sum = sum(p["market_value"] for p in combo)

over a combo that nothing constrained to one board.  A package holding
a TE and a linebacker therefore added a KTC number to an IDPTC number
and produced a total denominated in no market at all.  It was not a
rounding-level error either: on the 2026-07-26 board Brock Bowers is
KTC 9,882 and IDPTC 8,975, so a Bowers + Schwesinger offer summed to
15,549 against a true IDPTC total of 14,642 — 6.2% of overstatement
handed straight to ``market_gain_pct``, which is the field the ±5%
plausibility gate reads.

Package totals now go through
:func:`src.league_intel.cross_market.value_package`, which prices a
package **entirely inside one market** (offense-only → ``ktcSfTep``;
any IDP present → ``idpTradeCalc``, the only board spanning both
universes), and through
:func:`~src.league_intel.cross_market.compare_packages`, which decides
whether the resulting verdict survives its own uncertainty.  Nothing
about single-market valuation is re-implemented here — see ADR-010 and
that module's docstring for why the exchange-rate assumption is
stamped rather than buried.

What this deliberately does NOT fix
───────────────────────────────────
Each SIDE is valued inside one market, but the two sides can still
land on different markets — an offense-only offer prices on KTC while
an IDP-bearing counter prices on IDPTC.  That is the comparison
``compare_packages`` is built to take, and it is defensible because
the two boards are measured to share a scale (pooled IDPTC/KTC ratio
0.9997, Spearman 0.990, n=476).  The residual doubt is not ignored: it
is exactly what the IDP-bearing side's ``uncertainty_band`` carries
into the straddle check.  Forcing both sides onto one board would need
a market argument ``value_package`` does not expose, and inventing one
here would put a second single-market implementation in the tree.

``find_angles`` (the 1-for-1 pivot) is untouched: it compares two
single assets, so there is no cross-market sum to constrain.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Sequence

from src.league_intel.cross_market import (
    NORMALIZATION_VERSION,
    PackageValuation,
    compare_packages,
    value_package,
)

# Trade-fairness math is delegated to ``src.trade.ktc_va``, the Python
# port of KTC's actual algorithm (PR #335 ported it to JS; this
# replaced the V2 regression-fit constants in 2026-04-27).  The legacy
# V2 coefficients (calibrated against 13 trades) disagreed materially
# with what KTC.com displays, so the Angle Finder graded trades
# differently than the trade calculator did.
#
# Arbitrage math was previously pure sum-of-raw-totals, which is wrong
# for uneven sizes: 3 stars for 4 scrubs can look fair on market and a
# big win on my-value in raw terms, yet no leaguemate would accept it.
# VA injects the consolidation premium on the SMALLER side — so the
# side receiving more studs sees its effective total climb, and the
# thresholds get evaluated on the adjusted numbers.
from src.packages import EligibilityPolicy as _EligibilityPolicy
from src.trade.ktc_va import (
    adjusted_pair_totals as _adjusted_pair_totals,  # noqa: F401
    ktc_adjust_package,
)
from src.utils.name_clean import normalize_position as _normalize_position

# Raw spellings, kept as-is because ``server.py`` imports this set to
# decide whether a caller's ``positions`` request implies an IDP
# opt-in, and that check runs against un-normalized request tokens.
# Position DECISIONS inside this module go through
# :func:`_is_idp_position`, which normalizes first, so a spelling
# missing from this literal can no longer route a defender to a board
# that prices no defenders (the #556 defect in ``finder.py``).
_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"}
)

# The three canonical buckets ``POSITION_ALIASES`` collapses IDP
# spellings to — same set ``cross_market`` tests against, so routing
# here and valuation there cannot disagree about what an IDP is.
_IDP_FAMILIES: frozenset[str] = frozenset({"DL", "LB", "DB"})


def _value_adjustment(small: Sequence[float], large: Sequence[float]) -> float:
    """KTC's VA from the perspective of ``small`` as team1.

    Returns the VA magnitude when KTC awards it to the ``small`` side
    (``small`` is team1 → side==1), else 0.0.  Thin compat shim around
    :func:`ktc_adjust_package` so existing callers (tests, importers)
    keep working with the legacy float-return signature.

    The legacy V2 implementation lived inline here; it was replaced
    with KTC's actual algorithm via :mod:`src.trade.ktc_va` so the
    Angle Finder grades trades the same way the trade calculator
    displays them (PR follow-up to #335).
    """
    small_sorted = sorted((float(v) for v in small), reverse=True)
    large_sorted = sorted((float(v) for v in large), reverse=True)
    if not small_sorted or not large_sorted:
        return 0.0
    result = ktc_adjust_package(small_sorted, large_sorted)
    if not result.displayed or result.value <= 0 or result.side != 1:
        return 0.0
    return float(result.value)


def _is_idp_position(position: Any) -> bool:
    """True for any spelling of a defensive position.

    Normalizes before testing so ``"EDGE"``/``"CB"``/``"MLB"`` and any
    future spelling ``POSITION_ALIASES`` learns are all caught, then
    falls back to the raw literal set for anything normalization leaves
    alone.  Strictly wider than the old raw-membership test.
    """
    raw = str(position or "").strip().upper()
    if not raw:
        return False
    return _normalize_position(raw) in _IDP_FAMILIES or raw in _IDP_POSITIONS


def _market_source_for(position: str | None) -> str:
    """Return the canonicalSiteValues key the counterparty would
    consult for this position.  IDP positions compare on IDPTC;
    everything else (offense, picks, kickers, etc.) compares on
    KTC's TE+ board — the canonical KTC retail signal as of
    2026-04-28 when standard ``ktc`` was retired from the blend.

    ``_value_pair`` falls back to the legacy ``"ktc"`` key when a
    fixture only carries the standard board, so callers that
    haven't been migrated keep working.
    """
    if _is_idp_position(position):
        return "idpTradeCalc"
    return "ktcSfTep"


# ── Package-level market valuation (ADR-010) ─────────────────────────


def _market_values(pkg: PackageValuation) -> list[float]:
    """Per-asset values from a package valuation, in input order.

    These are the numbers the VA step and the totals must be built
    from: every one of them is denominated in ``pkg.market``.
    """
    return [float(a.normalized_market_value or 0.0) for a in pkg.assets]


def _restate_on(pkg: PackageValuation, adjusted_total: float) -> PackageValuation:
    """``pkg`` restated on its VA-adjusted total.

    ``compare_packages`` has to adjudicate the same quantity the caller
    gates on, and Angle gates on the KTC-Value-Adjustment-adjusted
    gain, not the raw sum.  Handing it the raw totals would have it
    certify a verdict about a number nothing downstream uses.

    The band is scaled with the total rather than carried across in
    absolute points: it represents a proportion of the package's value
    that rests on the offense<->IDP exchange rate, and a consolidation
    premium does not make that rate any better known.  Scaling also
    errs toward the wider band on the side receiving the VA, which
    matches ``cross_market``'s posture of withholding near-boundary
    verdicts rather than asserting them.
    """
    total = pkg.total
    if total is None or total <= 0:
        return pkg
    scale = adjusted_total / total
    return replace(
        pkg,
        total=adjusted_total,
        uncertainty_band=pkg.uncertainty_band * scale,
    )


def _market_stamp(pkg: PackageValuation, *, verbose: bool = True) -> dict[str, Any]:
    """Provenance for a package total, renderable by the caller.

    ``verbose=False`` for the per-candidate stamp.  The prose warnings
    run ~500 characters and are near-identical across every package on
    the same market, so repeating them on 50 candidates adds ~25 KB to
    a response for no information the fixed side does not already
    carry.  The version string is likewise constant and lives once in
    ``market_diagnostics``.
    """
    stamp = {
        "market": pkg.market,
        "market_strategy": pkg.strategy.value,
        "market_uncertainty_band": int(round(pkg.uncertainty_band)),
    }
    if verbose:
        stamp["market_normalization_version"] = pkg.normalization_version
        stamp["market_warnings"] = list(pkg.warnings)
    return stamp


def _unvaluable_stamp(pkg: PackageValuation) -> dict[str, Any]:
    """Provenance for a package that has no defensible total."""
    return {
        "market": None,
        "market_strategy": pkg.strategy.value,
        "market_uncertainty_band": 0,
        "market_normalization_version": pkg.normalization_version,
        "market_unvaluable_reason": pkg.suppressed_reason,
        "market_unvaluable_label": pkg.label,
    }


def _package_players(
    entries: Iterable[dict[str, Any]],
    pkg: PackageValuation,
) -> list[dict[str, Any]]:
    """Player rows whose ``market_source`` matches the package total.

    ``value_package`` preserves input order, so asset *i* is entry *i*.
    Labelling each player with the board the PACKAGE was priced on —
    rather than the board that player's position indexes — is the whole
    point: a WR inside an IDP package really was priced on IDPTC, and
    the UI badge should say so.

    ``market_source`` is deliberately ``pkg.market`` and not the
    asset's ``raw_market_source``.  On the scalar-fallback path those
    two differ: an asset the target board does not price is read off
    the OTHER board and converted, so its raw source would badge a
    value that is no longer denominated in it.  The raw board is kept,
    but under ``market_converted_from``, where it reads as provenance
    instead of as a contradiction of the number beside it.
    """
    rows: list[dict[str, Any]] = []
    for entry, asset in zip(entries, pkg.assets):
        converted = bool(asset.converted)
        rows.append(
            {
                "name": entry["name"],
                "position": entry["position"],
                "my_value": int(entry["my_value"]),
                "market_value": int(round(float(asset.normalized_market_value or 0.0))),
                "market_source": pkg.market or asset.raw_market_source,
                "market_converted": converted,
                "market_converted_from": asset.raw_market_source if converted else None,
            }
        )
    return rows


def _new_market_diagnostics() -> dict[str, Any]:
    return {
        "combos_valued": 0,
        "unvaluable": 0,
        "withheld_uncertain": 0,
        "reasons": {},
        "normalization_version": NORMALIZATION_VERSION,
    }


def _note_reason(diag: dict[str, Any], reason: str | None) -> None:
    key = (reason or "unspecified")[:160]
    diag["reasons"][key] = diag["reasons"].get(key, 0) + 1


def _diagnostic_warnings(diag: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if diag["unvaluable"]:
        out.append(
            f"{diag['unvaluable']} package(s) excluded: no single market prices every "
            "asset in them, and Angle will not substitute a cross-board sum."
        )
    if diag["withheld_uncertain"]:
        out.append(
            f"{diag['withheld_uncertain']} package(s) withheld: the market gap sits "
            "inside the cross-market uncertainty band around the plausibility gate, "
            "so the verdict is too close to call."
        )
    return out


def _value_pair(row: dict[str, Any]) -> tuple[float, float, str] | None:
    """Return (my_value, market_value, market_source_key) for a row.

    ``market_source_key`` reflects which key was actually read —
    ``"idpTradeCalc"`` for IDP rows, ``"ktcSfTep"`` for offense
    rows (with a graceful fallback to ``"ktc"`` when the row
    only carries the legacy standard board, e.g. older fixtures).
    Returns ``None`` when neither value is populated.

    """
    my_val = row.get("rankDerivedValue")
    sites = row.get("canonicalSiteValues") or {}
    source = _market_source_for(row.get("position"))
    market_val = sites.get(source) if isinstance(sites, dict) else None
    if market_val is None and source == "ktcSfTep" and isinstance(sites, dict):
        # Pre-supersession fixtures (and any production row missing
        # the TE+ vote for some reason) still expose the legacy
        # board — read it and report the actual key consulted.
        legacy_val = sites.get("ktc")
        if legacy_val is not None:
            market_val = legacy_val
            source = "ktc"
    try:
        my_num = float(my_val) if my_val is not None else 0.0
        market_num = float(market_val) if market_val is not None else 0.0
    except (TypeError, ValueError):
        return None
    if my_num <= 0 or market_num <= 0:
        return None
    return my_num, market_num, source


def find_angles(
    players_array: list[dict[str, Any]],
    selected_player_name: str,
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_market_gain_pct: float = 5.0,
    limit: int = 50,
    target_team_owner_id: str | None = None,
) -> dict[str, Any]:
    """Find trade-target candidates that lean in the user's favour.

    Each player's "market value" is drawn from the source that indexes
    their position — IDP Trade Calculator for DL/LB/DB, KTC for
    everyone else. The counterparty looks at the same market their
    player is listed in, so the threshold check matches their
    perspective.

    Parameters
    ----------
    players_array
        Canonical player rows (from build_api_data_contract's
        ``playersArray``). Each row must carry ``canonicalName``,
        ``rankDerivedValue`` (the calibrated my-league value), and
        a market value at ``canonicalSiteValues.idpTradeCalc`` for
        IDP or ``canonicalSiteValues.ktc`` for offense.
    max_market_gain_pct
        Maximum market value gain on the target side for the trade
        to still look "plausible" to the counterparty. Default 5%.
    limit
        Cap on returned candidates (sorted by arbitrage score desc).

    Returns
    -------
    dict
        ``{selected: {...}, candidates: [{...}, ...], warnings: [...]}``
        Market value is in ``market_value``; market source (``ktc``
        vs ``idpTradeCalc``) is in ``market_source``.
    """
    warnings: list[str] = []

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if name and name not in by_name:
            by_name[name] = row

    selected_row = by_name.get(selected_player_name)
    if not selected_row:
        return {
            "selected": None,
            "candidates": [],
            "warnings": [f"Player {selected_player_name!r} not found in the current board."],
        }

    pair = _value_pair(selected_row)
    if pair is None:
        sel_source = _market_source_for(selected_row.get("position"))
        return {
            "selected": {
                "name": selected_player_name,
                "my_value": selected_row.get("rankDerivedValue"),
                "market_value": None,
                "market_source": sel_source,
            },
            "candidates": [],
            "warnings": [
                f"{selected_player_name!r} is missing a my-league or {sel_source} value "
                "— Angle needs both to compute the arbitrage."
            ],
        }
    my_val_selected, market_val_selected, selected_market_source = pair

    # Build reverse index: canonical name -> owner's team dict.
    owner_by_player: dict[str, dict[str, Any]] = {}
    my_team_name: str | None = None
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner == selected_team_owner_id:
            my_team_name = team.get("name")
        for p in team.get("players") or []:
            owner_by_player[str(p)] = team

    if my_team_name is None:
        warnings.append(
            f"Owner {selected_team_owner_id!r} not found in sleeper roster list; "
            "results will include all other teams."
        )

    candidates: list[dict[str, Any]] = []
    for target_name, target_row in by_name.items():
        if target_name == selected_player_name:
            continue
        owner_team = owner_by_player.get(target_name)
        # Skip same-team targets (trading with yourself is nonsense).
        if (
            owner_team is not None
            and str(owner_team.get("ownerId") or "") == selected_team_owner_id
        ):
            continue
        if target_team_owner_id:
            if owner_team is None:
                continue
            if str(owner_team.get("ownerId") or "") != target_team_owner_id:
                continue
        target_pair = _value_pair(target_row)
        if target_pair is None:
            continue
        my_val_target, market_val_target, target_market_source = target_pair

        my_gain = my_val_target - my_val_selected
        market_gain = market_val_target - market_val_selected
        my_gain_pct = 100.0 * my_gain / my_val_selected
        market_gain_pct = 100.0 * market_gain / market_val_selected

        if my_gain_pct < min_my_gain_pct:
            continue
        if market_gain_pct > max_market_gain_pct:
            continue

        candidates.append(
            {
                "name": target_name,
                "position": str(target_row.get("position") or ""),
                "team": owner_team.get("name") if owner_team else "(free agent)",
                "owner_id": str(owner_team.get("ownerId") or "") if owner_team else "",
                "my_value": int(my_val_target),
                "market_value": int(market_val_target),
                "market_source": target_market_source,
                "my_gain": int(round(my_gain)),
                "market_gain": int(round(market_gain)),
                "my_gain_pct": round(my_gain_pct, 2),
                "market_gain_pct": round(market_gain_pct, 2),
                "arb_score": round(my_gain_pct - market_gain_pct, 2),
            }
        )

    candidates.sort(key=lambda c: c["arb_score"], reverse=True)
    candidates = candidates[: max(1, int(limit))]

    return {
        "selected": {
            "name": selected_player_name,
            "position": str(selected_row.get("position") or ""),
            "team": my_team_name,
            "my_value": int(my_val_selected),
            "market_value": int(market_val_selected),
            "market_source": selected_market_source,
        },
        "candidates": candidates,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_market_gain_pct": max_market_gain_pct,
            "limit": limit,
            "target_team_owner_id": target_team_owner_id or "",
        },
        "warnings": warnings,
    }


#: Angle decides eligibility upstream; the substrate must not re-filter.
_ANGLE_POLICY = _EligibilityPolicy(min_value=None, allow_unknown_value=True, require_position=False)


# ── Package construction mechanics — DELEGATED (V1-36 / C3-PKG-01) ────
#
# This module had three hand-rolled ``combinations`` enumerations: the
# seed/filler split and the per-team default in ``find_angle_packages``, and
# the pool sweep in ``find_acquisition_packages``.  They are the same mechanic
# — build every side of size N from a pool, without repeating an asset and
# without emitting the same side twice — and it now has one owner in
# ``src/packages``.
#
# What did NOT move: the eligibility filters above (IDP inclusion, value
# floors, team scoping), the pool sort, the per-team cap, ``_make_candidate``
# and the arbitrage objective.  Those are this product's question.
#
# Angle's pool entries are plain dicts, so the accessors are explicit.  They
# carry no canonical asset id, which means the dedup identity here falls back
# to names — the substrate reports that rather than letting it pass as an id
# key.
def _angle_sides(pool, sizes, *, required=()):
    """Every candidate package side, via the canonical substrate."""
    from src.packages import enumerate_sides  # noqa: PLC0415

    sides, _report = enumerate_sides(
        pool,
        sizes,
        required=required,
        # Eligibility is already decided upstream by this module's own
        # filters; re-applying a generic one here would silently drop
        # entries angle deliberately kept (a positionless pick row, say).
        policy=_ANGLE_POLICY,
        adapt=False,
    )
    for side in sides:
        yield tuple(a.source for a in side)


def _angle_pool_assets(entries):
    """Project angle's dict pool entries onto the substrate's asset view."""
    from src.packages import PackageAsset  # noqa: PLC0415

    def _value(entry):
        # A missing ``my_value`` is UNKNOWN, and a measured 0 is a real zero.
        # ``float(x or 0.0) or None`` collapsed both to None, which is a
        # decision-path fabrication in the ordering direction: pool order
        # decides what survives truncation, so "we have no number" and "the
        # number is zero" must not become the same thing.
        raw = entry.get("my_value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)

    return [
        PackageAsset(
            asset_id="",
            name=str(e.get("name") or ""),
            position=str(e.get("position") or ""),
            value=_value(e),
            source=e,
        )
        for e in entries
    ]


def find_angle_packages(
    players_array: list[dict[str, Any]],
    selected_player_names: list[str],
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_market_gain_pct: float = 5.0,
    limit: int = 50,
    candidate_pool_per_team: int = 25,
    per_team_limit: int = 4,
    positions: list[str] | None = None,
    min_player_my_value: float = 0.0,
    target_team_owner_ids: list[str] | None = None,
    seed_player_names: list[str] | None = None,
    include_idp: bool = False,
) -> dict[str, Any]:
    """Find multi-player counter-packages for a user-built offer.

    Parameters
    ----------
    selected_player_names
        List of canonical player names on the user's roster that
        constitute the OFFER side of the trade.
    selected_team_owner_id
        Sleeper ``ownerId`` identifying the user's team (excluded
        from candidate pool).
    candidate_pool_per_team
        Top-N players (by ``rankDerivedValue``) considered per
        opposing team when enumerating combinations. Caps the
        combinatorial explosion; 25 × size-5 ≈ 53k combos per team
        which completes comfortably inside a request.
    per_team_limit
        Max packages kept per opposing team (by arb score desc)
        before the global ``limit`` is applied. Default 4 — keeps
        one team from swamping the results with 50 variations of
        the same trade. Set to a large number to disable.
    positions
        When non-empty, restrict the candidate pool to players whose
        ``position`` matches one of these tokens (case-insensitive).
        ``None`` or empty list = any position.
    min_player_my_value
        Minimum ``rankDerivedValue`` a player must have to be
        considered in the candidate pool. Caller uses this to say
        "don't suggest filler-depth guys in my counter-package."
    include_idp
        When ``False`` (default) IDP positions (DL/LB/DB and their
        sub-positions) are filtered OUT of the candidate pool entirely.
        Most managers don't value IDP the way KTC/our-board scores
        them, so the default keeps counter-packages offense+picks
        only. Set ``True`` (or explicitly include an IDP player in
        the offer / seeds) to allow IDP candidates. Offer-side and
        user-selected seeds are never filtered — the user's explicit
        choices always win.

    Returns
    -------
    dict
        ``{offer, candidates, thresholds, warnings}`` where
        ``candidates`` is a list of package dicts, each with
        ``{team, size, players, my_total, market_total, my_gain_pct,
        market_gain_pct, arb_score}``. Sorted by ``arb_score`` desc.
        Market value is per-position: IDPTC for DL/LB/DB, KTC for
        offense/picks/other. Individual player rows carry
        ``market_value`` and ``market_source`` so the UI can label
        correctly.

    The counter-package size is constrained to ``{N-1, N, N+1}``
    where ``N`` is the offered-player count. Size ``0`` is skipped
    when ``N == 1`` (that's what :func:`find_angles` is for).
    """
    warnings: list[str] = []

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if name and name not in by_name:
            by_name[name] = row

    # Resolve offer-side rows; drop any with missing values and warn.
    offer_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in selected_player_names:
        row = by_name.get(name)
        if not row:
            missing.append(name)
            continue
        pair = _value_pair(row)
        if pair is None:
            missing.append(name)
            continue
        offer_rows.append(row)
    if missing:
        warnings.append(
            f"Dropped {len(missing)} player(s) from the offer that have no "
            f"my-value or market value: {', '.join(missing[:5])}"
            + (" …" if len(missing) > 5 else "")
        )
    if not offer_rows:
        return {
            "offer": {"players": [], "size": 0, "my_total": 0, "market_total": 0},
            "candidates": [],
            "warnings": warnings or ["No valid offer-side players."],
        }

    offer_my_total = sum(
        _value_pair(r)[0]
        for r in offer_rows  # type: ignore[index]
    )
    offer_size = len(offer_rows)
    diag = _new_market_diagnostics()

    # Offer side: ONE market for the whole package, or no total at all.
    # The user picks these names freely, with no IDP filter in the way,
    # so this is the side where a mixed-board sum was reachable from the
    # UI without any opt-in.
    offer_pkg = value_package(offer_rows)
    offer_entries = [
        {
            "name": str(r.get("canonicalName") or r.get("displayName") or ""),
            "position": str(r.get("position") or ""),
            "my_value": _value_pair(r)[0],  # type: ignore[index]
        }
        for r in offer_rows
    ]
    if not offer_pkg.is_rankable:
        _note_reason(diag, offer_pkg.suppressed_reason)
        diag["unvaluable"] += 1
        warnings.append(
            offer_pkg.label or "Offer cannot be valued on a single market — no results."
        )
        return {
            "offer": {
                "team": None,
                "size": offer_size,
                "players": [
                    {
                        "name": e["name"],
                        "position": e["position"],
                        "my_value": int(e["my_value"]),
                        "market_value": 0,
                        "market_source": None,
                    }
                    for e in offer_entries
                ],
                "my_total": int(round(offer_my_total)),
                "market_total": 0,
                **_unvaluable_stamp(offer_pkg),
            },
            "candidates": [],
            "market_diagnostics": diag,
            "warnings": warnings,
        }
    offer_market_total = float(offer_pkg.total or 0.0)
    if offer_pkg.uncertainty_band > 0:
        # One line in the UI banner; the full measured/assumed wording
        # lives in the offer block's ``market_warnings`` so a caller
        # that wants it can render it without burying the page.
        warnings.append(
            f"Offer priced on {offer_pkg.market} because it spans offense and IDP; "
            f"±{int(round(offer_pkg.uncertainty_band))} pts of that total rests on an "
            "assumed offense<->IDP exchange rate."
        )

    # Target sizes: N-1, N, N+1 — never less than 1.
    target_sizes = sorted({max(1, offer_size - 1), offer_size, offer_size + 1})

    # Normalise position filter.
    position_filter: set[str] | None = None
    if positions:
        position_filter = {str(p).strip().upper() for p in positions if str(p).strip()}
        if not position_filter:
            position_filter = None
    min_my_value_floor = max(0.0, float(min_player_my_value or 0.0))

    # Build per-team candidate pool, filtered + capped.
    my_team_name: str | None = None
    teams_pool: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    offer_name_set = {str(r.get("canonicalName") or "") for r in offer_rows}
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner == selected_team_owner_id:
            my_team_name = team.get("name")
            continue
        pool: list[dict[str, Any]] = []
        for pname in team.get("players") or []:
            pname = str(pname)
            if pname in offer_name_set:
                continue  # never suggest trading for your own player
            row = by_name.get(pname)
            if not row:
                continue
            pair = _value_pair(row)
            if pair is None:
                continue
            my_v = pair[0]
            # Per-player filters: position allow-list, my-value floor,
            # and the IDP gate. IDP players get filtered out of the
            # candidate pool by default because most leaguemates don't
            # gravitate toward them — setting include_idp=True (or an
            # IDP position in ``positions``) re-admits them.
            row_pos = str(row.get("position") or "").strip().upper()
            if position_filter is not None and row_pos not in position_filter:
                continue
            if not include_idp and _is_idp_position(row_pos):
                continue
            if my_v < min_my_value_floor:
                continue
            pool.append(
                {
                    "name": pname,
                    "position": str(row.get("position") or ""),
                    "my_value": my_v,
                    # ``row`` is the payload: package market values are
                    # produced by ``value_package`` from the contract
                    # row, never by re-reading a per-position site key.
                    "row": row,
                }
            )
        pool.sort(key=lambda p: -p["my_value"])
        pool = pool[:candidate_pool_per_team]
        teams_pool.append((team, pool))

    # Offer-side value lists (sorted descending) used by the VA path
    # below. We keep raw totals available for display/back-compat.
    offer_my_values = sorted(
        (float(_value_pair(r)[0]) for r in offer_rows),
        reverse=True,  # type: ignore[index]
    )
    # Market side comes from the single-market valuation, NOT from
    # per-player ``_value_pair`` reads — that plain sum was the defect.
    offer_market_values = sorted(_market_values(offer_pkg), reverse=True)

    # Normalise target-team + seed inputs for constructed-package mode.
    target_ids: set[str] = {str(t).strip() for t in (target_team_owner_ids or []) if str(t).strip()}
    seed_names_requested = [str(n).strip() for n in (seed_player_names or []) if str(n).strip()]

    candidates: list[dict[str, Any]] = []
    seed_names_set: set[str] = set()

    def _row_to_pool_entry(row: dict[str, Any]) -> dict[str, Any] | None:
        pair = _value_pair(row)
        if pair is None:
            return None
        return {
            "name": str(row.get("canonicalName") or row.get("displayName") or ""),
            "position": str(row.get("position") or ""),
            "my_value": pair[0],
            "row": row,
        }

    def _make_candidate(
        combo: tuple[dict[str, Any], ...],
        team_label: str,
        owner_id_label: str,
    ) -> dict[str, Any] | None:
        # Apply KTC-style Value Adjustment so consolidation packages
        # (e.g. 3 studs vs 4 filler pieces whose raws happen to match)
        # don't slip through the thresholds on pure sum-of-raws.
        #
        # My-value gate runs FIRST and unchanged. It is pure arithmetic
        # on values already in hand, it rejects the overwhelming
        # majority of combos, and both gates are conjunctive — so
        # ordering it ahead of the market valuation is free and keeps
        # ``value_package`` off the hot path.
        counter_my_values = [p["my_value"] for p in combo]
        (
            counter_my_adj,
            offer_my_adj,
            counter_my_va,
            offer_my_va,
        ) = _adjusted_pair_totals(counter_my_values, offer_my_values)
        if offer_my_adj <= 0:
            return None
        my_gain_pct = 100.0 * (counter_my_adj - offer_my_adj) / offer_my_adj
        if my_gain_pct < min_my_gain_pct:
            return None

        # Counter side: one market for the whole package, or nothing.
        counter_pkg = value_package([p["row"] for p in combo])
        diag["combos_valued"] += 1
        if not counter_pkg.is_rankable:
            diag["unvaluable"] += 1
            _note_reason(diag, counter_pkg.suppressed_reason)
            return None
        counter_market_values = _market_values(counter_pkg)
        (
            counter_market_adj,
            offer_market_adj,
            counter_market_va,
            offer_market_va,
        ) = _adjusted_pair_totals(counter_market_values, offer_market_values)

        if offer_market_adj <= 0:
            return None
        market_gain_pct = 100.0 * (counter_market_adj - offer_market_adj) / offer_market_adj
        if market_gain_pct > max_market_gain_pct:
            return None

        # Does the verdict survive its own uncertainty?  For the
        # offense-only default both bands are zero and this is certain
        # by construction; it only bites when IDP is in play, which is
        # exactly when the offense<->IDP exchange rate is load-bearing.
        comparison = compare_packages(
            _restate_on(counter_pkg, counter_market_adj),
            _restate_on(offer_pkg, offer_market_adj),
            gate_pct=max_market_gain_pct,
        )
        if not comparison.verdict_certain:
            diag["withheld_uncertain"] += 1
            _note_reason(diag, comparison.suppressed_reason)
            return None

        my_sum = sum(counter_my_values)
        market_sum = float(counter_pkg.total or 0.0)
        return {
            "team": team_label,
            "owner_id": owner_id_label,
            "size": len(combo),
            "players": _package_players(combo, counter_pkg),
            "my_total": int(round(my_sum)),
            "market_total": int(round(market_sum)),
            "my_total_adjusted": int(round(counter_my_adj)),
            "market_total_adjusted": int(round(counter_market_adj)),
            "my_value_adjustment": int(round(counter_my_va)),
            "market_value_adjustment": int(round(counter_market_va)),
            "offer_my_total_adjusted": int(round(offer_my_adj)),
            "offer_market_total_adjusted": int(round(offer_market_adj)),
            "offer_my_value_adjustment": int(round(offer_my_va)),
            "offer_market_value_adjustment": int(round(offer_market_va)),
            "my_gain_pct": round(my_gain_pct, 2),
            "market_gain_pct": round(market_gain_pct, 2),
            "market_gain_low_pct": (
                round(comparison.gain_low_pct, 2) if comparison.gain_low_pct is not None else None
            ),
            "market_gain_high_pct": (
                round(comparison.gain_high_pct, 2) if comparison.gain_high_pct is not None else None
            ),
            "arb_score": round(my_gain_pct - market_gain_pct, 2),
            **_market_stamp(counter_pkg, verbose=False),
        }

    if target_ids:
        # ── Constructed-package mode ─────────────────────────────
        # User picked 1 or 2 specific opposing teams. Pool is the
        # union of those teams' candidates; all seed players are
        # required in every result (seeds bypass position/value
        # filters because the user explicitly asked for them).
        target_teams: list[dict[str, Any]] = []
        combined_pool_by_name: dict[str, dict[str, Any]] = {}
        owner_by_pool_name: dict[str, str] = {}
        # Seed ownership lookup: covers *all* players on target teams
        # (not just ones that survived the filter cuts into ``pool``),
        # so seed resolution is O(1) per seed instead of scanning every
        # target team's roster for each requested seed name.
        owner_by_all_player: dict[str, str] = {}
        target_team_names: list[str] = []
        target_team_owners: list[str] = []
        for team, pool in teams_pool:
            owner = str(team.get("ownerId") or "")
            if owner not in target_ids:
                continue
            target_teams.append(team)
            target_team_names.append(str(team.get("name") or ""))
            target_team_owners.append(owner)
            for entry in pool:
                combined_pool_by_name[entry["name"]] = entry
                owner_by_pool_name[entry["name"]] = owner
            for pname in team.get("players") or []:
                owner_by_all_player.setdefault(str(pname), owner)

        # Resolve seeds. Seeds must be owned by one of the target
        # teams and bypass the filter pool — they're mandatory.
        seed_entries: list[dict[str, Any]] = []
        missing_seeds: list[str] = []
        wrong_team_seeds: list[str] = []
        for sname in seed_names_requested:
            row = by_name.get(sname)
            if not row:
                missing_seeds.append(sname)
                continue
            # O(1) ownership lookup against the precomputed roster map.
            owner_of_seed = owner_by_all_player.get(sname)
            if owner_of_seed is None:
                wrong_team_seeds.append(sname)
                continue
            entry = _row_to_pool_entry(row)
            if entry is None:
                missing_seeds.append(sname)
                continue
            seed_entries.append(entry)
            # Ensure seeds are present in the combined pool so they
            # can participate in filter-respecting combo selection
            # (but seeds themselves bypass the filter cuts above).
            combined_pool_by_name.setdefault(entry["name"], entry)
            owner_by_pool_name.setdefault(entry["name"], owner_of_seed)
        if missing_seeds:
            warnings.append(
                f"Dropped {len(missing_seeds)} seed player(s) with missing data: "
                f"{', '.join(missing_seeds[:5])}" + (" …" if len(missing_seeds) > 5 else "")
            )
        if wrong_team_seeds:
            warnings.append(
                f"Ignored {len(wrong_team_seeds)} seed player(s) not on any selected "
                f"target team: {', '.join(wrong_team_seeds[:5])}"
                + (" …" if len(wrong_team_seeds) > 5 else "")
            )

        seed_names_set = {e["name"] for e in seed_entries}
        non_seed_pool = [
            e for e in combined_pool_by_name.values() if e["name"] not in seed_names_set
        ]
        # Sort non-seed pool by my_value for deterministic order.
        non_seed_pool.sort(key=lambda p: -p["my_value"])

        team_label = " + ".join(target_team_names) or "(selected teams)"
        owner_label = "+".join(target_team_owners) or ",".join(sorted(target_ids))

        for size in target_sizes:
            if size < len(seed_entries):
                continue  # can't fit all required seeds
            free_slots = size - len(seed_entries)
            if free_slots == 0:
                combo = tuple(seed_entries)
                cand = _make_candidate(combo, team_label, owner_label)
                if cand is not None:
                    candidates.append(cand)
                continue
            if len(non_seed_pool) < free_slots:
                continue
            for combo in _angle_sides(
                _angle_pool_assets(non_seed_pool),
                [size],
                required=_angle_pool_assets(seed_entries),
            ):
                cand = _make_candidate(combo, team_label, owner_label)
                if cand is not None:
                    candidates.append(cand)
    else:
        # ── Default mode: one team per candidate package ──
        # This is the existing behaviour — each opposing team
        # contributes its own packages independently.
        for team, pool in teams_pool:
            for combo in _angle_sides(_angle_pool_assets(pool), target_sizes):
                cand = _make_candidate(
                    combo,
                    str(team.get("name") or ""),
                    str(team.get("ownerId") or ""),
                )
                if cand is not None:
                    candidates.append(cand)

    # Per-team cap first — prevents a single opposing roster from
    # swamping the results with 50 near-identical variations of the
    # same trade. Sort each team's candidates by arb_score desc, keep
    # the top ``per_team_limit``, then apply the global cap across
    # what's left.
    candidates.sort(key=lambda c: c["arb_score"], reverse=True)
    if per_team_limit and per_team_limit > 0:
        kept: list[dict[str, Any]] = []
        seen_per_team: dict[str, int] = {}
        for c in candidates:
            owner_id = c.get("owner_id") or c.get("team") or ""
            count = seen_per_team.get(owner_id, 0)
            if count >= per_team_limit:
                continue
            kept.append(c)
            seen_per_team[owner_id] = count + 1
        candidates = kept
    candidates = candidates[: max(1, int(limit))]

    offer_players = _package_players(offer_entries, offer_pkg)
    warnings.extend(_diagnostic_warnings(diag))

    return {
        "offer": {
            "team": my_team_name,
            "size": offer_size,
            "players": offer_players,
            "my_total": int(round(offer_my_total)),
            "market_total": int(round(offer_market_total)),
            # Verbose here and nowhere else: the fixed side is the one
            # place the measured/assumed wording is worth carrying.
            **_market_stamp(offer_pkg),
        },
        "candidates": candidates,
        "market_diagnostics": diag,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_market_gain_pct": max_market_gain_pct,
            "limit": limit,
            "candidate_pool_per_team": candidate_pool_per_team,
            "per_team_limit": per_team_limit,
            "target_sizes": target_sizes,
            "positions": sorted(position_filter) if position_filter else [],
            "min_player_my_value": int(min_my_value_floor),
            "target_team_owner_ids": sorted(target_ids) if target_ids else [],
            "seed_player_names": sorted(seed_names_set) if target_ids else [],
            "include_idp": bool(include_idp),
        },
        "warnings": warnings,
    }


def find_acquisition_packages(
    players_array: list[dict[str, Any]],
    desired_player_names: list[str],
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_market_gain_pct: float = 5.0,
    limit: int = 50,
    candidate_pool: int = 25,
    positions: list[str] | None = None,
    min_player_my_value: float = 0.0,
    include_idp: bool = False,
) -> dict[str, Any]:
    """Find offer-side packages from the user's roster that acquire a
    fixed set of desired players from other teams.

    Inverse of :func:`find_angle_packages`. The user picks players on
    opposing rosters they want to acquire; this enumerates combinations
    of their own roster (size within ±1 of the desired count) and
    keeps those that (a) leave the user ahead on my-value by at least
    ``min_my_gain_pct`` and (b) look fair-or-better to the counterparty
    on the market the counterparty consults (IDPTC for IDP, KTC
    otherwise), gap ≤ ``max_market_gain_pct``.

    Parameters
    ----------
    desired_player_names
        Canonical names of players the user wants to acquire. They
        must each be owned by a team OTHER than ``selected_team_owner_id``.
        Any missing or user-owned names are dropped with a warning.
    candidate_pool
        Top-N players (by ``rankDerivedValue``) from the user's own
        roster to enumerate combinations from. Caps combinatorial
        explosion.

    Returns
    -------
    dict
        ``{acquire: {...}, candidates: [{...}], thresholds, warnings}``
        where each candidate is an offer-side package from the user's
        roster satisfying the arbitrage constraints vs the fixed
        desired package. Sorted by ``arb_score`` desc.
    """
    warnings: list[str] = []

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if name and name not in by_name:
            by_name[name] = row

    # Locate the user's team and build a reverse index so we can
    # validate desired players are on opposing rosters.
    my_team: dict[str, Any] | None = None
    owner_by_player: dict[str, str] = {}
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner == selected_team_owner_id:
            my_team = team
        for pname in team.get("players") or []:
            owner_by_player[str(pname)] = owner

    if my_team is None:
        return {
            "acquire": {
                "players": [],
                "size": 0,
                "my_total": 0,
                "market_total": 0,
                "targets": [],
            },
            "candidates": [],
            "warnings": [f"Owner {selected_team_owner_id!r} not found in sleeper rosters."],
        }

    # Resolve desired players. Drop unknowns, self-owned, and rows
    # missing values — each with a warning.
    desired_rows: list[dict[str, Any]] = []
    desired_owners: dict[str, str] = {}
    missing: list[str] = []
    own_roster: list[str] = []
    for name in desired_player_names:
        name = str(name).strip()
        if not name:
            continue
        row = by_name.get(name)
        if not row:
            missing.append(name)
            continue
        owner_of = owner_by_player.get(name)
        if owner_of == selected_team_owner_id:
            own_roster.append(name)
            continue
        pair = _value_pair(row)
        if pair is None:
            missing.append(name)
            continue
        desired_rows.append(row)
        desired_owners[name] = owner_of or ""
    if missing:
        warnings.append(
            f"Dropped {len(missing)} desired player(s) with missing data: "
            f"{', '.join(missing[:5])}" + (" …" if len(missing) > 5 else "")
        )
    if own_roster:
        warnings.append(
            f"Dropped {len(own_roster)} player(s) already on your roster: "
            f"{', '.join(own_roster[:5])}" + (" …" if len(own_roster) > 5 else "")
        )
    if not desired_rows:
        return {
            "acquire": {
                "players": [],
                "size": 0,
                "my_total": 0,
                "market_total": 0,
                "targets": [],
            },
            "candidates": [],
            "warnings": warnings or ["No valid desired-acquisition players."],
        }

    desired_my_total = sum(_value_pair(r)[0] for r in desired_rows)  # type: ignore[index]
    desired_size = len(desired_rows)
    diag = _new_market_diagnostics()

    # Fixed side: one market for the whole acquire package, or nothing.
    # ``desired_player_names`` comes straight from the user's picks on
    # opposing rosters with no IDP filter, so this side mixes boards as
    # freely as the offer side of ``find_angle_packages`` did.
    desired_pkg = value_package(desired_rows)
    desired_entries = [
        {
            "name": str(r.get("canonicalName") or r.get("displayName") or ""),
            "position": str(r.get("position") or ""),
            "my_value": _value_pair(r)[0],  # type: ignore[index]
        }
        for r in desired_rows
    ]
    if not desired_pkg.is_rankable:
        _note_reason(diag, desired_pkg.suppressed_reason)
        diag["unvaluable"] += 1
        warnings.append(desired_pkg.label or "Acquire package cannot be valued on a single market.")
        return {
            "acquire": {
                "team": my_team.get("name"),
                "size": desired_size,
                "players": [
                    {
                        "name": e["name"],
                        "position": e["position"],
                        "my_value": int(e["my_value"]),
                        "market_value": 0,
                        "market_source": None,
                        "owner_id": desired_owners.get(e["name"], ""),
                    }
                    for e in desired_entries
                ],
                "my_total": int(round(desired_my_total)),
                "market_total": 0,
                "targets": [],
                **_unvaluable_stamp(desired_pkg),
            },
            "candidates": [],
            "market_diagnostics": diag,
            "warnings": warnings,
        }
    desired_market_total = float(desired_pkg.total or 0.0)
    if desired_pkg.uncertainty_band > 0:
        warnings.append(
            f"Acquire package priced on {desired_pkg.market} because it spans offense and "
            f"IDP; ±{int(round(desired_pkg.uncertainty_band))} pts of that total rests on "
            "an assumed offense<->IDP exchange rate."
        )

    target_sizes = sorted({max(1, desired_size - 1), desired_size, desired_size + 1})

    position_filter: set[str] | None = None
    if positions:
        position_filter = {str(p).strip().upper() for p in positions if str(p).strip()}
        if not position_filter:
            position_filter = None
    min_my_value_floor = max(0.0, float(min_player_my_value or 0.0))

    # Build offer-side pool from the user's own roster.
    desired_name_set = {str(r.get("canonicalName") or "") for r in desired_rows}
    pool: list[dict[str, Any]] = []
    for pname in my_team.get("players") or []:
        pname = str(pname)
        if pname in desired_name_set:
            continue  # not on user's roster anyway, but guard
        row = by_name.get(pname)
        if not row:
            continue
        pair = _value_pair(row)
        if pair is None:
            continue
        my_v = pair[0]
        row_pos = str(row.get("position") or "").strip().upper()
        if position_filter is not None and row_pos not in position_filter:
            continue
        # IDP gate — see docstring on find_angle_packages. Fixed side
        # (desired players) is never filtered; this only restricts the
        # offer-side pool built from the user's own roster.
        if not include_idp and _is_idp_position(row_pos):
            continue
        if my_v < min_my_value_floor:
            continue
        pool.append(
            {
                "name": pname,
                "position": str(row.get("position") or ""),
                "my_value": my_v,
                # See find_angle_packages: ``row`` is what gets priced.
                "row": row,
            }
        )
    pool.sort(key=lambda p: -p["my_value"])
    pool = pool[: max(1, int(candidate_pool))]

    # Desired-side value lists (sorted descending) for the VA path.
    desired_my_values = sorted(
        (float(_value_pair(r)[0]) for r in desired_rows),
        reverse=True,  # type: ignore[index]
    )
    desired_market_values = sorted(_market_values(desired_pkg), reverse=True)

    def _make_candidate(combo: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
        # Arbitrage math: user receives ``desired_*``, gives up
        # ``offer_*``. Apply KTC-style VA so consolidation (e.g. giving
        # 4 filler to land 3 studs) isn't treated as a fair swap just
        # because raw totals line up — the consolidated side carries a
        # premium on both my-value and market-value.
        #
        # My-value gate first — same reasoning as find_angle_packages.
        offer_my_values = [p["my_value"] for p in combo]
        (
            desired_my_adj,
            offer_my_adj,
            desired_my_va,
            offer_my_va,
        ) = _adjusted_pair_totals(desired_my_values, offer_my_values)
        if offer_my_adj <= 0:
            return None
        my_gain_pct = 100.0 * (desired_my_adj - offer_my_adj) / offer_my_adj
        if my_gain_pct < min_my_gain_pct:
            return None

        offer_pkg = value_package([p["row"] for p in combo])
        diag["combos_valued"] += 1
        if not offer_pkg.is_rankable:
            diag["unvaluable"] += 1
            _note_reason(diag, offer_pkg.suppressed_reason)
            return None
        offer_market_values = _market_values(offer_pkg)
        (
            desired_market_adj,
            offer_market_adj,
            desired_market_va,
            offer_market_va,
        ) = _adjusted_pair_totals(desired_market_values, offer_market_values)

        if offer_market_adj <= 0:
            return None
        market_gain_pct = 100.0 * (desired_market_adj - offer_market_adj) / offer_market_adj
        if market_gain_pct > max_market_gain_pct:
            return None

        comparison = compare_packages(
            _restate_on(desired_pkg, desired_market_adj),
            _restate_on(offer_pkg, offer_market_adj),
            gate_pct=max_market_gain_pct,
        )
        if not comparison.verdict_certain:
            diag["withheld_uncertain"] += 1
            _note_reason(diag, comparison.suppressed_reason)
            return None

        offer_my_sum = sum(offer_my_values)
        offer_market_sum = float(offer_pkg.total or 0.0)
        return {
            "size": len(combo),
            "players": _package_players(combo, offer_pkg),
            "my_total": int(round(offer_my_sum)),
            "market_total": int(round(offer_market_sum)),
            "my_total_adjusted": int(round(offer_my_adj)),
            "market_total_adjusted": int(round(offer_market_adj)),
            "my_value_adjustment": int(round(offer_my_va)),
            "market_value_adjustment": int(round(offer_market_va)),
            "acquire_my_total_adjusted": int(round(desired_my_adj)),
            "acquire_market_total_adjusted": int(round(desired_market_adj)),
            "acquire_my_value_adjustment": int(round(desired_my_va)),
            "acquire_market_value_adjustment": int(round(desired_market_va)),
            "my_gain_pct": round(my_gain_pct, 2),
            "market_gain_pct": round(market_gain_pct, 2),
            "market_gain_low_pct": (
                round(comparison.gain_low_pct, 2) if comparison.gain_low_pct is not None else None
            ),
            "market_gain_high_pct": (
                round(comparison.gain_high_pct, 2) if comparison.gain_high_pct is not None else None
            ),
            "arb_score": round(my_gain_pct - market_gain_pct, 2),
            **_market_stamp(offer_pkg, verbose=False),
        }

    candidates: list[dict[str, Any]] = []
    for combo in _angle_sides(_angle_pool_assets(pool), target_sizes):
        cand = _make_candidate(combo)
        if cand is not None:
            candidates.append(cand)

    candidates.sort(key=lambda c: c["arb_score"], reverse=True)
    candidates = candidates[: max(1, int(limit))]

    desired_players = _package_players(desired_entries, desired_pkg)
    for p in desired_players:
        p["owner_id"] = desired_owners.get(p["name"], "")
    warnings.extend(_diagnostic_warnings(diag))

    # Deduplicated list of target teams the desired players come from.
    targets: list[dict[str, Any]] = []
    seen_owners: set[str] = set()
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner in desired_owners.values() and owner not in seen_owners:
            targets.append({"team": str(team.get("name") or ""), "owner_id": owner})
            seen_owners.add(owner)

    return {
        "acquire": {
            "team": my_team.get("name"),
            "size": desired_size,
            "players": desired_players,
            "my_total": int(round(desired_my_total)),
            "market_total": int(round(desired_market_total)),
            "targets": targets,
            **_market_stamp(desired_pkg),
        },
        "candidates": candidates,
        "market_diagnostics": diag,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_market_gain_pct": max_market_gain_pct,
            "limit": limit,
            "candidate_pool": candidate_pool,
            "target_sizes": target_sizes,
            "positions": sorted(position_filter) if position_filter else [],
            "min_player_my_value": int(min_my_value_floor),
            "include_idp": bool(include_idp),
        },
        "warnings": warnings,
    }
