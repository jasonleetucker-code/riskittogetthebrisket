"""Per-source VOTING STATUS — is each registered source voting, at what weight, and why.

Owner directive 2026-10-19 ("Universal Source Voting and Freshness Policy"
§5 / §7 / §8; ``docs/sources/UNIVERSAL_FRESHNESS_SCHEDULE_2026-10-19.md``).
One entry per registered ranking source, in registry order, answering in
plain English the questions the Settings and Source Health pages show:

    Source | Last Updated | Freshness | Voting Weight | Status

This module DECIDES NOTHING.  It is a pure function of facts the canonical
pipeline already produced and stamped:

* freshness, clock and factors — the ``SourceWeighting`` objects of
  :mod:`src.sources.freshness` (the same objects the blend applied);
* whether a source is in the active set and why not — the contract's
  ``privateSourceAvailability`` (vote holds: private, shadow, owner policy)
  and ``sourceSeasonalState`` stamps, written by the vote-hold and seasonal
  owners in ``data_contract`` / ``seasonal_policy``;
* whether it actually influenced anything — every row's ``sourceRankMeta``
  (the blend's own per-observation record: applied weight, freshness /
  health exclusion, family supersession, outlier drop).

Nothing here is re-derived: a vote hold, a family treatment or an outlier
verdict is READ from what the contract stamps, so this payload cannot
disagree with the board it describes.  Public-safe by construction: source
metadata, dates, factors and row COUNTS only — never a player value.

Status vocabulary (``status`` -> owner label)::

    active_100  Active — 100%          stale       Stale — Not Voting
    active_75   Active — 75%           data_issue  Data Issue — Not Voting
    active_50   Active — 50%           seasonal    Seasonal — Not Voting
    active_25   Active — 25%           testing     Testing — Not Voting
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from src.sources.freshness import (
    CLOCK_BASIS_CONTENT,
    CLOCK_BASIS_NOT_TRACKED,
    CLOCK_BASIS_PUBLISHER,
    CLOCK_BASIS_UNKNOWN,
    SCHEDULE_V1,
    SCHEDULE_V2,
    STYLE_EXPLICIT,
    STYLE_SNAPSHOT,
    default_step_schedule,
    whole_days_elapsed,
)

VERSION = "source-voting-status/v1"

STATUS_ACTIVE_100 = "active_100"
STATUS_ACTIVE_75 = "active_75"
STATUS_ACTIVE_50 = "active_50"
STATUS_ACTIVE_25 = "active_25"
STATUS_STALE = "stale"
STATUS_DATA_ISSUE = "data_issue"
STATUS_SEASONAL = "seasonal"
STATUS_TESTING = "testing"

STATUS_LABELS: dict[str, str] = {
    STATUS_ACTIVE_100: "Active — 100%",
    STATUS_ACTIVE_75: "Active — 75%",
    STATUS_ACTIVE_50: "Active — 50%",
    STATUS_ACTIVE_25: "Active — 25%",
    STATUS_STALE: "Stale — Not Voting",
    STATUS_DATA_ISSUE: "Data Issue — Not Voting",
    STATUS_SEASONAL: "Seasonal — Not Voting",
    STATUS_TESTING: "Testing — Not Voting",
}
ACTIVE_STATUSES = frozenset(
    {STATUS_ACTIVE_100, STATUS_ACTIVE_75, STATUS_ACTIVE_50, STATUS_ACTIVE_25}
)

COVERAGE_OFFENSE = "offense"
COVERAGE_IDP = "idp"
COVERAGE_ROOKIE = "rookie"
COVERAGE_COMBINED = "combined"

_RESTORE_ON_PUBLISH = (
    "Returns to 100% of its base weight as soon as the publisher posts new rankings."
)

#: Provider display names (``config/sources/source_lineage.json`` ``providers``).
_IDP_POSITIONS = frozenset({"DL", "LB", "DB", "DE", "DT", "EDGE", "CB", "S", "ILB", "OLB"})


def coverage_of(src: Mapping[str, Any]) -> str:
    """offense / idp / rookie / combined, from the registry declaration."""
    if src.get("needs_rookie_translation"):
        return COVERAGE_ROOKIE
    scope = str(src.get("scope") or "")
    extra = {str(s) for s in (src.get("extra_scopes") or [])}
    if scope in ("overall_idp", "position_idp"):
        return COVERAGE_COMBINED if "overall_offense" in extra else COVERAGE_IDP
    return COVERAGE_OFFENSE


def _provider(key: str) -> tuple[str | None, str | None]:
    """``(provider id, provider display name)`` from the lineage registry."""
    try:
        from src.sources.source_census import load_lineage, provider_of  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — diagnostics never fail a build
        return None, None
    pid = provider_of(key)
    if pid is None:
        return None, None
    try:
        names = load_lineage().get("providers") or {}
    except (OSError, ValueError):
        names = {}
    return pid, str(names.get(pid) or pid)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _date(dt: datetime | None) -> str:
    return "an unknown date" if dt is None else dt.astimezone(timezone.utc).strftime("%b %d, %Y")


def _universe(row: Mapping[str, Any]) -> str:
    if row.get("assetClass") == "pick":
        return "pick"
    if row.get("assetClass") in ("idp", "offense"):
        return str(row["assetClass"])
    pos = str(row.get("position") or "").strip().upper()
    return "idp" if pos in _IDP_POSITIONS else "offense"


def _row_tallies(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per source: rows it voted on (by universe) and why it did not vote
    elsewhere — read from each row's ``sourceRankMeta``."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        meta = row.get("sourceRankMeta") or {}
        if not isinstance(meta, Mapping):
            continue
        uni = _universe(row)
        for key, m in meta.items():
            if not isinstance(m, Mapping):
                continue
            t = out.setdefault(
                str(key),
                {"voting": {"offense": 0, "idp": 0, "pick": 0}, "notVoting": {}, "applied": 0.0},
            )
            applied = m.get("appliedWeight")
            voted = (
                m.get("contributedToBlend") is not False
                and not m.get("hampelDropped")
                and isinstance(applied, (int, float))
                and not isinstance(applied, bool)
                and applied > 0
            )
            if voted:
                t["voting"][uni] += 1
                t["applied"] += float(applied)
                continue
            if m.get("hampelDropped"):
                reason = "outlier_filter"
            elif m.get("excludedReason"):
                reason = str(m["excludedReason"])
            elif m.get("supersededBy"):
                reason = "superseded_by_family"
            elif m.get("contributedToBlend") is False:
                reason = "not_contributed"
            else:
                reason = "zero_weight"
            t["notVoting"][reason] = t["notVoting"].get(reason, 0) + 1
    return out


def _subset_facts(sub: Any, *, schedule: str, as_of: datetime | None) -> dict[str, Any]:
    """Clock + freshness facts for one ``SubsetFreshness`` (or ``None``)."""
    if sub is None:
        return {
            "lastGenuineUpdate": None,
            "lastGenuineUpdateBasis": CLOCK_BASIS_UNKNOWN,
            "daysSinceUpdate": None,
            "freshness": None,
        }
    if schedule == SCHEDULE_V2:
        genuine = sub.genuine_update_at()
        basis = sub.clock_basis or CLOCK_BASIS_UNKNOWN
    else:
        # v1 rollback: the same clock the v1 rule judged on; the baseline
        # (a fetch time) is never published as a genuine update.
        genuine = None if (sub.clock_is_baseline or sub.clock_at is None) else sub.clock_at
        if sub.clock_at is None:
            basis = CLOCK_BASIS_NOT_TRACKED
        elif genuine is None:
            basis = CLOCK_BASIS_UNKNOWN
        elif sub.clock == "upstreamPublishedAt":
            basis = CLOCK_BASIS_PUBLISHER
        else:
            basis = CLOCK_BASIS_CONTENT
    ref = as_of or sub.as_of
    return {
        "lastGenuineUpdate": _iso(genuine),
        "lastGenuineUpdateBasis": basis,
        "daysSinceUpdate": None if genuine is None else whole_days_elapsed(genuine, ref),
        "freshness": float(sub.freshness),
        "_genuine": genuine,
        "_lowerBoundDays": (
            None if sub.clock_at is None else whole_days_elapsed(sub.clock_at, ref)
        ),
        "rowLevelClock": bool(getattr(sub, "row_changed_at", None))
        and getattr(sub, "style", None) not in (STYLE_SNAPSHOT, STYLE_EXPLICIT),
    }


def _pct(freshness: float | None, schedule: str) -> float | None:
    if freshness is None:
        return None
    pct = freshness * 100.0
    return float(round(pct)) if schedule == SCHEDULE_V2 else round(pct, 1)


def _active_status(freshness: float) -> str:
    if freshness >= 0.999:
        return STATUS_ACTIVE_100
    if freshness >= 0.75 - 1e-9:
        return STATUS_ACTIVE_75
    if freshness >= 0.5 - 1e-9:
        return STATUS_ACTIVE_50
    return STATUS_ACTIVE_25


def _ago(days: int | None) -> str:
    if days is None:
        return ""
    if days == 0:
        return " (less than a day ago)"
    return f" ({days} day{'s' if days != 1 else ''} ago)"


def _basis_phrase(basis: str) -> str:
    if basis == CLOCK_BASIS_PUBLISHER:
        return "the date the publisher says it last updated"
    if basis == CLOCK_BASIS_CONTENT:
        return "the last time we saw its rankings actually change"
    return "an unknown date"


def build_source_voting_status(
    contract: Mapping[str, Any],
    weighting: Mapping[str, Any] | None,
    registry: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """The ``sourceVotingStatus`` block for one built board.

    ``weighting`` is the ``{key: SourceWeighting}`` map the blend applied
    (``data_contract._source_weighting_resolution``) — every registered key
    is in it, including those held out of the active set.
    """
    summary = contract.get("sourceWeighting") or {}
    active = summary.get("sources") or {}
    applied = bool(summary.get("applied"))
    unavailable = summary.get("unavailableReason")
    vote_states = contract.get("privateSourceAvailability") or {}
    seasonal = (contract.get("sourceSeasonalState") or {}).get("inactive") or {}
    tallies = _row_tallies(contract.get("playersArray") or [])
    weighting = weighting or {}
    schedules = {getattr(sw, "schedule", SCHEDULE_V1) for sw in weighting.values()}
    schedule = SCHEDULE_V2 if SCHEDULE_V2 in schedules else SCHEDULE_V1
    max_days = default_step_schedule().max_days if schedule == SCHEDULE_V2 else None

    entries: list[dict[str, Any]] = []
    for src in registry:
        key = str(src.get("key") or "")
        if not key:
            continue
        base = max(0.0, float(src.get("weight") or 1.0))
        sw = weighting.get(key)
        measured = bool(sw is not None and getattr(sw, "measured", False))
        players_sub = sw.subset_for(False) if measured else None
        picks_sub = (sw.subsets.get("picks") if measured else None) or None
        facts = _subset_facts(players_sub, schedule=schedule, as_of=as_of)
        if not measured and sw is not None:
            # No recorded state: unmeasured, votes at base (both rules).
            facts["freshness"] = 1.0
            facts["lastGenuineUpdateBasis"] = CLOCK_BASIS_NOT_TRACKED
        health_factor = float(sw.health_factor) if sw is not None else 1.0
        coverage_factor = float(sw.coverage_factor) if sw is not None else 1.0
        freshness = facts["freshness"]
        tally = tallies.get(
            key, {"voting": {"offense": 0, "idp": 0, "pick": 0}, "notVoting": {}, "applied": 0.0}
        )
        players_voting = tally["voting"]["offense"] + tally["voting"]["idp"]
        picks_voting = tally["voting"]["pick"]
        in_active = key in active
        vstate = vote_states.get(key) or {}
        pid, pname = _provider(key)

        if in_active and applied and freshness is not None:
            effective = base * freshness * health_factor * coverage_factor
        elif in_active:
            effective = base
        else:
            effective = 0.0

        status, reason, restore = _decide(
            key=key,
            in_active=in_active,
            applied=applied,
            unavailable=unavailable,
            vstate=vstate,
            seasonal=seasonal.get(key),
            sw=sw,
            facts=facts,
            freshness=freshness,
            effective=effective,
            players_voting=players_voting + picks_voting,
            schedule=schedule,
            max_days=max_days,
        )
        entry: dict[str, Any] = {
            "key": key,
            "displayName": src.get("display_name") or key,
            "provider": pname,
            "providerId": pid,
            "family": src.get("correlation_group") or key,
            "coverage": coverage_of(src),
            "lastGenuineUpdate": facts["lastGenuineUpdate"],
            "lastGenuineUpdateBasis": facts["lastGenuineUpdateBasis"],
            "daysSinceUpdate": facts["daysSinceUpdate"],
            # Unknown (no recorded state) is published as unknown, never as a
            # measured 0%; the factor the blend applied is in weightFactors.
            "freshnessPct": (
                None
                if not measured or facts["lastGenuineUpdateBasis"] == CLOCK_BASIS_NOT_TRACKED
                else _pct(freshness, schedule)
            ),
            "baseWeight": round(base, 4),
            "effectiveWeight": round(effective, 4),
            "weightFactors": {
                "freshness": None if freshness is None else round(freshness, 4),
                "health": round(health_factor, 4),
                "coverage": round(coverage_factor, 4),
                "applied": applied,
            },
            "playersContributing": players_voting,
            "picksContributing": picks_voting,
            "contributingByUniverse": dict(tally["voting"]),
            "meanAppliedWeight": (
                round(tally["applied"] / (players_voting + picks_voting), 4)
                if (players_voting + picks_voting)
                else None
            ),
            "notVotingRows": dict(sorted(tally["notVoting"].items())),
            "voting": (players_voting + picks_voting) > 0,
            "status": status,
            "statusLabel": STATUS_LABELS[status],
            "reason": reason,
            "restoreRequirement": restore,
            "health": getattr(sw, "health_state", None) if sw is not None else None,
            "rowLevelClock": bool(facts.get("rowLevelClock")),
        }
        if vstate.get("holdKind") or vstate.get("heldFromVote"):
            entry["voteHold"] = {
                "reason": vstate.get("heldFromVote"),
                "kind": vstate.get("holdKind")
                or ("private" if vstate.get("private", True) else None),
                "decision": vstate.get("holdDecision"),
                "rollbackFlag": vstate.get("rollbackFlag"),
            }
        if picks_sub is not None:
            pf = _subset_facts(picks_sub, schedule=schedule, as_of=as_of)
            pfresh = pf["freshness"]
            entry["picks"] = {
                "lastGenuineUpdate": pf["lastGenuineUpdate"],
                "lastGenuineUpdateBasis": pf["lastGenuineUpdateBasis"],
                "daysSinceUpdate": pf["daysSinceUpdate"],
                "freshnessPct": _pct(pfresh, schedule),
                "effectiveWeight": round(
                    (base * pfresh * health_factor * coverage_factor)
                    if (in_active and applied and pfresh is not None)
                    else (base if in_active else 0.0),
                    4,
                ),
            }
        entries.append(entry)

    counts: dict[str, int] = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return {
        "version": VERSION,
        "asOf": _iso(as_of),
        "freshnessSchedule": schedule,
        "freshnessApplied": applied,
        "statusLabels": dict(STATUS_LABELS),
        "statusCounts": dict(sorted(counts.items())),
        "votingCount": sum(1 for e in entries if e["voting"]),
        "registeredCount": len(entries),
        "sources": entries,
    }


def _decide(
    *,
    key: str,
    in_active: bool,
    applied: bool,
    unavailable: Any,
    vstate: Mapping[str, Any],
    seasonal: Mapping[str, Any] | None,
    sw: Any,
    facts: Mapping[str, Any],
    freshness: float | None,
    effective: float,
    players_voting: int,
    schedule: str,
    max_days: int | None,
) -> tuple[str, str, str | None]:
    """``(status, reason, restoreRequirement)`` — first matching rule wins."""
    genuine = facts.get("_genuine")
    days = facts.get("daysSinceUpdate")
    basis = facts.get("lastGenuineUpdateBasis")

    if seasonal:
        cls = seasonal.get("classYear")
        cls_txt = f"the {cls} rookie class" if cls else "its rookie class"
        return (
            STATUS_SEASONAL,
            f"Rookie board between draft classes: {cls_txt} has graduated and the "
            "publisher has not posted the next class yet. This is a normal seasonal "
            "pause, not stale data.",
            "Votes again automatically when the publisher posts the next rookie class.",
        )
    vote_state = str(vstate.get("voteState") or "")
    if vote_state == "shadow":
        return (
            STATUS_TESTING,
            "Collected and checked in test mode only. Its IDP values are ranked within "
            "each position group and still need a validated translation onto the shared "
            "player scale before they can vote.",
            "Passes the shared-market translation validation and the owner-approved "
            "promotion gate.",
        )
    if vstate.get("holdKind") == "owner_policy" and not in_active:
        decision = vstate.get("holdDecision") or "an owner policy"
        return (
            STATUS_TESTING,
            f"Collected and shown, but held from voting by an owner decision ({decision}).",
            f"The owner policy hold is lifted (switch: {vstate.get('rollbackFlag') or 'policy'}).",
        )
    if vote_state == "rolled_back":
        return (
            STATUS_TESTING,
            "Collected, but its vote is switched off by an operator rollback switch.",
            "The rollback switch is turned back on.",
        )
    if vstate and vstate.get("state") == "not_provisioned":
        return (
            STATUS_DATA_ISSUE,
            "Private source that is collected only on the production server; it is "
            "not available where this board was built.",
            "Votes wherever its private collector runs (production).",
        )
    if vstate and vstate.get("state") == "missing":
        return (
            STATUS_DATA_ISSUE,
            "Its data file is missing on this server, so it cannot vote.",
            "The next successful download restores its data file.",
        )
    if not in_active:
        return (
            STATUS_DATA_ISSUE,
            "Not in this board's active source set.",
            "The source is re-enabled for the board.",
        )
    health = getattr(sw, "health_state", None) if sw is not None else None
    if sw is not None and float(getattr(sw, "health_factor", 1.0)) <= 0.0:
        errs = list(getattr(sw, "health_errors", []) or [])[:2]
        detail = f" ({'; '.join(errs)})" if errs else ""
        return (
            STATUS_DATA_ISSUE,
            f"The latest download was not a usable rankings board{detail}.",
            "The next successful download of a valid board restores its vote.",
        )
    if not applied:
        # Freshness not applied (rollback switch, or no dataset state for
        # this board): every collected source votes at its base weight.
        why = (
            "freshness could not be measured for this board"
            if unavailable
            else "freshness weighting is switched off"
        )
        if players_voting > 0:
            return (STATUS_ACTIVE_100, f"Votes at its full base weight ({why}).", None)
        return (
            STATUS_DATA_ISSUE,
            f"Collected, but none of its rows could be used on this board ({why}).",
            "Its players are matched and its values normalize onto the board.",
        )
    if basis == CLOCK_BASIS_NOT_TRACKED:
        if players_voting > 0:
            return (
                STATUS_ACTIVE_100,
                "Freshness is not measured for this board: our update tracking for this "
                "source does not reach back to the board's date, so it votes at its base "
                "weight (the standing rule for unmeasured sources).",
                None,
            )
        return (
            STATUS_DATA_ISSUE,
            "No update history is recorded for this source at this board's date, and "
            "none of its rows were used.",
            "Its board is recorded (dataset state) and its players are matched.",
        )
    if freshness is None or (basis == CLOCK_BASIS_UNKNOWN and (freshness or 0.0) <= 0.0):
        lower = facts.get("_lowerBoundDays")
        if max_days is not None and lower is not None and lower > max_days:
            return (
                STATUS_STALE,
                f"No genuine rankings update has been seen in the {lower} days we have "
                f"been tracking it — older than {max_days} days.",
                "Votes again (at 100%) as soon as the publisher posts new rankings.",
            )
        return (
            STATUS_DATA_ISSUE,
            "We have not yet seen this source publish a change since we started "
            "tracking it, so the date of its last genuine update is unknown.",
            "Votes as soon as we observe a genuine update (changed rankings or a "
            "publisher-stated update date).",
        )
    if freshness <= 0.0:
        limit = f"{max_days} days" if max_days is not None else "its freshness limit"
        since = _ago(days)
        return (
            STATUS_STALE,
            f"Its rankings were last genuinely updated on {_date(genuine)}{since}, based on "
            f"{_basis_phrase(str(basis))} — older than {limit}. We may still download it "
            "successfully; unchanged rankings do not count as an update.",
            "Votes again (at 100%) as soon as the publisher posts new rankings.",
        )
    if players_voting == 0:
        return (
            STATUS_DATA_ISSUE,
            "Fresh, but none of its players could be used on this board (matching or "
            "normalization problem).",
            "Its players are matched and its values normalize onto the board.",
        )
    status = _active_status(freshness)
    pct = _pct(freshness, schedule)
    since = _ago(days)
    if basis == CLOCK_BASIS_UNKNOWN:
        # v1 rollback only: the first-download time is a lower bound.
        reason = (
            "Its last genuine update date is unknown (only our first download time is "
            f"known); under the v1 rule it votes at {pct:g}% of its base weight."
        )
    else:
        reason = (
            f"Last genuine update {_date(genuine)}{since}, based on "
            f"{_basis_phrase(str(basis))}: votes at {pct:g}% of its base weight."
        )
    notes = []
    if sw is not None and float(getattr(sw, "health_factor", 1.0)) < 1.0:
        notes.append(f"its latest board looked partial ({health}), so it counts at reduced weight")
    if sw is not None and float(getattr(sw, "coverage_factor", 1.0)) < 1.0:
        notes.append("its board is smaller than usual, so it counts at reduced weight")
    if notes:
        reason += " Also, " + "; ".join(notes) + "."
    restore = None if status == STATUS_ACTIVE_100 else _RESTORE_ON_PUBLISH
    if effective <= 0.0:
        restore = restore or _RESTORE_ON_PUBLISH
    return status, reason, restore
