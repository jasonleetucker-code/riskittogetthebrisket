"""Canonical player-identity resolution engine (C1-ID-01).

One engine, named per-site policies
-----------------------------------
Before this unit the repo carried three independent player-identity
matchers, and they disagreed on real players on the live board (measured
2026-08-16: 10 of 949 board rows — see
``docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md``):

* ``Dynasty Scraper.py``'s run()-scope ladder ``_resolve_sleeper_identity``
  — the decider that stamps ``playerId`` on every board row;
* ``src/api/data_contract.py``'s CSV-enrichment cascade — exact-key only;
* ``src/identity/unified_mapper.py::resolve_player`` — the directory
  ladder used by playerctx and the realized endpoint.

This module owns the resolution SEMANTICS for all of them.  A *policy* is
a named, versioned description of which rungs run at a site:

``SCRAPER_SLEEPER_ATTACH_V1``  (:func:`resolve_scraper_attach_v1`)
    Exact transcription of the scraper's ladder, including its known
    hazards (unguarded initial+last rung; argmax candidate scoring that
    always guesses among homonyms).  Exists so the scraper's dual-read
    adapter can prove ZERO divergence before cutover — never a flag-day
    swap.  Retired when the scraper site cuts over.

``CONTRACT_CSV_JOIN_V1``  (:func:`match_row_to_source_entry`)
    Exact transcription of the contract-side CSV join cascade
    (sleeper-id first, then position-aware canonical key).  Deliberately
    conservative: no fuzzy rung — measured on the live corpus the exact
    join rejected all 544 unmatched CSV names with zero false merges
    (W06-F006 ``whatWorks``).

``CANONICAL_V2``  (:func:`resolve_canonical_v2`)
    The repaired canonical ladder — the destination semantics.  DARK
    today: no production consumer reads it until the dual-read prod gate
    (zero divergence over a full refresh cycle) authorizes cutover.
    Differences from the legacy ladders, each grounded in a measured
    defect:

    * fuzzy and initial-expansion rungs are GUARDED by
      :func:`src.identity.name_primitives.is_safe_name_merge` — kills the
      measured sibling false-merges (Whit→West Weeks, Rod→Rahim Moore,
      Jamarion→Jordan Miller) and all 11 W06-F006 false merges;
    * homonym selection prefers the single ACTIVE candidate (mapper's
      first-in-directory rung served the RETIRED Frank Gore for the
      active Frank Gore Jr.);
    * unresolvable ambiguity is an explicit UNRESOLVED/ambiguous result,
      never a silent first-wins guess;
    * fuzzy confidence is capped below every exact rung (W06-F006
      required repair: "never report a fuzzy match above 0.90").

Non-negotiables inherited from the governance layer:

* MISSING IS NEVER ZERO — an unresolved identity is an explicit state
  with a reason, never a fabricated match.
* Determinism — same directory + same signals → same answer.  V2
  tie-breaks are explicit ``(score desc, sleeper_id asc)``; the V1
  policies faithfully reproduce the legacy insertion-order behaviour
  because that is what they exist to prove parity against.
* The near-name duplicate detector retired by W06-F002 stays retired —
  nothing here reintroduces it.
* Pick identity is OUT OF SCOPE (C1-ID-02 / unit C1-U3): pick-shaped
  names are refused with reason ``pick_name``, exactly as the scraper's
  ladder refuses them today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from src.identity.name_primitives import (
    best_match,
    clean_name,
    is_safe_name_merge,
    normalize_lookup_name,
)
from src.utils.name_clean import resolve_canonical_name

# ── Resolution result contract ──────────────────────────────────────────

RESOLVED = "resolved"
UNRESOLVED = "unresolved"

# Reasons an identity is explicitly NOT resolved.  These are states, not
# errors — every consumer must be able to render them honestly.
REASON_EMPTY_INPUT = "empty_input"
REASON_PICK_NAME = "pick_name"
REASON_NO_CANDIDATE = "no_candidate"
REASON_AMBIGUOUS = "ambiguous"
REASON_BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True)
class SleeperCandidate:
    """One directory entry, in exactly the shape the scraper's ladder
    derives from the Sleeper ``/v1/players/nfl`` dump."""

    sleeper_id: str
    display_name: str  # clean_name()'d full name — the scraper's vocabulary
    position: str  # raw upper-cased Sleeper position ("DE", "LB", …)
    team: str
    active: int
    search_rank: float
    years_exp: int


@dataclass(frozen=True)
class Resolution:
    """The canonical answer to "which player is this?".

    ``status`` is ``resolved`` or ``unresolved`` — never a guess dressed
    as certainty.  ``method`` is real join provenance (which rung fired),
    not a restatement of field presence (W06-F005's defect class).
    """

    status: str
    policy: str
    method: str
    sleeper_id: str | None = None
    display_name: str | None = None
    position: str | None = None
    team: str | None = None
    confidence: float | None = None
    reason: str | None = None
    candidates_considered: int = 0
    tie_detected: bool = False
    candidate_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.status == RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy": self.policy,
            "method": self.method,
            "sleeperId": self.sleeper_id,
            "displayName": self.display_name,
            "position": self.position,
            "team": self.team,
            "confidence": self.confidence,
            "reason": self.reason,
            "candidatesConsidered": self.candidates_considered,
            "tieDetected": self.tie_detected,
            "candidateIds": list(self.candidate_ids),
        }


# ── Directory index ─────────────────────────────────────────────────────


class SleeperDirectoryIndex:
    """Indexes the Sleeper NFL directory once for all resolution policies.

    Construction is an exact transcription of the scraper's candidate
    index build (``Dynasty Scraper.py`` 4516-4550): same name derivation,
    same skip rules, same insertion order — the V1 policy's fidelity
    depends on it.  V2-only indexes (ids, canonical-alias names) are
    built alongside.
    """

    def __init__(self, directory: Mapping[str, Any] | None):
        self.by_clean: dict[str, list[SleeperCandidate]] = {}
        self.by_lookup: dict[str, list[SleeperCandidate]] = {}
        self.by_initial_last: dict[tuple[str, str], list[SleeperCandidate]] = {}
        # V2-only indexes.
        self.by_sleeper_id: dict[str, SleeperCandidate] = {}
        self.by_gsis: dict[str, SleeperCandidate] = {}
        self.by_espn: dict[str, SleeperCandidate] = {}
        self.by_canonical: dict[str, list[SleeperCandidate]] = {}

        for pid, pdata in (directory or {}).items():
            if not isinstance(pdata, dict):
                continue
            full = clean_name(
                pdata.get("full_name")
                or f"{pdata.get('first_name', '')} {pdata.get('last_name', '')}".strip()
            )
            if not full:
                continue
            pos = str(pdata.get("position", "") or "").upper()
            cand = SleeperCandidate(
                sleeper_id=str(pid),
                display_name=full,
                position=pos,
                active=1 if pdata.get("active") else 0,
                team=pdata.get("team") or "",
                search_rank=float(pdata.get("search_rank", 0) or 0),
                years_exp=int(pdata.get("years_exp", pdata.get("experience", 0)) or 0),
            )
            self.by_clean.setdefault(full, []).append(cand)
            self.by_lookup.setdefault(normalize_lookup_name(full), []).append(cand)
            parts = full.split()
            if len(parts) >= 2:
                key = (
                    parts[0][0].lower(),
                    " ".join(parts[1:]).lower().replace("-", " ").replace(".", ""),
                )
                self.by_initial_last.setdefault(key, []).append(cand)

            self.by_sleeper_id[str(pid)] = cand
            gsis = str(pdata.get("gsis_id") or "").strip()
            if gsis:
                self.by_gsis.setdefault(gsis, cand)
            espn = str(pdata.get("espn_id") or "").strip()
            if espn:
                self.by_espn.setdefault(espn, cand)
            self.by_canonical.setdefault(resolve_canonical_name(full), []).append(cand)

        self.clean_pool: list[str] = list(self.by_clean.keys())


def build_sleeper_index(directory: Mapping[str, Any] | None) -> SleeperDirectoryIndex:
    return SleeperDirectoryIndex(directory)


# ── Shared rung helpers ─────────────────────────────────────────────────

_POS_FAMILY = {
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
    "OLB": "LB",
    "ILB": "LB",
}


def pos_family(pos: object) -> str:
    """Position family exactly as the scraper's run()-scope ``_pos_family``
    computes it (4552-4560): unknowns pass through upper-cased."""
    up = str(pos or "").upper()
    return _POS_FAMILY.get(up, up)


def candidate_score(cand: SleeperCandidate, preferred_pos: str = "") -> float:
    """Exact transcription of the scraper's ``_candidate_score`` (4562-4579)."""
    score = 0.0
    if cand.active:
        score += 10000.0
    if cand.team:
        score += 500.0
    sr = cand.search_rank or 0
    if 0 < sr < 9999999:
        score += max(0.0, 1000.0 - float(sr))
    score += cand.years_exp * 2.0
    if preferred_pos:
        if pos_family(cand.position) == pos_family(preferred_pos):
            score += 300.0
    return score


_PICK_NAME_RES = (
    re.compile(r"^20\d{2}\s+(PICK\s+)?[1-6]\.(0?[1-9]|1[0-2])$"),
    re.compile(r"^[1-6]\.(0?[1-9]|1[0-2])$"),
    re.compile(r"^20\d{2}\s+(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)$"),
    re.compile(r"^(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)$"),
    re.compile(r"^20\d{2}\s+[1-6]\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$"),
    re.compile(r"^[1-6]\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$"),
)


def looks_like_pick_name(name: object) -> bool:
    """Exact transcription of the scraper's ``_looks_like_pick_name``
    (4586-4604).  Pick identity itself is C1-ID-02 scope; this predicate
    only routes pick-shaped names AWAY from player resolution."""
    s = str(name or "").upper().strip()
    if not s:
        return False
    for rx in _PICK_NAME_RES:
        if rx.match(s):
            return True
    return " PICK " in f" {s} "


# ── Policy: SCRAPER_SLEEPER_ATTACH_V1 ───────────────────────────────────

SCRAPER_ATTACH_V1 = "scraper_sleeper_attach_v1"


def resolve_scraper_attach_v1(
    index: SleeperDirectoryIndex,
    name: str,
    preferred_pos: str = "",
    *,
    merge_guard: Callable[[str, str], bool] | None = None,
    debug: bool = False,
) -> Resolution:
    """Exact transcription of ``Dynasty Scraper.py::_resolve_sleeper_identity``
    (4606-4635) — the ladder that stamps ``playerId`` on every board row.

    Ladder: clean-name exact → lookup-norm exact → (initial, last) index →
    guarded fuzzy ≥0.90 → argmax ``candidate_score``.  KNOWN HAZARDS are
    preserved on purpose (this policy exists to prove dual-read parity):
    the (initial, last) rung is unguarded — it is what merged Whit Weeks
    into his brother West — and the final argmax always guesses among
    homonyms rather than refusing.  Provenance records which rung fired
    and whether the argmax had company (``tie_detected`` when more than
    one candidate reached selection), so the dual-read artifact can show
    exactly where the legacy ladder was exposed.

    ``merge_guard`` is the caller's fuzzy-merge guard.  The scraper
    injects its roster-position-aware ``_is_safe_name_merge``; ``None``
    falls back to the positionless guard, which is what the scraper's
    guard degrades to when its roster map is empty.
    """
    guard = merge_guard or (lambda s, d: is_safe_name_merge(s, d, position_lookup=None))
    cleaned = clean_name(name)
    if not cleaned:
        return Resolution(
            status=UNRESOLVED,
            policy=SCRAPER_ATTACH_V1,
            method="none",
            reason=REASON_EMPTY_INPUT,
        )
    if looks_like_pick_name(cleaned):
        return Resolution(
            status=UNRESOLVED,
            policy=SCRAPER_ATTACH_V1,
            method="none",
            reason=REASON_PICK_NAME,
        )

    method = "exact_clean"
    candidates = list(index.by_clean.get(cleaned, []))
    if not candidates:
        method = "exact_lookup"
        candidates = list(index.by_lookup.get(normalize_lookup_name(cleaned), []))
    if not candidates:
        parts = cleaned.split()
        if len(parts) >= 2:
            key = (
                parts[0][0].lower(),
                " ".join(parts[1:]).lower().replace("-", " ").replace(".", ""),
            )
            method = "initial_last"
            candidates = list(index.by_initial_last.get(key, []))
    if not candidates and index.clean_pool:
        method = "fuzzy_guarded"
        fm = best_match(
            cleaned,
            index.clean_pool,
            threshold=0.90,
            match_guard=guard,
            debug=debug,
        )
        if fm:
            candidates = list(index.by_clean.get(fm, []))

    if not candidates:
        return Resolution(
            status=UNRESOLVED,
            policy=SCRAPER_ATTACH_V1,
            method="none",
            reason=REASON_NO_CANDIDATE,
        )

    # max() keeps the FIRST maximum — the legacy tie-break, preserved.
    best = max(candidates, key=lambda c: candidate_score(c, preferred_pos))
    top_score = candidate_score(best, preferred_pos)
    ties = sum(1 for c in candidates if candidate_score(c, preferred_pos) == top_score)
    return Resolution(
        status=RESOLVED,
        policy=SCRAPER_ATTACH_V1,
        method=method,
        sleeper_id=best.sleeper_id,
        display_name=best.display_name,
        position=pos_family(best.position),
        team=best.team or None,
        confidence=None,  # the legacy ladder never scored confidence
        candidates_considered=len(candidates),
        tie_detected=ties > 1,
        candidate_ids=tuple(c.sleeper_id for c in candidates),
    )


# ── Policy: CANONICAL_V2 ────────────────────────────────────────────────

CANONICAL_V2 = "canonical_v2"

# Fuzzy matches may never outrank an exact rung (W06-F006 required
# repair).  0.89 sits below name_unique's 0.90.
_V2_FUZZY_CONFIDENCE_CAP = 0.89
_V2_FUZZY_THRESHOLD = 0.90


def _v2_guard(src: str, dst: str) -> bool:
    """V2's merge guard: the shared structural guard with the surname
    requirement TIGHTENED to exact equality (the legacy guard's 0.92
    near-surname branch admitted 5 of the 11 W06-F006 false-merge pairs).
    Position compatibility is checked against candidate metadata by the
    caller, not a module global."""
    from src.identity.name_primitives import name_tokens  # noqa: PLC0415

    if not is_safe_name_merge(src, dst, position_lookup=None):
        return False
    s_tokens, d_tokens = name_tokens(src), name_tokens(dst)
    if len(s_tokens) < 2 or len(d_tokens) < 2:
        return False
    if s_tokens[-1] != d_tokens[-1]:
        # Different surnames survive the legacy guard only through its
        # near-surname (≥0.92) and trailing-artifact branches; V2 refuses
        # both for fuzzy resolution — a surname is not evidence when it
        # merely resembles another surname.
        return False
    return True


def _v2_select(
    candidates: list[SleeperCandidate],
    *,
    position: str | None,
    team: str | None,
) -> tuple[SleeperCandidate | None, str, bool, list[SleeperCandidate]]:
    """Deterministic candidate selection with an explicit ambiguity state.

    Returns ``(winner_or_None, how, ambiguous, considered)``.

    Order of evidence (each step only narrows, never invents):
      1. position GROUP (OFFENSE / IDP / KICKER), when the caller
         supplied a position.  Deliberately coarser than the family:
         sources drift between DL and LB for the same human (measured on
         the live board: "Byron Young" is DL on the board and LB in
         Sleeper's directory for the very player the board serves), and
         ``canonical_position_group`` exists precisely to absorb that
         drift.  A family-exact filter here would exclude the correct
         candidate;
      2. team, when the caller supplied one;
      3. the single candidate currently ROSTERED on an NFL team
         (``team`` non-empty), when exactly one remains — measured on the
         live directory, Sleeper's ``active`` flag is unreliable for
         retirees (Frank Gore Sr., retired 2020, is ``active: True`` with
         ``team: None``), so team presence is the honest
         "currently-in-the-league" signal and it is what actually
         separates the measured homonym pairs (Gore Jr. BUF vs Sr. None);
      4. the single ACTIVE candidate, when exactly one remains active —
         weaker fallback for off-roster players;
      5. otherwise: one survivor resolves; several survivors are
         AMBIGUOUS and V2 refuses rather than guessing.
    """
    from src.utils.name_clean import canonical_position_group  # noqa: PLC0415

    considered = list(candidates)
    pool = considered
    how = "name"
    if position:
        grp = canonical_position_group(position)
        narrowed = [
            c for c in pool if not c.position or canonical_position_group(c.position) == grp
        ]
        if narrowed:
            pool = narrowed
            how = "name_pos"
    if team:
        team_u = str(team).strip().upper()
        narrowed = [c for c in pool if str(c.team or "").strip().upper() == team_u]
        if narrowed:
            pool = narrowed
            how = "name_team" if how == "name" else "name_team_pos"
    if len(pool) == 1:
        return pool[0], how, False, considered
    if len(pool) > 1:
        teamed = [c for c in pool if str(c.team or "").strip()]
        if len(teamed) == 1:
            return teamed[0], f"{how}_teamed", False, considered
        actives = [c for c in pool if c.active]
        if len(actives) == 1:
            return actives[0], f"{how}_active", False, considered
        return None, how, True, considered
    return None, how, False, considered


def resolve_canonical_v2(
    index: SleeperDirectoryIndex,
    *,
    name: str | None = None,
    position: str | None = None,
    team: str | None = None,
    sleeper_id: str | None = None,
    gsis_id: str | None = None,
    espn_id: str | None = None,
) -> Resolution:
    """The canonical (destination) resolution ladder.  DARK until the
    dual-read prod gate authorizes cutover — no production decision reads
    this today.

    Ladder: external ids → exact name rungs (clean, lookup-norm, then
    alias-aware canonical) → guarded initial-expansion → guarded fuzzy.
    Every multi-candidate rung goes through :func:`_v2_select`; an
    unseparable tie is an explicit ``ambiguous`` refusal.
    """

    def _resolved(
        cand: SleeperCandidate,
        method: str,
        confidence: float,
        considered: list[SleeperCandidate],
        tie: bool = False,
    ) -> Resolution:
        return Resolution(
            status=RESOLVED,
            policy=CANONICAL_V2,
            method=method,
            sleeper_id=cand.sleeper_id,
            display_name=cand.display_name,
            position=pos_family(cand.position),
            team=cand.team or None,
            confidence=confidence,
            candidates_considered=len(considered),
            tie_detected=tie,
            candidate_ids=tuple(sorted(c.sleeper_id for c in considered)),
        )

    def _unresolved(method: str, reason: str, considered: list[SleeperCandidate]) -> Resolution:
        return Resolution(
            status=UNRESOLVED,
            policy=CANONICAL_V2,
            method=method,
            reason=reason,
            candidates_considered=len(considered),
            candidate_ids=tuple(sorted(c.sleeper_id for c in considered)),
        )

    # 1. External ids — exact, highest confidence.
    if sleeper_id:
        sid = str(sleeper_id).strip()
        if sid and sid in index.by_sleeper_id:
            return _resolved(
                index.by_sleeper_id[sid], "sleeper_id", 1.00, [index.by_sleeper_id[sid]]
            )
    if gsis_id:
        gid = str(gsis_id).strip()
        if gid and gid in index.by_gsis:
            return _resolved(index.by_gsis[gid], "gsis_id", 1.00, [index.by_gsis[gid]])
    if espn_id:
        eid = str(espn_id).strip()
        if eid and eid in index.by_espn:
            return _resolved(index.by_espn[eid], "espn_id", 1.00, [index.by_espn[eid]])

    cleaned = clean_name(name) if name else ""
    if not cleaned:
        return _unresolved(
            "none", REASON_EMPTY_INPUT if name is not None else REASON_NO_CANDIDATE, []
        )
    if looks_like_pick_name(cleaned):
        return _unresolved("none", REASON_PICK_NAME, [])

    confidence_by_how = {
        "name_team_pos": 0.98,
        "name_pos": 0.93,
        "name_team": 0.93,
        "name": 0.90,
        "name_pos_teamed": 0.88,
        "name_team_teamed": 0.88,
        "name_team_pos_teamed": 0.88,
        "name_teamed": 0.88,
        "name_pos_active": 0.88,
        "name_team_active": 0.88,
        "name_team_pos_active": 0.88,
        "name_active": 0.88,
    }

    # 2. Exact name rungs, in decreasing vocabulary strictness.
    for method, candidates in (
        ("exact_clean", index.by_clean.get(cleaned)),
        ("exact_lookup", index.by_lookup.get(normalize_lookup_name(cleaned))),
        ("exact_canonical", index.by_canonical.get(resolve_canonical_name(cleaned))),
    ):
        if not candidates:
            continue
        winner, how, ambiguous, considered = _v2_select(
            list(candidates), position=position, team=team
        )
        if winner is not None:
            return _resolved(
                winner, f"{method}:{how}", confidence_by_how.get(how, 0.90), considered
            )
        if ambiguous:
            return _unresolved(f"{method}:{how}", REASON_AMBIGUOUS, considered)

    # 3. Guarded initial-expansion ("J. Smith-Njigba" → "Jaxon Smith-Njigba").
    parts = cleaned.split()
    if len(parts) >= 2:
        key = (
            parts[0][0].lower(),
            " ".join(parts[1:]).lower().replace("-", " ").replace(".", ""),
        )
        candidates = [
            c
            for c in index.by_initial_last.get(key, [])
            if is_safe_name_merge(cleaned, c.display_name, position_lookup=None)
        ]
        if candidates:
            winner, how, ambiguous, considered = _v2_select(
                candidates, position=position, team=team
            )
            if winner is not None:
                return _resolved(
                    winner,
                    f"initial_last_guarded:{how}",
                    min(confidence_by_how.get(how, 0.90), _V2_FUZZY_CONFIDENCE_CAP),
                    considered,
                )
            if ambiguous:
                return _unresolved(f"initial_last_guarded:{how}", REASON_AMBIGUOUS, considered)

    # 4. Guarded fuzzy — surname-exact, first-name-compatible, capped.
    fm = best_match(cleaned, index.clean_pool, threshold=_V2_FUZZY_THRESHOLD, match_guard=_v2_guard)
    if fm:
        candidates = list(index.by_clean.get(fm, []))
        winner, how, ambiguous, considered = _v2_select(candidates, position=position, team=team)
        if winner is not None:
            from src.identity.name_primitives import similarity  # noqa: PLC0415

            conf = min(similarity(cleaned, fm), _V2_FUZZY_CONFIDENCE_CAP)
            return _resolved(winner, f"fuzzy_guarded:{how}", conf, considered)
        if ambiguous:
            return _unresolved(f"fuzzy_guarded:{how}", REASON_AMBIGUOUS, considered)

    return _unresolved("none", REASON_NO_CANDIDATE, [])


# ── Policy: CONTRACT_CSV_JOIN_V1 ────────────────────────────────────────

CONTRACT_CSV_JOIN_V1 = "contract_csv_join_v1"


@dataclass(frozen=True)
class CsvJoinDecision:
    """The contract-side answer to "which CSV entry feeds this row?"."""

    entry_key: str | None  # per_source key that matched, None on miss
    via: str  # "sleeper_id" | "name_group" | "name_star" | "single_group" | "none"
    policy: str = CONTRACT_CSV_JOIN_V1


def match_row_to_source_entry(
    *,
    row_player_id: str | None,
    row_name: str,
    row_position: str | None,
    per_source: Mapping[str, Mapping[str, Any]],
    sid_index: Mapping[str, Mapping[str, Any]],
    row_groups_by_key: Mapping[str, set[str]],
    canonical_match_key: Callable[[str], str],
    position_group: Callable[[str | None], str],
) -> CsvJoinDecision:
    """Exact transcription of the identity decision inside
    ``data_contract._enrich_from_source_csvs``'s row loop (4253-4296):
    sleeper-id join first when the source publishes ids, then the
    position-aware canonical-key cascade.  No fuzzy rung, by design —
    the conservative exact join is the measured-correct behaviour on the
    board path (0 false merges over 544 rejected names, W06-F006).

    ``canonical_match_key`` / ``position_group`` are injected so this
    function provably uses the SAME key functions as the caller — a
    second normalization sneaking in here is exactly the defect class
    this unit retires.
    """
    if sid_index:
        row_sid = str(row_player_id or "").strip()
        if row_sid and row_sid in sid_index:
            return CsvJoinDecision(entry_key=f"sid::{row_sid}", via="sleeper_id")

    nm = str(row_name or "")
    if not nm:
        return CsvJoinDecision(entry_key=None, via="none")
    cname = canonical_match_key(nm)
    if not cname:
        return CsvJoinDecision(entry_key=None, via="none")
    grp = position_group(row_position)
    if f"{cname}::{grp}" in per_source:
        return CsvJoinDecision(entry_key=f"{cname}::{grp}", via="name_group")
    if f"{cname}::*" in per_source:
        return CsvJoinDecision(entry_key=f"{cname}::*", via="name_star")
    groups = row_groups_by_key.get(cname, set())
    if len(groups) == 1:
        only_grp = next(iter(groups))
        if f"{cname}::{only_grp}" in per_source:
            return CsvJoinDecision(entry_key=f"{cname}::{only_grp}", via="single_group")
    return CsvJoinDecision(entry_key=None, via="none")


# ── Dual-read comparator ────────────────────────────────────────────────


class DualReadTally:
    """Accumulates old-vs-engine comparisons at one adapter site.

    The artifact this serializes to is the unit's prod-gate evidence:
    ``v1`` divergence must be ZERO over a full refresh cycle before
    cutover, and ``v2WouldChange`` is the measured, owner-reviewable cost
    of the eventual semantic step — recorded, never silently applied.
    """

    def __init__(self, site: str, example_cap: int = 50):
        self.site = site
        self.example_cap = example_cap
        self.calls = 0
        self.v1_agree = 0
        self.v1_diverge = 0
        self.v1_examples: list[dict[str, Any]] = []
        self.v2_same = 0
        self.v2_would_change = 0
        self.v2_examples: list[dict[str, Any]] = []

    def record(
        self,
        *,
        input_name: str,
        input_pos: str = "",
        legacy_id: str | None,
        v1_id: str | None,
        v2: Resolution | None = None,
    ) -> None:
        self.calls += 1
        if legacy_id == v1_id:
            self.v1_agree += 1
        else:
            self.v1_diverge += 1
            if len(self.v1_examples) < self.example_cap:
                self.v1_examples.append(
                    {
                        "name": input_name,
                        "pos": input_pos,
                        "legacy": legacy_id,
                        "engineV1": v1_id,
                    }
                )
        if v2 is not None:
            v2_id = v2.sleeper_id if v2.resolved else None
            if v2_id == legacy_id:
                self.v2_same += 1
            else:
                self.v2_would_change += 1
                if len(self.v2_examples) < self.example_cap:
                    self.v2_examples.append(
                        {
                            "name": input_name,
                            "pos": input_pos,
                            "legacy": legacy_id,
                            "engineV2": v2_id,
                            "v2Method": v2.method,
                            "v2Reason": v2.reason,
                        }
                    )

    def record_served(
        self,
        *,
        input_name: str,
        input_pos: str = "",
        served_id: str | None,
        v2: "Resolution | None" = None,
    ) -> None:
        """POST-CUTOVER accounting: the canonical owner is the only
        decider, so there is no legacy answer left to diverge from.  The
        v1 counters are therefore not comparisons and stay at zero; the
        meaningful figure is ``v2WouldChange`` — the standing measurement
        of the gap between the served policy and ``CANONICAL_V2``, which
        is the evidence base for the deferred semantic step."""
        self.calls += 1
        if v2 is not None:
            v2_id = v2.sleeper_id if v2.resolved else None
            if v2_id == served_id:
                self.v2_same += 1
            else:
                self.v2_would_change += 1
                if len(self.v2_examples) < self.example_cap:
                    self.v2_examples.append(
                        {
                            "name": input_name,
                            "pos": input_pos,
                            "served": served_id,
                            "engineV2": v2_id,
                            "v2Method": v2.method,
                            "v2Reason": v2.reason,
                        }
                    )

    def record_keys(
        self,
        *,
        input_name: str,
        input_pos: str = "",
        source: str = "",
        legacy_key: str | None,
        engine_key: str | None,
    ) -> None:
        """Key-level comparison for join sites (contract CSV join): the
        compared decision is *which index entry feeds this row*, not a
        sleeper id."""
        self.calls += 1
        if legacy_key == engine_key:
            self.v1_agree += 1
        else:
            self.v1_diverge += 1
            if len(self.v1_examples) < self.example_cap:
                self.v1_examples.append(
                    {
                        "name": input_name,
                        "pos": input_pos,
                        "source": source,
                        "legacy": legacy_key,
                        "engineV1": engine_key,
                    }
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "calls": self.calls,
            "v1Agree": self.v1_agree,
            "v1Diverge": self.v1_diverge,
            "v1Examples": self.v1_examples,
            "v2Same": self.v2_same,
            "v2WouldChange": self.v2_would_change,
            "v2Examples": self.v2_examples,
        }


# ``cutover_active`` / ``RISKIT_IDENTITY_CUTOVER`` are DELETED (2026-08-16).
# The flag existed to make the dual-read window reversible; the cutover
# happened and the legacy paths were removed, so there is nothing left to
# fall back to.  Keeping a flag that cannot restore anything would
# misdescribe the system — the honest statement is that the canonical
# owner is the only decider.


def dual_read_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Whether the standing ``CANONICAL_V2`` watch runs.

    Post-cutover this gates OBSERVATION only: the watch records what V2
    would answer differently (§9 of the design doc) so the deferred
    semantic work starts from live evidence.  ``RISKIT_IDENTITY_DUAL_READ=0``
    turns that measurement off for cost; it cannot change a served
    identity, because the served answer no longer depends on it."""
    import os  # noqa: PLC0415

    src = env if env is not None else os.environ
    return str(src.get("RISKIT_IDENTITY_DUAL_READ", "1")).strip() not in {"0", "false", "no", "off"}
