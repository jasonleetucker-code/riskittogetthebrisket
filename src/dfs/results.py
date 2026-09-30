"""Contest RESULTS import + forecast evaluation — the first learning-loop evidence.

A DraftKings contest-standings file (downloaded by the owner after a slate) has
two blocks side by side: the field's entries (Rank, EntryId, EntryName,
TimeRemaining, Points, Lineup) and a player table (Player, Roster Position,
%Drafted, FPTS).  Layout status: ``assumed`` — the commonly documented shape,
not a verified template; a header that does not match is refused.

From it:

* **realized ownership and points** per slate athlete, joined by normalized
  name + position (the file carries no player IDs).  Two slate athletes that
  the join cannot tell apart are quarantined, never first-wins;
* **field lineups**, parsed from the ``Lineup`` string and resolved the same
  way — a lineup with any unresolved name is kept but marked unresolved;
* **evaluation** of what the owner imported for this slate: projected
  ownership vs realized %Drafted, projection vs actual FPTS.

A player the results do not list is NOT 0% / 0 points: it is counted apart
(``notInResults``).  That also means the evaluation excludes them — reported,
because true zero-ownership players are exactly the ones the file tends to omit.
Evaluation is evidence only; it promotes, reweights or changes nothing.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

from src.dfs.imports import ImportError_, SlateAthlete
from src.dfs.rules import RuleSet
from src.utils.name_clean import normalize_player_name

LAYOUT = "draftkings_contest_standings_v1"
LAYOUT_VERIFICATION = "assumed"
_ENTRY_COLS = ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"]
_PLAYER_COLS = ["Player", "Roster Position", "%Drafted", "FPTS"]
_OWN_BANDS = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 101)]
MAX_FIELD_ENTRIES = 250_000
DUP_SAMPLE_REPEATED = 5_000
DUP_SAMPLE_SINGLES = 2_000
# Large-field standings run to tens of MB.  Production nginx refuses bodies over
# 25 MB (deploy/nginx/chaseupside-proxy.conf), so this stays under it; bigger
# fields are refused with FILE_TOO_LARGE rather than half-read.
MAX_RESULTS_BYTES = 24 * 1024 * 1024


def _num(raw: str | None, pct: bool = False) -> float | None:
    if raw is None:
        return None
    s = raw.strip().rstrip("%") if pct else raw.strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _athlete_index(athletes: list[SlateAthlete]) -> dict[tuple[str, str], list[SlateAthlete]]:
    idx: dict[tuple[str, str], list[SlateAthlete]] = {}
    for a in athletes:
        labels = set(a.positions) | set(a.eligible_slots)
        for pos in labels:
            idx.setdefault((normalize_player_name(a.name), pos.upper()), []).append(a)
    return idx


def _resolve(
    idx: dict[tuple[str, str], list[SlateAthlete]], name: str, pos: str
) -> tuple[SlateAthlete | None, str | None]:
    cands = idx.get((normalize_player_name(name), pos.upper()), [])
    ids = {c.player_id for c in cands}
    if len(ids) == 1:
        return cands[0], None
    return None, ("ambiguous_identity" if ids else "no_slate_athlete")


def _is_owner_entry(entry_id: str, entry_name: str, ids: set[str], username: str | None) -> bool:
    if entry_id in ids:
        return True
    if not username:
        return False
    # DraftKings names multi-entries "user (3/20)"; the handle is the part before " (".
    handle = entry_name.split(" (", 1)[0].strip()
    return handle.casefold() == username.strip().casefold()


def parse_standings(
    text: str,
    ruleset: RuleSet,
    athletes: list[SlateAthlete],
    *,
    owner_entry_ids: list[str] | None = None,
    owner_username: str | None = None,
) -> dict[str, Any]:
    if ruleset.platform != "draftkings":
        raise ImportError_(
            "UNSUPPORTED_FORMAT",
            f"Contest results are only understood for DraftKings so far ({ruleset.platform} is not).",
        )
    if len(text.encode("utf-8")) > MAX_RESULTS_BYTES:
        raise ImportError_(
            "FILE_TOO_LARGE",
            f"Results files over {MAX_RESULTS_BYTES // (1024 * 1024)} MB are refused.",
        )
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise ImportError_("EMPTY_FILE", "The results file is empty.")
    header = [h.strip() for h in rows[0]]
    if header[: len(_ENTRY_COLS)] != _ENTRY_COLS or not all(c in header for c in _PLAYER_COLS):
        raise ImportError_(
            "RESULTS_FILE_UNRECOGNISED",
            "This does not match the expected contest-standings layout.",
            {"expected": _ENTRY_COLS + ["", *_PLAYER_COLS], "found": header[:12]},
        )
    col = {h: i for i, h in enumerate(header) if h}
    idx = _athlete_index(athletes)
    by_name: dict[str, set[str]] = {}
    for a in athletes:
        by_name.setdefault(normalize_player_name(a.name), set()).add(a.player_id)
    one_by_name = {n: next(iter(ids)) for n, ids in by_name.items() if len(ids) == 1}
    slot_labels = sorted({s.name.upper() for s in ruleset.slots}, key=len, reverse=True)

    realized: dict[str, dict[str, Any]] = {}
    quarantined: list[dict[str, Any]] = []
    field: list[dict[str, Any]] = []
    points_counts: dict[float, int] = {}
    unscored_entries = 0
    owner_ids = {str(x).strip() for x in (owner_entry_ids or [])}
    owner_entries: list[dict[str, Any]] = []
    for r_i, row in enumerate(rows[1:], start=2):
        cell = lambda name: row[col[name]].strip() if col[name] < len(row) else ""  # noqa: E731
        name = cell("Player")
        if name:
            pos = cell("Roster Position")
            own, pts = _num(cell("%Drafted"), pct=True), _num(cell("FPTS"))
            a, why = _resolve(idx, name, pos)
            if a is None:
                quarantined.append({"row": r_i, "name": name[:80], "position": pos, "reason": why})
            elif own is None:
                quarantined.append({"row": r_i, "name": name[:80], "reason": "drafted_not_numeric"})
            else:
                realized[a.player_id] = {"ownership": own, "points": pts}
        entry = cell("EntryId")
        if entry:
            # Every entry's score counts toward rank and ties, lineup readable or not.
            pts = _num(cell("Points"))
            if pts is None:
                unscored_entries += 1
            else:
                points_counts[pts] = points_counts.get(pts, 0) + 1
            if _is_owner_entry(entry, cell("EntryName"), owner_ids, owner_username):
                owner_entries.append(
                    {
                        "entryId": entry[:40],
                        "entryName": cell("EntryName")[:80],
                        "points": pts,
                        "platformRank": _num(cell("Rank")),
                    }
                )
            if len(field) < MAX_FIELD_ENTRIES:
                field.append(_field_entry(row, col, idx, one_by_name, slot_labels))
    resolved_lineups = sum(1 for f in field if f["state"] == "resolved")
    return {
        "layout": LAYOUT,
        "layoutVerification": LAYOUT_VERIFICATION,
        "realized": realized,
        "quarantined": quarantined[:200],
        "field": {
            "entries": len(field),
            "resolvedLineups": resolved_lineups,
            "unresolvedLineups": len(field) - resolved_lineups,
            "truncated": len(field) >= MAX_FIELD_ENTRIES,
            "sample": field[:25],
        },
        # Full-field score distribution: rank and tie size for any score.
        "pointsCounts": sorted(points_counts.items(), key=lambda kv: -kv[0]),
        "unscoredEntries": unscored_entries,
        "ownerEntries": owner_entries,
        "duplication": duplication([f["lineup"] for f in field if f["state"] == "resolved"]),
    }


def duplication(lineups: list[list[str]]) -> dict[str, Any] | None:
    """How often identical lineups (same players, any slot order) recur in the field.

    Over RESOLVED lineups only — an unresolved lineup cannot be compared, and
    the resolved share is reported so the histogram is never read as the whole field.
    """
    if not lineups:
        return None
    from collections import Counter

    import random

    counts = Counter(frozenset(lu) for lu in lineups)
    hist = Counter(counts.values())  # copies-per-lineup -> how many distinct lineups
    # Compact FITTING SAMPLE for the duplication model (DFS-MOD-06): every lineup
    # entered more than once, plus a seeded sample of single-entry lineups carrying
    # the inverse sampling rate as its weight — so a fit sees the real mix without
    # storing a 150k-entry field.
    repeated = [(sorted(k), c) for k, c in counts.items() if c > 1][:DUP_SAMPLE_REPEATED]
    singles = sorted(sorted(k) for k, c in counts.items() if c == 1)
    take = min(len(singles), DUP_SAMPLE_SINGLES)
    picked = random.Random(1729).sample(singles, take) if take else []
    single_weight = len(singles) / take if take else None
    return {
        "lineupsCompared": len(lineups),
        "distinctLineups": len(counts),
        "entriesInDuplicatedLineups": sum(c for c in counts.values() if c > 1),
        "histogram": {str(k): v for k, v in sorted(hist.items())},
        "maxCopies": max(counts.values()),
        "fitSample": {
            "repeated": [{"players": p, "count": c, "weight": 1.0} for p, c in repeated],
            "singles": [{"players": p, "count": 1, "weight": single_weight} for p in picked],
            "repeatedTruncated": sum(1 for c in counts.values() if c > 1) > DUP_SAMPLE_REPEATED,
        },
    }


def _field_entry(row, col, idx, one_by_name, slot_labels) -> dict[str, Any]:
    def cell(name: str) -> str:
        return row[col[name]].strip() if col[name] < len(row) else ""

    lineup_text = cell("Lineup")
    pattern = r"(?:^|\s)(" + "|".join(re.escape(s) for s in slot_labels) + r")\s"
    parts = re.split(pattern, " " + lineup_text + " ")
    # re.split yields [prefix, slot, name, slot, name, ...]
    pairs = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
    ids, unresolved = [], []
    for slot, name in pairs:
        a, _why = _resolve(idx, name, slot)
        # A flex slot label is not the player's position: fall back to a name
        # that is unique on the whole slate, never a best guess among several.
        pid = a.player_id if a else one_by_name.get(normalize_player_name(name))
        if pid is None:
            unresolved.append(name[:60])
        else:
            ids.append(pid)
    state = "resolved" if pairs and not unresolved else "unresolved"
    return {
        "entryId": cell("EntryId")[:40],
        "rank": _num(cell("Rank")),
        "points": _num(cell("Points")),
        "state": state,
        "lineup": ids if state == "resolved" else [],
        "unresolved": unresolved[:9],
    }


def evaluate(athletes: list[SlateAthlete], realized: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Imported forecasts vs realized results, for athletes that have BOTH."""
    by_id = {a.player_id: a for a in athletes}
    own_pairs = [
        (by_id[p].ownership, r["ownership"])
        for p, r in realized.items()
        if by_id[p].ownership is not None
    ]
    proj_pairs = [
        (by_id[p].projection, r["points"])
        for p, r in realized.items()
        if by_id[p].projection is not None and r["points"] is not None
    ]
    forecast_not_in_results = sum(
        1 for a in athletes if a.ownership is not None and a.player_id not in realized
    )

    def stats(pairs: list[tuple[float, float]]) -> dict[str, Any] | None:
        if not pairs:
            return None
        errs = [f - r for f, r in pairs]
        return {
            "n": len(pairs),
            "bias": round(sum(errs) / len(errs), 3),  # + = forecast too high
            "mae": round(sum(abs(e) for e in errs) / len(errs), 3),
            "rmse": round(math.sqrt(sum(e * e for e in errs) / len(errs)), 3),
        }

    bands = []
    for lo, hi in _OWN_BANDS:
        inside = [(f, r) for f, r in own_pairs if lo <= f < hi]
        if inside:
            bands.append(
                {
                    "band": f"{lo}–{hi if hi <= 100 else '100'}%",
                    "n": len(inside),
                    "meanForecast": round(sum(f for f, _ in inside) / len(inside), 2),
                    "meanRealized": round(sum(r for _, r in inside) / len(inside), 2),
                }
            )
    return {
        "ownership": stats(own_pairs),
        "ownershipBands": bands,
        "projection": stats(proj_pairs),
        "notInResults": forecast_not_in_results,
        "note": (
            "Evaluation only: nothing is reweighted or promoted. Players the results do not list are "
            "excluded, not scored 0% — true zero-ownership players are what such files tend to omit."
        ),
    }
