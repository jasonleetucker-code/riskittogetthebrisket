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
