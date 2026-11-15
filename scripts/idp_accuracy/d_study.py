"""Lane D study: build the player universe, run scenarios, aggregate by archetype.

Research only (``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` section 8 and 13).
This module must not import ``src.bestball``: ``tests/bestball/test_import_graph.py`` forbids it
outside ``scripts/bestball_marginal_report.py``.  The exact owners it does use are
``src.ros.lineup`` (eligibility) and ``src.nfl_data.realized_points`` (scoring), both through
``d_data`` / ``d_engine``.

Definitions fixed BEFORE the first result was computed (a pre-specification, not a fit):

* archetype labels come from provenance fields only (nflverse fine position, host eligibility);
* the evaluated universe is every rostered, forward-available player with >= 3 appearances;
* the primary distribution is the player's own empirical weeks (E); the archetype-shape (S) and
  gamma (P) models are sensitivity checks;
* the primary metric is the context-averaged marginal vs the best free-agent claim; the
  volatility premium J is its Jensen gap (M with the player's real weekly spread minus M with the
  same mean and zero spread), reported with a player + week bootstrap.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from scripts.idp_accuracy import d_data as D
from scripts.idp_accuracy import d_engine as E
from src.ros.lineup import lineup_position

MIN_OBS_EVAL = 3  # appearances needed to be evaluated (and to appear in archetype statistics)
FA_MIN_PLAYED = 2  # appearances needed to be a "production-qualified" free agent
EARLY = (1, 2, 3)
LATE = (4, 5, 6)


# ── entities ──────────────────────────────────────────────────────────────────


def _snap_share(ps: D.PlayerSeason, weeks: tuple[int, ...], idp: bool) -> float | None:
    vals = []
    for w in weeks:
        o = ps.weeks.get(w)
        if o is None or o.status != "played":
            continue
        a, b = (o.def_snaps, o.team_def_snaps) if idp else (o.off_snaps, o.team_off_snaps)
        if a is not None and b:
            vals.append(float(a) / float(b))
    return float(np.mean(vals)) if vals else None


def make_entity(
    pid: str,
    inp: D.Inputs,
    window: tuple[int, ...] | None = None,
) -> tuple[E.Entity | None, str | None]:
    """An :class:`Entity` for ``pid`` over ``window`` weeks, or (None, reason)."""
    meta = inp.directory.get(pid) or {}
    ps = inp.season26.get(pid)
    if ps is None:
        return None, "no_2026_stat_line"
    position = str(meta.get("position") or "")
    lpos = lineup_position(position)
    fps = tuple(meta.get("fantasy_positions") or (position,))
    sig = E.signature_for(pid, position, fps, inp.slots)
    sub = E.subproblem_of(sig)
    if sub is None:
        return None, "not_lineup_eligible" if not sig else "two_way_eligibility_out_of_scope"
    weeks = [w for w in ps.weeks if window is None or w in window]
    played = [ps.weeks[w].points for w in weeks if ps.weeks[w].status == "played"]
    games = [w for w in weeks if ps.weeks[w].status in ("played", "dnp")]
    idp = lpos in D.IDP_FAMILIES
    fine, _prov = inp.fine.get(pid, ("UNKNOWN", "")) if idp else (lpos, "")
    ev_counts = None
    if idp and played:
        ev_counts = np.array(
            [
                [ps.weeks[w].events.get(k, 0.0) for k in D.EVENT_KEYS]
                for w in weeks
                if ps.weeks[w].status == "played" and ps.weeks[w].events is not None
            ],
            dtype=float,
        )
    team = D._team(meta.get("team"))
    ent = E.Entity(
        pid=pid,
        name=str(meta.get("full_name") or pid),
        lpos=lpos,
        sub=sub,
        sig=sig,
        arch=D.archetype_for(fine, lpos, fps),
        fine=fine,
        team=team,
        bye_week=inp.bye26.get(team) if team else None,
        played=np.array([x for x in played if x is not None], dtype=float),
        n_games=len(games),
        played_weeks=tuple(w for w in weeks if ps.weeks[w].status == "played"),
        snap_share_early=_snap_share(ps, EARLY, idp),
        snap_share_late=_snap_share(ps, LATE, idp),
        ev_counts=ev_counts,
    )
    return ent, None


@dataclass
class Universe:
    window: str
    entities: list[E.Entity]
    pools: E.Pools
    eval_idx: list[int]
    owner_of: dict[int, int]
    teams: list[list[str]]
    fa_pids: set[str]
    slots: list[str]
    accounting: dict[str, Any] = field(default_factory=dict)


def classify(inp: D.Inputs, *, include_injured: bool = False) -> dict[str, Any]:
    """Who is rostered / free-agent / excluded, decided once from the full 6-week data.

    ``include_injured`` keeps players the host lists Out / IR / PUP / Sus in the pools at their
    historical availability.  It is a SENSITIVITY switch, not the base case: a player who is out
    must not count as healthy weekly production.
    """
    rostered = {pid: k for k, team in enumerate(inp.rosters) for pid in team}
    acct: dict[str, Any] = {
        "rosteredEntries": len(rostered),
        "excludedReasons": defaultdict(int),
    }
    excluded: dict[str, str] = {}
    eval_pids: list[str] = []
    fa_pids: set[str] = set()
    pool_pids: list[str] = []
    for pid in set(rostered) | set(inp.season26):
        meta = inp.directory.get(pid) or {}
        lpos = lineup_position(str(meta.get("position") or ""))
        if lpos not in D.OFFENSE_POSITIONS and lpos not in D.IDP_FAMILIES:
            if pid in rostered:
                excluded[pid] = "not_fantasy_position"
            continue
        ent, why = make_entity(pid, inp)
        if ent is None:
            if pid in rostered:
                excluded[pid] = why or "no_entity"
            continue
        if ent.n_played == 0:
            if pid in rostered:
                excluded[pid] = "no_appearance_weeks_1_6"
            continue
        if D.is_forward_unavailable(meta) and not include_injured:
            excluded[pid] = "forward_unavailable"
            continue
        if pid in rostered:
            pool_pids.append(pid)
            if ent.n_played >= MIN_OBS_EVAL:
                eval_pids.append(pid)
        else:
            recent = any(w in LATE for w in ent.played_weeks)
            if ent.n_played >= FA_MIN_PLAYED and recent and ent.team is not None:
                fa_pids.add(pid)
                pool_pids.append(pid)
    # roster entries that are not in any pool, by reason
    for pid in rostered:
        if pid not in set(pool_pids):
            excluded.setdefault(pid, "no_2026_stat_line")
    for pid, why in excluded.items():
        if pid in rostered:
            acct["excludedReasons"][why] += 1
    acct["excludedReasons"] = dict(acct["excludedReasons"])
    return {
        "rostered": rostered,
        "excluded": excluded,
        "eval_pids": eval_pids,
        "fa_pids": fa_pids,
        "pool_pids": pool_pids,
        "accounting": acct,
    }


def build_universe(inp: D.Inputs, cls: dict[str, Any], window: str = "all") -> Universe:
    win = {"all": None, "early": EARLY, "late": LATE, "all_inj": None}[window]
    ents: list[E.Entity] = []
    for pid in cls["pool_pids"]:
        ent, _ = make_entity(pid, inp, win)
        assert ent is not None
        ents.append(ent)
    teams = [[] for _ in inp.rosters]
    for pid, k in cls["rostered"].items():
        teams[k].append(pid)
    pools = E.build_pools(ents, teams, cls["fa_pids"], inp.slots, set())
    by = {e.pid: i for i, e in enumerate(ents)}
    eval_idx = [by[p] for p in cls["eval_pids"]]
    owner_of = {by[p]: cls["rostered"][p] for p in cls["rostered"] if p in by}
    return Universe(
        window,
        ents,
        pools,
        eval_idx,
        owner_of,
        teams,
        set(cls["fa_pids"]),
        list(inp.slots),
        cls["accounting"],
    )


# ── shape reference from the prior season ────────────────────────────────────


#: the shape reference is matched to the population the study evaluates (players with a real,
#: roster-relevant role): >= 10 appearances and >= 5 ppg when active.  The unfiltered variant
#: (>= 8 appearances, > 0.5 ppg) is kept as ``alt`` / model "Su" because it was the first one
#: computed and it includes fringe players whose weekly spread is much larger.
SHAPE_MATCHED = (10, 5.0)
SHAPE_UNFILTERED = (8, 0.5)


def _shape(inp: D.Inputs, min_weeks: int, min_mean: float) -> E.ShapeReference:
    by_arch: dict[str, list[float]] = defaultdict(list)
    n_players: dict[str, int] = defaultdict(int)
    for pid, ps in inp.season25.items():
        meta = inp.directory.get(pid) or {}
        position = str(meta.get("position") or "")
        lpos = lineup_position(position)
        if lpos not in D.OFFENSE_POSITIONS and lpos not in D.IDP_FAMILIES:
            continue
        pts = ps.played_points()
        if len(pts) < min_weeks:
            continue
        m = float(np.mean(pts))
        if m <= min_mean:
            continue
        idp = lpos in D.IDP_FAMILIES
        fine = inp.fine.get(pid, ("UNKNOWN", ""))[0] if idp else lpos
        fps = tuple(meta.get("fantasy_positions") or (position,))
        arch = D.archetype_for(fine, lpos, fps)
        z = [x / m for x in pts]
        for key in (arch, f"POS_{lpos}"):
            by_arch[key].extend(z)
            n_players[key] += 1
    ratios = {k: np.array(v, dtype=float) for k, v in by_arch.items()}
    cv = {k: float(np.std(v, ddof=1)) for k, v in ratios.items() if v.size > 2}
    event_points = np.array([float(inp.card.get(k, 0.0)) for k in D.EVENT_KEYS])
    return E.ShapeReference(ratios, cv, dict(n_players), event_points)


def build_shape(inp: D.Inputs) -> E.ShapeReference:
    """Archetype ratio pools from 2025, rescored under the 2026 card.  SHAPE ONLY.

    The returned reference is the matched one; the unfiltered one rides along as ``.alt``.
    """
    ref = _shape(inp, *SHAPE_MATCHED)
    ref.alt = _shape(inp, *SHAPE_UNFILTERED)
    return ref


# ── scenario execution ───────────────────────────────────────────────────────


def run_scenario(
    universes: dict[str, Universe], shape: E.ShapeReference, sc: E.Scenario
) -> list[dict[str, Any]]:
    """Per-evaluated-player record for one scenario."""
    uni = universes[sc.window]
    ds = E.DrawSet(uni.entities, shape, sc)
    # a bootstrap replicate resamples the weeks, so the FA ranking and type table follow it
    pools = uni.pools
    if sc.boot is not None:
        pools = E.build_pools(ds.eff, uni.teams, uni.fa_pids, uni.slots, set())
    res = E.evaluate_marginals(ds, pools, uni.eval_idx, uni.owner_of)
    det = E.deterministic_marginals(
        ds.eff, pools, uni.eval_idx, uni.owner_of, sc.cand_ranks, sc.repl_mode
    )
    out = []
    Dn = sc.draws
    for i in uni.eval_idx:
        e = ds.eff[i]
        r = res[i]
        base = r.base_with
        strip = r.deltas[-1.0]
        plus = r.deltas[0.5]
        j_draw = base - strip
        out.append(
            {
                "pid": e.pid,
                "name": e.name,
                "arch": e.arch,
                "lpos": e.lpos,
                "fine": e.fine,
                "sub": e.sub,
                "nPlayed": e.n_played,
                "nGames": e.n_games,
                "pActive": e.p_active,
                "muCond": e.mu_cond,
                "sdCond": e.sd_cond,
                "cvCond": e.cv_cond,
                "muUnc": e.mu_unc,
                "M": float(base.mean()),
                "Mse": float(base.std(ddof=1) / math.sqrt(Dn)),
                "Mown": r.own_with,
                "Mstrip": float(strip.mean()),
                "Mplus": float(plus.mean()),
                "J": float(j_draw.mean()),
                "Jse": float(j_draw.std(ddof=1) / math.sqrt(Dn)),
                "Mdet": det[i][0],
                "MdetOwn": det[i][1],
                "contexts": r.contexts,
                "noCandidateContexts": r.no_candidate_contexts,
                "snapEarly": e.snap_share_early,
                "snapLate": e.snap_share_late,
            }
        )
    return out
