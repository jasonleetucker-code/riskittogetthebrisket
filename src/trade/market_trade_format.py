"""Trade-market format fingerprint, per-axis comparability, target dispositions.

ONE canonical answer to "what format was this trade made in, and does that
format let it price the TARGET league?" (owner addendum 2026-10-01, item 3;
spec §4).  Every comparison is per AXIS and every axis stays inspectable —
there is no hidden single similarity score.

WHAT IS CONSUMED, NOT REBUILT
─────────────────────────────
* slot rules — ``src.ros.lineup`` (``starter_slots_from_roster_positions``,
  ``resolve_starter_slots`` — the live → registry → refuse truth ladder —,
  ``slot_eligible_positions``, ``lineup_position``);
  no private slot→position table lives here;
* scoring identity — ``src.league_comparison.sleeper_scoring``
  (``normalize_scoring_settings``, ``scoring_fingerprint``);
* TE scoring edge — ``src.league_intel.te_premium.measure_te_demand``;
* target league — ``src.api.league_registry`` (roster settings, the ACTUAL
  scoring card snapshot and its evidence state).  The ``scoringProfile`` LABEL
  is never read.

THE REPRESENTATION THAT MAKES SOURCES COMPARABLE
────────────────────────────────────────────────
Roster demand is a ``(min, max)`` starter count per position family: ``min``
= slots only that family can fill, ``max`` = slots that family is ELIGIBLE
for.  A Sleeper ``roster_positions`` array and KTC's own
``leagueStartingLineup`` limits (``"QB": "1-2"``) both reduce to it exactly,
so a KTC superflex row and a Sleeper QB+SUPER_FLEX league compare on the same
footing without anyone inventing a crosswalk.

DISPOSITIONS
────────────
Every observation gets exactly ONE of:

* ``NATIVE_COMPARABLE`` — every axis is ``MATCH``.  Unknown is not a match.
* ``VALIDATED_TRANSFORMABLE`` — a registered translator, validated out of
  sample, maps it onto the target.  **None is validated today**; the registry
  refuses ``validated=True`` without held-out evidence and refuses any global
  multiplier (``1QB×k = SF``, ``IDP×k``) outright.
* ``TARGET_UNSUPPORTED`` — anything else, with the strongest unsupported axis
  named.  The observation is KEPT for broad research; it just cannot price the
  target.

BDVM SEAM (documented, not implemented): BDVM may later supply only a
STRUCTURAL prior for a translator — ``structural_ratio = BDVM(F_target) /
BDVM(F_source)`` — never market truth, and a source format whose scoring
vocabulary BDVM cannot score must lower or block such a translation.  Nor may
any future translator be fit on current canonical values as labels: that is
circular (trade evidence would be graded by the board it is meant to test).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.league_comparison.sleeper_scoring import normalize_scoring_settings, scoring_fingerprint
from src.ros.lineup import (
    lineup_position,
    resolve_starter_slots,
    slot_eligible_positions,
    starter_slots_from_roster_positions,
)

FORMAT_FINGERPRINT_VERSION = "tmf1"

MATCH = "MATCH"
DIFFERENT = "DIFFERENT"
UNKNOWN = "UNKNOWN"

NATIVE_COMPARABLE = "NATIVE_COMPARABLE"
VALIDATED_TRANSFORMABLE = "VALIDATED_TRANSFORMABLE"
TARGET_UNSUPPORTED = "TARGET_UNSUPPORTED"

DYNASTY = "dynasty"
KEEPER = "keeper"
REDRAFT = "redraft"

SOURCE_SLEEPER = "sleeper_league_capture"
SOURCE_KTC = "ktc_vendor_settings"
SOURCE_REGISTRY = "registry_and_scoring_card"
SOURCE_UNKNOWN = "unknown"

OFFENSE_FAMILIES = ("QB", "RB", "WR", "TE")
IDP_FAMILIES = ("DL", "LB", "DB")

#: Sleeper ``settings.type``.  2 = dynasty is the code
#: ``src/intel/league_filter.py`` already keys on; 1 = keeper, 0 = redraft.
_SLEEPER_TYPE = {2: DYNASTY, 1: KEEPER, 0: REDRAFT}

#: Axis order is the order in which an unsupported axis is NAMED as the
#: strongest reason (structure before scoring before depth).
AXES: tuple[str, ...] = (
    "dynastyState",
    "qbDemand",
    "idpEnabled",
    "idpStarterDepth",
    "idpPositionalStructure",
    "teRosterDemand",
    "teamCount",
    "offenseRosterDemand",
    "teScoring",
    "offenseScoring",
    "idpScoring",
    "rosterDepth",
    "bestBall",
)

_TE_KEY = re.compile(r"(^|_)te($|_)")


def _is_idp_key(key: str) -> bool:
    return key.startswith("idp_")


def _is_te_key(key: str) -> bool:
    return bool(_TE_KEY.search(key))


# ── Fingerprint ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TradeMarketFormat:
    """One league's market format.  ``None`` anywhere means UNKNOWN."""

    source: str
    dynasty_state: str | None = None
    dynasty_basis: str | None = None
    teams: int | None = None
    roster_size: int | None = None
    taxi_size: int | None = None
    best_ball: bool | None = None
    season: str | None = None
    #: per family -> (min, max) starters; ``None`` = roster demand unknown.
    demand: Mapping[str, tuple[int, int]] | None = None
    total_starters: int | None = None
    idp_enabled: bool | None = None
    #: raw IDP slot tokens as the host wrote them (true-position structure).
    idp_slot_tokens: Mapping[str, int] | None = None
    #: normalized numeric scoring card (absent == 0 removed); ``None`` = unknown.
    scoring: Mapping[str, float] | None = None
    card_hash: str | None = None
    vendor: Mapping[str, Any] = field(default_factory=dict)

    # -- derived views -------------------------------------------------
    def demand_for(self, family: str) -> tuple[int, int] | None:
        if self.demand is None:
            return None
        return tuple(self.demand.get(family, (0, 0)))  # type: ignore[return-value]

    @property
    def superflex(self) -> bool | None:
        qb = self.demand_for("QB")
        return None if qb is None else qb[1] >= 2

    @property
    def idp_starters(self) -> int | None:
        if self.idp_enabled is False:
            return 0
        if self.demand is None:
            return None
        return sum(self._idp_slot_count())

    def _idp_slot_count(self) -> list[int]:
        # Total IDP starters = slots whose eligibility is defensive-only.
        tokens = self.idp_slot_tokens or {}
        return [int(n) for n in tokens.values()]

    def scoring_subset(self, predicate: Callable[[str], bool]) -> dict[str, float] | None:
        if self.scoring is None:
            return None
        return {k: v for k, v in self.scoring.items() if predicate(k)}

    def te_scoring_edge(self) -> bool | None:
        if self.scoring is None:
            return None
        from src.league_intel.te_premium import measure_te_demand  # noqa: PLC0415

        return measure_te_demand(None, dict(self.scoring)).has_scoring_edge

    def to_dict(self) -> dict[str, Any]:
        out = {
            "version": FORMAT_FINGERPRINT_VERSION,
            "source": self.source,
            "general": {
                "dynastyState": self.dynasty_state,
                "dynastyBasis": self.dynasty_basis,
                "teams": self.teams,
                "rosterSize": self.roster_size,
                "taxiSize": self.taxi_size,
                "bestBall": self.best_ball,
                "season": self.season,
                "cardHash": self.card_hash,
            },
            "offense": {
                "demand": (
                    {f: list(self.demand_for(f) or ()) for f in OFFENSE_FAMILIES}
                    if self.demand is not None
                    else None
                ),
                "superflex": self.superflex,
                "totalStarters": self.total_starters,
            },
            "te": {
                "demand": list(self.demand_for("TE")) if self.demand is not None else None,
                "scoringKeys": self.scoring_subset(_is_te_key),
                "scoringEdge": self.te_scoring_edge(),
            },
            "idp": {
                "enabled": self.idp_enabled,
                "starters": self.idp_starters,
                "demand": (
                    {f: list(self.demand_for(f) or ()) for f in IDP_FAMILIES}
                    if self.demand is not None
                    else None
                ),
                "slotTokens": dict(self.idp_slot_tokens)
                if self.idp_slot_tokens is not None
                else None,
                "scoring": self.scoring_subset(_is_idp_key),
            },
            "scoringKnown": self.scoring is not None,
            "vendor": dict(self.vendor),
        }
        out["fingerprint"] = format_fingerprint(out)
        return out

    def to_full_dict(self) -> dict[str, Any]:
        """:meth:`to_dict` plus the whole normalized scoring card."""
        out = self.to_dict()
        out["scoring"] = dict(self.scoring) if self.scoring is not None else None
        return out


def format_fingerprint(fmt_dict: Mapping[str, Any]) -> str:
    """Content hash of a format dict (vendor block and the hash itself excluded)."""
    body = {k: v for k, v in fmt_dict.items() if k not in ("fingerprint", "vendor", "source")}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return f"{FORMAT_FINGERPRINT_VERSION}:{hashlib.sha1(blob.encode('utf-8')).hexdigest()[:16]}"


def _demand_from_slots(slots: Sequence[str]) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """``(family -> (min, max), raw IDP slot token counts)`` from lineup slots."""
    mins: dict[str, int] = {}
    maxs: dict[str, int] = {}
    idp_tokens: dict[str, int] = {}
    for slot in slots:
        families = {lineup_position(p) for p in slot_eligible_positions(slot)}
        families.discard("")
        if families and families <= set(IDP_FAMILIES):
            idp_tokens[slot] = idp_tokens.get(slot, 0) + 1
        for fam in families:
            maxs[fam] = maxs.get(fam, 0) + 1
        if len(families) == 1:
            fam = next(iter(families))
            mins[fam] = mins.get(fam, 0) + 1
    keys = set(mins) | set(maxs) | set(OFFENSE_FAMILIES) | set(IDP_FAMILIES)
    return {k: (mins.get(k, 0), maxs.get(k, 0)) for k in keys}, idp_tokens


def _as_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def format_from_sleeper_league(
    league: Mapping[str, Any] | None, *, captured_at: str | None = None
) -> TradeMarketFormat:
    """From a Sleeper league object, or the capture dict
    :func:`capture_sleeper_league_format` persists (same keys)."""
    if not isinstance(league, Mapping):
        return TradeMarketFormat(source=SOURCE_UNKNOWN)
    settings = league.get("settings") if isinstance(league.get("settings"), Mapping) else {}
    positions = league.get("roster_positions")
    slots = starter_slots_from_roster_positions(positions) if isinstance(positions, list) else []
    demand: dict[str, tuple[int, int]] | None = None
    idp_tokens: dict[str, int] | None = None
    total: int | None = None
    if slots:
        demand, idp_tokens = _demand_from_slots(slots)
        total = len(slots)
    scoring = normalize_scoring_settings(league.get("scoring_settings"))
    ltype = _as_int(settings.get("type"))
    teams = _as_int(league.get("total_rosters")) or _as_int(settings.get("num_teams"))
    best = settings.get("best_ball")
    return TradeMarketFormat(
        source=SOURCE_SLEEPER,
        dynasty_state=_SLEEPER_TYPE.get(ltype) if ltype is not None else None,
        dynasty_basis="host_league_settings_type" if ltype is not None else None,
        teams=teams,
        roster_size=len(positions) if isinstance(positions, list) and positions else None,
        taxi_size=_as_int(settings.get("taxi_slots")),
        best_ball=None if best is None else bool(best),
        season=str(league.get("season")) if league.get("season") else None,
        demand=demand,
        total_starters=total,
        idp_enabled=(bool(idp_tokens) if demand is not None else None),
        idp_slot_tokens=idp_tokens,
        scoring=scoring,
        card_hash=scoring_fingerprint(league.get("scoring_settings")),
        vendor={"capturedAt": captured_at} if captured_at else {},
    )


def capture_sleeper_league_format(league: Mapping[str, Any], *, captured_at: str) -> dict[str, Any]:
    """The persistable subset of a Sleeper league object.

    Called by the Sharp discovery crawl (``src/sharp/discovery.py``) on the
    league objects it ALREADY fetched — no extra request.  Only host facts are
    kept: roster slots, the numeric scoring card, and the settings keys the
    format reads.  Nothing about the discovering manager is stored here.
    """
    settings = league.get("settings") if isinstance(league.get("settings"), Mapping) else {}
    keep = ("type", "best_ball", "num_teams", "taxi_slots", "reserve_slots", "bench_lock")
    return {
        "capturedAt": captured_at,
        "season": league.get("season"),
        "total_rosters": league.get("total_rosters"),
        "roster_positions": list(league.get("roster_positions") or []) or None,
        "scoring_settings": normalize_scoring_settings(league.get("scoring_settings")),
        "settings": {k: settings.get(k) for k in keep if k in settings},
    }


_KTC_LIMIT = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$")


def format_from_ktc_settings(settings: Mapping[str, Any] | None) -> TradeMarketFormat:
    """From a KTC trade-row ``settings`` block.

    KTC states starter LIMITS per position (``"1-2"``), which are exactly the
    ``(min, max)`` demand representation.  It publishes no scoring card, so
    every scoring axis is UNKNOWN; its 0-3 TEP level and ppr code are kept in
    ``vendor`` and are not translated (no measured crosswalk exists).
    """
    if not isinstance(settings, Mapping):
        return TradeMarketFormat(source=SOURCE_UNKNOWN)
    lineup = settings.get("leagueStartingLineup")
    demand: dict[str, tuple[int, int]] | None = None
    idp_tokens: dict[str, int] | None = None
    total: int | None = None
    if isinstance(lineup, Mapping) and isinstance(lineup.get("position"), list):
        demand = {f: (0, 0) for f in (*OFFENSE_FAMILIES, *IDP_FAMILIES)}
        idp_tokens = {}
        parsed_any = False
        for entry in lineup["position"]:
            if not isinstance(entry, Mapping):
                continue
            fam = lineup_position(str(entry.get("name") or ""))
            m = _KTC_LIMIT.match(str(entry.get("limit") or ""))
            if not fam or not m:
                continue
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            demand[fam] = (lo, hi)
            parsed_any = True
            if fam in IDP_FAMILIES and hi > 0:
                idp_tokens[fam] = hi
        if not parsed_any:
            demand, idp_tokens = None, None
        total = _as_int(lineup.get("count"))
    return TradeMarketFormat(
        source=SOURCE_KTC,
        dynasty_state=DYNASTY,
        dynasty_basis="source_level_claim:ktc_dynasty_trade_database",
        teams=_as_int(settings.get("teams")),
        roster_size=None,
        taxi_size=None,
        best_ball=None,
        season=None,
        demand=demand,
        total_starters=total,
        idp_enabled=(bool(idp_tokens) if demand is not None else None),
        # KTC limits are not slot tokens; IDP depth from them is a range,
        # recorded as the max per family and compared as such.
        idp_slot_tokens=idp_tokens,
        scoring=None,
        card_hash=None,
        vendor={
            "tepLevel": settings.get("tep"),
            "is2TE": settings.get("is2TE"),
            "pprCode": settings.get("ppr"),
            "passTdPoints": settings.get("passTDPoints"),
            "rostersPerPlayer": settings.get("rostersPerPlayer"),
            "qBs": settings.get("qBs"),
        },
    )


def format_from_registry(
    league_key: str,
    *,
    allow_stale_scoring: bool = False,
    roster_positions: Sequence[str] | None = None,
) -> TradeMarketFormat:
    """The TARGET league's format from the canonical owners.

    Starter slots come from THE truth ladder,
    :func:`src.ros.lineup.resolve_starter_slots`: the live host
    ``roster_positions`` when the caller holds them, else the registry's
    ``starters``, else REFUSE (demand UNKNOWN — never a literal lineup).  The
    scoring card is the league's ACTUAL card snapshot, used only when its
    evidence is ``fresh`` (the same authority rule every scoring gate uses).  A
    stale or missing card leaves scoring UNKNOWN unless the caller explicitly
    accepts stale evidence for research, which is stamped on the result.

    Registry DEFAULTS are not facts: ``best_ball`` is known only when the entry
    states ``bestBall``, and ``idp_enabled`` comes from the resolved lineup, or
    from a stated ``idpEnabled`` when no lineup resolves — otherwise UNKNOWN.
    """
    from src.api import league_registry as reg  # noqa: PLC0415

    cfg = reg.get_league_by_key(league_key)
    if cfg is None:
        return TradeMarketFormat(source=SOURCE_UNKNOWN)
    rs = dict(cfg.roster_settings or {})
    slots, starter_source = resolve_starter_slots(
        roster_positions=roster_positions, roster_settings=rs
    )
    demand, idp_tokens = _demand_from_slots(slots) if slots else (None, None)
    stated = getattr(cfg, "stated_fields", frozenset())
    if demand is not None:
        idp_enabled: bool | None = bool(idp_tokens)
    elif "idpEnabled" in stated:
        idp_enabled = bool(cfg.idp_enabled)
    else:
        idp_enabled = None
    evidence = reg.scoring_evidence_state(cfg)
    card = reg.scoring_settings_for_league(cfg)
    use_card = card is not None and (evidence == "fresh" or allow_stale_scoring)
    scoring = normalize_scoring_settings(card) if use_card else None
    return TradeMarketFormat(
        source=SOURCE_REGISTRY,
        dynasty_state=DYNASTY,
        dynasty_basis="registry_league",
        teams=_as_int(rs.get("teamCount")),
        roster_size=_as_int(rs.get("rosterSize")),
        taxi_size=_as_int(rs.get("taxiSize")),
        best_ball=bool(cfg.best_ball) if "bestBall" in stated else None,
        season=None,
        demand=demand,
        total_starters=len(slots) if slots else None,
        idp_enabled=idp_enabled,
        idp_slot_tokens=idp_tokens,
        scoring=scoring,
        card_hash=scoring_fingerprint(card) if use_card else None,
        vendor={
            "leagueKey": league_key,
            "starterSource": starter_source,
            "scoringEvidence": evidence,
            "staleScoringAcceptedForResearch": bool(
                card is not None and evidence != "fresh" and allow_stale_scoring
            ),
        },
    )


# ── Per-axis comparability ────────────────────────────────────────────────


def _axis(state: str, source: Any = None, target: Any = None, detail: Any = None) -> dict[str, Any]:
    out = {"state": state, "source": source, "target": target}
    if detail is not None:
        out["detail"] = detail
    return out


def _eq_axis(src: Any, tgt: Any) -> dict[str, Any]:
    if src is None or tgt is None:
        return _axis(UNKNOWN, src, tgt)
    return _axis(MATCH if src == tgt else DIFFERENT, src, tgt)


def _scoring_axis(src: Mapping[str, float] | None, tgt: Mapping[str, float] | None) -> dict:
    if src is None or tgt is None:
        return _axis(UNKNOWN, None if src is None else "known", None if tgt is None else "known")
    keys = sorted(set(src) | set(tgt))
    diffs = {
        k: [src.get(k, 0.0), tgt.get(k, 0.0)] for k in keys if src.get(k, 0.0) != tgt.get(k, 0.0)
    }
    if not diffs:
        return _axis(MATCH, len(src), len(tgt))
    # Max relative difference is a DIAGNOSTIC only — no tolerance is
    # validated, so any difference is DIFFERENT.
    rel = []
    for s, t in diffs.values():
        denom = max(abs(s), abs(t))
        if denom > 0:
            rel.append(abs(s - t) / denom)
    return _axis(
        DIFFERENT,
        len(src),
        len(tgt),
        {
            "differingKeys": len(diffs),
            "examples": dict(list(diffs.items())[:8]),
            "maxRelativeDifference": round(max(rel), 4) if rel else None,
        },
    )


def _demand_axis(src: TradeMarketFormat, tgt: TradeMarketFormat, families: Iterable[str]) -> dict:
    fams = tuple(families)
    if src.demand is None or tgt.demand is None:
        return _axis(UNKNOWN)
    s = {f: list(src.demand_for(f) or (0, 0)) for f in fams}
    t = {f: list(tgt.demand_for(f) or (0, 0)) for f in fams}
    return _axis(MATCH if s == t else DIFFERENT, s, t)


def compare_formats(src: TradeMarketFormat, tgt: TradeMarketFormat) -> dict[str, dict[str, Any]]:
    axes: dict[str, dict[str, Any]] = {}
    axes["dynastyState"] = (
        _axis(UNKNOWN, src.dynasty_state, tgt.dynasty_state)
        if src.dynasty_state is None or tgt.dynasty_state is None
        else _axis(
            MATCH if src.dynasty_state == tgt.dynasty_state == DYNASTY else DIFFERENT,
            src.dynasty_state,
            tgt.dynasty_state,
            {"sourceBasis": src.dynasty_basis},
        )
    )
    axes["teamCount"] = _eq_axis(src.teams, tgt.teams)
    axes["qbDemand"] = _demand_axis(src, tgt, ("QB",))
    axes["offenseRosterDemand"] = _demand_axis(src, tgt, ("RB", "WR"))
    if axes["offenseRosterDemand"]["state"] == MATCH and (
        src.total_starters is not None and tgt.total_starters is not None
    ):
        # Total starters guards a K / DEF / extra-flex difference the
        # per-family pairs alone would not see.
        if src.total_starters != tgt.total_starters:
            axes["offenseRosterDemand"] = _axis(
                DIFFERENT,
                {"totalStarters": src.total_starters},
                {"totalStarters": tgt.total_starters},
            )
    axes["teRosterDemand"] = _demand_axis(src, tgt, ("TE",))
    axes["teScoring"] = _scoring_axis(
        src.scoring_subset(_is_te_key), tgt.scoring_subset(_is_te_key)
    )
    axes["offenseScoring"] = _scoring_axis(
        src.scoring_subset(lambda k: not _is_idp_key(k) and not _is_te_key(k)),
        tgt.scoring_subset(lambda k: not _is_idp_key(k) and not _is_te_key(k)),
    )
    axes["idpEnabled"] = _eq_axis(src.idp_enabled, tgt.idp_enabled)
    both_off = src.idp_enabled is False and tgt.idp_enabled is False
    if both_off:
        for name in ("idpStarterDepth", "idpPositionalStructure", "idpScoring"):
            axes[name] = _axis(MATCH, 0, 0, "both_offense_only")
    elif axes["idpEnabled"]["state"] != MATCH:
        for name in ("idpStarterDepth", "idpPositionalStructure", "idpScoring"):
            axes[name] = _axis(axes["idpEnabled"]["state"], detail="idp_enabled_not_matched")
    else:
        axes["idpStarterDepth"] = _eq_axis(src.idp_starters, tgt.idp_starters)
        axes["idpPositionalStructure"] = _demand_axis(src, tgt, IDP_FAMILIES)
        if axes["idpPositionalStructure"]["state"] == MATCH and (
            (src.idp_slot_tokens or {}).get("IDP_FLEX", 0)
            != (tgt.idp_slot_tokens or {}).get("IDP_FLEX", 0)
        ):
            axes["idpPositionalStructure"] = _axis(
                DIFFERENT, dict(src.idp_slot_tokens or {}), dict(tgt.idp_slot_tokens or {})
            )
        axes["idpScoring"] = _scoring_axis(
            src.scoring_subset(_is_idp_key), tgt.scoring_subset(_is_idp_key)
        )
    axes["rosterDepth"] = (
        _axis(UNKNOWN, [src.roster_size, src.taxi_size], [tgt.roster_size, tgt.taxi_size])
        if None in (src.roster_size, src.taxi_size, tgt.roster_size, tgt.taxi_size)
        else _eq_axis([src.roster_size, src.taxi_size], [tgt.roster_size, tgt.taxi_size])
    )
    axes["bestBall"] = _eq_axis(src.best_ball, tgt.best_ball)
    return {name: axes[name] for name in AXES}


def strongest_unsupported_axis(axes: Mapping[str, Mapping[str, Any]]) -> str | None:
    for name in AXES:
        if axes[name]["state"] == DIFFERENT:
            return name
    for name in AXES:
        if axes[name]["state"] == UNKNOWN:
            return name
    return None


def format_authority(axes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """A summary whose every component stays inspectable — counts and names,
    never a blended score."""
    return {
        "matchedAxes": [n for n in AXES if axes[n]["state"] == MATCH],
        "differentAxes": [n for n in AXES if axes[n]["state"] == DIFFERENT],
        "unknownAxes": [n for n in AXES if axes[n]["state"] == UNKNOWN],
        "matchedCount": sum(1 for n in AXES if axes[n]["state"] == MATCH),
        "axisCount": len(AXES),
    }


# ── Translators (plumbing only — none validated) ─────────────────────────


class TranslatorRefused(ValueError):
    """A translator was registered in a way the policy forbids."""


#: Evidence keys a translator must carry before it may claim ``validated``.
REQUIRED_VALIDATION_EVIDENCE = (
    "trainTradeIds",
    "testTradeIds",
    "split",
    "baselines",
    "metrics",
    "beatsAllBaselines",
)
REQUIRED_BASELINES = ("no_adjustment", "exclusion", "positional_baseline")


@dataclass(frozen=True)
class Translator:
    version: str
    applies: Callable[[TradeMarketFormat, TradeMarketFormat], bool]
    transform: Callable[[Mapping[str, Any], TradeMarketFormat, TradeMarketFormat], dict[str, Any]]
    #: ``per_asset_structural`` etc.  ``global`` (one multiplier for a whole
    #: format axis) is refused at registration.
    adjustment_scope: str
    validated: bool = False
    validation_evidence: Mapping[str, Any] | None = None


def check_validation_evidence(evidence: Mapping[str, Any] | None) -> list[str]:
    """Problems that forbid ``validated=True``; empty list = acceptable."""
    if not isinstance(evidence, Mapping):
        return ["no_evidence"]
    problems = [f"missing:{k}" for k in REQUIRED_VALIDATION_EVIDENCE if k not in evidence]
    train = set(evidence.get("trainTradeIds") or [])
    test = set(evidence.get("testTradeIds") or [])
    if not test:
        problems.append("empty_test_set")
    if train & test:
        problems.append("train_test_overlap")
    baselines = set(evidence.get("baselines") or [])
    for b in REQUIRED_BASELINES:
        if b not in baselines:
            problems.append(f"baseline_missing:{b}")
    if evidence.get("beatsAllBaselines") is not True:
        problems.append("does_not_beat_baselines")
    return problems


class TranslatorRegistry:
    def __init__(self) -> None:
        self._translators: list[Translator] = []

    def register(self, translator: Translator) -> None:
        if translator.adjustment_scope == "global":
            raise TranslatorRefused(
                "a single global format multiplier (e.g. 1QB×k = SF, IDP×k) is prohibited"
            )
        if translator.validated:
            problems = check_validation_evidence(translator.validation_evidence)
            if problems:
                raise TranslatorRefused(f"validated=True refused: {problems}")
        self._translators.append(translator)

    def validated_for(self, src: TradeMarketFormat, tgt: TradeMarketFormat) -> Translator | None:
        for t in self._translators:
            if t.validated and t.applies(src, tgt):
                return t
        return None

    def __len__(self) -> int:
        return len(self._translators)


#: Production registry.  EMPTY by design: no translator has held-out
#: evidence yet, so nothing reaches VALIDATED_TRANSFORMABLE.
DEFAULT_REGISTRY = TranslatorRegistry()


def disposition(
    src: TradeMarketFormat,
    tgt: TradeMarketFormat,
    *,
    observation: Mapping[str, Any] | None = None,
    registry: TranslatorRegistry | None = None,
) -> dict[str, Any]:
    """Exactly one target-pricing disposition, with every axis attached."""
    reg = registry if registry is not None else DEFAULT_REGISTRY
    axes = compare_formats(src, tgt)
    authority = format_authority(axes)
    if not authority["differentAxes"] and not authority["unknownAxes"]:
        return {
            "disposition": NATIVE_COMPARABLE,
            "strongestUnsupportedAxis": None,
            "comparability": axes,
            "formatAuthority": authority,
            "translation": None,
        }
    translator = reg.validated_for(src, tgt)
    if translator is not None and observation is not None:
        transformed = translator.transform(observation, src, tgt)
        return {
            "disposition": VALIDATED_TRANSFORMABLE,
            "strongestUnsupportedAxis": strongest_unsupported_axis(axes),
            "comparability": axes,
            "formatAuthority": authority,
            "translation": {
                "originalObservationId": observation.get("underlyingTradeId")
                or observation.get("observationId"),
                "sourceFingerprint": src.to_dict()["fingerprint"],
                "targetFingerprint": tgt.to_dict()["fingerprint"],
                "transformationVersion": translator.version,
                "adjustments": transformed.get("adjustments"),
                "transformed": transformed.get("transformed"),
                "uncertainty": transformed.get("uncertainty"),
                "validationEvidence": dict(translator.validation_evidence or {}),
            },
        }
    return {
        "disposition": TARGET_UNSUPPORTED,
        "strongestUnsupportedAxis": strongest_unsupported_axis(axes),
        "comparability": axes,
        "formatAuthority": authority,
        "translation": None,
    }


def holdout_split(
    trades: Sequence[Mapping[str, Any]],
    *,
    is_test: Callable[[Mapping[str, Any]], bool],
    group_key: Callable[[Mapping[str, Any]], Any] | None = None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Split UNDERLYING trades (never raw observations) into train / test.

    ``group_key`` (default: host league) makes the split respect clusters: if
    any trade of a group is a test trade, the whole group is test, so a league
    or period can never sit on both sides.  The same underlying trade can
    therefore never be both trained on and tested on.
    """
    gk = group_key or (
        lambda t: (t.get("host"), t.get("hostLeagueId"))
        if t.get("hostLeagueId")
        else t.get("underlyingTradeId")
    )
    test_groups = {gk(t) for t in trades if is_test(t)}
    train = [t for t in trades if gk(t) not in test_groups]
    test = [t for t in trades if gk(t) in test_groups]
    train_ids = {t.get("underlyingTradeId") for t in train}
    test_ids = {t.get("underlyingTradeId") for t in test}
    if train_ids & test_ids:  # pragma: no cover - structural guard
        raise AssertionError("holdout split leaked an underlying trade into both sides")
    return train, test
