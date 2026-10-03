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
            path = S.board_csv_path(store, spec.source_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(S.render_board_csv(rows), encoding="utf-8")


def _build(root: Path) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(_raw_payload(), csv_root=root)


def _rows(contract: dict) -> dict[str, dict]:
    return {str(r.get("displayName")): r for r in contract.get("playersArray") or []}


@pytest.fixture(scope="module")
def boards(tmp_path_factory):
    on = tmp_path_factory.mktemp("signals_on")
    _write_store(on)
    off = tmp_path_factory.mktemp("signals_off")
    with_signals = _build(on)
    without = _build(off)
    return with_signals, without


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

    def test_idp_through_the_shared_market_ladder(self, boards):
        rows = _rows(boards[0])
        row = rows[_idp(0)]
        meta = row["sourceRankMeta"]["signalsIdp"]
        assert _voted(meta)
        assert meta.get("sharedMarketTranslated") is True
        assert row["sourceNativeValues"]["signalsIdp"] == 4900.0

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
    @pytest.mark.parametrize(
        "name,key", [(_off(OFF_FALLBACK), "signalsSf"), (_idp(IDP_FALLBACK), "signalsIdp")]
    )
    def test_a_cross_position_rank_without_a_value_votes_as_rank(self, boards, name, key):
        row = _rows(boards[0])[name]
        assert _voted(row["sourceRankMeta"][key])
        assert key not in (row.get("sourceNativeValues") or {})  # RANK basis: no value
        assert key in row["sourceOriginalRanks"]

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
        assert reg["signalsIdp"]["scope"] == "overall_idp" and not reg["signalsIdp"].get(
            "extra_scopes"
        )
        assert (
            reg["signalsSf"]["correlation_group"]
            == reg["signalsIdp"]["correlation_group"]
            == "fantasyCalc"
        )
        for key in ("signalsSf", "signalsIdp"):
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

    def test_no_independence_bonus_for_the_confidence_gate(self, boards):
        with_s, without = (_rows(b) for b in boards)
        row_on, row_off = with_s[_off(0)], without[_off(0)]
        assert row_on["independentSourceCount"] == row_off["independentSourceCount"]


# ── 12: missing is never zero; not provisioned is not an error ──────────


class TestMissingAndProvisioning:
    def test_uncovered_rows_carry_no_signals_key(self, boards):
        rows = _rows(boards[0])
        for i in OFF_UNCOVERED:
            assert "signalsSf" not in (rows[_off(i)].get("canonicalSiteValues") or {})
        for i in IDP_UNCOVERED:
            assert "signalsIdp" not in (rows[_idp(i)].get("canonicalSiteValues") or {})

    def test_an_unprovisioned_host_carries_nothing_and_raises_nothing(self, boards):
        contract = boards[1]
        state = contract["privateSourceAvailability"]
        assert state["signalsSf"]["state"] == PRIVATE_SOURCE_NOT_PROVISIONED
        assert state["signalsSf"]["votes"] is False
        for row in contract["playersArray"]:
            for key in ("signalsSf", "signalsIdp"):
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

    def test_a_payload_without_the_stamp_fails_closed(self, boards):
        contract = dict(boards[1])
        contract.pop("privateSourceAvailability")
        report = validate_api_data_contract(contract)
        assert "source_missing:signalsSf" in report["errors"]

    def test_present_state_on_a_provisioned_host(self, tmp_path):
        _write_store(tmp_path)
        assert (
            private_source_availability(tmp_path)["signalsIdp"]["state"] == PRIVATE_SOURCE_PRESENT
        )


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
        {"sourceOriginalRanks": {"signalsIdp": 1.0}},
        {"x": {"signalsSf": 1}},
        {"canonicalSiteValues": {"signalsSf": 1}},
        {"sourceRankMeta": {"signalsSf": {}}},
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
    for key in ("signalsSf", "signalsIdp"):
        cfg = _SOURCE_CSV_PATHS[key]
        assert cfg["path"].startswith("data/sources/signals/")
        assert cfg["private_marker"].startswith("data/sources/signals/")
    assert json.loads(json.dumps(private_source_availability(Path("/nonexistent-root")))) == {
        "signalsSf": {"state": "not_provisioned", "provisioned": False, "csvPresent": False},
        "signalsIdp": {"state": "not_provisioned", "provisioned": False, "csvPresent": False},
    }
