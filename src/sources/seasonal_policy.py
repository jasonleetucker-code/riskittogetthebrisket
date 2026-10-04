"""Declared seasonal windows for phase-dependent sources.  ONE owner.

Owner methodology decision 2026-10-03 (issue #1552; supersedes the open
choice in ``docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md`` §4).

Some boards legitimately stop existing for part of the year.  Flock's
``PROSPECTS_SF`` rookie board empties once the class graduates onto the
main board and stays empty until the next class is published.  Without a
declaration, "the vendor publishes no board this phase" and "the fetch
broke" arrive as the same silence: the fetcher exits 1, no success stamp is
written, the 2026 class keeps voting from a frozen CSV, and the freshness
watchdog stays red forever — which means it can no longer report a NEW
failure.

This module is the single answer to *"is this board expected to exist right
now?"*.  It does not answer *"is this board malformed or truncated?"* — the
fetcher's own shape and row-count guards keep that job, unchanged.

What it owns
────────────

* **Policy** — ``config/sources/seasonal_policy_v1.json``.  A source with no
  entry has no seasonal semantics: every consumer fails closed for it (a
  stray state file cannot make an undeclared source inactive).
* **Verdict** — :func:`classify_empty_response`: is THIS empty response the
  declared expected-empty signature, inside the declared window?
* **State** — ``data/scrape_state/<key>_seasonal.json``, written ONLY by the
  fetcher, ONLY on an expected-empty observation or on reactivation.  It
  carries an explicit ``seasonally_inactive`` state and a bounded transition
  history.  It never carries a success time: ``lastInactiveVerifiedAt`` is
  when the inactive signature was last re-observed, which is the proof that
  fetch attempts are continuing — not a claim that a board was acquired.
* **Readers** — :func:`inactive_sources_as_of` (the contract: no current
  vote) and :func:`watchdog_seasonal_split` (freshness watchdog / alert
  engine: inactive is green only while it keeps being re-verified within the
  source's normal staleness threshold).

Inactive means NO current vote — not a zero value, and not stale authority
decaying forever.  The historical CSV is never touched, so replay and
research keep the graduated class.  Reactivation is the first valid
non-empty response, whatever the date; after it the normal freshness policy
and every normal guard apply again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "ACTIVE",
    "CONFIG_PATH",
    "EmptyResponseVerdict",
    "SEASONALLY_INACTIVE",
    "SeasonalPolicy",
    "classify_empty_response",
    "contract_inactive_sources",
    "inactive_sources_as_of",
    "load_policies",
    "load_state",
    "record_inactive_observation",
    "record_reactivation",
    "state_as_of",
    "state_path",
    "watchdog_seasonal_split",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "sources" / "seasonal_policy_v1.json"
DEFAULT_STATE_DIR = REPO_ROOT / "data" / "scrape_state"

SEASONALLY_INACTIVE = "seasonally_inactive"
ACTIVE = "active"
_STATES = frozenset({SEASONALLY_INACTIVE, ACTIVE})

STATE_SUFFIX = "_seasonal.json"
SCHEMA_VERSION = 1
MAX_TRANSITIONS = 50


class SeasonalPolicyError(ValueError):
    """The declared policy file is malformed.  Loud, never silently empty."""


@dataclass(frozen=True)
class SeasonalPolicy:
    source_key: str
    policy_id: str
    data_field: str
    class_year_field: str
    format_field: str | None
    expected_format: str | None
    inactive_month: int
    inactive_day: int
    reactivation: str

    def window_for(self, class_year: int) -> tuple[datetime, datetime]:
        """``[start, end)`` in UTC for one class year — one declared cycle."""
        start = datetime(class_year, self.inactive_month, self.inactive_day, tzinfo=timezone.utc)
        end = datetime(class_year + 1, self.inactive_month, self.inactive_day, tzinfo=timezone.utc)
        return start, end


@dataclass(frozen=True)
class EmptyResponseVerdict:
    """Was an empty response the declared expected-empty state?

    ``expected`` False means: fail closed exactly as an undeclared source
    would.  ``reason`` always says why, in both directions.
    """

    expected: bool
    reason: str
    class_year: int | None = None


def _parse_month_day(text: Any, key: str) -> tuple[int, int]:
    try:
        month_s, day_s = str(text).split("-")
        month, day = int(month_s), int(day_s)
        datetime(2000, month, day)  # leap year: validates 02-29 too
    except (ValueError, TypeError) as exc:
        raise SeasonalPolicyError(
            f"{key}: inactiveFromMonthDay must be 'MM-DD', got {text!r}"
        ) from exc
    return month, day


def load_policies(path: Path | None = None) -> dict[str, SeasonalPolicy]:
    """``{source_key: SeasonalPolicy}``.  A missing file means no policies.

    A present-but-malformed file RAISES: a typo must not silently turn a
    declared seasonal source back into a permanently red one, nor (worse)
    the reverse.
    """
    cfg_path = Path(path) if path is not None else CONFIG_PATH
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SeasonalPolicyError(f"seasonal policy unreadable: {cfg_path}: {exc}") from exc
    sources = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(sources, dict):
        raise SeasonalPolicyError(f"{cfg_path}: 'sources' must be an object")
    out: dict[str, SeasonalPolicy] = {}
    for key, entry in sources.items():
        if not isinstance(entry, dict):
            raise SeasonalPolicyError(f"{key}: policy must be an object")
        empty = entry.get("expectedEmpty")
        if not isinstance(empty, dict):
            raise SeasonalPolicyError(f"{key}: expectedEmpty must be an object")
        data_field = str(empty.get("dataField") or "")
        year_field = str(empty.get("classYearField") or "")
        if not data_field or not year_field:
            raise SeasonalPolicyError(f"{key}: expectedEmpty needs dataField and classYearField")
        reactivation = str(entry.get("reactivation") or "")
        if reactivation != "first_valid_nonempty_response":
            raise SeasonalPolicyError(
                f"{key}: unsupported reactivation {reactivation!r} "
                "(only 'first_valid_nonempty_response' is defined)"
            )
        month, day = _parse_month_day(entry.get("inactiveFromMonthDay"), key)
        out[str(key)] = SeasonalPolicy(
            source_key=str(key),
            policy_id=str(entry.get("policyId") or key),
            data_field=data_field,
            class_year_field=year_field,
            format_field=(str(empty["formatField"]) if empty.get("formatField") else None),
            expected_format=(str(empty["format"]) if empty.get("format") else None),
            inactive_month=month,
            inactive_day=day,
            reactivation=reactivation,
        )
    return out


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return _utc(dt).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(text: Any) -> datetime | None:
    if not text or not isinstance(text, str):
        return None
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def classify_empty_response(
    policy: SeasonalPolicy | None, response: Any, now: datetime
) -> EmptyResponseVerdict:
    """Is ``response`` the declared expected-empty state at ``now``?

    Every condition must hold; any miss is ``expected=False`` (fail closed):

    * a declared policy exists for the source;
    * the response is an object whose ``dataField`` is a list of length 0 —
      the RAW list, so a non-empty board whose rows were all filtered out is
      a parse problem, never seasonal inactivity;
    * the declared format field (if any) equals the declared format;
    * the class-year field is an integer (``bool`` is not a year);
    * ``now`` lies in that class's declared window.
    """
    if policy is None:
        return EmptyResponseVerdict(False, "no_declared_seasonal_policy")
    if not isinstance(response, Mapping):
        return EmptyResponseVerdict(False, "response_not_an_object")
    data = response.get(policy.data_field)
    if not isinstance(data, list):
        return EmptyResponseVerdict(False, f"{policy.data_field}_not_a_list")
    if data:
        return EmptyResponseVerdict(False, "response_not_empty")
    if policy.format_field is not None:
        got = response.get(policy.format_field)
        if got != policy.expected_format:
            return EmptyResponseVerdict(
                False, f"format_mismatch:{got!r}!={policy.expected_format!r}"
            )
    year = response.get(policy.class_year_field)
    if isinstance(year, bool) or not isinstance(year, int):
        return EmptyResponseVerdict(False, f"class_year_missing_or_not_int:{year!r}")
    start, end = policy.window_for(year)
    at = _utc(now)
    if at < start:
        return EmptyResponseVerdict(
            False, f"before_declared_window:class={year}:opens={_iso(start)}", year
        )
    if at >= end:
        return EmptyResponseVerdict(
            False, f"after_declared_window:class={year}:closed={_iso(end)}", year
        )
    return EmptyResponseVerdict(True, f"expected_empty:class={year}:since={_iso(start)}", year)


# ── State ───────────────────────────────────────────────────────────────
def state_path(state_dir: Path, source_key: str) -> Path:
    return Path(state_dir) / f"{source_key}{STATE_SUFFIX}"


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _save(path: Path, state: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _current_state(state: Mapping[str, Any] | None) -> str | None:
    if not state:
        return None
    value = state.get("state")
    return value if value in _STATES else None


def record_inactive_observation(
    state_dir: Path,
    policy: SeasonalPolicy,
    verdict: EmptyResponseVerdict,
    observed_at: datetime,
    *,
    vendor_last_updated: Any = None,
) -> dict[str, Any]:
    """Fold one expected-empty observation into the source's state.

    Refuses a verdict that is not ``expected`` — the only way into the
    inactive state is the declared signature.  Writes NO success stamp, no
    CSV and no row: the state file is the whole record.
    """
    if not verdict.expected:
        raise ValueError(
            f"{policy.source_key}: refusing to record seasonal inactivity for a "
            f"non-expected empty response ({verdict.reason})"
        )
    path = state_path(state_dir, policy.source_key)
    prior = load_state(path) or {}
    at = _iso(observed_at)
    transitions = list(prior.get("transitions") or [])
    if _current_state(prior) != SEASONALLY_INACTIVE:
        transitions.append(
            {
                "state": SEASONALLY_INACTIVE,
                "at": at,
                "classYear": verdict.class_year,
                "reason": verdict.reason,
            }
        )
        since = at
    else:
        since = str(prior.get("since") or at)
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceKey": policy.source_key,
        "policyId": policy.policy_id,
        "state": SEASONALLY_INACTIVE,
        "since": since,
        "classYear": verdict.class_year,
        # When the expected-empty signature was last RE-OBSERVED.  Proof that
        # attempts continue; never a success / freshness time.
        "lastInactiveVerifiedAt": at,
        "lastObservation": {
            "at": at,
            "outcome": "expected_empty",
            "reason": verdict.reason,
            "rawRowCount": 0,
            "vendorLastUpdated": vendor_last_updated,
        },
        "transitions": transitions[-MAX_TRANSITIONS:],
    }
    _save(path, state)
    return state


def record_reactivation(
    state_dir: Path,
    source_key: str,
    observed_at: datetime,
    *,
    row_count: int,
    class_year: Any = None,
) -> dict[str, Any] | None:
    """Close an inactive window on the first valid non-empty board.

    Called by the fetcher AFTER the board passed every normal guard and the
    CSV was written (so a crash between the two leaves the source excluded,
    never voting with the graduated board).  Writes only on a real
    transition: with no state file, or a state already ``active``, it is a
    no-op and returns ``None``.
    """
    if row_count <= 0:
        raise ValueError(f"{source_key}: reactivation requires a non-empty board")
    path = state_path(state_dir, source_key)
    prior = load_state(path)
    if _current_state(prior) != SEASONALLY_INACTIVE:
        return None
    at = _iso(observed_at)
    transitions = list((prior or {}).get("transitions") or [])
    transitions.append(
        {
            "state": ACTIVE,
            "at": at,
            "classYear": class_year if isinstance(class_year, int) else None,
            "reason": f"first_valid_nonempty_response:rows={row_count}",
        }
    )
    state = {
        **(prior or {}),
        "schemaVersion": SCHEMA_VERSION,
        "sourceKey": source_key,
        "state": ACTIVE,
        "since": at,
        "classYear": class_year if isinstance(class_year, int) else None,
        "lastInactiveVerifiedAt": None,
        "lastObservation": {
            "at": at,
            "outcome": "valid_board",
            "rawRowCount": row_count,
        },
        "transitions": transitions[-MAX_TRANSITIONS:],
    }
    _save(path, state)
    return state


def state_as_of(state: Mapping[str, Any] | None, as_of: datetime | None) -> str | None:
    """The source's seasonal state at ``as_of`` (``None`` = latest).

    Read from the transition history so a board rebuilt for time T sees the
    state in force at T — never a later transition (determinism; the same
    reason freshness is evaluated at the board's own scrape time).  ``None``
    when no transition precedes ``as_of`` (no seasonal claim at all).
    """
    if not state:
        return None
    transitions = [t for t in state.get("transitions") or [] if isinstance(t, Mapping)]
    if as_of is None:
        return _current_state(state)
    cutoff = _utc(as_of)
    latest: str | None = None
    latest_at: datetime | None = None
    for t in transitions:
        at = _parse_iso(t.get("at"))
        st = t.get("state")
        if at is None or st not in _STATES or at > cutoff:
            continue
        if latest_at is None or at >= latest_at:
            latest, latest_at = str(st), at
    return latest


def inactive_sources_as_of(
    state_dir: Path | None,
    as_of: datetime | None,
    *,
    policies: Mapping[str, SeasonalPolicy] | None = None,
) -> dict[str, dict[str, Any]]:
    """``{source_key: info}`` for declared sources inactive at ``as_of``.

    The contract's question: which sources cast no current vote.  Only keys
    with a declared policy are eligible — a state file for an undeclared
    source is ignored (fail closed to the source's normal behaviour).
    """
    pols = load_policies() if policies is None else policies
    if not pols:
        return {}
    root = Path(state_dir) if state_dir is not None else DEFAULT_STATE_DIR
    out: dict[str, dict[str, Any]] = {}
    for key, policy in pols.items():
        state = load_state(state_path(root, key))
        if state_as_of(state, as_of) != SEASONALLY_INACTIVE:
            continue
        out[key] = {
            "state": SEASONALLY_INACTIVE,
            "policyId": policy.policy_id,
            "since": (state or {}).get("since"),
            "classYear": (state or {}).get("classYear"),
            "lastInactiveVerifiedAt": (state or {}).get("lastInactiveVerifiedAt"),
        }
    return out


def contract_inactive_sources(contract: Any) -> frozenset[str]:
    """Sources a BUILT contract recorded as seasonally inactive.

    Reads the contract's own ``sourceSeasonalState.inactive`` stamp — the
    state in force at THAT board's scrape time — never the state directory.
    A coverage check asks "should this source be on THIS board?", and only
    the board can answer it: the refresh workflow builds the board before
    the seasonal fetcher runs, so on a reactivation (or inactivation) run
    the current state and the board's state legitimately differ, and
    comparing a board with today's state reports a regression that is not
    there.

    Any missing or malformed stamp answers the empty set: nothing is
    excused, the source is judged normally (fail closed).
    """
    if not isinstance(contract, Mapping):
        return frozenset()
    block = contract.get("sourceSeasonalState")
    inactive = block.get("inactive") if isinstance(block, Mapping) else None
    if not isinstance(inactive, Mapping):
        return frozenset()
    return frozenset(str(k) for k in inactive if isinstance(k, str) and k)


def watchdog_seasonal_split(
    state_dir: Path | None,
    now: datetime,
    threshold_for: Any,
    *,
    policies: Mapping[str, SeasonalPolicy] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """``(verified_inactive, lapsed_inactive)`` for the freshness watchdog.

    ``verified_inactive`` — currently inactive AND the expected-empty
    signature was re-observed within the source's NORMAL staleness threshold
    (``threshold_for(key) -> hours``).  These are reported, not failed.

    ``lapsed_inactive`` — currently inactive but not re-verified within that
    threshold.  The fetcher has stopped answering (network, auth, a changed
    response), so the inactive claim is no longer evidence; the caller keeps
    the source in the normal stale classification.  This is what stops a
    declared window from becoming "this source is unmonitored".
    """
    pols = load_policies() if policies is None else policies
    root = Path(state_dir) if state_dir is not None else DEFAULT_STATE_DIR
    verified: dict[str, dict[str, Any]] = {}
    lapsed: dict[str, dict[str, Any]] = {}
    at = _utc(now)
    for key, policy in (pols or {}).items():
        state = load_state(state_path(root, key))
        if _current_state(state) != SEASONALLY_INACTIVE:
            continue
        verified_at = _parse_iso((state or {}).get("lastInactiveVerifiedAt"))
        threshold = float(threshold_for(key))
        age = None if verified_at is None else max(0.0, (at - verified_at).total_seconds() / 3600)
        info = {
            "policyId": policy.policy_id,
            "since": (state or {}).get("since"),
            "classYear": (state or {}).get("classYear"),
            "lastInactiveVerifiedAt": (state or {}).get("lastInactiveVerifiedAt"),
            "verificationAgeHours": None if age is None else round(age, 2),
            "thresholdHours": threshold,
        }
        if age is not None and age <= threshold:
            verified[key] = info
        else:
            lapsed[key] = info
    return verified, lapsed
