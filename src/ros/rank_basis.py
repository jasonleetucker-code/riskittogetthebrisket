"""Rank-basis diagnostics for ROS source rows — REPORTING ONLY.

``rank_to_score`` (``src/ros/parse.py``) turns a row's ``(rank,
total_ranked)`` into a 0-100 score, so a rank only means something
relative to the POPULATION it was ranked within — its *rank basis*.  Rank
12 of a 250-row all-positions board and rank 12 of a 440-row IDP-only
board are different statements, and the aggregate cannot tell them apart.

That is the class of defect this module detects.  On 2026-09-16
(``907dfee4d``, an automated refresh) the vendor's DraftSharks superflex
ROS board stopped listing IDP players.  The adapter then filled the IDP
group entirely from the vendor's IDP-only board, still under the one
``draftSharksRosSf`` key, and the top LB's DraftSharks score went from
30.3 (rank 47 of 250, all positions) to 100.0 (rank 1 of 440, IDP only)
with no change to any code and nothing in any status report.

Two questions, both answered per refresh and published in the source's
``data/ros/runs/index.json`` entry (and so ``/api/ros/status`` and
``/api/ros/health``):

* **Does one source mix rank bases?**  ``mixedRankBasis`` /
  ``groupsSplitAcrossBases``.  A source should rank every row on ONE
  basis; a position group ranked on two bases inside one source is the
  sharpest form (its rows are not even ordered consistently).
* **Did a group's coverage or basis change since the last refresh?**
  ``groupCoverageVanished`` / ``groupRankBasisChanged``.  This is the
  907dfee4d signature, and it is invisible to a row count: the source's
  total IDP coverage barely moved; only the basis under it did.

A third question is answered from what the ADAPTER states: does a key carry
a position group another key of the same vendor serves
(``cross_key_family_overlap:<G>``, from the adapter's
``groupsServedByOtherKey``), and did the adapter withhold rows because they
sat on another basis (``rows_withheld:rank_basis_mismatch``)?  Either is the
pre-907dfee4d shape -- one vendor's group split across two keys -- returning.

A row states its basis with ``rankBasis`` (an adapter-chosen board id).
A row that states none is grouped by ``total_ranked`` — each adapter
stamps one ``total_ranked`` per board, so that is the board identity the
scoring itself uses — and the report says ``basisDeclared: false``.

Nothing here changes a row, a weight or a value.  ``issues`` is a list of
stable machine strings; an empty list is a measured "no issue", never a
default.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from src.utils.name_clean import canonical_position_group

#: Issue codes (stable strings — consumers may key on them).
MIXED_RANK_BASIS = "mixed_rank_basis"
GROUP_SPLIT_ACROSS_BASES = "group_split_across_rank_bases"
GROUP_COVERAGE_VANISHED = "group_coverage_vanished"
GROUP_RANK_BASIS_CHANGED = "group_rank_basis_changed"

#: A position group appeared on a key while the adapter states another key
#: of the same vendor serves that group (``groupsServedByOtherKey``), i.e.
#: the vendor's group is split across two keys on two rank bases.
CROSS_KEY_FAMILY_OVERLAP = "cross_key_family_overlap"
#: An adapter withheld rows for a reason worth surfacing (see
#: :data:`SURFACED_WITHHELD_REASONS`): ``rows_withheld:<reason>``.
ROWS_WITHHELD = "rows_withheld"

#: Reason an adapter withheld rows rather than mixing bases.
RANK_BASIS_MISMATCH = "rank_basis_mismatch"

#: Withheld reasons that raise an issue when their count is positive.  A
#: ``rank_basis_mismatch`` withholding means another key of the same vendor
#: is ranking this key's group on a different basis -- the signature of the
#: pre-907dfee4d board shape returning.
SURFACED_WITHHELD_REASONS: tuple[str, ...] = (RANK_BASIS_MISMATCH,)


def _row_basis(row: Mapping[str, Any]) -> tuple[str, bool]:
    declared = str(row.get("rankBasis") or "").strip()
    if declared:
        return declared, True
    return f"total_ranked:{row.get('total_ranked')}", False


def rank_basis_report(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe the rank bases one source's rows sit on.

    ``rows`` are adapter row dicts (``position``, ``total_ranked`` and,
    when the adapter declares it, ``rankBasis``).
    """
    by_basis: dict[str, Counter[str]] = {}
    totals: dict[str, set[Any]] = {}
    declared_all = True
    any_rows = False
    for row in rows:
        any_rows = True
        basis, declared = _row_basis(row)
        declared_all = declared_all and declared
        group = canonical_position_group(row.get("position"))
        by_basis.setdefault(basis, Counter())[group] += 1
        totals.setdefault(basis, set()).add(row.get("total_ranked"))

    group_bases: dict[str, list[str]] = {}
    for basis, groups in by_basis.items():
        for group in groups:
            group_bases.setdefault(group, []).append(basis)
    for bases in group_bases.values():
        bases.sort()

    split = sorted(g for g, bases in group_bases.items() if len(bases) > 1)
    issues: list[str] = []
    if len(by_basis) > 1:
        issues.append(MIXED_RANK_BASIS)
    issues.extend(f"{GROUP_SPLIT_ACROSS_BASES}:{g}" for g in split)

    coverage: Counter[str] = Counter()
    for groups in by_basis.values():
        coverage.update(groups)

    return {
        "basisDeclared": bool(any_rows and declared_all),
        "bases": [
            {
                "basis": basis,
                "rows": sum(groups.values()),
                "totalRanked": sorted(
                    (t for t in totals[basis] if t is not None), key=lambda t: str(t)
                ),
                "groups": dict(sorted(groups.items())),
            }
            for basis, groups in sorted(by_basis.items())
        ],
        "groupCoverage": dict(sorted(coverage.items())),
        "groupBases": dict(sorted(group_bases.items())),
        "mixedRankBasis": len(by_basis) > 1,
        "groupsSplitAcrossBases": split,
        "issues": issues,
    }


def compare_to_previous(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> list[str]:
    """Issues raised by the change from ``previous`` to ``current``.

    Both are :func:`rank_basis_report` outputs.  ``previous`` is ``None``
    (or carries no coverage) on a source's first diagnosed run, which is
    a baseline, not a pass: nothing can be said, so nothing is raised.

    * ``group_coverage_vanished:<G>`` — the group had rows, now has none.
    * ``group_rank_basis_changed:<G>`` — the group is still covered, but
      on a different set of bases.  Only compared when BOTH reports have
      declared bases: an inferred ``total_ranked:N`` id moves whenever a
      board's length does, which is not a basis change.
    """
    if not previous or not isinstance(previous.get("groupCoverage"), Mapping):
        return []
    prev_cov = previous.get("groupCoverage") or {}
    cur_cov = current.get("groupCoverage") or {}
    issues: list[str] = []
    for group in sorted(prev_cov):
        had = prev_cov.get(group)
        # Only a PROVEN positive previous count can vanish; an unreadable one
        # says nothing (never coerced to 0).
        if isinstance(had, bool) or not isinstance(had, int) or had <= 0:
            continue
        now = cur_cov.get(group)
        # A group absent from this run's coverage has no rows this run; an
        # explicit 0 says the same.  Any other value is not a vanishing.
        if now is None or (isinstance(now, int) and not isinstance(now, bool) and now == 0):
            issues.append(f"{GROUP_COVERAGE_VANISHED}:{group}")
    if previous.get("basisDeclared") and current.get("basisDeclared"):
        prev_bases = previous.get("groupBases") or {}
        cur_bases = current.get("groupBases") or {}
        for group in sorted(set(prev_bases) & set(cur_bases)):
            if sorted(prev_bases[group]) != sorted(cur_bases[group]):
                issues.append(f"{GROUP_RANK_BASIS_CHANGED}:{group}")
    return issues


def _positive_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def adapter_issues(
    report: Mapping[str, Any],
    *,
    withheld: Mapping[str, Any] | None = None,
    groups_served_by_other_key: Mapping[str, Any] | None = None,
) -> list[str]:
    """Issues from what the ADAPTER stated about this key.

    * ``cross_key_family_overlap:<G>`` -- this key has rows in group ``G``
      while the adapter says another key of the same vendor serves ``G``.
    * ``rows_withheld:<reason>`` -- a positive withheld count for a reason in
      :data:`SURFACED_WITHHELD_REASONS`.  A count that is absent or not a
      positive int raises nothing (never coerced).
    """
    issues: list[str] = []
    coverage = report.get("groupCoverage") or {}
    for group in sorted(groups_served_by_other_key or {}):
        if _positive_count(coverage.get(group)):
            issues.append(f"{CROSS_KEY_FAMILY_OVERLAP}:{group}")
    for reason in SURFACED_WITHHELD_REASONS:
        if _positive_count((withheld or {}).get(reason)):
            issues.append(f"{ROWS_WITHHELD}:{reason}")
    return issues


def diagnose(
    rows: Iterable[Mapping[str, Any]],
    previous: Mapping[str, Any] | None,
    *,
    withheld: Mapping[str, Any] | None = None,
    groups_served_by_other_key: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Full per-refresh diagnostic: the report, the transition issues, the
    adapter-stated issues, and whatever the adapter withheld (``withheld`` —
    counts by reason)."""
    report = rank_basis_report(rows)
    transition = compare_to_previous(report, previous)
    stated = adapter_issues(
        report, withheld=withheld, groups_served_by_other_key=groups_served_by_other_key
    )
    report["transitionIssues"] = transition
    report["adapterIssues"] = stated
    report["issues"] = list(report["issues"]) + transition + stated
    report["baseline"] = previous is None or not isinstance(
        (previous or {}).get("groupCoverage"), Mapping
    )
    if withheld:
        report["withheld"] = dict(withheld)
    if groups_served_by_other_key:
        report["groupsServedByOtherKey"] = dict(groups_served_by_other_key)
    return report
