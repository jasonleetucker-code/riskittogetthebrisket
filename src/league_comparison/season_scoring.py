"""Which scoring card scored a given SEASON — the as-of owner for rescoring.

WHY THIS EXISTS
---------------
Historical rescoring applied **today's** scoring card to every season.  That
is not a rounding error, it is the wrong question: a league that moved from
0.5 PPR to full PPR between 2023 and 2025 has its 2023 rewritten under rules
nobody played, and the resulting "realized points" describe a season that
never happened.

Two independent consumers had the defect, both measured:

* ``league_comparison.service`` loops seasons and passes the single
  ``league_info.scoring_settings`` into every one of them;
* ``bdvm.baseline.realized_ppg_history`` takes one ``scoring_settings`` and
  applies it across 2021-2025.

Sleeper chains a dynasty league year to year under a NEW league id, linked by
``previous_league_id``, and each link carries its own ``season`` and its own
``scoring_settings``.  So the correct card for a season is not a guess — it is
published, and this module goes and gets it.

FAIL CLOSED
-----------
A season whose card cannot be resolved is reported ``unresolved``.  It is
never scored with today's card, because substituting today's card IS the
defect this module exists to remove, and a silent substitution would preserve
it while hiding the evidence.  ``MISSING IS NEVER ZERO`` applied to
configuration: an unknown rule set is unknown, not "presumably the current
one".

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not score anything and it does not decide compatibility.  Scoring is
``src.nfl_data.realized_points``; the factual scoring identity used for
cross-league ranking compatibility is ``sleeper_scoring.scoring_fingerprint``
(W18-F001) and is a different question from "what did this league pay in
2023".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from . import sleeper_scoring as _sleeper

_LOGGER = logging.getLogger(__name__)

#: How many ``previous_league_id`` hops to follow.  A dynasty league is one
#: hop per season, so this bounds the walk at a decade — far past any season
#: the stat feeds cover — while still terminating on a cyclic or malformed
#: chain.  ``walk`` also guards cycles explicitly by id.
MAX_CHAIN_HOPS = 12

#: Reasons a season can be unresolved.  Machine-readable so a caller can tell
#: "the league did not exist yet" from "the fetch failed", which are very
#: different things to show a user.
REASON_NOT_IN_CHAIN = "season_not_in_league_chain"
REASON_FETCH_FAILED = "league_fetch_failed"
REASON_NO_CARD = "league_has_no_scoring_settings"


@dataclass(frozen=True)
class SeasonCard:
    """One season's actual scoring card, with the league it came from."""

    season: int
    league_id: str
    scoring_settings: dict[str, float]
    scoring_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "leagueId": self.league_id,
            "scoringHash": self.scoring_hash,
            "scoringKeys": len(self.scoring_settings),
        }


@dataclass(frozen=True)
class SeasonScoringChain:
    """The resolved ``season -> card`` map for one league chain.

    ``unresolved`` is as much of the answer as ``cards`` is: a caller that
    reads only ``cards`` and silently skips the rest reintroduces the silence
    this module removes.
    """

    start_league_id: str
    cards: dict[int, SeasonCard] = field(default_factory=dict)
    unresolved: dict[int, str] = field(default_factory=dict)

    def card_for(self, season: int) -> SeasonCard | None:
        """The card that scored ``season``, or ``None`` — never a substitute."""
        return self.cards.get(int(season))

    def settings_for(self, season: int) -> dict[str, float] | None:
        card = self.card_for(season)
        return dict(card.scoring_settings) if card is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "startLeagueId": self.start_league_id,
            "seasons": {str(s): c.to_dict() for s, c in sorted(self.cards.items())},
            "unresolved": {str(s): r for s, r in sorted(self.unresolved.items())},
        }


def _season_of(raw: Mapping[str, Any]) -> int | None:
    try:
        season = int(str(raw.get("season") or "").strip())
    except (TypeError, ValueError):
        return None
    return season if season > 1900 else None


def walk_scoring_chain(
    start_league_id: str,
    *,
    max_hops: int = MAX_CHAIN_HOPS,
    fetcher: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[int, SeasonCard]:
    """Follow ``previous_league_id`` and index each hop by ITS OWN season.

    Indexing by the hop's own ``season`` field rather than by position in the
    walk is what makes this correct: a chain with a missing year, or one that
    skips a season, must not shift every earlier card by one.

    ``fetcher`` takes a league id and returns the raw Sleeper league object;
    injected so tests are hermetic and so a caller with a snapshot on disk can
    supply it instead of the network.
    """
    fetch = fetcher or _default_fetcher
    cards: dict[int, SeasonCard] = {}
    seen: set[str] = set()
    current = str(start_league_id or "").strip()
    hops = 0

    while current and current not in seen and hops < max_hops:
        seen.add(current)
        hops += 1
        try:
            raw = fetch(current)
        except Exception as exc:  # noqa: BLE001 — a broken hop ends the walk
            _LOGGER.warning("season_scoring.fetch_failed league_id=%s err=%r", current, exc)
            break
        if not isinstance(raw, Mapping):
            _LOGGER.warning("season_scoring.non_dict_league league_id=%s", current)
            break

        season = _season_of(raw)
        scoring_raw = raw.get("scoring_settings")
        if season is not None and isinstance(scoring_raw, Mapping):
            scoring: dict[str, float] = {}
            for key, value in scoring_raw.items():
                try:
                    scoring[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
            # First writer wins: the walk runs newest → oldest, and a
            # well-formed chain has one league per season.  If a malformed
            # chain repeats a season, the NEARER league is the one the user
            # is actually playing in.
            cards.setdefault(
                season,
                SeasonCard(
                    season=season,
                    league_id=current,
                    scoring_settings=scoring,
                    scoring_hash=_sleeper._scoring_hash(scoring),
                ),
            )
        else:
            _LOGGER.warning(
                "season_scoring.hop_missing_card league_id=%s season=%r", current, season
            )

        nxt = raw.get("previous_league_id") or raw.get("previous_league") or ""
        current = str(nxt or "").strip()

    return cards


def _default_fetcher(league_id: str) -> Mapping[str, Any] | None:
    """Fetch one league object, reusing the scoring module's HTTP layer."""
    return _sleeper._fetch_raw(league_id)


def resolve_season_cards(
    start_league_id: str,
    seasons: Iterable[int],
    *,
    max_hops: int = MAX_CHAIN_HOPS,
    fetcher: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> SeasonScoringChain:
    """``season -> card`` for the requested seasons, failing closed.

    Every requested season lands in exactly one of ``cards`` or
    ``unresolved``; nothing is silently dropped and nothing is substituted.
    """
    start = str(start_league_id or "").strip()
    wanted = sorted({int(s) for s in seasons})
    if not start:
        return SeasonScoringChain(
            start_league_id=start,
            unresolved={s: REASON_FETCH_FAILED for s in wanted},
        )

    walked = walk_scoring_chain(start, max_hops=max_hops, fetcher=fetcher)

    cards: dict[int, SeasonCard] = {}
    unresolved: dict[int, str] = {}
    for season in wanted:
        card = walked.get(season)
        if card is None:
            unresolved[season] = REASON_NOT_IN_CHAIN
        elif not card.scoring_settings:
            unresolved[season] = REASON_NO_CARD
        else:
            cards[season] = card

    if unresolved:
        _LOGGER.info(
            "season_scoring.unresolved start=%s seasons=%s",
            start,
            sorted(unresolved),
        )
    return SeasonScoringChain(start_league_id=start, cards=cards, unresolved=unresolved)
