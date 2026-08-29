"""Persisted sharp ROSTER observations — the store behind Sharp Roster %.

Why a new store at all
──────────────────────
The sharp ledger records MOVEMENTS (who traded what, when).  A roster
percentage needs the orthogonal fact — who HOLDS what right now — and
that did not exist anywhere durable:

* ``src/intel/crawler.py`` builds ``league_entry["holdings"]`` but writes
  it to the per-league Insider Trading snapshot JSON, scoped to ONE
  league's member pool.  ``src/intel/service.py::holdings_from_state``
  is its only reader.  That pool is not the sharp cohort.
* ``src/sharp/records.py`` fetches ``/league/{id}/rosters`` for
  sharp-eligible leagues but reads only ``owner_id``/``settings`` — it
  throws the player list away.
* FFPC roster contents DO reach the ledger, but only as opaque
  ``platform_memberships.metadata_json["rosterAssets"]`` — unqueryable
  and with no eligibility, freshness, or exclusion record.

Deduplication is STRUCTURAL, not a cleanup pass
───────────────────────────────────────────────
Every requirement about not double-counting is enforced by a primary
key, so no caller can forget to apply it and no later refactor can drop
it silently:

    sharp_roster_assets  PK (roster_key, canonical_asset_id)
        A player counts AT MOST ONCE per roster.  Re-observing the same
        roster, importing the same page twice, or seeing the same player
        arrive through two source rows all collapse to one row.

    sharp_rosters        PK roster_key = "<league_key>#<source_roster_id>"
        One row per real roster.  The same roster collected twice, or
        reached through two different sharp members in the same league,
        is ONE denominator slot.  Re-snapshotting overwrites in place.

    sharp_roster_asset_spans  PK (roster_key, canonical_asset_id, span_start_ms)
        History as OPEN INTERVALS rather than daily copies.  Dynasty
        turnover is low, so this is a few rows per holding instead of one
        row per holding per day, and it answers "did this roster hold
        this player on date D" exactly.

    sharp_roster_observations  PK (roster_key, observed_ms)
        When a roster was actually LOOKED AT.  Needed so "not observed"
        can never be read as "dropped the player" — a delta is only
        computed over rosters observed in both periods.

One sharp manager with five legitimate dynasty teams therefore
contributes FIVE rows to ``sharp_rosters`` (five roster observations,
which is what the denominator wants) while still being ONE person in
``uniqueSharpManagers`` (see ``cohort.canonical_manager_ids``).

Schema installation
───────────────────
``ensure_roster_schema`` is plain ``CREATE TABLE IF NOT EXISTS`` and is
deliberately NOT wired into ``platform_ledger.PLATFORM_SCHEMA_VERSION``.
Bumping that version would re-run the whole platform migration —
``_backfill_sleeper``, ``_sync_legacy_entities``, invariant checks — on
every deployed ledger just to add three tables.  These tables are
additive, reference nothing in the platform migration, and are created
on first use.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.intel import platform_ledger

log = logging.getLogger(__name__)

# Roster slots.  Sleeper's ``players`` array already CONTAINS the taxi
# and reserve players, so these are a label on an existing membership,
# never an extra one — see ``collect.py`` for how they are derived.
SLOT_ACTIVE = "active"
SLOT_TAXI = "taxi"
SLOT_RESERVE = "reserve"

# How long a roster observation stays usable as CURRENT.  Past this it
# is excluded with ``stale_roster_data`` rather than quietly aging into
# the denominator.
DEFAULT_MAX_ROSTER_AGE_DAYS = 21

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sharp_rosters (
  roster_key             TEXT PRIMARY KEY,
  platform               TEXT NOT NULL,
  league_key             TEXT NOT NULL,
  manager_key            TEXT NOT NULL,
  source_roster_id       TEXT NOT NULL,
  season                 TEXT,
  team_name              TEXT,
  is_eligible            INTEGER NOT NULL DEFAULT 0,
  exclusion_reasons_json TEXT,
  format_json            TEXT,
  contention             TEXT,
  asset_count            INTEGER NOT NULL DEFAULT 0,
  player_count           INTEGER NOT NULL DEFAULT 0,
  observed_ms            INTEGER NOT NULL,
  first_seen_ms          INTEGER NOT NULL,
  source_run_id          TEXT
);

CREATE TABLE IF NOT EXISTS sharp_roster_assets (
  roster_key         TEXT NOT NULL,
  canonical_asset_id TEXT NOT NULL,
  asset_type         TEXT NOT NULL DEFAULT 'player',
  slot               TEXT,
  source_asset_id    TEXT,
  observed_ms        INTEGER NOT NULL,
  PRIMARY KEY (roster_key, canonical_asset_id)
);

-- ``span_end_ms`` is the LAST OBSERVATION THAT CONFIRMED the holding.
-- ``closed_at_ms`` is the observation that CONTRADICTED it — the first
-- time we looked and the player was gone.  Both are needed, and
-- conflating them is a real bug rather than a redundancy: a roster seen
-- on day 0 and again on day 40 has span_end_ms = day 0, but the player
-- was still presumed rostered on day 10 because nothing had said
-- otherwise yet.  Asking "was he held on day 10" against span_end_ms
-- answers no; asking against closed_at_ms answers yes, which is what a
-- 30-day trend needs to be right.
CREATE TABLE IF NOT EXISTS sharp_roster_asset_spans (
  roster_key         TEXT NOT NULL,
  canonical_asset_id TEXT NOT NULL,
  span_start_ms      INTEGER NOT NULL,
  span_end_ms        INTEGER NOT NULL,
  closed             INTEGER NOT NULL DEFAULT 0,
  closed_at_ms       INTEGER,
  PRIMARY KEY (roster_key, canonical_asset_id, span_start_ms)
);

CREATE TABLE IF NOT EXISTS sharp_roster_observations (
  roster_key  TEXT NOT NULL,
  observed_ms INTEGER NOT NULL,
  eligible    INTEGER NOT NULL DEFAULT 0,
  asset_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (roster_key, observed_ms)
);

CREATE INDEX IF NOT EXISTS idx_sr_manager ON sharp_rosters(manager_key);
CREATE INDEX IF NOT EXISTS idx_sr_league ON sharp_rosters(league_key);
CREATE INDEX IF NOT EXISTS idx_sr_eligible ON sharp_rosters(is_eligible, observed_ms);
CREATE INDEX IF NOT EXISTS idx_sra_asset ON sharp_roster_assets(canonical_asset_id);
CREATE INDEX IF NOT EXISTS idx_sras_asset ON sharp_roster_asset_spans(canonical_asset_id);
CREATE INDEX IF NOT EXISTS idx_sras_window
  ON sharp_roster_asset_spans(span_start_ms, span_end_ms);
CREATE INDEX IF NOT EXISTS idx_sro_ts ON sharp_roster_observations(observed_ms);
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def roster_key(league_key: str, source_roster_id: str) -> str:
    """The stable identity of one roster.

    ``league_key`` is already ``"<platform>:<source_league_id>"``, so
    this is unique across platforms without a third component.  The
    separator is ``#`` because Sleeper league ids and FFPC ltuids both
    contain neither ``#`` nor a colon-delimited roster suffix.
    """
    return f"{str(league_key).strip()}#{str(source_roster_id).strip()}"


def ensure_roster_schema(
    path: Path | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Connection:
    """Create the roster tables if absent and return an open connection.

    When ``conn`` is supplied ownership stays with the caller; otherwise
    the caller must close the returned connection.
    """
    connection = conn if conn is not None else platform_ledger.ensure_platform_schema(path)
    connection.executescript(_SCHEMA)
    connection.commit()
    return connection


@dataclass
class RosterAsset:
    canonical_asset_id: str
    asset_type: str = "player"
    slot: str = SLOT_ACTIVE
    source_asset_id: str | None = None


@dataclass
class RosterObservation:
    """One roster, as seen at one moment.

    ``exclusion_reasons`` being non-empty is what makes a roster
    ineligible — eligibility is never asserted independently of the
    reasons, so an excluded roster is always explainable.
    """

    platform: str
    league_key: str
    manager_key: str
    source_roster_id: str
    assets: list[RosterAsset] = field(default_factory=list)
    season: str | None = None
    team_name: str | None = None
    exclusion_reasons: list[str] = field(default_factory=list)
    league_format: dict[str, Any] = field(default_factory=dict)
    contention: str | None = None
    observed_ms: int | None = None
    source_run_id: str | None = None

    @property
    def roster_key(self) -> str:
        return roster_key(self.league_key, self.source_roster_id)

    @property
    def is_eligible(self) -> bool:
        return not self.exclusion_reasons


def _unique_assets(assets: Iterable[RosterAsset]) -> list[RosterAsset]:
    """Collapse duplicate canonical assets within ONE roster.

    The table's primary key would collapse them anyway; doing it here
    too means ``asset_count`` reports the real number rather than the
    number of source rows, and it makes the slot precedence explicit:
    a player listed both actively and on taxi keeps the more specific
    label rather than whichever row happened to be inserted last.
    """
    precedence = {SLOT_ACTIVE: 0, SLOT_RESERVE: 1, SLOT_TAXI: 2}
    by_id: dict[str, RosterAsset] = {}
    for asset in assets:
        asset_id = str(asset.canonical_asset_id or "").strip()
        if not asset_id:
            continue
        prior = by_id.get(asset_id)
        if prior is None or precedence.get(asset.slot, 0) > precedence.get(prior.slot, 0):
            by_id[asset_id] = RosterAsset(
                canonical_asset_id=asset_id,
                asset_type=asset.asset_type or "player",
                slot=asset.slot or SLOT_ACTIVE,
                source_asset_id=asset.source_asset_id,
            )
    return list(by_id.values())


def record_roster(observation: RosterObservation, *, conn: sqlite3.Connection) -> dict[str, int]:
    """Write one roster observation, replacing any prior state for it.

    Idempotent by construction: re-recording the identical roster
    produces the identical stored state, and re-recording a CHANGED
    roster closes the spans of departed assets and opens spans for
    arrivals.  The caller commits.
    """
    now = int(observation.observed_ms or _now_ms())
    key = observation.roster_key
    assets = _unique_assets(observation.assets)
    player_count = sum(1 for a in assets if a.asset_type == "player")

    prior = conn.execute(
        "SELECT first_seen_ms FROM sharp_rosters WHERE roster_key=?", (key,)
    ).fetchone()
    first_seen = int(prior["first_seen_ms"]) if prior else now

    conn.execute(
        """
        INSERT INTO sharp_rosters
          (roster_key, platform, league_key, manager_key, source_roster_id,
           season, team_name, is_eligible, exclusion_reasons_json,
           format_json, contention, asset_count, player_count,
           observed_ms, first_seen_ms, source_run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(roster_key) DO UPDATE SET
          platform=excluded.platform,
          league_key=excluded.league_key,
          manager_key=excluded.manager_key,
          source_roster_id=excluded.source_roster_id,
          season=excluded.season,
          team_name=COALESCE(excluded.team_name, sharp_rosters.team_name),
          is_eligible=excluded.is_eligible,
          exclusion_reasons_json=excluded.exclusion_reasons_json,
          format_json=excluded.format_json,
          contention=excluded.contention,
          asset_count=excluded.asset_count,
          player_count=excluded.player_count,
          observed_ms=excluded.observed_ms,
          source_run_id=excluded.source_run_id
        """,
        (
            key,
            observation.platform,
            observation.league_key,
            observation.manager_key,
            observation.source_roster_id,
            observation.season,
            observation.team_name,
            1 if observation.is_eligible else 0,
            json.dumps(sorted(set(observation.exclusion_reasons))),
            json.dumps(observation.league_format or {}),
            observation.contention,
            len(assets),
            player_count,
            now,
            first_seen,
            observation.source_run_id,
        ),
    )

    previous_ids = {
        str(row["canonical_asset_id"])
        for row in conn.execute(
            "SELECT canonical_asset_id FROM sharp_roster_assets WHERE roster_key=?",
            (key,),
        ).fetchall()
    }
    current_ids = {a.canonical_asset_id for a in assets}

    # Current holdings: replace wholesale so a dropped player disappears.
    conn.execute("DELETE FROM sharp_roster_assets WHERE roster_key=?", (key,))
    conn.executemany(
        """
        INSERT INTO sharp_roster_assets
          (roster_key, canonical_asset_id, asset_type, slot,
           source_asset_id, observed_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(key, a.canonical_asset_id, a.asset_type, a.slot, a.source_asset_id, now) for a in assets],
    )

    # History: extend open spans that persist, close spans that ended,
    # open spans for arrivals.
    open_spans = {
        str(row["canonical_asset_id"]): int(row["span_start_ms"])
        for row in conn.execute(
            """
            SELECT canonical_asset_id, span_start_ms
              FROM sharp_roster_asset_spans
             WHERE roster_key=? AND closed=0
            """,
            (key,),
        ).fetchall()
    }
    for asset_id in current_ids:
        if asset_id in open_spans:
            conn.execute(
                """
                UPDATE sharp_roster_asset_spans
                   SET span_end_ms=?
                 WHERE roster_key=? AND canonical_asset_id=? AND span_start_ms=?
                """,
                (now, key, asset_id, open_spans[asset_id]),
            )
        else:
            conn.execute(
                """
                INSERT INTO sharp_roster_asset_spans
                  (roster_key, canonical_asset_id, span_start_ms, span_end_ms, closed)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(roster_key, canonical_asset_id, span_start_ms)
                DO UPDATE SET span_end_ms=excluded.span_end_ms, closed=0
                """,
                (key, asset_id, now, now),
            )
    for asset_id in open_spans:
        if asset_id not in current_ids:
            conn.execute(
                """
                UPDATE sharp_roster_asset_spans
                   SET closed=1, closed_at_ms=?
                 WHERE roster_key=? AND canonical_asset_id=? AND span_start_ms=?
                """,
                (now, key, asset_id, open_spans[asset_id]),
            )

    conn.execute(
        """
        INSERT INTO sharp_roster_observations
          (roster_key, observed_ms, eligible, asset_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(roster_key, observed_ms) DO UPDATE SET
          eligible=excluded.eligible, asset_count=excluded.asset_count
        """,
        (key, now, 1 if observation.is_eligible else 0, len(assets)),
    )

    return {
        "assetsRecorded": len(assets),
        "assetsAdded": len(current_ids - previous_ids),
        "assetsRemoved": len(previous_ids - current_ids),
    }


def record_rosters(
    observations: Sequence[RosterObservation],
    *,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    own = conn is None
    connection = conn if conn is not None else ensure_roster_schema(path)
    if conn is not None:
        ensure_roster_schema(conn=connection)
    totals = {"rosters": 0, "eligibleRosters": 0, "assetsRecorded": 0}
    try:
        for observation in observations:
            result = record_roster(observation, conn=connection)
            totals["rosters"] += 1
            totals["eligibleRosters"] += 1 if observation.is_eligible else 0
            totals["assetsRecorded"] += result["assetsRecorded"]
        connection.commit()
    finally:
        if own:
            connection.close()
    return totals


# ── reads ────────────────────────────────────────────────────────────


def load_rosters(
    *,
    manager_keys: Sequence[str] | None = None,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    include_ineligible: bool = True,
) -> list[dict[str, Any]]:
    """Every stored roster, with its assets attached.

    Restricting to ``manager_keys`` is how a caller ties the store back
    to the live sharp cohort: a roster whose manager has since fallen
    out of the cohort must not keep contributing, and this is the only
    place that filter belongs.
    """
    own = conn is None
    connection = conn if conn is not None else ensure_roster_schema(path)
    try:
        clauses = []
        params: list[Any] = []
        if manager_keys is not None:
            if not manager_keys:
                return []
            clauses.append(f"manager_key IN ({','.join('?' for _ in manager_keys)})")
            params.extend(str(k) for k in manager_keys)
        if not include_ineligible:
            clauses.append("is_eligible=1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"SELECT * FROM sharp_rosters{where} ORDER BY roster_key", params
        ).fetchall()
        if not rows:
            return []
        keys = [str(r["roster_key"]) for r in rows]
        assets_by_roster: dict[str, list[dict[str, Any]]] = {key: [] for key in keys}
        for start in range(0, len(keys), 500):
            chunk = keys[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"""
                SELECT roster_key, canonical_asset_id, asset_type, slot
                  FROM sharp_roster_assets
                 WHERE roster_key IN ({placeholders})
                """,
                chunk,
            ).fetchall():
                assets_by_roster[str(row["roster_key"])].append(
                    {
                        "canonicalAssetId": str(row["canonical_asset_id"]),
                        "assetType": str(row["asset_type"] or "player"),
                        "slot": str(row["slot"] or SLOT_ACTIVE),
                    }
                )
        out = []
        for row in rows:
            key = str(row["roster_key"])
            try:
                reasons = json.loads(row["exclusion_reasons_json"] or "[]")
            except (TypeError, ValueError):
                reasons = []
            try:
                league_format = json.loads(row["format_json"] or "{}")
            except (TypeError, ValueError):
                league_format = {}
            out.append(
                {
                    "rosterKey": key,
                    "platform": str(row["platform"]),
                    "leagueKey": str(row["league_key"]),
                    "managerKey": str(row["manager_key"]),
                    "sourceRosterId": str(row["source_roster_id"]),
                    "season": row["season"],
                    "teamName": row["team_name"],
                    "isEligible": bool(row["is_eligible"]),
                    "exclusionReasons": [str(r) for r in reasons],
                    "format": league_format if isinstance(league_format, dict) else {},
                    "contention": row["contention"],
                    "assetCount": int(row["asset_count"] or 0),
                    "playerCount": int(row["player_count"] or 0),
                    "observedMs": int(row["observed_ms"] or 0),
                    "firstSeenMs": int(row["first_seen_ms"] or 0),
                    "assets": assets_by_roster.get(key, []),
                }
            )
        return out
    finally:
        if own:
            connection.close()


def holdings_as_of(
    as_of_ms: int,
    *,
    roster_keys: Sequence[str],
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, set[str]]:
    """``{roster_key: {canonical_asset_id}}`` as the rosters stood at ``as_of_ms``.

    A holding covers ``as_of_ms`` when it had started by then and had not
    yet been CONTRADICTED — that is, when the observation which found the
    player gone came later (``closed_at_ms > as_of_ms``) or has not
    happened at all (``closed = 0``).

    Note what this is deliberately NOT: a test against ``span_end_ms``,
    the last observation that confirmed the holding.  Rosters are
    observed periodically, so a roster seen on day 0 and again on day 40
    has no confirmation at day 10 — yet the player was rostered then,
    because nothing had said otherwise.  Reading ``span_end_ms`` here
    silently zeroes every drop that happened between two observations,
    which shows up as a 30-day trend of exactly zero no matter what
    moved.

    Rosters never observed on or before ``as_of_ms`` are ABSENT from the
    result rather than present-and-empty.  That distinction is what lets
    a trend compare a like-for-like population instead of reading a
    roster we had not yet discovered as one that owned nobody.
    """
    if not roster_keys:
        return {}
    own = conn is None
    connection = conn if conn is not None else ensure_roster_schema(path)
    try:
        as_of = int(as_of_ms)
        out: dict[str, set[str]] = {}
        keys = [str(k) for k in roster_keys]
        for start in range(0, len(keys), 400):
            chunk = keys[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            observed = {
                str(row["roster_key"])
                for row in connection.execute(
                    f"""
                    SELECT DISTINCT roster_key
                      FROM sharp_roster_observations
                     WHERE roster_key IN ({placeholders}) AND observed_ms <= ?
                    """,
                    [*chunk, as_of],
                ).fetchall()
            }
            for key in observed:
                out.setdefault(key, set())
            if not observed:
                continue
            observed_list = sorted(observed)
            obs_placeholders = ",".join("?" for _ in observed_list)
            for row in connection.execute(
                f"""
                SELECT roster_key, canonical_asset_id
                  FROM sharp_roster_asset_spans
                 WHERE roster_key IN ({obs_placeholders})
                   AND span_start_ms <= ?
                   AND (closed = 0 OR COALESCE(closed_at_ms, span_end_ms) > ?)
                """,
                [*observed_list, as_of, as_of],
            ).fetchall():
                out[str(row["roster_key"])].add(str(row["canonical_asset_id"]))
        return out
    finally:
        if own:
            connection.close()


def holdings_as_of_multi(
    as_of_ms_values: Sequence[int],
    *,
    roster_keys: Sequence[str],
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[int, dict[str, set[str]]]:
    """``{as_of_ms: {roster_key: {canonical_asset_id}}}`` for SEVERAL
    timestamps against the same roster population in one pass.

    Semantically identical to calling ``holdings_as_of()`` once per
    timestamp (byte-identical output, pinned by
    ``test_holdings_as_of_multi_matches_per_call_output`` in
    ``tests/sharp/test_roster_store.py``) — it exists purely to avoid
    re-scanning ``sharp_roster_observations`` and
    ``sharp_roster_asset_spans`` once per baseline. Both tables are read
    ONCE for the full ``roster_keys`` population (unfiltered by any
    ``as_of``), and the per-timestamp ``observed_ms <=`` / span-open
    logic runs in Python instead of as N separate SQL scans.

    A roster's earliest observation already answers "was this roster
    observed by X" for every X at once (the existence test
    ``holdings_as_of()`` runs per timestamp is monotonic), and each
    span's own open/closed shape does not depend on which timestamp is
    asked — both properties are what make one shared pass correct here.
    """
    if not roster_keys or not as_of_ms_values:
        return {int(a): {} for a in as_of_ms_values}
    own = conn is None
    connection = conn if conn is not None else ensure_roster_schema(path)
    try:
        keys = [str(k) for k in roster_keys]
        as_ofs = sorted({int(a) for a in as_of_ms_values})

        earliest_observed: dict[str, int] = {}
        for start in range(0, len(keys), 400):
            chunk = keys[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"""
                SELECT roster_key, MIN(observed_ms) AS earliest
                  FROM sharp_roster_observations
                 WHERE roster_key IN ({placeholders})
                 GROUP BY roster_key
                """,
                chunk,
            ).fetchall():
                earliest_observed[str(row["roster_key"])] = int(row["earliest"])

        spans: list[tuple[str, str, int, bool, int | None, int | None]] = []
        for start in range(0, len(keys), 400):
            chunk = keys[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"""
                SELECT roster_key, canonical_asset_id, span_start_ms,
                       closed, closed_at_ms, span_end_ms
                  FROM sharp_roster_asset_spans
                 WHERE roster_key IN ({placeholders})
                """,
                chunk,
            ).fetchall():
                spans.append(
                    (
                        str(row["roster_key"]),
                        str(row["canonical_asset_id"]),
                        int(row["span_start_ms"]),
                        bool(row["closed"]),
                        row["closed_at_ms"],
                        row["span_end_ms"],
                    )
                )

        result: dict[int, dict[str, set[str]]] = {}
        for as_of in as_ofs:
            out: dict[str, set[str]] = {
                rkey: set() for rkey, earliest in earliest_observed.items() if earliest <= as_of
            }
            if out:
                for rkey, asset_id, start_ms, closed, closed_at_ms, span_end_ms in spans:
                    if rkey not in out or start_ms > as_of:
                        continue
                    if not closed:
                        out[rkey].add(asset_id)
                        continue
                    end_bound = closed_at_ms if closed_at_ms is not None else span_end_ms
                    if end_bound is not None and end_bound > as_of:
                        out[rkey].add(asset_id)
            result[as_of] = out
        return result
    finally:
        if own:
            connection.close()


def coverage(
    *,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own = conn is None
    connection = conn if conn is not None else ensure_roster_schema(path)
    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS rosters,
                   SUM(CASE WHEN is_eligible=1 THEN 1 ELSE 0 END) AS eligible,
                   COUNT(DISTINCT manager_key) AS managers,
                   COUNT(DISTINCT league_key) AS leagues,
                   MAX(observed_ms) AS latest_ms,
                   MIN(observed_ms) AS earliest_ms
              FROM sharp_rosters
            """
        ).fetchone()
        by_platform = {
            str(r["platform"]): {
                "rosters": int(r["n"] or 0),
                "eligibleRosters": int(r["eligible"] or 0),
            }
            for r in connection.execute(
                """
                SELECT platform, COUNT(*) AS n,
                       SUM(CASE WHEN is_eligible=1 THEN 1 ELSE 0 END) AS eligible
                  FROM sharp_rosters GROUP BY platform
                """
            ).fetchall()
        }
        return {
            "rosters": int(row["rosters"] or 0),
            "eligibleRosters": int(row["eligible"] or 0),
            "managersWithRosters": int(row["managers"] or 0),
            "leaguesWithRosters": int(row["leagues"] or 0),
            "latestObservedMs": int(row["latest_ms"]) if row["latest_ms"] else None,
            "earliestObservedMs": int(row["earliest_ms"]) if row["earliest_ms"] else None,
            "platforms": by_platform,
        }
    finally:
        if own:
            connection.close()


def exclusion_reason_counts(
    *,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """``{reason: rosters}`` — the audit trail for everything dropped.

    Excluded rosters are kept as rows, never deleted, so "why is the
    denominator smaller than the cohort" always has an answer.
    """
    own = conn is None
    connection = conn if conn is not None else ensure_roster_schema(path)
    try:
        counts: dict[str, int] = {}
        for row in connection.execute(
            "SELECT exclusion_reasons_json FROM sharp_rosters WHERE is_eligible=0"
        ).fetchall():
            try:
                reasons = json.loads(row["exclusion_reasons_json"] or "[]")
            except (TypeError, ValueError):
                reasons = ["unparseable_exclusion_record"]
            for reason in reasons or ["unspecified"]:
                counts[str(reason)] = counts.get(str(reason), 0) + 1
        return dict(sorted(counts.items()))
    finally:
        if own:
            connection.close()
