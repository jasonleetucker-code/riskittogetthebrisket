"""Synthetic dynasty_main-shaped boards and BDVM-shaped payloads.

No live data, no network. Shapes mirror ``src.api.data_contract`` playersArray
rows and ``src.bdvm.service.run_valuation`` output, reduced to the fields the
challenger reads.
"""

from __future__ import annotations

import copy
import random
from datetime import datetime, timezone
from typing import Any, Iterable

from src.league_valuation.challenger import compute_fair_values
from src.league_valuation.contracts import MODEL_VERSION, load_params
from src.league_valuation.evidence import utility_evidence_from_bdvm

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
SNAPSHOT_AS_OF = "2026-10-14T06:10:00+00:00"
LEAGUE_KEY = "dynasty_main"
PARAMS = load_params()

OFFENSE = ("QB", "RB", "WR", "TE")
IDP = ("DL", "LB", "DB")


def pins(params: dict[str, Any] | None = None) -> dict[str, str]:
    p = params or PARAMS
    return {
        "leagueKey": LEAGUE_KEY,
        "scoringFingerprint": "sf1:0123456789abcdef",
        "formatFingerprint": "tmf1:fedcba9876543210",
        "contractScrapeTimestamp": "2026-10-19T10:00:00Z",
        "contractVersion": "2026-03-10.v2",
        "bdvmModelVersion": "bdvm-1.0.0",
        "bdvmParamSetId": "params_v1:abcdef123456",
        "bdvmSnapshotAsOf": SNAPSHOT_AS_OF,
        "challengerVersion": MODEL_VERSION,
        "challengerParamSetId": str(p["paramSetId"]),
    }


def params_with(**overrides: Any) -> dict[str, Any]:
    """A params copy with nested overrides; paramSetId is kept in step."""
    from src.league_valuation.contracts import param_set_id_for

    p = copy.deepcopy(PARAMS)
    for dotted, value in overrides.items():
        node = p
        parts = dotted.split("__")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    p["paramSetId"] = param_set_id_for(p)
    return p


def row(
    pid: str,
    pos: str,
    value: int | None,
    rank: int | None,
    *,
    name: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "playerId": pid,
        "canonicalName": name or f"Player {pid}",
        "displayName": name or f"Player {pid}",
        "position": pos,
        "assetClass": "idp" if pos in IDP else "offense",
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
        "canonicalTierId": 1,
        "confidenceBucket": "high",
    }
    out.update(extra)
    return out


def bdvm_entry(
    pid: str,
    pos: str,
    dv: float | None,
    vorg: float | None,
    *,
    name: str | None = None,
    sources: Iterable[str] = ("clay_espn", "idpshow", "manual"),
    stale: Iterable[str] = (),
    proxy: bool = False,
    strategies: dict[str, float] | None = None,
) -> dict[str, Any]:
    fundamental: dict[str, float] = dict(strategies or {})
    if dv is not None:
        fundamental["balanced"] = dv
    raw: dict[str, Any] = {"fpg": 10.0, "replacement": 8.0}
    if vorg is not None:
        raw["vorg"] = vorg
    return {
        "playerId": pid,
        "name": name or f"Player {pid}",
        "position": pos,
        "group": pos,
        "raw": raw,
        "fundamental": fundamental,
        "tradeValue": {"balanced": 5000.0},
        "projection": {
            "sourceCount": len(list(sources)),
            "sources": list(sources),
            "anyProxy": proxy,
            "staleSources": list(stale),
        },
        # The market layer is present in real payloads and must never be read.
        "market": {"marketValue": 1.0, "gap": 99999.0},
    }


def payload(
    entries: list[dict[str, Any]],
    *,
    as_of: str | None = SNAPSHOT_AS_OF,
    unpriced: list[dict[str, Any]] | None = None,
    status: str = "ok",
    league_key: str = LEAGUE_KEY,
) -> dict[str, Any]:
    snap: dict[str, Any] = {"asOf": as_of, "asOfUnknown": as_of is None}
    if as_of is not None:
        snap["asOfSource"] = "snapshot"
    return {
        "status": status,
        "meta": {
            "modelVersion": "bdvm-1.0.0",
            "paramSetId": "params_v1:abcdef123456",
            "leagueKey": league_key,
            "asOf": "2026-10-19",
            "projectionSnapshot": snap,
        },
        "players": entries,
        "unpriced": unpriced or [],
    }


def board(seed: int = 7, *, per_offense: int = 12, per_idp: int = 40) -> list[dict[str, Any]]:
    """A deterministic board: distinct values, contiguous ranks across all rows."""
    rng = random.Random(seed)
    specs: list[tuple[str, str]] = []
    n = 0
    for pos in OFFENSE:
        for _ in range(per_offense):
            n += 1
            specs.append((f"{1000 + n}", pos))
    for pos in IDP:
        for _ in range(per_idp):
            n += 1
            specs.append((f"{1000 + n}", pos))
    values = rng.sample(range(150, 9900), len(specs))
    values.sort(reverse=True)
    rng.shuffle(specs)
    return [row(pid, pos, v, i + 1) for i, ((pid, pos), v) in enumerate(zip(specs, values))]


def aligned_payload(rows: list[dict[str, Any]], *, shift: float = 0.0) -> dict[str, Any]:
    """BDVM utility in EXACTLY the market order (per scope), optionally shifted."""
    entries = []
    for r in rows:
        v = float(r["rankDerivedValue"])
        entries.append(
            bdvm_entry(r["playerId"], r["position"], v / 10.0 + shift, v / 1000.0 + shift)
        )
    return payload(entries)


def shuffled_payload(rows: list[dict[str, Any]], seed: int = 3) -> dict[str, Any]:
    rng = random.Random(seed)
    entries = []
    for r in rows:
        dv = rng.uniform(0, 1000)
        entries.append(bdvm_entry(r["playerId"], r["position"], dv, rng.uniform(-5, 10)))
    return payload(entries)


def run(rows, bdvm, *, params=None, anchor_year=None):
    p = params or PARAMS
    ev = utility_evidence_from_bdvm(bdvm, now=NOW, params=p)
    return compute_fair_values(rows, ev, params=p, pins=pins(p), anchor_year=anchor_year)
