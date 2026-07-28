"""Record what a measurement was computed FROM, alongside the number.

A derived constant is only as good as the inputs it was derived from,
and inputs get fixed after the fact. On 2026-07-28 the IDP positional
scoring multipliers shipped with DB and DL the wrong way round, because
they were measured on a scoring card where one Sleeper key alias had
been repaired and a second had not. Nothing about the number said so.
It was caught by reading an unrelated document.

**A hash alone would not have caught it.** "The inputs changed" is only
actionable once someone re-derives and compares, which is the work the
hash was supposed to save. What was actually needed is narrower and more
useful: *were the inputs known to be incomplete at the moment of
measurement?* They were — seven scoring rules the engine could read and
did not. A measurement carrying that count would have been visibly
suspect on the day it was taken.

So a :class:`Provenance` records both:

* ``input_digest`` — answers "is this stale?"
* ``input_gaps`` / ``input_unscorable`` — answers "was this measured on
  a complete input?", which is the question that mattered.

The second field is what makes this more than bookkeeping. It is
deliberately a **count of known-missing inputs**, not a quality score:
counts are checkable, and a partial input is disproportionately
dangerous for a *relative* measurement, where a gap that hits one
category and not another inverts an ordering rather than merely shifting
a level.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


def input_digest(*inputs: Any) -> str:
    """A stable short digest of the inputs a measurement consumed.

    Sorted-key JSON so dict ordering cannot change the digest, and
    ``default=str`` so an unexpected type degrades to something stable
    rather than raising inside a diagnostic.
    """
    blob = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Provenance:
    """What a measurement was computed from."""

    input_digest: str = ""
    """Digest of the measurement's inputs; changes when they change."""

    input_gaps: tuple[str, ...] = ()
    """Scoring rules the engine COULD score and did not, at measurement
    time. Non-empty means the number is suspect — this is the field that
    would have flagged the inverted IDP tilt."""

    input_unscorable: tuple[str, ...] = ()
    """Rules no available data can reconstruct. Not a defect, but still
    a known understatement the number inherits."""

    rows_scored: int = 0
    notes: str = ""

    @property
    def inputs_complete(self) -> bool:
        """True when nothing the engine could have read was missed.

        ``input_unscorable`` deliberately does NOT count against this:
        those cannot be fixed by a code change, so treating them as
        incompleteness would make the flag permanently red and therefore
        ignored.
        """
        return not self.input_gaps

    def to_dict(self) -> dict[str, Any]:
        return {
            "inputDigest": self.input_digest,
            "inputsComplete": self.inputs_complete,
            "inputGaps": list(self.input_gaps),
            "inputUnscorable": list(self.input_unscorable),
            "rowsScored": self.rows_scored,
            "notes": self.notes,
        }


def scoring_provenance(
    *scoring_cards: Mapping[str, Any] | None,
    rows_scored: int = 0,
    notes: str = "",
) -> Provenance:
    """Build a :class:`Provenance` for a measurement driven by Sleeper
    scoring cards.

    The union of gaps across every card is recorded: a measurement that
    *compares* two leagues is compromised by an unread rule in either
    one, and for a relative quantity an asymmetric gap is the worst
    case.
    """
    from src.nfl_data.scoring_coverage import (  # noqa: PLC0415 - avoids an import cycle
        Coverage,
        audit_scoring_settings,
    )

    gaps: set[str] = set()
    unscorable: set[str] = set()
    for card in scoring_cards:
        if not card:
            continue
        audit = audit_scoring_settings(dict(card))
        gaps |= set(audit[Coverage.GAP])
        unscorable |= set(audit[Coverage.UNSCORABLE])

    return Provenance(
        input_digest=input_digest(*[dict(c) if c else {} for c in scoring_cards]),
        input_gaps=tuple(sorted(gaps)),
        input_unscorable=tuple(sorted(unscorable)),
        rows_scored=rows_scored,
        notes=notes,
    )


@dataclass
class _Unset:
    """Sentinel for a measurement that predates provenance stamping."""

    value: Provenance = field(default_factory=Provenance)
