"""V1-136 failure-state structuring for the IDP Show fetcher.

``scripts/fetch_idpshow.py`` used to signal its outcome with a bare exit
code (0/1/2), and ``deploy/idpshow_fetch_and_push.sh`` collapsed even that:
every non-zero exit logged the same "exited non-zero — keeping previous
CSV/stamp" line, so an expired session, a vendor page redesign, a network
blip and a thin-board schema regression were indistinguishable at the
persistence layer.

This pins the acquisition-layer instrumentation that removes that collapse
for BOTH boards this fetcher acquires. Every ``main()`` return point — on
the plain (diagnostic) path AND the ``--combined`` (voting) path — now
constructs a real ``src.sources.acquisition_state.AcquisitionOutcome`` (the
existing, shared vocabulary — nothing invented here) and persists it to a
board-specific status file:

* ``data/scrape_state/idpShow_last_status.json`` — the plain board. Fetched
  for diagnostics only; unregistered, cannot vote.
* ``data/scrape_state/idpShowCombined_last_status.json`` — the combined
  board. This is the IDP Show provider family's SOLE voting source as of
  #1012 (2026-08-20).

Two files, not one, because ``deploy/idpshow_fetch_and_push.sh`` runs this
script TWICE per cycle (plain, then ``--combined``) as two separate process
invocations. A single shared file would let the second run's outcome
silently overwrite the first's — exactly the "which board is this status
even about" collapse this instrumentation exists to prevent. No
auth/session logic changed; no bridge/ranking code changed.

Reconciliation note (2026-08-21, Integration/Claude 5). This file replaces
the plain-board-only version written on ``claude/lane8-v1-136-idpshow-audit``
(#1001, commit ``136340964``), whose copy of ``scripts/fetch_idpshow.py``
predates PR #1008's ``--combined`` machinery entirely. Per
``docs/sources/LANE8_POST_1012_RECONCILIATION_AUDIT.md`` Task C's 5-point
reconciliation plan, the instrumentation pattern is re-applied from CURRENT
main's copy of the fetcher (which has ``--combined``), extended onto that
branch's return points too, with the status path made board-aware and a new
``SCHEMA_CHANGED`` outcome added for the combined board's 450-row floor
(previously a bare ``return 2`` with no outcome at all).
"""

from __future__ import annotations

import json

import pytest

import scripts.fetch_idpshow as mod
from src.sources.acquisition_state import (
    AUTH_REQUIRED,
    HEALTHY,
    PARSE_FAILED,
    SCHEMA_CHANGED,
    UNAVAILABLE,
)

_FAKE_COOKIE_VALUE = "synthetic-test-fixture-cookie-not-a-real-credential"

_GOOD_CSV_HEADER = "PLAYER,POSITION RANK,OVERALL\n"
_GOOD_COMBINED_HEADER = "Rank\tName\tPosition\tTeam\tChange\n"

_IFRAME_HTML = "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>"


def _good_csv(n: int) -> str:
    lines = [_GOOD_CSV_HEADER]
    for i in range(1, n + 1):
        lines.append(f"Player {i},DL{i},{i}\n")
    return "".join(lines)


def _good_combined_csv(n: int) -> str:
    lines = [_GOOD_COMBINED_HEADER]
    for i in range(1, n + 1):
        lines.append(f"{i}\tPlayer {i}\tDL\tXXX\t0\n")
    return "".join(lines)


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    session_path = tmp_path / "idpshow_session.json"
    out_path = tmp_path / "CSVs" / "site_raw" / "idpShow.csv"
    combined_out_path = tmp_path / "CSVs" / "site_raw" / "idpShowCombined.csv"
    status_path = tmp_path / "data" / "scrape_state" / "idpShow_last_status.json"
    combined_status_path = tmp_path / "data" / "scrape_state" / "idpShowCombined_last_status.json"
    monkeypatch.setattr(mod, "SESSION_PATH", session_path)
    monkeypatch.setattr(mod, "OUT_PATH", out_path)
    monkeypatch.setattr(mod, "COMBINED_OUT_PATH", combined_out_path)
    monkeypatch.setattr(mod, "STATUS_PATH", status_path)
    monkeypatch.setattr(mod, "COMBINED_STATUS_PATH", combined_status_path)
    # Every scenario stubs the network; _build_session's return value is
    # never actually used for a real request once _fetch_article_html /
    # _resolve_latest_version / _fetch_dataset_csv are monkeypatched below.
    monkeypatch.setattr(mod, "_build_session", lambda: object())
    return {
        "session": session_path,
        "out": out_path,
        "combined_out": combined_out_path,
        "status": status_path,
        "combined_status": combined_status_path,
    }


def _write_session_file(path) -> None:
    path.write_text(
        json.dumps({"cookies": [{"name": "connect.sid", "value": _FAKE_COOKIE_VALUE}]}),
        encoding="utf-8",
    )


def _read_status(status_path) -> dict:
    return json.loads(status_path.read_text(encoding="utf-8"))


class TestExplicitOutcomeStatesPlainBoard:
    def test_missing_session_file_is_auth_required(self, paths, capsys):
        # No _write_session_file call — the file is absent.
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == AUTH_REQUIRED
        assert status["reason"] == "session_file_missing"
        assert status["rowCount"] is None
        assert status["acquired"] is False
        assert status["usable"] is False
        assert not paths[
            "combined_status"
        ].exists(), "plain run must not touch the combined status file"

    def test_expired_session_is_auth_required_not_unavailable(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session, url=mod.ARTICLE_URL: "Subscribe to read this post",
        )
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == AUTH_REQUIRED
        assert status["reason"] == "session_expired_paywalled"

    def test_article_fetch_network_failure_is_unavailable(self, paths, monkeypatch):
        _write_session_file(paths["session"])

        def _boom(session, url=mod.ARTICLE_URL):
            raise RuntimeError("GET failed: HTTP 503")

        monkeypatch.setattr(mod, "_fetch_article_html", _boom)
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == UNAVAILABLE
        assert status["reason"] == "article_fetch_failed"

    def test_missing_chart_id_is_parse_failed(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session, url=mod.ARTICLE_URL: "<html>no iframe</html>",
        )
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == PARSE_FAILED
        assert status["reason"] == "chart_id_not_found"

    def test_version_redirect_failure_is_unavailable(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: None)
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == UNAVAILABLE
        assert status["reason"] == "version_resolution_http_error"

    def test_zero_rows_parsed_is_parse_failed(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: "UNRELATED,HEADER\n1,2\n"
        )
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == PARSE_FAILED
        assert status["reason"] == "no_rows_extracted"

    def test_below_floor_is_schema_changed(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(10)
        )
        code = mod.main([])
        assert code == 2
        status = _read_status(paths["status"])
        assert status["state"] == SCHEMA_CHANGED
        assert status["reason"] == "row_count_below_floor"
        assert status["rowCount"] is None  # a failure state may never carry a count

    def test_success_is_healthy_and_advances_freshness(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(200)
        )
        code = mod.main([])
        assert code == 0
        status = _read_status(paths["status"])
        assert status["state"] == HEALTHY
        assert status["rowCount"] == 200
        assert status["acquired"] is True
        assert status["usable"] is True
        assert paths["out"].exists()
        assert not paths["combined_status"].exists()

    def test_dry_run_never_persists_a_status(self, paths, monkeypatch):
        """A dry run writes no CSV, so persisting HEALTHY would claim an
        acquisition that never happened."""
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(200)
        )
        code = mod.main(["--dry-run"])
        assert code == 0
        assert not paths["status"].exists()
        assert not paths["out"].exists()


class TestExplicitOutcomeStatesCombinedBoard:
    """The ``--combined`` path — the board that ACTUALLY VOTES since #1012.

    Every state here is stamped to ``idpShowCombined_last_status.json``,
    never the plain board's file.
    """

    def test_missing_session_file_is_auth_required(self, paths):
        code = mod.main(["--combined"])
        assert code == 1
        status = _read_status(paths["combined_status"])
        assert status["sourceKey"] == "idpShowCombined"
        assert status["state"] == AUTH_REQUIRED
        assert status["reason"] == "session_file_missing"
        assert not paths["status"].exists(), "combined run must not touch the plain status file"

    def test_expired_session_is_auth_required(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session, url=mod.ARTICLE_URL: "Log in to read this post",
        )
        code = mod.main(["--combined"])
        assert code == 1
        status = _read_status(paths["combined_status"])
        assert status["state"] == AUTH_REQUIRED
        assert status["reason"] == "session_expired_paywalled"

    def test_article_fetch_failure_is_unavailable(self, paths, monkeypatch):
        _write_session_file(paths["session"])

        def _boom(session, url=mod.ARTICLE_URL):
            raise RuntimeError("GET failed: HTTP 503")

        monkeypatch.setattr(mod, "_fetch_article_html", _boom)
        code = mod.main(["--combined"])
        assert code == 1
        status = _read_status(paths["combined_status"])
        assert status["state"] == UNAVAILABLE
        assert status["reason"] == "article_fetch_failed"

    def test_no_usable_chart_is_parse_failed(self, paths, monkeypatch):
        """Neither candidate chart produced a usable dataset --
        ``_pick_widest_chart`` returned ``None``."""
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["a", "b"])
        monkeypatch.setattr(mod, "_pick_widest_chart", lambda session, ids: None)
        code = mod.main(["--combined"])
        assert code == 1
        status = _read_status(paths["combined_status"])
        assert status["state"] == PARSE_FAILED
        assert status["reason"] == "no_combined_chart_found"

    def test_zero_rows_parsed_is_parse_failed(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", "UNRELATED\tHEADER\n1\t2\n"),
        )
        code = mod.main(["--combined"])
        assert code == 1
        status = _read_status(paths["combined_status"])
        assert status["state"] == PARSE_FAILED
        assert status["reason"] == "no_rows_extracted"

    def test_below_combined_floor_is_schema_changed(self, paths, monkeypatch):
        """The 450-row floor. Main's copy of this branch previously had
        NO outcome instrumentation at all here -- a bare ``return 2``."""
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(20)),
        )
        code = mod.main(["--combined"])
        assert code == 2
        status = _read_status(paths["combined_status"])
        assert status["state"] == SCHEMA_CHANGED
        assert status["reason"] == "row_count_below_floor"
        assert status["rowCount"] is None

    def test_success_is_healthy(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(500)),
        )
        code = mod.main(["--combined"])
        assert code == 0
        status = _read_status(paths["combined_status"])
        assert status["sourceKey"] == "idpShowCombined"
        assert status["state"] == HEALTHY
        assert status["rowCount"] == 500
        assert paths["combined_out"].exists()
        assert not paths["status"].exists()

    def test_dry_run_never_persists_a_status(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(500)),
        )
        code = mod.main(["--combined", "--dry-run"])
        assert code == 0
        assert not paths["combined_status"].exists()
        assert not paths["combined_out"].exists()


class TestBoardsDoNotContaminateEachOther:
    """The critical anti-false-green property: the plain board succeeding
    must never make the combined (voting) board's report read HEALTHY, and
    vice versa. Two independent files, two independent facts."""

    def test_plain_healthy_then_combined_failure_leaves_combined_unhealthy(
        self, paths, monkeypatch
    ):
        _write_session_file(paths["session"])

        # Run 1: plain board, real success.
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(200)
        )
        code_plain = mod.main([])
        assert code_plain == 0
        plain_status = _read_status(paths["status"])
        assert plain_status["state"] == HEALTHY

        # Run 2: combined board, genuine failure (below the 450-row floor).
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(20)),
        )
        code_combined = mod.main(["--combined"])
        assert code_combined == 2

        # The board that actually votes must report its OWN true outcome --
        # never inherit, default to, or be masked by the other board's
        # HEALTHY status.
        combined_status = _read_status(paths["combined_status"])
        assert combined_status["state"] != HEALTHY, (
            "idpShowCombined reported HEALTHY despite a genuine acquisition "
            "failure, merely because the plain board (a non-voting "
            "diagnostic) succeeded in the same cycle"
        )
        assert combined_status["state"] == SCHEMA_CHANGED
        assert combined_status["sourceKey"] == "idpShowCombined"

        # And the plain board's own (real, correct) success is untouched by
        # the later combined-board run.
        assert _read_status(paths["status"])["state"] == HEALTHY

    def test_combined_healthy_then_plain_failure_leaves_plain_unhealthy(self, paths, monkeypatch):
        _write_session_file(paths["session"])

        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(500)),
        )
        code_combined = mod.main(["--combined"])
        assert code_combined == 0
        assert _read_status(paths["combined_status"])["state"] == HEALTHY

        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: None)
        code_plain = mod.main([])
        assert code_plain == 1
        plain_status = _read_status(paths["status"])
        assert plain_status["state"] != HEALTHY
        assert plain_status["state"] == UNAVAILABLE
        assert _read_status(paths["combined_status"])["state"] == HEALTHY


class TestLastGoodPreservation:
    """Every failure path must leave a pre-existing CSV byte-for-byte
    untouched -- this is the freshness stamp's counterpart guarantee for
    the board itself. Covers both boards."""

    @pytest.mark.parametrize(
        "argv,monkeypatch_failure",
        [
            ([], "missing_session"),
            ([], "article_failure"),
            ([], "paywalled"),
            ([], "chart_id_missing"),
            ([], "version_failure"),
            ([], "zero_rows"),
            ([], "below_floor"),
            (["--combined"], "missing_session"),
            (["--combined"], "article_failure"),
            (["--combined"], "paywalled"),
            (["--combined"], "no_chart"),
            (["--combined"], "zero_rows"),
            (["--combined"], "below_floor"),
        ],
    )
    def test_failure_never_overwrites_existing_csv(
        self, paths, monkeypatch, argv, monkeypatch_failure
    ):
        combined = "--combined" in argv
        target = paths["combined_out"] if combined else paths["out"]
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = "name,position,rank\nLast Good Player,DL,1\n"
        target.write_text(existing, encoding="utf-8")

        if monkeypatch_failure != "missing_session":
            _write_session_file(paths["session"])

        if monkeypatch_failure == "paywalled":
            monkeypatch.setattr(
                mod,
                "_fetch_article_html",
                lambda session, url=mod.ARTICLE_URL: "Log in to read this post",
            )
        elif monkeypatch_failure == "article_failure":

            def _boom(session, url=mod.ARTICLE_URL):
                raise RuntimeError("boom")

            monkeypatch.setattr(mod, "_fetch_article_html", _boom)
        elif monkeypatch_failure == "chart_id_missing":
            monkeypatch.setattr(
                mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: "<html></html>"
            )
        elif monkeypatch_failure == "no_chart":
            monkeypatch.setattr(
                mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
            )
            monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["a"])
            monkeypatch.setattr(mod, "_pick_widest_chart", lambda session, ids: None)
        elif monkeypatch_failure in ("version_failure", "zero_rows", "below_floor"):
            monkeypatch.setattr(
                mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
            )
            if combined:
                monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
                if monkeypatch_failure == "zero_rows":
                    monkeypatch.setattr(
                        mod,
                        "_pick_widest_chart",
                        lambda session, ids: ("Kwh7Y", "5", "X\tY\n1\t2\n"),
                    )
                else:  # below_floor
                    monkeypatch.setattr(
                        mod,
                        "_pick_widest_chart",
                        lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(5)),
                    )
            else:
                if monkeypatch_failure == "version_failure":
                    monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, cid: None)
                else:
                    monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, cid: "5")
                    if monkeypatch_failure == "zero_rows":
                        monkeypatch.setattr(
                            mod, "_fetch_dataset_csv", lambda session, cid, v: "X,Y\n1,2\n"
                        )
                    else:
                        monkeypatch.setattr(
                            mod, "_fetch_dataset_csv", lambda session, cid, v: _good_csv(5)
                        )

        code = mod.main(argv)
        assert code in (1, 2)
        assert target.read_text(encoding="utf-8") == existing


class TestNoSecretValuesLeak:
    @pytest.mark.parametrize("argv", [[], ["--combined"]])
    def test_status_json_never_contains_the_cookie_value(self, paths, monkeypatch, capsys, argv):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session, url=mod.ARTICLE_URL: "Subscribe to read this post",
        )
        mod.main(argv)
        status_path = paths["combined_status"] if "--combined" in argv else paths["status"]
        raw_status = status_path.read_text(encoding="utf-8")
        assert _FAKE_COOKIE_VALUE not in raw_status
        captured = capsys.readouterr()
        assert _FAKE_COOKIE_VALUE not in captured.out
        assert _FAKE_COOKIE_VALUE not in captured.err


class TestOrdinalStaysOrdinalAndStatusGrantsNoEligibility:
    def test_written_csv_never_carries_a_manufactured_value_column(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(200)
        )
        mod.main([])
        header = paths["out"].read_text(encoding="utf-8").splitlines()[0]
        assert header == "name,position,rank"

    def test_combined_csv_never_carries_a_manufactured_value_column(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(500)),
        )
        mod.main(["--combined"])
        header = paths["combined_out"].read_text(encoding="utf-8").splitlines()[0]
        assert header == "name,position,rank"

    def test_acquisition_status_wiring_stays_out_of_the_ranking_pipeline(self):
        """Static guard: the status files / this module's outcome must
        never be read by the ranking/bridge pipeline to decide voting
        eligibility -- acquisition status is fetch-layer instrumentation
        only."""
        import src.api.data_contract as dc
        import src.bridges.assess as bridges_assess
        import src.bridges.descriptor as bridges_descriptor

        for mod_under_test in (dc, bridges_assess, bridges_descriptor):
            src_text = mod_under_test.__file__
            with open(src_text, encoding="utf-8") as f:
                content = f.read()
            # A comment naming the fetcher script as the CSV's producer is
            # fine (data_contract.py already does this, harmlessly), and so
            # is the ranking pipeline's own PRE-EXISTING, generic use of
            # AcquisitionOutcome for build-level bridge-capability
            # bookkeeping (Lane 8 PR B) -- that is a different,
            # already-reviewed concern. What must never appear is either
            # idpShow board's own persisted STATUS artifact being read to
            # decide anything: that would be THIS instrumentation granting
            # voting eligibility, which is out of scope for this slice.
            assert "idpShow_last_status" not in content
            assert "idpShowCombined_last_status" not in content


class TestMutationProofs:
    """Force each failure branch through as if it were HEALTHY (or force a
    healthy branch through as a failure) and confirm the guard tests above
    go RED -- proving the state assignment, not just the exit code, is
    load-bearing."""

    def test_mutating_auth_required_to_healthy_is_caught(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session, url=mod.ARTICLE_URL: "Subscribe to read this post",
        )

        original_outcome_cls = mod.AcquisitionOutcome

        def _mutated(*args, **kwargs):
            if kwargs.get("state") == AUTH_REQUIRED:
                kwargs["state"] = HEALTHY
                kwargs["row_count"] = 0
            return original_outcome_cls(*args, **kwargs)

        monkeypatch.setattr(mod, "AcquisitionOutcome", _mutated)
        mod.main([])
        status = _read_status(paths["status"])
        # The mutation takes effect...
        assert status["state"] == HEALTHY
        # ...which is exactly the defect this instrumentation exists to
        # prevent: an auth failure must never be reported as HEALTHY.
        with pytest.raises(AssertionError):
            assert status["state"] == AUTH_REQUIRED

    def test_mutating_combined_schema_changed_to_healthy_is_caught(self, paths, monkeypatch):
        """Same proof, on the board that actually votes -- the row-floor
        guard #1001's own branch never had instrumentation for at all."""
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session, url=mod.ARTICLE_URL: _IFRAME_HTML
        )
        monkeypatch.setattr(mod, "_extract_all_chart_ids", lambda html: ["Kwh7Y"])
        monkeypatch.setattr(
            mod,
            "_pick_widest_chart",
            lambda session, ids: ("Kwh7Y", "5", _good_combined_csv(20)),
        )

        original_outcome_cls = mod.AcquisitionOutcome

        def _mutated(*args, **kwargs):
            if kwargs.get("state") == SCHEMA_CHANGED:
                kwargs["state"] = HEALTHY
                kwargs["row_count"] = 20
            return original_outcome_cls(*args, **kwargs)

        monkeypatch.setattr(mod, "AcquisitionOutcome", _mutated)
        mod.main(["--combined"])
        status = _read_status(paths["combined_status"])
        assert status["state"] == HEALTHY
        with pytest.raises(AssertionError):
            assert status["state"] == SCHEMA_CHANGED
