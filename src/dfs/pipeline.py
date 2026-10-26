"""The contest-aware pipeline, end to end, as ONE auditable function per question.

``prepare`` assembles everything a simulation needs from what was HELD at a
pre-lock time T: ownership forecast (``ownership.forecast`` via ``pit.as_of``)
→ field sample (``field.generate``) → outcome distributions
(``distributions.build``) → correlation priors → duplication estimates.  It
refuses rather than guesses: a player the field or our lineups need with no
outcome range is listed (unless the caller explicitly allows flagged priors),
and a contest without a known field size cannot be simulated.

``simulate_lineups`` then runs the contest Monte Carlo on given lineups.  The
portfolio optimizer and the backtest harness call the same two functions, so a
live answer and a historical replay are computed identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.dfs import contestsim, correlation, distributions, duplication, field, ownership, pit
from src.dfs.contests import Contest
from src.dfs.imports import SlateAthlete
from src.dfs.rules import RuleSet

API_MAX_SIMS = 2_000
API_MAX_FIELD_SAMPLE = 3_000


class PipelineError(ValueError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass
class Prepared:
    setup: contestsim.SimSetup
    ownership: dict[str, Any]
    field_fit: dict[str, Any]
    athletes: dict[str, SlateAthlete]
    dup_params: dict[str, float] | None
    correlation: dict[str, Any]
    as_of: str


def field_size(contest: Contest) -> int:
    n = contest.current_entries or contest.capacity
    if not n or n < 2:
        raise PipelineError(
            "FIELD_SIZE_UNKNOWN", "The contest's field size is unknown; it cannot be simulated."
        )
    return int(n)


def prepare(
    owner: str,
    snapshot: dict[str, Any],
    ruleset: RuleSet,
    contest: Contest,
    at: str,
    *,
    sims: int,
    field_sample: int,
    seed: int,
    allow_priors: bool = False,
    must_cover: set[str] | None = None,
) -> Prepared:
    n = field_size(contest)
    if pit.get_slate(owner, snapshot["id"]) is None:
        pit.capture_snapshot(owner, snapshot)
    fc = ownership.forecast(owner, snapshot, ruleset, at)
    target = {pid: r["ownership"] for pid, r in fc["players"].items() if r["ownership"]}
    athletes = [SlateAthlete(**a) for a in snapshot["body"]["athletes"]]
    by_id = {a.player_id: a for a in athletes}
    sport = ruleset.sport
    fld = field.generate(athletes, ruleset, target, sport=sport, size=field_sample, seed=seed)
    if not fld.lineups:
        raise PipelineError(
            "FIELD_EMPTY", "No legal field lineup could be generated from the ownership forecast."
        )
    needed = {p for lu in fld.lineups for p in lu} | (must_cover or set())
    dists, missing = [], []
    for pid in sorted(needed):
        d = distributions.build(by_id[pid], sport, allow_priors=allow_priors)
        (dists.append(d) if d else missing.append(by_id[pid].name))
    if missing:
        raise PipelineError(
            "OUTCOME_RANGE_MISSING",
            f"{len(missing)} player(s) the contest needs have no outcome range. Import ranges (StDev or "
            "percentiles) or explicitly allow flagged spread priors.",
            {"players": missing[:40]},
        )
    corr = correlation.pairs([by_id[p] for p in needed], sport)
    champ = pit.champion(duplication.MODEL_ID)
    return Prepared(
        setup=contestsim.SimSetup(
            ruleset, contest, n, dists, corr["pairs"], fld.lineups, sims, seed
        ),
        ownership=fc,
        field_fit=fld.fit,
        athletes=by_id,
        dup_params=champ["params"] if champ else None,
        correlation={k: v for k, v in corr.items() if k != "pairs"}
        | {"pairCount": len(corr["pairs"])},
        as_of=fc["asOf"],
    )


def expected_copies(prep: Prepared, lineups: list[tuple[str, ...]]) -> list[dict[str, Any]]:
    own = {
        pid: r["ownership"]
        for pid, r in prep.ownership["players"].items()
        if r["ownership"] is not None
    }
    sal = {pid: a.salary for pid, a in prep.athletes.items()}
    return [
        duplication.estimate(
            list(lu),
            own,
            sal,
            prep.setup.ruleset.salary_cap,
            prep.setup.field_size,
            prep.dup_params,
        )
        for lu in lineups
    ]


def simulate_lineups(prep: Prepared, lineups: list[tuple[str, ...]]) -> dict[str, Any]:
    dup = expected_copies(prep, lineups)
    rate = [
        (d.get("fitted", d.get("naive", 0.0)) if d["state"] == "estimated" else 0.0) for d in dup
    ]
    out = contestsim.simulate(prep.setup, lineups, rate)
    for row, d in zip(out["perLineup"], dup):
        row["duplication"] = d
    out["inputs"] = {
        "asOf": prep.as_of,
        "inputsDigest": prep.ownership["inputsDigest"],
        "ownershipMethods": _methods(prep.ownership),
        "fieldFit": prep.field_fit,
        "correlation": prep.correlation,
        "duplicationModel": duplication.MODEL_ID if prep.dup_params else duplication.NAIVE_ID,
    }
    if any(d["state"] != "estimated" for d in dup):
        out["assumptions"].append(
            "duplication unknown for some lineups (missing ownership): simulated with no copies"
        )
    return out


def _methods(fc: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in fc["players"].values():
        key = r["method"].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    return counts
