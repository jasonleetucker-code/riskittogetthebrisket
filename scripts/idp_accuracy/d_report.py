"""Lane D report: aggregate scenario rows into the published evidence document.

Research only.  Public output rules (directive section 8 / task): aggregates and NFL player
names only.  Nothing here writes a manager, team-owner, roster id or user id, and no per-player
own-roster number (``Mown``) is published: contexts are only ever averaged.

Statistics are computed from the BASE empirical scenario; every confidence interval is a nested
percentile bootstrap: an outer replicate resamples each player's own weeks (the player-level
sampling error of an n = 6 sample, run through the whole pipeline again), an inner resample
draws players with replacement inside the group (the population sampling error).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

import numpy as np

from scripts.idp_accuracy import d_data as D
from scripts.idp_accuracy import d_engine as E
from scripts.idp_accuracy import d_study as S

SCHEMA = "idp_accuracy.bestball_archetypes.v1"
BASE_KEY = "E|observed|schedule|all|median:1-2-3-4-5"


def _k(
    model="E", avail="observed", byes="schedule", window="all", mode="median", ranks="1-2-3-4-5"
):
    return f"{model}|{avail}|{byes}|{window}|{mode}:{ranks}"


INNER = 20  # player resamples per outer (week-bootstrap) replicate
OFF4 = ("QB", "RB", "WR", "TE")
#: players compete for the same slots exactly when their eligibility is identical, so rank
#: comparisons are made inside these classes (a DL/LB hybrid is not a "linebacker" or a "lineman")
CLASSES = ("DL", "LB", "DB", "DL/LB", "DB/LB", "QB", "RB", "WR", "TE")
CLASSES_K = CLASSES + ("K",)


def elig_class(sig, lpos: str) -> str:
    if lpos in OFF4 or lpos == "K":
        return lpos
    s = frozenset(sig)
    if s == frozenset({"DL"}):
        return "DL"
    if s == frozenset({"LB"}):
        return "LB"
    if s == frozenset({"DB"}):
        return "DB"
    if s == frozenset({"DL", "LB"}):
        return "DL/LB"
    if s == frozenset({"DB", "LB"}):
        return "DB/LB"
    return "OTHER"


IDP_ARCHS = ("EDGE", "DT", "OLB", "ILB", "CB", "S")

#: ordered (label, member archetypes)
GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("EDGE", ("EDGE",)),
    ("DT", ("DT",)),
    ("DL (EDGE+DT)", ("EDGE", "DT")),
    ("ILB", ("ILB",)),
    ("OLB", ("OLB",)),
    ("LB (ILB+OLB)", ("ILB", "OLB")),
    ("CB", ("CB",)),
    ("S", ("S",)),
    ("DB (CB+S)", ("CB", "S")),
    ("IDP (all six)", IDP_ARCHS),
    ("QB", ("QB",)),
    ("RB", ("RB",)),
    ("WR", ("WR",)),
    ("TE", ("TE",)),
    ("K", ("K",)),
    ("Offense (QB/RB/WR/TE)", OFF4),
]
GROUP_MEMBERS = dict(GROUPS)

#: event groupings for the profile table.  These are the CANONICAL SCORER's component keys
#: (``compute_weekly_points(...).components``), which differ from the host stat-line keys in two
#: places: ``idp_pd`` (host ``idp_pass_def``) and ``idp_hit`` (host ``idp_qb_hit``).  Getting this
#: wrong silently drops pass defenses and QB hits from every share, so a test pins it.
KEYSETS = {
    "tackles": ("idp_tkl_solo", "idp_tkl_ast", "idp_tkl"),
    "tfl": ("idp_tkl_loss",),
    "passRush": ("idp_sack", "idp_sack_yd", "idp_hit"),
    "coverage": ("idp_pd", "idp_pd_3p", "idp_int", "idp_int_ret_yd"),
    "other": (
        "idp_ff",
        "idp_fum_rec",
        "idp_fum_ret_yd",
        "idp_def_td",
        "idp_safe",
        "idp_blk_kick",
        "st_tkl_solo",
        "st_ff",
        "st_fum_rec",
        "st_td",
    ),
}
#: the a-priori "big play" share: every priced DEFENSIVE event except tackles and TFL
#: (special-teams points are in "other" for the profile table but are not defensive big plays)
BIG_PLAY_IDP = (
    KEYSETS["passRush"]
    + KEYSETS["coverage"]
    + ("idp_ff", "idp_fum_rec", "idp_fum_ret_yd", "idp_def_td", "idp_safe", "idp_blk_kick")
)
BIG_PLAY_SKILL = (
    "rec_td",
    "rush_td",
    "rec_20_29",
    "rec_30_39",
    "rec_40p",
    "rush_td_40p",
    "rec_td_40p",
    "rec_td_50p",
)
BIG_PLAY_QB = ("rush_yd", "rush_att", "rush_td", "rush_fd", "rush_2pt")


def _r(x: float | None, nd: int = 3) -> float | None:
    if x is None:
        return None
    try:
        return None if not math.isfinite(float(x)) else round(float(x), nd)
    except (TypeError, ValueError):
        return None


# ── statistics over a list of rows ────────────────────────────────────────────


def _ratio(num: float, den: float) -> float:
    return num / den if den else float("nan")


def stat_mean(key: str) -> Callable[[list[dict]], float]:
    return lambda rs: float(np.mean([r[key] for r in rs])) if rs else float("nan")


def stat_J(rs):
    return float(np.mean([r["J"] for r in rs])) if rs else float("nan")


def stat_J_over_ppg(rs):
    return _ratio(sum(r["J"] for r in rs), sum(r["muUnc"] for r in rs))


def stat_J_over_sd(rs):
    return _ratio(sum(r["J"] for r in rs), sum(r["sdCond"] for r in rs if np.isfinite(r["sdCond"])))


def stat_plus_slope(rs):
    """Local value of +1 ppg of weekly SD: (M at +50% spread - M) / (0.5 SD)."""
    return _ratio(
        sum(r["Mplus"] - r["M"] for r in rs),
        0.5 * sum(r["sdCond"] for r in rs if np.isfinite(r["sdCond"])),
    )


def stat_M(rs):
    return float(np.mean([r["M"] for r in rs])) if rs else float("nan")


def stat_Mdet(rs):
    return float(np.mean([r["Mdet"] for r in rs])) if rs else float("nan")


def stat_bb_adjust(rs):
    return float(np.mean([r["M"] - r["Mdet"] for r in rs])) if rs else float("nan")


def stat_sd_over_ppg(rs):
    return _ratio(
        sum(r["sdCond"] for r in rs if np.isfinite(r["sdCond"])), sum(r["muCond"] for r in rs)
    )


def _rank(vals: list[float]) -> np.ndarray:
    from scipy.stats import rankdata

    return rankdata([-v for v in vals], method="average")


def _rho(a, b):
    return E.spearman(a, b)


def stat_rho_M(rs):
    return _rho([r["muUnc"] for r in rs], [r["M"] for r in rs])


def stat_rho_Mdet(rs):
    return _rho([r["muUnc"] for r in rs], [r["Mdet"] for r in rs])


def stat_rho_gap(rs):
    return stat_rho_Mdet(rs) - stat_rho_M(rs)


def stat_move_share(rs):
    """Share of players whose within-group rank by M differs from their rank by ppg materially."""
    n = len(rs)
    if n < 6:
        return float("nan")
    rp = _rank([r["muUnc"] for r in rs])
    rm = _rank([r["M"] for r in rs])
    thr = max(3, math.ceil(0.10 * n))
    return float(np.mean(np.abs(rp - rm) >= thr))


def stat_top_third_overlap(rs):
    n = len(rs)
    if n < 9:
        return float("nan")
    k = math.ceil(n / 3)
    a = set(np.argsort([-r["muUnc"] for r in rs], kind="stable")[:k])
    b = set(np.argsort([-r["M"] for r in rs], kind="stable")[:k])
    return len(a & b) / k


def stat_beta_sd(rs):
    """OLS coefficient of J on weekly SD, controlling for the mean (ppg lineup value per +1 ppg SD)."""
    rs = [r for r in rs if np.isfinite(r["sdCond"])]
    if len(rs) < 12:
        return float("nan")
    y = np.array([r["J"] for r in rs])
    sd = np.array([r["sdCond"] for r in rs])
    mu = np.array([r["muUnc"] for r in rs])
    X = np.column_stack([np.ones(len(rs)), sd, mu, mu * mu])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(beta[1])


def filt(rows: list[dict], archs: tuple[str, ...]) -> list[dict]:
    return [r for r in rows if r["arch"] in archs]


# ── bootstrap ────────────────────────────────────────────────────────────────


class Boot:
    """Nested bootstrap over the replicate scenario rows."""

    def __init__(self, base: list[dict], boots: list[list[dict]], seed: int = 61):
        self.base = base
        self.by_pid = [{r["pid"]: r for r in rows} for rows in boots]
        self.seed = seed

    def draws(
        self, pids: list[str], stat: Callable[[list[dict]], float], inner: int = INNER
    ) -> list[float]:
        out: list[float] = []
        for b, byp in enumerate(self.by_pid):
            rs = [byp[p] for p in pids if p in byp]
            if len(rs) < 3:
                continue
            rng = np.random.default_rng([self.seed, b])
            for _ in range(inner):
                idx = rng.integers(0, len(rs), len(rs))
                out.append(stat([rs[i] for i in idx]))
        return out

    def ci(
        self, pids, stat, point, lo=2.5, hi=97.5
    ) -> tuple[float | None, float | None, float | None]:
        """BASIC (reverse-percentile) bootstrap interval around ``point`` and the bootstrap bias.

        A percentile interval is wrong here: resampling the weeks of an n = 6 sample gives
        distributions with ~(n-1)/n of the original variance, so every replicate sits BELOW the
        plug-in estimate.  The basic interval ``[2*point - q_hi, 2*point - q_lo]`` measures the
        replicate-to-estimate gap and applies it the other way round, which absorbs that shift.
        ``bias`` (mean replicate minus point) is returned so the shift is visible, not hidden.
        """
        v = [x for x in self.draws(pids, stat) if np.isfinite(x)]
        if not v or not np.isfinite(point):
            return None, None, None
        a, b = E.percentile_ci(v, lo, hi)
        return _r(2 * point - b), _r(2 * point - a), _r(float(np.mean(v)) - point)

    def diff_ci(self, pids_a, pids_b, stat_a, stat_b, point, lo=2.5, hi=97.5):
        va = self.draws(pids_a, stat_a)
        vb = self.draws(pids_b, stat_b)
        n = min(len(va), len(vb))
        d = [x - y for x, y in zip(va[:n], vb[:n]) if np.isfinite(x) and np.isfinite(y)]
        if not d:
            return None, None, 0, None
        a, b = E.percentile_ci(d, lo, hi)
        return _r(2 * point - b), _r(2 * point - a), len(d), float(np.mean(d)) - point


def _est(
    boot: Boot, rows: list[dict], stat, lo=2.5, hi=97.5, bounds=None, kind: str = "bc"
) -> dict[str, Any]:
    """Estimate, 95% interval, plug-in and bootstrap bias.

    ``kind="bc"`` (levels, ratios, spreads): ``plugIn`` is the statistic on the observed weeks as
    pre-specified.  Every replicate resamples n = 6 weeks per player, which shrinks each spread by
    about (n-1)/n, so the replicates sit systematically below the plug-in: that gap is the plug-in's
    own small-sample bias, and ``est = plugIn - bootBias`` removes it (``2 * plugIn - mean(replicates)``).
    The interval is the matching basic interval, so ``est`` always lies inside it.

    ``kind="plain"`` (rank agreements and shares, which compare two quantities computed from the
    same weeks): the plug-in is reported as it is and the interval is the percentile interval of
    the replicates, i.e. "how this agreement would look had the six weeks come out differently".
    No bias correction is applied; the bias is still published.

    ``bounds`` clips to the statistic's natural range (a correlation or a share).
    """
    pids = [r["pid"] for r in rows]
    point = stat(rows) if rows else float("nan")
    a, b, bias = boot.ci(pids, stat, point, lo, hi) if rows else (None, None, None)
    if kind == "plain" and a is not None:
        # recover the percentile interval from the basic one: [2p - q_hi, 2p - q_lo]
        a, b = _r(2 * point - b), _r(2 * point - a)
        est = point
    else:
        est = point - bias if bias is not None else point
    if bounds is not None:
        if a is not None:
            a, b = max(a, bounds[0]), min(b, bounds[1])
        est = min(max(est, bounds[0]), bounds[1]) if np.isfinite(est) else est
    return {"est": _r(est), "plugIn": _r(point), "ci95": [a, b], "bootBias": bias}


# ── event, profile and variance tables ───────────────────────────────────────


def _key_share(ps: D.PlayerSeason, keys: tuple[str, ...]) -> float | None:
    tot = sum(ps.key_points.values())
    if tot <= 0:
        return None
    return sum(ps.key_points.get(k, 0.0) for k in keys) / tot


def big_play_share(inp: D.Inputs, pid: str, lpos: str) -> float | None:
    ps = inp.season26.get(pid)
    if ps is None:
        return None
    if lpos in D.IDP_FAMILIES:
        keys = BIG_PLAY_IDP
    elif lpos == "QB":
        keys = BIG_PLAY_QB
    elif lpos in ("RB", "WR", "TE"):
        keys = BIG_PLAY_SKILL
    else:
        return None
    return _key_share(ps, keys)


def archetype_profile(inp: D.Inputs, base: list[dict]) -> list[dict[str, Any]]:
    out = []
    for label, archs in GROUPS:
        rs = filt(base, archs)
        if not rs:
            continue
        row: dict[str, Any] = {
            "group": label,
            "n": len(rs),
            "meanAppearances": _r(np.mean([r["nPlayed"] for r in rs]), 2),
            "ppg": _r(np.mean([r["muUnc"] for r in rs]), 2),
            "ppgWhenActive": _r(np.mean([r["muCond"] for r in rs]), 2),
            "weeklySd": _r(np.nanmean([r["sdCond"] for r in rs]), 2),
            "cvPooled": _r(stat_sd_over_ppg(rs), 3),
            "pActive": _r(np.mean([r["pActive"] for r in rs]), 3),
        }
        if all(a in IDP_ARCHS for a in archs):
            ev_tot = np.zeros(len(D.EVENT_KEYS))
            games = 0.0
            shares = defaultdict(list)
            for r in rs:
                ps = inp.season26[r["pid"]]
                for w, o in ps.weeks.items():
                    if o.status == "played" and o.events is not None:
                        ev_tot += np.array([o.events.get(k, 0.0) for k in D.EVENT_KEYS])
                        games += 1
                for name, keys in KEYSETS.items():
                    s = _key_share(ps, keys)
                    if s is not None:
                        shares[name].append(s)
                bp = big_play_share(inp, r["pid"], r["lpos"])
                if bp is not None:
                    shares["bigPlay"].append(bp)
            row["eventsPerAppearance"] = {
                k.replace("idp_", ""): _r(v / games, 3) for k, v in zip(D.EVENT_KEYS, ev_tot)
            }
            row["pointsShare"] = {k: _r(np.mean(v), 3) for k, v in shares.items()}
            row["playerAppearances"] = int(games)
        else:
            bps = [big_play_share(inp, r["pid"], r["lpos"]) for r in rs]
            bps = [b for b in bps if b is not None]
            row["pointsShare"] = {"bigPlay": _r(np.mean(bps), 3)} if bps else {}
        out.append(row)
    return out


def variance_assumptions(
    inp: D.Inputs, shape: E.ShapeReference, base: list[dict]
) -> dict[str, Any]:
    """What is observed (event counts) versus what the models ASSUME about their spread."""
    ev_pts = shape.event_points
    rows = []
    for label, archs in GROUPS:
        if not all(a in IDP_ARCHS for a in archs):
            continue
        rs = filt(base, archs)
        if not rs:
            continue
        ratios = []
        for r in rs:
            ps = inp.season26[r["pid"]]
            counts = np.array(
                [
                    [o.events.get(k, 0.0) for k in D.EVENT_KEYS]
                    for o in ps.weeks.values()
                    if o.status == "played" and o.events is not None
                ]
            )
            if counts.shape[0] < 3:
                continue
            lam = counts.mean(axis=0)
            pois_var = float((ev_pts**2) @ lam)
            obs_var = float(r["sdCond"] ** 2)
            if pois_var > 0:
                ratios.append(obs_var / pois_var)
        # event-level dispersion from the prior season (large n): within-player var / mean
        disp = _dispersion_2025(inp, archs)
        rows.append(
            {
                "group": label,
                "playersWithRates": len(ratios),
                "observedOverPoissonScoreVariance": {
                    "median": _r(np.median(ratios), 2) if ratios else None,
                    "mean": _r(np.mean(ratios), 2) if ratios else None,
                },
                "eventDispersionIndex2025": disp,
            }
        )
    return {
        "classification": {
            "verified": [
                "per-appearance event counts (2026 wk 1-6 host stat lines, scorer-verified)",
                "points per event (the league card, fingerprint-pinned)",
                "weekly appearance record (played / DNP / bye from host snaps + nflverse schedule)",
            ],
            "provisionalVarianceAssumptions": [
                "E: a player's own <=6 weekly scores are his whole distribution (n-limited, bootstrap shows the cost)",
                "S: archetype SHAPE from 2025, rescored under the 2026 card (shape only; level is the player's own)",
                "P: gamma with archetype CV (two moments only)",
                "Q: independent Poisson event counts at the player's own observed rates (no event stacking)",
                "players are independent within a week (no shared game environment)",
                "the best free-agent claim is free, unique to the claiming team and unconstested",
                "availability = share of non-bye weeks the player appeared; no injury model",
            ],
        },
        "scoreVarianceVsPoisson": rows,
    }


def _dispersion_2025(inp: D.Inputs, archs: tuple[str, ...]) -> dict[str, float | None]:
    """Pooled within-player variance / mean of weekly event COUNTS (Poisson = 1.0), 2025."""
    num = defaultdict(float)
    den = defaultdict(float)
    nplayers = 0
    for pid, ps in inp.season25.items():
        meta = inp.directory.get(pid) or {}
        lpos = S.lineup_position(str(meta.get("position") or ""))
        if lpos not in D.IDP_FAMILIES:
            continue
        fine = inp.fine.get(pid, ("UNKNOWN", ""))[0]
        arch = D.archetype_for(fine, lpos, tuple(meta.get("fantasy_positions") or ()))
        if arch not in archs:
            continue
        evs = [o.events for o in ps.weeks.values() if o.status == "played" and o.events is not None]
        if len(evs) < 8:
            continue
        nplayers += 1
        for k in ("idp_sack", "idp_tkl_loss", "idp_qb_hit", "idp_pass_def", "idp_tkl_solo"):
            x = np.array([e.get(k, 0.0) for e in evs])
            num[k] += float(((x - x.mean()) ** 2).sum()) / (x.size - 1) * x.size
            den[k] += float(x.mean()) * x.size
    out = {k.replace("idp_", ""): _r(num[k] / den[k], 2) if den[k] else None for k in num}
    out["players"] = nplayers
    return out


# ── reliability (prior season) ───────────────────────────────────────────────


def _arch_of(inp: D.Inputs, pid: str) -> tuple[str, str]:
    meta = inp.directory.get(pid) or {}
    lpos = S.lineup_position(str(meta.get("position") or ""))
    fine = inp.fine.get(pid, ("UNKNOWN", ""))[0] if lpos in D.IDP_FAMILIES else lpos
    return D.archetype_for(fine, lpos, tuple(meta.get("fantasy_positions") or ())), lpos


def _sb(r: float) -> float:
    return 2 * r / (1 + r) if np.isfinite(r) and r > -1 else float("nan")


def reliability_2025(inp: D.Inputs) -> dict[str, Any]:
    """Split-half (odd / even weeks) reliability of mean, SD and CV, per group, 2025."""
    per: dict[str, list[tuple]] = defaultdict(list)
    for pid, ps in inp.season25.items():
        arch, lpos = _arch_of(inp, pid)
        wk = sorted(w for w, o in ps.weeks.items() if o.status == "played" and o.points is not None)
        if len(wk) < 12:
            continue
        a = np.array([ps.weeks[w].points for w in wk[0::2]])
        b = np.array([ps.weeks[w].points for w in wk[1::2]])
        if a.mean() <= 0.5 or b.mean() <= 0.5:
            continue
        per[arch].append(
            (
                a.mean(),
                b.mean(),
                a.std(ddof=1),
                b.std(ddof=1),
                a.std(ddof=1) / a.mean(),
                b.std(ddof=1) / b.mean(),
            )
        )
    out = {}
    for label, archs in GROUPS:
        if label.startswith(("DL ", "LB ", "DB ", "IDP", "Offense")):
            continue
        rows = [t for a in archs for t in per.get(a, [])]
        if len(rows) < 10:
            continue
        arr = np.array(rows)
        r_mean = E.spearman(arr[:, 0], arr[:, 1])
        r_sd = E.spearman(arr[:, 2], arr[:, 3])
        r_cv = E.spearman(arr[:, 4], arr[:, 5])
        out[label] = {
            "players": len(rows),
            "halfLengthWeeks": "6 (odd / even weeks of >= 12 appearances)",
            "meanHalfCorr": _r(r_mean, 2),
            "sdHalfCorr": _r(r_sd, 2),
            "cvHalfCorr": _r(r_cv, 2),
            "cvFullSeasonReliabilitySpearmanBrown": _r(_sb(r_cv), 2),
            "meanFullSeasonReliabilitySpearmanBrown": _r(_sb(r_mean), 2),
        }
    return out


def yoy(inp: D.Inputs) -> dict[str, Any]:
    out = {}
    per: dict[str, list[tuple]] = defaultdict(list)
    for pid, ps25 in inp.season25.items():
        ps26 = inp.season26.get(pid)
        if ps26 is None:
            continue
        a = ps25.played_points()
        b = ps26.played_points()
        if len(a) < 8 or len(b) < 4:
            continue
        a, b = np.array(a), np.array(b)
        if a.mean() <= 0.5 or b.mean() <= 0.5:
            continue
        arch, _ = _arch_of(inp, pid)
        per[arch].append((a.mean(), b.mean(), a.std(ddof=1) / a.mean(), b.std(ddof=1) / b.mean()))
    for label, archs in GROUPS:
        if label.startswith(("DL ", "LB ", "DB ", "IDP", "Offense")):
            continue
        rows = [t for a in archs for t in per.get(a, [])]
        if len(rows) < 10:
            continue
        arr = np.array(rows)
        out[label] = {
            "players": len(rows),
            "meanYoYCorr": _r(E.spearman(arr[:, 0], arr[:, 1]), 2),
            "cvYoYCorr": _r(E.spearman(arr[:, 2], arr[:, 3]), 2),
        }
    return out


def winners_curse(inp: D.Inputs) -> dict[str, Any]:
    """2025: do players ranked in the replacement band by weeks 1-6 keep their weekly mean after?"""
    out = {}
    for fam in ("DL", "LB", "DB", "RB", "WR", "TE"):
        rows = []
        for pid, ps in inp.season25.items():
            arch, lpos = _arch_of(inp, pid)
            if lpos != fam:
                continue
            early = [
                ps.weeks[w].points
                for w in range(1, 7)
                if w in ps.weeks and ps.weeks[w].status == "played"
            ]
            late = [
                ps.weeks[w].points
                for w in range(7, 19)
                if w in ps.weeks and ps.weeks[w].status == "played"
            ]
            if len(early) < 4 or len(late) < 6:
                continue
            rows.append((float(np.mean(early)), float(np.mean(late))))
        if len(rows) < 60:
            continue
        rows.sort(key=lambda t: -t[0])
        arr = np.array(rows)
        k = {"DL": 36, "LB": 36, "DB": 36, "RB": 24, "WR": 36, "TE": 24}[fam]
        band = arr[k : k + 80]
        top = arr[:k]
        out[fam] = {
            "players": len(rows),
            "topStarterBand": {
                "n": len(top),
                "meanWk1to6": _r(top[:, 0].mean(), 2),
                "meanWk7to18": _r(top[:, 1].mean(), 2),
            },
            "replacementBand": {
                "n": len(band),
                "rankRange": f"{k + 1}-{k + len(band)}",
                "meanWk1to6": _r(band[:, 0].mean(), 2),
                "meanWk7to18": _r(band[:, 1].mean(), 2),
                "regressionPpg": _r(band[:, 1].mean() - band[:, 0].mean(), 2),
            },
        }
    return out


# ── the main table builders ──────────────────────────────────────────────────


def premium_table(base: list[dict], boot: Boot) -> list[dict[str, Any]]:
    out = []
    for label, archs in GROUPS:
        rs = filt(base, archs)
        if len(rs) < 5:
            continue
        row = {
            "group": label,
            "n": len(rs),
            "J": _est(boot, rs, stat_J),
            "JoverPpg": _est(boot, rs, stat_J_over_ppg),
            "JperWeeklySd": _est(boot, rs, stat_J_over_sd),
            "plusSlopePerSd": _est(boot, rs, stat_plus_slope),
            "M": _est(boot, rs, stat_M, kind="plain"),
            "Mdet": _est(boot, rs, stat_Mdet, kind="plain"),
            "bestBallAdjustment": _est(boot, rs, stat_bb_adjust, kind="plain"),
            "sdOverPpg": _est(boot, rs, stat_sd_over_ppg),
            "betaSdControlMean": _est(boot, rs, stat_beta_sd),
        }
        row["jCiExcludesZero"] = bool(row["J"]["ci95"][0] is not None and row["J"]["ci95"][0] > 0)
        out.append(row)
    return out


def contrasts(base: list[dict], boot: Boot) -> list[dict[str, Any]]:
    spec = [
        ("EDGE minus DT", ("EDGE",), ("DT",)),
        ("CB minus S", ("CB",), ("S",)),
        ("DL (EDGE+DT) minus LB (ILB+OLB)", ("EDGE", "DT"), ("ILB", "OLB")),
        ("CB minus ILB", ("CB",), ("ILB",)),
        ("IDP (all six) minus offense (QB/RB/WR/TE)", IDP_ARCHS, OFF4),
    ]
    m = len(spec)
    lo, hi = 100 * (0.05 / m / 2), 100 * (1 - 0.05 / m / 2)
    out = []
    for name, a, b in spec:
        ra, rb = filt(base, a), filt(base, b)
        if len(ra) < 5 or len(rb) < 5:
            continue
        pa, pb = [r["pid"] for r in ra], [r["pid"] for r in rb]
        entry = {"contrast": name, "nA": len(ra), "nB": len(rb)}
        for metric, stat in (
            ("JoverPpg", stat_J_over_ppg),
            ("JperWeeklySd", stat_J_over_sd),
            ("sdOverPpg", stat_sd_over_ppg),
        ):
            plug = stat(ra) - stat(rb)
            c95 = boot.diff_ci(pa, pb, stat, stat, plug)
            cb = boot.diff_ci(pa, pb, stat, stat, plug, lo, hi)
            bias = c95[3] or 0.0
            entry[metric] = {
                "diff": _r(plug - bias),
                "plugIn": _r(plug),
                "bootBias": _r(bias),
                "ci95": [c95[0], c95[1]],
                "ciBonferroni": [cb[0], cb[1]],
                "bonferroniFamilySize": m,
                "ciExcludesZero95": bool(c95[0] is not None and (c95[0] > 0 or c95[1] < 0)),
                "ciExcludesZeroBonferroni": bool(cb[0] is not None and (cb[0] > 0 or cb[1] < 0)),
            }
        out.append(entry)
    return out


def rank_table(base: list[dict], boot: Boot) -> dict[str, Any]:
    fam_out = []
    for fam in CLASSES_K:
        rs = [r for r in base if r["cls"] == fam and r["arch"] in (IDP_ARCHS + OFF4 + ("K",))]
        if len(rs) < 8:
            continue
        fam_out.append(
            {
                "family": fam,
                "n": len(rs),
                "rhoPpgVsBestBall": _est(boot, rs, stat_rho_M, bounds=(-1.0, 1.0), kind="plain"),
                "rhoPpgVsDeterministicLineup": _est(
                    boot, rs, stat_rho_Mdet, bounds=(-1.0, 1.0), kind="plain"
                ),
                "rhoGap": _est(boot, rs, stat_rho_gap, bounds=(-2.0, 2.0), kind="plain"),
                "materialRankChangeShare": _est(
                    boot, rs, stat_move_share, bounds=(0.0, 1.0), kind="plain"
                ),
                "topThirdOverlap": _est(
                    boot, rs, stat_top_third_overlap, bounds=(0.0, 1.0), kind="plain"
                ),
            }
        )
    arch_out = []
    for label, archs in GROUPS:
        if len(archs) != 1:
            continue
        rs = filt(base, archs)
        if len(rs) < 8:
            continue
        arch_out.append(
            {
                "group": label,
                "n": len(rs),
                "rhoPpgVsBestBall": _est(boot, rs, stat_rho_M, bounds=(-1.0, 1.0), kind="plain"),
                "rhoGap": _est(boot, rs, stat_rho_gap, bounds=(-2.0, 2.0), kind="plain"),
                "materialRankChangeShare": _est(
                    boot, rs, stat_move_share, bounds=(0.0, 1.0), kind="plain"
                ),
            }
        )
    return {
        "definition": (
            "rank within the lineup-position family (DL, LB, DB, QB, RB, WR, TE, K) by expected ppg "
            "(availability-weighted mean) versus by the best-ball marginal over the best free-agent claim; "
            "'deterministic lineup' is the same marginal in a world where every player scores exactly his "
            "ppg every week; 'material' = rank differs by at least max(3, 10% of the group)"
        ),
        "byFamily": fam_out,
        "byArchetype": arch_out,
    }


def player_ranks(base: list[dict]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    by: dict[str, list[dict]] = defaultdict(list)
    for r in base:
        by[r["cls"]].append(r)
    for fam, rs in by.items():
        rp = _rank([r["muUnc"] for r in rs])
        rm = _rank([r["M"] for r in rs])
        rd = _rank([r["Mdet"] for r in rs])
        for r, a, b, c in zip(rs, rp, rm, rd):
            out[r["pid"]] = {
                "rankPpg": _r(a, 1),
                "rankBestBall": _r(b, 1),
                "rankDeterministic": _r(c, 1),
                "familySize": len(rs),
            }
    return out


def model_comparison(res: dict[str, Any], boot: Boot, base: list[dict]) -> dict[str, Any]:
    keys = {
        "E (own weeks)": _k("E"),
        "Ec (own weeks, n/(n-1) variance correction)": _k("Ec"),
        "S (2025 archetype shape, matched)": _k("S"),
        "Su (2025 archetype shape, unfiltered)": _k("Su"),
        "P (gamma, archetype CV)": _k("P"),
        "Q (Poisson events)": _k("Q"),
    }
    tables = {}
    byp = {}
    for name, k in keys.items():
        if k not in res:
            continue
        rows = res[k]["rows"]
        byp[name] = {r["pid"]: r for r in rows}
        tables[name] = rows
    out_groups = []
    for label, archs in GROUPS:
        entry = {"group": label}
        for name, rows in tables.items():
            if name.startswith("Q") and not all(a in IDP_ARCHS for a in archs):
                continue
            rs = filt(rows, archs)
            if len(rs) < 5:
                continue
            entry[name] = {
                "JoverPpg": _r(stat_J_over_ppg(rs)),
                "J": _r(stat_J(rs)),
                "M": _r(stat_M(rs)),
                "rhoPpgVsBestBall": _r(stat_rho_M(rs)),
            }
        if len(entry) > 1:
            out_groups.append(entry)
    corr = {}
    for fam in CLASSES:
        e_rows = [r for r in base if r["cls"] == fam]
        d = {}
        for name, mp in byp.items():
            if name.startswith("E ("):
                continue
            pairs = [
                (r["J"], mp[r["pid"]]["J"], r["M"], mp[r["pid"]]["M"])
                for r in e_rows
                if r["pid"] in mp
            ]
            if len(pairs) < 10:
                continue
            arr = np.array(pairs)
            d[name] = {
                "n": len(pairs),
                "playerJSpearmanVsE": _r(E.spearman(arr[:, 0], arr[:, 1]), 2),
                "playerMSpearmanVsE": _r(E.spearman(arr[:, 2], arr[:, 3]), 2),
            }
        corr[fam] = d
    spec = [
        ("EDGE minus DT", ("EDGE",), ("DT",)),
        ("CB minus S", ("CB",), ("S",)),
        ("DL (EDGE+DT) minus LB (ILB+OLB)", ("EDGE", "DT"), ("ILB", "OLB")),
        ("CB minus ILB", ("CB",), ("ILB",)),
        ("IDP (all six) minus offense (QB/RB/WR/TE)", IDP_ARCHS, OFF4),
    ]
    contrast_models = []
    for cname, ga, gb in spec:
        entry = {"contrast": cname}
        for name, rows in tables.items():
            ra = filt(rows, ga)
            # the event model has no offense: its offense side is the empirical one
            rb_rows = tables["E (own weeks)"] if (name.startswith("Q") and gb == OFF4) else rows
            rb = filt(rb_rows, gb)
            if len(ra) < 5 or len(rb) < 5:
                continue
            entry[name] = _r(stat_J_over_ppg(ra) - stat_J_over_ppg(rb))
        contrast_models.append(entry)
    return {
        "byGroup": out_groups,
        "playerLevelAgreementWithE": corr,
        "contrastsByModel": contrast_models,
    }


def sensitivity_table(res: dict[str, Any], base: list[dict]) -> dict[str, Any]:
    variants = {
        "base (median of FA ranks 1-5, observed availability, schedule byes)": BASE_KEY,
        "replacement = best of FA ranks 1-2": _k(mode="best", ranks="1-2"),
        "replacement = FA rank 1 only": _k(mode="best", ranks="1"),
        "replacement = third-best FA": _k(mode="best", ranks="3"),
        "replacement = fifth-best FA": _k(mode="best", ranks="5"),
        "availability forced to 100%": _k(avail="always"),
        "no bye weeks": _k(byes="none"),
        "injured / out players kept at historical availability": _k(window="all_inj"),
    }
    out = []
    for label, archs in GROUPS:
        entry = {"group": label}
        for name, k in variants.items():
            if k not in res:
                continue
            rows = res[k]["rows"]
            keep = {r["pid"] for r in base}
            rs = [r for r in filt(rows, archs) if r["pid"] in keep]
            if len(rs) < 5:
                continue
            # a forced-100%-availability world ranks players by ppg WHEN ACTIVE; every other world
            # ranks by the availability-weighted ppg the base uses
            ppg_key = "muCond" if "forced" in name else "muUnc"
            entry[name] = {
                "n": len(rs),
                "JoverPpg": _r(stat_J_over_ppg(rs)),
                "M": _r(stat_M(rs)),
                "rhoPpgVsBestBall": _r(_rho([r[ppg_key] for r in rs], [r["M"] for r in rs])),
            }
        if len(entry) > 1:
            out.append(entry)
    return {"variants": list(variants), "byGroup": out}


def role_change(res: dict[str, Any], base: list[dict]) -> dict[str, Any]:
    ke, kl = _k(window="early"), _k(window="late")
    if ke not in res or kl not in res:
        return {"available": False}
    early = {r["pid"]: r for r in res[ke]["rows"]}
    late = {r["pid"]: r for r in res[kl]["rows"]}
    keep = [
        r
        for r in base
        if r["pid"] in early
        and r["pid"] in late
        and early[r["pid"]]["nPlayed"] >= 2
        and late[r["pid"]]["nPlayed"] >= 2
    ]
    flagged = [
        r
        for r in keep
        if r["snapEarly"] is not None
        and r["snapLate"] is not None
        and abs(r["snapLate"] - r["snapEarly"]) >= 0.15
    ]
    fam_rows = []
    for fam in CLASSES:
        fr = [r for r in keep if r["cls"] == fam]
        if len(fr) < 10:
            continue
        fam_rows.append(
            {
                "family": fam,
                "n": len(fr),
                "ppgEarlyVsLateSpearman": _r(
                    E.spearman(
                        [early[r["pid"]]["muUnc"] for r in fr],
                        [late[r["pid"]]["muUnc"] for r in fr],
                    ),
                    2,
                ),
                "bestBallMarginalEarlyVsLateSpearman": _r(
                    E.spearman(
                        [early[r["pid"]]["M"] for r in fr], [late[r["pid"]]["M"] for r in fr]
                    ),
                    2,
                ),
                "volatilityPremiumEarlyVsLateSpearman": _r(
                    E.spearman(
                        [early[r["pid"]]["J"] for r in fr], [late[r["pid"]]["J"] for r in fr]
                    ),
                    2,
                ),
            }
        )
    grp = []
    for label, archs in GROUPS:
        if len(archs) != 1:
            continue
        pe = [early[r["pid"]] for r in keep if r["arch"] in archs]
        pl = [late[r["pid"]] for r in keep if r["arch"] in archs]
        if len(pe) < 8:
            continue
        grp.append(
            {
                "group": label,
                "n": len(pe),
                "JoverPpgEarly": _r(stat_J_over_ppg(pe)),
                "JoverPpgLate": _r(stat_J_over_ppg(pl)),
            }
        )
    movers = []
    for r in flagged:
        e, lt = early[r["pid"]], late[r["pid"]]
        movers.append(
            {
                "name": r["name"],
                "archetype": r["arch"],
                "snapShareEarly": _r(r["snapEarly"], 2),
                "snapShareLate": _r(r["snapLate"], 2),
                "ppgEarly": _r(e["muUnc"], 2),
                "ppgLate": _r(lt["muUnc"], 2),
                "bestBallMarginalEarly": _r(e["M"], 2),
                "bestBallMarginalLate": _r(lt["M"], 2),
            }
        )
    movers.sort(key=lambda m: -abs((m["snapShareLate"] or 0) - (m["snapShareEarly"] or 0)))
    return {
        "available": True,
        "definition": "early = weeks 1-3, late = weeks 4-6; role change = |late - early snap share| >= 0.15; players need >= 2 appearances in each window",
        "playersCompared": len(keep),
        "roleChangeFlagged": len(flagged),
        "byFamily": fam_rows,
        "volatilityPremiumByArchetypeByWindow": grp,
        "largestRoleChanges": movers[:15],
    }


def realized_check(
    inp: D.Inputs, uni: S.Universe, base: list[dict], seed_cand=(1, 2, 3, 4, 5)
) -> dict[str, Any]:
    """Descriptive, in-sample: the same marginal on the SIX ACTUAL weeks, no model of the spread."""
    ents = uni.entities
    X = np.zeros((6, len(ents)))
    for i, e in enumerate(ents):
        ps = inp.season26.get(e.pid)
        if ps is None:
            continue
        for w in D.WEEKS:
            o = ps.weeks.get(w)
            if o is not None and o.status == "played" and o.points is not None:
                X[w - 1, i] = o.points
    sc = E.Scenario(draws=6, deltas=(), cand_ranks=seed_cand)
    ds = E.DrawSet.from_matrix(ents, X, sc)
    res = E.evaluate_marginals(ds, uni.pools, uni.eval_idx, uni.owner_of)
    real = {ents[i].pid: float(r.base_with.mean()) for i, r in res.items()}
    out = []
    for fam in CLASSES:
        rs = [r for r in base if r["cls"] == fam and r["pid"] in real]
        if len(rs) < 10:
            continue
        out.append(
            {
                "family": fam,
                "n": len(rs),
                "spearmanModelVsRealized": _r(
                    E.spearman([r["M"] for r in rs], [real[r["pid"]] for r in rs]), 2
                ),
                "spearmanPpgVsRealized": _r(
                    E.spearman([r["muUnc"] for r in rs], [real[r["pid"]] for r in rs]), 2
                ),
            }
        )
    return {
        "definition": "marginal vs the best free-agent claim on the six actual weeks (weeks 1-6, bye = 0), averaged over the 12 roster contexts; n = 6 weeks per player, in-sample, no variance model",
        "byFamily": out,
    }


def population_block(
    inp: D.Inputs, cls: dict[str, Any], universes: dict[str, S.Universe], base: list[dict]
) -> dict[str, Any]:
    uni = universes["all"]
    by_arch = defaultdict(int)
    for r in base:
        by_arch[r["arch"]] += 1
    fa_by_group = {g: len(v) for g, v in sorted(uni.pools.fa_by_group.items())}
    return {
        "evaluated": len(base),
        "evaluatedByArchetype": dict(sorted(by_arch.items())),
        "definition": f"rostered in the league, forward-available, >= {S.MIN_OBS_EVAL} appearances in 2026 weeks 1-6",
        "poolPlayersSimulated": len(uni.entities),
        "freeAgentsQualified": len(cls["fa_pids"]),
        "freeAgentDefinition": f"unrostered, forward-available, >= {S.FA_MIN_PLAYED} appearances and at least one in weeks 4-6",
        "freeAgentsByEligibleSlotGroup": fa_by_group,
        "rosterEntriesExcluded": cls["accounting"]["excludedReasons"],
        "rosterEntries": cls["accounting"]["rosteredEntries"],
        "teams": len(inp.rosters),
        "startingSlots": inp.slots,
    }


def fine_resolution(inp: D.Inputs, base: list[dict]) -> dict[str, Any]:
    prov = defaultdict(int)
    by_fine = defaultdict(int)
    for pid, (fine, why) in inp.fine.items():
        if inp.season26.get(pid) and len(inp.season26[pid].played_points()) >= 1:
            prov[why.split(":")[0] if fine != "UNKNOWN" else f"UNKNOWN:{why}"] += 1
            by_fine[fine] += 1
    # independent cross-check: where Sleeper's own depth chart names a fine position too
    agree = disagree = 0
    for pid, (fine, why) in inp.fine.items():
        meta = inp.directory.get(pid) or {}
        sd = D._SLEEPER_DEPTH.get(str(meta.get("depth_chart_position") or "").strip().upper())
        if sd and fine != "UNKNOWN" and not why.startswith("sleeper_depth"):
            if sd == fine:
                agree += 1
            else:
                disagree += 1
    unknown_eval = sum(1 for r in base if r["arch"].startswith("UNK_"))
    return {
        "source": "nflverse-data rosters/roster_{2026,2025}.csv depth_chart_position (primary); Sleeper depth_chart_position only when nflverse is silent",
        "joinOrder": ["sleeper_id", "gsis_id", "unique name+team", "sleeper_depth_chart"],
        "playersWithAppearancesByProvenance": dict(sorted(prov.items())),
        "playersWithAppearancesByFinePosition": dict(sorted(by_fine.items())),
        "crossCheckNflverseVsSleeperDepth": {
            "agree": agree,
            "disagree": disagree,
            "agreementRate": _r(agree / (agree + disagree), 3) if agree + disagree else None,
        },
        "evaluatedPlayersWithUnknownFinePosition": unknown_eval,
        "archetypeRules": {
            "EDGE": "nflverse DE, or an OLB the host also lists at DL",
            "DT": "nflverse DT or NT",
            "OLB": "nflverse OLB without host DL eligibility (off-ball)",
            "ILB": "nflverse ILB or MLB",
            "CB": "nflverse CB",
            "S": "nflverse FS / SS / S",
            "UNKNOWN": "no nflverse or Sleeper-depth fine position; excluded from archetype statistics",
        },
    }


def provenance_block(inp: D.Inputs, args, shape: E.ShapeReference) -> dict[str, Any]:
    return {
        "leagueKey": D.LEAGUE_KEY,
        "leagueId": D.LEAGUE_ID,
        "season": D.SEASON,
        "statisticsWeeks": list(D.WEEKS),
        "shapeSeason": D.SHAPE_SEASON,
        "shapeUse": "2025 weekly stat lines rescored under the 2026 card; used for distribution SHAPE only (model S, model P CV), never for level, rank or value",
        "scoringFingerprint": inp.fingerprint,
        "scoringFingerprintMatchesLaneA": inp.fingerprint == D.PINNED_SCORING_FINGERPRINT,
        "scorer": "src.nfl_data.realized_points.compute_weekly_points(source='sleeper') over the league scoring_settings (Lane A: 3,710 / 3,710 within 0.01 of Sleeper players_points, 2026 wk 1-6)",
        "lineupEligibility": "src.ros.lineup.precompute_slot_eligibility (host fantasy_positions); vectorized solver pinned to src.ros.lineup.solve_optimal_assignment by tests",
        "datasets": inp.receipts,
        "canonicalWeeklyRowsSha256": inp.canonical_rows_sha256,
        "parameters": {
            "draws": args.draws,
            "seed": args.seed,
            "weekBootstrapReplicates": args.boots,
            "innerPlayerResamples": INNER,
            "remainingFantasyWeeks": list(E.Scenario().remaining_weeks),
            "candidateReplacementRanks": [1, 2, 3, 4, 5],
            "replacementRule": "median-scoring roster among the rank 1-5 free agents per opened slot family (sensitivities: best-of, rank 1, 3, 5)",
            "deltasMeanPreservingSdScale": [-1.0, 0.5],
            "minAppearancesEvaluated": S.MIN_OBS_EVAL,
            "minAppearancesFreeAgent": S.FA_MIN_PLAYED,
            "shapeFilterMatched": {
                "minAppearances": S.SHAPE_MATCHED[0],
                "minPpgWhenActive": S.SHAPE_MATCHED[1],
            },
            "shapeFilterUnfiltered": {
                "minAppearances": S.SHAPE_UNFILTERED[0],
                "minPpgWhenActive": S.SHAPE_UNFILTERED[1],
            },
        },
        "shapeReference": {
            "playersByArchetype": shape.n_players,
            "pooledCv": {k: _r(v, 3) for k, v in shape.cv.items()},
        },
        "byeWeeksFromSchedule": "nflverse schedules/games.csv, 2026 REG",
    }


def players_table(
    inp: D.Inputs, base: list[dict], res: dict[str, Any], ranks: dict[str, Any]
) -> list[dict[str, Any]]:
    other = {}
    for tag, key in (("S", _k("S")), ("P", _k("P")), ("Q", _k("Q")), ("Ec", _k("Ec"))):
        if key in res:
            other[tag] = {r["pid"]: r for r in res[key]["rows"]}
    rows = []
    for r in sorted(base, key=lambda r: (r["cls"], -r["muUnc"])):
        rk = ranks[r["pid"]]
        rows.append(
            {
                "name": r["name"],
                "sleeperId": r["pid"],
                "archetype": r["arch"],
                "family": r["lpos"],
                "rankGroup": r["cls"],
                "appearances": r["nPlayed"],
                "nonByeWeeks": r["nGames"],
                "ppg": _r(r["muUnc"], 2),
                "ppgWhenActive": _r(r["muCond"], 2),
                "weeklySd": _r(r["sdCond"], 2),
                "cv": _r(r["cvCond"], 2),
                "bigPlayShare": _r(big_play_share(inp, r["pid"], r["lpos"]), 3),
                "bestBallMarginal": _r(r["M"], 2),
                "bestBallMarginalMcSe": _r(r["Mse"], 3),
                "deterministicMarginal": _r(r["Mdet"], 2),
                "volatilityPremium": _r(r["J"], 2),
                "volatilityPremiumMcSe": _r(r["Jse"], 3),
                "rankPpg": rk["rankPpg"],
                "rankBestBall": rk["rankBestBall"],
                "rankDeterministic": rk["rankDeterministic"],
                "familySize": rk["familySize"],
                "volatilityPremiumByModel": {
                    t: _r(m[r["pid"]]["J"], 2) for t, m in other.items() if r["pid"] in m
                },
                "bestBallMarginalByModel": {
                    t: _r(m[r["pid"]]["M"], 2) for t, m in other.items() if r["pid"] in m
                },
            }
        )
    return rows


def profile_split(inp: D.Inputs, base: list[dict], boot: Boot) -> list[dict[str, Any]]:
    """Within each archetype: is the explosive HALF (high big-play share) worth more volatility premium?

    A family of up to nine within-archetype splits, so each carries a Bonferroni interval too.
    """
    out = []
    eligible = []
    for label, archs in GROUPS:
        if len(archs) != 1 or archs[0] == "K":
            continue
        sh = [(r, big_play_share(inp, r["pid"], r["lpos"])) for r in filt(base, archs)]
        sh = [(r, s) for r, s in sh if s is not None]
        if len(sh) >= 16:  # too few players to split in half otherwise (OLB has 8)
            eligible.append((label, sh))
    m = len(eligible)  # the family is the splits actually performed
    lo, hi = 100 * (0.05 / m / 2), 100 * (1 - 0.05 / m / 2)
    for label, sh in eligible:
        med = float(np.median([s for _, s in sh]))
        hi_rs = [r for r, s in sh if s > med]
        lo_rs = [r for r, s in sh if s <= med]
        pa, pb = [r["pid"] for r in hi_rs], [r["pid"] for r in lo_rs]
        d = stat_J_over_ppg(hi_rs) - stat_J_over_ppg(lo_rs)
        c = boot.diff_ci(pa, pb, stat_J_over_ppg, stat_J_over_ppg, d)
        cb = boot.diff_ci(pa, pb, stat_J_over_ppg, stat_J_over_ppg, d, lo, hi)
        d_bc = d - (c[3] or 0.0)
        out.append(
            {
                "group": label,
                "medianBigPlayShare": _r(med, 3),
                "nExplosiveHalf": len(hi_rs),
                "nStableHalf": len(lo_rs),
                "cvExplosive": _r(stat_sd_over_ppg(hi_rs), 3),
                "cvStable": _r(stat_sd_over_ppg(lo_rs), 3),
                "JoverPpgExplosive": _r(stat_J_over_ppg(hi_rs)),
                "JoverPpgStable": _r(stat_J_over_ppg(lo_rs)),
                "diff": _r(d_bc),
                "plugInDiff": _r(d),
                "ci95": [c[0], c[1]],
                "ciBonferroni": [cb[0], cb[1]],
                "bonferroniFamilySize": m,
                "ciExcludesZero95": bool(c[0] is not None and (c[0] > 0 or c[1] < 0)),
                "ciExcludesZeroBonferroni": bool(cb[0] is not None and (cb[0] > 0 or cb[1] < 0)),
            }
        )
    return out


def premium_by_tier(base: list[dict], boot: Boot, key: str) -> list[dict[str, Any]]:
    """Where the volatility premium lives: terciles of ``key`` inside each lineup family."""
    out = []
    for fam in CLASSES:
        rs = [
            r
            for r in base
            if r["cls"] == fam and r["arch"] in (IDP_ARCHS + OFF4) and np.isfinite(r[key])
        ]
        rs.sort(key=lambda r: -r[key])
        if len(rs) < 18:
            continue
        k = len(rs) // 3
        tiers = {
            "top third": rs[:k],
            "middle third": rs[k : len(rs) - k],
            "bottom third": rs[len(rs) - k :],
        }
        row = {"family": fam, "n": len(rs), "orderedBy": key, "tiers": []}
        for name, t in tiers.items():
            row["tiers"].append(
                {
                    "tier": name,
                    "n": len(t),
                    "range": [_r(min(r[key] for r in t), 2), _r(max(r[key] for r in t), 2)],
                    "ppg": _r(np.mean([r["muUnc"] for r in t]), 2),
                    "J": _est(boot, t, stat_J),
                    "JoverPpg": _est(boot, t, stat_J_over_ppg),
                    "weeklySdOverPpg": _r(stat_sd_over_ppg(t), 3),
                }
            )
        out.append(row)
    return out


def library_variance_comparison(base: list[dict], shape: E.ShapeReference) -> dict[str, Any]:
    """The weekly spread the shipped best-ball model ASSUMES versus the spread measured here."""
    from src.league_intel.sim_calibration import FALLBACK_DEFAULT_CV, PointsModel

    pm = PointsModel()
    rows = []
    for fam in CLASSES_K:
        rs = [r for r in base if r["cls"] == fam]
        if len(rs) < 8:
            continue
        lib = pm.cv_for(fam) if fam != "K" else FALLBACK_DEFAULT_CV
        obs = stat_sd_over_ppg(rs)
        rows.append(
            {
                "family": fam,
                "n": len(rs),
                "libraryAssumedCv": _r(lib, 2),
                "observedCv2026": _r(obs, 3),
                "priorSeasonShapeCv": _r(shape.cv.get(f"POS_{fam}"), 3),
                "observedOverAssumed": _r(obs / lib, 2),
            }
        )
    return {
        "model": "src.league_intel.sim_calibration.PointsModel (per-position coefficient of variation; draw = max(0, N(mean, max(0.5, mean*cv))))",
        "source": pm.source,
        "note": "this checkout holds no fitted sim_points_model.json, so the documented fallback constants are what the library uses here; a box-local fitted artifact would replace them",
        "byFamily": rows,
    }


def rank_movers(base: list[dict], ranks: dict[str, Any], k: int = 6) -> dict[str, Any]:
    """The players best-ball ranking moves most relative to ppg ranking, per family."""
    out = {}
    for fam in CLASSES:
        rs = [r for r in base if r["cls"] == fam]
        if len(rs) < 12:
            continue
        rows = []
        for r in rs:
            rk = ranks[r["pid"]]
            rows.append((rk["rankPpg"] - rk["rankBestBall"], r, rk))
        rows.sort(key=lambda t: -t[0])

        def fmt(t):
            d, r, rk = t
            return {
                "name": r["name"],
                "archetype": r["arch"],
                "ppg": _r(r["muUnc"], 2),
                "cv": _r(r["cvCond"], 2),
                "rankPpg": rk["rankPpg"],
                "rankBestBall": rk["rankBestBall"],
                "ranksGained": _r(d, 1),
            }

        out[fam] = {
            "familySize": len(rs),
            "gainers": [fmt(t) for t in rows[:k]],
            "losers": [fmt(t) for t in rows[-k:][::-1]],
        }
    return out


def short_sample_bias_2025(inp: D.Inputs) -> dict[str, Any]:
    """How much does a 6-game weekly spread understate the full-season spread? (2025, same players)"""
    out = {}
    per: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    for pid, ps in inp.season25.items():
        arch, lpos = _arch_of(inp, pid)
        full = ps.played_points()
        first = [
            ps.weeks[w].points
            for w in range(1, 7)
            if w in ps.weeks and ps.weeks[w].status == "played"
        ]
        if len(full) < 14 or len(first) < 5:
            continue
        a, b = np.array(full), np.array(first)
        if a.mean() <= 0.5 or b.mean() <= 0.5:
            continue
        per[arch].append(
            (b.std(ddof=1), a.std(ddof=1), b.std(ddof=1) / b.mean(), a.std(ddof=1) / a.mean())
        )
    for label, archs in GROUPS:
        if label.startswith(("DL ", "LB ", "DB ", "IDP", "Offense")):
            continue
        rows = [t for a in archs for t in per.get(a, [])]
        if len(rows) < 10:
            continue
        arr = np.array(rows)
        out[label] = {
            "players": len(rows),
            "medianSdRatioFirst6OverFullSeason": _r(float(np.median(arr[:, 0] / arr[:, 1])), 3),
            "medianCvRatioFirst6OverFullSeason": _r(float(np.median(arr[:, 2] / arr[:, 3])), 3),
            "meanSdRatio": _r(float(np.mean(arr[:, 0] / arr[:, 1])), 3),
        }
    return out


def headline_block(prem: list[dict], base: list[dict]) -> dict[str, Any]:
    by = {r["group"]: r for r in prem}
    pick = lambda g: by.get(g)  # noqa: E731
    out: dict[str, Any] = {"evaluated": len(base)}
    for tag, g in (("idp", "IDP (all six)"), ("offense", "Offense (QB/RB/WR/TE)")):
        r = pick(g)
        if r:
            out[tag] = {
                "n": r["n"],
                "J": r["J"],
                "JoverPpg": r["JoverPpg"],
                "JperWeeklySd": r["JperWeeklySd"],
            }
    return out


# ── assemble ─────────────────────────────────────────────────────────────────


def build_evidence(inp, cls, universes, shape, results, args) -> dict[str, Any]:
    sig_by_pid = {e.pid: e.sig for u in ("all", "all_inj") for e in universes[u].entities}
    for v in results.values():
        for r in v["rows"]:
            r["cls"] = elig_class(sig_by_pid[r["pid"]], r["lpos"])
    base = results[BASE_KEY]["rows"]
    boots_rows = [v["rows"] for v in results.values() if v["scenario"].boot is not None]
    boot = Boot(base, boots_rows)
    ranks = player_ranks(base)
    prem = premium_table(base, boot)
    ev: dict[str, Any] = {
        "schema": SCHEMA,
        "lane": "D",
        "authority": "docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md section 8 and 13 (research only; no served behaviour, flag or value changes)",
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "provenance": provenance_block(inp, args, shape),
        "population": population_block(inp, cls, universes, base),
        "fineResolution": fine_resolution(inp, base),
        "archetypeProfile": archetype_profile(inp, base),
        "varianceAssumptions": variance_assumptions(inp, shape, base),
        "volatilityPremium": prem,
        "contrasts": contrasts(base, boot),
        "profileSplit": profile_split(inp, base, boot),
        "premiumByPpgTier": premium_by_tier(base, boot, "muUnc"),
        "premiumByVolatilityTier": premium_by_tier(base, boot, "cvCond"),
        "libraryVarianceAssumption": library_variance_comparison(base, shape),
        "rankMovers": rank_movers(base, ranks),
        "rankComparison": rank_table(base, boot),
        "distributionChoice": model_comparison(results, boot, base),
        "sensitivity": sensitivity_table(results, base),
        "roleChange": role_change(results, base),
        "reliability": {
            "splitHalf2025": reliability_2025(inp),
            "yearOverYear2025to2026": yoy(inp),
            "replacementBandWinnersCurse2025": winners_curse(inp),
            "shortSampleSpreadBias2025": short_sample_bias_2025(inp),
        },
        "realizedCheck": realized_check(inp, universes["all"], base),
        "players": players_table(inp, base, results, ranks),
        "headline": headline_block(prem, base),
        "bootstrap": {
            "weekReplicates": len(boots_rows),
            "innerPlayerResamples": INNER,
            "draws": args.draws,
            "note": "levels, ratios and spreads: bias-corrected estimate with a 95% basic-bootstrap interval (plug-in and bias published beside it); rank agreements, shares and marginal levels vs replacement: plug-in with the percentile interval of the replicates; contrasts also carry a Bonferroni interval over their family",
        },
    }
    return ev
