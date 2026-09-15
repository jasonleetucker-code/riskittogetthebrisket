import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from src.serving import input_manifest as manifests


@pytest.fixture
def repo(tmp_path):
    for directory in (
        "src/api",
        "config/model_registry",
        "CSVs/site_raw",
        "data/leagues",
        "data/scrape_state",
    ):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "src/api/data_contract.py").write_text(
        '_SOURCE_CSV_PATHS: dict = {"githubFeed": {"path": "CSVs/site_raw/feed.csv"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "CSVs/site_raw/feed.csv").write_text("name,value\nA,100\n", encoding="utf-8")
    for name in manifests.LEAGUE_CODE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# implementation\n", encoding="utf-8")
    return tmp_path


def test_canonical_inventory_is_explicitly_incomplete_and_never_claims_safe_skip(repo):
    manifest = manifests.capture_canonical_inputs({"players": {"A": 1}}, repo_dir=repo)
    assert manifest.complete is False
    assert len(manifest.unknowns) == 4
    assert any("league_context" in item for item in manifest.unknowns)
    assert any("clock" in item for item in manifest.unknowns)
    assert manifest.input_generations["inputManifestComplete"] == "false"
    assert manifest.as_dict()["unknowns"] == list(manifests.CANONICAL_UNKNOWNS)


def test_observation_timestamp_does_not_change_raw_computation_identity(repo):
    first = manifests.capture_canonical_inputs(
        {"players": {"A": 1}, "scrapeTimestamp": "first"}, repo_dir=repo
    )
    second = manifests.capture_canonical_inputs(
        {"players": {"A": 1}, "scrapeTimestamp": "second"}, repo_dir=repo
    )
    assert first.fingerprint == second.fingerprint
    changed = manifests.capture_canonical_inputs(
        {"players": {"A": 2}, "scrapeTimestamp": "second"}, repo_dir=repo
    )
    assert changed.fingerprint != first.fingerprint


@pytest.mark.parametrize(
    "relative",
    [
        "config/model_registry/hill.json",
        "config/scoring.json",
        "data/leagues/scoring_123.json",
        "data/rank_history.jsonl",
        "data/temporal_ledger.sqlite-wal",
        "data/scrape_state/githubFeed_last_success",
        "src/api/new_owner.py",
    ],
)
def test_missing_created_then_same_size_rewrite_invalidates_known_inputs(repo, relative):
    raw = {"players": {"A": 1}}
    first = manifests.capture_canonical_inputs(raw, repo_dir=repo)
    target = repo / relative
    target.write_text("a", encoding="utf-8")
    created = manifests.capture_canonical_inputs(raw, repo_dir=repo)
    assert first.fingerprint != created.fingerprint
    previous = target.stat()
    target.write_text("b", encoding="utf-8")
    os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    rewritten = manifests.capture_canonical_inputs(raw, repo_dir=repo)
    assert rewritten.fingerprint != created.fingerprint


def test_registered_github_feed_same_size_changes_are_captured(repo):
    first = manifests.capture_canonical_inputs({}, repo_dir=repo)
    target = repo / "CSVs/site_raw/feed.csv"
    stamp = target.stat()
    target.write_text("name,value\nA,101\n", encoding="utf-8")
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    second = manifests.capture_canonical_inputs({}, repo_dir=repo)
    assert first.generations["registeredSourceCSVs"] != second.generations["registeredSourceCSVs"]


def test_registry_and_factual_snapshot_overrides_are_hashed_without_values(
    repo, tmp_path, monkeypatch
):
    override = tmp_path / "external.json"
    override.write_text('{"private":"alpha"}', encoding="utf-8")
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(override))
    first = manifests.capture_canonical_inputs({}, repo_dir=repo)
    override.write_text('{"private":"omega"}', encoding="utf-8")
    second = manifests.capture_canonical_inputs({}, repo_dir=repo)
    assert first.generations["registryOverride"] != second.generations["registryOverride"]
    assert "omega" not in str(second.as_dict())


def test_data_archives_and_unrelated_caches_are_not_traversed(repo, monkeypatch):
    archive = repo / "data/archive"
    archive.mkdir()
    (archive / "huge.bin").write_bytes(b"do not read")
    original = manifests.file_identity

    def checked(path):
        assert "archive" not in path.parts
        return original(path)

    monkeypatch.setattr(manifests, "file_identity", checked)
    manifests.capture_canonical_inputs({}, repo_dir=repo)


@dataclass
class Config:
    key: str = "league"
    scoring_profile: str = "scoring"


def league_manifest(repo, *, board=None, cfg=None, overlay=None, scoring="card", settings=None):
    return manifests.league_input_manifest(
        board or SimpleNamespace(generation_id="logical", artifact_generation_id="physical"),
        cfg or Config(),
        overlay or {"teams": [{"players": ["A"]}], "overlayFetchedAt": "first"},
        factual_scoring_fingerprint=scoring,
        registry_defaults={} if settings is None else settings,
        repo_dir=repo,
    )


def test_league_reobservation_uses_logical_board_and_ignores_only_root_observation(repo):
    first = league_manifest(repo)
    second = league_manifest(
        repo,
        board=SimpleNamespace(generation_id="logical", artifact_generation_id="new-physical"),
        overlay={"teams": [{"players": ["A"]}], "overlayFetchedAt": "second"},
    )
    assert first.complete
    assert first.fingerprint == second.fingerprint
    changed = league_manifest(
        repo,
        overlay={
            "teams": [{"players": ["A"]}],
            "overlayFetchedAt": "second",
            "tradeWindowStart": "new",
        },
    )
    assert first.fingerprint != changed.fingerprint


@pytest.mark.parametrize("change", ["board", "roster", "card", "config", "settings", "code"])
def test_every_league_computation_dependency_invalidates(repo, change):
    first = league_manifest(repo)
    args = {}
    if change == "board":
        args["board"] = SimpleNamespace(generation_id="new")
    elif change == "roster":
        args["overlay"] = {"teams": [{"players": ["B"]}]}
    elif change == "card":
        args["scoring"] = "new-card"
    elif change == "config":
        args["cfg"] = Config(scoring_profile="new-profile")
    elif change == "settings":
        args["settings"] = {"starters": ["QB"]}
    else:
        (repo / "src/ros/lineup.py").write_text("new logic", encoding="utf-8")
    assert first.fingerprint != league_manifest(repo, **args).fingerprint


def test_unknown_factual_card_disables_league_skip(repo):
    assert league_manifest(repo, scoring=None).complete is False


def test_missing_projection_owner_disables_league_skip(repo):
    (repo / "src/serving/league_views.py").unlink()
    assert league_manifest(repo).complete is False


def test_manifest_detects_mutation_after_capture(repo):
    overlay = {"teams": [{"players": ["A"]}]}
    manifest = league_manifest(repo, overlay=overlay)
    assert manifest.verify()
    overlay["teams"][0]["players"].append("B")
    assert not manifest.verify()
