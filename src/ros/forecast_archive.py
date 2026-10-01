"""Point-in-time playoff / title forecast archive (AL-P6, CAPTURE ONLY).

``src/ros/scrape.py`` writes each league's playoff and championship Monte
Carlo output to ``data/ros/sims/*.json`` and overwrites it every refresh.
Season-end calibration ("a team given 20% should win about 20% of comparable
predictions") needs every forecast as it was produced, with what produced it.
This module keeps that record. It changes no forecast and serves nothing.

**One record per forecast**, append-only JSONL under gitignored
``data/forecast_archive/`` (``forecasts-YYYY-MM.jsonl`` by the forecast's own
``computedAt``, plus a ``forecasts.keys`` index so a re-run is a no-op without
re-parsing every line -- the ``src/api/sparse_evidence_shadow.py`` pattern).
A forecast's identity is ``(leagueKey, kind, computedAt, forecastSha256)``;
archiving the same forecast twice, by any transport, writes nothing. Identity
metadata is NOT part of the key, so the same forecast arriving once with and
once without its identity sidecar can never become two calibration samples.

**Model identity travels with every record**: code SHA, a hash of the
simulator parameters actually in force (every module-level constant of the
producing engines plus the points model it loaded), and hashes of the inputs
(the league snapshot fields the simulators read, the persisted team-strength
file, the ROS aggregate and its ``aggregatedAt`` -- the ROS projection snapshot
id -- and the points-model file). A field that cannot be established is
``None`` with its reason in ``nullReasons``; nothing is guessed.

**Why the store is not under ``data/ros/``**: the scheduled-refresh workflow
``git add -f``s the whole of ``data/ros/`` (``.github/workflows/scheduled-refresh.yml``),
which overrides ``.gitignore``. An archive there would be committed to a public
repository every two hours. ``data/forecast_archive/`` is outside every
force-added path, so it stays private.

**Where forecasts are produced, and how they reach the box.** The refresh runs
``python -m src.ros.scrape`` on an ephemeral GitHub Actions runner, so a store
written there is discarded with the runner. The producer therefore ALSO writes
a small identity sidecar beside each sim file (``<stem>.identity.json``: the
record minus the forecast). The sidecar rides the same force-add as the sim
file it describes -- no forecast bytes are duplicated into git -- and on the
production box ``scripts/archive_ros_forecasts.py`` (run by ``deploy/deploy.sh``
after each deploy) joins sim file + sidecar into the private archive. A sidecar
whose ``forecastSha256`` does not match the sim file beside it is never trusted:
the forecast is archived with its identity ``None`` and the reason named.

Nothing here may fail a refresh: :func:`archive_safely` and
:func:`write_identity_sidecar_safely` catch, log and continue.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

LOG = logging.getLogger("ros.forecast_archive")

SCHEMA = "ros-forecast-archive/v1"
IDENTITY_SCHEMA = "ros-forecast-identity/v1"
PRODUCER = "src.ros.scrape._refresh_sim_caches_for_league"
KINDS = ("playoff", "championship")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "data" / "forecast_archive"
INDEX_NAME = "forecasts.keys"
SIDECAR_SUFFIX = ".identity.json"

#: Transports. Recorded on the record, never part of its key.
TRANSPORT_PRODUCER = "producer"
TRANSPORT_PUBLISHED_FILE = "published_file"
TRANSPORT_GIT_HISTORY = "git_history"


# ── hashing ─────────────────────────────────────────────────────────


def canonical_sha256(value: Any) -> str:
    """SHA-256 of ``value``'s canonical JSON (sorted keys, no whitespace)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_key(
    league_key: str | None, kind: str, computed_at: str | None, forecast_sha: str
) -> str:
    """The identity of one forecast: league, kind, its own stamp, its content."""
    return canonical_sha256([SCHEMA, league_key, kind, computed_at, forecast_sha])[:32]


# ── identity (never raises; unknown is None + a reason) ─────────────


def _module_constants(module: ModuleType) -> dict[str, Any]:
    """Every module-level UPPER_CASE scalar of ``module`` -- its parameters."""
    out: dict[str, Any] = {}
    for name, value in vars(module).items():
        if name.isupper() and isinstance(value, (bool, int, float, str)):
            out[name] = value
        elif (
            name.isupper()
            and isinstance(value, tuple)
            and all(isinstance(v, (bool, int, float, str)) for v in value)
        ):
            out[name] = list(value)
    return dict(sorted(out.items()))


def _code_identity(nulls: dict[str, str]) -> dict[str, Any]:
    try:
        from src.api.build_identity import resolve_build_identity  # noqa: PLC0415

        build = resolve_build_identity(REPO_ROOT)
    except Exception as exc:  # noqa: BLE001
        build = {"commit": None, "commit_source": None, "unavailable_reason": f"error:{exc}"}
    if build.get("commit") is None:
        nulls["model.codeSha"] = str(build.get("unavailable_reason") or "unknown")
    return {"codeSha": build.get("commit"), "codeShaSource": build.get("commit_source")}


def _sim_params(best_ball: bool | None, nulls: dict[str, str]) -> dict[str, Any] | None:
    try:
        from src.league_intel import sim_calibration  # noqa: PLC0415
        from src.ros import championship, playoff_sim  # noqa: PLC0415

        return {
            "bestBall": best_ball,
            "playoffSim": _module_constants(playoff_sim),
            "championship": _module_constants(championship),
            "pointsModel": sim_calibration.load_points_model().to_dict(),
        }
    except Exception as exc:  # noqa: BLE001
        nulls["model.simParams"] = f"error:{type(exc).__name__}"
        return None


def _season_week(snapshot: Any, nulls: dict[str, str]) -> dict[str, Any]:
    current = getattr(snapshot, "current_season", None)
    if current is None:
        nulls["season"] = "snapshot_has_no_current_season"
        nulls["week"] = "snapshot_has_no_current_season"
        nulls["lastScoredWeek"] = "snapshot_has_no_current_season"
        return {"season": None, "week": None, "lastScoredWeek": None}
    season = str(getattr(current, "season", "") or "") or None
    if season is None:
        nulls["season"] = "season_not_published_by_host"
    settings = (getattr(current, "league", None) or {}).get("settings") or {}

    def _week(field: str) -> int | None:
        raw = settings.get(field)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = None
        if value is None or value < 0:
            nulls[{"leg": "week", "last_scored_leg": "lastScoredWeek"}[field]] = (
                f"sleeper_settings_{field}_absent"
            )
            return None
        return value

    return {"season": season, "week": _week("leg"), "lastScoredWeek": _week("last_scored_leg")}


#: The snapshot fields the playoff / championship engines read. ``nfl_players``
#: (not fetched for sims), transactions and drafts are not simulator inputs, and
#: the league object's top-level ``last_*`` cursors are dropped before hashing.
LEAGUE_SNAPSHOT_SCOPE = (
    "season",
    "league_id",
    "league",
    "rosters",
    "matchups_by_week",
    "winners_bracket",
    "losers_bracket",
)


def _league_snapshot_sha(snapshot: Any, nulls: dict[str, str]) -> str | None:
    try:
        seasons = []
        for season in getattr(snapshot, "seasons", None) or []:
            fields = {f: getattr(season, f, None) for f in LEAGUE_SNAPSHOT_SCOPE}
            if isinstance(fields["league"], dict):
                # Sleeper's top-level ``last_*`` keys are chat / notification
                # cursors (``last_message_time``, ``last_read_id``, ...) that move
                # with no change to anything a simulator reads; hashing them would
                # make two forecasts from identical inputs look different.
                # ``settings.last_scored_leg`` lives under ``settings`` and stays.
                fields["league"] = {
                    k: v for k, v in fields["league"].items() if not str(k).startswith("last_")
                }
            seasons.append(fields)
        if not seasons:
            nulls["inputs.leagueSnapshotSha256"] = "snapshot_has_no_seasons"
            return None
        managers = getattr(snapshot, "managers", None)
        ordered = managers.ordered_managers() if managers is not None else []
        return canonical_sha256(
            {
                "rootLeagueId": getattr(snapshot, "root_league_id", None),
                "seasons": seasons,
                "managers": [getattr(m, "owner_id", None) for m in ordered],
            }
        )
    except Exception as exc:  # noqa: BLE001
        nulls["inputs.leagueSnapshotSha256"] = f"error:{type(exc).__name__}"
        return None


def _hash_file(path: Path, field: str, nulls: dict[str, str]) -> str | None:
    try:
        if not path.exists():
            nulls[field] = "file_absent"
            return None
        return _file_sha256(path)
    except OSError as exc:
        nulls[field] = f"unreadable:{type(exc).__name__}"
        return None


def _inputs(snapshot: Any, nulls: dict[str, str]) -> dict[str, Any]:
    from src.ros import ROS_DATA_DIR  # noqa: PLC0415

    out: dict[str, Any] = {
        "leagueSnapshotSha256": _league_snapshot_sha(snapshot, nulls),
        "leagueSnapshotScope": list(LEAGUE_SNAPSHOT_SCOPE),
        "leagueSnapshotGeneratedAt": getattr(snapshot, "generated_at", None),
        "teamStrengthFileSha256": None,
        "teamStrengthFileFresh": None,
        "rosAggregateSha256": None,
        "rosAggregatedAt": None,
        "pointsModelFileSha256": None,
        # The playoff / championship engines read the ROS aggregate and team
        # strength, never the canonical dynasty contract. Recording a board
        # generation here would claim an input the forecast did not use.
        "contractGeneration": None,
    }
    nulls["inputs.contractGeneration"] = "not_an_input_of_the_playoff_or_title_simulators"
    try:
        from src.ros import team_strength  # noqa: PLC0415

        league_key = team_strength.resolve_snapshot_league_key(snapshot)
        out["teamStrengthFileSha256"] = _hash_file(
            team_strength._team_strength_path(league_key), "inputs.teamStrengthFileSha256", nulls
        )
        out["teamStrengthFileFresh"] = bool(team_strength._persisted_snapshot_is_fresh(league_key))
    except Exception as exc:  # noqa: BLE001
        nulls["inputs.teamStrengthFileSha256"] = f"error:{type(exc).__name__}"
        nulls["inputs.teamStrengthFileFresh"] = f"error:{type(exc).__name__}"
    agg = ROS_DATA_DIR / "aggregate" / "latest.json"
    out["rosAggregateSha256"] = _hash_file(agg, "inputs.rosAggregateSha256", nulls)
    if out["rosAggregateSha256"] is not None:
        try:
            out["rosAggregatedAt"] = json.loads(agg.read_text(encoding="utf-8")).get("aggregatedAt")
        except (OSError, ValueError, AttributeError) as exc:
            nulls["inputs.rosAggregatedAt"] = f"unreadable:{type(exc).__name__}"
        if out["rosAggregatedAt"] is None and "inputs.rosAggregatedAt" not in nulls:
            nulls["inputs.rosAggregatedAt"] = "aggregate_has_no_aggregatedAt"
    else:
        nulls["inputs.rosAggregatedAt"] = "aggregate_absent"
    try:
        from src.league_intel import sim_calibration  # noqa: PLC0415

        out["pointsModelFileSha256"] = _hash_file(
            sim_calibration.MODEL_PATH, "inputs.pointsModelFileSha256", nulls
        )
    except Exception as exc:  # noqa: BLE001
        nulls["inputs.pointsModelFileSha256"] = f"error:{type(exc).__name__}"
    return out


def collect_context(snapshot: Any, *, best_ball: bool | None) -> dict[str, Any]:
    """Per-league identity shared by both forecasts of one refresh. Never raises."""
    nulls: dict[str, str] = {}
    try:
        season_week = _season_week(snapshot, nulls)
    except Exception as exc:  # noqa: BLE001
        reason = f"error:{type(exc).__name__}"
        nulls.update(season=reason, week=reason, lastScoredWeek=reason)
        season_week = {"season": None, "week": None, "lastScoredWeek": None}
    params = _sim_params(best_ball, nulls)
    model = {
        **_code_identity(nulls),
        "simParamsSha256": None if params is None else canonical_sha256(params),
        "simParams": params,
    }
    if params is None:
        nulls["model.simParamsSha256"] = nulls.get("model.simParams", "unknown")
    try:
        inputs = _inputs(snapshot, nulls)
    except Exception as exc:  # noqa: BLE001
        nulls["inputs"] = f"error:{type(exc).__name__}"
        inputs = {}
    hashed = {k: v for k, v in inputs.items() if k.endswith("Sha256") or k == "rosAggregatedAt"}
    if any(v is not None for v in hashed.values()):
        # A partial fingerprint still pins what WAS known; which components
        # are missing is in ``nullReasons``.
        inputs["inputsSha256"] = canonical_sha256(hashed)
    else:
        inputs["inputsSha256"] = None
        nulls["inputs.inputsSha256"] = "no_input_could_be_hashed"
    return {**season_week, "model": model, "inputs": inputs, "nullReasons": nulls}


def build_identity(
    *, league_key: str | None, kind: str, forecast: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    """The identity sidecar for one forecast: everything but the forecast itself."""
    nulls = dict(context.get("nullReasons") or {})
    computed_at = forecast.get("computedAt")
    if not computed_at:
        nulls["computedAt"] = "absent_from_forecast"
    n_sims = forecast.get("n_simulations")
    if n_sims is None:
        nulls["nSimulations"] = "absent_from_forecast"
    if not league_key:
        nulls["leagueKey"] = "league_key_unresolved"
    return {
        "schema": IDENTITY_SCHEMA,
        "producer": PRODUCER,
        "kind": kind,
        "leagueKey": league_key or None,
        "computedAt": computed_at or None,
        "season": context.get("season"),
        "week": context.get("week"),
        "lastScoredWeek": context.get("lastScoredWeek"),
        "nSimulations": n_sims,
        "forecastSha256": canonical_sha256(dict(forecast)),
        "model": context.get("model"),
        "inputs": context.get("inputs"),
        "nullReasons": dict(sorted(nulls.items())),
    }


def unidentified(
    *, league_key: str | None, kind: str, forecast: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    """Identity for a forecast whose producer identity is unavailable."""
    nulls = {f: reason for f in ("season", "week", "lastScoredWeek", "model", "inputs")}
    return build_identity(
        league_key=league_key,
        kind=kind,
        forecast=forecast,
        context={
            "season": None,
            "week": None,
            "lastScoredWeek": None,
            "model": None,
            "inputs": None,
            "nullReasons": nulls,
        },
    )


def assemble_record(
    identity: Mapping[str, Any], forecast: Mapping[str, Any], *, transport: str
) -> dict[str, Any]:
    """One archive record: the identity, the forecast as produced, and its key."""
    forecast = dict(forecast)
    forecast_sha = canonical_sha256(forecast)
    if identity.get("forecastSha256") != forecast_sha:
        raise ValueError("identity does not describe this forecast")
    return {
        **identity,
        "schema": SCHEMA,
        "key": record_key(
            identity.get("leagueKey"),
            str(identity.get("kind")),
            identity.get("computedAt"),
            forecast_sha,
        ),
        "forecast": forecast,
        "transport": transport,
        "archivedAt": datetime.now(timezone.utc).isoformat(),
    }


# ── the store (append-only, monthly, keys index) ────────────────────


def _month_of(stamp: str | None) -> str:
    text = str(stamp or "")
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        return text[:7]
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ledger_path(base: Path = DEFAULT_DIR, month: str | None = None) -> Path:
    return Path(base) / f"forecasts-{_month_of(month)}.jsonl"


def ledger_files(base: Path = DEFAULT_DIR) -> list[Path]:
    return sorted(Path(base).glob("forecasts-[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl"))


def iter_records(base: Path = DEFAULT_DIR) -> Iterator[dict[str, Any]]:
    """Every parseable record, oldest file first. A torn line is skipped."""
    for path in ledger_files(base):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record


def _ends_with_newline(path: Path) -> bool:
    with path.open("rb") as fh:
        fh.seek(-1, os.SEEK_END)
        return fh.read(1) == b"\n"


def recorded_keys(base: Path = DEFAULT_DIR) -> set[str]:
    """Every archived key: the index, unioned with a scan when the index is absent.

    The scan also runs when the index exists but a ledger line's key is missing
    from it (a crash between the ledger append and the index append), because
    the tail of every file is checked -- a duplicate line is never the result.
    """
    index = Path(base) / INDEX_NAME
    if index.exists():
        with index.open("r", encoding="utf-8") as fh:
            keys = {line.strip() for line in fh if line.strip()}
        for path in ledger_files(base):
            tail = _last_key(path)
            if tail:
                keys.add(tail)
        return keys
    return {str(r["key"]) for r in iter_records(base) if r.get("key")}


def _last_key(path: Path) -> str | None:
    """The key of one file's final complete record, read from its tail only."""
    data = b""
    try:
        with path.open("rb") as fh:
            pos = fh.seek(0, os.SEEK_END)
            while pos > 0:
                step = min(65536, pos)
                pos -= step
                fh.seek(pos)
                data = fh.read(step) + data
                if data.rstrip(b"\n").count(b"\n") >= 1:
                    break
    except OSError:
        return None
    for raw in reversed(data.rstrip(b"\n").split(b"\n")[-2:]):
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(record, dict) and record.get("key"):
            return str(record["key"])
    return None


def append_record(base: Path, record: Mapping[str, Any]) -> bool:
    """Append ``record`` unless its key is already archived. True when written."""
    key = record.get("key")
    if not key:
        raise ValueError("record has no key")
    base = Path(base)
    index = base / INDEX_NAME
    seed = not index.exists()
    known = recorded_keys(base)
    if key in known:
        return False
    base.mkdir(parents=True, exist_ok=True)
    path = ledger_path(base, record.get("computedAt"))
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    torn = path.exists() and path.stat().st_size > 0 and not _ends_with_newline(path)
    with path.open("a", encoding="utf-8") as fh:
        if torn:  # a crash mid-append: start a fresh line, never rewrite one
            fh.write("\n")
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    index_torn = index.exists() and index.stat().st_size > 0 and not _ends_with_newline(index)
    with index.open("a", encoding="utf-8") as fh:
        if index_torn:
            fh.write("\n")
        for k in sorted(known) if seed else ():
            fh.write(k + "\n")
        fh.write(str(key) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return True


# ── the producer seam (never raises) ────────────────────────────────


def sidecar_path(sim_path: Path) -> Path:
    sim_path = Path(sim_path)
    return sim_path.with_name(sim_path.stem + SIDECAR_SUFFIX)


def write_identity_sidecar_safely(sim_path: Path, identity: Mapping[str, Any]) -> bool:
    """Write ``identity`` beside the sim file it describes. False on any failure."""
    try:
        target = sidecar_path(sim_path)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(
            json.dumps(dict(identity), indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        os.replace(tmp, target)
        return True
    except Exception as exc:  # noqa: BLE001 -- the archive must never fail a refresh
        LOG.warning("[ros] forecast identity sidecar for %s not written: %s", sim_path, exc)
        return False


def archive_safely(
    *,
    league_key: str | None,
    kind: str,
    forecast: Mapping[str, Any],
    context: Mapping[str, Any],
    sim_path: Path | None = None,
    base: Path | None = None,
) -> dict[str, Any] | None:
    """Producer seam: sidecar + local archive for one forecast. Never raises.

    Returns the identity written (``None`` if even that failed). The forecast
    file itself is written by the caller BEFORE this runs and is never touched.
    """
    try:
        identity = build_identity(
            league_key=league_key, kind=kind, forecast=forecast, context=context
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] forecast archive (%s %s): identity failed: %s", league_key, kind, exc)
        return None
    if sim_path is not None:
        write_identity_sidecar_safely(sim_path, identity)
    try:
        record = assemble_record(identity, forecast, transport=TRANSPORT_PRODUCER)
        append_record(DEFAULT_DIR if base is None else base, record)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] forecast archive (%s %s) not appended: %s", league_key, kind, exc)
    return identity


# ── the box-side ingest (published files, git history) ──────────────


def _identity_for(
    forecast: Mapping[str, Any], sidecar_text: str | None, *, league_key: str | None, kind: str
) -> dict[str, Any]:
    """The sidecar identity when it provably describes ``forecast``; else unidentified."""
    if sidecar_text is None:
        return unidentified(
            league_key=league_key, kind=kind, forecast=forecast, reason="identity_sidecar_missing"
        )
    try:
        identity = json.loads(sidecar_text)
    except ValueError:
        identity = None
    if not isinstance(identity, dict) or identity.get("schema") != IDENTITY_SCHEMA:
        return unidentified(
            league_key=league_key,
            kind=kind,
            forecast=forecast,
            reason="identity_sidecar_unreadable",
        )
    if identity.get("forecastSha256") != canonical_sha256(dict(forecast)):
        return unidentified(
            league_key=league_key, kind=kind, forecast=forecast, reason="identity_sidecar_mismatch"
        )
    return identity


def ingest_text(
    sim_text: str,
    sidecar_text: str | None,
    *,
    league_key: str | None,
    kind: str,
    transport: str,
    base: Path = DEFAULT_DIR,
) -> str:
    """Archive one published forecast. Returns ``written`` / ``duplicate`` / ``skipped:<why>``."""
    try:
        forecast = json.loads(sim_text)
    except ValueError:
        return "skipped:forecast_unreadable"
    if not isinstance(forecast, dict) or not forecast.get("computedAt"):
        return "skipped:not_a_forecast"
    identity = _identity_for(forecast, sidecar_text, league_key=league_key, kind=kind)
    record = assemble_record(identity, forecast, transport=transport)
    return "written" if append_record(base, record) else "duplicate"


def published_paths() -> list[tuple[str, str, Path]]:
    """``(leagueKey, kind, sim path)`` for every active league, via the writer's own naming."""
    from src.api.league_registry import active_leagues, default_league_key  # noqa: PLC0415
    from src.ros.scrape import _sim_paths  # noqa: PLC0415

    default_key = default_league_key()
    out: list[tuple[str, str, Path]] = []
    for cfg in active_leagues():
        playoff, champ = _sim_paths(cfg.key, default_key)
        out.append((cfg.key, "playoff", playoff))
        out.append((cfg.key, "championship", champ))
    return out


def ingest_published(base: Path = DEFAULT_DIR) -> dict[str, int]:
    """Archive the forecasts currently on disk beside their sidecars."""
    counts: dict[str, int] = {}
    for league_key, kind, path in published_paths():
        try:
            if not path.exists():
                status = "skipped:absent"
            else:
                side = sidecar_path(path)
                status = ingest_text(
                    path.read_text(encoding="utf-8"),
                    side.read_text(encoding="utf-8") if side.exists() else None,
                    league_key=league_key,
                    kind=kind,
                    transport=TRANSPORT_PUBLISHED_FILE,
                    base=base,
                )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[ros] forecast ingest %s %s failed: %s", league_key, kind, exc)
            status = "error"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def ingest_git_history(base: Path = DEFAULT_DIR, *, max_commits: int = 50) -> dict[str, int]:
    """Recover forecasts a skipped or cancelled deploy never placed on disk.

    Walks the last ``max_commits`` commits touching each published sim file.
    Only commits that ALSO carry the identity sidecar are archived: those were
    produced by this archive's producer. Earlier commits are counted as
    ``skipped:pre_archive`` -- backfilling them is a separate, labelled unit,
    never folded in here.
    """
    counts: dict[str, int] = {}
    for league_key, kind, path in published_paths():
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
            side_rel = sidecar_path(path).resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            counts["error:outside_repository"] = counts.get("error:outside_repository", 0) + 1
            continue
        log = _git("log", f"--max-count={int(max_commits)}", "--format=%H", "--", rel)
        if log is None:
            counts["error:git_log"] = counts.get("error:git_log", 0) + 1
            continue
        for sha in log.split():
            side = _git("show", f"{sha}:{side_rel}")
            if side is None:
                status = "skipped:pre_archive"
            else:
                sim = _git("show", f"{sha}:{rel}")
                try:
                    status = (
                        "skipped:absent"
                        if sim is None
                        else ingest_text(
                            sim,
                            side,
                            league_key=league_key,
                            kind=kind,
                            transport=TRANSPORT_GIT_HISTORY,
                            base=base,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    LOG.warning(
                        "[ros] forecast git ingest %s %s %s: %s", league_key, kind, sha, exc
                    )
                    status = "error"
            counts[status] = counts.get(status, 0) + 1
    return counts
