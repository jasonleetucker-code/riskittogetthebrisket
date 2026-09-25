"""As-of queries over the analyst claim ledger — never future, missing ≠ empty.

THE question this module answers: *what did analyst / source X say about
asset Y as of T?*  Consumers (Player File intelligence, ingestion
consumers, the homepage ticker, Weekly Report Studio) call this typed
interface; none of them reads ``data/analyst_ledger.sqlite`` directly.

It mirrors ``src.history.asof`` (C1-U4) and reuses its fidelity vocabulary
(``exact`` / ``nearest-prior`` / ``unavailable``) rather than minting a
second one.  It does not reuse that module's query functions: those read the
temporal ledger's value/rank columns, and a stance is neither.

Two bases, and the caller must choose — there is deliberately no default,
because the two questions have different correct answers:

``Basis.SAID``   the public record as of T, read with today's corrections.
                 A claim is visible when it was said AND its content was
                 published at or before T.  Right for "what had X said by
                 T" (analyst accuracy, Weekly Report retrospectives).  A
                 content item backfilled today answers a past T under this
                 basis — exactly as an archive backfill answers a past date
                 in ``src.history``: the producer's own time claim is the
                 temporal key, and ``recorded_at`` is provenance.
``Basis.KNOWN``  replay: what THIS LEDGER held at T.  Adds
                 ``recorded_at <= T`` for claims and content, and applies a
                 correction only from the instant it was recorded.  Right
                 for reproducing what a consumer would have been served at T.

Never future, under both bases: every predicate is "at or before T" and no
API accepts an undirected "nearest".  Precision is honoured conservatively,
as ``src.history.asof.value_known_before`` does for unknown instants: a
``day``-precision stamp answers a DATE query for its own day, but an INSTANT
query only from the following day — "said sometime on Tuesday" is not
provably before Tuesday 10:00.

``as_of`` is either a ``date`` / ``YYYY-MM-DD`` string (end of that UTC day)
or a timezone-aware ``datetime`` / ISO instant.  A naive instant is refused.

Missing is never empty — three distinct statuses:

``claims``       at least one visible claim (``NO_SIGNAL`` is a claim: "we
                 listened and there was no call" is an answer);
``empty``        content in scope was covered by extraction at/before T and
                 contained no claim about this asset;
``unavailable``  no answer, with a machine-readable reason —
                 ``no_ledger`` (nothing was ever recorded) or
                 ``no_coverage_at_or_before`` (no covered content in scope).

Thesis collapse, syndication and analyst retractions are NOT re-implemented
here: :meth:`ClaimsAsOf.independent` delegates to
``src.analyst.claim.independent_claims`` over the claims visible at T, so a
retraction said after T can never hide a claim as of T.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.analyst.claim import AnalystClaim, dynasty_claims, independent_claims
from src.analyst.store import (
    LedgerError,
    StoredClaim,
    TimePrecision,
    connect_readonly,
    stored_claim_from_row,
)
from src.history.asof import FIDELITY_EXACT, FIDELITY_NEAREST_PRIOR, FIDELITY_UNAVAILABLE

STATUS_CLAIMS = "claims"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"

REASON_NO_LEDGER = "no_ledger"
REASON_NO_COVERAGE = "no_coverage_at_or_before"
#: Visible claims existed but every one was superseded by another visible
#: claim (a self-referencing retraction chain).  Reported, never guessed.
REASON_ALL_SUPERSEDED = "all_superseded"


class Basis(str, Enum):
    SAID = "said"
    KNOWN = "known"


@dataclass(frozen=True)
class AsOf:
    """A normalised as-of bound: exactly one of ``day`` / ``instant``."""

    day: date | None = None
    instant: datetime | None = None

    @property
    def utc_date(self) -> date:
        if self.day is not None:
            return self.day
        assert self.instant is not None
        return self.instant.date()

    @property
    def granularity(self) -> str:
        return "day" if self.day is not None else "instant"

    def iso(self) -> str:
        return self.day.isoformat() if self.day is not None else self.instant.isoformat()  # type: ignore[union-attr]

    def admits(self, stamp: datetime, precision: TimePrecision = TimePrecision.INSTANT) -> bool:
        """Is ``stamp`` (UTC, at ``precision``) provably at or before this bound?"""
        if self.day is not None:
            return stamp.date() <= self.day
        assert self.instant is not None
        if precision is TimePrecision.DAY:
            return stamp.date() < self.instant.date()
        return stamp <= self.instant


def parse_as_of(value: date | datetime | str) -> AsOf:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise LedgerError("naive as-of instant; pass a UTC-aware datetime or a date")
        return AsOf(instant=value.astimezone(timezone.utc))
    if isinstance(value, date):
        return AsOf(day=value)
    text = str(value).strip()
    if len(text) == 10:
        try:
            return AsOf(day=date.fromisoformat(text))
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise LedgerError(
            f"unparseable as-of {value!r}; expected YYYY-MM-DD or a UTC-aware ISO-8601 instant"
        ) from None
    return parse_as_of(parsed)


@dataclass(frozen=True)
class ClaimsAsOf:
    """Every claim in scope visible as of T, oldest first."""

    asset_key: str
    as_of: AsOf
    basis: Basis
    status: str
    missing_reason: str | None
    claims: tuple[StoredClaim, ...]
    covered_content: int
    analyst_id: str | None = None
    platform: str | None = None
    show_id: str | None = None

    def independent(self, *, dynasty_only: bool = False) -> list[AnalystClaim]:
        """One claim per (analyst, asset, thesis), retractions applied —
        delegated to the claim owner.  ``dynasty_only`` applies the claim
        owner's fail-closed dynasty gate first."""
        pool = [s.claim for s in self.claims]
        if dynasty_only:
            pool = dynasty_claims(pool)
        return independent_claims(pool)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assetKey": self.asset_key,
            "asOf": self.as_of.iso(),
            "asOfGranularity": self.as_of.granularity,
            "basis": self.basis.value,
            "status": self.status,
            "missingReason": self.missing_reason,
            "coveredContent": self.covered_content,
            "analystId": self.analyst_id,
            "platform": self.platform,
            "showId": self.show_id,
            "claims": [c.to_dict() for c in self.claims],
        }


@dataclass(frozen=True)
class StanceAsOf:
    """One analyst's latest surviving take on one asset as of T."""

    asset_key: str
    analyst_id: str
    as_of: AsOf
    basis: Basis
    status: str
    fidelity: str
    missing_reason: str | None
    claim: StoredClaim | None
    distance_days: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assetKey": self.asset_key,
            "analystId": self.analyst_id,
            "asOf": self.as_of.iso(),
            "asOfGranularity": self.as_of.granularity,
            "basis": self.basis.value,
            "status": self.status,
            "fidelity": self.fidelity,
            "missingReason": self.missing_reason,
            "distanceDays": self.distance_days,
            "claim": self.claim.to_dict() if self.claim is not None else None,
        }


def _content_visible(row: sqlite3.Row, bound: AsOf, basis: Basis, prefix: str = "") -> bool:
    published = datetime.fromisoformat(row[f"{prefix}published_at"])
    precision = TimePrecision(row[f"{prefix}published_precision"])
    if not bound.admits(published, precision):
        return False
    if basis is Basis.KNOWN:
        return bound.admits(datetime.fromisoformat(row[f"{prefix}recorded_at"]))
    return True


def claims_as_of(
    asset_key: str,
    as_of: date | datetime | str,
    *,
    basis: Basis | str,
    analyst_id: str | None = None,
    platform: str | None = None,
    show_id: str | None = None,
    path: Path | None = None,
) -> ClaimsAsOf:
    """Claims about ``asset_key`` visible as of ``as_of``, optionally scoped
    to one analyst and/or one source (platform, show)."""
    bound = parse_as_of(as_of)
    basis = Basis(basis)

    def result(status: str, reason: str | None, claims=(), covered=0) -> ClaimsAsOf:
        return ClaimsAsOf(
            asset_key=asset_key,
            as_of=bound,
            basis=basis,
            status=status,
            missing_reason=reason,
            claims=tuple(claims),
            covered_content=covered,
            analyst_id=analyst_id,
            platform=platform,
            show_id=show_id,
        )

    conn = connect_readonly(path)
    if conn is None:
        return result(STATUS_UNAVAILABLE, REASON_NO_LEDGER)
    try:
        q = (
            "SELECT c.*, k.published_at AS k_published_at, "
            "k.published_precision AS k_published_precision, k.recorded_at AS k_recorded_at "
            "FROM claims c JOIN content k ON k.platform=c.platform AND k.content_id=c.content_id "
            "WHERE c.asset_key=?"
        )
        params: list[Any] = [asset_key]
        if analyst_id is not None:
            q += " AND c.analyst_id=?"
            params.append(analyst_id)
        if platform is not None:
            q += " AND c.platform=?"
            params.append(platform)
        if show_id is not None:
            q += " AND k.show_id=?"
            params.append(show_id)
        claim_rows = conn.execute(q, params).fetchall()

        corrections: dict[int, datetime] = {}
        ids = [int(r["id"]) for r in claim_rows]
        if ids:
            marks = ",".join("?" for _ in ids)
            for r in conn.execute(
                f"SELECT superseded_id, recorded_at FROM corrections WHERE superseded_id IN ({marks})",
                ids,
            ).fetchall():
                corrections[int(r["superseded_id"])] = datetime.fromisoformat(r["recorded_at"])

        cq = "SELECT k.* FROM content k"
        cparams: list[Any] = []
        if analyst_id is not None:
            cq += " JOIN content_analysts a ON a.content_row_id=k.id AND a.analyst_id=?"
            cparams.append(analyst_id)
        cq += " WHERE 1=1"
        if platform is not None:
            cq += " AND k.platform=?"
            cparams.append(platform)
        if show_id is not None:
            cq += " AND k.show_id=?"
            cparams.append(show_id)
        content_rows = conn.execute(cq, cparams).fetchall()
    finally:
        conn.close()

    visible: list[StoredClaim] = []
    for row in claim_rows:
        if not _content_visible(row, bound, basis, prefix="k_"):
            continue
        stored = stored_claim_from_row(row)
        if not bound.admits(stored.claim.said_at, stored.said_at_precision):
            continue
        if basis is Basis.KNOWN and not bound.admits(stored.recorded_at):
            continue
        corrected_at = corrections.get(stored.ledger_id)
        if corrected_at is not None and (basis is Basis.SAID or bound.admits(corrected_at)):
            continue
        visible.append(stored)
    visible.sort(key=lambda s: (s.claim.said_at, s.ledger_id))

    covered = sum(1 for r in content_rows if _content_visible(r, bound, basis))
    if visible:
        return result(STATUS_CLAIMS, None, visible, covered)
    if covered:
        return result(STATUS_EMPTY, None, (), covered)
    return result(STATUS_UNAVAILABLE, REASON_NO_COVERAGE)


def stance_as_of(
    asset_key: str,
    analyst_id: str,
    as_of: date | datetime | str,
    *,
    basis: Basis | str,
    path: Path | None = None,
) -> StanceAsOf:
    """What did ``analyst_id`` say about ``asset_key`` as of ``as_of``?

    The latest surviving claim after thesis collapse and retractions
    (``independent_claims`` over the claims visible at T).  Fidelity is
    ``exact`` when it was said on the as-of UTC date, else ``nearest-prior``
    with its distance in days.  No freshness judgement is made: how old is
    too old is take-type-aware policy (C6-FRESH-01), not this layer's.
    """
    found = claims_as_of(asset_key, as_of, basis=basis, analyst_id=analyst_id, path=path)

    def answer(status, fidelity, reason, claim=None, distance=None) -> StanceAsOf:
        return StanceAsOf(
            asset_key=asset_key,
            analyst_id=analyst_id,
            as_of=found.as_of,
            basis=found.basis,
            status=status,
            fidelity=fidelity,
            missing_reason=reason,
            claim=claim,
            distance_days=distance,
        )

    if found.status != STATUS_CLAIMS:
        return answer(found.status, FIDELITY_UNAVAILABLE, found.missing_reason)

    survivors = {id(c) for c in independent_claims(s.claim for s in found.claims)}
    candidates = [s for s in found.claims if id(s.claim) in survivors]
    if not candidates:
        return answer(STATUS_UNAVAILABLE, FIDELITY_UNAVAILABLE, REASON_ALL_SUPERSEDED)
    latest = max(candidates, key=lambda s: (s.claim.said_at, s.ledger_id))
    distance = (found.as_of.utc_date - latest.claim.said_at.date()).days
    fidelity = FIDELITY_EXACT if distance == 0 else FIDELITY_NEAREST_PRIOR
    return answer(STATUS_CLAIMS, fidelity, None, latest, distance)
