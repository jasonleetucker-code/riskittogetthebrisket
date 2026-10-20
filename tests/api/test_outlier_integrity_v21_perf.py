"""Outlier integrity V2.1 repair R13: build time and contract size, decisions unchanged.

V2.1 preregistration (``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md``)
R13 / criteria 13-14: no full-board deep copy, identity grading memoized per
(source, CSV), per-vote stamps only for non-default verdicts, census per source.
R13 is NOT a decision rule, so every test here pins that it changes no value,
rank, vote or exclusion -- only how fast the build runs and how many bytes the
contract carries.  Synthetic rows only (Stage 1).
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import os
import random
import tempfile
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.sources import voting_status as vs
from tests.api.test_outlier_integrity_v21_repairs import V21_ON
from tests.api.test_source_integrity import (
    ALL_ON,
    META,
    PAYLOAD,
    _build,
    _csvs,
    _flags,
    _rows,
)

NO_R13 = si.Repairs.all_on().without("R13")


def _canon(contract) -> dict:
    """The contract without its build clock and file-age readings (each
    synthetic build reads its CSVs from a fresh temporary directory)."""
    c = copy.deepcopy(contract)
    c.pop("generatedAt", None)
    c.pop("dataFreshness", None)
    return c


def _decisions(contract) -> dict:
    """Every value, rank and per-vote decision of a board (no stamps)."""
    out = {}
    for r in contract["playersArray"]:
        votes = {}
        for s, m in (r.get("sourceRankMeta") or {}).items():
            integ = m.get("integrity") or {}
            votes[s] = (
                m.get("valueContribution"),
                m.get("contributedToBlend"),
                m.get("excludedReason"),
                bool(m.get("hampelDropped")),
                integ.get("status", si.STATUS_VOTING),
            )
        out[r["displayName"]] = (
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
            r.get("confidenceBucket"),
            tuple(sorted((r.get("canonicalSiteValues") or {}).items())),
            votes,
        )
    return out


def _clear_memos():
    dc._V21_GRADE_MEMO.update({"board": None, "sources": {}})
    dc._V2_BUCKET_MEMO.clear()
    si._SEGMENT_SCREEN_MEMO.clear()
    si._FORMAT_FINDINGS_MEMO.clear()


_STABLE_ROOT = tempfile.TemporaryDirectory(prefix="oiv21-perf-")
_MTIME_NS = [1_800_000_000_000_000_000]


def _build_stable(flags=(), *, csvs=None, history="unset", mutate=None):
    """``_build`` over ONE CSV tree for the whole module, as production
    rebuilds read the same files: a file is rewritten (with a strictly newer
    mtime) only when its content changes, so the memo's scopes persist across
    builds exactly as they do in serving."""
    root = Path(_STABLE_ROOT.name)
    d = root / "CSVs" / "site_raw"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in (csvs if csvs is not None else _csvs(META)).items():
        path = d / name
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            _MTIME_NS[0] += 1_000_000_000
            os.utime(path, ns=(_MTIME_NS[0], _MTIME_NS[0]))
    payload = json.loads(json.dumps(PAYLOAD))
    if mutate:
        mutate(payload)
    with contextlib.redirect_stdout(io.StringIO()), _flags(*flags), contextlib.ExitStack() as st:
        if history != "unset":
            st.enter_context(si.history_override(history))
        return dc.build_api_data_contract(payload, csv_root=root)


@contextlib.contextmanager
def _grading_calls():
    """Counts the memo's misses (joins graded by the identity owner) during
    the block; hits are re-served verdicts."""
    before = dict(dc._V21_GRADE_MEMO_STATS)
    calls = [0]
    try:
        yield calls
    finally:
        calls[0] = dc._V21_GRADE_MEMO_STATS["misses"] - before["misses"]


@pytest.fixture(scope="module")
def boards():
    _clear_memos()
    with _grading_calls() as cold_calls:
        cold = _build_stable(V21_ON)
    with _grading_calls() as warm_calls:
        warm = _build_stable(V21_ON)
    with si.repairs_override(NO_R13):
        full = _build(V21_ON)
    return {
        "cold": cold,
        "warm": warm,
        "full": full,
        "calls": (cold_calls[0], warm_calls[0]),
    }


# ── compact stamps (contract size) ─────────────────────────────────────


def test_r13_changes_no_decision(boards):
    assert _decisions(boards["cold"]) == _decisions(boards["full"])


def test_r13_contract_is_smaller_and_compaction_is_counted(boards):
    def size(c):
        return len(json.dumps(c, sort_keys=True, default=str))

    assert size(boards["cold"]) < size(boards["full"])
    counts = boards["cold"]["sourceIntegrity"]["compactStamps"]
    assert counts["rowStampsDropped"] + counts["voteBlocksDropped"] > 0
    assert "compactStamps" not in boards["full"]["sourceIntegrity"]


def test_r13_compaction_keeps_every_non_default_stamp(boards):
    """Refusals, holds, withholds, quarantines, Layer C decisions, advisories,
    TEAM_UNCONFIRMED votes: all verbatim."""
    full, cold = _rows(boards["full"]), _rows(boards["cold"])
    for name, row in full.items():
        for source, stamp in (row.get("sourceIntegrity") or {}).items():
            ident = stamp.get("identity") or {}
            default = set(stamp) == {"identity"} and ident.get("verdict") in (
                si.DEFAULT_VOTING_VERDICTS
            )
            if not default:
                assert cold[name]["sourceIntegrity"][source] == stamp, (name, source)
        for source, meta in (row.get("sourceRankMeta") or {}).items():
            integ = meta.get("integrity")
            default = (
                integ
                and integ.get("status") == si.STATUS_VOTING
                and integ.get("primaryReason") in (si.REASON_VOTING, si.REASON_NAME_ONLY)
                and set(integ) <= {"status", "primaryReason", "category", "identity"}
            )
            if integ and not default:
                assert cold[name]["sourceRankMeta"][source]["integrity"] == integ


def test_r13_census_and_history_record_are_unchanged(boards):
    """The per-source census (identity verdicts, §10 categories) is taken
    before compaction, and the history lane's record reads the entry teams
    compaction keeps -- so neither moves."""
    a, b = boards["cold"]["sourceIntegrity"], boards["full"]["sourceIntegrity"]
    assert a["identity"] == b["identity"]
    assert a["votingCategories"] == b["votingCategories"]
    assert si.board_record(boards["cold"]) == si.board_record(boards["full"])


def test_r13_compacted_votes_read_as_voting_normally(boards):
    for row in boards["cold"]["playersArray"]:
        for meta in (row.get("sourceRankMeta") or {}).values():
            category, _reason = si.observation_category(meta)
            if "integrity" not in meta and not meta.get("excludedReason"):
                assert category not in vs.INVALID_OBSERVATION_CATEGORIES


def test_compact_default_stamps_is_idempotent_and_shares_legacy_metas():
    meta = {
        "integrity": si.voting_stamp(
            {"sourceIntegrity": {"s": {"identity": {"verdict": "NAME_ONLY"}}}}, "s"
        )
    }
    rows = [
        {
            "sourceRankMeta": {"s": meta},
            "sourceIntegrity": {
                "s": {"identity": {"verdict": "VERIFIED", "evidence": ["id"], "entryTeam": "BUF"}}
            },
        }
    ]
    first = si.compact_default_stamps(rows, {"x": {"sourceRankMeta": {"s": meta}}})
    assert first == {"rowStampsDropped": 0, "rowStampsSlimmed": 1, "voteBlocksDropped": 1}
    assert rows[0]["sourceIntegrity"]["s"] == {
        "identity": {"verdict": "VERIFIED", "entryTeam": "BUF"}
    }
    assert si.compact_default_stamps(rows) == {
        "rowStampsDropped": 0,
        "rowStampsSlimmed": 1,
        "voteBlocksDropped": 0,
    }


# ── memoized identity grading (build time) ─────────────────────────────


def test_a_warm_rebuild_is_identical_to_the_cold_build(boards):
    assert _canon(boards["warm"]) == _canon(boards["cold"])


def test_a_warm_rebuild_grades_nothing_again(boards):
    """The memo is really used: the cold build grades every join, the warm
    rebuild of the same board and files grades none."""
    cold, warm = boards["calls"]
    assert cold > 100 and warm == 0


def test_the_memo_never_serves_a_changed_csv():
    """A different CSV (new content, new mtime) is graded afresh: the memoized
    build equals a build from an empty memo."""
    csvs = _csvs(META)
    lines = csvs["dynastyNerdsSfTep.csv"].splitlines()
    lines = [ln for ln in lines if not ln.startswith("Off Vet 002,")]
    lines.append("Off Vet 002,90,5500,,LB,CLE")  # a wrong-position entry: refused
    csvs["dynastyNerdsSfTep.csv"] = "\n".join(lines) + "\n"
    _clear_memos()
    _build_stable(V21_ON)  # warm the memo on the clean board
    memo_changed = _build_stable(V21_ON, csvs=csvs)
    _clear_memos()
    fresh_changed = _build(V21_ON, csvs=csvs)
    assert _canon(memo_changed) == _canon(fresh_changed)
    stamp = _rows(memo_changed)["Off Vet 002"]["sourceIntegrity"]["dynastyNerdsSfTep"]
    assert stamp["status"] == si.STATUS_REFUSED


def test_the_memo_never_serves_a_changed_history():
    """History facts (prior team, the row's previous teams) are part of every
    memo key: a board built with a different history equals a fresh build."""
    _clear_memos()
    base = _build_stable(V21_ON, history=None)
    rec = si.board_record(base)
    rec["asOf"] = "2026-08-01T00:00:00"
    # Every source last saw every player on a different team.
    for k, obs in rec["observations"].items():
        obs["team"] = "ARI" if obs.get("team") != "ARI" else "ATL"
    hist = si.advance(None, rec)
    with _grading_calls() as calls:
        with_memo = _build_stable(V21_ON, history=hist)
    assert calls[0] > 0  # the changed history facts missed the memo
    _clear_memos()
    fresh = _build(V21_ON, history=hist)
    assert _canon(with_memo) == _canon(fresh)


def test_the_board_identity_resets_the_memo():
    _clear_memos()
    _build_stable(V21_ON)
    first = dc._V21_GRADE_MEMO["board"]
    assert first is not None and dc._V21_GRADE_MEMO["sources"]

    def rename(payload):
        payload["players"]["Off Vet 001"]["team"] = "SEA"

    with _grading_calls() as calls:
        renamed = _build_stable(V21_ON, mutate=rename)
    assert dc._V21_GRADE_MEMO["board"] != first and calls[0] > 100
    _clear_memos()
    assert _canon(renamed) == _canon(_build(V21_ON, mutate=rename))


def test_v2_without_the_sub_flag_never_uses_the_memo():
    _clear_memos()
    _build(ALL_ON)
    assert dc._V21_GRADE_MEMO["board"] is None
    assert not si._SEGMENT_SCREEN_MEMO


# ── snapshot, segment screen, B0 memo ──────────────────────────────────


def test_snapshot_round_trip_keeps_the_shared_object_graph():
    shared = {"a": 1}
    board = ([{"x": shared}, {"y": shared}], {"p": shared})
    restored = si._restore_board_snapshot(si._board_snapshot(board))
    assert restored == board
    arr, by = restored
    assert arr[0]["x"] is arr[1]["y"] is by["p"]
    assert arr[0]["x"] is not shared


def test_snapshot_falls_back_to_deepcopy_for_unpicklable_boards():
    board = ([{"f": lambda: 1}], {})
    kind, _blob = si._board_snapshot(board)
    assert kind == "deepcopy"


def _reversed_wr_csvs():
    csvs = _csvs(META)
    lines = csvs["fantasyCalc.csv"].splitlines()
    head, body = lines[0], lines[1:]
    wr_names = {m[0] for m in META if m[1] == "WR" and not m[3]}
    wr = [i for i, ln in enumerate(body) if ln.split(",")[0] in wr_names]
    ranks = [body[i].split(",")[2] for i in wr]
    vals = [body[i].split(",")[1] for i in wr]
    for j, i in enumerate(wr):
        name = body[i].split(",")[0]
        body[i] = f"{name},{vals[len(wr) - 1 - j]},{ranks[len(wr) - 1 - j]}"
    csvs["fantasyCalc.csv"] = "\n".join([head] + body) + "\n"
    return csvs


def test_the_re_rank_after_a_quarantine_is_identical_with_either_snapshot(monkeypatch):
    """A B3 quarantine restores the pre-ranking board and ranks again: the
    serialized snapshot restores exactly what ``copy.deepcopy`` did."""
    csvs = _reversed_wr_csvs()
    _clear_memos()
    fast = _build(V21_ON, csvs=csvs)
    assert fast["sourceIntegrity"]["rankingPasses"] == 2
    monkeypatch.setattr(si, "_board_snapshot", lambda b: ("deepcopy", copy.deepcopy(b)))
    _clear_memos()
    slow = _build(V21_ON, csvs=csvs)
    assert _canon(fast) == _canon(slow)


def _seg_rows(n=30, seed=3):
    rng = random.Random(seed)
    rows = {}
    for i in range(n):
        base = 2.0 + 0.1 * i
        votes = {f"s{j}": base + rng.uniform(-0.2, 0.2) for j in range(5)}
        rows[i] = ("offense", ("WR", "RB")[i % 2], votes)
    return rows


def test_segment_screen_memo_equals_the_screen_and_cannot_be_altered():
    si._SEGMENT_SCREEN_MEMO.clear()
    thr = si.IntegrityThresholds()
    rows = _seg_rows()
    plain = si.segment_screen(rows, provider_of=str, thresholds=thr, history=None)
    first = si.segment_screen_memo(rows, provider_of=str, thresholds=thr, history=None)
    first.medians.clear()  # a caller altering its result
    second = si.segment_screen_memo(rows, provider_of=str, thresholds=thr, history=None)
    assert second.medians == plain.medians and second.stats == plain.stats
    assert second.quarantines == plain.quarantines and second.findings == plain.findings
    # Any changed input recomputes.
    changed = copy.deepcopy(rows)
    changed[0][2]["s0"] += 1.0
    again = si.segment_screen_memo(changed, provider_of=str, thresholds=thr, history=None)
    assert (
        again.medians
        == si.segment_screen(changed, provider_of=str, thresholds=thr, history=None).medians
    )


def test_format_findings_cached_returns_fresh_copies():
    si._FORMAT_FINDINGS_MEMO.clear()
    census = {
        "rows": 3,
        "rankValuePairs": [(1, 30), (2, 40), (3, 10)],
        "rankValueKeys": ["a", "b", "c"],
    }
    a = si.format_findings_cached("x", census, tolerant=True)
    assert a == si.format_findings("x", census, tolerant=True)
    if a:
        a[0].evidence.clear()
    assert si.format_findings_cached("x", census, tolerant=True) == si.format_findings(
        "x", census, tolerant=True
    )


# ── exact rewrites of two inner loops ──────────────────────────────────


def test_leave_source_out_references_equal_the_one_source_function():
    rng = random.Random(11)
    provs = "ABCDE"
    for _ in range(3000):
        k = rng.randint(1, 12)
        votes = {
            f"s{i}": rng.choice([rng.uniform(1, 7), float(rng.randint(1, 5))]) for i in range(k)
        }
        pmap = {s: rng.choice(provs) for s in votes}
        got = si.leave_source_out_references(votes, pmap.get)
        for s in votes:
            assert got[s] == si.leave_source_out_reference(s, votes, pmap.get), (votes, pmap, s)


def test_layer_c_nearest_other_provider_equals_the_pairwise_scan():
    rng = random.Random(7)
    curve = op.scope_curve("offense")
    for _ in range(4000):
        k = rng.randint(2, 14)
        provs = [rng.choice("ABCDEFG") for _ in range(k)]
        pairs = [
            (f"s{i}", rng.choice([rng.uniform(1, 9998), float(rng.randint(1, 50) * 100)]))
            for i in range(k)
        ]
        pmap = {f"s{i}": provs[i] for i in range(k)}
        v = op.assess_row_layer_c(
            pairs, curve=curve, provider_of=pmap.get, family_of=pmap.get, tau_c_big=math.log(4)
        )
        coords = {key: op.rank_coordinate(x, curve) for key, x in pairs}
        for o, info in v.details.items():
            brute = min(abs(coords[o] - coords[q]) for q in coords if pmap[q] != pmap[o])
            assert info["nearestOtherProvider"] == round(brute, 4)
        for o in coords:
            if all(pmap[q] == pmap[o] for q in coords):
                assert o not in v.details


def test_layer_c_lazy_weights_decide_exactly_as_eager_weights():
    """Guard 4 is the only reader of the family-capped weights; computing them
    lazily changes no decision."""
    rng = random.Random(5)
    curve = op.scope_curve("offense")
    for _ in range(1500):
        k = rng.randint(3, 9)
        pairs = [(f"s{i}", rng.uniform(50, 9900)) for i in range(k)]
        if rng.random() < 0.5:
            pairs.append(("far", rng.uniform(1, 60)))
        fam = {key: rng.choice("XYZ") for key, _v in pairs}
        weights = {key: rng.uniform(0.1, 2.0) for key, _v in pairs}
        eager = op.assess_row_layer_c(
            pairs, curve=curve, provider_of=str, family_of=fam.get, weights=weights
        )
        lazy = op.assess_row_layer_c(
            pairs, curve=curve, provider_of=str, family_of=fam.get, weights_fn=lambda: weights
        )
        assert eager == lazy


def test_a_wrapped_grading_function_sees_every_call():
    """A replay call recorder (``oiv2_replay.IdentityAgeRecorder``) wraps the
    identity owner's grading function; the memo then stands aside, so the
    recorder sees every join on every build -- warm or not."""
    from src.identity import resolution as res
    from src.robust_filter_shadow import oiv2_replay as RP

    _clear_memos()
    _build_stable(V21_ON)  # a warm memo
    calls = [0]
    original = res.assess_identity_evidence

    def counted(**kw):
        calls[0] += 1
        return original(**kw)

    res.assess_identity_evidence = counted
    try:
        _build_stable(V21_ON)
    finally:
        res.assess_identity_evidence = original
    assert calls[0] > 100
    rec = RP.IdentityAgeRecorder()
    with rec.active():
        _build_stable(V21_ON)
    assert rec.rows  # every aged join recorded on a warm build


def test_layer_c_memo_re_asks_every_recorded_lookup():
    """A Layer C memo hit needs the same panel AND the same answers from the
    context's lookups (lineage link, persistence, weights); a changed answer
    is a miss that decides afresh."""
    curve = op.scope_curve("offense")
    pairs = [("a", 5000.0), ("b", 5050.0), ("c", 4980.0), ("bad", 60.0)]
    linked = {"v": False}
    ctx = op.LayerCContext(
        curve=curve,
        provider_of=str,
        family_of=str,
        linked=lambda _a, _b: linked["v"],
        persistence_confirmed=lambda _k, _u: False,
        tau_c_big=math.log(4),
        weights_for=lambda ks: {k: 1.0 for k in ks},
    )
    memo = op.LayerCMemo()
    first = memo.assess(ctx, pairs)
    assert first == ctx.assess(pairs) and first.dropped == ("bad",)
    assert memo.assess(ctx, pairs) is first and memo.hits == 1
    linked["v"] = True  # every pair is now a translation and its backbone
    changed = memo.assess(ctx, pairs)
    assert changed == ctx.assess(pairs) and changed.dropped == ()
    assert memo.misses == 2


def test_layer_c_memo_stands_aside_for_a_recorder():
    from src.robust_filter_shadow import oiv2_replay as RP

    curve = op.scope_curve("offense")
    ctx = op.LayerCContext(curve=curve, provider_of=str, family_of=str)
    pairs = [("a", 5000.0), ("b", 5100.0), ("c", 4900.0)]
    memo = op.LayerCMemo()
    memo.assess(ctx, pairs)
    rec = RP.LayerCRecorder()
    with rec.active():
        memo.assess(ctx, pairs)
    assert rec.by_panel and memo.hits == 0
