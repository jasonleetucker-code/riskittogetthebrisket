"""Player context: age, draft capital, experience, career load.

Fills the gaps the Phase-0 audit found (age sparse on the contract,
draft capital and career load absent everywhere) from nflverse public
data: the players id-map (birth date, draft slot, rookie season) plus
weekly stats / snap counts (career loads in each position's mileage
unit).

Builders are pure functions over row lists so tests never touch the
network; ``fetch_and_build_context`` wires them to ``src.nfl_data``
(24h-cached, feature-flag guarded, degrades to an empty context).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping

_LOGGER = logging.getLogger(__name__)

# nflverse listing → BDVM true position.  OLB is genuinely ambiguous
# (3-4 edge vs off-ball); we map it to LB and flag the ambiguity so the
# service can raise designation risk instead of guessing silently.
TRUE_POSITION_MAP = {
    "QB": "QB",
    "RB": "RB",
    "FB": "RB",
    "HB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DT": "DT",
    "NT": "DT",
    "DE": "EDGE",
    "EDGE": "EDGE",
    "LB": "LB",
    "ILB": "LB",
    "MLB": "LB",
    "OLB": "LB",
    "CB": "CB",
    "NB": "CB",
    "S": "S",
    "SAF": "S",
    "FS": "S",
    "SS": "S",
    "DB": "S",
}
_AMBIGUOUS_LISTINGS = frozenset({"OLB", "DB"})

_IDP_TRUE = frozenset({"DT", "EDGE", "LB", "CB", "S"})


@dataclass(frozen=True)
class PlayerContext:
    player_key: str
    birth_date: str | None = None
    draft_year: int | None = None
    draft_overall: int | None = None
    draft_capital_score: float = 0.0  # 0-1; 1.0 = top-10 pick, 0.0 = UDFA/unknown
    rookie_season: int | None = None
    true_position: str | None = None
    position_ambiguous: bool = False
    # career loads by mileage unit (touches/targets/dropbacks/snaps)
    loads: Mapping[str, float] = field(default_factory=dict)

    def age_at_season_start(self, season: int) -> float | None:
        """Age on Sept 1 of ``season`` (the BDVM age convention)."""
        if not self.birth_date:
            return None
        try:
            bd = date.fromisoformat(str(self.birth_date)[:10])
        except ValueError:
            return None
        anchor = date(int(season), 9, 1)
        return round((anchor - bd).days / 365.25, 1)

    def nfl_season_for(self, season: int) -> int | None:
        """1 = rookie year, for the given target season."""
        if self.rookie_season is None:
            return None
        return max(1, int(season) - int(self.rookie_season) + 1)

    def career_load_for(self, unit: str) -> float:
        return float(self.loads.get(unit, 0.0))


def draft_capital_score(draft_overall: int | None) -> float:
    """0-1 score: 1.0 for top-10 picks decaying to 0 by the draft's end.

    Provisional prior (documented judgment call): linear decay from
    pick 10, zero at ~pick 233+.  UDFA / unknown → 0.0 — draft capital
    is an *ascension/survival* input, so unknown must not fabricate
    pedigree.
    """
    if draft_overall is None or draft_overall <= 0:
        return 0.0
    if draft_overall <= 10:
        return 1.0
    return max(0.0, min(1.0, 1.045 - 0.0045 * float(draft_overall)))


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _opt_int(v: Any) -> int | None:
    try:
        s = str(v).strip()
        if not s:
            return None
        return int(float(s))
    except (TypeError, ValueError):
        return None


def build_player_context(
    *,
    id_map_rows: Iterable[Mapping[str, Any]],
    weekly_rows: Iterable[Mapping[str, Any]] = (),
    snap_rows: Iterable[Mapping[str, Any]] = (),
    name_normalizer,
) -> dict[str, PlayerContext]:
    """Pure builder: nflverse rows → context keyed by normalized name.

    ``weekly_rows`` / ``snap_rows`` may span multiple seasons; loads are
    summed over whatever is provided (an underestimate for veterans
    whose careers predate the fetched window — conservative direction,
    since mileage only ever *adds* effective age above the reference
    load).
    """
    # -- career loads --------------------------------------------------
    touches: dict[str, float] = {}
    targets: dict[str, float] = {}
    dropbacks: dict[str, float] = {}
    def_snaps: dict[str, float] = {}

    for row in weekly_rows:
        name = row.get("player_display_name") or row.get("player_name") or ""
        if not name:
            continue
        key = name_normalizer(str(name))
        carries = _num(row.get("carries"))
        recs = _num(row.get("receptions"))
        tgts = _num(row.get("targets"))
        atts = _num(row.get("attempts"))
        sacks_taken = _num(row.get("sacks_suffered") or row.get("sacks"))
        touches[key] = touches.get(key, 0.0) + carries + recs
        targets[key] = targets.get(key, 0.0) + tgts
        dropbacks[key] = dropbacks.get(key, 0.0) + atts + sacks_taken

    for row in snap_rows:
        name = row.get("player") or row.get("player_display_name") or ""
        if not name:
            continue
        key = name_normalizer(str(name))
        def_snaps[key] = def_snaps.get(key, 0.0) + _num(row.get("defense_snaps"))

    # -- identity / draft ----------------------------------------------
    out: dict[str, PlayerContext] = {}
    for row in id_map_rows:
        name = row.get("display_name") or ""
        if not name:
            continue
        key = name_normalizer(str(name))
        if key in out:
            # keep the row with the most recent activity
            if _opt_int(row.get("last_season")) is None:
                continue
        listing = str(row.get("position") or "").upper()
        true_pos = TRUE_POSITION_MAP.get(listing)
        draft_year = _opt_int(row.get("draft_year"))
        # nflverse players.csv ``draft_pick`` is the OVERALL selection
        # (verified: Brock Purdy round 7, draft_pick 262).
        overall = _opt_int(row.get("draft_pick"))
        rookie = _opt_int(row.get("rookie_season")) or draft_year
        out[key] = PlayerContext(
            player_key=key,
            birth_date=str(row.get("birth_date") or "") or None,
            draft_year=draft_year,
            draft_overall=overall,
            draft_capital_score=draft_capital_score(overall),
            rookie_season=rookie,
            true_position=true_pos,
            position_ambiguous=listing in _AMBIGUOUS_LISTINGS,
            loads={
                "touches": touches.get(key, 0.0),
                "targets": targets.get(key, 0.0),
                "dropbacks": dropbacks.get(key, 0.0),
                "snaps": def_snaps.get(key, 0.0),
            },
        )
    return out


def fetch_and_build_context(
    season: int,
    *,
    seasons_back: int = 6,
    include_snaps: bool = True,
    name_normalizer=None,
    cache_only: bool = False,
) -> dict[str, PlayerContext]:
    """Fetch nflverse data (cached, flag-guarded) and build the context.

    Degrades to {} on any fetch failure — the engine then falls back to
    contract ages and neutral priors exactly as before this module
    existed.

    ``cache_only=True`` is the REQUEST-PATH mode: it reads whatever the
    refresh owner has already materialised and NEVER fetches.  With
    ``seasons_back=6`` a cold fetch here is six seasons of weekly stats
    plus six of snap counts — ~270,000 rows — and parsing that inside the
    serving process is what starved ``/api/data`` past the Next bridge's
    4s idle timeout.  When nothing is materialised the result is the same
    empty context this function already returns on failure, so the engine
    degrades exactly as it always has: neutral priors, never zeroed
    career load.
    """
    if name_normalizer is None:
        from src.utils.name_clean import normalize_player_name as name_normalizer  # noqa: PLC0415
    try:
        from src.nfl_data import ingest  # noqa: PLC0415

        id_rows = ingest.fetch_id_map(cache_only=cache_only)
        years = [y for y in range(season - seasons_back, season)]
        weekly: list[Mapping[str, Any]] = []
        try:
            weekly = ingest.fetch_weekly_stats(years, cache_only=cache_only)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("bdvm context: weekly stats unavailable: %s", exc)
        snaps: list[Mapping[str, Any]] = []
        if include_snaps:
            try:
                snaps = ingest.fetch_snap_counts(years, cache_only=cache_only)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("bdvm context: snap counts unavailable: %s", exc)
        return build_player_context(
            id_map_rows=id_rows,
            weekly_rows=weekly,
            snap_rows=snaps,
            name_normalizer=name_normalizer,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm context unavailable (degrading to empty): %s", exc)
        return {}
