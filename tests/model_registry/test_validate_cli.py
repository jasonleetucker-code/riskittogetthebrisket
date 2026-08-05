"""``model_registry.py validate`` must not compare two stored scores.

WHY THIS EXISTS
===============
`cmd_validate` read the champion's and challenger's STORED holdout
criteria and handed both to ``decide_promotion``. ``promotion.py``'s
module docstring says the comparison must be made on ONE snapshot with
both curves scored against it, because the criterion's absolute level
drifts with the market while the paired delta does not.

Stored scores carry whatever date someone last ran ``evaluate --record``;
a challenger's is stamped at ``register`` time. Those coincide only by
luck. Measured on the live registry 2026-08-05, margin 25.0:

    stored vs stored (the old behaviour)   +12.79   REJECT (right, by luck)
    both scored fresh (correct)            +22.44   REJECT
    champion re-recorded only              +31.91   PROMOTE   <- WRONG

The third row is why "just re-record the champion" is not a data fix:
refreshing only the staler side inflates the gap by exactly the drift it
removes. The champion's score was 7 days stale, the challenger's 1.

The registry had already been bitten by this once and written it down —
``hill_scope_masters.json`` records v1 being re-scored in 2026-07 for
exactly this reason — and still shipped the defect in the CLI. Its own
files disagree today: v3's note says the improvement was ``+22.4`` while
the stored pair computes ``+12.79``.

WHAT COULD DISAGREE WITH IT, BEFORE
===================================
Nothing. **No test imported, executed or subprocessed
``scripts/model_registry.py`` at all** — the whole CLI (`status`,
`evaluate`, `validate`, `promote`, `rollback`, `apply`) had zero direct
coverage, and nothing would have failed if `cmd_validate` were deleted
outright.

`test_lifecycle.py` looks like coverage and is not: it calls
``decide_promotion`` on criteria it computes itself, freshly and paired,
inside the test. It exercises the correct semantics; the shipped CLI
implemented different ones; nothing compared the two.

WHY THIS MATTERS MORE THAN AN ADVISORY CLI USUALLY WOULD
========================================================
``cmd_promote`` has **no holdout gate** — it checks status and requires
a reason, nothing else. So this verdict is the only thing standing
between a human and ``promote`` + ``apply``, and ``apply`` writes the
constants ``_compute_unified_rankings`` uses for every row.

``evaluate_offense_master`` is stubbed here, so these are pure logic and
must block; the live-CSV path is covered by ``test_holdout.py``.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.model_registry.holdout import HoldoutError
from src.model_registry.versioning import ModelRegistry, ModelVersion

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_cli():
    """Import ``scripts/model_registry.py`` as a module.

    It is a script, not a package member, so there is no import path for
    it — which is a large part of why it went untested.
    """
    spec = importlib.util.spec_from_file_location(
        "_model_registry_cli", REPO_ROOT / "scripts" / "model_registry.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CLI = _load_cli()

CHAMP_PARAMS = {"HILL_PERCENTILE_C": 0.110, "HILL_PERCENTILE_S": 1.110}
CHAL_PARAMS = {"HILL_PERCENTILE_C": 0.108, "HILL_PERCENTILE_S": 1.110}


@dataclass
class _FakeEval:
    """Enough of ``HoldoutResult`` for ``cmd_validate``."""

    criterion: float


def _registry(champ_stored: float | None, chal_stored: float | None) -> ModelRegistry:
    reg = ModelRegistry("hill")
    reg.seed_champion(
        ModelVersion(
            model_id="hill",
            version=2,
            params=dict(CHAMP_PARAMS),
            fitted_at="2026-07-28T00:00:00Z",
            producer="test",
            status="champion",
            holdout={"criterion": champ_stored} if champ_stored is not None else None,
        )
    )
    reg.add(
        ModelVersion(
            model_id="hill",
            version=3,
            params=dict(CHAL_PARAMS),
            fitted_at="2026-08-04T00:00:00Z",
            producer="test",
            status="challenger",
            holdout={"criterion": chal_stored} if chal_stored is not None else None,
        )
    )
    return reg


def _run(monkeypatch, *, champ_stored, chal_stored, champ_fresh, chal_fresh):
    """Run ``cmd_validate`` with stored and fresh scores decoupled."""
    monkeypatch.setattr(CLI, "_load_or_seed", lambda: _registry(champ_stored, chal_stored))

    def fake_eval(c, s, **kw):
        if (c, s) == (CHAMP_PARAMS["HILL_PERCENTILE_C"], CHAMP_PARAMS["HILL_PERCENTILE_S"]):
            return _FakeEval(champ_fresh)
        return _FakeEval(chal_fresh)

    monkeypatch.setattr(CLI, "evaluate_offense_master", fake_eval)
    return CLI.cmd_validate(argparse.Namespace(version=3))


class TestThePremiseHolds:
    """Non-vacuity: these numbers straddle the real margin, so a verdict
    flip below is a genuine flip and not an artifact of the fixture."""

    def test_the_margin_is_what_this_test_assumes(self):
        from src.model_registry.promotion import PROMOTION_MARGIN

        assert PROMOTION_MARGIN == 25.0

    def test_the_fixture_numbers_straddle_it(self):
        assert 806.9611 - 784.5184 < 25.0  # paired -> REJECT
        assert 806.9611 - 775.0471 > 25.0  # champion-refreshed-only -> PROMOTE


class TestTheVerdictComesFromFreshScores:
    def test_stored_scores_do_not_decide(self, monkeypatch, capsys):
        """The live numbers, with stored and fresh deliberately different.

        Stored would give +12.79; fresh gives +22.44. Both REJECT, but
        for different reasons — so this asserts the printed figures, not
        just the exit code.
        """
        rc = _run(
            monkeypatch,
            champ_stored=787.8416,
            chal_stored=775.0471,
            champ_fresh=806.9611,
            chal_fresh=784.5184,
        )
        out = capsys.readouterr().out
        assert rc == 1
        assert "806.9611" in out and "784.5184" in out
        assert "REJECT" in out

    def test_a_stale_champion_cannot_manufacture_a_promote(self, monkeypatch, capsys):
        """THE headline case, and the one my own earlier advice got wrong.

        Re-recording only the champion leaves a 7-day-stale challenger
        beside a fresh champion: +31.91 against a 25-point margin, a
        false PROMOTE. With both scored fresh the same registry yields
        REJECT.
        """
        rc = _run(
            monkeypatch,
            champ_stored=806.9611,  # champion refreshed...
            chal_stored=775.0471,  # ...challenger left stale
            champ_fresh=806.9611,
            chal_fresh=784.5184,
        )
        out = capsys.readouterr().out
        assert rc == 1, "a stale-vs-fresh pairing produced a PROMOTE"
        assert "REJECT" in out
        assert "PROMOTE" not in out

    @pytest.mark.parametrize("perturbation", [-150.0, -25.1, 25.1, 150.0])
    def test_perturbing_a_stored_criterion_never_moves_the_verdict(
        self, monkeypatch, capsys, perturbation
    ):
        """The mutation, as a property.

        Each perturbation exceeds the promotion margin, so under the old
        stored-vs-stored behaviour every one of these would flip or
        distort the verdict.
        """
        rc = _run(
            monkeypatch,
            champ_stored=787.8416 + perturbation,
            chal_stored=775.0471,
            champ_fresh=806.9611,
            chal_fresh=784.5184,
        )
        out = capsys.readouterr().out
        assert rc == 1
        assert "REJECT" in out

    def test_a_genuine_win_still_promotes(self, monkeypatch, capsys):
        """The asymmetry — this is not a blanket REJECT."""
        rc = _run(
            monkeypatch,
            champ_stored=787.8416,
            chal_stored=775.0471,
            champ_fresh=806.9611,
            chal_fresh=700.0,  # -106.96, comfortably past the margin
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "PROMOTE" in out


class TestStalenessIsReportedNotHidden:
    def test_a_drifted_stored_figure_is_named(self, monkeypatch, capsys):
        """Re-scoring silently would tidy away the evidence that the
        registry is stale. The fix must surface it, not just bypass it."""
        _run(
            monkeypatch,
            champ_stored=787.8416,
            chal_stored=775.0471,
            champ_fresh=806.9611,
            chal_fresh=784.5184,
        )
        out = capsys.readouterr().out
        assert "STORED" in out
        assert "787.8416" in out
        assert "+19.1195" in out

    def test_no_note_when_the_registry_is_current(self, monkeypatch, capsys):
        """Without this the note could be unconditional and the test
        above would still pass."""
        _run(
            monkeypatch,
            champ_stored=806.9611,
            chal_stored=784.5184,
            champ_fresh=806.9611,
            chal_fresh=784.5184,
        )
        assert "STORED" not in capsys.readouterr().out


class TestAnUnevaluableGateIsNotAPass:
    def test_holdout_error_exits_2(self, monkeypatch, capsys):
        monkeypatch.setattr(CLI, "_load_or_seed", lambda: _registry(787.8416, 775.0471))

        def boom(*a, **kw):
            raise HoldoutError("holdout CSVs missing")

        monkeypatch.setattr(CLI, "evaluate_offense_master", boom)
        rc = CLI.cmd_validate(argparse.Namespace(version=3))
        assert rc == 2, "an unevaluable gate must not read as a pass"
        assert "Refusing" in capsys.readouterr().err

    def test_missing_params_exit_2_rather_than_crash(self, monkeypatch, capsys):
        """A version predating VALIDATED_PARAMS has no such keys. The
        gate should refuse, not raise a KeyError at the operator."""
        reg = _registry(787.8416, 775.0471)
        reg.get(3).params.pop("HILL_PERCENTILE_C", None)
        monkeypatch.setattr(CLI, "_load_or_seed", lambda: reg)
        monkeypatch.setattr(CLI, "evaluate_offense_master", lambda c, s, **kw: _FakeEval(1.0))
        assert CLI.cmd_validate(argparse.Namespace(version=3)) == 2


class TestTheRecipeIncludesTheRefreshStep:
    def test_the_driver_prints_evaluate_record_before_validate(self):
        """ADR-008 step 2 was dropped when steps 1-4 were collapsed into
        the driver, so the recipe handed to a human began at `validate`
        against a registry nobody had refreshed."""
        src = (REPO_ROOT / "scripts" / "auto_refit_hill_curves.py").read_text(encoding="utf-8")
        i_eval = src.find("model_registry.py evaluate --champion --record")
        i_val = src.find("model_registry.py validate {target}")
        assert i_eval != -1, "the promotion recipe no longer refreshes the champion first"
        assert i_eval < i_val, "the refresh step must come before validate"
