"""B8 — git is a distribution channel too.

Fixing HTTP access while the same payload ships in a public repository is
not a boundary.  ``SECURITY.md`` records that everything tracked under
``data/`` and ``exports/`` is readable by anyone, so a tracked file is a
published file.

Two leak paths, both closed here.

**The pipeline channel.**  ``scheduled-refresh.yml`` runs ``git add -f``
over whole directories every two hours, and ``-f`` overrides
``.gitignore``.  That is how ``data/ros/team_strength/<league>.json`` came
to be published despite ``.gitignore`` stating that generated
team-strength output stays ignored — 78 KB per league of ``ownerId`` +
``benchDepthScore`` + ``positionalCoverageScore`` +
``healthAvailabilityScore`` + a full ``startingLineup`` with per-player
``rosValue``.  A per-rival weakness map, and precisely the payload
``rosTeamStrength`` now requires a session for.

**The audit-evidence channel.**  This suite previously carried a
``KNOWN_STATIC_EVIDENCE`` allowlist naming three captures that "DO contain
real per-manager payloads and are deliberately committed as finding
provenance".  That is not a resolution — it is the leak, written down.
Public git audit provenance gets no exception from the privacy boundary,
so the rule is now:

    Tracked audit evidence may prove the defect, but must itself satisfy
    the public-Git privacy contract.

Both halves matter.  Deleting the captures would satisfy privacy and
destroy the ability to understand what was proven, so
``scripts/sanitize_audit_evidence.py`` pseudonymizes identity and nulls
per-manager quantities while preserving structure, field names, counts and
the strategy text the findings turn on.  W20-F002 still reads exactly as
recorded — a team at ROS strength percentile 100% labelled *Seller* — with
no real person attached.

That script owns the contract; this suite asserts it.  One definition, so
the assertion and the repair cannot drift apart.

Deliberately NOT a blanket ban on tracked data, and NOT a ban on
``ownerId``.  The repo tracks ``data/scrape_state/`` and ``exports/`` on
purpose — CLAUDE.md records that ``git rm --cached`` there would freeze
production's source_health and that deploy dispatch keys on those commit
subjects — and an owner id is the team identifier that legitimately
appears in public standings, power rankings, playoff odds, award winners
and trade grades.  The rule is about CONTENT: per-manager decision
intelligence, wherever it is.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from sanitize_audit_evidence import (  # noqa: E402
    PRIVATE_RECORD_MARKERS,
    PRIVATE_VALUE_KEYS,
    _public_league_ids,
    private_bindings,
    roster_enumerations,
)

#: Field names that only appear in per-manager decomposition — a rival's
#: roster weaknesses or their behavioural tendencies.  Used for the
#: coarse, fast scan over the pipeline-published channel; the audit tree
#: gets the structural contract instead.
PRIVATE_INTELLIGENCE_FIELDS = (
    "benchDepthScore",
    "positionalCoverageScore",
    "healthAvailabilityScore",
    "teamAggression",
)

#: The directories the refresh pipeline REPUBLISHES.  ``scheduled-refresh.yml``
#: force-adds these every two hours, so anything here is a live, ongoing
#: publication of current data — which is the channel B8 closes.
PUBLISHED_PREFIXES = ("data/", "exports/", "CSVs/")

#: Skip genuinely huge artifacts so the sweep stays a test rather than a
#: batch job.  Nothing above this is a per-manager capture: the largest is
#: the 12 MB full-contract board, which is players, not managers.
_MAX_SCAN_BYTES = 40_000_000


@lru_cache(maxsize=1)
def _tracked_files() -> tuple[str, ...]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(p for p in out.split("\0") if p)


@lru_cache(maxsize=None)
def _read(rel: str) -> str | None:
    path = REPO / rel
    try:
        if not path.is_file() or path.stat().st_size > _MAX_SCAN_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def test_no_republished_artifact_carries_per_manager_intelligence():
    """The pipeline-published channel, scanned wholesale.

    Scoped to what the refresh workflow force-adds every two hours,
    because that is the ONGOING publication.  Scanning it wholesale rather
    than one directory is the point: the next leak will not arrive through
    the path this test was written for.
    """
    offenders: list[tuple[str, list[str]]] = []
    for rel in _tracked_files():
        if not rel.endswith(".json") or not rel.startswith(PUBLISHED_PREFIXES):
            continue
        body = _read(rel)
        if body is None:
            continue
        hits = [f for f in PRIVATE_INTELLIGENCE_FIELDS if f in body]
        if hits:
            offenders.append((rel, hits))

    assert not offenders, (
        "the refresh pipeline republishes per-manager intelligence to a public "
        "repository:\n" + "\n".join(f"  {rel}: {hits}" for rel, hits in offenders[:20])
    )


def test_no_tracked_file_binds_a_manager_identity_to_their_intelligence():
    """The contract, over EVERY tracked file, with no allowlist.

    This replaces ``KNOWN_STATIC_EVIDENCE``.  Naming the three captures
    that leaked did not stop them leaking; it recorded that they did and
    called the matter closed.  A new capture committed tomorrow is now
    caught by the same rule that caught those three, which is the only
    version of this test that keeps working after the person who wrote it
    stops looking.
    """
    public_ids = _public_league_ids()
    offenders: list[tuple[str, list[str]]] = []
    for rel in _tracked_files():
        if not rel.endswith((".json", ".jsonl")):
            continue
        body = _read(rel)
        if body is None:
            continue
        try:
            docs = (
                [json.loads(body)]
                if rel.endswith(".json")
                else [json.loads(ln) for ln in body.splitlines() if ln.strip()]
            )
        except (ValueError, RecursionError):
            continue  # unparseable is a different problem than a leak
        reasons: list[str] = []
        for doc in docs:
            reasons.extend(private_bindings(doc, public_ids=public_ids))
        if reasons:
            offenders.append((rel, sorted(set(reasons))[:6]))

    assert not offenders, (
        "tracked files bind a real manager identity to that manager's decision "
        "intelligence. Audit evidence is not exempt — run\n"
        "    python scripts/sanitize_audit_evidence.py\n"
        "which pseudonymizes identity and nulls the private quantities while "
        "keeping the structure and the field names the findings assert:\n"
        + "\n".join(f"  {rel}: {why}" for rel, why in offenders[:20])
    )


def test_no_tracked_file_publishes_the_manager_roster_inline():
    """Reproduction commands enumerated every manager id in the league.

    ``for id in 1303… 1002… 8316…`` is a machine-readable roster wearing a
    shell loop.  The command's evidentiary value is its METHOD, which
    survives pseudonymization, so the ids are rewritten and the command
    still shows exactly how the finding was reproduced.
    """
    public_ids = _public_league_ids()
    offenders: list[tuple[str, str]] = []
    for rel in _tracked_files():
        body = _read(rel)
        if body is None:
            continue
        hits = roster_enumerations(body, public_ids)
        if hits:
            offenders.append((rel, hits[0]))

    assert not offenders, (
        "tracked files enumerate the league's manager roster inline:\n"
        + "\n".join(f"  {rel}: {sample}…" for rel, sample in offenders[:10])
    )


def test_the_sanitizer_is_idempotent_and_the_tree_is_clean():
    """The repair converges, and it has already been applied.

    Without this, a sanitizer that changed a file every run would keep the
    tree churning and the two tests above would still pass.
    """
    from sanitize_audit_evidence import discover_targets

    assert discover_targets() == [], (
        "scripts/sanitize_audit_evidence.py still finds work to do, so the "
        "committed tree does not satisfy the contract it enforces"
    )


def test_the_contract_can_actually_fail():
    """Guard against the guard being vacuous.

    Every scan above passes trivially if the detector stopped detecting.
    Feed it a payload shaped exactly like the leak that started this and
    require a complaint.
    """
    leak = {
        "teams": [
            {
                "ownerId": "900000000000000001",
                "displayName": "Brent",
                "teamRosStrength": 645.12,
                "benchDepthScore": 211.01,
                "startingLineup": [{"playerId": "4971", "rosValue": 27.16}],
            }
        ]
    }
    reasons = private_bindings(leak)
    assert "teamRosStrength" in reasons, "the C1 value check no longer fires"
    assert "startingLineup" in reasons, "the C2 record check no longer fires"

    # Assembled at runtime, not written out as a literal: three id-shaped
    # tokens on one source line would make THIS file a roster enumeration
    # and fail the very scan it exists to exercise. The detector cannot
    # tell a synthetic id from a real one — which is correct, and is why
    # the fixture has to be built rather than spelled.
    enumeration = "for id in " + " ".join(f"9000000000000000{n}" for n in (41, 42, 43)) + "; do"
    assert roster_enumerations(enumeration), "the roster-enumeration check no longer fires"


def test_a_public_payload_is_not_falsely_flagged():
    """The rule is semantic, not "ban ownerId".

    An award winner and a trade grade are both an ``ownerId`` beside a
    ``label``, and both are public league facts. If those started failing,
    the next person would 'fix' it by deleting public product.
    """
    award = {"key": "league_mvp", "label": "League MVP", "ownerId": "900000000000000002"}
    grade = {"transactionId": "900000000000000009", "ownerId": "900000000000000003", "grade": "A+"}
    standings = {"ownerId": "900000000000000002", "rank": 3, "playoffOdds": 1.0, "wins": 8}
    for payload in (award, grade, standings):
        assert not private_bindings(payload), f"public payload wrongly flagged: {payload}"


def test_the_evidence_still_proves_its_finding():
    """Sanitized, not gutted.

    W20-F002 is "a team at ROS strength percentile 100% was labelled
    Seller". If a future sweep nulls the percentile or the label to make
    the privacy scan quieter, the finding becomes unreadable and this says
    so — the reason the sanitizer keeps public odds and strategy text.
    """
    path = REPO / "docs/master-site-audit/evidence/W20/ros-trade-deadline.json"
    if not path.exists():
        pytest.skip("W20 trade-deadline capture not present")
    teams = json.loads(path.read_text(encoding="utf-8"))["data"]["teams"]
    assert len(teams) == 12, f"the capture no longer covers 12 managers ({len(teams)})"
    proof = [t for t in teams if t.get("rosStrengthPercentile") == 1.0]
    assert proof, "the strength percentile the finding turns on was nulled"
    assert proof[0].get("label"), "the label the finding turns on was nulled"
    assert not re.fullmatch(
        r"\d{15,20}", str(proof[0].get("ownerId", ""))
    ), "the capture still carries a real manager id"


@pytest.mark.parametrize(
    "marker",
    ("benchDepthScore", "positionalCoverageScore", "healthAvailabilityScore"),
)
def test_the_marker_actually_appears_in_the_live_artifact(marker):
    """Guard against the pipeline scan being vacuous.

    If the producer renames these fields, that scan keeps passing while
    publishing the same intelligence under new names. This fails loudly
    instead, on the untracked live file the ROS pipeline writes.
    """
    live = REPO / "data/ros/team_strength/latest.json"
    if not live.exists():
        pytest.skip("no local ROS team-strength artifact to sample")
    body = live.read_text(encoding="utf-8", errors="ignore")
    assert marker in body, (
        f"{marker!r} no longer appears in the artifact this suite protects — "
        "the producer's field names changed and the scan is now checking for "
        "something that cannot occur"
    )


def test_the_private_key_sets_are_not_empty():
    """A contract over zero field names would pass forever."""
    assert len(PRIVATE_VALUE_KEYS) >= 15, "the private-value set was emptied out"
    assert len(PRIVATE_RECORD_MARKERS) >= 4, "the private-record set was emptied out"
    for expected in ("teamRosStrength", "benchDepthScore", "avgBid", "tradePartnerFitScore"):
        assert expected in PRIVATE_VALUE_KEYS, f"{expected} dropped out of the contract"


def test_the_ros_team_strength_payload_is_not_tracked():
    """The specific artifact, pinned by path.

    The general scan above would also catch this, but a named test says
    WHICH file and why when it fails.
    """
    tracked = {p for p in _tracked_files() if p.startswith("data/ros/team_strength/")}
    payloads = {p for p in tracked if p.endswith(".json")}
    assert not payloads, (
        f"{sorted(payloads)} are tracked. Each is ~78 KB of per-manager "
        "weakness intelligence and the rosTeamStrength route now requires a "
        "session for the same payload."
    )
    # The directory itself stays in source control: .gitignore's own
    # comment says the ROS pipeline keeps the tree so a fresh checkout has
    # the layout in place.
    assert "data/ros/team_strength/.gitkeep" in tracked, (
        "the directory placeholder was removed with the payloads; a fresh "
        "checkout would lose the layout the ROS pipeline expects"
    )


def test_the_refresh_workflow_cannot_re_add_them():
    """``git add -f`` overrides ``.gitignore``.

    Ignoring the files is not enough on its own — the two-hourly refresh
    force-adds whole directories, which is how they became tracked in the
    first place.
    """
    workflow = (REPO / ".github/workflows/scheduled-refresh.yml").read_text(encoding="utf-8")
    assert "data/ros/team_strength" in workflow, (
        "scheduled-refresh.yml force-adds data/ros/ wholesale and no longer "
        "excludes team_strength — the next run will re-publish it"
    )


def test_a_public_artifact_is_not_falsely_flagged():
    """The rule is about content, not about tracking data at all.

    ``exports/`` and ``data/scrape_state/`` are tracked deliberately and
    must stay that way; CLAUDE.md records that untracking them freezes
    production's source_health and breaks deploy dispatch.
    """
    tracked = _tracked_files()
    assert any(p.startswith("exports/latest/") for p in tracked), (
        "exports/latest/ is no longer tracked — B8 was supposed to redact "
        "content, not stop publishing artifacts the pipeline depends on"
    )
    board = REPO / "exports/latest/dynasty_data.js"
    if board.exists():
        body = board.read_text(encoding="utf-8", errors="ignore")
        hits = [f for f in PRIVATE_INTELLIGENCE_FIELDS if f in body]
        assert not hits, f"the published board artifact carries {hits}"


def test_scan_is_not_silently_empty():
    """A scan over zero files would pass forever."""
    files = _tracked_files()
    assert len(files) > 100, f"git ls-files returned {len(files)} paths"
    assert any(f.endswith(".json") for f in files), "no tracked JSON found to scan"


def test_the_ros_artifacts_still_exist_on_disk():
    """Untracked, not deleted.

    ``src/ros/playoff_sim.py`` reads ``team_strength/latest.json`` from the
    filesystem, and production's deploy uses ``git reset --hard``, which
    leaves untracked files alone.  If a future change starts cleaning them,
    the private ROS surfaces go dark and this says so.
    """
    live = REPO / "data/ros/team_strength/latest.json"
    if not live.exists():
        pytest.skip("no local ROS artifact in this environment")
    payload = json.loads(live.read_text(encoding="utf-8"))
    assert payload, "team-strength artifact is present but empty"
