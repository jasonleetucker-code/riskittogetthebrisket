"""Distributions + correlation: marginals preserved, dependence as declared, nothing invented."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

from src.dfs import correlation, distributions
from src.dfs.metrics import spearman


@dataclass
class A:
    player_id: str
    positions: list[str]
    team: str = "AA"
    opponent: str | None = "BB"
    game: str | None = "AA@BB"
    projection: float | None = 20.0
    distribution: dict | None = None
    group_key: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def identity(self):
        return self.group_key or self.player_id


def _sd(v):
    return {"sd": v, "quantiles": {}, "unassigned": {}}


def test_no_range_means_no_distribution_unless_priors_are_explicitly_allowed():
    a = A("1", ["WR"])
    assert distributions.build(a, "nfl") is None
    d = distributions.build(a, "nfl", allow_priors=True)
    assert d.family == "prior" and d.uncalibrated and d.sd == pytest.approx(20.0 * 0.65)
    assert distributions.build(A("2", ["F"]), "mma", allow_priors=True) is None  # no MMA prior
    assert distributions.build(A("3", ["WR"], projection=None), "nfl", allow_priors=True) is None


def test_quantile_marginal_interpolates_and_bounds_its_tails():
    d = distributions.build(
        A("1", ["WR"], distribution={"sd": None, "quantiles": {"0.10": 5, "0.50": 14, "0.90": 30}}),
        "nfl",
    )
    assert d.inverse_cdf(0.5) == 14 and d.inverse_cdf(0.30) == pytest.approx(9.5)
    assert d.inverse_cdf(0.9999) <= 30 + (30 - 14)  # one outer-segment width at most
    assert d.inverse_cdf(0.0001) >= 5 - (14 - 5)
    u = np.array([0.0001, 0.3, 0.5, 0.9999])
    assert list(distributions._quantile_inverse(d, u)) == pytest.approx(
        [d.inverse_cdf(x) for x in u]
    )


def test_copula_preserves_marginals_and_recovers_the_declared_dependence():
    qb = A("qb", ["QB"], projection=22.0, distribution=_sd(7.0))
    wr = A("wr", ["WR"], projection=15.0, distribution=_sd(8.0))
    dst = A("dst", ["DST"], team="BB", opponent="AA", projection=7.0, distribution=_sd(5.0))
    ds = [distributions.build(x, "nfl") for x in (qb, wr, dst)]
    corr = correlation.pairs([qb, wr, dst], "nfl")["pairs"]
    out = distributions.sample(ds, corr, 20_000, seed=11)
    pts = out["points"]
    assert pts[:, 0].mean() == pytest.approx(22.0, abs=0.2) and pts[:, 1].std() == pytest.approx(
        8.0, abs=0.2
    )
    rho_qb_wr = np.corrcoef(pts[:, 0], pts[:, 1])[0, 1]
    rho_qb_dst = np.corrcoef(pts[:, 0], pts[:, 2])[0, 1]
    assert rho_qb_wr == pytest.approx(0.30, abs=0.03) and rho_qb_dst == pytest.approx(
        -0.20, abs=0.03
    )
    again = distributions.sample(ds, corr, 20_000, seed=11)
    assert np.array_equal(pts, again["points"])  # seeded: identical


def test_rows_of_one_athlete_share_a_draw_and_bounds_are_enforced():
    cpt = A("cpt", ["QB"], distribution=_sd(6.0), group_key="joe")
    flex = A("flex", ["QB"], distribution=_sd(6.0), group_key="joe")
    ds = [distributions.build(x, "nfl") for x in (cpt, flex)]
    pts = distributions.sample(ds, {}, 500, seed=1)["points"]
    assert np.array_equal(pts[:, 0], pts[:, 1])
    with pytest.raises(ValueError):
        distributions.sample(ds, {}, distributions.MAX_SIMS + 1, seed=1)


def test_inconsistent_priors_are_repaired_to_a_valid_correlation_and_reported():
    x, y, z = (A(i, ["WR"], distribution=_sd(3.0)) for i in "xyz")
    ds = [distributions.build(a, "nfl") for a in (x, y, z)]
    bad = {("x", "y"): 0.9, ("y", "z"): 0.9, ("x", "z"): -0.9}  # impossible together
    out = distributions.sample(ds, bad, 2000, seed=3)
    assert out["correlationRepaired"] is True
    assert np.all(np.isfinite(out["points"]))


def test_sport_modules_encode_the_declared_directions():
    qb, wr = A("qb", ["QB"]), A("wr", ["WR"])
    rb1, rb2 = A("rb1", ["RB"]), A("rb2", ["RB"])
    opp_wr = A("owr", ["WR"], team="BB", opponent="AA")
    dst = A("dst", ["DST"], team="BB", opponent="AA")
    p = correlation.pairs([qb, wr, rb1, rb2, opp_wr, dst], "nfl")["pairs"]
    get = lambda a, b: p.get((a, b), p.get((b, a), 0.0))  # noqa: E731
    assert (
        get("qb", "wr") > 0
        and get("rb1", "rb2") < 0
        and get("qb", "owr") > 0
        and get("qb", "dst") < 0
    )
    f1 = A("f1", ["F"], team="X", opponent="Y", game="X@Y")
    f2 = A("f2", ["F"], team="Y", opponent="X", game="X@Y")
    f3 = A("f3", ["F"], team="Z", opponent="W", game="Z@W")
    m = correlation.pairs([f1, f2, f3], "mma")["pairs"]
    assert m == {("f1", "f2"): -0.60}
    none = correlation.pairs([qb, wr], "cricket")
    assert none["pairs"] == {} and none["model"] == "independent"


def test_sampled_rank_order_tracks_forecasts():
    ds = [
        distributions.build(A(str(i), ["WR"], projection=5.0 + 3 * i, distribution=_sd(2.0)), "nfl")
        for i in range(8)
    ]
    pts = distributions.sample(ds, {}, 4000, seed=5)["points"]
    assert spearman([d.mean for d in ds], list(pts.mean(axis=0))) == 1.0
