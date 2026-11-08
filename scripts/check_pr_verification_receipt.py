#!/usr/bin/env python3
"""Enforce the PR "Feature verification receipt" (CW-53, owner directive 2026-11-07).

A material PR (one that changes runtime code or config) must carry a filled
``## Feature verification receipt`` section in its body.  See
docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md section 4 step 9
and the "PR verification receipt check" subsection.

This is NOT a validation-risk classifier (that is scripts/ci_change_scope.py);
"material" here only decides whether a receipt is required.

Protected methodology (owner master directive 2026-11-08, Priority 4): a PR
that changes a file listed in ``config/ci/protected_methodology_paths.json``
(owner-reserved valuation / forecasting / activation state) must also carry a
``Methodology authorization:`` line in the receipt, citing the owner decision
or ``n/a — <reason>`` stating why no methodology, value or activation changes.
The check names the touched concepts either way so review cannot miss them.

Exit codes: 0 pass (or exempt / not material), 1 receipt incomplete, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_change_scope  # noqa: E402  (single owner of high-risk path knowledge)

EXEMPT_AUTHORS = ("dependabot[bot]", "github-actions[bot]")

MATERIAL_PREFIXES = (
    "src/",
    "frontend/",
    "deploy/",
    "config/",
    ".github/workflows/",
    "scripts/",
)
MATERIAL_EXACT = ("server.py", "Dynasty Scraper.py")
NOT_MATERIAL_PREFIXES = ("frontend/__tests__/", "scripts/research/")
MANIFEST_RE = re.compile(
    r"(^|/)(requirements[^/]*\.(txt|in)|pyproject\.toml|package(-lock)?\.json)$"
)
NA_FORBIDDEN = ("intended", "commands", "state")
TEST_FILE_RE = re.compile(r"(^|/)[^/]*\.(test|spec)\.[^/]+$")
TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__)/")

# (key, human label, accepted label prefixes, lower-cased)
FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("intended", "Intended behavior and prohibited behavior", ("intended behavior",)),
    (
        "requirement",
        "Controlling owner requirement / spec + clause",
        ("controlling owner requirement",),
    ),
    ("livepath", "Live path and canonical owner", ("live path", "live implementation path")),
    ("baseline", "Baseline before the change", ("baseline",)),
    ("oracle", "Independent oracle (or provisional)", ("independent oracle",)),
    (
        "cases",
        "Positive / negative / edge / missing / stale cases",
        ("positive / negative", "positive/negative", "cases covered"),
    ),
    ("regression", "Regression tests protecting existing behavior", ("regression tests",)),
    ("commands", "Exact test commands and outcomes", ("test commands", "exact test commands")),
    (
        "limitations",
        "Remaining unverified behavior and gaps",
        ("remaining unverified", "remaining limitations"),
    ),
    ("rollback", "Production impact and rollback", ("production impact",)),
    ("review", "Independent review and exact-tree validation", ("independent review",)),
    ("state", "State", ("state",)),
)

PLACEHOLDER_FRAGMENTS = (
    "latest owner requirement / spec + clause",
    "route / flag / audience",
    "the reproducing test failed on the old code?",
    "hand-computed, host truth, reference implementation, frozen fixture",
    "tested_in_pr / merged / deployed / verified_in_production",
    "(each with evidence; never inferred)",
)
PLACEHOLDER_EXACT = {
    "tbd",
    "todo",
    "...",
    "…",
    "-",
    "none yet",
    "fill in",
    "fill me",
    "?",
    "n/a",
    "na",
    "none",
}
NA_RE = re.compile(r"^n/?a\b\s*[-–—:]*\s*(.*)$", re.I | re.S)
STATE_WORDS = ("TESTED_IN_PR", "MERGED", "DEPLOYED", "VERIFIED_IN_PRODUCTION")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
SECTION_TITLE = "feature verification receipt"

PROTECTED_MANIFEST = (
    Path(__file__).resolve().parents[1] / "config" / "ci" / "protected_methodology_paths.json"
)
METHODOLOGY_LABEL = "Methodology authorization"
_METHODOLOGY_RE = re.compile(
    r"^\s{0,1}(?:[-*+]|\d+[.)])\s+(?:\*\*)?methodology authorization(?:\*\*)?\s*:(?:\*\*)?\s*(.*)$",
    re.I,
)


class ManifestError(ValueError):
    """The protected-methodology manifest is missing, unreadable or empty."""


def load_protected_paths(path: Path | None = None) -> list[tuple[str, str]]:
    """``[(pattern, concept)]`` from the manifest.  Missing, unreadable or EMPTY
    is a ``ManifestError`` (exit 2 in ``main``), never a silent pass: an empty
    list would protect nothing."""
    target = path or PROTECTED_MANIFEST
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        entries = [(str(e["pattern"]), str(e.get("concept") or "")) for e in data["paths"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"protected methodology manifest unreadable: {target}: {exc}") from exc
    if not entries or any(not pattern for pattern, _ in entries):
        raise ManifestError(f"protected methodology manifest lists no usable paths: {target}")
    return entries


def protected_hits(files: list[str], protected: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """``[(file, concept)]`` for every changed file that is protected."""
    hits = []
    for f in files:
        p = f.replace("\\", "/")
        if p.startswith("./"):
            p = p[2:]
        for pattern, concept in protected:
            if (pattern.endswith("/") and p.startswith(pattern)) or p == pattern:
                hits.append((p, concept))
                break
    return hits


def methodology_problem(section: str | None) -> str | None:
    """Why the receipt's methodology line is missing or empty, or ``None``."""
    if section is None:
        return f"{METHODOLOGY_LABEL}: field missing (receipt section missing)"
    # Same reading rules as ``parse_fields``: a line inside a fenced block is
    # never a field, and continuation lines join the value until the next
    # bullet or fence.
    value: list[str] | None = None
    in_fence = False
    for line in section.split("\n"):
        if _is_fence(line):
            in_fence = not in_fence
            if value is not None:
                break
            continue
        if in_fence:
            continue
        if value is None:
            m = _METHODOLOGY_RE.match(line)
            if m:
                value = [m.group(1)]
            continue
        if re.match(r"^\s{0,1}(?:[-*+]|\d+[.)])\s+", line):
            break
        value.append(line)
    if value is None:
        return f"{METHODOLOGY_LABEL}: field missing"
    value = "\n".join(value).strip()
    problem = field_problem("methodology", value)
    return f"{METHODOLOGY_LABEL}: {problem}" if problem else None


def is_material_path(path: str) -> bool:
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if p.startswith(NOT_MATERIAL_PREFIXES) or TEST_FILE_RE.search(p):
        return False
    if p.startswith("tests/"):
        return False
    if p in MATERIAL_EXACT or p.startswith(MATERIAL_PREFIXES):
        return True
    # Dependency/build manifests, workflows, migrations etc. are material too.
    return ci_change_scope._matches_high_risk(p) or bool(MANIFEST_RE.search(p))


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return bool(TEST_PATH_RE.search(p) or TEST_FILE_RE.search(p))


def _is_fence(line: str) -> bool:
    t = line.lstrip()
    return t.startswith("```") or t.startswith("~~~")


def _field_key(label: str) -> str | None:
    norm = re.sub(r"\s+", " ", label.strip().strip("*_ ").lower())
    for k, _human, prefixes in FIELDS:
        if any(norm.startswith(p) for p in prefixes):
            return k
    return None


def extract_section(body: str) -> str | None:
    lines = body.replace("\r\n", "\n").split("\n")
    start = None
    level = 0
    in_fence = False
    for i, line in enumerate(lines):
        if _is_fence(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else HEADING_RE.match(line)
        if m and m.group(1).strip().lower().startswith(SECTION_TITLE):
            start = i + 1
            level = len(line.lstrip()) - len(line.lstrip().lstrip("#"))
            break
    if start is None:
        return None
    out = []
    in_fence = False
    for line in lines[start:]:
        if _is_fence(line):
            in_fence = not in_fence
            out.append(line)
            continue
        m = None if in_fence else HEADING_RE.match(line)
        if m and (len(line.lstrip()) - len(line.lstrip().lstrip("#"))) <= level:
            break
        out.append(line)
    return "\n".join(out)


def parse_fields(section: str) -> dict[str, str]:
    """Map each bullet label to its value; continuation lines join the value."""
    items: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in section.split("\n"):
        if _is_fence(line):
            in_fence = not in_fence
            if items:
                items[-1][1].append(line)
            continue
        m = None
        if not in_fence:
            m = re.match(
                r"^( {0,1})(?:[-*+]|\d+[.)])\s+(?:\*\*)?(.+?)(?:\*\*)?\s*:(?:\*\*)?\s*(.*)$", line
            )
        if m and _field_key(m.group(2)):
            items.append((m.group(2), [m.group(3)]))
        elif items:
            items[-1][1].append(line)
    parsed: dict[str, str] = {}
    for label, vals in items:
        key = _field_key(label)
        if key and key not in parsed:
            parsed[key] = "\n".join(vals).strip()
    return parsed


def field_problem(key: str, value: str | None) -> str | None:
    if value is None:
        return "field missing"
    v = re.sub(r"<!--.*?-->", "", value, flags=re.S).strip()
    low = v.lower()
    if not v:
        return "empty"
    if low in PLACEHOLDER_EXACT and not NA_RE.match(v):
        return "placeholder text"
    if any(f in low for f in PLACEHOLDER_FRAGMENTS):
        return "template placeholder text left in place"
    na = NA_RE.match(v)
    if na:
        if key in NA_FORBIDDEN:
            return "n/a is not allowed for this field"
        reason = na.group(1).strip()
        if len(re.findall(r"[A-Za-z0-9]+", reason)) < 3:
            return "n/a needs a reason of at least a few words"
        return None
    if key == "state" and not any(s in v.upper().replace(" ", "_") for s in STATE_WORDS):
        return "must name a state: " + " / ".join(STATE_WORDS)
    return None


def evaluate(body: str) -> list[str]:
    section = extract_section(body or "")
    if section is None:
        return ["missing section: '## Feature verification receipt'"]
    parsed = parse_fields(section)
    problems = []
    na_count = 0
    for key, human, _ in FIELDS:
        p = field_problem(key, parsed.get(key))
        if p:
            problems.append(f"{human}: {p}")
        elif NA_RE.match(re.sub(r"<!--.*?-->", "", parsed.get(key) or "", flags=re.S).strip()):
            na_count += 1
    if na_count * 2 > len(FIELDS):
        problems.append(
            f"too many n/a fields ({na_count} of {len(FIELDS)}); at most half may be n/a"
        )
    return problems


def classify(files: list[str]) -> str:
    """'material' | 'tests_only' | 'other'."""
    if any(is_material_path(f) for f in files):
        return "material"
    if files and any(is_test_path(f) for f in files):
        return "tests_only"
    return "other"


def run(
    body: str,
    files: list[str],
    author: str,
    protected: list[tuple[str, str]] | None = None,
) -> tuple[int, str]:
    if author in EXEMPT_AUTHORS:
        return 0, f"EXEMPT: author '{author}' is an automated-refresh account; no receipt required."
    hits = protected_hits(files, protected if protected is not None else load_protected_paths())
    if hits:
        notice = [
            "PROTECTED METHODOLOGY touched (owner-reserved; config/ci/protected_methodology_paths.json):"
        ]
        notice += [f"  - {f} — {concept}" for f, concept in hits]
        problem = methodology_problem(extract_section(body or ""))
        code, report = _run_receipt(body, files)
        if problem:
            return 1, "\n".join(
                [
                    *notice,
                    f"FAIL: {problem}. Cite the owner decision that authorizes the change, or",
                    "`n/a — <reason>` stating that no methodology, canonical value or activation state changes.",
                    "",
                    report,
                ]
            )
        return code, "\n".join([*notice, f"{METHODOLOGY_LABEL}: stated.", "", report])
    return _run_receipt(body, files)


def _run_receipt(body: str, files: list[str]) -> tuple[int, str]:
    kind = classify(files)
    if kind == "other":
        return (
            0,
            "NOT MATERIAL: no runtime code/config changed (docs, data, exports and similar); no receipt required.",
        )
    if kind == "tests_only":
        msg = "ADVISORY: tests-only change; a receipt is not required but a short one is welcome."
        problems = evaluate(body)
        if problems:
            msg += "\n(Receipt incomplete: " + "; ".join(problems) + ")"
        return 0, msg
    problems = evaluate(body)
    mat = [f for f in files if is_material_path(f)]
    head = f"Material PR ({len(mat)} runtime/config file(s), e.g. {mat[0]})."
    if not problems:
        return 0, head + "\nPASS: Feature verification receipt is complete."
    lines = [
        head,
        "FAIL: Feature verification receipt is incomplete. Edit the PR body; this check re-runs automatically.",
        "",
    ]
    lines += [f"- {p}" for p in problems]
    lines += [
        "",
        "Use `n/a — <reason>` for a field that genuinely does not apply.",
        "Template: .github/pull_request_template.md; standard: docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md",
    ]
    return 1, "\n".join(lines)


def _load_event(path: str) -> tuple[str, str, str, str]:
    with open(path, encoding="utf-8") as fh:
        ev = json.load(fh)
    pr = ev.get("pull_request") or {}
    return (
        pr.get("body") or "",
        (pr.get("user") or {}).get("login", ""),
        (pr.get("base") or {}).get("sha", ""),
        (pr.get("head") or {}).get("sha", ""),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--body-file")
    ap.add_argument("--files-from", help="file with one changed path per line ('-' for stdin)")
    ap.add_argument("--base")
    ap.add_argument("--head")
    ap.add_argument("--author")
    args = ap.parse_args(argv)

    body, author, base, head = "", "", "", ""
    ev_path = os.environ.get("GITHUB_EVENT_PATH")
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    elif ev_path and os.path.exists(ev_path):
        body, author, base, head = _load_event(ev_path)
    else:
        print("error: need --body-file or GITHUB_EVENT_PATH", file=sys.stderr)
        return 2
    author = args.author or author
    base = args.base or base
    head = args.head or head

    if args.files_from:
        src = sys.stdin if args.files_from == "-" else open(args.files_from, encoding="utf-8")
        files = [ln.strip() for ln in src.read().splitlines() if ln.strip()]
    elif base and head:
        r = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"error: git diff failed: {r.stderr.strip()}", file=sys.stderr)
            return 2
        files = [ln for ln in r.stdout.splitlines() if ln.strip()]
    else:
        print("error: need --files-from or --base/--head", file=sys.stderr)
        return 2

    try:
        code, report = run(body, files, author)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## PR verification receipt\n\n" + report + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
