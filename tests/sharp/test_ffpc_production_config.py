import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_ffpc_production_sources_are_public_only_and_usable():
    config = json.loads(
        (ROOT / "config" / "sharp" / "ffpc_sources.json").read_text(encoding="utf-8")
    )
    assert config["enabled"] is True
    assert config["mode"] == "public_only"
    assert config["authenticatedApi"]["enabled"] is False
    assert config["allowProvisionalPublicInCombinedSignals"] is True
    assert 0 < config["provisionalPublicWeight"] < 1

    enabled = [source for source in config["seedLeagues"] if source["enabled"]]
    assert len(enabled) >= 10
    assert all(source["format"] == "dynasty" for source in enabled)
    assert all(source["publicUrl"].startswith("https://myffpc.com/LeagueHome.aspx?") for source in enabled)
    assert all(source["allowProvisionalContribution"] is True for source in enabled)
    assert all(source["sharpEligible"] is False for source in enabled)
