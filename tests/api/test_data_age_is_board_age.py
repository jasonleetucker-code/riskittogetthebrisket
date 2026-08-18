"""Data age must measure the BOARD, not this process.

AUDIT FINDING F-19 (2026-08-18)
───────────────────────────────
``latest_data_source["loadedAt"]`` is stamped ``_utc_now_iso()`` when THIS
PROCESS loads a payload (``server.py::_set_latest_data_source``).  Four
consumers treated it as when the board was PRODUCED:

    /api/health   data_age_hours / data_stale
                  # its own comment: "flag stale if no refresh in
                  #                   SCRAPE_INTERVAL_HOURS * 3"
    /api/metrics  data_age_seconds
    /api/status   "last_data_refresh_at"
    the ops-alert sweep, which passes data_age_hours into
    ``ops_alerts.check_and_alert``

So "no refresh" was measured as "no process restart".  Loading a payload
12.74 h old — more than 2x the 6 h budget — returned ``data_age_hours = 0.0``
and ``data_stale = False``.

THE REPO ALREADY KNEW
─────────────────────
``deploy/systemd/dynasty-healthcheck.sh``, verbatim:

    a restart clears the in-memory scrape error and reloads the disk cache
    with a fresh loadedAt, flipping health green WITHOUT a successful scrape
    and concealing the ingestion fault.

The response was a restart POLICY — degraded 503s are log-only — which
protects the one path the watchdog controls.  Every other restart still
launders a stale board, and **a production deploy is one of them**, several
times a day.

THE TRAP THIS MODULE EXISTS TO CATCH
────────────────────────────────────
The scraper *used to* write ``scrapeTimestamp`` with
``datetime.datetime.now()`` — no timezone:
``"2026-08-18T11:04:55.664246"``.  Subtracting a naive datetime from a
tz-aware ``now`` raises ``TypeError``, and every one of these call sites
swallows it with ``except (ValueError, TypeError): pass``.

So the obvious implementation of this repair produces ``data_age_hours =
None`` EVERYWHERE and looks like it worked.  ``test_naive_timestamp_still_
produces_an_age`` is the assertion that stops that, and it is the reason this
module is not just "assert stale is True".  Naive stamps still arrive from
committed archives, so the branch is live, not vestigial.

AUDIT F-28 — WHY "ATTACH UTC" WAS NOT ENOUGH
────────────────────────────────────────────
Attaching UTC to a naive stamp is an ASSUMPTION about where the producer
runs, and production said it was false: the VPS runs UTC+2, so a board
scraped at 17:36 UTC reported ``data_age_hours: -1.0`` at 18:35 UTC.  A
negative age sits below every staleness threshold by construction, which
made ``data_stale`` structurally unreachable rather than merely inaccurate.

The repair is in two halves that must stay together, and the tests below
pin both: the SOURCE now stamps tz-aware UTC, and the reader refuses a
board produced in the future.  The guard alone would make every production
reading UNKNOWN; the source fix alone leaves nothing catching the next
producer that reintroduces a local clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import server


@pytest.fixture
def restore_source():
    saved = dict(server.latest_data_source)
    yield
    server.latest_data_source.clear()
    server.latest_data_source.update(saved)


def _iso_naive(hours_ago: float) -> str:
    """A naive ISO stamp, exactly the shape ``Dynasty Scraper.py`` writes."""
    return (
        (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(tzinfo=None).isoformat()
    )


def _iso_aware(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ── the helper ──────────────────────────────────────────────────────────


def test_a_single_owner_answers_how_old_the_board_is(restore_source) -> None:
    """One function, so the four consumers cannot drift apart again."""
    assert callable(getattr(server, "_board_age_hours", None))


def test_naive_timestamp_still_produces_an_age(restore_source) -> None:
    """THE trap.  A naive stamp must not silently yield None."""
    server.latest_data_source.update({"producedAt": _iso_naive(5.0), "loadedAt": _iso_aware(0.0)})
    age = server._board_age_hours()
    assert age is not None, "naive scrapeTimestamp produced no age — the repair is inert"
    assert 4.5 < age < 5.5, age


def test_aware_timestamp_works_too(restore_source) -> None:
    server.latest_data_source.update({"producedAt": _iso_aware(3.0), "loadedAt": _iso_aware(0.0)})
    age = server._board_age_hours()
    assert age is not None and 2.5 < age < 3.5, age


def test_absent_production_time_is_unknown_not_zero_and_never_falls_back(
    restore_source,
) -> None:
    """MISSING IS NEVER ZERO, and here it must also never be ``loadedAt``.

    A payload that does not state when it was produced is UNKNOWN.  Falling
    back to the load time is precisely the defect — and 0.0 is the most
    reassuring number the field can carry.
    """
    server.latest_data_source.update({"producedAt": "", "loadedAt": _iso_aware(0.0)})
    assert server._board_age_hours() is None

    server.latest_data_source.pop("producedAt", None)
    assert server._board_age_hours() is None


def test_unparseable_production_time_is_unknown(restore_source) -> None:
    server.latest_data_source.update({"producedAt": "not a timestamp", "loadedAt": _iso_aware(0.0)})
    assert server._board_age_hours() is None


# ── AUDIT F-28: a board from the future is UNKNOWN, never a number ──────
#
# Production served ``data_age_hours: -1.0`` at 18:35 UTC for a board scraped
# at 17:36 UTC.  The producing host runs UTC+2 and stamped naive local time,
# which the reader above attaches UTC to.  A negative age is not a small
# error: it sits below every staleness threshold BY CONSTRUCTION, so
# ``data_stale`` (age > SCRAPE_INTERVAL_HOURS * 3) was unreachable and the
# alarm F-19 exists to feed could not fire at all.


def test_a_board_from_the_future_is_unknown_not_negative(restore_source) -> None:
    server.latest_data_source.update({"producedAt": _iso_aware(-2.0), "loadedAt": _iso_aware(0.0)})
    assert server._board_age_hours() is None, (
        "a board claiming to be produced two hours from now published an age; "
        "a negative age is below every staleness threshold by construction"
    )


def test_the_measured_production_state_is_unknown(restore_source) -> None:
    """The exact shape of the live defect, as an assertion.

    A naive stamp one hour old, written by a host two hours ahead of UTC,
    reads as one hour in the future.  That is the ``-1.0`` production served.
    """
    ahead = datetime.now(timezone.utc) + timedelta(hours=1)
    server.latest_data_source.update(
        {"producedAt": ahead.replace(tzinfo=None).isoformat(), "loadedAt": _iso_aware(0.0)}
    )
    assert server._board_age_hours() is None


def test_ordinary_clock_skew_is_tolerated_not_refused(restore_source) -> None:
    """The guard must not turn every just-produced board into UNKNOWN.

    A board stamped seconds ahead of this host's clock is a normal NTP
    difference, not a timezone error — the tolerance is bounded well below
    the smallest timezone quantum (15 minutes) for exactly that reason.
    """
    server.latest_data_source.update(
        {"producedAt": _iso_aware(-1.0 / 60.0), "loadedAt": _iso_aware(0.0)}
    )
    age = server._board_age_hours()
    assert age is not None, "one minute of clock skew was refused as a future board"
    assert age >= 0.0, age


def test_the_guard_leaves_real_ages_alone(restore_source) -> None:
    """The converse of the guard: it may only reject the future."""
    server.latest_data_source.update({"producedAt": _iso_aware(7.0), "loadedAt": _iso_aware(0.0)})
    age = server._board_age_hours()
    assert age is not None and 6.5 < age < 7.5, age


def test_the_scraper_stamps_a_zone_qualified_instant() -> None:
    """F-28's repair is AT THE SOURCE; the guard alone would hide it.

    With the producer still naive-local, every board prod makes reads as
    future-dated and the guard above turns the age UNKNOWN — trading a wrong
    number for a permanently missing one.  The two must land together, so
    this reads the producer.

    Text rather than an import: ``Dynasty Scraper.py`` is a ~6,700-line module
    that opens browsers at import time.  The same reason
    ``tests/identity/test_name_primitives_parity.py`` reads it as source.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "Dynasty Scraper.py").read_text(encoding="utf-8")
    writers = [ln.strip() for ln in src.splitlines() if '"scrapeTimestamp":' in ln]
    assert writers, "the scrapeTimestamp writer disappeared from Dynasty Scraper.py"
    for line in writers:
        assert "datetime.datetime.now()" not in line, (
            "scrapeTimestamp is stamped with a NAIVE now() again (F-28). "
            "The production VPS runs UTC+2, so a naive stamp read as UTC put "
            "the board an hour in the future and made data_stale unreachable."
        )
        assert "timezone.utc" in line, line


# ── the behaviour the finding is about ──────────────────────────────────


def test_a_stale_board_loaded_just_now_is_reported_stale(restore_source) -> None:
    """The measured defect, inverted into an assertion.

    A board produced 12.74 h ago and loaded THIS INSTANT — the state every
    deploy creates — must read stale, not fresh.
    """
    server.latest_data_source.update({"producedAt": _iso_naive(12.74), "loadedAt": _iso_aware(0.0)})
    age = server._board_age_hours()
    assert age is not None and age > server.SCRAPE_INTERVAL_HOURS * 3


def test_a_fresh_board_loaded_long_ago_is_not_reported_stale(restore_source) -> None:
    """The converse, so the guard is not simply 'always stale'.

    A long-running process holding a recently produced board is healthy;
    process uptime must not make it look old either.
    """
    server.latest_data_source.update({"producedAt": _iso_naive(0.5), "loadedAt": _iso_aware(48.0)})
    age = server._board_age_hours()
    assert age is not None and age < server.SCRAPE_INTERVAL_HOURS * 3


# ── the wiring, read from the AST ───────────────────────────────────────
#
# Defining the helper is not the repair; USING it at all four sites is.  A
# version that added ``producedAt`` and left the consumers on ``loadedAt``
# would keep every assertion above passing while production still reported a
# stale board as fresh.  So this reads the CODE.


def _server_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / "server.py").read_text()


def _code_lines() -> list[str]:
    """Source with comment-only lines stripped.

    Learned the hard way twice this session: a guard that matches prose
    matches the explanation of the defect as readily as its fix.
    """
    return [ln for ln in _server_source().splitlines() if not ln.strip().startswith("#")]


def test_no_consumer_still_computes_an_age_from_loaded_at() -> None:
    code = _code_lines()
    offenders = [
        (i + 1, ln.strip())
        for i, ln in enumerate(code)
        if 'latest_data_source.get("loadedAt")' in ln
    ]
    # The setter and the diagnostic surface may still READ loadedAt — it is a
    # real fact about the process.  What must not survive is an AGE computed
    # from it, which is what these tests pin by requiring the helper instead.
    for _, line in offenders:
        assert "age" not in line.lower(), line


def test_every_age_consumer_routes_through_the_owner() -> None:
    """One owner, and the AGE consumers all call it.

    Three of the four surfaces publish an age — ``/api/health``,
    ``/api/metrics`` and the ops sweep — so the file must carry the
    definition plus at least three call sites.  ``/api/status`` is
    deliberately NOT one of them: it publishes a TIMESTAMP, not a duration,
    so it reads ``producedAt`` directly (pinned separately below).  This
    assertion states that split rather than a round number.
    """
    code = "\n".join(_code_lines())
    assert code.count("_board_age_hours(") >= 4, code.count("_board_age_hours(")


def test_status_publishes_both_facts_under_honest_names() -> None:
    """``last_data_refresh_at`` claims to be a refresh time, so it must carry
    one — the board's production time.  The process fact is real too and
    keeps its own name rather than being deleted."""
    code = "\n".join(_code_lines())
    assert '"last_payload_loaded_at"' in code
    refresh = [ln for ln in _code_lines() if '"last_data_refresh_at"' in ln]
    assert refresh, "last_data_refresh_at disappeared"
    for line in refresh:
        assert "producedAt" in line, line
        assert "loadedAt" not in line, line
