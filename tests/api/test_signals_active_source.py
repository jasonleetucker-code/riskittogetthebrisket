"""Signals as an ACTIVE canonical source — the contract half (owner 2026-10-03).

Proves, through the production entry point ``build_api_data_contract`` on a
SYNTHETIC raw payload and SYNTHETIC private Signals board CSVs (written by the
real owner, ``src/sources/signals.py``), that:

1/3  a native VALUE contributes to offense / IDP canonical valuation;
2/4  a row with no value but a cross-position rank contributes as the RANK
     fallback (structurally inert on today's payloads — neither dataset
     publishes such a rank — but implemented and pinned);
6-8  the offense board is Superflex, not TE-premium: the board's base -> TE++
     conversion applies exactly once and no league adjustment is re-applied;
10/11/16  one Signals observation per row, inside the FantasyCalc family —
     the family's authority is capped at one provider and it is ONE family
     to the confidence gate (no independence bonus);
12   missing is never zero: an unprovisioned host has no Signals key on any
     row, no error in either lane, and a provisioned host whose board
     vanished IS an error;
13   the rollback flag removes the vote but keeps the evidence visible;
14   the public /league payload guard refuses every Signals carrier.

Nothing here reads the live board, the network or a real session.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.api import feature_flags
from src.api.data_contract import (
    PRIVATE_SOURCE_MISSING,
    PRIVATE_SOURCE_NOT_PROVISIONED,
    PRIVATE_SOURCE_PRESENT,
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    build_api_data_contract,
    private_source_availability,
    validate_api_data_contract,
)
from src.sources import signals as S

SIGNALS_KEYS = ("signalsSf", "signalsIdpDl", "signalsIdpLb", "signalsIdpDb")
N_OFF = 140
N_IDP = 140
OFF_POS = ("QB", "RB", "WR", "TE")
IDP_POS = ("DL", "LB", "DB")
SIGNALS_IDP_RAW = {"DL": "DE", "LB": "LB", "DB": "CB"}


def _off(i: int) -> str:
    return f"Synthetic Off {i:03d}"


def _idp(i: int) -> str:
    return f"Synthetic Idp {i:03d}"


def _raw_payload() -> dict:
    """Offense rows priced by KTC Crowd + IDPTC + FantasyCalc; IDP rows by
    the IDPTC backbone + DraftSharks IDP + DLF IDP.  Sleeper ids on every
    row so the Signals CSV joins ID-grade."""
    players: dict[str, dict] = {}
    market = 9500
    for i in range(max(N_OFF, N_IDP)):
        if i < N_OFF:
            sites = {"ktcCrowdSfTep": market, "idpTradeCalc": market, "fantasyCalc": market}
            players[_off(i)] = {
                "_canonicalSiteValues": dict(sites),
                **sites,
                "position": OFF_POS[i % 4],
                "_sleeperId": str(10000 + i),
                "age": 25,
            }
            market -= 23
        if i < N_IDP:
            sites = {"idpTradeCalc": market, "draftSharksIdp": market, "dlfIdp": market}
            players[_idp(i)] = {
                "_canonicalSiteValues": dict(sites),
                **sites,
                "position": IDP_POS[i % 3],
                "_sleeperId": str(20000 + i),
                "age": 26,
            }
            market -= 19
    return {
        "version": "signals-active-fixture",
        "date": "2026-10-03",
        "scrapeTimestamp": "2026-10-03T14:00:00Z",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }


def _obs(sid: str, name: str, pos: str, *, value=None, cross=None, raw=None) -> dict:
    return {
        "sleeperId": sid,
        "name": name,
        "position": pos,
        "rawPosition": raw,
        "team": None,
        "nativeValue": value,
        "positionalRank": 3,
        "crossPositionRank": cross,
        "valueAsOf": "2026-10-03T11:30:00Z",
    }


# Offense: Signals values every offense row EXCEPT 10-19; 20 is the RANK
# fallback row (no value, a cross-position rank); 30 has a positional rank
# only (must stay missing).  Signals orders rows 0..9 in REVERSE of the
# market so its vote visibly disagrees.
OFF_FALLBACK = 20
OFF_POSITIONAL_ONLY = 30
OFF_UNCOVERED = range(10, 20)
IDP_FALLBACK = 21
IDP_UNCOVERED = range(10, 20)


def _signals_observations() -> tuple[list[dict], list[dict]]:
    off: list[dict] = []
    for i in range(N_OFF):
        if i in OFF_UNCOVERED:
            continue
        sid, name, pos = str(10000 + i), _off(i), OFF_POS[i % 4]
        if i == OFF_FALLBACK:
            off.append(_obs(sid, name, pos, cross=25))
        elif i == OFF_POSITIONAL_ONLY:
            off.append(_obs(sid, name, pos))
        else:
            value = 9000 - 50 * (9 - i) if i < 10 else 8000 - 40 * i
            off.append(_obs(sid, name, pos, value=float(value)))
    idp: list[dict] = []
    for i in range(N_IDP):
        if i in IDP_UNCOVERED:
            continue
        sid, name, fam = str(20000 + i), _idp(i), IDP_POS[i % 3]
        if i == IDP_FALLBACK:
            idp.append(_obs(sid, name, fam, cross=12, raw=SIGNALS_IDP_RAW[fam]))
        else:
            idp.append(_obs(sid, name, fam, value=float(4900 - 30 * i), raw=SIGNALS_IDP_RAW[fam]))
    return off, idp


def _write_store(root: Path, *, marker: bool = True, boards: bool = True) -> None:
    store = root / "data" / "sources" / "signals"
    if marker:
        (store / "values").mkdir(parents=True, exist_ok=True)
        (store / "values" / S.PROVISIONED_MARKER).write_text("{}", encoding="utf-8")
    if boards:
        off, idp = _signals_observations()
        for spec, obs in ((S.VALUE_DATASETS["offense"], off), (S.VALUE_DATASETS["idp"], idp)):
            rows, _ = S.build_board_rows(obs, spec)
            for key in spec.output_keys():
                board = [r for r in rows if spec.board_key_for(r) == key]
                path = S.board_csv_path(store, key)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(S.render_board_csv(board), encoding="utf-8")


def _build(root: Path) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(_raw_payload(), csv_root=root)


def _rows(contract: dict) -> dict[str, dict]:
    return {str(r.get("displayName")): r for r in contract.get("playersArray") or []}


@contextlib.contextmanager
def _idp_promoted():
    """``signals_idp_shared_market`` ON — the promotion switch, exercised
    through the real flag (env + reload), not by editing the hold table."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET", "1")
        feature_flags.reload()
        try:
            yield
        finally:
            mp.delenv("RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET")
            feature_flags.reload()


@pytest.fixture(scope="module")
def boards(tmp_path_factory):
    """Built with Signals IDP PROMOTED (voting through the shared-market
    family crosswalk), so the voting mechanics stay pinned for the day the
    promotion gate passes."""
    on = tmp_path_factory.mktemp("signals_on")
    _write_store(on)
    off = tmp_path_factory.mktemp("signals_off")
    with _idp_promoted():
        with_signals = _build(on)
        without = _build(off)
    return with_signals, without


@pytest.fixture(scope="module")
def held(tmp_path_factory):
    """The shipped configuration: offense votes, IDP is collected but HELD."""
    on = tmp_path_factory.mktemp("signals_held")
    _write_store(on)
    off = tmp_path_factory.mktemp("signals_held_off")
    return _build(on), _build(off)


def _voted(meta: dict | None) -> bool:
    return (
        isinstance(meta, dict)
        and meta.get("contributedToBlend") is not False
        and not meta.get("hampelDropped")
        and isinstance(meta.get("valueContribution"), (int, float))
        and float(meta.get("appliedWeight") or 0) > 0
    )


# ── 1 / 3: native value contributes ─────────────────────────────────────


class TestNativeValueContributes:
    def test_offense(self, boards):
        rows = _rows(boards[0])
        row = rows[_off(40)]
        meta = row["sourceRankMeta"]["signalsSf"]
        assert _voted(meta)
        assert row["sourceNativeValues"]["signalsSf"] == 6400.0
        # the rank it voted with is DERIVED from Signals' value ordering
        off_obs, _ = _signals_observations()
        higher = sum(1 for o in off_obs if (o["nativeValue"] or 0) > 6400.0)
        assert row["sourceOriginalRanks"]["signalsSf"] == float(higher + 1)
        assert boards[0]["privateSourceAvailability"]["signalsSf"]["votes"] is True

    def test_a_disagreeing_signals_vote_goes_through_the_same_outlier_filter(self, boards):
        """Rows 0-9 are ordered in REVERSE by Signals; the existing per-row
        Hampel filter treats the vote like any other source's — no exemption."""
        meta = _rows(boards[0])[_off(0)]["sourceRankMeta"]["signalsSf"]
        assert meta["effectiveRank"] == 10

    def test_idp_through_the_shared_market_family_ladder(self, boards):
        rows = _rows(boards[0])
        row = rows[_idp(0)]  # a DL
        meta = row["sourceRankMeta"]["signalsIdpDl"]
        assert _voted(meta)
        assert meta["scope"] == "position_idp" and meta["positionGroup"] == "DL"
        assert meta["method"] != "fallback"
        # Provenance reports the OUTCOME: crosswalked onto the bridge's
        # shared-market family ladder (review of the shadow round).
        assert meta["sharedMarketTranslated"] is True
        assert meta["rankCoordinatePool"] == "shared_market"
        assert row["sourceNativeValues"]["signalsIdpDl"] == 4900.0

    def test_signals_moves_the_board(self, boards):
        """It is a vote, not a decoration: the canonical values change."""
        with_s, without = (_rows(b) for b in boards)
        moved = [
            n
            for n in with_s
            if with_s[n].get("rankDerivedValue") != without[n].get("rankDerivedValue")
        ]
        assert any(n.startswith("Synthetic Off") for n in moved)
        assert any(n.startswith("Synthetic Idp") for n in moved)


# ── 2 / 4: rank fallback ─────────────────────────────────────────────────


class TestRankFallback:
    def test_a_cross_position_rank_without_a_value_votes_as_rank(self, boards):
        row = _rows(boards[0])[_off(OFF_FALLBACK)]
        assert _voted(row["sourceRankMeta"]["signalsSf"])
        assert "signalsSf" not in (row.get("sourceNativeValues") or {})  # RANK basis
        assert "signalsSf" in row["sourceOriginalRanks"]

    def test_an_idp_cross_position_rank_is_never_read_as_a_family_rank(self, boards, held):
        """The IDP crosswalk translates a WITHIN-FAMILY rank, and Signals'
        only within-family order is its native values.  A cross-position
        rank with no value (inert today: the IDP dataset publishes none) is
        not "the k-th DL" and is withheld, voting or shadow."""
        promoted = _rows(boards[0])[_idp(IDP_FALLBACK)]
        assert "signalsIdpDl" not in (promoted.get("sourceRankMeta") or {})
        withheld = boards[0]["crossPositionBridges"]["withheldFamilyCrosswalk"]
        assert withheld["signalsIdpDl"]["not_a_within_family_rank"] == 1
        shadow = _rows(held[0])[_idp(IDP_FALLBACK)]["sourceShadowMeta"]["signalsIdpDl"]
        assert shadow["withheldReason"] == "not_a_within_family_rank"
        assert shadow["wouldContribute"] is None

    def test_a_positional_rank_alone_never_votes(self, boards):
        row = _rows(boards[0])[_off(OFF_POSITIONAL_ONLY)]
        assert "signalsSf" not in (row.get("canonicalSiteValues") or {})
        assert "signalsSf" not in (row.get("sourceRankMeta") or {})


# ── 6-8: Superflex, non-TEP, converted exactly once ─────────────────────


def test_te_rows_take_the_board_te_conversion_exactly_once(boards):
    rows = _rows(boards[0])
    te = next(
        r
        for n, r in rows.items()
        if n.startswith("Synthetic Off")
        and r.get("position") == "TE"
        and "signalsSf" in (r.get("sourceRankMeta") or {})
    )
    meta = te["sourceRankMeta"]["signalsSf"]
    assert meta.get("tepBoostApplied") is True
    assert meta.get("tepBasisFrom") == "base"
    assert not meta.get("tepNativeCorrectionApplied")
    reg = {s["key"]: s for s in _RANKING_SOURCES}
    assert reg["signalsSf"]["is_tep_premium"] is False
    assert S.VALUE_DATASETS["offense"].format["superflex"] is True
    assert S.VALUE_DATASETS["offense"].format["leagueAdjusted"] is False


# ── 10 / 11 / 16: one family, no double vote, cap holds ─────────────────


class TestOneFamily:
    def test_registry_shape(self):
        reg = {s["key"]: s for s in _RANKING_SOURCES}
        assert reg["signalsSf"]["scope"] == "overall_offense" and not reg["signalsSf"].get(
            "extra_scopes"
        )
        for fam in ("Dl", "Lb", "Db"):
            k = f"signalsIdp{fam}"
            assert reg[k]["scope"] == "position_idp" and reg[k]["position_group"] == fam.upper()
            assert not reg[k].get("extra_scopes") and not reg[k].get(
                "needs_shared_market_translation"
            )
        assert "signalsIdp" not in reg
        assert {reg[k]["correlation_group"] for k in SIGNALS_KEYS} == {"fantasyCalc"}
        for key in SIGNALS_KEYS:
            assert _SOURCE_CSV_PATHS[key]["signal"] == "rank"
            assert reg[key]["game_type"] == "DYNASTY"

    def test_one_signals_vote_per_row(self, boards):
        for row in boards[0]["playersArray"]:
            keys = {k for k in (row.get("sourceRankMeta") or {}) if k.startswith("signals")}
            assert len(keys) <= 1, row.get("displayName")

    def test_fantasycalc_and_signals_share_one_providers_authority(self, boards):
        rows = _rows(boards[0])
        capped = 0
        for name, row in rows.items():
            meta = row.get("sourceRankMeta") or {}
            fam = [m for k, m in meta.items() if k in ("fantasyCalc", "signalsSf") and _voted(m)]
            if len(fam) == 2:
                total = sum(float(m["appliedWeight"]) for m in fam)
                assert total <= 1.0 + 1e-6, name
                capped += 1
        assert capped > 50

    def test_no_independence_bonus_on_offense(self, boards):
        with_s, without = (_rows(b) for b in boards)
        row_on, row_off = with_s[_off(0)], without[_off(0)]
        assert row_on["independentSourceCount"] == row_off["independentSourceCount"]

    def test_on_idp_rows_signals_is_its_own_family(self, boards):
        """FantasyCalc publishes no IDP, so the shared group adds ONE family
        on an IDP row Signals covers — stated, not hidden (review N1)."""
        with_s, without = (_rows(b) for b in boards)
        # The top DL: above the fixture's coverage gap, and a row where no
        # other source sits outside the outlier window (the synthetic
        # IDPTC's value-direct price runs high against the Hill-priced
        # specialists deeper down, so an added agreeing vote can Hampel-drop
        # it there — a fixture artifact, not a family question).
        row_on, row_off = with_s[_idp(0)], without[_idp(0)]
        assert row_on["independentSourceCount"] == row_off["independentSourceCount"] + 1


# ── the shared-market family crosswalk (2026-10-04; replaces review B1's
#    IDP-local positional route) ───────────────────────────────────────────


def _shared_market_family_ladder(group: str, raw: dict | None = None) -> list[int]:
    """COMBINED offense+IDP ranks of each ``group`` member on the bridge's
    (IDPTC's) pool — recomputed independently from the fixture's values,
    with the bridge owner's ordering (value desc, displayName)."""
    players = (raw or _raw_payload())["players"]
    pool = [
        (float(p["idpTradeCalc"]), n, p["position"])
        for n, p in players.items()
        if float(p.get("idpTradeCalc") or 0) > 0
    ]
    pool.sort(key=lambda t: (-t[0], t[1].lower()))
    return [i for i, (_v, _n, pos) in enumerate(pool, start=1) if pos == group]


def _idp_local_family_ladder(group: str) -> list[int]:
    """The RETIRED route's ladder: IDP-only ranks of each ``group`` member."""
    idp = [
        (p["idpTradeCalc"], n, p["position"])
        for n, p in _raw_payload()["players"].items()
        if p["position"] in IDP_POS
    ]
    idp.sort(key=lambda t: (-t[0], t[1].lower()))
    return [i for i, (_v, _n, pos) in enumerate(idp, start=1) if pos == group]


class TestSharedMarketFamilyCrosswalk:
    @pytest.mark.parametrize("group", ["DL", "LB", "DB"])
    def test_family_rank_k_lands_where_the_kth_of_that_family_sits_on_the_market(
        self, boards, group
    ):
        ladder = _shared_market_family_ladder(group)
        key = f"signalsIdp{group.title()}"
        seen = 0
        for row in boards[0]["playersArray"]:
            meta = (row.get("sourceRankMeta") or {}).get(key)
            if not meta:
                continue
            assert row["position"] == group
            assert meta["effectiveRank"] == ladder[int(meta["rawRank"]) - 1], row["displayName"]
            assert meta["rankCoordinatePool"] == "shared_market"
            seen += 1
        assert seen > 20

    def test_the_shared_market_ladder_is_not_the_idp_local_one(self):
        """The fixture interleaves offense and IDP on IDPTC, so the two
        coordinate systems genuinely differ — the tests above would catch a
        regression to the IDP-local route."""
        for group in IDP_POS:
            assert _shared_market_family_ladder(group) != _idp_local_family_ladder(group)

    def test_every_family_board_starts_at_one(self, boards):
        """No cross-family order: each family's best Signals row carries
        within-family rank 1, whatever the other families' values are."""
        firsts = {}
        for row in boards[0]["playersArray"]:
            for key in SIGNALS_KEYS[1:]:
                if (row.get("sourceOriginalRanks") or {}).get(key) == 1.0:
                    firsts[key] = row["displayName"]
        assert set(firsts) == set(SIGNALS_KEYS[1:])

    def test_a_db_number_one_lands_where_the_first_db_sits_not_at_market_one(self, boards):
        rows = _rows(boards[0])
        db1 = next(
            r
            for r in rows.values()
            if (r.get("sourceOriginalRanks") or {}).get("signalsIdpDb") == 1.0
        )
        meta = db1["sourceRankMeta"]["signalsIdpDb"]
        assert meta["rawRank"] == 1
        assert meta["effectiveRank"] == _shared_market_family_ladder("DB")[0] > 1

    def test_signals_idp_prices_in_the_same_coordinates_as_its_peers(self, boards):
        """THE regression the hold existed for.  On the retired route an LB
        the backbone ranked IDP #4 contributed 9,484 against 5,238-5,668 from
        the row's other sources.  The fixture's sources all agree on order,
        so every Signals IDP vote must now sit within a few percent of the
        shared-market specialist (``dlfIdp``) on the same row, and none may
        be outlier-dropped."""
        compared = 0
        for row in boards[0]["playersArray"]:
            # Rows above the fixture's coverage gap (10-19 are absent from
            # Signals): below it, Signals' within-family rank is relative to
            # its own coverage — the 4th DB it lists is the 7th the market
            # lists — a property of every rank crosswalk, measured on the
            # production board by the shadow evaluation rather than hidden.
            if int(str(row["displayName"])[-3:]) >= 10:
                continue
            metas = row.get("sourceRankMeta") or {}
            peer = metas.get("dlfIdp")
            for key in SIGNALS_KEYS[1:]:
                meta = metas.get(key)
                if not meta or not peer or "valueContribution" not in peer:
                    continue
                assert not meta.get("hampelDropped"), (row["displayName"], key)
                a, b = float(meta["valueContribution"]), float(peer["valueContribution"])
                assert abs(a - b) <= 0.08 * max(a, b), (row["displayName"], key, a, b)
                compared += 1
        assert compared >= 6

    def test_no_bridge_means_the_vote_is_withheld_not_passed_through(self, tmp_path):
        """Without a usable bridge (no IDPTC IDP values) there is no family
        ladder; the raw within-family rank must NOT be voted."""
        _write_store(tmp_path)
        raw = _raw_payload()
        for p in raw["players"].values():
            if p["position"] in IDP_POS:
                p.pop("idpTradeCalc", None)
                p["_canonicalSiteValues"].pop("idpTradeCalc", None)
        with _idp_promoted(), contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(raw, csv_root=tmp_path)
        for row in contract["playersArray"]:
            for key in SIGNALS_KEYS[1:]:
                meta = (row.get("sourceRankMeta") or {}).get(key)
                assert not meta, (row["displayName"], key, meta)
        withheld = (contract.get("crossPositionBridges") or {}).get("withheldFamilyCrosswalk")
        assert sum((withheld or {}).get(k, {}).get("no_family_ladder", 0) for k in SIGNALS_KEYS[1:])

    def test_a_rank_past_the_familys_market_depth_is_withheld_not_extrapolated(self, tmp_path):
        """Candidate A: k deeper than the market's own LB list has no
        measured market position.  Drop IDPTC from the deepest LBs so the
        Signals LB board runs past the family ladder."""
        _write_store(tmp_path)
        raw = _raw_payload()
        lbs = [n for n, p in raw["players"].items() if p["position"] == "LB"]
        for name in lbs[-15:]:
            raw["players"][name].pop("idpTradeCalc", None)
            raw["players"][name]["_canonicalSiteValues"].pop("idpTradeCalc", None)
        with _idp_promoted(), contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(raw, csv_root=tmp_path)
        depth = len(_shared_market_family_ladder("LB", raw))
        for row in contract["playersArray"]:
            meta = (row.get("sourceRankMeta") or {}).get("signalsIdpLb")
            if meta:
                assert int(meta["rawRank"]) <= depth
                assert meta["method"] != "extrapolated"
        withheld = (contract.get("crossPositionBridges") or {}).get("withheldFamilyCrosswalk")
        assert (withheld or {}).get("signalsIdpLb", {}).get("beyond_family_ladder", 0) > 0

    def test_a_family_mismatch_with_our_position_casts_no_vote(self, boards):
        """A Signals DB board row joined to a row WE hold as DL is not
        scope-eligible: the DB board never prices a DL row."""
        for row in boards[0]["playersArray"]:
            for key, grp in zip(SIGNALS_KEYS[1:], ("DL", "LB", "DB")):
                if (row.get("sourceRankMeta") or {}).get(key):
                    assert row["position"] == grp
            for key, grp in zip(SIGNALS_KEYS[1:], ("DL", "LB", "DB")):
                if (row.get("sourceShadowMeta") or {}).get(key):
                    assert row["position"] == grp


# ── 12: missing is never zero; not provisioned is not an error ──────────


class TestMissingAndProvisioning:
    def test_uncovered_rows_carry_no_signals_key(self, boards):
        rows = _rows(boards[0])
        for i in OFF_UNCOVERED:
            assert "signalsSf" not in (rows[_off(i)].get("canonicalSiteValues") or {})
        for i in IDP_UNCOVERED:
            sites = rows[_idp(i)].get("canonicalSiteValues") or {}
            assert not any(k in sites for k in SIGNALS_KEYS[1:])

    def test_an_unprovisioned_host_carries_nothing_and_raises_nothing(self, boards):
        contract = boards[1]
        state = contract["privateSourceAvailability"]
        assert state["signalsSf"]["state"] == PRIVATE_SOURCE_NOT_PROVISIONED
        assert state["signalsSf"]["votes"] is False
        for row in contract["playersArray"]:
            for key in SIGNALS_KEYS:
                assert key not in (row.get("canonicalSiteValues") or {})
                assert key not in ((row.get("sourceAudit") or {}).get("expectedSources") or [])
        report = validate_api_data_contract(contract)
        assert not [e for e in report["errors"] if "signals" in e]
        assert "private_source_absent_by_design:signalsSf" in report["warnings"]
        ts = contract["dataFreshness"]["sourceTimestamps"]["signalsSf"]
        assert ts["staleness"] == PRIVATE_SOURCE_NOT_PROVISIONED

    def test_a_provisioned_host_whose_board_vanished_is_a_source_error(self, tmp_path):
        _write_store(tmp_path, marker=True, boards=False)
        assert private_source_availability(tmp_path)["signalsSf"]["state"] == PRIVATE_SOURCE_MISSING
        contract = _build(tmp_path)
        report = validate_api_data_contract(contract)
        assert "source_missing:signalsSf" in report["sourceHealthErrors"]
        assert "source_missing:signalsSf" not in report["structuralErrors"]

    @pytest.mark.parametrize("trace", ["signalsSf_last_success", "signalsIdpDb_dataset.json"])
    def test_a_deleted_store_on_a_box_that_collected_is_missing_not_unprovisioned(
        self, tmp_path, trace
    ):
        """Review N2: the collector's freshness traces in the scrape state are
        provisioning evidence too, so wiping data/sources/signals/ on a box
        that collected surfaces source_missing rather than going quiet."""
        state = tmp_path / "data" / "scrape_state"
        state.mkdir(parents=True)
        (state / trace).write_text("1\n", encoding="utf-8")
        key = trace.split("_", 1)[0]
        assert private_source_availability(tmp_path)[key]["state"] == PRIVATE_SOURCE_MISSING

    def test_a_payload_without_the_stamp_fails_closed(self, boards):
        contract = dict(boards[1])
        contract.pop("privateSourceAvailability")
        report = validate_api_data_contract(contract)
        assert "source_missing:signalsSf" in report["errors"]

    def test_present_state_on_a_provisioned_host(self, tmp_path):
        _write_store(tmp_path)
        avail = private_source_availability(tmp_path)
        assert {avail[k]["state"] for k in SIGNALS_KEYS} == {PRIVATE_SOURCE_PRESENT}


def _stale_board(root: Path, *, age: timedelta) -> dict[str, bytes]:
    from src.sources import dataset_state as DS

    _write_store(root)
    state_dir = root / "data" / "scrape_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    # Age is measured against the BUILD's as-of (the fixture payload's
    # scrapeTimestamp), so the board is stamped relative to that, never the
    # wall clock: ``now - 60h`` drifted under the decay window a day later.
    as_of = datetime.fromisoformat(_raw_payload()["scrapeTimestamp"].replace("Z", "+00:00"))
    old = as_of - age
    DS.record_source_file(
        source_key="signalsSf",
        csv_path=S.board_csv_path(root / "data" / "sources" / "signals", "signalsSf"),
        signal="rank",
        state_dir=state_dir,
        observed_at=old,
        upstream_published_at=old.isoformat(),
        track_rows=False,
    )
    return {p.name: p.read_bytes() for p in state_dir.iterdir()}


class TestExpiredSession:
    """Auth expiry end to end.  The collector stops making requests (pinned in
    tests/sources/test_signals_values.py), so the board on disk is the last
    good one and the scrape state keeps its old clocks.  The contract still
    builds and Signals' weight follows that TRUE age — building the board
    refreshes no clock, and a board past its cadence budget stops voting
    rather than passing as current."""

    def test_a_few_days_stale_still_votes_at_a_decayed_weight(self, tmp_path):
        before = _stale_board(tmp_path, age=timedelta(hours=60))
        contract = _build(tmp_path)
        assert contract["privateSourceAvailability"]["signalsSf"]["votes"] is True
        metas = [
            r["sourceRankMeta"]["signalsSf"]
            for r in contract["playersArray"]
            if (r.get("sourceRankMeta") or {}).get("signalsSf")
        ]
        assert metas and any(_voted(m) for m in metas)
        # The age is measured against the build's own as-of clock, so it is
        # the stamped age that is asserted, not wall-clock arithmetic.
        assert all(0.0 < m["freshness"] < 1.0 for m in metas)
        assert all(m["freshnessAgeHours"] > 24 for m in metas)
        state_dir = tmp_path / "data" / "scrape_state"
        assert {p.name: p.read_bytes() for p in state_dir.iterdir()} == before

    def test_weeks_stale_stops_voting_but_keeps_its_evidence(self, tmp_path):
        before = _stale_board(tmp_path, age=timedelta(days=20))
        contract = _build(tmp_path)
        row = _rows(contract)[_off(0)]
        meta = row["sourceRankMeta"]["signalsSf"]
        assert not _voted(meta)
        assert meta["freshness"] == 0.0 and meta["freshnessAgeHours"] > 14 * 24
        assert meta["excludedReason"] == "freshness_or_health_zero_weight"
        assert row["sourceNativeValues"]["signalsSf"] == 8550.0  # still visible
        state_dir = tmp_path / "data" / "scrape_state"
        assert {p.name: p.read_bytes() for p in state_dir.iterdir()} == before


# ── 13: rollback ─────────────────────────────────────────────────────────


def test_the_rollback_flag_removes_the_vote_and_keeps_the_evidence(tmp_path, monkeypatch):
    _write_store(tmp_path)
    monkeypatch.setenv("RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE", "0")
    feature_flags.reload()
    try:
        contract = _build(tmp_path)
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE")
        feature_flags.reload()
    assert contract["privateSourceAvailability"]["signalsSf"]["rolledBack"] is True
    row = _rows(contract)[_off(0)]
    assert not _voted((row.get("sourceRankMeta") or {}).get("signalsSf"))
    assert row["sourceNativeValues"]["signalsSf"] == 8550.0  # evidence still visible
    report = validate_api_data_contract(contract)
    assert not [e for e in report["errors"] if "signals" in e]


# ── 14: privacy ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "carrier",
    [
        {"sourceNativeValues": {"signalsSf": 1.0}},
        {"sourceOriginalRanks": {"signalsIdpDb": 1.0}},
        {"x": {"signalsSf": 1}},
        {"x": {"signalsIdpDl": 1}},
        {"canonicalSiteValues": {"signalsSf": 1}},
        {"sourceRankMeta": {"signalsSf": {}}},
        {"sourceShadowMeta": {"x": {}}},
    ],
)
def test_the_public_league_guard_refuses_every_signals_carrier(carrier):
    from src.public_league.public_contract import assert_public_payload_safe

    with pytest.raises(AssertionError):
        assert_public_payload_safe({"section": [carrier]})


def test_no_public_api_path_serves_the_contract():
    import server

    for path in ("/api/data", "/api/rankings/overrides", "/api/second-opinion/signals"):
        assert not server._is_public_api_path(path), path


def test_the_csv_paths_never_point_into_the_committed_tree():
    for key in SIGNALS_KEYS:
        cfg = _SOURCE_CSV_PATHS[key]
        assert cfg["path"].startswith("data/sources/signals/")
        assert cfg["private_marker"].startswith("data/sources/signals/")
    assert json.loads(json.dumps(private_source_availability(Path("/nonexistent-root")))) == {
        k: {"state": "not_provisioned", "provisioned": False, "csvPresent": False}
        for k in SIGNALS_KEYS
    }


# ── Signals IDP in SHADOW (the shipped state) ───────────────────────────


class TestIdpShadow:
    def test_idp_boards_are_collected_shown_and_shadowed_but_cast_no_vote(self, held):
        contract, _ = held
        for key in SIGNALS_KEYS[1:]:
            info = contract["privateSourceAvailability"][key]
            assert info["state"] == PRIVATE_SOURCE_PRESENT
            assert info["votes"] is False
            assert info["voteState"] == "shadow"
            assert info["heldFromVote"] == "shared_market_crosswalk_in_shadow_pending_promotion"
        assert contract["privateSourceAvailability"]["signalsSf"]["voteState"] == "active"
        shown = 0
        for row in contract["playersArray"]:
            meta = row.get("sourceRankMeta") or {}
            assert not any(k in meta for k in SIGNALS_KEYS[1:]), row["displayName"]
            if any(k in (row.get("sourceNativeValues") or {}) for k in SIGNALS_KEYS[1:]):
                shown += 1
        assert shown > 50  # displayed: native value + within-family rank

    def test_shadow_meta_carries_the_shared_market_translation(self, held):
        contract, _ = held
        seen = 0
        for row in contract["playersArray"]:
            for key, grp in zip(SIGNALS_KEYS[1:], ("DL", "LB", "DB")):
                shadow = (row.get("sourceShadowMeta") or {}).get(key)
                if not shadow or shadow.get("withheldReason"):
                    continue
                ladder = _shared_market_family_ladder(grp)
                assert shadow["translatedRank"] == ladder[int(shadow["familyRank"]) - 1]
                assert shadow["rankCoordinatePool"] == "shared_market"
                assert isinstance(shadow["wouldContribute"], int)
                seen += 1
        assert seen > 50

    def test_the_shadow_number_is_exactly_what_promotion_would_vote(self, held, boards):
        """The diagnostic must not be a second methodology: the published
        ``wouldContribute`` equals the contribution the same row casts once
        the switch is on (pre-blend; same curve, same rank)."""
        shadow_rows, promoted_rows = _rows(held[0]), _rows(boards[0])
        compared = 0
        for name, row in shadow_rows.items():
            for key in SIGNALS_KEYS[1:]:
                shadow = (row.get("sourceShadowMeta") or {}).get(key)
                voted = (promoted_rows[name].get("sourceRankMeta") or {}).get(key)
                if not shadow or not voted or shadow.get("withheldReason"):
                    continue
                assert shadow["translatedRank"] == voted["effectiveRank"]
                assert abs(shadow["wouldContribute"] - float(voted["valueContribution"])) <= 1
                compared += 1
        assert compared > 50

    def test_shadow_meta_reaches_the_runtime_view_legacy_dict(self, held):
        """``view=app`` strips playersArray; the Rankings page reads the
        legacy ``players`` dict, so the shadow diagnostic is mirrored there."""
        contract, _ = held
        mirrored = sum(
            1 for p in (contract.get("players") or {}).values() if p.get("sourceShadowMeta")
        )
        assert mirrored > 50

    def test_offense_still_votes(self, held):
        row = _rows(held[0])[_off(40)]
        assert _voted(row["sourceRankMeta"]["signalsSf"])

    def test_shadow_idp_moves_no_idp_value_and_raises_nothing(self, held):
        on, off = (_rows(b) for b in held)
        idp = [n for n in on if n.startswith("Synthetic Idp")]
        assert all(on[n]["rankDerivedValue"] == off[n]["rankDerivedValue"] for n in idp)
        assert all(on[n]["independentSourceCount"] == off[n]["independentSourceCount"] for n in idp)
        assert all(on[n].get("confidenceBucket") == off[n].get("confidenceBucket") for n in idp)
        report = validate_api_data_contract(held[0])
        assert not [e for e in report["errors"] if "signals" in e]

    def test_promotion_switch_turns_the_shadow_into_a_vote(self, boards):
        for key in SIGNALS_KEYS[1:]:
            info = boards[0]["privateSourceAvailability"][key]
            assert info["votes"] is True and info["voteState"] == "active"
            assert info["heldFromVote"] is None


def test_a_retired_pick_class_does_not_misplace_shadow_meta(tmp_path, monkeypatch):
    """Production 2026-10-05 (the Rankings outage): the shadow diagnostic was
    stamped by Phase-1 row INDEX after ``_drop_retired_pick_class_rows`` had
    compacted ``playersArray`` in place.  With a retired class sitting before
    the IDP rows, every shadow index shifted — the tail ran off the end
    (``IndexError``, contract build failed, no board served) and the rest
    landed on the wrong rows.  The stamp must go on the row it was computed
    for, whatever is removed afterwards."""
    from src.api import data_contract as dc

    _write_store(tmp_path)
    raw = _raw_payload()
    retired = {
        f"2025 Pick 1.{slot:02d}": {
            "_canonicalSiteValues": {"ktcCrowdSfTep": 6000 - 10 * slot},
            "ktcCrowdSfTep": 6000 - 10 * slot,
            "position": "PICK",
        }
        for slot in range(1, 13)
    }
    raw["players"] = {**retired, **raw["players"]}  # the retired rows come FIRST

    real = dc._evaluate_pick_class_lifecycle

    def lifecycle_with_2025_retired(players_by_name, sleeper_block):
        out = real(players_by_name, sleeper_block)
        out["retiredYears"] = sorted({*out.get("retiredYears", []), 2025})
        return out

    monkeypatch.setattr(dc, "_evaluate_pick_class_lifecycle", lifecycle_with_2025_retired)
    with contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(raw, csv_root=tmp_path)

    rows = contract["playersArray"]
    assert not any(str(r.get("displayName", "")).startswith("2025 Pick") for r in rows)
    stamped = 0
    for row in rows:
        for key, meta in (row.get("sourceShadowMeta") or {}).items():
            # Each diagnostic describes THIS row: a row Signals covers, on
            # the board of its own family (the fixture's coverage map).
            name = str(row["displayName"])
            assert name.startswith("Synthetic Idp "), (name, key)
            i = int(name.rsplit(" ", 1)[1])
            assert i not in IDP_UNCOVERED, (name, key)
            family = dict(zip(SIGNALS_KEYS[1:], IDP_POS))[key]
            assert IDP_POS[i % 3] == family and meta["positionGroup"] == family, (name, key)
            stamped += 1
    assert stamped > 50
