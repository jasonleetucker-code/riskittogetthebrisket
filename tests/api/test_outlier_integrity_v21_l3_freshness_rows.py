"""Outlier integrity V2.1, cold-start safety set L3: the #1831 Option-B rows.

Owner decision on PR #1831 (2026-10-20, Option B) item 6 and the V2.1
preregistration (``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md`` §7.4,
part L3; owner O-1): the freshness-schedule-v2 affected rows of
``tests/fixtures/outlier_integrity_v2/freshness_v2_affected_rows_2026-10-20.json``
are LEGITIMATE votes, and with no history V2.1 must drop none of them.

Stage 1 may read synthetic rows only (§5.4), so these tests rebuild each fixture
row as a synthetic panel / board with the fixture's own player, position, asset
class, value level and source set (the board behind the fixture, pinOB, is a
Stage 3 constraint and is not read here):

* **Regression** (Layer C, the per-row filter V2.1 serves): every fixture row in
  each freshness state, its incumbent-excluded sources placed as a legitimate
  dissent the incumbent Hampel filter drops (reproducing the fixture's verdict)
  next to agreeing votes.  V2.1 with an empty history keeps every vote.
* **Integration** (``build_api_data_contract`` end to end, V2.1-NOHIST): a
  synthetic board carrying the fixture's offense rows under their own names and
  the fixture's own sources, LaJohntay Wester's Flock vote among them, plus the
  three newly unpriced IDP DBs voting through FantasyPros IDP alone.  No V2.1
  layer refuses, quarantines, withholds, holds or drops any of those votes, none
  is labelled with an invalid category, and when the FantasyPros IDP vote stops
  the DBs are UNPRICED -- never zero.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.sources import source_census
from src.sources import voting_status as vs
from tests.api.test_source_integrity import ALL_ON, _flags

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/outlier_integrity_v2/freshness_v2_affected_rows_2026-10-20.json"
V21_ON = (*ALL_ON, "outlier_integrity_v21")
DATA = json.loads(FIXTURE.read_text())
ROWS = DATA["rows"]
UNPRICED_DBS = ("Dee Alford", "James Pierre", "Kyle Dugger")

#: Agreeing votes that fill a panel up to a realistic size (real source keys,
#: so provider lineage and families are the production ones).
_CORE = {
    "offense": ("idpTradeCalc", "ktcTradesSfTep", "dynastyDaddySf", "fantasyProsSf"),
    "rookie": ("idpTradeCalc", "ktcTradesSfTep", "dynastyDaddySf", "fantasyProsSf"),
    "idp": ("idpTradeCalc", "draftSharksIdp"),
}
#: Votes that must stay out of the blend if a V2.1 layer excluded them.
_V21_EXCLUSION_STATUSES = {
    si.STATUS_REFUSED,
    si.STATUS_QUARANTINED,
    si.STATUS_WITHHELD,
    si.STATUS_HELD,
    si.STATUS_REJECTED_TAIL,
}


def _curve(asset_class: str) -> tuple[float, float]:
    return op.scope_curve("idp" if asset_class == "idp" else "offense")


def _family(key: str) -> str:
    return dc.correlation_group_for(key)


def _sign(*parts: str) -> int:
    return 1 if hashlib.sha256("|".join(parts).encode()).digest()[0] % 2 else -1


def _dissent_value(v0: float, player: str, state: str) -> float:
    """A legitimate disagreement the incumbent drops: more than its 1,000-point
    floor (and its 2.75 x MAD band, MAD being tiny among agreeing votes) away
    from the consensus, inside the board's value range."""
    gap = max(dc._HAMPEL_MIN_THRESHOLD + 100.0, 0.3 * v0)
    sign = _sign(player, state)
    if not 100.0 < v0 + sign * gap < 9900.0:
        sign = -sign
    return v0 + sign * gap


def _panels():
    """``(row, state, pairs, excluded)`` for every fixture row and freshness
    state that has votes: ``OFF`` is the board as served (``before``), ``ON``
    the freshness-v2 state (``after``)."""
    out = []
    for row in ROWS:
        mentioned = set(
            row["votesStarted"]
            + row["votesStopped"]
            + row["outlierExcludedBefore"]
            + row["outlierExcludedAfter"]
        )
        for state, value, excluded, absent in (
            ("OFF", row["before"], row["outlierExcludedBefore"], row["votesStarted"]),
            ("ON", row["after"], row["outlierExcludedAfter"], row["votesStopped"]),
        ):
            if value is None:
                continue  # unpriced in that state: no vote to keep
            present = sorted(mentioned - set(absent))
            agree = [k for k in present if k not in excluded]
            agree += [k for k in _CORE[row["class"]] if k not in mentioned]
            pairs = [(k, float(value) * (1.0 + 0.002 * i)) for i, k in enumerate(agree)]
            d = _dissent_value(float(value), row["player"], state)
            pairs += [(k, d * (1.0 + 0.001 * i)) for i, k in enumerate(sorted(excluded))]
            out.append((row, state, pairs, tuple(sorted(excluded))))
    return out


PANELS = _panels()


def _layer_c(row, pairs):
    return op.assess_row_layer_c(
        pairs,
        curve=_curve(row["class"]),
        provider_of=source_census.provider_of,
        family_of=_family,
        tau_c_big=si.load_thresholds().tau_c_big,
        # Cold start (owner O-1): no history, so no persistence ever confirms.
        persistence_confirmed=None,
    )


# ── the registered set ─────────────────────────────────────────────────


def test_the_panels_cover_every_registered_l3_vote_instance():
    """§7.4 L3: 27 flag-OFF + 23 flag-ON = 50 incumbent exclusions over 39
    player-source pairs, every one of them in a panel here."""
    instances = [(r["player"], s, k) for r, s, _p, ex in PANELS for k in ex]
    assert len(instances) == 50
    assert len({(p, k) for p, _s, k in instances}) == 39
    by_state = {s: sum(1 for _p, st, _k in instances if st == s) for s in ("OFF", "ON")}
    assert by_state == {"OFF": 27, "ON": 23}


@pytest.mark.parametrize(
    "row,state,pairs,excluded",
    [p for p in PANELS if p[3]],
    ids=[f"{p[0]['player']}-{p[1]}" for p in PANELS if p[3]],
)
def test_the_synthetic_panel_reproduces_the_incumbent_exclusion(row, state, pairs, excluded):
    """The panel is the fixture's mechanism: the incumbent per-player Hampel
    filter drops exactly the votes the fixture records it dropping."""
    _kept, dropped = dc._hampel_filter_per_player(list(pairs))
    assert sorted(dropped) == sorted(excluded)


# ── regression: Layer C at cold start keeps every legitimate vote ──────


@pytest.mark.parametrize(
    "row,state,pairs,excluded",
    PANELS,
    ids=[f"{p[0]['player']}-{p[1]}" for p in PANELS],
)
def test_v21_layer_c_without_history_drops_no_l3_vote(row, state, pairs, excluded):
    v = _layer_c(row, pairs)
    assert v.dropped == ()
    assert set(v.kept) == {k for k, _ in pairs}
    # A kept dissent is "valid but disagreeing", never an invalid category.
    for source, label in v.dissent.items():
        assert si.reason_category(label) == si.CATEGORY_DISSENT, (source, label)
        assert si.reason_category(label) not in vs.INVALID_OBSERVATION_CATEGORIES
    # The decision is a function of the multiset of votes, not their order.
    assert _layer_c(row, list(reversed(pairs))).dropped == ()


def test_wester_flock_vote_is_kept_in_both_freshness_states():
    """LaJohntay Wester (+40.4% when freshness v2 is on): the incumbent dropped
    Flock with the flag off and kept it with the flag on, because the voting
    population changed.  V2.1 keeps Flock in both states."""
    wester = [p for p in PANELS if p[0]["player"] == "LaJohntay Wester"]
    assert {s for _r, s, _p, _e in wester} == {"OFF", "ON"}
    off = next(p for p in wester if p[1] == "OFF")
    assert off[3] == ("flockFantasySf",)
    assert "flockFantasySf" in dc._hampel_filter_per_player(list(off[2]))[1]
    for row, _state, pairs, _ex in wester:
        assert "flockFantasySf" in _layer_c(row, pairs).kept


def test_every_dissent_sits_inside_tau_c_so_the_property_is_not_vacuous():
    """Each placed dissent is beyond the incumbent's band but within V2.1's
    corroboration threshold of the consensus (a gross, uncorroborated tail is a
    different, separately tested case)."""
    tau = op.effective_tau_c_big(si.load_thresholds().tau_c_big)
    for row, _state, pairs, excluded in PANELS:
        if not excluded:
            continue
        curve = _curve(row["class"])
        values = dict(pairs)
        consensus = min(values[k] for k in values if k not in excluded)
        for k in excluded:
            dist = abs(op.rank_coordinate(values[k], curve) - op.rank_coordinate(consensus, curve))
            assert 0.0 < dist < tau, (row["player"], k, dist)


# ── integration: the full pipeline, V2.1-NOHIST ────────────────────────

_TEAMS = ("BUF", "MIA", "NE", "NYJ", "KC", "DEN", "LV", "LAC", "DAL", "PHI")
_OFF_POS = ("QB", "RB", "WR", "TE")
#: The fixture's offense sources, each with its own CSV shape (rank boards).
_RANK_BOARDS = (
    "flockFantasySf",
    "fantasyNavigatorSf",
    "otcffbSf",
    "pfkDynasty",
    "yahooBoone",
    "dlfSf",
    "fantasyProsFitzmaurice",
    "dynastyNerdsSfTep",
    "fantasyCalc",
)
_CSV_FILE = {
    "flockFantasySf": "flockFantasySf.csv",
    "fantasyNavigatorSf": "fantasyNavigatorSf.csv",
    "otcffbSf": "otcffbSf.csv",
    "pfkDynasty": "pfkDynasty.csv",
    "yahooBoone": "yahooBoone.csv",
    "dlfSf": "dlfSf.csv",
    "fantasyProsFitzmaurice": "fantasyProsFitzmaurice.csv",
    "dynastyNerdsSfTep": "dynastyNerdsSfTep.csv",
    "fantasyCalc": "fantasyCalc.csv",
    "draftSharks": "draftSharksSf.csv",
}


def _value_at_rank(rank: float) -> float:
    """The offense Hill value whose Layer C coordinate is ``ln(10 + rank)``."""
    c, s = op.scope_curve("offense")
    return 9999.0 / (1.0 + (rank / op.REFERENCE_N / c) ** s)


def _fixture_offense_rows():
    """Fixture rows priced in the served (flag-OFF) state, offense or rookie."""
    return [r for r in ROWS if r["class"] in ("offense", "rookie") and r["before"] is not None]


def _board():
    """``(payload, csvs, dissent pairs, positions)``: a synthetic board whose
    offense rows include every priced fixture offense row under its own name,
    position and value level; every vote of a fixture row that the incumbent
    excluded in the served state is a legitimate dissent on that source's own
    board (a well-formed row, moved to the rank whose consensus value is the
    dissent value)."""
    fixture = {r["player"]: r for r in _fixture_offense_rows()}
    players: dict[str, dict] = {}
    # Consensus order: the fixture rows (by their served value) spread over the
    # board's ranks, fillers elsewhere; every row's consensus value is the
    # offense Hill value at its rank, so payload and rank boards agree.
    n_ranks = 300
    by_rank: dict[int, tuple[str, str]] = {}
    for i, r in enumerate(sorted(fixture.values(), key=lambda r: (-r["before"], r["player"]))):
        by_rank[15 + 10 * i] = (r["player"], r["position"])
    filler = 0
    for rank in range(1, n_ranks + 1):
        if rank not in by_rank:
            filler += 1
            by_rank[rank] = (f"Filler Vet {filler:03d}", _OFF_POS[rank % 4])
    order: list[tuple[str, str, float]] = []  # (name, position, consensus value)
    for i, rank in enumerate(sorted(by_rank)):
        name, pos = by_rank[rank]
        value = round(_value_at_rank(rank), 1)
        cls = fixture.get(name, {}).get("class")
        players[name] = {
            "position": pos,
            "team": _TEAMS[i % len(_TEAMS)],
            "age": 22 if cls == "rookie" else 25,
            "_sleeperId": str(5000 + i),
            "_yearsExp": 0 if cls == "rookie" else 3,
            "_isRookie": cls == "rookie",
            "_canonicalSiteValues": {"idpTradeCalc": value, "ktcCrowdSfTep": value},
            "idpTradeCalc": value,
            "ktcCrowdSfTep": value,
        }
        order.append((name, pos, value))
    consensus = {n: v for n, _p, v in order}
    dissents: set[tuple[str, str]] = set()
    # Payload-carried sources: the dissent is the payload value itself.
    for name, row in fixture.items():
        for source in ("idpTradeCalc", "ktcCrowdSfTep"):
            if source in row["outlierExcludedBefore"]:
                d = round(_dissent_value(consensus[name], name, "OFF"), 1)
                players[name]["_canonicalSiteValues"][source] = d
                players[name][source] = d
                dissents.add((name, source))
    # IDP: filler defenders on the IDPTC payload, plus the three DBs the
    # freshness schedule left unpriced -- they vote through FantasyPros IDP only.
    idp: list[tuple[str, str]] = []
    for i in range(45):
        name, pos = f"Filler Idp {i + 1:03d}", ("DL", "LB", "DB")[i % 3]
        value = 4500.0 - 60.0 * i
        players[name] = {
            "position": pos,
            "team": _TEAMS[(i + 3) % len(_TEAMS)],
            "age": 26,
            "_sleeperId": str(7000 + i),
            "_yearsExp": 4,
            "_canonicalSiteValues": {"idpTradeCalc": value},
            "idpTradeCalc": value,
        }
        idp.append((name, pos))
    for j, name in enumerate(UNPRICED_DBS):
        players[name] = {
            "position": "DB",
            "team": _TEAMS[j],
            "age": 27,
            "_sleeperId": str(7900 + j),
            "_yearsExp": 5,
            "_canonicalSiteValues": {},
        }
        idp.append((name, "DB"))

    by_source: dict[str, list[tuple[str, str]]] = {}
    for source in (*_RANK_BOARDS, "draftSharks"):
        ranked = [(n, p) for n, p, _v in order]
        for name, row in fixture.items():
            if source not in row["outlierExcludedBefore"]:
                continue
            target = _dissent_value(consensus[name], name, "OFF")
            ranked.remove((name, players[name]["position"]))
            at = min(range(len(ranked)), key=lambda i: abs(order[i][2] - target))
            ranked.insert(at, (name, players[name]["position"]))
            dissents.add((name, source))
        by_source[source] = ranked

    csvs: dict[str, str] = {}
    for source, ranked in by_source.items():
        lines: list[str]
        if source == "draftSharks":
            lines = ["Rank,Team,Player,Fantasy Position,ADP,Bye,Age,3D Value +"] + [
                f"{r},{players[n]['team']},{n},{p},0,0,{players[n]['age']},{round(100 - r * 0.3, 1)}"
                for r, (n, p) in enumerate(ranked, 1)
            ]
        elif source == "pfkDynasty":
            lines = ["name,value,rank,sleeper_id"] + [
                f"{n},{10000 - r * 40},{r},{players[n]['_sleeperId']}"
                for r, (n, _p) in enumerate(ranked, 1)
            ]
        elif source == "yahooBoone":
            lines = ["name,pos,rank,boone_value"] + [
                f"{n},{p},{r},{max(1, 300 - r)}" for r, (n, p) in enumerate(ranked, 1)
            ]
        elif source == "fantasyProsFitzmaurice":
            lines = ["name,team,position,value,rank"] + [
                f"{n},{players[n]['team']},{p},{max(1, 300 - r)},{r}"
                for r, (n, p) in enumerate(ranked, 1)
            ]
        elif source == "dynastyNerdsSfTep":
            lines = ["Name,Rank,Value,SleeperId,Pos,Team"] + [
                f"{n},{r},{10000 - r * 50},{players[n]['_sleeperId']},{p},{players[n]['team']}"
                for r, (n, p) in enumerate(ranked, 1)
            ]
        elif source in ("otcffbSf", "fantasyNavigatorSf", "fantasyCalc"):
            lines = ["name,value,rank"] + [
                f"{n},{10000 - r * 40},{r}" for r, (n, _p) in enumerate(ranked, 1)
            ]
        elif source == "dlfSf":
            lines = ["name,rank,value"] + [f"{n},{r}," for r, (n, _p) in enumerate(ranked, 1)]
        else:  # flockFantasySf
            lines = ["name,Rank"] + [f"{n},{r}" for r, (n, _p) in enumerate(ranked, 1)]
        csvs[_CSV_FILE[source]] = "\n".join(lines) + "\n"
    fpi = [
        "name,originalRank,effectiveRank,derivationMethod,family,normalizedValue,"
        "matchedSourceName,position,team"
    ] + [
        f"{n},{r},{r},direct,{p},0,{n},{p},{players[n]['team']}" for r, (n, p) in enumerate(idp, 1)
    ]
    csvs["fantasyProsIdp.csv"] = "\n".join(fpi) + "\n"
    payload = {
        "version": "oiv21-l3-synth",
        "date": "2026-10-20",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }
    return payload, csvs, dissents


PAYLOAD, CSVS, DISSENTS = _board()


def _build(flags=(), *, overrides=None):
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        d = Path(tmp) / "CSVs" / "site_raw"
        d.mkdir(parents=True)
        for name, text in CSVS.items():
            (d / name).write_text(text)
        with _flags(*flags), si.history_override(None):
            return dc.build_api_data_contract(
                json.loads(json.dumps(PAYLOAD)), csv_root=Path(tmp), source_overrides=overrides
            )


def _rows(contract):
    return {r["displayName"]: r for r in contract["playersArray"]}


@pytest.fixture(scope="module")
def incumbent():
    return _build()


@pytest.fixture(scope="module")
def v21_nohist():
    return _build(V21_ON)


def _v21_exclusion(row, source):
    """The V2.1 layer and reason that kept ``source`` out of ``row``'s blend, or
    ``None``.  Layer C's ``rejected_tail`` counts; non-V2.1 exclusions
    (freshness, declared range, non-positive values) are not V2.1's."""
    meta = (row.get("sourceRankMeta") or {}).get(source) or {}
    integ = meta.get("integrity") or {}
    if integ.get("status") in _V21_EXCLUSION_STATUSES:
        return integ.get("status"), integ.get("primaryReason")
    stamp = (row.get("sourceIntegrity") or {}).get(source) or {}
    if stamp.get("status") in _V21_EXCLUSION_STATUSES:
        return stamp.get("status"), stamp.get("primaryReason")
    return None


def test_board_carries_every_priced_fixture_offense_row_and_its_dissents(v21_nohist):
    rows = _rows(v21_nohist)
    fixture = _fixture_offense_rows()
    assert {r["player"] for r in fixture} <= set(rows)
    expected = {(r["player"], s) for r in fixture for s in r["outlierExcludedBefore"]}
    assert DISSENTS == expected
    assert ("LaJohntay Wester", "flockFantasySf") in DISSENTS


def test_incumbent_drops_wester_flock_vote_on_the_synthetic_board(incumbent):
    """The board exercises the fixture's mechanism end to end: the served
    filter removes Wester's legitimate Flock vote."""
    meta = _rows(incumbent)["LaJohntay Wester"]["sourceRankMeta"]["flockFantasySf"]
    assert meta.get("hampelDropped") is True


def test_v21_nohist_drops_no_vote_on_any_fixture_row(v21_nohist):
    """§7.4 L3 at pipeline level: on every fixture row, no V2.1 layer (A
    refusal, B0 / B3 quarantine, B1 withhold, B2 withhold, B4 hold, Layer C
    drop) excludes any vote -- the fixture's dissents included."""
    rows = _rows(v21_nohist)
    dropped = []
    for r in _fixture_offense_rows():
        row = rows[r["player"]]
        for source in row.get("sourceRankMeta") or {}:
            got = _v21_exclusion(row, source)
            if got is not None:
                dropped.append((r["player"], source, got))
        for source in row.get("sourceIntegrity") or {}:
            got = _v21_exclusion(row, source)
            if got is not None:
                dropped.append((r["player"], source, got))
    assert dropped == []


def test_v21_nohist_keeps_every_fixture_dissent_in_the_blend(v21_nohist):
    rows = _rows(v21_nohist)
    for player, source in sorted(DISSENTS):
        meta = rows[player]["sourceRankMeta"][source]
        assert meta.get("contributedToBlend") is not False, (player, source)
        assert not meta.get("hampelDropped"), (player, source)
        assert not meta.get("excludedReason"), (player, source)
        category = (meta.get("integrity") or {}).get("category")
        assert category not in vs.INVALID_OBSERVATION_CATEGORIES, (player, source, category)


def test_v21_nohist_wester_flock_vote_counts(v21_nohist, incumbent):
    """Wester's value moves only because his Flock vote is kept: V2.1 prices
    him above the incumbent, which dropped it."""
    v21 = _rows(v21_nohist)["LaJohntay Wester"]
    inc = _rows(incumbent)["LaJohntay Wester"]
    assert v21["sourceRankMeta"]["flockFantasySf"].get("contributedToBlend") is not False
    assert v21["rankDerivedValue"] > inc["rankDerivedValue"]


def test_v21_nohist_no_fixture_vote_is_labelled_invalid(v21_nohist):
    """R7 / directive §10: a vote that passed A and B is never shown as an
    invalid identity, format, normalization or broken-feed observation."""
    rows = _rows(v21_nohist)
    for r in _fixture_offense_rows():
        for source, meta in (rows[r["player"]].get("sourceRankMeta") or {}).items():
            category, _reason = si.observation_category(meta)
            assert category not in vs.INVALID_OBSERVATION_CATEGORIES, (r["player"], source)


# ── the three newly unpriced IDP DBs ───────────────────────────────────


def test_unpriced_dbs_are_the_fixture_rows():
    rows = {r["player"]: r for r in ROWS}
    for name in UNPRICED_DBS:
        assert rows[name]["pricing"] == "newly_unpriced"
        assert rows[name]["votesStopped"] == ["fantasyProsIdp"]
        assert rows[name]["position"] == "DB"


@pytest.mark.parametrize("name", UNPRICED_DBS)
def test_v21_nohist_keeps_the_dbs_sole_fantasypros_vote(v21_nohist, name):
    """Served state (freshness v2 off): FantasyPros IDP is each DB's only vote.
    A single legitimate vote is never removed by V2.1 at cold start (Layer C
    abstains below two providers; Layer A / B find nothing), so the DB is
    priced exactly as the incumbent prices it."""
    row = _rows(v21_nohist)[name]
    assert _v21_exclusion(row, "fantasyProsIdp") is None
    assert row["sourceRankMeta"]["fantasyProsIdp"].get("contributedToBlend") is not False
    assert isinstance(row.get("rankDerivedValue"), (int, float)) and row["rankDerivedValue"] > 0


@pytest.mark.parametrize("name", UNPRICED_DBS)
def test_dbs_priced_identically_by_v21_and_the_incumbent(v21_nohist, incumbent, name):
    assert _rows(v21_nohist)[name]["rankDerivedValue"] == _rows(incumbent)[name]["rankDerivedValue"]


@pytest.mark.parametrize("flags", [(), V21_ON], ids=["incumbent", "v21"])
def test_when_the_fantasypros_vote_stops_the_dbs_are_unpriced_never_zero(flags):
    """The fixture's ON state: the FantasyPros IDP vote stops (there, a
    freshness exclusion; here, the same observation withdrawn).  The DB has no
    vote left, so it is UNPRICED: no value, never 0 -- and V2.1 labels nothing
    on it as invalid, because nothing on it was judged invalid."""
    rows = _rows(_build(flags, overrides={"fantasyProsIdp": {"include": False}}))
    for name in UNPRICED_DBS:
        row = rows.get(name)
        if row is None:
            continue  # absent from the board entirely: missing, not zero
        value = row.get("rankDerivedValue")
        assert value is None, (name, value)  # unpriced: never 0, never a NaN stand-in
        for source in row.get("sourceIntegrity") or {}:
            assert _v21_exclusion(row, source) is None
