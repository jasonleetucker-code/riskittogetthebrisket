"""Projection-source capability declarations and per-record scoring coverage.

ONE owner for two questions the BDVM projection lane used to answer only in a
report (``scoring_census``) and never per player:

1. **What does each projection source actually publish?**  Declared here as a
   :class:`SourceCapability` per source name.  The stat-line vocabularies are
   DERIVED by running each adapter's own parser on a synthetic input, so an
   adapter that starts emitting a new column shows up without editing a list.

2. **Which league-card rules can THIS record score?**  Answered per record by
   :func:`record_coverage`:

   * ``stat_line`` records (Clay, IDP Show, a manual CSV of stat columns) are
     probed with the columns the record actually carries: a nonzero card rule
     that applies to the player's position family, that the realized engine
     can score, and that no column on the line can move, is UNSCORED.  So a
     Clay-scored QB lists ``fum_lost`` (a penalty), a Clay-only defender lists
     ``idp_pass_def`` / ``idp_tkl_loss`` / ``idp_qb_hit``, and an IDP Show
     capture that published no PD column says so for its players.
   * ``realized_proxy`` records (the reconstructed baseline, rookie draft-slot
     priors) carry the fpg the realized engine produced; their coverage is the
     realized engine's own ``unscored`` keys for the seasons the fpg came
     from, declared on the record at build time.  A proxy whose declaration
     was never recorded (a snapshot written before this existed) is
     ``unverifiable`` — never fully scoreable by default.
   * ``source_points`` records (fpts/fpg the SOURCE computed, e.g. IDP Show's
     Big-3 points) are ``unverifiable``: which rules those points include is
     not ours to know.

An unscored rule is never a lower bound: it may be a penalty (``fum_lost``,
``pass_int_td``), so the omitted contribution may be positive or negative.
The card's own sign per rule travels with it (``weightSign``).

Nothing here changes a projected point, a value or a consensus weight — it
REPORTS what each projected total omits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable, Mapping

from src.nfl_data.realized_points import (
    _FG_BAND_KEYS,
    _SCORING_KEY_ALIASES,
    _SIMPLE_KEYS,
    PBP_SUPPLEMENT_KEYS,
    PBP_SUPPLEMENT_ROW_KEY,
    compute_weekly_points,
)
from src.nfl_data.scoring_coverage import _MAXIMAL_ROW, Coverage, classify
from src.utils.name_clean import POSITION_ALIASES

# ---------------------------------------------------------------------------
# Families and rule scopes
# ---------------------------------------------------------------------------

#: BDVM's priced positions → position family (POSITION_ALIASES vocabulary).
PRICED_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "DT", "EDGE", "LB", "CB", "S")
OFFENSE_FAMILIES = frozenset({"QB", "RB", "WR", "TE"})
IDP_FAMILIES = frozenset({"DL", "LB", "DB"})
PRICED_FAMILIES = OFFENSE_FAMILIES | IDP_FAMILIES

#: Kicker rules: any card key the engine reads off a ``fg_*`` / ``pat_*`` column.
KICKER_KEYS: frozenset[str] = frozenset(_FG_BAND_KEYS) | frozenset(
    k for k, (cols, _l) in _SIMPLE_KEYS.items() if all(c.startswith(("fg_", "pat_")) for c in cols)
)

#: Player special-teams rules: earned by offensive AND defensive players.
SPECIAL_TEAMS_KEYS: frozenset[str] = frozenset(
    {"kr_yd", "pr_yd", "st_td", "punt_ret_td", "kick_ret_td", "st_tkl_solo", "st_ff", "st_fum_rec"}
)


def family_of(position: Any) -> str | None:
    return POSITION_ALIASES.get(str(position or "").upper())


def rule_families(key: str) -> set[str]:
    """The families a rule is FOR — which decides which sources are expected
    to supply it.  A trick-play pass by a WR or a two-way player's catch does
    not make a defensive feed responsible for passing yards."""
    canon = _SCORING_KEY_ALIASES.get(key, key)
    if canon.startswith("idp_"):
        return set(IDP_FAMILIES)
    if canon in SPECIAL_TEAMS_KEYS:
        return set(PRICED_FAMILIES)
    return set(OFFENSE_FAMILIES)


# ---------------------------------------------------------------------------
# Source vocabularies — derived by running each adapter's own parser
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def clay_vocabularies() -> tuple[frozenset[str], frozenset[str]]:
    """(offense columns, IDP columns) the Clay parser emits, probed by parsing a
    synthetic team page with every number nonzero."""
    from src.bdvm.clay_projections import parse_clay_text  # noqa: PLC0415

    letters = "abcdefghij"
    nums = " ".join(str(n) for n in range(1, 17))
    lines = [f"QB Probe {letters[i // 10]}{letters[i % 10]} {nums}" for i in range(50)]
    lines.append("LB Probe Defender 900 100 2.0 1.0 5")
    rows, report = parse_clay_text("\n".join(lines))
    if not report.get("usable"):
        raise RuntimeError(f"clay vocabulary probe rejected by the parser: {report}")
    off: set[str] = set()
    idp: set[str] = set()
    for row in rows:
        (off if row["position"] in OFFENSE_FAMILIES else idp).update(row["stats"])
    return frozenset(off), frozenset(idp)


@lru_cache(maxsize=1)
def idpshow_vocabulary() -> frozenset[str]:
    """Columns the IDP Show parser CAN emit (one header per semantic field).
    A given capture may publish fewer — per-record coverage reads the record."""
    from src.bdvm.idpshow_projections import (  # noqa: PLC0415
        _HEADER_ALIASES,
        _STAT_FIELDS,
        parse_projection_csv,
    )

    headers = ["Player", "Pos"]
    for fld in sorted(_STAT_FIELDS):
        headers.append(next(h for h, sem in _HEADER_ALIASES.items() if sem == fld))
    row = ["Probe Defender", "LB"] + ["5"] * (len(headers) - 2)
    rows, report = parse_projection_csv(",".join(headers) + "\n" + ",".join(row) + "\n")
    if not rows:
        raise RuntimeError(f"idpShow vocabulary probe rejected by the parser: {report}")
    return frozenset(rows[0]["stats"])


def manual_csv_vocabulary() -> frozenset[str]:
    """The manual CSV takes ANY numeric column, so its vocabulary is every weekly
    column the engine reads — but no play-by-play supplement (that rides a
    nested row key a CSV cell cannot carry)."""
    return frozenset(k for k in _MAXIMAL_ROW if k not in ("season", "week"))


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

BASIS_STAT_LINE = "stat_line"
BASIS_REALIZED_PROXY = "realized_proxy"
BASIS_SOURCE_POINTS = "source_points"

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNVERIFIABLE = "unverifiable"
_STATUS_ORDER = {STATUS_COMPLETE: 0, STATUS_PARTIAL: 1, STATUS_UNVERIFIABLE: 2}


@dataclass(frozen=True)
class SourceCapability:
    """What one projection source publishes.

    ``vocabulary_by_family`` is the declared MAXIMUM stat-column vocabulary
    per position family (``None`` for a lane that publishes no stat line).
    ``imputed`` names rules the projection boundary fills by estimate rather
    than from a published stat (first downs from yards today).
    """

    source: str
    basis: str
    vocabulary_by_family: Mapping[str, frozenset[str]] | None
    families: frozenset[str]
    imputed: tuple[str, ...] = ()
    note: str = ""
    # A FIXED-SCHEMA source publishes its whole declared vocabulary for every
    # record of a family, but its parser may drop zero-valued columns (Clay
    # keeps only nonzero stats).  For such a source a column absent from one
    # record is a published ZERO, not an omission.  A per-capture source (the
    # IDP Show sheet) keeps zeros, so absence there IS an omission.
    fixed_schema: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "basis": self.basis,
            "fixedSchema": self.fixed_schema,
            "families": sorted(self.families),
            "vocabularyByFamily": (
                {f: sorted(v) for f, v in sorted(self.vocabulary_by_family.items())}
                if self.vocabulary_by_family is not None
                else None
            ),
            "imputed": list(self.imputed),
            "note": self.note,
        }


_FIRST_DOWN_IMPUTED = ("bonus_fd_qb", "bonus_fd_rb", "bonus_fd_wr", "bonus_fd_te")


@lru_cache(maxsize=1)
def declared_capabilities() -> dict[str, SourceCapability]:
    """Every projection source BDVM knows, by the ``source`` name its records
    carry.  An unknown source name resolves through :func:`capability_for` to
    an explicit ``undeclared`` capability — never to a guessed one."""
    from src.bdvm.clay_projections import SOURCE_NAME as CLAY  # noqa: PLC0415
    from src.bdvm.idpshow_projections import SOURCE_NAME as IDPSHOW  # noqa: PLC0415

    clay_off, clay_idp = clay_vocabularies()
    idpshow = idpshow_vocabulary()
    return {
        CLAY: SourceCapability(
            source=CLAY,
            basis=BASIS_STAT_LINE,
            vocabulary_by_family={
                **{f: clay_off for f in OFFENSE_FAMILIES},
                **{f: clay_idp for f in IDP_FAMILIES},
            },
            families=PRICED_FAMILIES,
            imputed=_FIRST_DOWN_IMPUTED,
            fixed_schema=True,
            note=(
                "Mike Clay's ESPN guide: offense pass/rush/receiving lines (no fumbles, "
                "2-pt, returns, first downs — first downs imputed from yards); IDP "
                "tackles (solo/assist split at the shared solo share), sacks, INT only"
            ),
        ),
        IDPSHOW: SourceCapability(
            source=IDPSHOW,
            basis=BASIS_STAT_LINE,
            vocabulary_by_family={f: idpshow for f in IDP_FAMILIES},
            families=IDP_FAMILIES,
            note=(
                "The IDP Show sheet: any of solo/assist tackles, TFL, sacks, QB hits, "
                "INT, PD, FF, FR, def TD, safety — per capture; a column the sheet "
                "omits is missing for its players. Big-3 points are source-scored "
                "(not this league's card) and unverifiable when no stat line exists"
            ),
        ),
        "reconstructedBaseline": SourceCapability(
            source="reconstructedBaseline",
            basis=BASIS_REALIZED_PROXY,
            vocabulary_by_family=None,
            families=PRICED_FAMILIES,
            note=(
                "fpg-only proxy: realized per-game points under this league's card from "
                "the nflverse weekly feed (+ the play-by-play supplement where built); "
                "its coverage is the realized engine's unscored rules, declared per record"
            ),
        ),
        "rookieDraftSlotPrior": SourceCapability(
            source="rookieDraftSlotPrior",
            basis=BASIS_REALIZED_PROXY,
            vocabulary_by_family=None,
            families=PRICED_FAMILIES,
            note=(
                "fpg-only proxy: mean realized rookie-season PPG by position and draft "
                "round; coverage is the union of its contributing seasons' unscored rules"
            ),
        ),
    }


def capability_for(source: str) -> SourceCapability:
    known = declared_capabilities().get(source)
    if known is not None:
        return known
    return SourceCapability(
        source=source,
        basis="undeclared",
        vocabulary_by_family=None,
        families=PRICED_FAMILIES,
        note=(
            "no declaration for this source name (e.g. a manual CSV drop): coverage is "
            "read from the columns each record actually carries"
        ),
    )


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _probe_line(vocab: Iterable[str]) -> dict[str, float]:
    return {c: float(_MAXIMAL_ROW.get(c) or 50.0) for c in vocab}


def source_supply(key: str, vocab: Iterable[str], positions: Iterable[str]) -> str:
    """``direct`` / ``imputed`` / ``none`` — can a stat line built from ``vocab``
    move ``key`` at any of ``positions`` through BDVM's projection scorer?"""
    from src.bdvm.scoring import score_stat_line_per_game_detailed  # noqa: PLC0415

    line = _probe_line(vocab)
    best = "none"
    for pos in positions:
        for impute in (False, True):
            off, _ = score_stat_line_per_game_detailed(
                line, {key: 0.0}, position=pos, impute_first_downs=impute
            )
            on, _ = score_stat_line_per_game_detailed(
                line, {key: 7.0}, position=pos, impute_first_downs=impute
            )
            if on != off:
                if not impute:
                    return "direct"
                best = "imputed"
    return best


@lru_cache(maxsize=4096)
def engine_fires(key: str, position: str) -> bool:
    """Can the realized engine score ``key`` at ``position`` on a maximal row
    (with the play-by-play supplement)?  False means the rule does not apply
    to this position at all (a TE-only bonus at WR) or the engine cannot read
    it (see :func:`engine_unreachable`)."""
    row = {**_MAXIMAL_ROW, "position": position}
    row[PBP_SUPPLEMENT_ROW_KEY] = {k: 1.0 for k in PBP_SUPPLEMENT_KEYS}
    off = compute_weekly_points(row, {key: 0.0}, position=position)
    on = compute_weekly_points(row, {key: 7.0}, position=position)
    return (off.fantasy_points if off else 0.0) != (on.fantasy_points if on else 0.0)


@lru_cache(maxsize=1024)
def engine_unreachable(key: str) -> bool:
    """A rule for a valued player that the realized engine cannot score from
    any input it has (``GAP`` / ``UNSCORABLE``) — unscored for every record."""
    return classify(key, pbp_supplement=True) in (Coverage.GAP, Coverage.UNSCORABLE)


def _nonzero_rules(card: Mapping[str, Any]) -> tuple[tuple[str, float], ...]:
    out = []
    for key, raw in (card or {}).items():
        try:
            rate = float(raw)
        except (TypeError, ValueError):
            continue
        if rate:
            out.append((str(key), rate))
    return tuple(sorted(out))


def _relevant_families(position: str, vocab: frozenset[str]) -> frozenset[str]:
    fam = family_of(position)
    fams = {fam} if fam else set()
    # A two-way record (Clay combines both sides under the DEFENSIVE
    # position) carries offense columns: its offense rules apply too.
    if vocab & clay_vocabularies()[0]:
        fams |= OFFENSE_FAMILIES
    return frozenset(fams)


@lru_cache(maxsize=2048)
def _missing_for_vocabulary(
    vocab: frozenset[str], position: str, rules: tuple[tuple[str, float], ...]
) -> tuple[str, ...]:
    families = _relevant_families(position, vocab)
    missing: list[str] = []
    for key, _rate in rules:
        if key in KICKER_KEYS or not (rule_families(key) & families):
            continue
        if engine_unreachable(key):
            missing.append(key)
            continue
        if not engine_fires(key, position):
            # The rule does not apply at this position (a TE-only bonus at WR).
            continue
        if source_supply(key, vocab, [position]) == "none":
            missing.append(key)
    return tuple(sorted(missing))


@lru_cache(maxsize=256)
def _unreachable_for_families(
    families: frozenset[str], rules: tuple[tuple[str, float], ...]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            key
            for key, _rate in rules
            if key not in KICKER_KEYS and rule_families(key) & families and engine_unreachable(key)
        )
    )


# ---------------------------------------------------------------------------
# Per-record coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordCoverage:
    source: str
    basis: str
    status: str
    unscored_keys: tuple[str, ...] = ()
    reason: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source": self.source,
            "basis": self.basis,
            "status": self.status,
            "unscoredKeys": list(self.unscored_keys),
        }
        if self.reason:
            out["reason"] = self.reason
        return out


def record_coverage(
    record: Any,
    scoring_settings: Mapping[str, Any],
    *,
    engine_unscored: Iterable[str] = (),
) -> RecordCoverage:
    """Coverage of ONE :class:`~src.bdvm.projections.ProjectionRecord` under a card.

    ``engine_unscored`` is what the realized engine already reported for the
    record's scored stat line (the play-by-play-only rules); it is unioned in
    so nothing it said is lost.
    """
    rules = _nonzero_rules(scoring_settings)
    cap = capability_for(record.source)
    if record.stat_line:
        vocab = frozenset(str(k) for k in record.stat_line)
        own_family = family_of(record.position)
        if cap.fixed_schema and cap.vocabulary_by_family and own_family:
            # Published zeros the parser dropped are still published.
            vocab = vocab | cap.vocabulary_by_family.get(own_family, frozenset())
        families = _relevant_families(str(record.position).upper(), vocab)
        missing = set(_missing_for_vocabulary(vocab, str(record.position).upper(), rules))
        # The engine reports every nonzero play-by-play rule whatever the
        # position; a reception-distance band is not a linebacker's omission
        # (unless the record carries offense columns — a two-way player).
        missing.update(k for k in engine_unscored if rule_families(k) & families)
        return RecordCoverage(
            source=record.source,
            basis=BASIS_STAT_LINE,
            status=STATUS_PARTIAL if missing else STATUS_COMPLETE,
            unscored_keys=tuple(sorted(missing)),
        )
    declared = getattr(record, "declared_unscored", None)
    if record.is_proxy and record.scoring_native and declared is not None:
        from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

        built_under = getattr(record, "declared_card_fingerprint", None)
        current = scoring_fingerprint(dict(scoring_settings)) if scoring_settings else None
        if built_under is None or current is None or built_under != current:
            # The declared omissions describe the card the proxy was SCORED
            # under; under any other (or an unrecorded) card its total is not
            # this card's partial total, so completeness cannot be claimed.
            return RecordCoverage(
                source=record.source,
                basis=BASIS_REALIZED_PROXY,
                status=STATUS_UNVERIFIABLE,
                reason=(
                    "proxy_card_not_recorded"
                    if built_under is None
                    else "proxy_built_under_different_card"
                ),
            )
        fam = family_of(record.position)
        families = frozenset({fam}) if fam else frozenset()
        card_keys = {k for k, _r in rules}
        # Realized rows carry every stat a player recorded, so a proxy is
        # scoped by its own family (same rule-family scope as above).
        missing = {k for k in declared if k in card_keys and rule_families(k) & families}
        missing.update(_unreachable_for_families(families, rules))
        return RecordCoverage(
            source=record.source,
            basis=BASIS_REALIZED_PROXY,
            status=STATUS_PARTIAL if missing else STATUS_COMPLETE,
            unscored_keys=tuple(sorted(missing)),
        )
    if record.is_proxy:
        return RecordCoverage(
            source=record.source,
            basis=BASIS_REALIZED_PROXY,
            status=STATUS_UNVERIFIABLE,
            reason="proxy_coverage_not_recorded",
        )
    return RecordCoverage(
        source=record.source,
        basis=BASIS_SOURCE_POINTS if cap.basis != BASIS_REALIZED_PROXY else cap.basis,
        status=STATUS_UNVERIFIABLE,
        reason="source_scored_points",
    )


def worst_status(statuses: Iterable[str]) -> str:
    worst = STATUS_COMPLETE
    for s in statuses:
        if _STATUS_ORDER.get(s, 2) > _STATUS_ORDER[worst]:
            worst = s
    return worst
