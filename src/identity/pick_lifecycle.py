"""Draft-class lifecycle — THE owner of "is this rookie-draft class still an
active asset?" (issue #1414, owner decision 2026-09-24).

Sibling of :mod:`src.identity.picks` and owned by the same identity layer:
``picks`` says WHAT a pick asset is; this module says whether the class that
asset belongs to is still PRESENT-TENSE.  Neither module reads, computes or
stores a value.

The rule
========

A season's rookie-draft class is **retired** from active/current surfaces
only when real league state proves BOTH halves of the owner's definition:

1. **the draft is complete** — Sleeper reports ``status == "complete"`` for a
   draft of that season that is a ROOKIE draft, and no draft of that season
   is live (``drafting`` / ``paused``) or not yet started (``pre_draft``);
2. **the drafted rookies were consumed onto rosters** — at least
   :data:`CONSUMPTION_MIN_ROSTERED_SHARE` of the players picked in that
   season's completed rookie draft(s) are on the league's current rosters.

Everything else is **not** retirement.  Missing or unreadable evidence is
``UNKNOWN``, and ``UNKNOWN`` keeps the class active: the failure this rule
exists to prevent is a stale class lingering, but the failure it must never
cause is a live class vanishing from a trade calculator mid-season.  There is
no calendar date and no year literal anywhere in the decision — a future
season retires the moment its own evidence says so.

Three states, deliberately
--------------------------

* ``active``  — evidence says the class is live (draft not started or in
  progress).
* ``retired`` — both halves proven.
* ``unknown`` — no evidence, an unrecognized draft status, no completed
  ROOKIE draft, rosters unobserved, or consumption not proven.

Only ``retired`` changes behaviour (:func:`is_retired`).  ``active`` and
``unknown`` are kept separate because "we know it is live" and "we cannot
tell" are different statements, and the contract stamp reports which.

Why the thresholds are what they are
------------------------------------

* :data:`CONSUMPTION_MIN_ROSTERED_SHARE` = 0.5.  Sleeper places every drafted
  player on the drafter's roster the instant the draft completes, so the
  rostered share starts at 1.0 and decays only as managers release late
  picks.  Measured 2026-09-24 against the live leagues: the 2026 class is
  70/84 = 0.83 rostered in ``dynasty_main`` and 38/40 = 0.95 in
  ``dynasty_new`` four months after their drafts, and the 2025 class is still
  61/70 = 0.87 and 35/40 = 0.88 sixteen months on.  A completed draft whose
  picks never reached rosters (a mock, a reset, an offline draft recorded
  without assignment) sits near 0.  A majority separates the two regimes
  with wide margin on both sides; requiring 100% would never retire anything
  because one release blocks it forever.
* :data:`ROOKIE_DRAFT_MIN_ROOKIE_SHARE` = 0.5.  Only a ROOKIE draft can
  consume a rookie class — a completed startup or dispersal draft must not
  retire next year's picks.  Sleeper states it directly when
  ``settings.player_type == 1`` (rookies only; both live 2026 drafts); a
  mixed-pool draft (``player_type == 0``, the 2025 ``dynasty_main`` draft) is
  a rookie draft when most of its picks were rookies at pick time
  (``metadata.years_exp == "0"``: 58/70 = 0.83 measured).  A startup or
  dispersal draft is overwhelmingly veterans.

Two structural rules
--------------------

* **Completed drafts with no picks are ignored**, not treated as failures:
  ``dynasty_main`` carries a second 2026 draft object marked ``complete``
  with zero picks.  It consumed nothing and blocks nothing.
* **Supersession** (:func:`league_class_lifecycles`): if a LATER class is
  retired, an earlier class whose own evidence is merely ``unknown`` is
  retired too.  Rookie drafts run in season order, so a consumed 2027 class
  proves the 2026 picks were used.  This is what keeps a class retired after
  its league rolls over to a new Sleeper league id and the old draft leaves
  the current league's ``/drafts`` list.  It never overrides an ``active``
  verdict.

League scope vs board scope
===========================

Draft completion is a **leagueKey** fact; the canonical board is
**scoring-profile** scoped and may be served to every league proven to score
identically (CLAUDE.md, "Rankings vs. league context").  So two answers exist
and both are derived here from the one per-league predicate:

* **Per-league surfaces** (a league's own pick ownership, its draft capital)
  use THAT league's lifecycle — :func:`league_class_lifecycles`.
* **The board** (market pick rows such as ``"2026 Pick 1.01"`` /
  ``"2026 Early 1st"`` / ``"2026 Round 1"``) retires a class only when EVERY
  league the board may be served to proves retirement —
  :func:`board_class_lifecycle`.  Any league still ``active`` keeps it
  ``active``; any league ``unknown`` (including a league with no evidence at
  all) keeps it ``unknown``.  Which leagues count as "may be served" is the
  API layer's question (``src/api/draft_class_evidence.py``), answered
  fail-closed: a league is excluded only when its scoring is PROVEN different.

Retirement means ABSENT from present-tense selectors — never valued 0, never
rewritten.  History is untouched: :mod:`src.identity.picks` still parses every
retired pick name and id, the temporal ledger keeps every observation, and
past trades keep their stored labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "CONSUMPTION_MIN_ROSTERED_SHARE",
    "EVIDENCE_SCHEMA_VERSION",
    "LIFECYCLE_ACTIVE",
    "LIFECYCLE_RETIRED",
    "LIFECYCLE_UNKNOWN",
    "ROOKIE_DRAFT_MIN_ROOKIE_SHARE",
    "SLEEPER_ROOKIES_ONLY_PLAYER_TYPE",
    "ClassLifecycle",
    "DraftObservation",
    "LeagueDraftEvidence",
    "board_class_lifecycle",
    "draft_class_lifecycle",
    "evidence_from_sleeper",
    "first_active_class",
    "is_retired",
    "league_class_lifecycles",
    "retired_seasons",
]

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_RETIRED = "retired"
LIFECYCLE_UNKNOWN = "unknown"

#: Bumped only on a breaking change to :meth:`LeagueDraftEvidence.to_dict`.
EVIDENCE_SCHEMA_VERSION = 1

#: See the module docstring for the measurement behind both thresholds.
CONSUMPTION_MIN_ROSTERED_SHARE = 0.5
ROOKIE_DRAFT_MIN_ROOKIE_SHARE = 0.5

#: Sleeper ``draft.settings.player_type``: 0 = all players, 1 = rookies only.
SLEEPER_ROOKIES_ONLY_PLAYER_TYPE = 1

_STATUS_COMPLETE = "complete"
_STATUSES_LIVE = frozenset({"drafting", "paused"})
_STATUSES_NOT_STARTED = frozenset({"pre_draft"})


def _coerce_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── Evidence ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DraftObservation:
    """What one Sleeper draft object proves.  Counts, not player lists.

    ``None`` always means UNOBSERVED — never zero.  ``pick_count`` is
    ``None`` when the picks were not fetched (e.g. a live draft, or a fetch
    failure); ``rostered_pick_count`` is ``None`` when rosters were not
    observed; ``rookie_pick_count`` is ``None`` when the picks carried no
    ``years_exp`` metadata to count.
    """

    draft_id: str
    season: int | None
    status: str | None
    player_type: int | None = None
    pick_count: int | None = None
    rookie_pick_count: int | None = None
    rostered_pick_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "draftId": self.draft_id,
            "season": self.season,
            "status": self.status,
            "playerType": self.player_type,
            "pickCount": self.pick_count,
            "rookiePickCount": self.rookie_pick_count,
            "rosteredPickCount": self.rostered_pick_count,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DraftObservation | None":
        if not isinstance(raw, Mapping):
            return None
        draft_id = str(raw.get("draftId") or "").strip()
        if not draft_id:
            return None
        status = raw.get("status")
        return cls(
            draft_id=draft_id,
            season=_coerce_int(raw.get("season")),
            status=str(status).strip().lower() if status not in (None, "") else None,
            player_type=_coerce_int(raw.get("playerType")),
            pick_count=_coerce_int(raw.get("pickCount")),
            rookie_pick_count=_coerce_int(raw.get("rookiePickCount")),
            rostered_pick_count=_coerce_int(raw.get("rosteredPickCount")),
        )


@dataclass(frozen=True)
class LeagueDraftEvidence:
    """One league's observed draft state at ``observed_at``.

    Draft completion and roster consumption only ever move toward
    retirement, so an old observation can delay retirement but can never
    cause a premature one — which is why this evidence carries a timestamp
    for provenance but no freshness gate.
    """

    league_key: str | None
    sleeper_league_id: str | None
    observed_at: str | None
    drafts: tuple[DraftObservation, ...] = field(default_factory=tuple)
    #: Sleeper league ids whose ``/drafts`` list was actually read.
    draft_lists_observed: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": EVIDENCE_SCHEMA_VERSION,
            "leagueKey": self.league_key,
            "sleeperLeagueId": self.sleeper_league_id,
            "observedAt": self.observed_at,
            "draftListsObserved": list(self.draft_lists_observed),
            "drafts": [d.to_dict() for d in self.drafts],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "LeagueDraftEvidence | None":
        """Inverse of :meth:`to_dict`; ``None`` for anything unreadable.

        An unknown schema version is unreadable, not "close enough" — a
        misread field here could retire a live class.
        """
        if not isinstance(raw, Mapping):
            return None
        if _coerce_int(raw.get("schemaVersion")) != EVIDENCE_SCHEMA_VERSION:
            return None
        drafts_raw = raw.get("drafts")
        if not isinstance(drafts_raw, list):
            return None
        drafts = tuple(d for d in (DraftObservation.from_dict(x) for x in drafts_raw) if d)
        lists = raw.get("draftListsObserved")
        return cls(
            league_key=(str(raw["leagueKey"]) if raw.get("leagueKey") else None),
            sleeper_league_id=(str(raw["sleeperLeagueId"]) if raw.get("sleeperLeagueId") else None),
            observed_at=(str(raw["observedAt"]) if raw.get("observedAt") else None),
            drafts=drafts,
            draft_lists_observed=tuple(str(x) for x in lists) if isinstance(lists, list) else (),
        )


def evidence_from_sleeper(
    *,
    league_key: str | None,
    sleeper_league_id: str | None,
    drafts: Iterable[Any],
    picks_by_draft_id: Mapping[str, Any],
    rostered_player_ids: Iterable[Any] | None,
    observed_at: str | None,
    draft_lists_observed: Iterable[str] = (),
) -> LeagueDraftEvidence:
    """Assemble evidence from Sleeper-shaped objects.  Pure — no I/O.

    ``drafts`` are ``/league/{id}/drafts`` rows (any number of leagues in
    the chain).  ``picks_by_draft_id[draft_id]`` is that draft's
    ``/draft/{id}/picks`` list, or absent / ``None`` when it was not
    fetched.  ``rostered_player_ids`` is every player id on the league's
    CURRENT rosters, or ``None`` when rosters were not observed.
    """
    rostered: set[str] | None
    if rostered_player_ids is None:
        rostered = None
    else:
        rostered = {str(p) for p in rostered_player_ids if p not in (None, "")}

    observations: list[DraftObservation] = []
    seen: set[str] = set()
    for d in drafts or ():
        if not isinstance(d, Mapping):
            continue
        draft_id = str(d.get("draft_id") or "").strip()
        if not draft_id or draft_id in seen:
            continue
        seen.add(draft_id)
        status_raw = d.get("status")
        status = str(status_raw).strip().lower() if status_raw not in (None, "") else None
        settings = d.get("settings") if isinstance(d.get("settings"), Mapping) else {}
        picks = picks_by_draft_id.get(draft_id) if isinstance(picks_by_draft_id, Mapping) else None
        pick_count: int | None = None
        rookie_count: int | None = None
        rostered_count: int | None = None
        if isinstance(picks, list):
            picked_ids = [
                str(p.get("player_id"))
                for p in picks
                if isinstance(p, Mapping) and p.get("player_id") not in (None, "")
            ]
            pick_count = len(picked_ids)
            exp_known = 0
            rookies = 0
            for p in picks:
                if not isinstance(p, Mapping) or p.get("player_id") in (None, ""):
                    continue
                meta = p.get("metadata") if isinstance(p.get("metadata"), Mapping) else {}
                exp = _coerce_int(meta.get("years_exp"))
                if exp is None:
                    continue
                exp_known += 1
                if exp == 0:
                    rookies += 1
            rookie_count = rookies if exp_known else None
            if rostered is not None:
                rostered_count = sum(1 for pid in picked_ids if pid in rostered)
        observations.append(
            DraftObservation(
                draft_id=draft_id,
                season=_coerce_int(d.get("season")),
                status=status,
                player_type=_coerce_int(settings.get("player_type")),
                pick_count=pick_count,
                rookie_pick_count=rookie_count,
                rostered_pick_count=rostered_count,
            )
        )
    return LeagueDraftEvidence(
        league_key=league_key,
        sleeper_league_id=str(sleeper_league_id) if sleeper_league_id else None,
        observed_at=observed_at,
        drafts=tuple(observations),
        draft_lists_observed=tuple(str(x) for x in draft_lists_observed),
    )


# ── The predicate ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassLifecycle:
    season: int
    status: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"season": self.season, "status": self.status, "reasons": list(self.reasons)}


def is_retired(lifecycle: ClassLifecycle | None) -> bool:
    """The ONE behavioural question.  ``unknown`` and ``None`` are not retired."""
    return lifecycle is not None and lifecycle.status == LIFECYCLE_RETIRED


def _is_rookie_draft(d: DraftObservation) -> bool:
    if d.player_type == SLEEPER_ROOKIES_ONLY_PLAYER_TYPE:
        return True
    if d.rookie_pick_count is None or not d.pick_count:
        return False
    return d.rookie_pick_count / d.pick_count >= ROOKIE_DRAFT_MIN_ROOKIE_SHARE


def draft_class_lifecycle(season: int, evidence: LeagueDraftEvidence | None) -> ClassLifecycle:
    """One league's verdict on one season's class, from its own evidence only.

    See the module docstring for the rule.  Reasons are machine-readable
    ``kind[:detail]`` strings so the contract stamp explains itself.
    """
    season = int(season)
    if evidence is None:
        return ClassLifecycle(season, LIFECYCLE_UNKNOWN, ("no_draft_evidence",))
    drafts = [d for d in evidence.drafts if d.season == season]
    if not drafts:
        return ClassLifecycle(season, LIFECYCLE_UNKNOWN, ("no_draft_observed_for_season",))

    live = [d.draft_id for d in drafts if d.status in _STATUSES_LIVE]
    if live:
        return ClassLifecycle(
            season, LIFECYCLE_ACTIVE, tuple(f"draft_in_progress:{i}" for i in live)
        )
    not_started = [d.draft_id for d in drafts if d.status in _STATUSES_NOT_STARTED]
    if not_started:
        return ClassLifecycle(
            season, LIFECYCLE_ACTIVE, tuple(f"draft_not_started:{i}" for i in not_started)
        )
    unrecognized = [d for d in drafts if d.status != _STATUS_COMPLETE]
    if unrecognized:
        return ClassLifecycle(
            season,
            LIFECYCLE_UNKNOWN,
            tuple(f"draft_status_unrecognized:{d.draft_id}={d.status}" for d in unrecognized),
        )

    notes: list[str] = []
    rookie_drafts: list[DraftObservation] = []
    for d in drafts:
        if d.pick_count is None:
            notes.append(f"picks_unobserved:{d.draft_id}")
        elif d.pick_count == 0:
            notes.append(f"empty_complete_draft_ignored:{d.draft_id}")
        elif not _is_rookie_draft(d):
            notes.append(f"non_rookie_draft_ignored:{d.draft_id}")
        else:
            rookie_drafts.append(d)
    if not rookie_drafts:
        return ClassLifecycle(season, LIFECYCLE_UNKNOWN, ("no_completed_rookie_draft", *notes))
    if any(d.rostered_pick_count is None for d in rookie_drafts):
        return ClassLifecycle(season, LIFECYCLE_UNKNOWN, ("rosters_unobserved", *notes))

    # Both counts are observed on every rookie draft here (the branches
    # above returned on anything unobserved), so nothing is coerced.
    picked = sum(d.pick_count for d in rookie_drafts if d.pick_count is not None)
    rostered = sum(
        d.rostered_pick_count for d in rookie_drafts if d.rostered_pick_count is not None
    )
    ids = ",".join(d.draft_id for d in rookie_drafts)
    consumed = f"{rostered}/{picked}"
    if picked > 0 and rostered / picked >= CONSUMPTION_MIN_ROSTERED_SHARE:
        return ClassLifecycle(
            season,
            LIFECYCLE_RETIRED,
            (f"rookie_draft_complete:{ids}", f"rookies_rostered:{consumed}", *notes),
        )
    return ClassLifecycle(
        season,
        LIFECYCLE_UNKNOWN,
        (f"rookie_draft_complete:{ids}", f"consumption_unproven:{consumed}", *notes),
    )


def league_class_lifecycles(
    seasons: Iterable[int], evidence: LeagueDraftEvidence | None
) -> dict[int, ClassLifecycle]:
    """Per-league verdicts for ``seasons``, with supersession applied.

    Supersession looks at every season the evidence covers, not only the
    requested ones, so asking about 2026 alone still sees a retired 2027.
    """
    wanted = {int(s) for s in seasons}
    covered = {d.season for d in (evidence.drafts if evidence else ()) if d.season is not None}
    base = {s: draft_class_lifecycle(s, evidence) for s in wanted | covered}
    retired_years = sorted(s for s, lc in base.items() if lc.status == LIFECYCLE_RETIRED)
    out: dict[int, ClassLifecycle] = {}
    for s in sorted(wanted):
        lc = base[s]
        if lc.status == LIFECYCLE_UNKNOWN:
            later = [y for y in retired_years if y > s]
            if later:
                lc = ClassLifecycle(
                    s,
                    LIFECYCLE_RETIRED,
                    (f"superseded_by_retired_class:{later[0]}", *lc.reasons),
                )
        out[s] = lc
    return out


def board_class_lifecycle(
    season: int, per_league: Mapping[str, ClassLifecycle | None]
) -> ClassLifecycle:
    """The board-scoped verdict: retired only when EVERY served league is.

    ``per_league`` maps each league the board may be served to onto its own
    verdict for ``season`` (``None`` = no evidence).  An empty mapping is
    ``unknown`` — "no league proved anything" is not "every league did".
    """
    season = int(season)
    if not per_league:
        return ClassLifecycle(season, LIFECYCLE_UNKNOWN, ("no_served_league_evidence",))
    reasons: list[str] = []
    statuses: list[str] = []
    for key in sorted(per_league):
        lc = per_league[key]
        status = lc.status if lc is not None else LIFECYCLE_UNKNOWN
        statuses.append(status)
        detail = ";".join(lc.reasons) if lc is not None and lc.reasons else "no_draft_evidence"
        reasons.append(f"{key}:{status}:{detail}")
    if LIFECYCLE_ACTIVE in statuses:
        status = LIFECYCLE_ACTIVE
    elif LIFECYCLE_UNKNOWN in statuses:
        status = LIFECYCLE_UNKNOWN
    else:
        status = LIFECYCLE_RETIRED
    return ClassLifecycle(season, status, tuple(reasons))


def retired_seasons(
    lifecycles: Mapping[int, ClassLifecycle] | Iterable[ClassLifecycle],
) -> set[int]:
    values = lifecycles.values() if isinstance(lifecycles, Mapping) else lifecycles
    return {lc.season for lc in values if is_retired(lc)}


def first_active_class(anchor_year: int, retired: Iterable[int]) -> int:
    """The upcoming draft: the first class at or after ``anchor_year`` that is
    not retired.

    ``anchor_year`` is the board's active draft year (the future-pick horizon
    anchor, which retirement deliberately does not move — owner decision on
    #1442).  Consumers that mean "the next draft that will actually happen"
    (draft-capital pick stacks) read this instead, so the two concepts stay
    separately named.  With nothing retired it IS ``anchor_year``.
    """
    retired_set = {int(y) for y in retired}
    year = int(anchor_year)
    while year in retired_set:
        year += 1
    return year
