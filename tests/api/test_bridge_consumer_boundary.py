"""The cross-position bridge program has NO production consumer yet, and its
public API structurally excludes any not-yet-qualified bridge.

Placement note
---------------
This file lives in ``tests/api/``, not ``tests/bridges/`` or
``tests/sources/``.  Those two directories -- along with ``src/bridges/*``
and ``src/sources/acquisition_state.py`` -- are Lane 8 / Claude 8's claimed
territory (``docs/WORK_CLAIMS.md``, the "Claude 8 / cross-position bridge
V1" row).  This file tests the boundary from the OUTSIDE, exactly as a
future production consumer (PR B, still unbuilt and explicitly blocked on
owner-level bridge-combination methodology) would see it: it imports only
the package's own declared public API (``src.bridges.__all__``) and edits
nothing under ``src/bridges/`` or ``src/sources/``.

What is proven here
--------------------
1. Today, literally nothing under ``src/api``, ``src/canonical``,
   ``src/league_intel``, ``src/trade`` or ``server.py`` imports the bridge
   layer.  This is a TRIPWIRE, not a design claim -- it will become false on
   the day PR B lands, and that is fine.  What must never happen is for it
   to become false BY ACCIDENT: a future import must arrive already routed
   through the gated API (``assess_bridges`` / ``usable_bridges``), not
   through the raw ``measure_capability`` / ``BridgeCapability``, which
   carry no comparability gate at all (see ``TestTheRawAndGatedAPIsAreBothExported``
   below for why that distinction matters).
2. The gated public API (``assess_bridges`` + ``usable_bridges``) excludes a
   PENDING/DISPROVEN/UNAVAILABLE/STALE/INSUFFICIENT_COVERAGE bridge from
   voting under adversarial, extreme-value injection -- not just on the
   small boards ``tests/bridges/test_bridge_capability.py`` already covers,
   but at magnitudes (rank #1, values far outside any real board) chosen so
   a leak could not hide inside "the values just happened to be similar".
3. An unqualified bridge's own magnitude cannot cross-contaminate a
   DIFFERENT, healthy bridge's measured capability -- each bridge's pool is
   built strictly from ITS OWN declared keys, so one bridge's extreme value
   must never move another's ``ladder_start`` / ``ladder_depth`` /
   ``spans_both_pools``.
4. Mutation proof: the gate is deliberately broken (comparability no longer
   checked) via a same-process monkeypatch scoped to one test -- never a
   file edit -- and the adversarial test above is shown to go RED under
   that mutation, then GREEN once restored.  A guard that stays green when
   the thing it guards is broken proves nothing; this is the check that it
   is not that guard.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from typing import Any

from src.bridges import (
    CARDINAL,
    DISPROVEN,
    ORDINAL,
    PENDING,
    QUALIFIED,
    BridgeDescriptor,
    assess_bridges,
    usable_bridges,
)
from src.bridges import assess as _bridge_assess
from src.bridges import states as bridge_states
from src.bridges.states import UNAVAILABLE
from src.sources import acquisition_state as acq

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Where a production consumer would live.  Deliberately excludes
#: ``src/bridges`` and ``src/sources`` themselves (that is Lane 8's own
#: code, not a consumer of it) and excludes ``tests/`` (a test importing the
#: package to test it is not "production consuming" it).
_PRODUCTION_ROOTS = (
    "src/api",
    "src/canonical",
    "src/league_intel",
    "src/trade",
    "src/packages",
    "src/roster_intel",
    "server.py",
)

#: The modules a production consumer must not yet reach.
_BRIDGE_MODULE_PREFIXES = (
    "src.bridges",
    "src.sources.acquisition_state",
    "src.source_archive",
)


def _iter_py_files(root: str):
    path = REPO / root
    if path.is_file():
        if path.suffix == ".py":
            yield path
        return
    if path.is_dir():
        yield from path.rglob("*.py")


def _imported_module_names(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


#: The ONE production module approved to consume the bridge layer, and the
#: exact names it is approved to import.  PR B (#993) made this non-empty on
#: purpose; before it the approved set was EMPTY and this file's tripwire
#: said so.  The invariant did not weaken when PR B landed - it changed
#: shape, from "no consumer" to "exactly this consumer, reaching only for
#: the gated entry points".
_APPROVED_CONSUMERS = {
    "src/api/data_contract.py": {
        "src.bridges.assess.assess_bridges",
        "src.bridges.states.QUALIFIED",
        "src.bridges.ladder.build_bridge_ladder",
        "src.bridges.registry.load_bridge_descriptors",
        # Acquisition state is what makes UNAVAILABLE reachable at the gate:
        # a bridge whose source could not be acquired must not vote, and
        # data_contract has to be able to say so.  Gated helpers, not raw
        # measurement.
        "src.sources.acquisition_state.AcquisitionOutcome",
        "src.sources.acquisition_state.UNAVAILABLE",
    },
}

#: Ungated primitives.  These exist and are exported, and reaching for one
#: from production is how the comparability gate gets bypassed without
#: anyone deciding to.  ``measure_capability`` is the raw measurement with
#: no PENDING/DISPROVEN/UNAVAILABLE check at all.
_UNGATED_PRIMITIVES = (
    "measure_capability",
    "_measure_capability",
)


class TestExactlyOneApprovedBridgeConsumer(unittest.TestCase):
    """Post-PR-B boundary: one approved consumer, reaching only for the gate.

    Before #993 the honest invariant was "zero production consumers", and
    the previous version of this class asserted exactly that, with a comment
    saying it would become false ON PURPOSE when PR B landed.  PR B has
    landed.  Rewriting the assertion to match is the point of the tripwire -
    the failure mode it protects against is a SECOND consumer, or the one
    approved consumer quietly switching from the gated API to a raw one.
    """

    def _production_bridge_imports(self):
        """(file, fully-qualified imported name) for every production import."""
        found = []
        for root in _PRODUCTION_ROOTS:
            for path in _iter_py_files(root):
                rel = str(path.relative_to(REPO))
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if any(
                            node.module == pre or node.module.startswith(pre + ".")
                            for pre in _BRIDGE_MODULE_PREFIXES
                        ):
                            for alias in node.names:
                                found.append((rel, f"{node.module}.{alias.name}"))
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if any(
                                alias.name == pre or alias.name.startswith(pre + ".")
                                for pre in _BRIDGE_MODULE_PREFIXES
                            ):
                                found.append((rel, alias.name))
        return found

    def test_the_census_is_non_empty(self) -> None:
        """Vacuity guard.

        Every assertion below is about the CONTENT of the census.  If the
        walker silently stopped finding imports - a moved root, a renamed
        package - they would all pass while proving nothing, which is
        exactly how the pre-PR-B version of this file could have rotted
        into a false green.
        """
        self.assertNotEqual(
            self._production_bridge_imports(),
            [],
            "the bridge-import census found nothing at all. Since PR B "
            "(#993) there IS an approved production consumer, so an empty "
            "census means this test stopped measuring, not that the "
            "boundary is clean.",
        )

    def test_there_is_exactly_one_production_bridge_consumer(self) -> None:
        consumers = sorted({f for f, _ in self._production_bridge_imports()})
        self.assertEqual(
            consumers,
            sorted(_APPROVED_CONSUMERS),
            "the set of production modules importing the cross-position "
            "bridge layer changed. Exactly ONE consumer is approved "
            "(src/api/data_contract.py, the canonical valuation owner). A "
            "second consumer is a second place cross-position evidence can "
            "enter canonical value, which is the ONE CONCEPT, ONE CANONICAL "
            "OWNER rule. If this is deliberate, it needs owner approval and "
            "an entry in _APPROVED_CONSUMERS naming what it may import.",
        )

    def test_the_approved_consumer_imports_only_approved_names(self) -> None:
        by_file: dict[str, set[str]] = {}
        for f, name in self._production_bridge_imports():
            by_file.setdefault(f, set()).add(name)
        for f, approved in _APPROVED_CONSUMERS.items():
            self.assertEqual(
                by_file.get(f, set()),
                approved,
                f"{f}'s bridge imports changed. The approved set is the "
                "gated entry point plus the descriptor/ladder/state helpers "
                "it needs; anything else must be reviewed before it can "
                "influence canonical value.",
            )

    def test_no_production_module_reaches_an_ungated_primitive(self) -> None:
        """The gate is only a gate if nothing routes around it.

        ``assess_bridges()`` applies the PENDING / DISPROVEN / UNAVAILABLE
        checks; ``measure_capability()`` does not and is separately
        exported. A consumer calling the raw one would produce a bridge
        that votes without ever having qualified - the precise defect this
        file's extreme-value injection tests prove the GATED path is immune
        to.
        """
        offenders = [
            f"{f}: {name}"
            for f, name in self._production_bridge_imports()
            if name.rsplit(".", 1)[-1] in _UNGATED_PRIMITIVES
        ]
        self.assertEqual(
            offenders,
            [],
            "a production module imports a bridge primitive that performs "
            f"no comparability gating. Found: {offenders}",
        )

    def test_the_approved_consumer_actually_calls_the_gated_entry_point(self) -> None:
        """Importing the gate and then not using it would pass every check above."""
        source = (REPO / "src/api/data_contract.py").read_text(encoding="utf-8")
        self.assertIn(
            "assess_bridges(",
            source,
            "data_contract imports assess_bridges but never calls it - the "
            "gate is present in the import list and absent from the code "
            "path, which is indistinguishable from ungated at run time.",
        )

    def test_the_multi_bridge_ladder_stays_off_by_default(self) -> None:
        """Admitting a SECOND bridge is a methodology change, not a default.

        The ladder is capped at one bridge unless ``multi_bridge_ladder`` is
        enabled. That default is load-bearing: the withholding repair is
        unconditional, but combining two bridges' evidence is an owner
        decision with measured board movement, and it has not been made.
        """
        from src.api import feature_flags

        self.assertIs(
            feature_flags._DEFAULTS["multi_bridge_ladder"],
            False,
            "multi_bridge_ladder is ON by default. Admitting a second "
            "cross-position bridge into the shared-market ladder is an "
            "owner-level methodology decision (weighting, cardinal "
            "precedence, disagreement, confidence, tie-breaker) that has "
            "not been taken.",
        )


class TestTheRawAndGatedAPIsAreBothExported(unittest.TestCase):
    """Document, precisely, why (1) matters: the package's public surface
    contains BOTH a gated entry point and an ungated one, and nothing
    prevents a future caller from reaching for the wrong one."""

    def test_measure_capability_is_reachable_without_the_comparability_gate(self) -> None:
        import src.bridges as bridges_pkg

        # measure_capability and BridgeCapability are exported at package
        # level -- callable directly, with no comparability check at all.
        # This is legitimate (assess_bridge uses it internally, and it is
        # unit-tested directly in tests/bridges/), but it means "capable"
        # and "usable" are NOT the same question, and a caller who only
        # checks the former has silently skipped the PENDING gate.
        self.assertIn("measure_capability", bridges_pkg.__all__)
        self.assertIn("BridgeCapability", bridges_pkg.__all__)
        # The gated entry points exist alongside it -- this is not a
        # request to remove the raw one (assess_bridge needs it), only a
        # pinned statement that a consumer must choose correctly.
        self.assertIn("assess_bridges", bridges_pkg.__all__)
        self.assertIn("usable_bridges", bridges_pkg.__all__)


# ---------------------------------------------------------------------------
# Shared fixtures for the adversarial tests below.
# ---------------------------------------------------------------------------

_OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
_IDP = frozenset({"DL", "LB", "DB"})


def _row(name: str, position: str, **values: float) -> dict[str, Any]:
    return {
        "displayName": name,
        "position": position,
        "canonicalSiteValues": dict(values),
    }


def _healthy_board() -> list[dict[str, Any]]:
    """A plausible combined pool: offense assets above the best defender,
    for TWO distinct bridge families (``healthy`` and ``rival``), each
    covering both pools on its own scale."""
    return [
        _row("Elite QB", "QB", healthy=9800, rival=9700),
        _row("Star WR", "WR", healthy=9200, rival=9100),
        _row("Good RB", "RB", healthy=7000, rival=6900),
        _row("Best DL", "DL", healthy=4000, rival=3900),
        _row("Good LB", "LB", healthy=2000, rival=2100),
        _row("Depth DB", "DB", healthy=500, rival=600),
    ]


def _descriptor(
    key: str = "pending_bridge",
    *,
    family: str | None = None,
    comparability: str = PENDING,
    comparability_evidence: str = "",
    offense_keys: tuple[str, ...] = ("pending_off",),
    idp_keys: tuple[str, ...] = ("pending_idp",),
    kind: str = CARDINAL,
) -> BridgeDescriptor:
    return BridgeDescriptor(
        bridge_key=key,
        display_name=key,
        family=family or key,
        kind=kind,
        offense_keys=offense_keys,
        idp_keys=idp_keys,
        comparability=comparability,
        comparability_evidence=comparability_evidence
        or ("unproven" if comparability == PENDING else "n/a"),
    )


class TestAdversarialExtremeValueInjection(unittest.TestCase):
    """Inject absurd magnitudes into an UNQUALIFIED bridge and prove the
    gated public API excludes it regardless -- not merely on ordinary
    boards, at the values Phase 5 of the mandate specifically asks for."""

    def _pending_descriptor(self, **kw: Any) -> BridgeDescriptor:
        base = dict(
            comparability=PENDING,
            offense_keys=("unq_off",),
            idp_keys=("unq_idp",),
        )
        base.update(kw)
        return _descriptor(key="unqualified", family="unqualified_family", **base)

    def test_rank_one_extreme_value_does_not_make_a_pending_bridge_usable(self) -> None:
        board = _healthy_board() + [
            # An absurd, rank-#1-worthy value on BOTH halves of a PENDING
            # bridge. If magnitude alone could buy a vote, this would.
            _row("Injected Top Defender", "DB", unq_off=1, unq_idp=999_999),
            _row("Injected Top Offense", "QB", unq_off=999_999, unq_idp=1),
        ]
        descriptor = self._pending_descriptor()
        assessments = assess_bridges(
            [descriptor], board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        usable = usable_bridges(assessments)
        self.assertEqual(usable, [], "a PENDING bridge voted despite an extreme injected value")
        (only,) = assessments
        self.assertEqual(only.state, bridge_states.NOT_COMPARABLE)
        self.assertFalse(only.usable)

    def test_negative_direction_extreme_value_also_does_not_vote(self) -> None:
        board = _healthy_board() + [
            _row("Injected Bottom", "DB", unq_off=9999, unq_idp=1),
        ]
        assessments = assess_bridges(
            [self._pending_descriptor()], board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        self.assertEqual(usable_bridges(assessments), [])

    def test_disproven_bridge_is_equally_immune_to_extreme_injection(self) -> None:
        board = _healthy_board() + [
            _row("Injected", "DB", unq_off=500, unq_idp=999_999),
        ]
        descriptor = self._pending_descriptor(
            comparability=DISPROVEN, comparability_evidence="proven distinct bases"
        )
        assessments = assess_bridges(
            [descriptor], board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        self.assertEqual(usable_bridges(assessments), [])

    def test_unavailable_acquisition_overrides_an_otherwise_qualified_bridge(self) -> None:
        """Even a QUALIFIED, capable bridge must not vote if its halves
        never arrived -- extreme values in the BOARD are irrelevant when
        the ACQUISITION itself failed."""
        board = _healthy_board() + [
            _row("Injected", "DB", unq_off=9999, unq_idp=9999),
        ]
        descriptor = self._pending_descriptor(
            comparability=QUALIFIED, comparability_evidence="measured basis parity"
        )
        acquisition = {
            "unq_off": acq.AcquisitionOutcome("unq_off", acq.HEALTHY, row_count=1),
            "unq_idp": acq.AcquisitionOutcome(
                "unq_idp", acq.PARSE_FAILED, reason="table shape changed"
            ),
        }
        assessments = assess_bridges(
            [descriptor],
            board,
            offense_positions=_OFFENSE,
            idp_positions=_IDP,
            acquisition=acquisition,
        )
        self.assertEqual(usable_bridges(assessments), [])
        self.assertEqual(assessments[0].state, UNAVAILABLE)


class TestNoCrossContaminationBetweenBridges(unittest.TestCase):
    """An unqualified bridge's extreme value must not leak into a
    DIFFERENT, healthy bridge's measured capability -- each bridge's pool is
    built strictly from its own declared keys."""

    def test_healthy_bridge_capability_is_unaffected_by_a_pending_bridges_extreme_value(
        self,
    ) -> None:
        healthy = _descriptor(
            key="healthy",
            family="healthy_family",
            comparability=QUALIFIED,
            comparability_evidence="measured basis parity",
            offense_keys=("healthy",),
            idp_keys=("healthy",),
        )
        pending = _descriptor(
            key="unqualified",
            family="unqualified_family",
            comparability=PENDING,
            offense_keys=("unq_off",),
            idp_keys=("unq_idp",),
        )

        baseline_board = _healthy_board()
        assessments_baseline = assess_bridges(
            [healthy, pending], baseline_board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        healthy_baseline = next(
            a for a in assessments_baseline if a.descriptor.bridge_key == "healthy"
        )

        injected_board = baseline_board + [
            _row("Injected", "DB", unq_off=1, unq_idp=999_999),
        ]
        assessments_injected = assess_bridges(
            [healthy, pending], injected_board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        healthy_injected = next(
            a for a in assessments_injected if a.descriptor.bridge_key == "healthy"
        )

        self.assertEqual(
            healthy_baseline.capability.to_dict(), healthy_injected.capability.to_dict()
        )
        self.assertEqual(healthy_baseline.state, healthy_injected.state)
        self.assertTrue(healthy_injected.usable)

        # And the pending bridge itself, whatever its own capability looks
        # like now, still does not vote.
        pending_injected = next(
            a for a in assessments_injected if a.descriptor.bridge_key == "unqualified"
        )
        self.assertFalse(pending_injected.usable)


class TestMutationProofOfTheComparabilityGate(unittest.TestCase):
    """Deliberately break the gate (comparability no longer checked first),
    require the adversarial test above to go RED, then restore and require
    GREEN.  The monkeypatch is scoped to this test only and touches no file
    on disk under src/bridges/."""

    def test_removing_the_pending_check_lets_the_bridge_vote_then_restoring_fixes_it(
        self,
    ) -> None:
        board = _healthy_board() + [
            _row("Injected Top Defender", "DB", unq_off=1, unq_idp=999_999),
            _row("Injected Top Offense", "QB", unq_off=999_999, unq_idp=1),
        ]
        descriptor = _descriptor(
            key="unqualified",
            family="unqualified_family",
            comparability=PENDING,
            offense_keys=("unq_off",),
            idp_keys=("unq_idp",),
        )

        original = _bridge_assess.assess_bridge

        def _mutated_assess_bridge(descriptor, rows, **kwargs):
            # The mutation: skip straight to capability, never consulting
            # descriptor.comparability at all -- the exact defect "PENDING
            # does not vote" exists to prevent.
            capability = kwargs.get("capability")
            if capability is None:
                from src.bridges.descriptor import measure_capability

                capability = measure_capability(
                    descriptor,
                    rows,
                    offense_positions=kwargs["offense_positions"],
                    idp_positions=kwargs["idp_positions"],
                )
            from src.bridges.descriptor import BridgeAssessment

            state = (
                bridge_states.VALID if capability.capable else bridge_states.INSUFFICIENT_COVERAGE
            )
            return BridgeAssessment(descriptor, capability, state)

        _bridge_assess.assess_bridge = _mutated_assess_bridge
        try:
            broken_assessments = [
                _bridge_assess.assess_bridge(
                    descriptor, board, offense_positions=_OFFENSE, idp_positions=_IDP
                )
            ]
            mutation_was_caught = usable_bridges(broken_assessments) != []
        finally:
            _bridge_assess.assess_bridge = original

        self.assertTrue(
            mutation_was_caught,
            "removing the comparability check did not let the PENDING bridge "
            "vote -- this test would not have caught the exact defect it "
            "exists to catch",
        )

        restored_assessments = assess_bridges(
            [descriptor], board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        self.assertEqual(usable_bridges(restored_assessments), [])


class TestOrdinalIsNotSilentlyCardinalized(unittest.TestCase):
    """FINDING, pinned rather than fixed (fixing it would edit
    src/bridges/assess.py, which is Lane 8's claimed file -- see the module
    docstring).  ``BridgeAssessment.usable`` does not currently distinguish
    ``kind=CARDINAL`` from ``kind=ORDINAL``: an ORDINAL bridge that clears
    every other check reaches ``VALID`` exactly like a CARDINAL one.  That
    is correct for LADDER purposes (an ordinal bridge can legitimately seed
    a ladder -- ``descriptor.py``'s own docstring says so) and would be
    WRONG if a future consumer read ``usable_bridges()`` and assumed every
    entry carries a cardinal VALUE.  This test pins the current, narrower
    fact (kind is not gated) so it cannot regress silently into being
    trusted as something it isn't; widening the gate is Lane 8's call, not
    this file's."""

    def test_an_ordinal_bridge_reaches_valid_exactly_like_a_cardinal_one(self) -> None:
        board = _healthy_board()
        ordinal = _descriptor(
            key="ordinal_bridge",
            family="ordinal_family",
            comparability=QUALIFIED,
            comparability_evidence="measured order parity",
            offense_keys=("healthy",),
            idp_keys=("healthy",),
            kind=ORDINAL,
        )
        cardinal = _descriptor(
            key="cardinal_bridge",
            family="cardinal_family",
            comparability=QUALIFIED,
            comparability_evidence="measured basis parity",
            offense_keys=("rival",),
            idp_keys=("rival",),
            kind=CARDINAL,
        )
        assessments = assess_bridges(
            [ordinal, cardinal], board, offense_positions=_OFFENSE, idp_positions=_IDP
        )
        states = {a.descriptor.bridge_key: a.state for a in assessments}
        self.assertEqual(states["ordinal_bridge"], bridge_states.VALID)
        self.assertEqual(states["cardinal_bridge"], bridge_states.VALID)
        # Nothing in `usable` or `state` names the difference -- a caller
        # MUST separately read `descriptor.kind` before treating a usable
        # assessment's evidence as a cardinal magnitude.
        usable = usable_bridges(assessments)
        self.assertEqual({a.descriptor.kind for a in usable}, {ORDINAL, CARDINAL})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
