"""B8 — git is a distribution channel too.

Fixing HTTP access while the same payload ships in a public repository
is not a boundary.  ``SECURITY.md`` records that everything tracked
under ``data/`` and ``exports/`` is readable by anyone, so a tracked
file is a published file.

This suite inspects the INDEX rather than any one handler, because the
leak path it guards is not an endpoint: ``scheduled-refresh.yml`` runs
``git add -f`` over whole directories every two hours, and ``-f``
overrides ``.gitignore``.  That is how
``data/ros/team_strength/<league>.json`` came to be published despite
``.gitignore`` stating that generated team-strength output stays
ignored — 78 KB per league of ``ownerId`` + ``benchDepthScore`` +
``positionalCoverageScore`` + ``healthAvailabilityScore`` + a full
``startingLineup`` with per-player ``rosValue``.  A per-rival weakness
map, and precisely the payload ``rosTeamStrength`` now requires a
session for.

Deliberately NOT a blanket ban on tracked data.  The repo tracks
``data/scrape_state/`` and ``exports/`` on purpose — CLAUDE.md records
that ``git rm --cached`` there would freeze production's source_health
and that deploy dispatch keys on those commit subjects.  The rule is
about CONTENT: per-manager decision intelligence, wherever it is.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Field names that only appear in per-manager decomposition — a
#: rival's roster weaknesses or their behavioural tendencies.
#:
#: ``ownerId`` is deliberately absent: it is the team identifier, and it
#: legitimately appears in public standings, power rankings and playoff
#: odds.  Banning it would fail on genuinely public artifacts and teach
#: the next reader that the rule is about identifiers rather than about
#: intelligence.
PRIVATE_INTELLIGENCE_FIELDS = (
    "benchDepthScore",
    "positionalCoverageScore",
    "healthAvailabilityScore",
    "teamAggression",
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


#: The directories the refresh pipeline REPUBLISHES.  ``scheduled-refresh.yml``
#: force-adds these every two hours, so anything here is a live, ongoing
#: publication of current data — which is the channel B8 closes.
PUBLISHED_PREFIXES = ("data/", "exports/", "CSVs/")

#: Static audit captures that DO contain real per-manager payloads and are
#: deliberately committed as finding provenance.  Named rather than silently
#: excluded, because narrowing a privacy rule without saying so is how the
#: rule stops meaning anything:
#:
#:   docs/master-site-audit/evidence/W17/sec-rosTeamStrength.json  63,686 B
#:   docs/master-site-audit/evidence/W11/faab-analytics.json       86,899 B
#:   docs/master-site-audit/findings.json                       2,021,317 B
#:      (embeds ``numericProof.inputs.ownerId`` in finding records —
#:       the audit's own database, and the provenance of the findings
#:       this whole programme is executing against)
#:
#: These are one-off snapshots of a past date, not a live feed, and editing
#: them changes an audit record rather than a product surface — a judgement
#: about the audit, not a code fix.  Carried in the B-series backlog.
KNOWN_STATIC_EVIDENCE = (
    "docs/master-site-audit/evidence/W17/sec-rosTeamStrength.json",
    "docs/master-site-audit/evidence/W11/faab-analytics.json",
    "docs/master-site-audit/findings.json",
)


def test_no_republished_artifact_carries_per_manager_intelligence():
    """The pipeline-published channel, scanned wholesale.

    Scoped to what the refresh workflow force-adds every two hours,
    because that is the ONGOING publication.  Scanning it wholesale
    rather than one directory is the point: the next leak will not
    arrive through the path this test was written for.
    """
    offenders: list[tuple[str, list[str]]] = []
    for rel in _tracked_files():
        if not rel.endswith(".json"):
            continue
        if not rel.startswith(PUBLISHED_PREFIXES):
            continue
        path = REPO / rel
        try:
            if path.stat().st_size > 20_000_000:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = [f for f in PRIVATE_INTELLIGENCE_FIELDS if f in body]
        if hits:
            offenders.append((rel, hits))

    assert not offenders, (
        "the refresh pipeline republishes per-manager intelligence to a public "
        "repository:\n" + "\n".join(f"  {rel}: {hits}" for rel, hits in offenders[:20])
    )


def test_the_known_static_evidence_captures_have_not_grown():
    """The exception is bounded and visible, not a hole.

    If a NEW documentation file starts carrying real per-manager
    payloads, this fails — the carve-out covers two named audit
    captures, not "anything under docs/".
    """
    offenders: list[str] = []
    for rel in _tracked_files():
        if not rel.endswith(".json") or rel.startswith(PUBLISHED_PREFIXES):
            continue
        if rel in KNOWN_STATIC_EVIDENCE:
            continue
        path = REPO / rel
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Field NAMES appear legitimately in findings text and config
        # baselines.  A real payload is the pairing of the field with a
        # numeric owner id.
        if not re.search(r'"ownerId"\s*:\s*"\d{6,}"', body):
            continue
        if any(f in body for f in PRIVATE_INTELLIGENCE_FIELDS):
            offenders.append(rel)
    assert not offenders, (
        "new tracked documentation carries real per-manager payloads: " f"{offenders}"
    )


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
    # comment says the ROS pipeline keeps the tree so a fresh checkout
    # has the layout in place.
    assert "data/ros/team_strength/.gitkeep" in tracked, (
        "the directory placeholder was removed with the payloads; a fresh "
        "checkout would lose the layout the ROS pipeline expects"
    )


def test_the_refresh_workflow_cannot_re_add_them():
    """``git add -f`` overrides ``.gitignore``.

    Ignoring the files is not enough on its own — the two-hourly refresh
    force-adds whole directories, which is how they became tracked in
    the first place.
    """
    workflow = (REPO / ".github/workflows/scheduled-refresh.yml").read_text(encoding="utf-8")
    assert "data/ros/team_strength" in workflow, (
        "scheduled-refresh.yml force-adds data/ros/ wholesale and no longer "
        "excludes team_strength — the next run will re-publish it"
    )


@pytest.mark.parametrize(
    "marker",
    ("benchDepthScore", "positionalCoverageScore", "healthAvailabilityScore"),
)
def test_the_marker_actually_appears_in_the_live_artifact(marker):
    """Guard against the guard being vacuous.

    If the producer renames these fields, the scan above keeps passing
    while publishing the same intelligence under new names.  This fails
    loudly instead, on the untracked live file the ROS pipeline writes.
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

    ``src/ros/playoff_sim.py`` reads ``team_strength/latest.json`` from
    the filesystem, and production's deploy uses ``git reset --hard``,
    which leaves untracked files alone.  If a future change starts
    cleaning them, the private ROS surfaces go dark and this says so.
    """
    live = REPO / "data/ros/team_strength/latest.json"
    if not live.exists():
        pytest.skip("no local ROS artifact in this environment")
    payload = json.loads(live.read_text(encoding="utf-8"))
    assert payload, "team-strength artifact is present but empty"
