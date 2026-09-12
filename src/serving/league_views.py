"""Prepare league context upstream; API readers only consume local bytes.

The canonical board is shared by scoring identity. League-specific roster and
lineup context is projected separately, with the board generation in its key.
The producer is explicit; importing this module performs no provider work.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType

from src.api import league_registry, sleeper_overlay
from src.api.data_contract import stamp_optimal_lineups
from src.api.telemetry import work_span
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.serving.artifacts import ArtifactError, ArtifactStore, CorruptArtifact
from src.serving.builder import json_bytes, prepare_payload
from src.serving.projections import MODEL_VERSION, ReadModelEnvelope
from src.serving.runtime import PreparedBytes, PreparedPayload

log = logging.getLogger(__name__)
ASSET = "league-serving"
VIEWS = ("rankings", "trade", "catalog", "full", "array", "compact", "runtime", "startup")
ROSTER_STALE_CEILING_SECONDS = 30 * 60
STATES = ("ready", "stale", "unknown")


@dataclass(frozen=True)
class LeagueViews:
    board_generation: str
    league_key: str
    views: dict
    variants: dict | None = None
    binding: dict | None = None

    def __post_init__(self):
        object.__setattr__(self, "views", MappingProxyType(dict(self.views)))
        if self.binding is not None:
            object.__setattr__(self, "binding", MappingProxyType(dict(self.binding)))
        if self.variants is not None:
            object.__setattr__(
                self,
                "variants",
                MappingProxyType(
                    {state: MappingProxyType(dict(views)) for state, views in self.variants.items()}
                ),
            )


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


def _binding(board, cfg):
    """Small factual/configuration identity, shared by producer and reader."""
    from src.serving.input_manifest import content_identity

    configuration = asdict(cfg) if is_dataclass(cfg) else vars(cfg)
    return {
        "boardGeneration": board.generation_id,
        "leagueKey": cfg.key,
        "scoringProfile": cfg.scoring_profile,
        "boardScoring": scoring_fingerprint(
            (board.contract.get("sleeper") or {}).get("scoringSettings")
        ),
        "requestedScoring": league_registry.scoring_fingerprint_for_league(cfg),
        "leagueConfiguration": content_identity(configuration),
        "registryLineupSettings": content_identity(
            league_registry.get_league_roster_settings(cfg.key)
        ),
    }


def _attested_compatible(board, cfg):
    # Keep the loaded-league policy for missing registry evidence, but a known
    # changed factual card must not authorize old values even for the same key.
    loaded = scoring_fingerprint((board.contract.get("sleeper") or {}).get("scoringSettings"))
    requested = league_registry.scoring_fingerprint_for_league(cfg)
    return compatible(board, cfg) and not (requested and loaded != requested)


def _expired_views(views, state):
    return {
        name: prepare_payload(
            {
                **view.payload,
                "sleeper": None,
                "meta": {
                    **view.payload["meta"],
                    "sleeperDataReady": False,
                    "leagueFreshnessState": state,
                },
            }
        )
        for name, view in views.items()
    }


def _final_variants(bundle):
    ready = bundle.variants["ready"] if bundle.variants is not None else bundle.views
    variants = {"ready": ready}
    for state in ("stale", "unknown"):
        variants[state] = _expired_views(ready, state)
    return replace(bundle, views=ready, variants=variants)


def _parse_final_index(artifact):
    index = json.loads(artifact.files["index.json"])
    if (
        artifact.asset != ASSET
        or index.get("schemaVersion") != 2
        or artifact.manifest.get("modelVersion") != MODEL_VERSION
        or index.get("leagueKey") != artifact.key
        or set(index.get("variants", {})) != set(STATES)
        or artifact.manifest.get("inputGenerations", {}).get("board")
        != index.get("boardGeneration")
        or index.get("binding") != dict(artifact.manifest.get("leagueBinding", {}))
        or index.get("binding", {}).get("boardGeneration") != index.get("boardGeneration")
        or index.get("binding", {}).get("leagueKey") != index.get("leagueKey")
    ):
        raise CorruptArtifact("invalid final league serving index")
    expected_files = {"index.json"}
    for state in STATES:
        if set(index["variants"][state]) != set(VIEWS):
            raise CorruptArtifact("incomplete final league variants")
        for name in VIEWS:
            expected_files.add(f"{state}/{name}.gz")
            if state == "ready":
                expected_files.add(f"{state}/{name}.json")
            entry = index["variants"][state][name]
            meta = entry.get("metadata") or {}
            if (
                set(entry) != {"etag", "metadata"}
                or meta.get("readModelGeneration") != index["boardGeneration"]
                or meta.get("leagueKey") != index["leagueKey"]
                or meta.get("scoringProfile") != index["binding"].get("scoringProfile")
                or meta.get("leagueSourceAsOf") != artifact.manifest.get("sourceAsOf")
                or (
                    state != "ready"
                    and (
                        meta.get("sleeperDataReady") is not False
                        or meta.get("leagueFreshnessState") != state
                    )
                )
            ):
                raise CorruptArtifact("incoherent final league metadata")
    if set(artifact.files) - {"validation.json"} != expected_files:
        raise CorruptArtifact("unexpected final league inventory")
    return index


def _final_index(artifact):
    try:
        return _parse_final_index(artifact)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CorruptArtifact("invalid final league serving index") from exc


def _validate_final_bundle(bundle, board, cfg):
    """Producer proof covers both canonical semantics and exact expiry behavior."""
    if bundle.binding != _binding(board, cfg) or not _attested_compatible(board, cfg):
        raise CorruptArtifact("final league binding does not match current board/configuration")
    for views in bundle.variants.values():
        validate_league_views(replace(bundle, views=views), board, cfg)
    ready_meta = bundle.variants["ready"]["trade"].metadata
    for view in bundle.variants["ready"].values():
        if any(
            view.metadata.get(key) != ready_meta.get(key)
            for key in ("sleeperDataReady", "sleeperSource", "sleeperLoadedLeagueKey")
        ):
            raise CorruptArtifact("incoherent ready league metadata")
    for state in ("stale", "unknown"):
        for name in VIEWS:
            ready = bundle.variants["ready"][name].payload
            expected = {
                **ready,
                "sleeper": None,
                "meta": {
                    **ready["meta"],
                    "sleeperDataReady": False,
                    "leagueFreshnessState": state,
                },
            }
            if json_bytes(bundle.variants[state][name].payload) != json_bytes(expected):
                raise CorruptArtifact("expired league variant differs from ready transformation")


def _load_final_variants(artifact, index, *, lightweight):
    """Decode only the small index in web; semantic decoding belongs to producer."""
    variants = {}
    for state in STATES:
        views = {}
        for name in VIEWS:
            entry = index["variants"][state][name]
            gz = artifact.files[f"{state}/{name}.gz"]
            raw = (
                artifact.files[f"{state}/{name}.json"] if state == "ready" else gzip.decompress(gz)
            )
            if lightweight:
                views[name] = PreparedBytes(raw, gz, entry["etag"], name, entry["metadata"])
                continue
            payload = json.loads(raw)
            if name in {"rankings", "trade", "catalog"}:
                ReadModelEnvelope.model_validate(payload)
            if (
                hashlib.sha1(raw).hexdigest() != entry["etag"]
                or payload.get("meta") != entry["metadata"]
                or payload.get("payloadView") != name
                or (state == "ready" and gzip.decompress(gz) != raw)
                or (state != "ready" and payload.get("sleeper") is not None)
            ):
                raise CorruptArtifact("incoherent final league representation")
            views[name] = PreparedPayload(payload, raw, gz, entry["etag"])
        variants[state] = views
    return LeagueViews(
        index["boardGeneration"], index["leagueKey"], variants["ready"], variants, index["binding"]
    )


def load_web_league_views(artifact, board, cfg):
    """Verify an exact producer certificate before accepting byte-only views."""
    from src.serving.attestation import verify_artifact

    verify_artifact(artifact)
    index = _final_index(artifact)
    if index["binding"] != _binding(board, cfg) or not _attested_compatible(board, cfg):
        raise CorruptArtifact("final league binding does not match current board/configuration")
    return _load_final_variants(artifact, index, lightweight=True)


def validate_serialized_artifact(artifact, board, cfg):
    """Issuer-owned strict final representation validation against live context."""
    from src.serving.serialization import validate_generation

    if board is None or cfg is None:
        raise CorruptArtifact("league certification requires canonical board/configuration")
    validate_generation(board)
    binding = _binding(board, cfg)
    index = _final_index(artifact)
    if index["binding"] != binding or not _attested_compatible(board, cfg):
        raise CorruptArtifact("league certification context differs")
    loaded = _load_final_variants(artifact, index, lightweight=False)
    context = loaded.views["trade"].payload.get("sleeper") or {}
    expected = hashlib.sha256(json_bytes(context.get("scoringSettings"))).hexdigest()
    if artifact.manifest.get("configHash") != expected:
        raise CorruptArtifact("league serialized scoring identity differs")
    _validate_final_bundle(loaded, board, cfg)
    if _binding(board, cfg) != binding:
        raise CorruptArtifact("league effective configuration changed during validation")
    return loaded


def _publish_final_variants(bundle, store, *, input_generations, board, cfg):
    from src.serving.attestation import certify, verify_artifact

    if board is None or cfg is None:
        raise ValueError("attested league publication requires its canonical board/configuration")
    if not _attested_compatible(board, cfg):
        raise CorruptArtifact("league scoring changed since the canonical build")
    as_of = bundle.views["trade"].metadata.get("leagueSourceAsOf")
    try:
        if datetime.fromisoformat(str(as_of).replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("unqualified source age")
    except (TypeError, ValueError):
        # Malformed/missing age remains unknown. Never sign it as a known fresh
        # observation; readiness selection will choose the unknown variant.
        if as_of is not None:
            context = bundle.views["trade"].payload.get("sleeper")
            if isinstance(context, dict) and "overlayFetchedAt" in context:
                context = {**context, "overlayFetchedAt": None}
            bundle = replace(
                bundle,
                views={
                    name: prepare_payload(
                        {
                            **view.payload,
                            "sleeper": context,
                            "meta": {**view.metadata, "leagueSourceAsOf": None},
                        }
                    )
                    for name, view in bundle.views.items()
                },
                variants=None,
            )
    bundle = _final_variants(bundle)
    binding = _binding(board, cfg)
    index = {
        "schemaVersion": 2,
        "boardGeneration": bundle.board_generation,
        "leagueKey": bundle.league_key,
        "binding": binding,
        "variants": {
            state: {
                name: {"etag": view.etag, "metadata": view.metadata} for name, view in views.items()
            }
            for state, views in bundle.variants.items()
        },
    }
    files = {"index.json": json_bytes(index)}
    for state, views in bundle.variants.items():
        for name, view in views.items():
            files[f"{state}/{name}.gz"] = view.gzip
            if state == "ready":
                files[f"{state}/{name}.json"] = view.raw
    context = bundle.views["trade"].payload.get("sleeper") or {}
    metadata = {
        "modelVersion": MODEL_VERSION,
        "inputGenerations": input_generations or {"board": bundle.board_generation},
        "configHash": hashlib.sha256(json_bytes(context.get("scoringSettings"))).hexdigest(),
        "sourceAsOf": bundle.views["trade"].metadata.get("leagueSourceAsOf"),
        "leagueBinding": binding,
    }

    files = certify(store, ASSET, cfg.key, files, metadata, board=board, cfg=cfg)
    return store.publish(
        ASSET,
        cfg.key,
        files,
        metadata,
        validator=lambda artifact: verify_artifact(artifact, require_observation=False),
    )


def reobserve_league_views(artifact, store, *, board, cfg, input_generations, source_as_of):
    """Restamp final producer bytes without rerunning roster/lineup construction."""
    loaded = load_league_views(artifact)
    ready = loaded.variants["ready"] if loaded.variants is not None else loaded.views
    context = ready["trade"].payload.get("sleeper")
    if isinstance(context, dict) and "overlayFetchedAt" in context:
        context = {**context, "overlayFetchedAt": source_as_of}
    views = {
        name: prepare_payload(
            {
                **view.payload,
                "sleeper": context,
                "meta": {**view.metadata, "leagueSourceAsOf": source_as_of},
            }
        )
        for name, view in ready.items()
    }
    return publish_league_views(
        LeagueViews(board.generation_id, cfg.key, views),
        store,
        input_generations=input_generations,
        board=board,
        cfg=cfg,
    )


def publish_league_views(
    bundle: LeagueViews, store: ArtifactStore, *, input_generations=None, board=None, cfg=None
):
    from src.serving.attestation import enabled

    if enabled():
        return _publish_final_variants(
            bundle, store, input_generations=input_generations, board=board, cfg=cfg
        )
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
    index = json.loads(artifact.files["index.json"])
    if index.get("schemaVersion") == 2:
        return _load_final_variants(artifact, _final_index(artifact), lightweight=False)
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


def _validate_accepted_league(artifact, board, cfg):
    """Producer no-op eligibility still proves every accepted final variant."""
    from src.serving.attestation import enabled, verify_artifact

    if enabled():
        verify_artifact(artifact)
    loaded = load_league_views(artifact)
    if loaded.variants is not None:
        _validate_final_bundle(loaded, board, cfg)
    else:
        validate_league_views(loaded, board, cfg)


def _freshness_state(meta, *, now=None):
    if not meta.get("sleeperDataReady"):
        return "ready"
    as_of = meta.get("leagueSourceAsOf")
    try:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("unqualified source timestamp")
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if -300 <= age <= ROSTER_STALE_CEILING_SECONDS:
            return "ready"
        state = "stale" if age >= 0 else "unknown"
    except (TypeError, ValueError):
        state = "unknown"
    return state


def expire_context(bundle: LeagueViews, *, now=None) -> LeagueViews:
    """Age is source age; attested expiry only selects existing representations."""
    ready = bundle.variants["ready"] if bundle.variants is not None else bundle.views
    state = _freshness_state(ready["trade"].metadata, now=now)
    if bundle.variants is not None:
        selected = bundle.variants[state]
        if all(bundle.views[name] is selected[name] for name in VIEWS):
            return bundle
        return replace(bundle, views=selected)
    if state == "ready":
        return bundle
    return LeagueViews(bundle.board_generation, bundle.league_key, _expired_views(ready, state))


def _cold_bundle(board, cfg, *, lightweight):
    # A lightweight canonical board has byte-only read models. Project from the
    # full canonical contract explicitly for this cold, artifact-free fallback;
    # a missing decoded projection is never treated as an empty player universe.
    semantic = board
    if any(not hasattr(board.views[name], "payload") for name in VIEWS):
        from src.serving.builder import project_contract_views

        semantic = replace(
            board,
            views={
                name: prepare_payload(payload)
                for name, payload in project_contract_views(
                    board.contract, board.generation_id
                ).items()
            },
        )
    bundle = prepare_league_views(semantic, cfg)
    if not lightweight:
        return bundle
    bundle = _final_variants(bundle)
    variants = {
        state: {
            name: PreparedBytes(view.raw, view.gzip, view.etag, name, view.metadata)
            for name, view in views.items()
        }
        for state, views in bundle.variants.items()
    }
    return replace(bundle, views=variants["ready"], variants=variants, binding=_binding(board, cfg))


def refresh_league_serving(store=None, *, lease_wait_seconds=0) -> dict:
    """One league-refresh owner; queued requests never run providers in web."""
    from src.serving.artifacts import _mkdir, _publish_lock, PublishLockTimeout
    from src.serving.producer_status import claim_league_refresh

    store = store or ArtifactStore()
    _mkdir(store.root)
    admitted = False
    try:
        with _publish_lock(store.root / "league-producer.lock", lease_wait_seconds):
            admitted = True
            claim_league_refresh(store)
            return _refresh_league_serving(store)
    except PublishLockTimeout:
        if admitted:
            raise  # Claim/storage timeouts after admission are refresh failures.
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
    from src.serving.attestation import enabled

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
                    validate=lambda artifact: _validate_accepted_league(artifact, board, cfg),
                    source_as_of=overlay.get("overlayFetchedAt"),
                    reobserve=(
                        lambda artifact, inputs, stamp: reobserve_league_views(
                            artifact,
                            store,
                            board=board,
                            cfg=cfg,
                            input_generations=inputs,
                            source_as_of=stamp,
                        )
                    )
                    if enabled()
                    else None,
                )
                report["published"].append(cfg.key)
                if not result.rebuilt:
                    report["reobserved"].append(cfg.key)
        except Exception as exc:  # noqa: BLE001
            report["failed"].append(cfg.key)
            log.warning("league serving refresh failed for %s: %s", cfg.key, exc)
    return report


class LeagueServingReader:
    """Publish each league's bound board and views together, off-request."""

    def __init__(self, store, get_board, *, lightweight=False):
        self.store, self.get_board = store, get_board
        self.lightweight = lightweight
        self._current = {}
        self._versions = {}
        self._refresh_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.last_error = None

    def capture(self, league_key):
        """Capture once: callers keep the bound board through their response.

        A newer canonical pointer does not invalidate this accepted snapshot.
        One snapshot per active league is retained; in-flight requests own older
        refs. Leagues sharing a board share its object, without generation history.
        """
        return self._current.get(league_key)

    def get(self, generation, league_key, view):
        captured = self.capture(league_key)
        if captured is None or captured[0].generation_id != generation:
            return None
        return captured[1].views.get(view)

    def refresh(self):
        # Concurrent manual/poll refreshes coalesce. Request captures never wait
        # on this lock or on candidate loading/encoding.
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._refresh()
        finally:
            self._refresh_lock.release()

    def _refresh(self):
        old = self._current
        # Even a failed next-board build must not preserve ready roster context
        # beyond its existing source-age ceiling. Expiry stays off-request.
        expired = {
            key: (held_board, expire_context(bundle)) for key, (held_board, bundle) in old.items()
        }
        if any(expired[key][1] is not old[key][1] for key in old):
            self._current = expired
        old = expired
        board = self.get_board()
        if board is None:
            return
        refresh_error = None
        captures = {}
        versions = {}
        for cfg in league_registry.active_leagues():
            if not (
                _attested_compatible(board, cfg) if self.lightweight else compatible(board, cfg)
            ):
                continue
            held = old.get(cfg.key)
            if self.lightweight and held is not None and held[1].binding != _binding(held[0], cfg):
                # A last-known-good board cannot authorize an old scoring or
                # league configuration after that configuration changes.
                held = None
            if held is not None:
                captures[cfg.key] = held
                if cfg.key in self._versions:
                    versions[cfg.key] = self._versions[cfg.key]
            try:
                version = self.store.current_version(ASSET, cfg.key)
                if (
                    held is not None
                    and held[0].generation_id == board.generation_id
                    and versions.get(cfg.key) == version
                ):
                    captures[cfg.key] = (board, held[1])
                    continue
                artifact = self.store.read_current(ASSET, cfg.key)
                bundle = (
                    load_web_league_views(artifact, board, cfg)
                    if self.lightweight
                    else load_league_views(artifact)
                )
                if bundle.board_generation != board.generation_id:
                    raise CorruptArtifact("league bundle belongs to an older board")
                if not self.lightweight:
                    if bundle.variants is not None:
                        _validate_final_bundle(bundle, board, cfg)
                    else:
                        validate_league_views(bundle, board, cfg)
                captures[cfg.key] = (board, expire_context(bundle))
                versions[cfg.key] = version
            except (ArtifactError, ValueError, KeyError, OSError) as exc:
                refresh_error = type(exc).__name__
                if held is not None:
                    # Canonical publication precedes the standalone league job.
                    # Keep coherent A until B's prepared artifacts arrive; do
                    # not encode eight replacement views in the web process on
                    # each refresh. Expired A context was already removed above.
                    continue
                if cfg.key not in captures:
                    # Explicit board-as-of context for its own league, and
                    # unavailable context for another compatible league. No
                    # provider fetch is hidden behind this fallback.
                    captures[cfg.key] = (
                        board,
                        expire_context(_cold_bundle(board, cfg, lightweight=self.lightweight)),
                    )
        if self.get_board() is board and not self._stop.is_set():
            self._current = captures
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
