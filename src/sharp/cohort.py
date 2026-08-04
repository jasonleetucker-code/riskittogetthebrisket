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

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.intel import platform_ledger
from src.sharp import platform_records
from src.sharp import score as sharp_score

REPO_ROOT = Path(__file__).resolve().parents[2]
FFPC_CONFIG_PATH = REPO_ROOT / "config" / "sharp" / "ffpc_sources.json"

ALLOWED_QUALIFICATION = ("all", "automated", "curated", "provisional")

# Automated qualification outranks a curated entry, which outranks a
# provisional observation.  Used when ONE manager_key arrives through
# more than one method — the strongest claim wins rather than the
# manager appearing twice.
_QUALIFICATION_PRIORITY = {
    "provisional_public": 1,
    "curated_high_stakes": 2,
    "automated_qualified": 3,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "managerKey": self.manager_key,
            "platform": self.platform,
            "qualificationMethod": self.qualification_method,
            "quality": round(self.quality, 4),
            "displayName": self.display_name,
            "methodologyVersion": self.methodology_version,
            "sourceRationale": self.source_rationale,
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
    if qualification == "automated":
        selected = automatic
    elif qualification == "curated":
        selected = curated
    elif qualification == "provisional":
        selected = provisional
    else:
        selected = [*automatic, *curated, *provisional]

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
        "evidenceManagers": len(evidence),
        "methodologyVersion": sharp_score.methodology_version(),
    }
    return list(by_key.values()), coverage


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
