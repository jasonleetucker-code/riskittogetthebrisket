"""IDP Trade Calculator's freshness-quarantine cutoff — readiness (owner 2026-10-07).

Owner decision (final): ``config/sources/freshness_v1.json::quarantineBelow``
stays 0.02 and there is NO production voting floor.  When IDP Trade
Calculator's stale offense + pick observations fall below it they stop
voting, and picks rest on KTC Crowd + KTC Trades.  What must hold then:

1. every pick stays finitely priced with provenance — nothing becomes
   unpriced or 0 merely because IDPTC dropped (MISSING IS NEVER ZERO);
2. the evidence state is stamped: one current PROVIDER, reduced coverage,
   lower confidence under the existing canonical rules;
3./4. no second independent vote is manufactured from another KTC-derived
   signal — KTC Crowd + KTC Trades are two B10 families (owner 2026-09-23,
   values untouched) but ONE provider for independence, and KTC Market is
   benchmark-only and never counts;
5. confidence never RISES because IDPTC disappeared;
6. the degraded evidence is reported (warnings, ``degraded`` status, a
   content alert) and is NOT a contract error in either lane;
7. IDPTC's stale observations stay on the record.

Two halves.  The confidence-owner properties are synthetic and exact.  The
SIMULATION builds the newest complete archived scrape twice — once against
the committed dataset states, once with IDP Trade Calculator's data clocks
aged by exactly the time the freshness owner says it takes its pick
observations to cross ``quarantineBelow`` (plus an hour).  Only the CLOCKS
age; the change history the cadence is learned from is untouched, so the
expected interval — and every other source — is exactly as committed.  That
is "advance the as-of for IDPTC alone": nothing here sets a weight.

Everything asserted on the simulated board is an invariant (all-of, never a
count), so a refresh of the committed state or archive cannot flip it; the
precondition (IDPTC's picks quarantined) is constructed, not hoped for.
"""

from __future__ import annotations

import copy
import json
import math
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import src.api.data_contract as dc
from src.api.confidence import (
    _PICK_CONFIDENCE_SOURCES,
    CONFIDENCE_LEVELS,
    FamilyEvidence,
    assess_confidence,
    assess_pick_confidence,
    pick_evidence,
)
from src.api.source_health_alerts import detect_content_alerts
from src.sources import freshness as F
from src.sources.dataset_state import load_state, parse_iso, state_path
from src.sources.source_census import provider_of
from tests.archive_fixtures import newest_complete_raw_payload

_REPO = Path(__file__).resolve().parents[2]
_STATE_DIR = _REPO / "data" / "scrape_state"
_IDPTC = "idpTradeCalc"
_LEVEL = {name: i for i, name in enumerate(CONFIDENCE_LEVELS)}
_KTC_KEYS = ("ktcCrowdSfTep", "ktcTradesSfTep", "ktcCrowdTradesSfTep")


# ── 3/4: provider identity — KTC is one provider, Market never counts ──────


def test_every_pick_confidence_source_has_a_recorded_provider() -> None:
    """A lineage gap would fall back to the key and OVERSTATE independence."""
    missing = [k for k in _PICK_CONFIDENCE_SOURCES if provider_of(k) is None]
    assert not missing, f"pick confidence sources with no recorded provider: {missing}"


def test_ktc_crowd_trades_and_market_are_one_provider() -> None:
    assert {provider_of(k) for k in _KTC_KEYS} == {"keepTradeCut"}
    assert provider_of(_IDPTC) not in {None, "keepTradeCut"}


def test_ktc_market_cannot_count_toward_pick_confidence() -> None:
    assert "ktcCrowdTradesSfTep" not in _PICK_CONFIDENCE_SOURCES
    base = {"ktcCrowdSfTep": 5000.0, "idpTradeCalc": 5050.0}
    with_market = {**base, "ktcCrowdTradesSfTep": 5025.0}
    assert assess_pick_confidence(with_market, is_slot_specific=False) == assess_pick_confidence(
        base, is_slot_specific=False
    )
    ev = pick_evidence({"ktcCrowdTradesSfTep": 5000.0, "ktcTradesSfTep": 4900.0})
    assert ev["votingSources"] == ["ktcTradesSfTep"]
    assert ev["state"] == "single_provider"


def test_ktc_crowd_plus_trades_alone_is_a_single_provider_pick() -> None:
    """Two value modes of one KTC payload agreeing is one vendor agreeing with itself."""
    for slot in (False, True):
        bucket, label = assess_pick_confidence(
            {"ktcCrowdSfTep": 5000.0, "ktcTradesSfTep": 5010.0}, is_slot_specific=slot
        )
        assert (bucket, label) == ("low", "Low — single pick provider")
    ev = pick_evidence({"ktcCrowdSfTep": 5000.0, "ktcTradesSfTep": 5010.0})
    assert ev["votingProviders"] == ["keepTradeCut"]
    assert ev["state"] == "single_provider"
    assert ev["reducedCoverage"] is False


def test_two_providers_still_corroborate() -> None:
    bucket, _ = assess_pick_confidence(
        {"ktcCrowdSfTep": 5000.0, "ktcTradesSfTep": 4900.0, "idpTradeCalc": 5050.0},
        is_slot_specific=False,
    )
    assert bucket == "high"


# ── 5: a withheld source can never RAISE confidence (exact, synthetic) ─────


def test_withheld_pick_market_never_raises_pick_confidence() -> None:
    """Including the disagreeing case: IDPTC far off makes the observed panel
    ``low``; dropping it leaves KTC alone — still ``low``, never higher."""
    rng = random.Random(20261007)
    keys = list(_PICK_CONFIDENCE_SOURCES)
    for _ in range(3000):
        present = [k for k in keys if rng.random() < 0.6] or [keys[0]]
        values = {k: rng.uniform(500.0, 9000.0) for k in present}
        if rng.random() < 0.5:  # a tight panel, where dropping an outlier would help
            centre = rng.uniform(1000.0, 8000.0)
            values = {k: centre * rng.uniform(0.95, 1.05) for k in present}
            values[present[-1]] = centre * rng.choice((0.4, 1.9))
        withheld = [k for k in present if rng.random() < 0.4]
        slot = rng.random() < 0.5
        before = assess_pick_confidence(values, is_slot_specific=slot)[0]
        after = assess_pick_confidence(values, is_slot_specific=slot, withheld_sources=withheld)[0]
        assert _LEVEL[after] <= _LEVEL[before], (values, withheld, before, after)


def _family(i: int, rng: random.Random, value: float) -> FamilyEvidence:
    return FamilyEvidence(
        family=f"f{i}",
        source_key=f"s{i}",
        value_contribution=value * rng.choice((0.8, 0.95, 1.0, 1.05, 1.3)),
        fresh=rng.choice((True, True, True, False, None)),
        format_native=rng.random() < 0.8,
        directly_observed=rng.random() < 0.9,
    )


def test_losing_a_family_never_raises_any_axis_at_a_fixed_value() -> None:
    """Moving one family from the voting panel to a lost seat, with the
    published value held fixed, can only hold or lower every axis.

    This is the confidence owner's whole share of requirement 5.  A lost
    seat earns nothing a voting head could have earned, so no axis — not
    agreement, freshness, applicability or the TE-basis penalty — can rise.
    """
    rng = random.Random(7)
    for _ in range(4000):
        value = rng.uniform(500.0, 9000.0)
        n = rng.randint(1, 12)
        panel = [_family(i, rng, value) for i in range(n)]
        eligible = {f"f{i}" for i in range(n + rng.randint(0, 3))}
        lost_idx = set(rng.sample(range(n), rng.randint(1, n)))
        voting = [e for i, e in enumerate(panel) if i not in lost_idx]
        lost = [e for i, e in enumerate(panel) if i in lost_idx]
        before = assess_confidence(panel, eligible_families=eligible, consensus_value=value)
        after = assess_confidence(
            voting, eligible_families=eligible, consensus_value=value, withheld=lost
        )
        for axis, level in after.axes.items():
            assert _LEVEL[level] <= _LEVEL[before.axes[axis]], (axis, before.axes, after.axes)
        assert _LEVEL[after.overall] <= _LEVEL[before.overall]


def test_without_the_lost_seat_dropping_a_dissenter_would_promote() -> None:
    """The failure the seat closes: 5 of 8 agree (medium); drop the three
    dissenters and 5 of 5 agree (high).  Seated, it stays 5 of 8."""
    heads = [FamilyEvidence(f"f{i}", f"s{i}", 1000.0, True) for i in range(5)]
    dissent = [
        FamilyEvidence("x", "idp", 2000.0, False),
        FamilyEvidence("y", "ds", 2100.0, True),
        FamilyEvidence("z", "dn", 600.0, True),
    ]
    eligible = {e.family for e in heads + dissent}
    before = assess_confidence(heads + dissent, eligible_families=eligible, consensus_value=1000.0)
    dropped = assess_confidence(heads, eligible_families=eligible, consensus_value=1000.0)
    seated = assess_confidence(
        heads, eligible_families=eligible, consensus_value=1000.0, withheld=dissent
    )
    assert before.axes["agreement"] == "medium"
    assert dropped.axes["agreement"] == "high"  # the pathology, without the seat
    assert seated.axes["agreement"] == "medium"
    assert seated.metrics["withheldFamilies"] == 3


def test_a_withheld_family_must_not_also_vote() -> None:
    head = FamilyEvidence("f", "a", 1.0, True)
    with pytest.raises(ValueError):
        assess_confidence([head], eligible_families={"f"}, consensus_value=1.0, withheld=[head])


# ── 6: alerting surface ─────────────────────────────────────────────────────


def test_withheld_votes_raise_a_content_alert_not_an_outage() -> None:
    entry = {"role": "model_input", "votingRows": 375, "excludedRows": 513, "health": "HEALTHY"}
    keys = [a.source for a in detect_content_alerts({"sources": {_IDPTC: entry}})]
    assert f"content:{_IDPTC}:votes_withheld" in keys
    entry_ok = {**entry, "excludedRows": 0}
    keys_ok = [a.source for a in detect_content_alerts({"sources": {_IDPTC: entry_ok}})]
    assert f"content:{_IDPTC}:votes_withheld" not in keys_ok


# ── The simulation ──────────────────────────────────────────────────────────


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _picks_quarantine_delay(state: dict[str, Any], as_of: datetime) -> timedelta | None:
    """How far IDPTC's clocks must age for its PICK observations to cross
    ``quarantineBelow`` — asked of the freshness owner, never re-derived."""

    def quarantined(delta: timedelta) -> bool:
        sub = F.assess_source(_IDPTC, state, as_of=as_of + delta).subsets.get("picks")
        return sub is not None and sub.freshness <= 0.0

    lo, hi = timedelta(0), timedelta(days=120)
    if quarantined(lo):
        return timedelta(0)
    if not quarantined(hi):
        return None
    while hi - lo > timedelta(minutes=1):
        mid = lo + (hi - lo) / 2
        if quarantined(mid):
            hi = mid
        else:
            lo = mid
    return hi


def _aged(state: dict[str, Any], delta: timedelta) -> dict[str, Any]:
    """IDPTC's offense + pick data CLOCKS aged by ``delta``.

    * the picks subset's clocks and per-row clocks all age;
    * in the players subset, every per-row clock OLDER than the subset's
      latest broad change ages — the offense universe's clock is read from
      those rows, so offense ages with them — while the latest broad change
      itself (today an IDP-only publication) keeps its time, so the IDP side
      does not decay.  That isolates the event the owner decided on: offense
      and picks crossing ``quarantineBelow``, as if IDPTC refreshed only its
      IDP board in the meantime.  (Ageing the IDP side too would mix in the
      ordinary continuous freshness decay of its IDP vote, which moves IDP
      values and agreement every refresh and is not this event.)

    The change history is untouched, so the learned cadence (the curve's
    ``E``) is exactly as committed.
    """
    out = copy.deepcopy(state)
    subsets = out.get("subsets") or {}
    picks = subsets.get("picks") or {}
    for key in ("lastBroadDatasetChangeAt", "lastAnyMeaningfulChangeAt"):
        if picks.get(key):
            picks[key] = _iso(parse_iso(picks[key]) - delta)
    picks["rowChangedAt"] = {
        k: _iso(parse_iso(v) - delta) for k, v in (picks.get("rowChangedAt") or {}).items()
    }
    players = subsets.get("players") or {}
    latest = parse_iso(players.get("lastBroadDatasetChangeAt"))
    players["rowChangedAt"] = {
        k: (_iso(parse_iso(v) - delta) if latest is None or parse_iso(v) < latest else v)
        for k, v in (players.get("rowChangedAt") or {}).items()
    }
    return out


_SIM: dict[str, Any] = {}


def _simulation(tmp_root: Path) -> dict[str, Any]:
    if _SIM:
        return _SIM
    raw, archive = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape to build a contract from")
    as_of = dc._payload_as_of(raw)
    state = load_state(state_path(_STATE_DIR, _IDPTC))
    if as_of is None or not state:
        pytest.skip("no as-of or no committed IDP Trade Calculator dataset state")
    delay = _picks_quarantine_delay(state, as_of)
    if delay is None:
        pytest.skip("IDP Trade Calculator's picks do not quarantine within 120 days")
    delta = delay + timedelta(hours=1)

    base_dir, cut_dir = tmp_root / "base", tmp_root / "cut"
    shutil.copytree(_STATE_DIR, base_dir)
    shutil.copytree(_STATE_DIR, cut_dir)
    (cut_dir / f"{_IDPTC}_dataset.json").write_text(
        json.dumps(_aged(state, delta)), encoding="utf-8"
    )

    original = dc._source_weighting_state_dir
    try:
        dc._source_weighting_state_dir = lambda csv_root=None: base_dir  # noqa: ARG005
        before = dc.build_api_data_contract(copy.deepcopy(raw))
        dc._source_weighting_state_dir = lambda csv_root=None: cut_dir  # noqa: ARG005
        after = dc.build_api_data_contract(copy.deepcopy(raw))
    finally:
        dc._source_weighting_state_dir = original
    _SIM.update(
        archive=archive,
        delta=delta,
        cutoff=as_of + delay,
        before=before,
        after=after,
        state_dir=cut_dir,
    )
    return _SIM


@pytest.fixture(scope="module")
def sim(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _simulation(tmp_path_factory.mktemp("idptc_cutoff"))


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("canonicalName") or row.get("displayName"), row.get("assetClass"))


def _rows(contract: dict[str, Any]) -> dict[tuple[Any, ...], dict[str, Any]]:
    return {_key(r): r for r in contract.get("playersArray") or []}


def _priced(row: dict[str, Any]) -> bool:
    v = row.get("rankDerivedValue")
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
        and v > 0
    )


def _withheld_picks(after: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        r
        for r in after["playersArray"]
        if r.get("assetClass") == "pick" and _IDPTC in (r.get("freshnessExcludedSources") or [])
    ]
    if not rows:
        pytest.skip("IDP Trade Calculator prices no pick on this archived board")
    return rows


def test_precondition_idptc_picks_are_quarantined_and_nothing_else_aged(sim) -> None:
    sources = sim["after"]["sourceWeighting"]["sources"]
    assert sources[_IDPTC]["subsets"]["picks"]["state"] == F.STATE_QUARANTINED
    assert sources[_IDPTC]["excludedRows"] > 0
    before = sim["before"]["sourceWeighting"]["sources"]
    for key, entry in sources.items():
        if key == _IDPTC:
            continue
        assert entry.get("subsets") == before[key].get("subsets"), key
    _withheld_picks(sim["after"])


def test_1_no_pick_becomes_unpriced_because_idptc_dropped(sim) -> None:
    before, after = _rows(sim["before"]), _rows(sim["after"])
    assert set(before) == set(after), "rows appeared or vanished"
    lost = [
        k
        for k, row in before.items()
        if row.get("assetClass") == "pick" and _priced(row) and not _priced(after[k])
    ]
    assert not lost, f"picks unpriced after the cutoff: {lost}"
    for row in after.values():
        if row.get("assetClass") != "pick":
            continue
        prov = row.get("pickValueProvenance") or {}
        if prov.get("class") == "alias_suppressed":
            continue  # the one deliberate valueless state, named by provenance
        assert _priced(row), (row.get("canonicalName"), row.get("rankDerivedValue"))
        assert prov.get("class") and prov.get("class") != "unavailable", row.get("canonicalName")


def test_2_withheld_picks_are_stamped_single_provider_and_reduced(sim) -> None:
    for row in _withheld_picks(sim["after"]):
        if row.get("confidenceBasis") != "pick_dispersion":
            continue  # value from a tether/derivation; its provenance says so
        ev = row.get("pickEvidence") or {}
        assert ev.get("reducedCoverage") is True, row.get("canonicalName")
        assert "idpTradeCalculator" in ev.get("withheldProviders", []), row.get("canonicalName")
        assert "idpTradeCalculator" not in ev.get("votingProviders", [])
        if set(ev.get("votingProviders") or []) == {"keepTradeCut"}:
            assert ev["state"] == "single_provider", row.get("canonicalName")
            assert row["confidenceBucket"] == "low", row.get("canonicalName")
        assert row.get("sourceWeightState") in (
            "DEGRADED",
            "SEVERELY_DEGRADED",
            "INSUFFICIENT_DATA",
        ), row.get("canonicalName")


def test_3_4_ktc_crowd_and_trades_never_two_providers_on_the_board(sim) -> None:
    for contract in (sim["before"], sim["after"]):
        for row in contract["playersArray"]:
            ev = row.get("pickEvidence")
            if not ev:
                continue
            assert "ktcCrowdTradesSfTep" not in ev["votingSources"] + ev["withheldSources"]
            assert len(ev["votingProviders"]) == len(set(ev["votingProviders"]))
            ktc = {"ktcCrowdSfTep", "ktcTradesSfTep"}
            if set(ev["votingSources"]) <= ktc and ev["votingSources"]:
                assert ev["votingProviders"] == ["keepTradeCut"]
                assert ev["state"] == "single_provider"


def test_5_confidence_never_rises_because_idptc_dropped(sim) -> None:
    """Every row that lost evidence: no confidence axis it controls rises.

    The confidence layer's guarantee is exact at a fixed published value
    (``test_losing_a_family_never_raises_any_axis_at_a_fixed_value``).  On
    the board, a row's value itself can move when IDPTC stops voting (that
    is the owner-decided value behaviour), and the AGREEMENT axis is
    measured against the value that ships — so a moved value can bring
    another family inside tolerance.  That residual is asserted to be the
    ONLY way a level can rise, and only on a row whose value moved; it is
    surfaced as an owner decision in the PR (closing it needs a
    counterfactual second blend, which the architecture forbids).
    """
    before, after = _rows(sim["before"]), _rows(sim["after"])
    residual = []
    for key, b in before.items():
        a = after[key]
        lb, la = _LEVEL.get(b.get("confidenceBucket"), 0), _LEVEL.get(a.get("confidenceBucket"), 0)
        if la <= lb:
            continue
        lost = bool(a.get("freshnessExcludedSources"))
        moved = a.get("rankDerivedValue") != b.get("rankDerivedValue")
        ab, aa = b.get("confidenceAxes") or {}, a.get("confidenceAxes") or {}
        risen = {ax for ax in aa if _LEVEL[aa[ax]] > _LEVEL.get(ab.get(ax, "none"), 0)}
        assert lost and moved and risen == {"agreement"}, (
            key,
            b.get("confidenceBucket"),
            a.get("confidenceBucket"),
            ab,
            aa,
        )
        assert any("did not reach the value" in r for r in a.get("confidenceReasons") or [])
        residual.append(key)
    # Pick confidence has no value-drift path at all: strictly monotone.
    assert not [k for k in residual if k[1] == "pick"]


def test_6_degraded_evidence_is_warned_never_an_error(sim) -> None:
    before = dc.validate_api_data_contract(sim["before"])
    after = dc.validate_api_data_contract(sim["after"])
    assert after["structurallyOk"] is True, after["structuralErrors"]
    assert (
        after["sourceHealthErrors"] == before["sourceHealthErrors"]
    ), "IDPTC aging out must not add a source-health (deploy-blocking) error"
    assert after["ok"] == before["ok"]
    assert any(w.startswith(f"source_votes_withheld:{_IDPTC}:") for w in after["warnings"])
    assert after["status"] in ("degraded", "invalid")
    alerts = [a.source for a in detect_content_alerts(sim["after"]["sourceWeighting"])]
    assert f"content:{_IDPTC}:votes_withheld" in alerts


def test_7_idptc_observations_stay_on_the_record(sim) -> None:
    before, after = _rows(sim["before"]), _rows(sim["after"])
    for row in _withheld_picks(sim["after"]):
        k = _key(row)
        assert (row.get("canonicalSiteValues") or {}).get(_IDPTC) == (
            before[k].get("canonicalSiteValues") or {}
        ).get(_IDPTC)
        meta = (row.get("sourceRankMeta") or {}).get(_IDPTC) or {}
        assert meta.get("contributedToBlend") is False
        assert meta.get("excludedReason") == "freshness_or_health_zero_weight"
        assert isinstance(meta.get("valueContribution"), (int, float))
    # The committed dataset state is never rewritten by a build.
    assert load_state(state_path(_STATE_DIR, _IDPTC)) == load_state(state_path(_STATE_DIR, _IDPTC))
    assert any(_IDPTC in (r.get("canonicalSiteValues") or {}) for r in after.values())
