#!/usr/bin/env python3
"""Audit source-CSV → player-pool identity matching across all sources.

For every source CSV registered in
``src.api.data_contract._SOURCE_CSV_PATHS`` this script replays the
exact join the live contract build performs (same parser, same
``_canonical_match_key`` cascade, same position-group pool that
``_enrich_from_source_csvs`` builds via ``row_groups_by_key``) and
reports, per source:

  * total raw CSV rows and rows the parser accepted
  * rows whose canonical key matches a player-pool row (name join)
  * rows recovered ONLY by the sleeper_id join (name drift the
    canonical cascade missed — e.g. PFK "Kenneth Gainwell" vs
    Sleeper "Kenny Gainwell")
  * unmatched rows, each with a best-guess fuzzy near-miss against
    the pool (rapidfuzz when installed, difflib otherwise) so a human
    can triage TRUE aliases vs genuinely-absent players

It also runs an **alias collision-delta check**: the
``CANONICAL_NAME_ALIASES`` table must never merge two DISTINCT pool
players onto one canonical name.  See :func:`alias_collision_delta`
for the method and for why the check runs at name granularity rather
than ``name::position_group`` granularity.

This is an AUDIT, not a gate: it exits 0 by default even with findings.
Pass ``--fail-on-collision`` to exit 1 when the collision-delta check
finds anything — that is the mode
``.github/workflows/audit-identity-matches.yml`` runs against freshly
refreshed CSVs, so vendor drift that introduces a collision surfaces
without blocking the data refresh itself.

.. warning::
   **Re-verifying alias impact with an A/B contract build?**
   ``src.api.data_contract._SOURCE_CSV_PARSE_CACHE`` is keyed on
   ``(csv path, mtime)`` and stores a lookup whose keys are ALREADY
   alias-resolved.  Building the contract, mutating the alias table
   in-process, and rebuilding therefore reuses the first build's
   resolved keys and reports a false "0 delta".  Run each arm in a
   FRESH interpreter (or clear the cache between arms) — this script
   and the tests do.

Usage:
    python scripts/audit_identity_matches.py [--json-path PATH]
                                             [--json OUT.json]
                                             [--near-miss-cutoff 0.84]
                                             [--limit N]
                                             [--fail-on-collision]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import (  # noqa: E402
    _SOURCE_CSV_PATHS,
    _canonical_match_key,
    _derive_current_draft_year_from_names,
    _derive_player_row,
    _inject_far_future_pick_sources,
    _parse_source_csv_cached,
    current_rookie_draft_year,
    set_observed_current_draft_year,
)
from src.utils.name_clean import (  # noqa: E402
    canonical_position_group,
    normalize_player_name,
)

try:  # optional accelerator — requirements do not pin it
    from rapidfuzz import fuzz as _rapidfuzz  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - environment-dependent
    _rapidfuzz = None

if _rapidfuzz is None:
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()
else:  # pragma: no cover - environment-dependent

    def _similarity(a: str, b: str) -> float:
        return _rapidfuzz.ratio(a, b) / 100.0


_PICK_NAME_RE = re.compile(r"^\d{4}\s+(pick|round|[1-6](st|nd|rd|th)?)\b", re.IGNORECASE)


def _load_payload(json_path: str | None) -> tuple[Path, dict[str, Any]]:
    if json_path:
        p = Path(json_path)
        if not p.exists():
            print(f"ERROR: payload not found: {p}", file=sys.stderr)
            sys.exit(1)
    else:
        candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
        for extra in (
            REPO / "exports" / "latest" / "dynasty_data.json",
            REPO / "data" / "latest.json",
        ):
            if extra.exists():
                candidates.append(extra)
        if not candidates:
            print(
                "ERROR: no exports/latest/dynasty_data_*.json found; pass --json-path.",
                file=sys.stderr,
            )
            sys.exit(1)
        p = candidates[-1]
    with p.open("r", encoding="utf-8") as f:
        return p, json.load(f)


def _build_pool(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the player-row pool the same way ``build_api_data_contract``
    does before calling ``_enrich_from_source_csvs``.

    Mirrors the pre-enrichment steps: draft-year derivation, far-future
    pick injection, then ``_derive_player_row`` per player.
    """
    players_by_name = dict(payload.get("players") or {})
    set_observed_current_draft_year(_derive_current_draft_year_from_names(players_by_name.keys()))
    _inject_far_future_pick_sources(players_by_name, current_rookie_draft_year())

    sleeper = payload.get("sleeper") or {}
    pos_map = sleeper.get("positions") if isinstance(sleeper, dict) else {}
    if not isinstance(pos_map, dict):
        pos_map = {}
    sites = payload.get("sites")
    site_keys = (
        [str(s.get("key")) for s in sites if isinstance(s, dict) and s.get("key")]
        if isinstance(sites, list)
        else []
    )

    rows: list[dict[str, Any]] = []
    for name in sorted(players_by_name.keys(), key=lambda x: str(x).lower()):
        p_data = players_by_name.get(name)
        if not isinstance(p_data, dict):
            continue
        rows.append(_derive_player_row(str(name), p_data, pos_map, site_keys))
    return rows


def _count_csv_rows(csv_path: Path) -> int:
    try:
        with csv_path.open("r", encoding="utf-8-sig") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:  # noqa: BLE001 — count is informational only
        return 0


# Canonical names where the pool genuinely contains ONE player twice,
# so an alias merging them is correct rather than a defect.
#
# ``alias_collision_delta``'s own docstring carves this case out — "a
# same-family collision is also a defect ... unless the pool genuinely
# contains one player twice" — but the code never implemented it, so
# the exception had nowhere to live and the first real instance turned
# the hard gate red on ``main``.
#
# Entries are NOT a way to quiet the check. Each one needs a verified
# same-player claim, and every collision outside this set still fails.
# The collisions are still reported and still printed in the run
# summary; they are marked, not hidden.
# Verified same-player duplicates, mapped to the EXACT set of alias
# sources whose merge onto that name was checked by a human.
#
# The value is not decoration.  An exemption keyed on the name alone
# widens silently: add a second alias pointing at "rob henry" next year
# and it inherits the carve-out without anyone looking.  Pinning the
# source set means a new alias into an exempted name fails
# ``test_the_allowlist_still_describes_the_aliases_it_exempts`` and has
# to be verified on its own merits.
#
# NOTE the presence of the collision in any given snapshot is NOT the
# criterion — the pool is refreshed from external sources every two
# hours and the second spelling comes and goes with it (it was present
# on 2026-07-30T18:06Z and gone by 2026-07-31T04:09Z).  What makes the
# exemption live is the alias, which is committed code.
_KNOWN_POOL_DUPLICATES: dict[str, frozenset[str]] = {
    # "Rob Henry" + "Robert Henry" — one player, two pool rows.
    #
    # ``src/utils/name_clean.py`` aliases "robert henry" → "rob henry"
    # with the identity verified on both sides: RB, UTSA UDFA → WAS,
    # age 24. The alias existed to bridge DraftSharks/FantasyPros'
    # "Robert Henry Jr." to the pool's "Rob Henry".
    #
    # The 2026-07-30T18:06Z scheduled refresh then added "Robert Henry"
    # to CSVs/dynasty_full.csv alongside the existing "Rob Henry", so
    # the pool now carries both spellings and the alias merges two rows
    # that are the same person. That is the alias working, not failing.
    #
    # It reports ``crossFamily`` only because the new row carries no
    # position and lands in the OTHER group — absence of position data,
    # not evidence of a second player. The vote-replication hazard this
    # check exists for (a WR absorbing a CB's ballot) needs two KNOWN
    # and different families.
    #
    # Removing the alias was the alternative and is worse: it would
    # leave one player sitting on the board as two separate rows.
    "rob henry": frozenset({"robert henry"}),
}


def alias_collision_delta(pool_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return alias-introduced collisions among distinct pool players.

    The check runs at **name granularity**, not ``name::group``
    granularity, because that is the granularity the join it protects
    actually uses: ``_enrich_from_source_csvs`` builds ``csv_lookup``
    keyed by the name-only ``_canonical_match_key``, and when one
    canonical name maps to pool rows in more than one position group
    it *replicates* the best CSV entry across every one of those
    groups (the ``len(row_groups) > 1`` branch).  A group-keyed check
    therefore cannot see the worst failure mode: an alias that pulls
    two players of DIFFERENT position families onto one name, e.g. a
    hypothetical WR "Michael Jackson" absorbing CB "Mike Jackson"'s
    draftSharksIdp vote.  An earlier revision of this function keyed on
    ``canonical_player_key`` and reported that case clean.

    Method: for every pool row compute the pre-alias name
    (``normalize_player_name``) and the post-alias name
    (``resolve_canonical_name``).  A post-alias name that absorbs more
    than one DISTINCT pre-alias name is an alias-introduced collision —
    the alias, not the normalizer, is what merged them.  Pool rows that
    already shared a pre-alias name (e.g. "DJ Turner" WR vs "DJ Turner
    II" CB) collide *without* the alias table and are deliberately not
    reported here: this is a delta check, and that pre-existing class is
    handled by the position-aware ``canonical_player_key`` used
    elsewhere.

    Each reported collision carries ``crossFamily`` — True when the
    merged rows span more than one position group, which is the
    vote-replication case above and always a hard defect.  A
    same-family collision is also a defect (two real players merged)
    unless the pool genuinely contains one player twice.
    """
    post_to_pre: dict[str, dict[str, list[dict[str, str]]]] = {}
    for row in pool_rows:
        nm = str(row.get("canonicalName") or row.get("displayName") or "")
        if not nm:
            continue
        pre_name = normalize_player_name(nm)
        post_name = _canonical_match_key(nm)
        if not post_name:
            continue
        grp = canonical_position_group(row.get("position"))
        post_to_pre.setdefault(post_name, {}).setdefault(pre_name, []).append(
            {"name": nm, "group": grp}
        )

    collisions: list[dict[str, Any]] = []
    for post_name, pre_map in sorted(post_to_pre.items()):
        if len(pre_map) < 2:
            continue
        entries = [e for group in pre_map.values() for e in group]
        groups = sorted({e["group"] for e in entries})
        collisions.append(
            {
                "canonicalName": post_name,
                "mergedNames": sorted(e["name"] for e in entries),
                "preAliasNames": sorted(pre_map),
                "positionGroups": groups,
                "crossFamily": len(groups) > 1,
                # Reported either way; the gate ignores only the
                # verified same-player duplicates above.
                "knownPoolDuplicate": post_name in _KNOWN_POOL_DUPLICATES,
            }
        )
    return collisions


def audit_sources(
    pool_rows: list[dict[str, Any]],
    *,
    near_miss_cutoff: float = 0.84,
    fuzzy_floor: float = 0.60,
) -> dict[str, Any]:
    """Run the per-source match audit against ``pool_rows``."""
    # Pool indexes — mirrors row_groups_by_key in _enrich_from_source_csvs.
    row_groups_by_key: dict[str, set[str]] = {}
    pool_names_by_key: dict[str, set[str]] = {}
    pool_ids: dict[str, str] = {}
    for row in pool_rows:
        nm = str(row.get("canonicalName") or row.get("displayName") or "")
        if not nm:
            continue
        cname = _canonical_match_key(nm)
        if not cname:
            continue
        grp = canonical_position_group(row.get("position"))
        row_groups_by_key.setdefault(cname, set()).add(grp)
        pool_names_by_key.setdefault(cname, set()).add(nm)
        sid = str(row.get("playerId") or "").strip()
        if sid:
            pool_ids[sid] = nm

    pool_keys = list(row_groups_by_key.keys())

    sources: dict[str, Any] = {}
    for source_key, cfg in _SOURCE_CSV_PATHS.items():
        if isinstance(cfg, str):
            csv_rel, signal = cfg, "value"
        elif isinstance(cfg, dict):
            csv_rel = str(cfg.get("path") or "")
            signal = str(cfg.get("signal") or "value").lower()
        else:
            continue
        if not csv_rel:
            continue
        csv_path = REPO / csv_rel
        if not csv_path.exists():
            sources[source_key] = {"path": csv_rel, "error": "file_not_found"}
            continue
        csv_lookup, schema_err = _parse_source_csv_cached(csv_path, source_key, signal, csv_rel)
        if schema_err is not None:
            sources[source_key] = {"path": csv_rel, "error": schema_err.get("error")}
            continue

        raw_rows = _count_csv_rows(csv_path)
        parsed_rows = sum(len(v) for v in csv_lookup.values())
        matched_rows = 0
        matched_keys = 0
        id_matched_rows = 0
        unmatched: list[dict[str, Any]] = []
        for cname, entries in sorted(csv_lookup.items()):
            if cname in row_groups_by_key:
                matched_keys += 1
                matched_rows += len(entries)
                continue
            # Name join failed — try the sleeper_id join the enrichment
            # loop performs first (only CSVs that carry sleeper_id).
            sid_hits = [e for e in entries if e[4] and str(e[4]) in pool_ids]
            if sid_hits:
                id_matched_rows += len(sid_hits)
            leftover = [e for e in entries if not (e[4] and str(e[4]) in pool_ids)]
            for entry in leftover:
                display = str(entry[0])
                is_pick = bool(_PICK_NAME_RE.match(display))
                best: list[dict[str, Any]] = []
                if not is_pick:
                    scored = sorted(
                        ((k, _similarity(cname, k)) for k in pool_keys),
                        key=lambda t: -t[1],
                    )[:3]
                    best = [
                        {
                            "poolKey": k,
                            "poolNames": sorted(pool_names_by_key.get(k, set())),
                            "groups": sorted(row_groups_by_key.get(k, set())),
                            "score": round(score, 4),
                        }
                        for k, score in scored
                        if score >= fuzzy_floor
                    ]
                top_score = best[0]["score"] if best else 0.0
                category = (
                    "pick"
                    if is_pick
                    else ("near_miss" if top_score >= near_miss_cutoff else "no_close_match")
                )
                unmatched.append(
                    {
                        "sourceName": display,
                        "canonicalKey": cname,
                        "sleeperId": entry[4],
                        "category": category,
                        "nearMisses": best,
                    }
                )
        total_considered = matched_rows + id_matched_rows + len(unmatched)
        sources[source_key] = {
            "path": csv_rel,
            "signal": signal,
            "csvRows": raw_rows,
            "parsedRows": parsed_rows,
            "matchedRows": matched_rows,
            "matchedKeys": matched_keys,
            "idOnlyMatchedRows": id_matched_rows,
            "unmatchedRows": len(unmatched),
            "matchRate": (
                round((matched_rows + id_matched_rows) / total_considered, 4)
                if total_considered
                else None
            ),
            "unmatched": sorted(
                unmatched,
                key=lambda u: -(u["nearMisses"][0]["score"] if u["nearMisses"] else 0.0),
            ),
        }

    return {
        "poolRows": len(pool_rows),
        "poolKeys": len(pool_keys),
        "sources": sources,
    }


def build_report(
    payload: dict[str, Any],
    *,
    near_miss_cutoff: float = 0.84,
) -> dict[str, Any]:
    pool_rows = _build_pool(payload)
    report = audit_sources(pool_rows, near_miss_cutoff=near_miss_cutoff)
    report["aliasCollisions"] = alias_collision_delta(pool_rows)
    report["generatedAt"] = datetime.now(timezone.utc).isoformat()
    return report


def _print_human(report: dict[str, Any], *, limit: int) -> None:
    print(f"Pool: {report['poolRows']} rows / {report['poolKeys']} canonical keys")
    print()
    header = f"{'source':<24}{'csv':>6}{'parsed':>8}{'match':>7}{'id':>5}{'unmat':>7}{'rate':>8}"
    print(header)
    print("-" * len(header))
    for key, info in report["sources"].items():
        if "error" in info:
            print(f"{key:<24}  ERROR: {info['error']} ({info['path']})")
            continue
        rate = info["matchRate"]
        print(
            f"{key:<24}{info['csvRows']:>6}{info['parsedRows']:>8}"
            f"{info['matchedRows']:>7}{info['idOnlyMatchedRows']:>5}"
            f"{info['unmatchedRows']:>7}"
            f"{('' if rate is None else format(rate * 100, '.1f') + '%'):>8}"
        )
    print()
    for key, info in report["sources"].items():
        unmatched = info.get("unmatched") or []
        if not unmatched:
            continue
        print(f"── {key}: {len(unmatched)} unmatched ──")
        for u in unmatched[:limit]:
            best = u["nearMisses"][0] if u["nearMisses"] else None
            if best:
                print(
                    f"  [{u['category']:<14}] {u['sourceName']!r} → "
                    f"{best['poolNames']} ({'/'.join(best['groups'])}) "
                    f"score={best['score']}"
                )
            else:
                print(f"  [{u['category']:<14}] {u['sourceName']!r} → no candidate")
        if len(unmatched) > limit:
            print(f"  ... {len(unmatched) - limit} more")
        print()
    collisions = report.get("aliasCollisions") or []
    if collisions:
        print(f"!! ALIAS-INTRODUCED COLLISIONS: {len(collisions)}")
        for c in collisions:
            tag = "CROSS-FAMILY " if c.get("crossFamily") else ""
            print(
                f"  {tag}{c['canonicalName']}: merges {c['mergedNames']} "
                f"({'/'.join(c['positionGroups'])})"
            )
    else:
        print("Alias collision-delta check: clean (0 alias-introduced pool collisions)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json-path", help="raw dynasty_data payload JSON (default: newest export)")
    ap.add_argument("--json", dest="json_out", help="write the full machine-readable report here")
    ap.add_argument(
        "--near-miss-cutoff",
        type=float,
        default=0.84,
        help="similarity at/above which an unmatched row is flagged near_miss (default 0.84)",
    )
    ap.add_argument(
        "--limit", type=int, default=15, help="max unmatched rows printed per source (default 15)"
    )
    ap.add_argument(
        "--fail-on-collision",
        action="store_true",
        help=(
            "exit 1 when the alias collision-delta check finds anything "
            "(CI gate mode; the audit is exit-0-always without it)"
        ),
    )
    ap.add_argument(
        "--github-summary",
        action="store_true",
        help="append a Markdown summary to $GITHUB_STEP_SUMMARY when set",
    )
    args = ap.parse_args()

    path, payload = _load_payload(args.json_path)
    print(f"Loading: {path}")
    report = build_report(payload, near_miss_cutoff=args.near_miss_cutoff)
    report["payload"] = str(path)
    _print_human(report, limit=args.limit)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nJSON report written: {out}")

    collisions = report.get("aliasCollisions") or []
    if args.github_summary:
        _write_github_summary(report, collisions)
    if collisions and args.fail_on_collision:
        # ``_KNOWN_POOL_DUPLICATES`` entries are REPORTED but do not fail
        # the gate — that is the whole point of the set, and until now it
        # was only half-implemented: ``build_report`` stamped
        # ``knownPoolDuplicate`` on the row and this gate ignored the
        # stamp, so the carve-out annotated the collision and still went
        # red.  The set's own docstring says "every collision outside
        # this set still fails", which only means anything if the ones
        # inside it do not.  A guard whose stated purpose and actual
        # predicate differ is the exact failure mode this repo keeps
        # tripping over (docs/ORCHESTRATION.md §6.15).
        #
        # They stay visible as ::notice, never silently dropped.
        blocking = [c for c in collisions if not c.get("knownPoolDuplicate")]
        for c in collisions:
            kind = "cross-family " if c.get("crossFamily") else ""
            if c.get("knownPoolDuplicate"):
                print(
                    f"::notice title=Known pool duplicate::{kind}"
                    f"'{c['canonicalName']}' merges {c['mergedNames']} — "
                    "verified same player, allow-listed in "
                    "_KNOWN_POOL_DUPLICATES; not failing the gate"
                )
            else:
                print(
                    f"::error title=Alias collision::{kind}'{c['canonicalName']}' "
                    f"merges {c['mergedNames']}"
                )
        if blocking:
            return 1
    return 0


def _write_github_summary(report: dict[str, Any], collisions: list[dict[str, Any]]) -> None:
    """Append a Markdown summary to ``$GITHUB_STEP_SUMMARY`` if present."""
    import os  # noqa: PLC0415

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## Identity match audit", ""]
    lines.append(f"- Payload: `{report.get('payload')}`")
    lines.append(f"- Pool: **{report['poolRows']}** rows")
    lines.append("")
    if collisions:
        lines.append(f"### {len(collisions)} alias-introduced collision(s)")
        lines.append("")
        lines.append("| canonical name | merged pool rows | position groups | cross-family |")
        lines.append("|---|---|---|---|")
        for c in collisions:
            lines.append(
                f"| `{c['canonicalName']}` | {', '.join(c['mergedNames'])} | "
                f"{'/'.join(c['positionGroups'])} | {'**yes**' if c['crossFamily'] else 'no'} |"
            )
    else:
        lines.append("### Alias collision-delta: clean")
        lines.append("")
        lines.append("No alias-introduced pool collisions.")
    lines.append("")
    lines.append("| source | csv rows | matched | unmatched | rate |")
    lines.append("|---|---|---|---|---|")
    for key, info in report["sources"].items():
        if "error" in info:
            lines.append(f"| `{key}` | — | — | — | ERROR: {info['error']} |")
            continue
        rate = info["matchRate"]
        rate_s = "—" if rate is None else f"{rate * 100:.1f}%"
        lines.append(
            f"| `{key}` | {info['csvRows']} | {info['matchedRows']} | "
            f"{info['unmatchedRows']} | {rate_s} |"
        )
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
