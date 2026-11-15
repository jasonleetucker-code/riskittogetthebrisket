"""CW-40 Batch S (security / auth / ops / test integrity) -- findings still OPEN or PARTIAL (2026-11-07).

Each strict xfail states the CORRECT behaviour and flips (XPASS strict -> failure) the moment the
defect is repaired, so the marker must then be deleted in the repair PR.  Everything is offline
and deterministic: stub news provider, source-shape scans, ``git ls-files``, the workflow YAML.

* W21-F003  REPAIRED: roster news filters by the roster's player names (tests below are plain passes).
* W24-F001  no union skip census (characterization); the executed/skip floor gate now exists (sharded hard gate).
* W24-F002  the 22 ``test_real_rosters.py`` tests skip: an input file they need is untracked.
* W24-F004  ``e2e.yml`` sets ``SKIP_VISUAL_REGRESSION=1`` and the specs skip the whole describe.
* W20-F006  three team-direction classifiers remain reachable (was four; ``scoreTeamTiers`` gone).
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STRICT = {"strict": True, "raises": AssertionError}


# --------------------------------------------------------------------------- W21-F003
def _news_service_with_one_player_item():
    from src.news.base import NewsItem, NewsProvider, PlayerMention
    from src.news.service import NewsService

    class _Static(NewsProvider):
        name = "static"
        label = "Static"

        def fetch(self, *, player_names=None, limit=50):
            return [
                NewsItem(
                    id="n1",
                    ts=datetime.now(timezone.utc).isoformat(),
                    provider="static",
                    provider_label="Static",
                    severity="info",
                    kind="news",
                    headline="Josh Allen limited in practice",
                    players=[PlayerMention(name="Josh Allen", position="QB", team="BUF")],
                )
            ]

    return NewsService([_Static()])


def test_w21_f003_control_unfiltered_gather_returns_the_item():
    from src.api.terminal import gather_news_items

    svc = _news_service_with_one_player_item()
    items = gather_news_items(lambda: svc, ["Josh Allen"], None)
    assert [i["id"] for i in items] == ["n1"]


def test_w21_f003_resolved_fantasy_team_does_not_empty_the_news_feed():
    from src.api.terminal import gather_news_items

    svc = _news_service_with_one_player_item()
    items = gather_news_items(lambda: svc, ["Josh Allen"], "Jason")
    assert [i["id"] for i in items] == ["n1"], "authenticated roster view received no news"


def test_w21_f003_roster_filter_uses_player_names_not_team_name():
    from src.api.terminal import gather_news_items, roster_player_names

    svc = _news_service_with_one_player_item()
    team = {"name": "Jason", "players": ["Josh Allen", "Bijan Robinson"]}
    roster = roster_player_names(team)
    assert roster == ["Josh Allen", "Bijan Robinson"]
    kept = gather_news_items(lambda: svc, ["Josh Allen"], "Jason", roster_player_names=roster)
    assert [i["id"] for i in kept] == ["n1"]
    dropped = gather_news_items(
        lambda: svc, ["Josh Allen"], "Jason", roster_player_names=["Bijan Robinson"]
    )
    assert dropped == []
    assert roster_player_names(None) is None and roster_player_names({"players": []}) is None


# --------------------------------------------------------------------------- W24-F001
_UNION = re.compile(
    r"pytest\.skip\(|self\.skipTest\(|pytest\.mark\.skipif|unittest\.skipIf|unittest\.skipUnless|"
    r"skipIf\(|pytest\.mark\.skip\b|@unittest\.skip\b"
)
_NAIVE = re.compile(r"pytest\.skip\(|pytest\.mark\.skipif")


def _census(pattern):
    total = 0
    for path in (REPO / "tests").rglob("*.py"):
        if path.name == Path(__file__).name:
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            total += bool(pattern.search(line))
    return total


def test_w24_f001_characterization_naive_census_undercounts():
    """The August claim, re-measured: a ``pytest.skip(``-only census misses unittest-style sites."""
    naive, union = _census(_NAIVE), _census(_UNION)
    assert union > naive + 50, (naive, union)


def test_w24_f001_python_suite_has_an_executed_or_skip_floor_gate():
    """W24-F001's gate half, CLOSED by the sharded hard gate (2026-11-07).

    Was a strict xfail: nothing compared executed tests with collected ones,
    so a skipped test was byte-identical to a passing one.  ``Validate PR`` now
    runs ``scripts/ci_test_shards.py verify``, which fails on a collection
    floor breach, a suite-wide skip-budget overrun, or a selected test with no
    verdict.  The behaviour itself is pinned in
    ``tests/scripts/test_ci_test_shards.py``; this test pins the wiring.  The
    finding's OTHER half — a union skip-site census — is still open and is
    characterized above.
    """
    import json

    import yaml

    wf = yaml.safe_load((REPO / ".github" / "workflows" / "pr-validation.yml").read_text("utf-8"))
    aggregator = next(j for j in wf["jobs"].values() if j.get("name") == "Validate PR")
    runs = "\n".join(step.get("run") or "" for step in aggregator.get("steps") or [])
    assert "scripts/ci_test_shards.py verify" in runs
    config = json.loads((REPO / "config" / "ci" / "test_shards.json").read_text("utf-8"))
    assert int(config["min_collected"]) > 10_000
    assert 0 < int(config["max_skipped"]) < int(config["min_collected"])


# --------------------------------------------------------------------------- W24-F002
def _tracked(rel: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
    except OSError:
        pytest.skip("git unavailable")
    return out.returncode == 0


def test_w24_f002_two_of_three_inputs_are_tracked_now():
    """Progress since August: the Sleeper snapshot and ROS aggregate are committed."""
    assert _tracked("data/sleeper_last_good.json")
    assert _tracked("data/ros/aggregate/latest.json")


@pytest.mark.xfail(
    reason="W24-F002 OPEN: tests/roster_intel/test_real_rosters.py also reads "
    "data/public_league/nfl_players_full.json (gitignored, absent in CI) and pytest.skips all "
    "22 'constant masquerading as a score' tests; the advisory livedata step cannot run them either",
    **STRICT,
)
def test_w24_f002_every_input_of_the_real_roster_variation_guards_is_tracked():
    from tests.roster_intel import test_real_rosters as mod

    missing = [
        str(p.relative_to(REPO))
        for p in (mod.SLEEPER, mod.AGGREGATE, mod.NFL_DUMP)
        if not _tracked(str(p.relative_to(REPO)))
    ]
    assert missing == [], f"untracked inputs make the 22 tests skip: {missing}"


# --------------------------------------------------------------------------- W24-F004
def _e2e_sets_skip_visual() -> bool:
    import yaml

    doc = yaml.safe_load((REPO / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if "SKIP_VISUAL_REGRESSION" in (step.get("env") or {}):
                return True
    return False


def _spec_skips_whole_describe(rel: str) -> bool:
    src = (REPO / "tests" / "e2e" / "specs" / rel).read_text(encoding="utf-8")
    return bool(
        re.search(r"test\.describe\([^\n]*\n\s*test\.skip\(\s*!!process\.env\.SKIP_VISUAL", src)
    )


def test_w24_f004_characterization_both_visual_specs_skip_their_whole_describe():
    assert _spec_skips_whole_describe("chart-visual-regression.spec.js")
    assert _spec_skips_whole_describe("public-league-visual.spec.js")


@pytest.mark.xfail(
    reason="W24-F004 OPEN: e2e.yml sets SKIP_VISUAL_REGRESSION=1 and each visual spec skips its "
    "ENTIRE describe on it, so the structural assertions the workflow comment says still run "
    "never execute (13 tests)",
    **STRICT,
)
def test_w24_f004_ci_does_not_skip_the_structural_visual_assertions():
    skips_everything = _e2e_sets_skip_visual() and (
        _spec_skips_whole_describe("chart-visual-regression.spec.js")
        or _spec_skips_whole_describe("public-league-visual.spec.js")
    )
    assert not skips_everything


# --------------------------------------------------------------------------- W20-F006
def _classifier_owners() -> list[str]:
    owners = []
    if re.search(r"function\s+classifyPhase\b", _read("frontend/lib/team-phase.js")):
        owners.append("frontend/lib/team-phase.js::classifyPhase")
    if re.search(r"def\s+classify_team\b", _read("src/ros/direction.py")):
        owners.append("src/ros/direction.py::classify_team")
    if re.search(r"def\s+competitive_posture\b", _read("src/roster_intel/window.py")):
        owners.append("src/roster_intel/window.py::competitive_posture")
    return owners


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_w20_f006_scoreTeamTiers_is_gone_so_four_is_now_three():
    assert not re.search(
        r"(function|const)\s+scoreTeamTiers\b|export\s*\{[^}]*scoreTeamTiers",
        _read("frontend/lib/league-analysis.js"),
    )
    assert len(_classifier_owners()) == 3


@pytest.mark.xfail(
    reason="W20-F006 PARTIAL / REQUIRES_OWNER_DECISION: Win-now/Contender/Mixed/Rebuild "
    "(/phases, client 2x2 median split), PUSH/HOLD/RETOOL/REBUILD (roster_intel window) and the "
    "ROS Buyer/Seller labels (ros/direction) still ship side by side with no reconciliation",
    **STRICT,
)
def test_w20_f006_one_team_direction_classifier_is_reachable():
    assert len(_classifier_owners()) == 1, _classifier_owners()


# --------------------------------------------------------------------------- W25-F010
def test_w25_f010_finder_idp_claim_was_fixed_after_the_audited_sha():
    """The one head-to-head contradiction resolves on chronology: the IDP fix is NOT an ancestor
    of the SHA the 08-04 audit read, and the routing is pinned today."""
    try:
        res = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "a62af217", "9c5d972f"],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
    except OSError:
        pytest.skip("git unavailable")
    if res.returncode not in (0, 1):
        pytest.skip("shallow clone: audited SHAs not present")
    assert res.returncode == 1
    assert (REPO / "tests" / "trade" / "test_finder_idp_routing.py").is_file()


@pytest.mark.xfail(
    reason="W25-F010 PARTIAL: the reconciliation verdict is verified, but the recommended header "
    "cross-references (object audited + SHA + pointer to the other audit) were never added",
    **STRICT,
)
def test_w25_f010_each_audit_header_points_at_the_other():
    a = _read("docs/audits/complete-codebase-audit-2026-07-29.md")[:1500]
    b = _read("docs/audits/decision-intelligence-audit-2026-08-04.md")[:1500]
    assert "decision-intelligence-audit-2026-08-04" in a
    assert "complete-codebase-audit-2026-07-29" in b
