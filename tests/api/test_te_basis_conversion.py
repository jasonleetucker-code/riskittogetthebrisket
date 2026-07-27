"""The TE basis conversion is WIRED — not merely present in the tree.

ORCHESTRATION.md §6.14/§6.15 record the previous attempt at this: a
complete, tested TE-premium module that ``data_contract.py`` deliberately
never imported, so that "toggle off" would be byte-identical. The cost of
that design was named explicitly — *a design whose safety argument is
"nothing calls it yet" disables the tests that would catch it.* The
double-count invariant existed and could not fire, because the code it
guarded was unreachable.

So the first test in this file asserts the module is REACHED, by
patching ``convert_te_value`` and requiring a call. Every other
assertion here would pass against a completely unwired pipeline that
happened to produce plausible numbers; that one would not.

The second thing worth stating plainly: this moves live consensus values
for tight ends, upward. That is the point. ``ktcSfTep`` — the board this
blend anchors on — IS KTC's TE++ board, every non-TEP source's TE
contribution was already being scaled to align with it, and the flat
1.15 doing that scaling sat below the entire observed range of KTC's own
uplift (minimum 1.209, maximum 2.053). The magnitude was wrong in one
direction for every tight end on the board.
"""

from __future__ import annotations

import pytest

from src.api import data_contract, feature_flags
from src.league_intel import te_premium


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


# ── A minimal board: enough sources for the blend to run ─────────────


_TE_NAME = "Test Tight End"
_WR_NAME = "Test Wide Out"


def _player(value: str | int, position: str) -> dict:
    v = int(value)
    return {
        "_composite": v,
        "_rawComposite": v,
        "_finalAdjusted": v,
        "_canonicalSiteValues": {"ktcSfTep": v, "dlfSf": v},
        "position": position,
    }


def _raw() -> dict:
    """A TE and a WR sitting mid-board, plus filler above them.

    Two properties are deliberate and the fixture is vacuous without
    either:

    * The TE is NOT at rank 1. A top-of-board TE's Hill contribution is
      already 9999, and every uplift — flat 1.15 or the measured curve —
      clamps straight back to 9999. The test would then pass with the
      conversion entirely disabled.
    * The WR sits one slot away from the TE. It is the control: a bug
      that scaled every position would look exactly like a working TE
      premium against a TE-only fixture.
    """
    players = {f"Filler {i:02d}": _player(9000 - i * 60, "WR") for i in range(40)}
    players[_TE_NAME] = _player(5000, "TE")
    players[_WR_NAME] = _player(4940, "WR")
    return {
        "players": players,
        "sites": [{"key": "ktcSfTep"}, {"key": "dlfSf"}],
        "maxValues": {"ktcSfTep": 9999, "dlfSf": 9999},
        "sleeper": {"positions": {}},
    }


def _contribution(payload, player_name, source_key):
    """The per-source transparency block stamped for one player."""
    for row in payload.get("playersArray") or []:
        if row.get("displayName") == player_name:
            return (row.get("sourceRankMeta") or {}).get(source_key) or {}
    raise AssertionError(f"{player_name} not found in payload")


def _build(monkeypatch, **kwargs):
    return data_contract.build_api_data_contract(_raw(), **kwargs)


# ── 1. It is actually called ─────────────────────────────────────────


def test_convert_te_value_is_reached_by_the_live_blend(monkeypatch):
    """The §6.15 guard. Everything else in this file passes against a
    pipeline that never imports the module.

    A spy rather than an output assertion: "the number moved" is
    satisfiable by the flat multiplier, by a coincidence, or by any
    future replacement. "this function ran, with these bases" is not.
    """
    calls: list[tuple] = []
    real = te_premium.convert_te_value

    def spy(value, *, from_basis, to_basis):
        calls.append((value, from_basis, to_basis))
        return real(value, from_basis=from_basis, to_basis=to_basis)

    monkeypatch.setattr(te_premium, "convert_te_value", spy)
    _build(monkeypatch)

    assert calls, "convert_te_value was never called — the module is unwired again"
    # Excluding the one warm-up call the resolver makes before
    # committing the hot path.
    real_calls = [c for c in calls if c[0] != 1000.0]
    assert real_calls, "only the warm-up call fired; no TE row reached the conversion"
    for _value, from_basis, to_basis in calls:
        assert from_basis == "base"
        assert to_basis == "tepp"


def test_the_target_basis_is_the_board_anchor_basis():
    """``ktcSfTep`` is KTC's TE++ (level 2) board and is the blend's
    anchor. Converting onto any other basis would align every source to
    a board nothing here publishes."""
    assert data_contract._BOARD_TE_BASIS == "tepp"
    assert data_contract._TE_SOURCE_DEFAULT_BASIS == "base"
    assert data_contract._BOARD_TE_BASIS in te_premium.TE_BASES


# ── 2. It does the right thing ───────────────────────────────────────


def test_a_te_is_lifted_and_a_wide_receiver_is_not(monkeypatch):
    payload = _build(monkeypatch)
    te = _contribution(payload, _TE_NAME, "dlfSf")
    wr = _contribution(payload, _WR_NAME, "dlfSf")
    assert te.get("tepBoostApplied") is True
    assert wr.get("tepBoostApplied") is not True
    assert "tepMultiplier" not in wr


def test_the_uplift_is_the_measured_curve_not_the_flat_constant(monkeypatch):
    """The whole point of the change, stated as a number.

    1.15 is below KTC's smallest observed uplift, so a correct
    conversion is strictly greater than it at every value on the board.
    """
    payload = _build(monkeypatch)
    te = _contribution(payload, _TE_NAME, "dlfSf")
    assert te["tepBasisFrom"] == "base"
    assert te["tepBasisTo"] == "tepp"
    uplift = te["tepMultiplier"]
    assert uplift > data_contract._TE_BLANKET_NON_NATIVE_MULTIPLIER
    curve_floor = te_premium.load_tep_curve()[2]
    # The stamp is rounded to 4dp, so allow half a unit in the last
    # place rather than exact-comparing a rounded number to a raw one.
    assert uplift >= curve_floor - 5e-5


def test_the_market_anchor_is_still_exempt(monkeypatch):
    """The double-count guard, restated against the wired path.
    ``ktcSfTep`` already IS the TE++ board; lifting it would apply the
    premium twice."""
    payload = _build(monkeypatch)
    te = _contribution(payload, _TE_NAME, "ktcSfTep")
    assert te.get("tepBoostApplied") is not True
    assert "tepBasisTo" not in te


def test_the_conversion_cannot_compound(monkeypatch):
    """Idempotence is the structural half of the double-count guard —
    it holds by construction rather than by discipline, because the API
    takes two bases and a second call sees ``from == to``."""
    once = te_premium.convert_te_value(4000.0, from_basis="base", to_basis="tepp")
    twice = te_premium.convert_te_value(once, from_basis="tepp", to_basis="tepp")
    assert twice == once


# ── 3. Both paths of the flag actually run ───────────────────────────


def test_flag_off_restores_the_flat_multiplier(monkeypatch):
    """The rollback path, exercised rather than assumed.

    A flag whose "off" branch is never run is not a rollback — it is an
    untested code path that happens to be reachable from an env var.
    """
    monkeypatch.setenv("RISKIT_FEATURE_TE_BASIS_CONVERSION", "0")
    feature_flags.reload()
    payload = _build(monkeypatch)
    te = _contribution(payload, _TE_NAME, "dlfSf")
    assert te.get("tepBoostApplied") is True
    assert te["tepMultiplier"] == pytest.approx(
        data_contract._TE_BLANKET_NON_NATIVE_MULTIPLIER, rel=1e-6
    )
    assert "tepBasisTo" not in te


def test_an_explicit_operator_slider_wins_over_the_curve(monkeypatch):
    """A number the operator typed on /settings is a decision, not a
    measurement waiting to be overruled."""
    payload = _build(monkeypatch, tep_multiplier=1.3)
    te = _contribution(payload, _TE_NAME, "dlfSf")
    assert te["tepMultiplier"] == pytest.approx(1.3, rel=1e-6)
    assert "tepBasisTo" not in te


def test_a_broken_curve_degrades_to_the_flat_multiplier(monkeypatch):
    """A missing or unimportable module must cost the TE correction, not
    the whole board. The fallback logs at WARNING because a silent one
    is indistinguishable from the feature working."""

    def boom(*_a, **_k):
        raise RuntimeError("curve unavailable")

    monkeypatch.setattr(te_premium, "convert_te_value", boom)
    payload = _build(monkeypatch)
    te = _contribution(payload, _TE_NAME, "dlfSf")
    assert te["tepMultiplier"] == pytest.approx(
        data_contract._TE_BLANKET_NON_NATIVE_MULTIPLIER, rel=1e-6
    )


# ── 4. Axis B stays out of the shared board ──────────────────────────


def test_league_demand_is_not_consulted_by_the_blend():
    """The scoring-profile/leagueKey split, enforced on the source.

    ``measure_te_demand`` answers a LEAGUE question, and this board is
    shared across every league on one scoring profile. The live registry
    proves the two disagree: dynasty_main (2 TE starters) wants ``tepp``
    and dynasty_new (1) wants ``base``, on the same profile. If the
    blend ever called it, one league's roster shape would reprice the
    other's board.
    """
    import inspect

    # Strip comments and docstring prose before matching. The first draft
    # of this test failed on the words "roster_positions" inside a
    # COMMENT explaining why the blend does not read them — a matcher
    # that succeeds on the documentation rather than the code, which is
    # ORCHESTRATION.md §2b's named trap almost verbatim.
    raw = inspect.getsource(data_contract._compute_unified_rankings)
    code_lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line.split("  #", 1)[0])
    src = "\n".join(code_lines)

    assert "measure_te_demand" not in src
    assert "roster_positions" not in src
    # And the prose really did contain them, so the strip above is doing
    # work rather than passing on an empty haystack.
    assert "roster_positions" in raw


def test_the_two_registry_leagues_really_do_want_different_bases():
    """The premise of the test above, measured rather than asserted.

    If this ever fails — both leagues landing on one basis — the
    constraint above is no longer load-bearing and the decision to keep
    Axis B out of the blend should be revisited on purpose rather than
    inherited.
    """
    import json
    from pathlib import Path

    registry = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "leagues" / "registry.json").read_text(
            encoding="utf-8"
        )
    )
    by_profile: dict[str, set[str]] = {}
    for entry in registry.get("leagues") or []:
        if not entry.get("active"):
            continue
        demand = te_premium.measure_te_demand(entry.get("rosterSettings"))
        by_profile.setdefault(str(entry.get("scoringProfile")), set()).add(demand.target_basis)

    assert any(
        len(bases) > 1 for bases in by_profile.values()
    ), f"no scoring profile spans two TE bases any more: {by_profile}"
