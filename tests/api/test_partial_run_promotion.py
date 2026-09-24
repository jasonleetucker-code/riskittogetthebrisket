"""A critical-source partial run must not replace a healthy served board.

THE INCIDENT (production, 2026-09-23)
-------------------------------------
The 22:38Z startup scrape logged ``source_failed - IDPTradeCalc timed out
after 480s``. The scraper recovered IDPTradeCalc's PARTIAL values, so:

* the anchor was non-empty, and ``_missing_expected_sites`` passed;
* both legacy sites carried rows, so the ratio test passed ("2/2 sites");
* 979 of 1111 players (88%) cleared the 75% retention floor.

The run was promoted. The contract then failed
``partial_run_critical:IDPTradeCalc``, and ``/api/health`` returned 503 with
``contract_ok=false``. The partial export had been mirrored over
``exports/latest``, so the 23:19Z restart's startup recovery found no healthy
generation ("Checked-out startup recovery payload also built an invalid
contract"). The board stayed shrunken until the next complete scrape.

The earlier KTC (14:14Z) and IDPTradeCalc (16:32Z) timeouts that day were the
same class of failure.

WHAT MUST HOLD
--------------
* **Promotion.** A run whose critical source failed or timed out does not
  replace a contract-healthy served generation. That covers the in-memory
  generation, ``exports/latest`` and the scraper-owned ``site_raw`` CSVs.
* **Health.** Contract integrity and ingestion health are separate truths.
  While that run is the latest one, ``/api/health`` is DEGRADED/503 with
  ``contract_ok=true``, ``served_generation_ok=true`` and
  ``source_health_ok=false``, and it names the failed source.
* **Recovery.** A later complete run promotes normally, and health returns to 200.
* **Cold start.** With no healthy board to keep, the partial run is still
  served. The contract then truthfully reports itself not ok.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
from datetime import datetime, timezone

import pytest

import server

LKG_PLAYERS = 1111
PARTIAL_PLAYERS = 979


def _players(n: int) -> dict:
    return {str(i): {"name": f"Player {i}"} for i in range(n)}


def _run_summary(*, timed_out: list[str] | None = None) -> dict:
    timed_out = list(timed_out or [])
    return {
        "enabledSources": ["KTC", "IDPTradeCalc"],
        "completeSources": [s for s in ("KTC", "IDPTradeCalc") if s not in timed_out],
        "partialSources": [],
        "failedSources": [],
        "timedOutSources": timed_out,
        "partialRun": bool(timed_out),
        "overallStatus": "partial" if timed_out else "complete",
    }


def _scrape_result(*, players: int, timed_out: list[str] | None = None) -> dict:
    """The production shape: both anchors non-empty, the summary says partial."""
    return {
        "date": "2026-09-23",
        "scrapeTimestamp": datetime.now(timezone.utc).isoformat(),
        "players": _players(players),
        "sites": [
            {"key": "ktc", "playerCount": 500},
            # Recovered partial values: non-empty, so the anchor check passes.
            {"key": "idpTradeCalc", "playerCount": 480 if timed_out else 1024},
        ],
        "coverageAudit": {"expectedSites": {"offense": ["ktc"], "idp": ["idpTradeCalc"]}},
        "settings": {"sourceRunSummary": _run_summary(timed_out=timed_out)},
    }


PRODUCTION_PARTIAL = _scrape_result(players=PARTIAL_PLAYERS, timed_out=["IDPTradeCalc"])


class TestCriticalSourceRunFailures:
    def test_the_production_run_is_critical_partial(self) -> None:
        assert server._critical_source_run_failures(PRODUCTION_PARTIAL) == [  # noqa: SLF001
            "IDPTradeCalc"
        ]

    def test_the_earlier_double_timeout(self) -> None:
        result = _scrape_result(players=1000, timed_out=["KTC", "IDPTradeCalc"])
        assert server._critical_source_run_failures(result) == [  # noqa: SLF001
            "KTC",
            "IDPTradeCalc",
        ]

    def test_a_complete_run_is_clean(self) -> None:
        result = _scrape_result(players=LKG_PLAYERS)
        assert server._critical_source_run_failures(result) == []  # noqa: SLF001

    def test_qualified_run_names_resolve_like_the_contract(self) -> None:
        result = _scrape_result(players=1000)
        summary = result["settings"]["sourceRunSummary"]
        summary.update(
            partialRun=True,
            overallStatus="partial",
            failedSources=["DLF_LocalCSV", "DraftSharks_IDP"],
        )
        # DLF_LocalCSV is critical; DraftSharks_IDP is not (it stays a
        # contract warning, so it must not block promotion either).
        assert server._critical_source_run_failures(result) == [  # noqa: SLF001
            "DLF_LocalCSV"
        ]

    def test_agrees_with_the_contract_gate(self) -> None:
        """The guard and ``partial_run_critical`` must name the same sources."""
        from src.api.data_contract import critical_primary_for_run_source  # noqa: PLC0415

        for name in ("KTC", "IDPTradeCalc", "DLF_LocalCSV", "DynastyNerds", "FantasyPros_IDP"):
            result = _scrape_result(players=1000)
            result["settings"]["sourceRunSummary"].update(
                partialRun=True, overallStatus="partial", timedOutSources=[name]
            )
            flagged = server._critical_source_run_failures(result) == [name]  # noqa: SLF001
            assert flagged == (critical_primary_for_run_source(name) is not None), name

    def test_malformed_payload_does_not_break_the_scrape(self) -> None:
        for bad in (
            None,
            {},
            {"settings": "nope"},
            {"settings": {"sourceRunSummary": "nope"}},
            {"settings": {"sourceRunSummary": {"partialRun": True, "timedOutSources": "x"}}},
        ):
            assert server._critical_source_run_failures(bad) == []  # noqa: SLF001


# ── run_scraper + /api/health, hermetic ──────────────────────────────────


def _fake_scraper(result: dict):
    class _FakeScraper:
        SCRIPT_DIR = ""

        async def run(self, progress_callback=None):
            return json.loads(json.dumps(result))

    return lambda: _FakeScraper()


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolated dirs, stubbed fetchers and a recorded ``_prime_latest_payload``."""
    base = tmp_path / "repo"
    data = base / "data"
    (base / "CSVs" / "site_raw").mkdir(parents=True)
    (base / "exports" / "latest").mkdir(parents=True)
    (data / "exports" / "latest" / "site_raw").mkdir(parents=True)
    # The scraper's own output for this run, which the server may mirror.
    (data / "exports" / "latest" / "site_raw" / "idpTradeCalc.csv").write_text("partial\n")
    (data / "exports" / "latest" / "dynasty_data_2026-09-23.json").write_text("{}")
    (base / "CSVs" / "site_raw" / "idpTradeCalc.csv").write_text("last-known-good\n")
    monkeypatch.setattr(server, "BASE_DIR", base)
    monkeypatch.setattr(server, "DATA_DIR", data)

    primed: list[dict] = []

    def _record_prime(payload, **_kwargs):
        primed.append(payload)
        server.latest_contract_data = {"players": []}
        server.contract_health = {"ok": True, "sourceHealthOk": True, "errors": []}

    monkeypatch.setattr(server, "_prime_latest_payload", _record_prime)
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    for mod_path in (
        "scripts.fetch_dynasty_nerds",
        "scripts.fetch_fantasypros_offense",
        "scripts.fetch_fantasypros_idp",
    ):
        mod = importlib.import_module(mod_path)
        monkeypatch.setattr(mod, "main", lambda argv=None: 0)

    # Scrape telemetry writes under REPO_ROOT/data/diagnostics, not DATA_DIR.
    monkeypatch.setenv("RISKIT_SCRAPE_TELEMETRY", "0")
    monkeypatch.setattr(server, "latest_data", None)
    monkeypatch.setattr(server, "latest_contract_data", None)
    monkeypatch.setattr(server, "contract_health", copy.deepcopy(server.contract_health))
    monkeypatch.setattr(server, "scrape_status", copy.deepcopy(server.scrape_status))
    monkeypatch.setattr(server, "scrape_history", [])
    monkeypatch.setattr(server, "_metrics", copy.deepcopy(server._metrics))  # noqa: SLF001
    monkeypatch.setattr(server, "latest_data_source", dict(server.latest_data_source))
    server.scrape_status["critical_source_failures"] = []
    return {"base": base, "data": data, "primed": primed}


def _serve_healthy_lkg() -> dict:
    lkg = _scrape_result(players=LKG_PLAYERS)
    server.latest_data = lkg
    server.latest_contract_data = {"players": []}
    server.contract_health = {"ok": True, "sourceHealthOk": True, "errors": []}
    server._set_latest_data_source(  # noqa: SLF001
        "scrape_run", "", produced_at=datetime.now(timezone.utc).isoformat()
    )
    return lkg


def _run(monkeypatch, result: dict) -> None:
    monkeypatch.setattr(server, "_import_scraper_module", _fake_scraper(result))
    asyncio.run(server.run_scraper(trigger="test"))


def _health() -> tuple[int, dict]:
    response = asyncio.run(server.get_health())
    return response.status_code, json.loads(response.body)


class TestPartialRunDoesNotReplaceHealthyBoard:
    def test_the_production_run_is_refused(self, env, monkeypatch) -> None:
        lkg = _serve_healthy_lkg()
        _run(monkeypatch, PRODUCTION_PARTIAL)

        assert env["primed"] == [], "the partial generation must not be primed"
        assert server.latest_data is lkg, "the last-known-good board must stay served"
        assert server.scrape_status["current_step"] == "blocked"
        assert server.scrape_history[-1]["outcome"] == "blocked"
        assert "IDPTradeCalc" in server.scrape_history[-1]["reason"]

    def test_exports_latest_is_not_overwritten(self, env, monkeypatch) -> None:
        """Startup recovery's fallback must still hold a healthy generation."""
        _serve_healthy_lkg()
        _run(monkeypatch, PRODUCTION_PARTIAL)
        assert not (env["base"] / "exports" / "latest" / "dynasty_data_2026-09-23.json").exists()

    def test_scraper_owned_csvs_are_not_mirrored(self, env, monkeypatch) -> None:
        """The contract rebuild reads CSVs/site_raw; the partial CSV must not reach it."""
        _serve_healthy_lkg()
        _run(monkeypatch, PRODUCTION_PARTIAL)
        mirrored = env["base"] / "CSVs" / "site_raw" / "idpTradeCalc.csv"
        assert mirrored.read_text() == "last-known-good\n"

    def test_health_is_degraded_with_both_truths(self, env, monkeypatch) -> None:
        _serve_healthy_lkg()
        _run(monkeypatch, PRODUCTION_PARTIAL)
        code, body = _health()
        assert code == 503
        assert body["status"] == "degraded"
        assert body["contract_ok"] is True
        assert body["served_generation_ok"] is True
        assert body["source_health_ok"] is False
        assert body["latest_run_critical_source_failures"] == ["IDPTradeCalc"]
        assert body["last_blocked_at"]

    def test_recovery_promotes_and_health_returns(self, env, monkeypatch) -> None:
        _serve_healthy_lkg()
        _run(monkeypatch, PRODUCTION_PARTIAL)
        assert _health()[0] == 503

        complete = _scrape_result(players=LKG_PLAYERS)
        _run(monkeypatch, complete)
        assert len(env["primed"]) == 1, "a complete run promotes normally"
        assert server.scrape_status["critical_source_failures"] == []
        code, body = _health()
        assert code == 200, body
        assert body["source_health_ok"] is True
        assert body["contract_ok"] is True
        # The complete run's own CSVs are mirrored again.
        mirrored = env["base"] / "CSVs" / "site_raw" / "idpTradeCalc.csv"
        assert mirrored.read_text() == "partial\n"


class TestColdStart:
    def test_no_healthy_board_means_the_partial_run_is_served(self, env, monkeypatch) -> None:
        """Nothing to keep: serving the partial board beats serving nothing."""
        _run(monkeypatch, PRODUCTION_PARTIAL)
        assert len(env["primed"]) == 1
        assert server.scrape_status["critical_source_failures"] == ["IDPTradeCalc"]

    def test_a_structurally_invalid_board_is_not_kept_over_a_new_run(
        self, env, monkeypatch
    ) -> None:
        server.latest_data = _scrape_result(players=LKG_PLAYERS)
        server.contract_health = {
            "ok": False,
            "structurallyOk": False,
            "sourceHealthOk": True,
            "errors": ["value_out_of_scale:x"],
        }
        _run(monkeypatch, PRODUCTION_PARTIAL)
        assert len(env["primed"]) == 1


class TestSourceLaneOnlyBoardIsStillKept:
    def test_a_served_board_with_only_source_lane_errors_is_kept(self, env, monkeypatch) -> None:
        """The owner's test is structural validity, not a spotless source lane.

        A served board carrying, say, ``pick_count_below_floor`` is still a
        better board than a critical-partial run, and replacing it would
        mirror the partial export over ``exports/latest`` again.
        """
        lkg = _serve_healthy_lkg()
        server.contract_health = {
            "ok": False,
            "structurallyOk": True,
            "sourceHealthOk": False,
            "errors": ["pick_count_below_floor:2027"],
        }
        _run(monkeypatch, PRODUCTION_PARTIAL)
        assert env["primed"] == []
        assert server.latest_data is lkg
        assert not (env["base"] / "exports" / "latest" / "dynasty_data_2026-09-23.json").exists()


class TestOtherRefusalsDoNotMirrorCsvs:
    def test_a_missing_anchor_refusal_keeps_the_served_csvs(self, env, monkeypatch) -> None:
        _serve_healthy_lkg()
        result = _scrape_result(players=LKG_PLAYERS)
        result["sites"][1]["playerCount"] = 0  # the anchor arrived empty
        _run(monkeypatch, result)
        assert env["primed"] == []
        mirrored = env["base"] / "CSVs" / "site_raw" / "idpTradeCalc.csv"
        assert mirrored.read_text() == "last-known-good\n"
        assert server.scrape_status["critical_source_failures"] == ["idpTradeCalc"]


class TestRestartKeepsTheVerdict:
    def test_a_restart_does_not_turn_health_green(self, env, monkeypatch) -> None:
        """Startup must not forget that the last completed run lost a critical source.

        The scraper wrote the refused run's raw payload to the runtime path
        before the guard ran.  ``load_from_disk`` returns it (88% retention,
        above the collapse floor), and startup recovery then serves the
        untouched ``exports/latest`` board, which has a valid contract.
        """
        (env["data"] / "dynasty_data_2026-09-23.json").write_text(json.dumps(PRODUCTION_PARTIAL))
        (env["base"] / "exports" / "latest" / "dynasty_data_2026-09-23.json").write_text(
            json.dumps(_scrape_result(players=LKG_PLAYERS))
        )
        server.scrape_status["critical_source_failures"] = []  # a fresh process
        loaded = server.load_from_disk()
        assert server.latest_data_source["type"] == "disk_cache"
        server._seed_ingestion_verdict_from_startup_payload(loaded)  # noqa: SLF001
        assert server.scrape_status["critical_source_failures"] == ["IDPTradeCalc"]

        # Recovery serves a valid board, and health still reports the outage.
        server.latest_contract_data = {"players": []}
        server.contract_health = {"ok": True, "sourceHealthOk": True, "errors": []}
        server._set_latest_data_source(  # noqa: SLF001
            "checkout_contract_recovery", "", produced_at=datetime.now(timezone.utc).isoformat()
        )
        code, body = _health()
        assert code == 503
        assert body["contract_ok"] is True
        assert body["source_health_ok"] is False

    def test_a_missing_anchor_last_run_is_seeded_too(self, env, monkeypatch) -> None:
        """Same union the guard records: an empty anchor is a critical-source failure."""
        refused = _scrape_result(players=LKG_PLAYERS)
        refused["sites"][1]["playerCount"] = 0
        (env["data"] / "dynasty_data_2026-09-23.json").write_text(json.dumps(refused))
        server.scrape_status["critical_source_failures"] = []
        loaded = server.load_from_disk()
        server._seed_ingestion_verdict_from_startup_payload(loaded)  # noqa: SLF001
        assert server.scrape_status["critical_source_failures"] == ["idpTradeCalc"]

    def test_a_complete_last_run_seeds_a_clean_verdict(self, env, monkeypatch) -> None:
        (env["data"] / "dynasty_data_2026-09-23.json").write_text(
            json.dumps(_scrape_result(players=LKG_PLAYERS))
        )
        server.scrape_status["critical_source_failures"] = ["stale"]
        loaded = server.load_from_disk()
        server._seed_ingestion_verdict_from_startup_payload(loaded)  # noqa: SLF001
        assert server.scrape_status["critical_source_failures"] == []

    def test_a_checkout_load_leaves_the_verdict_alone(self, env, monkeypatch) -> None:
        (env["base"] / "exports" / "latest" / "dynasty_data_2026-09-23.json").write_text(
            json.dumps(PRODUCTION_PARTIAL)
        )
        server.scrape_status["critical_source_failures"] = []
        loaded = server.load_from_disk()
        assert server.latest_data_source["type"] == "checkout_cache"
        server._seed_ingestion_verdict_from_startup_payload(loaded)  # noqa: SLF001
        assert server.scrape_status["critical_source_failures"] == []


class TestUnknownSourceHealthIsNotOk:
    def test_an_uninitialized_contract_reports_unknown(self, env) -> None:
        server.contract_health = {"ok": False, "errors": ["contract not initialized"]}
        code, body = _health()
        assert code == 503
        assert body["source_health_ok"] is None

    def test_health_after_a_served_partial_run_stays_degraded(self, env, monkeypatch) -> None:
        _run(monkeypatch, PRODUCTION_PARTIAL)
        # What the real contract says about that board (source lane).
        server.contract_health = {
            "ok": False,
            "sourceHealthOk": False,
            "structurallyOk": True,
            "errors": ["partial_run_critical:IDPTradeCalc"],
        }
        server._set_latest_data_source(  # noqa: SLF001
            "scrape_run", "", produced_at=datetime.now(timezone.utc).isoformat()
        )
        code, body = _health()
        assert code == 503
        assert body["contract_ok"] is False
        assert body["source_health_ok"] is False
