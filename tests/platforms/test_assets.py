from src.platforms.assets import AssetResolver, canonical_pick_id


def directory():
    return {
        "1": {"full_name": "Same Name", "position": "WR", "team": "MIN"},
        "2": {"full_name": "Same Name", "position": "LB", "team": "PIT"},
        "3": {"full_name": "Unique Player Jr.", "position": "RB", "team": "DAL"},
    }


def test_exact_name_team_position_maps_to_sleeper_canonical_id():
    resolver = AssetResolver.from_sleeper_directory(directory())
    result = resolver.resolve(
        platform="ffpc", source_asset_id="x", name="Same Name", nfl_team="MIN", position="WR"
    )
    assert result.canonical_asset_id == "1"
    assert result.match_method == "exact_name_team_position"


def test_ambiguous_exact_name_is_not_auto_mapped():
    resolver = AssetResolver.from_sleeper_directory(directory())
    result = resolver.resolve(platform="ffpc", source_asset_id="x", name="Same Name")
    assert result.canonical_asset_id is None
    assert result.reason == "ambiguous_exact_name"
    assert result.candidates == ("1", "2")


def test_suffix_variation_is_not_silently_auto_mapped():
    resolver = AssetResolver.from_sleeper_directory(directory())
    result = resolver.resolve(
        platform="ffpc",
        source_asset_id="x",
        name="Unique Player",
    )
    assert result.canonical_asset_id is None
    assert result.reason == "no_exact_match"


def test_exact_suffix_maps_when_unambiguous():
    resolver = AssetResolver.from_sleeper_directory(directory())
    result = resolver.resolve(
        platform="ffpc",
        source_asset_id="x",
        name="Unique Player Jr.",
    )
    assert result.canonical_asset_id == "3"


def test_pick_keeps_original_ownership_distinction():
    assert canonical_pick_id(2027, 1, "team-12") == "pick:2027:1:team-12"
    assert canonical_pick_id(2027, 1, "team-99") != canonical_pick_id(2027, 1, "team-12")
