"""The §4.3 challenger pass on M — that it runs, and that it cannot promote.

The script itself is evidence tooling and its numbers come from a real
board, so this file does not re-assert them. What it pins is the two
properties that make the evidence trustworthy: the champion cannot be
moved by running the pass, and the degenerate statistic that fooled the
first version stays visible.
"""

from __future__ import annotations

import ast
import json
import pathlib

from src.roster_intel.core import load_core_config, reserve_demand

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/challenge_core_multiplier.py"


def test_the_champion_is_still_one_point_five_and_still_labelled_prior():
    """Evaluation is not activation. Whatever the pass printed, the
    served multiplier is unchanged and its status is unchanged."""
    cfg = json.loads((REPO / "config/roster_intel/meaningful_core.json").read_text())
    assert cfg["reserveMultiplier"] == 1.5
    assert cfg["reserveMultiplierStatus"] == "PRIOR"
    assert load_core_config()["reserveMultiplier"] == 1.5


def test_the_config_records_that_the_pass_ran_without_claiming_it_froze_anything():
    cfg = json.loads((REPO / "config/roster_intel/meaningful_core.json").read_text())
    note = cfg["reserveMultiplierChallengerPass"]
    assert "run_" in note
    assert "not_frozen" in note
    assert "frozen" not in cfg["reserveMultiplierStatus"].lower()


def test_the_script_writes_no_config_and_imports_no_writer():
    """Structural: a challenger that can edit the champion's config is
    not a challenger. The one file it may write is the evidence JSON the
    caller names on the command line."""
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body[0].value.value = ""
    stripped = ast.unparse(tree)
    assert "meaningful_core.json" not in stripped
    assert "config/" not in stripped
    # Exactly one write, and it is the evidence file behind an explicit flag.
    assert stripped.count("write_text") == 1
    assert "args.json" in stripped


def test_the_degenerate_absence_count_is_still_reachable_and_still_explained():
    """``k = 1`` reads 100% for every candidate including M = 1.01, so it
    proves nothing — and it is kept in the default sweep precisely so
    that degeneracy is visible in the output rather than discovered
    again. A future edit that quietly drops it should fail here."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'default="1,2,3"' in source
    assert "DEGENERATE" in source


def test_the_candidates_the_policy_names_are_all_measured():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "candidates = [1.25, 1.50, 1.75]" in source
    # …and the data-derived cutoff is a threshold on the OUTCOME, swept
    # over several targets rather than reported at one chosen line.
    assert "--targets" in source
    assert "nargs=" in source


def test_a_challenger_multiplier_actually_changes_the_demand_it_is_meant_to():
    """Guards the whole exercise: if ``reserve_demand`` ignored an
    injected multiplier, every candidate would score identically and the
    pass would be measuring nothing."""
    slots = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
    totals = {
        m: reserve_demand(slots, config={"reserveMultiplier": m}).total()
        for m in (1.25, 1.50, 1.75)
    }
    assert totals[1.25] < totals[1.50] < totals[1.75], totals
