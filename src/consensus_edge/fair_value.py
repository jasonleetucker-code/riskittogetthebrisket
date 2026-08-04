"""An internal value that is independent of the price it is judged against.

To say "the market is wrong about this player" you need two numbers: a
market price, and your own estimate.  If the estimate was partly built
from the price, the comparison is the model agreeing with itself — it
will report the smallest gaps exactly where it is most confident, and the
error is invisible because both sides move together.

The live board (``rankDerivedValue``) cannot serve as the estimate.  It
blends 21 sources and ``ktcSfTep`` — the offense market anchor — is one
of them.  ``_compute_market_gap`` already differences KTC's rank against
the mean of the others and calls it a "market gap"; that quantity is
partly KTC measured against KTC.

This module builds the honest version: **leave-one-out boards**.  Drop
the market anchor from the blend, recompute through the *same* pipeline,
and compare the result against the anchor.  No second ranker, no parallel
valuation system — ``build_api_data_contract`` already accepts
``source_overrides``, so this is the existing engine asked a different
question.

Three ways the anchor leaks back in, all measured on the live payload
2026-08-04 and all closed here:

1. **Correlated sources.**  ``fantasyNavigatorSf`` republishes
   KTC-derived values (every row carries a ``ktc_player_id``).  Excluding
   ``ktcSfTep`` alone still left **440 rows** carrying an FN vote.  Closed
   by ``expand_correlation_groups`` — the registry now declares the
   ``ktc`` correlation group and members leave together.
2. **The rookie ladder.**  ``dlfRookieSf`` / ``flockFantasySfRookies``
   translate their within-class rank through a ladder built from KTC's
   live rookie ranks.  Already closed upstream: the ladder pass guards on
   ``ref_key not in active_keys``, so excluding KTC skips the
   translation.  Verified — 0 of 25 surviving ladder translations went
   via ``ktcSfTep``.  Pinned by a test so it stays closed.
3. **The market-corridor clamp.**  Reads the anchor out of
   ``canonicalSiteValues``, *not* out of the vote, so dropping a source
   does not stop the clamp pulling values back toward it.  With
   ``idpTradeCalc`` excluded, **101 IDP rows** were still clamped toward
   idpTradeCalc, mean shift 552 points.  Closed by
   ``suppress_market_corridor_clamp=True``.

**Two boards, not one.**  Offense and IDP have different anchors, and a
board that dropped both would have no cross-market scale left.  So we
build one board per anchor and take each row's fair value from the board
that excluded *that row's own* anchor.  ``fair_value_index`` does this
routing and stamps which basis priced each row; a row whose anchor board
declines to price it gets ``None``, never a substituted number from the
other board.

Cost: two extra pipeline passes, ~2s each on a live payload.  Callers
that need both should use :func:`fair_value_index`, which builds each
board once.
"""

from __future__ import annotations

from typing import Any, Iterable

from src.api.data_contract import build_api_data_contract, expand_correlation_groups

# Which source is the acquisition market for each asset class.  Mirrors
# ``data_contract._MARKET_ANCHOR_BY_ASSET_CLASS`` and
# ``league_intel.values.MARKET_ANCHOR_BY_ASSET_CLASS``; a parity test
# keeps the three honest.  Picks are deliberately absent — neither
# retail board publishes a pick market we can treat as a price, so pick
# rows get no mispricing signal rather than an invented one.
MARKET_ANCHOR_BY_ASSET_CLASS: dict[str, str] = {
    "offense": "ktcSfTep",
    "idp": "idpTradeCalc",
}

# Reasons a row can fail to receive a fair value.  Surfaced verbatim so
# the UI can say WHY a player has no signal instead of showing a blank.
UNPRICED_NO_ANCHOR = "no_market_anchor_for_asset_class"
UNPRICED_NOT_ON_BOARD = "not_priced_by_anchor_free_board"
UNPRICED_NO_MARKET_VALUE = "no_market_value"


def leave_one_out_board(
    raw_payload: dict[str, Any],
    *,
    exclude: Iterable[str],
    extra_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a contract with ``exclude`` (and everything correlated) removed.

    ``exclude`` names the sources whose influence must not appear in the
    result.  It is expanded through the registry's correlation groups
    first, so naming ``ktcSfTep`` also drops ``fantasyNavigatorSf``.

    The corridor clamp is suppressed unconditionally: it anchors on the
    very sources a leave-one-out board exists to be free of.

    ``extra_overrides`` is merged last for callers that also want a
    weight change; per-source keys collide by ``include`` semantics, so
    an explicit ``{"include": True}`` here would *re-enable* an excluded
    source.  That is intentional and the caller's responsibility.
    """
    keys = expand_correlation_groups(exclude)
    overrides: dict[str, dict[str, Any]] = {k: {"include": False} for k in keys}
    for key, value in (extra_overrides or {}).items():
        overrides.setdefault(str(key), {}).update(value or {})
    return build_api_data_contract(
        raw_payload,
        source_overrides=overrides,
        suppress_market_corridor_clamp=True,
    )


def _row_key(row: dict[str, Any]) -> str:
    """Join key for a contract row.

    ``displayName`` matches what ``league_intel.overlay.row_factor_key``
    and ``publish._row_key`` use, so a Consensus Edge join lines up with
    the league-adjusted overlay's join rather than inventing a third
    convention.
    """
    return str(row.get("displayName") or row.get("canonicalName") or "")


def _market_value(row: dict[str, Any], anchor_key: str) -> float | None:
    """Raw native-scale value the anchor publishes for this row.

    Read from ``canonicalSiteValues`` — the scraped number — rather than
    from the blend's vote, because the vote is exactly what we removed.
    """
    sites = row.get("canonicalSiteValues")
    if not isinstance(sites, dict):
        return None
    raw = sites.get(anchor_key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def fair_value_index(
    raw_payload: dict[str, Any],
    *,
    anchors: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fair value + market value per player, each free of its own anchor.

    Returns ``{playerKey: entry}`` where ``entry`` carries::

        fairValue         anchor-free blended value, or None
        marketValue       the anchor's own published value, or None
        assetClass        offense | idp | pick | ...
        anchorKey         which source is the market for this row
        basis             "leaveOneOut"
        excludedSources   sorted keys dropped to produce fairValue
        unpricedReason    set when fairValue or marketValue is None

    One pipeline pass per distinct anchor (two today), not one per row.

    Rows whose asset class has no anchor — picks — are returned with
    ``fairValue`` populated but ``marketValue`` None and an explicit
    reason.  They are still useful to a caller that wants the board; they
    simply cannot carry a mispricing score.
    """
    anchor_map = dict(anchors or MARKET_ANCHOR_BY_ASSET_CLASS)

    # The default board supplies asset class, market values, and the row
    # universe.  It is never used as a fair value — that is the whole
    # point — but it is the only board guaranteed to contain every row.
    default_contract = build_api_data_contract(raw_payload)
    default_rows = {
        _row_key(r): r for r in (default_contract.get("playersArray") or []) if _row_key(r)
    }

    # One anchor-free board per distinct anchor source.
    boards: dict[str, dict[str, dict[str, Any]]] = {}
    excluded_by_anchor: dict[str, list[str]] = {}
    for anchor_key in sorted(set(anchor_map.values())):
        contract = leave_one_out_board(raw_payload, exclude=[anchor_key])
        boards[anchor_key] = {
            _row_key(r): r for r in (contract.get("playersArray") or []) if _row_key(r)
        }
        excluded_by_anchor[anchor_key] = sorted(expand_correlation_groups([anchor_key]))

    out: dict[str, dict[str, Any]] = {}
    for key, row in default_rows.items():
        asset_class = str(row.get("assetClass") or "")
        anchor_key = anchor_map.get(asset_class)

        entry: dict[str, Any] = {
            "playerKey": key,
            "displayName": row.get("displayName"),
            "position": row.get("position"),
            "assetClass": asset_class or None,
            "anchorKey": anchor_key,
            "basis": "leaveOneOut",
            "excludedSources": excluded_by_anchor.get(anchor_key or "", []),
            "fairValue": None,
            "marketValue": None,
            "unpricedReason": None,
        }

        if not anchor_key:
            entry["unpricedReason"] = UNPRICED_NO_ANCHOR
            out[key] = entry
            continue

        loo_row = boards.get(anchor_key, {}).get(key)
        fair = None
        if loo_row is not None:
            raw_fair = loo_row.get("rankDerivedValue")
            if isinstance(raw_fair, (int, float)) and raw_fair > 0:
                fair = float(raw_fair)
        entry["fairValue"] = fair

        entry["marketValue"] = _market_value(row, anchor_key)

        if fair is None:
            entry["unpricedReason"] = UNPRICED_NOT_ON_BOARD
        elif entry["marketValue"] is None:
            entry["unpricedReason"] = UNPRICED_NO_MARKET_VALUE

        out[key] = entry

    return out


def coverage(index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarise what a fair-value index could and could not price.

    Exists so a caller never has to infer coverage from the absence of
    rows.  ``unpricedByReason`` is the field that turns "no signal" from
    a silence into a statement.
    """
    total = len(index)
    priced = sum(1 for e in index.values() if e.get("fairValue") and e.get("marketValue"))
    by_reason: dict[str, int] = {}
    for entry in index.values():
        reason = entry.get("unpricedReason")
        if reason:
            by_reason[str(reason)] = by_reason.get(str(reason), 0) + 1
    by_class: dict[str, int] = {}
    for entry in index.values():
        if entry.get("fairValue") and entry.get("marketValue"):
            cls = str(entry.get("assetClass") or "unknown")
            by_class[cls] = by_class.get(cls, 0) + 1
    return {
        "totalRows": total,
        "pricedRows": priced,
        "pricedByAssetClass": by_class,
        "unpricedByReason": by_reason,
    }
