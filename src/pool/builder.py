"""Canonical player pool constructor.

Builds one authoritative universe from exactly three membership sources:
  1. Sleeper — every currently rostered player from the hardcoded league
  2. KTC — ranks 1..525 (structured rows, not just name→value)
  3. Adamidp — extracted from local PDFs (normalized artifact)

IDPTradeCalc enriches the final union but NEVER decides membership.

This module is called by Dynasty Scraper.py after raw source ingestion
and before players_json export.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Historical note: this file used to export
# ``DEFAULT_SLEEPER_LEAGUE_ID`` as a hardcoded fallback.  The constant
# was never consumed outside its own module (confirmed by grep on
# 2026-04-24) — the scraper resolves the league ID through
# ``src/api/league_registry`` with its own env-var fallback, not via
# this builder.  Removed during the multi-league audit.
KTC_UNIVERSE_LIMIT = 525

# Source type classification for the valuation pipeline
SOURCE_TYPES = {
    "ktc": "full_mixed_value",
    "idpTradeCalc": "mixed_offense_idp_bridge",
}


@dataclass
class CanonicalPoolRow:
    """One player in the canonical universe."""
    canonical_id: str | None = None
    canonical_name: str = ""
    position: str = ""
    team: str | None = None

    # Membership flags
    in_sleeper: bool = False
    in_ktc_top525: bool = False
    in_adamidp_pdf: bool = False

    # Source records
    ktc_value: float | None = None
    ktc_rank: int | None = None
    adamidp_rank: int | None = None
    adamidp_value_text: str | None = None
    adamidp_position_rank: int | None = None
    idp_trade_calc_value: float | None = None
    idp_trade_calc_matched: bool = False

    # Sleeper identity
    sleeper_id: str | None = None
    sleeper_position: str | None = None

    # Audit
    match_status: str = "unmatched"
    raw_source_names: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class AdamidpRow:
    """One row from an Adamidp PDF."""
    overall_rank: int | None = None
    player_name: str = ""
    position: str = ""
    position_rank: int | None = None
    trade_value_text: str = ""
    class_year: str | None = None
    draft_capital: str | None = None
    age: str | None = None
    source_pdf: str = ""
    ambiguous: bool = False
    ambiguous_reason: str = ""


@dataclass
class PoolAuditReport:
    """Structured audit of the pool build."""
    sleeper_count: int = 0
    ktc_top525_count: int = 0
    adamidp_extracted_raw_count: int = 0
    adamidp_unique_count: int = 0
    final_union_count: int = 0
    idp_trade_calc_queried_count: int = 0
    idp_trade_calc_matched_count: int = 0
    idp_trade_calc_unmatched_count: int = 0
    sleeper_only_sample: list[str] = field(default_factory=list)
    ktc_only_sample: list[str] = field(default_factory=list)
    adamidp_only_sample: list[str] = field(default_factory=list)
    idp_trade_calc_unmatched_names: list[str] = field(default_factory=list)
    excluded_names: list[dict[str, str]] = field(default_factory=list)
    source_type_docs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Position normalization (reuse from Dynasty Scraper.py) ──

_OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}
_IDP_POSITIONS_EXPANDED = {"DL", "DE", "DT", "LB", "DB", "CB", "S", "EDGE", "NT",
                           "OLB", "ILB", "FS", "SS"}
_IDP_POSITIONS_NORMALIZED = {"DL", "LB", "DB"}


def normalize_position(pos: str) -> str:
    # Delegate to the shared helper so dual-position inputs
    # (e.g. "DL/LB") collapse under the canonical DL > DB > LB
    # priority. Non-IDP inputs fall through to the raw uppercased
    # string to preserve offense/K/PICK handling downstream.
    from src.utils.name_clean import resolve_idp_position

    resolved = resolve_idp_position(pos)
    if resolved:
        return resolved
    return str(pos or "").strip().upper()


def is_offense(pos: str) -> bool:
    return normalize_position(pos) in _OFFENSE_POSITIONS


def is_idp(pos: str) -> bool:
    return normalize_position(pos) in _IDP_POSITIONS_NORMALIZED


# ── Name cleaning (extracted from Dynasty Scraper.py) ──

_TEAM_CODES = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    "FA",
}


def pool_clean_name(raw: str) -> str:
    """Clean a player name for matching."""
    if not raw:
        return ""
    name = str(raw).strip()
    if '\\u' in name:
        try:
            name = name.encode('utf-8').decode('unicode_escape')
        except Exception:
            name = re.sub(r'\\u([0-9a-fA-F]{4})',
                          lambda m: chr(int(m.group(1), 16)), name)
    name = re.sub(r"^\s*#?\d+\s*[\).:-]\s*", "", name)
    name = re.sub(r"\s*[\*\u2020\u2021]+\s*$", "", name)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    name = re.sub(r'[\u2018\u2019\u0060\u00B4\u0027\u2032]', "'", name)
    if "," in name:
        m = re.match(r"^\s*([A-Za-z.'\- ]+),\s*([A-Za-z.'\- ]+)\s*$", name)
        if m:
            name = f"{m.group(2).strip()} {m.group(1).strip()}".strip()
    name = re.split(
        r'\s+(QB|RB|WR|TE|K|DEF|DST|OL|LB|DB|DL|DE|DT|CB|S|PK)\b', name
    )[0].strip()
    m = re.match(r'^(.+?)([A-Z]{2,3})$', name)
    if m and m.group(2) in _TEAM_CODES and len(m.group(1).strip()) > 3:
        name = m.group(1).strip()
    name = re.sub(
        r'[,\s]+(Jr.?|Sr.?|I{2,3}|IV|V|VI)\s*$', '', name, flags=re.IGNORECASE
    ).strip()
    name = re.sub(r'\s{2,}', ' ', name)
    return name


def pool_normalize_lookup(raw: str) -> str:
    """Normalized key for resilient matching."""
    s = pool_clean_name(raw or "").lower()
    s = s.replace("-", " ").replace(".", "").replace("'", "")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return s
    parts = s.split()
    initial_run = []
    idx = 0
    while idx < len(parts) and len(parts[idx]) == 1:
        initial_run.append(parts[idx])
        idx += 1
    if len(initial_run) >= 2:
        merged = ''.join(initial_run)
        s = ' '.join([merged] + parts[idx:])
    return s


def _is_pick_name(name: str) -> bool:
    s = str(name or "").upper().strip()
    if re.match(r"^20\d{2}\s+(PICK\s+)?[1-6]\.(0?[1-9]|1[0-2])$", s):
        return True
    if re.match(r"^20\d{2}\s+(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)$", s):
        return True
    if re.match(r"^(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)$", s):
        return True
    return False


# ── Sleeper ingestion ──

def extract_sleeper_roster_names(
    sleeper_roster_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract rostered player entries from Sleeper roster data.

    Returns list of {name, position, sleeper_id} dicts.
    """
    positions = sleeper_roster_data.get("positions", {})
    player_ids = sleeper_roster_data.get("playerIds", {})
    entries = []
    for name, pos in positions.items():
        if _is_pick_name(name):
            continue
        clean = pool_clean_name(name)
        if not clean:
            continue
        entries.append({
            "name": clean,
            "position": normalize_position(pos or ""),
            "sleeper_id": str(player_ids.get(name, "") or ""),
        })
    return entries


# ── KTC structured ingestion ──

def extract_ktc_structured(
    full_data_ktc: dict[str, float | int],
    limit: int = KTC_UNIVERSE_LIMIT,
) -> list[dict[str, Any]]:
    """Convert KTC name→value dict to structured rows with derived rank.

    Ranks are derived from deterministic value-descending sort order.
    Only the top `limit` players are included for universe membership.
    """
    cleaned = []
    for name, value in full_data_ktc.items():
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        if _is_pick_name(name):
            continue
        cn = pool_clean_name(name)
        if not cn:
            continue
        cleaned.append({"name": cn, "raw_name": name, "value": float(value)})

    # Sort by value descending — highest value = rank 1
    cleaned.sort(key=lambda x: -x["value"])

    rows = []
    for i, entry in enumerate(cleaned[:limit]):
        rows.append({
            "name": entry["name"],
            "raw_name": entry["raw_name"],
            "source_rank": i + 1,
            "source_value": entry["value"],
            "position": "",  # KTC doesn't reliably expose position in name→value
        })
    return rows


# ── Adamidp PDF extraction ──

def _reconstruct_split_names(lines: list[str]) -> list[str]:
    """Reconstruct player names that were split across PDF lines.

    Common patterns:
    - "Will" + "Anderson" → "Will Anderson"
    - "Akeem" + "Davis" + "Gaither" → "Akeem Davis Gaither"
    - "Rueben Bain" + "Jr" → "Rueben Bain Jr"
    """
    reconstructed = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Check if next line looks like a name continuation (no rank number, short text)
        while (i + 1 < len(lines)
               and lines[i + 1].strip()
               and not re.match(r'^\d+\s', lines[i + 1].strip())
               and len(lines[i + 1].strip().split()) <= 2
               and re.match(r'^[A-Za-z.\'-]+$', lines[i + 1].strip().split()[0])):
            next_part = lines[i + 1].strip()
            # Don't merge if next line looks like a position tag
            if re.match(r'^(QB|RB|WR|TE|LB|DL|DB|DE|DT|CB|S|K|EDGE)$', next_part, re.I):
                break
            line = line + " " + next_part
            i += 1

        reconstructed.append(line)
        i += 1
    return reconstructed


def extract_adamidp_from_artifact(artifact_path: str | Path) -> list[AdamidpRow]:
    """Read a pre-normalized Adamidp JSON artifact.

    The artifact is a JSON file with a list of player dicts.
    """
    path = Path(artifact_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows = []
    if isinstance(data, dict):
        raw_rows = data.get("rows", data.get("players", []))
    elif isinstance(data, list):
        raw_rows = data
    else:
        return []

    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        row = AdamidpRow(
            overall_rank=item.get("overallRank") or item.get("overall_rank"),
            player_name=str(item.get("playerName") or item.get("player_name") or "").strip(),
            position=normalize_position(item.get("position") or ""),
            position_rank=item.get("positionRank") or item.get("position_rank"),
            trade_value_text=str(item.get("tradeValueText") or item.get("trade_value_text") or ""),
            class_year=item.get("classYear") or item.get("class_year"),
            draft_capital=item.get("draftCapital") or item.get("draft_capital"),
            age=item.get("age"),
            source_pdf=str(item.get("sourcePdf") or item.get("source_pdf") or ""),
            ambiguous=bool(item.get("ambiguous", False)),
            ambiguous_reason=str(item.get("ambiguousReason") or item.get("ambiguous_reason") or ""),
        )
        if row.player_name:
            rows.append(row)
    return rows


def dedupe_adamidp_rows(rows: list[AdamidpRow]) -> tuple[list[AdamidpRow], list[AdamidpRow]]:
    """Dedupe Adamidp rows across overlapping PDFs.

    Uses normalized name + position as the key. When duplicates exist,
    keeps the row with the lower overall_rank (better).

    Returns (unique_rows, ambiguous_rows).
    """
    seen: dict[str, AdamidpRow] = {}
    ambiguous: list[AdamidpRow] = []

    for row in rows:
        if row.ambiguous:
            ambiguous.append(row)
            continue

        key = pool_normalize_lookup(row.player_name) + "|" + normalize_position(row.position)

        if key in seen:
            existing = seen[key]
            # Keep the one with the lower (better) overall rank
            if row.overall_rank and existing.overall_rank:
                if row.overall_rank < existing.overall_rank:
                    seen[key] = row
            # Same rank — skip as true duplicate
        else:
            seen[key] = row

    return list(seen.values()), ambiguous


# ── Union construction ──

def build_canonical_pool(
    *,
    sleeper_roster_data: dict[str, Any],
    full_data_ktc: dict[str, float | int],
    adamidp_artifact_path: str | Path | None = None,
    adamidp_rows: list[AdamidpRow] | None = None,
    idp_trade_calc_data: dict[str, float | int] | None = None,
    sleeper_all_nfl: dict[str, Any] | None = None,
) -> tuple[list[CanonicalPoolRow], PoolAuditReport]:
    """Build the canonical player universe.

    Membership rule: a player enters if present in ANY of:
    - Sleeper roster
    - KTC top 525
    - Adamidp PDFs

    IDPTradeCalc enriches but never decides membership.
    """
    report = PoolAuditReport(source_type_docs=dict(SOURCE_TYPES))

    # ── 1. Sleeper roster ──
    sleeper_entries = extract_sleeper_roster_names(sleeper_roster_data)
    report.sleeper_count = len(sleeper_entries)

    # Build normalized lookup for matching
    pool: dict[str, CanonicalPoolRow] = {}
    norm_to_key: dict[str, str] = {}

    for entry in sleeper_entries:
        norm = pool_normalize_lookup(entry["name"])
        if not norm:
            continue
        if norm in norm_to_key:
            # Merge into existing
            existing_key = norm_to_key[norm]
            row = pool[existing_key]
            row.in_sleeper = True
            if not row.sleeper_id and entry.get("sleeper_id"):
                row.sleeper_id = entry["sleeper_id"]
            if not row.sleeper_position and entry.get("position"):
                row.sleeper_position = entry["position"]
        else:
            row = CanonicalPoolRow(
                canonical_name=entry["name"],
                position=entry.get("position", ""),
                in_sleeper=True,
                sleeper_id=entry.get("sleeper_id"),
                sleeper_position=entry.get("position"),
                raw_source_names={"sleeper": entry["name"]},
            )
            pool[norm] = row
            norm_to_key[norm] = norm

    # ── 2. KTC top 525 ──
    ktc_rows = extract_ktc_structured(full_data_ktc, limit=KTC_UNIVERSE_LIMIT)
    report.ktc_top525_count = len(ktc_rows)

    for krow in ktc_rows:
        norm = pool_normalize_lookup(krow["name"])
        if not norm:
            continue
        if norm in norm_to_key:
            existing_key = norm_to_key[norm]
            row = pool[existing_key]
            row.in_ktc_top525 = True
            row.ktc_value = krow["source_value"]
            row.ktc_rank = krow["source_rank"]
            row.raw_source_names["ktc"] = krow["raw_name"]
        else:
            row = CanonicalPoolRow(
                canonical_name=krow["name"],
                in_ktc_top525=True,
                ktc_value=krow["source_value"],
                ktc_rank=krow["source_rank"],
                raw_source_names={"ktc": krow["raw_name"]},
            )
            pool[norm] = row
            norm_to_key[norm] = norm

    # ── 3. Adamidp PDFs ──
    if adamidp_rows is None and adamidp_artifact_path:
        adamidp_rows = extract_adamidp_from_artifact(adamidp_artifact_path)

    if adamidp_rows:
        report.adamidp_extracted_raw_count = len(adamidp_rows)
        unique_rows, ambiguous_rows = dedupe_adamidp_rows(adamidp_rows)
        report.adamidp_unique_count = len(unique_rows)

        for arow in ambiguous_rows:
            report.excluded_names.append({
                "name": arow.player_name,
                "reason": f"ambiguous: {arow.ambiguous_reason}",
                "source": "adamidp",
            })

        for arow in unique_rows:
            norm = pool_normalize_lookup(arow.player_name)
            if not norm:
                report.excluded_names.append({
                    "name": arow.player_name,
                    "reason": "name could not be normalized",
                    "source": "adamidp",
                })
                continue
            if norm in norm_to_key:
                existing_key = norm_to_key[norm]
                row = pool[existing_key]
                row.in_adamidp_pdf = True
                row.adamidp_rank = arow.overall_rank
                row.adamidp_value_text = arow.trade_value_text
                row.adamidp_position_rank = arow.position_rank
                if not row.position and arow.position:
                    row.position = arow.position
                row.raw_source_names["adamidp"] = arow.player_name
            else:
                row = CanonicalPoolRow(
                    canonical_name=arow.player_name,
                    position=arow.position,
                    in_adamidp_pdf=True,
                    adamidp_rank=arow.overall_rank,
                    adamidp_value_text=arow.trade_value_text,
                    adamidp_position_rank=arow.position_rank,
                    raw_source_names={"adamidp": arow.player_name},
                )
                pool[norm] = row
                norm_to_key[norm] = norm

    # ── 4. Position resolution ──
    # Use Sleeper all-NFL DB when available for position truth
    sleeper_all = sleeper_all_nfl or {}
    for norm_key, row in pool.items():
        if row.position:
            row.position = normalize_position(row.position)
            continue

        # Try to resolve from Sleeper all-NFL by ID
        if row.sleeper_id and row.sleeper_id in sleeper_all:
            sdata = sleeper_all[row.sleeper_id]
            if isinstance(sdata, dict):
                pos = normalize_position(sdata.get("position", ""))
                if pos:
                    row.position = pos
                    continue

        # Still unresolved — report it
        if not row.position:
            row.match_status = "position_unresolved"

    # ── 5. Position safety checks ──
    # Offense cannot become IDP from fallback joins
    for norm_key, row in pool.items():
        if row.sleeper_position and row.position:
            sleeper_is_off = is_offense(row.sleeper_position)
            sleeper_is_idp = is_idp(row.sleeper_position)
            current_is_off = is_offense(row.position)
            current_is_idp = is_idp(row.position)

            if sleeper_is_off and current_is_idp:
                row.position = row.sleeper_position
            elif sleeper_is_idp and current_is_off:
                row.position = row.sleeper_position

    # ── 6. Exclude unresolvable entries ──
    excluded_norms = set()
    for norm_key, row in pool.items():
        if not row.canonical_name:
            excluded_norms.add(norm_key)
            report.excluded_names.append({
                "name": "",
                "reason": "empty canonical name",
                "source": ",".join(row.raw_source_names.keys()),
            })
            continue
        if _is_pick_name(row.canonical_name):
            excluded_norms.add(norm_key)
            continue

    for norm_key in excluded_norms:
        pool.pop(norm_key, None)
        norm_to_key.pop(norm_key, None)

    # ── 7. IDPTradeCalc crosswalk (enrichment only) ──
    idp_tc = idp_trade_calc_data or {}
    idp_tc_norm: dict[str, tuple[str, float]] = {}
    for name, value in idp_tc.items():
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        cn = pool_clean_name(name)
        if not cn:
            continue
        n = pool_normalize_lookup(cn)
        if n:
            idp_tc_norm[n] = (cn, float(value))

    queried = 0
    matched = 0
    unmatched_names: list[str] = []

    for norm_key, row in pool.items():
        if _is_pick_name(row.canonical_name):
            continue
        queried += 1
        if norm_key in idp_tc_norm:
            name, val = idp_tc_norm[norm_key]
            row.idp_trade_calc_value = val
            row.idp_trade_calc_matched = True
            row.raw_source_names["idpTradeCalc"] = name
            matched += 1
        else:
            unmatched_names.append(row.canonical_name)

    report.idp_trade_calc_queried_count = queried
    report.idp_trade_calc_matched_count = matched
    report.idp_trade_calc_unmatched_count = queried - matched
    report.idp_trade_calc_unmatched_names = unmatched_names[:100]

    # ── 8. Set match status ──
    for row in pool.values():
        sources = sum([row.in_sleeper, row.in_ktc_top525, row.in_adamidp_pdf])
        if sources >= 2:
            row.match_status = "multi_source"
        elif sources == 1:
            row.match_status = "single_source"

    # ── 9. Compute final union and audit ──
    final_rows = sorted(pool.values(), key=lambda r: (r.ktc_rank or 9999, r.canonical_name))
    report.final_union_count = len(final_rows)

    # Sample unique-to-source lists
    sleeper_only = [r.canonical_name for r in final_rows
                    if r.in_sleeper and not r.in_ktc_top525 and not r.in_adamidp_pdf]
    ktc_only = [r.canonical_name for r in final_rows
                if r.in_ktc_top525 and not r.in_sleeper and not r.in_adamidp_pdf]
    adamidp_only = [r.canonical_name for r in final_rows
                    if r.in_adamidp_pdf and not r.in_sleeper and not r.in_ktc_top525]

    report.sleeper_only_sample = sleeper_only[:20]
    report.ktc_only_sample = ktc_only[:20]
    report.adamidp_only_sample = adamidp_only[:20]

    return final_rows, report
