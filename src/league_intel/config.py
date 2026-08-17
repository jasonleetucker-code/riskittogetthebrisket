"""Canonical league configuration for the League Intelligence Engine.

Single source of truth for *what the league's rules actually are*:
scoring settings (every Sleeper key, verbatim), the starter-slot
structure, roster size, and season/playoff parameters — loaded from
the dated provenance snapshot in ``config/league_intel/`` (the raw
``GET /v1/league/{id}`` response captured by LI-0 and cross-validated
against screenshot evidence; see docs/league-intelligence/SETTINGS_AUDIT.md).

Relationship to ``config/leagues/registry.json`` (ADR-002): the
registry stays the lightweight per-league pointer used for routing and
roster-shape consumers; this module is the *full-fidelity* config the
scorer, optimizer, and replacement engine consume.  The two must agree
— ``tests/league_intel/test_registry_consumers.py`` pins that.

Refresh path (drift handling is a report, NOT a mutation): call
:func:`refresh_snapshot` to fetch the live config (one polite GET),
diff it against the stored snapshot, and — only when drift exists —
write a NEW dated snapshot next to the old one.  The stored snapshot
is never overwritten; ``load_canonical_config`` keeps reading the
newest dated file, so a drift report becomes active config only once
the new snapshot lands on disk (and the diff tells reviewers exactly
what changed).
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.ros import lineup as lineup_owner

CONFIG_VERSION = 1
"""Version of the canonical-config *shape* produced by this module.
Bump when the dataclass contract below changes incompatibly."""

_REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = _REPO_ROOT / "config" / "league_intel"
_SNAPSHOT_RE = re.compile(r"^sleeper_league_snapshot_(\d{4}-\d{2}-\d{2})(?:T\d{6})?\.json$")

_SLEEPER_API_ROOT = "https://api.sleeper.app/v1"
_HTTP_TIMEOUT = 20.0

# Sleeper's own flex-slot eligibility.  READ from the canonical owner
# (C2-U1) rather than mirrored: the comment here used to say "Mirrors
# src/ros/lineup.py", and a mirror maintained by comment is exactly the
# second table this unit removed.
FLEX_ELIGIBLE: tuple[str, ...] = lineup_owner.ordered_positions(
    lineup_owner.slot_eligible_positions("FLEX")
)
SUPER_FLEX_ELIGIBLE: tuple[str, ...] = lineup_owner.ordered_positions(
    lineup_owner.slot_eligible_positions("SUPER_FLEX")
)

# Scoring keys that must exist for the config to be usable by the
# exact scorer — a canary against truncated/malformed snapshots, not
# an exhaustive schema.
_REQUIRED_SCORING_KEYS: tuple[str, ...] = (
    "pass_yd",
    "pass_td",
    "pass_int",
    "rush_yd",
    "rush_td",
    "rec",
    "rec_yd",
    "rec_td",
    "fgm_yds",
    "xpm",
    "idp_tkl_solo",
    "idp_sack",
    "idp_int",
)


class LeagueConfigError(ValueError):
    """Raised when a snapshot fails validation."""


@dataclass(frozen=True)
class LeagueIntelConfig:
    """Immutable, validated canonical league configuration."""

    config_version: int
    sourced_at: str  # ISO date the snapshot was captured
    snapshot_path: Path
    sleeper_league_id: str
    season: str
    league_status: str
    team_count: int
    best_ball: bool
    playoff_teams: int
    playoff_week_start: int
    taxi_slots: int
    reserve_slots: int
    draft_rounds: int
    waiver_budget: int
    scoring_settings: Mapping[str, float]
    starter_slots: tuple[str, ...]  # flattened, Sleeper naming, BN excluded
    starter_counts: Mapping[str, int]
    bench_slots: int
    flex_eligible: tuple[str, ...] = FLEX_ELIGIBLE
    super_flex_eligible: tuple[str, ...] = SUPER_FLEX_ELIGIBLE

    @property
    def roster_size(self) -> int:
        return len(self.starter_slots) + self.bench_slots

    def to_dict(self) -> dict[str, Any]:
        return {
            "configVersion": self.config_version,
            "sourcedAt": self.sourced_at,
            "snapshotPath": str(self.snapshot_path),
            "sleeperLeagueId": self.sleeper_league_id,
            "season": self.season,
            "leagueStatus": self.league_status,
            "teamCount": self.team_count,
            "bestBall": self.best_ball,
            "playoffTeams": self.playoff_teams,
            "playoffWeekStart": self.playoff_week_start,
            "taxiSlots": self.taxi_slots,
            "reserveSlots": self.reserve_slots,
            "draftRounds": self.draft_rounds,
            "waiverBudget": self.waiver_budget,
            "scoringSettings": dict(self.scoring_settings),
            "starterSlots": list(self.starter_slots),
            "starterCounts": dict(self.starter_counts),
            "benchSlots": self.bench_slots,
            "rosterSize": self.roster_size,
        }


# ── Snapshot discovery + loading ──────────────────────────────────────


def _snapshot_date(path: Path) -> str | None:
    m = _SNAPSHOT_RE.match(path.name)
    return m.group(1) if m else None


def find_latest_snapshot(snapshot_dir: Path | None = None) -> Path:
    """Return the newest dated snapshot file in ``snapshot_dir``."""
    d = snapshot_dir or SNAPSHOT_DIR
    candidates = sorted(
        (p for p in d.glob("sleeper_league_snapshot_*.json") if _snapshot_date(p)),
        key=lambda p: p.name,
    )
    if not candidates:
        raise LeagueConfigError(f"no league snapshot found in {d}")
    return candidates[-1]


def _coerce_scoring(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        raise LeagueConfigError("snapshot scoring_settings missing or not a dict")
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError) as exc:
            raise LeagueConfigError(f"non-numeric scoring rate for {k!r}: {v!r}") from exc
    missing = [k for k in _REQUIRED_SCORING_KEYS if k not in out]
    if missing:
        raise LeagueConfigError(f"scoring_settings missing required keys: {missing}")
    return out


def _int_setting(settings: Mapping[str, Any], key: str, default: int | None = None) -> int:
    v = settings.get(key, default)
    if v is None:
        raise LeagueConfigError(f"snapshot settings missing {key!r}")
    try:
        return int(v)
    except (TypeError, ValueError) as exc:
        raise LeagueConfigError(f"settings[{key!r}] not an int: {v!r}") from exc


def build_config_from_snapshot(raw: Mapping[str, Any], *, snapshot_path: Path) -> LeagueIntelConfig:
    """Validate a raw Sleeper league payload and build the canonical config."""
    if not isinstance(raw, Mapping):
        raise LeagueConfigError("snapshot is not a JSON object")

    league_id = str(raw.get("league_id") or "").strip()
    if not league_id:
        raise LeagueConfigError("snapshot missing league_id")

    settings = raw.get("settings")
    if not isinstance(settings, Mapping):
        raise LeagueConfigError("snapshot missing settings block")

    positions = raw.get("roster_positions")
    if not isinstance(positions, list) or not positions:
        raise LeagueConfigError("snapshot missing roster_positions")
    slots = [str(p).strip().upper() for p in positions]
    starter_slots = tuple(s for s in slots if s != "BN")
    bench_slots = sum(1 for s in slots if s == "BN")
    if not starter_slots:
        raise LeagueConfigError("roster_positions contains no starter slots")
    starter_counts: dict[str, int] = {}
    for s in starter_slots:
        starter_counts[s] = starter_counts.get(s, 0) + 1

    team_count = _int_setting(settings, "num_teams")
    total_rosters = raw.get("total_rosters")
    if total_rosters is not None and int(total_rosters) != team_count:
        raise LeagueConfigError(
            f"total_rosters {total_rosters} disagrees with settings.num_teams {team_count}"
        )
    if team_count < 2:
        raise LeagueConfigError(f"implausible team_count {team_count}")

    sourced_at = _snapshot_date(snapshot_path) or datetime.now(timezone.utc).date().isoformat()

    return LeagueIntelConfig(
        config_version=CONFIG_VERSION,
        sourced_at=sourced_at,
        snapshot_path=snapshot_path,
        sleeper_league_id=league_id,
        season=str(raw.get("season") or ""),
        league_status=str(raw.get("status") or ""),
        team_count=team_count,
        best_ball=bool(_int_setting(settings, "best_ball", 0)),
        playoff_teams=_int_setting(settings, "playoff_teams"),
        playoff_week_start=_int_setting(settings, "playoff_week_start"),
        taxi_slots=_int_setting(settings, "taxi_slots", 0),
        reserve_slots=_int_setting(settings, "reserve_slots", 0),
        draft_rounds=_int_setting(settings, "draft_rounds", 0),
        waiver_budget=_int_setting(settings, "waiver_budget", 0),
        scoring_settings=_coerce_scoring(raw.get("scoring_settings")),
        starter_slots=starter_slots,
        starter_counts=starter_counts,
        bench_slots=bench_slots,
    )


def load_canonical_config(snapshot_dir: Path | None = None) -> LeagueIntelConfig:
    """Load + validate the canonical config from the newest snapshot."""
    path = find_latest_snapshot(snapshot_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LeagueConfigError(f"cannot read snapshot {path}: {exc}") from exc
    return build_config_from_snapshot(raw, snapshot_path=path)


# ── Live refresh + drift detection ────────────────────────────────────

# Drift diffs are scoped to behavior-relevant payload fields
# (scoring_settings, roster_positions, settings, status, season,
# total_rosters) so chatter (last_message_id etc.) never reads as drift.

# Settings sub-keys that are pure in-season bookkeeping, not rules.
_SETTINGS_NOISE_KEYS: frozenset[str] = frozenset({"leg", "last_scored_leg", "last_report"})


@dataclass(frozen=True)
class LeagueConfigDrift:
    """Diff between the stored snapshot and the live league config."""

    league_id: str
    checked_at: str
    stored_snapshot: Path
    scoring_changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    settings_changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    other_changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    roster_positions_changed: bool = False
    new_snapshot: Path | None = None

    @property
    def has_drift(self) -> bool:
        return bool(
            self.scoring_changed
            or self.settings_changed
            or self.other_changed
            or self.roster_positions_changed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueId": self.league_id,
            "checkedAt": self.checked_at,
            "storedSnapshot": str(self.stored_snapshot),
            "hasDrift": self.has_drift,
            "scoringChanged": {k: list(v) for k, v in self.scoring_changed.items()},
            "settingsChanged": {k: list(v) for k, v in self.settings_changed.items()},
            "otherChanged": {k: list(v) for k, v in self.other_changed.items()},
            "rosterPositionsChanged": self.roster_positions_changed,
            "newSnapshot": str(self.new_snapshot) if self.new_snapshot else None,
        }


def _default_fetcher(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "riskit-league-intel/1.0"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read())


def fetch_live_league(league_id: str, *, fetcher: Callable[[str], Any] | None = None) -> dict:
    """One polite GET of the live league config."""
    fetch = fetcher or _default_fetcher
    raw = fetch(f"{_SLEEPER_API_ROOT}/league/{league_id}")
    if not isinstance(raw, dict) or not raw.get("league_id"):
        raise LeagueConfigError(f"live fetch for {league_id!r} returned malformed payload")
    return raw


def _dict_diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def diff_league_config(
    stored: Mapping[str, Any],
    live: Mapping[str, Any],
    *,
    stored_path: Path,
) -> LeagueConfigDrift:
    """Compare stored snapshot vs live payload over behavior-relevant fields."""
    scoring_changed = _dict_diff(
        stored.get("scoring_settings") or {}, live.get("scoring_settings") or {}
    )
    stored_settings = {
        k: v for k, v in (stored.get("settings") or {}).items() if k not in _SETTINGS_NOISE_KEYS
    }
    live_settings = {
        k: v for k, v in (live.get("settings") or {}).items() if k not in _SETTINGS_NOISE_KEYS
    }
    settings_changed = _dict_diff(stored_settings, live_settings)
    other_changed = {
        k: (stored.get(k), live.get(k))
        for k in ("status", "season", "total_rosters")
        if stored.get(k) != live.get(k)
    }
    return LeagueConfigDrift(
        league_id=str(stored.get("league_id") or live.get("league_id") or ""),
        checked_at=datetime.now(timezone.utc).isoformat(),
        stored_snapshot=stored_path,
        scoring_changed=scoring_changed,
        settings_changed=settings_changed,
        other_changed=other_changed,
        roster_positions_changed=(stored.get("roster_positions") or [])
        != (live.get("roster_positions") or []),
    )


def refresh_snapshot(
    *,
    snapshot_dir: Path | None = None,
    fetcher: Callable[[str], Any] | None = None,
    write: bool = True,
) -> LeagueConfigDrift:
    """Fetch the live league config, diff against the stored snapshot,
    and report drift.

    NEVER mutates the stored snapshot.  When drift is found and
    ``write`` is true, a new dated snapshot is written alongside the
    old one (with a UTC-timestamp suffix if today's file already
    exists) and its path is stamped on the returned drift report.
    """
    d = snapshot_dir or SNAPSHOT_DIR
    stored_path = find_latest_snapshot(d)
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    league_id = str(stored.get("league_id") or "").strip()
    if not league_id:
        raise LeagueConfigError(f"stored snapshot {stored_path} missing league_id")

    live = fetch_live_league(league_id, fetcher=fetcher)
    drift = diff_league_config(stored, live, stored_path=stored_path)
    if not drift.has_drift or not write:
        return drift

    # Validate the live payload builds a well-formed config before
    # persisting it — a truncated API response must not become the
    # newest snapshot.
    today = datetime.now(timezone.utc).date().isoformat()
    new_path = d / f"sleeper_league_snapshot_{today}.json"
    build_config_from_snapshot(live, snapshot_path=new_path)
    if new_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        new_path = d / f"sleeper_league_snapshot_{today}T{stamp}.json"
    new_path.write_text(json.dumps(live, sort_keys=True) + "\n", encoding="utf-8")
    return replace(drift, new_snapshot=new_path)
