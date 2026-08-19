"""Projection ingestion, snapshots, and robust consensus.

This is the swappable layer (BDVM module 1).

The Phase-0 audit's finding that the ROS pipeline's ``projection`` column
is empty still holds — re-measured 2026-08-19 at **0 of 2,168 rows**
across all five cached ROS boards.  But "the platform has **zero**
forward-looking statistical projection sources", which this docstring
used to say, is **not** the same statement and is no longer true.

``CSVs/site_raw/draftSharksSf.csv`` and ``draftSharksIdp.csv`` publish
``1yr. Proj`` — 412 of 439 offensive rows and 375 of 410 IDP rows
populated, with the season-total shape you would expect (QB max 403,
RB1 309, WR1 257, TE1 214).  It is fetched, committed, and consumed by
nothing.

Two properties stop it being a drop-in, and both are the source's shape
rather than a wiring gap:

* it publishes **totals, not stat lines**, so there is nothing to score
  under this league's card; and
* it publishes **no scoring metadata**, so the basis those totals are
  denominated in cannot be verified — and an unverified basis fails
  closed here exactly as an unverified game type does in the dynasty
  lane.

Ingesting it therefore means ``fpts`` with ``scoring_native=False``,
which ``blend_consensus`` now excludes from a mixed-basis mean rather
than averaging across scoring systems.  Using its numbers as league
points would need either a stat line or a validated conversion, and
neither exists.

So v1 still ships:

* a snapshot store with mandatory ``as_of`` stamps (never overwritten);
* a manual-CSV adapter — the moment a real projection feed lands it
  drops CSVs here and the whole engine lights up;
* the documented proxy from BDVM §8.3 — a *reconstructed baseline* from
  realized per-game scoring history (shrunk recency-weighted PPG),
  flagged ``is_proxy`` so downstream confidence reflects it.

Missing-data rule (master prompt §6.3): a player with no projection is
**unpriced** — never a silent zero, never an invented number.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.bdvm.params import ParamSet
from src.bdvm.scoring import score_stat_line_per_game, season_line_to_per_game
from src.nfl_data.first_down_rate import with_imputed_first_downs

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = REPO_ROOT / "data" / "bdvm" / "projections"
MANUAL_CSV_DIR = SNAPSHOT_DIR / "manual"

_STAT_BASES = ("season", "per_game")


class ProjectionError(ValueError):
    """Raised on malformed projection inputs."""


@dataclass(frozen=True)
class ProjectionRecord:
    """One source's projection for one player-season."""

    source: str
    player_key: str  # normalized canonical name (join key)
    position: str
    season: int
    as_of: str  # ISO date the source published/was captured
    games: float
    stat_line: Mapping[str, float] | None = None
    stat_basis: str = "season"  # "season" | "per_game"
    fpg: float | None = None  # direct per-game points fallback
    fpts: float | None = None  # direct season points fallback
    scoring_native: bool = False  # True when fpg/fpts already use league scoring
    is_proxy: bool = False  # True for reconstructed-baseline rows
    proj_high: float | None = None
    proj_low: float | None = None

    def __post_init__(self) -> None:
        if self.stat_basis not in _STAT_BASES:
            raise ProjectionError(f"bad stat_basis {self.stat_basis!r}")
        if self.games <= 0:
            raise ProjectionError(f"games must be positive for {self.player_key!r}")
        if self.stat_line is None and self.fpg is None and self.fpts is None:
            raise ProjectionError(
                f"projection for {self.player_key!r} from {self.source!r} has "
                "neither a stat line nor fantasy points"
            )

    @property
    def first_downs_imputed(self) -> bool:
        """Were this projection's first downs estimated rather than supplied?

        Inspectable rather than inferable: a points figure that silently
        might or might not include an estimate is the ambiguity the
        imputation exists to remove, so the fact travels with the record.
        """
        if self.stat_line is None:
            return False
        _, imputed = with_imputed_first_downs(self.stat_line, self.position)
        return imputed

    def resolve_fpg(self, scoring_settings: Mapping[str, Any]) -> tuple[float, bool]:
        """(fpg under league scoring, scoring_native flag for this value)."""
        if self.stat_line is not None:
            per_game = (
                dict(self.stat_line)
                if self.stat_basis == "per_game"
                else season_line_to_per_game(self.stat_line, self.games)
            )
            return (
                score_stat_line_per_game(
                    per_game,
                    scoring_settings,
                    position=self.position,
                    # THE projection boundary.  No projection source
                    # publishes first downs, and the realized path reads
                    # them from columns, so scoring a projected line
                    # as-is drops 22-30% of a player's points — unevenly
                    # by position, and only for players a real source
                    # covers, since proxy rows are scored from realized
                    # stats that DO have the columns.  Imputed from the
                    # measured one-per-twenty-yards fit; a no-op if the
                    # source supplied them or the league does not pay
                    # the bonus.  See src/nfl_data/first_down_rate.py.
                    impute_first_downs=True,
                ),
                True,
            )
        if self.fpg is not None:
            return float(self.fpg), self.scoring_native
        assert self.fpts is not None  # guaranteed by __post_init__
        return float(self.fpts) / self.games, self.scoring_native


@dataclass(frozen=True)
class ConsensusProjection:
    player_key: str
    position: str
    mu_fpg: float
    sigma_source: float
    games: float
    n_sources: int
    sources: tuple[str, ...]
    any_proxy: bool
    all_scoring_native: bool
    stale_sources: tuple[str, ...] = ()
    # Sources down-weighted because their stat line's league-scored IDP
    # categories are a strict subset of a peer's (vocabulary-dominated).
    vocabulary_limited: tuple[str, ...] = ()
    # Sources EXCLUDED from the mean because their points are denominated
    # in a scoring basis this league cannot verify.  Excluded rather than
    # down-weighted: a weight says "less reliable", and this is
    # "different unit".  See ``blend_consensus``.
    excluded_foreign_basis: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Consensus blend
# ---------------------------------------------------------------------------


def _idp_scoring_vocabulary(
    scoring_settings: Mapping[str, Any],
) -> tuple[frozenset[str], dict[str, str]]:
    """(league-scored IDP category ids, stat-column → category map).

    Derived from the production scoring vocabulary in
    ``realized_points`` (its private maps are the single source of
    truth for which stat columns feed which Sleeper keys — ADR-005;
    duplicating the list here is exactly the drift this module must
    not create).  Categories collapse column-name variants
    (``def_pass_defended`` / ``def_passes_defended``) so two sources
    spelling the same category differently compare as equals.
    """
    from src.nfl_data.realized_points import (  # noqa: PLC0415
        _IDP_KEYS,
        _IDP_TACKLE_KEYS,
        _SCORING_KEY_ALIASES,
    )

    effective = dict(scoring_settings)
    for alias, canonical in _SCORING_KEY_ALIASES.items():
        if alias in effective and canonical not in effective:
            effective[canonical] = effective[alias]

    def _nonzero(key: str) -> bool:
        try:
            return abs(float(effective.get(key) or 0.0)) > 0.0
        except (TypeError, ValueError):
            return False

    col_to_cat: dict[str, str] = {}
    scored: set[str] = set()
    for sleeper_key, (candidates, _label) in _IDP_KEYS.items():
        for col in candidates:
            col_to_cat[col] = sleeper_key
        if _nonzero(sleeper_key):
            scored.add(sleeper_key)
    # All tackle columns resolve through one view — one category.
    for col in ("def_tackles_solo", "def_tackle_assists", "def_tackles"):
        col_to_cat[col] = "idp_tkl"
    if any(_nonzero(key) for key, _label in _IDP_TACKLE_KEYS):
        scored.add("idp_tkl")
    return frozenset(scored), col_to_cat


def _staleness_weight(
    record_as_of: str, snapshot_as_of: str, params: ParamSet
) -> tuple[float, bool]:
    cfg = params["projection_consensus"]
    try:
        d_rec = date.fromisoformat(str(record_as_of)[:10])
        d_snap = date.fromisoformat(str(snapshot_as_of)[:10])
    except ValueError:
        return 1.0, False
    age_days = (d_snap - d_rec).days
    if age_days > int(cfg["stale_after_days"]):
        return float(cfg["stale_weight_mult"]), True
    return 1.0, False


def _cap_weights(weights: list[float], cap_frac: float) -> list[float]:
    """Iteratively cap any single weight share at ``cap_frac``.

    The cap is only *feasible* when ``n · cap_frac >= 1`` (with two
    sources nobody can be held under 35%); below that it is skipped —
    forcing it would equalize the weights and silently erase staleness
    penalties.
    """
    if not weights:
        return weights
    w = [max(0.0, x) for x in weights]
    if len(w) * cap_frac < 1.0:
        return w
    for _ in range(200):
        total = sum(w)
        if total <= 0:
            return [1.0 for _ in w]
        over = [i for i, x in enumerate(w) if x / total > cap_frac + 1e-9]
        if not over:
            return w
        for i in over:
            w[i] = cap_frac * total
    return w


def blend_consensus(
    records: Iterable[ProjectionRecord],
    *,
    scoring_settings: Mapping[str, Any],
    snapshot_as_of: str,
    params: ParamSet,
) -> ConsensusProjection | None:
    """Robust weighted consensus for ONE player's records.

    v1 uses equal base weights (no honest source-accuracy history exists
    yet — master prompt §4.1), a weighted trimmed mean at >=
    ``trim_min_sources`` sources, a 35% single-source cap, and a
    staleness penalty.  Returns None when there are no records (the
    caller records the player as unpriced).
    """
    recs = list(records)
    if not recs:
        return None
    cfg = params["projection_consensus"]

    scored: list[tuple[ProjectionRecord, float, float, bool]] = []
    stale: list[str] = []
    for r in recs:
        fpg, native = r.resolve_fpg(scoring_settings)
        w, is_stale = _staleness_weight(r.as_of, snapshot_as_of, params)
        if is_stale:
            stale.append(r.source)
        scored.append((r, fpg, w, native))

    # ONE CONSENSUS, ONE SCORING BASIS.
    #
    # ``resolve_fpg`` returns ``native=False`` when the value is a points
    # total the source published under ITS OWN scoring rather than a stat
    # line this league can score.  Averaging those with league-scored
    # points is a category error, not an imprecision: the two are not the
    # same quantity, so their mean is not a quantity at all.
    #
    # ``all_scoring_native`` recorded this and nothing read it — written
    # in one place, consumed in none — so a foreign-denominated
    # projection landed in ``mu_fpg`` beside a league-scored one with no
    # consumer able to tell.  The manual-CSV adapter, which the module
    # docstring names as the drop-in for a real feed, sets
    # ``scoring_native=False`` unconditionally, so the path was the
    # documented one rather than an edge case.
    #
    # EXCLUDED, not down-weighted, and named in the result: a weight
    # expresses lower confidence in the same quantity.
    #
    # When EVERY record is non-native there is nothing native to protect
    # and nothing to verify against.  Excluding them all would report the
    # player as UNPRICED, which is a different and false claim — a
    # projection does exist.  So they blend and the consensus carries
    # ``all_scoring_native=False`` for the caller to act on.
    excluded_foreign: list[str] = []
    if any(native for (_, _, _, native) in scored) and not all(
        native for (_, _, _, native) in scored
    ):
        kept: list[tuple[ProjectionRecord, float, float, bool]] = []
        for entry in scored:
            if entry[3]:
                kept.append(entry)
            else:
                excluded_foreign.append(entry[0].source)
        scored = kept

    # Vocabulary-aware down-weighting.  A stat-line record whose
    # league-scored IDP categories are a STRICT SUBSET of a peer's is
    # known-incomplete under THIS league's scoring — e.g. a source
    # publishing no TFL/PD in a league that pays 4.25/5.32 for them is
    # biased low by construction, not lower on the player.  A plain
    # mean would drag every dual-covered defender down by the missing
    # categories' value.  Down-weighting via a labelled prior keeps
    # the corroboration signal without silently imputing the missing
    # categories (§6.3: never invent numbers).  Proxies and
    # direct-points records compare as None: complete-by-construction
    # or unknowable — they neither dominate nor get dominated.
    vocab_limited: list[str] = []
    vocab_mult = float(cfg.get("vocabulary_dominated_weight_mult", 1.0))
    if vocab_mult < 1.0 and len(scored) >= 2:
        scored_cats, col_to_cat = _idp_scoring_vocabulary(scoring_settings)
        vocabs: list[frozenset[str] | None] = []
        for r, _fpg, _w, _native in scored:
            if r.is_proxy or not r.stat_line:
                vocabs.append(None)
            else:
                cats = frozenset(
                    col_to_cat[c] for c in r.stat_line if col_to_cat.get(c) in scored_cats
                )
                vocabs.append(cats or None)
        for i, vocab_i in enumerate(vocabs):
            if vocab_i is None:
                continue
            dominated = any(
                vocab_j is not None and vocab_i < vocab_j
                for j, vocab_j in enumerate(vocabs)
                if j != i
            )
            if dominated:
                r, fpg, w, native = scored[i]
                scored[i] = (r, fpg, w * vocab_mult, native)
                vocab_limited.append(r.source)

    # Trim extremes when enough sources exist.
    if len(scored) >= int(cfg["trim_min_sources"]) and float(cfg["trim_frac"]) > 0:
        scored.sort(key=lambda t: t[1])
        k = max(1, int(len(scored) * float(cfg["trim_frac"])))
        if len(scored) - 2 * k >= 3:
            scored = scored[k:-k]

    weights = _cap_weights([w for (_, _, w, _) in scored], float(cfg["max_single_source_weight"]))
    total_w = sum(weights)
    if total_w <= 0:
        return None
    mu = sum(w * fpg for w, (_, fpg, _, _) in zip(weights, scored)) / total_w
    games = sum(w * r.games for w, (r, _, _, _) in zip(weights, scored)) / total_w
    var = sum(w * (fpg - mu) ** 2 for w, (_, fpg, _, _) in zip(weights, scored)) / total_w

    first = recs[0]
    return ConsensusProjection(
        player_key=first.player_key,
        position=first.position,
        mu_fpg=mu,
        sigma_source=math.sqrt(max(0.0, var)),
        games=games,
        n_sources=len(scored),
        sources=tuple(r.source for (r, _, _, _) in scored),
        any_proxy=any(r.is_proxy for (r, _, _, _) in scored),
        all_scoring_native=all(native for (_, _, _, native) in scored),
        excluded_foreign_basis=tuple(excluded_foreign),
        stale_sources=tuple(stale),
        vocabulary_limited=tuple(vocab_limited),
    )


# ---------------------------------------------------------------------------
# Snapshot store (as-of stamped, append-only)
# ---------------------------------------------------------------------------


def write_snapshot(
    records: Iterable[ProjectionRecord],
    *,
    season: int,
    as_of: str,
    label: str = "",
    base_dir: Path | None = None,
) -> Path:
    """Persist a projection snapshot.  Never overwrites an existing one."""
    root = (base_dir or SNAPSHOT_DIR) / str(season)
    root.mkdir(parents=True, exist_ok=True)
    stamp = str(as_of)[:10]
    suffix = f"_{label}" if label else ""
    path = root / f"projections_{stamp}{suffix}.json"
    if path.exists():
        raise ProjectionError(f"snapshot already exists (immutable): {path}")
    payload = {
        "asOf": as_of,
        "season": season,
        "recordCount": 0,
        "records": [],
    }
    for r in records:
        payload["records"].append(
            {
                "source": r.source,
                "playerKey": r.player_key,
                "position": r.position,
                "season": r.season,
                "asOf": r.as_of,
                "games": r.games,
                "statLine": dict(r.stat_line) if r.stat_line is not None else None,
                "statBasis": r.stat_basis,
                "fpg": r.fpg,
                "fpts": r.fpts,
                "scoringNative": r.scoring_native,
                "isProxy": r.is_proxy,
                "projHigh": r.proj_high,
                "projLow": r.proj_low,
            }
        )
    payload["recordCount"] = len(payload["records"])
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def load_snapshot(path: Path) -> tuple[str, list[ProjectionRecord]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = [
        ProjectionRecord(
            source=row["source"],
            player_key=row["playerKey"],
            position=row["position"],
            season=int(row["season"]),
            as_of=row["asOf"],
            games=float(row["games"]),
            stat_line=row.get("statLine"),
            stat_basis=row.get("statBasis", "season"),
            fpg=row.get("fpg"),
            fpts=row.get("fpts"),
            scoring_native=bool(row.get("scoringNative", False)),
            is_proxy=bool(row.get("isProxy", False)),
            proj_high=row.get("projHigh"),
            proj_low=row.get("projLow"),
        )
        for row in data.get("records", [])
    ]
    return str(data.get("asOf", "")), records


def latest_snapshot_path(season: int, base_dir: Path | None = None) -> Path | None:
    root = (base_dir or SNAPSHOT_DIR) / str(season)
    if not root.exists():
        return None
    candidates = sorted(root.glob("projections_*.json"))
    return candidates[-1] if candidates else None


def supersede_merge_into_snapshot(
    new_records: list[ProjectionRecord],
    *,
    source_name: str,
    season: int,
    as_of: str,
    label: str,
    base_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Merge one real source's records over the latest snapshot and
    write a new immutable snapshot.

    The shared merge policy every real (non-proxy) source uses:

    * this source's own prior records are replaced wholesale (a rerun
      is authoritative for its source);
    * reconstructed-baseline proxies are dropped for players the new
      records cover (the proxy is a stand-in for absent data, BDVM
      §8.3);
    * every other source's records — real records from other feeds,
      proxies for uncovered players — carry through untouched, so two
      real sources coexist and feed the consensus as peers.
    """
    if not new_records:
        raise ProjectionError("refusing to write a snapshot from zero records")
    existing: list[ProjectionRecord] = []
    prior = latest_snapshot_path(season, base_dir=base_dir)
    if prior is not None:
        _as_of, existing = load_snapshot(prior)
    covered = {r.player_key for r in new_records}
    kept = [
        r
        for r in existing
        if r.source != source_name  # replaced wholesale
        and not (r.is_proxy and r.player_key in covered)  # proxy superseded
    ]
    merged = kept + new_records
    path = write_snapshot(merged, season=season, as_of=as_of, label=label, base_dir=base_dir)
    summary = {
        "priorSnapshot": str(prior) if prior else None,
        "priorRecords": len(existing),
        "newRealRecords": len(new_records),
        "proxiesSuperseded": sum(1 for r in existing if r.is_proxy and r.player_key in covered),
        "mergedRecords": len(merged),
        "snapshot": str(path),
    }
    return path, summary


# ---------------------------------------------------------------------------
# Adapter: manual CSV drop
# ---------------------------------------------------------------------------

_CSV_META_COLS = {
    "name",
    "player",
    "position",
    "pos",
    "games",
    "fpts",
    "fpg",
    "proj_high",
    "proj_low",
    "as_of",
}


def load_manual_csv(
    path: Path,
    *,
    source: str,
    season: int,
    default_as_of: str,
    name_normalizer=None,
) -> list[ProjectionRecord]:
    """Read one source's projections from a CSV drop.

    Expected columns: ``name``, ``position``, ``games``, then EITHER raw
    nflverse-vocabulary stat columns (``passing_yards``, ``receptions``,
    ``def_tackles_solo``, …) as season totals, OR ``fpts``/``fpg``.
    Optional ``as_of`` per row; otherwise ``default_as_of``.
    """
    if name_normalizer is None:
        from src.utils.name_clean import normalize_player_name as name_normalizer  # noqa: PLC0415

    records: list[ProjectionRecord] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ProjectionError(f"empty projection CSV: {path}")
        for i, row in enumerate(reader, start=2):
            name = (row.get("name") or row.get("player") or "").strip()
            if not name:
                continue
            position = (row.get("position") or row.get("pos") or "").strip().upper()
            if not position:
                raise ProjectionError(f"{path}:{i}: missing position for {name!r}")
            try:
                games = float(row.get("games") or 0)
            except ValueError as exc:
                raise ProjectionError(f"{path}:{i}: bad games value") from exc
            stat_line: dict[str, float] = {}
            for col, val in row.items():
                if col is None or col.lower() in _CSV_META_COLS or val in (None, ""):
                    continue
                try:
                    stat_line[col] = float(val)
                except ValueError:
                    continue
            fpts = _opt_float(row.get("fpts"))
            fpg = _opt_float(row.get("fpg"))
            records.append(
                ProjectionRecord(
                    source=source,
                    player_key=name_normalizer(name),
                    position=position,
                    season=season,
                    as_of=(row.get("as_of") or default_as_of),
                    games=games if games > 0 else 17.0,
                    stat_line=stat_line or None,
                    stat_basis="season",
                    fpg=fpg,
                    fpts=fpts,
                    scoring_native=False,
                    proj_high=_opt_float(row.get("proj_high")),
                    proj_low=_opt_float(row.get("proj_low")),
                )
            )
    return records


def _opt_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Adapter: reconstructed baseline (BDVM §8.3 documented proxy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealizedSeason:
    season: int
    ppg: float  # realized per-game points UNDER THIS LEAGUE'S SCORING
    games: float


# Recent-first season weights for the 3-year blend.
_BASELINE_SEASON_WEIGHTS = (0.5, 0.3, 0.2)
_BASELINE_SHRINK_BASE = 0.35  # §8.3 prior
_BASELINE_SHRINK_CAP = 0.90
_BASELINE_REF_GAMES = 16.0


def build_reconstructed_baseline(
    history: Mapping[str, tuple[str, list[RealizedSeason]]],
    *,
    season: int,
    as_of: str,
    positional_means: Mapping[str, float],
    source: str = "reconstructedBaseline",
) -> list[ProjectionRecord]:
    """Build proxy projections from realized scoring history.

    ``history`` maps player_key -> (position, [RealizedSeason...]).
    mu0 = (1 - s) * weighted_ppg + s * positional_mean, where the
    shrink ``s`` grows as the sample shrinks:
    s = min(0.90, 0.35 * 16 / avg_games_per_season).

    This is EXPLICITLY a worse projection than a real preseason
    consensus (acceptable bias direction: it understates model
    accuracy).  Every record is flagged ``is_proxy=True`` and downstream
    confidence must reflect it.
    """
    out: list[ProjectionRecord] = []
    for player_key, (position, seasons) in history.items():
        usable = sorted(
            (s for s in seasons if s.season < season and s.games > 0),
            key=lambda s: s.season,
            reverse=True,
        )[:3]
        if not usable:
            continue
        weights = _BASELINE_SEASON_WEIGHTS[: len(usable)]
        wsum = sum(weights)
        wppg = sum(w * s.ppg for w, s in zip(weights, usable)) / wsum
        avg_games = sum(s.games for s in usable) / len(usable)
        shrink = min(
            _BASELINE_SHRINK_CAP,
            _BASELINE_SHRINK_BASE * (_BASELINE_REF_GAMES / max(1.0, avg_games)),
        )
        pos_mean = float(positional_means.get(position.upper(), 0.0))
        mu = (1.0 - shrink) * wppg + shrink * pos_mean
        games_proj = min(17.0, max(8.0, avg_games))
        out.append(
            ProjectionRecord(
                source=source,
                player_key=player_key,
                position=position,
                season=season,
                as_of=as_of,
                games=games_proj,
                fpg=mu,
                scoring_native=True,
                is_proxy=True,
            )
        )
    return out
