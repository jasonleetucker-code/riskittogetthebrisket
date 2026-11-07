"""Pin scripts/ci_test_shards.py — the sharded hard gate's split and its proof.

The property that matters is not speed but completeness: every collected
hard-gate test runs on exactly one runner, and a run that cannot prove that is
red.  These tests use independent expectations (hand-built manifests, a real
pytest run over a tiny fixture suite) rather than calling the assignment and
then trusting it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts import ci_test_shards as shards
from scripts.ci_test_shards import (
    ShardConfig,
    ShardError,
    assign_files,
    collected_digest,
    parse_shard_spec,
    verify_manifests,
)

REPO = Path(__file__).resolve().parents[2]


# ── shard spec ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("spec,expected", [("1/1", (1, 1)), ("3/8", (3, 8)), (" 8/8 ", (8, 8))])
def test_parse_shard_spec_accepts_one_based_specs(spec, expected):
    assert parse_shard_spec(spec) == expected


@pytest.mark.parametrize("spec", ["0/8", "9/8", "1/0", "3", "a/b", "1/2/3", ""])
def test_parse_shard_spec_refuses_anything_else(spec):
    with pytest.raises(ShardError):
        parse_shard_spec(spec)


# ── assignment ─────────────────────────────────────────────────────────


def _files(n: int) -> dict[str, int]:
    return {f"tests/pkg{i % 7}/test_m{i:03d}.py": 1 + (i * 37) % 23 for i in range(n)}


@pytest.mark.parametrize("shard_count", [1, 2, 3, 8, 13])
def test_every_file_lands_on_exactly_one_valid_shard(shard_count):
    files = _files(120)
    assignment = assign_files(files, shard_count)
    assert set(assignment) == set(files)
    assert set(assignment.values()) <= set(range(1, shard_count + 1))


def test_assignment_is_deterministic_regardless_of_input_order():
    files = _files(200)
    reversed_files = dict(reversed(list(files.items())))
    durations = {f: float(n) * 0.3 for f, n in list(files.items())[::3]}
    assert assign_files(files, 8, durations) == assign_files(reversed_files, 8, durations)


def test_recorded_durations_override_test_counts():
    # One slow file with few tests must not be packed as if it were cheap.
    files = {"tests/test_slow.py": 2, **{f"tests/test_fast{i}.py": 50 for i in range(6)}}
    durations = {"tests/test_slow.py": 600.0, **{f"tests/test_fast{i}.py": 10.0 for i in range(6)}}
    assignment = assign_files(files, 2, durations)
    slow_shard = assignment["tests/test_slow.py"]
    # Every fast file goes to the OTHER shard: 600 s outweighs all 60 s of them.
    assert all(assignment[f] != slow_shard for f in files if f != "tests/test_slow.py")


def test_lpt_balance_bound_holds():
    """Graham's bound for longest-processing-time-first: the busiest shard
    carries at most 4/3 of the optimum, so at most 4/3 of max(mean, largest)."""
    files = _files(300)
    durations = {f: float(sum(map(ord, f)) % 97 + 1) for f in files}
    n = 8
    assignment = assign_files(files, n, durations)
    loads = [0.0] * n
    for f, s in assignment.items():
        loads[s - 1] += durations[f]
    lower_bound = max(sum(durations.values()) / n, max(durations.values()))
    assert max(loads) <= (4 / 3) * lower_bound + 1e-9


def test_unknown_files_are_estimated_from_the_recorded_rate():
    weights = shards.file_weights({"a.py": 10, "b.py": 10, "new.py": 4}, {"a.py": 5.0, "b.py": 5.0})
    assert weights["new.py"] == pytest.approx(4 * 0.5)


def test_file_of_strips_the_node_part_and_normalises_separators():
    assert shards.file_of("tests/api/test_x.py::TestC::test_y[a::b]") == "tests/api/test_x.py"
    assert shards.file_of("tests\\api\\test_x.py::test_y") == "tests/api/test_x.py"


# ── verification (hand-built manifests: an independent oracle) ──────────


CONFIG = ShardConfig(shard_count=3, min_collected=6, max_skipped=2, durations={})
ALL = [f"tests/test_{c}.py::t{i}" for c in "abc" for i in range(2)]


def _manifest(idx, selected, *, outcomes=None, exitstatus=0, collected=ALL, verdicts=None):
    outcomes = outcomes or {"passed": len(selected), "skipped": 0}
    return {
        "version": shards.MANIFEST_VERSION,
        "shard": idx,
        "shard_count": 3,
        "collected_total": len(collected),
        "collected_sha256": collected_digest(collected),
        "selected": sorted(selected),
        "verdict_sha256": collected_digest(selected if verdicts is None else verdicts),
        "outcomes": outcomes,
        "exitstatus": exitstatus,
        "file_seconds": {},
    }


def _complete():
    return [_manifest(1, ALL[:2]), _manifest(2, ALL[2:4]), _manifest(3, ALL[4:])]


def test_a_complete_partition_verifies():
    assert verify_manifests(_complete(), CONFIG) == []


def test_a_missing_shard_is_refused():
    problems = verify_manifests(_complete()[:2], CONFIG)
    assert any("shard(s) [3]" in p for p in problems)


def test_a_test_selected_twice_is_refused():
    ms = _complete()
    ms[1] = _manifest(2, ALL[1:4])
    assert any("selected by shards 1 and 2" in p for p in verify_manifests(ms, CONFIG))


def test_a_test_selected_by_nobody_is_refused():
    ms = _complete()
    ms[2] = _manifest(3, ALL[4:5])
    assert any("ran nowhere" in p for p in verify_manifests(ms, CONFIG))


def test_shards_that_collected_different_sets_are_refused():
    ms = _complete()
    ms[0] = _manifest(1, ALL[:2], collected=ALL + ["tests/test_d.py::t0"])
    assert any("different test sets" in p for p in verify_manifests(ms, CONFIG))


def test_a_failed_shard_is_refused():
    ms = _complete()
    ms[1] = _manifest(2, ALL[2:4], exitstatus=1, outcomes={"passed": 1, "failed": 1})
    assert any("shard 2 exited 1" in p for p in verify_manifests(ms, CONFIG))


def test_a_selected_test_without_a_verdict_is_refused():
    ms = _complete()
    ms[0] = _manifest(1, ALL[:2], outcomes={"passed": 1}, verdicts=ALL[:1])
    assert any("never ran" in p for p in verify_manifests(ms, CONFIG))


def test_a_different_verdict_set_of_the_same_size_is_refused():
    ms = _complete()
    ms[0] = _manifest(1, ALL[:2], verdicts=[ALL[0], "tests/test_z.py::t9"])
    assert any("never ran" in p for p in verify_manifests(ms, CONFIG))


def test_the_collection_floor_is_enforced():
    floor = ShardConfig(shard_count=3, min_collected=7, max_skipped=2, durations={})
    assert any("below the floor" in p for p in verify_manifests(_complete(), floor))


def test_the_skip_budget_is_enforced_suite_wide():
    ms = _complete()
    ms[0] = _manifest(1, ALL[:2], outcomes={"passed": 0, "skipped": 2})
    ms[2] = _manifest(3, ALL[4:], outcomes={"passed": 1, "skipped": 1})
    assert any("skip budget" in p for p in verify_manifests(ms, CONFIG))


def test_module_level_skips_count_once_against_the_budget():
    ms = _complete()
    for m in ms:
        m["collect_skipped"] = ["tests/test_x.py", "tests/test_y.py", "tests/test_z.py"]
    assert any("skip budget" in p for p in verify_manifests(ms, CONFIG))
    for m in ms:
        m["collect_skipped"] = ["tests/test_x.py", "tests/test_y.py"]
    assert verify_manifests(ms, CONFIG) == []


def test_shards_disagreeing_on_module_skips_are_refused():
    ms = _complete()
    ms[0]["collect_skipped"] = ["tests/test_x.py"]
    assert any("skipped different modules" in p for p in verify_manifests(ms, CONFIG))


def test_a_shard_count_mismatch_is_refused():
    ms = _complete()
    ms[0]["shard_count"] = 4
    assert any("shard_count 4" in p for p in verify_manifests(ms, CONFIG))


def test_the_committed_config_loads_and_names_a_real_floor_and_budget():
    config = ShardConfig.load()
    assert config.shard_count >= 2
    assert config.min_collected > 10_000, "the floor must catch a directory that stopped collecting"
    assert 0 < config.max_skipped < config.min_collected


def test_register_is_a_no_op_without_the_shard_variable():
    class _PM:
        def register(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("registered without RISKIT_TEST_SHARD")

    assert shards.register_if_requested(_PM(), environ={}) is None


def test_register_refuses_a_spec_that_disagrees_with_the_config(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text(
        json.dumps({"shard_count": 4, "min_collected": 1, "max_skipped": 1}), encoding="utf-8"
    )
    with pytest.raises(ShardError, match="disagrees"):
        shards.register_if_requested(object(), environ={shards.SHARD_ENV: "1/3"}, config_path=cfg)


# ── the real plugin, end to end, over a tiny suite ──────────────────────

_FIXTURE_TESTS = {
    "test_alpha.py": """
        import pytest

        def test_pass():
            assert True

        @pytest.mark.skipif(True, reason="setup-phase skip")
        def test_setup_skip():
            pass

        def test_call_skip():
            pytest.skip("call-phase skip")

        @pytest.mark.xfail(reason="known")
        def test_xfail():
            assert False

        @pytest.mark.xfail(run=False, reason="not run")
        def test_xfail_not_run():
            pass
    """,
    "test_beta.py": """
        def test_with_subtests(subtests):
            for i in range(4):
                with subtests.test(i=i):
                    assert i >= 0

        def test_plain():
            assert 1 + 1 == 2
    """,
    "test_gamma.py": """
        import pytest

        @pytest.mark.parametrize("n", range(5))
        def test_param(n):
            assert n < 5
    """,
    "test_delta.py": """
        import pytest

        pytestmark = pytest.mark.livedata

        def test_live():
            assert True
    """,
    # Skipped at COLLECTION: its tests never exist as items, so only the
    # collect report can see it.
    "test_epsilon.py": """
        import pytest

        pytest.importorskip("a_module_that_does_not_exist_anywhere")

        def test_hidden():
            assert True
    """,
}


def _run_fixture_suite(
    tmp_path: Path, shard: str, count: int, tests: dict[str, str] = _FIXTURE_TESTS
) -> tuple[int, dict]:
    suite = tmp_path / "suite"
    if not suite.exists():
        suite.mkdir()
        for name, body in tests.items():
            (suite / name).write_text(textwrap.dedent(body), encoding="utf-8")
        (tmp_path / "shards.json").write_text(
            json.dumps({"shard_count": count, "min_collected": 1, "max_skipped": 99}),
            encoding="utf-8",
        )
        (suite / "conftest.py").write_text(
            textwrap.dedent(
                f"""
                from pathlib import Path
                import sys
                sys.path.insert(0, {str(REPO)!r})
                from scripts import ci_test_shards

                def pytest_configure(config):
                    config.addinivalue_line("markers", "livedata: x")
                    ci_test_shards.register_if_requested(
                        config.pluginmanager, config_path=Path({str(tmp_path / "shards.json")!r})
                    )
                """
            ),
            encoding="utf-8",
        )
    manifest = tmp_path / f"m{shard.split('/')[0]}.json"
    env = {
        **os.environ,
        shards.SHARD_ENV: shard,
        shards.MANIFEST_ENV: str(manifest),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not livedata", "."],
        cwd=suite,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert manifest.exists(), proc.stdout + proc.stderr
    return proc.returncode, json.loads(manifest.read_text(encoding="utf-8"))


def test_the_plugin_partitions_a_real_run_and_counts_one_verdict_per_test(tmp_path):
    count = 2
    results = [_run_fixture_suite(tmp_path, f"{i}/{count}", count) for i in range(1, count + 1)]
    assert all(rc == 0 for rc, _ in results), results
    manifests = [m for _, m in results]

    # Independent expectation, written out by hand from _FIXTURE_TESTS:
    # 5 + 2 + 5 = 12 hard-gate tests; the livedata module is deselected by -m
    # BEFORE the split, so it is in no shard's collected set.
    expected_ids = {
        "test_alpha.py::test_pass",
        "test_alpha.py::test_setup_skip",
        "test_alpha.py::test_call_skip",
        "test_alpha.py::test_xfail",
        "test_alpha.py::test_xfail_not_run",
        "test_beta.py::test_with_subtests",
        "test_beta.py::test_plain",
        *{f"test_gamma.py::test_param[{n}]" for n in range(5)},
    }
    for m in manifests:
        assert m["collected_total"] == 12
        assert m["collected_sha256"] == collected_digest(expected_ids)
    union = [nodeid for m in manifests for nodeid in m["selected"]]
    assert sorted(union) == sorted(expected_ids)

    totals = shards.summarize(manifests)
    assert totals["passed"] == 2 + 5 + 1  # pass, plain, 5 params, subtest parent
    assert totals["skipped"] == 2
    assert totals["xfailed"] == 2
    assert totals["failed"] == totals["error"] == 0
    # Every shard collects every module, so each records the one module-level
    # skip; the suite counts it once.
    assert totals["skipped_modules"] == 1
    assert all(m["collect_skipped"] == ["test_epsilon.py"] for m in manifests)

    # Budget = 2 test skips + 1 module skip.
    config = ShardConfig(shard_count=count, min_collected=12, max_skipped=3, durations={})
    assert verify_manifests(manifests, config) == []
    stricter = ShardConfig(shard_count=count, min_collected=12, max_skipped=2, durations={})
    assert any("skip budget" in p for p in verify_manifests(manifests, stricter))


def test_a_failing_test_fails_its_shard_and_the_proof(tmp_path):
    rc, manifest = _run_fixture_suite(
        tmp_path, "1/1", 1, tests={"test_boom.py": "def test_boom():\n    assert False\n"}
    )
    assert rc != 0
    assert manifest["exitstatus"] != 0
    config = ShardConfig(shard_count=1, min_collected=1, max_skipped=99, durations={})
    assert any("exited" in p for p in verify_manifests([manifest], config))


def test_a_child_pytest_does_not_inherit_the_shard(tmp_path):
    """A test that launches pytest in a subprocess must get an UNSHARDED run.
    Inheriting the variables would split the child's own collection (silently
    deselecting the tests it meant to run) and overwrite this shard's manifest."""
    child = """
        import os, subprocess, sys

        def test_child_env_is_clean():
            assert "RISKIT_TEST_SHARD" not in os.environ
            assert "RISKIT_TEST_SHARD_MANIFEST" not in os.environ
    """
    rc, manifest = _run_fixture_suite(tmp_path, "1/1", 1, tests={"test_child.py": child})
    assert rc == 0, manifest
    assert manifest["outcomes"]["passed"] == 1


def test_cli_verify_exit_codes(tmp_path):
    d = tmp_path / "manifests"
    d.mkdir()
    for m in _complete():
        (d / f"shard-{m['shard']}.json").write_text(json.dumps(m), encoding="utf-8")
    cfg = tmp_path / "shards.json"
    cfg.write_text(
        json.dumps({"shard_count": 3, "min_collected": 6, "max_skipped": 2}), encoding="utf-8"
    )
    ok = shards.main(["--config", str(cfg), "verify", "--manifests", str(d)])
    assert ok == 0
    (d / "shard-3.json").unlink()
    assert shards.main(["--config", str(cfg), "verify", "--manifests", str(d)]) == 1
