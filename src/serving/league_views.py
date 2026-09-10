"""Prepare league context upstream; API readers only consume local bytes.

The canonical board is shared by scoring identity. League-specific roster and
lineup context is projected separately, with the board generation in its key.
The producer is explicit; importing this module performs no provider work.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from src.api import league_registry, sleeper_overlay
from src.api.data_contract import stamp_optimal_lineups
from src.api.telemetry import work_span
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.serving.artifacts import ArtifactError, ArtifactStore, CorruptArtifact
from src.serving.builder import json_bytes, prepare_payload
from src.serving.projections import MODEL_VERSION, ReadModelEnvelope
from src.serving.runtime import PreparedPayload

log = logging.getLogger(__name__)
ASSET = "league-serving"
VIEWS = ("rankings", "trade", "catalog", "full", "array", "compact", "runtime", "startup")
ROSTER_STALE_CEILING_SECONDS = 30 * 60


@dataclass(frozen=True)
class LeagueViews:
    board_generation: str
    league_key: str
    views: dict

    def __post_init__(self):
        object.__setattr__(self, "views", MappingProxyType(dict(self.views)))


def compatible(board, cfg) -> bool:
    # Reuse the existing loaded-league policy. Cross-league reuse needs the
    # factual scoring card, never merely the registry's profile label.
    if (board.contract.get("meta") or {}).get("leagueKey") == cfg.key:
        return True
    loaded = scoring_fingerprint((board.contract.get("sleeper") or {}).get("scoringSettings"))
    requested = league_registry.scoring_fingerprint_for_league(cfg)
    return bool(loaded and requested and loaded == requested)


def prepare_league_views(board, cfg, overlay=None) -> LeagueViews:
    if not compatible(board, cfg):
        raise ValueError("league scoring identity is incompatible with this board")
    loaded = board.contract.get("sleeper") or {}
    same = (board.contract.get("meta") or {}).get("leagueKey") == cfg.key
    context = loaded if same else None
    ready = bool(
        same
        and loaded.get("teams")
        and sleeper_overlay.league_config_is_complete(loaded)
        and (board.contract.get("meta") or {}).get("sleeperDataReady") is not False
    )
    if overlay and overlay.get("teams"):
        if same:
            # The league-specific configuration from a refreshed overlay is
            # authoritative when complete; otherwise preserve the baked card.
            context = {
                **loaded,
                **{
                    k: overlay[k]
                    for k in (
                        "teams",
                        "trades",
                        "waivers",
                        "tradeWindowDays",
                        "tradeWindowStart",
                        "tradeWindowCutoffMs",
                        "overlayFetchedAt",
                        "overlaySource",
                    )
                    if k in overlay
                },
            }
            config = overlay.get("leagueConfig")
            if sleeper_overlay.league_config_is_complete(config):
                context.update(
                    {
                        k: config[k]
                        for k in sleeper_overlay.LEAGUE_SPECIFIC_SLEEPER_FIELDS
                        if k in config
                    }
                )
            ready = bool(
                context.get("teams") and sleeper_overlay.league_config_is_complete(context)
            )
        else:
            context, ready = sleeper_overlay.merge_cross_league_sleeper_block(
                loaded_sleeper=loaded,
                overlay=overlay,
                requested_league_config=overlay.get("leagueConfig"),
            )
        # A newly observed scoring card cannot be laid over values built under
        # different rules. Retain the previous generation until its board lands.
        loaded_fp = scoring_fingerprint(loaded.get("scoringSettings"))
        context_fp = scoring_fingerprint((context or {}).get("scoringSettings"))
        if loaded_fp and context_fp and loaded_fp != context_fp:
            raise ValueError("league scoring changed since the canonical build")
        container = {
            "sleeper": copy.deepcopy(context),
            "meta": {**(board.contract.get("meta") or {}), "leagueKey": cfg.key},
        }
        stamp_optimal_lineups(container, rows=board.contract.get("playersArray"))
        context = container["sleeper"]
    result = {}
    for view in VIEWS:
        base = board.views[view].payload
        meta = {
            **(base.get("meta") or {}),
            "readModelGeneration": board.generation_id,
            "leagueKey": cfg.key,
            "scoringProfile": cfg.scoring_profile,
            "sleeperDataReady": ready,
            "sleeperSource": "prepared-overlay" if overlay else "prepared-board",
            "leagueSourceAsOf": (context or {}).get("overlayFetchedAt")
            or board.source.get("producedAt")
            if context
            else None,
        }
        if not same:
            meta["sleeperLoadedLeagueKey"] = (board.contract.get("meta") or {}).get("leagueKey")
        payload = {**base, "payloadView": view, "meta": meta, "sleeper": context}
        result[view] = prepare_payload(payload)
    return LeagueViews(board.generation_id, cfg.key, result)


def validate_league_views(bundle: LeagueViews, board, cfg) -> None:
    """Bind accepted bytes to the canonical board and factual league context."""
    if (
        bundle.board_generation != board.generation_id
        or bundle.league_key != cfg.key
        or not compatible(board, cfg)
        or set(bundle.views) != set(VIEWS)
    ):
        raise CorruptArtifact("league bundle does not match its canonical board")
    context = bundle.views["trade"].payload.get("sleeper")
    if context:
        loaded_fp = scoring_fingerprint(
            (board.contract.get("sleeper") or {}).get("scoringSettings")
        )
        context_fp = scoring_fingerprint(context.get("scoringSettings"))
        if loaded_fp and context_fp != loaded_fp:
            raise CorruptArtifact("league context has a different factual scoring card")
        context_id = context.get("leagueId")
        requested_id = getattr(cfg, "sleeper_league_id", None)
        if context_id and requested_id and str(context_id) != str(requested_id):
            raise CorruptArtifact("league context belongs to another league")
    context_bytes = json_bytes(context)
    allowed_meta = {
        "readModelGeneration",
        "leagueKey",
        "scoringProfile",
        "sleeperDataReady",
        "sleeperSource",
        "leagueSourceAsOf",
        "sleeperLoadedLeagueKey",
        "leagueFreshnessState",
    }
    for name, view in bundle.views.items():
        payload, canonical = view.payload, board.views[name].payload
        meta = payload.get("meta") or {}
        if (
            meta.get("readModelGeneration") != board.generation_id
            or meta.get("leagueKey") != cfg.key
            or meta.get("scoringProfile") != cfg.scoring_profile
            or json_bytes(payload.get("sleeper")) != context_bytes
        ):
            raise CorruptArtifact("incoherent league context")
        if meta.get("sleeperDataReady") and not (
            context and context.get("teams") and sleeper_overlay.league_config_is_complete(context)
        ):
            raise CorruptArtifact("incomplete league context marked ready")

        def invariant(value):
            return {
                **{k: v for k, v in value.items() if k not in {"meta", "sleeper", "payloadView"}},
                "meta": {
                    k: v for k, v in (value.get("meta") or {}).items() if k not in allowed_meta
                },
            }

        if json_bytes(invariant(payload)) != json_bytes(invariant(canonical)):
            raise CorruptArtifact("league view differs from its canonical projection")


def publish_league_views(
    bundle: LeagueViews, store: ArtifactStore, *, input_generations=None, board=None, cfg=None
):
    if board is not None:
        validate_league_views(bundle, board, cfg)

    def validate(artifact):
        loaded = load_league_views(artifact)
        if board is not None:
            validate_league_views(loaded, board, cfg)
        return loaded

    files = {
        "index.json": json_bytes(
            {
                "schemaVersion": 1,
                "boardGeneration": bundle.board_generation,
                "leagueKey": bundle.league_key,
                "views": {name: view.etag for name, view in bundle.views.items()},
            }
        )
    }
    for name, view in bundle.views.items():
        files[f"{name}.json"] = view.raw
        files[f"{name}.gz"] = view.gzip
    context = bundle.views["trade"].payload.get("sleeper") or {}
    metadata = {
        "modelVersion": MODEL_VERSION,
        "inputGenerations": input_generations or {"board": bundle.board_generation},
        "configHash": hashlib.sha256(json_bytes(context.get("scoringSettings"))).hexdigest(),
        "sourceAsOf": bundle.views["trade"].payload["meta"].get("leagueSourceAsOf"),
    }
    return store.publish(ASSET, bundle.league_key, files, metadata, validator=validate)


def load_league_views(artifact) -> LeagueViews:
    import gzip

    index = json.loads(artifact.files["index.json"])
    if index.get("schemaVersion") != 1 or index.get("leagueKey") != artifact.key:
        raise CorruptArtifact("invalid league serving index")
    views = {}
    for name in VIEWS:
        raw, gz = artifact.files[f"{name}.json"], artifact.files[f"{name}.gz"]
        payload = json.loads(raw)
        if name in {"rankings", "trade", "catalog"}:
            ReadModelEnvelope.model_validate(payload)
        if (
            payload["meta"].get("readModelGeneration") != index["boardGeneration"]
            or payload["meta"].get("leagueKey") != index["leagueKey"]
            or payload.get("payloadView") != name
            or hashlib.sha1(raw).hexdigest() != index["views"][name]
            or gzip.decompress(gz) != raw
        ):
            raise CorruptArtifact("incoherent league serving view")
        source_as_of = artifact.manifest.get("sourceAsOf")
        if source_as_of and source_as_of != payload["meta"].get("leagueSourceAsOf"):
            payload["meta"]["leagueSourceAsOf"] = source_as_of
            if (
                isinstance(payload.get("sleeper"), dict)
                and "overlayFetchedAt" in payload["sleeper"]
            ):
                payload["sleeper"]["overlayFetchedAt"] = source_as_of
            views[name] = prepare_payload(payload)
        else:
            views[name] = PreparedPayload(payload, raw, gz, index["views"][name])
    return LeagueViews(index["boardGeneration"], index["leagueKey"], views)


def expire_context(bundle: LeagueViews, *, now=None) -> LeagueViews:
    """Age is source age, never process load time; missing age is unknown."""
    meta = bundle.views["trade"].payload.get("meta") or {}
    if not meta.get("sleeperDataReady"):
        return bundle
    as_of = meta.get("leagueSourceAsOf")
    try:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("unqualified source timestamp")
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if -300 <= age <= ROSTER_STALE_CEILING_SECONDS:
            return bundle
        state = "stale" if age >= 0 else "unknown"
    except (TypeError, ValueError):
        state = "unknown"
    views = {}
    for name, view in bundle.views.items():
        payload = {
            **view.payload,
            "sleeper": None,
            "meta": {
                **view.payload["meta"],
                "sleeperDataReady": False,
                "leagueFreshnessState": state,
            },
        }
        views[name] = prepare_payload(payload)
    return LeagueViews(bundle.board_generation, bundle.league_key, views)


def refresh_league_serving(store=None, *, lease_wait_seconds=0) -> dict:
    """One league-refresh owner; queued requests never run providers in web."""
    from src.serving.artifacts import _mkdir, _publish_lock, PublishLockTimeout
    from src.serving.producer_status import claim_league_refresh

    store = store or ArtifactStore()
    _mkdir(store.root)
    try:
        with _publish_lock(store.root / "league-producer.lock", lease_wait_seconds):
            claim_league_refresh(store)
            return _refresh_league_serving(store)
    except PublishLockTimeout:
        return {
            "outcome": "busy",
            "published": [],
            "reobserved": [],
            "failed": [],
            "boardGeneration": None,
        }


def _refresh_league_serving(store) -> dict:
    """Standalone producer entrypoint; the ONLY provider work in this module."""
    from src.serving.serialization import ASSET as BOARD_ASSET, KEY, load_generation
    from src.serving.coordinator import prepare_or_reobserve
    from src.serving.input_manifest import league_input_manifest

    store = store or ArtifactStore()
    board = load_generation(store.read_current(BOARD_ASSET, KEY))
    report = {
        "published": [],
        "reobserved": [],
        "failed": [],
        "boardGeneration": board.generation_id,
    }
    loaded = board.contract.get("sleeper") or {}
    for cfg in league_registry.active_leagues():
        try:
            with work_span("producer.league_context"):
                league_registry.refresh_scoring_snapshot(cfg)
                overlay = sleeper_overlay.fetch_sleeper_overlay(
                    sleeper_league_id=cfg.sleeper_league_id,
                    id_to_player=loaded.get("idToPlayer") or {},
                    force_refresh=True,
                )
                if not overlay or not overlay.get("teams"):
                    raise ValueError("league provider returned no valid roster")
                manifest = league_input_manifest(
                    board,
                    cfg,
                    overlay,
                    factual_scoring_fingerprint=scoring_fingerprint(
                        (overlay.get("leagueConfig") or {}).get("scoringSettings")
                    ),
                    registry_defaults=league_registry.get_league_roster_settings(cfg.key),
                )
                result = prepare_or_reobserve(
                    store=store,
                    asset=ASSET,
                    key=cfg.key,
                    manifest=manifest,
                    build=lambda: prepare_league_views(board, cfg, overlay),
                    publish=lambda bundle, inputs: publish_league_views(
                        bundle, store, input_generations=inputs, board=board, cfg=cfg
                    ),
                    validate=lambda artifact: validate_league_views(
                        load_league_views(artifact), board, cfg
                    ),
                    source_as_of=overlay.get("overlayFetchedAt"),
                )
                report["published"].append(cfg.key)
                if not result.rebuilt:
                    report["reobserved"].append(cfg.key)
        except Exception as exc:  # noqa: BLE001
            report["failed"].append(cfg.key)
            log.warning("league serving refresh failed for %s: %s", cfg.key, exc)
    return report


class LeagueServingReader:
    """Poll local pointers off-request, preserving an accepted same-board bundle."""

    def __init__(self, store, get_board):
        self.store, self.get_board = store, get_board
        self._current = (None, {})
        self._versions = {}
        self._stop = threading.Event()
        self._thread = None
        self.last_error = None

    def get(self, generation, league_key, view):
        current_generation, bundles = self._current
        if generation != current_generation:
            return None
        bundle = bundles.get(league_key)
        return bundle.views.get(view) if bundle else None

    def refresh(self):
        board = self.get_board()
        if board is None:
            return
        old_generation, old = self._current
        refresh_error = None
        bundles = dict(old) if old_generation == board.generation_id else {}
        versions = dict(self._versions) if old_generation == board.generation_id else {}
        for cfg in league_registry.active_leagues():
            if not compatible(board, cfg):
                bundles.pop(cfg.key, None)
                continue
            try:
                version = self.store.current_version(ASSET, cfg.key)
                if cfg.key in bundles and versions.get(cfg.key) == version:
                    bundles[cfg.key] = expire_context(bundles[cfg.key])
                    continue
                bundle = load_league_views(self.store.read_current(ASSET, cfg.key))
                if bundle.board_generation != board.generation_id:
                    raise CorruptArtifact("league bundle belongs to an older board")
                validate_league_views(bundle, board, cfg)
                bundles[cfg.key], versions[cfg.key] = expire_context(bundle), version
            except (ArtifactError, ValueError, KeyError, OSError) as exc:
                refresh_error = type(exc).__name__
                if cfg.key not in bundles:
                    # Explicit board-as-of context for its own league, and
                    # unavailable context for another compatible league. No
                    # provider fetch is hidden behind this fallback.
                    bundles[cfg.key] = prepare_league_views(board, cfg)
                bundles[cfg.key] = expire_context(bundles[cfg.key])
        if self.get_board() is board and not self._stop.is_set():
            self._current = (board.generation_id, bundles)
            self._versions = versions
            self.last_error = refresh_error

    def start(self, interval=2):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def run():
            while not self._stop.is_set():
                try:
                    self.refresh()
                except Exception as exc:  # noqa: BLE001
                    self.last_error = type(exc).__name__
                self._stop.wait(interval)

        self._thread = threading.Thread(target=run, name="league-serving-reader", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
