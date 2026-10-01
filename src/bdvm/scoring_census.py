"""BDVM scoring-coverage census: which league-card rules can a projection score?

This MODULE is reporting only: nothing in it changes a projected point, a
value, or a consensus weight; it measures where the projection lane's
per-game totals are partial and by how much.

It is NOT true that the unit which introduced it changed no value.  The same
unit made ``src/nfl_data/realized_points.py`` emit the whole position-scoped
reception-bonus family (``bonus_rec_rb`` / ``bonus_rec_wr`` / ``bonus_rec_te``)
instead of the TE member only.  That flows into every
``compute_weekly_points`` caller — BDVM projection rescoring, the
reconstructed baseline, in-season actuals, and
``league_comparison/scoring_engine.py`` — and on dynasty_main's live card
(``bonus_rec_wr`` 0.02/rec) every WR gains 0.02 per reception.  Host-verified
and measured on a before/after BDVM board in
``docs/research/bdvm-v1/scoring-census-2026-10-01/`` (``host_verification.json``,
``board_diff.json``).

Two layers, deliberately separate:

* **engine** — does ``realized_points`` read the rule at all?  Answered by
  ``src.nfl_data.scoring_coverage.classify`` (a behavioural probe), never
  re-derived here.
* **source vocabulary** — given that the engine reads it, can each
  projection SOURCE supply the stat?  Answered by the same probe idea:
  build a stat line carrying exactly the columns a source can emit, then ask
  BDVM's own scorer (``score_stat_line_per_game_detailed``, first-down
  imputation on, as the projection boundary runs it) whether the rule moves
  the score.  The vocabularies are DERIVED by running each adapter's own
  parser on a synthetic input, so an adapter that starts emitting a new
  column shows up here without editing a list.

Classification (projection lane, priced positions only):

* ``NOT_APPLICABLE`` — team-defense / kicker rules (BDVM prices neither).
* ``MAPPING_ERROR`` — the engine ignores a rule whose stat exists (probe
  verdict ``GAP``), or a declared, host-evidenced column mismapping
  (:data:`ENGINE_MAPPING_FINDINGS`).
* ``UNSUPPORTED_VOCABULARY`` — no real projection source covering the
  affected positions can emit the stat.  Includes the PLAY-TYPE first-down
  rules (:data:`PLAY_TYPE_FIRST_DOWN_KEYS`): the realized engine also reads
  no column for them (probe ``GAP``), but for the projection lane the
  question is the source, and no projection source publishes play-type first
  downs.  They must never be derived from aggregate yards.
* ``ABSENT_FIELD`` — some covering source emits it and another does not, so
  players covered only by the latter are partial.
* ``SUPPORTED_IMPUTED`` — every covering source supplies it, but at least one
  only through an ESTIMATE (today: ``bonus_fd_*`` from the first-down-rate
  model on yards).  The points are not omitted; they rest on an imputation,
  so they are reported apart from directly supplied rules.
* ``SUPPORTED`` — every covering source supplies it directly.

A COUNT of unscored keys is not a share of missing points.  Where realized
history is supplied, impact is measured as the rule's realized 2025 points
under the card (signed), its share of the affected families' realized
points, and the number of players who recorded the stat.  Rules can be
NEGATIVE (``fum_lost``, ``pass_int_td``): an omitted penalty OVERSTATES a
partial total, so a partial total is not a lower bound.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from src.bdvm.source_vocabulary import (  # noqa: F401  (re-exported: one owner)
    IDP_FAMILIES,
    KICKER_KEYS,
    OFFENSE_FAMILIES,
    PRICED_FAMILIES,
    PRICED_POSITIONS,
    SPECIAL_TEAMS_KEYS,
    _probe_line,
    clay_vocabularies,
    engine_fires,
    idpshow_vocabulary,
    manual_csv_vocabulary,
    source_supply,
)
from src.bdvm.source_vocabulary import family_of as _family
from src.bdvm.source_vocabulary import rule_families as _rule_families
from src.nfl_data.realized_points import (
    _SCORING_KEY_ALIASES,
    _SIMPLE_KEYS,
    PBP_SUPPLEMENT_KEYS,
    PBP_SUPPLEMENT_ROW_KEY,
    _pbp_supplement_line,
    compute_weekly_points,
    sleeper_stat_line_from_row,
)
from src.nfl_data.scoring_coverage import Coverage, classify

CENSUS_VERSION = "bdvm-scoring-census.v1"

#: Real (non-proxy) projection sources and the families they cover.
REAL_SOURCES: dict[str, frozenset[str]] = {
    "clayOffense": OFFENSE_FAMILIES,
    "clayIdp": IDP_FAMILIES,
    "idpShow": IDP_FAMILIES,
}
#: Adapter lanes that carry no live data feed but bound what COULD be supplied.
CAPABILITY_SOURCES: tuple[str, ...] = ("manualCsv", "reconstructedBaseline")

#: Engine column mismappings established against HOST truth (not a probe
#: verdict: the engine DOES read the rule, from the wrong column).  Measured
#: here on realized history when supplied; the evidence string is the host
#: comparison that established it.
ENGINE_MAPPING_FINDINGS: dict[str, dict[str, str]] = {}
# RESOLVED 2026-10-01 (BDVM correctness unit J1): ``idp_fum_rec`` /
# ``idp_fum_ret_yd`` read ``fumble_recovery_own`` / ``_yards_own``.  The
# realized engine now reads the opponent-recovery columns minus the
# play-by-play special-teams recoveries, host-golden 92/92 on rostered
# dynasty_main 2025 player-weeks — see
# ``docs/research/bdvm-v1/fumble-recovery-host-golden-2026-10-01/`` and
# ``tests/nfl_data/test_idp_fumble_recovery_host_golden.py``.  The mechanism
# stays for the next host-evidenced mismapping.

#: Sleeper's PLAY-TYPE first-down rules (distinct from the position-scoped
#: ``bonus_fd_*`` family — see realized_points ``_FIRST_DOWN_BONUS_KEYS``).
#: No projection source publishes first downs by play type, so for the
#: projection lane these are UNSUPPORTED_VOCABULARY, never a mapping fix:
#: deriving them from aggregate yards would be a fabricated stat.
PLAY_TYPE_FIRST_DOWN_KEYS: frozenset[str] = frozenset({"pass_fd", "rush_fd", "rec_fd"})

#: Realized-history measurement only (never a projection input): the nflverse
#: first-down column and the TD column Sleeper's count excludes.
_PLAY_TYPE_FD_COLUMNS: dict[str, tuple[str, str]] = {
    "pass_fd": ("passing_first_downs", "passing_tds"),
    "rush_fd": ("rushing_first_downs", "rushing_tds"),
    "rec_fd": ("receiving_first_downs", "receiving_tds"),
}

_PLAY_TYPE_FD_REMEDY = (
    "a projection feed publishing first downs BY PLAY TYPE (none does); never "
    "derive them from aggregate yards or the position-scoped first-down imputation"
)

# What a capable projection feed / forecast component would have to supply.
_REMEDY: dict[str, str] = {
    "pass_fd": _PLAY_TYPE_FD_REMEDY,
    "rush_fd": _PLAY_TYPE_FD_REMEDY,
    "rec_fd": _PLAY_TYPE_FD_REMEDY,
    "bonus_fd_qb": "a projection feed publishing first downs; today imputed from yards by the first-down-rate model",
    "bonus_fd_rb": "a projection feed publishing first downs; today imputed from yards by the first-down-rate model",
    "bonus_fd_wr": "a projection feed publishing first downs; today imputed from yards by the first-down-rate model",
    "bonus_fd_te": "a projection feed publishing first downs; today imputed from yards by the first-down-rate model",
    "rec_0_4": "per-target depth distribution (a reception-distance forecast); historical PBP can train it but is not a projection",
    "rec_5_9": "per-target depth distribution (a reception-distance forecast)",
    "rec_10_19": "per-target depth distribution (a reception-distance forecast)",
    "rec_20_29": "per-target depth distribution (a reception-distance forecast)",
    "rec_30_39": "per-target depth distribution (a reception-distance forecast)",
    "rec_40p": "per-target depth distribution (a reception-distance forecast)",
    "fum_lost": "a projection feed publishing fumbles lost (Clay's guide has no fumbles column); manual CSV 'fumbles_lost' column is accepted",
    "pass_2pt": "a projection feed publishing 2-pt conversions",
    "rush_2pt": "a projection feed publishing 2-pt conversions",
    "rec_2pt": "a projection feed publishing 2-pt conversions",
    "pass_int_td": "a pick-six-thrown rate component (no projection feed publishes it)",
    "kr_yd": "a return-role / return-yards projection",
    "pr_yd": "a return-role / return-yards projection",
    "st_td": "a return-TD projection",
    "punt_ret_td": "a return-TD projection",
    "kick_ret_td": "a return-TD projection",
    "st_tkl_solo": "a special-teams snap/tackle projection",
    "st_ff": "a special-teams forced-fumble projection",
    "st_fum_rec": "a special-teams fumble-recovery projection",
    "idp_tkl_loss": "an IDP feed with TFL (IDP Show has it; Clay's guide does not)",
    "idp_pass_def": "an IDP feed with passes defended (IDP Show has it; Clay's guide does not)",
    "idp_qb_hit": "an IDP feed with QB hits (IDP Show has it; Clay's guide does not)",
    "idp_ff": "an IDP feed with forced fumbles (Clay's FF column does not survive text extraction)",
    "idp_fum_rec": "an IDP feed with fumble recoveries",
    "idp_def_td": "an IDP feed with defensive TDs",
    "idp_safe": "an IDP feed with safeties",
    "idp_sack_yd": "an IDP feed with sack yards (none publishes it)",
    "idp_int_ret_yd": "an IDP feed with interception return yards (none publishes it)",
    "idp_fum_ret_yd": "an IDP feed with fumble return yards (none publishes it)",
    "idp_blk_kick": "an IDP feed with blocked kicks (none publishes it)",
    "pass_sack": "already in Clay ('Sk')",
}


# ---------------------------------------------------------------------------
# Probes (source vocabularies and source_supply live in src.bdvm.source_vocabulary)
# ---------------------------------------------------------------------------


def baseline_supply(key: str) -> str:
    """The reconstructed baseline scores realized weekly rows + the PBP supplement."""
    return "direct" if classify(key, pbp_supplement=True) is Coverage.SCORED else "none"


def engine_positions(key: str) -> tuple[str, ...]:
    """Priced positions at which the rule can fire on a maximal realized row."""
    return tuple(pos for pos in PRICED_POSITIONS if engine_fires(key, pos))


def weight_sign(rate: float) -> str:
    return "+" if rate > 0 else "-"


def _num(value: Any) -> float | None:
    """A finite number, or ``None`` when absent / unreadable.  Missing is
    reported as missing — never coerced to 0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


# ---------------------------------------------------------------------------
# Realized-history measurement (optional input)
# ---------------------------------------------------------------------------


def measure_realized(
    weekly_rows: Iterable[Mapping[str, Any]],
    card: Mapping[str, Any],
    keys: Iterable[str],
    *,
    attach: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per-key realized impact under ``card`` over REG rows.

    Returns ``{"families": {fam: {"players": n, "points": pts}},
    "keys": {key: {"players": n, "stat": s, "points": p, "byFamily": {...}}},
    "pbpAttached": bool, "columnTotals": {...}}``.  ``points`` is SIGNED.
    """
    # A key whose rate is absent/unreadable cannot be measured: it is
    # reported in ``unmeasuredKeys``, never priced at a rate of 0.
    rates: dict[str, float] = {}
    unmeasured: list[str] = []
    for k in keys:
        rate = _num(card.get(k))
        if rate is None:
            unmeasured.append(k)
        else:
            rates[k] = rate
    keys = list(rates)
    canon = {k: _SCORING_KEY_ALIASES.get(k, k) for k in keys}
    fam_players: dict[str, set[str]] = {}
    fam_points: dict[str, float] = {}
    key_players: dict[str, dict[str, set[str]]] = {k: {} for k in keys}
    key_stat: dict[str, float] = {k: 0.0 for k in keys}
    key_fam_pts: dict[str, dict[str, float]] = {k: {} for k in keys}
    col_totals: dict[str, dict[str, float]] = {}
    col_missing: dict[str, int] = {}
    pbp_seen = False
    for raw in weekly_rows:
        if str(raw.get("season_type") or "REG").upper() != "REG":
            continue
        fam = _family(raw.get("position"))
        if fam not in PRICED_FAMILIES:
            continue
        pid = str(raw.get("player_id") or raw.get("player_display_name") or "")
        if not pid:
            continue
        row = dict(attach(raw) if attach else raw)
        pos = str(row.get("position") or "").upper()
        line = sleeper_stat_line_from_row(row, position=pos)
        supplement = row.get(PBP_SUPPLEMENT_ROW_KEY)
        if isinstance(supplement, Mapping):
            pbp_seen = True
            line.update(_pbp_supplement_line(supplement))
        fam_players.setdefault(fam, set()).add(pid)
        rp = compute_weekly_points(row, dict(card), position=pos)
        fam_points[fam] = fam_points.get(fam, 0.0) + (rp.fantasy_points if rp else 0.0)
        for finding in ENGINE_MAPPING_FINDINGS.values():
            for col in (finding["engineColumn"], finding["hostMatchingColumn"]):
                value = _num(row.get(col))
                if value is None:
                    # Absent column: counted, not added as a zero.
                    col_missing[col] = col_missing.get(col, 0) + 1
                    continue
                bucket = col_totals.setdefault(col, {})
                bucket[fam] = bucket.get(fam, 0.0) + value
        for k in keys:
            finding = ENGINE_MAPPING_FINDINGS.get(k)
            if finding and fam in IDP_FAMILIES:
                # Measure what the HOST pays, not what the mismapped engine reads.
                stat = _num(row.get(finding["hostMatchingColumn"]))
            elif canon[k] in _PLAY_TYPE_FD_COLUMNS:
                # The engine reads no column for play-type first downs, so the
                # stat line never carries them.  Measured (realized history
                # only, never a projection input) the way Sleeper counts them:
                # nflverse first downs minus that play type's TDs (Sleeper
                # excludes scoring plays; see realized_points
                # ``_FIRST_DOWN_TD_COLUMNS``).
                fd_col, td_col = _PLAY_TYPE_FD_COLUMNS[canon[k]]
                fd, td = _num(row.get(fd_col)), _num(row.get(td_col))
                stat = None if fd is None or td is None else max(0.0, fd - td)
            else:
                stat = _num(line.get(canon[k]))
            if not stat:
                # None (stat absent from this row) or a recorded 0: nothing
                # to add either way, and neither is counted as an occurrence.
                continue
            key_players[k].setdefault(fam, set()).add(pid)
            key_stat[k] += stat
            key_fam_pts[k][fam] = key_fam_pts[k].get(fam, 0.0) + stat * rates[k]
    return {
        "pbpAttached": pbp_seen,
        "families": {
            f: {"players": len(fam_players[f]), "points": round(fam_points.get(f, 0.0), 2)}
            for f in sorted(fam_players)
        },
        "keys": {
            k: {
                "players": len(set().union(*key_players[k].values())) if key_players[k] else 0,
                "playersByFamily": {f: len(v) for f, v in sorted(key_players[k].items())},
                "stat": round(key_stat[k], 2),
                "points": round(sum(key_fam_pts[k].values()), 2),
                "byFamily": {f: round(v, 2) for f, v in sorted(key_fam_pts[k].items())},
            }
            for k in keys
        },
        "columnTotals": {
            c: {f: round(v, 2) for f, v in sorted(t.items())} for c, t in col_totals.items()
        },
        "columnRowsMissing": dict(sorted(col_missing.items())),
        "unmeasuredKeys": sorted(unmeasured),
    }


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


def _engine_class(key: str) -> str:
    return classify(key, pbp_supplement=True).value


def census_for_card(
    card: Mapping[str, Any],
    *,
    realized: Mapping[str, Any] | None = None,
    idp_enabled: bool = True,
) -> list[dict[str, Any]]:
    """One row per NONZERO card rule, sorted by priority (highest first).

    ``idp_enabled=False`` (a league that starts no defenders) removes the IDP
    families from what BDVM prices, so an IDP rule is NOT_APPLICABLE there and
    a special-teams rule is judged on the offensive feed only."""
    priced = set(PRICED_FAMILIES if idp_enabled else OFFENSE_FAMILIES)
    clay_off, clay_idp = clay_vocabularies()
    vocabs = {
        "clayOffense": clay_off,
        "clayIdp": clay_idp,
        "idpShow": idpshow_vocabulary(),
        "manualCsv": manual_csv_vocabulary(),
    }
    rows: list[dict[str, Any]] = []
    for key, raw in sorted(card.items()):
        rate = _num(raw)
        if rate is None or rate == 0.0:
            # Absent / non-numeric values are not rules, and a zero rate
            # scores nothing; neither is a census row.
            continue
        engine = _engine_class(key)
        positions = engine_positions(key) if engine == Coverage.SCORED.value else ()
        entry: dict[str, Any] = {
            "key": key,
            "weight": rate,
            "weightSign": weight_sign(rate),
            "engine": engine,
            "reportedInUnscoredKeys": key in PBP_SUPPLEMENT_KEYS,
        }
        if engine == Coverage.NOT_APPLICABLE.value or key in KICKER_KEYS:
            entry.update(
                classification="NOT_APPLICABLE",
                reason="kicker rule" if key in KICKER_KEYS else "team-defense rule",
            )
            rows.append(entry)
            continue
        measured = (realized or {}).get("keys", {}).get(key)
        families = sorted(
            _rule_families(key)
            & priced
            & ({f for f in (_family(p) for p in positions)} or set(PRICED_FAMILIES))
        )
        if not families and engine != Coverage.GAP.value:
            entry.update(classification="NOT_APPLICABLE", reason="no priced family in this league")
            rows.append(entry)
            continue
        supply: dict[str, str] = {}
        for src, covered in REAL_SOURCES.items():
            if not covered.intersection(families):
                continue
            src_positions = [p for p in PRICED_POSITIONS if _family(p) in covered]
            supply[src] = source_supply(key, vocabs[src], src_positions)
        capability = {
            "manualCsv": source_supply(key, vocabs["manualCsv"], PRICED_POSITIONS),
            "reconstructedBaseline": baseline_supply(key),
        }
        if key in PLAY_TYPE_FIRST_DOWN_KEYS:
            # Projection lane: no source publishes play-type first downs, so
            # this is a vocabulary gap whatever the realized engine does.
            classification = "UNSUPPORTED_VOCABULARY"
        elif engine == Coverage.GAP.value:
            classification = "MAPPING_ERROR"
        elif supply and all(v != "none" for v in supply.values()):
            classification = (
                "SUPPORTED_IMPUTED" if any(v == "imputed" for v in supply.values()) else "SUPPORTED"
            )
        elif any(v != "none" for v in supply.values()):
            classification = "ABSENT_FIELD"
        else:
            classification = "UNSUPPORTED_VOCABULARY"
        missing = [s for s, v in supply.items() if v == "none"]
        entry.update(
            classification=classification,
            affectedFamilies=families,
            sources=supply,
            capability=capability,
            imputed=sorted(s for s, v in supply.items() if v == "imputed"),
            missingFrom=missing,
            missingStatistic=_missing_statistic(key),
            remedy=_REMEDY.get(key) if classification != "SUPPORTED" else None,
            # Since J1 (2026-10-01) per-player ``unscoredKeys`` carries every
            # rule a record's SOURCE cannot publish (src.bdvm.source_vocabulary),
            # not only the play-by-play-only rules — so a source-vocabulary gap
            # is no longer silent per player.
            reportedInUnscoredKeys=(
                key in PBP_SUPPLEMENT_KEYS or bool(missing) or engine == Coverage.GAP.value
            ),
        )
        if key in PLAY_TYPE_FIRST_DOWN_KEYS:
            entry["note"] = (
                "the realized engine also reads no column for this play-type rule "
                "(probe GAP); realized impact is measured from nflverse first downs "
                "minus that play type's TDs, the host's counting rule"
            )
        finding = ENGINE_MAPPING_FINDINGS.get(key)
        if finding:
            entry["baselineMappingError"] = dict(finding)
        if realized:
            fam_totals = realized.get("families", {})
            eligible = sum(fam_totals.get(f, {}).get("players", 0) for f in families)
            fam_pts = sum(fam_totals.get(f, {}).get("points", 0.0) for f in families)
            by_fam = (measured or {}).get("byFamily", {})
            pts = round(sum(by_fam.get(f, 0.0) for f in families), 2)
            players_by_fam = (measured or {}).get("playersByFamily", {})
            entry["realized"] = {
                "eligiblePlayers": eligible,
                "affectedPlayers": sum(players_by_fam.get(f, 0) for f in families),
                "stat": measured["stat"] if measured else 0.0,
                "points": pts,
                "byFamily": by_fam,
                "shareOfAffectedFamilyPoints": round(pts / fam_pts, 5) if fam_pts else None,
                # How much of ``points`` a projected total actually omits.
                "atRiskBasis": _AT_RISK_BASIS.get(classification, "none"),
            }
        rows.append(entry)
    for e in rows:
        e["priority"] = _priority(e)
    rows.sort(key=lambda e: (-e["priority"], e["key"]))
    return rows


_AT_RISK_BASIS: dict[str, str] = {
    "SUPPORTED_IMPUTED": (
        "estimated: not omitted — every covering source supplies it, but at least one "
        "only through an imputation (first downs from yards), so these points rest on "
        "an estimate rather than a published stat"
    ),
    "UNSUPPORTED_VOCABULARY": "full: no real source supplies it, every projected total omits it",
    "ABSENT_FIELD": "upper_bound: only players covered solely by a source lacking it omit it",
    "MAPPING_ERROR": "full: the engine reads no column for it",
}


def _missing_statistic(key: str) -> str:
    canon = _SCORING_KEY_ALIASES.get(key, key)
    if canon in _SIMPLE_KEYS:
        return "/".join(_SIMPLE_KEYS[canon][0])
    if key in PBP_SUPPLEMENT_KEYS:
        return f"{key} (play-by-play-derived)"
    return canon


def _priority(entry: Mapping[str, Any]) -> float:
    """|points at risk|: realized |points| for a non-SUPPORTED rule (0 when
    SUPPORTED or N/A).  For ABSENT_FIELD it is an UPPER bound — only players
    covered solely by the lacking source are partial.  For SUPPORTED_IMPUTED
    the points are not omitted but rest wholly on an estimate (see
    ``atRiskBasis``), so they rank by the same magnitude.  Without realized data,
    |weight| as a weak tiebreak (a vocabulary census cannot rank by impact)."""
    cls = entry.get("classification")
    if cls in ("SUPPORTED", "NOT_APPLICABLE") and not entry.get("baselineMappingError"):
        return 0.0
    realized = entry.get("realized")
    if realized is not None:
        return abs(float(realized["points"]))
    weight = _num(entry.get("weight"))
    return abs(weight) * 1e-6 if weight is not None else 0.0
