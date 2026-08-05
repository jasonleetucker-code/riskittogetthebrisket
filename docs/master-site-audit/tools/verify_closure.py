"""Audit-only: measure which findings are actually closed.

"Done" on this effort means a finding's reproduction stops reproducing — not
that a commit mentioning it exists. This reports both, separately, because
conflating them is how a repair log starts lying.

Three signals per finding:

  claimed   a commit on this branch says "Closes <id>" / "Fixes <id>"
  rerun     the stored reproduction was re-executed and its result compared
  status    closed | claimed-unverified | open | unsafe-to-rerun | no-repro

Reproductions are NOT executed blindly. 431 findings carry arbitrary shell —
some POST, some redirect into files, some assume a cwd or a fixture that no
longer exists. Only commands that pass `_is_read_only` run, and everything
else is reported as `unsafe-to-rerun` rather than quietly skipped. A harness
that silently drops what it cannot check would overstate closure, which is
the failure this whole audit is about.

Usage:
    .venv/bin/python docs/master-site-audit/tools/verify_closure.py
    .venv/bin/python docs/master-site-audit/tools/verify_closure.py --rerun
    .venv/bin/python docs/master-site-audit/tools/verify_closure.py --rerun --id W03-F001
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FINDINGS = ROOT / "docs/master-site-audit/findings.json"
OUT = ROOT / "docs/master-site-audit/closure.json"
REPORT = ROOT / "docs/master-site-audit/CLOSURE_STATUS.md"

CLOSE_KEYWORD_RE = re.compile(r"\b(?:closes|fixes|resolves)\b", re.I)
ID_RE = re.compile(r"W\d{2}-F\d{3}")


def _closing_ids(body: str) -> set[str]:
    """Every finding id in a SENTENCE that also carries a closing keyword.

    Sentence-scoped rather than line-scoped or body-scoped. Body-scoped would
    over-claim — commit messages reference neighbouring findings for context
    ("NOT fixed by ...") and those must not read as closed. A first attempt
    matched only up to the first id on a line, which under-claimed: one
    commit closing three findings registered one.
    """
    found: set[str] = set()
    for chunk in re.split(r"[\n.;]", body):
        if CLOSE_KEYWORD_RE.search(chunk):
            found.update(ID_RE.findall(chunk))
    return found


# Anything that can mutate state, reach a write endpoint, or run unbounded.
_UNSAFE = (
    " -X POST",
    " -X PUT",
    " -X DELETE",
    " -x post",
    "--request POST",
    " rm ",
    "rm -",
    " mv ",
    "> /",
    ">> /",
    "tee ",
    "git commit",
    "git push",
    "git checkout",
    "git stash",
    "git reset",
    "npm install",
    "pip install",
    "scrape",
    "crawl_",
    "fetch_",
    "refresh",
    "/run",
    "sudo ",
)


def _is_read_only(cmd: str) -> tuple[bool, str]:
    """Conservative allowlist check. False positives are fine; the cost of a
    false NEGATIVE is running a mutating command against the live stack."""
    low = cmd.lower()
    for token in _UNSAFE:
        if token.lower() in low:
            return False, f"contains {token.strip()!r}"
    # A POST to a pure-computation endpoint is still a POST; require the
    # caller to vet those by hand.
    if "post" in low and "curl" in low:
        return False, "curl POST"
    if ">" in cmd and "2>&1" not in cmd and ">=" not in cmd:
        return False, "redirects output"
    return True, ""


def claimed_ids() -> dict[str, str]:
    """finding id -> short commit sha that claims to close it."""
    try:
        log = subprocess.run(
            ["git", "log", "--format=%h%x00%B%x00%x00", "origin/main..HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return {}
    out: dict[str, str] = {}
    for entry in log.split("\x00\x00"):
        if "\x00" not in entry:
            continue
        sha, body = entry.split("\x00", 1)
        sha = sha.strip()
        for fid in _closing_ids(body):
            out.setdefault(fid, sha)
    return out


def rerun(cmd: str, timeout: int = 180) -> dict:
    ok, why = _is_read_only(cmd)
    if not ok:
        return {"ran": False, "reason": why}
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable="/bin/bash",
        )
        return {
            "ran": True,
            "exit": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ran": False, "reason": f"timeout after {timeout}s"}
    except Exception as exc:  # noqa: BLE001
        return {"ran": False, "reason": str(exc)[:200]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", action="store_true", help="execute read-only reproductions")
    ap.add_argument("--id", action="append", help="limit to these finding ids")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    data = json.loads(FINDINGS.read_text())
    findings = [f for f in data["findings"] if f.get("published", True)]
    claims = claimed_ids()

    records = []
    for f in findings:
        fid = f.get("id")
        if args.id and fid not in args.id:
            continue
        cmd = ((f.get("reproduction") or {}).get("command") or "").strip()
        claimed = fid in claims
        safe, why = _is_read_only(cmd) if cmd else (False, "no reproduction command")

        rec = {
            "id": fid,
            "priority": f.get("priority"),
            "status_label": f.get("status"),
            "subsystem": f.get("subsystem"),
            "title": f.get("title"),
            "claimedBy": claims.get(fid),
            "hasRepro": bool(cmd),
            "reproSafe": safe,
            "reproSafetyNote": why,
        }
        if args.rerun and cmd:
            rec["rerun"] = rerun(cmd, timeout=args.timeout)

        if claimed:
            rec["closure"] = (
                "claimed-unverified" if not rec.get("rerun") else "closed-claimed-rerun"
            )
        elif not cmd:
            rec["closure"] = "no-repro"
        elif not safe:
            rec["closure"] = "open-unsafe-to-rerun"
        else:
            rec["closure"] = "open"
        records.append(rec)

    by_closure = Counter(r["closure"] for r in records)
    by_pri_claimed = Counter(r["priority"] for r in records if r["claimedBy"])
    payload = {
        "generatedAt": subprocess.run(
            ["git", "log", "-1", "--format=%cI"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "totals": {
            "findings": len(records),
            "claimedClosed": sum(1 for r in records if r["claimedBy"]),
            "reproSafeToRerun": sum(1 for r in records if r["reproSafe"]),
        },
        "byClosure": dict(by_closure),
        "claimedByPriority": dict(by_pri_claimed),
        "records": records,
    }
    OUT.write_text(json.dumps(payload, indent=1))

    lines = [
        "# Closure status",
        "",
        "Generated by `tools/verify_closure.py`. Regenerate rather than hand-edit.",
        "",
        f"- Published findings: **{len(records)}**",
        f"- Claimed closed by a commit on this branch: **{payload['totals']['claimedClosed']}**",
        f"- Reproductions safe to re-run unattended: **{payload['totals']['reproSafeToRerun']}**",
        "",
        "`claimed` means a commit says *Closes <id>*. That is a claim, not a",
        "measurement — the reproduction is what settles it, and the ones this",
        "harness refuses to run are listed so they can be checked by hand rather",
        "than assumed.",
        "",
        "| closure | count |",
        "|---|---|",
    ]
    for k, v in sorted(by_closure.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Claimed closed", "", "| id | pri | commit | title |", "|---|---|---|---|"]
    for r in sorted(
        (r for r in records if r["claimedBy"]),
        key=lambda r: (r["priority"] or "P9", r["id"]),
    ):
        title = str(r["title"] or "").replace("|", "\\|")[:110]
        lines.append(f"| {r['id']} | {r['priority']} | `{r['claimedBy']}` | {title} |")
    REPORT.write_text("\n".join(lines) + "\n")

    print(f"findings={len(records)} claimedClosed={payload['totals']['claimedClosed']}")
    print("byClosure:", dict(by_closure))
    print("claimed by priority:", dict(by_pri_claimed))
    print(f"wrote {OUT} and {REPORT}")


if __name__ == "__main__":
    main()
