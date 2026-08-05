"""A value that is not known, and refuses to pretend otherwise.

WHY THIS EXISTS
---------------
The 2026-08-04 audit's largest cross-cutting pattern, found in **every**
subsystem it examined:

    "Missing data resolves to an optimistic, neutral or fabricated
     value instead of abstention."

The consequences are not subtle.  A team absent from a sim file becomes
``or 0.0`` playoff odds and is told to **sell** — and the roster that
happened to be absent was ranked #1 in the league on ROS strength.  An
unknown FAAB budget became ``$100``.  An unresolvable asset was priced
at ``1.0`` and publicly graded a fleecing, *with the losing manager
named*.  Unknown starter slots became "half the position group".
Confidence was RAISED by missing sources.

Every one of those is the same substitution: a number stood in for an
absence, and nothing downstream could tell the difference.

WHAT MAKES THIS DIFFERENT FROM ``None``
----------------------------------------
``None`` is already available and did not prevent any of the above,
because ``None`` is silently coercible — ``x or 0``, ``float(x or 0)``,
``sum(...)`` over a list containing it.  The whole defect class lives in
that coercion.

So this type is **arithmetically inert**: every numeric operator raises
:class:`UnknownArithmeticError`.  You cannot add it, average it, or
compare it into a threshold by accident.  The failure is loud, at the
point of the mistake, instead of silent and 400 lines downstream.

It is also deliberately **not falsy**.  Making it falsy would let
``value or 0`` keep working, which is the exact expression this exists
to eliminate.  ``bool(Unknown(...))`` raises too.

HOW IT REACHES THE USER
-----------------------
:func:`stamp` writes the API convention: the field serializes to
``null``, and a sibling ``<field>Unknown`` carries the machine-readable
reason.  A dash on screen is not enough — "we don't know" and "zero"
look identical otherwise, and the frontend needs to render *why*.

This is the same posture BDVM already takes with ``unpriced`` +
a reason (``src/bdvm/service.py``, ``src/bdvm/roster.py``), and that
``src/trade/finder.py`` takes with ``metadata.assetsUnpricedByBoard``.
Those were the audit's examples of the pattern done RIGHT; this
promotes them to a shared type so the rest of the codebase can adopt
it without re-deciding the semantics each time.

AGGREGATES
----------
:func:`aggregate` is the sanctioned way to reduce a mixed list.  It
returns the statistic over the known values **and the count it
excluded**, because "the average of the 8 teams we could measure" and
"the average of 12 teams" are different claims and the second one is
what the audit kept finding published.
"""

from __future__ import annotations

import statistics

# ``field`` is aliased because this dataclass has an attribute of the
# same name (the field being measured), which otherwise shadows
# dataclasses.field and breaks default_factory at class-definition time.
from dataclasses import dataclass, field as _dc_field
from typing import Any, Callable, Iterable, Sequence


class UnknownArithmeticError(TypeError):
    """Raised when code tries to use an Unknown as if it were a number.

    Carries the reason, because the traceback is usually the first time
    anyone learns the value was missing at all.
    """

    def __init__(self, unknown: "Unknown", operation: str) -> None:
        super().__init__(
            f"cannot {operation} an unknown value: {unknown.reason}"
            + (f" (field: {unknown.field})" if unknown.field else "")
            + ". Handle the absence explicitly — see src/utils/unknown.py."
        )
        self.unknown = unknown
        self.operation = operation


@dataclass(frozen=True)
class Unknown:
    """An absent measurement, carrying why it is absent.

    ``reason`` is machine-readable and short (``"team_absent_from_sim"``,
    ``"no_remaining_schedule"``).  ``detail`` is for humans.  ``field``
    names what was being measured, so an error raised three frames away
    still says what went missing.
    """

    reason: str
    detail: str | None = None
    field: str | None = None
    context: dict[str, Any] = _dc_field(default_factory=dict)

    # ── Arithmetic is refused, loudly ──────────────────────────────────
    #
    # Every one of these exists because the audit found the silent
    # version of it in production.  ``__bool__`` is included on purpose:
    # without it, ``value or 0`` — the single most common form of this
    # defect — would keep working exactly as before.
    def _refuse(self, operation: str):
        raise UnknownArithmeticError(self, operation)

    def __bool__(self):
        self._refuse("take the truthiness of")

    def __float__(self):
        self._refuse("convert to float")

    def __int__(self):
        self._refuse("convert to int")

    def __add__(self, other):
        self._refuse("add")

    __radd__ = __add__

    def __sub__(self, other):
        self._refuse("subtract")

    __rsub__ = __sub__

    def __mul__(self, other):
        self._refuse("multiply")

    __rmul__ = __mul__

    def __truediv__(self, other):
        self._refuse("divide")

    __rtruediv__ = __truediv__

    def __lt__(self, other):
        self._refuse("compare")

    def __le__(self, other):
        self._refuse("compare")

    def __gt__(self, other):
        self._refuse("compare")

    def __ge__(self, other):
        self._refuse("compare")

    def __round__(self, ndigits=None):
        self._refuse("round")

    def as_payload(self) -> dict[str, Any]:
        """The machine-readable half of the API convention."""
        out: dict[str, Any] = {"reason": self.reason}
        if self.detail:
            out["detail"] = self.detail
        if self.context:
            out["context"] = dict(self.context)
        return out


def is_unknown(value: Any) -> bool:
    return isinstance(value, Unknown)


def stamp(payload: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Write ``value`` under ``key``, following the API convention.

    A known value is written plainly.  An Unknown writes ``null`` **and**
    a sibling ``<key>Unknown`` object — because a bare ``null`` is
    indistinguishable from a field the producer forgot, and the frontend
    has to be able to render *why* rather than just a dash.
    """
    if is_unknown(value):
        payload[key] = None
        payload[f"{key}Unknown"] = value.as_payload()
    else:
        payload[key] = value
        payload.pop(f"{key}Unknown", None)
    return payload


def aggregate(
    values: Iterable[Any],
    reducer: Callable[[Sequence[float]], float] = statistics.fmean,
    *,
    reason_when_empty: str = "no_known_values",
    field_name: str | None = None,
) -> tuple[Any, int]:
    """Reduce a list that may contain Unknowns.

    Returns ``(result, excluded_count)``.  The count is not optional and
    not a nicety: the audit repeatedly found aggregates published as
    though they covered everything when they silently covered a subset.
    A caller that ignores the second element is making a claim it has
    not checked, and the shape of this signature is meant to make that
    obvious in review.

    With no known values at all the result is an Unknown rather than
    ``0`` — an average of nothing is not zero.
    """
    known: list[float] = []
    excluded = 0
    for value in values:
        if is_unknown(value) or value is None:
            excluded += 1
            continue
        try:
            known.append(float(value))
        except (TypeError, ValueError):
            excluded += 1
    if not known:
        return (
            Unknown(
                reason=reason_when_empty,
                detail=f"all {excluded} input value(s) were unknown or unusable",
                field=field_name,
            ),
            excluded,
        )
    return reducer(known), excluded
