"""V1-36 / C3-PKG-01 — single-owner discovery guard for package-generation MECHANICS.

Scope, and why it is drawn this way: the market-value trade-recommendation
surfaces (``src/trade/``, ``src/roster_intel/``) are ONE domain sharing ONE
canonical asset-value scale (``rankDerivedValue``), and it is that domain
this guard protects — a second combinatorial two-sided-package enumerator
appearing anywhere in it, other than the one documented exception below,
is the exact defect class C3-PKG-01 exists to prevent.

Current census (2026-08-22), performed fresh rather than trusted from the
manifest:

* ``src/trade/finder.py`` and ``src/trade/angle.py`` call the owner's own
  ``enumerate_packages`` / ``enumerate_sides`` directly — consolidated.
* ``src/roster_intel/packages.py::generate_packages`` is a DIFFERENT,
  documented, deliberately-separate staged Pareto-frontier search (its own
  ``max_candidates_per_stage`` budget, no ``itertools.combinations``, no
  topology-bound check) — it imports only the owner's identity primitives
  (``PackageAsset``, ``package_key``) plus the shared ``src.trade.constraints``
  outgoing-constraint owner. Allowlisted by name below, not exempted from
  scanning silently.
* ``src/trade/suggestions.py``'s four ``_generate_*`` functions are
  needs-driven heuristic searches (weakest-starter, sweetener-widening,
  tightest-gap dedup) with hardcoded 1-for-1 / 2-for-1 shapes — no
  ``itertools.combinations``, no explicit topology-bound comparison. NOT
  migrated by this unit: see ``docs/WORK_CLAIMS.md``'s V1-36 row for why a
  mechanics-only migration here is either inert (the one clean slice,
  ``MIN_RELEVANT_VALUE``, is a bare numeric threshold already identical to
  the owner's ``EligibilityPolicy.min_value`` and moves nothing measurable)
  or requires resolving the recorded deferred owner-policy decision in
  ``_generate_consolidation`` (the IDP-exclusion-for-offense-only-pairs
  rule) along the way — reported to Claude 5 rather than decided here.
* ``src/bdvm/roster.py`` also builds ``itertools.combinations``-based 2-sided
  trade shapes (``find_double_positive_trades``), but it is BDVM's
  fundamental-value double-positive scan — a second, INDEPENDENT value
  concept by explicit design (see ``CLAUDE.md``'s BDVM section: "never
  touches ``rankDerivedValue``", "additive... never touches an existing
  route"). Out of this guard's scope by directory (``src/bdvm/``), not by
  a silently broadened allowlist.

The signature scanned for — ``itertools.combinations`` co-occurring with an
explicit player-count-difference bound (``abs(...) <= N``) inside one
function — is deliberately narrow: broad enough to catch a real
reimplementation of the owner's enumerate-plus-topology mechanics, narrow
enough not to flag ``src/roster_intel/packages.py``'s different search or
unrelated ``combinations()`` uses elsewhere in the scanned trees.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MECHANICS_OWNER = "src/packages/construction.py"
_SCAN_ROOTS = ("src/trade", "src/roster_intel")
#: Documented, deliberately-separate generators — not exemptions from being
#: scanned, exemptions from being COUNTED as a mechanics duplicate.
_KNOWN_SEPARATE_GENERATORS = frozenset({"src/roster_intel/packages.py"})

_TOPOLOGY_BOUND_PATTERN = re.compile(r"abs\([^)]*\)\s*<=\s*\d")


def _find_mechanics_offenders() -> list[str]:
    """Module-level co-occurrence, not per-function: the owner itself splits
    enumeration (``enumerate_packages``/``enumerate_sides``, which call
    ``itertools.combinations``) and the topology bound
    (``topology_is_allowed``, a separate function) across two functions in
    one file — a per-function AND would miss the owner's own pattern. A
    reimplementation elsewhere is no less a duplicate for structuring itself
    the same tidy way, so the signature is scoped to the file."""
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        for path in sorted((_REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel == _MECHANICS_OWNER or rel in _KNOWN_SEPARATE_GENERATORS:
                continue
            text = path.read_text(encoding="utf-8")
            uses_combinations = "combinations(" in text
            has_topology_bound = bool(_TOPOLOGY_BOUND_PATTERN.search(text))
            if uses_combinations and has_topology_bound:
                offenders.append(rel)
    return offenders


def test_there_is_exactly_one_package_mechanics_owner():
    """No file in the trade-recommendation surfaces, other than the one
    documented exception, both enumerates asset combinations AND enforces a
    topology (player-count-difference) bound — that pairing is the owner's
    own signature (``enumerate_packages`` / ``enumerate_sides`` +
    ``topology_is_allowed`` / ``MAX_PLAYER_COUNT_DIFFERENCE``)."""
    offenders = _find_mechanics_offenders()
    assert not offenders, (
        f"second package-generation mechanics implementation found outside "
        f"src/packages/construction.py: {offenders} — route through "
        f"src.packages.enumerate_packages / enumerate_sides instead, or add "
        f"a documented exception to _KNOWN_SEPARATE_GENERATORS with a reason"
    )


def test_the_guard_is_not_vacuous_against_the_owner_itself():
    """Sanity check on the detector: the owner file itself DOES contain the
    scanned-for signature (it is where enumerate-plus-topology mechanics
    legitimately live) — proving the scan can find a positive, not just
    return an empty list because the pattern never matches anything."""
    text = (_REPO_ROOT / _MECHANICS_OWNER).read_text(encoding="utf-8")
    assert "combinations(" in text and _TOPOLOGY_BOUND_PATTERN.search(text), (
        "the detector pattern (itertools.combinations + an abs(...)<=N "
        "topology bound somewhere in the same file) does not match the "
        "owner file — the guard would pass vacuously"
    )
