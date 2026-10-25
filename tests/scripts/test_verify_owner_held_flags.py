"""``scripts/verify_owner_held_flags.py`` -- the deploy-time check that the
LIVE process keeps the owner-held source-vote flags in force (DLF IDP hold ON,
DLF Values voting OFF, universal freshness schedule v2 OFF; owner decisions
2026-10-20; the depth-note shadow counters, the LI-5 replacement-level
consolidation and the forced-drop fix OFF, owner decisions 2026-10-21).  It is what covers the
production box's untracked ``.env``; ``deploy/verify-deploy.sh`` runs it and a
non-zero exit fails the deploy (auto-rollback)."""

from __future__ import annotations

import pytest

from scripts import verify_owner_held_flags as v


def _status(**enabled):
    flags = {"other_flag": {"enabled": True, "gateStatus": "live"}}
    for name, on in enabled.items():
        flags[name] = {"enabled": on, "gateStatus": "live"}
    return {"featureFlags": flags}


_GOOD = {
    "dlf_offense_only_vote": True,
    "dlf_values_rank_hill_vote": False,
    "source_freshness_schedule_v2": False,
    "low_value_depth_disclosure_shadow": False,
    "replacement_level_li5_consolidation": False,
    "forced_drop_cheapest_legal": False,
}


def test_required_states_pass():
    assert v.evaluate(_status(**_GOOD)) == []
    # The bare-bool ``snapshot()`` shape is accepted too.
    assert v.evaluate({"featureFlags": dict(_GOOD)}) == []


def test_dlf_values_on_fails_with_an_explicit_message():
    out = v.evaluate(_status(**{**_GOOD, "dlf_values_rank_hill_vote": True}))
    assert len(out) == 1
    msg = out[0]
    assert "dlf_values_rank_hill_vote is effectively ON" in msg and "must be OFF" in msg
    assert "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE" in msg and ".env" in msg
    assert "owner's activation decision" in msg


def test_dlf_idp_hold_lifted_fails():
    out = v.evaluate(_status(**{**_GOOD, "dlf_offense_only_vote": False}))
    assert len(out) == 1 and "dlf_offense_only_vote is effectively OFF" in out[0]
    assert "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE" in out[0]


def test_freshness_v2_on_fails_with_an_explicit_message():
    """Owner decision 2026-10-20 on PR #1831 (Option B): the schedule ships
    disabled; a live process with it ON fails the deploy."""
    out = v.evaluate(_status(**{**_GOOD, "source_freshness_schedule_v2": True}))
    assert len(out) == 1
    msg = out[0]
    assert "source_freshness_schedule_v2 is effectively ON" in msg and "must be OFF" in msg
    assert "RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2" in msg and ".env" in msg
    assert "PR #1831" in msg and "owner's activation decision" in msg


def test_freshness_v2_absent_fails_closed_like_d4():
    """Same convention as D4: the check runs against the process the deploy
    just restarted, whose registry carries the flag, so an ABSENT entry is
    "cannot tell" and fails closed -- never read as OFF."""
    snap = _status(**_GOOD)
    del snap["featureFlags"]["source_freshness_schedule_v2"]
    out = v.evaluate(snap)
    assert len(out) == 1
    assert "source_freshness_schedule_v2: missing or unreadable" in out[0]
    assert "Failing closed" in out[0]


def test_all_wrong_reports_all():
    out = v.evaluate(
        _status(
            dlf_offense_only_vote=False,
            dlf_values_rank_hill_vote=True,
            source_freshness_schedule_v2=True,
            low_value_depth_disclosure_shadow=True,
            replacement_level_li5_consolidation=True,
            forced_drop_cheapest_legal=True,
        )
    )
    assert len(out) == 6


def test_depth_disclosure_shadow_on_fails_with_an_explicit_message():
    """Owner decision 2026-10-21 (LVA Package 4): the shadow counters ship
    dormant; a live process with them ON fails the deploy."""
    out = v.evaluate(_status(**{**_GOOD, "low_value_depth_disclosure_shadow": True}))
    assert len(out) == 1
    msg = out[0]
    assert "low_value_depth_disclosure_shadow is effectively ON" in msg and "must be OFF" in msg
    assert "RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW" in msg and ".env" in msg
    assert "Package 4" in msg and "owner's activation decision" in msg


def test_li5_replacement_consolidation_on_fails_with_an_explicit_message():
    """Owner decision 2026-10-21 (LVA Package 3): the LI-5 waiver level ships
    dormant; a live process with it ON fails the deploy."""
    out = v.evaluate(_status(**{**_GOOD, "replacement_level_li5_consolidation": True}))
    assert len(out) == 1
    msg = out[0]
    assert "replacement_level_li5_consolidation is effectively ON" in msg and "must be OFF" in msg
    assert "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION" in msg and ".env" in msg
    assert "Package 3" in msg and "owner's activation decision" in msg


def test_forced_drop_cheapest_legal_on_fails_with_an_explicit_message():
    """Owner decision 2026-10-21 (LVA Package 1, item 3): the forced-drop fix
    ships dormant; a live process with it ON fails the deploy."""
    out = v.evaluate(_status(**{**_GOOD, "forced_drop_cheapest_legal": True}))
    assert len(out) == 1
    msg = out[0]
    assert "forced_drop_cheapest_legal is effectively ON" in msg and "must be OFF" in msg
    assert "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL" in msg and ".env" in msg
    assert "Package 1" in msg and "owner's activation decision" in msg


@pytest.mark.parametrize(
    "status",
    [
        None,
        [],
        {},
        {"featureFlags": {}},
        {"featureFlags": "on"},
        {"featureFlags": {"dlf_offense_only_vote": {"enabled": True}}},  # D4 missing
        {"featureFlags": {"dlf_offense_only_vote": True, "dlf_values_rank_hill_vote": False}},
        {"featureFlags": {"dlf_offense_only_vote": {"enabled": "1"}, **{"x": True}}},
        _status(dlf_offense_only_vote=True, dlf_values_rank_hill_vote=None),
        _status(**{**_GOOD, "source_freshness_schedule_v2": "0"}),
    ],
)
def test_missing_or_malformed_snapshots_fail_closed(status):
    assert v.evaluate(status), status


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(v, "_fetch_status", lambda url: _status(**_GOOD))
    assert v.main(["http://127.0.0.1:8000"]) == 0
    monkeypatch.setattr(
        v,
        "_fetch_status",
        lambda url: _status(**{**_GOOD, "dlf_values_rank_hill_vote": True}),
    )
    assert v.main(["http://127.0.0.1:8000"]) == 1
    assert "::error" in capsys.readouterr().out
    monkeypatch.setattr(v, "_fetch_status", lambda url: None)  # unreachable
    assert v.main(["http://127.0.0.1:8000"]) == 1
    monkeypatch.delenv("DEPLOY_VERIFY_BASE_URL", raising=False)
    assert v.main([]) == 1


def test_the_live_registry_snapshot_shape_passes(monkeypatch):
    """The real ``effective_flags()`` -- what /api/status serves -- passes
    with default flags and fails when the production env flips either."""
    from src.api import feature_flags

    envs = (
        "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE",
        "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE",
        "RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2",
        "RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW",
        "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION",
        "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL",
    )
    for env in envs:
        monkeypatch.delenv(env, raising=False)
    feature_flags.reload()
    try:
        # The first deploy that introduces a held flag passes: the restarted
        # process's own registry snapshot carries every held flag.
        live = feature_flags.effective_flags()
        assert set(v.OWNER_HELD_FLAGS) <= set(live)
        assert v.evaluate({"featureFlags": live}) == []
        for env in (
            "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE",
            "RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2",
            "RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW",
            "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION",
            "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL",
        ):
            for other in envs:
                monkeypatch.delenv(other, raising=False)
            monkeypatch.setenv(env, "1")
            feature_flags.reload()
            assert v.evaluate({"featureFlags": feature_flags.effective_flags()}), env
    finally:
        for env in envs:
            monkeypatch.delenv(env, raising=False)
        feature_flags.reload()
