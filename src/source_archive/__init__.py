"""Multi-format dynasty source archive — ``C1-SRC-01``.

WHAT THIS IS FOR
────────────────
Providers publish the same dynasty market under several native formats —
KTC's Off / TE+ / TE++ / TE+++ ladder, 1QB versus Superflex boards, IDP
presets. ``docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md`` §2: those
paired observations "have option value that cannot reliably be recreated
later", because a provider can change its rankings, controls or
endpoints at any time and historical variants are then gone.

Today nothing keeps them. ``CSVs/site_raw/*.csv`` is overwritten in
place on every fetch, and the ``data/raw*`` trees have been frozen since
April 2026. Specifically: **KTC's four TE-premium states already arrive
in every scrape response** (``superflexValues: {value, tep, tepp,
teppp}``) and the scraper reads ``tepp`` and discards the rest. The
ladder costs no extra request; discarding it is the loss.

THE BOUNDARY, STATED FIRST BECAUSE IT IS THE POINT
──────────────────────────────────────────────────
**Archiving a board is not authorization to price with it.** §16 item 9
and §19 are explicit, and this package is built so that the separation
is structural rather than a matter of nobody having wired it up yet:

* the vote gate is membership of ``data_contract._RANKING_SOURCES``, and
  nothing here writes to it;
* :data:`ARCHIVE_ELIGIBLE` and :data:`PRODUCTION_ELIGIBLE` are separate
  sets, and a test asserts their intersection with the voting registry
  is empty;
* a test asserts ``data_contract`` does not import this package, so an
  archived variant is not one edit away from voting.

ONE PROVIDER FAMILY, NOT FOUR VOTES
───────────────────────────────────
KTC states that its TE-premium values are **algorithmically applied from
its base crowd values** (§4.2). Off / TE+ / TE++ / TE+++ are therefore
four calibration anchors on one opinion, not four crowds. Every archived
variant carries ``provider_family``, and archiving the whole ladder is
proven not to change the independent-family set that confidence and
Consensus Edge count — reopening the B10 circularity through a new door
is the specific failure this guards.

GAME TYPE FAILS CLOSED HERE TOO
───────────────────────────────
The same rule the blend gate enforces (``C1-SRC-02``): only ``DYNASTY``
is eligible, and ``UNKNOWN`` is refused rather than accepted. A board we
cannot prove is dynasty does not become dynasty by being stored.

WHY ITS OWN STORE RATHER THAN ``src/history``
─────────────────────────────────────────────
``src/history`` owns *canonical* as-of value observations, and its
identity index is ``(asset_key, lane, source_key, observed_date, ...)``
with no variant dimension — so an alternate-format board could only be
carried by overloading ``source_key`` into a compound string, which
would make a format variant indistinguishable from a distinct source at
exactly the layer that must never confuse them. Native source-format
observations are a different quantity in a different lifecycle, kept
raw and never overwritten with our normalized value (§5).
"""

from __future__ import annotations

from src.source_archive.store import (
    ARCHIVE_ELIGIBLE,
    DB_PATH,
    PRODUCTION_ELIGIBLE,
    SCHEMA_VERSION,
    ArchivedBoard,
    archive_board,
    coverage,
    read_boards,
)

__all__ = [
    "ARCHIVE_ELIGIBLE",
    "DB_PATH",
    "PRODUCTION_ELIGIBLE",
    "SCHEMA_VERSION",
    "ArchivedBoard",
    "archive_board",
    "coverage",
    "read_boards",
]
