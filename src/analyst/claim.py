"""What an analyst claim IS — the schema, before any ingestion exists.

Owner spec: ``OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`` §4.16 (stance
and context), §4.19 (podcast pipeline and freshness), §4.20 (YouTube reuses
this rather than growing a parallel one).  Tracked as **T-NEW-10**.

WHY THE SCHEMA COMES FIRST
──────────────────────────
An ingestion system built before the claim is defined ends up storing
whatever the first parser happened to produce, and every later question —
"is this dynasty?", "did he actually say that or did we infer it?", "is this
the same take he made last week?" — becomes unanswerable from the stored row.
Those answers are not recoverable later: the transcript may be gone, the
episode may be re-cut, and a model's paraphrase is indistinguishable from a
quote once it has been written down as one.

So this module defines the record and its invariants, and stops.  Nothing
reads it yet, and that is the intended sequencing rather than an oversight —
stated plainly here because this repo already carries one module that
described itself as a live single entry point while being imported by
nothing.

WHAT IT REFUSES TO DO
─────────────────────
No scoring, no weighting, no freshness constants.  Freshness is
*take-type-aware, event-aware and season-aware* per §4.19, which is a set of
inputs, not a number — fitting decay rates is evidence-gated work for
whatever engine consumes this, and inventing them here would bake a guess
into the schema everything else has to live with.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, Sequence

from src.analyst.stance import SourceLabel, Stance, requires_condition, stance_for_label


class Provenance(str, Enum):
    """How the platform came to believe the analyst said this.

    The distinction between the first three is load-bearing and cannot be
    reconstructed after the fact: once a paraphrase is stored without its
    provenance it is indistinguishable from a quote.
    """

    #: Words lifted from a transcript exactly.  Only this may be quoted.
    TRANSCRIPT_VERBATIM = "transcript_verbatim"
    #: A faithful restatement of transcript content.
    TRANSCRIPT_PARAPHRASE = "transcript_paraphrase"
    #: The platform's own reading of what was implied.  Never a quote, and
    #: the schema will not let it become one.
    MODEL_INFERENCE = "model_inference"
    #: A structured feed that publishes stances directly (a rankings delta,
    #: an article's own tag) — no transcript involved.
    STRUCTURED_FEED = "structured_feed"


class GameType(str, Enum):
    """The format the take was made ABOUT.

    ``UNKNOWN`` is not ``DYNASTY``.  CLAUDE.md's source-domain boundary is
    explicit that game type is proven per source and fails closed, and a
    redraft take reaching a dynasty conclusion is the same defect there as
    it is in the ranking pipeline.
    """

    DYNASTY = "dynasty"
    REDRAFT = "redraft"
    BEST_BALL = "best_ball"
    UNKNOWN = "unknown"


class AssetSide(str, Enum):
    """Offense, IDP or a pick.  Kept because the platform's own evidence
    domains split here — an offense-only panel cannot price a linebacker,
    the same limitation the external FAAB market carries."""

    OFFENSE = "offense"
    IDP = "idp"
    PICK = "pick"
    UNKNOWN = "unknown"


class TakeType(str, Enum):
    """§4.19's take types, which are what freshness is a function of.

    Enumerated here so a consumer can key a decay policy off a declared
    vocabulary instead of a free-text guess.  This module assigns no decay.
    """

    INJURY = "injury"
    ROLE = "role"
    GAME_SPECIFIC = "game_specific"
    POSTGAME_USAGE = "postgame_usage"
    BUY_SELL_VALUE = "buy_sell_value"
    DURABLE_THESIS = "durable_thesis"
    HISTORICAL_BACKGROUND = "historical_background"


@dataclass(frozen=True)
class Condition:
    """A stated trigger — "buy only if cheap", "sell for a 2027 second".

    §4.16 requires this context be preserved, and a conditional stance
    without one is not actionable, so the claim refuses to be built that way.
    """

    text: str
    kind: str = "unspecified"

    def __post_init__(self) -> None:
        if not str(self.text).strip():
            raise ValueError("a condition must state what the trigger is")


@dataclass(frozen=True)
class SourceRef:
    """Who said it, where, and in which piece of content.

    ``analyst_id`` and ``content_id`` are separate because syndication is
    the thing §4.20 exists to stop: the same take reaching us through a
    podcast and its YouTube cut is ONE opinion.  Deduplication keys on the
    analyst and the thesis, never on the platform.
    """

    analyst_id: str
    content_id: str
    platform: str
    show_id: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        for name in ("analyst_id", "content_id", "platform"):
            if not str(getattr(self, name)).strip():
                raise ValueError(
                    f"SourceRef.{name} is required — an unattributable take is not a claim"
                )


@dataclass(frozen=True)
class AnalystClaim:
    """One take, by one analyst, about one asset, at one time."""

    source: SourceRef
    asset_key: str
    stance: Stance
    source_label: SourceLabel
    take_type: TakeType
    said_at: datetime
    provenance: Provenance
    game_type: GameType = GameType.UNKNOWN
    asset_side: AssetSide = AssetSide.UNKNOWN
    conditions: tuple[Condition, ...] = ()
    #: The analyst's own words, permitted ONLY for verbatim provenance.
    quote: str = ""
    #: Stable id for the ARGUMENT, not the utterance.  Two airings of the
    #: same thesis share it and must count once; a genuinely changed mind
    #: gets a new one.  Supplied by extraction, which is the only layer that
    #: can tell those apart.
    thesis_id: str = ""
    #: When the platform first saw it.  Distinct from ``said_at`` because
    #: §4.19 is explicit that the discovery window is not the voting window.
    discovered_at: datetime | None = None
    #: A later claim this one supersedes (a retraction, or an update).
    supersedes: str = ""
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not str(self.asset_key).strip():
            raise ValueError("a claim must name the asset it is about")

        if requires_condition(self.stance) and not self.conditions:
            raise ValueError(
                f"{self.stance.value} is a conditional stance and must carry its trigger — "
                "'buy only if cheap' and 'buy' are different claims (owner spec §4.16)"
            )

        # A model's reading may never be presented as something the analyst
        # said.  This is the one invariant that cannot be repaired after
        # storage, so it is refused at construction.
        if self.quote and self.provenance is not Provenance.TRANSCRIPT_VERBATIM:
            raise ValueError(
                f"a quote requires {Provenance.TRANSCRIPT_VERBATIM.value} provenance, "
                f"not {self.provenance.value} — inference must never be quoted"
            )

    @property
    def is_dynasty_evidence(self) -> bool:
        """May this claim inform a DYNASTY conclusion?

        Only a claim proven to be about dynasty.  ``UNKNOWN`` fails closed,
        exactly as unverified game type does in the ranking pipeline.
        """
        return self.game_type is GameType.DYNASTY

    @property
    def is_explicit_call(self) -> bool:
        """Did the analyst make a call, or was this discussion?

        ``NO_SIGNAL`` is a real, reportable answer — "we listened and there
        was no call here" — and it is not an explicit call.
        """
        return self.stance is not Stance.NO_SIGNAL

    @property
    def thesis_key(self) -> str:
        """The identity used for one-analyst-one-vote.

        Keyed on the ANALYST, the ASSET and the THESIS — never on the
        content or the platform, so a podcast and its YouTube cut collapse,
        and so repeating a take weekly does not manufacture agreement.

        Without an explicit ``thesis_id`` the fallback is the analyst's
        stance on that asset: restating the same position is the same
        thesis until extraction says otherwise.  That direction is the safe
        one — it under-counts a genuinely new argument rather than
        inventing independent votes.
        """
        thesis = str(self.thesis_id).strip()
        if not thesis:
            thesis = f"stance:{self.stance.value}"
        raw = f"{self.source.analyst_id}|{self.asset_key}|{thesis}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, object]:
        return {
            "analystId": self.source.analyst_id,
            "contentId": self.source.content_id,
            "platform": self.source.platform,
            "showId": self.source.show_id,
            "url": self.source.url,
            "assetKey": self.asset_key,
            "stance": self.stance.value,
            "sourceLabel": self.source_label.value,
            "takeType": self.take_type.value,
            "saidAt": self.said_at.isoformat(),
            "discoveredAt": self.discovered_at.isoformat() if self.discovered_at else None,
            "provenance": self.provenance.value,
            "gameType": self.game_type.value,
            "assetSide": self.asset_side.value,
            "isDynastyEvidence": self.is_dynasty_evidence,
            "isExplicitCall": self.is_explicit_call,
            "conditions": [{"text": c.text, "kind": c.kind} for c in self.conditions],
            "quote": self.quote,
            "thesisId": self.thesis_id,
            "thesisKey": self.thesis_key,
            "supersedes": self.supersedes,
            "tags": list(self.tags),
            "notes": self.notes,
        }


def claim_from_label(
    label: SourceLabel,
    **kwargs: object,
) -> AnalystClaim:
    """Build a claim from the source's own word, translating once.

    The canonical stance is DERIVED here so no caller has to remember the
    mapping, and the label is retained on the record so the source's meaning
    survives (``SLEEPER`` and ``STASH`` both exist for a reason).
    """
    return AnalystClaim(stance=stance_for_label(label), source_label=label, **kwargs)  # type: ignore[arg-type]


def independent_claims(claims: Iterable[AnalystClaim]) -> list[AnalystClaim]:
    """Collapse to one claim per thesis — the input any tally needs.

    §4.16: *"Repeated takes from the same analyst/thesis lineage must not
    become independent votes."*  §4.20 adds the syndication case, which this
    covers for free because the key ignores platform and content entirely.

    The SURVIVOR is the most recent by ``said_at``, and a claim explicitly
    superseded by another in the same set is dropped regardless of date — a
    retraction is not outvoted by its own original.
    """
    ordered = sorted(claims, key=lambda c: c.said_at)
    superseded: set[str] = {c.supersedes for c in ordered if str(c.supersedes).strip()}
    survivors: dict[str, AnalystClaim] = {}
    for claim in ordered:
        if claim.source.content_id in superseded:
            continue
        survivors[claim.thesis_key] = claim  # later said_at wins
    return list(survivors.values())


def dynasty_claims(claims: Sequence[AnalystClaim]) -> list[AnalystClaim]:
    """Only claims PROVEN to be about dynasty.

    A convenience with a hard edge: it is the gate, not a filter a caller
    may skip when the sample looks thin.
    """
    return [c for c in claims if c.is_dynasty_evidence]
