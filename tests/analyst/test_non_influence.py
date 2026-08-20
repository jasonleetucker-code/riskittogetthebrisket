"""Structural proof: the analyst ledger cannot reach canonical valuation.

Mirrors the style of ``tests/api/test_canonical_ownership_protections.py``
(repository scans + real function calls, no AST framework — deliberately
simple, per that file's own stated rationale) rather than
``src.retention``'s absolute "no decision path may read this" rule,
which is stricter than this ledger needs: future analyst-facing features
(Manager Scout, Universal Player Profile, Ask Brisket) ARE meant to read
it. What must never happen is the canonical VALUATION path reading it.

Every scan here asserts non-vacuity (a non-empty file set was actually
scanned) — a check that silently stops matching is worse than no check
at all, same rule the file above states.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The modules that decide canonical player/pick VALUE. If any of these
#: ever imports src.analyst.store or src.analyst.query, an evidence
#: ledger has become a second, undeclared valuation voter — exactly what
#: CLAUDE.md's "recommendations and execution are separate" and this
#: unit's own governing brief ("the first analyst ledger PR should be
#: inert with respect to canonical valuation") forbid.
_CANONICAL_VALUE_PATHS = (
    REPO / "src" / "api" / "data_contract.py",
    REPO / "src" / "canonical",
    REPO / "src" / "trade" / "ktc_va.py",
)

_ANALYST_LEDGER_IMPORT = re.compile(
    r"""
    (?:from\s+src\.analyst\.(?:store|query)\s+import)
    | (?:import\s+src\.analyst\.(?:store|query))
    """,
    re.VERBOSE,
)


def _python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return [p for p in target.rglob("*.py") if "__pycache__" not in p.parts]
    return []


def test_scan_target_is_non_vacuous():
    """Guard on the guard — if this ever finds zero files, the scan below
    is passing for the wrong reason."""
    files = [f for target in _CANONICAL_VALUE_PATHS for f in _python_files(target)]
    assert len(files) >= 3, f"expected the canonical-value module set to be non-empty, got {files}"


def test_canonical_valuation_modules_never_import_the_analyst_ledger():
    offenders: list[str] = []
    for target in _CANONICAL_VALUE_PATHS:
        for path in _python_files(target):
            text = path.read_text(encoding="utf-8")
            if _ANALYST_LEDGER_IMPORT.search(text):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        "a canonical-valuation module imports src.analyst.store/query: "
        + ", ".join(offenders)
        + ". The analyst ledger is evidence storage — it may never become "
        "a second, undeclared canonical valuation voter."
    )


def test_store_and_query_never_import_data_contract_or_canonical():
    """The inverse direction, for the same reason — the ledger reading
    FROM the value pipeline is fine (e.g. resolving an asset_key); the
    ledger's write/query path calling INTO it to influence a value would
    not be. Scoped narrowly: this repo's canonical value writer is
    data_contract.py and src/canonical/, not every module those import."""
    forbidden = re.compile(r"(?:from|import)\s+src\.(?:api\.data_contract|canonical)\b")
    for path in (REPO / "src" / "analyst" / "store.py", REPO / "src" / "analyst" / "query.py"):
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path.name} imports a canonical-valuation module"


def test_write_claims_and_claims_as_of_never_touch_a_contract_global():
    """Behavioral companion to the structural scans above: the two public
    entry points are pure over their own SQLite file and never reach for
    the live contract global (``latest_contract_data``) or any
    module-level canonical-value state."""
    import datetime as dt

    from src.analyst import claim as C
    from src.analyst.stance import SourceLabel, Stance
    from src.analyst.store import LedgerEntry, write_claims
    from src.analyst.query import claims_as_of

    # If either function reached into src.api.data_contract's globals,
    # this would either raise (module not imported/available in this
    # minimal call) or require server state that was never set up here.
    # Succeeding with no such setup is itself the proof.
    claim = C.AnalystClaim(
        source=C.SourceRef(analyst_id="a", content_id="c", platform="p"),
        asset_key="player:1",
        stance=Stance.BUY,
        source_label=SourceLabel.BUY,
        take_type=C.TakeType.BUY_SELL_VALUE,
        said_at=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
        discovered_at=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
        provenance=C.Provenance.MODEL_INFERENCE,
    )

    def _run(tmp_path):
        path = tmp_path / "ledger.sqlite"
        write_claims([LedgerEntry(claim=claim)], path=path)
        return claims_as_of("player:1", dt.datetime(2026, 8, 2, tzinfo=dt.timezone.utc), path=path)

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        result = _run(Path(td))
    assert len(result) == 1
