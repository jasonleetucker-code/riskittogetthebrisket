"""Sport-specific correlation between players' fantasy outcomes (DFS-MOD-04).

One interface — ``pairs(athletes) -> {(identity_a, identity_b): rho}`` — with a
module per sport, so the simulator never grows a per-sport branch.  Every
number below is a declared, CONSERVATIVE PRIOR (``PRIOR_VERSION``), not a fit:
the directions follow well-established DFS game logic, the magnitudes are
deliberately shrunk toward zero because nothing here has been fitted to this
system's data yet.  A fitted model replaces a module through the model
registry (``pit``), never by editing these constants in place.

* NFL — QB with his own pass catchers (+), QB with his RB (small +), same-team
  pass catchers compete (small −), same-team RBs compete (−), bring-back:
  QB with opposing pass catchers (+), DST against the opposing offense (−),
  DST with its own RB (small +, game script).
* NBA — teammates compete for usage (small −); opponents share pace and
  overtime (small +).
* NHL — same-team skaters score together (+; no line data, so one team-wide
  value), a goalie against the opposing skaters (−), own goalie and skaters (small +).
* MMA — the two fighters in one bout are strongly opposed (−): one wins.
* anything else — independent (no correlation), stated.
"""

from __future__ import annotations

from typing import Any

PRIOR_VERSION = "correlation.priors@1.0.0"

_NFL_PASS_CATCHERS = {"WR", "TE"}


def _pos(a: Any) -> set[str]:
    return set(a.positions)


def _same_team(a: Any, b: Any) -> bool:
    return bool(a.team) and a.team == b.team


def _opponents(a: Any, b: Any) -> bool:
    return bool(a.opponent) and a.opponent == b.team


def nfl(a: Any, b: Any) -> float:
    pa, pb = _pos(a), _pos(b)
    if _same_team(a, b):
        if "QB" in pa and pb & _NFL_PASS_CATCHERS or "QB" in pb and pa & _NFL_PASS_CATCHERS:
            return 0.30
        if "QB" in pa and "RB" in pb or "QB" in pb and "RB" in pa:
            return 0.08
        if pa & _NFL_PASS_CATCHERS and pb & _NFL_PASS_CATCHERS:
            return -0.05
        if "RB" in pa and "RB" in pb:
            return -0.15
        if "DST" in pa and "RB" in pb or "DST" in pb and "RB" in pa:
            return 0.08
        return 0.0
    if _opponents(a, b) or _opponents(b, a):
        if "DST" in pa or "DST" in pb:
            return -0.20 if not ("DST" in pa and "DST" in pb) else -0.05
        if "QB" in pa and pb & _NFL_PASS_CATCHERS or "QB" in pb and pa & _NFL_PASS_CATCHERS:
            return 0.12
        if "QB" in pa and "QB" in pb:
            return 0.10
        return 0.03
    return 0.0


def nba(a: Any, b: Any) -> float:
    if _same_team(a, b):
        return -0.05
    if _opponents(a, b) or _opponents(b, a):
        return 0.05
    return 0.0


def nhl(a: Any, b: Any) -> float:
    ga, gb = "G" in _pos(a), "G" in _pos(b)
    if _same_team(a, b):
        return 0.05 if ga or gb else 0.12
    if _opponents(a, b) or _opponents(b, a):
        if ga != gb:
            return -0.20
        return 0.03
    return 0.0


def mma(a: Any, b: Any) -> float:
    # Same bout: the file gives both fighters one game; they are opponents.
    if a.game and a.game == b.game:
        return -0.60
    return 0.0


MODULES = {"nfl": nfl, "nba": nba, "nhl": nhl, "mma": mma}


def pairs(athletes: list[Any], sport: str) -> dict[str, Any]:
    """Pairwise correlations between distinct ATHLETES (identities) on one slate."""
    fn = MODULES.get(sport)
    by_ident: dict[str, Any] = {}
    for a in athletes:
        by_ident.setdefault(getattr(a, "identity", a.player_id), a)
    out: dict[tuple[str, str], float] = {}
    if fn is not None:
        idents = list(by_ident)
        for i, x in enumerate(idents):
            for y in idents[i + 1 :]:
                rho = fn(by_ident[x], by_ident[y])
                if rho:
                    out[(x, y)] = rho
    return {
        "model": PRIOR_VERSION if fn else "independent",
        "sport": sport,
        "calibrated": False,
        "pairs": out,
        "note": "Declared conservative priors, not fitted to this system's data."
        if fn
        else f"No correlation module for {sport!r}: players treated as independent.",
    }
