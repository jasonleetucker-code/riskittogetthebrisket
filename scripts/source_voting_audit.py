#!/usr/bin/env python3
"""Print every registered ranking source's voting status from a built board.

Owner directive 2026-10-19 ("Universal Source Voting and Freshness Policy"
§5): for each source — name, key, provider, coverage, last genuine publisher
update, days since, freshness %, base weight, effective weight, players
contributing, voting or not, the exact reason, and what restores it.

Reads the contract's ``sourceVotingStatus`` block
(``src/sources/voting_status.py``) — nothing is recomputed here, so the
table cannot disagree with the board.  Either point it at a built contract
(``--contract``, plain or ``.gz`` JSON) or let it build one through the real
entry point (``build_api_data_contract``) from a raw export (``--input``,
default: the newest ``exports/latest/dynasty_data_*.json``).  A build reads
the tracked ``CSVs/site_raw`` boards and ``data/scrape_state`` as they are
in this checkout; the input hashes are printed so a table is reproducible.

Usage::

    python scripts/source_voting_audit.py                      # text table
    python scripts/source_voting_audit.py --format markdown    # for the docs
    python scripts/source_voting_audit.py --format json --out status.json

Exit codes: 0 success, 1 the board carries no voting-status block, 2 usage
or input error.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    blob = path.read_bytes()
    if path.suffix == ".gz":
        blob = gzip.decompress(blob)
    return json.loads(blob.decode("utf-8")), hashlib.sha256(blob).hexdigest()


def _newest_export() -> Path | None:
    exports = sorted((REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
    return exports[-1] if exports else None


def _tree_digest(rel: str, pattern: str) -> str:
    h = hashlib.sha256()
    root = REPO_ROOT / rel
    if root.is_dir():
        for path in sorted(root.glob(pattern)):
            h.update(path.name.encode("utf-8"))
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def load_status(args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(sourceVotingStatus block, provenance)``."""
    if args.contract:
        contract, sha = _read_json(Path(args.contract))
        return contract.get("sourceVotingStatus"), {"contract": str(args.contract), "sha256": sha}
    inp = Path(args.input) if args.input else _newest_export()
    if inp is None or not inp.is_file():
        raise FileNotFoundError(f"no export to build from ({inp})")
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    raw, sha = _read_json(inp)
    contract = build_api_data_contract(raw)
    return contract.get("sourceVotingStatus"), {
        "input": str(inp.relative_to(REPO_ROOT) if inp.is_relative_to(REPO_ROOT) else inp),
        "inputSha256": sha,
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "sourceCsvDigest": _tree_digest("CSVs/site_raw", "*.csv"),
        "datasetStateDigest": _tree_digest("data/scrape_state", "*_dataset.json"),
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _date(iso: str | None) -> str:
    return iso[:10] if iso else "unknown"


COLUMNS = (
    ("Source", lambda e: e["displayName"]),
    ("Key", lambda e: e["key"]),
    ("Provider", lambda e: e.get("provider")),
    ("Coverage", lambda e: e.get("coverage")),
    ("Last genuine update", lambda e: _date(e.get("lastGenuineUpdate"))),
    ("Basis", lambda e: e.get("lastGenuineUpdateBasis")),
    ("Days", lambda e: e.get("daysSinceUpdate")),
    ("Freshness %", lambda e: e.get("freshnessPct")),
    ("Base", lambda e: e.get("baseWeight")),
    ("Effective", lambda e: e.get("effectiveWeight")),
    ("Players", lambda e: e.get("playersContributing")),
    ("Picks", lambda e: e.get("picksContributing")),
    ("Voting", lambda e: e.get("voting")),
    ("Status", lambda e: e.get("statusLabel")),
)


def render_markdown(block: dict[str, Any], provenance: dict[str, Any]) -> str:
    lines = [
        f"Board as of `{block.get('asOf')}`; freshness rule `{block.get('freshnessSchedule')}`; "
        f"freshness applied: {_fmt(block.get('freshnessApplied'))}.",
        "",
        "| " + " | ".join(c for c, _ in COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    for e in block.get("sources") or []:
        lines.append("| " + " | ".join(_fmt(fn(e)).replace("|", "/") for _, fn in COLUMNS) + " |")
    lines += ["", "**Why each source is voting or not, and what restores it**", ""]
    lines += ["| Key | Status | Reason | Restore requirement |", "|---|---|---|---|"]
    for e in block.get("sources") or []:
        lines.append(
            f"| `{e['key']}` | {e.get('statusLabel')} | {e.get('reason')} | "
            f"{e.get('restoreRequirement') or '—'} |"
        )
    counts = block.get("statusCounts") or {}
    labels = block.get("statusLabels") or {}
    lines += [
        "",
        "Status counts: "
        + ", ".join(f"{labels.get(k, k)} {v}" for k, v in sorted(counts.items()))
        + f". Voting: {block.get('votingCount')} of {block.get('registeredCount')}.",
        "",
        "Provenance: " + ", ".join(f"{k} `{v}`" for k, v in provenance.items()),
    ]
    return "\n".join(lines) + "\n"


def render_text(block: dict[str, Any], provenance: dict[str, Any]) -> str:
    out = [
        f"SOURCE VOTING STATUS  as of {block.get('asOf')}  rule {block.get('freshnessSchedule')}"
        f"  applied={_fmt(block.get('freshnessApplied'))}",
        "",
    ]
    hdr = f"{'key':24} {'coverage':8} {'last update':11} {'days':>4} {'fresh%':>6} "
    hdr += f"{'base':>4} {'eff':>5} {'players':>7} {'picks':>5}  status"
    out.append(hdr)
    for e in block.get("sources") or []:
        out.append(
            f"{e['key']:24} {e.get('coverage') or '':8} {_date(e.get('lastGenuineUpdate')):11} "
            f"{_fmt(e.get('daysSinceUpdate')):>4} {_fmt(e.get('freshnessPct')):>6} "
            f"{_fmt(e.get('baseWeight')):>4} {_fmt(e.get('effectiveWeight')):>5} "
            f"{_fmt(e.get('playersContributing')):>7} {_fmt(e.get('picksContributing')):>5}  "
            f"{e.get('statusLabel')}"
        )
    out.append("")
    for e in block.get("sources") or []:
        if not e.get("voting") or e.get("status") != "active_100":
            out.append(f"- {e['key']}: {e.get('reason')}")
            if e.get("restoreRequirement"):
                out.append(f"    restore: {e['restoreRequirement']}")
    out.append("")
    out.append(
        f"voting {block.get('votingCount')} of {block.get('registeredCount')}; "
        f"counts {json.dumps(block.get('statusCounts'), sort_keys=True)}"
    )
    out.append("provenance " + json.dumps(provenance, sort_keys=True))
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--contract", help="a built contract (JSON or .json.gz)")
    src.add_argument("--input", help="a raw export to build from (default: newest exports/latest)")
    ap.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    ap.add_argument("--out", help="write here instead of stdout")
    args = ap.parse_args(argv)
    try:
        block, provenance = load_status(args)
    except (OSError, ValueError) as exc:
        print(f"source_voting_audit: {exc}", file=sys.stderr)
        return 2
    if not block:
        print("source_voting_audit: the board carries no sourceVotingStatus block", file=sys.stderr)
        return 1
    if args.format == "json":
        text = json.dumps({"provenance": provenance, **block}, indent=1, sort_keys=True) + "\n"
    elif args.format == "markdown":
        text = render_markdown(block, provenance)
    else:
        text = render_text(block, provenance)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
