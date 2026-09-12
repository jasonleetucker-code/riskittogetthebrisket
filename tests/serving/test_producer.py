"""Offline preservation of the live source cycle and its admission/publication guards."""

from __future__ import annotations

import asyncio
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.serving import producer
from src.serving.artifacts import _publish_lock


def raw(count=4, **changes):
    return {
        "players": {str(index): {"name": str(index)} for index in range(count)},
        "sites": [{"key": "ktc", "playerCount": 2}, {"key": "idpTradeCalc", "playerCount": 2}],
        "coverageAudit": {"expectedSites": {"offense": ["ktc"], "idp": ["idpTradeCalc"]}},
        "date": "2026-09-10",
        "scrapeTimestamp": "2026-09-10T12:00:00+00:00",
        **changes,
    }


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    config = producer.ProducerConfig(
        tmp_path, tmp_path / "data", artifact_root=tmp_path / "private"
    )
    config.data_dir.mkdir()
    events, calls = [], []
    result = raw()

    async def run(*, progress_callback):
        calls.append("core")
        await progress_callback({"step": "core", "source": "ktc", "event": "done"})
        return result

    monkeypatch.setattr(
        producer,
        "_load_scraper",
        lambda _config: SimpleNamespace(
            run=run, SITES={"KTC": True, "IDPTradeCalc": True, "disabled": False}
        ),
    )
    monkeypatch.setattr(producer, "_check_disk_space", lambda _config: (True, 1000))
    from src.maintenance import retention

    monkeypatch.setattr(
        retention, "prune_data_dir", lambda _root: SimpleNamespace(total_deleted=0, total_errors=0)
    )
    for source, script, expected_args in producer.SUPPLEMENTAL_SOURCES:
        module_name = Path(script).stem

        def main(args, source=source, expected_args=expected_args):
            assert args == list(expected_args)
            calls.append(source)
            return 0

        stub = SimpleNamespace(main=main)
        monkeypatch.setitem(sys.modules, f"scripts.{module_name}", stub)
        import scripts

        monkeypatch.setattr(scripts, module_name, stub, raising=False)

    async def publish(candidate, source):
        calls.append("publish")
        assert candidate is result
        assert source["producedAt"] == result["scrapeTimestamp"]
        assert source["loadedAt"] != source["producedAt"]

    def event(name, **meta):
        events.append((name, meta))

    return SimpleNamespace(
        config=config, result=result, calls=calls, events=events, publish=publish, event=event
    )


def test_exact_source_set_args_mirrors_timestamp_and_success(cycle):
    (cycle.config.repo_dir / "idpshow_session.json").write_text("opaque", encoding="utf-8")
    source = cycle.config.data_dir / "exports/latest/site_raw"
    target = cycle.config.repo_dir / "CSVs/site_raw"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    for name in producer.MIRROR_FILES:
        (source / name).write_text(name, encoding="utf-8")
    (source / "unrelated.csv").write_text("do not mirror", encoding="utf-8")
    result = asyncio.run(
        producer.run_source_cycle(cycle.config, raw(), publish=cycle.publish, event=cycle.event)
    )
    assert result.outcome == "success"
    assert cycle.calls == [
        "core",
        "dynastyNerdsSfTep",
        "fantasyProsSf",
        "fantasyProsIdp",
        "idpShow",
        "publish",
    ]
    assert sorted(path.name for path in target.iterdir()) == sorted(producer.MIRROR_FILES)
    assert result.source_evidence["core"]["enabledSites"] == ["IDPTradeCalc", "KTC"]
    assert all(
        attempt["outcome"] == "success" for attempt in result.source_evidence["supplemental"]
    )


def test_conditional_idpshow_missing_is_explicit_skip(cycle):
    result = asyncio.run(producer.run_source_cycle(cycle.config, raw(), publish=cycle.publish))
    assert result.outcome == "success"
    assert "idpShow" not in cycle.calls
    assert result.source_evidence["supplemental"][-1] == {
        "source": "idpShow",
        "outcome": "skipped",
        "reason": "session_missing",
    }


@pytest.mark.parametrize(
    "exit_code,expected_event,level",
    [
        (1, "dynasty_nerds_fetch_failed", "warning"),
        (2, "dynasty_nerds_schema_regression", "error"),
    ],
)
def test_supplemental_return_codes_preserve_warning_only_promotion(
    cycle, monkeypatch, exit_code, expected_event, level
):
    monkeypatch.setattr(sys.modules["scripts.fetch_dynasty_nerds"], "main", lambda _args: exit_code)
    result = asyncio.run(
        producer.run_source_cycle(cycle.config, raw(), publish=cycle.publish, event=cycle.event)
    )
    assert result.outcome == "success"
    assert next(meta for name, meta in cycle.events if name == expected_event)["level"] == level
    assert result.source_evidence["supplemental"][0]["outcome"] == "failed"


def test_supplemental_exception_does_not_skip_later_sources(cycle, monkeypatch):
    def fail(_args):
        raise RuntimeError("transient")

    monkeypatch.setattr(sys.modules["scripts.fetch_dynasty_nerds"], "main", fail)
    result = asyncio.run(
        producer.run_source_cycle(cycle.config, raw(), publish=cycle.publish, event=cycle.event)
    )
    assert result.outcome == "success"
    assert "fantasyProsIdp" in cycle.calls
    assert any(name == "dynasty_nerds_fetch_exception" for name, _ in cycle.events)


@pytest.mark.parametrize("kind", ["anchor", "collapse", "half", "empty"])
def test_promotion_guards_keep_accepted_raw_and_never_call_publisher(cycle, kind):
    previous = raw(8)
    if kind == "anchor":
        cycle.result["sites"][0]["playerCount"] = 0
    elif kind == "half":
        cycle.result.pop("coverageAudit")
        cycle.result["sites"] = [{"playerCount": count} for count in (1, 0, 0)]
        previous = raw()
    elif kind == "empty":
        cycle.result["players"] = {}
    result = asyncio.run(producer.run_source_cycle(cycle.config, previous, publish=cycle.publish))
    assert result.outcome == ("failed" if kind == "empty" else "blocked")
    if kind != "empty":
        assert result.raw is previous
    assert "publish" not in cycle.calls


def test_exact_retention_floor_and_half_sources_are_allowed_without_missing_anchor():
    candidate = raw(3, coverageAudit={}, sites=[{"playerCount": 1}, {"playerCount": 0}])
    assert producer.promotion_reason(candidate, raw(4)) == ""
    assert "COLLAPSE" in producer.promotion_reason(candidate, raw(5))


@pytest.mark.parametrize(
    "shape", [None, {}, {"coverageAudit": "bad"}, {"coverageAudit": {"expectedSites": "bad"}}]
)
def test_missing_anchor_diagnostic_preserves_malformed_fail_open(shape):
    assert producer.missing_expected_sites(shape) == []


def test_site_stats_positive_counts_can_prove_anchor():
    candidate = raw(sites=[], siteStats={"ktc": {"count": 1}, "idpTradeCalc": {"count": 1}})
    assert producer.missing_expected_sites(candidate) == []
    candidate["siteStats"]["ktc"]["count"] = "1"
    assert producer.missing_expected_sites(candidate) == ["ktc"]


@pytest.mark.parametrize("requires_disk,outcome", [(False, "success"), (True, "blocked")])
def test_low_disk_preserves_legacy_mode_and_blocks_disk_publication(
    cycle, monkeypatch, requires_disk, outcome
):
    from dataclasses import replace

    monkeypatch.setattr(producer, "_check_disk_space", lambda _config: (False, 2))
    config = replace(cycle.config, publication_requires_disk=requires_disk)
    result = asyncio.run(producer.run_source_cycle(config, raw(), publish=cycle.publish))
    assert result.outcome == outcome


def test_failed_publisher_never_replaces_accepted_recovery_export(cycle):
    source = cycle.config.data_dir / "exports/latest/dynasty_data_2026-09-10.json"
    target = cycle.config.repo_dir / "exports/latest/dynasty_data_2026-09-10.json"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("new", encoding="utf-8")
    target.write_text("accepted", encoding="utf-8")

    async def fail(_raw, _source):
        raise ValueError("rejected canonical candidate")

    result = asyncio.run(producer.run_source_cycle(cycle.config, raw(), publish=fail))
    assert result.outcome == "failed"
    assert target.read_text(encoding="utf-8") == "accepted"


def test_lease_covers_accepted_input_loading_publish_and_completion(cycle):
    observed = []

    def accepted():
        with (
            pytest.raises(producer.PublishLockTimeout),
            _publish_lock(cycle.config.serving_root / "producer.lock", 0),
        ):
            pass
        observed.append("load")
        return raw()

    async def scenario():
        async def publish(_raw, _source):
            competitor = await producer.run_source_cycle(
                cycle.config, raw(), publish=cycle.publish, event=cycle.event
            )
            assert competitor.outcome == "busy"
            observed.append("publish")

        def completed(_result):
            with (
                pytest.raises(producer.PublishLockTimeout),
                _publish_lock(cycle.config.serving_root / "producer.lock", 0),
            ):
                pass
            observed.append("completed")

        return await producer.run_source_cycle(
            cycle.config, accepted, publish=publish, completed=completed
        )

    assert asyncio.run(scenario()).outcome == "success"
    assert observed == ["load", "publish", "completed"]
    assert cycle.calls.count("core") == 1
    with _publish_lock(cycle.config.serving_root / "producer.lock", 0):
        pass


def test_cancelled_cycle_releases_lease(cycle, monkeypatch):
    async def cancel(*, progress_callback):
        raise asyncio.CancelledError

    monkeypatch.setattr(producer, "_load_scraper", lambda _config: SimpleNamespace(run=cancel))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(producer.run_source_cycle(cycle.config, raw(), publish=cycle.publish))
    with _publish_lock(cycle.config.serving_root / "producer.lock", 0):
        pass


def test_source_code_change_during_collection_refuses_parity_claim(cycle, monkeypatch):
    original = producer.source_parity_contract
    checks = 0

    def changed():
        nonlocal checks
        checks += 1
        return {**original(), "version": checks}

    monkeypatch.setattr(producer, "source_parity_contract", changed)
    result = asyncio.run(producer.run_source_cycle(cycle.config, raw(), publish=cycle.publish))
    assert result.outcome == "failed"
    assert "changed during collection" in result.reason
    assert "publish" not in cycle.calls


def test_timeout_finishes_failed_and_releases_lease(cycle, monkeypatch):
    from dataclasses import replace

    async def hanging(*, progress_callback):
        await asyncio.Event().wait()

    monkeypatch.setattr(producer, "_load_scraper", lambda _config: SimpleNamespace(run=hanging))
    config = replace(cycle.config, timeout_seconds=0.01)
    results = []
    result = asyncio.run(
        producer.run_source_cycle(config, raw(), publish=cycle.publish, completed=results.append)
    )
    assert result.outcome == "failed"
    assert "TimeoutError" in result.reason
    assert results == [result]
    with _publish_lock(config.serving_root / "producer.lock", 0):
        pass


def test_scraper_is_only_loaded_on_explicit_cycle_and_uses_data_directory(tmp_path):
    config = producer.ProducerConfig(tmp_path, tmp_path / "data")
    (tmp_path / "Dynasty Scraper.py").write_text(
        "SCRIPT_DIR = 'original'\nSITES = {}\n", encoding="utf-8"
    )
    scraper = producer._load_scraper(config)
    assert scraper.SCRIPT_DIR == str(config.data_dir)


def test_source_script_compiles_and_does_not_import_web_server():
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "src/serving/producer.py",
        "src/serving/producer_status.py",
        "scripts/run_source_producer.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(text)
        compile(tree, relative, "exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "server" for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "server"


def test_dry_run_only_prints_plan_without_creating_store(tmp_path, capsys):
    from scripts.run_source_producer import main

    root = tmp_path / "not-created"
    assert main(["--dry-run", "--artifact-root", str(root)]) == 0
    assert not root.exists()
    output = json.loads(capsys.readouterr().out)
    assert output["sourceParity"] == producer.source_parity_contract()
