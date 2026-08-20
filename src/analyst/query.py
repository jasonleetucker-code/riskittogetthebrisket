"""As-of reads over the analyst claim ledger (C6-ANA-01).

No shared "as-of" library exists independent of ``src.history.asof``'s
value/rank-hardcoded column reads (its ``_SELECT_COLS``/``_result_from_row``
bake in ``value``/``rank``/``tier``/``confidence`` — the wrong shape for a
text/stance claim). Established precedent for a new evidence class
(``src.retention.evidence_store.scoring_card_at``,
``src.acquisition.roster.roster_at``) is to hand-roll a sibling
as-of function in the same IDIOM rather than generalizing that module —
this file does the same: never-future, deterministic, explicit about
what it excludes and why.

THE NEVER-FUTURE GUARANTEE, PRECISELY
────────────────────────────────────────
A claim is visible as of instant D only when BOTH:

* ``said_at <= D`` — the analyst had actually said it by D, and
* ``effective_discovered_at <= D`` — WE had actually recorded it by D,
  where ``effective_discovered_at = claim.discovered_at or entry.recorded_at``.

The second condition is the one that is easy to get wrong, and is the
whole reason this module exists rather than a one-line filter on
``said_at`` alone: an analyst could have said something on Monday that
this platform did not ingest until Thursday, and a query asked for
"Tuesday" must not see it — the discovery window is not the voting
window (owner spec §4.19, `docs/analyst/CLAIM_SCHEMA.md`). Falling back
to ``entry.recorded_at`` (the LEDGER's own insertion instant, always
present, never optional) when a claim carries no ``discovered_at`` means
the guarantee holds even before any extractor populates that field —
there is no code path where a missing ``discovered_at`` degrades into
"skip the check."
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.analyst.claim import AnalystClaim, independent_claims
from src.analyst.store import LedgerEntry, claims_for_asset

__all__ = ["claims_as_of", "independent_claims_as_of"]


def _require_aware(on_instant: datetime) -> datetime:
    if on_instant.tzinfo is None or on_instant.utcoffset() is None:
        raise ValueError(
            "claims_as_of requires a timezone-aware instant — a naive datetime "
            "is not a proven point in time (mirrors src.history.asof's own "
            "instant-strict discipline)"
        )
    return on_instant


def _effective_discovered_at(entry: LedgerEntry) -> datetime:
    """The real upper bound on when we could have known this claim.

    NEVER returns None and never falls back to a sentinel like
    ``datetime.min`` — that would make every claim visible at every
    instant, which is the exact leak this module exists to prevent. The
    ledger's own ``recorded_at`` is always present (stamped by the store
    on write, never left unset), so this always resolves to a real
    timestamp.
    """
    if entry.claim.discovered_at is not None:
        return entry.claim.discovered_at
    assert entry.recorded_at is not None, (
        "a stored LedgerEntry always carries recorded_at — the store stamps it "
        "on every write; a None here means the row did not come through "
        "src.analyst.store, which is a caller bug, not a data gap"
    )
    return entry.recorded_at


def claims_as_of(
    asset_key: str,
    on_instant: datetime,
    *,
    include_superseded: bool = False,
    path: Path | None = None,
) -> list[LedgerEntry]:
    """Every stored claim about ``asset_key`` visible as of ``on_instant``.

    Ordered oldest ``said_at`` first. Superseded claims (any claim whose
    ``content_id`` appears in another visible claim's ``supersedes``
    field) are excluded unless ``include_superseded=True`` — matching
    ``AnalystClaim``'s own ``supersedes`` semantics
    (``independent_claims()``'s docstring: "a retraction is not outvoted
    by its own original").
    """
    on_instant = _require_aware(on_instant)
    entries = claims_for_asset(asset_key, path=path)
    visible = [
        e
        for e in entries
        if e.claim.said_at <= on_instant and _effective_discovered_at(e) <= on_instant
    ]
    if include_superseded:
        return visible
    superseded_content_ids = {
        e.claim.supersedes for e in visible if str(e.claim.supersedes).strip()
    }
    return [e for e in visible if e.claim.source.content_id not in superseded_content_ids]


def independent_claims_as_of(
    asset_key: str,
    on_instant: datetime,
    *,
    path: Path | None = None,
) -> list[AnalystClaim]:
    """``claims_as_of(...)`` piped through the EXISTING thesis-lineage
    collapse in ``src.analyst.claim.independent_claims`` — reused, not
    re-implemented, so the one-analyst-one-vote rule (§4.16) and the
    syndication collapse (§4.20) stay owned by a single function."""
    entries = claims_as_of(asset_key, on_instant, path=path)
    return independent_claims(e.claim for e in entries)
