"""Additive scoring detail on ``ProjectionObservation`` (LI scoring, batch 1).

Three optional fields — ``scoring_components``, ``uncovered_paid_keys``,
``synthetic_components`` (plus ``coverage_status``) — are populated by
``rescore_projection_record`` from the ONE scoring call that produces
``league_scored_fpg``.  Every existing consumer and serializer must be
byte-identical with them present.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.bdvm import projections as bdvm_projections
from src.bdvm.projections import ProjectionRecord
from src.bdvm.source_vocabulary import record_coverage
from src.model_registry import projection_scorecard as ps
from src.model_registry.learning_receipt import canonical_json
from src.nfl_data.synthetic_splits import RECEPTION_BAND_KEYS
from src.ros import projection_observations as po
from src.ros.projection_ensemble import combine_ensemble
from src.ros.projection_observations import ProjectionObservation, rescore_projection_record

ROOT = Path(__file__).resolve().parents[2]
CARD = json.loads(
    (ROOT / "tests/fixtures/li_scoring/dynasty_main_league_2026.json").read_text("utf-8")
)["scoring_settings"]
NEW_FIELDS = (
    "scoring_components",
    "uncovered_paid_keys",
    "synthetic_components",
    "coverage_status",
)


def _wr(**kw) -> ProjectionRecord:
    base = dict(
        source="clayProjections",
        player_key="ja'marr chase",
        position="WR",
        season=2026,
        as_of="2026-08-01",
        games=17.0,
        stat_line={
            "receptions": 105.0,
            "receiving_yards": 1400.0,
            "receiving_tds": 11.0,
            "targets": 160.0,
            "rushing_yards": 30.0,
        },
    )
    base.update(kw)
    return ProjectionRecord(**base)


def _qb() -> ProjectionRecord:
    return _wr(
        player_key="josh allen",
        position="QB",
        stat_line={
            "attempts": 560.0,
            "completions": 370.0,
            "passing_yards": 4100.0,
            "passing_tds": 30.0,
            "interceptions": 11.0,
            "rushing_yards": 520.0,
            "rushing_tds": 9.0,
            "carries": 105.0,
        },
    )


def _lb() -> ProjectionRecord:
    return _wr(
        source="idpShowProjections",
        player_key="fred warner",
        position="LB",
        stat_line={
            "def_tackles_solo": 85.0,
            "def_tackle_assists": 40.0,
            "def_sacks": 3.0,
            "def_interceptions": 1.0,
        },
    )


def _strip(obs: ProjectionObservation) -> ProjectionObservation:
    return dataclasses.replace(
        obs,
        scoring_components=(),
        uncovered_paid_keys=(),
        synthetic_components=(),
        coverage_status=None,
    )


# ── the one scoring call ──────────────────────────────────────────────────


@pytest.mark.parametrize("record", [_wr(), _qb(), _lb()], ids=["WR", "QB", "LB"])
def test_components_sum_to_league_scored_fpg_exactly(record):
    obs = rescore_projection_record(record, scoring_settings=CARD, census_source_key=record.source)
    assert obs is not None and obs.scoring_components
    total = 0.0
    for key, raw, rate, points in obs.scoring_components:
        assert isinstance(key, str) and key in CARD
        assert rate == float(CARD[key])
        assert points == raw * rate
        total += points
    assert total == obs.league_scored_fpg  # bit-exact, same order as the scorer
    # And the legacy total is unchanged by the new path.
    assert obs.league_scored_fpg == record.resolve_fpg(CARD)[0]


def test_rescore_makes_exactly_one_scoring_call(monkeypatch):
    calls = []
    real = bdvm_projections.score_stat_line_per_game_breakdown

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(bdvm_projections, "score_stat_line_per_game_breakdown", spy)
    rescore_projection_record(_wr(), scoring_settings=CARD, census_source_key="clayProjections")
    assert len(calls) == 1


def test_resolve_fpg_detailed_is_unchanged_by_the_breakdown():
    for record in (_wr(), _qb(), _lb()):
        detailed = record.resolve_fpg_detailed(CARD)
        resolved = record.resolve_fpg_breakdown(CARD)
        assert detailed == (resolved.fpg, resolved.scoring_native, resolved.unscored)


# ── uncovered keys come from the canonical coverage owner, never zero ────


@pytest.mark.parametrize("record", [_wr(), _qb(), _lb()], ids=["WR", "QB", "LB"])
def test_uncovered_keys_are_the_canonical_record_coverage(record):
    obs = rescore_projection_record(record, scoring_settings=CARD, census_source_key=record.source)
    _fpg, _native, unscored = record.resolve_fpg_detailed(CARD)
    expected = record_coverage(record, CARD, engine_unscored=unscored)
    assert obs.uncovered_paid_keys == tuple(expected.unscored_keys)
    assert obs.coverage_status == expected.status
    # dynasty_main pays the reception bands; a WR column line cannot supply them.
    if record.position == "WR":
        assert set(RECEPTION_BAND_KEYS) <= set(obs.uncovered_paid_keys)
        assert obs.coverage_status == "partial"
    for key in obs.uncovered_paid_keys:
        assert float(CARD[key]) != 0.0
        assert all(c[0] != key for c in obs.scoring_components)  # never scored as 0


def test_source_scored_points_are_unverifiable_not_complete():
    rec = ProjectionRecord(
        source="idpShowProjections",
        player_key="fred warner",
        position="LB",
        season=2026,
        as_of="2026-08-01",
        games=17.0,
        fpg=12.0,
        scoring_native=True,
    )
    obs = rescore_projection_record(rec, scoring_settings=CARD, census_source_key=rec.source)
    assert obs.scoring_components == ()
    assert obs.uncovered_paid_keys == ()
    assert obs.coverage_status == "unverifiable"  # empty list does NOT read as complete
    assert obs.league_scored_fpg == 12.0


def test_unreadable_card_rate_is_reported_not_zero():
    card = dict(CARD)
    card["rec_td"] = "six"  # unreadable rate: the engine coerces it to 0
    obs = rescore_projection_record(
        _wr(), scoring_settings=card, census_source_key="clayProjections"
    )
    assert obs is not None
    assert "rec_td" in obs.uncovered_paid_keys
    assert obs.coverage_status in ("partial", "unverifiable")
    # The total is the existing engine's, untouched (batch 1 moves no value).
    assert obs.league_scored_fpg == _wr().resolve_fpg(card)[0]


def test_a_readable_card_gets_no_extra_uncovered_keys():
    obs = rescore_projection_record(
        _qb(), scoring_settings=CARD, census_source_key="clayProjections"
    )
    _f, _n, unscored = _qb().resolve_fpg_detailed(CARD)
    assert obs.uncovered_paid_keys == tuple(
        record_coverage(_qb(), CARD, engine_unscored=unscored).unscored_keys
    )


# ── synthetic band label: a label, never a value change ──────────────────


def _sleeper_banded(rec: float = 6.0) -> dict[str, float]:
    from src.nfl_data.synthetic_splits import SLEEPER_RECEPTION_BAND_SHARES

    line = {k: round(v * rec, 2) for k, v in SLEEPER_RECEPTION_BAND_SHARES.items()}
    line.update({"rec": rec, "receptions": rec, "receiving_yards": 70.0})
    return line


def test_synthetic_band_split_is_labelled_and_moves_no_points():
    rec = _wr(stat_line=_sleeper_banded(), stat_basis="per_game")
    obs = rescore_projection_record(rec, scoring_settings=CARD, census_source_key="clayProjections")
    assert obs.synthetic_components == RECEPTION_BAND_KEYS
    assert obs.league_scored_fpg == rec.resolve_fpg(CARD)[0]
    plain = _wr(
        stat_line={"receptions": 6.0, "receiving_yards": 70.0, "rec": 6.0}, stat_basis="per_game"
    )
    plain_obs = rescore_projection_record(
        plain, scoring_settings=CARD, census_source_key="clayProjections"
    )
    assert plain_obs.synthetic_components == ()


def test_realized_shaped_bands_are_not_labelled_synthetic():
    line = {
        "rec": 5.0,
        "receptions": 5.0,
        "receiving_yards": 60.0,
        "rec_0_4": 1.0,
        "rec_5_9": 2.0,
        "rec_10_19": 2.0,
    }
    rec = _wr(stat_line=line, stat_basis="per_game")
    obs = rescore_projection_record(rec, scoring_settings=CARD, census_source_key="clayProjections")
    assert obs.synthetic_components == ()


# ── byte identity for every existing consumer ────────────────────────────


def test_legacy_keyword_construction_defaults_the_new_fields():
    """game_day_estimates and to_projection_observation build with the
    legacy keyword set; the new fields must default, not be required."""
    obs = ProjectionObservation(
        census_source_key="sleeperWeeklyProjections",
        provider_family="rotowire",
        evidence_class="PROJECTION_MODEL",
        horizon="WEEKLY",
        access_posture="x",
        player_key="player:1",
        position="WR",
        season=2026,
        as_of="2026-10-01",
        games=1.0,
        league_scored_fpg=10.0,
        league_scored_is_native=False,
        native_fpg=None,
        native_is_scoring_native=False,
        stat_line_available=True,
        proj_high=None,
        proj_low=None,
        is_proxy=False,
    )
    assert (obs.scoring_components, obs.uncovered_paid_keys, obs.synthetic_components) == (
        (),
        (),
        (),
    )
    assert obs.coverage_status is None
    legacy = [f.name for f in dataclasses.fields(ProjectionObservation)][: -len(NEW_FIELDS)]
    assert [f.name for f in dataclasses.fields(ProjectionObservation)][-len(NEW_FIELDS) :] == list(
        NEW_FIELDS
    )
    assert "league_scored_fpg" in legacy


def test_combine_ensemble_is_identical_with_the_new_fields_present():
    # The real n=2 case: an IDP defender covered by both live families.
    idp_show = rescore_projection_record(
        _lb(), scoring_settings=CARD, census_source_key="idpShowProjections"
    )
    clay = rescore_projection_record(
        dataclasses.replace(_lb(), source="clayProjections"),
        scoring_settings=CARD,
        census_source_key="clayProjections",
    )
    observations = [idp_show, clay]
    assert any(o.scoring_components for o in observations)
    for method in ("equal_family_mean", "median"):
        with_fields = combine_ensemble(observations, method=method)
        stripped = combine_ensemble([_strip(o) for o in observations], method=method)
        assert with_fields == stripped
        assert repr(with_fields) == repr(stripped)


def _snapshot(as_of: str) -> ps.SeasonSnapshot:
    records = []
    for key in ("a", "b"):
        records.append(dataclasses.replace(_wr(), player_key=key, as_of=as_of, season=2026))
        records.append(
            ProjectionRecord(
                source="idpShowProjections",
                player_key=key,
                position="WR",
                season=2026,
                as_of=as_of,
                games=17.0,
                fpg=12.0,
                scoring_native=True,
            )
        )
    return ps.SeasonSnapshot(as_of=as_of, records=records, source_key=f"data/bdvm/p_{as_of}.json")


def _realized() -> ps.RealizedSeason:
    first = datetime(2026, 9, 10, 0, 15, tzinfo=timezone.utc)
    return ps.RealizedSeason(
        season=2026,
        known_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        points={"a": [(3, 10.0)], "b": [(3, 14.0)]},
        week_first_kickoff={w: first + timedelta(days=7 * (w - 1)) for w in range(1, 5)},
        source_key="nflverse-2026",
        final_weeks=frozenset((1, 2, 3, 4)),
    )


def test_projection_scorecard_results_are_identical_with_the_new_fields(monkeypatch):
    def run():
        return ps.evaluate(
            league_key="dynasty_main",
            scoring=CARD,
            scoring_fingerprint="sf",
            season_snapshots=[_snapshot("2026-08-01")],
            realized_season=_realized(),
        )

    with_fields = run()
    assert with_fields.pairs  # non-vacuous
    real = po.rescore_projection_record

    def stripped(*a, **k):
        obs = real(*a, **k)
        return None if obs is None else _strip(obs)

    monkeypatch.setattr(ps, "rescore_projection_record", stripped)
    without = run()
    assert canonical_json(with_fields.summary) == canonical_json(without.summary)
    assert with_fields.pairs == without.pairs
    ra = [
        r.content_hash() for r in ps.receipts(with_fields, code_sha="c", scoring_fingerprint="sf")
    ]
    rb = [r.content_hash() for r in ps.receipts(without, code_sha="c", scoring_fingerprint="sf")]
    assert ra == rb


CONSUMERS = (
    "src/ros/projection_observations.py",
    "src/ros/projection_ensemble.py",
    "src/ros/game_day_estimates.py",
    "src/ros/sleeper_weekly_projections.py",
    "src/ros/keyed_weekly_projections.py",
    "src/model_registry/projection_scorecard.py",
)


@pytest.mark.parametrize("path", CONSUMERS)
def test_no_consumer_serializes_observations_generically(path):
    """New fields could only reach a payload through a generic dataclass
    serializer; none of the observation's consumers uses one.  If one is
    added, it must use an explicit field list (and this test is updated
    deliberately)."""
    tree = ast.parse((ROOT / path).read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            assert name not in {"asdict", "astuple", "vars"}, (path, name)


def test_realized_points_components_are_additive_and_never_serialized():
    """The one plumbing change outside this lane's new modules: the
    canonical realized engine now carries its scorer's components.  It must
    not change equality, repr or the served ``to_dict``."""
    from src.nfl_data.realized_points import compute_weekly_points

    row = {"season": 2025, "week": 3, "receptions": 6, "receiving_yards": 80, "position": "WR"}
    rp = compute_weekly_points(row, dict(CARD), position="WR")
    assert rp.components
    assert "components" not in rp.to_dict()
    assert "components" not in repr(rp)
    assert dataclasses.replace(rp, components=()) == rp
    total = 0.0
    for _key, _raw, _rate, pts in rp.components:
        total += pts
    assert total == rp.fantasy_points
