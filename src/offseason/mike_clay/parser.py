from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - exercised in production when optional dep missing
    PdfReader = None

from .constants import (
    IDP_SECTION_ORDER,
    PARSER_VERSION,
    STARTER_SLOT_TOKENS,
    STARTER_SLOT_TO_POS,
    TEAM_GUIDE_TO_CANONICAL,
    TEAM_NAME_TO_CANONICAL,
)

_QB_ROW_RE = re.compile(
    r"^(?P<player>.+?)\s+(?P<team>[A-Z]{2,4})\s+"
    r"(?P<positional_rank>\d+)\s+(?P<projected_points>\d+)\s+(?P<games>\d+)\s+"
    r"(?P<pass_att>\d+)\s+(?P<pass_comp>\d+)\s+(?P<pass_yds>\d+)\s+(?P<pass_td>\d+)\s+"
    r"(?P<pass_int>\d+)\s+(?P<sacks_taken>\d+)\s+(?P<rush_att>\d+)\s+"
    r"(?P<rush_yds>\d+)\s+(?P<rush_td>\d+)$"
)
_SKILL_ROW_RE = re.compile(
    r"^(?P<player>.+?)\s+(?P<team>[A-Z]{2,4})\s+"
    r"(?P<positional_rank>\d+)\s+(?P<projected_points>\d+)\s+(?P<games>\d+)\s+"
    r"(?P<rush_att>\d+)\s+(?P<rush_yds>\d+)\s+(?P<rush_td>\d+)\s+"
    r"(?P<targets>\d+)\s+(?P<receptions>\d+)\s+(?P<rec_yds>\d+)\s+(?P<rec_td>\d+)\s+"
    r"(?P<carry_share>\d+%)\s+(?P<target_share>\d+%)$"
)
_IDP_ROW_RE = re.compile(
    r"^(?P<player>.+?)\s+(?P<team>[A-Z]{2,4})\s+"
    r"(?P<positional_rank>\d+)\s+(?P<projected_points>\d+)\s+(?P<snaps>\d+)\s+"
    r"(?P<tot_tkl>\d+)\s+(?P<solos>\d+)\s+(?P<assists>\d+)\s+"
    r"(?P<tfl>\d+(?:\.\d+)?)\s+(?P<sacks>\d+(?:\.\d+)?)\s+"
    r"(?P<ints>\d+(?:\.\d+)?)\s+(?P<forced_fumbles>\d+(?:\.\d+)?)$"
)
_STANDINGS_NUM_RE = re.compile(
    r"^(?P<wins>\d+\.\d)\s+(?P<losses>\d+\.\d)\s+(?P<fav>\d+)\s+"
    r"(?P<pf>\d+)\s+(?P<pa>\d+)\s+(?P<diff>-?\d+)\s+(?P<sch>\d+)\b"
)
_GRADE_TEAM_RE = re.compile(r"^(?P<grade>\d+)\s+(?P<team>.+)$")
_UPDATED_RE = re.compile(r"Updated:\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
_NOISE_LINE_RE = re.compile(
    r"(Projections \(\d+/\d+\)|Projections$|^Team Pos Rk|^Rk Team|^Div Team|^Tm Head Coach)",
    re.IGNORECASE,
)


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    return bool(_NOISE_LINE_RE.search(line))


def _is_placeholder_player_name(name: str) -> bool:
    token = re.sub(r"\s+", " ", str(name or "")).strip().upper()
    return token in {"", "0", "-", "--", "N/A", "NA"}


def _to_int(raw: str | int | float | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _to_float(raw: str | int | float | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _starter_segments(line: str) -> list[dict[str, str]]:
    tokens = line.split()
    segments: list[dict[str, str]] = []
    active_team = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if (
            tok in TEAM_GUIDE_TO_CANONICAL
            and i + 1 < len(tokens)
            and tokens[i + 1] in STARTER_SLOT_TOKENS
        ):
            active_team = tok
            i += 1
            tok = tokens[i]
        if tok not in STARTER_SLOT_TOKENS:
            i += 1
            continue
        slot = tok
        i += 1
        name_tokens: list[str] = []
        while i < len(tokens):
            nxt = tokens[i]
            if nxt in STARTER_SLOT_TOKENS:
                break
            if (
                nxt in TEAM_GUIDE_TO_CANONICAL
                and i + 1 < len(tokens)
                and tokens[i + 1] in STARTER_SLOT_TOKENS
            ):
                break
            name_tokens.append(nxt)
            i += 1
        segments.append(
            {
                "team_source": active_team,
                "slot": slot,
                "player_name_source": " ".join(name_tokens).strip(),
            }
        )
    return [
        s
        for s in segments
        if s["slot"]
        and s["player_name_source"]
        and not _is_placeholder_player_name(s["player_name_source"])
    ]


@dataclass
class MikeClayParseBundle:
    source_file: str
    parser_version: str
    extracted_at: str
    guide_updated_date: str | None
    guide_year: int | None
    pages: list[dict[str, Any]]
    positional_rows: list[dict[str, Any]]
    team_rows: list[dict[str, Any]]
    sos_rows: list[dict[str, Any]]
    unit_grade_rows: list[dict[str, Any]]
    unit_rank_rows: list[dict[str, Any]]
    coaching_rows: list[dict[str, Any]]
    starter_rows: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


def parse_mike_clay_pdf(pdf_path: Path, *, guide_year_hint: int | None = None) -> MikeClayParseBundle:
    if PdfReader is None:
        raise RuntimeError(
            "Mike Clay PDF parsing requires optional dependency 'pypdf'. "
            "Install pypdf to enable import pipeline."
        )

    reader = PdfReader(str(pdf_path))
    pages: list[dict[str, Any]] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(
            {
                "page": idx,
                "chars": len(text),
                "lines": _clean_lines(text),
                "text": text,
            }
        )

    extracted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    first_page_text = pages[0]["text"] if pages else ""
    updated_match = _UPDATED_RE.search(first_page_text or "")
    updated_date = updated_match.group(1) if updated_match else None

    guide_year = guide_year_hint
    if guide_year is None:
        m = re.search(r"(20\d{2})", pdf_path.name)
        if m:
            guide_year = int(m.group(1))

    warnings: list[dict[str, Any]] = []
    positional_rows: list[dict[str, Any]] = []
    idp_section_idx = 0

    for page_data in pages:
        page_num = int(page_data["page"])
        lines: list[str] = list(page_data["lines"])
        if not lines:
            continue
        header = lines[0]
        body = lines[1:]

        if header.startswith("Quarterback Team Pos Rk"):
            for line in body:
                if _is_noise_line(line):
                    continue
                m = _QB_ROW_RE.match(line)
                if not m:
                    warnings.append({"page": page_num, "type": "qb_parse_fail", "line": line})
                    continue
                row = m.groupdict()
                positional_rows.append(
                    {
                        "page": page_num,
                        "section": "QB",
                        "position_source": "QB",
                        "player_name_source": row["player"],
                        "team_source": row["team"],
                        "positional_rank": _to_int(row["positional_rank"]),
                        "projected_points": _to_float(row["projected_points"]),
                        "projected_games": _to_float(row["games"]),
                        "passing_attempts": _to_float(row["pass_att"]),
                        "passing_completions": _to_float(row["pass_comp"]),
                        "passing_yards": _to_float(row["pass_yds"]),
                        "passing_tds": _to_float(row["pass_td"]),
                        "interceptions": _to_float(row["pass_int"]),
                        "sacks_taken": _to_float(row["sacks_taken"]),
                        "rushing_attempts": _to_float(row["rush_att"]),
                        "rushing_yards": _to_float(row["rush_yds"]),
                        "rushing_tds": _to_float(row["rush_td"]),
                        "targets": None,
                        "receptions": None,
                        "receiving_yards": None,
                        "receiving_tds": None,
                        "idp_total_tackles": None,
                        "idp_solo_tackles": None,
                        "idp_assist_tackles": None,
                        "idp_tfl": None,
                        "idp_sacks": None,
                        "idp_interceptions": None,
                        "idp_forced_fumbles": None,
                        "carry_share_pct": None,
                        "target_share_pct": None,
                        "parse_confidence": 1.0,
                    }
                )
            continue

        if header.startswith("Running Back Team Pos Rk") or header.startswith("Wide Receiver Team Pos Rk") or header.startswith("Tight End Team Pos Rk"):
            section = "RB" if header.startswith("Running Back") else ("WR" if header.startswith("Wide Receiver") else "TE")
            for line in body:
                if _is_noise_line(line):
                    continue
                m = _SKILL_ROW_RE.match(line)
                if not m:
                    warnings.append({"page": page_num, "type": "skill_parse_fail", "line": line, "section": section})
                    continue
                row = m.groupdict()
                positional_rows.append(
                    {
                        "page": page_num,
                        "section": section,
                        "position_source": section,
                        "player_name_source": row["player"],
                        "team_source": row["team"],
                        "positional_rank": _to_int(row["positional_rank"]),
                        "projected_points": _to_float(row["projected_points"]),
                        "projected_games": _to_float(row["games"]),
                        "passing_attempts": None,
                        "passing_completions": None,
                        "passing_yards": None,
                        "passing_tds": None,
                        "interceptions": None,
                        "sacks_taken": None,
                        "rushing_attempts": _to_float(row["rush_att"]),
                        "rushing_yards": _to_float(row["rush_yds"]),
                        "rushing_tds": _to_float(row["rush_td"]),
                        "targets": _to_float(row["targets"]),
                        "receptions": _to_float(row["receptions"]),
                        "receiving_yards": _to_float(row["rec_yds"]),
                        "receiving_tds": _to_float(row["rec_td"]),
                        "idp_total_tackles": None,
                        "idp_solo_tackles": None,
                        "idp_assist_tackles": None,
                        "idp_tfl": None,
                        "idp_sacks": None,
                        "idp_interceptions": None,
                        "idp_forced_fumbles": None,
                        "carry_share_pct": _to_float(row["carry_share"].replace("%", "")),
                        "target_share_pct": _to_float(row["target_share"].replace("%", "")),
                        "parse_confidence": 1.0,
                    }
                )
            continue

        if header.startswith("Defender Team Pos Rk"):
            section_pos = IDP_SECTION_ORDER[idp_section_idx] if idp_section_idx < len(IDP_SECTION_ORDER) else "DB"
            idp_section_idx += 1
            for line in body:
                if _is_noise_line(line):
                    continue
                m = _IDP_ROW_RE.match(line)
                if not m:
                    warnings.append(
                        {"page": page_num, "type": "idp_parse_fail", "line": line, "section": section_pos}
                    )
                    continue
                row = m.groupdict()
                positional_rows.append(
                    {
                        "page": page_num,
                        "section": section_pos,
                        "position_source": section_pos,
                        "player_name_source": row["player"],
                        "team_source": row["team"],
                        "positional_rank": _to_int(row["positional_rank"]),
                        "projected_points": _to_float(row["projected_points"]),
                        "projected_games": None,
                        "passing_attempts": None,
                        "passing_completions": None,
                        "passing_yards": None,
                        "passing_tds": None,
                        "interceptions": None,
                        "sacks_taken": None,
                        "rushing_attempts": None,
                        "rushing_yards": None,
                        "rushing_tds": None,
                        "targets": None,
                        "receptions": None,
                        "receiving_yards": None,
                        "receiving_tds": None,
                        "idp_snaps": _to_float(row["snaps"]),
                        "idp_total_tackles": _to_float(row["tot_tkl"]),
                        "idp_solo_tackles": _to_float(row["solos"]),
                        "idp_assist_tackles": _to_float(row["assists"]),
                        "idp_tfl": _to_float(row["tfl"]),
                        "idp_sacks": _to_float(row["sacks"]),
                        "idp_interceptions": _to_float(row["ints"]),
                        "idp_forced_fumbles": _to_float(row["forced_fumbles"]),
                        "carry_share_pct": None,
                        "target_share_pct": None,
                        "parse_confidence": 1.0,
                    }
                )
            continue

    team_rows: list[dict[str, Any]] = []
    standings_page = pages[59] if len(pages) >= 60 else None
    if standings_page:
        for line in standings_page["lines"]:
            for team_name, canonical_code in sorted(TEAM_NAME_TO_CANONICAL.items(), key=lambda kv: len(kv[0]), reverse=True):
                if team_name not in line:
                    continue
                after = line.split(team_name, 1)[1].strip()
                m = _STANDINGS_NUM_RE.match(after)
                if not m:
                    continue
                d = m.groupdict()
                team_rows.append(
                    {
                        "team_name_source": team_name,
                        "team_canonical": canonical_code,
                        "projected_wins": _to_float(d["wins"]),
                        "projected_losses": _to_float(d["losses"]),
                        "favored_games": _to_int(d["fav"]),
                        "projected_points_for": _to_int(d["pf"]),
                        "projected_points_against": _to_int(d["pa"]),
                        "projected_point_diff": _to_int(d["diff"]),
                        "schedule_rank_from_standings": _to_int(d["sch"]),
                    }
                )
                break

    sos_rows: list[dict[str, Any]] = []
    sos_page = pages[60] if len(pages) >= 61 else None
    if sos_page:
        for line in sos_page["lines"]:
            if not line or not line[0].isdigit():
                continue
            parts = line.split(" ", 1)
            if len(parts) < 2:
                continue
            rank = _to_int(parts[0])
            rest = parts[1].strip()
            if rank is None:
                continue
            matched_team = None
            for team_name in sorted(TEAM_NAME_TO_CANONICAL.keys(), key=len, reverse=True):
                if rest.startswith(team_name + " ") or rest == team_name:
                    matched_team = team_name
                    break
            if not matched_team:
                continue
            schedule_blob = rest[len(matched_team) :].strip()
            sos_rows.append(
                {
                    "team_name_source": matched_team,
                    "team_canonical": TEAM_NAME_TO_CANONICAL[matched_team],
                    "strength_of_schedule_rank": rank,
                    "schedule_tokens": schedule_blob.split(),
                }
            )

    unit_grade_rows: list[dict[str, Any]] = []
    unit_grade_page = pages[61] if len(pages) >= 62 else None
    if unit_grade_page:
        for line in unit_grade_page["lines"]:
            for team_name, canonical_code in sorted(TEAM_NAME_TO_CANONICAL.items(), key=lambda kv: len(kv[0]), reverse=True):
                if not line.startswith(team_name + " "):
                    continue
                tail_tokens = line[len(team_name) :].strip().split()
                if len(tail_tokens) < 16:
                    warnings.append({"page": 62, "type": "unit_grade_parse_fail", "line": line})
                    break
                values = tail_tokens[:16]
                unit_grade_rows.append(
                    {
                        "team_name_source": team_name,
                        "team_canonical": canonical_code,
                        "qb_grade": _to_float(values[0]),
                        "rb_grade": _to_float(values[1]),
                        "wr_grade": _to_float(values[2]),
                        "te_grade": _to_float(values[3]),
                        "ol_grade": _to_float(values[4]),
                        "di_grade": _to_float(values[5]),
                        "ed_grade": _to_float(values[6]),
                        "lb_grade": _to_float(values[7]),
                        "cb_grade": _to_float(values[8]),
                        "s_grade": _to_float(values[9]),
                        "offense_grade": _to_float(values[10]),
                        "offense_rank": _to_int(values[11]),
                        "defense_grade": _to_float(values[12]),
                        "defense_rank": _to_int(values[13]),
                        "total_grade": _to_float(values[14]),
                        "total_rank": _to_int(values[15]),
                    }
                )
                break

    unit_rank_rows: list[dict[str, Any]] = []
    unit_rank_categories = ["qb", "rb", "wr", "te", "ol", "di", "ed", "lb", "cb", "s"]
    for page_num in range(63, 73):
        if page_num > len(pages):
            break
        category = unit_rank_categories[page_num - 63]
        for line in pages[page_num - 1]["lines"]:
            m = _GRADE_TEAM_RE.match(line)
            if not m:
                continue
            grade = _to_float(m.group("grade"))
            team_name = m.group("team").strip()
            canonical = TEAM_NAME_TO_CANONICAL.get(team_name)
            if canonical is None:
                continue
            unit_rank_rows.append(
                {
                    "team_name_source": team_name,
                    "team_canonical": canonical,
                    "unit_category": category,
                    "unit_grade": grade,
                    "unit_rank_page": page_num,
                }
            )

    coaching_rows: list[dict[str, Any]] = []
    coaching_page = pages[72] if len(pages) >= 73 else None
    if coaching_page:
        for line in coaching_page["lines"]:
            tokens = line.split()
            if len(tokens) < 3:
                continue
            team_code = tokens[0]
            if team_code not in TEAM_GUIDE_TO_CANONICAL:
                continue
            coach_name = " ".join(tokens[1:]).strip()
            coaching_rows.append(
                {
                    "team_source": team_code,
                    "team_canonical": TEAM_GUIDE_TO_CANONICAL[team_code],
                    "head_coach": coach_name,
                }
            )

    starter_rows: list[dict[str, Any]] = []
    for page_num in range(74, min(81, len(pages)) + 1):
        lines = pages[page_num - 1]["lines"]
        if not lines:
            continue
        left_team = ""
        right_team = ""
        for line in lines:
            if "Projected Lineups" in line:
                continue
            segments = _starter_segments(line)
            if not segments:
                continue
            explicit = [seg["team_source"] for seg in segments if seg["team_source"]]
            if explicit:
                distinct: list[str] = []
                for team_code in explicit:
                    if team_code not in distinct:
                        distinct.append(team_code)
                if len(distinct) >= 2:
                    left_team, right_team = distinct[0], distinct[1]
                elif len(distinct) == 1 and not left_team:
                    left_team = distinct[0]

            missing_idx = [idx for idx, seg in enumerate(segments) if not seg["team_source"]]
            if missing_idx and left_team and right_team and len(missing_idx) == 4:
                for local_idx, seg_idx in enumerate(missing_idx):
                    segments[seg_idx]["team_source"] = left_team if local_idx < 2 else right_team
            elif missing_idx and left_team and right_team and len(missing_idx) == 2:
                segments[missing_idx[0]]["team_source"] = left_team
                segments[missing_idx[1]]["team_source"] = right_team
            elif missing_idx and left_team:
                for seg_idx in missing_idx:
                    segments[seg_idx]["team_source"] = left_team

            for seg in segments:
                team_source = seg["team_source"]
                slot = seg["slot"]
                player_name_source = seg["player_name_source"]
                if not team_source or team_source not in TEAM_GUIDE_TO_CANONICAL:
                    warnings.append(
                        {
                            "page": page_num,
                            "type": "starter_team_missing",
                            "line": line,
                            "segment": seg,
                        }
                    )
                    continue
                starter_rows.append(
                    {
                        "page": page_num,
                        "team_source": team_source,
                        "team_canonical": TEAM_GUIDE_TO_CANONICAL[team_source],
                        "slot": slot,
                        "position_source": STARTER_SLOT_TO_POS.get(slot, ""),
                        "player_name_source": player_name_source,
                    }
                )

    return MikeClayParseBundle(
        source_file=pdf_path.name,
        parser_version=PARSER_VERSION,
        extracted_at=extracted_at,
        guide_updated_date=updated_date,
        guide_year=guide_year,
        pages=pages,
        positional_rows=positional_rows,
        team_rows=team_rows,
        sos_rows=sos_rows,
        unit_grade_rows=unit_grade_rows,
        unit_rank_rows=unit_rank_rows,
        coaching_rows=coaching_rows,
        starter_rows=starter_rows,
        warnings=warnings,
    )
