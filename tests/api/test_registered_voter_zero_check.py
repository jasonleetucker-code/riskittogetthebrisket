"""A registered source that votes on NOTHING must be reported.

AUDIT FINDING F-15 (2026-08-18)
───────────────────────────────
F-10 fixed one source.  This is the class it belonged to.

``validate_api_data_contract`` drove its zero check off
``_load_source_row_floors()``:

    for src_key, threshold in row_floors.items():
        if count == 0:
            errors.append(f"source_missing:{src_key}")

so a key with no floor entry was never counted and never checked —
**absence of a THRESHOLD silently meant absence of a CHECK**.

Measured with F-10's ``ktcSfTep`` floor already in place, by zeroing each
registered voter's ``canonicalSiteValues`` in a built contract one at a time:
8 of 21 produced ``ok=True`` with an EMPTY source-health lane.

    fantasyProsSf           474 rows on the live board
    pfkDynasty              472
    fantasyNavigatorSf      454
    otcffbSf                447
    fantasyCalc             388
    dlfRookieSf             112
    flockFantasySfRookies    76
    dlfRookieIdp             29

Three of those omissions were not oversights but expired promises — the
``_DEFAULT_SOURCE_ROW_FLOORS`` note of 2026-07-25 said floors for
``fantasyCalc`` / ``fantasyNavigatorSf`` / ``pfkDynasty`` were "intentionally
NOT set yet … Add entries here once live canonical match counts are observed."
The counts now exist (388 / 454 / 472) and the entries were never added.

TWO QUESTIONS, ONE OF WHICH NEEDS NO NUMBER
───────────────────────────────────────────
*Is it gone?* needs no calibration.  *Is it thin?* does.  So the population for
the zero check is the REGISTRY (union the keys that declare a floor, so ``ktc``
— which carries a floor and the KTC pick market while not being a blend voter —
keeps its guard), and the floors map keeps answering only the below-floor
question.

Nothing is invented by this: no threshold is chosen, so census item S-6 (is
stale evidence still a full-weight vote?) is untouched.

IS ZERO EVER LEGITIMATE?  NO — AND THAT WAS CHECKED, NOT ASSUMED
────────────────────────────────────────────────────────────────
The rookie boards were the plausible seasonal exception.  Across the tracked git
history of every previously-unguarded CSV (up to 60 commits each) none has ever
been empty::

    dlfRookieIdp   min 29    dlfRookieSf    min 54    fantasyCalc  min 395
    fantasyNavSf   min 758   fantasyProsSf  min 540   otcffbSf     min 345
    flockRookies   min 62    pfkDynasty     min 496          ever_zero = 0

So the unconditional rule is evidence-backed and inert on today's board.  If a
source ever does acquire a legitimate empty state it gets an explicit reasoned
declaration — never a silent omission.

Every payload here is SYNTHETIC (§3d): this is a statement about our code and
must be provable with no live board, no scrape state and no network.
"""

from __future__ import annotations

import pytest

from src.api.data_contract import (
    _load_source_row_floors,
    get_ranking_source_keys,
    validate_api_data_contract,
)

_REGISTERED = tuple(sorted(get_ranking_source_keys()))


def _payload(*, silent: str | None, total: int = 300) -> dict:
    """A schema-complete contract payload where every watched key votes,
    except ``silent`` which votes on nothing.

    Shape-complete deliberately: ``validate_api_data_contract`` caps ``errors``
    at 200, and a payload missing per-row keys floods that cap with schema noise
    before the source-health block is reached — which would make these tests
    turn on list truncation rather than on the condition they assert.
    """
    keys = set(_REGISTERED) | set(_load_source_row_floors())
    rows = []
    for i in range(total):
        sites = {k: 5000 - i for k in keys if k != silent}
        rows.append(
            {
                "displayName": f"P{i}",
                "canonicalName": f"p{i}",
                "playerId": str(1000 + i),
                "position": "WR",
                "team": "FA",
                "age": 25,
                "rookie": False,
                "sourceCount": len(sites),
                "confidenceBucket": "medium",
                "anomalyFlags": [],
                "values": {"rankDerivedValue": 5000 - i},
                "canonicalSiteValues": sites,
            }
        )
    return {
        "contractVersion": "2026-03-10.v2",
        "generatedAt": "2026-08-18T00:00:00+00:00",
        "maxValues": {k: 9999 for k in keys},
        "players": {r["displayName"]: {} for r in rows},
        "valueAuthority": {},
        "playersArray": rows,
        "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
    }


def _lane(payload: dict) -> list[str]:
    """The SOURCE-HEALTH lane — what CI actually routes on."""
    return list(validate_api_data_contract(payload).get("sourceHealthErrors") or [])


@pytest.mark.parametrize("key", _REGISTERED)
def test_every_registered_voter_is_reported_when_it_votes_on_nothing(key: str) -> None:
    assert f"source_missing:{key}" in _lane(_payload(silent=key))


def test_a_board_where_everyone_votes_reports_nothing() -> None:
    """The guard must not fire on a healthy board — otherwise it is noise and
    would be tuned back out."""
    assert [e for e in _lane(_payload(silent=None)) if e.startswith("source_missing:")] == []


def test_the_population_is_the_registry_not_the_floors_config() -> None:
    """Structural, and stated as a PROPERTY rather than a name.

    At least one registered voter carries no floor entry today.  Whichever one
    that is must still be watched — and if a future change gives every voter a
    floor, this test stops asserting anything about an empty set and says so
    rather than passing vacuously.
    """
    floors = _load_source_row_floors()
    unfloored = [k for k in _REGISTERED if k not in floors]
    if not unfloored:
        pytest.skip("every registered voter now declares a floor — property not observable here")
    for key in unfloored:
        assert f"source_missing:{key}" in _lane(_payload(silent=key)), key


def test_a_floored_non_voter_keeps_its_guard() -> None:
    """``ktc`` is not a blend voter, but it carries a floor AND the KTC pick
    market — 60 pick rows ``ktcSfTep`` does not cover, read by
    ``src/trade/finder.py`` and ``src/bdvm/market.py``.  Widening the population
    to the registry must not narrow it for a key the floors map already had.
    """
    assert "ktc" in _load_source_row_floors()
    assert "source_missing:ktc" in _lane(_payload(silent="ktc"))


def test_thin_is_a_warning_not_an_error() -> None:
    """Between "gone" and "healthy" is "partially arrived", and the two must
    stay distinguishable: a thinner board is a degradation, not an absence."""
    floors = _load_source_row_floors()
    key = "ktcSfTep"
    thin = _payload(silent=None, total=300)
    # Drop the key from all but a handful of rows — present, but below floor.
    for row in thin["playersArray"][5:]:
        row["canonicalSiteValues"].pop(key, None)
    health = validate_api_data_contract(thin)
    assert f"source_missing:{key}" not in (health.get("sourceHealthErrors") or [])
    assert f"source_below_floor:{key}:5:{floors[key]}" in (health.get("warnings") or [])


def test_reported_order_is_deterministic() -> None:
    """The emitted order must be a property of the population, not of a config
    file's key order — otherwise a JSON reshuffle churns every diff."""
    missing = [
        e for e in _lane(_payload(silent=None, total=260)) if e.startswith("source_missing:")
    ]
    assert missing == sorted(missing)


# ── D8 (2026-10-07 audit): SEASONALLY INACTIVE is not BROKEN ─────────────
#
# A declared seasonal source (``src/sources/seasonal_policy.py``, owner
# decision 2026-10-03) that the board itself records as inactive at its own
# time casts no current vote BY DESIGN.  Its absence is the declared phase,
# not a lost source, so it is a warning — exactly as a private source the
# board declares absent by design is.  The excuse is read through the SAME
# owner the served-board coverage gate uses (``contract_inactive_sources``,
# reading the payload's own ``sourceSeasonalState`` stamp), and it fails
# closed: no stamp, a malformed stamp, or a different key excuses nothing.

_SEASONAL_KEY = "flockFantasySfRookies"


def _seasonal_stamp(*keys: str) -> dict:
    return {
        "asOf": "2026-10-07T17:36:08Z",
        "inactive": {
            k: {
                "state": "seasonally_inactive",
                "policyId": "flock_prospects_sf_class_graduation_v1",
                "since": "2026-10-03T05:48:40Z",
                "classYear": 2026,
                "lastInactiveVerifiedAt": "2026-10-07T17:36:12Z",
            }
            for k in keys
        },
    }


def test_a_declared_seasonally_inactive_source_with_no_rows_is_a_warning_not_missing() -> None:
    assert _SEASONAL_KEY in _REGISTERED
    payload = _payload(silent=_SEASONAL_KEY)
    payload["sourceSeasonalState"] = _seasonal_stamp(_SEASONAL_KEY)
    health = validate_api_data_contract(payload)
    assert f"source_missing:{_SEASONAL_KEY}" not in (health.get("sourceHealthErrors") or [])
    assert f"source_seasonally_inactive:{_SEASONAL_KEY}" in (health.get("warnings") or [])


def test_the_seasonal_excuse_covers_only_the_declared_key() -> None:
    other = next(k for k in _REGISTERED if k != _SEASONAL_KEY)
    payload = _payload(silent=other)
    payload["sourceSeasonalState"] = _seasonal_stamp(_SEASONAL_KEY)
    assert f"source_missing:{other}" in _lane(payload)


@pytest.mark.parametrize(
    "stamp",
    [None, {}, {"inactive": None}, {"inactive": [_SEASONAL_KEY]}, "seasonally_inactive"],
)
def test_a_missing_or_malformed_seasonal_stamp_fails_closed(stamp) -> None:
    payload = _payload(silent=_SEASONAL_KEY)
    if stamp is not None:
        payload["sourceSeasonalState"] = stamp
    assert f"source_missing:{_SEASONAL_KEY}" in _lane(payload)
