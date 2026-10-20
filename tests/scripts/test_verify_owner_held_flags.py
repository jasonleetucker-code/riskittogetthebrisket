"""``scripts/verify_owner_held_flags.py`` -- the deploy-time check that the
LIVE process keeps the owner-held source-vote flags in force (DLF IDP hold ON,
DLF Values voting OFF; owner decisions 2026-10-20).  It is what covers the
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


_GOOD = {"dlf_offense_only_vote": True, "dlf_values_rank_hill_vote": False}


def test_required_states_pass():
    assert v.evaluate(_status(**_GOOD)) == []
    # The bare-bool ``snapshot()`` shape is accepted too.
    assert v.evaluate({"featureFlags": dict(_GOOD)}) == []


def test_dlf_values_on_fails_with_an_explicit_message():
    out = v.evaluate(_status(dlf_offense_only_vote=True, dlf_values_rank_hill_vote=True))
    assert len(out) == 1
    msg = out[0]
    assert "dlf_values_rank_hill_vote is effectively ON" in msg and "must be OFF" in msg
    assert "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE" in msg and ".env" in msg
    assert "owner's activation decision" in msg


def test_dlf_idp_hold_lifted_fails():
    out = v.evaluate(_status(dlf_offense_only_vote=False, dlf_values_rank_hill_vote=False))
    assert len(out) == 1 and "dlf_offense_only_vote is effectively OFF" in out[0]
    assert "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE" in out[0]


def test_both_wrong_reports_both():
    out = v.evaluate(_status(dlf_offense_only_vote=False, dlf_values_rank_hill_vote=True))
    assert len(out) == 2


@pytest.mark.parametrize(
    "status",
    [
        None,
        [],
        {},
        {"featureFlags": {}},
        {"featureFlags": "on"},
        {"featureFlags": {"dlf_offense_only_vote": {"enabled": True}}},  # D4 missing
        {"featureFlags": {"dlf_offense_only_vote": {"enabled": "1"}, **{"x": True}}},
        _status(dlf_offense_only_vote=True, dlf_values_rank_hill_vote=None),
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
        lambda url: _status(dlf_offense_only_vote=True, dlf_values_rank_hill_vote=True),
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

    for env in ("RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE", "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE"):
        monkeypatch.delenv(env, raising=False)
    feature_flags.reload()
    try:
        assert v.evaluate({"featureFlags": feature_flags.effective_flags()}) == []
        monkeypatch.setenv("RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE", "1")
        feature_flags.reload()
        assert v.evaluate({"featureFlags": feature_flags.effective_flags()})
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE", raising=False)
        feature_flags.reload()
