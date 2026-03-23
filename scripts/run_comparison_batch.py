#!/usr/bin/env python3
"""Run a large-batch comparison between canonical pipeline values and legacy scraper values.

Produces both machine-readable JSON and founder-readable Markdown reports.

Usage:
    python scripts/run_comparison_batch.py [--legacy PATH] [--canonical PATH]

If paths are not provided, finds the latest available files automatically.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# Ensure repo root is on sys.path for shared imports
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._shared import _repo_root, _latest as _latest_file, _normalize_name


def load_legacy(path: Path) -> dict[str, dict]:
    """Load legacy dynasty_data JSON and extract player composite values."""
    data = json.loads(path.read_text())
    players = data.get("players", {})
    out: dict[str, dict] = {}
    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        val = (
            pdata.get("_finalAdjusted")
            or pdata.get("_leagueAdjusted")
            or pdata.get("_composite")
        )
        if val is None:
            continue
        val = int(val)
        if val <= 0:
            continue
        pos = str(pdata.get("_lamBucket") or pdata.get("POS") or pdata.get("pos") or "").upper()
        out[name] = {"value": val, "pos": pos, "name": name}
    return out


def load_canonical(path: Path) -> dict[str, dict]:
    """Load canonical snapshot and extract per-asset values.

    Uses scarcity_adjusted_value when available (from league context engine),
    falling back to raw blended_value.
    """
    data = json.loads(path.read_text())
    assets = data.get("assets", [])
    out: dict[str, dict] = {}
    for asset in assets:
        name = str(asset.get("display_name", asset.get("asset_key", ""))).strip()
        if not name:
            continue
        # Prefer calibrated > scarcity-adjusted > raw blended
        value = (
            asset.get("calibrated_value")
            or asset.get("scarcity_adjusted_value")
            or asset.get("blended_value")
        )
        if value is None:
            continue
        universe = str(asset.get("universe", ""))
        source_count = len(asset.get("source_values", {}))
        int_value = int(value)
        # On name collision (same player in rookie + vet universes), keep
        # the entry with the higher final value.  This mirrors the legacy
        # composite which keeps the best available value per player.
        existing = out.get(name)
        if existing is not None and existing["value"] >= int_value:
            continue
        out[name] = {
            "value": int_value,
            "raw_blended": int(asset.get("blended_value", 0)),
            "name": name,
            "universe": universe,
            "source_count": source_count,
            "source_values": asset.get("source_values", {}),
        }
    return out


def match_players(
    canonical: dict[str, dict], legacy: dict[str, dict]
) -> tuple[list[dict], list[str], list[str]]:
    """Match players between canonical and legacy by name, returning matched deltas."""
    # Build normalized lookup for legacy
    legacy_norm: dict[str, str] = {}
    for name in legacy:
        legacy_norm[_normalize_name(name)] = name

    matched: list[dict] = []
    canonical_only: list[str] = []

    for c_name, c_data in canonical.items():
        c_norm = _normalize_name(c_name)
        l_name = legacy_norm.get(c_norm)
        if l_name is None:
            # Try exact match
            if c_name in legacy:
                l_name = c_name
            else:
                canonical_only.append(c_name)
                continue

        l_data = legacy[l_name]
        delta = c_data["value"] - l_data["value"]
        pct = round(delta / l_data["value"] * 100, 1) if l_data["value"] else 0

        matched.append({
            "name": c_name,
            "legacy_name": l_name,
            "canonical_value": c_data["value"],
            "legacy_value": l_data["value"],
            "delta": delta,
            "abs_delta": abs(delta),
            "pct_delta": pct,
            "universe": c_data.get("universe", ""),
            "source_count": c_data.get("source_count", 0),
            "legacy_pos": l_data.get("pos", ""),
        })

    # Legacy-only
    matched_legacy_names = {m["legacy_name"] for m in matched}
    legacy_only = [n for n in legacy if n not in matched_legacy_names]

    return matched, canonical_only, legacy_only


def compute_stats(matched: list[dict]) -> dict:
    """Compute aggregate statistics from matched deltas."""
    if not matched:
        return {"count": 0}

    abs_deltas = sorted([m["abs_delta"] for m in matched])
    deltas = [m["delta"] for m in matched]
    n = len(abs_deltas)

    # Delta distribution buckets
    buckets = {"under100": 0, "100to300": 0, "300to600": 0, "600to1200": 0, "over1200": 0}
    for ad in abs_deltas:
        if ad < 100:
            buckets["under100"] += 1
        elif ad < 300:
            buckets["100to300"] += 1
        elif ad < 600:
            buckets["300to600"] += 1
        elif ad < 1200:
            buckets["600to1200"] += 1
        else:
            buckets["over1200"] += 1

    # Rank correlation: top-50 overlap
    by_canonical = sorted(matched, key=lambda m: -m["canonical_value"])
    by_legacy = sorted(matched, key=lambda m: -m["legacy_value"])
    c_top50 = {m["name"] for m in by_canonical[:50]}
    l_top50 = {m["name"] for m in by_legacy[:50]}
    top50_overlap = len(c_top50 & l_top50)

    c_top100 = {m["name"] for m in by_canonical[:100]}
    l_top100 = {m["name"] for m in by_legacy[:100]}
    top100_overlap = len(c_top100 & l_top100)

    # Verdict agreement: same "tier" of value
    def tier(v):
        if v >= 7000:
            return "elite"
        if v >= 5000:
            return "star"
        if v >= 3000:
            return "starter"
        if v >= 1500:
            return "bench"
        return "depth"

    verdict_agree = sum(1 for m in matched if tier(m["canonical_value"]) == tier(m["legacy_value"]))

    # By position
    by_pos: dict[str, list[int]] = defaultdict(list)
    for m in matched:
        pos = m.get("legacy_pos", "")
        if pos:
            by_pos[pos].append(m["abs_delta"])

    pos_stats = {}
    for pos, deltas_list in sorted(by_pos.items()):
        pos_stats[pos] = {
            "count": len(deltas_list),
            "avg_abs_delta": int(round(sum(deltas_list) / len(deltas_list))),
        }

    # By universe
    by_univ: dict[str, list[int]] = defaultdict(list)
    for m in matched:
        by_univ[m.get("universe", "unknown")].append(m["abs_delta"])
    univ_stats = {}
    for u, dl in sorted(by_univ.items()):
        univ_stats[u] = {
            "count": len(dl),
            "avg_abs_delta": int(round(sum(dl) / len(dl))),
        }

    # By source count
    multi_source = [m for m in matched if m.get("source_count", 0) > 1]
    single_source = [m for m in matched if m.get("source_count", 0) == 1]

    return {
        "count": n,
        "avg_abs_delta": int(round(sum(abs_deltas) / n)),
        "median_abs_delta": abs_deltas[n // 2],
        "p90_abs_delta": abs_deltas[int(n * 0.9)],
        "max_abs_delta": abs_deltas[-1],
        "avg_delta": int(round(sum(deltas) / n)),
        "delta_distribution": buckets,
        "top50_overlap": top50_overlap,
        "top50_overlap_pct": round(top50_overlap / 50 * 100),
        "top100_overlap": top100_overlap,
        "top100_overlap_pct": round(top100_overlap / min(100, n) * 100) if n >= 100 else None,
        "verdict_tier_agreement": verdict_agree,
        "verdict_tier_agreement_pct": round(verdict_agree / n * 100, 1),
        "by_position": pos_stats,
        "by_universe": univ_stats,
        "multi_source_avg_delta": int(round(sum(m["abs_delta"] for m in multi_source) / len(multi_source))) if multi_source else None,
        "single_source_avg_delta": int(round(sum(m["abs_delta"] for m in single_source) / len(single_source))) if single_source else None,
        "multi_source_count": len(multi_source),
        "single_source_count": len(single_source),
    }


def _is_pick_name(name: str) -> bool:
    """Check if a player name looks like a draft pick."""
    import re
    n = name.lower().strip()
    patterns = [
        r"^\d{4}\s+(pick|early|mid|late)",
        r"^(early|mid|late)\s+\d",
        r"^\d{4}\s+\d+\.\d+",
        r"pick\s+\d+\.\d+",
        r"^\d{4}\s+\d+(st|nd|rd|th)$",
    ]
    return any(re.search(p, n) for p in patterns)


def _compute_group_stats(subset: list[dict]) -> dict:
    """Compute overlap/tier/delta stats for a filtered subset of matched players."""
    if len(subset) < 5:
        return {"count": len(subset), "too_small": True}

    abs_deltas = sorted([m["abs_delta"] for m in subset])
    n = len(abs_deltas)

    by_c = sorted(subset, key=lambda m: -m["canonical_value"])
    by_l = sorted(subset, key=lambda m: -m["legacy_value"])

    top_n = min(50, n)
    c_top = {m["name"] for m in by_c[:top_n]}
    l_top = {m["name"] for m in by_l[:top_n]}
    top_overlap = len(c_top & l_top)

    # Also compute top-100 if enough data
    top100_overlap = None
    top100_pct = None
    if n >= 100:
        c_top100 = {m["name"] for m in by_c[:100]}
        l_top100 = {m["name"] for m in by_l[:100]}
        top100_overlap = len(c_top100 & l_top100)
        top100_pct = round(top100_overlap / 100 * 100)

    def tier(v):
        if v >= 7000: return "elite"
        if v >= 5000: return "star"
        if v >= 3000: return "starter"
        if v >= 1500: return "bench"
        return "depth"

    tier_agree = sum(1 for m in subset if tier(m["canonical_value"]) == tier(m["legacy_value"]))

    return {
        "count": n,
        "avg_abs_delta": int(round(sum(abs_deltas) / n)),
        "median_abs_delta": abs_deltas[n // 2],
        "top_n_used": top_n,
        "top_n_overlap": top_overlap,
        "top_n_overlap_pct": round(top_overlap / top_n * 100),
        "top100_overlap": top100_overlap,
        "top100_overlap_pct": top100_pct,
        "tier_agreement": tier_agree,
        "tier_agreement_pct": round(tier_agree / n * 100, 1),
    }


def compute_universe_stats(matched: list[dict]) -> dict[str, dict]:
    """Compute per-universe and player-only comparison stats.

    Returns stats for each universe plus:
    - offense_combined: offense_vet + offense_rookie
    - idp_combined: idp_vet + idp_rookie
    - players_only: all matched players excluding picks (most decision-useful)
    - offense_players_only: offense players excluding picks
    """
    # Define universe groups
    groups: dict[str, list[str]] = {
        "offense_vet": ["offense_vet"],
        "offense_rookie": ["offense_rookie"],
        "idp_vet": ["idp_vet"],
        "idp_rookie": ["idp_rookie"],
        "offense_combined": ["offense_vet", "offense_rookie"],
        "idp_combined": ["idp_vet", "idp_rookie"],
    }

    result: dict[str, dict] = {}

    for group_name, universes in groups.items():
        subset = [m for m in matched if m.get("universe") in universes]
        if len(subset) < 10:
            continue
        result[group_name] = _compute_group_stats(subset)

    # Player-only views (exclude picks from matching — most decision-useful)
    all_players = [m for m in matched if not _is_pick_name(m["name"]) and m.get("legacy_pos", "") != "PICK"]
    if len(all_players) >= 10:
        result["players_only"] = _compute_group_stats(all_players)

    offense_players = [m for m in all_players if m.get("universe") in ("offense_vet", "offense_rookie")]
    if len(offense_players) >= 10:
        result["offense_players_only"] = _compute_group_stats(offense_players)

    return result


def generate_markdown(
    stats: dict,
    matched: list[dict],
    canonical_only: list[str],
    legacy_only: list[str],
    canonical_path: str,
    legacy_path: str,
    universe_stats: dict[str, dict] | None = None,
) -> str:
    """Generate a founder-readable markdown report."""
    lines = [
        "# Canonical vs Legacy Comparison Report",
        "",
        f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"- **Canonical snapshot**: `{canonical_path}`",
        f"- **Legacy data**: `{legacy_path}`",
        "",
        "---",
        "",
        "## Bottom Line",
        "",
    ]

    n = stats.get("count", 0)
    avg = stats.get("avg_abs_delta", 0)
    t50 = stats.get("top50_overlap_pct", 0)
    tier_pct = stats.get("verdict_tier_agreement_pct", 0)

    if t50 >= 80 and tier_pct >= 75:
        lines.append(f"The canonical pipeline **broadly agrees** with legacy values. "
                      f"Top-50 overlap is {t50}%, and {tier_pct}% of matched players fall in the same value tier.")
    elif t50 >= 60:
        lines.append(f"The canonical pipeline **partially agrees** with legacy values. "
                      f"Top-50 overlap is {t50}%, tier agreement is {tier_pct}%. "
                      "Significant differences exist, especially in mid-tier players.")
    else:
        lines.append(f"The canonical pipeline **diverges significantly** from legacy values. "
                      f"Top-50 overlap is only {t50}%, tier agreement is {tier_pct}%. "
                      "This is expected when only 2 of 11+ sources are integrated.")

    lines.extend([
        "",
        "---",
        "",
        "## Key Numbers",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Players matched | {n} |",
        f"| Canonical-only players | {len(canonical_only)} |",
        f"| Legacy-only players | {len(legacy_only)} |",
        f"| Average absolute delta | {avg} (out of 9999) |",
        f"| Median absolute delta | {stats.get('median_abs_delta', 'n/a')} |",
        f"| 90th percentile delta | {stats.get('p90_abs_delta', 'n/a')} |",
        f"| Max delta | {stats.get('max_abs_delta', 'n/a')} |",
        f"| Top-50 player overlap | {stats.get('top50_overlap', 0)}/50 ({t50}%) |",
    ])
    if stats.get("top100_overlap_pct") is not None:
        lines.append(f"| Top-100 player overlap | {stats.get('top100_overlap', 0)}/100 ({stats['top100_overlap_pct']}%) |")
    lines.append(f"| Value tier agreement | {tier_pct}% |")

    if stats.get("multi_source_avg_delta") is not None:
        lines.extend([
            "",
            "### Multi-source vs Single-source Quality",
            "",
            f"| Source Count | Players | Avg Delta |",
            f"|-------------|---------|-----------|",
            f"| Multi-source (2+) | {stats['multi_source_count']} | {stats['multi_source_avg_delta']} |",
            f"| Single-source (1) | {stats['single_source_count']} | {stats['single_source_avg_delta']} |",
        ])

    # Delta distribution
    dist = stats.get("delta_distribution", {})
    lines.extend([
        "",
        "### Delta Distribution",
        "",
        "| Range | Count | Interpretation |",
        "|-------|-------|----------------|",
        f"| < 100 | {dist.get('under100', 0)} | Very close agreement |",
        f"| 100-300 | {dist.get('100to300', 0)} | Minor difference |",
        f"| 300-600 | {dist.get('300to600', 0)} | Moderate difference |",
        f"| 600-1200 | {dist.get('600to1200', 0)} | Significant difference |",
        f"| > 1200 | {dist.get('over1200', 0)} | Major divergence |",
    ])

    # By position
    if stats.get("by_position"):
        lines.extend(["", "### By Position", "", "| Position | Players | Avg Delta |", "|----------|---------|-----------|"])
        for pos, ps in sorted(stats["by_position"].items(), key=lambda x: -x[1]["avg_abs_delta"]):
            lines.append(f"| {pos} | {ps['count']} | {ps['avg_abs_delta']} |")

    # Top risers/fallers
    by_delta = sorted(matched, key=lambda m: m["delta"], reverse=True)
    risers = by_delta[:15]
    fallers = by_delta[-15:]

    lines.extend([
        "",
        "---",
        "",
        "## Top 15 Risers (canonical values HIGHER than legacy)",
        "",
        "| Player | Canonical | Legacy | Delta | % | Sources |",
        "|--------|-----------|--------|-------|---|---------|",
    ])
    for m in risers:
        if m["delta"] > 0:
            lines.append(f"| {m['name']} | {m['canonical_value']} | {m['legacy_value']} | +{m['delta']} | +{m['pct_delta']}% | {m['source_count']} |")

    lines.extend([
        "",
        "## Top 15 Fallers (canonical values LOWER than legacy)",
        "",
        "| Player | Canonical | Legacy | Delta | % | Sources |",
        "|--------|-----------|--------|-------|---|---------|",
    ])
    for m in reversed(fallers):
        if m["delta"] < 0:
            lines.append(f"| {m['name']} | {m['canonical_value']} | {m['legacy_value']} | {m['delta']} | {m['pct_delta']}% | {m['source_count']} |")

    # Biggest outliers
    outliers = sorted(matched, key=lambda m: -m["abs_delta"])[:20]
    lines.extend([
        "",
        "## Top 20 Biggest Mismatches (by absolute delta)",
        "",
        "| Player | Canonical | Legacy | Delta | Universe | Sources |",
        "|--------|-----------|--------|-------|----------|---------|",
    ])
    for m in outliers:
        sign = "+" if m["delta"] > 0 else ""
        lines.append(f"| {m['name']} | {m['canonical_value']} | {m['legacy_value']} | {sign}{m['delta']} | {m['universe']} | {m['source_count']} |")

    # Universe-aware comparison
    if universe_stats:
        lines.extend([
            "",
            "---",
            "",
            "## Universe-Aware Comparison",
            "",
            "Compares like-with-like by filtering to specific universes.",
            "",
            "| Universe | Players | Avg Delta | Top-N Overlap | Tier Agreement |",
            "|----------|---------|-----------|---------------|----------------|",
        ])
        # Order: player-only first (most decision-useful), then by universe
        display_order = ["offense_players_only", "players_only",
                         "offense_combined", "offense_vet", "offense_rookie",
                         "idp_combined", "idp_vet", "idp_rookie"]
        for u in display_order:
            if u not in universe_stats:
                continue
            us = universe_stats[u]
            label = u.replace("_", " ").title()
            lines.append(
                f"| **{label}** | {us['count']} | {us['avg_abs_delta']} | "
                f"{us['top_n_overlap']}/{us['top_n_used']} ({us['top_n_overlap_pct']}%) | "
                f"{us['tier_agreement_pct']}% |"
            )
        lines.extend([
            "",
            "_**Offense Players Only** is the most decision-useful view — it measures "
            "how well the canonical system ranks actual tradeable players, excluding picks. "
            "IDP metrics are secondary._",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## What This Means",
        "",
        "The canonical pipeline currently runs **2 sources** (DLF + FantasyCalc) compared to the legacy scraper's **11+ sources**. ",
        "Divergence is expected and does not indicate a problem. The canonical pipeline is designed to converge with legacy as more sources are added.",
        "",
        "**Why values differ:**",
        "- DLF is rank-based (expert curated); many legacy sources are market/crowd-based",
        "- Only offense_vet has 2-source blending; IDP and rookies are DLF-only",
        "- Legacy applies Z-score normalization; canonical uses percentile power curve",
        "- Source weights are all 1.0 (untuned) in canonical",
        "",
        f"_Report covers {n} matched players across {len(stats.get('by_universe', {}))} universes._",
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run canonical vs legacy comparison batch")
    parser.add_argument("--legacy", help="Path to legacy dynasty_data JSON")
    parser.add_argument("--canonical", help="Path to canonical snapshot JSON")
    parser.add_argument("--output-dir", default="data/comparison", help="Output directory")
    args = parser.parse_args()

    repo = _repo_root()

    # Find files
    if args.legacy:
        legacy_path = Path(args.legacy)
    else:
        legacy_path = _latest_file(repo / "data", "legacy_data_*.json")
        if legacy_path is None:
            legacy_path = _latest_file(repo / "data", "dynasty_data_*.json")
    if legacy_path is None or not legacy_path.exists():
        print("[comparison] No legacy data file found. Extract from exports zip first.")
        return 1

    if args.canonical:
        canonical_path = Path(args.canonical)
    else:
        canonical_path = _latest_file(repo / "data" / "canonical", "canonical_snapshot_*.json")
    if canonical_path is None or not canonical_path.exists():
        print("[comparison] No canonical snapshot found. Run canonical_build first.")
        return 1

    print(f"[comparison] Legacy: {legacy_path.name}")
    print(f"[comparison] Canonical: {canonical_path.name}")

    # Load data
    legacy = load_legacy(legacy_path)
    canonical = load_canonical(canonical_path)
    print(f"[comparison] Loaded {len(legacy)} legacy players, {len(canonical)} canonical assets")

    # Match and compute
    matched, canonical_only, legacy_only = match_players(canonical, legacy)
    print(f"[comparison] Matched: {len(matched)}, Canonical-only: {len(canonical_only)}, Legacy-only: {len(legacy_only)}")

    stats = compute_stats(matched)
    universe_stats = compute_universe_stats(matched)

    # Output
    out_dir = repo / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Machine-readable JSON
    json_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "legacy_file": legacy_path.name,
        "canonical_file": canonical_path.name,
        "legacy_player_count": len(legacy),
        "canonical_asset_count": len(canonical),
        "matched_count": len(matched),
        "canonical_only_count": len(canonical_only),
        "legacy_only_count": len(legacy_only),
        "stats": stats,
        "universe_stats": universe_stats,
        "top_risers": sorted(matched, key=lambda m: m["delta"], reverse=True)[:20],
        "top_fallers": sorted(matched, key=lambda m: m["delta"])[:20],
        "biggest_mismatches": sorted(matched, key=lambda m: -m["abs_delta"])[:30],
        "canonical_only_sample": sorted(canonical_only)[:30],
        "legacy_only_sample": sorted(legacy_only)[:30],
    }
    json_path = out_dir / f"comparison_batch_{ts}.json"
    json_path.write_text(json.dumps(json_report, indent=2) + "\n")
    print(f"[comparison] JSON report: {json_path}")

    # Founder-readable markdown
    md = generate_markdown(
        stats, matched, canonical_only, legacy_only,
        canonical_path.name, legacy_path.name,
        universe_stats=universe_stats,
    )
    md_path = out_dir / f"comparison_report_{ts}.md"
    md_path.write_text(md)
    print(f"[comparison] Markdown report: {md_path}")

    # Print summary to stdout
    print(f"\n--- COMPARISON SUMMARY ---")
    print(f"Matched players: {stats['count']}")
    print(f"Avg |delta|: {stats.get('avg_abs_delta', 'n/a')}")
    print(f"Top-50 overlap: {stats.get('top50_overlap', 0)}/50 ({stats.get('top50_overlap_pct', 0)}%)")
    print(f"Tier agreement: {stats.get('verdict_tier_agreement_pct', 0)}%")
    if stats.get("multi_source_avg_delta") is not None:
        print(f"Multi-source avg delta: {stats['multi_source_avg_delta']} ({stats['multi_source_count']} players)")
        print(f"Single-source avg delta: {stats['single_source_avg_delta']} ({stats['single_source_count']} players)")

    if universe_stats:
        print(f"\n--- UNIVERSE BREAKDOWN ---")
        for u in ["offense_players_only", "players_only", "offense_combined", "idp_combined"]:
            if u in universe_stats:
                us = universe_stats[u]
                t100 = f", top100={us['top100_overlap_pct']}%" if us.get('top100_overlap_pct') is not None else ""
                print(f"{u}: {us['count']} matched, delta={us['avg_abs_delta']}, "
                      f"top-{us['top_n_used']}={us['top_n_overlap_pct']}%, "
                      f"tier={us['tier_agreement_pct']}%{t100}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
