#!/usr/bin/env python3
"""Make tracked audit evidence satisfy the B8 privacy contract.

WHY
---
B8's ruling is literal: **git is a distribution channel**, and a tracked
file in a public repository is a published file.  "It is audit evidence"
is not an exemption.  Captures under ``docs/master-site-audit/`` are real
``/api/public/league`` and ``/api/gameplan`` payloads carrying real
``ownerId`` values, real manager names, and the exact per-manager
decomposition — bench depth, positional holes, bidding behaviour,
per-rival trade-acceptance estimates — that the HTTP routes now require a
session for.  Publishing them in the repository would have made that gate
decorative.

The evidence still has to work.  These captures are the provenance of the
findings this programme executes against, so deleting them would destroy
the ability to understand what was proven.  What carries the evidentiary
weight is the SHAPE and the PAIRING: which fields the payload exposed, how
many managers it covered, how deep the lineups went, and — for a finding
like W20-F002 — that a team at strength percentile 100% was labelled
*Seller*.  None of that needs a real person attached.

THE CONTRACT
------------
**No tracked file may bind a real manager identity to that manager's
decision intelligence.**  One sentence, two checkable halves:

* **C1 — values.**  No identity bound to a private per-manager QUANTITY
  (bench depth, bidding aggression, per-rival fit scores).
* **C2 — records.**  No identity bound to a private per-manager STRUCTURE
  (a strategy recommendation, a bid history, a starting lineup).

This is the semantic boundary from CLAUDE.md §5 applied to a second
channel — deliberately NOT a field-name denylist and deliberately NOT a
ban on ``ownerId``.  An owner id is the team identifier and legitimately
appears in public standings, power rankings, playoff odds, award winners
and trade grades; banning it would fail on genuinely public artifacts and
teach the next reader that the rule is about identifiers rather than about
intelligence.  Measured against the live tree, the contract clears
``evidence/W19/public-league-full.json`` (award labels) and
``evidence/W22/public-trade-grade-census.json`` (trade grades) while
catching every real per-manager payload.

Separately, and narrowly: reproduction commands that **enumerate the
league's whole manager roster** (``for id in 1303… 1002… 8316…``) publish
a machine-readable roster.  The command's evidentiary value is its METHOD,
which survives pseudonymization, so those inline ids are rewritten too.

WHAT THIS DOES
--------------
* **Identifiers** become deterministic, non-reversible pseudonyms —
  ``owner-<sha256(id)[:12]>``.  Deterministic so one manager stays one
  pseudonym across files and reruns, which keeps cross-file joins in the
  evidence intact; non-reversible because a reversible mapping is the data
  with extra steps.
* **Names and avatars** become ``Manager NN`` / ``Team NN``, keyed off the
  pseudonym so they stay internally consistent.
* **Private per-manager VALUES are nulled, keeping their KEY.**  A key
  with ``null`` still proves the field was in the payload, which is what
  the findings assert; the magnitude is the intelligence.  Nulling matters
  even after pseudonymization, because rank, playoff odds and championship
  odds are *public* — so a raw decomposition table can be re-identified by
  joining on them.  Removing only the names would not have been enough.
* **Strategy TEXT is kept** (``label``, ``summary``, ``recommendation``,
  methodology ``notes``).  It is a small closed vocabulary repeated across
  teams, it is derived from the public odds it sits beside, it carries no
  per-manager quantity once identity and numbers are gone, and it is the
  half of W17-F00x / W20-F002 that proves the defect.
* **Structure, counts, nesting, field names, contract version, and
  public-equivalent fields** (rank, percentile, playoff/championship odds)
  are preserved exactly.
* **Nothing is rewritten unless a field actually changed** — the contract
  is content, not formatting, so a clean file is never reflowed.

Idempotent: sanitizing an already-sanitized file is a no-op, so this runs
in CI or by hand without churn.

    python scripts/sanitize_audit_evidence.py --check   # report only
    python scripts/sanitize_audit_evidence.py           # rewrite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Keys whose VALUE is a manager identifier.
IDENTIFIER_KEYS = frozenset({"ownerId", "owner_id", "userId", "user_id"})

#: Keys whose value names a real person or their team, inside a manager
#: record.  Scoped to manager records so a player's ``name`` is untouched.
NAME_KEYS = frozenset(
    {"displayName", "display_name", "teamName", "currentTeamName", "managerName", "name"}
)

#: Keys carrying a real avatar hash — an identifier by another route.
AVATAR_KEYS = frozenset({"avatar", "avatarUrl"})

#: C1 — per-manager QUANTITIES: the numbers that let one manager scout a
#: rival.
#:
#: Deliberately excludes rank, playoffOdds, championshipOdds and
#: rosStrengthPercentile.  Those are the genuinely public league-wide facts
#: served by rosPower / rosPlayoffOdds / rosChampionship, and nulling them
#: would shrink the public product to satisfy a rule that never asked for
#: it.
PRIVATE_VALUE_KEYS = frozenset(
    {
        # ROS team-strength decomposition (rosTeamStrength)
        "teamRosStrength",
        "startingLineupScore",
        "benchDepthScore",
        "positionalCoverageScore",
        "healthAvailabilityScore",
        "lineupScore",
        "rosValue",
        "adjustedValue",
        "confidence",
        # FAAB bidding behaviour (faabAnalytics)
        "totalSpent",
        "avgBid",
        "maxBid",
        "winningCount",
        "totalCount",
        "bid",
        # Per-rival trade targeting (gameplan)
        "tradePartnerFitScore",
        "tradeAcceptanceEstimate",
        "partnerNeedAlignment",
        "partnerWindowAlignment",
        "acceptanceConfidence",
        "zScore",
        "gain",
    }
)

#: C2 — per-manager STRUCTURES.  An object carrying an identity AND one of
#: these is a private manager record even when every number in it is
#: public, which is exactly the ``rosTradeDeadline`` shape: playoff odds
#: (public) beside a buy/sell recommendation (private).
#:
#: ``recommendation`` rather than ``label``/``summary`` is the marker on
#: purpose — award names and trade grades are also a ``label`` beside an
#: ``ownerId``, and those are public.
PRIVATE_RECORD_MARKERS = frozenset(
    {
        "recommendation",
        "teamAggression",
        "playerHistory",
        "startingLineup",
        "managerEvidence",
        "strategy",
    }
)

#: Keys that mark the object they sit in as ONE manager's record, so the
#: private keys below them are that manager's rather than a coincidence of
#: field naming.
_MANAGER_RECORD_KEYS = IDENTIFIER_KEYS

#: A marker stamped on sanitized JSON captures so a reader can tell a
#: sanitized capture from a raw one without guessing.  Informational only:
#: the CONTRACT is the content, checked directly, because a leaky file
#: could carry a marker just as easily.
SANITIZED_MARKER = "_sanitized"

_SANITIZED_NOTE = {
    "by": "scripts/sanitize_audit_evidence.py",
    "why": (
        "B8 — git is a distribution channel. Manager identifiers are deterministic "
        "non-reversible pseudonyms and per-manager intelligence values are nulled "
        "with their keys kept, so this capture still proves which fields the payload "
        "exposed, how many managers it covered and how deep it went. Public "
        "league-wide facts (rank, odds, percentile) and the strategy text the "
        "findings turn on are preserved."
    ),
}

#: A pseudonym this script already produced.  Matching it is what makes the
#: pass idempotent: without it, a rerun pseudonymizes the pseudonym and the
#: labels drift every time.
_PSEUDONYM_RE = re.compile(r"^owner-[0-9a-f]{12}$")
_LABEL_RE = re.compile(r"^(Manager|Team) \d{2}$")

#: Sleeper manager ids are 15-20 digit strings.  Narrow on purpose:
#: matching shorter runs would rewrite roster ids, player ids and seasons.
#:
#: The lookarounds exclude a decimal point as well as a digit, because
#: ``\b`` alone matches INSIDE a float — ``-0.03823660069932731`` carries a
#: 17-digit run, and a measurement file full of correlation coefficients
#: would otherwise read as a roster enumeration.
_ID_RE = re.compile(r"(?<![\d.])\d{15,20}(?![\d.])")

#: Inline ids are only rewritten in strings long enough to be prose or a
#: command, so a bare id-shaped value under an unrelated key (a Sleeper
#: transaction id) is not collaterally rewritten.
_TEXT_MIN_LEN = 25

#: How many DISTINCT real manager ids in one string make it a roster
#: enumeration rather than an incidental mention.  Measured against the
#: live tree: at 3 it selects exactly the six audit registries whose
#: reproduction commands loop over the league's managers, and nothing else.
_ROSTER_ENUMERATION_MIN = 3


def _public_league_ids() -> frozenset[str]:
    """Sleeper LEAGUE ids, the same shape as manager ids and NOT to be
    rewritten: they are already tracked in the league registry and
    ``SECURITY.md`` accepts them.  Read from the registry rather than
    hard-coded, so a new league cannot silently start being pseudonymized.
    """
    try:
        doc = json.loads((ROOT / "config/leagues/registry.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — absence just means "assume none"
        return frozenset()
    ids: set[str] = set()
    for league in doc.get("leagues", []):
        for key in ("sleeperLeagueId", "rootLeagueId"):
            if league.get(key):
                ids.add(str(league[key]).strip())
        for historical in league.get("historicalLeagueIds") or []:
            ids.add(str(historical).strip())
    return frozenset(ids)


def pseudonym(raw: Any) -> str:
    """Deterministic, non-reversible stand-in for one identifier."""
    digest = hashlib.sha256(str(raw).encode("utf-8")).hexdigest()[:12]
    return f"owner-{digest}"


def _label(pseudo: str, kind: str) -> str:
    """A short readable label derived from the pseudonym.

    Stable per manager, so a reader can still follow "the same team"
    through a document without learning who it is.
    """
    n = int(pseudo.split("-", 1)[1][:4], 16) % 100
    return f"{kind} {n:02d}"


def _is_private_number(value: Any) -> bool:
    """A quantity, not a flag.

    ``bool`` is a subclass of ``int``, so a plain ``isinstance(value,
    (int, float))`` would null a ``flagged: true`` and turn a stated fact
    into a missing one — the same trap ``league_config_is_complete``
    rejects ``bool`` for.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_manager_id(value: Any, public_ids: frozenset[str] = frozenset()) -> bool:
    text = str(value)
    return text.isdigit() and 15 <= len(text) <= 20 and text not in public_ids


# --------------------------------------------------------------------------
# The contract.  Shared with tests/api/test_tracked_artifacts_privacy.py so
# the assertion and the repair cannot drift apart: the test asserts this
# returns empty, the repair below is what makes it so.
# --------------------------------------------------------------------------


def private_bindings(node: Any, *, public_ids: frozenset[str] | None = None) -> list[str]:
    """Every place a real manager identity is bound to that manager's
    decision intelligence.  Empty means the file satisfies the contract."""
    ids = _public_league_ids() if public_ids is None else public_ids
    found: list[str] = []

    def walk(node: Any, in_record: bool) -> None:
        if isinstance(node, dict):
            here = in_record or any(
                key in _MANAGER_RECORD_KEYS and is_manager_id(value, ids)
                for key, value in node.items()
            )
            if here:
                found.extend(key for key in node if key in PRIVATE_RECORD_MARKERS)
            for key, value in node.items():
                if is_manager_id(key, ids):
                    # An id-keyed map is per-manager by construction.
                    walk(value, True)
                    continue
                if here and key in PRIVATE_VALUE_KEYS and _is_private_number(value):
                    found.append(key)
                else:
                    walk(value, here)
        elif isinstance(node, list):
            for value in node:
                walk(value, in_record)

    walk(node, False)
    return found


def roster_enumerations(text: str, public_ids: frozenset[str] | None = None) -> list[str]:
    """Strings that enumerate the league's manager roster inline."""
    ids = _public_league_ids() if public_ids is None else public_ids
    hits: list[str] = []
    for chunk in re.findall(r"[^\"\n]{%d,}" % _TEXT_MIN_LEN, text):
        distinct = {m for m in _ID_RE.findall(chunk) if m not in ids}
        if len(distinct) >= _ROSTER_ENUMERATION_MIN:
            hits.append(chunk[:80])
    return hits


# --------------------------------------------------------------------------
# Repair
# --------------------------------------------------------------------------


def _sanitize_text(value: str, public_ids: frozenset[str], changed: list[str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in public_ids:
            return token
        changed.append("inline-id")
        return pseudonym(token)

    return _ID_RE.sub(_sub, value)


def sanitize(
    node: Any,
    *,
    changed: list[str],
    public_ids: frozenset[str],
    in_record: bool = False,
) -> Any:
    """Walk a decoded JSON document, returning the sanitized copy."""
    if isinstance(node, dict):
        # ``is_manager_record`` is THIS object; ``here`` includes anything
        # nested beneath one.  Names use the former and values the latter,
        # and the difference is load-bearing: a manager's name always sits
        # beside their ownerId, but ``rosValue`` sits a level down in
        # ``startingLineup[]`` and ``bid`` two levels down in
        # ``playerHistory``.  Pseudonymizing names on the inherited flag
        # renamed every PLAYER under a team to "Manager NN" — evidence
        # corruption, caught on the 2 MB W19 capture.
        is_manager_record = any(
            key in _MANAGER_RECORD_KEYS and is_manager_id(value, public_ids)
            for key, value in node.items()
        )
        here = in_record or is_manager_record
        out: dict[str, Any] = {}
        for key, value in node.items():
            # An identifier used as a KEY (faabAnalytics.teamAggression).
            new_key = key
            child_in_record = here
            if is_manager_id(key, public_ids):
                new_key = pseudonym(key)
                child_in_record = True
                changed.append("id-key")

            if key in IDENTIFIER_KEYS and is_manager_id(value, public_ids):
                out[new_key] = pseudonym(value)
                changed.append(key)
            elif key in NAME_KEYS and isinstance(value, str) and _LABEL_RE.match(value):
                # Already a label from a previous run — leave it, or the
                # pass is not idempotent and the labels drift every time.
                out[new_key] = value
            elif is_manager_record and key in NAME_KEYS and isinstance(value, str) and value:
                owner = next(
                    (
                        node[k]
                        for k in IDENTIFIER_KEYS
                        if k in node and is_manager_id(node[k], public_ids)
                    ),
                    value,
                )
                kind = "Team" if "team" in key.lower() else "Manager"
                out[new_key] = _label(pseudonym(owner), kind)
                changed.append(key)
            elif is_manager_record and key in AVATAR_KEYS and value:
                out[new_key] = None
                changed.append(key)
            elif here and key in PRIVATE_VALUE_KEYS and _is_private_number(value):
                # Key kept, value dropped: the field's PRESENCE is the
                # evidence, its magnitude is the intelligence.
                out[new_key] = None
                changed.append(key)
            else:
                out[new_key] = sanitize(
                    value,
                    changed=changed,
                    public_ids=public_ids,
                    in_record=child_in_record,
                )
        return out
    if isinstance(node, list):
        return [
            sanitize(value, changed=changed, public_ids=public_ids, in_record=in_record)
            for value in node
        ]
    if isinstance(node, str) and len(node) >= _TEXT_MIN_LEN:
        return _sanitize_text(node, public_ids, changed)
    return node


def _dump(doc: Any, original: str) -> str:
    """Re-serialize preserving the original file's formatting.

    A capture written minified stays minified: reflowing 2 MB of JSON would
    bury the sanitization in a whole-file diff nobody can review.
    """
    if "\n" not in original.strip():
        return json.dumps(doc, separators=(",", ":"), sort_keys=False)
    return json.dumps(doc, indent=1, sort_keys=False) + "\n"


def process(path: Path, *, check_only: bool) -> tuple[bool, int]:
    """Returns ``(needed_change, fields_touched)``."""
    original = path.read_text(encoding="utf-8")
    public_ids = _public_league_ids()
    changed: list[str] = []

    if path.suffix == ".json":
        doc = json.loads(original)
        out = sanitize(doc, changed=changed, public_ids=public_ids)
        if not changed:
            return False, 0
        if isinstance(out, dict):
            out[SANITIZED_MARKER] = _SANITIZED_NOTE
        new_text = _dump(out, original)
    elif path.suffix == ".jsonl":
        lines = []
        for line in original.splitlines():
            if not line.strip():
                lines.append(line)
                continue
            lines.append(
                json.dumps(
                    sanitize(json.loads(line), changed=changed, public_ids=public_ids),
                    separators=(",", ":"),
                    sort_keys=False,
                )
            )
        if not changed:
            return False, 0
        new_text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    else:
        # Prose, reproduction scripts, probe output: inline ids only.
        new_text = _sanitize_text(original, public_ids, changed)
        if not changed:
            return False, 0

    needed = new_text != original
    if needed and not check_only:
        path.write_text(new_text, encoding="utf-8")
    return needed, len(changed)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p]


def violations(path: Path, public_ids: frozenset[str]) -> list[str]:
    """Why this file fails the contract, or an empty list."""
    try:
        if path.stat().st_size > 40_000_000:
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    reasons = [f"roster enumeration: {c}" for c in roster_enumerations(text, public_ids)]
    if path.suffix in (".json", ".jsonl"):
        try:
            docs = (
                [json.loads(text)]
                if path.suffix == ".json"
                else [json.loads(ln) for ln in text.splitlines() if ln.strip()]
            )
        except Exception:  # noqa: BLE001 — unparseable is not this tool's problem
            docs = []
        for doc in docs:
            reasons.extend(private_bindings(doc, public_ids=public_ids))
    return reasons


def discover_targets() -> list[Path]:
    """Every tracked file that violates the contract.

    Discovered rather than listed, so a NEW capture cannot be committed
    without either being clean or being caught.
    """
    public_ids = _public_league_ids()
    targets: list[Path] = []
    for rel in tracked_files():
        path = ROOT / rel
        if path.is_file() and violations(path, public_ids):
            targets.append(path)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report without rewriting")
    parser.add_argument("paths", nargs="*", help="override the discovered target list")
    args = parser.parse_args()

    targets = [Path(p).resolve() for p in args.paths] or discover_targets()
    dirty = 0
    for path in targets:
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            continue
        needed, count = process(path, check_only=args.check)
        state = (
            "WOULD SANITIZE" if (needed and args.check) else ("sanitized" if needed else "clean")
        )
        print(f"{state:15s} {path.relative_to(ROOT)}  ({count} fields touched)")
        dirty += 1 if needed else 0

    if not targets:
        print("no tracked file violates the B8 evidence privacy contract")
    if args.check and dirty:
        print(f"\n{dirty} file(s) carry unsanitized manager data", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
