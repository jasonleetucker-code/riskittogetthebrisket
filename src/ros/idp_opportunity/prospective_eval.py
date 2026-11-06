"""Prospective weekly IDP evaluation runner (logic) — SHADOW ONLY.

Preregistration: ``docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md``.

This module lives beside, not inside, ``prospective.py`` on purpose: the freeze receipts
pin the git blobs of ``prospective.py`` and ``model.py``, so adding the evaluation runner
to either would itself be a code deviation from every receipt already committed.

It contains four pure pieces (no I/O, no clock, no network):

* :func:`verify_gate` — may this week be evaluated at all?  (pre-kickoff receipt, finality,
  frozen blob and code blobs)
* :func:`select_prov` — the PROV champion: per player, the latest archive capture strictly
  before that player's own kickoff, re-scored under the card.
* :func:`evaluate_week` — every preregistered metric on exactly the preregistered
  population.  Point-error and decision metrics are separate sections.
* :func:`team_kickoffs` — per-team kickoff instants from the nflverse schedule.

Metrics are NOT re-implemented: MAE / RMSE / bias / coverage / Spearman / top-N hit and the
player-clustered paired bootstrap are :mod:`src.ros.idp_opportunity.evaluate`'s (the
retrospective backtest's own).  Points come only from ``score_stat_line`` (``Card.points``).
A missing projection is an exclusion that is counted, never a 0.
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.ros.idp_opportunity.evaluate import (
    Prediction,
    bootstrap_delta_mae,
    metrics,
    population,
    top_n_hit,
)
from src.ros.idp_opportunity.leakage import SeasonData
from src.ros.idp_opportunity.model import Card
from src.ros.idp_opportunity.positions import FAMILIES, SUBGROUPS, UNKNOWN
from src.ros.idp_opportunity.prospective import PROSPECTIVE_MODELS
from src.ros.lineup import OBJECTIVE_REALIZED_POINTS, RosterPlayer, solve_optimal_assignment

__all__ = [
    "ALL_MODELS",
    "BONFERRONI_FAMILIES",
    "BIAS_MARGIN",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "GateResult",
    "GitFacts",
    "ProvSelection",
    "evaluate_week",
    "holm_adjust",
    "select_prov",
    "team_kickoffs",
    "verify_gate",
]

PROV = "PROV"
ALL_MODELS = (PROV, *PROSPECTIVE_MODELS)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261101
BIAS_MARGIN = 0.5  # |bias| no worse than the reference's + 0.5 points (prereg §6)
ALPHA = 0.05
#: Endpoint families Holm-corrected separately (prereg §6).
BONFERRONI_FAMILIES = ("pointError", "topN", "streaming")
#: The five challengers vs PROV (15 tests over 3 families) and four vs S0 (12 tests).
VS_PROV = PROSPECTIVE_MODELS
VS_S0 = ("SNAP", "OPP", "ROLE", "HYB")
#: Every receipted code blob must equal the receipt's (a plain blob comparison).
_RECEIPT_CODE_PATHS = (
    "src/ros/idp_opportunity/prospective.py",
    "src/ros/idp_opportunity/model.py",
    "scripts/idp_opportunity_prospective.py",
)


def _r(x: Any, nd: int = 6) -> Any:
    if isinstance(x, float):
        return None if math.isnan(x) or math.isinf(x) else round(x, nd)
    if isinstance(x, Mapping):
        return {str(k): _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


# ── kickoffs ─────────────────────────────────────────────────────────────────


def team_kickoffs(path: Path, season: int) -> dict[int, dict[str, datetime]]:
    """``{week: {team: kickoff UTC}}`` for REG games (nflverse ``games.csv``, ET kickoffs).

    Same ET→UTC rule as ``sources.parse_games`` (which keeps only the week's first)."""
    from zoneinfo import ZoneInfo

    from src.ros.idp_opportunity.sources import _team

    et = ZoneInfo("America/New_York")
    out: dict[int, dict[str, datetime]] = defaultdict(dict)
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("season")) != str(season) or row.get("game_type") != "REG":
                continue
            try:
                local = datetime.fromisoformat(
                    f"{row.get('gameday')}T{row.get('gametime') or '00:00'}:00"
                ).replace(tzinfo=et)
            except ValueError:
                continue  # unknown kickoff stays unknown (PROV excludes, counted)
            utc = local.astimezone(timezone.utc)
            for key in ("home_team", "away_team"):
                out[int(row["week"])][_team(row[key])] = utc
    return {w: dict(v) for w, v in out.items()}


# ── gate ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GitFacts:
    """What git (and the working tree) say; gathered by the CLI, judged here.

    ``receipt_commit_iso`` is the committer time of the commit that ADDED the receipt file.
    Git has no push time, so this is a PROXY: a commit made before kickoff but pushed after
    it would pass.  The runner records that limitation in every output."""

    receipt_commit_iso: str | None
    receipt_clean: bool
    frozen_blob_now: str | None
    code_blobs_now: Mapping[str, str | None]
    frozen_params_path_clean: bool = True


@dataclass
class GateResult:
    ok: bool
    refusals: list[str] = field(default_factory=list)
    deviations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "refusals": sorted(self.refusals),
            "deviations": sorted(self.deviations),
            "notes": list(self.notes),
        }


def verify_gate(
    *,
    week: int,
    receipt: Mapping[str, Any] | None,
    frozen: Mapping[str, Any],
    card_fingerprint: str | None,
    first_kickoff: datetime | None,
    week_final: bool,
    finality_reason: str | None,
    git: GitFacts,
    retrospective: bool = False,
    allow_deviation: bool = False,
) -> GateResult:
    """Decide whether ``week`` may be evaluated.

    HARD refusals (never overridable): no committed receipt, receipt commit not strictly
    before the week's first kickoff, week not final, receipt for another week / ``refit``
    not false, a scoring card that is not the frozen card.  DEVIATIONS (refused unless
    ``allow_deviation``, then labelled): the frozen artifact blob or a pinned code blob
    differs from the receipt.  ``retrospective`` (a week before the first evaluation week,
    explicitly NOT prospective) waives only the receipt-timing requirement.
    """
    g = GateResult(ok=False)
    if not week_final:
        g.refusals.append(f"week_not_final:{finality_reason or 'games_incomplete'}")
    if card_fingerprint is None or card_fingerprint != (frozen.get("card") or {}).get(
        "fingerprint"
    ):
        g.refusals.append("scoring_card_differs_from_frozen_card")
    g.notes.append(
        "receipt time is the committer time of the commit that added the receipt file: a "
        "proxy, because git does not record push time"
    )
    if retrospective:
        g.notes.append("retrospective: NOT a prospective evaluation; receipt timing waived")
    else:
        if receipt is None:
            g.refusals.append("no_receipt")
        else:
            if int(receipt.get("week", -1)) != int(week):
                g.refusals.append("receipt_week_mismatch")
            if receipt.get("refit") is not False:
                g.refusals.append("receipt_refit_not_false")
            if not git.receipt_clean or git.receipt_commit_iso is None:
                g.refusals.append("receipt_not_committed")
            elif first_kickoff is None:
                g.refusals.append("first_kickoff_unknown")
            else:
                at = datetime.fromisoformat(git.receipt_commit_iso.replace("Z", "+00:00"))
                if at.tzinfo is None or at >= first_kickoff:
                    g.refusals.append("receipt_commit_not_before_first_kickoff")
    if receipt is not None and not retrospective:
        pinned = (receipt.get("frozenParams") or {}).get("blob")
        if not git.frozen_params_path_clean or git.frozen_blob_now != pinned:
            g.deviations.append("frozen_params_blob_differs_from_receipt")
        code = receipt.get("code") or {}
        for path in _RECEIPT_CODE_PATHS:
            if git.code_blobs_now.get(path) != code.get(path):
                g.deviations.append(f"code_blob_differs_from_receipt:{path}")
    if g.deviations and not allow_deviation:
        g.refusals.append("deviation_without_allow_deviation")
    g.ok = not g.refusals
    return g


# ── PROV champion ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProvSelection:
    points: dict[str, float]  # pid -> league-scored points of the selected pre-kickoff row
    seen: frozenset[str]  # every pid any capture carried
    no_pre_kickoff: frozenset[str]  # seen, kickoff known, but no capture strictly before it
    unknown_kickoff: frozenset[str]
    post_kickoff_ignored: int
    provider_stamp_not_before_kickoff: int
    captures_read: int
    captures_unreadable: int


def select_prov(
    captures: Iterable[tuple[str, Sequence[Any]]],
    *,
    season: int,
    week: int,
    kickoff_by_team: Mapping[str, datetime],
    card_settings: Mapping[str, Any],
    unreadable: int = 0,
) -> ProvSelection:
    """Per player: the latest capture with ``fetchedAt`` STRICTLY before that player's own
    kickoff, its raw stat line re-scored under ``card_settings``.

    Selection is the canonical ``lock_baseline_at_kickoff`` (observation time, never the
    provider's stamp).  That owner keeps ``fetched <= kickoff``; the preregistration says
    ``<``, so each kickoff is passed 1 microsecond early (exactly ``<`` at the archive's
    millisecond resolution).  ``captures`` is ``(fetchedAt ISO, raw rows)``.
    """
    from src.ros.game_day_estimates import _normalize_team
    from src.ros.sleeper_weekly_projections import (
        build_weekly_observations,
        lock_baseline_at_kickoff,
    )

    observations = []
    n = 0
    for fetched_at, rows in captures:
        n += 1
        batch = build_weekly_observations(
            rows,
            season=season,
            week=week,
            observed_at=fetched_at,
            scoring_settings=card_settings,
        )
        observations.extend(batch.observations)
    kickoffs: dict[str, datetime] = {}
    for obs in observations:
        team = _normalize_team(obs.team) if obs.team else None
        ko = kickoff_by_team.get(team) if team else None
        if ko is not None:
            kickoffs[obs.game_id] = ko - timedelta(microseconds=1)
    lock = lock_baseline_at_kickoff(observations, kickoffs)
    points = {pid: float(e.observation.league_scored_points) for pid, e in lock.baselines.items()}
    stamp_bad = 0
    for pid, e in lock.baselines.items():
        ps = e.observation.provider_updated_at
        ko = kickoffs[e.observation.game_id] + timedelta(microseconds=1)
        if ps is None or datetime.fromisoformat(ps.replace("Z", "+00:00")) >= ko:
            stamp_bad += 1
    return ProvSelection(
        points=dict(sorted(points.items())),
        seen=frozenset(o.sleeper_player_id for o in observations),
        no_pre_kickoff=frozenset(lock.no_pre_kickoff_observation),
        unknown_kickoff=frozenset(lock.unknown_kickoff),
        post_kickoff_ignored=lock.post_kickoff_observations_ignored,
        provider_stamp_not_before_kickoff=stamp_bad,
        captures_read=n,
        captures_unreadable=int(unreadable),
    )


# ── multiplicity / inference helpers ─────────────────────────────────────────


def holm_adjust(pvalues: Mapping[Any, float | None]) -> dict[Any, float | None]:
    """Holm–Bonferroni adjusted p-values (monotone, capped at 1).  ``None`` stays ``None``
    and does not count toward the family size."""
    live = sorted(
        ((p, k) for k, p in pvalues.items() if p is not None), key=lambda t: (t[0], str(t[1]))
    )
    m = len(live)
    out: dict[Any, float | None] = {k: None for k in pvalues}
    run = 0.0
    for i, (p, k) in enumerate(live):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def _bootstrap_mean(values: Sequence[float], *, resamples: int, seed: int) -> dict[str, Any]:
    """Cluster bootstrap of a mean of per-cluster values (one value per cluster)."""
    n = len(values)
    if n == 0:
        return {"n": 0}
    point = sum(values) / n
    rng = random.Random(seed)
    draws = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo = draws[int(math.floor(0.025 * resamples))]
    hi = draws[min(resamples - 1, int(math.ceil(0.975 * resamples)) - 1)]
    n_le = sum(1 for d in draws if d <= 0.0)
    n_ge = sum(1 for d in draws if d >= 0.0)
    p = min(1.0, 2.0 * min((n_le + 1) / (resamples + 1), (n_ge + 1) / (resamples + 1)))
    return {
        "n": n,
        "mean": point,
        "ci95": [lo, hi],
        "pTwoSided": p,
        "resamples": resamples,
        "seed": seed,
    }


# ── decisions: roster lineup and streaming ───────────────────────────────────


def _slots(frozen: Mapping[str, Any]) -> list[str]:
    from src.ros.lineup import normalize_slot

    return [
        s
        for s in (normalize_slot(x) for x in (frozen.get("lineupDemand") or {}).get("slots") or [])
        if s in FAMILIES
    ]


def _lineup_ids(
    pids: Iterable[str],
    value: Mapping[str, float | None],
    family: Mapping[str, str],
    slots: list[str],
) -> set[str]:
    pool = [
        RosterPlayer(
            player_id=p,
            canonical_name=p,
            position=family[p],
            ros_value=value.get(p),
            fantasy_positions=(family[p],),
        )
        for p in sorted(set(pids))
        if p in family
    ]
    got = solve_optimal_assignment(pool, slots, objective=OBJECTIVE_REALIZED_POINTS)
    return {pl.player_id for pl in got.values()}


def _realized_sum(ids: Iterable[str], realized: Mapping[str, float]) -> float:
    return sum(realized.get(p, 0.0) for p in ids)


def decision_inputs_valid(inp: Any) -> bool:
    return isinstance(inp, Mapping) and isinstance(inp.get("teams"), Mapping) and bool(inp["teams"])


def roster_lineup_metric(
    inputs: Mapping[str, Any],
    *,
    slots: list[str],
    family: Mapping[str, str],
    realized: Mapping[str, float],
    proj: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """§5.2.2.  Per roster-week: IDP starters chosen from the ROSTERED defenders on each
    model's projections (a rostered defender the model did not project is NOT assignable
    and is counted — never 0), scored on realized points, against the realized-optimal
    lineup (ceiling).  Best ball: the host awards the ceiling anyway, so this measures the
    model's ordering of a manager's own defenders."""
    teams = inputs["teams"]
    cells: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    unproj: dict[str, int] = defaultdict(int)
    for tid in sorted(teams):
        roster = [p for p in teams[tid].get("roster") or [] if p in family]
        ceil_ids = _lineup_ids(roster, {p: realized.get(p, 0.0) for p in roster}, family, slots)
        ceiling = _realized_sum(ceil_ids, realized)
        for m in ALL_MODELS:
            vals = {p: proj.get(m, {}).get(p) for p in roster}
            unproj[m] += sum(1 for v in vals.values() if v is None)
            got = _realized_sum(_lineup_ids(roster, vals, family, slots), realized)
            cells[m][tid] = {"realized": got, "ceiling": ceiling, "regret": ceiling - got}
    out: dict[str, Any] = {
        "slots": slots,
        "rosterWeeks": len(teams),
        "unprojectedRosteredDefenders": dict(sorted(unproj.items())),
        "models": {},
        "didNotPlayScoredZero": "a rostered defender with no week stat line is the host's own "
        "realized 0 (best ball seats the better player); counted in the lineup, not hidden",
    }
    for m in ALL_MODELS:
        c = cells[m]
        n = len(c)
        out["models"][m] = {
            "n": n,
            "meanRealizedPoints": sum(v["realized"] for v in c.values()) / n if n else None,
            "meanCeilingPoints": sum(v["ceiling"] for v in c.values()) / n if n else None,
            "meanRegretVsCeiling": sum(v["regret"] for v in c.values()) / n if n else None,
        }
    paired: dict[str, Any] = {}
    for ref, models in ((PROV, VS_PROV), ("S0", VS_S0)):
        for m in models:
            d = [cells[m][t]["regret"] - cells[ref][t]["regret"] for t in sorted(teams)]
            paired[f"{m}_vs_{ref}"] = {
                "meanRegretDelta": sum(d) / len(d) if d else None,
                "note": "negative = smaller regret than the reference (descriptive, one week)",
            }
    out["pairedRegretDelta"] = paired
    return out


def streaming_metric(
    inputs: Mapping[str, Any],
    *,
    slots: list[str],
    family: Mapping[str, str],
    realized: Mapping[str, float],
    proj: Mapping[str, Mapping[str, float]],
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    """§5.2.3.  Per team-week, each model's single best add per IDP family (its highest
    projected AVAILABLE defender) replaces the team's lowest-projected same-family
    DROPPABLE rostered defender (droppable = the point-in-time context's zero-dynasty-loss
    set, supplied by the caller).  A move is made only when the model projects the add
    strictly above the drop; "no move" is a valid decision and scores 0.  Uplift = realized
    best-ball IDP lineup points with the swaps minus without (canonical solver on realized
    points).  A candidate or drop the model did not project is skipped and counted — never
    scored 0.  Opportunity cost = the realized-oracle uplift minus the model's."""
    teams = inputs["teams"]
    uplift: dict[str, dict[str, float]] = {m: {} for m in ALL_MODELS}
    opp: dict[str, dict[str, float]] = {m: {} for m in ALL_MODELS}
    moves: dict[str, int] = defaultdict(int)
    skipped: dict[str, int] = defaultdict(int)

    def lineup_points(ids: Iterable[str]) -> float:
        ids = list(ids)
        got = _lineup_ids(ids, {p: realized.get(p, 0.0) for p in ids}, family, slots)
        return _realized_sum(got, realized)

    def swaps(roster, pool, drop_ok, score, *, count: str | None):
        add_set: list[str] = []
        drop_set: list[str] = []
        for fam in FAMILIES:
            adds = [p for p in pool if family.get(p) == fam]
            drops = [p for p in roster if family.get(p) == fam and p in drop_ok]
            if count:
                skipped[count] += sum(1 for p in adds + drops if score.get(p) is None)
            adds = sorted(
                (p for p in adds if score.get(p) is not None), key=lambda p: (-score[p], p)
            )
            drops = sorted(
                (p for p in drops if score.get(p) is not None), key=lambda p: (score[p], p)
            )
            if adds and drops and score[adds[0]] > score[drops[0]]:
                add_set.append(adds[0])
                drop_set.append(drops[0])
        return add_set, drop_set

    for tid in sorted(teams):
        t = teams[tid]
        roster = [p for p in t.get("roster") or [] if p in family]
        pool = [p for p in t.get("pool") or [] if p in family]
        drop_ok = set(t.get("droppable") or [])
        base = lineup_points(roster)
        oa, od = swaps(
            roster, pool, drop_ok, {p: realized.get(p, 0.0) for p in roster + pool}, count=None
        )
        oracle = lineup_points([p for p in roster if p not in set(od)] + oa) - base
        for m in ALL_MODELS:
            adds, drops = swaps(roster, pool, drop_ok, proj.get(m, {}), count=m)
            gain = lineup_points([p for p in roster if p not in set(drops)] + adds) - base
            uplift[m][tid] = gain
            opp[m][tid] = oracle - gain
            moves[m] += len(adds)
    tids = sorted(teams)
    out: dict[str, Any] = {
        "teamWeeks": len(tids),
        "movesMade": dict(sorted(moves.items())),
        "unprojectedCandidatesOrDropsSkipped": dict(sorted(skipped.items())),
        "models": {
            m: {
                "meanUplift": sum(uplift[m].values()) / len(tids),
                "meanOpportunityCost": sum(opp[m].values()) / len(tids),
            }
            for m in ALL_MODELS
        },
        "paired": {},
        "pooledOverFamilies": True,
    }
    for ref, models in ((PROV, VS_PROV), ("S0", VS_S0)):
        for m in models:
            d = [uplift[m][t] - uplift[ref][t] for t in tids]
            out["paired"][f"{m}_vs_{ref}"] = _bootstrap_mean(d, resamples=resamples, seed=seed) | {
                "cluster": "team-week"
            }
    return out


# ── the weekly evaluation ────────────────────────────────────────────────────


def _paired_rows(
    rows: Mapping[str, list[Prediction]], a: str, b: str, family: str
) -> tuple[list[Prediction], list[Prediction]]:
    bk = {r.pid: r for r in rows[b] if r.family == family}
    ra = [r for r in rows[a] if r.family == family and r.pid in bk]
    return ra, [bk[r.pid] for r in ra]


def evaluate_week(
    *,
    data: SeasonData,
    card: Card,
    frozen: Mapping[str, Any],
    week: int,
    prediction_rows: Sequence[Mapping[str, Any]],
    prov: ProvSelection,
    decision_inputs: Mapping[str, Any] | None = None,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Every preregistered metric for ``week`` (prereg §4–§6).  Pure.

    Realized outcomes read ``data.stats[week]`` and are scored with ``card.points``
    (``score_stat_line``).  The result is DESCRIPTIVE for one week; confirmatory inference
    pools weeks 9–14 (the per-player rows are included so that pooling needs no re-fetch).
    """
    pop = population(data, week)
    outcomes = data.stats.get(week, {})
    preds = {str(r["pid"]): r for r in prediction_rows}
    top_n = {f: int(n) for f, n in (frozen.get("lineupDemand") or {}).get("topN", {}).items()}
    quant = (frozen.get("fit") or {}).get("residualQuantiles80") or {}

    rows: dict[str, list[Prediction]] = {m: [] for m in ALL_MODELS}
    excl: dict[str, dict[str, list[str]]] = {m: defaultdict(list) for m in ALL_MODELS}
    fallback_reasons: dict[str, int] = defaultdict(int)
    unknown_subgroup = 0
    per_player: list[dict[str, Any]] = []
    realized_all = {
        pid: card.points(line) for pid, line in outcomes.items() if data.positions.get(pid)
    }
    for pid in pop:
        fam, sub = data.positions[pid]
        actual = card.points(outcomes[pid])
        if sub == UNKNOWN:
            unknown_subgroup += 1
        rec: dict[str, Any] = {"pid": pid, "family": fam, "subgroup": sub, "actual": actual}
        p = preds.get(pid)
        for m in PROSPECTIVE_MODELS:
            if p is None:
                excl[m]["no_prediction_row"].append(pid)
                rec[m] = None
                continue
            proj = float(p["points"][m])
            q = (quant.get(m) or {}).get(fam)
            rows[m].append(
                Prediction(
                    season=data.season,
                    week=week,
                    pid=pid,
                    family=fam,
                    subgroup=sub,
                    challenger=None,
                    model=m,
                    effective_model=str((p.get("effectiveModel") or {}).get(m, m)),
                    projected=proj,
                    actual=actual,
                    lo=(proj + q[0]) if q else None,
                    hi=(proj + q[1]) if q else None,
                    reasons=tuple(p.get("reasons") or ()),
                )
            )
            rec[m] = proj
        if p is not None:
            for x in p.get("reasons") or ():
                fallback_reasons[str(x)] += 1
        if pid in prov.points:
            rows[PROV].append(
                Prediction(
                    season=data.season,
                    week=week,
                    pid=pid,
                    family=fam,
                    subgroup=sub,
                    challenger=None,
                    model=PROV,
                    effective_model=PROV,
                    projected=prov.points[pid],
                    actual=actual,
                    lo=None,
                    hi=None,
                    reasons=(),
                )
            )
            rec[PROV] = prov.points[pid]
        else:
            if pid in prov.unknown_kickoff:
                why = "kickoff_unknown"
            elif pid in prov.no_pre_kickoff:
                why = "no_pre_kickoff_capture"
            else:
                why = "no_provider_row"
            excl[PROV][why].append(pid)
            rec[PROV] = None
        per_player.append(rec)

    result: dict[str, Any] = {
        "week": week,
        "population": {
            "players": len(pop),
            "rule": "IDP-family player with week-W def_snp > 0 and >= 1 played week before W "
            "(evaluate.population)",
            "byFamily": {f: sum(1 for pid in pop if data.positions[pid][0] == f) for f in FAMILIES},
            "subgroupUnknownExcludedFromSubgroups": unknown_subgroup,
        },
        "coverage": {
            m: {"rows": len(rows[m]), "excluded": sum(len(v) for v in excl[m].values())}
            for m in ALL_MODELS
        },
        "exclusions": {m: {k: sorted(v) for k, v in sorted(excl[m].items())} for m in ALL_MODELS},
        "provArchive": {
            "capturesRead": prov.captures_read,
            "capturesUnreadable": prov.captures_unreadable,
            "playersSeen": len(prov.seen),
            "postKickoffCapturesIgnored": prov.post_kickoff_ignored,
            "selectedRowsWithProviderStampNotBeforeKickoff": prov.provider_stamp_not_before_kickoff,
        },
        "fallbackReasons": dict(sorted(fallback_reasons.items())),
        "descriptiveOnly": True,
    }

    # ── question 1: point error ──────────────────────────────────────────────
    pe: dict[str, Any] = {"byModelFamily": {}, "bySubgroup": {}, "primary": {}}
    for fam in FAMILIES:
        pe["byModelFamily"][fam] = {
            m: metrics([r for r in rows[m] if r.family == fam], top_n.get(fam, 0))
            for m in ALL_MODELS
        }
    for sg in SUBGROUPS:
        pe["bySubgroup"][sg] = {
            m: {
                k: v
                for k, v in metrics([r for r in rows[m] if r.subgroup == sg], 0).items()
                if k not in ("topN", "topNHitMeanWeekly")
            }
            for m in ALL_MODELS
        }
    tests: dict[tuple[str, str, str], dict[str, Any]] = {}
    for ref, models in ((PROV, VS_PROV), ("S0", VS_S0)):
        for fam in FAMILIES:
            for m in models:
                a, b = _paired_rows(rows, m, ref, fam)
                boot = bootstrap_delta_mae(a, b, resamples=resamples, seed=seed, levels=(0.95,))
                cell: dict[str, Any] = dict(boot)
                if a:
                    bias_m = sum(r.projected - r.actual for r in a) / len(a)
                    bias_r = sum(r.projected - r.actual for r in b) / len(b)
                    cell |= {
                        "biasModel": bias_m,
                        "biasReference": bias_r,
                        "biasNotWorse": abs(bias_m) <= abs(bias_r) + BIAS_MARGIN,
                    }
                tests[(m, ref, fam)] = cell
    adj = holm_adjust({k: v.get("pTwoSided") for k, v in tests.items()})
    for (m, ref, fam), cell in sorted(tests.items()):
        cell["holmAdjustedP"] = adj[(m, ref, fam)]
        ci = cell.get("ci95.0")
        cell["lowerPointError_descriptive"] = bool(
            ci
            and adj[(m, ref, fam)] is not None
            and adj[(m, ref, fam)] < ALPHA
            and ci[1] < 0
            and cell.get("biasNotWorse")
        )
        pe["primary"].setdefault(f"{m}_vs_{ref}", {})[fam] = cell
    pe["holmFamilySize"] = len(tests)
    result["pointError"] = pe

    # ── question 2: decisions ────────────────────────────────────────────────
    dec: dict[str, Any] = {"topN": {}}
    for ref, models in ((PROV, VS_PROV), ("S0", VS_S0)):
        for fam in FAMILIES:
            n = top_n.get(fam, 0)
            for m in models:
                a, b = _paired_rows(rows, m, ref, fam)
                ha, hb = top_n_hit(a, n), top_n_hit(b, n)
                dec["topN"].setdefault(f"{m}_vs_{ref}", {})[fam] = {
                    "topN": n,
                    "pairedRows": len(a),
                    "hitModel": ha,
                    "hitReference": hb,
                    "deltaHit": (ha - hb) if ha is not None and hb is not None else None,
                    "state": "ok" if ha is not None else "insufficient_paired_rows_for_top_n",
                }
    dec["topNInference"] = (
        "week-clustered CI and Holm (27 tests) need >= 2 weeks: pooled at the confirmatory read"
    )
    family_of = {pid: v[0] for pid, v in data.positions.items()}
    proj_by_model: dict[str, dict[str, float]] = {m: {} for m in ALL_MODELS}
    for pid, p in preds.items():
        for m in PROSPECTIVE_MODELS:
            proj_by_model[m][pid] = float(p["points"][m])
    proj_by_model[PROV] = dict(prov.points)
    slots = _slots(frozen)
    if decision_inputs_valid(decision_inputs):
        dec["rosterLineup"] = roster_lineup_metric(
            decision_inputs,
            slots=slots,
            family=family_of,
            realized=realized_all,
            proj=proj_by_model,
        )
        dec["streaming"] = streaming_metric(
            decision_inputs,
            slots=slots,
            family=family_of,
            realized=realized_all,
            proj=proj_by_model,
            resamples=resamples,
            seed=seed,
        )
        dec["decisionInputsSource"] = decision_inputs.get("source")
    else:
        why = {
            "state": "not_computed",
            "reason": "no point-in-time roster / candidate / droppable inputs were supplied "
            "(--decision-inputs); rosters at the week's first kickoff are not reconstructable "
            "from week-W data alone",
        }
        dec["rosterLineup"] = why
        dec["streaming"] = why
    result["decisions"] = dec
    result["rows"] = sorted(per_player, key=lambda r: r["pid"])
    return _r(result)
