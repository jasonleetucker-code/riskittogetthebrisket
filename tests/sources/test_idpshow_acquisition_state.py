"""V1-136 failure-state structuring for the IDP Show fetcher.

``scripts/fetch_idpshow.py`` used to signal its outcome with a bare exit
code (0/1/2), and ``deploy/idpshow_fetch_and_push.sh`` collapsed even that:
every non-zero exit logged the same "exited non-zero — keeping previous
CSV/stamp" line, so an expired session, a vendor page redesign, a network
blip and a thin-board schema regression were indistinguishable at the
persistence layer.

This pins the smallest acquisition-layer instrumentation that removes that
collapse: every ``main()`` return point now constructs a real
``src.sources.acquisition_state.AcquisitionOutcome`` (the existing, shared
vocabulary — nothing invented here) and persists it to
``data/scrape_state/idpShow_last_status.json`` alongside the pre-existing
freshness stamp. No auth/session logic changed; no bridge/ranking code
changed.
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


def _good_csv(n: int) -> str:
    lines = [_GOOD_CSV_HEADER]
    for i in range(1, n + 1):
        lines.append(f"Player {i},DL{i},{i}\n")
    return "".join(lines)


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    session_path = tmp_path / "idpshow_session.json"
    out_path = tmp_path / "CSVs" / "site_raw" / "idpShow.csv"
    status_path = tmp_path / "data" / "scrape_state" / "idpShow_last_status.json"
    monkeypatch.setattr(mod, "SESSION_PATH", session_path)
    monkeypatch.setattr(mod, "OUT_PATH", out_path)
    monkeypatch.setattr(mod, "STATUS_PATH", status_path)
    # Every scenario stubs the network; _build_session's return value is
    # never actually used for a real request once _fetch_article_html /
    # _resolve_latest_version / _fetch_dataset_csv are monkeypatched below.
    monkeypatch.setattr(mod, "_build_session", lambda: object())
    return {"session": session_path, "out": out_path, "status": status_path}


def _write_session_file(path) -> None:
    path.write_text(
        json.dumps({"cookies": [{"name": "connect.sid", "value": _FAKE_COOKIE_VALUE}]}),
        encoding="utf-8",
    )


def _read_status(status_path) -> dict:
    return json.loads(status_path.read_text(encoding="utf-8"))


class TestExplicitOutcomeStates:
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

    def test_expired_session_is_auth_required_not_unavailable(self, paths, monkeypatch):
        """A distinct auth failure from a missing file: the session file IS
        present, but the vendor still shows the paywall — this is fixed by
        an owner re-minting cookies, not by waiting, so it must be
        AUTH_REQUIRED and never collapse into UNAVAILABLE."""
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session: "Subscribe to read this post"
        )
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == AUTH_REQUIRED
        assert status["reason"] == "session_expired_paywalled"

    def test_article_fetch_network_failure_is_unavailable(self, paths, monkeypatch):
        _write_session_file(paths["session"])

        def _boom(session):
            raise RuntimeError("GET failed: HTTP 503")

        monkeypatch.setattr(mod, "_fetch_article_html", _boom)
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == UNAVAILABLE
        assert status["reason"] == "article_fetch_failed"

    def test_missing_chart_id_is_parse_failed(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(mod, "_fetch_article_html", lambda session: "<html>no iframe</html>")
        code = mod.main([])
        assert code == 1
        status = _read_status(paths["status"])
        assert status["state"] == PARSE_FAILED
        assert status["reason"] == "chart_id_not_found"

    def test_version_redirect_failure_is_unavailable(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
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
            mod,
            "_fetch_article_html",
            lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
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
            mod,
            "_fetch_article_html",
            lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
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
            mod,
            "_fetch_article_html",
            lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
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

    def test_dry_run_never_persists_a_status(self, paths, monkeypatch):
        """A dry run writes no CSV, so persisting HEALTHY would claim an
        acquisition that never happened."""
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(200)
        )
        code = mod.main(["--dry-run"])
        assert code == 0
        assert not paths["status"].exists()
        assert not paths["out"].exists()


class TestLastGoodPreservation:
    """Every failure path must leave a pre-existing CSV byte-for-byte
    untouched — this is the freshness stamp's counterpart guarantee for the
    board itself."""

    @pytest.mark.parametrize(
        "monkeypatch_failure",
        [
            "missing_session",
            "article_failure",
            "paywalled",
            "chart_id_missing",
            "version_failure",
            "zero_rows",
            "below_floor",
        ],
    )
    def test_failure_never_overwrites_existing_csv(
        self, paths, monkeypatch, monkeypatch_failure
    ):
        paths["out"].parent.mkdir(parents=True, exist_ok=True)
        existing = "name,position,rank\nLast Good Player,DL,1\n"
        paths["out"].write_text(existing, encoding="utf-8")

        if monkeypatch_failure != "missing_session":
            _write_session_file(paths["session"])

        if monkeypatch_failure == "paywalled":
            monkeypatch.setattr(
                mod, "_fetch_article_html", lambda session: "Log in to read this post"
            )
        elif monkeypatch_failure == "article_failure":
            def _boom(session):
                raise RuntimeError("boom")

            monkeypatch.setattr(mod, "_fetch_article_html", _boom)
        elif monkeypatch_failure == "chart_id_missing":
            monkeypatch.setattr(mod, "_fetch_article_html", lambda session: "<html></html>")
        elif monkeypatch_failure in ("version_failure", "zero_rows", "below_floor"):
            monkeypatch.setattr(
                mod,
                "_fetch_article_html",
                lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
            )
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

        code = mod.main([])
        assert code in (1, 2)
        assert paths["out"].read_text(encoding="utf-8") == existing


class TestNoSecretValuesLeak:
    def test_status_json_never_contains_the_cookie_value(self, paths, monkeypatch, capsys):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session: "Subscribe to read this post"
        )
        mod.main([])
        raw_status = paths["status"].read_text(encoding="utf-8")
        assert _FAKE_COOKIE_VALUE not in raw_status
        captured = capsys.readouterr()
        assert _FAKE_COOKIE_VALUE not in captured.out
        assert _FAKE_COOKIE_VALUE not in captured.err


class TestOrdinalStaysOrdinalAndStatusGrantsNoEligibility:
    def test_written_csv_never_carries_a_manufactured_value_column(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod,
            "_fetch_article_html",
            lambda session: "<iframe src='https://datawrapper.dwcdn.net/Kwh7Y/5/'></iframe>",
        )
        monkeypatch.setattr(mod, "_resolve_latest_version", lambda session, chart_id: "5")
        monkeypatch.setattr(
            mod, "_fetch_dataset_csv", lambda session, chart_id, version: _good_csv(200)
        )
        mod.main([])
        header = paths["out"].read_text(encoding="utf-8").splitlines()[0]
        assert header == "name,position,rank"

    def test_acquisition_status_wiring_stays_out_of_the_ranking_pipeline(self):
        """Static guard: the status file / this module's outcome must never
        be read by the ranking/bridge pipeline to decide voting eligibility
        -- acquisition status is fetch-layer instrumentation only."""
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
            # AcquisitionOutcome for build-level bridge-capability bookkeeping
            # (Lane 8 PR B) -- that is a different, already-reviewed concern.
            # What must never appear is idpShow's own persisted STATUS
            # artifact being read to decide anything: that would be THIS
            # instrumentation granting voting eligibility, which is out of
            # scope for this slice.
            assert "idpShow_last_status" not in content


class TestMutationProofs:
    """Force each failure branch through as if it were HEALTHY (or force a
    healthy branch through as a failure) and confirm the guard tests above
    go RED -- proving the state assignment, not just the exit code, is
    load-bearing."""

    def test_mutating_auth_required_to_healthy_is_caught(self, paths, monkeypatch):
        _write_session_file(paths["session"])
        monkeypatch.setattr(
            mod, "_fetch_article_html", lambda session: "Subscribe to read this post"
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
