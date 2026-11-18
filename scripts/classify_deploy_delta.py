#!/usr/bin/env python3
"""Is a deploy target DATA_ONLY or CODE relative to the last fully validated deploy?

SHADOW MODE ONLY (audit-remediation Task 3, owner directive 2026-11-18).  This
script decides nothing on its own: ``.github/workflows/data-delivery-shadow.yml``
records its verdict beside the full Deploy Production gate's verdict.  Any path
that ships on this verdict instead of running the full code gate changes a
binding Agent OS rule (``docs/AGENT_OPERATING_SYSTEM.md`` section 3, L3 "remains
fully unconditional") and is BLOCKED on an owner decision.  Design, evidence and
the proposed amendment: ``docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md``.

THE RULE
--------
``DATA_ONLY`` if and only if

1. both commits resolve in this repository, and the base is an ancestor of
   (or equal to) the target -- a rollback or a diverged history is CODE; and
2. the CODE TREE of the target is byte-identical to the code tree of the base.

The code tree is every tracked entry EXCEPT those this module classifies as
data.  Identity is git's own: (mode, object type, object id) per path, so a
one-byte edit, a mode change (``chmod +x``), an added file and a deleted file
all change it.  Both the digest comparison and the per-path diff are computed
from the same two ``git ls-tree`` listings and must agree; if they ever
disagree the answer is CODE.

WHAT IS DATA (the reviewed allowlist)
-------------------------------------
A tracked entry is data only when ALL of these hold:

* its path starts with one of ``DATA_ROOTS`` -- ``CSVs/``, ``data/``,
  ``exports/`` (case-sensitive; these are the roots the scheduled refresh and
  the box timers commit, and that ``deploy/deploy.sh`` already treats as
  auto-managed);
* its git mode is ``100644`` -- a symlink, an executable or a submodule is
  never data;
* its basename is not in ``CODE_NAMES`` and its suffix is not in
  ``CODE_SUFFIXES`` (Python, JavaScript, shell, YAML, TOML, unit files, ...),
  unless the exact path is a reviewed ``DATA_EXCEPTIONS`` entry;
* it has no empty, ``.`` or ``..`` path component.

Everything else is CODE, including every path nobody has classified yet:
``src/``, ``server.py``, ``Dynasty Scraper.py``, ``scripts/``, ``frontend/``
(lockfiles included), ``tests/``, ``deploy/``, ``.github/``,
``requirements*``, ``package*.json``, ``pyproject.toml``, root files, docs and
ALL of ``config/``.

``config/`` is CODE in full, deliberately.  Most of it is policy the code
executes (weights, thresholds, feature flags, curves).  The automation-written
parts were reviewed and still left CODE:

* ``config/draft_valuation/*`` stores change served draft dollars when a
  promotion lands, and change rarely (no commit 2026-10-26..11-18), so being
  strict costs nothing;
* ``config/model_registry/*`` is rewritten by every Hill evidence commit, and
  every one of those commits (50 of 50 since 2026-11-01) rewrites
  ``hill_scope_masters.json`` -- the registry whose CHAMPION the contract's
  provenance stamp verifies against the live constants in
  ``src/canonical/player_valuation.py``.  A champion-invariant content rule
  could make the evidence half data; it is DEFERRED until the shadow's
  ``codePathGroups`` say how many deltas it would unlock.

Docs are CODE too: the box reads ``docs/valuation/evidence/**``,
``docs/measurements/**``, ``docs/sources/**`` and ``docs/owner/*.json``, and the
prose subset is owned by ``deploy.yml``'s ``paths-ignore`` (a deploy never
starts for it), not by this classifier.

FAIL CLOSED
-----------
An empty, malformed or unresolvable base or target, a base that is not an
ancestor of the target, an unreadable tree or any internal error is CODE with
the reason recorded.  There is no third answer.

Exit codes: 0 classified (DATA_ONLY or CODE, both are results; the receipt
says which); 2 usage error.  Writes ``classification`` to ``$GITHUB_OUTPUT``
when that variable is set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

SCHEMA = "data-delivery-classification/v1"
DATA_ONLY = "DATA_ONLY"
CODE = "CODE"

_FULL_SHA = re.compile(r"[0-9a-f]{40}")

#: Root -> why it is data.  Order is irrelevant: the roots are disjoint.
DATA_ROOTS: dict[str, str] = {
    "CSVs/": (
        "source CSVs and the draft workbook; scheduled-refresh.yml rewrites them "
        "and commits them with every automated data refresh"
    ),
    "data/": (
        "pipeline outputs and refresh state (data/scrape_state stamps, ROS output, "
        "identity/player-map fallbacks); force-added by scheduled-refresh.yml and "
        "pushed by the box timers (DLF, IDP Show, playerctx)"
    ),
    "exports/": (
        "scraper/contract exports (exports/latest payload, exports/archive zips, "
        "narratives); scheduled-refresh.yml and weekly-narratives.yml commit them"
    ),
}

#: The only mode a data entry may carry.
DATA_MODE = "100644"

#: A file under a data root with one of these suffixes is executable or
#: configuration-shaped, so it is CODE wherever it lives.  None exists today
#: (measured 2026-11-18: the 12,184 tracked entries under the three roots are
#: .json/.csv/.jsonl/.zip/.xlsx/.md, extensionless stamps, one .gitkeep and the
#: one DATA_EXCEPTIONS file).
CODE_SUFFIXES = frozenset(
    {
        ".bash",
        ".bat",
        ".cfg",
        ".cjs",
        ".cmd",
        ".conf",
        ".css",
        ".dll",
        ".exe",
        ".htm",
        ".html",
        ".ini",
        ".ipynb",
        ".js",
        ".jsx",
        ".mjs",
        ".ps1",
        ".pth",
        ".py",
        ".pyc",
        ".pyi",
        ".pyw",
        ".service",
        ".sh",
        ".so",
        ".socket",
        ".timer",
        ".toml",
        ".ts",
        ".tsx",
        ".whl",
        ".yaml",
        ".yml",
        ".zsh",
    }
)

#: Basenames that change how git checks the tree out, or how Python starts,
#: wherever they appear.
CODE_NAMES = frozenset(
    {
        ".gitattributes",
        ".gitmodules",
        "__init__.py",
        "conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
    }
)

#: Exact paths under a data root that carry a CODE_SUFFIXES suffix and were
#: reviewed as data.  Each needs its reason.
DATA_EXCEPTIONS: dict[str, str] = {
    "exports/latest/dynasty_data.js": (
        "the raw scraper export wrapped as `window.DYNASTY_DATA = {...}`, written by "
        "Dynasty Scraper.py; nothing executes or serves it (nginx serves no exports/, "
        "and frontend/app/api/dynasty-data/route.js reads no disk)"
    ),
}

#: Path groups used to summarise CODE changes in a receipt.
_GROUPED_TOP_LEVEL = frozenset(
    {".github", "config", "deploy", "docs", "frontend", "scripts", "src", "tests"}
)

_MAX_LISTED_PATHS = 200


class ClassificationError(Exception):
    """A fact the rule needs could not be established (always means CODE)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def classify_entry(path: str, mode: str) -> tuple[str, str]:
    """``("data" | "code", reason)`` for one tracked entry."""
    parts = path.split("/")
    if not path or path.startswith("/") or any(p in ("", ".", "..") for p in parts):
        return "code", "suspicious_path"
    root = next((r for r in DATA_ROOTS if path.startswith(r)), None)
    if root is None:
        return "code", "outside_data_roots"
    if mode != DATA_MODE:
        return "code", f"non_regular_mode:{mode}"
    if path in DATA_EXCEPTIONS:
        return "data", "data_exception"
    name = parts[-1]
    if name in CODE_NAMES:
        return "code", f"code_name:{name}"
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in CODE_SUFFIXES:
        return "code", f"code_suffix:{suffix}"
    return "data", f"data_root:{root}"


def path_group(path: str) -> str:
    """A stable summary bucket: ``src/api/``, ``config/model_registry/``, a root file."""
    parts = path.split("/")
    if len(parts) == 1:
        return parts[0]
    if parts[0] in _GROUPED_TOP_LEVEL and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}/"
    return f"{parts[0]}/"


def rules_document() -> dict:
    """The rule set as data, stamped (with its digest) on every receipt."""
    return {
        "dataRoots": dict(sorted(DATA_ROOTS.items())),
        "dataMode": DATA_MODE,
        "codeSuffixes": sorted(CODE_SUFFIXES),
        "codeNames": sorted(CODE_NAMES),
        "dataExceptions": dict(sorted(DATA_EXCEPTIONS.items())),
    }


def rules_digest() -> str:
    blob = json.dumps(rules_document(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── git ────────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _require_commit(repo: Path, sha: str, role: str) -> None:
    if not _FULL_SHA.fullmatch(sha or ""):
        raise ClassificationError(f"{role}_invalid", repr(sha))
    probe = _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    if probe.returncode != 0:
        raise ClassificationError(f"{role}_unavailable", sha)


def read_tree(repo: Path, sha: str) -> dict[str, tuple[str, str, str]]:
    """``path -> (mode, type, object id)`` for every entry of a commit's tree."""
    out = _git(repo, "ls-tree", "-r", "-z", "--full-tree", sha)
    if out.returncode != 0:
        raise ClassificationError("tree_unreadable", sha)
    entries: dict[str, tuple[str, str, str]] = {}
    for record in out.stdout.split(b"\0"):
        if not record:
            continue
        meta, sep, raw_path = record.partition(b"\t")
        fields = meta.decode("ascii", "replace").split(" ")
        if not sep or len(fields) != 3:
            raise ClassificationError("tree_unparseable", sha)
        entries[raw_path.decode("utf-8", "surrogateescape")] = (fields[0], fields[1], fields[2])
    if not entries:
        raise ClassificationError("tree_empty", sha)
    return entries


def is_ancestor(repo: Path, base: str, target: str) -> bool:
    if base == target:
        return True
    probe = _git(repo, "merge-base", "--is-ancestor", base, target)
    if probe.returncode == 0:
        return True
    if probe.returncode == 1:
        return False
    raise ClassificationError("ancestry_unknown", probe.stderr.decode("utf-8", "replace").strip())


# ── the rule ───────────────────────────────────────────────────────────────


def tree_digest(entries: dict[str, tuple[str, str, str]], cls: str) -> str:
    """sha256 over the ``cls`` ("code" or "data") entries of one tree."""
    digest = hashlib.sha256()
    for path in sorted(entries):
        mode, kind, obj = entries[path]
        if classify_entry(path, mode)[0] != cls:
            continue
        digest.update(f"{mode} {kind} {obj}\t".encode("ascii"))
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    return digest.hexdigest()


def changed_entries(
    base: dict[str, tuple[str, str, str]], target: dict[str, tuple[str, str, str]]
) -> list[dict]:
    """Every path whose (mode, type, object) differs, with its class.

    A path is a DATA change only when every side that exists classifies as
    data; a data file becoming executable (or vice versa) is a CODE change.
    """
    changes = []
    for path in sorted(set(base) | set(target)):
        before, after = base.get(path), target.get(path)
        if before == after:
            continue
        status = "A" if before is None else "D" if after is None else "M"
        sides = [classify_entry(path, entry[0]) for entry in (before, after) if entry]
        code_sides = [reason for cls, reason in sides if cls == "code"]
        changes.append(
            {
                "path": path,
                "status": status,
                "class": "code" if code_sides else "data",
                "reason": code_sides[0] if code_sides else sides[0][1],
            }
        )
    return changes


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda item: (-item[1], item[0])))


def classify(repo: Path, base: str, target: str, *, base_source: str = "") -> dict:
    """The classification receipt.  Never raises for a domain failure: CODE."""
    base = (base or "").strip().lower()
    target = (target or "").strip().lower()
    receipt: dict = {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "classification": CODE,
        "reasons": [],
        "base": {"sha": base or None, "source": base_source or None},
        "target": {"sha": target or None},
        "baseIsAncestor": None,
        "codeTreeDigest": None,
        "dataTreeDigest": None,
        "changed": None,
        "codePaths": [],
        "codePathGroups": {},
        "dataPathRoots": {},
        "rulesDigest": rules_digest(),
        "rules": rules_document(),
    }
    try:
        if not base:
            raise ClassificationError("base_unknown", "no fully validated deploy was resolved")
        _require_commit(repo, target, "target")
        _require_commit(repo, base, "base")
        ancestor = is_ancestor(repo, base, target)
        receipt["baseIsAncestor"] = ancestor
        base_tree, target_tree = read_tree(repo, base), read_tree(repo, target)
        code_digest = {
            "base": tree_digest(base_tree, "code"),
            "target": tree_digest(target_tree, "code"),
        }
        receipt["codeTreeDigest"] = code_digest
        receipt["dataTreeDigest"] = {
            "base": tree_digest(base_tree, "data"),
            "target": tree_digest(target_tree, "data"),
        }
        changes = changed_entries(base_tree, target_tree)
        code_changes = [c for c in changes if c["class"] == "code"]
        data_changes = [c for c in changes if c["class"] == "data"]
        receipt["changed"] = {
            "total": len(changes),
            "code": len(code_changes),
            "data": len(data_changes),
        }
        receipt["codePaths"] = code_changes[:_MAX_LISTED_PATHS]
        receipt["codePathGroups"] = _counts([path_group(c["path"]) for c in code_changes])
        receipt["dataPathRoots"] = _counts(
            [next(r for r in DATA_ROOTS if c["path"].startswith(r)) for c in data_changes]
        )
        identical = code_digest["base"] == code_digest["target"]
        if identical == bool(code_changes):
            raise ClassificationError(
                "internal_inconsistency",
                f"digests identical={identical} but {len(code_changes)} code path(s) changed",
            )
        if not ancestor:
            receipt["reasons"].append("base_not_ancestor")
        if code_changes:
            receipt["reasons"].append("code_paths_changed")
        if ancestor and identical:
            receipt["classification"] = DATA_ONLY
            receipt["reasons"].append("code_tree_identical")
    except ClassificationError as exc:
        receipt["classification"] = CODE
        receipt["reasons"].append(exc.reason)
        if exc.detail:
            receipt["errorDetail"] = exc.detail
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        receipt["classification"] = CODE
        receipt["reasons"].append("internal_error")
        receipt["errorDetail"] = f"{type(exc).__name__}: {exc}"
    return receipt


def render_text(receipt: dict) -> str:
    lines = [
        f"classification: {receipt['classification']}",
        f"reasons:        {', '.join(receipt['reasons']) or '-'}",
        f"base:           {receipt['base']['sha']} ({receipt['base']['source'] or 'source unstated'})",
        f"target:         {receipt['target']['sha']}",
    ]
    if receipt.get("errorDetail"):
        lines.append(f"detail:         {receipt['errorDetail']}")
    changed = receipt.get("changed")
    if changed:
        lines.append(
            f"changed:        {changed['total']} path(s): {changed['data']} data, {changed['code']} code"
        )
        for group, count in list(receipt["codePathGroups"].items())[:15]:
            lines.append(f"  code {count:5d}  {group}")
        for root, count in receipt["dataPathRoots"].items():
            lines.append(f"  data {count:5d}  {root}")
    lines.append(f"rules digest:   {receipt['rulesDigest']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Exit 0 with a receipt for DATA_ONLY and for CODE; 2 on usage error.",
    )
    parser.add_argument(
        "--base", default="", help="last fully validated deployed commit (full SHA)"
    )
    parser.add_argument("--target", required=True, help="deploy target commit (full SHA)")
    parser.add_argument("--base-source", default="", help="where the base SHA came from (recorded)")
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(), help="git repository (default: cwd)"
    )
    parser.add_argument("--receipt", type=Path, help="write the JSON receipt here")
    parser.add_argument("--json", action="store_true", help="print the receipt as JSON")
    args = parser.parse_args(argv)

    receipt = classify(args.repo, args.base, args.target, base_source=args.base_source)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with args.receipt.open("w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(receipt, indent=2, sort_keys=True) if args.json else render_text(receipt))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"classification={receipt['classification']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
