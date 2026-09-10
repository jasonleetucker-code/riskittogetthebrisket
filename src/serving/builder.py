"""Canonical build and prepared representations shared by web and producer.

Only this adapter invokes the existing data-contract/history owners. Artifact
reload deserializes prepared bytes and never invokes these calculations.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from types import MappingProxyType

from src.api import data_contract, rank_history as _rank_history
from src.api import source_history as _source_history, league_registry as _league_registry
from src.api.compact_view import compact_contract
from src.history import record as _history_record
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.api.telemetry import work_span
from src.serving.projections import player_index, project_board
from src.serving.runtime import PreparedPayload, ServingGeneration

log = logging.getLogger(__name__)


def source_coverage(contract: dict | None) -> dict:
    coverage = {}
    for row in (contract or {}).get("playersArray") or []:
        for key in row.get("sourceRankMeta") or {}:
            coverage[key] = coverage.get(key, 0) + 1
    return coverage


def _contract_scoring_fingerprint(contract):
    return scoring_fingerprint((contract.get("sleeper") or {}).get("scoringSettings"))


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def prepare_payload(payload: dict) -> PreparedPayload:
    raw = json_bytes(payload)
    return PreparedPayload(
        payload, raw, gzip.compress(raw, compresslevel=5, mtime=0), hashlib.sha1(raw).hexdigest()
    )


def project_contract_views(contract: dict, generation: str, *, include_read_models=True) -> dict:
    """Pure serving projections shared by preparation and acceptance checks."""
    runtime = {k: v for k, v in contract.items() if k != "playersArray"}
    runtime["payloadView"] = "runtime"
    array = {k: v for k, v in contract.items() if k != "players"}
    array["payloadView"] = "array"
    views = {
        "full": contract,
        "runtime": runtime,
        "array": array,
        "startup": data_contract.build_api_startup_payload(runtime),
        "compact": compact_contract(contract),
    }
    if include_read_models:
        for view in ("rankings", "trade", "catalog"):
            views[view] = project_board(contract, generation, view=view)
    return views


def prepare_generation(
    contract: dict, raw: dict, source: dict, health: dict, *, include_read_models=True
) -> ServingGeneration:
    with work_span("serving.prepare"):
        generation = hashlib.sha256(json_bytes(contract)).hexdigest()
        views = {
            name: prepare_payload(payload)
            for name, payload in project_contract_views(
                contract, generation, include_read_models=include_read_models
            ).items()
        }
        return ServingGeneration(
            generation,
            contract,
            raw,
            dict(source),
            health,
            source_coverage(contract),
            MappingProxyType(views),
            indexes={"players": player_index(contract)} if include_read_models else {},
        )


def build_generation(
    raw: dict,
    source: dict,
    *,
    is_fresh_scrape=False,
    build_contract=None,
    validate_contract=None,
    include_read_models=True,
) -> ServingGeneration:
    build_contract = build_contract or data_contract.build_api_data_contract
    validate_contract = validate_contract or data_contract.validate_api_data_contract
    with work_span("serving.canonical_build"):
        contract_payload = build_contract(raw, data_source=source)
    contract_report = validate_contract(contract_payload)
    if not contract_report.get("ok"):
        raise ValueError(
            "candidate contract validation failed: "
            + "; ".join((contract_report.get("errors") or [])[:5])
        )
    contract_payload["contractHealth"] = {
        "ok": bool(contract_report.get("ok")),
        "status": contract_report.get("status"),
        "errorCount": int(contract_report.get("errorCount", 0)),
        "warningCount": int(contract_report.get("warningCount", 0)),
        "checkedAt": contract_report.get("checkedAt"),
    }
    try:
        _rank_history.stamp_contract_with_history(contract_payload, include_current=is_fresh_scrape)
    except Exception as exc:  # noqa: BLE001
        log.warning("rank_history: preview/stamp failed: %s", exc)
    # Tag the contract with the league + scoring profile it was
    # built for.  Two different roles:
    #
    #   * ``meta.leagueKey`` — which specific league's Sleeper
    #     block (teams, rosters, ownerIds) is stamped here.
    #     Team-requiring endpoints (/api/terminal, /api/trade/*)
    #     reject requests for other leagues with 503.
    #   * ``meta.scoringProfile`` — which scoring rules produced
    #     these rankings.  Rankings endpoints (/api/data,
    #     /api/rankings/overrides) serve the same rankings to
    #     any league that shares the profile, and only 503 when
    #     profiles actually differ.
    #
    # This split is the core of the "scoring drives rankings,
    # league drives context" architecture — see CLAUDE.md.
    #   * ``meta.scoringFingerprint`` — the FACTUAL identity of the
    #     scoring that produced them (W18-F001).  Derived from the
    #     contract's OWN ``sleeper.scoringSettings``, i.e. the card
    #     the scrape actually fetched from the host, and NOT copied
    #     from the registry: a stamp taken from a second file proves
    #     only that the second file said so, while this one can be
    #     recomputed from the artifact it describes.  Absent — never
    #     a hash of ``{}`` — when the scrape carried no card.
    try:
        _default_cfg = _league_registry.get_default_league()
        if _default_cfg and isinstance(contract_payload, dict):
            meta_block = contract_payload.setdefault("meta", {})
            meta_block["leagueKey"] = _default_cfg.key
            meta_block["scoringProfile"] = _default_cfg.scoring_profile
            _fp = _contract_scoring_fingerprint(contract_payload)
            if _fp:
                meta_block["scoringFingerprint"] = _fp
            else:
                meta_block.pop("scoringFingerprint", None)
    except Exception:  # noqa: BLE001
        pass
    return prepare_generation(
        contract_payload, raw, source, contract_report, include_read_models=include_read_models
    )


def record_accepted_generation(candidate: ServingGeneration) -> None:
    """Independent nonfatal recorders, called ONLY after a fresh build publishes.

    Candidate construction uses a read-only preview of today's rank point so
    the accepted payload matches the prior append-then-stamp behavior. Startup
    and artifact reload never call this function.
    """
    for name, recorder in (
        ("rank_history", _rank_history.append_snapshot),
        ("source_history", _source_history.append_snapshot),
        ("temporal_ledger", _history_record.record_contract),
    ):
        try:
            recorder(candidate.contract)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: accepted generation record failed: %s", name, exc)
