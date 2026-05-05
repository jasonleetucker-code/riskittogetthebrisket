"""TE Premium Lab — sandbox analysis of TE scoring + lineup changes.

Research-only.  This module never writes to ``latest_contract_data``,
never persists anything to the live ``data/canonical/`` snapshot,
and never adjusts any player's ``rankDerivedValue``, ``_composite``,
or any other live ranking field.  All outputs are computed on-the-fly
from immutable inputs and returned as plain dicts.

What this module answers
────────────────────────
"If we remove TE Premium scoring (extra TE reception bonus + extra TE
first-down bonus) but require teams to start two tight ends, how
should TE values shift compared to today?"

It separates four signals so they can be inspected independently:

1. **External market TE Premium boost** — for every source where we
   have both a "normal" and a "TE Premium" board, the per-player
   percentage boost the market applies to TEs.  Today the only source
   that gives us both boards in one scrape is KTC (``ktc.csv`` vs
   ``ktcSfTep.csv``).  Everything else either ships only one board
   (DLF SF, FantasyCalc, etc.) or is rank-only and not directly
   comparable; those are flagged "unavailable" rather than guessed.

2. **Internal scoring effect** — uses the existing
   ``_scoringAdjustment`` block already present on every offensive
   player in the live contract.  Each row carries a per-rule
   ``rule_contributions`` map keyed by category — e.g.
   ``{"te_premium": -0.35, "first_downs": 3.01, "receptions": -3.39}``
   in PPG terms vs the league's baseline scoring.  Removing the TE
   premium category + the TE-specific portion of ``first_downs``
   tells us how many PPG each TE *loses* if we strip those bonuses
   from the scoring config.

3. **Internal scarcity effect** — VOR (value over replacement) with
   the league's actual lineup vs the proposed lineup.  Today's
   ``starters.TE = 1`` plus FLEX/SFLEX contributions yields ~12-14
   starting TEs in a 12-team league.  Bumping ``starters.TE`` to 2
   yields ~24-26.  Replacement-level PPG drops accordingly, every
   TE's VOR rises, and the scarcity boost partially offsets the lost
   premium scoring.

4. **Recommended adjustment** — a per-player and per-tier net
   estimate combining (1) + (2) + (3).  Tier-based, not flat.  Marked
   with confidence so the operator can see when the signal is thin.

Math + safety notes
───────────────────
* Percentage boosts use a min-floor on the denominator
  (``_MIN_VALUE_FLOOR``) so a ``$50 → $200`` move on a deep-bench TE
  doesn't get reported as ``+300%`` against a near-zero base.  Below
  the floor the boost is reported as ``None`` and flagged
  ``unreliable``.
* The Hill curve from ``src/canonical/player_valuation.py`` is reused
  for converting hypothetical rank moves to value moves — never
  redefined, never re-fit.  This module imports ``rank_to_value``
  directly so any future curve refit picks up automatically.
* ``compute_internal_scoring_effect`` strips the TE premium
  contributions from each player's existing PPG delta in the live
  contract, rather than re-running the scoring pipeline from scratch.
  This keeps the sandbox aligned with the same scoring engine that
  produced the live values; we're not running a second-source
  scoring engine that could disagree.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.canonical.player_valuation import (
    HILL_MIDPOINT,
    HILL_SLOPE,
    rank_to_value,
)
from src.scoring.replacement_level import (
    PlayerSeasonRow,
    replacement_per_game,
    starter_slot_counts,
    vorp_table,
)


# ── Constants ────────────────────────────────────────────────────────

# Below this raw source value, percentage boosts become unstable.
# Reported as ``None`` + flagged unreliable instead of producing wild
# multipliers on near-zero bench rows.
_MIN_VALUE_FLOOR: float = 200.0

# Default repo paths — overridable via kwargs for testing.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KTC_NORMAL_CSV = _REPO_ROOT / "CSVs" / "site_raw" / "ktc.csv"
_DEFAULT_KTC_TEP_CSV = _REPO_ROOT / "CSVs" / "site_raw" / "ktcSfTep.csv"
_DEFAULT_LEAGUE_REGISTRY = _REPO_ROOT / "config" / "leagues" / "registry.json"
_DEFAULT_SANDBOX_DIR = _REPO_ROOT / "data" / "sandbox" / "te_premium"

# TE tier definitions — combine TE rank + age so "young upside" and
# "older productive" surface as distinct buckets.  Boundaries are
# deliberately conservative: a flat 24-row TE2 cutoff in a 2-TE-start
# 12-team league is the entire starter pool, and "depth" (TE3+)
# captures everyone outside.
_TIER_DEFS: tuple[dict[str, Any], ...] = (
    {"key": "elite_te1", "label": "Elite TE1", "max_rank": 3},
    {"key": "strong_te1", "label": "Strong TE1", "max_rank": 8},
    {"key": "back_te1", "label": "Low TE1 / High TE2", "max_rank": 14},
    {"key": "te2", "label": "TE2 range", "max_rank": 24},
    {"key": "depth", "label": "Depth TE", "max_rank": 60},
    {"key": "deep", "label": "Deep TE", "max_rank": 999},
)

# Age buckets — applied as a secondary tag, not a primary tier.
_YOUNG_AGE_THRESHOLD = 25
_OLDER_AGE_THRESHOLD = 30


# ── Public dataclasses ───────────────────────────────────────────────


@dataclass(frozen=True)
class TEPremiumBoost:
    """One source's normal-vs-premium comparison for one player."""

    source: str
    player_id: str
    display_name: str
    normal_value: float | None
    premium_value: float | None
    normal_rank: int | None
    premium_rank: int | None
    boost_abs: float | None
    boost_pct: float | None
    log_ratio: float | None
    rank_change: int | None
    reliable: bool
    note: str = ""


@dataclass(frozen=True)
class TEScoringEffect:
    """Per-player effect of removing the TE premium scoring rules."""

    player_id: str
    display_name: str
    current_ppg_delta: float
    te_premium_ppg: float
    te_first_down_ppg: float
    proposed_ppg_delta: float
    scoring_swing_ppg: float
    confidence: float
    archetype: str = ""


@dataclass(frozen=True)
class TEScarcityRow:
    """Per-TE VOR under both lineup configurations."""

    player_id: str
    display_name: str
    points: float
    games: int
    vor_one_te: float
    vor_two_te: float
    vor_delta: float
    replacement_one_te_ppg: float
    replacement_two_te_ppg: float


@dataclass(frozen=True)
class TEPremiumRecommendation:
    player_id: str
    display_name: str
    tier: str
    age: int | None
    current_value: float | None
    market_boost_pct: float | None
    scoring_swing_ppg: float
    scarcity_value_delta: float
    recommended_adjustment_pct: float
    recommended_value: float | None
    confidence: float
    notes: list[str] = field(default_factory=list)


# ── External market loaders ──────────────────────────────────────────


def _read_ktc_csv(path: Path) -> dict[str, float]:
    """Read a KTC CSV (``name,value`` rows) into a name→value dict.

    The current scrape format is a flat two-column CSV with no
    position metadata; we filter out picks (anything starting with a
    year prefix) at the caller and rely on the contract's own TE list
    for matching.  Missing file → empty dict; the comparison code
    flags the source as unavailable in that case.
    """
    out: dict[str, float] = {}
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                try:
                    val = float(row.get("value") or 0)
                except (TypeError, ValueError):
                    continue
                if val <= 0:
                    continue
                out[_normalize_name_for_match(name)] = val
    except (OSError, csv.Error):
        return {}
    return out


def _normalize_name_for_match(name: str) -> str:
    """Lower-case + strip punctuation for fuzzy-but-deterministic match.

    Mirrors the same normalisation used in ``src/utils/name_clean``
    minimally — keeping the surface area small so the sandbox doesn't
    drift from the canonical matcher's contract.  This is only used
    for comparing scraped CSV rows to live-contract player names; the
    live contract already carries Sleeper IDs we use as the primary
    key when available.
    """
    s = (name or "").lower().strip()
    s = s.replace(".", "").replace("'", "").replace("-", " ")
    s = " ".join(s.split())
    # Drop common position/team suffixes the CSVs sometimes carry.
    for suffix in (" qb", " rb", " wr", " te", " k", " def", " dl", " lb", " db"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s.strip()


def load_external_ktc_boards(
    *,
    normal_path: Path | None = None,
    premium_path: Path | None = None,
) -> dict[str, dict]:
    """Load both KTC boards (normal SF + TE-Premium SF) into name maps.

    Returns:
        ``{
            "normal": {normalized_name: value, ...},
            "premium": {normalized_name: value, ...},
            "normal_path": "...",
            "premium_path": "...",
            "normal_available": bool,
            "premium_available": bool,
        }``

    Both paths default to the canonical scraper outputs at
    ``CSVs/site_raw/ktc.csv`` and ``CSVs/site_raw/ktcSfTep.csv``.
    The "premium" board is KTC's TE+ Level 1 ("TE Premium") sub-board.
    KTC's TE++ (Level 2) board is structurally available in the API
    response but is NOT currently extracted by ``Dynasty Scraper.py``
    (see ``_KTC_TEP_FIELD_KEYS`` — only level 1 is plucked); when
    requested it's flagged unavailable.
    """
    np_path = Path(normal_path) if normal_path else _DEFAULT_KTC_NORMAL_CSV
    pp_path = Path(premium_path) if premium_path else _DEFAULT_KTC_TEP_CSV
    normal = _read_ktc_csv(np_path)
    premium = _read_ktc_csv(pp_path)
    return {
        "normal": normal,
        "premium": premium,
        "normal_path": str(np_path),
        "premium_path": str(pp_path),
        "normal_available": bool(normal),
        "premium_available": bool(premium),
    }


# ── Contract readers ─────────────────────────────────────────────────


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _coerce_int(v: Any) -> int | None:
    f = _coerce_float(v)
    if f is None:
        return None
    return int(round(f))


def extract_te_players_from_contract(contract: dict | None) -> list[dict]:
    """Pull the TE rows out of the live contract.

    Returns a list of dicts with the fields the sandbox needs:
    ``player_id`` (Sleeper ID when available, else canonical name),
    ``display_name``, ``team``, ``age``, ``position``, ``rank``,
    ``position_rank``, ``current_value``, ``ktc_normal``,
    ``ktc_premium``, ``scoring_adjustment`` (the raw block from the
    contract), ``ppg_test`` / ``ppg_custom`` / ``games`` etc.

    The contract has two parallel shapes — a name-keyed ``players``
    dict and a flat ``playersArray`` — depending on which field has
    been populated.  Both can carry TE rows; we consume whichever is
    present and dedupe by Sleeper ID first, name second.
    """
    if not isinstance(contract, dict):
        return []

    rows: dict[str, dict] = {}

    def _push(row: dict) -> None:
        if not isinstance(row, dict):
            return
        position = str(row.get("position") or row.get("pos") or "").upper()
        if position != "TE":
            return
        sleeper_id = (
            row.get("_sleeperId")
            or row.get("sleeperId")
            or row.get("sleeper_id")
        )
        sleeper_id = str(sleeper_id) if sleeper_id else ""
        display_name = str(
            row.get("displayName")
            or row.get("display_name")
            or row.get("name")
            or row.get("playerName")
            or ""
        ).strip()
        if not display_name:
            return
        key = sleeper_id or display_name.lower()
        if key in rows:
            return  # First write wins; both shapes carry the same fields.

        scoring_adj = (
            row.get("_scoringAdjustment")
            or row.get("scoringAdjustment")
            or {}
        )
        ppg_test = _coerce_float(
            row.get("_formatFitPPGTest") or row.get("formatFitPPGTest")
        )
        ppg_custom = _coerce_float(
            row.get("_formatFitPPGCustom") or row.get("formatFitPPGCustom")
        )
        rule_contribs = (
            scoring_adj.get("rule_contributions") if isinstance(scoring_adj, dict) else {}
        ) or {}

        rows[key] = {
            "player_id": key,
            "sleeper_id": sleeper_id,
            "display_name": display_name,
            "team": str(row.get("team") or row.get("team_abbr") or "").upper() or None,
            "age": _coerce_int(row.get("age")),
            "position": "TE",
            "rank": _coerce_int(
                row.get("rank")
                or row.get("canonicalConsensusRank")
                or row.get("canonical_consensus_rank")
            ),
            "position_rank": _coerce_int(
                row.get("positionRank") or row.get("position_rank")
            ),
            "current_value": _coerce_float(
                row.get("rankDerivedValue")
                or row.get("rank_derived_value")
                or row.get("_composite")
                or row.get("displayValue")
                or row.get("value")
            ),
            "ktc_normal_value": _coerce_float(
                row.get("ktc")
                or row.get("KTC")
                or (row.get("_canonicalSiteValues") or {}).get("ktc")
            ),
            "ktc_premium_value": _coerce_float(
                row.get("ktcSfTep")
                or row.get("ktcSftep")
                or row.get("ktc_sf_tep")
                or (row.get("_canonicalSiteValues") or {}).get("ktcSfTep")
            ),
            "ppg_baseline": ppg_test,
            "ppg_league": ppg_custom,
            "scoring_adjustment": dict(scoring_adj) if isinstance(scoring_adj, dict) else {},
            "rule_contributions": dict(rule_contribs) if isinstance(rule_contribs, dict) else {},
            "archetype": str(scoring_adj.get("archetype") or "") if isinstance(scoring_adj, dict) else "",
            "scoring_confidence": _coerce_float(
                scoring_adj.get("confidence") if isinstance(scoring_adj, dict) else None
            ) or 0.0,
            "rookie": bool(row.get("rookie") or row.get("isRookie")),
        }

    players_dict = contract.get("players")
    if isinstance(players_dict, dict):
        for name, row in players_dict.items():
            if isinstance(row, dict):
                merged = dict(row)
                merged.setdefault("displayName", name)
                _push(merged)

    arr = contract.get("playersArray")
    if isinstance(arr, list):
        for row in arr:
            _push(row)

    out = list(rows.values())
    # Sort by current_value descending so the natural "TE rank within the TE pool"
    # is just the index + 1.
    out.sort(key=lambda r: -(r.get("current_value") or 0))
    for idx, row in enumerate(out):
        row["te_pool_rank"] = idx + 1
    return out


# ── 1. External market boost ─────────────────────────────────────────


def compute_external_market_boost(
    te_rows: list[dict],
    *,
    boards: dict | None = None,
    source: str = "ktc",
) -> list[TEPremiumBoost]:
    """Compute per-TE normal-vs-premium boost for an external source.

    Today only KTC publishes both boards from the same scrape.  The
    function is structured so additional sources can be added by
    extending ``boards`` (each entry needs a ``normal`` + ``premium``
    name→value map).  Sources without both boards are skipped at the
    caller; this function expects a usable ``boards`` argument.

    Per player:
        boost_abs = premium - normal
        boost_pct = (premium - normal) / max(normal, _MIN_VALUE_FLOOR)
        log_ratio = log(premium / normal)  when both > 0

    When either side is missing we return ``None`` for the derived
    fields and ``reliable=False`` with a note.  When ``normal`` is
    below ``_MIN_VALUE_FLOOR`` we still compute ``boost_abs`` but flag
    ``boost_pct`` unreliable so the UI can mark it.
    """
    out: list[TEPremiumBoost] = []
    if not te_rows or not isinstance(boards, dict):
        return out
    normal_map = (boards.get("normal") or {}) if isinstance(boards.get("normal"), dict) else {}
    premium_map = (
        (boards.get("premium") or {}) if isinstance(boards.get("premium"), dict) else {}
    )
    if not normal_map or not premium_map:
        return out

    # Pre-compute per-board ranks so we can report rank movement.
    normal_ranked = sorted(normal_map.items(), key=lambda kv: -kv[1])
    premium_ranked = sorted(premium_map.items(), key=lambda kv: -kv[1])
    normal_rank = {name: idx + 1 for idx, (name, _) in enumerate(normal_ranked)}
    premium_rank = {name: idx + 1 for idx, (name, _) in enumerate(premium_ranked)}

    for row in te_rows:
        norm_key = _normalize_name_for_match(row.get("display_name") or "")
        if not norm_key:
            continue
        n_val = normal_map.get(norm_key)
        p_val = premium_map.get(norm_key)
        if n_val is None and p_val is None:
            continue  # No comparison data for this player; skip rather than emit nulls.

        boost_abs: float | None = None
        boost_pct: float | None = None
        log_ratio: float | None = None
        reliable = True
        note = ""

        if n_val is None:
            note = "missing on normal board"
            reliable = False
        elif p_val is None:
            note = "missing on premium board"
            reliable = False
        else:
            boost_abs = float(p_val) - float(n_val)
            denom = max(float(n_val), _MIN_VALUE_FLOOR)
            boost_pct = boost_abs / denom
            if float(n_val) < _MIN_VALUE_FLOOR:
                reliable = False
                note = (
                    f"normal value {n_val:.0f} below floor "
                    f"{_MIN_VALUE_FLOOR:.0f}; pct unreliable"
                )
            if n_val and p_val and n_val > 0 and p_val > 0:
                log_ratio = math.log(float(p_val) / float(n_val))

        n_rank = normal_rank.get(norm_key)
        p_rank = premium_rank.get(norm_key)
        rank_change = (
            (n_rank - p_rank) if isinstance(n_rank, int) and isinstance(p_rank, int) else None
        )

        out.append(
            TEPremiumBoost(
                source=source,
                player_id=str(row.get("player_id") or row.get("display_name") or ""),
                display_name=str(row.get("display_name") or ""),
                normal_value=float(n_val) if n_val is not None else None,
                premium_value=float(p_val) if p_val is not None else None,
                normal_rank=n_rank,
                premium_rank=p_rank,
                boost_abs=boost_abs,
                boost_pct=boost_pct,
                log_ratio=log_ratio,
                rank_change=rank_change,
                reliable=reliable,
                note=note,
            )
        )
    return out


# ── 2. Internal scoring effect ───────────────────────────────────────


def _ppg_to_value_units(
    ppg: float, *, current_value: float | None, ppg_baseline: float | None
) -> float:
    """Crude PPG→value conversion using the player's own implied scale.

    Uses the player's existing ``current_value : ppg_baseline`` ratio
    when both are present; otherwise falls back to ~25 value units per
    PPG, which is the empirical median across mid-pack TEs in the
    legacy ``_formatFitFinalScoringDeltaValue`` field (e.g. -0.72 PPG
    × ~26.7 = -19.2 value units on Brock Bowers).  This is "good
    enough" for a sandbox — the operator looks at the magnitude, not
    the third decimal.
    """
    if current_value and ppg_baseline and ppg_baseline > 0:
        ratio = current_value / ppg_baseline
        return ppg * ratio
    return ppg * 25.0


def compute_internal_scoring_effect(
    te_rows: list[dict],
    *,
    remove_te_reception_bonus: bool = True,
    remove_te_first_down_bonus: bool = True,
) -> list[TEScoringEffect]:
    """Project the PPG impact of removing TE premium components.

    Reads each TE's pre-computed ``rule_contributions`` map (already
    on every offensive row in the live contract via
    ``src/scoring/scoring_delta.py::bucket_rule_contributions``).
    The relevant categories:

        * ``te_premium``  — bonus for extra TE receptions (``bonus_rec_te``)
        * ``first_downs`` — TE-specific portion is ``bonus_fd_te``,
          but the contribution dict aggregates QB/RB/WR/TE first-down
          bonuses into a single ``first_downs`` key.  For TEs the only
          first-down rule that contributes is the TE one, so the full
          category contribution attributed to a TE row IS the TE
          first-down bonus.  This holds because
          ``bucket_rule_contributions`` filters rules by
          ``relevant_buckets`` before summing.

    Removing one or both of those rules takes the player's existing
    ``final_scoring_delta_points`` and adds the offsetting amount.
    """
    out: list[TEScoringEffect] = []
    for row in te_rows:
        sa = row.get("scoring_adjustment") or {}
        rules = row.get("rule_contributions") or {}
        current_delta = _coerce_float(sa.get("final_scoring_delta_points")) or 0.0

        te_premium_ppg = _coerce_float(rules.get("te_premium")) or 0.0
        te_fd_ppg = _coerce_float(rules.get("first_downs")) or 0.0

        # Removing a rule means subtracting its delta contribution
        # from the league side (not the baseline side).  The rule_contributions
        # map carries (league - baseline) per category, so dropping the
        # rule entirely zeros that category's contribution.
        offset = 0.0
        if remove_te_reception_bonus:
            offset -= te_premium_ppg
        if remove_te_first_down_bonus:
            offset -= te_fd_ppg

        proposed_delta = current_delta + offset
        scoring_swing = proposed_delta - current_delta  # always == offset

        out.append(
            TEScoringEffect(
                player_id=str(row.get("player_id") or ""),
                display_name=str(row.get("display_name") or ""),
                current_ppg_delta=round(current_delta, 4),
                te_premium_ppg=round(te_premium_ppg, 4),
                te_first_down_ppg=round(te_fd_ppg, 4),
                proposed_ppg_delta=round(proposed_delta, 4),
                scoring_swing_ppg=round(scoring_swing, 4),
                confidence=float(row.get("scoring_confidence") or 0.0),
                archetype=str(row.get("archetype") or ""),
            )
        )
    return out


# ── 3. Internal scarcity effect ──────────────────────────────────────


def _build_player_season_rows(
    te_rows: list[dict],
    *,
    games: int = 17,
    ppg_field: str = "ppg_league",
) -> list[PlayerSeasonRow]:
    """Convert TE contract rows to PlayerSeasonRow for VOR math.

    Uses the season-pace PPG as the "points" anchor and assumes a full
    17-game season for replacement math.  The replacement_per_game
    helper in ``src/scoring/replacement_level.py`` only cares about
    per-game pace, so any consistent ``games`` works.

    Falls back to ``ppg_baseline`` (test scoring) when ``ppg_league``
    is missing — this can happen for TEs without enough sample for a
    league-specific projection, in which case the baseline pace is
    still a reasonable scarcity signal.
    """
    out: list[PlayerSeasonRow] = []
    for row in te_rows:
        ppg = _coerce_float(row.get(ppg_field))
        if ppg is None:
            ppg = _coerce_float(row.get("ppg_baseline"))
        if ppg is None or ppg <= 0:
            continue
        out.append(
            PlayerSeasonRow(
                player_id=str(row.get("player_id") or ""),
                position="TE",
                points=float(ppg) * games,
                games=games,
                player_name=str(row.get("display_name") or ""),
            )
        )
    return out


def compute_scarcity_effect(
    te_rows: list[dict],
    *,
    one_te_starters: int = 12,
    two_te_starters: int = 24,
    games: int = 17,
    ppg_field: str = "ppg_league",
) -> tuple[list[TEScarcityRow], dict]:
    """Compute VOR for every TE under both lineup environments.

    ``one_te_starters`` defaults to 12 (a 12-team league with one TE
    starter slot, ignoring flex contributions which the league
    registry exposes separately).  ``two_te_starters`` defaults to 24
    (the proposed scenario: 12 teams × 2 starting TEs).  Both can be
    overridden by the caller — e.g. a 10-team league passes 10 / 20.

    Returns ``(rows, summary)`` where ``summary`` carries the
    replacement-level baselines, the count of evaluable TEs, and a
    quick-stat for the average value swing.  All values rounded.
    """
    season_rows = _build_player_season_rows(te_rows, games=games, ppg_field=ppg_field)
    if not season_rows:
        return [], {
            "evaluable_tes": 0,
            "replacement_one_te_ppg": 0.0,
            "replacement_two_te_ppg": 0.0,
            "avg_vor_delta": 0.0,
        }

    rep_one = replacement_per_game(season_rows, one_te_starters)
    rep_two = replacement_per_game(season_rows, two_te_starters)

    rows: list[TEScarcityRow] = []
    for r in season_rows:
        vor_one = r.points - (rep_one * r.games)
        vor_two = r.points - (rep_two * r.games)
        rows.append(
            TEScarcityRow(
                player_id=r.player_id,
                display_name=r.player_name,
                points=round(r.points, 2),
                games=r.games,
                vor_one_te=round(vor_one, 2),
                vor_two_te=round(vor_two, 2),
                vor_delta=round(vor_two - vor_one, 2),
                replacement_one_te_ppg=round(rep_one, 4),
                replacement_two_te_ppg=round(rep_two, 4),
            )
        )

    rows.sort(key=lambda r: -r.vor_two_te)
    avg_delta = (
        statistics.fmean(r.vor_delta for r in rows) if rows else 0.0
    )
    summary = {
        "evaluable_tes": len(rows),
        "replacement_one_te_ppg": round(rep_one, 4),
        "replacement_two_te_ppg": round(rep_two, 4),
        "avg_vor_delta": round(avg_delta, 2),
    }
    return rows, summary


# ── 4. Tier assignment + recommendation ──────────────────────────────


def assign_te_tier(te_pool_rank: int | None, age: int | None) -> dict[str, str]:
    """Map (TE-pool rank, age) → tier label + age tag.

    Tier is the primary classification (rank-based); age tag is a
    secondary signal so the recommendation can dampen older productive
    TEs and lift young upside TEs even within the same tier.
    """
    tier_key = "deep"
    tier_label = "Deep TE"
    if isinstance(te_pool_rank, int) and te_pool_rank > 0:
        for spec in _TIER_DEFS:
            if te_pool_rank <= spec["max_rank"]:
                tier_key = spec["key"]
                tier_label = spec["label"]
                break
    age_tag = ""
    if isinstance(age, int):
        if age <= _YOUNG_AGE_THRESHOLD:
            age_tag = "young_upside"
        elif age >= _OLDER_AGE_THRESHOLD:
            age_tag = "older_productive"
    return {"tier_key": tier_key, "tier_label": tier_label, "age_tag": age_tag}


def _tier_market_boost_default(tier_key: str) -> float:
    """Heuristic fallback when the live KTC TEP boards are missing.

    These are *not* used when the actual boards are loaded — the real
    per-player boost wins.  They exist so the page renders something
    sensible on a fresh dev machine without scraped CSVs.  Magnitudes
    chosen to be conservative (smaller than the typical KTC-observed
    boost) so the operator notices the disclaimer rather than acting
    on a synthetic recommendation.
    """
    return {
        "elite_te1": 0.05,
        "strong_te1": 0.07,
        "back_te1": 0.10,
        "te2": 0.12,
        "depth": 0.08,
        "deep": 0.04,
    }.get(tier_key, 0.06)


def build_recommendations(
    te_rows: list[dict],
    *,
    boost_rows: list[TEPremiumBoost] | None,
    scoring_rows: list[TEScoringEffect],
    scarcity_rows: list[TEScarcityRow],
    market_available: bool,
) -> list[TEPremiumRecommendation]:
    """Combine the three signals into a per-player recommended adjust %.

    Net adjustment = market_boost_pct (sign-flipped — when removing
    TEP we *give back* whatever TEP added) + scarcity_value_delta_pct
    + scoring_value_delta_pct.

    Confidence is the geometric mean of the per-source confidences:
    market reliability + internal scoring confidence + a flat 0.7 for
    scarcity (the VOR math is well-defined but depends on PPG inputs
    that have their own variance).
    """
    boost_by_id: dict[str, TEPremiumBoost] = {}
    for b in boost_rows or []:
        if b.reliable and b.boost_pct is not None:
            boost_by_id[b.player_id] = b
    scoring_by_id = {s.player_id: s for s in scoring_rows}
    scarcity_by_id = {s.player_id: s for s in scarcity_rows}

    out: list[TEPremiumRecommendation] = []
    for row in te_rows:
        pid = str(row.get("player_id") or "")
        tier = assign_te_tier(row.get("te_pool_rank"), row.get("age"))
        current_value = _coerce_float(row.get("current_value"))

        # Market signal: invert sign because removing TEP unwinds the
        # market premium, but adding scarcity from 2-TE start re-applies
        # demand pressure.  Net market + lineup pressure ≈
        # -market_pct + market_pct = 0 only if 2-TE start fully
        # mirrors KTC TEP — historically it's slightly larger
        # (KTC TE++ > KTC TEP+), so the operator sees this in the
        # sandbox and decides whether to lift or hold.
        m_signal: float | None = None
        m_boost = boost_by_id.get(pid)
        if m_boost and m_boost.boost_pct is not None:
            m_signal = float(m_boost.boost_pct)
        elif not market_available:
            m_signal = _tier_market_boost_default(tier["tier_key"])

        # Internal scoring signal — convert PPG swing to value units
        # using the player's own value:ppg ratio, then to pct of value.
        s_eff = scoring_by_id.get(pid)
        scoring_swing_ppg = float(s_eff.scoring_swing_ppg) if s_eff else 0.0
        scoring_value_delta = _ppg_to_value_units(
            scoring_swing_ppg,
            current_value=current_value,
            ppg_baseline=row.get("ppg_baseline"),
        )
        scoring_value_delta_pct = (
            scoring_value_delta / current_value if current_value and current_value > 0 else 0.0
        )

        # Scarcity signal — convert VOR delta (extra points above
        # replacement when we go to 2-TE start) to a percentage of
        # current value.  The VOR delta is in season-points; the
        # ppg→value mapping above already amortizes that.
        sc_row = scarcity_by_id.get(pid)
        scarcity_value_delta = 0.0
        scarcity_value_delta_pct = 0.0
        if sc_row:
            scarcity_value_delta = _ppg_to_value_units(
                sc_row.vor_delta / max(1, sc_row.games),
                current_value=current_value,
                ppg_baseline=row.get("ppg_baseline"),
            )
            if current_value and current_value > 0:
                scarcity_value_delta_pct = scarcity_value_delta / current_value

        # Market boost is what KTC charges for TE Premium — when we
        # *remove* TEP, we unwind that boost (negative).  The
        # 2-TE-start scarcity demand re-adds value (positive).  Net
        # is: -market_pct + scarcity_pct + scoring_pct.
        market_unwind_pct = -float(m_signal) if m_signal is not None else 0.0
        net_pct = market_unwind_pct + scarcity_value_delta_pct + scoring_value_delta_pct

        # Cap the recommended adjustment to ±25% to prevent runaway
        # values on thin signal — the sandbox surfaces the unclipped
        # signal in the player table for transparency, but the
        # recommendation column stays in a reasonable range.
        recommended_pct = max(-0.25, min(0.25, net_pct))
        recommended_value = (
            current_value * (1.0 + recommended_pct) if current_value else None
        )

        # Confidence: geometric mean of three components, clamped to
        # [0.1, 1.0].  Missing market data drops the market component
        # to 0.5, missing scoring to 0.5.
        market_conf = 0.85 if (m_boost and m_boost.reliable) else 0.5
        scoring_conf = float(s_eff.confidence) if s_eff and s_eff.confidence else 0.5
        scarcity_conf = 0.7 if sc_row else 0.4
        confidence = (market_conf * scoring_conf * scarcity_conf) ** (1.0 / 3.0)

        notes: list[str] = []
        if m_boost and not m_boost.reliable:
            notes.append("Market boost flagged unreliable.")
        if not market_available:
            notes.append("No external market boards loaded; using tier default.")
        if s_eff and s_eff.confidence < 0.4:
            notes.append("Low scoring-fit confidence (small projection sample).")
        if not sc_row:
            notes.append("No PPG sample; scarcity skipped.")
        if abs(net_pct) > 0.25:
            notes.append(
                f"Raw net signal {net_pct:+.0%} clipped to "
                f"{recommended_pct:+.0%} for safety."
            )
        if tier.get("age_tag") == "older_productive":
            notes.append("Older productive — discount a touch beyond the model.")
        if tier.get("age_tag") == "young_upside":
            notes.append("Young upside — model may understate ceiling.")

        out.append(
            TEPremiumRecommendation(
                player_id=pid,
                display_name=str(row.get("display_name") or ""),
                tier=tier["tier_label"],
                age=row.get("age"),
                current_value=current_value,
                market_boost_pct=m_signal,
                scoring_swing_ppg=scoring_swing_ppg,
                scarcity_value_delta=round(scarcity_value_delta, 2),
                recommended_adjustment_pct=round(recommended_pct, 4),
                recommended_value=round(recommended_value, 0) if recommended_value else None,
                confidence=round(confidence, 3),
                notes=notes,
            )
        )
    return out


# ── Tier summary ─────────────────────────────────────────────────────


def summarise_by_tier(
    te_rows: list[dict],
    *,
    boost_rows: list[TEPremiumBoost],
    scoring_rows: list[TEScoringEffect],
    scarcity_rows: list[TEScarcityRow],
    recommendations: list[TEPremiumRecommendation],
) -> list[dict]:
    """Group every per-player signal into the tier definitions."""
    boost_by_id = {b.player_id: b for b in boost_rows if b.reliable}
    scoring_by_id = {s.player_id: s for s in scoring_rows}
    scarcity_by_id = {s.player_id: s for s in scarcity_rows}
    rec_by_id = {r.player_id: r for r in recommendations}

    by_tier: dict[str, list[dict]] = {spec["key"]: [] for spec in _TIER_DEFS}
    for row in te_rows:
        tier = assign_te_tier(row.get("te_pool_rank"), row.get("age"))
        by_tier.setdefault(tier["tier_key"], []).append(row)

    out: list[dict] = []
    for spec in _TIER_DEFS:
        members = by_tier.get(spec["key"]) or []
        if not members:
            continue
        ids = [str(m.get("player_id") or "") for m in members]
        cur_values = [v for v in (m.get("current_value") for m in members) if v]
        boosts = [boost_by_id[i].boost_pct for i in ids if i in boost_by_id and boost_by_id[i].boost_pct is not None]
        scoring_swings = [scoring_by_id[i].scoring_swing_ppg for i in ids if i in scoring_by_id]
        scarcity_deltas = [scarcity_by_id[i].vor_delta for i in ids if i in scarcity_by_id]
        rec_pcts = [rec_by_id[i].recommended_adjustment_pct for i in ids if i in rec_by_id]
        confs = [rec_by_id[i].confidence for i in ids if i in rec_by_id]

        out.append(
            {
                "tier_key": spec["key"],
                "tier_label": spec["label"],
                "player_count": len(members),
                "avg_current_value": round(statistics.fmean(cur_values), 0) if cur_values else None,
                "avg_market_boost_pct": (
                    round(statistics.fmean(boosts), 4) if boosts else None
                ),
                "avg_scoring_swing_ppg": (
                    round(statistics.fmean(scoring_swings), 4) if scoring_swings else None
                ),
                "avg_scarcity_vor_delta": (
                    round(statistics.fmean(scarcity_deltas), 2) if scarcity_deltas else None
                ),
                "recommended_adjustment_range": (
                    [round(min(rec_pcts), 4), round(max(rec_pcts), 4)] if rec_pcts else None
                ),
                "avg_recommended_adjustment_pct": (
                    round(statistics.fmean(rec_pcts), 4) if rec_pcts else None
                ),
                "avg_confidence": (
                    round(statistics.fmean(confs), 3) if confs else None
                ),
            }
        )
    return out


# ── Top-level orchestrators ──────────────────────────────────────────


def _league_lineup_settings(
    league_cfg: Any | None,
    *,
    fallback_team_count: int = 12,
) -> dict[str, int]:
    """Pull starter slot counts for TE under 1-TE and 2-TE lineups.

    Reuses ``starter_slot_counts`` from
    ``src/scoring/replacement_level.py`` so flex/superflex
    contributions are accounted for consistently with the rest of the
    app's VOR math.  When ``league_cfg`` is missing we fall back to
    a 12-team league with QB/RB/RB/WR/WR/WR/TE/FLEX/FLEX/SFLEX
    starters — the registry default for ``dynasty_main``.
    """
    starters: dict[str, int] = {}
    team_count = fallback_team_count
    extra_te = 0
    if league_cfg is not None:
        rs = getattr(league_cfg, "roster_settings", None) or {}
        if isinstance(rs, dict):
            try:
                team_count = int(rs.get("teamCount") or fallback_team_count)
            except (TypeError, ValueError):
                team_count = fallback_team_count
            starters_raw = rs.get("starters") or {}
            roster_positions: list[str] = []
            for pos, count in starters_raw.items():
                try:
                    n = int(count)
                except (TypeError, ValueError):
                    n = 0
                pos_norm = str(pos).upper()
                roster_positions.extend([pos_norm] * max(0, n))
            slots = starter_slot_counts(roster_positions, team_count)
            te_one = int(slots.get("TE", team_count))
            te_two = te_one + team_count  # +1 starter per team
            return {
                "team_count": team_count,
                "te_starters_one": te_one,
                "te_starters_two": te_two,
            }
    return {
        "team_count": team_count,
        "te_starters_one": team_count,
        "te_starters_two": team_count * 2,
    }


def build_overview(
    contract: dict | None,
    league_cfg: Any | None = None,
    *,
    boards: dict | None = None,
) -> dict:
    """Read-only overview: data sources, league settings, warnings.

    Cheap; no heavy computation.  Used to populate the page header +
    controls panel before any analysis is run.
    """
    te_rows = extract_te_players_from_contract(contract)
    if boards is None:
        boards = load_external_ktc_boards()
    lineup = _league_lineup_settings(league_cfg)

    sources_status = [
        {
            "key": "ktc",
            "label": "KeepTradeCut",
            "supports_normal": True,
            "supports_te_premium": bool(boards.get("premium_available")),
            "supports_te_plus_plus": False,
            "note": (
                "KTC ships normal SF + TE+ Level 1 boards from the same scrape. "
                "TE++ (Level 2) is in the API response but not currently "
                "extracted by Dynasty Scraper.py — see _KTC_TEP_FIELD_KEYS."
            ),
            "available": bool(boards.get("normal_available") and boards.get("premium_available")),
        },
        {
            "key": "dlf_sf",
            "label": "Dynasty League Football",
            "supports_normal": True,
            "supports_te_premium": False,
            "supports_te_plus_plus": False,
            "note": "DLF SF board is rank-only and standard SF — no TEP variant available.",
            "available": False,
        },
        {
            "key": "fantasy_calc",
            "label": "FantasyCalc",
            "supports_normal": True,
            "supports_te_premium": False,
            "supports_te_plus_plus": False,
            "note": "FantasyCalc has TE Premium settings on their site; not currently scraped here.",
            "available": False,
        },
        {
            "key": "manual_csv",
            "label": "Manual CSV upload",
            "supports_normal": True,
            "supports_te_premium": True,
            "supports_te_plus_plus": True,
            "note": "Drop a CSV at CSVs/site_raw/te_premium_manual.csv with columns name,value,format.",
            "available": False,
        },
    ]

    # Surface a warning if the live contract has no TEs (likely a
    # cold-start dev machine before the first scrape) or no scoring
    # adjustment block (running against legacy data).
    warnings: list[str] = []
    if not te_rows:
        warnings.append(
            "No TE rows found in the live contract.  Run a scrape first; "
            "until then this page renders with empty data."
        )
    elif not any(r.get("rule_contributions") for r in te_rows):
        warnings.append(
            "No scoring rule contributions found on TE rows; the internal "
            "scoring effect tab will read zero.  Likely the live contract "
            "predates the per-rule scoring delta refactor."
        )
    if not boards.get("premium_available"):
        warnings.append(
            "KTC TE-Premium board (CSVs/site_raw/ktcSfTep.csv) is empty or missing.  "
            "External market comparison falls back to tier-default heuristics."
        )

    return {
        "leagueKey": getattr(league_cfg, "key", None),
        "scoringProfile": getattr(league_cfg, "scoring_profile", None),
        "lineup": lineup,
        "te_count": len(te_rows),
        "sources": sources_status,
        "warnings": warnings,
        "sandbox": True,
        "note": (
            "Research-only sandbox.  Outputs from this page are NOT applied "
            "to live player values.  No write endpoint exists for that path."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run_analysis(
    contract: dict | None,
    league_cfg: Any | None = None,
    *,
    remove_te_reception_bonus: bool = True,
    remove_te_first_down_bonus: bool = True,
    use_two_te_starters: bool = True,
    include_rookies: bool = True,
    boards: dict | None = None,
    persist: bool = False,
    sandbox_dir: Path | None = None,
) -> dict:
    """One-shot sandbox analysis.

    Pure read against ``contract``; does NOT mutate any field.  When
    ``persist=True`` the result is also written to
    ``data/sandbox/te_premium/<run_id>.json`` for audit; this is
    additive (a brand-new directory the live pipeline doesn't touch)
    and never overwrites a live snapshot.
    """
    te_rows = extract_te_players_from_contract(contract)
    if not include_rookies:
        te_rows = [r for r in te_rows if not r.get("rookie")]
    if boards is None:
        boards = load_external_ktc_boards()
    lineup = _league_lineup_settings(league_cfg)

    boost_rows = compute_external_market_boost(te_rows, boards=boards, source="ktc")
    scoring_rows = compute_internal_scoring_effect(
        te_rows,
        remove_te_reception_bonus=remove_te_reception_bonus,
        remove_te_first_down_bonus=remove_te_first_down_bonus,
    )

    one_te = lineup["te_starters_one"]
    two_te = lineup["te_starters_two"] if use_two_te_starters else lineup["te_starters_one"]
    scarcity_rows, scarcity_summary = compute_scarcity_effect(
        te_rows,
        one_te_starters=one_te,
        two_te_starters=two_te,
    )

    market_available = bool(boards.get("premium_available") and boards.get("normal_available"))
    recommendations = build_recommendations(
        te_rows,
        boost_rows=boost_rows,
        scoring_rows=scoring_rows,
        scarcity_rows=scarcity_rows,
        market_available=market_available,
    )
    tier_summary = summarise_by_tier(
        te_rows,
        boost_rows=boost_rows,
        scoring_rows=scoring_rows,
        scarcity_rows=scarcity_rows,
        recommendations=recommendations,
    )

    avg_market_boost = (
        statistics.fmean(b.boost_pct for b in boost_rows if b.reliable and b.boost_pct is not None)
        if any(b.reliable and b.boost_pct is not None for b in boost_rows)
        else None
    )
    avg_scoring_swing = (
        statistics.fmean(s.scoring_swing_ppg for s in scoring_rows)
        if scoring_rows
        else 0.0
    )
    avg_scarcity_delta = scarcity_summary.get("avg_vor_delta") or 0.0
    avg_recommended_pct = (
        statistics.fmean(r.recommended_adjustment_pct for r in recommendations)
        if recommendations
        else 0.0
    )
    avg_confidence = (
        statistics.fmean(r.confidence for r in recommendations) if recommendations else 0.0
    )

    summary = {
        "te_count": len(te_rows),
        "evaluable_for_market": sum(1 for b in boost_rows if b.reliable),
        "evaluable_for_scoring": sum(
            1 for s in scoring_rows if abs(s.scoring_swing_ppg) > 1e-6
        ),
        "evaluable_for_scarcity": scarcity_summary.get("evaluable_tes", 0),
        "avg_market_boost_pct": (
            round(avg_market_boost, 4) if avg_market_boost is not None else None
        ),
        "avg_internal_scoring_swing_ppg": round(avg_scoring_swing, 4),
        "avg_scarcity_vor_delta_points": round(avg_scarcity_delta, 2),
        "avg_recommended_adjustment_pct": round(avg_recommended_pct, 4),
        "avg_confidence": round(avg_confidence, 3),
        "lineup": lineup,
        "te_starters_proposed": two_te,
    }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sandbox": True,
        "leagueKey": getattr(league_cfg, "key", None),
        "scoringProfile": getattr(league_cfg, "scoring_profile", None),
        "scenario": {
            "remove_te_reception_bonus": remove_te_reception_bonus,
            "remove_te_first_down_bonus": remove_te_first_down_bonus,
            "use_two_te_starters": use_two_te_starters,
            "include_rookies": include_rookies,
        },
        "summary": summary,
        "scarcity_summary": scarcity_summary,
        "external_boards": {
            "ktc_normal_available": bool(boards.get("normal_available")),
            "ktc_premium_available": bool(boards.get("premium_available")),
            "ktc_te_plus_plus_available": False,
            "normal_path": boards.get("normal_path"),
            "premium_path": boards.get("premium_path"),
        },
        "players": [
            {
                **{k: v for k, v in row.items() if k not in {"rule_contributions", "scoring_adjustment"}},
                "tier": assign_te_tier(row.get("te_pool_rank"), row.get("age")),
            }
            for row in te_rows
        ],
        "external_boost": [b.__dict__ for b in boost_rows],
        "scoring_effect": [s.__dict__ for s in scoring_rows],
        "scarcity_effect": [s.__dict__ for s in scarcity_rows],
        "recommendations": [
            {**r.__dict__, "notes": list(r.notes)} for r in recommendations
        ],
        "tier_summary": tier_summary,
        "warnings": (
            []
            if (boards.get("normal_available") and boards.get("premium_available"))
            else ["External market boards unavailable; recommendations use tier defaults."]
        ),
    }

    if persist:
        out_dir = Path(sandbox_dir) if sandbox_dir else _DEFAULT_SANDBOX_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"te_premium_{run_id}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        payload["persisted_path"] = str(out_path)

    return payload


__all__ = [
    "TEPremiumBoost",
    "TEScoringEffect",
    "TEScarcityRow",
    "TEPremiumRecommendation",
    "load_external_ktc_boards",
    "extract_te_players_from_contract",
    "compute_external_market_boost",
    "compute_internal_scoring_effect",
    "compute_scarcity_effect",
    "assign_te_tier",
    "build_recommendations",
    "summarise_by_tier",
    "build_overview",
    "run_analysis",
]
