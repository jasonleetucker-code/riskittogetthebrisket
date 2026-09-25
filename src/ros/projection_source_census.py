"""C5-PROJ-A — projection-source capability / access / lineage census.

Governed by ``docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md``. This is the
FIRST sub-unit of the multi-source projection ensemble (``C5-U1``), and its
job is narrow: **record what exists and what is authorized before any
automation is built or extended.** It does not fetch, parse, or score
anything — that is C5-PROJ-B onward.

Data lives at ``config/projections/source_capability_census.json``. This
module is the validating loader, in the same "registry as data + typed
loader" shape as ``src.ros.sources.ROS_SOURCES`` and
``src.api.data_contract._RANKING_SOURCES`` — a new parallel registry
because this census answers a different question (evidence class / access
authorization) than either of those, over a population that mostly does
not yet have a scraper module to register into ``ROS_SOURCES``.

**This module authorizes no automation by itself.** ``access_posture`` is
data describing what is recorded, not a permission grant — see
``AccessPosture`` below. A source's ``PUBLIC_NO_AUTH`` posture means the
census evidence says no login is required; it is not this module deciding
that fetching the source is authorized product scope.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.utils.config_loader import repo_root

CENSUS_PATH = repo_root() / "config" / "projections" / "source_capability_census.json"

#: The three evidence classes the ensemble plan (§4, §6) requires the
#: weekly/ROS ensemble to keep distinct, plus RANKINGS_ONLY — a
#: disqualifying fourth class this census uses to flag a source that does
#: not qualify as any of the plan's three at all (plan: "Flag any source
#: that is rankings-only rather than a true projection model").
EVIDENCE_CLASSES: frozenset[str] = frozenset(
    {"PROJECTION_MODEL", "DFS_PROJECTION", "BETTING_MARKET", "RANKINGS_ONLY"}
)

#: Horizon vocabulary, taken verbatim from plan §4's observation-contract
#: field list. Deliberately a SEPARATE closed set from
#: ``src.api.data_contract.GAME_TYPES`` (DYNASTY/REDRAFT/REST_OF_SEASON/...)
#: — that vocabulary answers "is this dynasty evidence", a canonical-value
#: question this census must never touch; horizon answers "what time
#: window does this forecast cover", a seasonal-lane-only question.
HORIZONS: frozenset[str] = frozenset(
    {"WEEKLY", "REST_OF_SEASON", "PRESEASON_FULL_SEASON", "SELECTED_WEEKS"}
)

#: Access-authorization vocabulary. Every entry must carry one — an
#: unrecorded access posture is not distinguishable from "safe to
#: automate", which is exactly the ambiguity plan §3 exists to close
#: ("Subscription access must not be silently equated with unrestricted
#: automated acquisition/redistribution rights").
ACCESS_POSTURES: frozenset[str] = frozenset(
    {
        "PUBLIC_NO_AUTH",
        "CREDENTIALED_SESSION_ALREADY_WIRED",
        "SUBSCRIPTION_SCOPE_UNRECORDED",
        "NO_ACCESS_PATH_RECORDED",
        # A specific endpoint IS recorded and needs no credential, but it is
        # not part of the provider's documented API and no artifact records
        # terms permitting automated consumption. Distinct from
        # PUBLIC_NO_AUTH (an openly offered file/page) because "reachable
        # without a login" is not "licensed for automation". Fails closed.
        "PUBLIC_UNDOCUMENTED_NO_AUTH",
        # A documented commercial API that needs a per-account key. The key
        # lives only in the entry's ``credentialEnvVar``; its absence makes
        # the source unavailable at runtime, never zero data. Whether the
        # source may be automated at all is ``licensingStatus``.
        "KEYED_API_CREDENTIAL_REQUIRED",
    }
)

#: Licensing vocabulary. Optional per entry (the older entries predate
#: it); when present it must be one of these. ``UNVERIFIED`` is an
#: explicit open item, never a quiet "probably fine".
#: ``OWNER_ATTESTED_AUTHORIZED`` — the owner's written attestation
#: (docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md) covers the source.
LICENSING_STATUSES: frozenset[str] = frozenset(
    {"UNVERIFIED", "CLEARED_WITH_ARTIFACT", "OWNER_ATTESTED_AUTHORIZED"}
)

#: Credentials are environment-only; the name must look like one.
_CREDENTIAL_ENV_VAR_SHAPE = "UPPER_SNAKE_CASE ending in _API_KEY"

#: Implementation-status vocabulary used by this census. Distinct from
#: (and coarser than) ``ROS_SOURCES``'s ``enabled`` flag — this tracks
#: whether the source is wired at all, and if so, whether what is wired
#: actually qualifies as the evidence class claimed.
#:
#: ``IMPLEMENTED_FLAG_OFF`` — the parser/rescorer exists and is tested,
#: but acquisition sits behind a feature flag that defaults OFF and no
#: consumer reads it. Kept distinct from ``LIVE`` so "the code exists"
#: can never read as "production uses it"; the validator requires the
#: named flag to be registered AND to default False, so flipping the
#: default without deliberately updating this status fails validation.
IMPLEMENTATION_STATUSES: frozenset[str] = frozenset(
    {"LIVE", "LIVE_BUT_RANKINGS_ONLY", "IMPLEMENTED_FLAG_OFF", "GREENFIELD", "NOT_STARTED"}
)

#: Access postures that authorize NOTHING beyond recording the fact. A
#: consumer asking "can I automate this source" must treat every posture
#: other than PUBLIC_NO_AUTH or CREDENTIALED_SESSION_ALREADY_WIRED as a
#: hard stop pending an owner decision, per plan §3.
_POSTURES_REQUIRING_OWNER_DECISION: frozenset[str] = frozenset(
    {"SUBSCRIPTION_SCOPE_UNRECORDED", "NO_ACCESS_PATH_RECORDED", "PUBLIC_UNDOCUMENTED_NO_AUTH"}
)


class ProjectionCensusError(ValueError):
    """Raised when the census file itself is malformed."""


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with CENSUS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_census(*, validate: bool = True) -> dict[str, Any]:
    """Return the full parsed census. Validated by default — a caller
    that explicitly wants the unvalidated dict (e.g. a repair script
    reading a mid-edit file) may pass ``validate=False``.
    """
    data = _raw()
    if validate:
        errors = validate_census(data)
        if errors:
            raise ProjectionCensusError(
                "config/projections/source_capability_census.json is invalid:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
    return data


def validate_census(data: dict[str, Any] | None = None) -> list[str]:
    """Structural + closed-vocabulary validation. Returns a list of
    human-readable error strings — empty means valid. Does not raise, so
    a caller (or a test) can assert on the exact failures.
    """
    data = data if data is not None else _raw()
    errors: list[str] = []
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["'sources' must be a non-empty list"]

    seen_keys: set[str] = set()
    for i, src in enumerate(sources):
        where = f"sources[{i}]"
        key = src.get("key")
        if not key or not isinstance(key, str):
            errors.append(f"{where}: missing or non-string 'key'")
            continue
        where = f"sources[{i}] ({key})"
        if key in seen_keys:
            errors.append(f"{where}: duplicate key")
        seen_keys.add(key)

        evidence_class = src.get("evidenceClass")
        if evidence_class not in EVIDENCE_CLASSES:
            errors.append(
                f"{where}: evidenceClass {evidence_class!r} not in {sorted(EVIDENCE_CLASSES)}"
            )

        horizons = src.get("horizons")
        if not isinstance(horizons, list) or not horizons:
            errors.append(f"{where}: 'horizons' must be a non-empty list")
        else:
            bad = [h for h in horizons if h not in HORIZONS]
            if bad:
                errors.append(f"{where}: unknown horizon(s) {bad} not in {sorted(HORIZONS)}")

        status = src.get("implementationStatus")
        if status not in IMPLEMENTATION_STATUSES:
            errors.append(
                f"{where}: implementationStatus {status!r} not in {sorted(IMPLEMENTATION_STATUSES)}"
            )

        posture = src.get("accessPosture")
        if posture not in ACCESS_POSTURES:
            errors.append(f"{where}: accessPosture {posture!r} not in {sorted(ACCESS_POSTURES)}")

        # A LIVE (fully-qualifying) source must actually point at real code.
        if status == "LIVE" and not src.get("existingModule"):
            errors.append(f"{where}: implementationStatus LIVE but existingModule is empty")
        if status == "GREENFIELD" and src.get("existingModule"):
            errors.append(f"{where}: implementationStatus GREENFIELD but existingModule is set")
        if status == "IMPLEMENTED_FLAG_OFF":
            if not src.get("existingModule"):
                errors.append(
                    f"{where}: implementationStatus IMPLEMENTED_FLAG_OFF but existingModule is empty"
                )
            errors.extend(_flag_off_errors(where, src.get("featureFlag")))

        if posture == "KEYED_API_CREDENTIAL_REQUIRED":
            errors.extend(_keyed_errors(where, src))
        errors.extend(_ancestry_errors(where, src.get("modelAncestry")))

        licensing = src.get("licensingStatus")
        if licensing is not None and licensing not in LICENSING_STATUSES:
            errors.append(
                f"{where}: licensingStatus {licensing!r} not in {sorted(LICENSING_STATUSES)}"
            )

        if not src.get("providerFamily"):
            errors.append(
                f"{where}: missing 'providerFamily' (needed for §6 independence grouping)"
            )
        if not src.get("targetPopulation"):
            errors.append(f"{where}: missing 'targetPopulation'")
        if not src.get("acquisitionOwnerLane"):
            errors.append(f"{where}: missing 'acquisitionOwnerLane'")

    lanes = data.get("discoveryLanes")
    if not isinstance(lanes, list) or not lanes:
        errors.append("'discoveryLanes' must be a non-empty list")

    return errors


def _flag_off_errors(where: str, flag: Any) -> list[str]:
    """An IMPLEMENTED_FLAG_OFF entry must name a registered flag that
    really defaults OFF — otherwise the status is a claim nothing checks."""
    from src.api import feature_flags

    if not flag or not isinstance(flag, str):
        return [f"{where}: implementationStatus IMPLEMENTED_FLAG_OFF requires 'featureFlag'"]
    if flag not in feature_flags.registered_flags():
        return [f"{where}: featureFlag {flag!r} is not registered in src.api.feature_flags"]
    if feature_flags._DEFAULTS[flag]:
        return [
            f"{where}: featureFlag {flag!r} defaults ON, so the entry is no longer "
            "IMPLEMENTED_FLAG_OFF; update implementationStatus deliberately"
        ]
    return []


def _keyed_errors(where: str, src: dict[str, Any]) -> list[str]:
    """A keyed source must name its credential env var — and only a NAME:
    the census is committed, so a value here would be a leaked key."""
    name = src.get("credentialEnvVar")
    if not isinstance(name, str) or not name:
        return [f"{where}: KEYED_API_CREDENTIAL_REQUIRED requires 'credentialEnvVar'"]
    if not (name.isupper() and name.endswith("_API_KEY") and name.replace("_", "").isalnum()):
        return [f"{where}: credentialEnvVar {name!r} is not {_CREDENTIAL_ENV_VAR_SHAPE}"]
    if src.get("licensingStatus") is None:
        return [f"{where}: a keyed source must record licensingStatus"]
    return []


def _ancestry_errors(where: str, ancestry: Any) -> list[str]:
    """An aggregate must declare what it aggregates, or the ensemble cannot
    avoid counting it and its constituents as independent votes."""
    if ancestry is None:
        return []
    if not isinstance(ancestry, dict):
        return [f"{where}: modelAncestry must be an object"]
    families = ancestry.get("constituentFamilies", [])
    if not isinstance(families, list) or not all(isinstance(f, str) and f for f in families):
        return [f"{where}: modelAncestry.constituentFamilies must be a list of family names"]
    if ancestry.get("isAggregate") is True and not families:
        return [f"{where}: an aggregate (isAggregate) must list constituentFamilies"]
    return []


def ancestry_families(key: str) -> frozenset[str]:
    """Every independence family whose evidence may be inside ``key``'s
    numbers: its own ``providerFamily`` plus any declared constituents."""
    src = get_source(key)
    if src is None:
        raise KeyError(key)
    ancestry = src.get("modelAncestry") or {}
    return frozenset({str(src["providerFamily"])}) | frozenset(
        ancestry.get("constituentFamilies") or ()
    )


def ancestry_overlaps(keys: list[str] | tuple[str, ...]) -> list[tuple[str, str, frozenset[str]]]:
    """Pairs of census sources that share evidence ancestry — an aggregate
    and one of its constituents, or two products of one family. Such a pair
    must not be counted as two independent votes. Empty = independent."""
    fams = {k: ancestry_families(k) for k in keys}
    out = []
    ordered = sorted(fams)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            shared = fams[a] & fams[b]
            if shared:
                out.append((a, b, shared))
    return out


def sources_by_evidence_class(
    evidence_class: str, *, population: str | None = None
) -> list[dict[str, Any]]:
    """Sources carrying ``evidence_class``, optionally filtered to a
    target population ("OFFENSE" or "IDP"). Never includes
    ``RANKINGS_ONLY`` unless explicitly requested — a caller building the
    real ensemble should not have to remember to exclude it.
    """
    out = []
    for src in load_census()["sources"]:
        if src.get("evidenceClass") != evidence_class:
            continue
        if population and population not in (src.get("targetPopulation") or []):
            continue
        out.append(dict(src))
    return out


def automatable_sources() -> list[dict[str, Any]]:
    """Sources whose access posture does not require a further owner
    decision before automation could even be considered. Still not a
    green light by itself — implementation status and evidence class
    matter too — but a caller filtering for "what could I even start
    building against today" starts here.
    """
    return [
        dict(src)
        for src in load_census()["sources"]
        if src.get("accessPosture") not in _POSTURES_REQUIRING_OWNER_DECISION
    ]


def get_source(key: str) -> dict[str, Any] | None:
    for src in load_census()["sources"]:
        if src.get("key") == key:
            return dict(src)
    return None
