from types import SimpleNamespace

from src.sharp import market


def _member(mode):
    return SimpleNamespace(
        manager_key=f"sleeper:{mode}",
        person_id=f"person:{mode}",
        platform="sleeper",
        qualification_method=(
            "both_curated_and_performance" if mode == "both" else "curated_industry"
        ),
        quality=0.9,
        display_name=mode,
        network="Network A",
    )


def test_curated_population_is_a_separate_qualification_path(monkeypatch):
    monkeypatch.setattr(
        market.platform_records, "build_manager_records", lambda **_kwargs: ([], {})
    )
    monkeypatch.setattr(market.sharp_score, "score_managers", lambda _records: [])
    monkeypatch.setattr(
        market.curated_model,
        "curated_cohort_members",
        lambda mode, **_kwargs: [_member(mode)],
    )
    config = {"enabled": False}

    industry, coverage = market.cohort_members(qualification="industry", ffpc_config=config)
    super_sharps, _ = market.cohort_members(qualification="super", ffpc_config=config)
    both, _ = market.cohort_members(qualification="both", ffpc_config=config)

    assert [member.manager_key for member in industry] == ["sleeper:curated_industry"]
    assert [member.manager_key for member in super_sharps] == ["sleeper:super"]
    assert both[0].qualification_method == "both_curated_and_performance"
    assert coverage["curatedIndustryTrackedAccounts"] == 1


def test_all_includes_curated_industry_without_calling_it_empirical(monkeypatch):
    monkeypatch.setattr(
        market.platform_records, "build_manager_records", lambda **_kwargs: ([], {})
    )
    monkeypatch.setattr(market.sharp_score, "score_managers", lambda _records: [])
    monkeypatch.setattr(
        market.curated_model,
        "curated_cohort_members",
        lambda mode, **_kwargs: [_member(mode)] if mode == "curated_industry" else [],
    )
    members, _ = market.cohort_members(qualification="all", ffpc_config={"enabled": False})
    assert len(members) == 1
    assert members[0].qualification_method == "curated_industry"
