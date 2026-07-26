"""The refit driver's exit-code contract, exercised as a subprocess.

The workflow branches entirely on this script's exit code, so the
contract is tested the way the workflow uses it — ``subprocess.run``
against the real script, real registry and real boards — not by
importing ``main()`` and inspecting internals.

The point of these tests is the one thing the old guard could not do:
**come out red.**  A gate observed only passing is indistinguishable
from a gate that cannot fail, which is the defect this whole path was
rebuilt to remove.  ``test_a_bad_challenger_is_rejected`` uses the
exact curve ``(0.300, 2.50)`` that passed every pinned rank under the
old rebaselined guard.

All are ``--dry-run``: they must not mutate the committed registry.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.model_registry.hill_masters import CONSTANT_NAMES, read_committed_constants

pytestmark = pytest.mark.livedata

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "scripts" / "auto_refit_hill_curves.py"

EXIT_CHAMPION_STANDS = 0
EXIT_PROMOTABLE = 1
EXIT_ERROR = 2
EXIT_ALARM = 3


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DRIVER), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def _challenger(tmp_path: Path, **overrides: float) -> Path:
    params = dict(read_committed_constants())
    params.update(overrides)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "challenger.json"
    path.write_text(json.dumps(params, indent=2))
    return path


@pytest.fixture(scope="module", autouse=True)
def _require_boards():
    if not (REPO / "CSVs" / "site_raw" / "fantasyCalc.csv").exists():
        pytest.skip("holdout boards not present in this checkout")


class TestTheGateCanComeOutRed:
    def test_a_bad_challenger_is_rejected(self, tmp_path):
        """The curve the OLD guard accepted at every pinned rank."""
        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.300, HILL_PERCENTILE_S=2.500)
        r = _run("--challenger-json", str(path), "--dry-run")
        assert r.returncode == EXIT_ALARM, r.stdout + r.stderr
        assert "REJECTED" in r.stdout
        assert "ALARM" in r.stderr

    def test_a_mildly_worse_challenger_is_rejected_without_alarm(self, tmp_path):
        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.124)
        r = _run("--challenger-json", str(path), "--dry-run", "--force")
        assert r.returncode == EXIT_CHAMPION_STANDS, r.stdout + r.stderr
        assert "REJECTED" in r.stdout
        assert "Champion stands" in r.stdout

    def test_a_good_challenger_is_promotable(self, tmp_path):
        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.098)
        r = _run("--challenger-json", str(path), "--dry-run")
        assert r.returncode == EXIT_PROMOTABLE, r.stdout + r.stderr
        assert "PROMOTABLE" in r.stdout

    def test_both_verdicts_are_reachable_from_the_same_entry_point(self, tmp_path):
        """MECHANISM TEST. Red and green from one code path, so neither
        is an artifact of how the test invoked it."""
        bad = _challenger(tmp_path / "a", HILL_PERCENTILE_C=0.300, HILL_PERCENTILE_S=2.5)
        good = _challenger(tmp_path / "b", HILL_PERCENTILE_C=0.098)
        codes = {
            _run("--challenger-json", str(bad), "--dry-run").returncode,
            _run("--challenger-json", str(good), "--dry-run").returncode,
        }
        assert codes == {EXIT_ALARM, EXIT_PROMOTABLE}


class TestItRefusesToGuess:
    def test_a_malformed_challenger_is_an_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        r = _run("--challenger-json", str(path), "--dry-run")
        assert r.returncode == EXIT_ERROR
        assert "ERROR" in r.stderr

    def test_an_incomplete_challenger_is_an_error(self, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"HILL_PERCENTILE_C": 0.1}))
        r = _run("--challenger-json", str(path), "--dry-run")
        assert r.returncode == EXIT_ERROR
        assert "missing" in r.stderr

    def test_a_missing_challenger_file_is_an_error(self, tmp_path):
        r = _run("--challenger-json", str(tmp_path / "nope.json"), "--dry-run")
        assert r.returncode == EXIT_ERROR


class TestItDoesNotTouchProduction:
    def test_dry_run_leaves_constants_and_registry_untouched(self, tmp_path):
        before_constants = (REPO / "src/canonical/player_valuation.py").read_bytes()
        registry_path = REPO / "config" / "model_registry" / "hill_scope_masters.json"
        before_registry = registry_path.read_bytes()

        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.098)
        _run("--challenger-json", str(path), "--dry-run")

        assert (REPO / "src/canonical/player_valuation.py").read_bytes() == before_constants
        assert registry_path.read_bytes() == before_registry

    def test_a_promotable_challenger_still_does_not_self_promote(self, tmp_path):
        """MECHANISM TEST for the directive. Even the winning path must
        leave production alone and hand off to a human."""
        before = (REPO / "src/canonical/player_valuation.py").read_bytes()
        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.098)
        r = _run("--challenger-json", str(path), "--dry-run")
        assert r.returncode == EXIT_PROMOTABLE
        assert (REPO / "src/canonical/player_valuation.py").read_bytes() == before
        assert "A human must promote it" in r.stdout
        assert "model_registry.py promote" in r.stdout


class TestReportingHonesty:
    def test_it_names_which_parameters_are_actually_gated(self, tmp_path):
        """Six of the eight constants are versioned but not validated.
        The report must not let a reader assume otherwise."""
        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.098)
        r = _run("--challenger-json", str(path), "--dry-run")
        assert "only HILL_PERCENTILE_C / HILL_PERCENTILE_S" in r.stdout
        assert "not gated" in r.stdout

    def test_it_shows_both_sides_of_the_comparison(self, tmp_path):
        path = _challenger(tmp_path, HILL_PERCENTILE_C=0.098)
        r = _run("--challenger-json", str(path), "--dry-run")
        assert "champion v" in r.stdout
        assert "challenger" in r.stdout
        for board in ("FantasyCalc", "OTCFFB", "PFKDynasty", "FantasyNavigator"):
            assert board in r.stdout

    def test_no_drift_short_circuits_before_the_gate(self, tmp_path):
        """An identical challenger is not worth scoring."""
        params = dict(read_committed_constants())
        path = tmp_path / "same.json"
        path.write_text(json.dumps(params))
        r = _run("--challenger-json", str(path), "--dry-run")
        assert r.returncode == EXIT_CHAMPION_STANDS
        assert "No drift beyond threshold" in r.stdout
        assert "Held-out validation" not in r.stdout

    def test_force_scores_even_without_drift(self, tmp_path):
        params = dict(read_committed_constants())
        path = tmp_path / "same.json"
        path.write_text(json.dumps(params))
        r = _run("--challenger-json", str(path), "--dry-run", "--force")
        assert r.returncode == EXIT_CHAMPION_STANDS
        assert "Held-out validation" in r.stdout

    def test_all_eight_constants_are_required(self):
        assert len(CONSTANT_NAMES) == 8
