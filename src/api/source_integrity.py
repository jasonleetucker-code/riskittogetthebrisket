"""Outlier integrity v2, Layers A and B: identity and source integrity (DEFAULT OFF).

Owner directive 2026-10-20 ("Fix the outlier filter and restore DLF IDP voting")
and its 10:20 UTC addendum. Preregistered BEFORE implementation in
``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` (commit ``3c69945723``);
design in ``docs/sources/OUTLIER_INTEGRITY_V2_ARCHITECTURE.md``. This module is
Stage 1 of that registration: implementation behind default-OFF flags. It
authorizes no activation, and nothing here may be switched on in production
without the owner's explicit approval.

What it decides
---------------
Before any statistical test, each observation is asked questions that need no
row-estimated scale:

* **Layer A, identity** (``identity_evidence_v2``): does the observation belong
  to this player? Decided in the identity owner
  (``src/identity/resolution.assess_identity_evidence``) from what the source
  itself published (position, team, age, ids). This module only carries the
  board-side inputs and records the verdict.
* **Layer B, source and normalization integrity**:

  * **B0 format**: a value-plus-rank board whose own rank order contradicts its
    own value order is mis-formatted (``source_format_error:*``). Non-numeric
    cells are counted; they were never observations (missing, not zero).
  * **B1 structural normalization** (``rookie_ladder_fail_closed``): a rookie
    board vote that was not translated through its ladder votes a within-class
    rank as an overall rank. It is withheld (``normalization_untranslated``),
    never voted. A vote translated through a quarantined backbone or ladder
    inherits ``normalization_dependency_unavailable``.
  * **B2 feed provenance** (``payload_provenance_guard``): for sources with a
    scraper-payload copy AND a same-run CSV copy, a board whose payload departs
    from its own CSV by a common factor in at least two position groups is a
    broken capture (the October IDP Trade Calculator partial-fallback boards);
    a single row departing by more than 2x is a wrong-row capture (the
    "Justin Jefferson" surname case). The proven payload value is absent; the
    vendor's own preserved CSV value votes in its place, and with no CSV the
    observation is withheld.
  * **B3 segment integrity**: per (source, asset class, position group), a rank
    order that no longer agrees with the leave-source-out consensus is a
    direction error; a median shift against the source's own history beyond
    ``tau_gross`` is a scale error; a smaller shift is kept and stamped
    ``segment_break_unproven`` unless the same source build carries B0/B1/B2
    proof. B3a checks rank-mass conservation per (source, asset class).
  * **B4 per-observation continuity**: a vote that jumped away from both its
    own history and every other provider, with no co-movement, is HELD pending
    confirmation (not rejected), and released by reproduction, corroboration or
    a cap.

Layer C (legitimate disagreement) is ``src/api/outlier_policy.assess_row_layer_c``
(the outlier-policy owner, beside V1); this module supplies its history input
(``persistence_confirmed``), its per-vote stamps (``layer_c_stamp``) and its
census. Layer D (confidence) is the unchanged ``src/api/confidence.py``.

Missing is never zero
---------------------
A refused, withheld, quarantined or held observation is ABSENT from the blend:
it never contributes 0 and never contributes another player's value. Votes
excluded at the vote level stay in ``sourceRankMeta`` with ``excludedReason``
and ``contributedToBlend: false`` (the existing exclusion shape), so the source
family stays eligible on the row and coverage can only fall.

Reason codes
------------
Every excluded, held, withheld or refused observation carries exactly one
primary reason from the directive §10 vocabulary (``REASON_CATEGORY``). PR #1831's
``src/sources/voting_status.py`` is not on ``main`` at this commit; these codes
are the vocabulary it maps when it lands (coordinate, never fork).

Flags
-----
``outlier_integrity_v2`` (master) gates every layer here; each named change has
its own flag as well (``identity_evidence_v2``, ``payload_provenance_guard``,
``rookie_ladder_fail_closed``, ``integrity_holds_as_withheld``), effective only
with the master on. ``source_rank_history_record`` gates the record-only history
lane (``src/history/source_rank.py``) and moves no value. All default OFF; with
every one OFF the board is byte-identical. The master is mutually exclusive with
V1 (``outlier_disagreement_policy``): both on raises, never silently picks one.

V2.1 repairs
------------
``outlier_integrity_v21`` (default OFF, effective only under the master) applies
the repairs registered in ``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md``
§3.2 / §3.4 (``Repairs``): R1 B0 tolerance (``rank_value_tolerance``), R2 / R3
small-segment abstention (``class_rule`` / ``segment_rule``, the one rule the
Stage 2 selector also calls), R4 / R5 / R8 / R10 / R11 in the identity owner,
R6 ordinal slots and R7 explainer coverage in ``data_contract``, R13 compact
stamps, R14 the B2 sign share, and P-1..P-4 (content-distinct persistence;
holds and cap releases are never evidence; persistent gross dissent is alerted).
With it OFF every V2 rule here is unchanged. Implementation choices are logged in
``docs/sources/outlier_integrity_v21/DEVIATIONS.md``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sources import voting_status as _voting_status

POLICY_VERSION = "outlier-integrity-v2"
LAYERS_IMPLEMENTED = ("A", "B0", "B1", "B2", "B3", "B4", "C")

REPO_ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = REPO_ROOT / "config" / "sources" / "outlier_integrity_v2.json"

# ── Constants fixed a priori (preregistration §3.5) ─────────────────────────
#: Vote coordinate: u = ln(RANK_OFFSET + REFERENCE_N · p) (as in V1).
RANK_OFFSET = 10.0
REFERENCE_N = 500.0
#: B2: a single row whose payload departs from its CSV by more than 2x.
B2_ROW_DISTANCE = math.log(2.0)
#: B2 board proof: rows a position group needs, and the sign-agreement share.
B2_MIN_GROUP_ROWS = 15
B2_SIGN_SHARE = 0.80
#: B2 board proof: groups that must agree (a lone group can be a real re-price).
B2_MIN_GROUPS = 2
#: B2 board statistics read only overlapping rows at or above this value.
B2_MIN_VALUE = 100.0
#: B2 supporting evidence only: payload rows below this share of the trailing
#: median count (never sufficient on its own).
B2_COVERAGE_SUPPORT = 0.6
#: B3a floor and multiplier: fire at max(B3A_MULTIPLIER · tau_board, B3A_FLOOR).
B3A_FLOOR = math.log(1.25)
B3A_MULTIPLIER = 6.0
#: B3b: a sub-gross shift is NOTED (advisory / proof-backed quarantine) only
#: from this distance; below it a segment is unchanged. Same a-priori floor as
#: B3a (see outlier_integrity_v2/DEVIATIONS.md, clarification 2).
B3_SHIFT_FLOOR = math.log(1.25)
#: B3: other providers needed on a row to form its leave-source-out reference
#: (mirrors V1's MIN_OTHER_FAMILIES; DEVIATIONS.md clarification 3).
B3_MIN_REFERENCE_PROVIDERS = 2
#: History window: the median of the source's previous 3 accepted boards /
#: observations.
HISTORY_WINDOW = 3
#: B4 hold conditions.
B4_AWAY_GAIN = math.log(1.5)
B4_AWAY_MIN = math.log(2.0)
B4_CORROBORATION = math.log(1.25)
B4_COMOVE_SHARE = 0.5
B4_MIN_TAU_C = math.log(1.5)
B4_HOLD_CAP_FETCHES = 2
B4_HOLD_CAP_HOURS = 48.0
#: B4 depth bands on the implied rank of the source's own history.
B4_BANDS = ((50.0, "le50"), (150.0, "51_150"), (400.0, "151_400"), (math.inf, "gt400"))

#: Sources with a scraper-payload copy and a same-run CSV copy (B2).
PAYLOAD_PROVENANCE_SOURCES = ("idpTradeCalc", "ktc", "ktcSfTep")
#: B0 exemption: FantasyPros IDP's ``originalRank`` is a per-page rank by design.
B0_RANK_VALUE_EXEMPT = frozenset({"fantasyProsIdp"})

# ── V2.1 constants fixed a priori (V2.1 preregistration §3.2 / §3.6) ────────
#: R1: an adjacent (by vendor rank) pair is discordant only if the worse-ranked
#: value exceeds the better-ranked one by more than max(points, share x value).
B0_TOL_POINTS = 2.0
B0_TOL_SHARE = 0.005
#: R1: whole-source B0 iff discordant pairs >= share of adjacent pairs AND >=
#: the minimum count, OR Spearman(rank, value) > the maximum.
B0_WHOLE_SOURCE_SHARE = 0.05
B0_WHOLE_SOURCE_MIN_PAIRS = 10
B0_SPEARMAN_MAX = -0.5
#: R2: B3a is evaluated only with at least this many rows of the source and
#: class carrying a leave-source-out reference.
B3A_MIN_ROWS = 20
#: P-3: a cap-released vote becomes accepted on a cross-sectional release (a
#: provider within ln 1.25 — ``B4_CORROBORATION`` — or co-movement) or after
#: reproducing on this many content-distinct vendor datasets spanning >= hours.
P3_REPRODUCE_DATASETS = 3
P3_REPRODUCE_HOURS = 72.0
#: The V2.1 thresholds file (written by the V2.1 Stage 2 freeze).  Until it
#: exists V2.1 runs on V2's frozen file, stamped as provisional for V2.1.
V21_THRESHOLDS_PATH = REPO_ROOT / "config" / "sources" / "outlier_integrity_v21.json"
#: The persistence-rule version a board record carries when V2.1's P-1..P-4
#: (content-distinct evidence, holds and cap releases are not evidence) apply.
PERSISTENCE_RULES_V21 = "oiv21-P1-P4"

# ── Reason codes (directive §10; architecture §9) ───────────────────────────
STATUS_VOTING = "voting"
STATUS_REFUSED = "refused"
STATUS_WITHHELD = "withheld"
STATUS_QUARANTINED = "quarantined"
STATUS_HELD = "held"
#: Layer C: removed by the narrow cold-start tail rule. Still an ACCEPTED
#: observation for the history lane (DEVIATIONS.md C11): C is not an integrity
#: verdict, and a contrarian's persistence must be able to accumulate.
STATUS_REJECTED_TAIL = "rejected_tail"

REASON_VOTING = "voting"
REASON_NAME_ONLY = "voting_name_only_identity"
REASON_SEGMENT_BREAK_UNPROVEN = "segment_break_unproven"
REASON_FORMAT_SCHEMA = "source_format_error:schema"
REASON_FORMAT_NON_NUMERIC = "source_format_error:non_numeric_value"
REASON_FORMAT_RANK_VALUE = "source_format_error:vendor_rank_value_inconsistent"
REASON_UNTRANSLATED = "normalization_untranslated"
REASON_DEPENDENCY = "normalization_dependency_unavailable"
REASON_PROVENANCE = "broken_feed:payload_provenance_conflict"
REASON_HELD_DISCONTINUITY = "held_pending_confirmation:observation_discontinuity"
REASON_KEPT_DISSENT = "kept_dissent"
REASON_TAIL = "extreme_uncorroborated_tail"
ALERT_HOLD_CAP = "hold_released_at_cap"
# V2.1 (default OFF).
REASON_FORMAT_MINOR = "format_minor_discordance"
REASON_SEGMENT_TOO_SMALL = "segment_too_small"
REASON_TEAM_UNCONFIRMED = "voting_team_unconfirmed"
REASON_RELEASED_BY_CAP = "released_by_cap"
REASON_PERSISTENT_GROSS_DISSENT = "persistent_gross_dissent"
ALERT_PERSISTENT_GROSS_DISSENT = "persistent_gross_dissent"
#: Board-record status of a cap-released vote that counts in the blend but is
#: NOT an accepted observation (P-3).
STATUS_RELEASED_BY_CAP = "released_by_cap"
#: Advisory reasons a VOTING observation may carry (never an exclusion).
VOTING_ADVISORIES = frozenset(
    {REASON_FORMAT_MINOR, REASON_SEGMENT_TOO_SMALL, REASON_RELEASED_BY_CAP}
)

# The directive §10 categories and the reason -> category table live in the
# one per-observation vocabulary, ``src/sources/voting_status.py`` (V2.1
# preregistration R7: "mapped through voting_status.py, never a fork"); the
# names below are re-exports, kept so every existing import still resolves.
CATEGORY_VOTING = _voting_status.OBS_CATEGORY_VOTING
CATEGORY_DISSENT = _voting_status.OBS_CATEGORY_DISSENT
CATEGORY_IDENTITY = _voting_status.OBS_CATEGORY_IDENTITY
CATEGORY_FORMAT = _voting_status.OBS_CATEGORY_FORMAT
CATEGORY_NORMALIZATION = _voting_status.OBS_CATEGORY_NORMALIZATION
CATEGORY_STALE = _voting_status.OBS_CATEGORY_STALE
CATEGORY_BROKEN_FEED = _voting_status.OBS_CATEGORY_BROKEN_FEED
CATEGORY_MISSING = _voting_status.OBS_CATEGORY_MISSING
CATEGORY_HELD = _voting_status.OBS_CATEGORY_HELD
CATEGORY_RULE = _voting_status.OBS_CATEGORY_RULE

#: Reason code (or prefix before ``:`` / ``@``) → directive §10 category: the
#: shared table in ``voting_status`` (one owner).
REASON_CATEGORY: Mapping[str, str] = _voting_status.OBSERVATION_REASON_CATEGORY

#: Primary-reason precedence (architecture §9): identity > format / feed >
#: normalization > freshness > held > tail.
_PRECEDENCE = {
    CATEGORY_IDENTITY: 0,
    CATEGORY_FORMAT: 1,
    CATEGORY_BROKEN_FEED: 1,
    CATEGORY_NORMALIZATION: 2,
    CATEGORY_STALE: 3,
    CATEGORY_HELD: 4,
    CATEGORY_RULE: 5,
    CATEGORY_DISSENT: 6,
    CATEGORY_VOTING: 7,
}


def reason_category(code: str | None) -> str | None:
    """The directive §10 category of a reason code, or ``None`` if unknown
    (``voting_status.observation_reason_category``, the one owner)."""
    return _voting_status.observation_reason_category(code)


def primary_reason(codes: Iterable[str]) -> tuple[str | None, list[str]]:
    """``(primary, others)`` by the architecture's precedence; ties keep order."""
    ordered = [c for c in codes if c]
    if not ordered:
        return None, []
    ranked = sorted(
        enumerate(ordered),
        key=lambda t: (_PRECEDENCE.get(reason_category(t[1]) or "", 99), t[0]),
    )
    primary = ranked[0][1]
    return primary, [c for _i, c in ranked[1:]]


def scale_error_reason(source: str, asset_class: str, pos: str | None = None) -> str:
    scope = f"{source}/{asset_class}" + (f"/{pos}" if pos else "")
    return f"normalization_scale_error@{scope}"


def direction_error_reason(source: str, asset_class: str, pos: str) -> str:
    return f"normalization_direction_error@{source}/{asset_class}/{pos}"


# ── Flags (literal reads; the reachability test requires them) ─────────────


class ChallengerConflictError(RuntimeError):
    """``outlier_integrity_v2`` and V1 (``outlier_disagreement_policy``) are
    mutually exclusive: two owners of one decision is refused, not resolved."""


def v2_active() -> bool:
    """The master flag. Raises when V1 is on as well (architecture §3)."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    if not _ff.is_enabled("outlier_integrity_v2"):
        return False
    if _ff.is_enabled("outlier_disagreement_policy"):
        raise ChallengerConflictError(
            "outlier_integrity_v2 and outlier_disagreement_policy are both ON; they own "
            "the same decision and are mutually exclusive. Switch one off and restart."
        )
    return True


def identity_layer_active() -> bool:
    """Layer A: ``identity_evidence_v2`` under the master."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return v2_active() and _ff.is_enabled("identity_evidence_v2")


def provenance_guard_active() -> bool:
    """B2: ``payload_provenance_guard`` under the master."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return v2_active() and _ff.is_enabled("payload_provenance_guard")


def rookie_fail_closed_active() -> bool:
    """B1: ``rookie_ladder_fail_closed`` under the master."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return v2_active() and _ff.is_enabled("rookie_ladder_fail_closed")


def v21_active() -> bool:
    """V2.1 repairs: ``outlier_integrity_v21`` under the master (default OFF).
    OFF: every V2 layer behaves exactly as V2 registered it."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return v2_active() and _ff.is_enabled("outlier_integrity_v21")


def holds_as_withheld_active() -> bool:
    """D-1: ``integrity_holds_as_withheld`` under the master (a confidence change;
    evaluated separately as V2+D1)."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return v2_active() and _ff.is_enabled("integrity_holds_as_withheld")


def history_record_active() -> bool:
    """U4: ``source_rank_history_record`` (record-only; never moves a value)."""
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return _ff.is_enabled("source_rank_history_record")


def flag_snapshot() -> dict[str, bool]:
    from src.api import feature_flags as _ff  # noqa: PLC0415

    return {
        "outlier_integrity_v2": _ff.is_enabled("outlier_integrity_v2"),
        "identity_evidence_v2": _ff.is_enabled("identity_evidence_v2"),
        "payload_provenance_guard": _ff.is_enabled("payload_provenance_guard"),
        "rookie_ladder_fail_closed": _ff.is_enabled("rookie_ladder_fail_closed"),
        "integrity_holds_as_withheld": _ff.is_enabled("integrity_holds_as_withheld"),
        "source_rank_history_record": _ff.is_enabled("source_rank_history_record"),
        "outlier_integrity_v21": _ff.is_enabled("outlier_integrity_v21"),
    }


# ── V2.1 repair switches ───────────────────────────────────────────────────

#: Every V2.1 repair that changes code (V2.1 preregistration §3.2 / §3.4).
#: R9 registers V2's C4 rule unchanged (no code), R12 is ``P`` (§3.4).
REPAIR_IDS: tuple[str, ...] = (
    "R1",  # B0 tolerance
    "R2",  # B3a minimum n
    "R3",  # B3b n_min on every test; served-rule proof sources
    "R4",  # A3 position-family compatibility
    "R5",  # age interval basis
    "R6",  # ordinal-slot preservation
    "R7",  # explainer coverage
    "R8",  # team-only mismatch at cold start
    "R10",  # continuity read from the A4-chosen entry
    "R11",  # A1 against the full Sleeper directory
    "R13",  # compact per-vote stamps (contract size)
    "R14",  # B2 sign share over non-agreeing rows only
    "P",  # P-1..P-4 persistence and B4 release
)


@dataclass(frozen=True)
class Repairs:
    """Which V2.1 repairs a build applies.  Empty (the default) is V2 exactly.

    Serving reads ``outlier_integrity_v21`` (all repairs or none); the replay
    seam ``repairs_override`` can revert one repair at a time for the
    registered sensitivity S9.  Never a partial set in serving."""

    enabled: frozenset[str] = frozenset()

    def on(self, repair_id: str) -> bool:
        return repair_id in self.enabled

    @property
    def any(self) -> bool:
        return bool(self.enabled)

    @classmethod
    def all_on(cls) -> Repairs:
        return cls(frozenset(REPAIR_IDS))

    def without(self, *repair_ids: str) -> Repairs:
        return Repairs(self.enabled - set(repair_ids))

    def to_stamp(self) -> list[str]:
        return [r for r in REPAIR_IDS if r in self.enabled]


_REPAIRS_OVERRIDE: list[Repairs] = []


class repairs_override:  # noqa: N801 — used as a context manager
    """Replay seam: build the next board(s) with an explicit repair set (S9:
    V2.1 with one repair reverted).  Effective only while the master
    ``outlier_integrity_v2`` is on; never used in serving."""

    def __init__(self, repairs: Repairs) -> None:
        self.repairs = repairs

    def __enter__(self) -> repairs_override:
        _REPAIRS_OVERRIDE.append(self.repairs)
        return self

    def __exit__(self, *exc: Any) -> None:
        _REPAIRS_OVERRIDE.pop()


def repairs_for_build() -> Repairs:
    """The repair set of a build (call only while the master is on)."""
    if _REPAIRS_OVERRIDE:
        return _REPAIRS_OVERRIDE[-1]
    return Repairs.all_on() if v21_active() else Repairs()


# ── Thresholds ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IntegrityThresholds:
    """The constants selected on the exploratory population (preregistration
    §3.5), read from ``config/sources/outlier_integrity_v2.json``.

    Until Stage 2 freezes them, the file carries the MOST CONSERVATIVE grid
    point of each registered grid (fewest refusals / quarantines / holds) and
    ``status: provisional_stage1``; tables that need exploratory data
    (``tau_board``, ``tau_c``) are empty, and the layer that needs them
    abstains and says so. No value here was chosen by looking at V, I or R.
    """

    status: str = "provisional_stage1"
    tau_age: float | None = 2.0
    epsilon_b2: float = 0.05
    n_min: int = 20
    rho_min: float = 0.0
    tau_gross: float = math.log(4.0)
    k_c: float = 8.0
    #: Layer C guard 3 (``tau_C``): provisional = the LARGEST registered grid
    #: point (ln 6, fewest drops) until the Stage 2 freeze; never below ln 4.
    tau_c_big: float = math.log(6.0)
    tau_board: Mapping[str, float] = field(default_factory=dict)
    tau_c: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    def tau_board_for(self, source: str, asset_class: str) -> float | None:
        got = self.tau_board.get(f"{source}|{asset_class}")
        return float(got) if isinstance(got, (int, float)) else None

    def tau_c_for(self, source: str, band: str) -> float | None:
        got = (self.tau_c.get(source) or {}).get(band)
        if not isinstance(got, (int, float)):
            return None
        return max(B4_MIN_TAU_C, float(got))

    def to_stamp(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "tauAge": self.tau_age,
            "epsilonB2": self.epsilon_b2,
            "nMin": self.n_min,
            "rhoMin": self.rho_min,
            "tauGross": round(self.tau_gross, 6),
            "kC": self.k_c,
            "tauCLayerC": round(self.tau_c_big, 6),
            "tauBoardCells": len(self.tau_board),
            "tauCSources": len(self.tau_c),
        }


def load_thresholds(path: Path | None = None) -> IntegrityThresholds:
    """The thresholds file, or the in-code provisional defaults when absent."""
    p = path or THRESHOLDS_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return IntegrityThresholds()
    sel = raw.get("selected") if isinstance(raw, Mapping) else None
    if not isinstance(sel, Mapping):
        return IntegrityThresholds()
    base = IntegrityThresholds()

    def _num(key: str, default: Any) -> Any:
        v = sel.get(key, default)
        return v if v is None or isinstance(v, (int, float)) else default

    def _ln(raw: Any) -> Any:
        if isinstance(raw, str) and raw.startswith("ln "):
            return math.log(float(raw[3:]))
        return raw

    tau_gross = _ln(sel.get("tau_gross"))
    tau_c_big = _ln(sel.get("tau_C"))
    return IntegrityThresholds(
        status=str(raw.get("status") or base.status),
        tau_age=_num("tau_age", base.tau_age),
        epsilon_b2=float(_num("epsilon_b2", base.epsilon_b2)),
        n_min=int(_num("n_min", base.n_min)),
        rho_min=float(_num("rho_min", base.rho_min)),
        tau_gross=float(tau_gross) if isinstance(tau_gross, (int, float)) else base.tau_gross,
        k_c=float(_num("k_c", base.k_c)),
        tau_c_big=(
            max(math.log(4.0), float(tau_c_big))
            if isinstance(tau_c_big, (int, float))
            else base.tau_c_big
        ),
        tau_board=dict(sel.get("tau_board") or {}),
        tau_c={str(k): dict(v) for k, v in (sel.get("tau_c") or {}).items()},
    )


def load_v21_thresholds() -> IntegrityThresholds:
    """V2.1's thresholds: ``config/sources/outlier_integrity_v21.json`` once the
    V2.1 Stage 2 freeze writes it; until then V2's frozen file, stamped
    ``v2_frozen_provisional_for_v21``.  ``tau_age`` is R5's a-priori 1.0 year
    either way (fixed now, never selected)."""
    from src.identity.resolution import V21_TAU_AGE  # noqa: PLC0415

    if V21_THRESHOLDS_PATH.exists():
        t = load_thresholds(V21_THRESHOLDS_PATH)
    else:
        t = replace(load_thresholds(), status="v2_frozen_provisional_for_v21")
    return replace(t, tau_age=V21_TAU_AGE)


# ── The vote coordinate ────────────────────────────────────────────────────


def vote_coordinate(value: Any, asset_class: Any) -> float | None:
    """``u`` for a vote on the row's scope master (IDP master for IDP rows, the
    OFFENSE master otherwise), exactly V1's coordinate (``outlier_policy``),
    read from the vote value the blend uses. ``None``: no coordinate."""
    from src.api import outlier_policy as _v1  # noqa: PLC0415

    return _v1.rank_coordinate(value, _v1.scope_curve(asset_class))


def memoized_provider_of(fn: Callable[[str], str]) -> Callable[[str], str]:
    """A per-build memo of a provider lookup (the lineage registry is read once
    per source instead of once per vote pair). Same answers, never shared
    across builds."""
    cache: dict[str, str] = {}

    def _provider_of(key: str) -> str:
        got = cache.get(key)
        if got is None:
            got = cache[key] = fn(key)
        return got

    return _provider_of


def _count(value: Any) -> int | None:
    """A non-negative integer count, or ``None`` when absent / unreadable --
    never a fabricated 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0:
        return None
    return int(value)


def implied_rank(u: float) -> float:
    return max(0.0, math.exp(u) - RANK_OFFSET)


def depth_band(u: float) -> str:
    r = implied_rank(u)
    for edge, label in B4_BANDS:
        if r <= edge:
            return label
    return B4_BANDS[-1][1]


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def _avg_ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman correlation with average ranks; ``None`` when undefined."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


# ── B0: format ─────────────────────────────────────────────────────────────


def rank_value_discordant_rows(pairs: Iterable[tuple[float, float]]) -> int:
    """Rows whose value EXCEEDS the value of some strictly better-ranked row.

    Zero exactly when the board's rank order and value order agree (Spearman
    -1 on a tie-free board); ties in rank or value are not discordance, so a
    board with equal values at different ranks is not flagged.
    """
    by_rank: dict[float, list[float]] = defaultdict(list)
    for rank, value in pairs:
        if rank is None or value is None:
            continue
        if not (math.isfinite(rank) and math.isfinite(value)) or rank <= 0 or value <= 0:
            continue
        by_rank[float(rank)].append(float(value))
    running_min = math.inf
    bad = 0
    for rank in sorted(by_rank):
        vals = by_rank[rank]
        if running_min < math.inf:
            bad += sum(1 for v in vals if v > running_min)
        running_min = min(running_min, min(vals))
    return bad


@dataclass(frozen=True)
class FormatTolerance:
    """R1's reading of one value-plus-rank board."""

    adjacent_pairs: int
    discordant_pairs: int
    spearman: float | None
    whole_source: bool
    #: Canonical keys (where the census carried them) of the worse-ranked row
    #: of every discordant pair: stamped advisory, still voting.
    discordant_keys: tuple[str, ...]

    def to_evidence(self) -> dict[str, Any]:
        return {
            "adjacentPairs": self.adjacent_pairs,
            "discordantPairs": self.discordant_pairs,
            "spearman": None if self.spearman is None else round(self.spearman, 6),
            "wholeSource": self.whole_source,
            "discordantKeys": list(self.discordant_keys),
        }


def rank_value_tolerance(entries: Iterable[Sequence[Any]]) -> FormatTolerance:
    """R1 (V2.1 B0 tolerance) on one board's ``(rank, value[, key])`` entries.

    Sorted by vendor rank, an ADJACENT pair is discordant only if the
    worse-ranked value exceeds the better-ranked value by more than
    ``max(B0_TOL_POINTS, B0_TOL_SHARE x better value)``; tied ranks and tied
    values are never discordant.  Whole-source iff the discordant pairs are at
    least ``B0_WHOLE_SOURCE_SHARE`` of the adjacent pairs AND at least
    ``B0_WHOLE_SOURCE_MIN_PAIRS``, OR Spearman(rank, value) exceeds
    ``B0_SPEARMAN_MAX`` (an order-reversed board).  Non-positive and
    non-finite cells are not observations and are not read.  Deterministic:
    rank ties are broken by value (descending), then key.
    """
    clean: list[tuple[float, float, str]] = []
    for e in entries:
        if len(e) < 2:
            continue
        rank, value = e[0], e[1]
        key = str(e[2]) if len(e) > 2 and e[2] is not None else ""
        try:
            r, v = float(rank), float(value)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(r) and math.isfinite(v)) or r <= 0 or v <= 0:
            continue
        clean.append((r, v, key))
    clean.sort(key=lambda t: (t[0], -t[1], t[2]))
    adjacent = max(0, len(clean) - 1)
    bad = 0
    keys: list[str] = []
    for (r1, v1, _k1), (r2, v2, k2) in zip(clean, clean[1:]):
        if r2 == r1 or v2 == v1:
            continue
        if v2 - v1 > max(B0_TOL_POINTS, B0_TOL_SHARE * v1):
            bad += 1
            if k2:
                keys.append(k2)
    rho = spearman([t[0] for t in clean], [t[1] for t in clean])
    whole = (
        adjacent > 0
        and bad >= B0_WHOLE_SOURCE_MIN_PAIRS
        and bad >= B0_WHOLE_SOURCE_SHARE * adjacent
    ) or (rho is not None and rho > B0_SPEARMAN_MAX)
    return FormatTolerance(adjacent, bad, rho, bool(whole), tuple(sorted(set(keys))))


@dataclass(frozen=True)
class BoardFinding:
    """A source-, class- or segment-level integrity finding."""

    source: str
    reason: str
    scope: str  # "source" | "class:<asset class>" | "segment:<asset class>/<pos>"
    hard: bool
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_stamp(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "reason": self.reason,
            "category": reason_category(self.reason),
            "scope": self.scope,
            "hard": self.hard,
            "evidence": dict(self.evidence),
        }


def format_findings(
    source: str, census: Mapping[str, Any] | None, *, tolerant: bool = False
) -> list[BoardFinding]:
    """B0 on one source's parse census (fixed rules, no statistics).

    ``tolerant`` (V2.1 R1): the rank/value rule is ``rank_value_tolerance``;
    below the whole-source bar each discordant row gets an advisory
    ``format_minor_discordance`` finding (not hard: the votes still count).
    Schema, non-numeric and ``dataset_integrity`` rules are unchanged."""
    if not census:
        return []
    out: list[BoardFinding] = []
    pairs = list(census.get("rankValuePairs") or ())
    if tolerant and source not in B0_RANK_VALUE_EXEMPT and len(pairs) >= 2:
        keys = list(census.get("rankValueKeys") or ())
        if len(keys) != len(pairs):
            keys = [None] * len(pairs)
        tol = rank_value_tolerance([(r, v, k) for (r, v), k in zip(pairs, keys)])
        if tol.whole_source:
            out.append(
                BoardFinding(
                    source,
                    REASON_FORMAT_RANK_VALUE,
                    "source",
                    True,
                    {"rankValuePairs": len(pairs), **tol.to_evidence()},
                )
            )
        elif tol.discordant_pairs > 0:
            out.append(
                BoardFinding(
                    source,
                    REASON_FORMAT_MINOR,
                    "source",
                    False,
                    {"rankValuePairs": len(pairs), **tol.to_evidence()},
                )
            )
    elif source not in B0_RANK_VALUE_EXEMPT and len(pairs) >= 2:
        bad = rank_value_discordant_rows(pairs)
        if bad > 0:
            out.append(
                BoardFinding(
                    source,
                    REASON_FORMAT_RANK_VALUE,
                    "source",
                    True,
                    {"rankValuePairs": len(pairs), "discordantRows": bad},
                )
            )
    non_numeric = _count(census.get("nonNumericValueRows"))
    if non_numeric:
        # Never an exclusion: those cells were never observations. Reported so
        # "the vendor published nothing" and "we could not read it" differ.
        out.append(
            BoardFinding(
                source,
                REASON_FORMAT_NON_NUMERIC,
                "source",
                False,
                {"rows": _count(census.get("rows")), "nonNumericRows": non_numeric},
            )
        )
    return out


# ── B2: feed provenance ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProvenancePair:
    """One row carrying both copies of a source's observation."""

    row_idx: int
    group: str
    payload: float
    csv: float


@dataclass(frozen=True)
class ProvenanceResult:
    board_proof: bool
    proven_groups: tuple[str, ...]
    row_proofs: frozenset[int]
    group_stats: Mapping[str, Mapping[str, Any]]
    supporting: Mapping[str, Any]

    def to_stamp(self) -> dict[str, Any]:
        return {
            "boardProof": self.board_proof,
            "provenGroups": list(self.proven_groups),
            "rowProofs": len(self.row_proofs),
            "groups": {g: dict(v) for g, v in sorted(self.group_stats.items())},
            "supporting": dict(self.supporting),
        }


def provenance_check(
    pairs: Sequence[ProvenancePair],
    *,
    epsilon: float,
    format_toggle_off: bool = False,
    supporting: Mapping[str, Any] | None = None,
    nonzero_sign_share: bool = False,
) -> ProvenanceResult:
    """B2 for one source on one board (preregistration §3.2).

    Board proof: ``|m_g| > epsilon`` in at least two position groups, each with
    at least 15 overlapping rows (both copies at or above 100) and at least 80%
    of those rows on m_g's side, OR a capture stamp saying the SF / TEP toggle
    was off (``format_toggle_off``; no such stamp exists in any payload today,
    so callers pass ``False``). Row proof: ``|ln(payload / CSV)| > ln 2``.
    ``supporting`` evidence (coverage collapse, fallback share) is recorded and
    never sufficient. A healthy board gives m_g = 0.000 exactly.

    ``nonzero_sign_share`` (V2.1 R14): the 80% sign share counts only rows
    with ``|ln(payload / CSV)| > epsilon``; rows that agree with the CSV are
    neither sign.  Every other condition is unchanged, so a healthy capture
    (every row within epsilon) still never proves.
    """
    by_group: dict[str, list[float]] = defaultdict(list)
    rows: set[int] = set()
    for p in pairs:
        if p.payload <= 0 or p.csv <= 0:
            continue
        d = math.log(p.payload / p.csv)
        if abs(d) > B2_ROW_DISTANCE:
            rows.add(p.row_idx)
        if p.payload >= B2_MIN_VALUE and p.csv >= B2_MIN_VALUE:
            by_group[p.group].append(d)
    stats: dict[str, dict[str, Any]] = {}
    proven: list[str] = []
    for g in sorted(by_group):
        ds = by_group[g]
        m = _median(ds)
        same = sum(1 for d in ds if (d > 0 if m > 0 else d < 0)) if m != 0 else 0
        if nonzero_sign_share:
            moved = sum(1 for d in ds if abs(d) > epsilon)
            share = same / moved if moved else 0.0
        else:
            share = same / len(ds) if ds else 0.0
        hit = abs(m) > epsilon and len(ds) >= B2_MIN_GROUP_ROWS and share >= B2_SIGN_SHARE
        stats[g] = {"rows": len(ds), "medianLogRatio": round(m, 6), "signShare": round(share, 4)}
        if hit:
            proven.append(g)
    board = len(proven) >= B2_MIN_GROUPS or bool(format_toggle_off)
    return ProvenanceResult(
        board_proof=board,
        proven_groups=tuple(proven),
        row_proofs=frozenset(rows),
        group_stats=stats,
        supporting=dict(supporting or {}),
    )


# ── History lane (U4) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class PendingHold:
    u: float
    first_held_at: str | None
    fetches: int
    last_hash: str


@dataclass(frozen=True)
class ReleasedHold:
    """V2.1 P-3: a vote released by the B4 cap that counts in the blend but is
    NOT yet an accepted observation.  ``hashes`` are the content-distinct
    vendor datasets it has been observed on since the release (oldest first),
    ``first_at`` / ``last_at`` their board times."""

    u: float
    hashes: tuple[str, ...]
    first_at: str | None
    last_at: str | None


@dataclass(frozen=True)
class IntegrityHistory:
    """What the source_rank lane knows before a board is built.

    Keys: segments ``"source|class|pos"`` (``pos`` ``*`` = whole class) → the
    last ``HISTORY_WINDOW`` ACCEPTED median signed deviations, oldest first;
    observations ``"source|player key"`` → the last accepted vote coordinates;
    teams ``"source|player key"`` → the team the source published on its last
    accepted observation; pending ``"source|player key"`` → an open B4 hold;
    hashes ``source`` → content hash of the source's last board.

    "Accepted" means the observation passed A and B (it was not refused,
    withheld, quarantined or held). It is the source's own record, built from
    V2's own decisions on the boards before this one; never read from
    production by a replay.
    """

    as_of: str | None = None
    boards: int = 0
    segments: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    observations: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    teams: Mapping[str, str] = field(default_factory=dict)
    pending: Mapping[str, PendingHold] = field(default_factory=dict)
    hashes: Mapping[str, str] = field(default_factory=dict)
    #: V2.1 only (empty under V2, and then absent from the JSON):
    #: P-1 — the vendor dataset content hash of each entry of ``observations``
    #: (aligned), so one dataset counts once;
    obs_hashes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: P-3 — cap-released votes not yet accepted;
    released: Mapping[str, ReleasedHold] = field(default_factory=dict)
    #: R8 — the team-history map: ``player key`` → the distinct teams the
    #: board ROW carried on earlier boards (oldest first, newest last).
    row_teams: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.boards == 0

    def segment_baseline(self, key: str) -> float | None:
        got = self.segments.get(key)
        return _median(got) if got else None

    def observation_baseline(self, key: str) -> float | None:
        got = self.observations.get(key)
        return _median(got) if got else None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": "oiv2-source-rank-history/v1",
            "asOf": self.as_of,
            "boards": self.boards,
            "segments": {k: list(v) for k, v in sorted(self.segments.items())},
            "observations": {k: list(v) for k, v in sorted(self.observations.items())},
            "teams": dict(sorted(self.teams.items())),
            "pending": {
                k: {
                    "u": p.u,
                    "firstHeldAt": p.first_held_at,
                    "fetches": p.fetches,
                    "lastHash": p.last_hash,
                }
                for k, p in sorted(self.pending.items())
            },
            "hashes": dict(sorted(self.hashes.items())),
            **self._v21_json(),
        }

    def _v21_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.obs_hashes:
            out["obsHashes"] = {k: list(v) for k, v in sorted(self.obs_hashes.items())}
        if self.released:
            out["released"] = {
                k: {"u": r.u, "hashes": list(r.hashes), "firstAt": r.first_at, "lastAt": r.last_at}
                for k, r in sorted(self.released.items())
            }
        if self.row_teams:
            out["rowTeams"] = {k: list(v) for k, v in sorted(self.row_teams.items())}
        return out

    def previous_row_teams(self, player_key: str | None, current: str | None) -> tuple[str, ...]:
        """R8: the teams the row carried before ``current`` (newest first)."""
        if not player_key:
            return ()
        seq = [t for t in self.row_teams.get(player_key, ()) if t and t != current]
        return tuple(reversed(seq))

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> IntegrityHistory | None:
        """The folded state, or ``None`` when it is absent or malformed (an
        unreadable count is not a zero: the build then runs without history
        and says so)."""
        if not isinstance(raw, Mapping) or raw.get("schema") != "oiv2-source-rank-history/v1":
            return None
        boards = _count(raw.get("boards"))
        pending_raw = raw.get("pending") or {}
        if boards is None or any(
            not isinstance(v, Mapping) or _count(v.get("fetches")) is None
            for v in pending_raw.values()
        ):
            return None
        return cls(
            as_of=raw.get("asOf"),
            boards=boards,
            segments={
                k: tuple(float(x) for x in v) for k, v in (raw.get("segments") or {}).items()
            },
            observations={
                k: tuple(float(x) for x in v) for k, v in (raw.get("observations") or {}).items()
            },
            teams={str(k): str(v) for k, v in (raw.get("teams") or {}).items()},
            pending={
                k: PendingHold(
                    u=float(v["u"]),
                    first_held_at=v.get("firstHeldAt"),
                    fetches=int(v["fetches"]),
                    last_hash=str(v.get("lastHash") or ""),
                )
                for k, v in (raw.get("pending") or {}).items()
            },
            hashes={str(k): str(v) for k, v in (raw.get("hashes") or {}).items()},
            obs_hashes={
                str(k): tuple(str(x) for x in v) for k, v in (raw.get("obsHashes") or {}).items()
            },
            released={
                str(k): ReleasedHold(
                    u=float(v["u"]),
                    hashes=tuple(str(x) for x in v.get("hashes") or ()),
                    first_at=v.get("firstAt"),
                    last_at=v.get("lastAt"),
                )
                for k, v in (raw.get("released") or {}).items()
                if isinstance(v, Mapping) and isinstance(v.get("u"), (int, float))
            },
            row_teams={
                str(k): tuple(str(x) for x in v) for k, v in (raw.get("rowTeams") or {}).items()
            },
        )


def source_content_hash(observations: Iterable[tuple[str, Any]]) -> str:
    """Content hash of one source's board: sorted (player key, raw value)."""
    h = hashlib.sha256()
    for key, value in sorted((str(k), repr(v)) for k, v in observations):
        h.update(key.encode())
        h.update(b"\x00")
        h.update(value.encode())
        h.update(b"\x01")
    return h.hexdigest()[:20]


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── B3: segment integrity ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SegmentVote:
    row_idx: int
    asset_class: str
    pos: str
    source: str
    u: float


def leave_source_out_reference(
    source: str, row_votes: Mapping[str, float], provider_of: Callable[[str], str]
) -> float | None:
    """Median of the other sources' provider medians (the source itself left
    out), or ``None`` with fewer than ``B3_MIN_REFERENCE_PROVIDERS`` providers."""
    by_provider: dict[str, list[float]] = defaultdict(list)
    for k, u in row_votes.items():
        if k == source:
            continue
        by_provider[provider_of(k)].append(u)
    if len(by_provider) < B3_MIN_REFERENCE_PROVIDERS:
        return None
    return _median([_median(v) for v in by_provider.values()])


def leave_provider_out(
    source: str, row_votes: Mapping[str, float], provider_of: Callable[[str], str]
) -> dict[str, float]:
    """``{provider: median u}`` over every provider other than ``source``'s."""
    own = provider_of(source)
    by_provider: dict[str, list[float]] = defaultdict(list)
    for k, u in row_votes.items():
        p = provider_of(k)
        if p == own:
            continue
        by_provider[p].append(u)
    return {p: _median(v) for p, v in by_provider.items()}


@dataclass
class SegmentScreen:
    """B3's per-board result."""

    findings: list[BoardFinding] = field(default_factory=list)
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: (source, asset class, pos or None) → hard reason.
    quarantines: dict[tuple[str, str, str | None], str] = field(default_factory=dict)
    #: (source, asset class, pos) → advisory (votes kept).
    advisories: dict[tuple[str, str, str], str] = field(default_factory=dict)
    #: segment key → median signed deviation, for the history lane.
    medians: dict[str, float] = field(default_factory=dict)


def segment_rule(
    *,
    source: str,
    asset_class: str,
    pos: str,
    rows: int,
    rho: float | None,
    median: float,
    baseline: float | None,
    thresholds: IntegrityThresholds,
    proof: Collection[str],
    v21: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """B3b on one (source, asset class, position) segment: ``(hard reason,
    advisory reason, abstained)``.  The ONE rule the served screen and the
    Stage 2 selector both apply (V2.1 R3: the selector evaluates the served
    rule through the same code path).

    V2: ``n_min`` guards the direction test only.  V2.1 (R3): ``n_min`` guards
    EVERY B3b test — direction, gross scale and proof escalation — and a
    segment below it abstains, so a B1 / B2 proof never acts through a B3b test
    on a sub-``n_min`` segment.
    """
    if v21 and rows < thresholds.n_min:
        return None, None, "below_n_min"
    if rows >= thresholds.n_min and rho is not None and rho <= thresholds.rho_min:
        return direction_error_reason(source, asset_class, pos), None, None
    if baseline is not None and abs(median - baseline) >= thresholds.tau_gross:
        return scale_error_reason(source, asset_class, pos), None, None
    if baseline is not None and abs(median - baseline) >= B3_SHIFT_FLOOR:
        if source in proof:
            return scale_error_reason(source, asset_class, pos), None, None
        return None, REASON_SEGMENT_BREAK_UNPROVEN, None
    return None, None, None


def class_rule(
    *,
    source: str,
    asset_class: str,
    rows: int,
    median: float,
    baseline: float | None,
    tau_board: float | None,
    v21: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """B3a (rank-mass conservation) on one (source, asset class): ``(hard
    reason, advisory reason, abstained)``.

    V2.1 (R2): evaluated only with at least ``B3A_MIN_ROWS`` rows carrying a
    leave-source-out reference; below that it abstains and, where the rule
    could otherwise have been evaluated, stamps the advisory
    ``segment_too_small``."""
    if baseline is None:
        return None, None, "no_history"
    if tau_board is None:
        return None, None, "tau_board_unavailable"
    if v21 and rows < B3A_MIN_ROWS:
        return None, REASON_SEGMENT_TOO_SMALL, "segment_too_small"
    limit = max(B3A_MULTIPLIER * tau_board, B3A_FLOOR)
    if abs(median - baseline) >= limit:
        return scale_error_reason(source, asset_class), None, None
    return None, None, None


def segment_screen(
    rows: Mapping[int, tuple[str, str, Mapping[str, float]]],
    *,
    provider_of: Callable[[str], str],
    thresholds: IntegrityThresholds,
    history: IntegrityHistory | None,
    proof_sources: Iterable[str] = (),
    v21: bool = False,
    r2: bool = False,
    r3: bool = False,
) -> SegmentScreen:
    """B3 on one board.

    ``rows`` maps a row index to ``(asset class, position group, {source: u})``
    for every non-pick row (pick segments are report-only by authority, so the
    caller leaves picks out). ``proof_sources`` are sources carrying B0/B1/B2
    proof on this build. Deterministic and order-free: every statistic is a
    function of the multiset of votes. ``r2`` / ``r3`` apply V2.1's R2 / R3
    (``class_rule`` / ``segment_rule``); ``v21`` is both.
    """
    r2, r3 = r2 or v21, r3 or v21
    proof = set(proof_sources)
    seg: dict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for _idx in sorted(rows):
        asset_class, pos, votes = rows[_idx]
        for source in sorted(votes):
            ref = leave_source_out_reference(source, votes, provider_of)
            if ref is None:
                continue
            seg[(source, asset_class, pos)].append((votes[source], ref))
    out = SegmentScreen()
    by_class: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (source, asset_class, pos), pairs in sorted(seg.items()):
        resid = [u - r for u, r in pairs]
        by_class[(source, asset_class)].extend(resid)
        m = _median(resid)
        key = f"{source}|{asset_class}|{pos}"
        out.medians[key] = m
        rho = spearman([u for u, _r in pairs], [r for _u, r in pairs])
        base = history.segment_baseline(key) if history is not None else None
        stat: dict[str, Any] = {
            "rows": len(pairs),
            "medianSignedDeviation": round(m, 6),
            "spearman": None if rho is None else round(rho, 6),
            "baseline": None if base is None else round(base, 6),
        }
        hard, advisory, abstained = segment_rule(
            source=source,
            asset_class=asset_class,
            pos=pos,
            rows=len(pairs),
            rho=rho,
            median=m,
            baseline=base,
            thresholds=thresholds,
            proof=proof,
            v21=r3,
        )
        if abstained:
            stat["abstained"] = abstained
        if hard is not None:
            out.quarantines[(source, asset_class, pos)] = hard
            proven = (
                base is not None
                and abs(m - base) < thresholds.tau_gross
                and not hard.startswith("normalization_direction_error")
            )
            out.findings.append(
                BoardFinding(
                    source,
                    hard,
                    f"segment:{asset_class}/{pos}",
                    True,
                    {**stat, "provenBy": "same_build_b0_b1_b2_proof"} if proven else stat,
                )
            )
        elif advisory is not None:
            out.advisories[(source, asset_class, pos)] = advisory
            out.findings.append(
                BoardFinding(source, advisory, f"segment:{asset_class}/{pos}", False, stat)
            )
        out.stats[key] = stat
    # B3a — rank-mass conservation per (source, asset class).
    for (source, asset_class), resid in sorted(by_class.items()):
        m = _median(resid)
        key = f"{source}|{asset_class}|*"
        out.medians[key] = m
        base = history.segment_baseline(key) if history is not None else None
        tau_board = thresholds.tau_board_for(source, asset_class)
        stat = {
            "rows": len(resid),
            "medianResidual": round(m, 6),
            "baseline": None if base is None else round(base, 6),
            "tauBoard": tau_board,
        }
        if base is not None and tau_board is not None:
            stat["limit"] = round(max(B3A_MULTIPLIER * tau_board, B3A_FLOOR), 6)
        hard, advisory, abstained = class_rule(
            source=source,
            asset_class=asset_class,
            rows=len(resid),
            median=m,
            baseline=base,
            tau_board=tau_board,
            v21=r2,
        )
        if abstained:
            stat["abstained"] = abstained
        if hard is not None:
            out.quarantines[(source, asset_class, None)] = hard
            out.findings.append(BoardFinding(source, hard, f"class:{asset_class}", True, stat))
        elif advisory is not None:
            out.findings.append(BoardFinding(source, advisory, f"class:{asset_class}", False, stat))
        out.stats[key] = stat
    return out


# ── B4: per-observation continuity ─────────────────────────────────────────

B4_ABSTAIN = "abstain"
B4_ACCEPT = "accept"
B4_HOLD = "hold"
B4_RELEASE = "release"
#: V2.1 P-3: released by the cap — votes, stamped, NOT an accepted observation.
B4_RELEASED_BY_CAP = "released_by_cap"


@dataclass(frozen=True)
class ContinuityDecision:
    action: str
    detail: Mapping[str, Any] = field(default_factory=dict)
    alert: str | None = None

    @property
    def held(self) -> bool:
        return self.action == B4_HOLD

    @property
    def released_by_cap(self) -> bool:
        return self.action == B4_RELEASED_BY_CAP


def continuity_decision(
    *,
    source: str,
    player_key: str,
    row_votes: Mapping[str, float],
    provider_of: Callable[[str], str],
    history: IntegrityHistory | None,
    thresholds: IntegrityThresholds,
    source_hash: str,
    as_of: str | None,
    v21: bool = False,
) -> ContinuityDecision:
    """B4 for one observation (preregistration §3.2). ``row_votes`` are the
    row's current vote coordinates INCLUDING this one.

    ``v21`` applies P-3: a hold that reaches the release cap (2
    content-distinct fetches or 48 h) VOTES but is ``released_by_cap`` — not
    an accepted observation — and raises the source-health alert.  A
    cap-released vote becomes accepted only on a cross-sectional release (a
    provider within ln 1.25, or co-movement) or after reproducing on
    ``P3_REPRODUCE_DATASETS`` content-distinct datasets spanning
    ``P3_REPRODUCE_HOURS``; until then it keeps voting, stamped."""
    if history is None or source not in row_votes:
        return ContinuityDecision(B4_ABSTAIN, {"why": "no_history"})
    key = f"{source}|{player_key}"
    u_now = row_votes[source]
    others = {k: u for k, u in row_votes.items() if provider_of(k) != provider_of(source)}
    corroborated = any(abs(u - u_now) <= B4_CORROBORATION for u in others.values())
    prior = history.observation_baseline(key)
    du = None if prior is None else u_now - prior

    def _comoved() -> bool:
        if du is None or du == 0:
            return False
        by_provider: dict[str, list[float]] = defaultdict(list)
        for k, u in others.items():
            base = history.observation_baseline(f"{k}|{player_key}")
            if base is not None:
                by_provider[provider_of(k)].append(u - base)
        for deltas in by_provider.values():
            d = _median(deltas)
            if d * du > 0 and abs(d) >= B4_COMOVE_SHARE * abs(du):
                return True
        return False

    released = history.released.get(key) if v21 else None
    if released is not None:
        if corroborated or _comoved():
            return ContinuityDecision(B4_ACCEPT, {"why": "cross_sectional_release"})
        band = depth_band(prior if prior is not None else released.u)
        tau_r = thresholds.tau_c_for(source, band) or B4_MIN_TAU_C
        if abs(u_now - released.u) <= tau_r:
            hashes = list(released.hashes)
            if source_hash and source_hash not in hashes:
                hashes.append(source_hash)
            first = _parse_ts(released.first_at)
            now = _parse_ts(as_of)
            span_ok = (
                first is not None
                and now is not None
                and (now - first).total_seconds() >= P3_REPRODUCE_HOURS * 3600.0
            )
            if len(hashes) >= P3_REPRODUCE_DATASETS and span_ok:
                return ContinuityDecision(
                    B4_ACCEPT, {"why": "reproduced_content_distinct", "datasets": len(hashes)}
                )
            return ContinuityDecision(
                B4_RELEASED_BY_CAP,
                {"why": "released_by_cap_unconfirmed", "datasets": len(hashes)},
            )
        # Moved away from the released value: judged afresh below.
    pending = history.pending.get(key)
    if pending is not None:
        tau_c = thresholds.tau_c_for(source, depth_band(prior if prior is not None else pending.u))
        new_content = source_hash != pending.last_hash
        if new_content and tau_c is not None and abs(u_now - pending.u) <= tau_c:
            return ContinuityDecision(B4_RELEASE, {"why": "reproduced_on_next_fetch"})
        if corroborated or _comoved():
            return ContinuityDecision(B4_RELEASE, {"why": "corroborated_or_comoved"})
        cap_action = B4_RELEASED_BY_CAP if v21 else B4_RELEASE
        first = _parse_ts(pending.first_held_at)
        now = _parse_ts(as_of)
        if first is not None and now is not None:
            if (now - first).total_seconds() >= B4_HOLD_CAP_HOURS * 3600.0:
                return ContinuityDecision(cap_action, {"why": "hold_cap_hours"}, ALERT_HOLD_CAP)
        fetches = pending.fetches + (1 if new_content else 0)
        if fetches >= B4_HOLD_CAP_FETCHES:
            return ContinuityDecision(cap_action, {"why": "hold_cap_fetches"}, ALERT_HOLD_CAP)
        if not new_content:
            return ContinuityDecision(B4_HOLD, {"why": "same_content_still_pending"})
    if prior is None:
        return ContinuityDecision(B4_ABSTAIN, {"why": "no_prior_observation"})
    band = depth_band(prior)
    tau_c = thresholds.tau_c_for(source, band)
    if tau_c is None:
        return ContinuityDecision(B4_ABSTAIN, {"why": "tau_c_unavailable", "band": band})
    provider_medians = leave_provider_out(source, row_votes, provider_of)
    if not provider_medians:
        return ContinuityDecision(B4_ABSTAIN, {"why": "no_other_provider"})
    ref = _median(list(provider_medians.values()))
    jump = abs(u_now - prior) > tau_c
    away = abs(u_now - ref) - abs(prior - ref) >= B4_AWAY_GAIN and abs(u_now - ref) >= B4_AWAY_MIN
    detail = {
        "du": round(u_now - prior, 6),
        "tauC": round(tau_c, 6),
        "band": band,
        "reference": round(ref, 6),
    }
    if jump and away and not corroborated and not _comoved():
        return ContinuityDecision(B4_HOLD, detail)
    return ContinuityDecision(B4_ACCEPT, detail)


# ── Per-build accumulator ──────────────────────────────────────────────────


@dataclass
class IntegrityBuild:
    """Everything V2's A and B layers decide on ONE board build.

    Created by ``build_api_data_contract`` only while ``outlier_integrity_v2`` is
    on, filled by the enrichment and ranking passes, and stamped on the
    contract as ``sourceIntegrity``.
    """

    thresholds: IntegrityThresholds
    history: IntegrityHistory | None = None
    as_of: str | None = None
    identity_on: bool = False
    provenance_on: bool = False
    rookie_fail_closed_on: bool = False
    holds_as_withheld_on: bool = False
    history_state: str = "absent"
    #: Board-level findings (B0, B2 board proofs, B3).
    findings: list[BoardFinding] = field(default_factory=list)
    #: Sources quarantined whole by B0.
    source_quarantines: dict[str, str] = field(default_factory=dict)
    #: B3 hard quarantines from the screen, applied on the second pass.
    segment_quarantines: dict[tuple[str, str, str | None], str] = field(default_factory=dict)
    segment_advisories: dict[tuple[str, str, str], str] = field(default_factory=dict)
    #: Dependency propagation (``scale_integrity_lost`` over the quarantined set).
    dependency_sources: set[str] = field(default_factory=set)
    dependency_idp_shared_market: bool = False
    #: Sources with B0 / B1 / B2 proof on this build (B3's "same build" rule).
    proof_sources: set[str] = field(default_factory=set)
    #: B2 per-source results.
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Census counters.
    identity_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    vote_counts: dict[str, int] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    segment_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    segment_medians: dict[str, float] = field(default_factory=dict)
    ranking_passes: int = 1
    #: Layer C census: ``{source: {"dropped": n, "keptDissent": n}}`` and the
    #: guard that kept each guard-3 candidate.
    layer_c_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    layer_c_kept_because: dict[str, int] = field(default_factory=dict)
    layer_c_rows: int = 0
    #: V2.1: the repairs this build applies (empty = V2 exactly).
    repairs: Repairs = field(default_factory=Repairs)
    #: R1: ``{source: canonical keys of rows with a minor rank/value
    #: discordance}`` — advisory only, the votes still count.
    format_advisories: dict[str, set[str]] = field(default_factory=dict)
    #: R11: which Sleeper directory A1 resolved ids against.
    directory_state: str | None = None
    #: R4: ``{canonical name: fantasy positions}`` from the payload's Sleeper
    #: block (the directory's own facts win where present).
    fantasy_positions: Mapping[str, Sequence[str]] = field(default_factory=dict)

    @property
    def v21(self) -> bool:
        return self.repairs.any

    def count_identity(self, source: str, verdict: str) -> None:
        bucket = self.identity_counts.setdefault(source, {})
        bucket[verdict] = bucket.get(verdict, 0) + 1

    def count_vote(self, reason: str) -> None:
        self.vote_counts[reason] = self.vote_counts.get(reason, 0) + 1

    def count_layer_c(self, verdict: Any) -> None:
        """Fold one row's Layer C verdict (``outlier_policy.LayerCVerdict``)."""
        self.layer_c_rows += 1
        for source in verdict.dropped:
            bucket = self.layer_c_counts.setdefault(source, {})
            bucket["dropped"] = bucket.get("dropped", 0) + 1
        for source in verdict.dissent:
            bucket = self.layer_c_counts.setdefault(source, {})
            bucket["keptDissent"] = bucket.get("keptDissent", 0) + 1
        for why in verdict.kept_because.values():
            self.layer_c_kept_because[why] = self.layer_c_kept_because.get(why, 0) + 1

    def vote_exclusion(self, source: str, asset_class: str, pos: str) -> str | None:
        """The hard board-level reason excluding this vote, if any (B0 / B3 /
        dependency), by precedence."""
        codes: list[str] = []
        if source in self.source_quarantines:
            codes.append(self.source_quarantines[source])
        for key in ((source, asset_class, pos), (source, asset_class, None)):
            if key in self.segment_quarantines:
                codes.append(self.segment_quarantines[key])
        if source in self.dependency_sources:
            codes.append(REASON_DEPENDENCY)
        primary, _others = primary_reason(codes)
        return primary

    def layer_c_summary(self) -> dict[str, Any]:
        from src.api import outlier_policy as _op  # noqa: PLC0415

        return {
            "constants": _op.layer_c_constants(self.thresholds.tau_c_big),
            "rowsAssessed": self.layer_c_rows,
            "bySource": {
                k: dict(sorted(v.items())) for k, v in sorted(self.layer_c_counts.items())
            },
            "keptBecause": dict(sorted(self.layer_c_kept_because.items())),
        }

    def summary(self) -> dict[str, Any]:
        out = self._summary_v2()
        if self.repairs.any:
            out["repairs"] = self.repairs.to_stamp()
            out["proofSources"] = sorted(self.proof_sources)
            out["formatAdvisories"] = {
                k: len(v) for k, v in sorted(self.format_advisories.items()) if v
            }
            out["sleeperDirectory"] = self.directory_state
            out["persistenceRules"] = PERSISTENCE_RULES_V21 if self.repairs.on("P") else None
        return out

    def _summary_v2(self) -> dict[str, Any]:
        return {
            "version": POLICY_VERSION,
            "layers": list(LAYERS_IMPLEMENTED),
            "layerC": self.layer_c_summary(),
            "flags": flag_snapshot(),
            "thresholds": self.thresholds.to_stamp(),
            "historyLane": {
                "state": self.history_state,
                "asOf": None if self.history is None else self.history.as_of,
                "boards": 0 if self.history is None else self.history.boards,
            },
            "findings": [f.to_stamp() for f in self.findings],
            "sourceQuarantines": dict(sorted(self.source_quarantines.items())),
            "segmentQuarantines": {
                "/".join(x for x in k if x): v
                for k, v in sorted(
                    self.segment_quarantines.items(), key=lambda kv: tuple(str(x) for x in kv[0])
                )
            },
            "dependency": {
                "sources": sorted(self.dependency_sources),
                "idpSharedMarket": self.dependency_idp_shared_market,
            },
            "provenance": {k: v for k, v in sorted(self.provenance.items())},
            "identity": {
                k: dict(sorted(v.items())) for k, v in sorted(self.identity_counts.items())
            },
            "voteExclusions": dict(sorted(self.vote_counts.items())),
            "alerts": list(self.alerts),
            "segmentMedians": {k: round(v, 6) for k, v in sorted(self.segment_medians.items())},
            "segmentStats": {k: dict(v) for k, v in sorted(self.segment_stats.items())},
            "rankingPasses": self.ranking_passes,
        }


def integrity_stamp(
    status: str, reasons: Sequence[str], *, scope: str | None = None, **extra: Any
) -> dict[str, Any]:
    """The per-observation transparency block (architecture §9)."""
    primary, others = primary_reason(reasons)
    out: dict[str, Any] = {"status": status, "primaryReason": primary or REASON_VOTING}
    out["category"] = reason_category(out["primaryReason"])
    if others:
        out["otherReasons"] = others
    if scope:
        out["scope"] = scope
    for k, v in extra.items():
        if v is not None:
            out[k] = v
    return out


def vote_status_for(codes: Sequence[str]) -> str:
    """``withheld`` for a structural normalization exclusion (B1 / dependency),
    ``quarantined`` for a proven source / segment fault (B0 / B3)."""
    primary, _others = primary_reason(codes)
    if primary in (REASON_UNTRANSLATED, REASON_DEPENDENCY):
        return STATUS_WITHHELD
    if primary and primary.startswith(("identity_contradicted", "identity_unresolved")):
        # V2.1 R6: a Layer A refusal excluded at the vote keeps its status.
        return STATUS_REFUSED
    return STATUS_QUARANTINED


def voting_stamp(
    row: Mapping[str, Any], source: str, *, compact: bool = False
) -> dict[str, Any] | None:
    """The integrity block of a vote that passed A and B.

    V2.1: a ``TEAM_UNCONFIRMED`` identity votes as ``voting_team_unconfirmed``
    (R8) and an R1 advisory travels on the block.  ``compact`` (R13): a vote
    with nothing to say (VERIFIED or ungraded identity, no advisory) gets no
    block at all — ``None`` — because the absence of a block already reads as
    "voting normally" everywhere it is consumed."""
    ident = (row.get("sourceIntegrity") or {}).get(source)
    identity = ident.get("identity") if isinstance(ident, Mapping) else None
    advisory = ident.get("advisory") if isinstance(ident, Mapping) else None
    verdict = identity.get("verdict") if isinstance(identity, Mapping) else None
    reason = REASON_VOTING
    if verdict == "NAME_ONLY":
        reason = REASON_NAME_ONLY
    elif verdict == "TEAM_UNCONFIRMED":
        reason = REASON_TEAM_UNCONFIRMED
    if compact and reason == REASON_VOTING and not advisory:
        return None
    out = integrity_stamp(STATUS_VOTING, [reason])
    if verdict:
        out["identity"] = verdict
    if advisory:
        out["advisory"] = advisory
    return out


def player_key_for_row(row: Mapping[str, Any]) -> str | None:
    """The history lane's player key: the temporal ledger's own asset key
    (``src.history.keys``), so both lanes name a player the same way."""
    if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
        return None
    from src.history.keys import asset_key_for_contract_row  # noqa: PLC0415

    got = asset_key_for_contract_row(dict(row))
    return None if got is None else got[0]


def source_hashes_for_rows(
    rows: Sequence[Mapping[str, Any]], keys: Mapping[int, str | None] | None = None
) -> dict[str, str]:
    """``{source: content hash}`` over every non-pick row's raw observation."""
    per_source: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        pk = keys.get(idx) if keys is not None else player_key_for_row(row)
        if not pk:
            continue
        sites = row.get("canonicalSiteValues") or {}
        for source, value in sites.items():
            per_source[str(source)].append((pk, value))
        # V2.1 R6: a refused observation leaves ``canonicalSiteValues`` only
        # after the last ranking pass (it is kept on its stamp).  It is still
        # part of the vendor's dataset, so the hash a build computes and the
        # hash its board record computes see the same content.
        for source, stamp in (row.get("sourceIntegrity") or {}).items():
            if source in sites or not isinstance(stamp, Mapping):
                continue
            observed = stamp.get("refusedObservation")
            if isinstance(observed, Mapping) and "value" in observed:
                per_source[str(source)].append((pk, observed["value"]))
    return {s: source_content_hash(v) for s, v in sorted(per_source.items())}


def row_continuity_holds(
    row: Mapping[str, Any],
    pairs: Sequence[tuple[str, float]],
    *,
    player_key: str | None,
    integrity: IntegrityBuild,
    source_hashes: Mapping[str, str],
    provider_of: Callable[[str], str],
    released_out: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """B4 on one row: ``{source: held integrity stamp}`` for every vote held.

    Decisions are simultaneous — each vote is judged against the row's votes as
    they arrived, so the result does not depend on vote order. A release at the
    cap is recorded as an alert (the vote counts).  Under V2.1 (P-3) a vote
    released by the cap, or still unconfirmed after such a release, is put in
    ``released_out`` (``{source: continuity detail}``): it votes, stamped
    ``released_by_cap``, and is not an accepted observation.
    """
    if not player_key or integrity.history is None:
        return {}
    asset_class = row.get("assetClass")
    coords: dict[str, float] = {}
    for k, v in pairs:
        u = vote_coordinate(v, asset_class)
        if u is not None:
            coords[k] = u
    held: dict[str, dict[str, Any]] = {}
    for source in sorted(coords):
        decision = continuity_decision(
            source=source,
            player_key=player_key,
            row_votes=coords,
            provider_of=provider_of,
            history=integrity.history,
            thresholds=integrity.thresholds,
            source_hash=source_hashes.get(source, ""),
            as_of=integrity.as_of,
            v21=integrity.repairs.on("P"),
        )
        if decision.released_by_cap and released_out is not None:
            released_out[source] = dict(decision.detail)
        if decision.alert:
            integrity.alerts.append(
                {
                    "alert": decision.alert,
                    "source": source,
                    "player": player_key,
                    **dict(decision.detail),
                }
            )
        if decision.held:
            held[source] = integrity_stamp(
                STATUS_HELD,
                [REASON_HELD_DISCONTINUITY],
                continuity={k: v for k, v in decision.detail.items()},
            )
    return held


def persistence_confirmed(
    history: IntegrityHistory | None,
    thresholds: IntegrityThresholds,
    source: str,
    player_key: str | None,
    u: float,
) -> bool:
    """Layer C guard 4: the source's last ``C_PERSISTENCE_MIN`` (2) ACCEPTED
    observations of this player both sit within ``tau_c`` of ``u``.

    ``tau_c`` is the source's B4 continuity threshold for the depth band of its
    own prior median (never the new value's band). Until the Stage 2 freeze the
    ``tau_c`` table is empty and the registered floor ``ln 1.5`` is used: the
    strictest persistence test any frozen ``tau_c`` can produce, so it never
    exempts a vote a frozen threshold would not (DEVIATIONS.md C15). No history,
    or fewer than two accepted observations: not confirmed (cold start).
    """
    from src.api import outlier_policy as _op  # noqa: PLC0415

    if history is None or not player_key or not math.isfinite(u):
        return False
    got = history.observations.get(f"{source}|{player_key}")
    if not got or len(got) < _op.C_PERSISTENCE_MIN:
        return False
    recent = got[-_op.C_PERSISTENCE_MIN :]
    tau = thresholds.tau_c_for(source, depth_band(_median(got)))
    if tau is None:
        tau = B4_MIN_TAU_C
    return all(abs(u - x) <= tau for x in recent)


def layer_c_stamp(
    existing: Mapping[str, Any] | None,
    source: str,
    verdict: Any,
    *,
    v21: bool = False,
) -> dict[str, Any] | None:
    """The integrity block of one vote after Layer C, or ``None`` when Layer C
    has nothing to add (the vote keeps its existing ``voting`` block).

    Dropped -> ``rejected_tail`` / ``extreme_uncorroborated_tail`` (category
    "rejected by a justified integrity rule"; the vote is an accepted
    observation for the history lane). Kept further than ``ln 2`` from every
    other provider -> still ``voting``, primary reason ``kept_dissent``
    (category "valid but disagreeing" -- never an invalid category).
    """
    detail = verdict.details.get(source)
    if source in verdict.dropped:
        return integrity_stamp(
            STATUS_REJECTED_TAIL,
            [REASON_TAIL],
            layerC=dict(detail) if detail else None,
        )
    if source not in verdict.dissent:
        return None
    base = dict(existing) if isinstance(existing, Mapping) else {}
    from src.api import outlier_policy as _op  # noqa: PLC0415

    lead = REASON_KEPT_DISSENT
    if v21 and verdict.kept_because.get(source) == _op.C_KEPT_PERSISTENT:
        # P-4: persistence-confirmed while still beyond tau_C from every other
        # provider — votes, named, and alerted by the caller; never silent.
        lead = REASON_PERSISTENT_GROSS_DISSENT
    codes = [lead, str(base.get("primaryReason") or REASON_VOTING)]
    codes += [str(c) for c in base.get("otherReasons") or ()]
    out = integrity_stamp(
        STATUS_VOTING,
        [c for c in codes if c != REASON_VOTING],
        layerC=dict(detail) if detail else None,
        keptBecause=verdict.kept_because.get(source),
    )
    if base.get("identity"):
        out["identity"] = base["identity"]
    if v21 and base.get("advisory"):
        out["advisory"] = base["advisory"]
    return out


def stamp_segment_advisories(
    players_array: Sequence[Mapping[str, Any]],
    advisories: Mapping[tuple[str, str, str], str],
) -> int:
    """Add a kept segment advisory (``segment_break_unproven``) to every voting
    vote in an advised segment. The vote keeps voting; returns votes stamped."""
    if not advisories:
        return 0
    n = 0
    for row in players_array:
        if not isinstance(row, Mapping):
            continue
        asset_class = str(row.get("assetClass") or "")
        pos = str(row.get("position") or "").strip().upper()
        for source, meta in (row.get("sourceRankMeta") or {}).items():
            reason = advisories.get((str(source), asset_class, pos))
            if not reason or not isinstance(meta, dict):
                continue
            integ = meta.get("integrity")
            if isinstance(integ, dict) and integ.get("status") == STATUS_VOTING:
                integ["advisory"] = reason
                n += 1
            elif (
                integ is None
                and not meta.get("excludedReason")
                and not meta.get("hampelDropped")
                and meta.get("contributedToBlend") is not False
            ):
                # V2.1 R13: a compact (unstamped) vote gains a block only when
                # there is something to say.
                meta["integrity"] = {**integrity_stamp(STATUS_VOTING, []), "advisory": reason}
                n += 1
    return n


# ── Transparency census (directive §10) ────────────────────────────────────

#: ``sourceVotingEligibility[*].status`` (the existing per-source owner) →
#: directive §10 category. ``disabled_by_override`` is the user's own choice,
#: not a source fault, and keeps its own name.
ELIGIBILITY_CATEGORY: dict[str, str | None] = {
    "voting": CATEGORY_VOTING,
    "withheld": CATEGORY_STALE,
    "policy_held": CATEGORY_HELD,
    "seasonal_inactive": CATEGORY_HELD,
    "private_not_voting": CATEGORY_HELD,
    "no_observations": CATEGORY_MISSING,
    "disabled_by_override": None,
}
#: Observation states that are not a directive §10 category: reported under
#: their own name, never folded into an invalid category.
PASSTHROUGH_SUPERSEDED = "superseded_by_family"
PASSTHROUGH_OTHER_FILTER = "outlier_filter_challenger"


def observation_category(meta: Mapping[str, Any]) -> tuple[str, str]:
    """``(category, reason)`` for one ``sourceRankMeta`` entry, read from what
    the pipeline stamped -- never inferred. The integrity block wins (it was
    written by the layer that tested the observation); otherwise the existing
    exclusion stamps; otherwise the observation voted normally."""
    integ = meta.get("integrity")
    if isinstance(integ, Mapping) and integ.get("primaryReason"):
        reason = str(integ["primaryReason"])
        return str(integ.get("category") or reason_category(reason) or reason), reason
    excluded = meta.get("excludedReason")
    if excluded:
        reason = str(excluded)
        return reason_category(reason) or reason, reason
    if meta.get("supersededBy"):
        return PASSTHROUGH_SUPERSEDED, PASSTHROUGH_SUPERSEDED
    if meta.get("hampelDropped"):
        # Dropped by a filter challenger that took precedence over Layer C:
        # named as such, never as an integrity fault.
        return PASSTHROUGH_OTHER_FILTER, PASSTHROUGH_OTHER_FILTER
    return CATEGORY_VOTING, REASON_VOTING


def voting_category_census(
    players_array: Iterable[Mapping[str, Any]],
    eligibility: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Per source: the directive §10 category of every observation on the
    board, and the source-level state from ``sourceVotingEligibility``.

    ``rows`` counts observations by category; ``reasons`` by primary reason.
    A source with no observation on the board appears only through its
    eligibility entry (``missing_observation`` / held / stale) -- an absent
    observation is counted as missing evidence, never as a zero vote.
    """
    per_source: dict[str, dict[str, Any]] = {}

    def _entry(source: str) -> dict[str, Any]:
        return per_source.setdefault(source, {"rows": {}, "reasons": {}})

    for row in players_array:
        if not isinstance(row, Mapping):
            continue
        rank_meta = row.get("sourceRankMeta") or {}
        for source, meta in rank_meta.items():
            if not isinstance(meta, Mapping):
                continue
            category, reason = observation_category(meta)
            e = _entry(str(source))
            e["rows"][category] = e["rows"].get(category, 0) + 1
            e["reasons"][reason] = e["reasons"].get(reason, 0) + 1
        # Observations refused or withheld BEFORE ranking (Layer A identity,
        # B2 provenance without a CSV copy) never reach ``sourceRankMeta``;
        # their verdict lives on the row's ``sourceIntegrity`` block.
        for source, integ in (row.get("sourceIntegrity") or {}).items():
            if source in rank_meta or not isinstance(integ, Mapping):
                continue
            if not integ.get("status") or not integ.get("primaryReason"):
                continue
            reason = str(integ["primaryReason"])
            category = str(integ.get("category") or reason_category(reason) or reason)
            e = _entry(str(source))
            e["rows"][category] = e["rows"].get(category, 0) + 1
            e["reasons"][reason] = e["reasons"].get(reason, 0) + 1
    for source, info in (eligibility or {}).items():
        if not isinstance(info, Mapping):
            continue
        status = str(info.get("status") or "")
        e = _entry(str(source))
        e["sourceStatus"] = status or None
        e["sourceCategory"] = ELIGIBILITY_CATEGORY.get(status, status or None)
        if info.get("reason"):
            e["sourceReason"] = info.get("reason")
    out: dict[str, Any] = {}
    for source in sorted(per_source):
        e = per_source[source]
        out[source] = {
            **{k: v for k, v in e.items() if k not in ("rows", "reasons")},
            "rows": dict(sorted(e["rows"].items())),
            "reasons": dict(sorted(e["reasons"].items())),
        }
    totals: dict[str, int] = {}
    for e in out.values():
        for k, v in e["rows"].items():
            totals[k] = totals.get(k, 0) + v
    return {
        "categories": [
            CATEGORY_VOTING,
            CATEGORY_DISSENT,
            CATEGORY_IDENTITY,
            CATEGORY_FORMAT,
            CATEGORY_NORMALIZATION,
            CATEGORY_STALE,
            CATEGORY_BROKEN_FEED,
            CATEGORY_MISSING,
            CATEGORY_HELD,
            CATEGORY_RULE,
        ],
        "totals": dict(sorted(totals.items())),
        "sources": out,
    }


# ── History override (replay) and lane loading ─────────────────────────────

_HISTORY_OVERRIDE: list[IntegrityHistory | None] = []


class history_override:  # noqa: N801 — used as a context manager
    """Replay seam: build the next board(s) against an explicit history.

    ``with source_integrity.history_override(h): build_api_data_contract(...)``.
    ``None`` forces the empty-history (V2-NOHIST) state. Never used in serving.
    """

    def __init__(self, history: IntegrityHistory | None) -> None:
        self.history = history

    def __enter__(self) -> history_override:
        _HISTORY_OVERRIDE.append(self.history)
        return self

    def __exit__(self, *exc: Any) -> None:
        _HISTORY_OVERRIDE.pop()


def history_for_build(
    csv_root: Path | None, as_of: datetime | None
) -> tuple[IntegrityHistory | None, str]:
    """``(history, state)`` for a build: the replay override if one is set, else
    the source_rank lane under this build's own tree (never a later state)."""
    if _HISTORY_OVERRIDE:
        h = _HISTORY_OVERRIDE[-1]
        return h, "override" if h is not None else "override_empty"
    from src.history import source_rank as _lane  # noqa: PLC0415

    root = Path(csv_root) if csv_root is not None else REPO_ROOT
    raw = _lane.load_state(root, before=as_of)
    h = IntegrityHistory.from_json(raw)
    if h is None:
        return None, "absent"
    return h, "lane"


def new_build(csv_root: Path | None, as_of: datetime | None) -> IntegrityBuild:
    history, state = history_for_build(csv_root, as_of)
    repairs = repairs_for_build()
    return IntegrityBuild(
        thresholds=load_v21_thresholds() if repairs.any else load_thresholds(),
        repairs=repairs,
        history=history,
        history_state=state,
        as_of=None if as_of is None else as_of.astimezone(timezone.utc).isoformat(),
        identity_on=identity_layer_active(),
        provenance_on=provenance_guard_active(),
        rookie_fail_closed_on=rookie_fail_closed_active(),
        holds_as_withheld_on=holds_as_withheld_active(),
    )


# ── The board-level screen (second ranking pass) ───────────────────────────


def board_vote_rows(
    players_array: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[str, str, dict[str, float]]]:
    """``{row index: (asset class, position, {source: u})}`` over every non-pick
    row, from the votes the ranking pass stamped. Integrity-excluded votes are
    left out; votes the per-row filter dropped (incumbent, or Layer C's
    ``rejected_tail``) are kept (they are observations, and the filter is not
    an integrity verdict)."""
    out: dict[int, tuple[str, str, dict[str, float]]] = {}
    for idx, row in enumerate(players_array):
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        asset_class = str(row.get("assetClass") or "")
        pos = str(row.get("position") or "").strip().upper()
        votes: dict[str, float] = {}
        for source, meta in (row.get("sourceRankMeta") or {}).items():
            if not isinstance(meta, Mapping):
                continue
            integ = meta.get("integrity")
            if isinstance(integ, Mapping) and integ.get("status") not in (
                STATUS_VOTING,
                STATUS_REJECTED_TAIL,
            ):
                continue
            if meta.get("excludedReason"):
                continue
            u = vote_coordinate(meta.get("valueContribution"), asset_class)
            if u is not None:
                votes[str(source)] = u
        if votes:
            out[idx] = (asset_class, pos, votes)
    return out


def rank_with_segment_screen(
    rank_once: Callable[[], Any],
    players_array: list[Any],
    players_by_name: dict[str, Any],
    integrity: IntegrityBuild,
    *,
    provider_of: Callable[[str], str],
    dependency_of: Callable[[Iterable[str]], Mapping[str, Mapping[str, str]]],
) -> Any:
    """Rank, run B3 on the votes the pass priced, and re-rank once if B3 (or a
    B0 quarantine's dependants) excluded anything.

    Mirrors V1's ``rank_with_board_screen`` and takes its slot (never run
    alongside it). The votes are computed before any filter, so the first
    pass's votes ARE the second pass's: the screen is exact. Dependency
    propagation of B0 quarantines is applied before the first pass (by the
    caller), so a healthy board ranks once.
    """
    snapshot = copy.deepcopy((players_array, players_by_name))
    result = rank_once()
    screen = segment_screen(
        board_vote_rows(players_array),
        provider_of=provider_of,
        thresholds=integrity.thresholds,
        history=integrity.history,
        proof_sources=integrity.proof_sources,
        r2=integrity.repairs.on("R2"),
        r3=integrity.repairs.on("R3"),
    )
    integrity.findings.extend(screen.findings)
    integrity.segment_stats = screen.stats
    integrity.segment_medians = screen.medians
    integrity.segment_advisories = dict(screen.advisories)
    if screen.quarantines:
        integrity.segment_quarantines = dict(screen.quarantines)
        quarantined = {s for s, _c, _p in screen.quarantines} | set(integrity.source_quarantines)
        lost = dependency_of(quarantined)
        integrity.dependency_sources = set(lost.get("sources") or {})
        integrity.dependency_idp_shared_market = "idp" in (lost.get("assetClasses") or {})
        array0, by_name0 = snapshot
        players_array[:] = array0
        players_by_name.clear()
        players_by_name.update(by_name0)
        integrity.vote_counts.clear()
        integrity.alerts.clear()
        integrity.layer_c_counts.clear()
        integrity.layer_c_kept_because.clear()
        integrity.layer_c_rows = 0
        result = rank_once()
        integrity.ranking_passes = 2
    stamp_segment_advisories(players_array, integrity.segment_advisories)
    return result


# ── Board record for the history lane ──────────────────────────────────────


def board_record(
    contract: Mapping[str, Any],
    *,
    player_key_of: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> dict[str, Any]:
    """The source_rank lane's record of ONE built board (record-only).

    Per source: the content hash; per observation: the vote coordinate, the
    integrity status the board gave it, and the team the source published.
    Segment medians come from the board's own ``sourceIntegrity`` stamp when
    V2 was on (accepted segments only); without V2, every vote counts as
    accepted and no segment medians are recorded.
    """
    from src.history.keys import asset_key_for_contract_row  # noqa: PLC0415

    def _pk(row: Mapping[str, Any]) -> str | None:
        if player_key_of is not None:
            return player_key_of(row)
        got = asset_key_for_contract_row(dict(row))
        return None if got is None else got[0]

    rows = contract.get("playersArray") or []
    keys = {
        i: (_pk(r) if isinstance(r, Mapping) and r.get("assetClass") != "pick" else None)
        for i, r in enumerate(rows)
    }
    observations: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        pk = keys.get(idx)
        if not pk:
            continue
        identities = row.get("sourceIntegrity") or {}
        for source, meta in (row.get("sourceRankMeta") or {}).items():
            if not isinstance(meta, Mapping):
                continue
            u = vote_coordinate(meta.get("valueContribution"), row.get("assetClass"))
            if u is None:
                continue
            integ = meta.get("integrity")
            status = STATUS_VOTING
            if isinstance(integ, Mapping):
                status = str(integ.get("status") or STATUS_VOTING)
                if status == STATUS_VOTING and integ.get("advisory") == REASON_RELEASED_BY_CAP:
                    # P-3: votes, but is NOT an accepted observation.
                    status = STATUS_RELEASED_BY_CAP
            elif meta.get("excludedReason"):
                status = "excluded_" + str(meta.get("excludedReason"))
            team = None
            ident = identities.get(source) if isinstance(identities, Mapping) else None
            if isinstance(ident, Mapping) and isinstance(ident.get("identity"), Mapping):
                team = ident["identity"].get("entryTeam")
            observations[f"{source}|{pk}"] = {"u": round(u, 6), "status": status, "team": team}
    stamp = contract.get("sourceIntegrity") or {}
    persistence_rules = stamp.get("persistenceRules") if isinstance(stamp, Mapping) else None
    medians = stamp.get("segmentMedians") if isinstance(stamp, Mapping) else None
    quarantined = set()
    if isinstance(stamp, Mapping):
        for f in stamp.get("findings") or ():
            if isinstance(f, Mapping) and f.get("hard"):
                quarantined.add(str(f.get("source")) + "|" + str(f.get("scope")))
    out: dict[str, Any] = {
        "schema": "oiv2-board-record/v1",
        "asOf": contract.get("scrapeTimestamp") or contract.get("date"),
        "hashes": source_hashes_for_rows(rows, keys),
        "observations": dict(sorted(observations.items())),
        "segmentMedians": dict(sorted((medians or {}).items())),
        "quarantinedScopes": sorted(quarantined),
    }
    if persistence_rules == PERSISTENCE_RULES_V21:
        # V2.1: the record says which persistence rules fold it (P-1..P-4),
        # and carries the ROW's team per player for R8's team-history map.
        from src.identity.resolution import team_evidence  # noqa: PLC0415

        out["persistenceRules"] = PERSISTENCE_RULES_V21
        out["rowTeams"] = {
            pk: t
            for idx, r in enumerate(rows)
            if isinstance(r, Mapping)
            and (pk := keys.get(idx))
            and (t := team_evidence(r.get("team")))
        }
    return out


def advance(history: IntegrityHistory | None, record: Mapping[str, Any]) -> IntegrityHistory:
    """The history after one more board (V2's own decisions on that board).

    A record stamped ``persistenceRules: oiv21-P1-P4`` folds under V2.1's
    persistence rules (preregistration §3.4):

    * **P-1** an accepted observation enters the window only once per vendor
      dataset content hash — re-reading the same dataset adds nothing;
    * **P-2** refused, withheld, quarantined and B4-held observations are never
      accepted (as in V2);
    * **P-3** a ``released_by_cap`` vote is not accepted: it is tracked in
      ``released`` (content-distinct datasets and times) until a later board
      accepts it;
    * **P-4** a Layer C drop that passed A and B still accrues (C11), under
      P-1 and P-2.

    Any other record folds exactly as V2 registered it.
    """
    h = history or IntegrityHistory()
    v21 = record.get("persistenceRules") == PERSISTENCE_RULES_V21
    segments = dict(h.segments)
    quarantined = set(record.get("quarantinedScopes") or ())
    for key, m in (record.get("segmentMedians") or {}).items():
        source, asset_class, pos = (str(key).split("|") + ["", "", ""])[:3]
        scope = f"class:{asset_class}" if pos == "*" else f"segment:{asset_class}/{pos}"
        if f"{source}|{scope}" in quarantined:
            continue
        segments[key] = (tuple(segments.get(key, ())) + (float(m),))[-HISTORY_WINDOW:]
    observations = dict(h.observations)
    obs_hashes = dict(h.obs_hashes)
    released = dict(h.released)
    teams = dict(h.teams)
    pending = dict(h.pending)
    hashes = dict(h.hashes)
    new_hashes = dict(record.get("hashes") or {})
    for key, obs in (record.get("observations") or {}).items():
        source = str(key).split("|", 1)[0]
        status = obs.get("status")
        u = float(obs.get("u"))
        this_hash = new_hashes.get(source, "")
        if status in (STATUS_VOTING, STATUS_REJECTED_TAIL):
            if v21:
                prev_h = obs_hashes.get(key, ())
                if not (prev_h and this_hash and prev_h[-1] == this_hash):
                    observations[key] = (tuple(observations.get(key, ())) + (u,))[-HISTORY_WINDOW:]
                    obs_hashes[key] = (tuple(prev_h) + (this_hash,))[-HISTORY_WINDOW:]
                released.pop(key, None)
            else:
                observations[key] = (tuple(observations.get(key, ())) + (u,))[-HISTORY_WINDOW:]
            if obs.get("team"):
                teams[key] = str(obs["team"])
            pending.pop(key, None)
        elif v21 and status == STATUS_RELEASED_BY_CAP:
            pending.pop(key, None)
            prev = released.get(key)
            if prev is None:
                released[key] = ReleasedHold(
                    u, (this_hash,) if this_hash else (), record.get("asOf"), record.get("asOf")
                )
            elif this_hash and this_hash not in prev.hashes:
                released[key] = replace(
                    prev, u=u, hashes=prev.hashes + (this_hash,), last_at=record.get("asOf")
                )
        elif status == STATUS_HELD:
            prev = pending.get(key)
            if prev is None:
                pending[key] = PendingHold(u, record.get("asOf"), 0, this_hash)
            elif prev.last_hash != this_hash:
                pending[key] = replace(prev, u=u, fetches=prev.fetches + 1, last_hash=this_hash)
    hashes.update(new_hashes)
    row_teams = dict(h.row_teams)
    if v21:
        for pk, team in (record.get("rowTeams") or {}).items():
            seq = tuple(row_teams.get(pk, ()))
            if not seq or seq[-1] != team:
                row_teams[pk] = (seq + (str(team),))[-HISTORY_WINDOW:]
    return IntegrityHistory(
        as_of=record.get("asOf"),
        boards=h.boards + 1,
        segments=segments,
        observations=observations,
        teams=teams,
        pending=pending,
        hashes=hashes,
        obs_hashes=obs_hashes,
        released=released,
        row_teams=row_teams,
    )
