"""C1-U8 — the acquisition ledger cannot move a canonical value.

WHY A STRUCTURAL TEST AND NOT ONLY A MEASUREMENT
────────────────────────────────────────────────
A board diff proves inertness *on the day it was run*. What it cannot
prove is that inertness is a property of the design rather than an
accident of wiring — and for this unit it currently IS an accident:
nothing outside ``src/acquisition/`` imports the package, so the board
is unmoved because nobody wired it in, not because anything prevents it.
One future import would silently make a private historical substrate a
valuation input, and the measurement taken today would still read zero
because it was taken today.

So both halves are here. The measured zero is recorded in
``docs/acquisition/C1_U8_ACQUISITION_LEDGER.md``; these tests are the
half that survives the next change.

The direction of the rule matters. This is NOT "acquisition may not
import the pipeline" — it reads ``rankDerivedValue`` history through
``src/history`` quite legitimately. It is the reverse: **the valuation
path may not read acquisition.** Historical ownership is downstream of
value and must never become an input to it, or every measurement taken
from the ledger becomes circular — the same rule
``src/retention/__init__.py`` states for its own stores.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The modules that decide canonical player and pick value. If any of
#: them can reach acquisition history, the board is no longer a pure
#: function of market evidence.
_VALUATION_PATH = (
    "src/api/data_contract.py",
    "src/api/pick_value_resolution.py",
    "src/canonical/player_valuation.py",
    "src/canonical/calibration.py",
    "src/api/confidence.py",
    "Dynasty Scraper.py",
)


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestTheValuationPathCannotReachAcquisitionHistory:
    def test_no_valuation_module_imports_the_package(self):
        offenders = []
        for rel in _VALUATION_PATH:
            path = REPO / rel
            if not path.exists():
                continue
            if any(n.startswith("src.acquisition") for n in _imported_modules(path)):
                offenders.append(rel)
        assert not offenders, (
            f"the canonical valuation path imports acquisition history: {offenders}. "
            "Ownership history is DOWNSTREAM of value; feeding it back makes every "
            "measurement taken from the ledger circular."
        )

    def test_the_whole_src_tree_is_free_of_valuation_side_consumers(self):
        """Broader sweep, so a new pipeline module is covered the day it
        is written rather than the day someone remembers this list.

        ``src/trade/waiver_ledger.py`` (C4-WAIV-01) and
        ``src/trade/market_trade_ledger.py`` (C4-MTL-01) are the deliberate
        exceptions, both added 2026-08-20. Both are pure historical
        PROJECTIONS — grouping recorded transactions into claims/trades —
        and neither reaches ``rankDerivedValue`` or any canonical value;
        they read acquisition history the same legitimate direction
        ``src/history`` already reads value history, per this file's own
        stated rule ("historical ownership is downstream of value"). Each
        is named here by exact path rather than folded into a prefix
        allowance, so a third module reaching for the same import still
        has to earn its own line."""
        allowed_prefixes = ("src/acquisition/",)
        allowed_exact = {
            "src/trade/waiver_ledger.py",
            "src/trade/market_trade_ledger.py",
        }
        offenders = []
        for path in (REPO / "src").rglob("*.py"):
            rel = str(path.relative_to(REPO))
            if rel.startswith(allowed_prefixes) or rel in allowed_exact:
                continue
            if any(n.startswith("src.acquisition") for n in _imported_modules(path)):
                offenders.append(rel)
        assert not offenders, (
            f"unexpected src-tree consumers of src.acquisition: {offenders}. "
            "The authorized consumers are the offline collector and health probe under "
            "scripts/, plus src/trade/waiver_ledger.py and "
            "src/trade/market_trade_ledger.py; anything else needs a deliberate decision, "
            "not an import."
        )
        for rel in allowed_exact:
            assert rel not in _VALUATION_PATH, (
                f"{rel} is allowed to import acquisition history but is also listed in "
                "_VALUATION_PATH — those two facts cannot both hold."
            )


class TestTheContractBuildDoesNotTouchAcquisition:
    def test_building_a_contract_does_not_import_the_package(self):
        """The runtime counterpart of the static scan: import the
        contract builder in a fresh interpreter and assert the
        acquisition package never appears in ``sys.modules``.

        A static scan misses a lazy import inside a function; this does
        not.
        """
        import subprocess
        import sys

        probe = (
            "import sys;"
            "import src.api.data_contract as dc;"
            "leaked=[m for m in sys.modules if m.startswith('src.acquisition')];"
            "print('LEAKED' if leaked else 'CLEAN', leaked)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert result.stdout.startswith("CLEAN"), result.stdout


class TestConfidenceSemanticsAreUntouched:
    """C1-U8 is stacked directly on C1-U5, so "did U8 move confidence"
    needs its own answer rather than inheriting U5's."""

    def test_the_confidence_owner_does_not_know_about_acquisition(self):
        src = (REPO / "src" / "api" / "confidence.py").read_text(encoding="utf-8")
        assert "acquisition" not in src.lower()

    def test_the_level_and_basis_vocabularies_are_unchanged_by_this_unit(self):
        from src.api.confidence import CONFIDENCE_BASES, CONFIDENCE_LEVELS

        assert len(CONFIDENCE_LEVELS) == 4, "C1-U5 pinned four levels; U8 must not have added one"
        # The closed set C1-U5 established. U8 adds no evidence class.
        assert "acquisition" not in " ".join(CONFIDENCE_BASES).lower()
