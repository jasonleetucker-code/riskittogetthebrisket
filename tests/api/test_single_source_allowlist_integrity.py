"""An allowlist entry may not rest on a source we no longer have.

F-8 / census S-5.  ``SINGLE_SOURCE_ALLOWLIST`` suppresses
``assert_no_unexplained_single_source`` for top-board players who are
legitimately carried by one source, and each entry is a human-readable
statement of WHY.  Nothing checked that the statement was still true.

Measured on the 2026-08-18 board, **18 of 52 entries** named FootballGuys
as the sole ranker — a source that is in no registry, has no CSV path, no
CSV file, and last stamped `2026-05-24`.  None of the 18 was true:

* 2 players were not on the board at all;
* 14 were on the board and **not single-source** — the most extreme,
  Zavion Thomas, carried **13** sources under an entry saying he was
  "only ranked by FootballGuys";
* 2 were still single-source, but by ``draftSharks`` and
  ``fantasyProsSf`` respectively — and both sit past
  ``OVERALL_RANK_LIMIT``, outside the window the gate polices.

So the gate was suppressed by explanations that had quietly become
fiction, and the contract validates ``ok: True`` with all 18 removed —
they were guarding nothing.

The durable repair is not the deletion, it is this test: the
machine-readable prefix must name sources that EXIST.  A retired source
cannot survive in an explanation, because its key stops resolving.
"""

from __future__ import annotations

import re

import pytest

from src.api.data_contract import (
    SINGLE_SOURCE_ALLOWLIST,
    _SOURCE_CSV_PATHS,
    correlation_group_for,
    get_ranking_source_keys,
)

#: ``source_gap:a+b+c — prose``.  The prefix lists the sources that do
#: NOT carry the player; the prose says who does.
_PREFIX = re.compile(r"^(rookie_source_gap|source_gap|depth_boundary|rookie_exclusion):([^\s—]+)")


def _known_source_tokens() -> set[str]:
    """Every token an explanation is allowed to name.

    Registry keys, the CSV-path keys (``ktc`` loads without voting), and
    the correlation-group names — because an explanation legitimately
    says "no FantasyPros board carries him" rather than naming the SF and
    IDP boards separately.
    """
    keys = set(get_ranking_source_keys())
    return keys | set(_SOURCE_CSV_PATHS) | {correlation_group_for(k) for k in keys}


def test_every_entry_uses_the_machine_readable_grammar():
    unparsed = {k: v for k, v in SINGLE_SOURCE_ALLOWLIST.items() if not _PREFIX.match(v)}
    assert not unparsed, (
        "an allowlist reason must lead with a machine-readable category so it can be "
        f"checked rather than merely read: {unparsed}"
    )


def test_no_entry_names_a_source_that_does_not_exist():
    known = _known_source_tokens()
    offenders: dict[str, list[str]] = {}
    for player, reason in SINGLE_SOURCE_ALLOWLIST.items():
        m = _PREFIX.match(reason)
        assert m is not None  # covered by the test above
        unknown = [tok for tok in m.group(2).split("+") if tok not in known]
        if unknown:
            offenders[player] = unknown
    assert not offenders, (
        "an allowlist entry justifies suppressing a build check, so it may not rest on a "
        "source the pipeline no longer has — a retired source in an explanation is a "
        f"false explanation: {offenders}"
    )


@pytest.mark.parametrize("retired", ["footballGuys", "footballGuysSf", "footballGuysIdp"])
def test_the_retired_footballguys_boards_are_gone_from_the_allowlist(retired):
    """Named explicitly because this is the case that was measured.

    The prose half matters as much as the prefix: 18 entries said "only
    ranked by FootballGuys" in prose while the prefix named other
    sources, so a prefix-only check would have passed all 18.
    """
    mentions = {k: v for k, v in SINGLE_SOURCE_ALLOWLIST.items() if retired.lower() in v.lower()}
    assert not mentions, f"{retired} is retired; entries still naming it: {mentions}"


def test_no_entry_claims_a_sole_ranker_the_pipeline_does_not_have():
    """The prose form that rotted: ``only ranked by <X>``.

    Checked against the registry's DISPLAY names as well as its keys,
    because the prose is written for a human ("only ranked by FantasyPros
    dynasty SF") rather than in keys.  A prose name that matches nothing
    in the registry is the signature of a source that has been retired
    out from under its own explanation.
    """
    from src.api.data_contract import get_ranking_source_registry

    vocabulary = " ".join(
        [s["key"] for s in get_ranking_source_registry()]
        + [s["displayName"] for s in get_ranking_source_registry()]
        + [s["columnLabel"] for s in get_ranking_source_registry()]
    ).lower()

    offenders = {}
    for player, reason in SINGLE_SOURCE_ALLOWLIST.items():
        m = re.search(r"only ranked by\s+([A-Za-z][A-Za-z ]*)", reason)
        if not m:
            continue
        # First word is enough to identify the provider and avoids
        # matching on board qualifiers ("dynasty", "SF", "expert").
        provider = m.group(1).split()[0].lower()
        if provider not in vocabulary:
            offenders[player] = provider
    assert not offenders, (
        "an explanation names a sole ranker the registry does not contain — the source was "
        f"retired and the explanation was not: {offenders}"
    )
