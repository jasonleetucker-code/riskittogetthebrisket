"""Batch G — adversarial dataset: every bad input fails closed, explicitly.

``docs/draft/DRAFT_VALUATION_WORKSTREAM.md`` → Batch G.  Each case below
feeds the canonical owner a broken or hostile input and requires an
EXPLICIT state (a refusal reason, ``NOT_READY``, ``unavailable``, the SAME
year's ``last_known_good``, or a refused board with its error code) — never
$0, never another year's curve, never a silently different number.

Cases: ties, missing rookies, fewer than 72 rookies, duplicate names, a
rising value sequence, a stale or unknown class year, a malformed workbook,
a missing spine, a traded pick with unknown ownership, a refused board, and
the stale-while-revalidate boundaries.

Where a case has a well-defined answer instead of a refusal (ties, a rising
input to the formula itself), the answer is pinned against the independent
Batch A transcription rather than against production's own output.
"""

from __future__ import annotations

import json
import random
import shutil
import time
from decimal import Decimal
from fractions import Fraction

import pytest

from src.api import draft_capital_classes as dcc
from src.draft.rookie_auction import generation as gen
from src.draft.rookie_auction import published
from src.draft.rookie_auction.apportion import apportion_whole_dollars
from src.draft.rookie_auction.class_snapshot import (
    STATUS_COMPLETE,
    STATUS_NOT_READY,
    build_class_candidate,
)
from src.draft.rookie_auction.curve import (
    CurveInputError,
    compute_curve,
    whole_dollar_constraints,
)
from src.draft.rookie_auction.published import REPO_STORE, CandidateFailure
from src.draft.rookie_auction.snapshots import CONFIG_DIR, SnapshotIntegrityError
from src.identity.pick_lifecycle import ClassLifecycle
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation import reference_workbook_formulas as ref

LEAGUE = "dynasty_main"
FROZEN = [r["B"] for r in wb.rows()]
SPINE = [[r[c] for r in wb.rows()] for c in "FGH"]


def _no_zero_dollars(obj) -> bool:
    """True when no published dollar field anywhere in ``obj`` is a zero."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in {"dollarValue", "auctionDollars", "adjustedDollarValue"} and v == 0:
                return False
            if not _no_zero_dollars(v):
                return False
    elif isinstance(obj, list):
        return all(_no_zero_dollars(v) for v in obj)
    return True


@pytest.fixture()
def stores(tmp_path):
    """The repo's 2027 / 2028 / 2029 records in a private store, plus an empty one."""
    repo = tmp_path / "repo"
    for year in ("2027", "2028", "2029"):
        shutil.copytree(REPO_STORE / LEAGUE / year, repo / LEAGUE / year)
    return {"seeded": [repo], "empty": [tmp_path / "empty"], "write": tmp_path / "box"}


def _read(year, store_dirs, write, **kw):
    return gen.read_class_generation(
        LEAGUE, year, persist=False, store_dirs=store_dirs, write_dir=write, **kw
    )


def _seed_dollars(year):
    (path,) = sorted((REPO_STORE / LEAGUE / str(year)).glob("*.json"))
    rec = json.loads(path.read_text("utf-8"))
    return tuple(r["dollars"] for r in rec["finalWholeDollars"])


def _inputs_fn(values):
    def fn(_league, _year):
        return gen.ClassCurveInputs(
            values=tuple(values),
            input_mode="actual",
            inputs_id="adversarial",
            actual_input_class_year=_year,
            provenance={},
        )

    return fn


def _assert_fails_closed(g, year, *, seeded, reason_fragment):
    """A failed class refresh: that year's last verified record, else unavailable."""
    assert g.target_draft_year == year
    if seeded:
        assert g.allocation_state == "last_known_good"
        assert g.final_whole_dollars == _seed_dollars(year)  # THAT year's, never another's
        assert reason_fragment in g.allocation.failed_refresh["reason"]
    else:
        assert g.allocation_state == "unavailable"
        assert g.final_whole_dollars is None  # missing, never 72 zeros
        assert g.allocation.unavailable_reason == "no_verified_allocation"
        assert reason_fragment in g.allocation.failed_refresh["reason"]
        with pytest.raises(LookupError):
            g.allocation.dollars_by_slot()


# --- ties ---------------------------------------------------------------------------------


def test_all_tied_rookie_values_give_one_deterministic_curve_equal_to_the_transcription():
    tied = [5000] * 72
    result = compute_curve(tied, SPINE)
    assert sum(result.reference_dollars) == 1200
    whole = list(result.final_whole_dollars)
    assert sum(whole) == 1200 and all(whole[i] <= whole[i - 1] for i in range(1, 72))
    rows = range(2, 74)
    sheet = ref.evaluate_sheet(
        {r: 5000.0 for r in rows},
        {r: float(SPINE[0][r - 2]) for r in rows},
        {r: float(SPINE[1][r - 2]) for r in rows},
        {r: float(SPINE[2][r - 2]) for r in rows},
    )
    owner = ref.evaluate_integer_stage(sheet["C"], 12, tie_rule="earlier_first")
    assert [Fraction(owner["L"][r]) for r in rows] == [Fraction(d) for d in result.dollars]
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    expected, _ = ref.whole_dollars([Fraction(d) for d in result.dollars], 1200, floors, caps)
    assert whole == expected


def test_tied_remainders_at_the_whole_dollar_cutoff_go_to_the_earlier_pick():
    out = apportion_whole_dollars([Fraction(5, 2)] * 4, 10)
    assert list(out.dollars) == [3, 3, 2, 2]  # never [2, 3, 3, 2] or a total of 12
    assert list(out.dollars) == ref.whole_dollars([Fraction(5, 2)] * 4, 10)[0]


def test_tied_board_values_order_deterministically_whatever_the_row_order():
    rows = [
        {
            "playerId": f"p{i:03d}",
            "eligibleDraftYear": 2027,
            "rankDerivedValue": 4000 - 10 * (i // 2),
        }
        for i in range(80)
    ]
    snaps = []
    for seed in (1, 2, 3):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        snaps.append(
            build_class_candidate(
                {"playersArray": shuffled},
                target_draft_year=2027,
                league_key=LEAGUE,
                observed_nfl_season=None,
            )
        )
    ids = [[e.canonical_player_id for e in s.entries] for s in snaps]
    assert ids[0] == ids[1] == ids[2]
    assert snaps[0].status == STATUS_COMPLETE and len(ids[0]) == 72


# --- missing rookies / fewer than 72 ----------------------------------------------------------


@pytest.mark.parametrize("seeded", [True, False])
def test_a_missing_rookie_value_never_becomes_zero(stores, seeded):
    values = FROZEN[:]
    values[10] = None
    g = _read(
        2028,
        stores["seeded"] if seeded else stores["empty"],
        stores["write"],
        inputs_fn=_inputs_fn(values),
    )
    _assert_fails_closed(g, 2028, seeded=seeded, reason_fragment="missing is never zero")


@pytest.mark.parametrize("seeded", [True, False])
def test_fewer_than_72_rookies_is_refused_never_stretched(stores, seeded):
    g = _read(
        2029,
        stores["seeded"] if seeded else stores["empty"],
        stores["write"],
        inputs_fn=_inputs_fn(FROZEN[:71]),
    )
    _assert_fails_closed(
        g, 2029, seeded=seeded, reason_fragment="expected 72 rookie values, got 71"
    )


def test_short_class_snapshot_and_short_ladder_are_explicit():
    rows = [
        {"playerId": f"p{i}", "eligibleDraftYear": 2027, "rankDerivedValue": 5000 - i}
        for i in range(71)
    ]
    snap = build_class_candidate(
        {"playersArray": rows}, target_draft_year=2027, league_key=LEAGUE, observed_nfl_season=None
    )
    assert snap.status == STATUS_NOT_READY
    assert "insufficient_eligible:71/72" in snap.missing_reasons
    ladder = gen.rookie_ladder(
        [5000 - i for i in range(71)], league_key=LEAGUE, draft_year=2027, input_source="test"
    )
    assert ladder.dollars is None and ladder.reason == "inputs_incomplete:need_72_rookies_have_71"


def test_a_zero_or_missing_board_value_is_excluded_not_priced_at_zero():
    rows = [
        {"playerId": f"p{i}", "eligibleDraftYear": 2027, "rankDerivedValue": 5000 - i}
        for i in range(72)
    ]
    rows[3]["rankDerivedValue"] = 0
    rows[4]["rankDerivedValue"] = None
    snap = build_class_candidate(
        {"playersArray": rows}, target_draft_year=2027, league_key=LEAGUE, observed_nfl_season=None
    )
    assert snap.status == STATUS_NOT_READY
    assert snap.exclusions == {"no_positive_value": 2}
    assert all(e.value > 0 for e in snap.entries)
    with pytest.raises(CurveInputError, match="strictly positive"):
        compute_curve([0] + FROZEN[1:], SPINE)


# --- duplicate names ----------------------------------------------------------------------------


def _named(n, *, dup_name=None, dup_id=False):
    rows = [
        {"canonicalName": f"Rookie {i}", "eligibleDraftYear": 2027, "rankDerivedValue": 6000 - i}
        for i in range(n)
    ]
    if dup_name is not None:
        extra = {"canonicalName": dup_name, "eligibleDraftYear": 2027, "rankDerivedValue": 100}
        if dup_id:
            extra["playerId"] = "distinct-player"
        rows.append(extra)
    return rows


def test_two_records_with_the_same_name_and_no_id_refuse_the_class():
    snap = build_class_candidate(
        {"playersArray": _named(80, dup_name="Rookie 5")},
        target_draft_year=2027,
        league_key=LEAGUE,
        observed_nfl_season=None,
    )
    assert snap.status == STATUS_NOT_READY
    assert "duplicate_identity:name:rookie 5" in snap.missing_reasons
    # Neither record is silently chosen.
    assert all(e.canonical_player_id != "name:rookie 5" for e in snap.entries)


def test_same_name_with_a_distinct_player_id_is_a_different_player():
    snap = build_class_candidate(
        {"playersArray": _named(80, dup_name="Rookie 5", dup_id=True)},
        target_draft_year=2027,
        league_key=LEAGUE,
        observed_nfl_season=None,
    )
    assert snap.status == STATUS_COMPLETE
    assert not any(r.startswith("duplicate_identity") for r in snap.missing_reasons)


# --- rising value sequence ------------------------------------------------------------------------


def test_a_rising_input_still_publishes_a_non_increasing_curve_equal_to_the_transcription():
    rising = sorted(FROZEN)  # strictly the wrong way round
    result = compute_curve(rising, SPINE)
    whole = list(result.final_whole_dollars)
    assert sum(whole) == 1200 and all(whole[i] <= whole[i - 1] for i in range(1, 72))
    rows = range(2, 74)
    sheet = ref.evaluate_sheet(
        {r: float(rising[r - 2]) for r in rows},
        {r: float(SPINE[0][r - 2]) for r in rows},
        {r: float(SPINE[1][r - 2]) for r in rows},
        {r: float(SPINE[2][r - 2]) for r in rows},
    )
    owner = ref.evaluate_integer_stage(sheet["C"], 12, tie_rule="earlier_first")
    assert [Fraction(owner["L"][r]) for r in rows] == [Fraction(d) for d in result.dollars]


def test_a_rising_rookie_list_is_refused_by_the_ladder_never_misattributed():
    ranked = sorted(FROZEN, reverse=True)
    ok = gen.rookie_ladder(ranked, league_key=LEAGUE, draft_year=2027, input_source="test")
    assert ok.state == "computed"
    swapped = ranked[:]
    swapped[9], swapped[10] = swapped[10] - 1, swapped[9] + 1  # pick 11 now outranks pick 10
    out = gen.rookie_ladder(swapped, league_key=LEAGUE, draft_year=2027, input_source="test")
    assert out.dollars is None and out.state == "refused"
    assert out.reason == "inputs_not_ranked:value_rises_at_11"


def test_a_rising_board_is_sorted_into_rank_order_by_the_class_snapshot():
    rows = [
        {"playerId": f"p{i:02d}", "eligibleDraftYear": 2027, "rankDerivedValue": 1000 + i}
        for i in range(72)
    ]
    snap = build_class_candidate(
        {"playersArray": rows}, target_draft_year=2027, league_key=LEAGUE, observed_nfl_season=None
    )
    values = list(snap.curve_values())
    assert values == sorted(values, reverse=True) and values[0] == Decimal(1071)


# --- stale or unknown class year ------------------------------------------------------------------


def test_a_retired_class_publishes_nothing(stores):
    retired = ClassLifecycle(season=2027, status="retired", reasons=("test",))
    g = _read(2027, stores["seeded"], stores["write"], lifecycle=retired)
    assert g.allocation_state == "unavailable" and g.final_whole_dollars is None
    assert g.allocation.unavailable_reason == "draft_class_retired"


def test_a_class_with_no_spine_on_file_is_unavailable_never_the_next_years_curve(stores):
    # 2026 would need 2023-2025; only 2024/2025 exist before it.
    g = _read(2026, stores["seeded"], stores["write"])
    assert g.allocation_state == "unavailable" and g.final_whole_dollars is None
    assert "SpineUnavailableError" in g.allocation.failed_refresh["reason"]


def test_a_candidate_for_another_year_is_refused(stores):
    cand = gen.class_curve_candidate(LEAGUE, 2027, now="2026-10-18T00:00:00+00:00")
    alloc = published.resolve_published_allocation(
        LEAGUE, 2028, candidate=cand, store_dirs=stores["seeded"], persist=False
    )
    assert alloc.allocation_state == "unavailable"
    assert alloc.unavailable_reason == "draft_year_mismatch:2027!=2028"


def test_a_record_from_another_formula_version_is_stale_and_refused(stores, tmp_path):
    old = tmp_path / "old"
    (path,) = sorted((REPO_STORE / LEAGUE / "2028").glob("*.json"))
    rec = json.loads(path.read_text("utf-8"))
    rec["formulaVersion"] = "draft_data_workbook_v0"
    from src.draft.rookie_auction.snapshots import canonical_checksum

    rec["checksum"] = {"algorithm": "sha256", "value": canonical_checksum(rec)}
    (old / LEAGUE / "2028").mkdir(parents=True)
    (old / LEAGUE / "2028" / path.name).write_text(json.dumps(rec), "utf-8")
    alloc = published.resolve_published_allocation(
        LEAGUE,
        2028,
        candidate=CandidateFailure(2028, "refresh failed", "2026-10-18T00:00:00+00:00"),
        store_dirs=[old],
        persist=False,
    )
    assert alloc.allocation_state == "unavailable" and alloc.final_whole_dollars is None
    assert alloc.unavailable_reason == "stored_allocation_formula_version_mismatch"


@pytest.mark.parametrize(
    ("row", "excluded"),
    [
        ({"yearsExp": None}, "class_unprovable:no_years_exp"),
        ({"yearsExp": 0}, "class_unprovable:observation_season_unknown"),
        ({"eligibleDraftYear": 2026}, "other_class"),
    ],
)
def test_an_unknown_or_stale_class_year_is_excluded_never_guessed(row, excluded):
    rows = [
        {"playerId": f"p{i}", "eligibleDraftYear": 2027, "rankDerivedValue": 5000 - i}
        for i in range(72)
    ]
    rows[0] = {"playerId": "x", "rankDerivedValue": 9999, **row}
    snap = build_class_candidate(
        {"playersArray": rows}, target_draft_year=2027, league_key=LEAGUE, observed_nfl_season=None
    )
    assert snap.exclusions.get(excluded) == 1
    assert snap.status == STATUS_NOT_READY and "x" not in [
        e.canonical_player_id for e in snap.entries
    ]


def test_an_unconfigured_league_is_not_adapted(stores):
    g = gen.read_class_generation("dynasty_new", 2028, persist=False, store_dirs=stores["seeded"])
    assert g.allocation_state == "unavailable"
    assert g.allocation.unavailable_reason == "league_not_configured:dynasty_new"


# --- missing / tampered spine -----------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path):
    dst = tmp_path / "draft_valuation"
    shutil.copytree(CONFIG_DIR, dst)
    return dst


@pytest.mark.parametrize("seeded", [True, False])
def test_a_missing_spine_class_fails_closed(stores, cfg, seeded):
    (cfg / "historical_curves" / LEAGUE / "2025.json").unlink()
    g = _read(
        2028, stores["seeded"] if seeded else stores["empty"], stores["write"], config_dir=cfg
    )
    _assert_fails_closed(g, 2028, seeded=seeded, reason_fragment="SpineUnavailableError")


def test_a_tampered_spine_class_fails_closed(stores, cfg):
    path = cfg / "historical_curves" / LEAGUE / "2026.json"
    path.write_text(path.read_text("utf-8").replace('"134"', '"135"', 1), "utf-8")
    g = _read(2029, stores["seeded"], stores["write"], config_dir=cfg)
    _assert_fails_closed(g, 2029, seeded=True, reason_fragment="SnapshotIntegrityError")


def test_a_tampered_frozen_baseline_fails_closed(stores):
    def broken(_league, _year):
        raise SnapshotIntegrityError("2026_spreadsheet_baseline.json: checksum mismatch")

    g = _read(2027, stores["seeded"], stores["write"], inputs_fn=broken)
    _assert_fails_closed(g, 2027, seeded=True, reason_fragment="checksum mismatch")


# --- the served board: malformed workbook, unknown ownership, refused board ----------------------------


@pytest.fixture()
def board(monkeypatch):
    """The Batch E route harness: stubbed 72-pick workbook + Sleeper league."""
    server = pytest.importorskip("server")
    import src.api.draft_class_evidence as dce
    from tests.api import test_draft_capital_multi_year as my

    monkeypatch.setattr(server, "_parse_draft_data", my._fake_workbook)
    monkeypatch.setattr(server, "_sleeper_league_id_for_draft", lambda _k=None: my.LEAGUE_ID)
    monkeypatch.setattr(server, "_our_rookie_pool", lambda *_a, **_k: [])
    monkeypatch.setattr(
        server._league_registry,
        "league_key_for_sleeper_id",
        lambda lid: LEAGUE if lid == my.LEAGUE_ID else None,
    )
    monkeypatch.setattr(dce, "read_snapshot", lambda _lid: None)

    def run(traded=my.TRADED, **kw):
        monkeypatch.setattr(
            server.urllib.request, "urlopen", my._urlopen(my._sleeper(traded=traded, **kw))
        )
        return server._fetch_draft_capital(LEAGUE)

    return server, my, run


def test_unreadable_workbook_refuses_the_board(monkeypatch, tmp_path):
    server = pytest.importorskip("server")
    garbage = tmp_path / "Draft Data.xlsx"
    garbage.write_bytes(b"PK\x03\x04 this is not a workbook")
    monkeypatch.setattr(server, "DRAFT_DATA_XLSX", garbage)
    monkeypatch.setattr(server, "DRAFT_DATA_CSV", tmp_path / "missing.csv")
    monkeypatch.setattr(server, "_get_ktc_rookies", lambda: [])
    out = server._fetch_draft_capital(apply_sleeper_trades=False)
    assert out == {"error": "Draft data workbook not found or empty"}


def test_a_workbook_whose_dollars_do_not_total_the_pool_is_refused(board, monkeypatch):
    server, my, run = board
    short = [
        {"round": 1 + i // 10, "pick": 1 + i % 10, "value": 18.0, "owner": f"N{1 + i % 10:02d}"}
        for i in range(60)
    ]  # 60 picks x $18 = $1,080, not $1,200
    monkeypatch.setattr(server, "_parse_draft_data", lambda: ([], short, {}, {}, [], [18.0] * 60))
    out = run()
    assert out["error"] == "draft_dollars_refused" and out["conflict"] == "sum_not_total"
    assert "picks" not in out and "teamTotals" not in out


@pytest.mark.parametrize("traded", [OSError("sleeper down"), {"not": "a list"}])
def test_unknown_pick_ownership_refuses_the_board(board, traded):
    _server, _my, run = board
    out = run(traded=traded)
    assert out["error"] == "pick_ownership_unavailable"
    assert "picks" not in out and "teamTotals" not in out and _no_zero_dollars(out)


def test_a_failed_generation_refuses_the_board_with_its_year_and_receipt(
    board, monkeypatch, tmp_path
):
    _server, my, run = board
    monkeypatch.setattr(published, "REPO_STORE", tmp_path / "repo")
    monkeypatch.setattr(published, "BOX_STORE", tmp_path / "box")

    def broken(_league, _year):
        raise SnapshotIntegrityError("frozen baseline edited")

    monkeypatch.setattr(dcc, "class_curve_inputs", broken)
    out = run()
    assert out["error"] == "draft_dollars_unavailable"
    assert out["draftYear"] == my.YEAR + 1 and out["unavailableReason"] == "no_verified_allocation"
    assert "frozen baseline edited" in out["failedRefresh"]["reason"]
    assert out["draftValuationGeneration"]["allocationState"] == "unavailable"
    assert out["draftValuationGeneration"]["generationHash"] is None
    assert "picks" not in out and "teamTotals" not in out


def test_a_failed_generation_with_a_record_serves_that_years_last_known_good(board, monkeypatch):
    _server, my, run = board

    def broken(_league, _year):
        raise SnapshotIntegrityError("frozen baseline edited")

    monkeypatch.setattr(dcc, "class_curve_inputs", broken)
    out = run()
    assert "error" not in out
    assert out["draftValuationGeneration"]["allocationState"] == "last_known_good"
    assert out["draftValuationGeneration"]["targetDraftYear"] == my.YEAR + 1
    by_slot = sorted(out["picks"], key=lambda p: (p["round"], p["pickInRound"]))
    assert tuple(p["dollarValue"] for p in by_slot) == _seed_dollars(my.YEAR + 1)
    assert sum(t["auctionDollars"] for t in out["teamTotals"]) == 1200


# --- stale-while-revalidate boundaries -------------------------------------------------------------


@pytest.fixture()
def swr(monkeypatch):
    server = pytest.importorskip("server")
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LAST_VALID", {})
    return server


GOOD = {"season": 2027, "picks": [{"pick": "1.01", "dollarValue": 135}], "teamTotals": []}


def _failed(year=2027, error="draft_dollars_unavailable"):
    return {"error": error, "unavailableReason": "no_verified_allocation", "draftYear": year}


def test_swr_serves_up_to_exactly_the_staleness_budget_and_not_a_moment_longer(swr):
    budget = float(swr.SCRAPE_INTERVAL_HOURS) * 3 * 3600.0
    assert budget == 6 * 3600.0
    t0 = 1_800_000_000.0
    swr._DRAFT_CAPITAL_LAST_VALID["lk"] = (t0, GOOD)
    at_edge = swr._draft_capital_stale_fallback("lk", _failed(), t0 + budget)
    assert at_edge is not None and at_edge["picks"] == GOOD["picks"]
    assert at_edge["staleWhileRevalidate"]["ageSeconds"] == int(budget)
    assert swr._draft_capital_stale_fallback("lk", _failed(), t0 + budget + 0.001) is None
    # The stored board is never mutated by serving it.
    assert "staleWhileRevalidate" not in swr._DRAFT_CAPITAL_LAST_VALID["lk"][1]


@pytest.mark.parametrize(
    "failed",
    [
        _failed(2028),  # another year: never answered with 2027's board
        _failed(True),  # a bool is not a year
        _failed("2027"),  # a string is not a year
        {"error": "draft_dollars_unavailable"},  # year unstated
        _failed(error="pick_ownership_unavailable"),  # ownership refusals keep refusing
        _failed(error="sleeper_unreachable"),
        None,
    ],
)
def test_swr_never_answers_outside_its_guards(swr, failed):
    swr._DRAFT_CAPITAL_LAST_VALID["lk"] = (time.time(), GOOD)
    assert swr._draft_capital_stale_fallback("lk", failed, time.time()) is None


def test_swr_without_a_last_valid_board_answers_nothing(swr):
    assert swr._draft_capital_stale_fallback("lk", _failed(), time.time()) is None


def test_swr_serves_a_refused_whole_dollar_generation_of_the_same_year(swr):
    t0 = 1_800_000_000.0
    swr._DRAFT_CAPITAL_LAST_VALID["lk"] = (t0, GOOD)
    out = swr._draft_capital_stale_fallback("lk", _failed(error="draft_dollars_refused"), t0 + 60)
    assert out["staleWhileRevalidate"]["failedError"] == "draft_dollars_refused"
    assert out["staleWhileRevalidate"]["draftYear"] == 2027


def test_whole_dollar_bounds_are_the_formulas_own():
    floors, caps = whole_dollar_constraints()
    rf, rc = ref.dynasty_main_whole_dollar_bounds()
    assert floors == rf and caps == rc
