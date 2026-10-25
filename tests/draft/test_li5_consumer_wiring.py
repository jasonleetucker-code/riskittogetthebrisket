"""LI-5 replacement consolidation, phase P3 — consumers wired behind the flag.

docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md §6 (P3 row),
§7 (flag / rollback), §8 items 3, 4, 6, 7, 10; owner decisions D1-D8
(2026-10-21, LVA Package 3).  Flag ``replacement_level_li5_consolidation``,
default OFF and owner-held.

What this file proves:

* **flag-OFF byte identity** — every wired consumer reproduces the corpus
  recorded on the commit BEFORE the wiring (``origin/main@503f08581``,
  ``tests/fixtures/li5_wiring_flag_off_reference.json``), default and explicit
  ``0``; and the corpus MUST change with the flag ON, so the switch is real;
* **the two folds are behaviour-identical** — displacement's free-agent
  selection and capacity's rostered-key loop now delegate to their one owner;
  frozen copies of the retired loops are fuzzed against them;
* **per-consumer population parity (D6)** — capacity keeps an unrostered
  auction rookie, Perfect Draft and droppability exclude him, exactly as before;
* **the served level is LI-5's** — the mean of free-agent ranks 1-3 over the
  add pool (and health, when it applies), unknown states labelled;
* **F6** — an ``assumedWaiver`` charge is no longer called a ceiling under the
  LI-5 level;
* **scarcity stays inert (D8)** and **flag OFF reads nothing new**.

Hermetic: synthetic league, synthetic schedule and host metadata; no network.
"""

from __future__ import annotations

import ast
import json
import random
from datetime import date
from pathlib import Path

import pytest

from src.api import feature_flags
from src.draft import displacement, waiver_population
from src.draft.context import CONTEXT_VERSION, CONTEXT_VERSION_LI5, league_rostered_keys
from tests.draft import li5_wiring_reference as R

LI5_ENV = "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Deterministic rookie window (October: rookies eligible) and no stale
    # population from another test.
    monkeypatch.setattr("src.trade.suggestions._rookies_eligible_today", lambda: True)
    waiver_population.reset_cache()
    yield
    waiver_population.reset_cache()
    monkeypatch.delenv(LI5_ENV, raising=False)
    feature_flags.reload()


def _set_flag(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(LI5_ENV, raising=False)
    else:
        monkeypatch.setenv(LI5_ENV, value)
    feature_flags.reload()


@pytest.fixture(scope="module")
def reference():
    return json.loads(R.OUT.read_text(encoding="utf-8"))


# ── flag-OFF byte identity, flag-ON changes ──────────────────────────────


@pytest.mark.parametrize("value", [None, "0"], ids=["default", "explicit_off"])
def test_flag_off_reproduces_the_pre_wiring_reference(monkeypatch, reference, value):
    _set_flag(monkeypatch, value)
    assert waiver_population.enabled() is False
    now = R.reference()
    assert set(now["digests"]) == set(reference["digests"])
    for key, digest in reference["digests"].items():
        section, _, sub = key.partition("/")
        assert now["digests"][key] == digest, (
            f"{key} changed with the flag OFF",
            now["payloads"][section][sub],
        )
    assert R.canonical(now) == R.canonical(reference)


def test_flag_on_changes_every_wired_consumer(monkeypatch, reference):
    _set_flag(monkeypatch, "1")
    assert waiver_population.enabled() is True
    now = R.reference()
    changed = {k.split("/")[0] for k, d in reference["digests"].items() if now["digests"][k] != d}
    assert changed == {"draft", "draftApi", "droppability", "capacity"}
    for owner in ("o1", "o2"):
        draft = now["payloads"]["draft"][owner]
        assert draft["contextVersion"] == CONTEXT_VERSION_LI5 != CONTEXT_VERSION
        assert draft["replacementPopulation"]["rule"] == waiver_population.POPULATION_RULE
        assert "replacementPopulation" in now["payloads"]["droppability"][owner]
    for owner in ("o1", "o2"):
        off = reference["payloads"]["draft"][owner]
        assert off["contextVersion"] == CONTEXT_VERSION
        assert "replacementPopulation" not in off
        assert "replacementPopulation" not in reference["payloads"]["droppability"][owner]
    for key, block in reference["payloads"]["capacity"].items():
        if key.endswith("/waiverValues"):
            continue
        assert "replacementPopulation" not in block["capacity"], key


def test_the_forced_drop_reference_corpus_is_unchanged_with_li5_off(monkeypatch):
    """#1890's own flag-OFF corpus (``tests/fixtures/forced_drop_flag_off_reference.json``)
    hashes capacity blocks; the LI-5 wiring adds fields only when ON, so the
    corpus must stay byte-identical (design §6 collision handling)."""
    from tests.trade import forced_drop_reference as FR

    _set_flag(monkeypatch, "0")
    ref = json.loads(FR.OUT.read_text(encoding="utf-8"))
    now = FR.reference()
    assert now["digests"] == ref["digests"]
    assert now["capacity"] == ref["capacity"]


# ── the two folds are behaviour-identical ────────────────────────────────


def _legacy_available_players(contract, rostered_keys, unavailable_keys=()):
    """Verbatim copy of ``displacement._available_players`` as it stood on
    ``main@503f08581``, before the fold onto ``base_free_agent_rows``."""
    if not isinstance(contract, dict):
        return []
    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        return []
    taken = {str(k).strip().lower() for k in rostered_keys if str(k or "").strip()}
    taken |= {str(k).strip().lower() for k in unavailable_keys if str(k or "").strip()}
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("assetClass") or "").lower() == "pick":
            continue
        pos = str(row.get("position") or "").strip().upper()
        if not pos or pos == "PICK":
            continue
        value = row.get("rankDerivedValue")
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        keys = {
            str(row.get(f) or "").strip().lower()
            for f in ("playerId", "legacyRef", "canonicalName", "displayName")
        }
        keys.discard("")
        if keys & taken:
            continue
        out.append((float(value), pos))
    return out


def _legacy_capacity_rostered_keys(contract):
    """Verbatim copy of ``build_capacity_context``'s inline rostered-set loop
    on ``main@503f08581``, before the fold onto ``league_rostered_keys``."""

    def _norm(s):
        return str(s or "").strip().lower()

    rostered_keys = set()
    sleeper = contract.get("sleeper") if isinstance(contract, dict) else None
    teams = (sleeper or {}).get("teams") if isinstance(sleeper, dict) else None
    for t in teams if isinstance(teams, list) else []:
        if not isinstance(t, dict):
            continue
        for pid in t.get("playerIds") or []:
            if _norm(pid):
                rostered_keys.add(_norm(pid))
        for nm in t.get("players") or []:
            if _norm(nm):
                rostered_keys.add(_norm(nm))
    return rostered_keys


def _fuzz_contract(rng):
    rows = []
    for i in range(rng.randint(0, 40)):
        row = {
            "playerId": rng.choice([f"p{i}", f" P{i} ", "", None]),
            "displayName": rng.choice([f"Player {i}", f"player {i}", "", None]),
            "canonicalName": f"Player {i}",
            "legacyRef": rng.choice([f"Player {i}", None]),
            "position": rng.choice(["QB", "RB", " wr ", "DL", "K", "DEF", "", "PICK", None]),
            "rankDerivedValue": rng.choice([None, 0, -5, 120, 900, 1500.5, "7", True]),
        }
        if rng.random() < 0.1:
            row["assetClass"] = rng.choice(["pick", "PICK", "offense"])
        rows.append(row)
    if rng.random() < 0.1:
        rows.append("not a row")
    teams = []
    for t in range(rng.randint(0, 3)):
        members = rng.sample(range(40), rng.randint(0, 10))
        teams.append(
            {
                "players": [rng.choice([f"Player {m}", f" player {m}", "", None]) for m in members],
                "playerIds": [rng.choice([f"p{m}", None, ""]) for m in members],
            }
        )
    if rng.random() < 0.1:
        teams.append("not a team")
    sleeper = {"teams": teams} if rng.random() < 0.9 else {"teams": "bad"}
    return {"playersArray": rows, "sleeper": sleeper}


def test_the_free_agent_fold_is_byte_identical_to_the_retired_loop():
    rng = random.Random(1909)
    for _ in range(500):
        c = _fuzz_contract(rng)
        rostered = [rng.choice(["p1", "Player 2", " PLAYER 3 ", "", None]) for _ in range(4)]
        unavailable = [rng.choice(["p4", "player 5", ""]) for _ in range(rng.randint(0, 3))]
        assert displacement._available_players(c, rostered, unavailable) == (
            _legacy_available_players(c, rostered, unavailable)
        )
    assert displacement._available_players(None, ["x"]) == []
    assert displacement._available_players({"playersArray": "x"}, []) == []


def test_the_capacity_rostered_fold_is_identical_to_the_retired_loop():
    rng = random.Random(1890)
    for _ in range(500):
        c = _fuzz_contract(rng)
        assert league_rostered_keys(c) == _legacy_capacity_rostered_keys(c)
    assert league_rostered_keys(None) == set()


# ── the served level, per consumer ───────────────────────────────────────


def test_each_consumer_keeps_its_own_population_and_reads_the_li5_level(monkeypatch):
    """D6: capacity keeps the unrostered auction rookie (2500 WR); Perfect
    Draft and droppability exclude him.  The level is the mean of the add-pool
    ranks 1-3: single-source and sub-500 free agents are out (D5)."""
    _set_flag(monkeypatch, "1")
    payloads = R.build()
    cap = payloads["capacity"]["fds0/waiverValues"]
    draft = payloads["draft"]["o1"]["waiverValues"]
    drop = payloads["droppability"]["o1"]["waiverValues"]
    assert cap["WR"] == pytest.approx((2500 + 1700 + 1400) / 3)  # rookie kept
    assert draft["WR"] == pytest.approx(round((1700 + 1400 + 900) / 3, 1))  # rookie excluded
    assert drop == draft
    assert cap["QB"] == 1500.0  # (1900 + 1500 + 1100) / 3 — the 2400 single-source QB is out
    assert cap["RB"] == pytest.approx((1800 + 1600 + 1200) / 3)  # 450 is below the floor
    assert cap["TE"] == 1600.0  # thin wire: one eligible, sample size 1
    assert cap["DL"] == 1700.0  # two eligible
    assert cap["DB"] == 1550.0
    assert cap["K"] == 600.0 and cap["DEF"] == 700.0  # K/DEF keep a positional level
    # Every free LB is single-source: NO level (absent, never 0), and named.
    assert "LB" not in cap and "LB" not in draft
    block = payloads["draft"]["o1"]["replacementPopulation"]
    assert block["positionsWithoutLevel"] == ["LB"]
    assert block["waiverLevelDetail"]["TE"]["sampleSize"] == 1
    assert block["excludedByReason"] == {"below_min_value": 2, "single_source": 2}
    # The ladder and the count read the same population, unbanded.
    ladder = payloads["draft"]["o1"]["waiverLadder"]
    assert ladder == sorted(ladder, reverse=True) and 2500.0 not in ladder and 2400.0 not in ladder
    assert payloads["draft"]["o1"]["counts"]["freeAgents"] == len(ladder) == 18
    # The auction-exclusion measurement stays on the legacy set (unchanged).
    assert payloads["draft"]["o1"]["counts"]["auctionRookiesExcludedFromWaivers"] == 1


def test_unknown_health_is_labelled_never_treated_as_healthy(monkeypatch):
    """No league settings / no NFL season / no availability context: health is
    ``not_applicable`` with the boundary's reason, and the served lens is the
    banded-without-health one — never lens A's label (design F4, D5)."""
    _set_flag(monkeypatch, "1")
    block = R.build()["draft"]["o1"]["replacementPopulation"]
    assert block["lens"] == waiver_population.LENS_BANDED_NO_HEALTH
    assert block["health"]["state"] == waiver_population.HEALTH_NOT_APPLICABLE
    assert block["health"]["availabilityReason"] == "no_league_settings"
    inputs = waiver_population.resolve_request_inputs(R.contract(), today=date(2026, 4, 2))
    assert inputs.availability is None and inputs.availability_reason == "no_current_nfl_season"


def test_health_applies_through_the_consumer_when_the_league_week_is_known(monkeypatch):
    """With the league's own week known and host metadata on disk, lens A is
    served: an ``Out`` free agent leaves the pool and the level moves; a
    player with no metadata is ``unknown`` and excluded (never available)."""
    from src.ros.availability import build_context
    from src.trade import roster_capacity as RC

    _set_flag(monkeypatch, "1")
    ctx = build_context(
        season=2026,
        league_settings={"leg": 7, "playoff_week_start": 15},
        schedule_rows=[
            {"game_type": "REG", "week": 7, "gameday": "2026-10-25", "home_team": "KC"},
            {"game_type": "REG", "week": 8, "gameday": "2026-11-01", "home_team": "KC"},
        ],
        evidence_payload=None,
        overrides=[],
    )
    inputs = waiver_population.RequestInputs(True, ctx, date(2026, 10, 21), None, ("t",))
    monkeypatch.setattr(waiver_population, "resolve_request_inputs", lambda c, **kw: inputs)
    meta = {
        r["playerId"]: {"team": "KC", "injury_status": None}
        for r in R.contract()["playersArray"]
        if r.get("playerId")
    }
    meta["fa_db_a"] = {"team": "KC", "injury_status": "Out"}
    del meta["fa_db_b"]  # no host metadata -> unknown

    seen = []

    def loader(ids):
        seen.append(sorted(ids))
        return waiver_population.HealthEvidence(meta)

    monkeypatch.setattr(waiver_population, "load_health_evidence", loader)
    c = R.contract()
    us = next(t for t in c["sleeper"]["teams"] if t["ownerId"] == "o1")
    cctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    block = cctx.replacement_population
    assert block["lens"] == waiver_population.LENS_THIS_SEASON
    assert block["health"]["state"] == waiver_population.HEALTH_APPLIED
    assert block["health"]["unavailableExcluded"] == 1
    assert block["health"]["unknownExcluded"] == 1
    # DB pool 1600(Out) / 1550(unknown) / 1500 / 1400 -> mean of 1500, 1400.
    assert cctx.waiver_values["DB"] == pytest.approx((1500 + 1400) / 2)
    assert len(seen) == 1  # asked once, for the add-pool ids only


def test_missing_health_evidence_falls_back_to_the_add_pool_and_says_so(monkeypatch):
    """Players DB missing / stale / incomplete: labelled ``evidence_unavailable``
    and the banded add-pool level is served — never every player excluded
    (which would empty the wire to a 0) and never a network fetch (F5)."""
    from src.ros.availability import build_context
    from src.trade import roster_capacity as RC

    _set_flag(monkeypatch, "1")
    ctx = build_context(
        season=2026,
        league_settings={"leg": 7, "playoff_week_start": 15},
        schedule_rows=[{"game_type": "REG", "week": 7, "gameday": "2026-10-25", "home_team": "KC"}],
        evidence_payload=None,
        overrides=[],
    )
    inputs = waiver_population.RequestInputs(True, ctx, date(2026, 10, 21), None, ("t",))
    monkeypatch.setattr(waiver_population, "resolve_request_inputs", lambda c, **kw: inputs)
    monkeypatch.setattr("src.ros.game_day_live.persisted_players_meta", lambda ids, now=None: None)

    def _no_network(*a, **k):
        raise AssertionError("the request path must never fetch the players DB")

    monkeypatch.setattr("src.ros.game_day_live.fetch_players", _no_network, raising=False)
    monkeypatch.setattr("src.api.matchup_intel.players_meta_for_rosters", _no_network)
    c = R.contract()
    us = next(t for t in c["sleeper"]["teams"] if t["ownerId"] == "o1")
    cctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    block = cctx.replacement_population
    assert block["health"]["state"] == waiver_population.HEALTH_EVIDENCE_UNAVAILABLE
    assert block["lens"] == waiver_population.LENS_BANDED_NO_HEALTH
    assert cctx.waiver_values["DB"] == 1550.0  # the add-pool level, not 0


# ── F6: the assumedWaiver charge is an estimate under LI-5 ───────────────


def test_assumed_waiver_charge_is_relabelled_an_estimate_under_li5(monkeypatch, reference):
    off = reference["payloads"]["capacity"]
    _set_flag(monkeypatch, "1")
    on = R.build()["capacity"]
    relabelled = 0
    for key, block in on.items():
        if not key.startswith("fds1/") or key.endswith("/waiverValues"):
            continue
        basis = block["forcedDropCostBasis"]
        legacy = off[key]["forcedDropCostBasis"]
        assert basis["state"] == legacy["state"], key  # the consumed vocabulary is unchanged
        if basis.get("assumedWaiverBasis"):
            relabelled += 1
            assert basis["assumedWaiverBasis"] == "li5_banded_waiver_estimate"
            assert basis.get("bound") in ("estimate", "mixed")
            assert legacy.get("bound") in ("upper", "lower", "mixed")
        assert basis.get("bound") != "upper" or not basis.get("assumedWaiverDrops"), key
        assert block["capacity"]["replacementPopulation"]["assumedWaiverBasis"] == (
            "li5_banded_waiver_estimate"
        )
    assert relabelled >= 1, "no assumed charge was exercised — the F6 test is vacuous"
    # Under the incumbent forced-drop selection there is no basis bound at all.
    for key, block in on.items():
        if key.startswith("fds0/") and not key.endswith("/waiverValues"):
            assert "assumedWaiverBasis" not in block["forcedDropCostBasis"], key


# ── scarcity inert, nothing new read with the flag OFF ───────────────────


_WIRED = (
    "src/draft/displacement.py",
    "src/draft/waiver_population.py",
    "src/draft/context.py",
    "src/trade/roster_capacity.py",
    "src/roster_intel/droppability.py",
)


def test_scarcity_stays_inert_and_no_market_level_reaches_compute_scarcity(monkeypatch):
    """D8 / design §8 item 6.  No wired module calls the scarcity or the
    four-tier LI-5 path (a market-currency level can never become a
    ``waiver_scarcity`` input), and every ON cut rung keeps multiplier 1.0."""
    for rel in _WIRED:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        called = {
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert not called & {"compute_scarcity", "compute_replacement_levels"}, rel
    _set_flag(monkeypatch, "1")
    built = R.build()
    for owner in ("o1", "o2"):
        for rung in built["draft"][owner]["cutLadder"]["rungs"]:
            assert rung["scarcityMultiplier"] == 1.0
        for rung in built["droppability"][owner]["cutLadder"]["rungs"]:
            assert rung["scarcityMultiplier"] == 1.0


def test_flag_off_builds_no_population_and_reads_no_health(monkeypatch, reference):
    """Flag OFF = today's path: no population, no availability context, no
    players-DB read (design §7)."""
    _set_flag(monkeypatch, "0")

    def _boom(*a, **k):
        raise AssertionError("flag OFF must not reach the LI-5 population")

    monkeypatch.setattr(waiver_population, "consumer_population", _boom)
    monkeypatch.setattr(waiver_population, "resolve_request_inputs", _boom)
    monkeypatch.setattr(waiver_population, "load_health_evidence", _boom)
    monkeypatch.setattr(waiver_population, "build_waiver_population", _boom)
    now = R.reference()
    assert now["digests"] == reference["digests"]


def test_an_unreadable_registry_is_off(monkeypatch):
    def _broken(name):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(feature_flags, "is_enabled", _broken)
    assert waiver_population.enabled() is False


# ── one population per request, no stale context across a flip ──────────


def test_contexts_of_one_request_share_one_population(monkeypatch):
    """Design §8 item 10: the N-team engine and the finder build one capacity
    context per team; they must share ONE population computation."""
    from src.trade import roster_capacity as RC

    _set_flag(monkeypatch, "1")
    calls = []
    real = waiver_population.build_waiver_population

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(waiver_population, "build_waiver_population", counting)
    c = R.contract()
    for team in c["sleeper"]["teams"]:
        RC.build_capacity_context(c, None, team, roster_settings=R.SETTINGS)
    assert len(calls) == 1
    # A different contract object never reuses the entry (no id() aliasing).
    RC.build_capacity_context(R.contract(), None, c["sleeper"]["teams"][0])
    assert len(calls) == 2


def test_the_draft_context_cache_never_serves_across_a_flag_flip(monkeypatch):
    from src.api import draft_optimizer_api

    draft_optimizer_api.reset_cache()
    c = R.contract()
    _set_flag(monkeypatch, "0")
    off = draft_optimizer_api.get_roster_context(c, None, owner_id="o1")
    _set_flag(monkeypatch, "1")
    on = draft_optimizer_api.get_roster_context(c, None, owner_id="o1")
    _set_flag(monkeypatch, "0")
    again = draft_optimizer_api.get_roster_context(c, None, owner_id="o1")
    draft_optimizer_api.reset_cache()
    assert off["contextVersion"] == CONTEXT_VERSION == again["contextVersion"]
    assert on["contextVersion"] == CONTEXT_VERSION_LI5
    assert off == again and "replacementPopulation" in on
