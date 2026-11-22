"""Forward validation scoreboard: does a value predict where the market goes?

Owner Top-10 dynasty directive 2026-11-21, item #1 (intake DYN10, unit V1).
**Research tooling.  It changes nothing served**: no value, vote, weight,
flag, route or contract field, and it registers nothing in the Hill
independent-validation registry (``src/model_registry/independent_validation.py``
is owner-gated; :data:`INDEPENDENT_VALIDATION_ASSESSMENT` only says whether
this output could become a candidate).

The question, asked per origin date D and horizon H:

* **Board edge.** When the served board (``canonical_board`` lane,
  ``rankDerivedValue``) disagrees with the market at D, does the market
  later move toward the board?
* **Source edge.** The same question for each value-direct source's own
  number.
* **Persistence.** How much of the market at D+H is the market at D
  ("the market stays put"), so any skill above is read against that.

Reused rather than rebuilt (Consensus Edge already runs this measurement
for its own components):

* folds, horizon snapping, the minimum-pairs floor, Spearman, the
  ``marketValue`` and ``random`` benchmarks and the verdict language:
  :mod:`src.consensus_edge.backtest` (``folds`` walks NON-overlapping
  windows and snaps the horizon FORWARD, the rule
  :func:`src.consensus_edge.outcomes.horizon_date` states);
* the outcome: :func:`src.consensus_edge.outcomes.forward_returns`, the
  cohort-excess forward market return, and its ``attrition`` census;
* the gap: :func:`src.consensus_edge.mispricing.log_gap`, CE's mispricing
  form ``log((x + 1) / (market + 1))``.  Spearman is rank-based, so the
  plain ``(x - market) / market`` gap would give the identical rho;
* every historical read: :mod:`src.history.asof` (``batch_as_of`` with
  ``max_age_days=0``, so a value carried forward from an earlier day is
  missing, not current).  Nothing here opens a raw store for values.

Market target, fixed per fold so a change of instrument can never register
as a market move:

* offense and picks: KTC Market (``ktcCrowdTradesSfTep``) when it observed
  the asset class on BOTH fold dates, else the historical KTC board
  (``ktcSfTep``, then ``ktc``: the archive carries KTC pick prices under
  ``ktc`` only).  The instrument is chosen per asset class and named on
  every fold;
* IDP: ``idpTradeCalc``.

The board is partly in-sample with that target: KTC Crowd and KTC Trades
both vote in it and KTC Market is their published blend, and
``idpTradeCalc`` votes in it too.  The test still means something (does the
board's DEVIATION from the market predict the market's move?), but
agreement that comes from shared lineage is not independent evidence
(CLAUDE.md, "Signal independence").  The output carries that caveat.

Discipline, each pinned by a test:

* **No leakage.**  Every predictor is an exact observation dated D, read
  through the as-of layer, which cannot select a later row.  Only the
  outcome reads D+H.
* **Missing is never zero.**  A source with no observation of an asset at
  D leaves that asset out of the source's cross-section.  A non-positive
  value is missing too.
* **No pooling.**  Each origin is its own cross-section; summaries average
  per-origin rhos and report every origin.
* **A floor.**  Below ``backtest.MIN_PAIRS_PER_FOLD`` pairs a cross-section
  is recorded as unusable with its count, not reported as a number.
* **No verdict below two usable origins.**
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import statistics
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.bdvm.signal_diagnostics import pearson
from src.consensus_edge import backtest as bt
from src.consensus_edge import outcomes as oc
from src.consensus_edge.fair_value import MARKET_ANCHOR_BY_ASSET_CLASS
from src.consensus_edge.mispricing import log_gap
from src.history import asof, backfill, keys, store
from src.sources.ktc_market import (
    KTC_CROWD_KEY,
    KTC_HISTORICAL_MARKET_KEYS,
    KTC_MARKET_KEY,
    KTC_TRADES_KEY,
)
from src.sources.source_census import provider_of
from src.utils.name_clean import normalize_position

SCHEMA = "forward-scoreboard/v1"

DEFAULT_HORIZONS: tuple[int, ...] = (30, 60, 90)

GROUP_ALL = "ALL"
GROUPS: tuple[str, ...] = (GROUP_ALL, "QB", "RB", "WR", "TE", "IDP", "PICK")
_OFFENSE_GROUPS = frozenset({"QB", "RB", "WR", "TE"})

# A cross-section below this many pairs is noise; same floor CE uses.
MIN_PAIRS = bt.MIN_PAIRS_PER_FOLD

# Below this many usable origins no verdict is given at all.
MIN_USABLE_ORIGINS_FOR_VERDICT = 2

# Market instruments.
MARKET_KTC = KTC_MARKET_KEY
MARKET_KTC_HISTORICAL = KTC_HISTORICAL_MARKET_KEYS[0]
MARKET_IDP = MARKET_ANCHOR_BY_ASSET_CLASS[keys.ASSET_CLASS_IDP]
# Per asset class, the market instruments in preference order.  KTC's
# historical keys are the repo's own (``KTC_HISTORICAL_MARKET_KEYS``): the
# archive's raw payload carries KTC pick prices under ``ktc`` only.
_OFFENSE_MARKETS: tuple[str, ...] = (MARKET_KTC, *KTC_HISTORICAL_MARKET_KEYS)
MARKET_CHAINS: dict[str, tuple[str, ...]] = {
    keys.ASSET_CLASS_OFFENSE: _OFFENSE_MARKETS,
    keys.ASSET_CLASS_PICK: _OFFENSE_MARKETS,
    keys.ASSET_CLASS_IDP: (MARKET_IDP,),
}
_MARKET_KEYS: tuple[str, ...] = (*_OFFENSE_MARKETS, MARKET_IDP)

BOARD_SERIES = "board"

# Source keys never scored as a predictor, with the reason.  Signals' IDP
# boards are family-local scales: one cross-section over DL, LB and DB
# would rank one family's scale against another's.
EXCLUDED_SOURCES: dict[str, str] = {
    "signalsIdpDl": "family-local value scale; a DL/LB/DB cross-section is not comparable",
    "signalsIdpLb": "family-local value scale; a DL/LB/DB cross-section is not comparable",
    "signalsIdpDb": "family-local value scale; a DL/LB/DB cross-section is not comparable",
}

# KTC's three published modes ride in the archive as site_raw CSVs only.
# The live recorder stores all three (``record._CONTRACT_RETAIL_KEYS``);
# the archive backfill reads the raw payload, which carries none of them.
SITE_RAW_KEYS: tuple[str, ...] = (KTC_CROWD_KEY, KTC_TRADES_KEY, KTC_MARKET_KEY)
ORIGIN_SITE_RAW = "research:forward_scoreboard:site_raw"

# ``position_family`` only reads the family, so every IDP position cohorts
# as IDP and picks cohort on their own (family OTHER).
_COHORT_POSITION: dict[str, str] = {"IDP": "LB", "PICK": "PICK"}

REASON_NO_OBSERVATION = "no observation of this series on the origin date"
REASON_IS_TARGET = "this series is the market instrument for every scorable asset here"
REASON_NO_MARKET = "no market instrument observed on both fold dates"

TARGET_DEFINITION = {
    "offense": (
        f"the first of {list(_OFFENSE_MARKETS)} (KTC Market, then the historical KTC "
        "boards) that observed the class on both fold dates; named per fold"
    ),
    "pick": f"chosen the same way from {list(_OFFENSE_MARKETS)}, per fold",
    "idp": MARKET_IDP,
}

REALIZED_POINTS: dict[str, str] = {
    "state": "unavailable",
    "reason": (
        "No committed offline per-player realized fantasy points exist in the "
        "repository. src/nfl_data/realized_points scores nflverse weekly stat rows "
        "fetched over the network into a gitignored cache (src/nfl_data/cache.py); "
        "no tracked data/ file carries them, and this tool adds no network fetch."
    ),
}

INDEPENDENT_VALIDATION_ASSESSMENT: dict[str, Any] = {
    "registered": False,
    "couldQualifyAsIs": False,
    "reasons": [
        "The offense and pick target is KTC (provider keepTradeCut), the training "
        "substrate of the OFFENSE Hill master. The registry's owner rule: KTC evidence "
        "alone is not independent for a KTC-trained curve.",
        "No preregistration was committed before this measurement. A registry target "
        "needs a committed, unedited preregistration that precedes its registry entry.",
        "This scores board and source gaps against later prices. A registry target is "
        "a pass/fail rule over champion and challenger Hill parameters.",
        "The IDP target, idpTradeCalc, also votes in the board.",
    ],
    "whatWouldBeNeeded": (
        "A preregistered rule scored against a target with registered non-KTC "
        "provenance (for example the completed-trade ledger with its KTC components "
        "excluded), approved by the owner before registration."
    ),
}

CAVEATS: tuple[str, ...] = (
    "In-sample with the target: KTC Crowd and KTC Trades vote in the served board, "
    "KTC Market is their published blend, and idpTradeCalc votes too. The board's "
    "deviation from the market is still a fair test of whether the market moves "
    "toward the board, but agreement from shared lineage is not independent evidence.",
    "Per-source KTC rows (ktc, ktcSfTep, ktcCrowdSfTep, ktcTradesSfTep) are modes "
    "and calibration states of the target's own provider, not independent votes. "
    "KTC Market is the blend of Crowd and Trades, so a Crowd gap and a Trades gap "
    "against it are close to mirror images by construction.",
    "Market movement, not production: the outcome is the cohort-excess change in the "
    "market's own price. Realized points are reported separately (realizedPoints).",
    "Folds are non-overlapping and anchored at the panel's first date, so the fold "
    "count is small by construction. CE's verdict language needs 3 usable origins; "
    "below 2 no verdict is given.",
    "Survivorship: an asset that leaves the market's board before the horizon has no "
    "outcome. Each fold reports that attrition by reason.",
    "Day-granular: an observation dated D is 'as of D'. Archive scrape stamps are "
    "naive; the ledger records that rather than normalizing it.",
)


class ArchiveUnavailable(RuntimeError):
    """The archive directory is missing or holds no export bundles."""


@dataclass(frozen=True)
class SeriesSpec:
    """One predictor series: a ledger lane plus source key."""

    series_id: str
    lane: str
    source_key: str


# ── Archive → temporary ledger ──────────────────────────────────────────


def archive_fingerprint(archive_dir: Path) -> dict[str, Any]:
    """Pinned-input provenance for the committed archive."""
    zips = sorted(archive_dir.glob("dynasty_export_*.zip"))
    digest = hashlib.sha256()
    for z in zips:
        digest.update(z.name.encode("utf-8"))
        digest.update(hashlib.sha256(z.read_bytes()).digest())
    return {
        "zipCount": len(zips),
        "firstZip": zips[0].name if zips else None,
        "lastZip": zips[-1].name if zips else None,
        "sha256": digest.hexdigest(),
    }


def _positive(value: Any) -> float | None:
    """A strictly positive finite number, else ``None`` (missing, never 0)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return got if math.isfinite(got) and got > 0 else None


def site_raw_observations(
    raw: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    source_key: str,
    observed_date: str,
    origin: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Ledger observations for one site_raw CSV of one archive bundle.

    Keys exactly the way :func:`src.history.backfill.observations_from_raw`
    keys the same bundle's payload rows (the ``_sleeperId`` and
    ``sleeper.positions`` of THAT bundle, then :mod:`src.history.keys`), so a
    CSV row lands on the same asset key as the payload row for the same
    name.  A test pins that parity.  No fuzzy matching: a name the payload
    does not carry gets the identity-grade name key, never a guess.
    """
    players = raw.get("players") if isinstance(raw.get("players"), dict) else {}
    sleeper = raw.get("sleeper") if isinstance(raw.get("sleeper"), dict) else {}
    positions_by_name = (
        sleeper.get("positions") if isinstance(sleeper.get("positions"), dict) else {}
    )
    observed_at = str(raw.get("scrapeTimestamp") or "") or None
    zone = None
    if observed_at:
        zone = "utc" if ("+" in observed_at or observed_at.endswith("Z")) else "naive"

    out: list[dict[str, Any]] = []
    counts = {"rows": 0, "nonPositiveOrBlank": 0, "unresolved": 0, "nameKeyed": 0}
    for row in rows:
        counts["rows"] += 1
        name = str(row.get("name") or "").strip()
        value = _positive(row.get("value"))
        if not name or value is None:
            counts["nonPositiveOrBlank"] += 1
            continue
        pick_key = keys.pick_asset_key(name)
        if pick_key is not None:
            asset_key, asset_class, position, player_id = (
                pick_key,
                keys.ASSET_CLASS_PICK,
                "PICK",
                None,
            )
        else:
            prow = players.get(name) if isinstance(players.get(name), dict) else {}
            player_id = str(prow.get("_sleeperId") or "") or None
            position = (
                positions_by_name[name] if isinstance(positions_by_name.get(name), str) else None
            )
            asset_key = keys.player_asset_key(player_id, name, position)
            if asset_key is None:
                counts["unresolved"] += 1
                continue
            if player_id is None:
                counts["nameKeyed"] += 1
            group = keys.canonical_position_group(position) if position else ""
            if group == "OFFENSE":
                asset_class = keys.ASSET_CLASS_OFFENSE
            elif group == "IDP":
                asset_class = keys.ASSET_CLASS_IDP
            else:
                asset_class = "unknown"
        out.append(
            {
                "asset_key": asset_key,
                "asset_class": asset_class,
                "lane": store.LANE_SOURCE,
                "source_key": source_key,
                "observed_date": observed_date,
                "observed_at": observed_at,
                "observed_at_zone": zone,
                "value": value,
                "rank": None,
                "tier": None,
                "confidence": None,
                "display_name": name,
                "position": position,
                "player_id": player_id,
                "scope": None,
                "pipeline_version": None,
                "origin": origin,
            }
        )
    return out, counts


def _manifest(z: zipfile.ZipFile) -> dict[str, Any]:
    try:
        with z.open("manifest.json") as fh:
            got = json.load(fh)
    except (KeyError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def ingest_site_raw_market_modes(
    archive_dir: Path,
    *,
    path: Path,
    source_keys: Sequence[str] = SITE_RAW_KEYS,
) -> dict[str, Any]:
    """Write the archive's KTC-mode CSVs into a TEMPORARY ledger.

    Bundle selection is the backfill's own (``_select_by_date`` +
    ``_load_raw``: one bundle per UTC date, newest first, first readable
    wins), so a CSV observation shares its date and identity evidence with
    the payload rows the backfill wrote.  A CSV the bundle's manifest does
    not list as freshly fetched is a carry-forward, not that day's
    observation, and is skipped.  Never call this on
    ``data/temporal_ledger.sqlite``; :func:`build_archive_ledger` refuses.
    """
    totals = Counter()
    per_key: dict[str, Counter] = {k: Counter() for k in source_keys}
    for filename_date, candidates in backfill._select_by_date(archive_dir):
        chosen: tuple[Path, str, dict[str, Any]] | None = None
        for candidate in candidates:
            manifest_date, raw = backfill._load_raw(candidate)
            if raw is None:
                continue
            chosen = (candidate, manifest_date or filename_date, raw)
            break
        if chosen is None:
            totals["unreadableDates"] += 1
            continue
        zip_path, effective_date, raw = chosen
        origin = f"{ORIGIN_SITE_RAW}:zip={zip_path.name}"
        observations: list[dict[str, Any]] = []
        with zipfile.ZipFile(zip_path) as z:
            names = set(z.namelist())
            fresh = _manifest(z).get("siteRawFresh")
            fresh_set = set(fresh) if isinstance(fresh, list) else None
            for key in source_keys:
                member = f"site_raw/{key}.csv"
                if member not in names:
                    continue
                if fresh_set is not None and f"{key}.csv" not in fresh_set:
                    per_key[key]["skippedNotFresh"] += 1
                    continue
                with z.open(member) as fh:
                    rows = list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")))
                obs, counts = site_raw_observations(
                    raw, rows, source_key=key, observed_date=effective_date, origin=origin
                )
                observations.extend(obs)
                per_key[key]["dates"] += 1
                per_key[key].update(counts)
        totals["dates"] += 1
        if observations:
            result = store.write_observations(observations, path=path)
            totals["written"] += result["written"]
            totals["duplicates"] += result["duplicates"]
            totals["contentConflicts"] += len(result["contentConflicts"])
            totals["rejected"] += len(result["rejected"])
    return {
        "totals": dict(sorted(totals.items())),
        "bySource": {k: dict(sorted(v.items())) for k, v in per_key.items()},
    }


def build_archive_ledger(archive_dir: Path, ledger: Path) -> dict[str, Any]:
    """Build a temporary ledger from the committed archive.

    Stage 1 is the canonical builder's own archive stage
    (``backfill.backfill_archive``); stage 2 adds the KTC-mode CSVs.  The
    production ledger path is refused outright: this tool writes only to a
    path its caller owns.
    """
    if ledger.resolve() == store.DB_PATH.resolve():
        raise ValueError(f"refusing to write the production ledger {store.DB_PATH}")
    if not archive_dir.is_dir() or not any(archive_dir.glob("dynasty_export_*.zip")):
        raise ArchiveUnavailable(f"no export bundles under {archive_dir}")
    payload = backfill.backfill_archive(archive_dir, path=ledger)
    site_raw = ingest_site_raw_market_modes(archive_dir, path=ledger)
    return {
        "archive": archive_fingerprint(archive_dir),
        "payloadBackfill": payload["totals"],
        "siteRawIngest": site_raw,
    }


# ── Measurement ─────────────────────────────────────────────────────────


def asset_group(asset_class: Any, position: Any) -> str | None:
    """QB / RB / WR / TE / IDP / PICK, or ``None`` when the row cannot be
    placed (counted by the caller, never guessed)."""
    if asset_class == keys.ASSET_CLASS_PICK:
        return "PICK"
    if asset_class == keys.ASSET_CLASS_IDP:
        return "IDP"
    if asset_class == keys.ASSET_CLASS_OFFENSE:
        pos = normalize_position(position)
        return pos if pos in _OFFENSE_GROUPS else None
    return None


def fold_instruments(
    origin: str,
    horizon: str,
    classes_on: Callable[[str, str], set[str]],
) -> dict[str, str | None]:
    """``{asset_class: instrument}`` for one fold.

    ``classes_on(instrument, date)`` is the set of asset classes the
    instrument observed on that date.  Per class, the first instrument in
    :data:`MARKET_CHAINS` that observed the class on BOTH fold dates wins,
    so the same instrument prices both ends.  The choice reads which rows
    exist, never their values.  ``None`` means no market could be measured
    for that class over this fold.
    """
    out: dict[str, str | None] = {}
    for asset_class, chain in MARKET_CHAINS.items():
        out[asset_class] = None
        for inst in chain:
            if asset_class in classes_on(inst, origin) and asset_class in classes_on(inst, horizon):
                out[asset_class] = inst
                break
    return out


class _LedgerReader:
    """Exact-date reads through :mod:`src.history.asof`, memoized.

    Adjacent folds share a boundary date and every horizon reuses the same
    origins, so each (date, lane, source) is read once.
    """

    def __init__(self, ledger: Path):
        self.ledger = ledger
        self._cache: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}

    def exact(self, on_date: str, lane: str, source_key: str) -> dict[str, dict[str, Any]]:
        """``{asset_key: {value, assetClass, position}}`` observed EXACTLY on
        ``on_date``.  Nearest-prior answers are refused (``max_age_days=0``);
        a non-positive value is missing."""
        cache_key = (on_date, lane, source_key)
        if cache_key in self._cache:
            return self._cache[cache_key]
        census = asof.assets_observed_on(
            on_date, lane=lane, source_key=source_key, path=self.ledger
        )
        out: dict[str, dict[str, Any]] = {}
        if census:
            result = asof.batch_as_of(
                list(census),
                on_date,
                lane=lane,
                source_key=source_key,
                max_age_days=0,
                path=self.ledger,
            )
            for key, res in result["results"].items():
                if res.get("fidelity") != asof.FIDELITY_EXACT:
                    continue
                value = _positive(res.get("value"))
                if value is None:
                    continue
                out[key] = {
                    "value": value,
                    "assetClass": census[key]["assetClass"],
                    "position": census[key]["position"],
                }
        self._cache[cache_key] = out
        return out

    def classes_on(self, source_key: str, on_date: str) -> set[str]:
        """Asset classes the source observed exactly on ``on_date``."""
        return {
            str(row["assetClass"])
            for row in self.exact(on_date, store.LANE_SOURCE, source_key).values()
        }


def _residuals(ys: Sequence[float], xs: Sequence[float]) -> list[float] | None:
    """OLS residuals of ``ys`` on ``xs`` (with intercept); ``None`` if
    ``xs`` has no variance."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return [y - (my + beta * (x - mx)) for x, y in zip(xs, ys)]


def persistence(
    keys_: Iterable[str],
    prices_d: Mapping[str, float],
    prices_h: Mapping[str, float],
) -> dict[str, Any]:
    """How much of the market at D+H is the market at D.

    ``spearmanLevel`` is the rank persistence of price; ``r2LogLevel`` the
    share of log-price variance at D+H explained by log price at D (the
    "market stays put" baseline); ``medianAbsLogReturn`` how far a typical
    price moved at all; ``unchangedShare`` the share of prices that did not
    move (a frozen market gives an outcome of ties, not a signal).
    """
    pairs = [(prices_d[k], prices_h[k]) for k in sorted(keys_) if k in prices_d and k in prices_h]
    out: dict[str, Any] = {"n": len(pairs)}
    if len(pairs) < MIN_PAIRS:
        out.update(
            {
                "spearmanLevel": None,
                "r2LogLevel": None,
                "medianAbsLogReturn": None,
                "unchangedShare": None,
                "reason": f"only {len(pairs)} paired rows (need {MIN_PAIRS})",
            }
        )
        return out
    xs = [math.log(a) for a, _ in pairs]
    ys = [math.log(b) for _, b in pairs]
    r = pearson(xs, ys)
    out["spearmanLevel"] = bt.spearman([a for a, _ in pairs], [b for _, b in pairs])
    out["r2LogLevel"] = (r * r) if r is not None else None
    out["medianAbsLogReturn"] = statistics.median(abs(y - x) for x, y in zip(xs, ys))
    out["unchangedShare"] = sum(1 for a, b in pairs if a == b) / len(pairs)
    return out


def increment_over_persistence(
    keys_: Sequence[str],
    gaps: Mapping[str, float],
    prices_d: Mapping[str, float],
    prices_h: Mapping[str, float],
) -> dict[str, float | None]:
    """What the gap adds to "the market stays put", on the same pairs.

    ``partialR`` is the correlation of the gap with log price at D+H once
    log price at D is partialled out of both (its sign is the direction);
    ``deltaR2 = (1 - R2_persistence) x partialR**2`` is the exact OLS
    increase in R2 from adding the gap to the persistence regression.
    Linear in logs, so it complements the rank-based headline.
    """
    ks = [k for k in keys_ if k in gaps and k in prices_d and k in prices_h]
    xs = [math.log(prices_d[k]) for k in ks]
    ys = [math.log(prices_h[k]) for k in ks]
    gs = [gaps[k] for k in ks]
    r_xy = pearson(xs, ys)
    ry = _residuals(ys, xs)
    rg = _residuals(gs, xs)
    if r_xy is None or ry is None or rg is None:
        return {"r2Persistence": None, "partialR": None, "deltaR2": None}
    partial = pearson(rg, ry)
    r2 = r_xy * r_xy
    return {
        "r2Persistence": r2,
        "partialR": partial,
        "deltaR2": ((1.0 - r2) * partial * partial) if partial is not None else None,
    }


def _identical_series(per_series: Mapping[str, Mapping[str, dict[str, Any]]]) -> list[list[str]]:
    """Pairs of source series whose shared observations at one date are all
    equal (and share at least ``MIN_PAIRS`` assets) — duplicate rows a reader
    should not count twice."""
    ids = sorted(per_series)
    out: list[list[str]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            shared = set(per_series[a]) & set(per_series[b])
            if len(shared) < MIN_PAIRS:
                continue
            if all(per_series[a][k]["value"] == per_series[b][k]["value"] for k in shared):
                out.append([a, b])
    return out


def measure_fold(
    fold: bt.Fold,
    *,
    reader: _LedgerReader,
    specs: Sequence[SeriesSpec],
) -> tuple[dict[str, Any], dict[tuple[str, str], tuple[bt.FoldResult, dict[str, Any]]]]:
    """One origin's cross-sections: fold metadata plus, per (series, group),
    the CE ``FoldResult`` and the increment over persistence."""
    origin, horizon = fold.origin.isoformat(), fold.horizon.isoformat()
    instruments = fold_instruments(origin, horizon, reader.classes_on)

    prices_d: dict[str, float] = {}
    prices_h: dict[str, float] = {}
    group_of: dict[str, str] = {}
    instrument_of: dict[str, str] = {}
    start: dict[str, dict[str, Any]] = {}
    end: dict[str, dict[str, Any]] = {}
    excluded = Counter()
    for inst in sorted({v for v in instruments.values() if v}):
        classes = {c for c, v in instruments.items() if v == inst}
        at_d = reader.exact(origin, store.LANE_SOURCE, inst)
        at_h = reader.exact(horizon, store.LANE_SOURCE, inst)
        for key, row in at_d.items():
            if row["assetClass"] not in classes:
                continue
            group = asset_group(row["assetClass"], row["position"])
            if group is None:
                excluded["no_position_group"] += 1
                continue
            cohort_pos = _COHORT_POSITION.get(group, group)
            group_of[key] = group
            instrument_of[key] = inst
            prices_d[key] = row["value"]
            start[key] = {
                "price": row["value"],
                "assetClass": row["assetClass"],
                "position": cohort_pos,
            }
            if key in at_h:
                prices_h[key] = at_h[key]["value"]
                end[key] = {
                    "price": at_h[key]["value"],
                    "assetClass": row["assetClass"],
                    "position": cohort_pos,
                }

    returns = oc.forward_returns(start, end)
    excess = {k: e["excessReturn"] for k, e in returns.items() if e["excessReturn"] is not None}

    def in_group(key: str, group: str) -> bool:
        return group == GROUP_ALL or group_of[key] == group

    meta: dict[str, Any] = {
        "origin": origin,
        "horizon": horizon,
        "heldDays": fold.horizon_days,
        "instruments": instruments,
        "marketUniverse": len(prices_d),
        "byGroup": {g: sum(1 for k in prices_d if in_group(k, g)) for g in GROUPS},
        "excluded": dict(excluded),
        "attrition": oc.attrition(sorted(prices_d), returns),
        "persistence": {
            g: persistence([k for k in prices_d if in_group(k, g)], prices_d, prices_h)
            for g in GROUPS
        },
    }

    results: dict[tuple[str, str], tuple[bt.FoldResult, dict[str, Any]]] = {}
    source_values: dict[str, dict[str, dict[str, Any]]] = {}
    for spec in specs:
        values = reader.exact(origin, spec.lane, spec.source_key)
        if spec.lane == store.LANE_SOURCE:
            source_values[spec.series_id] = values
        if spec.series_id == BOARD_SERIES:
            meta["boardObservationsAtOrigin"] = len(values)
        gaps: dict[str, float] = {}
        target_skips = Counter()
        for key, row in values.items():
            if key not in prices_d:
                continue
            if spec.lane == store.LANE_SOURCE and spec.source_key == instrument_of[key]:
                target_skips[group_of[key]] += 1
                continue
            gaps[key] = log_gap(row["value"], prices_d[key])
        for group in GROUPS:
            members = [k for k in prices_d if in_group(k, group)]
            signal = {k: gaps[k] for k in members if k in gaps}
            outcome = {k: excess[k] for k in members if k in excess}
            skipped = sum(n for g, n in target_skips.items() if group in (GROUP_ALL, g))
            if not values:
                result = bt.FoldResult(
                    fold=fold, n_pairs=0, usable=False, reason=REASON_NO_OBSERVATION
                )
                inc: dict[str, Any] = {}
            elif not signal and skipped:
                result = bt.FoldResult(fold=fold, n_pairs=0, usable=False, reason=REASON_IS_TARGET)
                inc = {}
            else:
                result = bt.evaluate_fold(
                    fold,
                    signal,
                    outcome,
                    benchmarks={"marketValue": {k: prices_d[k] for k in members}},
                )
                inc = {}
                if result.usable:
                    paired = sorted(set(signal) & set(outcome))
                    inc = increment_over_persistence(paired, gaps, prices_d, prices_h)
            results[(spec.series_id, group)] = (result, inc)
    meta["identicalSourceSeriesAtOrigin"] = _identical_series(source_values)
    return meta, results


def _summary(entries: Sequence[tuple[bt.FoldResult, dict[str, Any]]]) -> dict[str, Any]:
    """CE ``summarise`` plus per-origin unusable reasons, the increment over
    persistence, and the two-origin verdict floor."""
    fold_results = [r for r, _ in entries]
    out = bt.summarise(fold_results)
    inc_by_origin = {r.fold.origin.isoformat(): inc for r, inc in entries if r.usable}
    for item in out["spearmanByFold"]:
        inc = inc_by_origin.get(item["origin"]) or {}
        item["partialR"] = inc.get("partialR")
        item["deltaR2"] = inc.get("deltaR2")
    out["originsUnusable"] = [
        {"origin": r.fold.origin.isoformat(), "n": r.n_pairs, "reason": r.reason}
        for r in fold_results
        if not r.usable
    ]
    del out["unusableReasons"]
    partials = [i["partialR"] for i in out["spearmanByFold"] if i["partialR"] is not None]
    deltas = [i["deltaR2"] for i in out["spearmanByFold"] if i["deltaR2"] is not None]
    out["meanPartialR"] = statistics.fmean(partials) if partials else None
    out["meanDeltaR2"] = statistics.fmean(deltas) if deltas else None
    if out["foldsUsable"] < MIN_USABLE_ORIGINS_FOR_VERDICT:
        out["verdict"] = (
            f"no verdict: {out['foldsUsable']} usable origin(s), fewer than "
            f"{MIN_USABLE_ORIGINS_FOR_VERDICT}"
        )
    return out


def _source_meta(source_key: str) -> dict[str, Any]:
    provider = provider_of(source_key)
    ktc_provider = provider_of(MARKET_KTC)
    return {
        "provider": provider,
        "sameProviderAsOffenseTarget": bool(provider and provider == ktc_provider),
        "isIdpTarget": source_key == MARKET_IDP,
    }


def measure(
    ledger: Path,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """The scoreboard over one ledger.  Reads only; never writes."""
    reader = _LedgerReader(ledger)
    market_dates = {
        k: set(asof.observed_dates(lane=store.LANE_SOURCE, source_key=k, path=ledger))
        for k in _MARKET_KEYS
    }
    all_dates = sorted(set().union(*market_dates.values()))
    available = [date.fromisoformat(d) for d in all_dates]
    board_dates = asof.observed_dates(lane=store.LANE_CANONICAL, source_key="", path=ledger)
    coverage = asof.source_lane_coverage(ledger)
    sources = sorted(k for k in coverage.get("sources", {}) if k not in EXCLUDED_SOURCES)
    specs = [SeriesSpec(BOARD_SERIES, store.LANE_CANONICAL, "")] + [
        SeriesSpec(k, store.LANE_SOURCE, k) for k in sources
    ]

    out_horizons: dict[str, Any] = {}
    for horizon_days in horizons:
        fold_list = bt.folds(available, horizon_days)
        fold_meta: list[dict[str, Any]] = []
        collected: dict[tuple[str, str], list[tuple[bt.FoldResult, dict[str, Any]]]] = {}
        for fold in fold_list:
            meta, results = measure_fold(fold, reader=reader, specs=specs)
            fold_meta.append(meta)
            for key, entry in results.items():
                collected.setdefault(key, []).append(entry)

        def block(series_id: str) -> dict[str, Any]:
            return {g: _summary(collected.get((series_id, g), [])) for g in GROUPS}

        board_measured = any(m.get("boardObservationsAtOrigin") for m in fold_meta)
        board: dict[str, Any] = {"status": "measured" if board_measured else "unavailable"}
        if board_measured:
            board["byGroup"] = block(BOARD_SERIES)
        else:
            board["reason"] = (
                "the ledger holds no canonical_board observation on any fold origin. "
                "The committed archive carries the raw scraper payload, not the served "
                "board (no rankDerivedValue; audit W04-F009), so archive mode cannot "
                "measure the board. Run --ledger against a ledger that recorded the "
                "served board (origins live:server / migration:*)."
            )
        out_horizons[str(horizon_days)] = {
            "horizonDays": horizon_days,
            "foldsAttempted": len(fold_list),
            "foldsNote": (
                None
                if fold_list
                else f"the panel ({all_dates[0] if all_dates else None} to "
                f"{all_dates[-1] if all_dates else None}) is shorter than {horizon_days} days"
            ),
            "folds": fold_meta,
            "board": board,
            "sources": {k: {**_source_meta(k), "byGroup": block(k)} for k in sources},
        }

    return {
        "schema": SCHEMA,
        "panel": {
            "dates": len(all_dates),
            "start": all_dates[0] if all_dates else None,
            "end": all_dates[-1] if all_dates else None,
            "marketDates": {k: len(v) for k, v in market_dates.items()},
            "boardDates": len(board_dates),
            "sourceLane": coverage.get("sources", {}),
        },
        "target": TARGET_DEFINITION,
        "outcome": (
            "cohort-excess forward market return over the fold "
            "(src.consensus_edge.outcomes.forward_returns): raw return minus the median "
            "return of the asset's position-family x value-tier cohort, cohort fixed at "
            "the origin price"
        ),
        "signal": (
            "log((x + 1) / (market + 1)) at the origin (CE mispricing.log_gap); x is the "
            "board or source value. Spearman is rank-based, so (x - market) / market gives "
            "the identical rho"
        ),
        "minPairsPerCrossSection": MIN_PAIRS,
        "minUsableOriginsForVerdict": MIN_USABLE_ORIGINS_FOR_VERDICT,
        "groups": list(GROUPS),
        "excludedSources": EXCLUDED_SOURCES,
        "horizons": out_horizons,
        "realizedPoints": REALIZED_POINTS,
        "independentValidationCandidate": INDEPENDENT_VALIDATION_ASSESSMENT,
        "caveats": list(CAVEATS),
    }


# ── Markdown summary ────────────────────────────────────────────────────


def _fmt(value: Any, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:+.3f}" if signed else f"{value:.3f}"
    return str(value)


def render_markdown(result: Mapping[str, Any], *, title: str) -> str:
    """A concise human summary of one measurement JSON."""
    lines = [f"# {title}", ""]
    inputs = result.get("inputs") or {}
    panel = result.get("panel") or {}
    lines.append(
        f"Research measurement, schema `{result.get('schema')}`. Changes nothing served. "
        f"Mode `{inputs.get('mode')}`; panel {panel.get('start')} to {panel.get('end')} "
        f"({panel.get('dates')} dates); code `{result.get('codeSha')}`."
    )
    archive = (inputs.get("ledgerBuild") or {}).get("archive") or {}
    if archive:
        lines.append(
            f"Archive: {archive.get('zipCount')} bundles, sha256 `{archive.get('sha256')}`."
        )
    lines += [
        "",
        "Signal: the gap `log((x+1)/(market+1))` at origin D. Outcome: the cohort-excess "
        "market return D→D+H. Cell: mean per-origin Spearman, then usable origins with a "
        "positive rho over usable origins. Each origin is its own cross-section, with at "
        f"least {result.get('minPairsPerCrossSection')} pairs. No origins are pooled.",
        "",
    ]
    for h_key, block in (result.get("horizons") or {}).items():
        lines.append(f"## Horizon {h_key} days")
        lines.append("")
        folds = block.get("folds") or []
        if not folds:
            lines += [f"No folds: {block.get('foldsNote')}.", ""]
            continue
        lines.append(
            "| origin → horizon | offense market | pick market | IDP market | universe "
            "| R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for f in folds:
            inst = f.get("instruments") or {}
            per = f.get("persistence") or {}
            per_all = per.get(GROUP_ALL) or {}
            per_idp = per.get("IDP") or {}
            lines.append(
                f"| {f['origin']} → {f['horizon']} | {inst.get('offense') or '—'} | "
                f"{inst.get('pick') or '—'} | {inst.get('idp') or '—'} | "
                f"{f.get('marketUniverse')} | "
                f"{_fmt(per_all.get('r2LogLevel'), signed=False)} | "
                f"{_fmt(per_all.get('medianAbsLogReturn'), signed=False)} / "
                f"{_fmt(per_idp.get('medianAbsLogReturn'), signed=False)} | "
                f"{_fmt(per_idp.get('unchangedShare'), signed=False)} |"
            )
        lines.append("")
        board = block.get("board") or {}
        series_rows: list[tuple[str, Mapping[str, Any]]] = []
        if board.get("status") == "measured":
            series_rows.append((BOARD_SERIES, board.get("byGroup") or {}))
        else:
            lines += [f"**Board: unavailable.** {board.get('reason')}", ""]
        for key, src in (block.get("sources") or {}).items():
            label = f"{key} ({src.get('provider') or 'provider unknown'})"
            series_rows.append((label, src.get("byGroup") or {}))
        if series_rows:
            lines.append("| series | " + " | ".join(GROUPS) + " |")
            lines.append("|---|" + "---|" * len(GROUPS))
            for name, by_group in series_rows:
                cells = []
                for g in GROUPS:
                    s = by_group.get(g) or {}
                    usable = s.get("foldsUsable") or 0
                    if not usable:
                        cells.append("—")
                        continue
                    cells.append(
                        f"{_fmt(s.get('meanSpearman'))} ({s.get('foldsPositive', 0)}/{usable})"
                    )
                lines.append(f"| {name} | " + " | ".join(cells) + " |")
            lines += [
                "",
                "— means no usable origin: no observation, the series is the market itself, "
                "or too few pairs. The JSON gives the reason for each origin.",
                "",
            ]
            verdicts = [
                f"- `{name}` ALL: {(by_group.get(GROUP_ALL) or {}).get('verdict')}"
                for name, by_group in series_rows
            ]
            lines += verdicts + [""]
    rp = result.get("realizedPoints") or {}
    lines += [
        "## Realized points",
        "",
        f"{rp.get('state')}: {rp.get('reason')}",
        "",
        "## Independent validation (Hill registry)",
        "",
        "Not registered; could not qualify as is:",
        "",
    ]
    for reason in (result.get("independentValidationCandidate") or {}).get("reasons", []):
        lines.append(f"- {reason}")
    lines += ["", "## Caveats", ""]
    for caveat in result.get("caveats") or []:
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)
