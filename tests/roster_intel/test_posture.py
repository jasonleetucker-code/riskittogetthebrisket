"""C7-POST-01 / #840 — Competitive Posture, the ONE strategic owner.

Binding record: ``docs/trade/ANALYZE_TRADE_COMPETITIVE_POSTURE_ADDENDUM_2026-08-14.md``.
What is pinned here:

* posture CONSUMES the competitive window (no second competitiveness or age
  axis) and is a continuous affinity model — no single hard threshold flips a
  team while its neighbour stays put;
* season timing changes the meaning of the same window (the deadline
  amplifies, post-deadline damps) — the addendum's "25% before Week 1 is not
  25% at the deadline";
* own-pick ownership moves REBUILD mass to RETOOL when losing improves no pick
  the team holds, and no draft-order claim is ever made;
* the playoff simulation is consumed only when it is current and can rank the
  league; otherwise the structural proxy is used and SAID;
* the published numbers are labelled uncalibrated affinities, never
  probabilities, and posture never counts as a vote;
* real league states (committed archive) all classify, with the distribution
  reported rather than asserted.
"""

from __future__ import annotations

import json
import math

import pytest

from src.roster_intel import posture as P
from src.roster_intel.window import CompetitiveWindow, WindowInputs


def _window(probs: dict[str, float], *, source: str = "lineupScoreRank") -> CompetitiveWindow:
    total = sum(probs.values())
    norm = {k: v / total for k, v in probs.items()}
    full = {s: norm.get(s, 0.0) for s in P.COMPETITIVE_STATES}
    best = max(full, key=lambda k: full[k])
    return CompetitiveWindow(
        probabilities=full,
        inputs=WindowInputs(0.5, 0.5, source, 5),
        most_likely=best,
    )


def _settings(**kw):
    base = {
        "leg": 4,
        "last_scored_leg": 3,
        "trade_deadline": 13,
        "playoff_week_start": 15,
        "start_week": 1,
    }
    base.update(kw)
    return base


# ── Season timing ────────────────────────────────────────────────────────


class TestSeasonTiming:
    def test_phases_from_the_hosts_own_settings(self):
        assert P.season_timing(_settings(leg=1, last_scored_leg=0)).phase == "preseason"
        assert P.season_timing(_settings()).phase == "regular_season"
        assert P.season_timing(_settings(leg=14, last_scored_leg=13)).phase == "post_deadline"
        assert P.season_timing(_settings(leg=16, last_scored_leg=15)).phase == "postseason"

    def test_unknown_when_the_host_publishes_no_week(self):
        t = P.season_timing({"trade_deadline": 13})
        assert t.phase == "unknown"
        assert t.notes, "unknown timing must say why, never pass as neutral silently"

    def test_the_deadline_amplifies_and_post_deadline_damps(self):
        early = P.season_timing(_settings(leg=2, last_scored_leg=1))
        late = P.season_timing(_settings(leg=13, last_scored_leg=12))
        after = P.season_timing(_settings(leg=14, last_scored_leg=13))
        assert early.multiplier < late.multiplier
        assert after.multiplier < early.multiplier

    def test_no_deadline_uses_the_regular_season_end(self):
        t = P.season_timing(_settings(trade_deadline=0, leg=10, last_scored_leg=9))
        assert t.phase == "regular_season"
        assert any("no trade deadline" in n for n in t.notes)


# ── Classification ───────────────────────────────────────────────────────


class TestClassification:
    def test_affinities_sum_to_one_and_are_labelled_uncalibrated(self):
        r = P.classify_posture(
            _window({"playoff_contender": 1, "retool": 1}),
            P.season_timing(_settings()),
            owns_own_first=True,
        )
        assert math.isclose(sum(r.affinities.values()), 1.0, abs_tol=1e-9)
        d = r.to_dict()
        assert d["calibration"]["state"] == "uncalibrated"
        assert "probabilities" not in d
        assert d["countedAsVote"] is False
        assert d["draftOrder"]["state"] == "unmodeled"

    def test_no_hard_threshold_small_moves_make_small_changes(self):
        timing = P.season_timing(_settings())
        prev = None
        for i in range(0, 101):
            c = i / 100
            r = P.classify_posture(
                _window({"championship_contender": c + 1e-9, "rebuild": 1 - c + 1e-9}),
                timing,
                owns_own_first=True,
            )
            if prev is not None:
                for k in P.POSTURES:
                    assert abs(r.affinities[k] - prev.affinities[k]) < 0.25, (c, k)
            prev = r

    def test_extremes_classify_as_expected(self):
        timing = P.season_timing(_settings())
        push = P.classify_posture(
            _window({"championship_contender": 1}), timing, owns_own_first=True
        )
        rebuild = P.classify_posture(_window({"rebuild": 1}), timing, owns_own_first=True)
        assert push.posture == "PUSH"
        assert rebuild.posture == "REBUILD"

    def test_balanced_evidence_is_hold_or_low_confidence(self):
        r = P.classify_posture(
            _window({s: 1 for s in P.COMPETITIVE_STATES}),
            P.season_timing(_settings()),
            owns_own_first=True,
        )
        assert r.posture == "HOLD" or r.confidence == "LOW"


# ── The addendum's twelve validation cases (posture side) ────────────────
#
# Cases 1, 2, 7-10 are decision cases and live in
# ``tests/trade/test_analyze_posture_weighting.py``; the posture-owner half of
# each is here.


class TestAddendumCases:
    def test_case3_bubble_team_commits_at_the_deadline(self):
        """Case 3 + case 12: the SAME window reads HOLD early and commits late."""
        w = _window({"playoff_contender": 0.7, "retool": 0.3})
        early = P.classify_posture(
            w, P.season_timing(_settings(leg=1, last_scored_leg=0)), owns_own_first=True
        )
        deadline = P.classify_posture(
            w, P.season_timing(_settings(leg=13, last_scored_leg=12)), owns_own_first=True
        )
        assert early.posture == "HOLD"
        assert deadline.posture != "HOLD"
        assert abs(deadline.lean) > abs(early.lean)

    def test_case4_and_5_own_first_ownership_matters(self):
        w = _window({"rebuild": 0.7, "productive_struggle": 0.3})
        timing = P.season_timing(_settings())
        owns = P.classify_posture(w, timing, owns_own_first=True)
        traded = P.classify_posture(w, timing, owns_own_first=False)
        assert traded.affinities["REBUILD"] < owns.affinities["REBUILD"]
        assert traded.affinities["RETOOL"] > owns.affinities["RETOOL"]
        assert any("own next first" in n for n in traded.notes)

    def test_case6_draft_order_is_never_modelled_or_credited(self):
        """Max PF vs record: neither is modelled, and every payload says so."""
        r = P.classify_posture(
            _window({"rebuild": 1}), P.season_timing(_settings()), owns_own_first=True
        )
        assert r.to_dict()["draftOrder"]["state"] == "unmodeled"

    def test_case12_post_deadline_damps_current_season_urgency(self):
        w = _window({"championship_contender": 0.6, "playoff_contender": 0.4})
        reg = P.classify_posture(w, P.season_timing(_settings()), owns_own_first=True)
        post = P.classify_posture(
            w, P.season_timing(_settings(leg=14, last_scored_leg=13)), owns_own_first=True
        )
        assert abs(post.lean) < abs(reg.lean)


# ── Playoff-sim input ────────────────────────────────────────────────────


class TestOddsInput:
    def _write(self, tmp_path, monkeypatch, *, league="L", week=3, champ=None):
        rows = [
            {"ownerId": f"o{i}", "championshipOdds": c, "playoffOdds": 0.5}
            for i, c in enumerate(champ or [0.4, 0.3, 0.2, 0.1])
        ]
        play = tmp_path / "x_playoff.json"
        play.write_text(json.dumps({"computedAt": "t", "playoffOdds": rows}), encoding="utf-8")
        (tmp_path / "x_playoff.identity.json").write_text(
            json.dumps({"leagueKey": league, "lastScoredWeek": week}), encoding="utf-8"
        )
        import src.ros.scrape as scrape

        monkeypatch.setattr(scrape, "playoff_sim_path", lambda k, d: play)
        return rows

    def test_fresh_only_when_league_and_week_match(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch)
        rows, meta = P.load_playoff_odds("L", last_scored_week=3, default_key="L")
        assert meta["state"] == "fresh" and rows
        rows, meta = P.load_playoff_odds("L", last_scored_week=4, default_key="L")
        assert rows is None and meta["state"] == "stale"
        rows, meta = P.load_playoff_odds("OTHER", last_scored_week=3, default_key="L")
        assert rows is None and meta["reason"] == "league_mismatch"

    def test_unverifiable_week_is_stale_not_fresh(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch)
        rows, meta = P.load_playoff_odds("L", last_scored_week=None, default_key="L")
        assert rows is None and meta["state"] == "stale"

    def test_degenerate_odds_cannot_rank_the_league(self):
        ok, tie = P._odds_discriminate(
            [{"ownerId": f"o{i}", "championshipOdds": 0.0} for i in range(8)]
            + [{"ownerId": "x", "championshipOdds": 0.9}]
        )
        assert not ok and tie == 8
        ok, _ = P._odds_discriminate(
            [{"ownerId": f"o{i}", "championshipOdds": i / 10} for i in range(9)]
        )
        assert ok


# ── Own-first detection ──────────────────────────────────────────────────


def test_owns_own_first_reads_the_league_inventory():
    teams = [
        {
            "roster_id": 1,
            "pickDetails": [
                {"season": 2027, "round": 1, "fromRosterId": 1, "assetId": "pick:L:2027:r1:o1"},
            ],
        },
        {
            "roster_id": 2,
            "pickDetails": [
                {"season": 2027, "round": 1, "fromRosterId": 1, "assetId": "pick:L:2027:r1:o1"},
                {"season": 2028, "round": 1, "fromRosterId": 2, "assetId": "pick:L:2028:r1:o2"},
            ],
        },
    ]
    owns, year, aid = P._owns_own_first(teams[0], teams)
    assert (owns, year, aid) == (True, 2027, "pick:L:2027:r1:o1")
    owns, year, _ = P._owns_own_first(teams[1], teams)
    assert owns is False and year == 2027
    # No inventory published -> UNKNOWN, never "does not own".
    assert P._owns_own_first({"roster_id": 3}, teams)[0] is None


# ── Real league states (committed archive) ──────────────────────────────


@pytest.fixture(scope="module")
def real_contract():
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape in exports/archive")
    from src.api.data_contract import build_api_data_contract

    return build_api_data_contract(payload)


def test_every_real_team_classifies_with_components(real_contract):
    out = P.build_league_postures(real_contract, league_key="dynasty_main")
    if not out.get("available"):
        pytest.skip(f"real contract has no resolvable lineup: {out.get('unavailableReason')}")
    teams = out["teams"]
    assert len(teams) >= 2
    for entry in teams.values():
        assert entry["posture"] in P.POSTURES
        assert entry["confidence"] in ("HIGH", "MEDIUM", "LOW")
        assert math.isclose(sum(entry["affinities"].values()), 1.0, abs_tol=1e-3)
        comp = entry["components"]
        assert comp["competitivenessSource"] in ("championshipOdds", "lineupScoreRank")
        assert comp["timing"]["source"] == "sleeper.leagueSettings"
    # Posture is evidence-derived, not one label for everybody.
    assert len({e["posture"] for e in teams.values()}) >= 2


def test_marginal_is_measured_on_one_basis(real_contract):
    from src.api.data_contract import contract_roster_pools

    pools, _slots, _ = contract_roster_pools(real_contract)
    if len(pools) < 2:
        pytest.skip("need two rosters")
    a, b = list(pools)[:2]
    give = [p.player_id for p in pools[a] if p.ros_value][:1]
    take = [p.player_id for p in pools[b] if p.ros_value][:1]
    m = P.posture_marginal(real_contract, a, players_in=take, players_out=give)
    assert m["available"] is True
    assert m["basis"] == "structural_lineup_rank"
    assert m["countedAsVote"] is False
    # Identity check: a no-op trade moves nothing.
    noop = P.posture_marginal(real_contract, a, players_in=[], players_out=[])
    assert noop["leanDelta"] == 0.0
    assert noop["postureBefore"] == noop["postureAfter"]
