"""CW-40 P1 re-audit, batch t1 -- findings that remain OPEN / PARTIAL /
need an owner decision on current main.

Each has a passing CHARACTERIZATION test pinning today's behaviour and, where
the intended behaviour is already stated by a controlling record, a
``strict`` xfail asserting it.  Flip the xfail when the repair lands.

    W09-F005  (PARTIAL)  Monte Carlo: no sampling-error / seed disclosure
    W10-F004  (OPEN)     vendor rookie dollars stretched over each vendor's own row count
    W13-F002  (OPEN)     BDVM roster capitals exclude every draft pick
    W27-F003  (REQUIRES_OWNER_DECISION)  /angle never offers IDP in counter-packages

Record: docs/audits/remediation_2026-11-06/CW40_P1_BATCH_t1.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

import server
from src.bdvm.params import load_param_set
from src.bdvm.roster import analyze_rosters
from src.trade import monte_carlo
from tests.archive_fixtures import newest_complete_contract
from tests.bdvm.test_roster import build_fixture

REPO = Path(__file__).resolve().parents[2]
BUDGET = 1200


# ------------------------------------------------------------------ W09-F005


def _result_dict() -> dict:
    a = monte_carlo.build_trade_player(
        {"name": "A", "team": "X", "pos": "QB", "rankDerivedValue": 8000}
    )
    b = monte_carlo.build_trade_player(
        {"name": "B", "team": "Y", "pos": "QB", "rankDerivedValue": 7900}
    )
    return monte_carlo.simulate_trade([a], [b], n_sims=2000, seed=11).to_dict()


def test_w09_f005_characterization_nsims_reported_but_no_sampling_error():
    out = _result_dict()
    assert out["nSims"] == 2000
    assert not [k for k in out if "stderr" in k.lower() or "standarderror" in k.lower()]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W09-F005 open: the result carries no Monte Carlo sampling-error / "
    "convergence diagnostic (seed echo, standard error of winProbA)",
)
def test_w09_f005_result_discloses_its_own_sampling_error():
    out = _result_dict()
    assert [k for k in out if "stderr" in k.lower() or "standarderror" in k.lower()]


# ------------------------------------------------------------------ W10-F004


def _pool_where_ktc_agrees_on_the_first(n_vendor: int) -> list[dict]:
    pool = []
    for i in range(72):
        v = 9000.0 * (0.955**i)
        pool.append(
            {
                "name": f"Rookie {i:02d}",
                "pos": "WR",
                "value": v,
                # The vendor ranks the SAME rookies with the SAME values, but
                # only the first ``n_vendor`` of them.
                "ktcRaw": v if i < n_vendor else None,
                "idpRaw": None,
            }
        )
    return pool


def test_w10_f004_characterization_partial_vendor_list_is_stretched_to_the_full_pool():
    pool = _pool_where_ktc_agrees_on_the_first(45)
    ktc, _idp = server._vendor_dollars_for_rookies(pool, BUDGET)
    assert len(ktc) == 45
    assert sum(ktc.values()) == pytest.approx(BUDGET, abs=1.0)  # 45 rows share $1200


def test_w10_f004_characterization_on_the_archived_board_ktc_overrates_most_covered_rookies():
    contract, _ = newest_complete_contract()
    if contract is None:
        pytest.skip("no complete archived board")
    prior = server.latest_contract_data
    server.latest_contract_data = contract
    try:
        pool = server._our_rookie_pool(72)
    finally:
        server.latest_contract_data = prior
    if len(pool) != 72:
        pytest.skip("archived board has no full 72-rookie class")
    covered = [r for r in pool if r["ktcRaw"]]
    if not 20 <= len(covered) < 72:
        pytest.skip("KTC covers all or almost none of the class on this board")
    ours = dict(
        zip(
            (r["name"].lower() for r in pool),
            server._rookie_dollars_from_values([r["value"] for r in pool], BUDGET),
        )
    )
    ktc, _ = server._vendor_dollars_for_rookies(pool, BUDGET)
    over = sum(1 for k, d in ktc.items() if d > ours[k])
    under = sum(1 for k, d in ktc.items() if d < ours[k])
    assert over > 2 * under, (over, under)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W10-F004 open: a vendor that agrees with our board on every rookie it covers "
    "still shows a positive 'vendor overrates us' gap, because its partial list is "
    "normalised to the same $1200 as our full 72",
)
def test_w10_f004_a_fully_agreeing_partial_vendor_shows_no_gap():
    pool = _pool_where_ktc_agrees_on_the_first(45)
    ours = dict(
        zip(
            (r["name"].lower() for r in pool),
            server._rookie_dollars_from_values([r["value"] for r in pool], BUDGET),
        )
    )
    ktc, _ = server._vendor_dollars_for_rookies(pool, BUDGET)
    worst = max(abs(d - ours[k]) for k, d in ktc.items())
    assert worst <= 1.0, worst


# ------------------------------------------------------------------ W13-F002

_PARAMS = load_param_set("params_v1")


def _young_team():
    payload, contract, meta = build_fixture()
    out = analyze_rosters(payload, contract, _PARAMS, league_cfg_meta=meta)
    return {r["name"]: r for r in out["rosters"]}["YoungTeam"]


def test_w13_f002_characterization_capitals_are_player_only_and_picks_are_a_count():
    y = _young_team()
    assert y["pickCount"] == 2
    # y1..y4 rebuilder values 9000 + 7500 + 6000 + 1200: the two picks add nothing.
    assert y["capitals"]["rebuilder"] == 23700.0
    assert not [k for k in y if "pickcapital" in k.lower()]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W13-F002 open: src/bdvm/roster.py documents 'pick capital' but the payload "
    "has none; strategy capitals / direction exclude every draft pick",
)
def test_w13_f002_a_roster_holding_picks_reports_pick_capital():
    y = _young_team()
    assert [k for k in y if "pickcapital" in k.lower()]


# ------------------------------------------------------------------ W27-F003


def test_w27_f003_characterization_angle_page_never_sends_include_idp_and_engine_defaults_off():
    page = (REPO / "frontend/app/angle/page.jsx").read_text(encoding="utf-8")
    assert "includeIdp" not in page
    src = (REPO / "src/trade/angle.py").read_text(encoding="utf-8")
    assert src.count("include_idp: bool = False") >= 2
    srv = (REPO / "server.py").read_text(encoding="utf-8")
    assert 'body.get("includeIdp", False)' in srv
