#!/usr/bin/env python3
"""Convert the Footballguys Dynasty Rankings PDF into CSV source files.

FootballGuys publishes dynasty rankings as a browser-rendered table;
users export it as a PDF.  The PDF mixes offense (QB/RB/WR/TE) and
IDP (DE/DT/LB/CB/S) rows, ordered by a single consensus overall rank.

This script:
    * Reads the PDF via ``pdftotext`` (poppler-utils must be installed).
    * Walks the extracted text, segmenting into player blocks on the
      basis that each player block contains a position token like
      ``QB1`` / ``RB2`` / ``DE3`` / ``LB4`` etc.
    * Splits the players into offense and IDP universes.
    * Re-ranks each universe densely (1..N) so downstream rank-signal
      conversion treats the source as a clean within-universe ranking
      (gaps in the mixed overall rank would otherwise look like weird
      jumps to the canonical-blend path).
    * Writes two output CSVs:
          CSVs/site_raw/footballGuysSf.csv   — offense, ``name,rank``
          CSVs/site_raw/footballGuysIdp.csv  — IDP, ``name,rank``

These files feed ``_SOURCE_CSV_PATHS`` in ``src/api/data_contract.py``
and register as two discrete ranking sources
(``footballGuysSf`` + ``footballGuysIdp``), matching the FantasyPros
SF/IDP split pattern.

Usage::

    python3 scripts/parse_footballguys_pdf.py \\
        --pdf "CSVs/Fantasy Football Dynasty Rankings - Footballguys.pdf" \\
        --out-sf CSVs/site_raw/footballGuysSf.csv \\
        --out-idp CSVs/site_raw/footballGuysIdp.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}
IDP_POSITIONS = {"DE", "DT", "LB", "CB", "S"}

# NFL team codes (+ FA) — used to reject false matches where a name
# suffix like "II" or "IV" (Patrick Mahomes II, Ernest Jones IV) would
# otherwise be captured as the team.
NFL_TEAM_CODES = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS",
    "FA",
})

# Position-with-rank token, e.g. "QB1", "WR184", "DE10", "S5".
_POSITION_RE = re.compile(r"^(QB|RB|WR|TE|DE|DT|LB|CB|S)(\d+)$")

# Team codes — always 2-3 uppercase letters.  "FA" = free agent.
# We're permissive; we validate by position-token lookup rather than
# team-code whitelist.
_TEAM_RE = re.compile(r"^[A-Z]{2,3}$")

# Rank-like integer standalone on a line.
_INT_RE = re.compile(r"^\d+$")


@dataclass
class Player:
    overall_rank: int
    name: str
    team: str
    position: str  # canonical family, e.g. "QB" or "DE"
    pos_rank: int
    age: int | None
    years_exp: str  # "R" for rookie, else a numeric string

    @property
    def is_offense(self) -> bool:
        return self.position in OFFENSE_POSITIONS

    @property
    def is_idp(self) -> bool:
        return self.position in IDP_POSITIONS


def _pdf_to_lines(pdf_path: Path) -> list[str]:
    """Run ``pdftotext -layout`` and return the output as raw lines
    (not stripped — indentation matters for row-continuation detection).
    """
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


# Row pattern: optional leading rank, then "Name Team PosRank age yrs_or_R".
# Each row is self-contained even if rendered with a leading follow
# count that spills onto the previous line — the core data row always
# has the name + position pattern together.
_ROW_RE = re.compile(
    r"""
    ^\s*
    (?P<rank>\d+)?                       # optional leading rank
    \s*
    (?P<name>[A-Z][A-Za-z'.\- ]+?)        # player name
    \s+
    (?P<team>[A-Z]{2,3})                  # team code
    (?:\s*\S)*?                           # optional trailing glyphs (shield icon, etc.)
    \s+
    (?P<position>QB|RB|WR|TE|DE|DT|LB|CB|S)
    (?P<pos_rank>\d+)
    \s+
    (?P<age>\d+)
    \s+
    (?P<years>\d+|R)
    \s
    """,
    re.VERBOSE,
)


def parse_players(lines: list[str]) -> list[Player]:
    """Walk the layout-mode pdftotext output line-by-line and extract
    player rows with regex.

    Layout mode renders most rows on a single line::

        "  1  Josh Allen BUF   QB1   29  8  -  1 1 2 1 1 1 1 2"

    A handful of rows spill onto two lines (when a "follow count"
    icon renders above the row).  In those cases the second line is
    indented and starts WITHOUT the rank::

        "4                         1"
        "     Lamar Jackson BAL   QB4   29  8  -  3 4 5 4 5 6 3 6"

    Our regex matches both: ``rank`` is optional.  When the rank is
    missing on a matching line, we walk backwards through prior lines
    to find the nearest standalone integer that's greater than the
    previous rank we recorded (monotonic).
    """
    players: list[Player] = []
    seen: set[int] = set()

    def _find_preceding_rank(i: int) -> int | None:
        """Look up to 3 non-blank lines back for a trailing integer
        that's a valid rank (greater than last-seen)."""
        last_seen_rank = max(seen) if seen else 0
        j = i - 1
        scanned = 0
        while j >= 0 and scanned < 3:
            stripped = lines[j].strip()
            if not stripped:
                j -= 1
                continue
            # The rank line often has the rank followed by a stray
            # follow-count like "4                         1".  Grab
            # the FIRST integer on the line.
            m = re.match(r"^(\d+)\b", stripped)
            if m:
                val = int(m.group(1))
                if val > last_seen_rank and val not in seen and val < 5000:
                    return val
            scanned += 1
            j -= 1
        return None

    for i, line in enumerate(lines):
        m = _ROW_RE.search(line)
        if not m:
            continue
        rank_str = m.group("rank")
        if rank_str:
            rank = int(rank_str)
            if rank in seen:
                continue
        else:
            found = _find_preceding_rank(i)
            if found is None:
                continue
            rank = found

        position = m.group("position")
        try:
            pos_rank = int(m.group("pos_rank"))
        except (TypeError, ValueError):
            continue
        age = int(m.group("age"))
        years_exp = m.group("years")
        name = m.group("name").strip()
        team = m.group("team").strip()

        # Quick sanity on age — bad extractions will match improbable
        # ages and we'd rather skip than add junk.
        if not (18 <= age <= 50):
            continue

        # Reject false matches where a Roman-numeral suffix ("II",
        # "III", "IV") got captured as the team.  In those cases the
        # ACTUAL team is the token that followed — we rebuild the row
        # with name including the suffix.
        if team not in NFL_TEAM_CODES:
            # Try extending the name by one token and re-matching the
            # remainder.  Simpler to just search the raw line for a
            # team code AFTER the captured "team".
            suffix = team
            remainder = line[m.end("team"):]
            team_m = re.search(r"\b([A-Z]{2,3})\b", remainder)
            if not team_m or team_m.group(1) not in NFL_TEAM_CODES:
                continue
            team = team_m.group(1)
            name = f"{name} {suffix}".strip()

        seen.add(rank)
        players.append(
            Player(
                overall_rank=rank,
                name=name,
                team=team,
                position=position,
                pos_rank=pos_rank,
                age=age,
                years_exp=years_exp,
            )
        )
    return players


def split_and_rank(players: list[Player]) -> tuple[list[Player], list[Player]]:
    """Return (offense_sorted, idp_sorted) with dense within-universe ranks.

    Each list is sorted by ``overall_rank`` ascending (so the player
    with the best consensus overall rank comes first within each
    universe).  The caller can emit these positions as 1..N dense ranks
    when writing the CSV.
    """
    offense = sorted(
        (p for p in players if p.is_offense), key=lambda p: p.overall_rank
    )
    idp = sorted(
        (p for p in players if p.is_idp), key=lambda p: p.overall_rank
    )
    return offense, idp


def write_csv(players: list[Player], out_path: Path) -> None:
    """Write ``name,rank,position,team,age`` with dense rank 1..N.

    The ``_enrich_from_source_csvs`` reader in ``src/api/data_contract.py``
    only needs ``name`` and one of ``value``/``rank`` — the extra
    position/team/age columns are metadata for debugging + future-
    proofing if we later want position-aware fallbacks.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "rank", "position", "team", "age", "years_exp"])
        for dense_rank, p in enumerate(players, start=1):
            w.writerow([
                p.name,
                dense_rank,
                f"{p.position}{p.pos_rank}",
                p.team,
                p.age if p.age is not None else "",
                p.years_exp,
            ])


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pdf",
        default=str(repo / "CSVs" / "Fantasy Football Dynasty Rankings - Footballguys.pdf"),
    )
    ap.add_argument("--out-sf", default=str(repo / "CSVs" / "site_raw" / "footballGuysSf.csv"))
    ap.add_argument("--out-idp", default=str(repo / "CSVs" / "site_raw" / "footballGuysIdp.csv"))
    ap.add_argument(
        "--verbose", action="store_true",
        help="Print parsing stats + a sample of the first parsed players.",
    )
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: {pdf_path} not found", file=sys.stderr)
        return 1

    lines = _pdf_to_lines(pdf_path)
    print(f"[footballguys] extracted {len(lines)} lines from {pdf_path.name}")

    players = parse_players(lines)
    print(f"[footballguys] parsed {len(players)} players")

    offense, idp = split_and_rank(players)
    print(f"[footballguys] offense={len(offense)}, idp={len(idp)}")

    write_csv(offense, Path(args.out_sf))
    write_csv(idp, Path(args.out_idp))
    print(f"[footballguys] wrote {args.out_sf}")
    print(f"[footballguys] wrote {args.out_idp}")

    if args.verbose:
        print("\nFirst 10 offense:")
        for p in offense[:10]:
            print(f"  {p.overall_rank:4d}  {p.name:<30}  {p.team:<4}  {p.position}{p.pos_rank}  age={p.age} yrs={p.years_exp}")
        print("\nFirst 10 IDP:")
        for p in idp[:10]:
            print(f"  {p.overall_rank:4d}  {p.name:<30}  {p.team:<4}  {p.position}{p.pos_rank}  age={p.age} yrs={p.years_exp}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
