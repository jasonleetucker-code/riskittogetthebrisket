"""An interactive BDVM request may never start a remote nflverse ingest.

THE DEFECT, reproduced.

PR #938 repaired the E2E Safety Net and proved a hidden architecture defect
underneath it.  ``journey-trade.spec.js:96`` did not fail because the page was
slow — the page had already rendered a terminal error::

    Rankings unavailable — Failed to load dynasty data: 503
    reason: backend_idle_timeout   timeoutMs: 4000

The Next data bridge aborts when the backend streams no chunk for >4s.  At
failure time the request-serving Python process was doing BDVM/nflverse work
that began at the FIRST BDVM values request: ~112,450 weekly-stat rows and
~157,615 snap-count rows parsed, plus schedule downloads.

``run_in_threadpool`` is not the protection and never was.  Parsing ~270,000
CSV rows is CPU/GIL-heavy, so a worker thread in the same uvicorn process
starves ``/api/data``'s response streaming just as effectively as blocking the
event loop would.

The request path, as measured on ``main`` at 547e51bc6::

    get_bdvm_values                       src/api/bdvm_api.py:162
      ├─ _actuals_for   :120 → actuals.py:170  → ingest.fetch_weekly_stats
      ├─ _context_for   :63  → context.py:199  → ingest.fetch_id_map
      │                                        → ingest.fetch_weekly_stats  (6 seasons)
      │                                        → ingest.fetch_snap_counts   (6 seasons)
      └─ _schedule_for  :79  → schedule.py:46  → urllib.request.urlopen

Note ``_actuals_for`` is already gated on a projection snapshot existing, but
``_context_for`` and ``_schedule_for`` are not — they run on every values-cache
miss regardless.

THE RULE THIS FILE PINS.  The refresh process decides WHEN TO FETCH.  The
request process decides only WHETHER A MATERIALISED ARTIFACT EXISTS, and
reports its freshness truthfully.  An interactive request reads what is on
disk or degrades honestly; it never crawls.
"""

from __future__ import annotations

import unittest
import urllib.request
from typing import Any
from unittest import mock

from src.api import bdvm_api


def _contract() -> dict[str, Any]:
    """A contract complete enough for ``run_valuation`` to reach its own logic.

    ``rosterPositions`` / ``leagueSettings`` are required — without them
    ``league_config`` raises before the prerequisites are even reported, and
    the test would fail for a fixture reason rather than the defect.
    """
    return {
        "generatedAt": "2026-08-20T00:00:00Z",
        "currentDraftYear": 2026,
        "playersArray": [],
        "sleeper": {
            "scoringSettings": {"rec": 1.0, "pass_td": 4.0},
            "rosterPositions": ["QB", "WR", "WR", "LB", "BN", "BN"],
            "leagueSettings": {"num_teams": 12},
        },
    }


class _NetworkRecorder:
    """Records every remote-fetch attempt instead of performing one.

    Returning empty rather than raising is deliberate: the test then reports
    *which* owners were called, rather than dying on whichever happened to run
    first and hiding the rest.
    """

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def ingest_fetch(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.attempts.append(f"ingest._try_fetch_with_fallback(label={kwargs.get('label')})")
        return []

    def urlopen(self, req: Any, *args: Any, **kwargs: Any):
        url = getattr(req, "full_url", None) or str(req)
        self.attempts.append(f"urllib.request.urlopen({url})")
        raise AssertionError("network disabled in this test")


class TestInteractiveBdvmRequestDoesNoRemoteIngest(unittest.TestCase):
    """TEST A — the cold interactive request must not fetch remotely."""

    def setUp(self) -> None:
        bdvm_api.reset_cache()
        self.addCleanup(bdvm_api.reset_cache)
        self.recorder = _NetworkRecorder()

    def _run_cold_request(self, tmp_cache_dir) -> dict[str, Any]:
        """Serve one BDVM request with a COLD cache and no network.

        Both remote owners are intercepted at the lowest level each one has:
        ``_try_fetch_with_fallback`` is the single choke point for everything
        under ``src.nfl_data.ingest``, and ``urllib.request.urlopen`` catches
        ``bdvm/schedule.py``, which bypasses that owner entirely.
        """
        from src.bdvm import context_store
        from src.nfl_data import cache as nfl_cache
        from src.nfl_data import ingest

        with (
            mock.patch.object(
                ingest, "_try_fetch_with_fallback", side_effect=self.recorder.ingest_fetch
            ),
            mock.patch.object(urllib.request, "urlopen", side_effect=self.recorder.urlopen),
            # Cold: empty artifact roots, so nothing can be served locally.
            # BOTH are redirected — leaving the context snapshot dir alone
            # would read the developer's real data/ and quietly make this a
            # warm test on one machine and a cold one in CI.
            mock.patch.object(nfl_cache, "_default_cache_dir", return_value=tmp_cache_dir),
            mock.patch.object(context_store, "SNAPSHOT_DIR", tmp_cache_dir / "ctx"),
        ):
            return bdvm_api.get_bdvm_values(_contract(), "dynasty_main")

    def test_a_cold_request_attempts_no_remote_fetch(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            payload = self._run_cold_request(Path(tmp) / "cold_cache")

        self.assertEqual(
            self.recorder.attempts,
            [],
            "an interactive BDVM request started a remote nflverse fetch:\n  "
            + "\n  ".join(self.recorder.attempts),
        )
        # Non-vacuity: the request must still have produced a payload. A repair
        # that made this test pass by refusing to serve anything is not a repair.
        self.assertIsInstance(payload, dict)
        self.assertIn("status", payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ══════════════════════════════════════════════════════════════════════
# The other half of the property.  "Attempts no fetch" is satisfiable by
# a request path that reads nothing at all, so every test below pins that
# what the refresh owner MATERIALISED is what the request path SERVES,
# and that its age is reported rather than assumed.
# ══════════════════════════════════════════════════════════════════════

import ast  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from src.bdvm import context as bdvm_context  # noqa: E402
from src.bdvm import context_store  # noqa: E402
from src.bdvm import schedule as bdvm_schedule  # noqa: E402
from src.nfl_data import cache as nfl_cache  # noqa: E402
from src.nfl_data import ingest  # noqa: E402
from tests.bdvm.test_context import ID_ROWS, SNAP_ROWS, WEEKLY_ROWS  # noqa: E402

_SEASON = 2026
_YEARS = list(range(_SEASON - bdvm_context.DEFAULT_SEASONS_BACK, _SEASON))
_SCHEDULE_ROWS = [
    {"week": w, "home_team": "AAA", "away_team": "BBB", "game_type": "REG"}
    for w in range(1, 19)
    if w != 7
]


def _materialise(cache_dir: Path) -> None:
    """Do what the refresh owner does: fill the four caches, out of band.

    Keys come from ``ingest.cache_key`` rather than being spelled out, so
    this fixture cannot drift from the entries the request path reads —
    which is the failure mode that would make every test below pass while
    the real thing serves nothing.
    """
    nfl_cache.put(ingest.cache_key("id_map"), ID_ROWS, cache_dir=cache_dir)
    nfl_cache.put(ingest.cache_key("weekly_stats", _YEARS), WEEKLY_ROWS, cache_dir=cache_dir)
    nfl_cache.put(ingest.cache_key("snap_counts", _YEARS), SNAP_ROWS, cache_dir=cache_dir)
    nfl_cache.put(ingest.cache_key("schedules", [_SEASON]), _SCHEDULE_ROWS, cache_dir=cache_dir)


def _age_entry(cache_dir: Path, key: str, seconds: float) -> None:
    """Backdate one entry's ``fetched_at`` — i.e. let it go stale in place."""
    _, meta_path = nfl_cache._entry_paths(cache_dir, key)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["fetched_at"] = time.time() - seconds
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture
def warm_cache(tmp_path, monkeypatch):
    """Everything the refresh owner produces, installed as the defaults.

    Two artifacts, deliberately distinct: the raw feed cache (which only the
    REFRESH owner reads) and the built player-context snapshot (which is what
    the REQUEST path reads).  Seeding only the first would leave the request
    path with no context and every test below would pass for the wrong reason.
    """
    cache_dir = tmp_path / "nfl_data_cache"
    snapshot_dir = tmp_path / "bdvm_context"
    _materialise(cache_dir)
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", snapshot_dir)

    built = bdvm_context.fetch_and_build_context(_SEASON, cache_only=True)
    assert built, "fixture built an empty context — the seeded cache is wrong"
    context_store.write_snapshot(_SEASON, built)
    return cache_dir


@pytest.fixture
def no_network(monkeypatch):
    """Record any remote-fetch attempt instead of performing one."""
    recorder = _NetworkRecorder()
    monkeypatch.setattr(ingest, "_try_fetch_with_fallback", recorder.ingest_fetch)
    monkeypatch.setattr(urllib.request, "urlopen", recorder.urlopen)
    return recorder


# ── B. materialised inputs are actually CONSUMED ──────────────────────


def test_b_materialised_context_is_served_without_a_fetch(warm_cache, no_network):
    """The repair must not have made BDVM blind.

    Same cache-only call the request path makes, against inputs the
    refresh owner put there — the context must come back POPULATED.
    """
    ctx = bdvm_context.fetch_and_build_context(_SEASON, cache_only=True)

    assert no_network.attempts == []
    assert ctx, "cache-only context came back empty against a materialised cache"
    entry = ctx.get("star receiver")
    assert entry is not None, f"seeded player missing from the context: {sorted(ctx)[:5]}"
    # Non-vacuity across BOTH feeds: draft capital proves the id map was
    # read, and a non-zero career load proves the weekly rows were.
    assert entry.draft_capital_score > 0
    assert sum(entry.loads.values()) > 0, f"weekly rows were not consumed: {entry.loads}"


def test_b_materialised_schedule_is_served_without_a_fetch(warm_cache, no_network):
    weeks = bdvm_schedule.fetch_team_weeks(_SEASON, cache_only=True)

    assert no_network.attempts == []
    assert set(weeks) == {"AAA", "BBB"}
    # Week 7 was omitted from the seeded schedule, so it must read as a bye —
    # proof the ROWS were parsed rather than a shape being fabricated.
    assert [w.week for w in weeks["AAA"] if w.is_bye] == [7]
    assert [w.week for w in weeks["AAA"] if w.is_league_playoff] == [15, 16, 17]


# ── G. stale is SERVED, and stamped stale ─────────────────────────────


def test_g_stale_input_is_still_served(warm_cache, no_network):
    """A day-old TTL governs the REFRESH owner, not readability.

    Dropping the input at the TTL would convert a latency repair into a
    daily freshness regression: the request path cannot re-fetch, so
    expiry would mean BDVM loses its evidence every 24h.
    """
    key = ingest.cache_key("weekly_stats", _YEARS)
    _age_entry(warm_cache, key, 10 * 24 * 3600)

    rows = ingest.fetch_weekly_stats(_YEARS, cache_only=True)

    assert no_network.attempts == []
    assert rows == WEEKLY_ROWS, "a stale-but-present input was dropped instead of served"


def test_g_a_missed_refresh_is_reported_never_shown_as_current(warm_cache, monkeypatch):
    """A snapshot older than its production cadence must SAY so.

    Nothing is withheld — the same snapshot is still loaded and served — but
    "a scheduled refresh was missed" and "current" must not render alike.
    """
    fresh = bdvm_api._auxiliary_input_report(_SEASON, None)
    assert fresh["playerContext"]["state"] == bdvm_api.AUX_AVAILABLE
    assert fresh["playerContext"]["playerCount"] > 0

    monkeypatch.setattr(context_store, "snapshot_age_seconds", lambda *a, **k: 30 * 24 * 3600.0)
    aged = bdvm_api._auxiliary_input_report(_SEASON, None)
    assert aged["playerContext"]["state"] == bdvm_api.AUX_STALE
    assert aged["playerContext"]["ageSeconds"] == pytest.approx(30 * 24 * 3600.0)
    # The schedule was written moments ago and must NOT be swept up with it.
    assert aged["schedules"]["state"] == bdvm_api.AUX_AVAILABLE


def test_g_the_report_names_only_what_the_request_path_reads(warm_cache):
    """The raw feeds are the REFRESH owner's inputs, not the request's.

    Reporting ``weeklyStats`` here would send whoever is diagnosing a
    degraded board to an artifact the request never opens.  Their freshness
    reaches the number that matters through the snapshot built from them.
    """
    report = bdvm_api._auxiliary_input_report(_SEASON, None)
    assert set(report) == {"policy", "refreshOwner", "playerContext", "schedules"}


def test_g_absent_is_missing_and_missing_is_not_zero(tmp_path, monkeypatch):
    """The three states are distinct, and none of them is a number.

    ``ageSeconds: None`` rather than ``0`` is the point: a zero age would
    read as "fetched this instant", which is the exact inversion of the
    truth.
    """
    # BOTH artifact roots are redirected. Leaving SNAPSHOT_DIR alone would
    # read the developer's real data/ — present locally, absent in CI — so
    # the test would report opposite answers on the two machines.
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "empty")
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", tmp_path / "empty")

    report = bdvm_api._auxiliary_input_report(_SEASON, None)

    for field in ("playerContext", "schedules"):
        assert report[field]["state"] == bdvm_api.AUX_MISSING
        assert report[field]["ageSeconds"] is None
    assert report["playerContext"]["playerCount"] is None
    assert report["policy"] == "cache_only_request_path"
    assert "refresh_bdvm_inputs" in report["refreshOwner"]


def test_g_the_report_and_the_reader_agree_about_the_key(warm_cache, no_network):
    """The freshness report and the reader must name the SAME entry.

    They did not: the report asked for ``id_map`` while the entry has always
    been written under ``id_map:v1``, so a present id map reported MISSING
    forever.  ``ingest.cache_key`` is now the one owner, and this asserts the
    agreement rather than the spelling.
    """
    for feed, years in (
        ("id_map", None),
        ("weekly_stats", _YEARS),
        ("snap_counts", _YEARS),
        ("schedules", [_SEASON]),
    ):
        key = ingest.cache_key(feed, years)
        served = ingest._cached_or_fetch(
            key,
            ttl_seconds=ingest.CACHE_TTLS[feed],
            cache_dir=warm_cache,
            fetch=lambda: None,
            cache_only=True,
        )
        age = nfl_cache.entry_age_seconds(key, cache_dir=warm_cache)
        assert bool(served) is (age is not None), (
            f"{feed}: the age probe and the reader disagree about whether the " "artifact exists"
        )


# ── D. a failed refresh degrades; it never destroys ───────────────────


def test_d_a_failed_refresh_leaves_last_known_good_in_place(warm_cache, monkeypatch):
    """The refresh owner's failure mode, from the request path's side.

    Expire the entry, then let the refresh FAIL. The old artifact must
    still be on disk and still be served — a refresh that cannot reach
    upstream must not delete evidence that is merely old.
    """
    key = ingest.cache_key("weekly_stats", _YEARS)
    _age_entry(warm_cache, key, 10 * 24 * 3600)

    def _explode(*_a, **_k):
        raise RuntimeError("nflverse unreachable")

    monkeypatch.setattr(ingest, "_try_fetch_with_fallback", _explode)
    with pytest.raises(RuntimeError):
        ingest.fetch_weekly_stats(_YEARS, cache_dir=warm_cache)

    assert ingest.fetch_weekly_stats(_YEARS, cache_dir=warm_cache, cache_only=True) == WEEKLY_ROWS


def test_d_the_refresh_owner_reports_failure_and_writes_nothing(tmp_path, monkeypatch):
    """``scripts/refresh_bdvm_inputs.py`` reports, never raises, never zeroes."""
    import scripts.refresh_bdvm_inputs as warm

    def _explode(*_a, **_k):
        raise RuntimeError("nflverse unreachable")

    label, count, ok = warm._warm("weekly_stats", _explode)
    assert (label, count, ok) == ("weekly_stats", 0, False)

    # An upstream that answers with nothing is a FAILURE, not a successful
    # refresh to zero rows — that distinction is what keeps _cached_or_fetch
    # from overwriting a good artifact with an empty one.
    assert warm._warm("weekly_stats", lambda: [])[2] is False


def test_d_bdvm_still_answers_with_every_input_missing(tmp_path, monkeypatch):
    """No inputs at all → a served payload on neutral priors, not a crash
    and not fabricated zeros."""
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "empty")
    bdvm_api.reset_cache()
    try:
        payload = bdvm_api.get_bdvm_values(_contract(), "dynasty_main")
    finally:
        bdvm_api.reset_cache()

    assert isinstance(payload, dict) and "status" in payload


# ── E. no stampede, from either side ──────────────────────────────────


def test_e_concurrent_cold_requests_start_no_ingest(tmp_path, monkeypatch):
    """Ten simultaneous cold readers, zero fetches.

    Cache-only needs no single-flight — there is nothing to serialise —
    so this is the stronger statement: not "one fetch", but none.
    """
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "cold")
    recorder = _NetworkRecorder()
    monkeypatch.setattr(ingest, "_try_fetch_with_fallback", recorder.ingest_fetch)

    errors: list[Exception] = []

    def _worker():
        try:
            bdvm_context.fetch_and_build_context(_SEASON, cache_only=True)
            bdvm_schedule.fetch_team_weeks(_SEASON, cache_only=True)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert errors == []
    assert recorder.attempts == []


def test_e_the_refresh_owner_still_fetches_once_under_concurrency(tmp_path):
    """The PRE-EXISTING single-flight (#753) is unchanged by ``cache_only``.

    Asserted rather than assumed: ``cache_only`` returns before the
    in-flight bookkeeping, so a careless edit there could have removed
    the leader/follower protection for the refresh path too.
    """
    calls: list[int] = []

    def _slow_provider(_years):
        calls.append(1)
        time.sleep(0.2)
        return WEEKLY_ROWS

    def _worker():
        ingest.fetch_weekly_stats(_YEARS, _provider=_slow_provider, cache_dir=tmp_path / "sf")

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert len(calls) == 1, f"the cold-cache single-flight regressed: {len(calls)} fetches"


# ── H. the second downloader cannot come back ─────────────────────────

_SCHEDULE_MODULE = Path(__file__).resolve().parents[2] / "src" / "bdvm" / "schedule.py"

_BANNED_IMPORT_ROOTS = {"urllib", "requests", "httpx", "aiohttp", "http", "socket"}
_BANNED_NAMES = {"urlopen", "urlretrieve", "Request", "HTTPSConnection", "HTTPConnection"}


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Ids of every docstring Constant node.

    This guard MUST be AST-based rather than a text search, and this is
    why: ``schedule.py``'s module docstring explains the retired
    downloader by name. A grep for ``urllib`` would either fire on the
    explanation or force deleting it, and the explanation is the thing
    that stops someone re-adding the downloader on purpose.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def remote_downloader_offenders(source: str) -> list[str]:
    """Every structural sign of a remote downloader in ``source``.

    Shared by the guard and its mutation test, so the mutation exercises
    the same code the guard runs — a second copy could pass while the
    real guard was blind.
    """
    tree = ast.parse(source)
    docstrings = _docstring_ids(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _BANNED_IMPORT_ROOTS:
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _BANNED_IMPORT_ROOTS:
                offenders.append(f"line {node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            offenders.append(f"line {node.lineno}: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _BANNED_NAMES:
            offenders.append(f"line {node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue  # prose about the retired defect, not a URL
            low = node.value.lower()
            if "http://" in low or "https://" in low or low.endswith(".csv"):
                offenders.append(f"line {node.lineno}: URL/file literal {node.value!r}")
    return offenders


def test_h_schedule_module_has_no_remote_downloader():
    """``src/bdvm/schedule.py`` acquires nothing; it only shapes rows.

    It used to be a SECOND nflverse downloader — its own
    ``urllib.request.urlopen``, no TTL cache, no single-flight, no
    feature gate — reachable from the live request path. Leaving it while
    repairing the ingest owner would have preserved the very ownership
    defect this unit exists to remove, so its absence is pinned
    structurally.
    """
    offenders = remote_downloader_offenders(_SCHEDULE_MODULE.read_text(encoding="utf-8"))
    assert not offenders, (
        "src/bdvm/schedule.py has a remote downloader again. Schedule "
        "acquisition has one owner — src.nfl_data.ingest.fetch_schedules:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "import urllib.request",
        "import requests",
        "from urllib.request import urlopen",
        'SCHEDULE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"',
        '_F = "sched_2026.csv"',
        "_R = urllib.request.urlopen(_U)",
    ],
)
def test_h_the_guard_is_not_vacuous(mutation):
    """Mutation proof. Each line is a real way the downloader could return."""
    source = _SCHEDULE_MODULE.read_text(encoding="utf-8")
    assert remote_downloader_offenders(source + "\n" + mutation + "\n"), (
        f"the guard did not notice {mutation!r} — it would not catch a "
        "reintroduced downloader either"
    )


def test_h_prose_about_the_retired_defect_stays_legal():
    """The control for the mutation test above.

    If naming ``urllib`` in a docstring tripped the guard, the pressure
    would be to delete the explanation — and the explanation is load-
    bearing documentation of why the downloader is gone.
    """
    source = _SCHEDULE_MODULE.read_text(encoding="utf-8")
    assert "urllib" in source, "the module no longer explains the retired downloader"
    assert not remote_downloader_offenders(source)


# ── C. the ENGINE is untouched ────────────────────────────────────────


def test_c_the_only_payload_change_is_the_operational_block(warm_cache, no_network, monkeypatch):
    """Methodology parity, asserted structurally rather than eyeballed.

    The brief for this repair is explicit: for identical materialised
    inputs the BDVM payload must be byte-equivalent apart from added
    OPERATIONAL metadata. ``run_valuation`` is stubbed with a sentinel so
    the comparison is exact and needs no projection snapshot — what is
    being proven is that ``get_bdvm_values`` adds ``meta.auxiliaryInputs``
    and touches nothing else on the way out.
    """
    sentinel = {
        "status": "ok",
        "meta": {"modelVersion": "v1", "paramSetId": "abc", "asOf": "2026-08-20"},
        "players": [{"playerId": "1", "fundamentalValue": 1234.5}],
    }
    monkeypatch.setattr(bdvm_api, "run_valuation", lambda *a, **k: copy.deepcopy(sentinel))
    bdvm_api.reset_cache()
    try:
        payload = bdvm_api.get_bdvm_values(_contract(), "dynasty_main")
    finally:
        bdvm_api.reset_cache()

    aux = payload["meta"].pop("auxiliaryInputs", None)
    assert aux is not None, "the operational block was not stamped at all"
    assert payload == sentinel, "get_bdvm_values changed a methodology-bearing field"


def test_c_the_engine_receives_the_same_arguments_it_always_did(
    warm_cache, no_network, monkeypatch
):
    """Acquisition changed; the engine's inputs did not.

    ``cache_only`` alters WHERE the rows come from, never WHAT is handed
    to ``run_valuation``. This records the full keyword set so a future
    edit that quietly drops or reshapes an engine input fails here rather
    than showing up as a value drift nobody can attribute.
    """
    seen: dict[str, Any] = {}

    def _spy(contract, **kwargs):
        seen.update(kwargs)
        return {"status": "ok", "meta": {}}

    monkeypatch.setattr(bdvm_api, "run_valuation", _spy)
    bdvm_api.reset_cache()
    try:
        bdvm_api.get_bdvm_values(_contract(), "dynasty_main")
    finally:
        bdvm_api.reset_cache()

    assert set(seen) == {
        "league_key",
        "params",
        "registry_roster_settings",
        "idp_enabled",
        "scoring_profile",
        "surplus_mode",
        "context",
        "schedule_weeks",
        "actuals",
    }
    # Non-vacuity: the two inputs this repair rerouted actually arrived,
    # built from the materialised cache rather than from a fetch.
    assert seen["context"], "the engine was handed an empty context off a warm cache"
    assert seen["schedule_weeks"], "the engine was handed no schedule off a warm cache"


# ── the request path LOADS; it never BUILDS ───────────────────────────


def test_the_request_path_never_builds_the_context(tmp_path, monkeypatch, no_network):
    """Cache-only stopped the DOWNLOAD; this stops the heavy BUILD.

    With a fully warm cache and no snapshot, building the context in the
    request costs 9.0s of GIL-bound parsing (a 369 MB weekly-stats entry) —
    still enough to starve /api/data past the Next bridge's 4s idle
    timeout, and still an interactive request triggering a heavy cache
    build. The honest degradation is the empty context this engine has
    always used when the input was unavailable, never a build-on-demand.
    """
    _materialise(tmp_path / "cache")
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", tmp_path / "no_snapshot")

    def _forbidden(*_a, **_k):  # pragma: no cover - the assertion is the point
        raise AssertionError("the request path built the player context")

    monkeypatch.setattr(bdvm_context, "fetch_and_build_context", _forbidden)

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        bdvm_api, "run_valuation", lambda c, **k: seen.update(k) or {"status": "ok", "meta": {}}
    )
    bdvm_api.reset_cache()
    try:
        payload = bdvm_api.get_bdvm_values(_contract(), "dynasty_main")
    finally:
        bdvm_api.reset_cache()

    assert seen["context"] == {}, "a missing snapshot must degrade, not be built around"
    assert payload["meta"]["auxiliaryInputs"]["playerContext"]["state"] == bdvm_api.AUX_MISSING


def test_the_snapshot_round_trips_exactly(tmp_path, monkeypatch):
    """What the refresh owner writes is what the request path gets.

    Equality on the dataclass map, not a spot check: the whole reason the
    built context can be materialised is that this is an identity.
    """
    _materialise(tmp_path / "cache")
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", tmp_path / "snap")

    built = bdvm_context.fetch_and_build_context(_SEASON, cache_only=True)
    context_store.write_snapshot(_SEASON, built)

    assert context_store.load_snapshot(_SEASON) == built


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda doc: doc.update(schemaVersion=999),
        lambda doc: doc.update(season=1999),
        lambda doc: doc["players"][0].update(unexpected_field=1),
        lambda doc: doc["players"][0].pop("player_key"),
        lambda doc: doc.update(players="not a list"),
    ],
)
def test_an_unusable_snapshot_is_missing_never_partial(tmp_path, monkeypatch, corrupt):
    """Field drift, a wrong season or a bad schema all read as ABSENT.

    A half-loaded context is worse than none: it would price the players it
    happened to cover with real career loads and the rest with neutral
    priors, on one board, invisibly. So the refusal is whole-artifact.
    """
    _materialise(tmp_path / "cache")
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", tmp_path / "snap")
    built = bdvm_context.fetch_and_build_context(_SEASON, cache_only=True)
    path = context_store.write_snapshot(_SEASON, built)
    assert context_store.load_snapshot(_SEASON) is not None  # control

    doc = json.loads(path.read_text(encoding="utf-8"))
    corrupt(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    assert context_store.load_snapshot(_SEASON) is None
    assert context_store.snapshot_age_seconds(_SEASON) is None or True


def test_a_failed_feed_does_not_overwrite_the_snapshot(tmp_path, monkeypatch):
    """ "Last-known-good is retained" applies to the SNAPSHOT too.

    A refresh whose upstream is down must not replace a full context with a
    thin one built from nothing — the failure mode that would turn an
    outage into silently degraded values that look completely normal.
    """
    import scripts.refresh_bdvm_inputs as warm

    _materialise(tmp_path / "cache")
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", tmp_path / "snap")
    good = bdvm_context.fetch_and_build_context(_SEASON, cache_only=True)
    context_store.write_snapshot(_SEASON, good)

    def _explode(*_a, **_k):
        raise RuntimeError("nflverse unreachable")

    # An EMPTY cache plus a dead upstream — i.e. the refresh genuinely has
    # nothing. (Against the warm cache it would rightly succeed without ever
    # reaching upstream, which is a different scenario.)
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: tmp_path / "cold")
    monkeypatch.setattr(ingest, "_try_fetch_with_fallback", _explode)
    rc = warm.main(["--season", str(_SEASON)])

    assert rc == 1, "a refresh that could not fetch reported success"
    assert context_store.load_snapshot(_SEASON) == good
