"""Low-value depth disclosure: the ONE owner of "would the depth note fire".

Owner decision 2026-10-21, LVA Package 4 (V4), recorded verbatim in
``docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md``: private-only, no public
disclosure, rule A-guarded, floor threshold, picks included, guard preserved,
calculator and War Room first, the War Room Team Context integration held
until #1890 is settled.  **Shadow measurement only.**  No copy is rendered, no
field is added to any payload, and nothing reads this module's answer back
into a value, a verdict or a ranking.  The display decision is the owner's,
separately.  Design: ``docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md``
(§2 definitions, §3.1 rule A-guarded, §7.1 owner sketch).

Pure: it computes no value, no band, no threshold and no package utility.

* The depth lines are read from their canonical owners: ``R_pos`` from
  ``src/draft/displacement.waiver_values_by_position`` (the prereg anchor),
  ``S_pos`` from the contract's ``sleeper.teams[].optimalLineup.starters``
  (the C2-U1 lineup owner's stamp), ``R_*`` from
  ``src/trade/faab_engine.resolve_anchors(...).v_repl``, built the way the
  shadow study built it.  An unavailable line is UNKNOWN, never a default and
  never another league's line.
* The fairness result is the market lens's own: ``analyze_trade.equity_verdict``
  (the one definition ``_market_lens`` and Best Trade share) over the priced
  values, banded by ``src/valuation_math/fairness_bands`` whatever version is
  active.  The counterfactual "without the low-value depth" is that same call
  on the reduced package.  Whether the fairness state is evaluable at all is
  the market lens's asset evidence gates (``trade_decision.asset_evidence_gaps``).

Both owners are injected (``verdict`` / ``evidence_gaps``) with the canonical
defaults, so the module itself holds no fairness logic (pinned by an AST test).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from src.utils.name_clean import normalize_position

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "depth_disclosure.json"

#: Positions whose pieces are IDP for the aggregate class buckets.
_IDP_POSITIONS = frozenset({"DL", "LB", "DB"})

PieceClass = Literal["lvd", "not_lvd", "unknown"]
Region = Literal["against", "fair", "favour"]

#: Reasons, design §7.1.  ``only_low_value_pieces`` is the guard.
STATE_SHOWN = "shown"
STATE_NOT_SHOWN = "not_shown"
STATE_NOT_EVALUATED = "not_evaluated"


class DepthDisclosureConfigError(ValueError):
    """The owner config is unreadable or names a choice the owner did not make."""


def load_config(path: Path | None = None) -> dict[str, Any]:
    """The owner-approved configuration.  Fails closed on any choice the owner
    did not approve (only ``A_guarded`` + ``floor`` exist)."""
    try:
        cfg = json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DepthDisclosureConfigError(f"depth_disclosure config unreadable: {exc}") from exc
    if not isinstance(cfg, dict):
        raise DepthDisclosureConfigError("depth_disclosure config is not an object")
    if cfg.get("rule") != "A_guarded" or cfg.get("threshold") != "floor":
        raise DepthDisclosureConfigError(
            "depth_disclosure config must be rule A_guarded with the floor threshold "
            "(owner decision 2026-10-21, Package 4)"
        )
    if not isinstance(cfg.get("includePicks"), bool) or not isinstance(cfg.get("guard"), bool):
        raise DepthDisclosureConfigError("includePicks and guard must be booleans")
    if not isinstance(cfg.get("version"), str) or not cfg["version"]:
        raise DepthDisclosureConfigError("depth_disclosure config carries no version")
    return cfg


# ── league depth lines (design §2.1) ──────────────────────────────────────


@dataclass(frozen=True)
class DepthLines:
    """League-level lines, built from one contract.  Never depends on who asks."""

    league_key: str
    replacement: Mapping[str, float]  # R_pos
    lowest_starter: Mapping[str, float]  # S_pos
    pick_line: float | None  # R_*
    include_picks: bool
    guard: bool
    version: str
    source: Mapping[str, str] = field(default_factory=dict)


def _board_rows(contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = contract.get("playersArray")
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []


def _priced(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def league_depth_lines(
    contract: Mapping[str, Any] | None,
    league_key: str,
    roster_settings: Mapping[str, Any] | None,
    *,
    config: Mapping[str, Any] | None = None,
) -> DepthLines | str:
    """The lines for the league whose rosters this contract carries, or the
    reason they are unavailable (``lines_unavailable:<why>``).

    Fails closed: every team must carry an available optimal lineup (one
    missing team could raise ``S_pos`` above the league's true lowest starter),
    the league must state its starters, and the pick line must come from the
    board rather than the FAAB engine's fallback constants.
    """
    from src.draft.displacement import waiver_values_by_position  # noqa: PLC0415
    from src.trade import faab_engine  # noqa: PLC0415

    cfg = config or load_config()
    if not isinstance(contract, Mapping) or not league_key:
        return "lines_unavailable:no_contract"
    sleeper = contract.get("sleeper")
    teams = sleeper.get("teams") if isinstance(sleeper, Mapping) else None
    if not isinstance(teams, list) or len(teams) < 2:
        return "lines_unavailable:no_rosters"
    rows = _board_rows(contract)
    if not rows:
        return "lines_unavailable:no_board"

    lineups = [t.get("optimalLineup") if isinstance(t, Mapping) else None for t in teams]
    if not all(isinstance(ol, Mapping) and ol.get("available") is True for ol in lineups):
        return "lines_unavailable:no_lineups"

    rostered_names: set[str] = set()
    rostered_keys: list[str] = []
    for t in teams:
        if not isinstance(t, Mapping):
            continue
        for n in t.get("players") or []:
            rostered_names.add(str(n))
            rostered_keys.append(str(n))
        rostered_keys.extend(str(x) for x in (t.get("playerIds") or []) if x)

    # R_pos — the canonical replacement owner, keyed in the canonical family.
    replacement: dict[str, float] = {}
    for pos, v in waiver_values_by_position(contract, rostered_keys).items():
        fam = normalize_position(pos)
        if fam and _priced(v):
            replacement[fam] = max(replacement.get(fam, 0.0), float(v))

    # S_pos — the lowest optimal-lineup starter per position, across the league.
    value_pos: dict[str, tuple[float, str]] = {}
    for r in rows:
        if str(r.get("assetClass") or "").lower() == "pick":
            continue
        v = r.get("rankDerivedValue")
        fam = normalize_position(r.get("position"))
        if not _priced(v) or not fam:
            continue
        for key in (r.get("canonicalName"), r.get("displayName")):
            if key:
                value_pos.setdefault(str(key), (float(v), fam))
    lowest_starter: dict[str, float] = {}
    for ol in lineups:
        for name in ol.get("starters") or []:  # type: ignore[union-attr]
            hit = value_pos.get(str(name))
            if hit is None:
                continue
            v, fam = hit
            lowest_starter[fam] = min(lowest_starter.get(fam, v), v)

    # R_* — the league-wide replacement level (FAAB V_repl), as the study built it.
    pick_line: float | None = None
    starters = (roster_settings or {}).get("starters")
    spt = (
        sum(int(v or 0) for k, v in starters.items() if str(k).upper() != "K")
        if isinstance(starters, Mapping)
        else 0
    )
    if spt <= 0:
        return "lines_unavailable:no_starter_counts"
    excluded = set(faab_engine.FaabConfig().get("anchors", "excludedPositions", []) or [])
    board_vals: list[float] = []
    avail_vals: list[float] = []
    for r in rows:
        v = r.get("rankDerivedValue")
        if str(r.get("assetClass") or "").lower() == "pick" or not _priced(v):
            continue
        if str(r.get("position") or "").upper() in excluded:
            continue
        board_vals.append(float(v))
        if str(r.get("displayName") or "") not in rostered_names:
            avail_vals.append(float(v))
    anchors = faab_engine.resolve_anchors(
        board_vals,
        faab_engine.LeagueContext(team_count=len(teams), starters_per_team=spt),
        available_values=avail_vals or None,
    )
    if "fallback" not in str(getattr(anchors, "source", "")) and _priced(anchors.v_repl):
        pick_line = float(anchors.v_repl)

    return DepthLines(
        league_key=str(league_key),
        replacement=replacement,
        lowest_starter=lowest_starter,
        pick_line=pick_line,
        include_picks=bool(cfg["includePicks"]),
        guard=bool(cfg["guard"]),
        version=str(cfg["version"]),
        source={
            "replacement": str(cfg.get("replacementSource") or ""),
            "lowestStarter": str(cfg.get("lowestStarterSource") or ""),
            "pickLine": str(cfg.get("pickLineSource") or ""),
        },
    )


# ── piece classification (design §2.2, floor threshold) ───────────────────


def is_pick(asset: Mapping[str, Any]) -> bool:
    return str(asset.get("assetClass") or "").lower() == "pick" or asset.get("pos") == "PICK"


def piece_group(asset: Mapping[str, Any]) -> str:
    """``offense`` / ``idp`` / ``pick`` — the aggregate bucket, never a name."""
    if is_pick(asset):
        return "pick"
    fam = normalize_position(asset.get("basePos") or asset.get("pos"))
    return "idp" if fam in _IDP_POSITIONS else "offense"


def classify_piece(asset: Mapping[str, Any], lines: DepthLines) -> PieceClass:
    """``lvd`` iff below the floor ``min(R_pos, S_pos)`` (a pick: below ``R_*``).

    No canonical value, a quarantined value or a position without both lines
    is ``unknown`` -- never zero, never LVD, never "not LVD".  With picks
    excluded by the owner config a priced pick is ``not_lvd``.
    """
    v = asset.get("value")
    if not _priced(v) or asset.get("quarantined") is True:
        return "unknown"
    if is_pick(asset):
        if not lines.include_picks:
            return "not_lvd"
        if lines.pick_line is None:
            return "unknown"
        return "lvd" if float(v) < lines.pick_line else "not_lvd"
    fam = normalize_position(asset.get("basePos") or asset.get("pos"))
    r = lines.replacement.get(fam)
    s = lines.lowest_starter.get(fam)
    if r is None or s is None:
        return "unknown"
    return "lvd" if float(v) < min(r, s) else "not_lvd"


def _asset_ref(asset: Mapping[str, Any]) -> str:
    """Canonical asset id for the top-piece tie-break (lowest id wins)."""
    aid = str(asset.get("assetId") or "").strip()
    if aid:
        return aid
    pid = str(asset.get("playerId") or "").strip()
    if pid:
        return f"p:{pid}"
    return str(asset.get("name") or asset.get("sourceLabel") or "")


def top_piece_index(received: Sequence[Mapping[str, Any]]) -> int | None:
    """The highest-valued received piece; ties go to the lowest asset id."""
    if not received:
        return None
    order = sorted(
        range(len(received)),
        key=lambda i: (-float(received[i]["value"]), _asset_ref(received[i])),
    )
    return order[0]


# ── the rule (design §3.1, A-guarded) ─────────────────────────────────────


@dataclass(frozen=True)
class TeamDepthDisclosure:
    """One team's would-be note.  Aggregate fields only: no names, no values."""

    state: str  # shown | not_shown | not_evaluated
    reason: str | None
    region: Region | None = None
    counterfactual_region: Region | None = None
    band: str | None = None
    counterfactual_band: str | None = None
    extra_groups: tuple[str, ...] = ()  # piece_group of every E_i piece
    received_count: int = 0
    given_count: int = 0

    @property
    def fires(self) -> bool:
        return self.state == STATE_SHOWN


Verdict = Callable[[list[float], list[float]], Mapping[str, Any]]


def _default_verdict() -> Verdict:
    from src.trade.analyze_trade import equity_verdict  # noqa: PLC0415

    return equity_verdict


def _counts_as_fair(level: Any) -> bool:
    from src.valuation_math import fairness_bands  # noqa: PLC0415

    return fairness_bands.counts_as_fair_trade(level)


def _region(result: Mapping[str, Any]) -> Region:
    level = (result.get("band") or {}).get("level")
    if _counts_as_fair(level):
        return "fair"
    gap = float(result.get("vaAdjustedGap") or 0)
    if gap > 0:
        return "favour"
    if gap < 0:
        return "against"
    return "fair"


def team_depth_disclosure(
    received: Sequence[Mapping[str, Any]],
    given: Sequence[Mapping[str, Any]],
    lines: DepthLines,
    *,
    verdict: Verdict | None = None,
) -> TeamDepthDisclosure:
    """Rule A-guarded for one team: ``received`` is ``Rcv_i``, ``given`` ``Gv_i``.

    The caller has already established that every piece is priced and the
    fairness state is evaluable (:func:`evaluate_two_team` does).  An unknown
    piece still refuses here, so this function can never guess on its own.
    """
    verdict = verdict or _default_verdict()
    if not received or not given:
        return TeamDepthDisclosure(STATE_NOT_EVALUATED, "one_sided")
    classes = [classify_piece(a, lines) for a in (*received, *given)]
    if "unknown" in classes:
        return TeamDepthDisclosure(STATE_NOT_EVALUATED, "unknown_piece")
    rcv_classes = classes[: len(received)]
    top = top_piece_index(received)
    extras = [i for i, c in enumerate(rcv_classes) if c == "lvd" and i != top]
    n_r, n_g = len(received), len(given)
    if not extras:
        return TeamDepthDisclosure(
            STATE_NOT_SHOWN, "no_low_value_depth", received_count=n_r, given_count=n_g
        )
    rcv_values = [float(a["value"]) for a in received]
    gv_values = [float(a["value"]) for a in given]
    real = verdict(gv_values, rcv_values)
    removed = set(extras)
    cf = verdict(gv_values, [v for i, v in enumerate(rcv_values) if i not in removed])
    region, cf_region = _region(real), _region(cf)
    common = {
        "region": region,
        "counterfactual_region": cf_region,
        "band": (real.get("band") or {}).get("level"),
        "counterfactual_band": (cf.get("band") or {}).get("level"),
        "extra_groups": tuple(sorted(piece_group(received[i]) for i in extras)),
        "received_count": n_r,
        "given_count": n_g,
    }
    if region == cf_region:
        return TeamDepthDisclosure(STATE_NOT_SHOWN, "result_does_not_depend", **common)
    if lines.guard and "not_lvd" not in classes:
        return TeamDepthDisclosure(STATE_NOT_SHOWN, "only_low_value_pieces", **common)
    return TeamDepthDisclosure(STATE_SHOWN, None, **common)


#: Asset evidence gate codes that mean a piece is UNKNOWN (design §2.2);
#: every other gate means the fairness state itself is unavailable (§3 p2).
_UNKNOWN_PIECE_GATES = frozenset(
    {"no_priced_assets", "off_board_assets", "unpriced_assets", "quarantined_values"}
)


def _default_evidence_gaps(simulation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    from src.trade import analyze_trade, trade_decision  # noqa: PLC0415

    return trade_decision.asset_evidence_gaps(
        dict(simulation), analyze_trade._market_lens(dict(simulation))
    )


def evaluate_two_team(
    simulation: Mapping[str, Any],
    lines: DepthLines | str,
    *,
    verdict: Verdict | None = None,
    evidence_gaps: Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, TeamDepthDisclosure]:
    """Both teams of one 2-team simulation: ``self`` (the simulated team, which
    receives ``receiving``) and ``partner`` (which receives ``sending``).

    Preconditions (design §3): lines unavailable, any evidence gap the market
    lens raises (UNKNOWN piece or NOT_ENOUGH_EVIDENCE), or a package model the
    rule is not defined under -> ``not_evaluated`` for both teams.
    """
    from src.trade.analyze_service import package_model_ready  # noqa: PLC0415

    def both(reason: str) -> dict[str, TeamDepthDisclosure]:
        d = TeamDepthDisclosure(STATE_NOT_EVALUATED, reason)
        return {"self": d, "partner": d}

    if isinstance(lines, str):
        return both(lines)
    if not package_model_ready():
        return both("package_model_unavailable")
    gaps = list((evidence_gaps or _default_evidence_gaps)(simulation))
    if gaps:
        code = str((gaps[0] or {}).get("code") or "unknown")
        kind = "unknown_piece" if code in _UNKNOWN_PIECE_GATES else "result_unavailable"
        return both(f"{kind}:{code}")
    receiving = [a for a in (simulation.get("receiving") or []) if isinstance(a, Mapping)]
    sending = [a for a in (simulation.get("sending") or []) if isinstance(a, Mapping)]
    return {
        "self": team_depth_disclosure(receiving, sending, lines, verdict=verdict),
        "partner": team_depth_disclosure(sending, receiving, lines, verdict=verdict),
    }
