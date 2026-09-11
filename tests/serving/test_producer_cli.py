"""CLI integration with stub domain builders/providers and real artifact files."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_source_producer as cli
from src.serving import producer
from src.serving.artifacts import ArtifactStore, CorruptArtifact, PublishLockTimeout, _publish_lock
from src.serving.producer_status import OWNERSHIP_ASSET, OWNERSHIP_KEY, RECEIPT_FILE, STATUS_FILE


@pytest.fixture
def worker(tmp_path, monkeypatch):
    config = producer.ProducerConfig(
        tmp_path, tmp_path / "data", artifact_root=tmp_path / "private"
    )
    config.data_dir.mkdir()
    raw = {
        "players": {"1": {"name": "A"}},
        "sites": [{"playerCount": 1}],
        "scrapeTimestamp": datetime.now(timezone.utc).isoformat(),
    }
    bootstrap = tmp_path / "accepted.json"
    bootstrap.write_text(json.dumps(raw), encoding="utf-8")
    calls = []

    async def scrape(**_kwargs):
        calls.append("scrape")
        return raw

    def supplements(_config, emit):
        for source, _, _ in producer.SUPPLEMENTAL_SOURCES:
            emit("source_attempt", source=source, outcome="success", exitCode=0)

    monkeypatch.setattr(
        producer, "_load_scraper", lambda _config: SimpleNamespace(run=scrape, SITES={"KTC": True})
    )
    monkeypatch.setattr(producer, "_run_supplemental_sources", supplements)
    monkeypatch.setattr(producer, "_check_disk_space", lambda _config: (True, 1000))
    from src.maintenance import retention

    monkeypatch.setattr(
        retention, "prune_data_dir", lambda _root: SimpleNamespace(total_deleted=0, total_errors=0)
    )

    def build(raw, source, *, is_fresh_scrape):
        calls.append("build")
        assert is_fresh_scrape is True
        return SimpleNamespace(raw=raw, source=source)

    def record(candidate):
        calls.append("record")

    def publish(candidate, *, store, input_generations):
        calls.append("publish")
        return store.publish(
            "canonical-serving",
            "default",
            {"input.json": json.dumps(candidate.raw).encode()},
            {
                "modelVersion": "test",
                "inputGenerations": input_generations,
                "configHash": "test",
                "sourceAsOf": candidate.source["producedAt"],
            },
        )

    def league_refresh(*, store):
        calls.append("leagues")
        assert store.root == config.serving_root
        return {"outcome": "success"}

    builder = SimpleNamespace(build_generation=build, record_accepted_generation=record)
    serialization = SimpleNamespace(
        ASSET="canonical-serving",
        KEY="default",
        publish_generation=publish,
        load_generation=lambda artifact: SimpleNamespace(
            raw=json.loads(artifact.files["input.json"])
        ),
    )
    leagues = SimpleNamespace(refresh_league_serving=league_refresh)
    monkeypatch.setitem(sys.modules, "src.serving.builder", builder)
    monkeypatch.setitem(sys.modules, "src.serving.serialization", serialization)
    monkeypatch.setitem(sys.modules, "src.serving.league_views", leagues)
    return SimpleNamespace(
        config=config,
        raw=raw,
        bootstrap=bootstrap,
        calls=calls,
        builder=builder,
        serialization=serialization,
        leagues=leagues,
    )


def test_cli_load_build_publish_history_league_order_and_receipt(worker, capsys):
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    assert worker.calls == ["scrape", "build", "publish", "record", "leagues"]
    store = ArtifactStore(worker.config.artifact_root)
    assert producer.source_receipt_ready(store)
    output = json.loads(capsys.readouterr().out)
    assert (
        output["acceptedGeneration"]
        == store.read_current("canonical-serving", "default").generation_id
    )
    assert cli._accepted_raw(store, None) == worker.raw
    artifact = store.read_current("canonical-serving", "default")
    assert artifact.manifest["inputGenerations"]["inputManifestComplete"] == "false"
    receipt = json.loads((store.root / RECEIPT_FILE).read_bytes())
    assert receipt["canonicalInputs"]["complete"] is False
    assert receipt["canonicalInputs"]["unknowns"]
    proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    assert json.loads(proof.files["receipt.json"]) == receipt
    assert json.loads((store.root / STATUS_FILE).read_bytes())["sourceOwnership"] == {
        "outcome": "verified"
    }


def test_cli_attests_inside_the_source_lease(worker, monkeypatch):
    from src.serving import producer_status

    checked = []
    original = producer_status._attest_current_source_ownership

    def attest(store):
        with pytest.raises(PublishLockTimeout):
            with _publish_lock(store.root / "producer.lock", 0):
                pytest.fail("source lease released before strict attestation")
        original(store)
        checked.append(store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY).generation_id)

    monkeypatch.setattr(producer_status, "_attest_current_source_ownership", attest)
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    assert len(checked) == 1


def test_healthy_recurring_cycles_retain_one_ownership_proof(worker):
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    store = ArtifactStore(worker.config.artifact_root)
    proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    first_board = store.read_current("canonical-serving", "default").generation_id
    worker.raw["players"]["2"] = {"name": "B"}
    assert asyncio.run(cli._run(worker.config, None)) == 0
    assert store.read_current("canonical-serving", "default").generation_id != first_board
    assert store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY).generation_id == proof.generation_id
    assert producer.source_receipt_ready(store)
    assert json.loads(proof.files["receipt.json"])["acceptedGeneration"] == first_board
    assert json.loads((store.root / STATUS_FILE).read_bytes())["sourceOwnership"] == {
        "outcome": "retained"
    }
    proof_root = store.root / OWNERSHIP_ASSET / OWNERSHIP_KEY / "generations"
    assert len(list(proof_root.iterdir())) == 1


@pytest.mark.parametrize("existing_proof", [False, True])
def test_degraded_accepted_cycle_cannot_mint_ownership(worker, monkeypatch, existing_proof):
    store = ArtifactStore(worker.config.artifact_root)
    before = None
    if existing_proof:
        assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
        before = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY).generation_id

    def supplements(_config, emit):
        for source, _, _ in producer.SUPPLEMENTAL_SOURCES:
            emit("source_attempt", source=source, outcome="failed", exitCode=1)

    monkeypatch.setattr(producer, "_run_supplemental_sources", supplements)
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    assert store.read_current("canonical-serving", "default")
    assert not producer.source_receipt_ready(store)
    status = json.loads((store.root / STATUS_FILE).read_bytes())
    assert status["sourceOwnership"]["outcome"] == ("retained" if existing_proof else "unverified")
    if existing_proof:
        assert store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY).generation_id == before
    else:
        assert not (store.root / OWNERSHIP_ASSET).exists()


def test_proof_write_failure_fails_worker_without_dropping_accepted_board(worker, monkeypatch):
    original = ArtifactStore.publish

    def publish(store, asset, *args, **kwargs):
        if asset == OWNERSHIP_ASSET:
            raise OSError("proof unavailable")
        return original(store, asset, *args, **kwargs)

    monkeypatch.setattr(ArtifactStore, "publish", publish)
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 1
    store = ArtifactStore(worker.config.artifact_root)
    assert store.read_current("canonical-serving", "default")
    assert not (store.root / OWNERSHIP_ASSET).exists()
    status = json.loads((store.root / STATUS_FILE).read_bytes())
    assert status["outcome"] == "failed"
    assert [run["outcome"] for run in status["runs"]] == ["failed"]
    assert worker.calls.count("record") == 1


@pytest.mark.parametrize(
    "published,failed,outcome",
    [
        (["a"], [], "success"),
        (["a"], ["b"], "partial"),
        ([], ["b"], "failed"),
        ([], [], "success"),
    ],
)
def test_cli_derives_actual_league_refresh_outcome(worker, monkeypatch, published, failed, outcome):
    monkeypatch.setattr(
        worker.leagues,
        "refresh_league_serving",
        lambda **_kwargs: {"published": published, "failed": failed},
    )
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    status = json.loads((worker.config.serving_root / STATUS_FILE).read_bytes())
    assert status["leagueRefresh"] == {
        "outcome": outcome,
        "published": len(published),
        "failed": len(failed),
    }


@pytest.mark.parametrize("failure", ["build", "publish"])
def test_failed_build_or_publication_cannot_record_history_or_cutover(worker, monkeypatch, failure):
    def fail(*_args, **_kwargs):
        raise ValueError("rejected")

    monkeypatch.setattr(
        worker.builder if failure == "build" else worker.serialization,
        "build_generation" if failure == "build" else "publish_generation",
        fail,
    )
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 1
    assert "record" not in worker.calls
    assert "leagues" not in worker.calls
    assert not (worker.config.serving_root / RECEIPT_FILE).exists()


def test_league_refresh_failure_keeps_accepted_canonical_and_receipt(worker, monkeypatch):
    def fail(**_kwargs):
        raise RuntimeError("temporary league provider failure")

    monkeypatch.setattr(worker.leagues, "refresh_league_serving", fail)
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    assert producer.source_receipt_ready(ArtifactStore(worker.config.artifact_root))
    status = json.loads((worker.config.serving_root / STATUS_FILE).read_bytes())
    assert status["leagueRefresh"]["outcome"] == "failed"
    assert worker.calls.count("record") == 1


def test_bootstrap_requires_explicit_accepted_raw_before_source_execution(worker):
    assert asyncio.run(cli._run(worker.config, None)) == 1
    assert worker.calls == []
    assert not (worker.config.serving_root / RECEIPT_FILE).exists()


def test_corrupt_current_generation_never_falls_back_to_bootstrap(worker):
    assert asyncio.run(cli._run(worker.config, worker.bootstrap)) == 0
    current = worker.config.serving_root / "canonical-serving/default/current.json"
    current.write_text("broken", encoding="utf-8")
    with pytest.raises(CorruptArtifact):
        cli._accepted_raw(ArtifactStore(worker.config.artifact_root), worker.bootstrap)


def test_history_maintenance_reuses_existing_owner_only_if_empty(worker, monkeypatch):
    from src.api import source_history

    history = worker.config.data_dir / "source_history.jsonl"
    export = worker.config.data_dir / "dynasty_data_2026-09-10.json"
    export.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(source_history, "HISTORY_PATH", history)
    calls = []
    monkeypatch.setattr(
        source_history, "backfill_from_exports", lambda paths: calls.append(paths) or 1
    )
    assert cli.backfill_history(worker.config) == 1
    assert calls == [[export]]
    history.write_text("existing", encoding="utf-8")
    assert cli.backfill_history(worker.config) == 0
    assert calls == [[export]]
    assert worker.calls == []
    assert not (worker.config.serving_root / RECEIPT_FILE).exists()


def test_import_has_no_server_scraper_builder_or_provider_side_effects():
    root = Path(__file__).resolve().parents[2]
    script = "import sys; import scripts.run_source_producer; assert not ({'server', 'Dynasty_Scraper', 'src.serving.builder', 'scripts.fetch_dynasty_nerds', 'scripts.fetch_idpshow'} & set(sys.modules))"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=root, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_source_and_league_templates_are_opt_in_processes():
    root = Path(__file__).resolve().parents[2] / "deploy/systemd"
    source = (root / "dynasty-source-producer.service.template").read_text(encoding="utf-8")
    league = (root / "dynasty-league-serving.service.template").read_text(encoding="utf-8")
    assert "scripts/run_source_producer.py" in source
    assert "SuccessExitStatus=3" in source
    for template in (source, league):
        assert "Type=oneshot" in template
        assert "KillMode=control-group" in template
        assert "UMask=0077" in template
    timer = (root / "dynasty-league-serving.timer.template").read_text(encoding="utf-8")
    assert "OnUnitActiveSec=10min" in timer
