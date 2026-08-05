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

**Leakage is not the only failure mode, and it was not the worst one.**
The three items above all ask "does the anchor's opinion still reach the
result?".  There is a second question — "is the result still denominated
in the same units?" — and for two row classes the answer was no, which
made the board *look* fine while inflating exactly the rows a buy list
surfaces:

* **IDP rows had no scale at all.**  Three IDP-only expert boards —
  ``dlfIdp``, ``idpShow`` and ``fantasyProsIdp``, all flagged
  ``needs_shared_market_translation`` — rank players within the IDP class
  only.  The backbone's shared-market ladder lifts that within-class
  ordinal into the combined offense+IDP rank space.  ``idpTradeCalc``
  is what builds that ladder, so excluding it empties it and
  ``translate_position_rank`` returns the raw rank as
  ``TRANSLATION_FALLBACK`` — the vote then says IDP #1 is asset #1.
  Measured on the 2026-08-03 payload, the three sources flip method
  ``exact`` → ``fallback`` on 159 / 235 / 177 rows, and the values move
  by **220 IDP rows, median LOO/base ratio 1.224, range 0.45x to
  3.48x**.  Caleb Banks went 1183 → 4115 and was published as the #19
  buy on that strength alone.
* **Rookie rows lost the ladder.**  Item 2's guard closes the leak by
  skipping the translation, and skipping it is what breaks the scale:
  the untranslated vote says rookie #1 is asset #1.  Measured on the same
  payload: non-rookie offense is sound (400 rows, median 0.992, max
  1.17x — a vote leaving, which is the point), while **87 rookie rows
  reach 2.44x**.  ``dlfRookieIdp`` is paired with ``idpTradeCalc`` in
  ``ROOKIE_LADDER_PAIRS``, so a rookie IDP row loses BOTH dependencies;
  26 rows do, and ``scaleIntegrity.reasons`` names both.

CORRECTION (2026-08-04).  The first bullet used to describe
``position_idp`` sources losing a within-DL/LB/DB crosswalk.  That branch
is dead — no registered source carries the ``position_idp`` scope, and a
census of every ``sourceRankMeta`` stamp on the 973-row live board
returns zero of them.  The measurement was always right; the mechanism
was not, and it had been copied into five other files.

Neither is fixable by excluding more sources, and neither is a bug in the
pipeline: the fallbacks are right for the default board, where an absent
source is one we never scraped.  They are wrong for a board built by
deliberately removing a source.  So the rows are returned **unpriced**,
with :data:`UNPRICED_SCALE_IDP_BACKBONE` / :data:`UNPRICED_SCALE_ROOKIE_LADDER`
naming which dependency broke.

**Why no other source can supply the IDP scale.**  Not "there is exactly
one IDP cross-market source" — there are two registered
``is_cross_market`` with scope ``overall_idp``.  The real constraint is
narrower: ``build_backbone_from_rows`` seeds its ladder from ONE registry
key, so a backbone needs a source whose own value column spans both
pools.  ``idpTradeCalc`` is the only key that does (529 positive offense
+ 258 positive IDP).  ``draftSharksIdp`` carries 0 positive offense
values under its key — its offense half is the separate ``draftSharks``
key — so promoting it yields the identity ladder ``[1, 2, 3, …]``, which
IS the fallback.

**The guard is a measurement, not a flag.**  ``scale_integrity_lost``
asks the registry and ``is_backbone`` is a label: setting it True on any
of the five non-backbone IDP sources empties that declaration while the
board stays bit-for-bit at median 1.224 / max 3.478.  The deciding gate
is therefore :func:`~src.api.data_contract.shared_market_crosswalk_failed`,
which reads the translation stamps off the board itself and cannot be
satisfied by a registry edit.  Both run; the measured one can only add
refusals.  See ADR-021 and ADR-025 in ``docs/consensus-edge/DECISIONS.md``.

Cost: two extra pipeline passes, ~2s each on a live payload.  Callers
that need both should use :func:`fair_value_index`, which builds each
board once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from src.api.data_contract import (
    SCALE_LOST_IDP_BACKBONE,
    build_api_data_contract,
    expand_correlation_groups,
    scale_integrity_lost,
    shared_market_crosswalk_failed,
)

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
# The anchor-free board produced a number for this row, and the number
# does not mean what the other rows' numbers mean.  Deliberately NOT
# folded into ``UNPRICED_NOT_ON_BOARD``: "the board could not price him"
# and "the board priced him in the wrong units" are different facts, and
# only the second one says a source needs registering.
UNPRICED_SCALE_IDP_BACKBONE = "anchor_free_board_lost_idp_backbone"
UNPRICED_SCALE_ROOKIE_LADDER = "anchor_free_board_lost_rookie_ladder"


def leave_one_out_board(
    raw_payload: dict[str, Any],
    *,
    exclude: Iterable[str],
    extra_overrides: dict[str, dict[str, Any]] | None = None,
    csv_root: "Path | None" = None,
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
        csv_root=csv_root,
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
    csv_root: "Path | None" = None,
    scoring_fit_board: Any = None,
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
        scaleIntegrity    present ONLY on rows discarded because the
                          anchor-free board could not express them on the
                          shared scale (see the module docstring)

    One pipeline pass per distinct anchor (two today), not one per row.

    ``csv_root`` MUST be supplied when replaying a historical date.  The
    pipeline enriches ``canonicalSiteValues`` from ``CSVs/site_raw`` on
    disk, so omitting it silently mixes today's source values into a past
    board — look-ahead leakage of the worst kind, because the result
    still looks like a valid board and would quietly inflate every
    backtest metric computed from it.

    Rows whose asset class has no anchor — picks — are returned with
    ``fairValue`` populated but ``marketValue`` None and an explicit
    reason.  They are still useful to a caller that wants the board; they
    simply cannot carry a mispricing score.
    """
    anchor_map = dict(anchors or MARKET_ANCHOR_BY_ASSET_CLASS)

    # The default board supplies asset class, market values, and the row
    # universe.  It is never used as a fair value — that is the whole
    # point — but it is the only board guaranteed to contain every row.
    default_contract = build_api_data_contract(raw_payload, csv_root=csv_root)
    default_rows = {
        _row_key(r): r for r in (default_contract.get("playersArray") or []) if _row_key(r)
    }

    # One anchor-free board per distinct anchor source.
    boards: dict[str, dict[str, dict[str, Any]]] = {}
    excluded_by_anchor: dict[str, list[str]] = {}
    # Per anchor: which asset classes and which surviving source votes
    # come out of that board on a broken scale.  Asked of the registry
    # once per board rather than inferred per row, so the answer cannot
    # drift from the exclusion that produced the board.
    scale_loss_by_anchor: dict[str, dict[str, dict[str, str]]] = {}
    for anchor_key in sorted(set(anchor_map.values())):
        contract = leave_one_out_board(raw_payload, exclude=[anchor_key], csv_root=csv_root)
        boards[anchor_key] = {
            _row_key(r): r for r in (contract.get("playersArray") or []) if _row_key(r)
        }
        excluded_by_anchor[anchor_key] = sorted(expand_correlation_groups([anchor_key]))

        # Two gates, and the MEASURED one can only add refusals.
        #
        # ``scale_integrity_lost`` reports what the registry declares;
        # ``shared_market_crosswalk_failed`` reports what this board
        # actually did. They agree today, and the reason to run both is
        # that the registry gate turns on ``is_backbone``, which is a
        # label rather than a capability: setting it True on any of the
        # five non-backbone IDP sources empties the declaration while the
        # board stays at median 1.224 / max 3.478. The board cannot lie
        # about its own translation stamps.
        declared = scale_integrity_lost([anchor_key])
        if shared_market_crosswalk_failed(contract.get("playersArray") or []):
            declared = {
                "assetClasses": {**declared["assetClasses"], "idp": SCALE_LOST_IDP_BACKBONE},
                "sources": declared["sources"],
            }
        scale_loss_by_anchor[anchor_key] = declared

    out: dict[str, dict[str, Any]] = {}
    for key, row in default_rows.items():
        asset_class = str(row.get("assetClass") or "")
        anchor_key = anchor_map.get(asset_class)

        entry: dict[str, Any] = {
            "playerKey": key,
            "displayName": row.get("displayName"),
            "position": row.get("position"),
            # How many sources actually priced this row on the default
            # board. Feeds the confidence score, so it must be the real
            # count — a fixed stand-in would make a one-source row look
            # as well-evidenced as a twelve-source one.
            "sourceCount": len(row.get("sourceRanks") or {}),
            # Identity quarantine, carried through rather than dropped.
            # ``data_contract._validate_and_quarantine_rows`` already
            # decides this and ``score.classify`` already has the branch
            # for it — the two were simply not connected, so a row the
            # pipeline had flagged as a bad identity join could reach the
            # top-20 with a full-confidence Buy on it. A wrong join means
            # the market price and the fair value may belong to two
            # different players, which is the one input error a value
            # model cannot absorb.
            "quarantined": bool(row.get("quarantined")),
            "identityConfidence": row.get("identityConfidence"),
            "assetClass": asset_class or None,
            "anchorKey": anchor_key,
            "basis": "leaveOneOut",
            "excludedSources": excluded_by_anchor.get(anchor_key or "", []),
            "fairValue": None,
            "marketValue": None,
            "unpricedReason": None,
            # EVERY reason this row is unpriced, not just the first.
            # ``unpricedReason`` stays as the single headline cause for
            # existing consumers; ``unpricedReasons`` is what coverage
            # counts, because a row can lose two dependencies at once and
            # reporting one of them hides the other entirely.
            "unpricedReasons": [],
        }

        if not anchor_key:
            entry["unpricedReason"] = UNPRICED_NO_ANCHOR
            entry["unpricedReasons"] = [UNPRICED_NO_ANCHOR]
            out[key] = entry
            continue

        loo_row = boards.get(anchor_key, {}).get(key)
        fair = None
        if loo_row is not None:
            raw_fair = loo_row.get("rankDerivedValue")
            if isinstance(raw_fair, (int, float)) and raw_fair > 0:
                fair = float(raw_fair)

        # Scale integrity, checked BEFORE the number is accepted.  A row
        # whose class lost the IDP backbone, or whose vote came from a
        # rookie source whose ladder reference was excluded, carries a
        # value in units the rest of the board does not share.  Discard
        # it and say which dependency broke — never blend it, never
        # substitute the default board's number, which would be the
        # anchor priced against itself.
        scale_loss = scale_loss_by_anchor.get(anchor_key) or {}
        # BOTH dependencies are collected, not the first one matched. A
        # rookie IDP row can lose the shared-market crosswalk AND its
        # rookie ladder — Caleb Banks, the worst row on the board at
        # 3.48x, loses both, and his rookie term is roughly four times
        # his backbone term. Testing ``assetClasses`` first and stopping
        # stamped him with the smaller of his two causes, which is the
        # wrong dependency to hand anyone debugging it. Scoring is
        # unaffected either way (both refuse); the label is the point.
        scale_reasons: list[str] = []
        if asset_class and asset_class in (scale_loss.get("assetClasses") or {}):
            scale_reasons.append(UNPRICED_SCALE_IDP_BACKBONE)
        broken_sources = scale_loss.get("sources") or {}
        # Per-row rather than per-class: only rows this source actually
        # voted on are affected, and the vote is the ground truth for
        # that — narrower and more honest than reading a rookie flag,
        # which would also catch rookies the broken source never ranked.
        if broken_sources and loo_row is not None:
            voted = set((loo_row.get("sourceRanks") or {}).keys())
            if voted & set(broken_sources):
                scale_reasons.append(UNPRICED_SCALE_ROOKIE_LADDER)
        scale_reason: str | None = scale_reasons[0] if scale_reasons else None
        if scale_reason:
            fair = None
            entry["scaleIntegrity"] = {
                "lost": True,
                "reason": scale_reason,
                # Every dependency that failed for this row, so a reader
                # is not told a single cause when there were two.
                "reasons": scale_reasons,
            }

        # League scoring fit enters HERE — inside the value — and nowhere
        # else. It changes what a player is worth to this league; it is
        # not independent evidence that the market is mispricing him, so
        # adding it again as a component would count one effect twice.
        # Inert (exactly 1.0) whenever unmeasured, and the resolved level
        # is stamped so a reader can tell player-level from position-level
        # from none.
        if fair is not None and scoring_fit_board is not None:
            fit = scoring_fit_board.for_player(key, row.get("position"))
            if fit.multiplier != 1.0:
                fair = fair * float(fit.multiplier)
            entry["scoringFit"] = {
                "multiplier": fit.multiplier,
                "level": fit.level,
                "reason": fit.reason,
            }

        entry["fairValue"] = fair

        entry["marketValue"] = _market_value(row, anchor_key)

        if scale_reason:
            entry["unpricedReason"] = scale_reason
            # Both causes, not just the headline one. Caleb Banks loses
            # the IDP backbone AND the rookie ladder; counting only the
            # first made every such row invisible under the second, so
            # `anchor_free_board_lost_rookie_ladder` undercounted by the
            # whole set of rows that lost both.
            entry["unpricedReasons"] = list(scale_reasons)
        elif fair is None:
            entry["unpricedReason"] = UNPRICED_NOT_ON_BOARD
            entry["unpricedReasons"] = [UNPRICED_NOT_ON_BOARD]
        elif entry["marketValue"] is None:
            entry["unpricedReason"] = UNPRICED_NO_MARKET_VALUE
            entry["unpricedReasons"] = [UNPRICED_NO_MARKET_VALUE]

        out[key] = entry

    return out


def coverage(index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarise what a fair-value index could and could not price.

    Exists so a caller never has to infer coverage from the absence of
    rows.  ``unpricedByReason`` is the field that turns "no signal" from
    a silence into a statement.

    Counts EVERY reason a row carries, so the totals can exceed the row
    count — a row that lost two dependencies is counted under both.  It
    previously counted the singular ``unpricedReason``, which is the
    first cause only, so rows that lost both the IDP backbone and the
    rookie ladder never appeared under the rookie one at all.
    ``unpricedRows`` is reported alongside so the two numbers can never
    be confused for each other.
    """
    total = len(index)
    priced = sum(1 for e in index.values() if e.get("fairValue") and e.get("marketValue"))
    by_reason: dict[str, int] = {}
    unpriced_rows = 0
    for entry in index.values():
        reasons = entry.get("unpricedReasons")
        if not reasons:
            # Older/hand-built entries carry only the singular field.
            single = entry.get("unpricedReason")
            reasons = [single] if single else []
        if reasons:
            unpriced_rows += 1
        for reason in reasons:
            by_reason[str(reason)] = by_reason.get(str(reason), 0) + 1
    by_class: dict[str, int] = {}
    for entry in index.values():
        if entry.get("fairValue") and entry.get("marketValue"):
            cls = str(entry.get("assetClass") or "unknown")
            by_class[cls] = by_class.get(cls, 0) + 1
    return {
        "totalRows": total,
        "pricedRows": priced,
        "unpricedRows": unpriced_rows,
        "pricedByAssetClass": by_class,
        "unpricedByReason": by_reason,
    }
