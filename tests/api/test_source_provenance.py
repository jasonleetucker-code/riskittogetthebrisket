"""Provider families are DECLARED — B10-T2.

WHAT THIS UNIT IS, AND WHAT IT DELIBERATELY IS NOT
──────────────────────────────────────────────────
This declares which ranking sources come from the SAME PROVIDER. It does
not change how they are counted. That separation is the point: a
declaration whose effect on the board is provably nil can be reviewed on
whether it is *true*, while a change to aggregation has to be reviewed on
what it *moves*. Doing both at once means neither gets checked properly.

Measured after declaring: **0 values moved, 0 ranks changed**
(`scripts/board_diff.py --expect-no-value-change`). The canonical blend
never reads `correlation_group`; only leave-one-out and Consensus Edge do.

WHY IT MATTERS — measured on the tracked 2026-08-14 CSVs
────────────────────────────────────────────────────────
19 of 21 sources declared nothing, so `correlation_group_for` defaulted
each to its own key and every one counted as an independent opinion.
Three providers publish more than one board that covers the SAME players:

| provider | rows it votes on more than once |
|---|---|
| FantasyPros | **299** |
| Flock Fantasy | 70 |
| DLF | 52 |

FantasyPros is the case the owner ruled on directly: `fantasyProsSf` is a
544-player expert **consensus**, and `fantasyProsFitzmaurice` is **one
expert inside that panel** — 299 players, **100% contained** in the
consensus board, Pearson r = 0.9297. An expert already inside a provider
consensus does not get a second independent canonical vote.

The lineage here is **declarative, not inferred**: the source's own
`display_name` is "FantasyPros / Pat Fitzmaurice SF-TEP". The correlation
measurement corroborates it and is not the basis for it — per the owner's
rule that family ownership must never be guessed from output correlation.

CORRECTION TO THE AUTHORISING PREMISE, recorded so it is not re-derived
───────────────────────────────────────────────────────────────────────
The B10 scope was written around "ktc weight ~1.3 + ktcSfTep ~1.0, so
KTC-family evidence votes at ~2.3 against IDPTC's 1.0". Measured on this
tree, that does not describe canonical aggregation:

* there is **no `ktc` entry** in `_RANKING_SOURCES`; the KTC family votes
  canonically exactly once, through `ktcSfTep`, at weight **1.00**;
* **all 21 sources are weight 1.00**, per the registry's stated policy;
* the `1.3` is real but belongs to `LEGACY_COMPOSITE_SITE_WEIGHTS` in
  `Dynasty Scraper.py`, whose own docstring scopes it to `_composite` and
  pick-row blending — a different concept that shares the word "weight";
* `ktc` DOES appear in `canonicalSiteValues` (464 rows, the same rows as
  `ktcSfTep`) but is not a registered source, so it casts no vote.

The real independence defect is the undeclared families above, not a
KTC double-weight.
"""

from __future__ import annotations

import collections
import inspect

from src.api import data_contract
from src.api.data_contract import (
    _RANKING_SOURCES,
    correlation_group_for,
    expand_correlation_groups,
)

#: Providers that publish more than one board in the registry. Declared
#: from provenance — the vendor each feed is fetched from — not from
#: output similarity.
KNOWN_MULTI_BOARD_PROVIDERS = {
    "dlf": {"dlfSf", "dlfRookieSf", "dlfIdp", "dlfRookieIdp"},
    "fantasyPros": {"fantasyProsSf", "fantasyProsIdp", "fantasyProsFitzmaurice"},
    "flockFantasy": {"flockFantasySf", "flockFantasySfRookies"},
    "draftSharks": {"draftSharks", "draftSharksIdp"},
    "ktc": {"ktcSfTep", "fantasyNavigatorSf"},
}


def _groups() -> dict[str, set[str]]:
    out: dict[str, set[str]] = collections.defaultdict(set)
    for src in _RANKING_SOURCES:
        key = str(src.get("key") or "")
        out[str(src.get("correlation_group") or key)].add(key)
    return dict(out)


class TestEveryMultiBoardProviderIsDeclared:
    def test_the_known_families_are_grouped(self):
        groups = _groups()
        for provider, members in KNOWN_MULTI_BOARD_PROVIDERS.items():
            assert (
                groups.get(provider) == members
            ), f"{provider} is declared as {groups.get(provider)}, expected {members}"

    def test_the_nested_expert_shares_its_panels_group(self):
        """The owner's ruling, as an assertion.

        Pat Fitzmaurice is an expert inside the FantasyPros consensus.
        Whatever B10-T3 decides a family is worth, these two must be
        deciding it together.
        """
        assert correlation_group_for("fantasyProsFitzmaurice") == correlation_group_for(
            "fantasyProsSf"
        )

    def test_expanding_one_member_reaches_the_whole_family(self):
        expanded = expand_correlation_groups(["fantasyProsFitzmaurice"])
        assert KNOWN_MULTI_BOARD_PROVIDERS["fantasyPros"] <= expanded

    def test_no_source_silently_defaults_into_a_declared_family(self):
        """A source whose key happens to match a family name would join it
        by accident rather than by declaration."""
        declared = {str(s.get("key") or "") for s in _RANKING_SOURCES if s.get("correlation_group")}
        for src in _RANKING_SOURCES:
            key = str(src.get("key") or "")
            if key in declared:
                continue
            assert (
                key not in KNOWN_MULTI_BOARD_PROVIDERS
            ), f"{key} lands in a multi-board family by defaulting to its own key"

    def test_independent_family_count_is_lower_than_source_count(self):
        """The number this exists to make available to B10-T3.

        21 source keys, 13 independent provider families. Any aggregation
        step whose mathematical meaning is "how much independent evidence
        is there" must use the second number.
        """
        assert len(_RANKING_SOURCES) == 21
        assert len(_groups()) == 13


class TestTheDeclarationHasOneConsumerPath:
    """T2 was inert. T3b deliberately stopped being.

    This class used to assert that ``_compute_unified_rankings`` contains
    no mention of ``correlation_group`` at all — the right guard for T2,
    whose entire reviewability rested on declaring families while moving
    no value.

    **T3b retired that property on purpose** (455 values moved, its own
    before/after envelope), and this guard did not notice, because T3b
    reached the family through a helper: ``collapse_to_independent_
    families`` calls ``correlation_group_for`` internally, so the literal
    string never appeared in the caller. A guard that survives the change
    it was written to catch is worse than no guard — it reads as evidence
    of a property that stopped holding.

    What replaces it is the property that IS true and IS worth pinning:
    the blend reads family membership from the declared owner and from
    nowhere else. B11 added a second call site (the confidence gate needs
    a family per source), which is exactly the kind of arrival the old
    guard existed to flag — so the guard now checks lineage, not silence.
    """

    def test_family_membership_comes_only_from_the_declared_owner(self):
        """No second list, no inline mapping, no re-derivation.

        Every way the blend learns which family a source belongs to must
        route through ``correlation_group_for`` / ``expand_correlation_
        groups`` / ``collapse_to_independent_families``. A dict literal
        mapping keys to providers inside this function would be a second
        declaration, and it would drift.
        """
        src = inspect.getsource(data_contract._compute_unified_rankings)
        sanctioned = (
            "correlation_group_for",
            "expand_correlation_groups",
            "collapse_to_independent_families",
        )
        for line in src.splitlines():
            code = line.split("#", 1)[0]
            if "correlation_group" not in code:
                continue
            assert any(
                name in code for name in sanctioned
            ), f"family membership resolved outside the declared owner: {line.strip()!r}"

    def test_the_registry_is_the_only_place_a_family_is_named(self):
        """A provider name hard-coded in the pipeline is a second registry."""
        src = inspect.getsource(data_contract._compute_unified_rankings)
        for family in KNOWN_MULTI_BOARD_PROVIDERS:
            assert (
                f'"{family}"' not in src and f"'{family}'" not in src
            ), f"provider family {family!r} is named inside the blend rather than declared"
