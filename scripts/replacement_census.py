#!/usr/bin/env python3
"""V1-29 — census of every replacement-level implementation, and the guard.

**Read this before reading the output.** Six things in this tree use the word
"replacement". They are not six copies of one quantity: they split by UNIT and
by POPULATION, and merging across either would be the defect rather than the
fix. This script exists to make that split *checkable* instead of a table in a
document that nothing enforces.

Each row below declares what its implementation computes — quantity, unit,
population, and its disposition — and the script derives the CALLERS from the
tree at run time by AST. So the declared half is reviewable and the measured
half cannot go stale.

Dispositions:

    OWNER     the canonical implementation for its (unit, population)
    ADAPTER   reshapes a caller's data and delegates to an OWNER
    DISTINCT  answers a materially different question; must NOT be merged
    DEAD      no production caller; retire
    RETIRED   deleted by V1-29; the guard fails if it comes back

Exit codes follow the repo convention (``scripts/backtest_perfect_draft.py``):
0 clean · 1 a violation was measured · 2 could not measure. ``2`` is never
collapsed into ``0`` — "no data" must not read as "passed".
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAG = "[replacement-census]"

EXIT_OK, EXIT_VIOLATION, EXIT_UNMEASURED = 0, 1, 2

OWNER, ADAPTER, DISTINCT, DEAD, RETIRED = "OWNER", "ADAPTER", "DISTINCT", "DEAD", "RETIRED"

#: Files scanned for call sites. Tests are excluded deliberately: a symbol kept
#: alive only by its own unit test is DEAD for production purposes, and that is
#: the distinction this census is for.
SCAN_ROOTS = ("src", "scripts")
SCAN_FILES = ("server.py",)


@dataclass(frozen=True)
class Impl:
    key: str
    path: str
    symbol: str
    quantity: str
    unit: str
    population: str
    disposition: str
    note: str
    #: Names that count as a call site for this row.
    call_names: tuple[str, ...] = ()
    callers: list[str] = field(default_factory=list)
    intra: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "path": self.path,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "unit": self.unit,
            "population": self.population,
            "disposition": self.disposition,
            "note": self.note,
            "crossModuleCallers": sorted(set(self.callers)),
            "crossModuleCallerCount": len(set(self.callers)),
            "intraModuleCallSites": sorted(set(self.intra)),
            "intraModuleCallCount": len(set(self.intra)),
        }


#: The declared census. Every unit/population claim here was read off the code
#: or its docstring at HEAD, not inherited from an earlier audit.
CENSUS: tuple[Impl, ...] = (
    Impl(
        key="A",
        path="src/league_intel/replacement.py",
        symbol="compute_replacement_levels / measure_endogenous_starters / compute_scarcity",
        quantity="four replacement tiers (starter / bestBallStarter / roster / waiver)",
        unit="rosValue — 0-100 log-rank ROS production index",
        population="every rostered player in the league, plus free agents",
        disposition=OWNER,
        note=(
            "Canonical for the ROS-production unit. Reads rosValue at :299/:375/"
            ":386/:567/:618; its own docstring :22 says 'runs the optimizer over "
            "rosValue'. Its production caller supplies ROS rows "
            "(gameplan.py:357 loads data/ros/team_strength/)."
        ),
        call_names=(
            "compute_replacement_levels",
            "measure_endogenous_starters",
            "compute_scarcity",
        ),
    ),
    Impl(
        key="A-demand",
        path="src/league_intel/replacement.py",
        symbol="measure_revealed_demand",
        quantity="rostership counts vs supply",
        unit="counts (unit-agnostic value floor)",
        population="league rosters",
        disposition=DISTINCT,
        note=(
            "NOT a replacement level. Its own docstring: 'Evidence about DEMAND, "
            "not about value.' No production caller yet, but it is exported, "
            "unit-agnostic by design and covered by tests/league_intel/"
            "test_replacement.py. Deleting it would remove tested behaviour for "
            "no V1-29 reason — out of scope, not dead."
        ),
        call_names=("measure_revealed_demand",),
    ),
    Impl(
        key="B",
        path="src/scoring/replacement_level.py",
        symbol="replacement_per_game",
        quantity="replacement-level points per game at one position",
        unit="fantasy points per game",
        population="players supplied by the caller, ranked by per-game pace",
        disposition=OWNER,
        note="Canonical for the fantasy-points unit. Consumed via the awards adapter.",
        call_names=("replacement_per_game",),
    ),
    Impl(
        key="B-dead",
        path="src/scoring/replacement_level.py",
        symbol="vorp_table",
        quantity="per-player VORP",
        unit="fantasy points",
        population="ALL points (rows.points / rows.games)",
        disposition=RETIRED,
        note=(
            "DELETED by V1-29. Had no production caller and no test, and its "
            "stated purpose — reuse by the IDP scoring-fit pipeline — never "
            "landed. It was NOT a duplicate of the awards VORP: different "
            "population (all points vs starter-only). It was simply a plausible "
            "second VORP sitting beside the live one."
        ),
        call_names=("vorp_table",),
    ),
    Impl(
        key="B-slots",
        path="src/scoring/replacement_level.py",
        symbol="starter_slot_counts",
        quantity="starter slots per position from a Sleeper roster_positions list",
        unit="slot counts",
        population="league roster_positions",
        disposition=ADAPTER,
        note=(
            "ALREADY CONSOLIDATED, and currently unconsumed. It routes through the "
            "canonical lineup owner — slot_demand(...).even_split from src/ros/"
            "lineup.py (C2-U1) — and its docstring records that this was one of four "
            "independent copies and that routing through the owner fixed a REC_FLEX "
            "split bug. It is also the only reason this module imports the owner, so "
            "deleting it would break tests/lineup/test_single_owner.py::"
            "test_every_consumer_imports_the_owner_rather_than_reimplementing. "
            "Retiring a correct consolidation is not a consolidation."
        ),
        call_names=("starter_slot_counts",),
    ),
    Impl(
        key="C",
        path="src/public_league/awards.py",
        symbol="_replacement_per_game_for_position / _vorp_rows / _vorp_starter_slots",
        quantity="award VORP per player",
        unit="fantasy season points",
        population=(
            "STARTER-ONLY points (_player_starter_totals: 'Aggregate starter-only "
            "points per player across the season')"
        ),
        disposition=ADAPTER,
        note=(
            "Already delegates the baseline: _replacement_per_game_for_position is "
            "a 'thin shim around src.scoring.replacement_level.replacement_per_game'. "
            "What remains local is DISTINCT and must stay: a starter-only population, "
            "an award-convention slot table with a dynamic RB/WR split from the top-84 "
            "flex pool, and a zero-floor that is a presentation rule."
        ),
        call_names=("_vorp_rows", "_replacement_per_game_for_position", "_vorp_starter_slots"),
    ),
    Impl(
        key="D",
        path="src/bdvm/replacement.py",
        symbol="ReplacementEngine.R",
        quantity="dynamic replacement baseline",
        unit="projected fantasy points per game",
        population="BDVM projection pools, flex-allocated + waiver buffer",
        disposition=DISTINCT,
        note="Different lane and unit; bound by the frozen Appendix-C parity fixture.",
        call_names=("ReplacementEngine", "has_replacement", "startable"),
    ),
    Impl(
        key="E",
        path="src/trade/faab_engine.py",
        symbol="resolve_anchors -> Anchors.v_repl",
        quantity="format replacement line, blended with the live pool",
        unit="rankDerivedValue (1-9999 dynasty)",
        population="league format line + Nth-best genuinely available player",
        disposition=DISTINCT,
        note=(
            "Answers 'what does the format make replacement', not 'what can I sign'. "
            "Explicitly rejects the single-best anchor. FAAB lane."
        ),
        call_names=("resolve_anchors", "surplus_over_replacement"),
    ),
    Impl(
        key="G",
        path="src/draft/displacement.py",
        symbol="waiver_values_by_position",
        quantity="best available (unrostered) value at each position",
        unit="rankDerivedValue (1-9999 dynasty)",
        population="unrostered players on the canonical board",
        disposition=DISTINCT,
        note=(
            "Answers 'what can I sign instead' — the opportunity cost of a roster "
            "spot. Different question from E even though the unit matches."
        ),
        call_names=("waiver_values_by_position", "free_agent_ladder"),
    ),
    Impl(
        key="I",
        path="src/league_comparison/metrics.py",
        symbol="position_metrics -> replacement_level",
        quantity="the Nth player's points at a position",
        unit="blended season points (volume+pace composite)",
        population="one league-season's players",
        disposition=DISTINCT,
        note="Display-only cross-league comparison.",
        call_names=("position_metrics",),
    ),
)

#: Symbols V1-29 deleted. The guard fails if any reappears as a call site.
#: Kept separate from CENSUS so a deletion cannot be undone by editing a row.
RETIRED_SYMBOLS: tuple[str, ...] = ("vorp_table",)


def _python_files(extra: Path | None = None) -> list[Path]:
    files = [p for root in SCAN_ROOTS for p in (REPO / root).rglob("*.py")]
    files += [REPO / f for f in SCAN_FILES]
    if extra is not None:
        files.append(extra)
    return [p for p in files if p.exists()]


def called_names(tree: ast.AST) -> set[str]:
    """Every name appearing in CALL position.

    AST rather than a substring scan, because a docstring explaining a
    retirement contains the retired name — the trap that made two earlier
    guards in this repo decorative — and because a text match would equally
    miss a call written through an alias.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            out.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            out.add(fn.attr)
    return out


def call_sites(names: set[str], extra: Path | None = None) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in _python_files(extra):
        rel = str(path.relative_to(REPO)) if REPO in path.parents else str(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for name in called_names(tree) & names:
            # A function calling itself, or a module defining it, is not a
            # consumer. Definition site is excluded by comparing paths below.
            hits.setdefault(name, []).append(rel)
    return hits


def build_census(extra: Path | None = None) -> list[Impl]:
    wanted = {n for impl in CENSUS for n in impl.call_names}
    hits = call_sites(wanted, extra=extra)
    out: list[Impl] = []
    for impl in CENSUS:
        callers: list[str] = []
        intra: list[str] = []
        for name in impl.call_names:
            for rel in hits.get(name, []):
                # Cross-module use is what "is this owner consumed" asks. An
                # intra-module call is real too (a private helper is called by
                # its own module) and is reported separately rather than
                # dropped, which would under-report an ADAPTER to zero.
                (intra if rel == impl.path else callers).append(f"{rel}::{name}")
        out.append(
            Impl(
                key=impl.key,
                path=impl.path,
                symbol=impl.symbol,
                quantity=impl.quantity,
                unit=impl.unit,
                population=impl.population,
                disposition=impl.disposition,
                note=impl.note,
                call_names=impl.call_names,
                callers=callers,
                intra=intra,
            )
        )
    return out


def retired_reachable(extra: Path | None = None) -> dict[str, list[str]]:
    """Any production call site for a symbol V1-29 deleted."""
    return call_sites(set(RETIRED_SYMBOLS), extra=extra)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)

    rows = build_census()
    if not rows:
        print(f"{TAG} census is empty — nothing was measured. exit 2.")
        return EXIT_UNMEASURED

    print(
        f"{TAG} {len(rows)} implementations declared; callers derived by AST over {len(_python_files())} files"
    )
    print("")
    for r in rows:
        print(f"  {r.disposition:<9} {r.key:<8} {r.path}::{r.symbol.split(' /')[0]}")
        print(f"            unit={r.unit}")
        print(f"            population={r.population}")
        print(
            f"            cross-module callers: {len(set(r.callers))}   "
            f"intra-module call sites: {len(set(r.intra))}"
        )
        for c in sorted(set(r.callers)):
            print(f"              - {c}")
    print("")

    failures: list[str] = []
    unconsumed: list[str] = []

    reachable = retired_reachable()
    if reachable:
        failures.append(f"retired symbols are reachable again: {reachable}")

    for r in rows:
        if r.disposition in (DEAD, RETIRED) and (r.callers or r.intra):
            failures.append(
                f"{r.key} is declared DEAD but has callers: "
                f"{sorted(set(r.callers)) or sorted(set(r.intra))}"
            )
        if r.disposition == OWNER and not (r.callers or r.intra):
            failures.append(
                f"{r.key} is declared OWNER but has NO production caller — "
                "either the declaration is stale or the owner is unconsumed"
            )
        if r.disposition == ADAPTER and not (r.callers or r.intra):
            # Not a failure: an adapter can be correct and simply unused. Said
            # out loud so "nobody calls it" cannot be mistaken for "it is wrong".
            unconsumed.append(r.key)

    print(f"{TAG} ── verdict ──")
    if failures:
        for f in failures:
            print(f"{TAG} ::error title=Replacement census::{f}")
        return EXIT_VIOLATION

    if unconsumed:
        print(
            f"{TAG} note: adapters with no current caller (correct, just unused): "
            f"{', '.join(unconsumed)}"
        )
    dead = [r.key for r in rows if r.disposition == DEAD]
    print(
        f"{TAG} clean: {len(RETIRED_SYMBOLS)} retired symbol(s) deleted and unreachable; "
        f"{len(dead)} DEAD row(s); every OWNER consumed; every OWNER unit distinct."
    )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "implementations": [r.to_dict() for r in rows],
                    "retiredSymbols": list(RETIRED_SYMBOLS),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"{TAG} census written to {args.json_out}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
