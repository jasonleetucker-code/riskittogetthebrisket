"""THE sharp cohort — one definition of "who is a sharp", for every feature.

Every sharp-powered surface resolves its manager pool through this
module.  The Sharp Buy/Sell Tracker (``src/sharp/market.py``) and the
Sharp Roster Percentage board (``src/sharp/roster_percentage.py``) both
call :func:`cohort_members`, so a change to qualification, an added
curated manager, or a flipped FFPC flag moves BOTH boards in the same
deploy — there is no second list to keep in sync.

Why this file exists at all
───────────────────────────
The definitions below used to live inside ``market.py``.  That was fine
while the tracker was the only consumer, but it made the cohort look
like a property of the buy/sell board rather than a shared asset, and
the obvious way to add a second feature would have been to import from
``market`` (coupling a roster board to a transactions board) or — far
worse — to re-derive the pool.  Moving them here makes the shared layer
explicit.

``market.py`` re-exports every name, so ``sharp_market.cohort_members``
and ``sharp_market.CohortMember`` continue to resolve exactly as before.
That is deliberate: existing tests monkeypatch ``market.cohort_members``
and ``market.market_payload`` reads it as a module global, so the seam
they patch is preserved.

What the cohort IS
──────────────────
A ``CohortMember`` is one QUALIFIED MANAGER IDENTITY, not one human and
not one roster:

* ``manager_key``  ``"<platform>:<source_manager_id>"`` — the ledger's
  identity key.  Two accounts belonging to one human are collapsed
  downstream via ``canonical_manager_id``; see
  :func:`canonical_manager_ids` for the resolution used by any feature
  that must not count a person twice.
* ``qualification_method``  how they got in — automated Sharp Score v2,
  a curated high-stakes entry, or a provisional public observation.
  These are NOT interchangeable and features may filter on them.
* ``quality``  0..1.  Sharp Score/100 for automated members, the
  configured weight for curated/provisional ones.

Qualification itself is not decided here — it is decided by
``src/sharp/score.py`` (gates + score) over evidence assembled by
``src/sharp/platform_records.py``.  This module only SELECTS and
DEDUPLICATES.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.intel import platform_ledger
from src.sharp import curated as curated_model
from src.sharp import platform_records
from src.sharp import score as sharp_score

REPO_ROOT = Path(__file__).resolve().parents[2]
FFPC_CONFIG_PATH = REPO_ROOT / "config" / "sharp" / "ffpc_sources.json"

# ``curated`` is the pre-existing FFPC high-stakes allow-list from
# ffpc_sources.json.  ``industry``/``super``/``both`` are the curated-PEOPLE
# model: the researched Final 100 and the subset with a verified public
# identity.  They are deliberately separate words because they answer
# different questions and must never be presented as one population.
ALLOWED_QUALIFICATION = (
    "all",
    "automated",
    "curated",
    "provisional",
    "industry",
    "super",
    "both",
)

# qualification -> curated_cohort_members(mode=...)
_CURATED_COHORT_MODE = {
    "industry": "curated_industry",
    "super": "super",
    "both": "both",
    "all": "curated_industry",
}

# Automated qualification outranks a curated entry, which outranks a
# provisional observation.  Used when ONE manager_key arrives through
# more than one method — the strongest claim wins rather than the
# manager appearing twice.
_QUALIFICATION_PRIORITY = {
    "provisional_public": 1,
    "curated_high_stakes": 2,
    "curated_industry": 3,
    "automated_qualified": 4,
    # Curated AND measured is the strongest claim available, so it must
    # outrank plain automated qualification -- otherwise the merge below
    # would relabel a double-qualified person as merely "automated" and
    # lose the curated half of their provenance.
    "both_curated_and_performance": 5,
}


@lru_cache(maxsize=4)
def load_ffpc_config(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else FFPC_CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


@dataclass(frozen=True)
class CohortMember:
    manager_key: str
    platform: str
    qualification_method: str
    quality: float
    display_name: str | None = None
    methodology_version: str | None = None
    source_rationale: str | None = None
    # ``person_id`` collapses one human's several accounts into one vote and
    # ``network`` lets colleagues at a shared outlet be discounted toward each
    # other. Both feed ``consensus.aggregate_person_consensus``; both are None
    # for managers we only know as an anonymous platform account.
    person_id: str | None = None
    network: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "managerKey": self.manager_key,
            "platform": self.platform,
            "qualificationMethod": self.qualification_method,
            "quality": round(self.quality, 4),
            "displayName": self.display_name,
            "methodologyVersion": self.methodology_version,
            "sourceRationale": self.source_rationale,
            "personId": self.person_id,
            "network": self.network,
        }


def curated_members(config: dict[str, Any]) -> list[CohortMember]:
    out = []
    for raw in config.get("curatedManagers") or []:
        if not isinstance(raw, dict):
            continue
        manager_key = str(raw.get("managerKey") or "").strip()
        if not manager_key.startswith("ffpc:"):
            continue
        if not bool(raw.get("verified")) or not bool(raw.get("allowedToContribute")):
            continue
        weight = max(0.0, min(1.0, float(raw.get("weight") or 0.75)))
        out.append(
            CohortMember(
                manager_key=manager_key,
                platform="ffpc",
                qualification_method="curated_high_stakes",
                quality=weight,
                display_name=str(raw.get("publicDisplayName") or "") or None,
                source_rationale=str(raw.get("sourceRationale") or "") or None,
            )
        )
    return out


def provisional_members(
    config: dict[str, Any],
    *,
    ledger_path: Path | None = None,
) -> list[CohortMember]:
    """Select public FFPC observations without claiming sharp-v2 qualification."""
    if not bool(config.get("enabled")) or not bool(
        config.get("allowProvisionalPublicInCombinedSignals")
    ):
        return []
    league_keys = [
        f"ffpc:{str(source.get('sourceLeagueId') or '').strip()}"
        for source in config.get("seedLeagues") or []
        if isinstance(source, dict)
        and bool(source.get("enabled", True))
        and bool(source.get("allowProvisionalContribution"))
        and str(source.get("sourceLeagueId") or "").strip()
    ]
    if not league_keys:
        return []
    weight = max(
        0.0,
        min(1.0, float(config.get("provisionalPublicWeight") or 0.5)),
    )
    placeholders = ",".join("?" for _ in league_keys)
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT am.manager_key, pm.display_name
              FROM asset_movements am
              JOIN transactions tx
                ON tx.transaction_key=am.transaction_key
              LEFT JOIN platform_managers pm
                ON pm.manager_key=am.manager_key
             WHERE am.platform='ffpc'
               AND am.league_key IN ({placeholders})
               AND tx.tx_type='trade'
               AND am.manager_key IS NOT NULL
            """,
            league_keys,
        ).fetchall()
    finally:
        conn.close()
    return [
        CohortMember(
            manager_key=str(row["manager_key"]),
            platform="ffpc",
            qualification_method="provisional_public",
            quality=weight,
            display_name=str(row["display_name"] or "") or None,
            source_rationale=(
                "Observed on an explicitly configured public FFPC dynasty page; "
                "has not passed Sharp Score v2 history gates."
            ),
        )
        for row in rows
    ]


def curated_industry_members(qualification: str) -> list[CohortMember]:
    """Curated people with a VERIFIED platform identity, as cohort members.

    ``curated_cohort_members`` gates on ``verification_status='verified'``, so
    this returns nothing until the review queue promotes an identity -- which
    is the correct and honest state, not a failure. A missing or unbuilt
    curated store degrades to an empty cohort rather than taking down the
    market: this population is additive to the automated one.
    """
    mode = _CURATED_COHORT_MODE.get(qualification)
    if mode is None:
        return []
    try:
        rows = curated_model.curated_cohort_members(mode=mode)
    except Exception:  # noqa: BLE001 — an optional population must never 500 the board
        return []
    return [
        CohortMember(
            manager_key=str(row.manager_key),
            platform=str(row.platform),
            qualification_method=str(row.qualification_method),
            quality=max(0.0, min(1.0, float(row.quality or 0.0))),
            display_name=row.display_name,
            person_id=row.person_id,
            network=row.network,
            source_rationale=(
                "Researched dynasty-industry sharp with an explicitly verified "
                "public identity. Curated inclusion is expertise evidence, not "
                "a measured win rate."
            ),
        )
        for row in rows
    ]


def _compute_cohort_members(
    *,
    qualification: str,
    ledger_path: Path | None,
    ffpc_config: dict[str, Any] | None,
) -> tuple[list[CohortMember], dict[str, Any]]:
    """The UNCACHED cohort computation — see :func:`cohort_members`.

    This is the O(N log N) rebuild (``build_manager_records`` →
    ``score_managers`` → curated/provisional selection → dedup) that the
    memo in :func:`cohort_members` fronts.  Selection logic lives here and
    nowhere else; the wrapper adds a correctness-preserving cache and
    changes no membership.
    """
    if qualification not in ALLOWED_QUALIFICATION:
        raise ValueError(f"unsupported qualification: {qualification}")
    records, evidence = platform_records.build_manager_records(ledger_path=ledger_path)
    scored = sharp_score.score_managers(records)
    config = ffpc_config if ffpc_config is not None else load_ffpc_config()
    ffpc_enabled = bool(config.get("enabled"))
    automatic = [
        CohortMember(
            manager_key=item.user_id,
            platform=item.user_id.split(":", 1)[0],
            qualification_method="automated_qualified",
            quality=max(0.0, min(1.0, float(item.score or 0.0) / 100.0)),
            methodology_version=item.methodology_version,
        )
        for item in scored
        if item.qualified and (item.user_id.split(":", 1)[0] != "ffpc" or ffpc_enabled)
    ]
    curated_enabled = bool(ffpc_enabled and config.get("allowCuratedInCombinedSignals"))
    curated = curated_members(config) if curated_enabled else []
    provisional_enabled = bool(
        ffpc_enabled and config.get("allowProvisionalPublicInCombinedSignals")
    )
    provisional = (
        provisional_members(config, ledger_path=ledger_path) if provisional_enabled else []
    )
    industry = curated_industry_members(qualification)
    if qualification == "automated":
        selected = automatic
    elif qualification == "curated":
        selected = curated
    elif qualification == "provisional":
        selected = provisional
    elif qualification in _CURATED_COHORT_MODE and qualification != "all":
        # ``industry``/``super``/``both`` are curated-people views and do NOT
        # fall back to the automated cohort. Mixing them would answer a
        # question about researched experts with a population that never met
        # that bar.
        selected = industry
    else:
        selected = [*automatic, *curated, *provisional, *industry]

    # A manager may be explicitly linked to one canonical identity and
    # appear through two methods. Automated qualification wins; otherwise
    # the higher configured quality wins.
    by_key: dict[str, CohortMember] = {}
    for item in selected:
        prior = by_key.get(item.manager_key)
        if prior is None or (
            _QUALIFICATION_PRIORITY.get(item.qualification_method, 0),
            item.quality,
        ) > (
            _QUALIFICATION_PRIORITY.get(prior.qualification_method, 0),
            prior.quality,
        ):
            by_key[item.manager_key] = item
    coverage = {
        "automatedQualifiedManagers": len(automatic),
        "curatedManagers": len(curated),
        "curatedContributionEnabled": curated_enabled,
        "provisionalManagers": len(provisional),
        "provisionalContributionEnabled": provisional_enabled,
        # Accounts, not people: one researched sharp may hold several. The
        # person count is what consensus votes on; this is the tracking surface.
        "curatedIndustryTrackedAccounts": len(industry),
        "curatedIndustryPeople": len({m.person_id for m in industry if m.person_id}),
        "evidenceManagers": len(evidence),
        "methodologyVersion": sharp_score.methodology_version(),
    }
    return list(by_key.values()), coverage


# ── cohort memo (W15-F017) ───────────────────────────────────────────
#
# ``_compute_cohort_members`` is an O(N log N) rebuild that ``market.py``
# calls three times per render and ``roster_percentage`` calls again.
# Memoizing it is a pure performance repair — the selection above is the
# single owner of WHO is a sharp and is not touched.
#
# The hard constraint: a memo MUST NOT serve a STALE membership.  So the
# cache key carries a freshness fingerprint of the ONE input a fresh call
# re-reads on every invocation — the platform-ledger sqlite file.  Trace
# of what ``_compute_cohort_members`` consumes:
#
#   * the platform ledger sqlite — read fresh (a live SQL query) on
#     every call, via ``build_manager_records`` / ``provisional_members``
#     AND ``curated_cohort_members`` (the curated tables live in the SAME
#     ledger db, not a separate file).  This is the per-trade-moving
#     input, so its ``(mtime_ns, size)`` is THE freshness signal.
#   * ``load_ffpc_config`` (this module) and ``score.load_config`` — both
#     ``@lru_cache``d by path.  They are read ONCE per process and frozen
#     thereafter, so between two calls in one process they cannot change
#     the output.  Fingerprinting the config FILES would therefore imply
#     a hot-reload the loaders do not perform; the honest key mirrors the
#     inputs a fresh call actually re-reads, which is the ledger alone.
#   * the ``ffpc_config`` ARGUMENT — a direct input (not cached), so its
#     content is folded into the key when a caller passes one.
#
# Fingerprint is taken BEFORE the compute: a concurrent ledger write
# during the compute only tags the entry with the pre-write fingerprint
# while holding post-write-or-equal data — never staler than current —
# and the next call sees the new fingerprint and recomputes.  The entry
# for a key always holds the LATEST fingerprint's result (a changed
# fingerprint overwrites rather than accumulating), so the cache stays
# bounded to the small (qualification × ledger path × ffpc-config) space.

_COHORT_CACHE_LOCK = threading.Lock()
# key -> (ledger_fingerprint, (members, coverage))
_cohort_cache: dict[
    tuple[str, str, str], tuple[str, tuple[list[CohortMember], dict[str, Any]]]
] = {}


def _resolve_ledger_path(ledger_path: Path | None) -> Path:
    """The concrete ledger file a call reads, resolved the same way the
    computation resolves it (``ledger.default_path()`` at call time when
    unspecified — deliberately dynamic so a test's monkeypatched data dir
    is honored)."""
    if ledger_path is not None:
        return Path(ledger_path)
    from src.intel import ledger  # noqa: PLC0415 — call-time, matches default_path()

    return ledger.default_path()


def _ledger_fingerprint(path: Path) -> str:
    """``mtime_ns:size`` of the ledger, or ``-`` when it cannot be
    stat-ed.  A missing input is a STATE, not an error (same posture as
    ``consensus_edge.inputs.fingerprint``); it must not raise, and it
    changes the instant the file is first created/written."""
    try:
        stat = path.stat()
    except OSError:
        return "-"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _ffpc_config_signal(ffpc_config: dict[str, Any] | None) -> str:
    """Stable key fragment for the ``ffpc_config`` argument.

    ``None`` means "read the file" and collapses to a single sentinel
    (the file's content is frozen by ``load_ffpc_config``'s cache within a
    process, per the note above).  An explicit dict is hashed by content
    so two different configs never share a cache entry.
    """
    if ffpc_config is None:
        return "file"
    try:
        blob = json.dumps(ffpc_config, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(ffpc_config)
    return "cfg:" + hashlib.sha1(blob.encode("utf-8")).hexdigest()


def reset_cohort_cache() -> None:
    """Forget every memoized cohort.

    Production never needs this — the ledger fingerprint invalidates
    entries on its own.  It exists for tests, which mutate MONKEYPATCHED
    internals (invisible to a file fingerprint) and must not see one
    test's cohort answer the next test's call.
    """
    with _COHORT_CACHE_LOCK:
        _cohort_cache.clear()


def cohort_members(
    *,
    qualification: str = "all",
    ledger_path: Path | None = None,
    ffpc_config: dict[str, Any] | None = None,
) -> tuple[list[CohortMember], dict[str, Any]]:
    """``(members, coverage)`` — THE sharp pool.

    This is the function every sharp feature must call.  Do not
    reimplement the selection, and do not filter its output by anything
    that amounts to a second qualification rule.

    Memoized (W15-F017): repeated calls with the same inputs AND an
    unchanged platform ledger share one computation, so the three
    ``market.py`` call sites in one render rebuild the cohort once rather
    than thrice.  The cache invalidates the instant the ledger's
    ``(mtime_ns, size)`` changes, so it can never serve a membership that
    is stale relative to the current ledger.  The returned collections
    are shared and MUST be treated read-only (every existing caller only
    reads keys off them).
    """
    if qualification not in ALLOWED_QUALIFICATION:
        raise ValueError(f"unsupported qualification: {qualification}")
    resolved = _resolve_ledger_path(ledger_path)
    key = (qualification, str(resolved), _ffpc_config_signal(ffpc_config))
    fingerprint = _ledger_fingerprint(resolved)
    with _COHORT_CACHE_LOCK:
        cached = _cohort_cache.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
    result = _compute_cohort_members(
        qualification=qualification,
        ledger_path=ledger_path,
        ffpc_config=ffpc_config,
    )
    with _COHORT_CACHE_LOCK:
        _cohort_cache[key] = (fingerprint, result)
    return result


# ── person-level identity ────────────────────────────────────────────


def canonical_manager_ids(
    manager_keys: list[str] | tuple[str, ...],
    *,
    ledger_path: Path | None = None,
) -> dict[str, str]:
    """``{manager_key: canonical_manager_id}`` for the given keys.

    One human with a Sleeper account AND an FFPC account is ONE person.
    ``platform_managers.canonical_manager_id`` (set by the identity
    linker) is what says so; ``manager_identity_links`` is the explicit
    verified-link table that feeds it.

    Keys with no recorded link map to THEMSELVES rather than being
    dropped.  An unlinked manager is a distinct person as far as we can
    prove, and silently collapsing unknowns would understate the pool.

    Note what this is and is not for.  A roster count's DENOMINATOR is
    rosters, not people (five real dynasty teams are five observations),
    so this is not applied there.  It is what answers "how many unique
    sharp managers are represented", and it is what stops the same
    person's single roster from being counted once per linked account.
    """
    keys = [str(k) for k in manager_keys if str(k or "").strip()]
    if not keys:
        return {}
    out = {key: key for key in keys}
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        for chunk_start in range(0, len(keys), 500):
            chunk = keys[chunk_start : chunk_start + 500]
            placeholders = ",".join("?" for _ in chunk)
            for row in conn.execute(
                f"""
                SELECT pm.manager_key AS manager_key,
                       COALESCE(mil.canonical_manager_id,
                                pm.canonical_manager_id) AS canonical_id
                  FROM platform_managers pm
                  LEFT JOIN manager_identity_links mil
                    ON mil.manager_key = pm.manager_key
                 WHERE pm.manager_key IN ({placeholders})
                """,
                chunk,
            ).fetchall():
                canonical = str(row["canonical_id"] or "").strip()
                if canonical:
                    out[str(row["manager_key"])] = canonical
    finally:
        conn.close()
    return out


def unique_person_count(
    manager_keys: list[str] | tuple[str, ...],
    *,
    ledger_path: Path | None = None,
) -> int:
    """How many distinct HUMANS the given manager keys represent."""
    if not manager_keys:
        return 0
    return len(set(canonical_manager_ids(manager_keys, ledger_path=ledger_path).values()))
