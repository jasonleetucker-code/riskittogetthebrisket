#!/usr/bin/env python3
"""Pinned value replay with counterfactual rebuilds (``src/api/value_replay.py``).

Builds the canonical board locally from a raw payload (default: the newest
``exports/latest/dynasty_data_*.json``), explains named assets stage by stage,
and rebuilds the whole board under single-change counterfactuals.

Usage:
    python scripts/value_replay.py --asset "Jalen Coker" --contrast \\
        --json out.json --markdown out.md
    python scripts/value_replay.py --asset "Jalen Coker" --counterfactual hampel_off

Exit codes: 0 ok; 2 an asset was not found on the board (reported, never guessed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import value_replay as vr  # noqa: E402


def _latest_payload() -> Path:
    candidates = sorted((REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
    if not candidates:
        raise SystemExit("no exports/latest/dynasty_data_*.json payload")
    return candidates[-1]


def contrast_set(contract: dict, *, per_group: int = 3) -> list[str]:
    """Data-chosen contrasts, so the replay never studies one player alone.

    * offense rows the board prices furthest BELOW and ABOVE the KTC market
      benchmark (``marketGapValueRatio``), among the top 300;
    * the top-ranked IDP rows and IDP rows the outlier filter touched;
    * the top-ranked rookies;
    * current-year slot picks and a future generic pick.
    Disagreement with the market is selected, never presumed wrong.
    """
    rows = [r for r in contract.get("playersArray") or [] if r.get("displayName")]
    ranked = [r for r in rows if r.get("canonicalConsensusRank")]
    offense = [
        r
        for r in ranked
        if r.get("assetClass") == "offense"
        and r["canonicalConsensusRank"] <= 300
        and isinstance(r.get("marketGapValueRatio"), (int, float))
    ]
    below = sorted(offense, key=lambda r: r["marketGapValueRatio"])[:per_group]
    above = sorted(offense, key=lambda r: -r["marketGapValueRatio"])[:per_group]
    idp = sorted(
        (r for r in ranked if r.get("assetClass") == "idp"),
        key=lambda r: r["canonicalConsensusRank"],
    )
    idp_touched = [r for r in idp if r.get("droppedSources")]
    rookies = sorted(
        (r for r in ranked if r.get("rookie") and r.get("assetClass") != "pick"),
        key=lambda r: r["canonicalConsensusRank"],
    )
    picks = [r for r in rows if r.get("assetClass") == "pick"]
    slot = sorted(
        (r for r in picks if "." in r["displayName"]),
        key=lambda r: -(r.get("rankDerivedValue") or 0),
    )
    generic = [r for r in picks if r["displayName"].endswith("Round 1")]
    chosen = below + above + idp[:2] + idp_touched[:1] + rookies[:2] + slot[:2] + generic[:1]
    seen, out = set(), []
    for row in chosen:
        if row["displayName"] not in seen:
            seen.add(row["displayName"])
            out.append(row["displayName"])
    return out


def markdown(result: dict) -> str:
    pins = result["pins"]
    lines = [
        "# Value replay",
        "",
        f"- Code revision: `{pins['codeRevision']}` (source tree dirty: {pins['workingTreeDirty']})",
        f"- Payload: `{pins['payload']['path']}` sha256 `{pins['payload']['sha256'][:16]}…`, "
        f"scrape `{pins['payload']['scrapeTimestamp']}`",
        f"- Flags: {pins['flags']}; outlier filter {pins['hampel']}; "
        f"single-source retention {pins['singleSourceRetention']}",
        f"- {len(pins['sourceCsvs'])} source CSVs and {len(pins['freshnessState'])} freshness-state "
        "files hashed in the JSON.",
        "",
        "> " + result["interpretation"],
        "",
    ]
    for name, entry in result["assets"].items():
        base = entry["baseline"]
        if base is None:
            lines += [f"## {name}", "", "NOT ON BOARD — not guessed.", ""]
            continue
        lines += [
            f"## {name} ({base['position']}, {base['assetClass']})",
            "",
            f"Value **{base['rankDerivedValue']}**, overall rank {base['canonicalConsensusRank']}, "
            f"position rank {base['positionRank']}, confidence {base['confidenceBucket']}. "
            f"Outlier-dropped: {base['droppedSources'] or 'none'}. "
            f"Blend check: {base['blendCheck']['status']}.",
            "",
            "| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for key, s in sorted(
            base["sources"].items(), key=lambda kv: -(kv[1].get("valueContribution") or 0)
        ):
            excluded = "outlier" if s.get("hampelDropped") else (s.get("excludedReason") or "")
            lines.append(
                f"| {key} | {s.get('nativeValue')} | {s.get('sourceRank')} | {s.get('valueContribution')} | "
                f"{s.get('valueContributionPath')} | {s.get('appliedWeight')} | {s.get('freshness')} | "
                f"{s.get('familyAdjustment')} | {excluded} |"
            )
        moved = {k: v for k, v in entry["counterfactuals"].items() if v.get("delta")}
        lines += ["", "Counterfactual sensitivities (value delta, rank after):", ""]
        if moved:
            for k, v in sorted(moved.items(), key=lambda kv: -abs(kv[1]["delta"])):
                lines.append(f"- `{k}`: {v['delta']:+} → {v['value']} (rank {v['rank']})")
        else:
            lines.append("- none of the counterfactuals moved this asset")
        lines.append("")
    lines += [
        "## Whole-board counterfactual effects",
        "",
        "| counterfactual | kind | rows changed | top-200 membership changes |",
        "|---|---|---|---|",
    ]
    for name, board in result["counterfactualBoard"].items():
        lines.append(
            f"| `{name}` | {board['kind']} | {board['rowsChanged']} | {board['top200MembershipChanges']} |"
        )
    census = result["board"]["outlierCensus"]
    lines += ["", f"Outlier-filter drops by source: {census['dropsBySource']}.", ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--payload", type=Path, default=None)
    parser.add_argument("--asset", action="append", default=[], help="Exact board displayName.")
    parser.add_argument("--contrast", action="store_true", help="Add the data-chosen contrast set.")
    parser.add_argument(
        "--counterfactual", action="append", default=None, help="Limit to these (default all)."
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)

    payload = args.payload or _latest_payload()
    assets = list(args.asset)
    if args.contrast:
        base = vr.build(json.loads(payload.read_text(encoding="utf-8")))
        assets += [a for a in contrast_set(base) if a not in assets]
    if not assets:
        parser.error("name at least one --asset or pass --contrast")
    result = vr.replay(
        payload,
        assets,
        counterfactuals=args.counterfactual,
        progress=lambda name: print(f"  rebuilding: {name}", file=sys.stderr),
    )
    if args.json:
        args.json.write_text(
            json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    text = markdown(result)
    if args.markdown:
        args.markdown.write_text(text, encoding="utf-8")
    else:
        print(text)
    missing = [a for a, e in result["assets"].items() if e["baseline"] is None]
    if missing:
        print(f"NOT ON BOARD: {missing}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
