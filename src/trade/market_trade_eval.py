"""Evaluation harness over canonical underlying trades — first version.

Answers, per underlying trade (never per raw observation):

1. **What shape is it?**  Topology class plus flags.
2. **Can it inform a latent-price fit at all?**  ``clean_1_for_1`` /
   ``package_va_required`` / ``unsuitable`` with every reason named.
3. **How far apart do our board and each source price its two sides?**  Only
   where the topology is identifiable, only on the format the board is built
   for, and always through the Value Adjustment owner
   (``src.trade.ktc_va.adjusted_pair_totals``) — a 3-for-1 is never read as an
   equality of raw sums.

WHAT A RESIDUAL HERE IS, AND IS NOT
───────────────────────────────────
Both managers accepted the trade, so the market cleared at "even" by
definition; a source that prices the two sides far apart disagrees with that
clearing.  The residual is a DIAGNOSTIC of disagreement.  It is not a label
for fitting anything, and no number here may move a canonical value (spec §3,
§18; owner directive Batch 3 §N).

Two lineage warnings travel with every report:

* **KTC Trades / KTC Market are partly IN-SAMPLE** against KTC-sourced rows:
  KTC's trade-derived value is fit on this very population (``isUsedInVft``).
  Residuals are also reported on rows whose latest archived revision says KTC
  had NOT yet consumed them — but ``isUsedInVft`` is a processing flag (rows
  flip False -> True within minutes), so that subset is "not yet consumed",
  not an out-of-sample set.  The canonical board — which votes KTC Trades —
  inherits the same caveat.
* **Board-vs-trade timing**: the board must date AT OR BEFORE the trade and no
  more than ``max_board_lag_days`` before it.  A board built after the trade is
  look-ahead and is never used; a much older one grades the trade with values
  nobody held at the time.

No latent-price model is fit here.  ``latent_fit_readiness`` reports whether
enough clean trades exist for a SHADOW prototype to be worth building; the
model itself, if ever built, is shadow-only until a preregistered gate passes.
"""

from __future__ import annotations

import math
import statistics
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from src.identity.picks import parse_market_pick_id
from src.trade.ktc_va import adjusted_pair_totals

TOPO_1_FOR_1 = "two_team_1_for_1"
TOPO_2_FOR_1 = "two_team_2_for_1"
TOPO_N_FOR_1 = "two_team_n_for_1"
TOPO_MULTI = "two_team_multi_asset"
TOPO_ONE_SIDED = "two_team_one_sided"
TOPO_MULTI_TEAM = "multi_team"
TOPO_EMPTY = "empty"

FIT_CLEAN = "clean_1_for_1"
FIT_PACKAGE = "package_va_required"
FIT_UNSUITABLE = "unsuitable"

#: Value-signal sources whose ``valueContribution`` is a native value read
#: directly (``raw / site_max × 9999``) — the rest vote rank -> Hill.  Only
#: used for labelling the report.
VALUE_DIRECT_SOURCES = ("ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc")
#: Sources derived (wholly or partly) from KTC's own trade population.
KTC_TRADE_DERIVED = ("ktcTradesSfTep", "ktcCrowdTradesSfTep", "ktcMarket")

DEFAULT_MAX_BOARD_LAG_DAYS = 7


# ── Topology ──────────────────────────────────────────────────────────────


def classify_topology(trade: Mapping[str, Any]) -> dict[str, Any]:
    sides = trade.get("sides") or []
    sizes = sorted(len(s) for s in sides)
    flags: list[str] = []
    assets = [a for s in sides for a in s]
    kinds = {a.get("kind") for a in assets}
    if any(a.get("canonicalId") is None and a.get("kind") != "faab" for a in assets):
        flags.append("includes_unresolved")
    if "faab" in kinds:
        flags.append("includes_faab")
    if any(
        a.get("kind") == "pick"
        and (a.get("resolution") or {}).get("reason") == "startup_pick_not_a_market_ref"
        for a in assets
    ):
        flags.append("includes_startup_pick")
    picks = [a for a in assets if a.get("kind") == "pick"]
    # An unresolved reference is still an asset that is not a pick (KTC's
    # pick references always classify), so it counts on the player side of
    # the picks/players flag — never silently turning a trade "picks only".
    players = [a for a in assets if a.get("kind") in ("player", "unresolved")]
    if picks and not players:
        flags.append("picks_only")
    elif players and not picks:
        flags.append("players_only")
    elif picks and players:
        flags.append("players_and_picks")
    if any((a.get("pick") or {}).get("round") and int(a["pick"]["round"]) > 6 for a in picks):
        flags.append("includes_pick_beyond_round_6")
    if any((a.get("position") or "") in ("DL", "LB", "DB") for a in players):
        flags.append("includes_idp_player")

    if not assets:
        topo = TOPO_EMPTY
    elif len(sides) >= 3:
        topo = TOPO_MULTI_TEAM
    elif len(sides) == 2 and 0 in sizes:
        topo = TOPO_ONE_SIDED
    elif sizes == [1, 1]:
        topo = TOPO_1_FOR_1
    elif sizes == [1, 2]:
        topo = TOPO_2_FOR_1
    elif len(sizes) == 2 and sizes[0] == 1:
        topo = TOPO_N_FOR_1
    elif len(sizes) == 2:
        topo = TOPO_MULTI
    else:
        topo = TOPO_EMPTY
    return {"topology": topo, "sideSizes": sizes, "flags": flags}


def fit_suitability(trade: Mapping[str, Any], topo: Mapping[str, Any]) -> dict[str, Any]:
    """Whether a trade can enter a latent-price fit, and why not."""
    reasons: list[str] = []
    t = topo["topology"]
    if t in (TOPO_MULTI_TEAM,):
        reasons.append("three_or_more_teams")
    if t in (TOPO_ONE_SIDED, TOPO_EMPTY):
        reasons.append("one_side_empty")
    for flag in (
        "includes_unresolved",
        "includes_faab",
        "includes_startup_pick",
        "includes_pick_beyond_round_6",
    ):
        if flag in topo["flags"]:
            reasons.append(flag)
    if trade.get("dedupeState") in ("POSSIBLE_OVERLAP", "UNRESOLVED"):
        # Volume-sensitive use of an unproven-unique trade risks counting one
        # event twice (§19.6).
        reasons.append(f"dedupe_state:{trade.get('dedupeState')}")
    fmt = trade.get("marketFormat") or {}
    if (fmt.get("general") or {}).get("dynastyState") != "dynasty":
        reasons.append("dynasty_state_unverified")
    if (fmt.get("offense") or {}).get("superflex") is None:
        reasons.append("qb_format_unknown")
    if reasons:
        return {"fit": FIT_UNSUITABLE, "reasons": reasons}
    if t == TOPO_1_FOR_1:
        return {"fit": FIT_CLEAN, "reasons": []}
    # 2-for-1, n-for-1 and multi-asset sides carry consolidation economics:
    # usable only through a package model (VA), never as an equality of sums.
    return {"fit": FIT_PACKAGE, "reasons": ["consolidation_effects_require_package_model"]}


# ── Board value lookup ────────────────────────────────────────────────────


class BoardIndex:
    """Per-asset values from one built contract: the canonical board
    (``rankDerivedValue``; picks through the one pick-value resolver) and every
    source's ``valueContribution`` on the same scale, plus KTC Market."""

    def __init__(self, contract: Mapping[str, Any]) -> None:
        from src.api.pick_value_resolution import _pick_rows_by_name, resolve_pick_value  # noqa: PLC0415

        self._contract = contract
        self._resolve_pick_value = resolve_pick_value
        self._pick_rows = _pick_rows_by_name(dict(contract))
        self._players: dict[str, Mapping[str, Any]] = {}
        for row in contract.get("playersArray") or []:
            if not isinstance(row, dict) or row.get("assetClass") == "pick":
                continue
            pid = str(row.get("playerId") or "").strip()
            if pid:
                self._players.setdefault(pid, row)
        self._pick_cache: dict[str, tuple[Mapping[str, Any] | None, int | None, str | None]] = {}

    def _pick(self, canonical_id: str) -> tuple[Mapping[str, Any] | None, int | None, str | None]:
        if canonical_id not in self._pick_cache:
            ref = parse_market_pick_id(canonical_id)
            if ref is None:
                self._pick_cache[canonical_id] = (None, None, "unparseable_ref")
            else:
                res = self._resolve_pick_value(
                    dict(self._contract), ref, rows_by_name=self._pick_rows
                )
                row = self._pick_rows.get(res.basis_row_name or "") if res.basis_row_name else None
                self._pick_cache[canonical_id] = (row, res.value, res.reason)
        return self._pick_cache[canonical_id]

    def values(self, asset: Mapping[str, Any]) -> dict[str, float]:
        """``{"canonical": v, "<sourceKey>": v, "ktcMarket": v}`` — keys only for
        values that exist.  Missing is ABSENT, never 0."""
        cid = asset.get("canonicalId")
        if not cid:
            return {}
        out: dict[str, float] = {}
        row: Mapping[str, Any] | None
        if cid.startswith("player:"):
            row = self._players.get(cid.split(":", 1)[1])
            if row is None:
                return {}
            v = row.get("rankDerivedValue")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                out["canonical"] = float(v)
        elif cid.startswith("mpick:"):
            row, value, _reason = self._pick(cid)
            if value is not None:
                out["canonical"] = float(value)
        else:
            return {}
        if row is not None:
            for src, meta in (row.get("sourceRankMeta") or {}).items():
                vc = (meta or {}).get("valueContribution") if isinstance(meta, dict) else None
                if isinstance(vc, (int, float)) and not isinstance(vc, bool) and vc > 0:
                    out[str(src)] = float(vc)
            km = row.get("ktcMarket")
            if (
                isinstance(km, dict)
                and km.get("available")
                and isinstance(km.get("value"), (int, float))
            ):
                if km["value"] > 0:
                    out["ktcMarket"] = float(km["value"])
        return out


# ── Residuals ─────────────────────────────────────────────────────────────


def _orient(sides: Sequence[Sequence[Mapping[str, Any]]], board: BoardIndex) -> tuple[list, list]:
    """Side A = the side holding the single most valuable asset by the
    canonical board (the 'stud' side).  A positive residual then means the
    source values the stud side ABOVE what came back for it."""

    def top(side):
        vals = [board.values(a).get("canonical") for a in side]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else -1.0

    a, b = sides[0], sides[1]
    return (list(a), list(b)) if top(a) >= top(b) else (list(b), list(a))


def trade_residual(
    trade: Mapping[str, Any], board: BoardIndex, source: str
) -> dict[str, Any] | None:
    """VA-adjusted relative gap for one trade under one source, or ``None``
    when the source does not price every asset (coverage is all-or-nothing:
    a partially priced side is not a smaller side)."""
    sides = trade.get("sides") or []
    if len(sides) != 2:
        return None
    a, b = _orient(sides, board)
    va = [board.values(x).get(source) for x in a]
    vb = [board.values(x).get(source) for x in b]
    if not va or not vb or any(v is None for v in va + vb):
        return None
    adj_a, adj_b, va_a, va_b = adjusted_pair_totals(va, vb)
    mean = (adj_a + adj_b) / 2.0
    if mean <= 0:
        return None
    return {
        "rawA": round(sum(va), 1),
        "rawB": round(sum(vb), 1),
        "adjustedA": round(adj_a, 1),
        "adjustedB": round(adj_b, 1),
        "valueAdjustment": round(va_a + va_b, 1),
        "relativeResidual": (adj_a - adj_b) / mean,
    }


def _summarize(rels: Sequence[float]) -> dict[str, Any]:
    if not rels:
        return {"n": 0}
    abs_r = sorted(abs(r) for r in rels)

    def q(p: float) -> float:
        k = (len(abs_r) - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return abs_r[lo] + (abs_r[hi] - abs_r[lo]) * (k - lo)

    return {
        "n": len(rels),
        "medianSignedRelative": round(statistics.median(rels), 4),
        "medianAbsRelative": round(q(0.5), 4),
        "p80AbsRelative": round(q(0.8), 4),
        "shareWithin10pct": round(sum(1 for r in abs_r if r <= 0.10) / len(abs_r), 4),
    }


#: Groups whose uniqueness is not proven never enter residual n.
RESIDUAL_EXCLUDED_DEDUPE_STATES = ("POSSIBLE_OVERLAP", "UNRESOLVED")
BOARD_DATE_UNKNOWN = "board_date_unknown_lookahead_unverifiable"


def residual_eligible(
    trade: Mapping[str, Any],
    topo: Mapping[str, Any],
    *,
    board_date: date | None,
    max_board_lag_days: int = DEFAULT_MAX_BOARD_LAG_DAYS,
) -> tuple[bool, str | None]:
    if board_date is None:
        # Without the board's date the look-ahead guard cannot run, and a board
        # built AFTER the trade would grade it with future values.  Fail closed.
        return False, BOARD_DATE_UNKNOWN
    if topo["topology"] not in (TOPO_1_FOR_1, TOPO_2_FOR_1, TOPO_N_FOR_1, TOPO_MULTI):
        return False, f"topology:{topo['topology']}"
    for flag in ("includes_unresolved", "includes_faab", "includes_startup_pick"):
        if flag in topo["flags"]:
            return False, flag
    state = trade.get("dedupeState")
    if state in RESIDUAL_EXCLUDED_DEDUPE_STATES:
        # Not proven unique: it may be the same real trade as another group
        # already in n, so it is left out of n rather than risk one event
        # counting twice (§19.6).  Disclosed in excludedByReason.
        return False, f"dedupe_state:{state}"
    fmt = trade.get("marketFormat") or {}
    dynasty_state = (fmt.get("general") or {}).get("dynastyState")
    if dynasty_state != "dynasty":
        # The board is a DYNASTY board; a redraft / keeper / unknown-type
        # trade cleared under a different horizon.  Unknown is not dynasty.
        return False, f"dynasty_state:{dynasty_state or 'unknown'}"
    if (fmt.get("offense") or {}).get("superflex") is not True:
        # The board is a SUPERFLEX TE++ board; a 1QB or unknown-QB trade cleared
        # under a different QB economy and grading it here measures the format.
        return False, "board_basis_superflex_mismatch_or_unknown"
    try:
        d = date.fromisoformat(str(trade.get("occurredDate")))
    except (TypeError, ValueError):
        return False, "undated_trade"
    # The board must be AT OR BEFORE the trade (the information the managers
    # could have held) and not stale relative to it.  A board built after the
    # trade is a future snapshot — look-ahead — and is never used to grade it.
    lag = (d - board_date).days
    if lag < 0:
        return False, "board_after_trade_lookahead"
    if lag > max_board_lag_days:
        return False, "board_older_than_max_lag"
    return True, None


def residual_report(
    trades: Sequence[Mapping[str, Any]],
    board: BoardIndex,
    *,
    board_date: date | None,
    sources: Iterable[str] | None = None,
    max_board_lag_days: int = DEFAULT_MAX_BOARD_LAG_DAYS,
) -> dict[str, Any]:
    """Per-source residual summaries over identifiable trades only.

    Refuses to grade at all when ``board_date`` is unknown: the look-ahead
    guard needs it, and skipping the guard would let a board built after the
    trade grade it (fail closed, never fail open)."""
    if board_date is None:
        return {
            "available": False,
            "reason": BOARD_DATE_UNKNOWN,
            "eligibleTrades": 0,
            "excludedByReason": {BOARD_DATE_UNKNOWN: len(trades)},
            "boardDate": None,
            "maxBoardLagDays": max_board_lag_days,
            "perSource": {},
            "notes": [
                "refused: the board's date is unknown, so a board built after a trade "
                "cannot be ruled out (look-ahead); supply a dated board"
            ],
        }
    eligible: list[Mapping[str, Any]] = []
    excluded: dict[str, int] = {}
    for t in trades:
        topo = classify_topology(t)
        ok, why = residual_eligible(
            t, topo, board_date=board_date, max_board_lag_days=max_board_lag_days
        )
        if ok:
            eligible.append(t)
        else:
            excluded[why or "unknown"] = excluded.get(why or "unknown", 0) + 1
    if sources is None:
        seen: set[str] = set()
        for t in eligible:
            for side in t["sides"]:
                for a in side:
                    seen.update(board.values(a).keys())
        sources = sorted(seen)
    per_source: dict[str, Any] = {}
    for src in sources:
        rels_all: list[float] = []
        rels_clean: list[float] = []
        rels_package: list[float] = []
        rels_not_vft: list[float] = []
        by_tep: dict[str, list[float]] = {}
        not_covered = 0
        for t in eligible:
            r = trade_residual(t, board, src)
            if r is None:
                not_covered += 1
                continue
            rel = r["relativeResidual"]
            rels_all.append(rel)
            topo = classify_topology(t)["topology"]
            (rels_clean if topo == TOPO_1_FOR_1 else rels_package).append(rel)
            if (t.get("vendorFlags") or {}).get("isUsedInVft") is False:
                rels_not_vft.append(rel)
            tep = (t.get("marketFormat") or {}).get("vendor", {}).get("tepLevel")
            by_tep.setdefault(str(tep), []).append(rel)
        per_source[src] = {
            "all": _summarize(rels_all),
            "clean1for1": _summarize(rels_clean),
            "packageVA": _summarize(rels_package),
            "rowsNotYetConsumedByKtcTrades": _summarize(rels_not_vft),
            "byKtcTepLevel": {k: _summarize(v) for k, v in sorted(by_tep.items())},
            "tradesNotFullyPricedBySource": not_covered,
            "inSampleRisk": src in KTC_TRADE_DERIVED or src == "canonical",
            "valueBasis": (
                "canonical_board"
                if src == "canonical"
                else "native_value_direct"
                if src in VALUE_DIRECT_SOURCES or src == "ktcMarket"
                else "rank_via_hill_curve"
            ),
        }
    return {
        "available": True,
        "eligibleTrades": len(eligible),
        "excludedByReason": dict(sorted(excluded.items())),
        "boardDate": board_date.isoformat() if board_date else None,
        "maxBoardLagDays": max_board_lag_days,
        "perSource": per_source,
        "notes": [
            "residual = (VA-adjusted stud side - VA-adjusted other side) / mean, via src.trade.ktc_va",
            "a completed trade cleared at 'even' for its two managers; the residual measures a source's disagreement with that clearing",
            "KTC Trades / KTC Market (and the canonical board, which votes KTC Trades) are partly in-sample on KTC rows; see rowsNotYetConsumedByKtcTrades",
            "isUsedInVft is a PROCESSING flag: measured 2026-10-01, 10 of 200 rows flipped False -> True within ~25 minutes of first appearing, so False mostly means not yet consumed (the latest archived revision governs), not deliberately excluded",
            "rank sources' values are their Hill-transformed votes on the canonical scale, not vendor values",
            "n counts proven-unique groups only: POSSIBLE_OVERLAP / UNRESOLVED groups are excluded (see excludedByReason dedupe_state:*), and non-dynasty or unknown-type leagues are excluded (dynasty_state:*)",
        ],
    }


def latent_fit_readiness(
    trades: Sequence[Mapping[str, Any]], *, min_appearances: int = 3
) -> dict[str, Any]:
    """Counts only.  Whether a shadow latent-price prototype has enough clean
    evidence to be worth building — not a model."""
    clean_assets: dict[str, int] = {}
    package = 0
    clean = 0
    for t in trades:
        topo = classify_topology(t)
        fit = fit_suitability(t, topo)
        if fit["fit"] == FIT_CLEAN:
            clean += 1
            for side in t["sides"]:
                for a in side:
                    clean_assets[a["canonicalId"]] = clean_assets.get(a["canonicalId"], 0) + 1
        elif fit["fit"] == FIT_PACKAGE:
            package += 1
    dense = sum(1 for n in clean_assets.values() if n >= min_appearances)
    return {
        "clean1for1Trades": clean,
        "packageTrades": package,
        "distinctAssetsInClean": len(clean_assets),
        f"assetsWithAtLeast{min_appearances}CleanAppearances": dense,
        "shadowPrototypeBuilt": False,
        "reason": "first version reports readiness only; any latent-price model stays shadow until a preregistered, leakage-safe gate passes (Batch 3 §N)",
    }


def summarize_topology(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_topo: dict[str, int] = {}
    by_fit: dict[str, int] = {}
    unsuitable_reasons: dict[str, int] = {}
    flags: dict[str, int] = {}
    for t in trades:
        topo = classify_topology(t)
        fit = fit_suitability(t, topo)
        by_topo[topo["topology"]] = by_topo.get(topo["topology"], 0) + 1
        by_fit[fit["fit"]] = by_fit.get(fit["fit"], 0) + 1
        if fit["fit"] == FIT_UNSUITABLE:
            for r in fit["reasons"]:
                unsuitable_reasons[r] = unsuitable_reasons.get(r, 0) + 1
        for f in topo["flags"]:
            flags[f] = flags.get(f, 0) + 1
    return {
        "byTopology": dict(sorted(by_topo.items())),
        "byFitSuitability": dict(sorted(by_fit.items())),
        "unsuitableReasons": dict(sorted(unsuitable_reasons.items(), key=lambda kv: -kv[1])),
        "flags": dict(sorted(flags.items())),
    }


__all__ = [
    "BoardIndex",
    "classify_topology",
    "fit_suitability",
    "latent_fit_readiness",
    "residual_report",
    "summarize_topology",
    "trade_residual",
]
