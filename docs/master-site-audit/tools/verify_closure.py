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
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FINDINGS = ROOT / "docs/master-site-audit/findings.json"
OUT = ROOT / "docs/master-site-audit/closure.json"
REPORT = ROOT / "docs/master-site-audit/CLOSURE_STATUS.md"
CLAIMS_FROZEN = ROOT / "docs/master-site-audit/claims-frozen-2026-08-05.json"

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


def _claims_from_range(rev_range: str) -> dict[str, str]:
    """finding id -> short commit sha, scanned from a git revision range."""
    try:
        log = subprocess.run(
            ["git", "log", "--format=%h%x00%B%x00%x00", rev_range],
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


class EvidenceLedgerError(RuntimeError):
    """A load-bearing evidence file is missing, unreadable or malformed.

    Raised instead of degrading to an empty mapping. Losing the ledger and
    losing the claims must not look the same to a caller — that equivalence
    is the exact failure this harness exists to prevent.
    """


# Explicit operator opt-out. Passing one of these says "run with no
# historical claims, I mean it" — as opposed to the file having gone
# missing, which is an accident and must fail.
_NO_LEDGER_SENTINELS = frozenset({"/dev/null", "nul", "none", ""})


def _is_explicit_opt_out(path: Path | None) -> bool:
    return path is None or str(path).strip().lower() in _NO_LEDGER_SENTINELS


def load_required_claim_ledger(path: Path | None) -> dict[str, str]:
    """finding id -> sha, from a frozen claims ledger. FAILS CLOSED.

    The ledger exists because the claim signal is not durable. Claims are
    read out of commit BODIES, and the 85 commits that carried them were
    squash-merged (PR #722): they are unreachable from ``main`` and their
    trailers do not survive in the squash commit. A range scan alone
    therefore reports zero and would overwrite the only surviving
    finding -> commit map with nothing.

    This function previously swallowed ``OSError`` and ``JSONDecodeError``
    into ``{}``, which recreated that very failure: a deleted or truncated
    ledger silently became "there were no claims". Measured on the real
    tree, pointing it at a missing path took claims 86 -> 2 and moved 84
    findings from claimed to open, exit 0, both outputs rewritten.

    So: missing, unreadable, malformed JSON, or malformed structure all
    raise. Only an EXPLICIT opt-out (``/dev/null``, ``none``) returns an
    empty mapping, because that is an operator stating intent rather than
    an accident.
    """
    if _is_explicit_opt_out(path):
        return {}
    assert path is not None  # narrowed by _is_explicit_opt_out
    try:
        raw = path.read_text()
    except FileNotFoundError as exc:
        raise EvidenceLedgerError(
            f"claims ledger not found: {path}\n"
            "This file is load-bearing — the claiming commits were squash-merged "
            "and a range scan alone reports zero. Refusing to publish a closure "
            "ledger that would silently drop every historical claim.\n"
            "If you genuinely want no historical claims, pass --claims-file /dev/null."
        ) from exc
    except OSError as exc:
        raise EvidenceLedgerError(f"claims ledger unreadable: {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceLedgerError(
            f"claims ledger is not valid JSON: {path}: {exc}\n"
            "Refusing to treat a corrupt ledger as an absence of claims."
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
        raise EvidenceLedgerError(
            f"claims ledger has the wrong shape: {path}\n"
            "Expected an object with a 'claims' array. A structurally valid file "
            "with zero claims is fine; a file that does not carry the key at all "
            "is indistinguishable from corruption, so it fails."
        )

    out: dict[str, str] = {}
    for row in payload["claims"]:
        if not isinstance(row, dict):
            continue
        fid, sha = row.get("id"), row.get("claimedBy")
        if fid and sha:
            out[fid] = sha
    return out


def load_existing_ledger_records(path: Path) -> list[dict]:
    """The published ledger's records, for a filtered run to merge onto.

    FAILS CLOSED for the same reason as the claims ledger, and it is the
    same defect wearing different clothes: a filtered ``--id`` run builds
    ``records`` from the requested ids only, so if the prior ledger cannot
    be read, treating it as ``[]`` lets the subset BECOME the full ledger.
    Measured: with a truncated closure.json, ``--id W10-F002`` replaced 431
    records with 1 and exited 0.
    """
    try:
        raw = path.read_text()
    except FileNotFoundError as exc:
        raise EvidenceLedgerError(
            f"cannot merge a filtered run onto a ledger that does not exist: {path}\n"
            "Run without --id to publish a full ledger first."
        ) from exc
    except OSError as exc:
        raise EvidenceLedgerError(f"existing ledger unreadable: {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceLedgerError(
            f"existing ledger is not valid JSON: {path}: {exc}\n"
            "A filtered update cannot safely proceed without a valid full ledger — "
            "merging onto nothing would publish only the filtered subset."
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise EvidenceLedgerError(
            f"existing ledger has the wrong shape: {path}\nExpected an object with a 'records' array."
        )
    return payload["records"]


def merge_filtered_records(previous: list[dict], records: list[dict]) -> list[dict]:
    """Apply a filtered run's records onto the full ledger.

    Requested ids update in place; every other record is preserved
    untouched. Ids new to the ledger are appended.
    """
    updated = {r["id"]: r for r in records}
    merged = [updated.pop(r["id"], r) for r in previous]
    merged.extend(updated.values())
    return merged


def classify_closure(*, claimed: bool, run: dict | None, has_repro: bool, safe: bool) -> str:
    """The closure bucket for one finding. Pure — no I/O, no globals.

    Extracted so the regression suite can exercise THIS function rather
    than a copy of its rules living in a test. A mirrored implementation
    stays green while production drifts, which for an evidence-preserving
    tool is the worst possible place for that to happen.
    """
    if claimed:
        run = run or {}
        if not run:
            return "claimed-unverified"
        if not run.get("ran") or run.get("exit") != 0:
            # The reproduction did not complete. That is NOT closure
            # evidence — it is usually the repro itself being broken (a
            # missing fixture, a dead path), and it may equally be the
            # defect back. Either way it needs a human.
            return "claimed-rerun-failed"
        # Exit 0 means the command RAN, not that the defect is gone: this
        # harness never compares stdout against the finding's `expected`.
        # Adjudication is manual, and the bucket name has to say so or the
        # count reads as proof.
        return "claimed-rerun-needs-adjudication"
    if not has_repro:
        return "no-repro"
    if not safe:
        return "open-unsafe-to-rerun"
    return "open"


def claimed_ids(rev_range: str, claims_file: Path | None) -> dict[str, str]:
    """finding id -> short commit sha that claims to close it.

    Union of the frozen ledger and a live range scan, range winning: a
    finding re-claimed by current work should point at the commit a
    reader can actually check out. A claim is still only a claim — the
    reproduction is what settles closure.
    """
    claims: dict[str, str] = dict(load_required_claim_ledger(claims_file))
    claims.update(_claims_from_range(rev_range))
    return claims


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
    ap.add_argument(
        "--range",
        dest="rev_range",
        default="origin/main..HEAD",
        help="git revision range scanned for 'Closes W##-F###' trailers",
    )
    ap.add_argument(
        "--claims-file",
        type=Path,
        default=CLAIMS_FROZEN,
        help="frozen id->sha ledger merged under the range scan (pass /dev/null to skip)",
    )
    # Overridable I/O so the regression suite can drive the REAL tool
    # against temporary fixtures and temporary outputs, and assert on
    # actual exit codes and actual files.
    ap.add_argument("--findings", type=Path, default=FINDINGS, help="findings.json to read")
    ap.add_argument("--out", type=Path, default=OUT, help="closure.json to write")
    ap.add_argument("--report", type=Path, default=REPORT, help="CLOSURE_STATUS.md to write")
    args = ap.parse_args()

    # Resolve every evidence input BEFORE writing anything. A failure here
    # must leave the last known-good outputs exactly as they were.
    try:
        claims = claimed_ids(args.rev_range, args.claims_file)
        previous_records = load_existing_ledger_records(args.out) if args.id else []
    except EvidenceLedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("wrote nothing; existing outputs left untouched.", file=sys.stderr)
        raise SystemExit(2) from exc

    data = json.loads(args.findings.read_text())
    findings = [f for f in data["findings"] if f.get("published", True)]

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

        rec["closure"] = classify_closure(
            claimed=claimed,
            run=rec.get("rerun"),
            has_repro=bool(cmd),
            safe=safe,
        )
        records.append(rec)

    if args.id:
        # A filtered run reports on a few findings; it must not PUBLISH a
        # few findings. Merge onto the existing ledger, which was loaded
        # and validated above — if it could not be read, we already
        # exited rather than treating it as empty and letting the subset
        # become the whole ledger.
        records = merge_filtered_records(previous_records, records)

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
    args.out.write_text(json.dumps(payload, indent=1))

    lines = [
        "# Closure status",
        "",
        "Generated by `tools/verify_closure.py`. Regenerate rather than hand-edit.",
        "",
        f"- Published findings: **{len(records)}**",
        f"- Claimed closed by a commit: **{payload['totals']['claimedClosed']}**",
        f"- Reproductions safe to re-run unattended: **{payload['totals']['reproSafeToRerun']}**",
        "",
        "`claimed` means a commit says *Closes <id>*. That is a claim, not a",
        "measurement — the reproduction is what settles it, and the ones this",
        "harness refuses to run are listed so they can be checked by hand rather",
        "than assumed.",
        "",
        f"Claims come from `{args.rev_range}` merged over the frozen ledger",
        "`claims-frozen-2026-08-05.json`. The ledger is load-bearing: the 85",
        "commits that carried the original trailers were squash-merged with",
        "PR #722 and are unreachable from `main`, so a range scan alone reports",
        "zero. A claim's sha may therefore name a commit that is no longer",
        "checkout-able — it identifies the work, not a reviewable diff.",
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
    args.report.write_text("\n".join(lines) + "\n")

    print(f"findings={len(records)} claimedClosed={payload['totals']['claimedClosed']}")
    print("byClosure:", dict(by_closure))
    print("claimed by priority:", dict(by_pri_claimed))
    print(f"wrote {args.out} and {args.report}")


if __name__ == "__main__":
    main()
