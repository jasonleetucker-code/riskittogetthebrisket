"""Mike Clay's ESPN projection guide → BDVM projection records.

The first REAL (non-proxy) OFFENSE projection source — and a second
IDP source beside The IDP Show.  The guide is a public PDF on ESPN's
fantasy draft-kit CDN (``g.espncdn.com/s/ffldraftkit/<yy>/
NFLDK<season>_CS_ClayProjections<season>.pdf``), fetched and
text-extracted by ``scripts/fetch_clay_projections.py`` (pdftotext
-layout).  Everything in this module is pure parsing/merging so it is
fully testable offline against extracted-text fixtures.

What we parse — the 32 TEAM pages only (the positional pages later in
the guide re-list the same numbers in a different layout; the team
pages cover every player down to the fringe):

* OFFENSE rows: ``Pos Player Gm | Att Comp Yds TD INT Sk | Att Yds TD
  | Tgt Rec Yd TD | Pts Rk`` — sixteen numbers after the name.  We
  keep the RAW season stat line (never ESPN's PPR points), so the
  record scores under the league's exact settings via the shared
  scoring path.
* DEFENSE rows (same physical lines, right-hand table): ``Pos Player
  Snap Tkl Sack INT Rk``.  Tackles are COMBINED — split solo/assist
  with the same documented ``TACKLE_SOLO_SHARE`` approximation the
  IDP Show adapter uses.  The guide's FF column does not survive text
  extraction; forced fumbles are omitted rather than guessed.

Merge policy: the shared ``supersede_merge_into_snapshot`` — Clay's
records replace their own prior run wholesale and supersede
reconstructed-baseline proxies per player; IDP Show records carry
through untouched, so defenders covered by both feeds get a genuine
two-source consensus.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from src.bdvm.idpshow_projections import TACKLE_SOLO_SHARE
from src.bdvm.projections import (
    ProjectionRecord,
    supersede_merge_into_snapshot,
)

SOURCE_NAME = "clayProjections"

# Clay position labels → BDVM true positions.
_DEF_POSITIONS = {"DI": "DT", "ED": "EDGE", "LB": "LB", "CB": "CB", "S": "S"}
_OFF_POSITIONS = ("QB", "RB", "WR", "TE")

# Offense: pos, name, then exactly 16 integers
# (Gm Att Comp Yds TD INT Sk | Att Yds TD | Tgt Rec Yd TD | Pts Rk).
_OFFENSE_ROW = re.compile(
    r"^\s*(QB|RB|WR|TE)\s+(?!Total\b)([A-Za-z][\w.'\- ]*?)\s+(\d+(?:\s+\d+){15})(?!\S)"
)

# Defense (searched anywhere in the line — the tables sit side by
# side): pos, name, Snap(int) Tkl(int) Sack(dec) INT(dec) Rk(int).
_DEFENSE_ROW = re.compile(
    r"\b(DI|ED|LB|CB|S)\s+(?!Total\b)([A-Za-z][\w.'\- ]*?)\s+"
    r"(\d+)\s+(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+)(?!\S)"
)

# The team-pages region ends where the positional re-lists begin.
_POSITIONAL_HEADER = re.compile(r"^\s*Quarterback Projections\s*$", re.MULTILINE)

_UPDATED_RE = re.compile(r"Updated:\s*(\d{1,2}/\d{1,2}/\d{4})")


class ClayParseError(ValueError):
    pass


def _team_pages(text: str) -> str:
    """Slice the extracted text down to the team-projection pages."""
    match = _POSITIONAL_HEADER.search(text)
    return text[: match.start()] if match else text


def parse_clay_text(text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse the extracted guide text.  Returns (rows, report).

    Rows are dicts: ``{"name", "position", "games", "stats"}`` with
    season-basis stat lines.  Duplicate names keep the first
    occurrence (team pages list each player once; a dupe would be a
    same-named player on another team — rare enough to flag, not
    guess).
    """
    region = _team_pages(text)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    offense_count = 0
    defense_count = 0

    for line in region.split("\n"):
        off = _OFFENSE_ROW.match(line)
        if off:
            pos, name, nums_blob = off.groups()
            nums = [int(n) for n in nums_blob.split()]
            (
                games,
                p_att,
                p_comp,
                p_yds,
                p_td,
                p_int,
                p_sk,
                r_att,
                r_yds,
                r_td,
                tgt,
                rec,
                re_yds,
                re_td,
                _pts,
                _rk,
            ) = nums
            key = (name.strip().lower(), "off")
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
                stats = {
                    "attempts": p_att,
                    "completions": p_comp,
                    "passing_yards": p_yds,
                    "passing_tds": p_td,
                    "interceptions": p_int,
                    "sacks": p_sk,
                    "carries": r_att,
                    "rushing_yards": r_yds,
                    "rushing_tds": r_td,
                    "targets": tgt,
                    "receptions": rec,
                    "receiving_yards": re_yds,
                    "receiving_tds": re_td,
                }
                rows.append(
                    {
                        "name": name.strip(),
                        "position": pos,
                        "games": float(games) if games else 17.0,
                        "stats": {k: float(v) for k, v in stats.items() if v},
                    }
                )
                offense_count += 1

        for dmatch in _DEFENSE_ROW.finditer(line):
            dpos, dname, _snap, tkl, sack, ints, _rk = dmatch.groups()
            key = (dname.strip().lower(), "def")
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            combined = float(tkl)
            stats = {
                "def_tackles_solo": combined * TACKLE_SOLO_SHARE,
                "def_tackle_assists": combined * (1.0 - TACKLE_SOLO_SHARE),
                "def_sacks": float(sack),
                "def_interceptions": float(ints),
            }
            rows.append(
                {
                    "name": dname.strip(),
                    "position": _DEF_POSITIONS[dpos],
                    "games": 17.0,  # defense block carries snaps, not games
                    "stats": {k: v for k, v in stats.items() if v},
                }
            )
            defense_count += 1

    updated = _UPDATED_RE.search(text)
    report: dict[str, Any] = {
        "usable": offense_count >= 50,  # a real guide has hundreds
        "offenseRows": offense_count,
        "defenseRows": defense_count,
        "duplicatesSkipped": duplicates,
        "guideUpdated": updated.group(1) if updated else None,
        "approximations": [
            f"tackle_split_solo_share_{TACKLE_SOLO_SHARE:.2f}",
            "forced_fumbles_unavailable_in_extraction",
        ],
    }
    if not report["usable"]:
        report["reason"] = "too_few_offense_rows_to_be_the_real_guide"
        return [], report
    return rows, report


def records_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    season: int,
    as_of: str,
    name_normalizer,
) -> tuple[list[ProjectionRecord], dict[str, Any]]:
    """Build one record per player.  Returns (records, summary).

    Name-collision policy (BDVM keys players by normalized name):

    * Offense row + defense row under ONE name is a TWO-WAY player
      (Travis Hunter) — the stat lines are COMBINED into one record,
      which scores as the sum under league rules: exactly his value in
      an IDP league.  The record keeps the DEFENSIVE position: the
      scoring gate lets an IDP position score offense keys too (a
      defender's receptions count in real fantasy), while an offense
      position gates the IDP keys off (the contract row decides the
      lineup group regardless).
    * Two rows on the SAME side under one name are two DIFFERENT
      players this source cannot tell apart (Byron Murphy the CB vs
      Byron Murphy the DT) — both are dropped and counted, never
      guessed.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if not dict(row.get("stats") or {}):
            # Zero-projection fringe rows (all columns 0) — honestly
            # nothing to record; the player stays proxy/unpriced.
            continue
        grouped.setdefault(name_normalizer(row["name"]), []).append(row)

    records: list[ProjectionRecord] = []
    two_way: list[str] = []
    ambiguous: list[str] = []
    for key, group in grouped.items():
        if len(group) == 1:
            row = group[0]
            stats = dict(row["stats"])
            position = row["position"]
            games = float(row.get("games") or 17.0)
        elif len(group) == 2 and {g["position"] in _OFF_POSITIONS for g in group} == {True, False}:
            offense = next(g for g in group if g["position"] in _OFF_POSITIONS)
            defense = next(g for g in group if g["position"] not in _OFF_POSITIONS)
            stats = {**dict(defense["stats"]), **dict(offense["stats"])}
            position = defense["position"]
            games = max(float(g.get("games") or 17.0) for g in group)
            two_way.append(key)
        else:
            ambiguous.append(key)
            continue
        records.append(
            ProjectionRecord(
                source=SOURCE_NAME,
                player_key=key,
                position=position,
                season=season,
                as_of=as_of,
                games=games,
                stat_line=stats,
                stat_basis="season",
                is_proxy=False,
            )
        )
    summary = {
        "records": len(records),
        "twoWayCombined": sorted(two_way),
        "ambiguousSameNameDropped": sorted(ambiguous),
    }
    return records, summary


def merge_into_snapshot(
    new_records: list[ProjectionRecord],
    *,
    season: int,
    as_of: str,
    label: str = "clay",
) -> tuple[Any, dict[str, Any]]:
    if not new_records:
        raise ClayParseError("refusing to write a snapshot from zero records")
    return supersede_merge_into_snapshot(
        new_records,
        source_name=SOURCE_NAME,
        season=season,
        as_of=as_of,
        label=label,
    )
