#!/usr/bin/env python3
"""IDP evidence independence -- reproducible, read-only, no network.

Builds a contract from committed inputs and prints the measurements of
``src/sources/idp_independence.py`` as JSON.  Changes no vote, weight, family,
cap, registry or flag; the optional cap scenario goes through the existing
override pipeline (``build_rankings_delta_payload`` with ``source_overrides``)
in memory and writes nothing.

    python scripts/idp_evidence_independence.py --board pinned
    python scripts/idp_evidence_independence.py --board latest --cap-scenario

``--board pinned`` is the hermetic committed fixture (tests/fixtures/pinned_board);
``--board latest`` builds ``exports/latest/dynasty_data_*.json`` against the
committed ``CSVs/site_raw``.  Record:
``docs/sources/IDP_EVIDENCE_INDEPENDENCE_2026-11-22.md``.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.sources import idp_independence as ii  # noqa: E402
from src.sources.source_census import load_lineage, provider_of  # noqa: E402

GATE_PATH = REPO / "config" / "confidence" / "gate_v1.json"


def _load_board(which: str):
    from src.api.data_contract import build_api_data_contract

    if which == "pinned":
        from tests.archive_fixtures import build_pinned_contract, pinned_board_payload

        payload, label = pinned_board_payload()
        return payload, build_pinned_contract(copy.deepcopy(payload)), label
    paths = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
    if not paths:
        raise SystemExit("exports/latest has no dynasty_data_*.json")
    payload = json.loads(paths[-1].read_text(encoding="utf-8"))
    return payload, build_api_data_contract(copy.deepcopy(payload)), paths[-1].name


def measure(contract: dict, family_of) -> dict:
    rows = ii.idp_rows(contract)
    priced = [r for r in rows if r.get("rankDerivedValue")]
    keys = ii.voting_keys(priced)
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))["parameters"]
    lineage = load_lineage()
    bridges = contract.get("crossPositionBridges") or {}
    ladder = bridges.get("ladder") or {}
    pairs = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            pairs[f"{a}|{b}"] = ii.pair_lineage(lineage, provider_of, a, b)
    anchor = (ladder.get("contributors") or [None])[0]
    anchor_key = {"idpTradeCalc": "idpTradeCalc"}.get(anchor or "", None)
    translated = [k for k in keys if ii.translation_profile(priced, k)["translatedRows"]]
    return {
        "idpRows": len(rows),
        "pricedIdpRows": len(priced),
        "votingSources": keys,
        "families": {k: family_of(k) for k in keys},
        "providers": {k: provider_of(k) for k in keys},
        "weightShare": ii.weight_shares(priced, keys),
        "spearman": {
            s: ii.pairwise_spearman(priced, keys, s)
            for s in ("rawRank", "effectiveRank", "voteValue")
        },
        "identicalRawValues": {
            f"{a}|{b}": ii.identical_value_share(priced, a, b)
            for i, a in enumerate(keys)
            for b in keys[i + 1 :]
        },
        "translation": {k: ii.translation_profile(priced, k) for k in keys},
        "ladder": {
            "contributors": ladder.get("contributors"),
            "multiBridgeLadderEnabled": bridges.get("multiBridgeLadderEnabled"),
            "perBridge": ladder.get("perBridge"),
        },
        "ladderCoupling": {
            k: ii.ladder_coupling(priced, k, anchor_key)
            for k in translated
            if anchor_key and k != anchor_key
        },
        "pairLineage": pairs,
        "confidence": ii.confidence_profile(
            priced,
            independence_high_families=int(gate["INDEPENDENCE_HIGH_FAMILIES"]["value"]),
        ),
        "authorityReasons": ii.withheld_reasons(priced),
    }


def cap_scenario(payload: dict, base_contract: dict, which: str) -> dict:
    """Proxy for a lineage-aware cap: halve the weights of idpTradeCalc and
    idpShowCombined (their sum then equals one provider's authority on rows
    where both vote).  Source overrides are board-wide, so offense and pick
    rows move too; only the IDP-row diff is the proposal's measure and the
    spill-over is reported."""
    from src.api import data_contract as dc

    ov = {"idpTradeCalc": {"weight": 0.5}, "idpShowCombined": {"weight": 0.5}}
    if which == "pinned":
        from tests.archive_fixtures import pinned_build_environment

        with pinned_build_environment() as root:
            alt = dc.build_api_data_contract(
                copy.deepcopy(payload), csv_root=root, source_overrides=ov
            )
    else:
        alt = dc.build_api_data_contract(copy.deepcopy(payload), source_overrides=ov)
    base_idp = ii.idp_rows(base_contract)
    alt_idp = ii.idp_rows(alt)
    spill = [r for r in base_contract["playersArray"] if r.get("assetClass") not in ("idp",)]
    alt_non = [r for r in alt["playersArray"] if r.get("assetClass") not in ("idp",)]
    return {
        "scenario": "idpTradeCalc and idpShowCombined weight x0.5 (proxy for a family cap)",
        "idpRows": ii.board_diff(base_idp, alt_idp),
        "nonIdpSpillover": ii.board_diff(spill, alt_non),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", choices=("pinned", "latest"), default="pinned")
    ap.add_argument("--cap-scenario", action="store_true")
    args = ap.parse_args(argv)
    from src.api.data_contract import correlation_group_for

    payload, contract, label = _load_board(args.board)
    out = {"board": label, "measurements": measure(contract, correlation_group_for)}
    if args.cap_scenario:
        out["capScenario"] = cap_scenario(payload, contract, args.board)
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
