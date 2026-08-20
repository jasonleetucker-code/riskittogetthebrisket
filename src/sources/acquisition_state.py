"""What happened when we tried to acquire a source.  ONE vocabulary.

Today there is none.  A fetcher signals its outcome by exit code — ``0``
success, ``1`` soft failure, ``2`` schema/shape regression — and that
convention is stated in every fetcher docstring but exists nowhere as data.
Two consequences, both measured:

* ``.github/workflows/scheduled-refresh.yml::run_fetcher`` branches on
  ``if "$@"``, so **exit 1 and exit 2 are the same event**: neither stamps
  ``data/scrape_state/<key>_last_success``.  The schema-regression signal the
  fetchers take care to raise is discarded before any observer sees it.
* Nothing downstream can tell *why* a source is absent.  A source that failed
  to authenticate, a source whose HTML changed shape, and a source that
  genuinely published nothing all arrive as the same silence.

That last one is the failure this module exists to make impossible.  **A
failed acquisition is not a healthy empty source**, and the only structural
way to hold that line is to refuse to represent one as the other — see
:class:`AcquisitionOutcome`, which will not let a non-healthy state carry a
row count at all.

The states
──────────

``HEALTHY``      the board was acquired and is complete enough to use.
``PARTIAL``      acquired, but a declared portion is missing (e.g. one
                 position family absent).  Usable, with the gap named.
``STALE``        the last acquisition succeeded but is older than its budget.
                 The rows are real; their currency is not.
``UNAVAILABLE``  the source could not be reached.  Nothing was acquired.
``AUTH_REQUIRED``  the source exists and needs credentials this environment
                 does not hold.  Deliberately NOT ``UNAVAILABLE``: one is
                 fixed by waiting, the other by an owner action.
``PARSE_FAILED`` a response arrived and could not be understood.
``SCHEMA_CHANGED``  a response arrived, was understood, and did not contain
                 what it used to.  Distinct from ``PARSE_FAILED`` because the
                 remedy is different: one is a bug, the other is the vendor
                 moving.
``NO_CROSS_POSITION_COVERAGE``  the board was acquired successfully and does
                 not connect offense to IDP.  This is a statement about the
                 CONTENT, not the acquisition, and it is here because it is
                 the reason a perfectly healthy source may still not bridge.

Freshness is deliberately not re-derived here.  ``STALE`` is an outcome a
caller may record, but the rule that decides it lives in
``scripts/watchdog_freshness.classify_freshness`` and stays there — a second
freshness rule is exactly what that module's docstring forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ACQUISITION_STATES",
    "AUTH_REQUIRED",
    "AcquisitionOutcome",
    "HEALTHY",
    "NO_CROSS_POSITION_COVERAGE",
    "PARSE_FAILED",
    "PARTIAL",
    "SCHEMA_CHANGED",
    "STALE",
    "UNAVAILABLE",
    "USABLE_ACQUISITION_STATES",
    "state_from_exit_code",
]


HEALTHY = "HEALTHY"
PARTIAL = "PARTIAL"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
PARSE_FAILED = "PARSE_FAILED"
SCHEMA_CHANGED = "SCHEMA_CHANGED"
NO_CROSS_POSITION_COVERAGE = "NO_CROSS_POSITION_COVERAGE"

ACQUISITION_STATES: frozenset[str] = frozenset(
    {
        HEALTHY,
        PARTIAL,
        STALE,
        UNAVAILABLE,
        AUTH_REQUIRED,
        PARSE_FAILED,
        SCHEMA_CHANGED,
        NO_CROSS_POSITION_COVERAGE,
    }
)

#: States whose rows may be consumed.  ``STALE`` is excluded on purpose: the
#: rows exist and are readable, but consuming them as CURRENT is the defect.
#: A caller that genuinely wants stale rows asks for them by name.
USABLE_ACQUISITION_STATES: frozenset[str] = frozenset({HEALTHY, PARTIAL})

#: States that describe a failure to acquire, as opposed to a property of what
#: was acquired.  These may never carry a row count — see ``__post_init__``.
_FAILURE_STATES: frozenset[str] = frozenset(
    {UNAVAILABLE, AUTH_REQUIRED, PARSE_FAILED, SCHEMA_CHANGED}
)


class AcquisitionStateError(ValueError):
    """An outcome was constructed that cannot be true."""


def state_from_exit_code(code: int, *, schema_regression_code: int = 2) -> str:
    """Map a fetcher's exit code onto a state.

    This is the ONE place the repo's ``0 / 1 / 2`` convention is turned into
    data.  It is deliberately lossy in the honest direction: exit ``1`` is
    documented as "fetch or parse error", which could be either
    ``UNAVAILABLE`` or ``PARSE_FAILED``, so it reports ``PARSE_FAILED`` only
    when the fetcher says so and otherwise the weaker ``UNAVAILABLE``.  A
    fetcher that knows better should construct the outcome directly rather
    than round-tripping through an integer.
    """
    if code == 0:
        return HEALTHY
    if code == schema_regression_code:
        return SCHEMA_CHANGED
    return UNAVAILABLE


@dataclass(frozen=True)
class AcquisitionOutcome:
    """One attempt to acquire one source's board.

    ``row_count`` is ``int | None`` and the distinction is load-bearing:
    ``None`` means "we did not get a board", ``0`` means "we got a board and
    it was empty".  Those are different facts with different remedies, and
    collapsing them is how a broken scraper reads as a quiet week.

    The constructor enforces it.  A failure state carrying a row count raises
    rather than being silently corrected, because a corrected value would be
    indistinguishable from a real one.
    """

    source_key: str
    state: str
    reason: str = ""
    detail: str = ""
    row_count: int | None = None
    observed_at: str = ""
    #: Free-form, adapter-owned.  Never consulted for a decision.
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in ACQUISITION_STATES:
            raise AcquisitionStateError(
                f"{self.source_key}: unknown acquisition state {self.state!r}; "
                f"expected one of {sorted(ACQUISITION_STATES)}"
            )
        if self.state in _FAILURE_STATES and self.row_count is not None:
            raise AcquisitionStateError(
                f"{self.source_key}: state {self.state} cannot carry rowCount="
                f"{self.row_count}. Nothing was acquired, so there is no count — "
                "a failed acquisition must not be representable as an empty board."
            )
        if self.state in _FAILURE_STATES and not self.reason:
            raise AcquisitionStateError(
                f"{self.source_key}: state {self.state} requires a reason. "
                "An unexplained failure is the thing this vocabulary exists to prevent."
            )
        if self.row_count is not None and self.row_count < 0:
            raise AcquisitionStateError(
                f"{self.source_key}: rowCount may not be negative ({self.row_count})"
            )

    @property
    def usable(self) -> bool:
        """May the rows from this acquisition be consumed as current?"""
        return self.state in USABLE_ACQUISITION_STATES

    @property
    def acquired(self) -> bool:
        """Did a board arrive at all, whatever its currency or completeness?"""
        return self.state not in _FAILURE_STATES

    def to_dict(self) -> dict[str, Any]:
        """camelCase for the API/contract surfaces."""
        out: dict[str, Any] = {
            "sourceKey": self.source_key,
            "state": self.state,
            "usable": self.usable,
            "acquired": self.acquired,
            "rowCount": self.row_count,
        }
        if self.reason:
            out["reason"] = self.reason
        if self.detail:
            out["detail"] = self.detail
        if self.observed_at:
            out["observedAt"] = self.observed_at
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out
