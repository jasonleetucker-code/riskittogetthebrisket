#!/usr/bin/env python3
"""Inventory of tracked data files that a PUBLIC repository publishes.

Read-only.  Never prints or stores a value: only counts, field names, paths,
vendor names and sizes.  Decides nothing about what may be published -- it is
input to ``docs/security/DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md``.

Also owns the detector used by the CI guard
``tests/governance/test_tracked_data_exposure_guard.py`` so the report and the
guard cannot drift apart.

Usage::

    python scripts/audit_tracked_data_exposure.py --out-json r.json --out-md r.md
    python scripts/audit_tracked_data_exposure.py --write-baseline
    python scripts/audit_tracked_data_exposure.py --changed-since origin/main   # PR gate

Determinism: no timestamps, sorted keys.  ``--with-last-commit`` adds the last
commit date per path group (slower, and changes as the repo moves).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO / "config" / "security" / "tracked_data_exposure_baseline.txt"

SCOPE_PREFIXES = ("CSVs/", "exports/", "data/", "config/", "reports/", "audit/")
DATA_EXTS = (".csv", ".jsonl", ".zip", ".sqlite", ".db", ".xlsx", ".parquet")
SCANNABLE_EXTS = (".json", ".jsonl", ".csv", ".js", ".txt", ".md")
MAX_SCAN_BYTES = 64_000_000

#: Directories the refresh / box timers REPUBLISH continuously.  New dated files
#: appear here every run, so the baseline acknowledges the directory, not each
#: file.  Exposure growing in a NEW directory still fails the guard.
ROTATING_PREFIXES = (
    "data/raw/",
    "data/raw_sources/",
    "data/canonical/",
    "data/ros/",
    "data/playerctx/history/",
    "exports/archive/",
    "exports/latest/",
    "exports/narratives/",
)

#: Vendors whose boards are paid / private / account-gated.  A heuristic list
#: for the OWNER to confirm -- not a legal classification.
PAID_VENDOR_PATTERNS = {
    "Dynasty League Football": ("dlf",),
    "Draft Sharks": ("draftsharks",),
    "The IDP Show": ("idpshow",),
    "Dynasty Nerds": ("dynastynerds",),
    "Footballguys": ("footballguys",),
    "PFF (via IDP tables)": ("pff",),
    "Signals Fantasy": ("signals",),
}
PAID_EXTS = (".csv", ".zip", ".xlsx", ".json", ".jsonl")

FREE_VENDOR_PATTERNS = {
    "KeepTradeCut": ("ktc",),
    "FantasyCalc": ("fantasycalc",),
    "FantasyPros": ("fantasypros",),
    "Dynasty Daddy": ("dynastydaddy", "dynasty_daddy"),
    "IDP Trade Calculator": ("idptradecalc",),
    "Yahoo (Boone)": ("yahoo",),
    "OTC Fantasy Football": ("otcffb",),
    "Fantasy Navigator": ("fantasynavigator",),
    "Play for Keeps": ("pfk",),
    "Flock Fantasy": ("flock",),
}

# --- identifier detectors (COUNT only) -------------------------------------
_ID_VALUE = r"\"?\s*[:=]\s*\"?\d{17,19}\b"
OWNER_ID_RE = re.compile(
    r"(?:owner_id|ownerId|user_id|userId|roster_owner_id|ownerUserId|sleeperUserId)" + _ID_VALUE
)
LEAGUE_ID_RE = re.compile(r"(?:league_id|leagueId|sleeperLeagueId|previous_league_id)" + _ID_VALUE)
NAME_FIELD_RE = re.compile(
    r"\"(?:username|ownerName|owner_name|managerName|manager_name|ownerDisplayName|owner_display_name)\"\s*:"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LONG_NUMERIC_RE = re.compile(r"(?<![\d.])\d{17,19}(?![\d.])")

IDENT_KEYS = ("ownerIds", "leagueIds", "nameFields", "emails", "longNumeric")


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return sorted(p for p in out.split("\0") if p)


def in_scope(rel: str) -> bool:
    return rel.startswith(SCOPE_PREFIXES) or rel.lower().endswith(DATA_EXTS)


def vendor_of(rel: str, paid_only: bool = False) -> tuple[str | None, bool]:
    """(vendor, is_paid) from path tokens.  Path-based and heuristic."""
    low = rel.lower()
    parts = re.split(r"[/\\]", low)
    names = []
    for p in parts[1:] if parts[0] in ("csvs", "data", "exports") else parts:
        names.append(re.sub(r"\.[a-z0-9]+$", "", p))
    for vendor, pats in PAID_VENDOR_PATTERNS.items():
        for n in names:
            if any(n.startswith(p) or f"/{p}" in f"/{n}" for p in pats):
                return vendor, True
    if paid_only:
        return None, False
    for vendor, pats in FREE_VENDOR_PATTERNS.items():
        for n in names:
            if any(n.startswith(p) for p in pats):
                return vendor, False
    return None, False


def is_paid_vendor_data_path(rel: str) -> str | None:
    """Guard rule: a tracked data file whose path names a paid vendor."""
    if not rel.lower().endswith(PAID_EXTS):
        return None
    if not rel.startswith(("CSVs/", "data/", "exports/")):
        return None
    vendor, paid = vendor_of(rel, paid_only=True)
    return vendor if paid else None


def _decode(blob: bytes) -> str:
    return blob.decode("utf-8", errors="ignore")


def count_identifiers(text: str) -> dict[str, int]:
    return {
        "ownerIds": len(OWNER_ID_RE.findall(text)),
        "leagueIds": len(LEAGUE_ID_RE.findall(text)),
        "nameFields": len(NAME_FIELD_RE.findall(text)),
        "emails": len([e for e in EMAIL_RE.findall(text) if not e.endswith("noreply.github.com")]),
        "longNumeric": len(LONG_NUMERIC_RE.findall(text)),
    }


def _zero() -> dict[str, int]:
    return dict.fromkeys(IDENT_KEYS, 0)


def scan_file(rel: str) -> tuple[dict[str, int], list[str]]:
    """Identifier counts plus names of paid-vendor members inside a zip."""
    path = REPO / rel
    counts = _zero()
    paid_members: list[str] = []
    try:
        if not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
            return counts, paid_members
        low = rel.lower()
        if low.endswith(".zip"):
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    name = info.filename
                    if is_paid_vendor_data_path("data/" + name):
                        paid_members.append(name)
                    if info.file_size > MAX_SCAN_BYTES or not name.lower().endswith(SCANNABLE_EXTS):
                        continue
                    c = count_identifiers(_decode(zf.read(name)))
                    for k in IDENT_KEYS:
                        counts[k] += c[k]
        elif low.endswith(SCANNABLE_EXTS):
            counts = count_identifiers(_decode(path.read_bytes()))
    except (OSError, zipfile.BadZipFile, RuntimeError):
        pass
    return counts, paid_members


def guard_findings(rel: str) -> list[str]:
    """Reasons a tracked file should not be NEW (empty = fine).  No values."""
    reasons: list[str] = []
    vendor = is_paid_vendor_data_path(rel)
    if vendor:
        reasons.append(f"paid-vendor data path ({vendor})")
    counts, paid_members = scan_file(rel)
    if counts["ownerIds"]:
        reasons.append(f"owner/user-id fields with id-like values (count={counts['ownerIds']})")
    if paid_members:
        reasons.append(f"zip carries paid-vendor members (count={len(paid_members)})")
    return reasons


# --- baseline ---------------------------------------------------------------
def load_baseline(path: Path = BASELINE_PATH) -> tuple[set[str], tuple[str, ...]]:
    exact: set[str] = set()
    prefixes: list[str] = []
    if not path.is_file():
        return exact, ()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("prefix: "):
            prefixes.append(line[len("prefix: ") :])
        elif line.startswith("path: "):
            exact.add(line[len("path: ") :])
    return exact, tuple(prefixes)


def baselined(rel: str, exact: set[str], prefixes: tuple[str, ...]) -> bool:
    return rel in exact or rel.startswith(prefixes)


def build_baseline_lines(files: list[str]) -> list[str]:
    lines = [
        "# Tracked-data exposure baseline (paths only; no values).",
        "# Generated by: python scripts/audit_tracked_data_exposure.py --write-baseline",
        "# Files here ALREADY publish owner-id-like fields or paid-vendor data.",
        "# The guard fails only on files NOT covered here.  Shrinking this file is good;",
        "# GROWING it needs the owner decision in docs/security/DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md.",
    ]
    for p in ROTATING_PREFIXES:
        lines.append(f"prefix: {p}")
    exact: list[str] = []
    for rel in files:
        if not in_scope(rel) or rel.startswith(ROTATING_PREFIXES):
            continue
        if guard_findings(rel):
            exact.append(rel)
    lines.extend(f"path: {p}" for p in sorted(exact))
    return lines


def changed_files(base_ref: str) -> list[str]:
    """Files ADDED or MODIFIED vs the merge base with ``base_ref`` (PR diff)."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=AM", f"{base_ref}...HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.split("\0") if p)


def check_changed_since(base_ref: str, baseline: Path | None = None) -> list[str]:
    """Offender lines for changed in-scope files not covered by the baseline."""
    exact, prefixes = load_baseline(baseline or BASELINE_PATH)
    lines = []
    for rel in changed_files(base_ref):
        if not in_scope(rel) or baselined(rel, exact, prefixes):
            continue
        reasons = guard_findings(rel)
        if reasons:
            lines.append(f"{rel}: {'; '.join(reasons)}")
    return lines


# --- classification ---------------------------------------------------------
WRITERS = (
    (
        "CSVs/site_raw/",
        ".github/workflows/scheduled-refresh.yml (git add -f CSVs/); deploy/dlf_fetch_and_push.sh and deploy/idpshow_fetch_and_push.sh (box timers push DLF / IDP Show)",
    ),
    ("CSVs/", ".github/workflows/scheduled-refresh.yml (git add -f CSVs/)"),
    (
        "exports/archive/",
        ".github/workflows/scheduled-refresh.yml; src/maintenance/retention; read by scripts/build_temporal_ledger.py, tests/archive_fixtures.py",
    ),
    ("exports/narratives/", ".github/workflows/weekly-narratives.yml"),
    (
        "exports/",
        ".github/workflows/scheduled-refresh.yml (git add -f exports/); shipped to the box by deploy",
    ),
    (
        "data/raw/",
        ".github/workflows/scheduled-refresh.yml (git add -f data/raw/); src/maintenance/retention prunes",
    ),
    ("data/raw_sources/", ".github/workflows/scheduled-refresh.yml; src/maintenance/retention"),
    (
        "data/scrape_state/",
        ".github/workflows/scheduled-refresh.yml (git add -f data/scrape_state/ every run; deploy dispatch keys on commit subjects, CLAUDE.md W31-F001)",
    ),
    (
        "data/ros/",
        ".github/workflows/scheduled-refresh.yml (git add -f data/ros/); team_strength unstaged by B8",
    ),
    (
        "data/playerctx/",
        ".github/workflows/c1a-run-playerctx-push.yml; deploy/playerctx_history_push.sh",
    ),
    ("data/ops/", ".github/workflows/verify-sharp-production.yml and one-off ops evidence"),
    (
        "data/sleeper_last_good.json",
        ".github/workflows/scheduled-refresh.yml (Sleeper-outage fallback)",
    ),
    ("data/", ".github/workflows/scheduled-refresh.yml (git add -f for named subtrees)"),
    (
        "config/draft_valuation/",
        ".github/workflows/scheduled-refresh.yml (create-only Batch D stores)",
    ),
    ("config/model_registry/", ".github/workflows/refit-hill-curves.yml"),
    ("config/", "hand-edited configuration (reviewed PRs)"),
    ("reports/", "hand-committed reports"),
    ("audit/", "hand-committed audit evidence"),
)


def why_tracked(rel: str) -> str:
    for prefix, why in WRITERS:
        if rel.startswith(prefix):
            return why
    return "committed by hand (PR); not written by an automated pipeline"


def category_of(rel: str, counts: dict[str, int]) -> str:
    _, paid = vendor_of(rel)
    if paid:
        return "paid_vendor_rankings"
    vendor, _ = vendor_of(rel)
    if (
        rel.startswith("data/scrape_state/")
        or rel.startswith("data/ops/")
        or rel.startswith("data/playerctx/")
    ):
        return "operational_state"
    if vendor and rel.startswith(("CSVs/site_raw/", "data/raw")):
        return "free_public_source"
    if rel.startswith("config/"):
        return "config"
    if counts["ownerIds"] or counts["nameFields"] or counts["emails"]:
        if rel.startswith(("exports/", "CSVs/dynasty")):
            return "derived_board_with_league_identifiers"
        return "user_identifying_data"
    if rel.startswith("data/ros/") or rel.startswith("data/sleeper") or "draft" in rel.lower():
        return "league_roster_data"
    if rel.startswith(("exports/", "CSVs/")):
        return "derived_board"
    return "other"


def prefix_group(rel: str) -> str:
    parts = rel.split("/")
    if rel.startswith(("data/raw/", "data/ros/", "exports/", "data/playerctx/")) and len(parts) > 2:
        return "/".join(parts[:2]) + "/" + (parts[2] if len(parts) > 3 else "")
    if len(parts) > 2:
        return "/".join(parts[:2]) + "/"
    return "/".join(parts[:1]) + "/" if len(parts) > 1 else "(repo root)"


_CODE_CACHE: dict[str, str] = {}


def references(prefix: str, files: list[str]) -> list[str]:
    """Paths of code/workflow files naming the prefix (paths only, capped)."""
    if not _CODE_CACHE:
        roots = (".github/", "deploy/", "scripts/", "src/", "tests/")
        for rel in files:
            if not (rel.startswith(roots) or rel in ("server.py", "Dynasty Scraper.py")):
                continue
            if not rel.endswith((".py", ".yml", ".sh", ".json")):
                continue
            try:
                _CODE_CACHE[rel] = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    return sorted(r for r, t in _CODE_CACHE.items() if prefix in t)


def build_report(with_last_commit: bool = False) -> dict:
    files = [f for f in tracked_files() if in_scope(f)]
    all_files = tracked_files()
    by_cat: dict[str, dict] = defaultdict(lambda: {"files": 0, "bytes": 0, **_zero()})
    by_vendor: dict[str, dict] = defaultdict(
        lambda: {"files": 0, "bytes": 0, "paid": False, **_zero()}
    )
    by_group: dict[str, dict] = defaultdict(lambda: {"files": 0, "bytes": 0, **_zero()})
    guard_hits = Counter()
    for rel in files:
        try:
            size = (REPO / rel).stat().st_size
        except OSError:
            continue
        counts, paid_members = scan_file(rel)
        cat = category_of(rel, counts)
        vendor, paid = vendor_of(rel)
        rows = [by_cat[cat], by_group[prefix_group(rel)]]
        if vendor:
            v = by_vendor[vendor]
            v["paid"] = paid
            rows.append(v)
        if paid_members:
            v = by_vendor["(paid vendor members inside export zips)"]
            v["files"] += 0
            v["paid"] = True
            rows.append(v)
        for r in rows:
            r["files"] += 1
            r["bytes"] += size
            for k in IDENT_KEYS:
                r[k] += counts[k]
        if is_paid_vendor_data_path(rel) or counts["ownerIds"] or paid_members:
            guard_hits[prefix_group(rel)] += 1
    groups = sorted(by_group)
    for g in groups:
        by_group[g]["whyTracked"] = why_tracked(g)
        probe = g.rstrip("/")
        refs: list[str] = []
        while probe and not refs:
            refs = references(probe, all_files)
            probe = probe.rsplit("/", 1)[0] if "/" in probe else ""
        by_group[g]["referencedBy"] = refs[:6]
        if with_last_commit:
            r = subprocess.run(
                ["git", "log", "-1", "--format=%cs", "--", g],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
            )
            by_group[g]["lastCommitDate"] = r.stdout.strip()
    exact, prefixes = load_baseline()
    return {
        "schema": "tracked-data-exposure-report/v1",
        "scope": list(SCOPE_PREFIXES) + [f"*{e}" for e in DATA_EXTS],
        "totals": {"files": len(files), "bytes": sum(v["bytes"] for v in by_cat.values())},
        "byCategory": {k: by_cat[k] for k in sorted(by_cat)},
        "byVendor": {k: by_vendor[k] for k in sorted(by_vendor)},
        "byPathGroup": {k: by_group[k] for k in groups},
        "guardTriggerFilesByGroup": dict(sorted(guard_hits.items())),
        "baseline": {"exactPaths": len(exact), "rotatingPrefixes": list(prefixes)},
        "notes": [
            "Counts only; no identifier or vendor value is emitted.",
            "Vendor / paid classification is path-based and heuristic; owner to confirm.",
            "nameFields counts person-name fields only (username/owner/manager names); player and NFL-team names are excluded.",
            "longNumeric counts every 17-19 digit number and over-counts (timestamps, ids of any kind).",
        ],
    }


def to_markdown(rep: dict) -> str:
    def mb(b: int) -> str:
        return f"{b / 1_000_000:.1f}"

    out = ["# Tracked data exposure inventory (aggregate)", ""]
    out.append(
        f"Files in scope: {rep['totals']['files']} ({mb(rep['totals']['bytes'])} MB). Counts only; no values."
    )
    out.append("")
    hdr = "| {} | files | MB | owner/user-id fields | league-id fields | name fields | emails | 17-19 digit numbers |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|"
    for title, key in (
        ("Category", "byCategory"),
        ("Vendor", "byVendor"),
        ("Path group", "byPathGroup"),
    ):
        out += [f"## By {title.lower()}", "", hdr.format(title), sep]
        for name, v in rep[key].items():
            tag = " (paid, heuristic)" if v.get("paid") else ""
            out.append(
                f"| `{name}`{tag} | {v['files']} | {mb(v['bytes'])} | {v['ownerIds']} | {v['leagueIds']} | {v['nameFields']} | {v['emails']} | {v['longNumeric']} |"
            )
        out.append("")
    out += ["## Why path groups are tracked", ""]
    for g, v in rep["byPathGroup"].items():
        refs = ", ".join(f"`{r}`" for r in v["referencedBy"]) or "none found"
        out.append(f"- `{g}`: {v['whyTracked']}. Referenced by: {refs}")
    out += ["", "## Guard trigger files by group", ""]
    out += [f"- `{k}`: {n}" for k, n in rep["guardTriggerFilesByGroup"].items()] or ["- none"]
    out += ["", "## Notes", ""] + [f"- {n}" for n in rep["notes"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-json")
    ap.add_argument("--out-md")
    ap.add_argument("--with-last-commit", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument(
        "--changed-since",
        metavar="BASE_REF",
        help="PR mode: only files added/modified vs the merge base; exit 1 on a new offender "
        "outside the baseline (hermetic to rolling data already on main)",
    )
    args = ap.parse_args(argv)
    if args.changed_since:
        offenders = check_changed_since(args.changed_since)
        if offenders:
            print(
                "New tracked files publish owner-id-like fields or paid-vendor data (public repo):"
            )
            print("\n".join(f"  {o}" for o in offenders))
            print(
                "See docs/security/DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md; no baseline growth without the owner decision."
            )
            return 1
        print("tracked-data exposure: no new offender in this diff")
        return 0
    if args.write_baseline:
        lines = build_baseline_lines(tracked_files())
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE_PATH.relative_to(REPO)}: {len(lines)} lines")
        return 0
    rep = build_report(args.with_last_commit)
    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    md = to_markdown(rep)
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    if not (args.out_json or args.out_md):
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
