"""Build the canonical Market Trade Ledger and its coverage report.

``observations (all lanes) -> underlying-trade groups -> per-group target
disposition`` and then two artifacts, deliberately kept apart (owner addendum
item 2):

* the RAW archive (``market_trade_archive``) — append-only, never touched here;
* the CANONICAL underlying-trade ledger — ``data/market_trades/
  underlying_trades.sqlite``.  A pure derivation of the raw evidence, rebuilt
  wholesale on every build (temp file + atomic rename) exactly like the
  acquisition store's holdings: a derivation that can be patched is one that
  can drift from the evidence it claims to summarise.

The report publishes counts only — never another league's trade contents —
and names its own sampling biases so no reader mistakes the sample for the
dynasty population.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.trade import market_trade_archive as archive
from src.trade import market_trade_eval as ev
from src.trade import market_trade_format as mtf
from src.trade import market_trade_groups as grp
from src.trade import market_trade_normalize as norm

LEDGER_FILENAME = "underlying_trades.sqlite"
DEFAULT_TARGET_LEAGUE = "dynasty_main"

KNOWN_SAMPLING_BIASES = (
    "KTC Trade Database: trades from leagues whose members synced them to KTC; a 200-row "
    "rolling window, so coverage depends on collection cadence; KTC selects which rows feed its "
    "own trade-derived value (isUsedInVft).",
    "Sharp-discovery Sleeper lane: leagues reachable from a seeded manager graph — skewed toward "
    "engaged, multi-league, long-running dynasty managers; it is NOT a random sample of dynasty "
    "leagues and must not be presented as the global dynasty population.",
    "Own-league lane: our registered leagues only — one or two leagues' cultures.",
    "Sleeper-lane trades do not record FAAB money that changed hands inside a trade.",
    "Formats: KTC publishes no scoring card, so no KTC-only row can be NATIVE_COMPARABLE; "
    "discovery leagues captured before format capture existed carry partial formats until "
    "rediscovered.",
)


def _ledger_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else Path(archive.DEFAULT_DIR)) / LEDGER_FILENAME


def build_ledger(
    *,
    target_league: str = DEFAULT_TARGET_LEAGUE,
    allow_stale_target_scoring: bool = False,
    archive_path: Path | None = None,
    intel_ledger_path: Path | None = None,
    acquisition_path: Path | None = None,
    league_keys: Sequence[str] | None = None,
    ctx: norm.IdentityContext | None = None,
    target_format: mtf.TradeMarketFormat | None = None,
    registry: mtf.TranslatorRegistry | None = None,
    lanes: Sequence[str] | None = None,
    target_roster_positions: Sequence[str] | None = None,
) -> dict[str, Any]:
    built = norm.build_observations(
        archive_path=archive_path,
        intel_ledger_path=intel_ledger_path,
        acquisition_path=acquisition_path,
        league_keys=league_keys,
        ctx=ctx,
        allow_stale_scoring=allow_stale_target_scoring,
        **({"lanes": lanes} if lanes is not None else {}),
    )
    observations = built["observations"]
    grouping = grp.group_observations(observations)
    tgt = (
        target_format
        if target_format is not None
        else mtf.format_from_registry(
            target_league,
            allow_stale_scoring=allow_stale_target_scoring,
            roster_positions=target_roster_positions,
        )
    )
    for g in grouping.groups:
        fmt = g.get("_format") or mtf.TradeMarketFormat(source=mtf.SOURCE_UNKNOWN)
        d = mtf.disposition(fmt, tgt, observation=g, registry=registry)
        g["targetLeague"] = target_league
        g["disposition"] = d["disposition"]
        g["strongestUnsupportedAxis"] = d["strongestUnsupportedAxis"]
        g["comparability"] = d["comparability"]
        g["formatAuthority"] = d["formatAuthority"]
        g["translation"] = d["translation"]
        # Owner decision 2: BROAD_CONTEXT / TARGET_UNSUPPORTED carry 0.
        g["targetPriceAuthority"] = d["targetPriceAuthority"]
        g["broadContextKind"] = d["broadContextKind"]
        g["dispositionReasons"] = d["dispositionReasons"]
    return {
        "observations": observations,
        "grouping": grouping,
        "lanes": built["lanes"],
        "identityDirectory": built["identityDirectory"],
        "targetFormat": tgt,
        "targetLeague": target_league,
    }


def _jsonable_group(g: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in g.items() if not k.startswith("_")}


def persist_canonical_ledger(
    groups: Sequence[Mapping[str, Any]],
    *,
    root: Path | None = None,
    built_at: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> Path:
    """Rebuild the derived ledger wholesale; atomic rename into place.

    A run killed mid-build (OOM, timeout) cannot unlink its own temp file, so
    every build first removes stale temp files left by earlier runs, and the
    temp file is removed on any failure of this one.
    """
    target = _ledger_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    remove_stale_temp_files(target.parent)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        _write_ledger_db(tmp, groups, built_at=built_at, extra_meta=extra_meta)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # pragma: no cover
                pass
    try:
        os.chmod(target, 0o600)
    except OSError:  # pragma: no cover
        pass
    return target


#: A temp file younger than this may belong to a concurrent manual build and
#: is left alone; anything older is a killed run's leftover.
STALE_TEMP_AGE_SECONDS = 15 * 60


def remove_stale_temp_files(directory: Path, *, now: float | None = None) -> list[str]:
    """Delete ``.underlying_trades.sqlite.<pid>.tmp`` files left by killed runs
    (older than :data:`STALE_TEMP_AGE_SECONDS`).  Returns the names removed."""
    import time  # noqa: PLC0415

    cutoff = (time.time() if now is None else now) - STALE_TEMP_AGE_SECONDS
    removed: list[str] = []
    for p in Path(directory).glob(f".{LEDGER_FILENAME}.*.tmp"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed.append(p.name)
        except OSError:  # pragma: no cover - raced with another cleaner
            continue
    return removed


def _write_ledger_db(
    tmp: Path,
    groups: Sequence[Mapping[str, Any]],
    *,
    built_at: str | None,
    extra_meta: Mapping[str, Any] | None,
) -> None:
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE underlying_trades (
                underlying_trade_id TEXT PRIMARY KEY,
                dedupe_state TEXT NOT NULL,
                occurred_date TEXT,
                host TEXT,
                host_league_id TEXT,
                host_tx_id TEXT,
                team_count INTEGER,
                observation_count INTEGER NOT NULL,
                source_families TEXT NOT NULL,
                disposition TEXT,
                strongest_unsupported_axis TEXT,
                format_fingerprint TEXT,
                record_json TEXT NOT NULL
            );
            CREATE TABLE trade_members (
                underlying_trade_id TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                PRIMARY KEY (underlying_trade_id, observation_id)
            );
            CREATE TABLE formats (fingerprint TEXT PRIMARY KEY, format_json TEXT NOT NULL);
            CREATE INDEX idx_ut_date ON underlying_trades(occurred_date);
            CREATE INDEX idx_ut_disp ON underlying_trades(disposition);
            """
        )
        for g in groups:
            fmt = g.get("_format")
            fp = None
            if isinstance(fmt, mtf.TradeMarketFormat):
                full = fmt.to_full_dict()
                fp = full["fingerprint"]
                conn.execute(
                    "INSERT OR IGNORE INTO formats VALUES (?, ?)",
                    (fp, json.dumps(full, sort_keys=True, default=str)),
                )
            conn.execute(
                "INSERT INTO underlying_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    g["underlyingTradeId"],
                    g["dedupeState"],
                    g.get("occurredDate"),
                    g.get("host"),
                    g.get("hostLeagueId"),
                    g.get("hostTxId"),
                    g.get("teamCount"),
                    g["observationCount"],
                    json.dumps(g["sourceFamilies"]),
                    g.get("disposition"),
                    g.get("strongestUnsupportedAxis"),
                    fp,
                    json.dumps(_jsonable_group(g), sort_keys=True, default=str),
                ),
            )
            for m in g["members"]:
                conn.execute("INSERT INTO trade_members VALUES (?, ?)", (g["underlyingTradeId"], m))
        meta = {"builtAt": built_at or datetime.now(timezone.utc).isoformat(), **(extra_meta or {})}
        for k, v in meta.items():
            conn.execute("INSERT INTO meta VALUES (?, ?)", (k, json.dumps(v, default=str)))
        conn.commit()
    finally:
        conn.close()


def _date_range(dates: Sequence[str | None]) -> dict[str, Any]:
    ds = sorted(d for d in dates if d)
    return {"oldest": ds[0] if ds else None, "newest": ds[-1] if ds else None, "dated": len(ds)}


def coverage_report(result: Mapping[str, Any]) -> dict[str, Any]:
    observations = result["observations"]
    grouping: grp.GroupingResult = result["grouping"]
    groups = grouping.groups

    by_source_obs: dict[str, int] = {}
    for o in observations:
        by_source_obs[o["sourceFamily"]] = by_source_obs.get(o["sourceFamily"], 0) + 1

    def state_count(state: str) -> int:
        return sum(1 for g in groups if g["dedupeState"] == state)

    cross_source = [
        g
        for g in groups
        if g["dedupeState"] in (grp.CONFIRMED_DUPLICATE, grp.PROBABLE_DUPLICATE)
        and len(g["sourceFamilies"]) > 1
    ]
    mix: dict[str, int] = {}
    for g in groups:
        key = "+".join(g["sourceFamilies"])
        mix[key] = mix.get(key, 0) + 1

    sharp_leagues = {
        o["hostLeagueId"]
        for o in observations
        if o["sourceFamily"] == norm.SOURCE_SLEEPER_DISCOVERY and o.get("hostLeagueId")
    }
    idp_groups = [
        g for g in groups if (g.get("marketFormat") or {}).get("idp", {}).get("enabled") is True
    ]
    idp_leagues = {
        (g.get("host"), g.get("hostLeagueId")) for g in idp_groups if g.get("hostLeagueId")
    }
    with_idp_player = [
        g for g in groups if "includes_idp_player" in ev.classify_topology(g)["flags"]
    ]
    native = [g for g in groups if g.get("disposition") == mtf.NATIVE_COMPARABLE]
    native_idp = [
        g for g in native if (g.get("marketFormat") or {}).get("idp", {}).get("enabled") is True
    ]
    disp: dict[str, int] = {}
    axis: dict[str, int] = {}
    fmt_src: dict[str, int] = {}
    scoring_known = 0
    sf: dict[str, int] = {}
    for g in groups:
        disp[str(g.get("disposition"))] = disp.get(str(g.get("disposition")), 0) + 1
        if g.get("strongestUnsupportedAxis"):
            axis[g["strongestUnsupportedAxis"]] = axis.get(g["strongestUnsupportedAxis"], 0) + 1
        fmt_src[str(g.get("formatSource"))] = fmt_src.get(str(g.get("formatSource")), 0) + 1
        mf = g.get("marketFormat") or {}
        if mf.get("scoringKnown"):
            scoring_known += 1
        sfv = (mf.get("offense") or {}).get("superflex")
        sf[str(sfv)] = sf.get(str(sfv), 0) + 1

    tgt: mtf.TradeMarketFormat = result["targetFormat"]
    return {
        "rawSourceObservations": {
            "total": len(observations),
            "bySource": by_source_obs,
            "ktcArchive": result["lanes"].get(norm.SOURCE_KTC),
        },
        "underlyingTrades": grouping.volume,
        "confirmedUniqueUnderlyingTrades": state_count(grp.CONFIRMED_UNIQUE),
        "confirmedSameHostDuplicateGroups": sum(
            1
            for g in groups
            if g["dedupeState"] == grp.CONFIRMED_DUPLICATE
            and grp.REL_SAME_HOST_TX in g["relations"]
        ),
        "confirmedCrossSourceDuplicateGroups": sum(
            1 for g in cross_source if g["dedupeState"] == grp.CONFIRMED_DUPLICATE
        ),
        "probableDuplicateGroups": state_count(grp.PROBABLE_DUPLICATE),
        "probableCrossSourceGroups": sum(
            1 for g in cross_source if g["dedupeState"] == grp.PROBABLE_DUPLICATE
        ),
        "possibleOverlapGroups": state_count(grp.POSSIBLE_OVERLAP),
        # Residual dedupe risk made visible: rows the blocking can relate only
        # through a package match (no league identity), and incomplete records.
        "observationsWithoutLeagueIdentity": sum(
            1 for o in observations if grp._host_key(o) is None
        ),
        "partialRecordObservations": sum(1 for o in observations if grp.partial_record(o)),
        "unresolvedGroups": state_count(grp.UNRESOLVED),
        "sourceMix": dict(sorted(mix.items())),
        "sleeperSharpDiscoveryLeagueCount": len(sharp_leagues),
        "idpLeagueCount": len(idp_leagues),
        "idpLeagueTradeCount": len(idp_groups),
        "tradesWithAnIdpPlayer": len(with_idp_player),
        "targetLeague": result.get("targetLeague", DEFAULT_TARGET_LEAGUE),
        "targetFormat": tgt.to_dict(),
        "nativeComparableTrades": len(native),
        "nativeComparableIdpTrades": len(native_idp),
        "dispositions": disp,
        "strongestUnsupportedAxis": dict(sorted(axis.items(), key=lambda kv: -kv[1])),
        "dateCoverage": {
            src: _date_range(
                [o.get("occurredDate") for o in observations if o["sourceFamily"] == src]
            )
            for src in by_source_obs
        },
        "formatCoverage": {
            "byFormatSource": fmt_src,
            "groupsWithScoringCard": scoring_known,
            "superflex": sf,
        },
        "knownSamplingBiases": list(KNOWN_SAMPLING_BIASES),
        "lanes": result["lanes"],
        "identity": norm.identity_summary(observations),
        "identityDirectory": result.get("identityDirectory"),
    }


def evaluation_report(
    result: Mapping[str, Any],
    *,
    contract: Mapping[str, Any] | None,
    board_date: date | None,
) -> dict[str, Any]:
    groups = result["grouping"].groups
    out: dict[str, Any] = {
        "topology": ev.summarize_topology(groups),
        "latentFitReadiness": ev.latent_fit_readiness(groups),
    }
    if contract is None:
        out["residuals"] = {"available": False, "reason": "no_board_supplied"}
    else:
        out["residuals"] = ev.residual_report(
            groups, ev.BoardIndex(contract), board_date=board_date
        )
    return out


# ── AL-2a: target-format evidence census (report-only) ───────────────────
#
# A census of the evidence the ledger ALREADY holds, measured against the
# target league's ACTUAL format, so the first IDP latent-price model can be
# chosen from data (exact-format only / close-format hierarchical / exact +
# validated transformed) instead of decided in advance (owner directive
# 2026-10-01; ``docs/research/ADAPTIVE_LEARNING_2026-09-26.md`` §21.2 AL-2a;
# methods in ``docs/market_trades/TARGET_FORMAT_CENSUS.md``).
#
# Consumed, never rebuilt: dedupe states and volume bounds come from the
# groups ``build_ledger`` produced (``market_trade_groups``); per-axis
# comparability and dispositions from ``market_trade_format``; IDP-player
# detection from ``market_trade_eval.classify_topology``; position families
# from ``src.ros.lineup.lineup_position``; the TE scoring edge from
# ``te_premium.measure_te_demand`` (via ``TradeMarketFormat``); factual
# scoring identity from ``scoring_fingerprint`` (``card_hash``).  It writes no
# value, no disposition and no ledger row.
#
# PRIVACY — the publishable output (:func:`build_target_format_census`) is
# AGGREGATE ONLY: no league id or name, manager/user id, transaction or
# underlying-trade id, roster or package.  Counts in ``sections`` between 1
# and ``CENSUS_MIN_CELL - 1`` publish as ``"<5"``; value-keyed distributions
# (scoring values, starter counts) fold any value fewer than
# ``CENSUS_MIN_CELL`` DISTINCT LEAGUES contribute into ``OTHER_SMALL_CELLS``
# — trade-level distributions included, so one league with many trades
# cannot publish its own rare value — and a TE scoring key fewer than
# ``CENSUS_MIN_CELL`` leagues use is not named; medians need at least
# ``CENSUS_MIN_CELL`` leagues.
#
# UNKNOWN STAYS UNKNOWN — every distribution carries an explicit ``UNKNOWN``
# cell; an unknowable exact/near comparison is ``UNKNOWN``, never "no match".
#
# DYNASTY FAILS CLOSED — EXACT and NEAR both require the ledger's own
# ``dynastyState`` axis to be MATCH.  An unverified dynasty state is never
# EXACT or NEAR; a VERIFIED non-dynasty league (redraft, keeper) is
# ``NOT_DYNASTY``, however closely its lineup and card match.

#: v2 (owner decision 2): BROAD_CONTEXT is a disposition; the reconciliation
#: section counts it and splits timing-limited all-MATCH trades out of
#: "unknown only" (where v1 filed them).
CENSUS_VERSION = "al2a-target-format-census-v2"
CENSUS_MIN_CELL = 5
SUPPRESSED = "<5"
UNKNOWN_CELL = "UNKNOWN"
OTHER_SMALL_CELLS = "OTHER_SMALL_CELLS"
NOT_DYNASTY = "NOT_DYNASTY"

#: "Near" is DESCRIPTIVE ONLY and authorizes nothing: no trade becomes
#: comparable, transformable or fit-eligible because it is near.  Published
#: verbatim in every census so the count can be read against its exact rule.
NEAR_RULE: dict[str, Any] = {
    "authority": "descriptive_only_authorizes_nothing",
    "excludesExact": True,
    "dynastyState": (
        "dynastyState axis == MATCH (both sides verified dynasty); UNKNOWN -> UNKNOWN or "
        "NOT_NEAR, never NEAR; verified non-dynasty -> NOT_DYNASTY, never NEAR"
    ),
    "axesThatMustMatch": ["dynastyState", "qbDemand", "idpEnabled", "teRosterDemand"],
    "teamCountMaxAbsDiff": 2,
    "totalStartersMaxAbsDiff": 2,
    "idpStartersMaxAbsDiff": 2,
    "teScoringEdgeMustMatch": True,
    "scoringCardRequiredOnBothSides": True,
    "unknownOnAnyDimension": "UNKNOWN (never counted as near or as not-near)",
}

#: "Exact" = verified dynasty state AND factual scoring identity AND
#: starting-lineup identity.  Team count, roster depth and best-ball are NOT
#: part of it; NATIVE_COMPARABLE (all 13 axes MATCH) is reported beside it so
#: the difference is visible.
EXACT_RULE: dict[str, Any] = {
    "dynastyState": (
        "the ledger's dynastyState axis == MATCH (both sides verified dynasty); UNKNOWN -> "
        "never EXACT; verified non-dynasty (redraft / keeper) -> NOT_DYNASTY, never EXACT"
    ),
    "scoringIdentity": "scoring_fingerprint(actual card) equal on both sides",
    "rosterStructureIdentity": [
        "per-family (min,max) starter demand QB/RB/WR/TE/DL/LB/DB",
        "total starters",
        "IDP slot tokens",
    ],
    "notIncluded": ["teamCount", "rosterDepth", "bestBall"],
    "unknownOnAnyComponent": "UNKNOWN",
    "staleTargetScoring": (
        "a target scoring card accepted although its evidence is not fresh "
        "(--allow-stale-target-scoring) counts as UNKNOWN here: EXACT and NEAR are refused, "
        "never reported as a match"
    ),
}

#: IDP scoring categories reported per key (Sleeper's key vocabulary).  Any
#: other ``idp_*`` key on the target card is reported too.
IDP_SCORING_CATEGORIES: dict[str, tuple[str, ...]] = {
    "tackles": ("idp_tkl", "idp_tkl_solo", "idp_tkl_ast"),
    "tackleForLoss": ("idp_tkl_loss",),
    "sacks": ("idp_sack", "idp_sack_yd"),
    "qbHit": ("idp_qb_hit",),
    "passDefended": ("idp_pass_def",),
    "interception": ("idp_int", "idp_int_ret_yd"),
    "forcedFumble": ("idp_ff",),
    "fumbleRecovery": ("idp_fum_rec", "idp_fum_ret_yd"),
    "defensiveTd": ("idp_def_td",),
    "safety": ("idp_safe",),
    "blockedKick": ("idp_blk_kick",),
}

#: BROAD_CONTEXT is a real disposition since owner decision 2 (2026-10-01),
#: decided by ``market_trade_format.disposition`` — this census only COUNTS it.
#: The #1595 descriptive candidate rule is kept, re-applied to the verified
#: dynasty non-native population, so the bootstrap census (three dispositions)
#: and later ones (four) can be reconciled line by line.
BROAD_CONTEXT_RULE: dict[str, Any] = {
    "authority": "disposition_decided_by_market_trade_format_targetPriceAuthority_0",
    "definition": (
        "verified dynasty transaction with trustworthy identity/topology where one or more "
        "material target-format dimensions differ, are unknown, or have no validated "
        "translator; targetPriceAuthority = 0"
    ),
    "kinds": {
        mtf.BROAD_FORMAT_MISMATCH: (
            "at least one axis DIFFERENT and no validated translator (outranks unknown axes "
            "and timing: a known difference cannot be target-like)"
        ),
        mtf.BROAD_FORMAT_UNKNOWN: (
            "no axis DIFFERENT and at least one axis UNKNOWN, or no format observed; a "
            "timing cap, if any, is an additional reason"
        ),
        mtf.BROAD_TIMING_LIMITED: (
            "every axis observed and MATCH, but no valid evidence brackets the format at "
            "trade time; never implies exactness"
        ),
    },
    "kindPrecedence": [
        "hard_failure (TARGET_UNSUPPORTED)",
        mtf.BROAD_FORMAT_MISMATCH,
        mtf.BROAD_FORMAT_UNKNOWN,
        mtf.BROAD_TIMING_LIMITED,
    ],
    "unpriceableAssets": (
        "an asset whose identity is known but which no market prices (startup pick, "
        "grammar-refused pick with a real round 1-20) is not a hard failure: BROAD_CONTEXT "
        "of its format's kind, reason includes_unpriceable_asset (a NATIVE trade stays "
        "NATIVE, authority 1, with the same reason); a pick round outside 1-20 is unresolved"
    ),
    "targetUnsupportedIs": (
        "hard insufficiency only: redraft / keeper / unverified dynasty state, unusable "
        "transaction identity, analysis-blocking unresolved assets (unknown identity or "
        "unparseable asset label), invalid topology; the integrity gate runs before the "
        "NATIVE check (owner TARGET_UNSUPPORTED definition)"
    ),
    "formerCandidateRule": (
        "#1595: dynastyState axis == MATCH and disposition not NATIVE_COMPARABLE / "
        "VALIDATED_TRANSFORMABLE (then all TARGET_UNSUPPORTED)"
    ),
    "split": {
        "verifiedDynastyKnownMismatch": "at least one axis DIFFERENT",
        "verifiedDynastyTimingLimitedAllObservedMatch": (
            "every axis observed and MATCH and a format timing cap "
            "(market_trade_format.broad_context_kind == timing_limited)"
        ),
        "verifiedDynastyUnknownOnly": (
            "no axis DIFFERENT and at least one axis UNKNOWN or no format observed, timing "
            "capped or not (broad_context_kind == format_unknown)"
        ),
        "verifiedDynastyNativeFormatIntegrityFailure": (
            "every axis MATCH and timing not capped, kept off NATIVE only by a transaction "
            "integrity failure (broad_context_kind is None); NATIVE under v1, which did not "
            "gate NATIVE on integrity"
        ),
    },
    "dynastyBasisCaveat": (
        "a KTC row's dynasty state is a SOURCE-LEVEL claim (the KTC dynasty trade database), "
        "not a host league setting; counts are split by that basis"
    ),
}


def _cell(value: Any) -> str:
    if value is None:
        return UNKNOWN_CELL
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _dist(
    values: Sequence[Any],
    *,
    fold_small: bool = False,
    leagues: Sequence[Any] | None = None,
) -> dict[str, int]:
    """Counts per value; ``None`` -> ``UNKNOWN`` (never folded).

    ``fold_small`` folds a KNOWN value into :data:`OTHER_SMALL_CELLS` when
    fewer than :data:`CENSUS_MIN_CELL` DISTINCT LEAGUES contribute it.  Without
    ``leagues`` every value is its own league (a league-level distribution).
    With ``leagues`` (parallel to ``values``: a trade-level distribution) the
    fold counts distinct non-``None`` league keys, never trades; a trade with
    no league identity contributes no league, so it can never lift a value
    over the threshold."""
    if leagues is not None and len(leagues) != len(values):
        raise ValueError("leagues must be parallel to values")
    out: dict[str, int] = {}
    contributors: dict[str, set[Any]] = {}
    for i, v in enumerate(values):
        k = _cell(v)
        out[k] = out.get(k, 0) + 1
        if leagues is None:
            contributors.setdefault(k, set()).add(i)
        elif leagues[i] is not None:
            contributors.setdefault(k, set()).add(leagues[i])
    if fold_small:
        folded: dict[str, int] = {}
        small = 0
        for k, n in out.items():
            if k != UNKNOWN_CELL and len(contributors.get(k, ())) < CENSUS_MIN_CELL:
                small += n
            else:
                folded[k] = n
        if small:
            folded[OTHER_SMALL_CELLS] = small
        out = folded
    return dict(sorted(out.items()))


def _median(values: Sequence[float]) -> dict[str, Any]:
    import statistics  # noqa: PLC0415

    if len(values) < CENSUS_MIN_CELL:
        return {"median": None, "reason": f"suppressed_n_lt_{CENSUS_MIN_CELL}"}
    return {"median": float(statistics.median(values))}


def suppress_small_cells(obj: Any, *, min_cell: int = CENSUS_MIN_CELL) -> Any:
    """Every integer count in ``[1, min_cell)`` becomes :data:`SUPPRESSED`."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return SUPPRESSED if 0 < obj < min_cell else obj
    if isinstance(obj, Mapping):
        return {k: suppress_small_cells(v, min_cell=min_cell) for k, v in obj.items()}
    if isinstance(obj, list):
        return [suppress_small_cells(v, min_cell=min_cell) for v in obj]
    return obj


def _fmt_of(g: Mapping[str, Any]) -> mtf.TradeMarketFormat:
    fmt = g.get("_format")
    if isinstance(fmt, mtf.TradeMarketFormat):
        return fmt
    return mtf.TradeMarketFormat(source=mtf.SOURCE_UNKNOWN)


def _demand_cell(fmt: mtf.TradeMarketFormat, family: str) -> str | None:
    d = fmt.demand_for(family)
    return None if d is None else f"{d[0]}-{d[1]}"


def _lineup_structure(fmt: mtf.TradeMarketFormat) -> tuple | None:
    if fmt.demand is None or fmt.total_starters is None:
        return None
    fams = (*mtf.OFFENSE_FAMILIES, *mtf.IDP_FAMILIES)
    return (
        tuple(fmt.demand_for(f) for f in fams),
        fmt.total_starters,
        tuple(sorted((fmt.idp_slot_tokens or {}).items())),
    )


def _dynasty_axis(
    src: mtf.TradeMarketFormat,
    tgt: mtf.TradeMarketFormat,
    axes: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """The ledger's OWN ``dynastyState`` axis state — never re-derived here."""
    if axes is None:
        axes = mtf.compare_formats(src, tgt)
    return str(axes["dynastyState"]["state"])


def exact_state(
    src: mtf.TradeMarketFormat,
    tgt: mtf.TradeMarketFormat,
    axes: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool | None:
    """:data:`EXACT_RULE` as a conjunction: ``False`` when any component is
    known to differ (a verified non-dynasty league included), else ``None``
    when any component is unknowable, else ``True``."""
    dyn = _dynasty_axis(src, tgt, axes)
    a, b = _lineup_structure(src), _lineup_structure(tgt)
    parts: list[bool | None] = [
        None if dyn == mtf.UNKNOWN else dyn == mtf.MATCH,
        None if src.card_hash is None or tgt.card_hash is None else src.card_hash == tgt.card_hash,
        None if a is None or b is None else a == b,
    ]
    if any(p is False for p in parts):
        return False
    if any(p is None for p in parts):
        return None
    return True


def _within(a: int | None, b: int | None, tol: int) -> bool | None:
    if a is None or b is None:
        return None
    return abs(int(a) - int(b)) <= tol


def near_state(
    src: mtf.TradeMarketFormat,
    tgt: mtf.TradeMarketFormat,
    axes: Mapping[str, Mapping[str, Any]],
) -> str:
    """``EXACT`` / ``NEAR`` / ``NOT_NEAR`` / ``NOT_DYNASTY`` / ``UNKNOWN``
    under :data:`EXACT_RULE` and :data:`NEAR_RULE`.

    A VERIFIED non-dynasty league is :data:`NOT_DYNASTY` before anything else
    is looked at, so it is never EXACT or NEAR.  An unverified dynasty state is
    never EXACT or NEAR either: it lands in ``UNKNOWN``, or in ``NOT_NEAR``
    when another dimension is known to differ."""
    if _dynasty_axis(src, tgt, axes) == mtf.DIFFERENT:
        return NOT_DYNASTY
    if exact_state(src, tgt, axes) is True:
        return "EXACT"
    checks: list[bool | None] = []
    for name in NEAR_RULE["axesThatMustMatch"]:
        st = axes[name]["state"]
        checks.append(None if st == mtf.UNKNOWN else st == mtf.MATCH)
    checks.append(_within(src.teams, tgt.teams, NEAR_RULE["teamCountMaxAbsDiff"]))
    checks.append(
        _within(src.total_starters, tgt.total_starters, NEAR_RULE["totalStartersMaxAbsDiff"])
    )
    checks.append(_within(src.idp_starters, tgt.idp_starters, NEAR_RULE["idpStartersMaxAbsDiff"]))
    if src.scoring is None or tgt.scoring is None:
        checks.append(None)
    else:
        se, te = src.te_scoring_edge(), tgt.te_scoring_edge()
        checks.append(None if se is None or te is None else se == te)
    if any(c is False for c in checks):
        return "NOT_NEAR"
    if any(c is None for c in checks):
        return UNKNOWN_CELL
    return "NEAR"


def _league_key(g: Mapping[str, Any]) -> tuple[str, str] | None:
    if g.get("hostLeagueId"):
        return (str(g.get("host")), str(g["hostLeagueId"]))
    if g.get("leagueKey"):
        return ("registry", str(g["leagueKey"]))
    return None


#: Which captured format represents a league (host capture beats registry
#: beats a partial discovery row beats the vendor summary) — the same order
#: the grouping uses to choose a group's representative.
_FORMAT_RANK = {src: i for i, src in enumerate(grp._FORMAT_PREFERENCE)}


def _format_rank(g: Mapping[str, Any]) -> int:
    return _FORMAT_RANK.get(str(g.get("formatSource")), len(_FORMAT_RANK))


def _population(families: Sequence[str]) -> str:
    fams = set(families)
    if norm.SOURCE_OWN_LEAGUE in fams:
        return "own_registered_league"
    if norm.SOURCE_SLEEPER_DISCOVERY in fams:
        return "sharp_discovery_sleeper"
    if norm.SOURCE_KTC in fams:
        return "ktc_only"
    return "other"


def _asset_families(g: Mapping[str, Any]) -> set[str]:
    from src.ros.lineup import lineup_position  # noqa: PLC0415

    out: set[str] = set()
    for side in g.get("sides") or []:
        for a in side:
            kind = a.get("kind")
            if kind == norm.KIND_PLAYER:
                out.add(lineup_position(str(a.get("position") or "")) or UNKNOWN_CELL)
            elif kind == norm.KIND_PICK:
                out.add("PICK")
            elif kind == norm.KIND_FAAB:
                out.add("FAAB")
            else:
                out.add("UNRESOLVED")
    return out


def _key_relation(src: float, tgt: float) -> str:
    if src == tgt:
        return "bothAbsent" if src == 0 else "equal"
    if src == 0:
        return "absentInSource"
    if tgt == 0:
        return "absentInTarget"
    return "higherInSource" if src > tgt else "lowerInSource"


def _share_bucket(share: float) -> str:
    if share >= 1:
        return "1.00"
    if share >= 0.75:
        return "0.75-0.99"
    if share >= 0.5:
        return "0.50-0.74"
    if share >= 0.25:
        return "0.25-0.49"
    return "0.00-0.24"


def _idp_scoring_similarity(
    leagues: Sequence[mtf.TradeMarketFormat], tgt: mtf.TradeMarketFormat
) -> dict[str, Any]:
    eligible = [f for f in leagues if f.idp_enabled is True]
    with_card = [f for f in eligible if f.scoring is not None]
    out: dict[str, Any] = {
        "idpLeagues": len(eligible),
        "idpLeaguesWithScoringCard": len(with_card),
        "idpLeaguesWithoutScoringCard": len(eligible) - len(with_card),
        # Excluded because their IDP state is UNKNOWN — counted, never dropped
        # silently and never assumed to be non-IDP.
        "leaguesExcludedIdpEnabledUnknown": sum(1 for f in leagues if f.idp_enabled is None),
    }
    tgt_idp = tgt.scoring_subset(lambda k: k.startswith("idp_"))
    if tgt_idp is None:
        out["comparison"] = {"available": False, "reason": "target_scoring_card_unknown"}
        return out
    category_of = {k: c for c, ks in IDP_SCORING_CATEGORIES.items() for k in ks}
    keys = sorted(set(category_of) | set(tgt_idp))
    per_key: dict[str, Any] = {}
    for key in keys:
        rels: list[str] = []
        nonzero: list[float] = []
        tv = float(tgt_idp.get(key, 0.0))
        for f in with_card:
            sv = float((f.scoring or {}).get(key, 0.0))
            rels.append(_key_relation(sv, tv))
            if sv != 0:
                nonzero.append(sv)
        per_key[key] = {
            "category": category_of.get(key, "other_target_key"),
            "targetValue": tv,
            "relation": _dist(rels),
            "sourceNonZeroMedian": _median(nonzero),
        }
    tgt_keys = sorted(k for k, v in tgt_idp.items() if v != 0)
    shares: list[str | None] = []
    for f in with_card:
        if not tgt_keys:
            shares.append(None)
            continue
        hit = sum(1 for k in tgt_keys if float((f.scoring or {}).get(k, 0.0)) == tgt_idp[k])
        shares.append(_share_bucket(hit / len(tgt_keys)))
    out["comparison"] = {
        "available": True,
        "targetNonZeroIdpKeyCount": len(tgt_keys),
        "perKey": per_key,
        "exactMatchShareOfTargetNonZeroIdpKeys": _dist(shares),
        "summaryDefinition": (
            "per IDP league WITH a scoring card: the share of the target's nonzero idp_* keys "
            "whose value is exactly equal, bucketed. A distribution, not a similarity score; "
            "leagues without a card are counted in idpLeaguesWithoutScoringCard, not here"
        ),
    }
    return out


def _league_formats(
    groups: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], mtf.TradeMarketFormat], dict[tuple[str, str], str], int]:
    """One format per league: its most authoritative capture, latest first."""
    by_league: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for g in groups:
        k = _league_key(g)
        if k is not None:
            by_league.setdefault(k, []).append(g)
    fmts: dict[tuple[str, str], mtf.TradeMarketFormat] = {}
    pops: dict[tuple[str, str], str] = {}
    multi = 0
    for k, gs in by_league.items():
        top = min(_format_rank(g) for g in gs)
        chosen = max(
            (g for g in gs if _format_rank(g) == top),
            key=lambda g: (str(g.get("occurredDate") or ""), g["underlyingTradeId"]),
        )
        fmts[k] = _fmt_of(chosen)
        if len({_fmt_of(g).to_dict()["fingerprint"] for g in gs}) > 1:
            multi += 1
        pops[k] = _population([f for g in gs for f in g["sourceFamilies"]])
    return fmts, pops, multi


def _league_ids(fmts: Sequence[mtf.TradeMarketFormat], leagues: Sequence[Any] | None) -> list[Any]:
    """League contributor keys parallel to ``fmts``: the given ones for a
    trade-level block, else one distinct key per entry (league-level)."""
    return list(leagues) if leagues is not None else list(range(len(fmts)))


def _te_block(
    fmts: Sequence[mtf.TradeMarketFormat], leagues: Sequence[Any] | None = None
) -> dict[str, Any]:
    lids = _league_ids(fmts, leagues)
    key_users: dict[str, set[Any]] = {}
    for f, lid in zip(fmts, lids):
        for k in f.scoring_subset(mtf._is_te_key) or {}:
            if lid is not None:
                key_users.setdefault(k, set()).add(lid)
    # A TE key fewer than CENSUS_MIN_CELL leagues use is not even NAMED: the
    # key's existence alone would single those leagues out.
    named = sorted(k for k, u in key_users.items() if len(u) >= CENSUS_MIN_CELL)
    unnamed = sorted(
        {k for f in fmts for k in (f.scoring_subset(mtf._is_te_key) or {})} - set(named)
    )
    ktc = [(f, lid) for f, lid in zip(fmts, lids) if f.source == mtf.SOURCE_KTC]
    return {
        "teStarterDemandMinMax": _dist(
            [_demand_cell(f, "TE") for f in fmts], fold_small=True, leagues=lids
        ),
        "teScoringEdge": _dist([f.te_scoring_edge() for f in fmts]),
        "teScoringKeyValues": {
            key: _dist(
                [None if f.scoring is None else float(f.scoring.get(key, 0.0)) for f in fmts],
                fold_small=True,
                leagues=lids,
            )
            for key in named
        },
        "teScoringKeysFoldedBelowMinLeagues": len(unnamed),
        "vendorTepLevelKtcOnly": _dist(
            [f.vendor.get("tepLevel") for f, _ in ktc],
            fold_small=True,
            leagues=[lid for _, lid in ktc],
        ),
    }


def _idp_structure_block(
    fmts: Sequence[mtf.TradeMarketFormat], leagues: Sequence[Any] | None = None
) -> dict[str, Any]:
    lids = _league_ids(fmts, leagues)
    return {
        "idpStarters": _dist([f.idp_starters for f in fmts], fold_small=True, leagues=lids),
        "familyDemandMinMax": {
            fam: _dist([_demand_cell(f, fam) for f in fmts], fold_small=True, leagues=lids)
            for fam in mtf.IDP_FAMILIES
        },
        "idpFlexSlots": _dist(
            [
                None if f.idp_slot_tokens is None else int(f.idp_slot_tokens.get("IDP_FLEX", 0))
                for f in fmts
            ],
            fold_small=True,
            leagues=lids,
        ),
    }


def target_format_census(result: Mapping[str, Any]) -> dict[str, Any]:
    """The AL-2a census BEFORE small-cell suppression.  Publish only
    :func:`build_target_format_census`."""
    import dataclasses  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    observations = result["observations"]
    grouping: grp.GroupingResult = result["grouping"]
    groups = grouping.groups
    tgt: mtf.TradeMarketFormat = result["targetFormat"]
    cov = coverage_report(result)
    # Only FRESH scoring evidence authorizes reuse.  A stale card accepted for
    # research is withheld from EXACT / NEAR (fail closed: UNKNOWN, never a
    # degraded "match"); the acceptance itself is published.
    stale_target_scoring = tgt.vendor.get("staleScoringAcceptedForResearch") is True
    match_tgt = (
        dataclasses.replace(tgt, scoring=None, card_hash=None) if stale_target_scoring else tgt
    )

    def comp(g: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
        return g.get("comparability") or mtf.compare_formats(_fmt_of(g), tgt)

    def tid(g: Mapping[str, Any]) -> str:
        return g["underlyingTradeId"]

    # ── raw observations ────────────────────────────────────────────────
    obs_by_src: dict[str, int] = {}
    for o in observations:
        obs_by_src[o["sourceFamily"]] = obs_by_src.get(o["sourceFamily"], 0) + 1
    ktc_obs = [o for o in observations if o["sourceFamily"] == norm.SOURCE_KTC]
    ktc_lane = result["lanes"].get(norm.SOURCE_KTC) or {}
    raw = {
        "ktc": {
            # None (not 0) when the lane is unavailable: missing is never zero.
            "archiveRawRevisions": ktc_lane.get("rawRevisions"),
            "distinctKtcTradeIds": ktc_lane.get("distinctTrades"),
            "normalizedObservations": len(ktc_obs),
            "withHostLeagueId": sum(1 for o in ktc_obs if o.get("hostLeagueId")),
            "withoutHostLeagueId": sum(1 for o in ktc_obs if not o.get("hostLeagueId")),
            "byHostPlatform": _dist([o.get("host") for o in ktc_obs]),
            "upgradedToHostCapturedFormat": sum(
                1 for o in ktc_obs if o.get("formatSource") == "host_capture_via_discovery"
            ),
        },
        "sharpDiscoverySleeper": obs_by_src.get(norm.SOURCE_SLEEPER_DISCOVERY, 0),
        "ownLeagueSleeper": obs_by_src.get(norm.SOURCE_OWN_LEAGUE, 0),
        "total": len(observations),
    }

    # ── dedupe: the ledger's own groups and bounds, never re-derived ────
    vol = grouping.volume
    dedupe = {
        "underlyingTradesPointEstimate": vol["underlyingTradesPointEstimate"],
        "underlyingTradesLowerBound": vol["underlyingTradesLowerBound"],
        "underlyingTradesUpperBound": vol["underlyingTradesUpperBound"],
        "groupsByState": dict(sorted(vol["groupsByState"].items())),
        "confirmedUnderlyingTrades": sum(
            1 for g in groups if g["dedupeState"] in (grp.CONFIRMED_UNIQUE, grp.CONFIRMED_DUPLICATE)
        ),
        "crossSourceDuplicates": {
            "confirmed": cov["confirmedCrossSourceDuplicateGroups"],
            "probable": cov["probableCrossSourceGroups"],
        },
        "confirmedSameHostDuplicateGroups": cov["confirmedSameHostDuplicateGroups"],
        "unresolvedOverlaps": {
            "possibleOverlapGroups": cov["possibleOverlapGroups"],
            "unresolvedGroups": cov["unresolvedGroups"],
        },
        "observationsWithoutLeagueIdentity": cov["observationsWithoutLeagueIdentity"],
        "partialRecordObservations": cov["partialRecordObservations"],
        "sourceMix": cov["sourceMix"],
    }

    # ── per-trade facts ─────────────────────────────────────────────────
    idp_flag = {tid(g): "includes_idp_player" in ev.classify_topology(g)["flags"] for g in groups}
    near_by_trade = {tid(g): near_state(_fmt_of(g), match_tgt, comp(g)) for g in groups}
    trade_leagues = [_league_key(g) for g in groups]
    by_mix: dict[str, list[Mapping[str, Any]]] = {}
    for g in groups:
        by_mix.setdefault("+".join(g["sourceFamilies"]), []).append(g)

    def trade_dims(sel: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        fmts = [_fmt_of(g) for g in sel]
        return {
            "trades": len(sel),
            "superflex": _dist([f.superflex for f in fmts]),
            "idpEnabled": _dist([f.idp_enabled for f in fmts]),
            "scoringCardKnown": _dist([f.scoring is not None for f in fmts]),
            "byFormatSource": _dist([g.get("formatSource") for g in sel]),
        }

    # ── leagues ─────────────────────────────────────────────────────────
    league_fmt, league_pop, multi_fp = _league_formats(groups)
    lfmts = list(league_fmt.values())
    league_axes = {k: mtf.compare_formats(f, tgt) for k, f in league_fmt.items()}
    leagues = {
        "distinctLeagues": len(league_fmt),
        "byPopulation": _dist(list(league_pop.values())),
        "tradesWithoutLeagueIdentity": sum(1 for g in groups if _league_key(g) is None),
        "leaguesWithMoreThanOneFormatFingerprint": multi_fp,
        "idpEnabled": _dist([f.idp_enabled for f in lfmts]),
        "superflex": _dist([f.superflex for f in lfmts]),
        "byFormatSource": _dist([f.source for f in lfmts]),
        "metadataSufficiency": {
            "allThirteenAxesKnown": sum(
                1
                for a in league_axes.values()
                if all(x["state"] != mtf.UNKNOWN for x in a.values())
            ),
            "scoringCardKnown": sum(1 for f in lfmts if f.scoring is not None),
            "rosterDemandKnown": sum(1 for f in lfmts if f.demand is not None),
            "scoringCardAndRosterDemandKnown": sum(
                1 for f in lfmts if f.scoring is not None and f.demand is not None
            ),
            "knownPerAxis": {
                name: sum(1 for a in league_axes.values() if a[name]["state"] != mtf.UNKNOWN)
                for name in mtf.AXES
            },
            "definition": (
                "sufficient for comparison = every one of the 13 comparability axes against "
                "the target is MATCH or DIFFERENT (none UNKNOWN)"
            ),
        },
    }

    # ── exact / near vs target ──────────────────────────────────────────
    match = {
        "trades": {
            "byState": _dist(list(near_by_trade.values())),
            "nativeComparable": cov["nativeComparableTrades"],
            "exactAndNativeComparable": sum(
                1
                for g in groups
                if near_by_trade[tid(g)] == "EXACT"
                and g.get("disposition") == mtf.NATIVE_COMPARABLE
            ),
            "exactIdpTrades": sum(
                1 for g in groups if near_by_trade[tid(g)] == "EXACT" and idp_flag[tid(g)]
            ),
            "nearIdpTrades": sum(
                1 for g in groups if near_by_trade[tid(g)] == "NEAR" and idp_flag[tid(g)]
            ),
        },
        "leagues": {
            "byState": _dist(
                [near_state(f, match_tgt, league_axes[k]) for k, f in league_fmt.items()]
            )
        },
        "staleTargetScoringRefusal": {
            "refused": stale_target_scoring,
            "reason": (
                "target scoring evidence is not fresh and was accepted for research only; "
                "EXACT and NEAR need a fresh card, so they are withheld (UNKNOWN)"
                if stale_target_scoring
                else None
            ),
        },
    }

    # ── QB populations, TE, IDP ─────────────────────────────────────────
    qb = {
        "trades": _dist([_fmt_of(g).superflex for g in groups]),
        "tradesBySourceMix": {
            k: _dist([_fmt_of(g).superflex for g in v]) for k, v in sorted(by_mix.items())
        },
        "leagues": leagues["superflex"],
        "qbDemandMinMax": {
            "trades": _dist(
                [_demand_cell(_fmt_of(g), "QB") for g in groups],
                fold_small=True,
                leagues=trade_leagues,
            ),
            "leagues": _dist([_demand_cell(f, "QB") for f in lfmts], fold_small=True),
        },
        "definition": "superflex = QB eligible for at least 2 starting slots (QB max demand >= 2)",
    }
    te = {
        "trades": _te_block([_fmt_of(g) for g in groups], trade_leagues),
        "leagues": _te_block(lfmts),
        "note": (
            "teScoringEdge = te_premium.measure_te_demand(None, card).has_scoring_edge over the "
            "ACTUAL card; KTC's 0-3 TEP level is a vendor field with no measured crosswalk, "
            "shown separately and never translated"
        ),
    }
    idp_trades = [g for g in groups if idp_flag[tid(g)]]
    idp_league_trades = [g for g in groups if _fmt_of(g).idp_enabled is True]
    idp = {
        "tradesWithAnIdpPlayer": len(idp_trades),
        "tradesWithAnIdpPlayerByLeagueIdpEnabled": _dist(
            [_fmt_of(g).idp_enabled for g in idp_trades]
        ),
        "tradesWithAnIdpPlayerByDisposition": _dist([g.get("disposition") for g in idp_trades]),
        "tradesWithAnIdpPlayerByDedupeState": _dist([g["dedupeState"] for g in idp_trades]),
        "tradesInIdpLeagues": len(idp_league_trades),
        "leaguesWithIdp": sum(1 for f in lfmts if f.idp_enabled is True),
        "leaguesByIdpEnabled": leagues["idpEnabled"],
        "starterStructure": {
            "idpLeagues": _idp_structure_block([f for f in lfmts if f.idp_enabled is True]),
            "tradesInIdpLeagues": _idp_structure_block(
                [_fmt_of(g) for g in idp_league_trades],
                [_league_key(g) for g in idp_league_trades],
            ),
        },
        "scoringSimilarity": _idp_scoring_similarity(lfmts, tgt),
        "idpScoringAxisAmongIdpLeagueTrades": _dist(
            [comp(g)["idpScoring"]["state"] for g in idp_league_trades]
        ),
    }

    if stale_target_scoring and idp["scoringSimilarity"].get("comparison", {}).get("available"):
        # Descriptive only, and computed against a card whose evidence is not
        # fresh: labelled as degraded rather than presented as current.
        idp["scoringSimilarity"]["comparison"]["degraded"] = (
            "stale_target_scoring_accepted_for_research"
        )

    # ── per-axis, translator support, month, position ───────────────────
    axis_states = {name: _dist([comp(g)[name]["state"] for g in groups]) for name in mtf.AXES}
    single_diff: list[str] = []
    for g in groups:
        c = comp(g)
        diffs = [n for n in mtf.AXES if c[n]["state"] == mtf.DIFFERENT]
        if len(diffs) == 1 and not any(c[n]["state"] == mtf.UNKNOWN for n in mtf.AXES):
            single_diff.append(diffs[0])
    by_month: dict[str, dict[str, int]] = {}
    for g in groups:
        m = str(g["occurredDate"])[:7] if g.get("occurredDate") else "UNDATED"
        d = str(g.get("disposition"))
        by_month.setdefault(m, {})
        by_month[m][d] = by_month[m].get(d, 0) + 1
    pos_all: dict[str, int] = {}
    pos_native: dict[str, int] = {}
    for g in groups:
        for fam in _asset_families(g):
            pos_all[fam] = pos_all.get(fam, 0) + 1
            if g.get("disposition") == mtf.NATIVE_COMPARABLE:
                pos_native[fam] = pos_native.get(fam, 0) + 1

    # ── BROAD_CONTEXT (a disposition since owner decision 2) ────────────
    # The disposition and its kind/reasons come from market_trade_format; this
    # section only counts them, and re-applies #1595's candidate rule to the
    # verified-dynasty non-native population so a three-disposition census and
    # a four-disposition census can be reconciled.
    def _reason_counts(gs: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for g in gs:
            for r in g.get("dispositionReasons") or ():
                out[r] = out.get(r, 0) + 1
        return dict(sorted(out.items()))

    def _inc(bucket: dict[str, int], key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1

    broad_groups = [g for g in groups if g.get("disposition") == mtf.BROAD_CONTEXT]
    unsupported = [g for g in groups if g.get("disposition") == mtf.TARGET_UNSUPPORTED]
    by_kind_basis: dict[str, dict[str, int]] = {}
    for g in broad_groups:
        _inc(
            by_kind_basis.setdefault(str(g.get("broadContextKind")), {}),
            _fmt_of(g).dynasty_basis or UNKNOWN_CELL,
        )
    known_mismatch: dict[str, int] = {}
    timing_all_match: dict[str, int] = {}
    unknown_only: dict[str, int] = {}
    native_format_integrity: dict[str, int] = {}
    former_total = former_broad = former_unsupported = 0
    not_verified = 0
    for g in groups:
        if g.get("disposition") in (mtf.NATIVE_COMPARABLE, mtf.VALIDATED_TRANSFORMABLE):
            continue
        c = comp(g)
        if c["dynastyState"]["state"] != mtf.MATCH:
            not_verified += 1
            continue
        former_total += 1
        if g.get("disposition") == mtf.BROAD_CONTEXT:
            former_broad += 1
        else:
            former_unsupported += 1
        basis = _fmt_of(g).dynasty_basis or UNKNOWN_CELL
        # The disposition owner's own sub-kind rule (one definition, mutually
        # exclusive kinds: mismatch > unknown > timing_limited).  v1 filed
        # timing-capped all-observed-MATCH trades under "unknown only" — a
        # mislabel (review note); they are split out here, and a timing-capped
        # trade with an UNKNOWN axis is "unknown only", never timing-limited.
        kind = mtf.broad_context_kind(
            _fmt_of(g), c, (g.get("formatAuthority") or {}).get("formatTimingCap")
        )
        bucket = {
            mtf.BROAD_FORMAT_MISMATCH: known_mismatch,
            mtf.BROAD_FORMAT_UNKNOWN: unknown_only,
            mtf.BROAD_TIMING_LIMITED: timing_all_match,
            None: native_format_integrity,
        }[kind]
        _inc(bucket, basis)
    broad = {
        "expressibleByCurrentDispositions": True,
        "disposition": mtf.BROAD_CONTEXT,
        "targetPriceAuthority": mtf.TARGET_PRICE_AUTHORITY[mtf.BROAD_CONTEXT],
        "broadContextTrades": len(broad_groups),
        "broadContextByKind": _dist([g.get("broadContextKind") for g in broad_groups]),
        "broadContextByKindAndDynastyBasis": {
            k: dict(sorted(v.items())) for k, v in sorted(by_kind_basis.items())
        },
        "broadContextByReason": _reason_counts(broad_groups),
        "targetUnsupportedTrades": len(unsupported),
        "targetUnsupportedByReason": _reason_counts(unsupported),
        "formerCandidateBroadContext": {
            "verifiedDynastyKnownMismatchByDynastyBasis": dict(sorted(known_mismatch.items())),
            "verifiedDynastyTimingLimitedAllObservedMatchByDynastyBasis": dict(
                sorted(timing_all_match.items())
            ),
            "verifiedDynastyUnknownOnlyByDynastyBasis": dict(sorted(unknown_only.items())),
            "verifiedDynastyNativeFormatIntegrityFailureByDynastyBasis": dict(
                sorted(native_format_integrity.items())
            ),
            "total": former_total,
            "nowBroadContext": former_broad,
            "nowTargetUnsupportedHardFailure": former_unsupported,
        },
        "unsupportedOrUnverifiedDynastyNotVerified": not_verified,
    }

    group_pin = hashlib.sha256("\n".join(sorted(tid(g) for g in groups)).encode("utf-8"))
    lane_status = {
        lane: {
            "available": bool((st or {}).get("available")),
            "reason": (str((st or {}).get("reason") or "").split(":", 1)[0] or None),
        }
        for lane, st in sorted((result.get("lanes") or {}).items())
    }
    tdict = tgt.to_dict()
    return {
        "censusVersion": CENSUS_VERSION,
        "authority": "report_only_writes_nothing_authorizes_nothing",
        "inputs": {
            "targetLeague": result.get("targetLeague", DEFAULT_TARGET_LEAGUE),
            "targetFormatFingerprint": tdict["fingerprint"],
            "formatFingerprintVersion": mtf.FORMAT_FINGERPRINT_VERSION,
            "underlyingTradeSetSha256": group_pin.hexdigest(),
            "lanes": lane_status,
            "staleScoringAcceptedForResearch": stale_target_scoring,
        },
        "target": {
            "superflex": tdict["offense"]["superflex"],
            "teStarterDemandMinMax": _demand_cell(tgt, "TE"),
            "teScoringEdge": tdict["te"]["scoringEdge"],
            "idpEnabled": tdict["idp"]["enabled"],
            "idpStarters": tdict["idp"]["starters"],
            "idpSlotTokens": tdict["idp"]["slotTokens"],
            "teams": tdict["general"]["teams"],
            "totalStarters": tdict["offense"]["totalStarters"],
            "scoringCardKnown": tdict["scoringKnown"],
            "scoringEvidence": tgt.vendor.get("scoringEvidence"),
            "starterSource": tgt.vendor.get("starterSource"),
        },
        "definitions": {
            "minCell": CENSUS_MIN_CELL,
            "suppressedToken": SUPPRESSED,
            "unknownCell": UNKNOWN_CELL,
            "otherSmallCells": OTHER_SMALL_CELLS,
            "notDynasty": NOT_DYNASTY,
            "exact": EXACT_RULE,
            "near": NEAR_RULE,
            "broadContext": BROAD_CONTEXT_RULE,
            "idpScoringCategories": {k: list(v) for k, v in IDP_SCORING_CATEGORIES.items()},
            "idpTrade": (
                "an underlying trade with at least one player whose position family is "
                "DL/LB/DB (market_trade_eval.classify_topology flag includes_idp_player)"
            ),
            "leagueUnit": (
                "distinct (host, host league id); own registered leagues without a host id "
                "by registry key; trades with no league identity are counted, not attributed"
            ),
            "knownSamplingBiases": list(KNOWN_SAMPLING_BIASES),
        },
        "sections": {
            "rawObservations": raw,
            "dedupe": dedupe,
            "dispositions": dict(sorted(cov["dispositions"].items())),
            "strongestUnsupportedAxis": cov["strongestUnsupportedAxis"],
            "tradeFormatOverview": {
                "all": trade_dims(groups),
                "bySourceMix": {k: trade_dims(v) for k, v in sorted(by_mix.items())},
            },
            "leagues": leagues,
            "matchToTarget": match,
            "qbPopulations": qb,
            "te": te,
            "idp": idp,
            "axisStates": axis_states,
            "translatorSupportSingleDifferingAxisTrades": _dist(single_diff),
            "tradesByMonthAndDisposition": {
                k: dict(sorted(v.items())) for k, v in sorted(by_month.items())
            },
            "tradesContainingPositionFamily": {
                "all": dict(sorted(pos_all.items())),
                "nativeComparable": dict(sorted(pos_native.items())),
            },
            "broadContextReconciliation": broad,
        },
    }


def build_target_format_census(result: Mapping[str, Any]) -> dict[str, Any]:
    """The PUBLISHABLE census: every count in ``sections`` small-cell
    suppressed, plus the privacy statement."""
    census = target_format_census(result)
    census["sections"] = suppress_small_cells(census["sections"])
    census["privacy"] = {
        "aggregateOnly": True,
        "smallCellRule": (
            f"counts in [1, {CENSUS_MIN_CELL}) publish as {SUPPRESSED!r}; in value-keyed "
            f"distributions (league-level AND trade-level) a value fewer than "
            f"{CENSUS_MIN_CELL} distinct leagues contribute folds into {OTHER_SMALL_CELLS!r} "
            "whatever its trade count, and a trade without league identity contributes no "
            f"league; a TE scoring key fewer than {CENSUS_MIN_CELL} leagues use is not named "
            f"(counted in teScoringKeysFoldedBelowMinLeagues); medians need n >= "
            f"{CENSUS_MIN_CELL}"
        ),
        "excluded": [
            "league ids and names",
            "manager / user ids",
            "transaction and underlying-trade ids",
            "rosters and per-trade packages",
        ],
        "knownLimitation": (
            "a suppressed cell can sometimes be bounded from a published total minus its "
            "siblings (complementary disclosure); every cell is a format count, never an identity"
        ),
    }
    return census


def _md_value(v: Any) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _md_block(obj: Any, depth: int, lines: list[str]) -> None:
    if isinstance(obj, Mapping):
        flat = [(k, v) for k, v in obj.items() if not isinstance(v, (Mapping, list))]
        nested = [(k, v) for k, v in obj.items() if isinstance(v, (Mapping, list))]
        if flat:
            lines += ["| key | value |", "|---|---|"]
            lines += [f"| {k} | {_md_value(v)} |" for k, v in flat]
            lines.append("")
        for k, v in nested:
            lines += [f"{'#' * min(depth, 6)} {k}", ""]
            _md_block(v, depth + 1, lines)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (Mapping, list)):
                _md_block(v, depth, lines)
            else:
                lines.append(f"- {_md_value(v)}")
        lines.append("")


def census_markdown(census: Mapping[str, Any]) -> str:
    """Render a PUBLISHABLE (already suppressed) census as markdown."""
    lines = [
        "# Target-format evidence census (AL-2a)",
        "",
        "Report-only: aggregate counts and distributions over the completed-trade ledger, "
        "measured against the target league's ACTUAL format. Writes nothing; authorizes "
        f"nothing. Counts below {CENSUS_MIN_CELL} show as `{SUPPRESSED}`; `{UNKNOWN_CELL}` is "
        "never folded into a known bucket.",
        "",
    ]
    for top in ("inputs", "target", "sections", "definitions", "privacy"):
        if top in census:
            lines += [f"## {top}", ""]
            _md_block(census[top], 3, lines)
    return "\n".join(lines).rstrip() + "\n"
