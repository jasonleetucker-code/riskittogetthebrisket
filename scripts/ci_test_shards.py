"""Backend hard-gate test sharding for CI — the single owner.

Why this exists
---------------
``PR Validation`` ran the whole hard-gate suite (``pytest tests/ -x -m "not
livedata"``, ~34,000 tests) serially in ONE job.  Measured over eight green
full-backend runs on 2026-11-06/07 that one step took 74-106 minutes — about
93% of the job's wall clock — while every other gate together took ~5.  The
suite is not slow because of any one test; it is slow because one machine runs
all of it.

This module splits that IDENTICAL test set across N machines and then proves
nothing was lost in the split.  It never chooses WHICH tests run: the command,
the markers and ``-x`` stay byte-identical, and every collected test runs in
exactly one shard.

Three pieces, one owner
-----------------------
* **assignment** (:func:`assign_files`) — pure and deterministic.  The unit is
  the test FILE, because the suite restores process-wide state per MODULE
  (``tests/conftest.py`` R-TEST-ISOLATION): a module is the isolation
  boundary, so a module is never split across machines.  Files are packed
  longest-first onto the least-loaded shard (LPT) using recorded per-file
  seconds where we have them and the test count times a per-test rate where we
  do not.
* **the pytest plugin** (:class:`ShardPlugin`) — registered by
  ``tests/conftest.py`` only when ``RISKIT_TEST_SHARD`` is set, so a local
  ``pytest`` run is untouched.  It deselects the other shards' files AFTER
  marker deselection and writes a manifest (what was collected, what this
  shard selected, how each selected test ended, per-file seconds).
* **verification** (:func:`verify_manifests`) — run by the ``Validate PR``
  aggregator over every shard's manifest.  It fails closed when a shard is
  missing, when the shards collected different test sets, when any test was
  selected twice or by nobody, when a shard's executed count does not match
  what it selected, when the collected total falls below the floor, or when the
  suite-wide skip count exceeds its budget.  A sharded run that cannot prove it
  ran everything is a red run.

The executed-count check, the collection floor and the skip budget are also
the gate audit finding W24-F001 asked for: before this, a skipped test was
indistinguishable from a passing one in ``pytest -q``, and nothing failed if a
whole directory silently stopped collecting.

Configuration: ``config/ci/test_shards.json`` (shard count, floor, skip
budget, recorded durations).  Refresh the durations from a green run with
``python scripts/ci_test_shards.py durations --manifests <dir> --write``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "ci" / "test_shards.json"

SHARD_ENV = "RISKIT_TEST_SHARD"
MANIFEST_ENV = "RISKIT_TEST_SHARD_MANIFEST"
MANIFEST_VERSION = 1

# Used only for a file with no recorded duration.  Measured 2026-11-07 on run
# 42371888297: 5,034 s over 34,207 hard-gate tests = 0.147 s/test.
FALLBACK_SECONDS_PER_TEST = 0.15

# pytest outcome keys that mean "this selected test ran to a verdict".  A test
# ends in exactly one of these; ``error`` (setup/teardown) is counted
# separately because a teardown error can follow a pass.
_TEST_OUTCOMES = ("passed", "failed", "skipped", "xfailed", "xpassed")


class ShardError(ValueError):
    """A shard spec, config or manifest that cannot be trusted."""


# ── configuration ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ShardConfig:
    shard_count: int
    min_collected: int
    max_skipped: int
    durations: Mapping[str, float]

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> ShardConfig:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShardError(f"cannot read shard config {path}: {exc}") from exc
        try:
            shard_count = int(raw["shard_count"])
            min_collected = int(raw["min_collected"])
            max_skipped = int(raw["max_skipped"])
            durations = {str(k): float(v) for k, v in (raw.get("durations") or {}).items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise ShardError(f"malformed shard config {path}: {exc}") from exc
        if shard_count < 1:
            raise ShardError(f"shard_count must be >= 1, got {shard_count}")
        if min_collected < 0 or max_skipped < 0:
            raise ShardError("min_collected and max_skipped must be non-negative")
        if any(v < 0 for v in durations.values()):
            raise ShardError("durations must be non-negative seconds")
        return cls(shard_count, min_collected, max_skipped, durations)


def parse_shard_spec(spec: str) -> tuple[int, int]:
    """``"3/8"`` -> ``(3, 8)``.  One-based; anything else is refused."""
    try:
        index_text, count_text = spec.strip().split("/")
        index, count = int(index_text), int(count_text)
    except ValueError as exc:
        raise ShardError(f"shard spec must look like 'i/N', got {spec!r}") from exc
    if count < 1 or not 1 <= index <= count:
        raise ShardError(f"shard index must satisfy 1 <= i <= N, got {spec!r}")
    return index, count


# ── assignment ──────────────────────────────────────────────────────────


def file_of(nodeid: str) -> str:
    """The test file a pytest node id belongs to (posix, rootdir-relative)."""
    return nodeid.split("::", 1)[0].replace("\\", "/")


def file_weights(
    file_counts: Mapping[str, int], durations: Mapping[str, float]
) -> dict[str, float]:
    """Seconds each file is expected to take.

    A file with a recorded duration uses it.  A file without one (new, or
    renamed) is estimated from its test count at the median recorded per-test
    rate, falling back to :data:`FALLBACK_SECONDS_PER_TEST` when nothing is
    recorded.  Estimates only steer balance — they can never drop a test.
    """
    rates = sorted(durations[f] / n for f, n in file_counts.items() if n > 0 and f in durations)
    rate = rates[len(rates) // 2] if rates else FALLBACK_SECONDS_PER_TEST
    rate = rate if rate > 0 else FALLBACK_SECONDS_PER_TEST
    return {f: float(durations[f]) if f in durations else n * rate for f, n in file_counts.items()}


def assign_files(
    file_counts: Mapping[str, int],
    shard_count: int,
    durations: Mapping[str, float] | None = None,
) -> dict[str, int]:
    """Map every file to exactly one shard in ``1..shard_count``.

    Deterministic: the same files, counts and durations give the same map on
    every machine, which is what lets N independent runners agree on a split
    without talking to each other.  Longest-processing-time-first onto the
    least-loaded shard; ties broken by path and then by shard index.
    """
    if shard_count < 1:
        raise ShardError(f"shard_count must be >= 1, got {shard_count}")
    weights = file_weights(file_counts, durations or {})
    loads = [0.0] * shard_count
    assignment: dict[str, int] = {}
    for path in sorted(weights, key=lambda f: (-weights[f], f)):
        target = min(range(shard_count), key=lambda i: (loads[i], i))
        assignment[path] = target + 1
        loads[target] += weights[path]
    return assignment


def _skip_reason(report) -> str:
    """The human reason a skipped report carries (``longrepr`` is ``(file, line, "Skipped: why")``)."""
    longrepr = getattr(report, "longrepr", None)
    text = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    text = str(text)
    return (text[len("Skipped: ") :] if text.startswith("Skipped: ") else text)[:300]


def collected_digest(nodeids: Iterable[str]) -> str:
    """Order-independent identity of a set of node ids."""
    h = hashlib.sha256()
    for nodeid in sorted(set(nodeids)):
        h.update(nodeid.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


# ── the pytest plugin ───────────────────────────────────────────────────


class ShardPlugin:
    """Selects one shard's files and records what happened to them.

    Registered by ``tests/conftest.py`` only when :data:`SHARD_ENV` is set.
    ``trylast`` on collection so it sees the items that survive ``-m``
    deselection — the hard-gate set — and splits exactly that.
    """

    def __init__(self, spec: str, manifest_path: str | None, config: ShardConfig) -> None:
        self.index, self.count = parse_shard_spec(spec)
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.config = config
        self.collected: list[str] = []
        self.selected: list[str] = []
        self.assignment: dict[str, int] = {}
        # One verdict per test node id.  Keyed rather than counted because
        # pytest's built-in subtests emit extra call-phase reports carrying the
        # PARENT's node id; counting reports would credit one test many times.
        self.verdicts: dict[str, str] = {}
        self.errors = 0
        self.file_seconds: dict[str, float] = {}
        # Modules skipped at COLLECTION (``pytest.importorskip``,
        # ``skip(allow_module_level=True)``): their tests are never collected,
        # so no per-test verdict can see them.  Every shard collects every
        # module, so each shard records the same list.
        self.collect_skipped: set[str] = set()
        # Why each skipped node id skipped (observability only: never hashed
        # or counted, so it cannot change a verdict).  Lets a skip audit read
        # the reasons straight from the shard artifacts instead of re-running.
        self.skip_reasons: dict[str, str] = {}

    def _deselect(self, config, items) -> None:
        self.collected = [item.nodeid for item in items]
        counts: dict[str, int] = {}
        for nodeid in self.collected:
            counts[file_of(nodeid)] = counts.get(file_of(nodeid), 0) + 1
        self.assignment = assign_files(counts, self.count, self.config.durations)
        keep, drop = [], []
        for item in items:
            (keep if self.assignment[file_of(item.nodeid)] == self.index else drop).append(item)
        if drop:
            config.hook.pytest_deselected(items=drop)
        items[:] = keep
        self.selected = [item.nodeid for item in keep]

    def _record(self, report, *, is_subtest: bool = False) -> None:
        if is_subtest:
            # Its time is already inside the parent's call duration, and its
            # outcome is not the parent's verdict.
            return
        f = file_of(report.nodeid)
        self.file_seconds[f] = self.file_seconds.get(f, 0.0) + float(report.duration or 0.0)
        if report.when == "call":
            if hasattr(report, "wasxfail"):
                self.verdicts[report.nodeid] = "xpassed" if report.passed else "xfailed"
            else:
                self.verdicts[report.nodeid] = report.outcome
                if report.skipped:
                    self.skip_reasons[report.nodeid] = _skip_reason(report)
        elif report.failed:
            self.errors += 1
        elif report.skipped and report.when == "setup":
            # A skip raised in setup (skipif, a fixture's pytest.skip,
            # xfail(run=False)) never reaches the call phase; it is still this
            # test's one verdict.
            self.verdicts[report.nodeid] = "xfailed" if hasattr(report, "wasxfail") else "skipped"
            if not hasattr(report, "wasxfail"):
                self.skip_reasons[report.nodeid] = _skip_reason(report)

    def _record_collect(self, report) -> None:
        if report.skipped:
            self.collect_skipped.add(report.nodeid.replace("\\", "/"))

    def outcomes(self) -> dict[str, int]:
        counts = {k: 0 for k in _TEST_OUTCOMES}
        for verdict in self.verdicts.values():
            counts[verdict] = counts.get(verdict, 0) + 1
        counts["error"] = self.errors
        return counts

    def manifest(self, exitstatus: int) -> dict:
        return {
            "version": MANIFEST_VERSION,
            "shard": self.index,
            "shard_count": self.count,
            "collected_total": len(self.collected),
            "collected_sha256": collected_digest(self.collected),
            "selected": sorted(self.selected),
            "verdict_sha256": collected_digest(self.verdicts),
            "outcomes": self.outcomes(),
            "collect_skipped": sorted(self.collect_skipped),
            "skip_reasons": dict(sorted(self.skip_reasons.items())),
            "exitstatus": int(exitstatus),
            "file_seconds": {k: round(v, 3) for k, v in sorted(self.file_seconds.items())},
        }

    def _write(self, exitstatus: int) -> None:
        if self.manifest_path is None:
            return
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self.manifest(exitstatus), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _make_hooks():
    """Bind the plugin's methods to pytest hook names lazily.

    Imported inside a function so this module stays importable (and its CLI
    usable) on a runner that has not installed pytest — the aggregator job
    verifies manifests with the standard library only.
    """
    import pytest
    from _pytest.reports import TestReport

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        self._deselect(config, items)

    def pytest_collectreport(self, report):
        self._record_collect(report)

    def pytest_runtest_logreport(self, report):
        # Only the test's own setup/call/teardown reports are exactly
        # TestReport; pytest's SubtestReport (and any plugin's report type)
        # subclasses it.
        self._record(report, is_subtest=type(report) is not TestReport)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        self._write(exitstatus)

    def pytest_report_header(self, config):
        return f"ci shard {self.index}/{self.count} ({SHARD_ENV})"

    return {
        "pytest_collection_modifyitems": pytest_collection_modifyitems,
        "pytest_collectreport": pytest_collectreport,
        "pytest_runtest_logreport": pytest_runtest_logreport,
        "pytest_sessionfinish": pytest_sessionfinish,
        "pytest_report_header": pytest_report_header,
    }


def register_if_requested(
    pluginmanager,
    environ: Mapping[str, str] = os.environ,
    config_path: Path = CONFIG_PATH,
) -> object | None:
    """Called from ``tests/conftest.py::pytest_configure``.

    No-op unless :data:`SHARD_ENV` is set, so ordinary local and L1 runs are
    byte-identical to before.  A malformed spec or config raises rather than
    silently running everything (or nothing) on one machine.
    """
    spec = environ.get(SHARD_ENV, "").strip()
    if not spec:
        return None
    config = ShardConfig.load(config_path)
    plugin_type = type("CiShardPlugin", (ShardPlugin,), _make_hooks())
    plugin = plugin_type(spec, environ.get(MANIFEST_ENV) or None, config)
    if plugin.count != config.shard_count:
        raise ShardError(
            f"{SHARD_ENV}={spec} disagrees with shard_count={config.shard_count} in "
            f"{config_path.name}; the matrix and the config must name one N"
        )
    if environ is os.environ:
        # Children must not inherit the shard.  A test that launches pytest in
        # a subprocess (several do) would otherwise split ITS collection —
        # silently deselecting the tests it meant to run — and overwrite this
        # shard's manifest when it finished.
        os.environ.pop(SHARD_ENV, None)
        os.environ.pop(MANIFEST_ENV, None)
    pluginmanager.register(plugin, "riskit-ci-shard")
    return plugin


# ── verification ────────────────────────────────────────────────────────


def verify_manifests(manifests: list[dict], config: ShardConfig) -> list[str]:
    """Every reason this set of shard manifests does not prove a complete run.

    Empty list = complete: every shard reported, all collected the same set,
    the shards partition that set exactly, every shard executed what it
    selected and exited 0, the collection floor holds and the skip budget is
    not exceeded.
    """
    problems: list[str] = []
    n = config.shard_count
    by_index: dict[int, dict] = {}
    for m in manifests:
        if m.get("version") != MANIFEST_VERSION:
            problems.append(f"manifest version {m.get('version')!r} != {MANIFEST_VERSION}")
            continue
        if m.get("shard_count") != n:
            problems.append(
                f"shard {m.get('shard')} ran with shard_count {m.get('shard_count')}, config says {n}"
            )
        idx = m.get("shard")
        if idx in by_index:
            problems.append(f"shard {idx} reported twice")
        by_index[idx] = m
    missing = sorted(set(range(1, n + 1)) - set(by_index))
    if missing:
        problems.append(f"no manifest from shard(s) {missing}: their tests are unaccounted for")
    if problems:
        return problems

    digests = {m["collected_sha256"] for m in by_index.values()}
    totals = {m["collected_total"] for m in by_index.values()}
    if len(digests) != 1 or len(totals) != 1:
        problems.append(
            "shards collected different test sets (collection is not deterministic "
            f"across machines): totals {sorted(totals)}"
        )
        return problems
    (digest,) = digests
    (total,) = totals
    module_skips = {tuple(m.get("collect_skipped") or ()) for m in by_index.values()}
    if len(module_skips) != 1:
        problems.append(
            "shards skipped different modules at collection (collection is not deterministic)"
        )
        return problems
    (skipped_modules,) = module_skips

    seen: dict[str, int] = {}
    for idx in sorted(by_index):
        for nodeid in by_index[idx]["selected"]:
            if nodeid in seen:
                problems.append(f"{nodeid} selected by shards {seen[nodeid]} and {idx}")
            seen[nodeid] = idx
    if collected_digest(seen) != digest or len(seen) != total:
        problems.append(
            f"the shards selected {len(seen)} tests between them but {total} were collected: "
            "some test ran nowhere"
        )

    # A module skipped at collection counts once, as pytest's own summary
    # counts it: it hides tests the per-test verdicts can never see.
    skipped = len(skipped_modules)
    for idx in sorted(by_index):
        m = by_index[idx]
        if m["exitstatus"] != 0:
            problems.append(f"shard {idx} exited {m['exitstatus']}")
        o = m.get("outcomes") or {}
        executed = sum(int(o.get(k, 0)) for k in _TEST_OUTCOMES)
        if m["exitstatus"] == 0 and (
            executed != len(m["selected"])
            or m.get("verdict_sha256") != collected_digest(m["selected"])
        ):
            problems.append(
                f"shard {idx} selected {len(m['selected'])} tests but {executed} reached a "
                "verdict (or a different set did): a selected test never ran"
            )
        skipped += int(o.get("skipped", 0))

    if total < config.min_collected:
        problems.append(
            f"only {total} hard-gate tests collected, below the floor of {config.min_collected} "
            "(config/ci/test_shards.json): a module or directory stopped collecting"
        )
    if skipped > config.max_skipped:
        problems.append(
            f"{skipped} tests skipped across the suite, above the skip budget of "
            f"{config.max_skipped} (config/ci/test_shards.json): a skipped test is not a "
            "passing one — fix the skip or raise the budget in a reviewed change"
        )
    return problems


def summarize(manifests: list[dict]) -> dict:
    out = {k: 0 for k in (*_TEST_OUTCOMES, "error")}
    for m in manifests:
        for k, v in (m.get("outcomes") or {}).items():
            out[k] = out.get(k, 0) + int(v)
    out["collected"] = max((m.get("collected_total", 0) for m in manifests), default=0)
    out["skipped_modules"] = max(
        (len(m.get("collect_skipped") or ()) for m in manifests), default=0
    )
    out["shards"] = len(manifests)
    return out


def read_manifests(directory: Path) -> list[dict]:
    paths = sorted(directory.rglob("*.json"))
    manifests = []
    for p in paths:
        try:
            manifests.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShardError(f"unreadable manifest {p}: {exc}") from exc
    return manifests


def merge_durations(manifests: list[dict]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for m in manifests:
        for f, s in (m.get("file_seconds") or {}).items():
            merged[f] = round(merged.get(f, 0.0) + float(s), 2)
    return dict(sorted(merged.items()))


# ── CLI ─────────────────────────────────────────────────────────────────


def _cmd_matrix(args) -> int:
    config = ShardConfig.load(Path(args.config))
    shards = list(range(1, config.shard_count + 1))
    lines = [f"shards={json.dumps(shards)}", f"shard_count={config.shard_count}"]
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def _cmd_verify(args) -> int:
    config = ShardConfig.load(Path(args.config))
    manifests = read_manifests(Path(args.manifests))
    problems = verify_manifests(manifests, config)
    summary = summarize(manifests)
    print(json.dumps(summary, sort_keys=True))
    if problems:
        print("SHARDED HARD GATE NOT PROVEN COMPLETE:", file=sys.stderr)
        for p in problems[:50]:
            print(f"  - {p}", file=sys.stderr)
        if len(problems) > 50:
            print(f"  ... and {len(problems) - 50} more", file=sys.stderr)
        return 1
    print(
        f"sharded hard gate complete: {summary['collected']} tests across "
        f"{summary['shards']} shards, {summary['skipped']} tests + "
        f"{summary['skipped_modules']} modules skipped "
        f"(budget {config.max_skipped}), floor {config.min_collected}"
    )
    return 0


def _cmd_durations(args) -> int:
    manifests = read_manifests(Path(args.manifests))
    merged = merge_durations(manifests)
    if not merged:
        print("no file_seconds in the manifests", file=sys.stderr)
        return 1
    if args.write:
        path = Path(args.config)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["durations"] = merged
        if args.source:
            raw["durations_source"] = args.source
        path.write_text(json.dumps(raw, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        print(f"wrote {len(merged)} file durations ({sum(merged.values()):.0f} s) to {path}")
    else:
        print(json.dumps(merged, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", default=str(CONFIG_PATH))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("matrix", help="print the shard list for a workflow matrix")
    p.add_argument("--github-output", action="store_true")
    p.set_defaults(func=_cmd_matrix)
    p = sub.add_parser("verify", help="prove a sharded run executed every collected test")
    p.add_argument("--manifests", required=True, help="directory holding every shard manifest")
    p.set_defaults(func=_cmd_verify)
    p = sub.add_parser("durations", help="merge per-file seconds from a green run's manifests")
    p.add_argument("--manifests", required=True)
    p.add_argument("--write", action="store_true", help="store them in the config")
    p.add_argument("--source", help="where the numbers came from (e.g. a run id)")
    p.set_defaults(func=_cmd_durations)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ShardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
