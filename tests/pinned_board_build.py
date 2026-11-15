"""Build the committed PINNED BOARD fixture (``tests/fixtures/pinned_board/board.zip``).

WHY THIS EXISTS
───────────────
``tests.archive_fixtures.newest_complete_*`` pick the NEWEST complete archived
scrape, and ``build_api_data_contract(payload)`` with ``csv_root=None`` reads
TODAY'S ``CSVs/site_raw`` and ``data/scrape_state``.  A blocking test built
that way is a function of the latest data refresh: a team that traded away
its picks, a provider gone stale, or one CSV row moving froze production
deploys five times in three weeks (PRs #2172, #2199 and the three before).

The pinned board is ONE complete board's full inputs, frozen together:

* ``raw_payload.json`` — the archived scraper payload (pseudonymized, below);
* ``tree/CSVs/site_raw/*.csv`` — every source CSV as it stood in the SAME
  refresh commit (archives carry only ~10 of the 30, which is why passing an
  archive's own ``site_raw`` as ``csv_root`` broke ``test_single_curve_live``);
* ``tree/data/scrape_state/*`` — the dataset-state / last-success / seasonal
  stamps the build reads for freshness and voting status;
* ``manifest.json`` — provenance (source commit, archive, as-of) and a sha256
  per file, verified on every extraction.

A contract built from it with ``csv_root`` = the extracted ``tree`` and the
clock frozen to the board's own as-of reads nothing from the live tree.

PRIVACY
───────
The repository is public.  The fixture carries no Sleeper user id, league id,
draft id, manager display name or team name: every one is replaced with a
labelled synthetic stand-in, consistently, everywhere it appears (team rows,
pick labels ``"(from X)"``, ``fromTeam``, trade sides).  NFL player names and
Sleeper PLAYER ids are public reference data and stay.  The build REFUSES to
write a fixture in which any original identifier survives.

REFRESH
───────
    python -m tests.pinned_board_build --commit <refresh-commit-sha> \\
        --archive dynasty_export_<stamp>.zip

Use the scheduled-refresh commit that ADDED the archive, so the CSVs and state
are the ones that board was built from.  Refreshing the pin is a reviewed
change like any other fixture: tests on the pinned board assert facts about
THIS board, so expect to re-derive any pinned-board expectations.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "pinned_board"
FIXTURE_ZIP = FIXTURE_DIR / "board.zip"

SCHEMA_VERSION = 1

#: ``data/scrape_state`` files the contract build reads (measured with an
#: ``open`` audit hook over a full build: the per-source dataset state, the
#: last-success stamp and the seasonal-inactivity record).  Nothing else in
#: that directory is read by the build.
_STATE_FILE_RE = re.compile(r"^[A-Za-z0-9_]+(_dataset\.json|_last_success|_seasonal\.json)$")

#: Synthetic identifiers.  Digits only, so anything that parses a Sleeper id
#: as an integer still can; the ``9`` prefix and the run of zeros make them
#: unmistakable for real ones.
SYNTHETIC_LEAGUE_ID = "900000000000000000"
SYNTHETIC_ID_PREFIX = "9000000000000"
SYNTHETIC_LEAGUE_NAME = "Pinned Board League"


def manager_name(roster_id: int) -> str:
    return f"Manager {int(roster_id):02d}"


def team_name(roster_id: int) -> str:
    return f"Team {int(roster_id):02d}"


def _git_bytes(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
    ).stdout


def _git_ls(commit: str, path: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", commit, "--", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


# ── Pseudonymization ───────────────────────────────────────────────────────


class _Pseudonymizer:
    """One consistent real → synthetic mapping for a payload's ``sleeper`` block."""

    def __init__(self, sleeper: dict[str, Any]) -> None:
        self.names: dict[str, str] = {}
        self.ids: dict[str, str] = {}
        teams = sleeper.get("teams") or []
        for team in teams:
            rid = int(team["roster_id"])
            if team.get("name"):
                self.names[str(team["name"])] = manager_name(rid)
            if team.get("sleeperTeamName"):
                self.names[str(team["sleeperTeamName"])] = team_name(rid)
            if team.get("ownerId"):
                self.ids[str(team["ownerId"])] = f"{SYNTHETIC_ID_PREFIX}1{rid:04d}"
        if sleeper.get("leagueId"):
            self.ids[str(sleeper["leagueId"])] = SYNTHETIC_LEAGUE_ID
        # Trade sides can name a manager who has since left the league; give
        # every one a stable stand-in too (ordered, so the build is repeatable).
        extra_owner_ids: set[str] = set()
        extra_names: set[str] = set()
        extra_leagues: set[str] = set()
        for trade in sleeper.get("trades") or []:
            if trade.get("leagueId"):
                extra_leagues.add(str(trade["leagueId"]))
            for side in trade.get("sides") or []:
                if side.get("ownerId"):
                    extra_owner_ids.add(str(side["ownerId"]))
                if side.get("team"):
                    extra_names.add(str(side["team"]))
        evidence = sleeper.get("draftClassEvidence") or {}
        for lid in evidence.get("draftListsObserved") or []:
            extra_leagues.add(str(lid))
        if evidence.get("sleeperLeagueId"):
            extra_leagues.add(str(evidence["sleeperLeagueId"]))
        drafts = [str(d.get("draftId")) for d in evidence.get("drafts") or [] if d.get("draftId")]
        for i, oid in enumerate(sorted(extra_owner_ids - set(self.ids)), start=1):
            self.ids[oid] = f"{SYNTHETIC_ID_PREFIX}2{i:04d}"
        for i, name in enumerate(sorted(extra_names - set(self.names)), start=1):
            self.names[name] = f"Former Manager {i:02d}"
        for i, lid in enumerate(sorted(extra_leagues - set(self.ids)), start=1):
            self.ids[lid] = f"{SYNTHETIC_ID_PREFIX}3{i:04d}"
        for i, did in enumerate(sorted(set(drafts) - set(self.ids)), start=1):
            self.ids[did] = f"{SYNTHETIC_ID_PREFIX}4{i:04d}"
        # Longest first, so "(from Rage Against The Achane )" is never
        # half-replaced by a shorter name it contains.
        self._from_re = (
            re.compile(
                r"\(from ("
                + "|".join(re.escape(n) for n in sorted(self.names, key=len, reverse=True))
                + r")\)"
            )
            if self.names
            else None
        )

    def label(self, text: Any) -> Any:
        """A pick label / asset string: replace every ``(from <name>)``."""
        if not isinstance(text, str) or self._from_re is None:
            return text
        return self._from_re.sub(lambda m: f"(from {self.names[m.group(1)]})", text)

    def name(self, value: Any) -> Any:
        if isinstance(value, str) and value in self.names:
            return self.names[value]
        return self.label(value)

    def ident(self, value: Any) -> Any:
        if value is None:
            return value
        return self.ids.get(str(value), value)


def pseudonymize_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """``(payload, counts)`` with every manager/team/league identifier replaced.

    Mutates and returns ``payload``.  ``counts`` says how many values of each
    kind were replaced (recorded in the manifest).
    """
    sleeper = payload.get("sleeper")
    if not isinstance(sleeper, dict):
        return payload, {}
    ps = _Pseudonymizer(sleeper)
    counts = {"managers": 0, "teams": 0, "ownerIds": 0, "leagueIds": 0, "draftIds": 0}
    sleeper["leagueId"] = ps.ident(sleeper.get("leagueId"))
    counts["leagueIds"] += 1
    if sleeper.get("leagueName"):
        sleeper["leagueName"] = SYNTHETIC_LEAGUE_NAME
    for team in sleeper.get("teams") or []:
        rid = int(team["roster_id"])
        if team.get("name"):
            team["name"] = manager_name(rid)
            counts["managers"] += 1
        if team.get("sleeperTeamName"):
            team["sleeperTeamName"] = team_name(rid)
            counts["teams"] += 1
        if team.get("ownerId"):
            team["ownerId"] = ps.ident(team["ownerId"])
            counts["ownerIds"] += 1
        if isinstance(team.get("picks"), list):
            team["picks"] = [ps.label(p) for p in team["picks"]]
        for detail in team.get("pickDetails") or []:
            if "label" in detail:
                detail["label"] = ps.label(detail["label"])
            if "fromTeam" in detail:
                detail["fromTeam"] = ps.name(detail["fromTeam"])
    for trade in sleeper.get("trades") or []:
        if "leagueId" in trade:
            trade["leagueId"] = ps.ident(trade["leagueId"])
        for side in trade.get("sides") or []:
            if "team" in side:
                side["team"] = ps.name(side["team"])
            if "ownerId" in side:
                side["ownerId"] = ps.ident(side["ownerId"])
            for key in ("got", "gave"):
                if isinstance(side.get(key), list):
                    side[key] = [ps.label(x) for x in side[key]]
    evidence = sleeper.get("draftClassEvidence")
    if isinstance(evidence, dict):
        if evidence.get("sleeperLeagueId"):
            evidence["sleeperLeagueId"] = ps.ident(evidence["sleeperLeagueId"])
        if isinstance(evidence.get("draftListsObserved"), list):
            evidence["draftListsObserved"] = [ps.ident(x) for x in evidence["draftListsObserved"]]
        for draft in evidence.get("drafts") or []:
            if draft.get("draftId"):
                draft["draftId"] = ps.ident(draft["draftId"])
                counts["draftIds"] += 1
    leftovers = privacy_leaks(json.dumps(payload, ensure_ascii=False), ps)
    if leftovers:
        raise SystemExit(f"refusing to write the fixture: identifiers survived: {leftovers[:10]}")
    return payload, counts


def privacy_leaks(text: str, ps: _Pseudonymizer) -> list[str]:
    """Every original identifier still present in ``text``.

    Ids and multi-word team names are checked as substrings anywhere.  A short
    manager first name ("Ty") also occurs inside public NFL player names
    ("Tyler"), so a NAME is a leak only where a name can live: a whole JSON
    string or a ``(from X)`` label.
    """
    leaks = [i for i in ps.ids if i in text]
    for real in ps.names:
        if f'"{real}"' in text or f"(from {real})" in text:
            leaks.append(real)
    return leaks


# ── Build ──────────────────────────────────────────────────────────────────


def _archive_payload(archive_bytes: bytes) -> tuple[dict[str, Any], str]:
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        if not names:
            raise SystemExit("archive carries no dynasty_data_*.json payload")
        return json.loads(zf.read(names[0])), names[0]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect(commit: str, archive: str) -> tuple[dict[str, bytes], dict[str, Any]]:
    """``(files, manifest)`` for the fixture zip.  ``files`` maps zip path → bytes."""
    from tests.archive_fixtures import _degraded_critical_sources

    archive_bytes = _git_bytes(commit, f"exports/archive/{archive}")
    payload, payload_name = _archive_payload(archive_bytes)
    degraded = _degraded_critical_sources(payload)
    if degraded:
        raise SystemExit(f"{archive} is source-degraded ({degraded}); pin a complete board")
    payload, counts = pseudonymize_payload(payload)

    files: dict[str, bytes] = {
        "raw_payload.json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    }
    csvs = [p for p in _git_ls(commit, "CSVs/site_raw") if p.endswith(".csv") and p.count("/") == 2]
    for path in csvs:
        files[f"tree/{path}"] = _git_bytes(commit, path)
    states = [
        p
        for p in _git_ls(commit, "data/scrape_state")
        if p.count("/") == 2 and _STATE_FILE_RE.match(p.rsplit("/", 1)[1])
    ]
    for path in states:
        files[f"tree/{path}"] = _git_bytes(commit, path)

    full_commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", commit], check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "purpose": (
            "One complete board's full contract inputs, frozen together, so blocking tests "
            "never depend on the latest data refresh. Built by tests/pinned_board_build.py."
        ),
        "sourceCommit": full_commit,
        "archive": archive,
        "archivePayload": payload_name,
        "asOf": payload.get("scrapeTimestamp"),
        "boardDate": payload.get("date"),
        "pseudonymized": counts,
        "csvCount": len(csvs),
        "stateFileCount": len(states),
        "files": {name: _sha256(data) for name, data in sorted(files.items())},
    }
    return files, manifest


def write_zip(files: dict[str, bytes], manifest: dict[str, Any], out: Path) -> None:
    """Deterministic: sorted entries, fixed timestamps, fixed compression."""
    out.parent.mkdir(parents=True, exist_ok=True)
    entries = dict(files)
    entries["manifest.json"] = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, entries[name], compresslevel=9)
    out.write_bytes(buf.getvalue())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--commit", required=True, help="refresh commit that added the archive")
    parser.add_argument(
        "--archive", required=True, help="exports/archive/<name>.zip at that commit"
    )
    parser.add_argument("--out", type=Path, default=FIXTURE_ZIP)
    args = parser.parse_args(argv)
    files, manifest = collect(args.commit, args.archive)
    write_zip(files, manifest, args.out)
    size = args.out.stat().st_size
    print(
        f"wrote {args.out.relative_to(REPO) if args.out.is_relative_to(REPO) else args.out}: "
        f"{size:,} bytes, {manifest['csvCount']} CSVs, {manifest['stateFileCount']} state files, "
        f"as of {manifest['asOf']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
