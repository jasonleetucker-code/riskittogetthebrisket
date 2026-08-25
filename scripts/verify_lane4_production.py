#!/usr/bin/env python3
"""Lane 4 production verification — executable post-deploy checks.

WHAT THIS IS
------------
The Lane 4 V1 rows (`docs/VERSION_1_COMPLETION_CONTRACT.md` §3.5) sit at
`IMPLEMENTED_UNVERIFIED` because their evidence is **production-side**: the
crowd-FAAB ledger, the own-league bid history, the Sharp cohort and the
league scoring cards are all gitignored and prod-only. A repository cannot
prove any of them. This script is what someone with access runs so that
"verified" stops being an assertion.

It is also the before/after instrument for **#927**. Several checks below
describe behaviour that only exists once #927 deploys; run it before and
after, and the difference is the evidence.

THE THREE RULES, ENFORCED IN CODE AND NOT ONLY IN PROSE
-------------------------------------------------------
1. **Production authentication is never bypassed.** `/api/sharp/*` and
   `/api/waiver/*` require a session; this script sends one only if the
   operator supplies it. There is no fallback, no test-mode header and no
   allowlist edit. A **401 is `UNVERIFIABLE_UNAUTHENTICATED`** — recorded as
   insufficient evidence, and deliberately neither a pass nor a failure. The
   vocabulary matches `.github/workflows/verify-sharp-production.yml`, which
   already treats it that way.
2. **Nothing is fabricated.** No cohort, ledger, scoring card, crowd row or
   player is invented to make a check runnable. A check whose real input is
   absent reports `BLOCKED` and names the input. A check whose input exists
   but does not contain the case under test reports `UNMEASURABLE` — "we
   looked and the situation did not arise" is a different statement from
   "we looked and it was correct", and collapsing them is the exact defect
   class Lane 4 exists to prevent.
3. **Read-only.** Every operation is a GET, a POST that computes a
   recommendation without persisting one, a file read, or a `systemctl`
   query. Nothing writes to production.

WHY A NEW SCRIPT
----------------
`scripts/audit_status.py` tracks audit findings by source-signature tripwire,
which is a different question (has this mechanism changed?) from this one
(does the deployed system behave correctly on real data?).
`.github/workflows/verify-sharp-production.yml` polls exactly one endpoint
for one row. Neither is the owner of per-row Lane 4 production evidence.

MODES
-----
``--mode remote`` runs over HTTPS against a deployed origin and needs a
session cookie. It can see what the API publishes.

``--mode onbox`` runs **in the deployed working directory** and reads local
`data/` plus the deployed source. It can see the scoring card, the crowd
ledger and the systemd units, and it is the only mode that can compute the
before/after counterfactuals, because those need the real stored rows
re-classified under two policies.

Neither mode subsumes the other; the package is both.

USAGE
-----
    # on the box, in the deployed working directory
    python scripts/verify_lane4_production.py --mode onbox \
        --league dynasty_main --out data/ops/lane4-verification.json

    # from anywhere, with an operator-supplied session
    export RISKIT_SESSION_COOKIE='session=...'
    python scripts/verify_lane4_production.py --mode remote \
        --origin https://chaseupside.com --league dynasty_main \
        --add-player 'Some Free Agent'

EXIT CODES
----------
    0  every applicable check passed, and at least one was applicable
    1  an unexpected error while running a check
    2  at least one check FAILED
    3  no failure, but the run proved nothing — every check was blocked,
       unverifiable or inapplicable.  Distinct from 0 on purpose: an
       evidence-free run must not read as a green one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Result vocabulary ──────────────────────────────────────────────

PASS = "pass"
FAIL = "fail"
#: The input was read but the case under test could not be measured from
#: it -- the situation did not arise, or the population was empty.  NOT a
#: pass: "we looked and it did not happen" is not "we looked and it was
#: correct", and collapsing them is the defect class this lane exists to
#: catch.
UNMEASURABLE = "unmeasurable"
#: A required input does not exist here.  NOT a pass and NOT a failure.
BLOCKED = "blocked"
#: The endpoint answered 401/403.  Insufficient evidence, by design.
UNVERIFIABLE = "unverifiable_unauthenticated"
ERROR = "error"

#: Statuses that answer no question.  Each one caps the run's exit code at
#: 3, so an incomplete run can never read as green.
_PROVES_NOTHING = {UNMEASURABLE, BLOCKED, UNVERIFIABLE}


@dataclass
class Check:
    """One named assertion, with the evidence that produced it.

    ``denominator`` is what the check actually inspected -- rows examined,
    files read, units listed.  It exists because the failure mode of any
    verification tool is being GREEN WHILE INSPECTING NOTHING: a check that
    iterates an empty list and finds no offenders is indistinguishable, in
    its output, from one that examined a thousand rows and found none.

    A check that has a denominator concept sets it.  ``None`` means the
    check is not a population check (a route registration, a signature, a
    file's presence), and those are exempt.
    """

    id: str
    row: str
    title: str
    status: str = BLOCKED
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    denominator: int | None = None

    def finalize(self) -> "Check":
        """Downgrade a vacuous pass, structurally rather than by discipline.

        ``PASS`` with a denominator of ``0`` means nothing was inspected, so
        nothing was proven.  It becomes ``UNMEASURABLE`` here rather than at
        every call site, because one forgotten guard is all it takes for a
        verification run to report success over an empty population.
        """
        if self.status == PASS and self.denominator == 0:
            self.status = UNMEASURABLE
            self.detail = (
                "downgraded from pass: the check inspected 0 items, so it proved "
                "nothing. " + self.detail
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "row": self.row,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "denominator": self.denominator,
            "evidence": self.evidence,
        }


class Report:
    def __init__(self, mode: str, league: str, origin: str | None) -> None:
        self.mode = mode
        self.league = league
        self.origin = origin
        self.checks: list[Check] = []
        self.deployed: dict[str, Any] = {}

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    def finalize(self) -> None:
        """Apply the vacuous-pass guard to every check, once, at the end.

        Deliberately here and not in ``add``: a check is mutated after it is
        added (its status and denominator are set by the analyser that owns
        it), so finalising on insert would run before the numbers exist.
        """
        for check in self.checks:
            check.finalize()

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
        applicable = [c for c in self.checks if c.status not in _PROVES_NOTHING]
        return {
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "league": self.league,
            "origin": self.origin,
            "deployed": self.deployed,
            "counts": counts,
            "applicableChecks": len(applicable),
            "checks": [c.to_dict() for c in self.checks],
        }

    def exit_code(self) -> int:
        """``0`` is reserved for a COMPLETE run.

        The strict reading, and the safe one: a 401, an absent credential, an
        empty population, a missing scoring card or a missing ledger must
        never reach exit ``0``.  Each of those leaves a question unanswered,
        and an unanswered question is not a pass -- so any check that did not
        actually measure its case caps the run at ``3``, however many other
        checks passed.

        Consequence, stated rather than hidden: until production evidence
        exists this exits ``3`` on every host, which is the accurate report.
        A green ``0`` means every check ran and every one passed.
        """
        statuses = {c.status for c in self.checks}
        if ERROR in statuses:
            return 1
        if FAIL in statuses:
            return 2
        if statuses & _PROVES_NOTHING:
            return 3
        if not any(c.status == PASS for c in self.checks):
            return 3
        return 0


# ── HTTP (remote mode) ─────────────────────────────────────────────


class Unauthenticated(Exception):
    """401/403 from a session-gated endpoint.

    Its own type because it must never be swallowed by a generic handler
    and reported as a transient failure: a 401 is a definitive answer to a
    different question ("do we hold a credential?"), and the measured
    history on this repo is 80/80 attempts across 79 runs.
    """


def _http(url: str, *, cookie: str | None, body: dict | None = None, timeout: float = 30.0):
    """GET, or POST when ``body`` is supplied.  Returns ``(status, payload)``.

    The cookie is sent ONLY when the operator supplied one.  There is no
    other credential path in this script by design.
    """
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise Unauthenticated(f"{exc.code} from {url}") from exc
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw[:500]}


# ── Shared helpers ─────────────────────────────────────────────────


def _repo_file(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── Route and field existence ──────────────────────────────────────
#
# A verification step that names a route or a field which does not exist is
# WORSE than no step: an unrunnable procedure reads identically to a runnable
# one until someone with production credentials wastes an evening on it.  The
# first draft of the Lane 4 procedures shipped four such references.  These
# two helpers make that class of error a FAIL rather than a silent skip.


#: Routes this package's steps depend on, each with the module that registers
#: it.  Derived by enumerating the real decorators and ``add_api_route`` calls,
#: not from documentation.
REQUIRED_ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/status", "GET"),
    ("/api/sharp/market", "GET"),
    ("/api/sharp/cohort", "GET"),
    ("/api/sharp/roster-percentage", "GET"),
    ("/api/waiver/faab-recommend", "POST"),
)

#: Field paths this package reads, as ``(producer, dotted path)``.  A rename
#: upstream must break this rather than silently produce ``None`` at a caller.
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("roster-percentage", "transparency.cohortCoveragePct"),
    ("roster-percentage", "transparency.cohortManagers"),
    ("roster-percentage", "transparency.eligibleRosters"),
    ("roster-percentage", "cohort.selectedManagers"),
    ("roster-percentage", "status"),
    ("sharp-market", "cohort.selectedManagers"),
    ("sharp-market", "coverage.platforms"),
    ("sharp-market", "status"),
    ("crowd-market", "state"),
    ("crowd-market", "targetFormatUnknown"),
    ("crowd-market", "excludedCounts"),
    ("crowd-market", "tierCounts"),
    ("crowd-market", "pricesIdp"),
    ("crowd-market", "rowsUsed"),
    ("crowd-market", "rowsTotal"),
)


def _dotted(obj: Any, path: str) -> tuple[bool, Any]:
    """``(present, value)`` for a dotted path.  Presence, not truthiness.

    A field that exists and holds ``None`` is PRESENT -- that is the whole
    point of ``cohortCoveragePct`` being null rather than zero, and a
    truthiness test here would report the correct behaviour as a missing
    field.
    """
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _registered_routes_static() -> set[tuple[str, str]]:
    """Every route the SOURCE registers, by AST rather than by import.

    ``import server`` refuses without ``JASON_LOGIN_PASSWORD`` -- correctly,
    it is a fail-closed auth requirement -- so an import-only check reports
    BLOCKED on every machine that is not the deployed box, which is exactly
    where a stale route name in a document needs catching.  Route
    registration is a source-level fact, so it is read from the source.
    """
    import ast

    found: set[tuple[str, str]] = set()
    targets = [REPO_ROOT / "server.py", *sorted((REPO_ROOT / "src").rglob("*.py"))]
    for path in targets:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            # @app.get("/api/...") and friends
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                        continue
                    verb = dec.func.attr.upper()
                    if verb not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                        continue
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        value = dec.args[0].value
                        if isinstance(value, str):
                            found.add((value, verb))
            # app.add_api_route("/api/...", handler, methods=["GET"])
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_api_route"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                path_value = node.args[0].value
                for kw in node.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for element in kw.value.elts:
                            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                                found.add((path_value, element.value.upper()))
    return found


def check_required_routes_exist(report: Report) -> None:
    """Every route these steps name is actually registered.

    Static by design (see :func:`_registered_routes_static`), with the live
    app used as a confirmation when it can be imported.
    """
    check = report.add(Check("R0", "-", "every route this package names is registered"))
    try:
        registered = _registered_routes_static()
    except Exception as exc:  # pragma: no cover - defensive
        check.status = ERROR
        check.detail = f"route scan failed: {exc!r}"
        return
    source = "source scan"
    try:
        import server

        live = {
            (getattr(route, "path", ""), method)
            for route in getattr(server.app, "routes", [])
            for method in (getattr(route, "methods", None) or ())
        }
        if live:
            registered = live
            source = "live app"
    except Exception:
        pass

    missing = [f"{m} {p}" for p, m in REQUIRED_ROUTES if (p, m) not in registered]
    check.denominator = len(REQUIRED_ROUTES)
    check.evidence = {
        "source": source,
        "routesDiscovered": len(registered),
        "required": [f"{m} {p}" for p, m in REQUIRED_ROUTES],
        "missing": missing,
    }
    if not registered:
        check.status = BLOCKED
        check.detail = "no routes discovered at all, so nothing was verified."
        return
    if missing:
        check.status = FAIL
        check.detail = (
            f"{len(missing)} of {len(REQUIRED_ROUTES)} routes are not registered "
            f"({source}): {missing}. Any step naming one of them is unrunnable."
        )
        return
    check.status = PASS
    check.detail = (
        f"all {len(REQUIRED_ROUTES)} routes registered, confirmed by {source} "
        f"({len(registered)} routes discovered)."
    )


def check_required_fields_exist(report: Report, producers: dict[str, Any]) -> None:
    """Every field path these steps read is present in its real producer.

    ``producers`` maps the names used in :data:`REQUIRED_FIELDS` to a real
    payload.  A producer that could not be built is reported as such rather
    than counted as passing.
    """
    check = report.add(Check("R1", "-", "every field this package reads exists in its producer"))
    missing: list[str] = []
    unchecked: list[str] = []
    checked = 0
    for producer, path in REQUIRED_FIELDS:
        payload = producers.get(producer)
        if payload is None:
            unchecked.append(f"{producer}.{path}")
            continue
        checked += 1
        present, _ = _dotted(payload, path)
        if not present:
            missing.append(f"{producer}.{path}")
    check.denominator = checked
    check.evidence = {
        "checked": checked,
        "missing": missing,
        "uncheckedBecauseProducerUnavailable": unchecked,
    }
    if missing:
        check.status = FAIL
        check.detail = (
            f"{len(missing)} field path(s) absent from their producer: {missing}. Either "
            "the producer renamed them -- so every consumer is now reading nothing -- or "
            "this package is pointed at the wrong names."
        )
        return
    if checked == 0:
        check.status = BLOCKED
        check.detail = (
            "no producer could be built here, so no field path was verified: " f"{unchecked}"
        )
        return
    check.status = PASS
    check.detail = (
        f"all {checked} field paths present"
        + (f"; {len(unchecked)} unchecked (producer unavailable)" if unchecked else "")
        + "."
    )


def check_idp_population_refusal(report: Report, crowd_market: Any) -> None:
    """The offense-only population must REFUSE to price an IDP claim.

    Measured on the live feed: zero of 86 external leagues start an individual
    defender, so a median drawn from that population is offense-only evidence.
    The gate reads what the retained rows actually contain, so it self-corrects
    the day an IDP league appears -- which is why ``pricesIdp: true`` is a
    finding to record, not a failure.
    """
    check = report.add(Check("C10", "V1-129", "an offense-only population refuses to price IDP"))
    try:
        from src.trade.faab_comparability import is_idp_position, population_prices_position
    except Exception as exc:  # pragma: no cover - deployment shape
        check.status = ERROR
        check.detail = f"could not import the population gate: {exc!r}"
        return
    if crowd_market is None:
        check.status = BLOCKED
        check.detail = (
            "no crowd ledger here, so the retained population cannot be inspected. "
            "Do not synthesise rows."
        )
        return
    prices_idp = bool(getattr(crowd_market, "prices_idp", False))
    idp_positions = ["DL", "LB", "DB"]
    offense_positions = ["QB", "RB", "WR", "TE"]
    refused = [
        p for p in idp_positions if not population_prices_position(p, any_idp_source=prices_idp)
    ]
    allowed = [
        p for p in offense_positions if population_prices_position(p, any_idp_source=prices_idp)
    ]
    check.denominator = len(idp_positions) + len(offense_positions)
    check.evidence = {
        "pricesIdp": prices_idp,
        "rowsUsed": getattr(crowd_market, "rows_used", None),
        "idpPositionsRefused": refused,
        "offensePositionsAllowed": allowed,
        "isIdpPositionSane": [p for p in idp_positions if is_idp_position(p)],
    }
    if prices_idp:
        check.status = UNMEASURABLE
        check.detail = (
            "the retained population contains at least one IDP league, so the refusal "
            "branch does not apply today. That is a finding about the feed, not a "
            "failure -- record which league, and note that the gate self-corrected."
        )
        return
    if refused != idp_positions or allowed != offense_positions:
        check.status = FAIL
        check.detail = (
            f"offense-only population: expected DL/LB/DB refused and QB/RB/WR/TE "
            f"allowed, got refused={refused} allowed={allowed}."
        )
        return
    check.status = PASS
    check.detail = (
        "the retained population starts no individual defender, and the gate refuses "
        "DL/LB/DB while still pricing QB/RB/WR/TE."
    )


# ── #927 group A: person-consensus semantic states (V1-63) ─────────
#
# Three states that must never read as one another.  All three are read
# off ONE market payload, because they are properties of the same rows and
# fetching three times would let the board move underneath the check.


def _person_rows(payload: dict) -> list[tuple[str, dict]]:
    """``(assetId, personConsensus)`` for every row that has one."""
    out: list[tuple[str, dict]] = []
    for row in payload.get("assets") or []:
        if not isinstance(row, dict):
            continue
        person = row.get("personConsensus")
        if isinstance(person, dict):
            out.append((str(row.get("assetId") or ""), person))
    return out


def check_zero_voter_quality(report: Report, payload: dict, source: str) -> None:
    """#927 check 1 — zero voters must publish ``null``, never ``1.0``.

    Reachable whenever every person who touched an asset both added AND
    dropped it inside the window: the row is still emitted, with
    ``personVotes: 0``.  ``1.0`` is the HIGHEST possible manager quality, so
    the pre-#927 behaviour answered "how good is the evidence?" with a
    green light precisely when there was none.
    """
    check = report.add(
        Check(
            "C1",
            "V1-63",
            "zero-voter personManagerQuality is JSON null, never 1.0",
        )
    )
    rows = _person_rows(payload)
    if not rows:
        check.status = BLOCKED
        check.detail = (
            f"{source} published no personConsensus block on any row. With an empty "
            "cohort or an empty movement ledger there is nothing to measure — this "
            "is not evidence that the field is correct."
        )
        return
    zero = [(a, p) for a, p in rows if p.get("personVotes") == 0]
    if not zero:
        check.status = UNMEASURABLE
        check.detail = (
            f"{len(rows)} rows carried personConsensus and none had personVotes == 0, "
            "so the zero-voter branch did not execute. Not a pass: the case under "
            "test did not arise. Re-run when the board carries a mixed-signal asset "
            "(mixedPersonSignals > 0 with personVotes == 0)."
        )
        check.evidence = {"rowsWithPersonConsensus": len(rows)}
        return
    offenders = [
        {
            "assetId": asset_id,
            "personManagerQuality": person.get("personManagerQuality"),
            "mixedPersonSignals": person.get("mixedPersonSignals"),
        }
        for asset_id, person in zero
        if person.get("personManagerQuality") is not None
    ]
    check.denominator = len(zero)
    check.evidence = {
        "rowsWithPersonConsensus": len(rows),
        "zeroVoterRows": len(zero),
        "offenders": offenders[:20],
        "offenderCount": len(offenders),
    }
    if offenders:
        check.status = FAIL
        check.detail = (
            f"{len(offenders)} of {len(zero)} zero-voter rows published a non-null "
            "personManagerQuality. Pre-#927 this is 1.0 on every one of them."
        )
    else:
        check.status = PASS
        check.detail = f"all {len(zero)} zero-voter rows published personManagerQuality: null."


def check_measured_zero_quality(report: Report, payload: dict, source: str) -> None:
    """#927 check 2 — a measured 0.0 must stay 0.0.

    The repair must not overshoot.  UNKNOWN and WORST are different answers,
    and a cohort of voters all scored 0.0 HAS an answer: the floor.  A row
    with voters and a null quality would mean the fix swallowed a real
    measurement.
    """
    check = report.add(Check("C2", "V1-63", "a measured personManagerQuality of 0.0 stays 0.0"))
    rows = _person_rows(payload)
    voted = [(a, p) for a, p in rows if (p.get("personVotes") or 0) > 0]
    if not voted:
        check.status = BLOCKED if not rows else UNMEASURABLE
        check.detail = (
            f"{source} published no row with personVotes > 0, so no measured quality "
            "exists to check. Nothing proven either way."
        )
        check.evidence = {"rowsWithPersonConsensus": len(rows)}
        return
    nulled = [a for a, p in voted if p.get("personManagerQuality") is None]
    zeros = [a for a, p in voted if p.get("personManagerQuality") == 0]
    check.denominator = len(voted)
    check.evidence = {
        "rowsWithVoters": len(voted),
        "nulledDespiteVoters": nulled[:20],
        "nulledCount": len(nulled),
        "measuredZeroRows": len(zeros),
    }
    if nulled:
        check.status = FAIL
        check.detail = (
            f"{len(nulled)} rows have voters but published personManagerQuality: null. "
            "A measurement was discarded — the repair overshot into treating a real "
            "value as missing."
        )
        return
    check.status = PASS
    if zeros:
        check.detail = (
            f"every one of {len(voted)} rows with voters published a number, including "
            f"{len(zeros)} at exactly 0.0 — measured worst, not unknown."
        )
    else:
        check.detail = (
            f"every one of {len(voted)} rows with voters published a number. No row "
            "measured exactly 0.0 on this board, so the floor case is reported by the "
            "absence of nulls rather than by an example."
        )


def check_undefined_concentration(report: Report, payload: dict, source: str) -> None:
    """#927 check 3 — no weighted volume means the ratio does not exist.

    ``networkConcentration`` is a SHARE of weighted volume.  With no weighted
    volume there is no share for any network to hold, and ``0.0`` is the one
    value that reads as its exact opposite: "no single network dominates".
    """
    check = report.add(
        Check(
            "C3",
            "V1-63",
            "networkConcentration is null when weighted volume is zero",
        )
    )
    rows = _person_rows(payload)
    if not rows:
        check.status = BLOCKED
        check.detail = f"{source} published no personConsensus block on any row."
        return
    novol = [(a, p) for a, p in rows if not (float(p.get("weightedPersonVolume") or 0.0) > 0.0)]
    if not novol:
        check.status = UNMEASURABLE
        check.detail = (
            f"every one of {len(rows)} rows carried weighted volume > 0, so the "
            "undefined branch did not execute."
        )
        check.evidence = {"rowsWithPersonConsensus": len(rows)}
        return
    offenders = [
        {"assetId": a, "networkConcentration": p.get("networkConcentration")}
        for a, p in novol
        if p.get("networkConcentration") is not None
    ]
    check.denominator = len(novol)
    check.evidence = {
        "rowsWithPersonConsensus": len(rows),
        "zeroVolumeRows": len(novol),
        "offenders": offenders[:20],
        "offenderCount": len(offenders),
    }
    if offenders:
        check.status = FAIL
        check.detail = (
            f"{len(offenders)} of {len(novol)} zero-volume rows published a "
            "networkConcentration number for a ratio that does not exist."
        )
    else:
        check.status = PASS
        check.detail = f"all {len(novol)} zero-volume rows published null."


# ── #927 group B: TEP is a fact, not a label (V1-129) ──────────────
#
# On-box only.  These need the league's real Sleeper scoring card, which
# lives at ``data/leagues/scoring_<sleeperLeagueId>.json`` and is gitignored,
# so no repository and no HTTP client can answer them.


def _deployed_tep_rule() -> str:
    """Which rule the DEPLOYED code implements: ``card`` or ``label``.

    Read from the constructor's own signature rather than from behaviour, so
    the answer is unambiguous on a board where both rules would agree.
    """
    import inspect

    from src.trade.faab_comparability import TargetFormat

    params = inspect.signature(TargetFormat.from_roster_settings).parameters
    if "scoring_settings" in params:
        return "card"
    if "scoring_profile" in params:
        return "label"
    return "unknown"


def check_tep_is_card_derived(report: Report, league: str) -> dict[str, Any]:
    """#927 check 4 — target TEP comes from the actual card, not the label.

    Returns a context dict the later checks reuse, so the card is read once.
    """
    check = report.add(
        Check("C4", "V1-129", "target TEP is derived from the scoring card, not the profile label")
    )
    ctx: dict[str, Any] = {}
    try:
        from src.api import league_registry
        from src.league_intel.te_premium import measure_te_demand
        from src.trade.faab_comparability import TargetFormat
    except Exception as exc:  # pragma: no cover - deployment shape
        check.status = ERROR
        check.detail = f"could not import the comparability owner: {exc!r}"
        return ctx

    cfg = league_registry.get_league_by_key(league)
    if cfg is None:
        check.status = BLOCKED
        check.detail = f"league {league!r} is not in the deployed registry."
        return ctx

    rule = _deployed_tep_rule()
    evidence_state = league_registry.scoring_evidence_state(cfg)
    card = league_registry.scoring_settings_for_league(cfg)
    profile = str(getattr(cfg, "scoring_profile", "") or "")
    label_says_tep = "tep" in profile.lower()

    ctx = {
        "cfg": cfg,
        "card": card,
        "evidenceState": evidence_state,
        "profile": profile,
        "labelSaysTep": label_says_tep,
        "rule": rule,
    }

    # The factual answer, computed here from the card the deployed process
    # would read.  ``None`` when the card is absent — never False.
    card_says_tep: bool | None = None
    edges: dict[str, float] = {}
    if isinstance(card, dict) and card:
        demand = measure_te_demand(None, card)
        card_says_tep = demand.has_scoring_edge
        edges = dict(demand.scoring_edges)
    ctx["cardSaysTep"] = card_says_tep
    ctx["scoringEdges"] = edges

    try:
        target = TargetFormat.from_registry(league)
    except Exception as exc:
        check.status = ERROR
        check.detail = f"TargetFormat.from_registry({league!r}) raised: {exc!r}"
        return ctx
    ctx["target"] = target

    check.evidence = {
        "deployedRule": rule,
        "scoringProfileLabel": profile,
        "labelSaysTep": label_says_tep,
        "scoringEvidenceState": evidence_state,
        "cardPresent": bool(card),
        "scoringEdges": edges,
        "cardSaysTep": card_says_tep,
        "servedTep": target.tep,
        "servedIs2te": target.is_2te,
    }

    if rule == "label":
        check.status = FAIL
        check.detail = (
            "the deployed build derives TEP from the scoring-profile LABEL "
            f"({profile!r} -> {label_says_tep}). MASTER_PRODUCT_PLAN 4.10 forbids a "
            "label deciding a factual question. This is the pre-#927 build."
        )
        return ctx
    if rule != "card":
        check.status = ERROR
        check.detail = "could not determine which TEP rule the deployed build implements."
        return ctx
    if evidence_state != "fresh":
        check.status = UNMEASURABLE
        check.detail = (
            f"the deployed build reads the card (rule={rule}), but this league's "
            f"scoring evidence is {evidence_state!r}, so no card-derived value was "
            "produced to compare. C5 is the check that covers this state."
        )
        return ctx
    if not isinstance(card, dict) or not card:
        # FRESH EVIDENCE IS NOT THE SAME AS A READABLE CARD, and conflating
        # them was a false green found in adversarial review.
        # ``scoring_evidence_state`` decides freshness from the snapshot's
        # fetch timestamp and season -- it never reads ``scoringSettings`` --
        # so a snapshot written by a partial fetch is ``fresh`` while carrying
        # no card at all.  In that state ``_tep_from_scoring`` correctly
        # returns ``None`` (fail-closed, so the PRODUCT is fine), and the
        # served value then equalled the derived value trivially: both
        # ``None``.  This check reported PASS with the detail "derived from
        # the fresh card" having observed no card.
        #
        # BLOCKED rather than FAIL because nothing is broken -- the evidence
        # is absent.  C6 already handled this case; C4 did not, which is what
        # marks it an oversight rather than a decision.
        check.status = BLOCKED
        check.detail = (
            f"scoring evidence is {evidence_state!r} but the snapshot carries no "
            "scoringSettings, so there is no card to derive from and nothing to "
            "compare against. Refetch with scripts/fetch_league_scoring.py; do not "
            "read this as the rule being verified."
        )
        return ctx
    if target.tep != card_says_tep:
        check.status = FAIL
        check.detail = (
            f"served tep={target.tep!r} but the league's own fresh card measures "
            f"{card_says_tep!r} (edges {edges}). The served value did not come from "
            "the card."
        )
        return ctx
    check.status = PASS
    agreement = "agrees with" if bool(card_says_tep) == label_says_tep else "DISAGREES with"
    check.detail = (
        f"served tep={target.tep!r}, derived from the fresh card (edges {edges}); it "
        f"{agreement} the {profile!r} label."
    )
    return ctx


def check_unproven_scoring_fails_closed(report: Report, ctx: dict[str, Any]) -> None:
    """#927 check 5 — stale/missing scoring evidence means UNKNOWN and excludes.

    A card proves when it was taken, not that it is still true.  Only
    ``fresh`` authorises the claim; and UNKNOWN must not quietly become "no
    TE premium", which would admit a whole population of offense-scoring
    leagues as comparable.
    """
    check = report.add(
        Check(
            "C5", "V1-129", "stale or missing scoring evidence leaves TEP UNKNOWN and fails closed"
        )
    )
    if "target" not in ctx:
        check.status = BLOCKED
        check.detail = "C4 could not resolve a target, so there is nothing to check."
        return
    state = ctx["evidenceState"]
    target = ctx["target"]
    try:
        from src.trade.faab_comparability import unprovable_target_fields
    except ImportError:
        check.status = FAIL
        check.detail = (
            "the deployed build has no unprovable_target_fields owner, so an "
            "unprovable target cannot be reported. This is the pre-#927 build."
        )
        return

    unprovable = list(unprovable_target_fields(target))
    check.evidence = {
        "scoringEvidenceState": state,
        "servedTep": target.tep,
        "unprovableTargetFields": unprovable,
    }
    if state == "fresh":
        if target.tep is None:
            check.status = FAIL
            check.detail = "evidence is fresh but TEP resolved to None."
            return
        check.status = UNMEASURABLE
        check.detail = (
            "this league's scoring evidence is fresh, so the unproven branch did not "
            "execute. Not a pass — to exercise it, run against a league whose card is "
            "stale or absent. Do NOT age or delete a card to manufacture the case."
        )
        return
    if target.tep is not None:
        check.status = FAIL
        check.detail = (
            f"scoring evidence is {state!r} but TEP resolved to {target.tep!r}. Unproven "
            "scoring became a positive claim."
        )
        return
    if "tep" not in unprovable:
        check.status = FAIL
        check.detail = (
            "TEP is None but the comparability owner does not report it as unprovable, "
            "so every external row would be judged against an unstated setting."
        )
        return
    check.status = PASS
    check.detail = (
        f"scoring evidence is {state!r}, TEP is None (UNKNOWN, not 'no premium'), and "
        f"the target reports unprovable fields {unprovable} so classification "
        "hard-excludes rather than assuming a match."
    )


def check_dynasty_main_is_not_te_premium(report: Report, ctx: dict[str, Any], league: str) -> None:
    """#927 check 6 — the specific measured claim about this league's card.

    `dynasty_main` carries a `superflex_tep15_ppr1` label while its 2026 card
    grants tight ends nothing over WRs.  This check asserts the CARD, and
    reports what the served value does with it.  It is deliberately specific:
    a generic "the rule is card-derived" check passes on a build that reads
    the card and still gets this league wrong.
    """
    check = report.add(
        Check("C6", "V1-129", f"{league} behaves as non-TE-premium under its actual card")
    )
    card = ctx.get("card")
    if not isinstance(card, dict) or not card:
        check.status = BLOCKED
        check.detail = (
            f"no scoring card on disk for {league} "
            "(data/leagues/scoring_<sleeperLeagueId>.json). Run "
            "scripts/fetch_league_scoring.py on the box first — do not synthesise one."
        )
        return
    edges = ctx.get("scoringEdges") or {}
    card_says_tep = ctx.get("cardSaysTep")
    served = ctx.get("target").tep if ctx.get("target") is not None else None
    check.evidence = {
        "bonus_rec_te": card.get("bonus_rec_te"),
        "bonus_rec_wr": card.get("bonus_rec_wr"),
        "bonus_fd_te": card.get("bonus_fd_te"),
        "bonus_fd_wr": card.get("bonus_fd_wr"),
        "scoringEdges": edges,
        "cardSaysTep": card_says_tep,
        "servedTep": served,
        "scoringProfileLabel": ctx.get("profile"),
        "scoringEvidenceState": ctx.get("evidenceState"),
    }
    if card_says_tep is True:
        check.status = UNMEASURABLE
        check.detail = (
            f"this league's current card DOES advantage TE ({edges}), so the "
            "non-premium claim does not describe it today. That is a real finding, not "
            "a failure — the commissioner may have restored the premium. What matters "
            "is that the served value follows the card, which is C4."
        )
        return
    if ctx.get("evidenceState") != "fresh":
        check.status = BLOCKED
        check.detail = (
            f"the card measures no TE edge ({edges}) but its evidence state is "
            f"{ctx.get('evidenceState')!r}, so it may not authorise a served value. "
            "Refresh it before reading this as the league's behaviour."
        )
        return
    if served is not False:
        check.status = FAIL
        check.detail = (
            f"the fresh card grants TE no edge ({edges}) but the served tep is "
            f"{served!r}. The label is still deciding."
        )
        return
    check.status = PASS
    check.detail = (
        f"the fresh card grants TE no edge over WR/RB ({edges}) and the served tep is "
        f"False, against a {ctx.get('profile')!r} label that says otherwise."
    )


# ── #927 group C: what the population change actually did (V1-129) ──


def check_comparable_population_before_after(
    report: Report, ctx: dict[str, Any], league: str
) -> None:
    """#927 check 7 — before/after comparable crowd population.

    A counterfactual over REAL stored rows, not a simulation: the accumulated
    ledger is classified twice, once against the served (card-derived) target
    and once against the same target with TEP forced to what the retired
    LABEL rule would have said.  Nothing is invented; the only thing that
    varies is the policy.
    """
    check = report.add(
        Check("C7", "V1-129", "comparable crowd population, card-derived vs the retired label rule")
    )
    if "target" not in ctx:
        check.status = BLOCKED
        check.detail = "C4 could not resolve a target."
        return
    try:
        import dataclasses

        from src.trade import faab_comparability as FC
        from src.trade.faab_history import build_crowd_market, load_crowd_history
    except Exception as exc:  # pragma: no cover - deployment shape
        check.status = ERROR
        check.detail = f"could not import the crowd market: {exc!r}"
        return

    payload = load_crowd_history(league)
    rows = (payload or {}).get("rows") if isinstance(payload, dict) else None
    if not rows:
        check.status = BLOCKED
        check.detail = (
            f"no crowd ledger for {league} at data/faab/crowd_history_{league}.json. "
            "It is gitignored and prod-only. Run the dynasty-crowd-faab timer (or "
            "scripts/fetch_crowd_faab.py) and re-check — do not synthesise rows."
        )
        return

    served = ctx["target"]
    label_tep = bool(ctx.get("labelSaysTep"))
    counterfactual = dataclasses.replace(served, tep=label_tep)

    try:
        from src.trade.faab_engine import FaabConfig

        policy = FC.ComparabilityPolicy.from_config(FaabConfig())
    except Exception:
        policy = FC.ComparabilityPolicy()

    after = build_crowd_market(payload, target=served, policy=policy)
    before = build_crowd_market(payload, target=counterfactual, policy=policy)

    check.evidence = {
        "rowsTotal": after.rows_total,
        "servedTep": served.tep,
        "retiredLabelRuleTep": label_tep,
        "after": {
            "rowsUsed": after.rows_used,
            "state": after.state,
            "tierCounts": dict(after.tier_counts),
            "excludedCounts": dict(after.excluded_counts),
        },
        "before": {
            "rowsUsed": before.rows_used,
            "state": before.state,
            "tierCounts": dict(before.tier_counts),
            "excludedCounts": dict(before.excluded_counts),
        },
    }
    if served.tep is None:
        check.status = UNMEASURABLE
        check.detail = (
            "the served target cannot prove TEP, so it admits nothing and there is no "
            "meaningful 'after' population to compare. Fix the scoring card first "
            "(C5/C6), then re-run."
        )
        return
    check.status = PASS
    if bool(served.tep) == label_tep:
        check.detail = (
            f"card and label agree ({served.tep!r}), so the admitted population is "
            f"unchanged at {after.rows_used}/{after.rows_total} rows. The measurement "
            "still ran; it simply found no divergence for this league today."
        )
    else:
        check.detail = (
            f"card ({served.tep!r}) and label ({label_tep!r}) DISAGREE: the retired rule "
            f"admitted {before.rows_used}/{before.rows_total} rows, the card-derived "
            f"rule admits {after.rows_used}. Every row in the difference was being "
            "compared on a TE premium this league does not grant."
        )


def check_crowd_refusal_reasons(report: Report, faab_payload: dict, source: str) -> None:
    """#927 check 8 — the refusal is specific, and names the right side.

    "We hold no crowd evidence" and "we cannot describe our own league well
    enough to judge any" are different failures with different fixes.
    Reporting them identically sends the reader to the feed when the answer
    is in the registry or in a scoring card nobody fetched.
    """
    check = report.add(
        Check("C8", "V1-129", "crowd-market refusal reasons are specific and honest")
    )
    block = faab_payload.get("crowdMarket")
    if not isinstance(block, dict):
        check.status = FAIL
        check.detail = (
            f"{source} published no crowdMarket block at all. A missing block and a "
            "reported refusal read the same to a consumer, which is the defect."
        )
        return
    state = block.get("state")
    reason = block.get("refusalReason")
    unknown = block.get("targetFormatUnknown")
    check.evidence = {
        "state": state,
        "refusalReason": reason,
        "targetFormatUnknown": unknown,
        "rowsTotal": block.get("rowsTotal"),
        "rowsUsed": block.get("rowsUsed"),
        "excludedCounts": block.get("excludedCounts"),
        "tierCounts": block.get("tierCounts"),
        "playerHasEvidence": block.get("playerHasEvidence"),
        "pricesIdp": block.get("pricesIdp"),
    }
    if unknown is None:
        check.status = FAIL
        check.detail = (
            "crowdMarket carries no targetFormatUnknown key, so a run that admitted "
            "nothing because OUR league is undescribable is indistinguishable from an "
            "absent feed. This is the pre-#927 build."
        )
        return
    if unknown:
        if reason != "target_format_unverifiable:" + ",".join(unknown):
            check.status = FAIL
            check.detail = (
                f"targetFormatUnknown is {unknown} but refusalReason is {reason!r}. The "
                "refusal must name our side, ahead of the freshness checks — freshness "
                "is moot when no row is admissible."
            )
            return
        check.status = PASS
        check.detail = (
            f"the target cannot prove {unknown} and the refusal says exactly that "
            f"({reason!r}) rather than blaming the feed."
        )
        return
    if state == "fresh" and reason is None:
        check.status = PASS
        check.detail = "target fully described, ledger fresh, no refusal — the usable state."
        return
    if state in {"stale", "missing"} and reason in {"crowd_ledger_stale", "no_crowd_ledger"}:
        check.status = PASS
        check.detail = (
            f"target fully described; the ledger itself is {state!r} and the refusal "
            f"({reason!r}) correctly points at the feed."
        )
        return
    check.status = FAIL
    check.detail = f"state {state!r} and refusalReason {reason!r} do not correspond."


def check_faab_recommendation_effect(report: Report, faab_payload: dict, source: str) -> None:
    """#927 check 9 — a refused population must not still move the bid.

    The crowd feeds ``rival_bid_cdf`` at weight 0.6, so what it admits moves
    real recommended bids.  This asserts the two directions that matter:
    when the crowd is USED it must be visible as a factor, and when it is
    REFUSED it must not appear at all.  A refusal that still quietly
    contributes would be cosmetic.

    The absolute numbers are recorded so two runs of this script — one before
    a deploy and one after — measure the effect directly.
    """
    check = report.add(
        Check("C9", "V1-129", "the crowd moves the bid only when it was actually admitted")
    )
    block = faab_payload.get("crowdMarket")
    if not isinstance(block, dict):
        check.status = BLOCKED
        check.detail = f"{source} published no crowdMarket block; C8 covers that."
        return
    factors = faab_payload.get("factors")
    factors = factors if isinstance(factors, list) else []
    # Matched on the LABEL, which is the engine's stable identifier for this
    # row (``_FactorRow("Cross-league market", ...)``), not on its prose --
    # a check that breaks when the wording is improved is a bad check.
    crowd_factors = [
        f for f in factors if isinstance(f, dict) and f.get("label") == "Cross-league market"
    ]
    used = bool(block.get("playerHasEvidence")) and block.get("state") == "fresh"
    contention = faab_payload.get("contention") or {}
    check.evidence = {
        "crowdState": block.get("state"),
        "playerHasEvidence": block.get("playerHasEvidence"),
        "refusalReason": block.get("refusalReason"),
        "rowsUsed": block.get("rowsUsed"),
        "crowdFactorRows": len(crowd_factors),
        "standard": faab_payload.get("standard"),
        "conservative": faab_payload.get("conservative"),
        "aggressive": faab_payload.get("aggressive"),
        "max": faab_payload.get("max"),
        "clearing": contention.get("clearing") if isinstance(contention, dict) else None,
        "contentionSkipped": contention.get("skipped") if isinstance(contention, dict) else None,
    }
    if used and not crowd_factors:
        check.status = FAIL
        check.detail = (
            "the crowd market is fresh and prices this player, but no crowd factor row "
            "was published — the evidence moved the bid invisibly, or was dropped."
        )
        return
    if not used and crowd_factors:
        check.status = FAIL
        check.detail = (
            f"the crowd was refused ({block.get('refusalReason')!r}) yet a crowd factor "
            "row is still present. The refusal is cosmetic."
        )
        return
    check.status = PASS
    if used:
        check.detail = (
            f"the crowd priced this player and is visible as {len(crowd_factors)} factor "
            f"row(s); standard={faab_payload.get('standard')}, "
            f"clearing={check.evidence['clearing']}. Record these and compare across "
            "deploys to measure the population change's effect."
        )
    else:
        check.detail = (
            f"the crowd was refused ({block.get('refusalReason')!r}) and contributed no "
            f"factor row. standard={faab_payload.get('standard')} is therefore free of "
            "external-market influence, which is the point of the refusal."
        )


# ── Lane 4 V1 rows beyond #927 ─────────────────────────────────────


def check_faab_history_timer(report: Report) -> None:
    """V1-57 (L3) — the collection is SCHEDULED, not a manual step.

    A green manual run of ``scripts/fetch_faab_history.py`` proves the script
    works, which was never the open question.  What L3 needs is the unit
    installed and firing.
    """
    check = report.add(Check("V57", "V1-57", "dynasty-faab-history timer is installed and firing"))
    try:
        listed = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        check.status = BLOCKED
        check.detail = f"systemctl is not available here ({exc!r}); run this on the box."
        return
    if listed.returncode != 0:
        check.status = BLOCKED
        check.detail = f"systemctl exited {listed.returncode}: {listed.stderr.strip()[:200]}"
        return
    lines = [ln for ln in listed.stdout.splitlines() if "faab-history" in ln]
    check.evidence = {"timerLines": lines}
    if not lines:
        check.status = FAIL
        check.detail = (
            "no faab-history timer is installed. The templates exist in the repo "
            "(deploy/systemd/dynasty-faab-history.{service,timer}.template) but "
            "install-systemd-service.sh has not run with them on this host."
        )
        return
    # NEXT/LEFT/LAST/PASSED/UNIT/ACTIVATES -- LAST is populated only once fired.
    fired = any(" n/a " not in ln.replace("\t", " ") for ln in lines)
    check.status = PASS if fired else FAIL
    check.detail = (
        "timer installed and has fired at least once."
        if fired
        else "timer is installed but has never fired (LAST is n/a)."
    )


def check_faab_history_artifact(report: Report, league: str) -> None:
    """V1-57, second half — the run produced the artifact the engine reads."""
    check = report.add(Check("V57b", "V1-57", "own-league bid history exists and is recent"))
    path = _repo_file("data", "faab", f"bid_history_{league}.json")
    if not path.exists():
        check.status = FAIL if _repo_file("data", "faab").exists() else BLOCKED
        check.detail = (
            f"{path} is absent. With data/faab/ present this is a real failure (the "
            "timer ran and produced nothing); without it, this is not the deployed "
            "working directory."
        )
        return
    age_h = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0
    payload = _load_json(path)
    entries = payload.get("bids") if isinstance(payload, dict) else None
    check.evidence = {
        "path": str(path),
        "ageHours": round(age_h, 2),
        "entryCount": len(entries) if isinstance(entries, list) else None,
    }
    if age_h > 25.0:
        check.status = FAIL
        check.detail = f"history is {age_h:.1f}h old against a daily timer."
        return
    check.status = PASS
    check.detail = f"history written {age_h:.1f}h ago."


def check_ffpc_lane_is_honest(report: Report) -> None:
    """V1-60 (L2) — zero rosters must never be silently zero.

    "The lane ran and found nothing" and "the lane did not run" are different
    facts.  ``cohortCoveragePct`` is the one that must be ``None`` rather than
    ``0`` when nothing was observed.
    """
    check = report.add(
        Check("V60", "V1-60", "the FFPC roster lane is real or honestly unavailable")
    )
    try:
        from src.sharp.roster_collect import CollectResult
    except Exception as exc:  # pragma: no cover - deployment shape
        check.status = ERROR
        check.detail = f"could not import roster_collect: {exc!r}"
        return
    has_status = hasattr(CollectResult, "unavailable") and "status" in getattr(
        CollectResult, "__dataclass_fields__", {}
    )
    check.evidence = {"collectResultCarriesStatus": has_status}
    if not has_status:
        check.status = FAIL
        check.detail = (
            "CollectResult has no status/unavailable() constructor, so a skipped lane "
            "and an empty-but-successful lane are indistinguishable."
        )
        return
    try:
        from src.sharp import roster_percentage

        payload = roster_percentage.build_board()
    except Exception as exc:
        check.status = BLOCKED
        check.detail = f"could not build the roster-percentage board here: {exc!r}"
        return
    # FIELD PATHS VERIFIED AGAINST THE PRODUCER, not remembered.  The
    # roster-percentage board puts the population counts under
    # ``transparency`` and only ``selectedManagers`` under ``cohort``; an
    # earlier draft of this check read ``cohort.cohortCoveragePct``, which is
    # always absent and would have reported BLOCKED for the wrong reason on a
    # perfectly healthy board.
    payload = payload if isinstance(payload, dict) else {}
    transparency = payload.get("transparency")
    transparency = transparency if isinstance(transparency, dict) else {}
    cohort = payload.get("cohort")
    cohort = cohort if isinstance(cohort, dict) else {}
    if "cohortCoveragePct" not in transparency:
        check.status = FAIL
        check.detail = (
            "the roster-percentage payload has no transparency.cohortCoveragePct. "
            "Either the producer renamed it -- in which case every consumer reading "
            "coverage is now reading nothing -- or this check is pointed at the wrong "
            "field. Both are failures; neither is a pass."
        )
        return
    coverage = transparency.get("cohortCoveragePct")
    check.evidence.update(
        {
            "cohortManagers": transparency.get("cohortManagers"),
            "cohortManagersRepresented": transparency.get("cohortManagersRepresented"),
            "cohortCoveragePct": coverage,
            "eligibleRosters": transparency.get("eligibleRosters"),
            "ffpcRosters": transparency.get("ffpcRosters"),
            "sleeperRosters": transparency.get("sleeperRosters"),
            "selectedManagers": cohort.get("selectedManagers"),
            "boardStatus": payload.get("status"),
        }
    )
    if not transparency.get("cohortManagers"):
        if coverage is not None:
            check.status = FAIL
            check.detail = (
                f"no cohort managers, yet cohortCoveragePct is {coverage!r}. An "
                "unmeasured coverage must be null, never a number."
            )
            return
        check.status = BLOCKED
        check.detail = (
            "the cohort is empty here, so the lane's populated behaviour cannot be "
            "measured. It correctly reports cohortCoveragePct: null rather than 0 — "
            "which is the honest-degraded half of the row, but not the whole row. "
            "V1-58 is the blocker."
        )
        return
    check.status = PASS
    check.denominator = int(transparency.get("cohortManagers") or 0)
    check.detail = (
        f"cohort of {transparency.get('cohortManagers')} managers, "
        f"{transparency.get('eligibleRosters')} eligible rosters "
        f"({transparency.get('ffpcRosters')} FFPC), coverage {coverage!r}."
    )


def check_single_cohort_owner(report: Report) -> None:
    """V1-65 (L2) — one definition of who is a sharp, structurally.

    Deterministic and runnable anywhere, so it is recorded here rather than
    deferred to production: a second cohort definition is the way this row
    regresses.
    """
    check = report.add(Check("V65", "V1-65", "cohort_members has exactly one definition"))
    hits: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("def cohort_members"):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    check.evidence = {"definitions": hits}
    if len(hits) == 1 and hits[0].startswith("src/sharp/cohort.py"):
        check.status = PASS
        check.detail = f"single owner at {hits[0]}; every surface re-exports it."
    else:
        check.status = FAIL
        check.detail = f"expected one definition in src/sharp/cohort.py, found {hits}."


def check_league_population_difference(report: Report, *, ledger_path: Path | None = None) -> None:
    """V1-65 (L2) — the two admitted league populations, from the deployed ledger.

    The row's L2 needs the CENSUS, not just the single-owner property that
    ``check_single_cohort_owner`` pins: how many discovered leagues the
    Insider (signal) gate admits, how many the strictly-narrower Sharp gate
    admits, and an explicit accounting of the difference.  All of it is read
    from the intel ledger through the existing read-only primitives
    (``discovery.signal_eligible_league_ids`` / ``sharp_eligible_league_ids``
    / ``graph_stats``); nothing is re-decided here.

    The one thing this check ASSERTS rather than reports: sharp is defined as
    strictly narrower than signal (dynasty-only, no keeper, >= 2 seasons —
    ``src/intel/league_filter.py``), so a sharp-admitted league outside the
    signal set means the two gates disagreed about the same stored evidence.

    The signal-but-not-sharp difference is EXPLAINED, not just counted: each
    league's stored ``settings_json`` evidence (type / bestBall / ageSeasons)
    is re-run through the canonical ``league_filter.sharp_exclusion_reason``
    ladder — never a second rule — and the reasons are published as a
    histogram.
    """
    check = report.add(
        Check(
            "V65b",
            "V1-65",
            "signal- vs sharp-admitted league populations, censused from the deployed ledger",
        )
    )
    try:
        from src.intel import league_filter
        from src.intel import ledger as intel_ledger
        from src.sharp import discovery
    except Exception as exc:  # pragma: no cover - deployment shape
        check.status = ERROR
        check.detail = f"could not import the discovery/ledger owners: {exc!r}"
        return

    path = Path(ledger_path) if ledger_path else intel_ledger.default_path()
    if not path.exists():
        # ``ledger.connect`` CREATES an absent file (schema write), and this
        # script is read-only — so presence is decided before any connect.
        check.status = BLOCKED
        check.detail = (
            f"no intel ledger at {path}, so there is no discovered-league store to "
            "census. This is the sandbox/undeployed state — the ledger is gitignored "
            "and prod-only. Run on the box; do not synthesise leagues."
        )
        check.evidence = {"ledgerPresent": False, "ledgerPath": str(path)}
        return

    conn = intel_ledger.connect(path)
    try:
        league_rows = conn.execute("SELECT league_id, settings_json FROM leagues").fetchall()
        ms_sharp_complete = conn.execute(
            "SELECT COUNT(DISTINCT league_id) AS n FROM manager_seasons "
            "WHERE sharp_eligible=1 AND is_complete=1"
        ).fetchone()["n"]
    finally:
        conn.close()

    if not league_rows:
        check.status = UNMEASURABLE
        check.detail = (
            "ledger carries no discovered leagues here — an environment artifact "
            "(the discovery crawl runs only on the deployed box), not a statement "
            "about the production graph. Empty-here is not evidence of anything."
        )
        check.evidence = {"ledgerPresent": True, "observedLeagues": 0}
        return

    signal = set(discovery.signal_eligible_league_ids(ledger_path=path))
    sharp = set(discovery.sharp_eligible_league_ids(ledger_path=path))
    stats = discovery.graph_stats(ledger_path=path)
    sharp_only = sorted(sharp - signal)
    signal_only = sorted(signal - sharp)

    stored = {str(r["league_id"]): r["settings_json"] for r in league_rows}
    histogram: dict[str, int] = {}
    for lid in signal_only:
        try:
            settings = json.loads(stored.get(lid) or "{}")
        except (TypeError, ValueError):
            settings = None
        if not isinstance(settings, dict):
            histogram["unparseable_settings"] = histogram.get("unparseable_settings", 0) + 1
            continue
        age_recorded = "ageSeasons" in settings
        # Faithful inverse of what discovery stored, not a guess:
        # ``league_age_seasons`` answers 2 iff ``previous_league_id`` was
        # truthy at crawl time, and ``ageSeasons`` recorded exactly that.
        reconstructed = {
            "settings": {"type": settings.get("type"), "best_ball": settings.get("bestBall")},
            "previous_league_id": (
                "recorded-chain" if (settings.get("ageSeasons") or 0) >= 2 else ""
            ),
        }
        reason = league_filter.sharp_exclusion_reason(reconstructed)
        if reason == "too_new" and not age_recorded:
            # An unrecorded age is UNKNOWN, and unknown must not read as a
            # measured "too new" — missing is never a value.
            reason = "age_unrecorded"
        if reason is None:
            # Re-derivation admits a league the stored sharpEligible flag
            # refused. Publish the drift; coerce neither side.
            reason = "stored_flag_disagrees_with_rederivation"
        histogram[reason] = histogram.get(reason, 0) + 1

    check.denominator = len(league_rows)
    check.evidence = {
        "ledgerPresent": True,
        "observedLeagues": len(league_rows),
        "signalAdmitted": len(signal),
        "sharpAdmitted": len(sharp),
        "signalOnlyCount": len(signal_only),
        "signalOnlySample": signal_only[:10],
        "sharpOnlyCount": len(sharp_only),
        "sharpOnlySample": sharp_only[:10],
        "sharpExclusionReasons": histogram,
        # Cross-check from an independent table: leagues whose crawled
        # season RECORDS are marked sharp-eligible and complete. Reported,
        # not asserted against the discovery flags — the records crawl
        # legitimately lags discovery.
        "managerSeasonsSharpCompleteLeagues": ms_sharp_complete,
        "graphStats": {
            key: stats.get(key) for key in ("observedUsers", "memberships", "discoveryOnlyLeagues")
        },
    }
    if sharp_only:
        check.status = FAIL
        check.detail = (
            f"{len(sharp_only)} league(s) are sharp-admitted but NOT signal-admitted "
            f"(sample {sharp_only[:10]}). Sharp is defined as strictly narrower than "
            "signal (dynasty-only, >= 2 seasons), so this set must be empty — a member "
            "here means the two gates disagree about the same stored evidence."
        )
        return
    check.status = PASS
    check.detail = (
        f"signal admits {len(signal)} of {len(league_rows)} discovered leagues, sharp "
        f"admits {len(sharp)}; the {len(signal_only)}-league difference is explained by "
        f"{histogram}. manager_seasons cross-check: {ms_sharp_complete} distinct "
        "league(s) carry sharp-eligible complete season records."
    )


def record_blocked_rows(report: Report, unauth_detail: str | None) -> None:
    """V1-58 / V1-59 — recorded as BLOCKED, with the credential named.

    Never closed by standing up a synthetic cohort: a manufactured population
    would verify the manufacture.
    """
    for row, title in (
        ("V1-58", "Sharp cohort proven populated in production"),
        ("V1-59", "Sharp bootstrap stops failing"),
    ):
        check = report.add(Check(f"B{row[-2:]}", row, title))
        check.status = UNVERIFIABLE if unauth_detail else BLOCKED
        check.detail = (
            (
                f"{unauth_detail} — /api/sharp/* is session-gated and correctly so. "
                "Insufficient evidence, deliberately neither pass nor fail. The single "
                "credential that unblocks both is an authenticated admin session for "
                "the deployed origin, held by the site owner."
            )
            if unauth_detail
            else (
                "needs the deployed host: an authenticated /api/sharp/cohort read "
                "(V1-58) and a clean journalctl run of dynasty-sharp-discovery -> "
                "-records -> -rosters (V1-59). Not closable from a repository, and not "
                "to be closed by manufacturing a cohort."
            )
        )


# ── Modes ──────────────────────────────────────────────────────────


def run_remote(report: Report, args: argparse.Namespace) -> None:
    """Everything the deployed API publishes, over HTTPS, with a real session."""
    origin = args.origin.rstrip("/")
    cookie = os.environ.get("RISKIT_SESSION_COOKIE") or None

    # /api/status is public, so the deployed SHA is always recordable even
    # when every gated check comes back unauthenticated.  An L3 result is
    # meaningless without knowing which commit produced it.
    # THE DEPLOYED SHA IS NOT OBSERVABLE OVER HTTP, and pretending otherwise
    # was a real defect in the first draft of this package.  ``/api/status``
    # publishes no ``commit``, no ``startedAt`` and no build identifier of any
    # kind -- its ``contract.version`` is the API DATA-CONTRACT version
    # (e.g. "2026-03-10.v2"), which identifies the payload shape and not the
    # commit that produced it.  Verified against the producer, not assumed.
    #
    # The contract's L3 definition says "executed against the deployed SHA",
    # so this is recorded as a NAMED GAP rather than papered over with a
    # field that happens to exist.  Only --mode onbox can answer it, via
    # ``git rev-parse HEAD`` in the deployed working directory.
    try:
        _, status_payload = _http(f"{origin}/api/status", cookie=cookie)
        status_payload = status_payload if isinstance(status_payload, dict) else {}
        contract = status_payload.get("contract")
        contract = contract if isinstance(contract, dict) else {}
        runtime = status_payload.get("data_runtime")
        runtime = runtime if isinstance(runtime, dict) else {}
        report.deployed = {
            "origin": origin,
            "headSha": None,
            "headShaSource": "unavailable_over_http",
            "contractVersion": contract.get("version"),
            "contractHealthy": (contract.get("health") or {}).get("ok")
            if isinstance(contract.get("health"), dict)
            else None,
            "lastDataRefreshAt": runtime.get("last_data_refresh_at"),
            "lastPayloadLoadedAt": runtime.get("last_payload_loaded_at"),
        }
    except Exception as exc:
        report.deployed = {"origin": origin, "error": repr(exc)}

    check_required_routes_exist(report)

    unauth: str | None = None

    # --- Sharp person consensus (C1-C3) ---
    market: dict | None = None
    try:
        code, market = _http(f"{origin}/api/sharp/market?window=30d&limit=250", cookie=cookie)
        if code != 200:
            market = None
    except Unauthenticated as exc:
        unauth = str(exc)
    except Exception as exc:
        report.add(
            Check("C1", "V1-63", "zero-voter personManagerQuality", ERROR, f"market fetch: {exc!r}")
        )
        market = None

    if market is not None:
        source = f"{origin}/api/sharp/market"
        check_zero_voter_quality(report, market, source)
        check_measured_zero_quality(report, market, source)
        check_undefined_concentration(report, market, source)
    elif unauth:
        for cid, title in (
            ("C1", "zero-voter personManagerQuality is JSON null, never 1.0"),
            ("C2", "a measured personManagerQuality of 0.0 stays 0.0"),
            ("C3", "networkConcentration is null when weighted volume is zero"),
        ):
            report.add(
                Check(
                    cid,
                    "V1-63",
                    title,
                    UNVERIFIABLE,
                    f"{unauth} — no session was supplied, so nothing was measured. "
                    "Set RISKIT_SESSION_COOKIE to an authenticated session; do not "
                    "relax the endpoint's gate.",
                )
            )

    # --- TEP + crowd, as the API reports them (C4-C9, partially) ---
    for cid, row, title in (
        ("C4", "V1-129", "target TEP is derived from the scoring card, not the profile label"),
        ("C5", "V1-129", "stale or missing scoring evidence leaves TEP UNKNOWN and fails closed"),
        ("C6", "V1-129", f"{args.league} behaves as non-TE-premium under its actual card"),
        ("C7", "V1-129", "comparable crowd population, card-derived vs the retired label rule"),
    ):
        report.add(
            Check(
                cid,
                row,
                title,
                BLOCKED,
                "needs the league's scoring card and/or the crowd ledger, both "
                "gitignored and prod-local. Run --mode onbox on the deployed host. "
                "C8 below is the API-visible shadow of C4/C5.",
            )
        )

    if not args.add_player:
        for cid, row, title in (
            ("C8", "V1-129", "crowd-market refusal reasons are specific and honest"),
            ("C9", "V1-129", "the crowd moves the bid only when it was actually admitted"),
        ):
            report.add(
                Check(
                    cid,
                    row,
                    title,
                    BLOCKED,
                    "needs --add-player naming a REAL free agent on the deployed board. "
                    "No player is invented for this check.",
                )
            )
        return

    try:
        code, faab = _http(
            f"{origin}/api/waiver/faab-recommend",
            cookie=cookie,
            body={"leagueKey": args.league, "addPlayerName": args.add_player},
        )
    except Unauthenticated as exc:
        for cid, row, title in (
            ("C8", "V1-129", "crowd-market refusal reasons are specific and honest"),
            ("C9", "V1-129", "the crowd moves the bid only when it was actually admitted"),
        ):
            report.add(Check(cid, row, title, UNVERIFIABLE, f"{exc} — no session supplied."))
        return
    except Exception as exc:
        report.add(Check("C8", "V1-129", "crowd-market refusal reasons", ERROR, repr(exc)))
        return

    if code != 200:
        for cid, row, title in (
            ("C8", "V1-129", "crowd-market refusal reasons are specific and honest"),
            ("C9", "V1-129", "the crowd moves the bid only when it was actually admitted"),
        ):
            report.add(Check(cid, row, title, BLOCKED, f"faab-recommend returned {code}: {faab}"))
        return

    source = f"{origin}/api/waiver/faab-recommend"
    check_crowd_refusal_reasons(report, faab, source)
    check_faab_recommendation_effect(report, faab, source)

    record_blocked_rows(report, unauth)


def run_onbox(report: Report, args: argparse.Namespace) -> None:
    """Everything that needs the deployed filesystem and the deployed source."""
    report.deployed = {
        "workingDirectory": str(REPO_ROOT),
        "headSha": _git_head(),
        "dataDirPresent": _repo_file("data").is_dir(),
    }

    # --- Do the routes and fields this package names actually exist? ---
    check_required_routes_exist(report)

    # --- Sharp person consensus, built locally from the real ledger ---
    try:
        from src.sharp import market as sharp_market

        payload = sharp_market.market_payload(window="30d", limit=250)
    except Exception as exc:
        payload = None
        report.add(
            Check("C1", "V1-63", "zero-voter personManagerQuality", ERROR, f"market build: {exc!r}")
        )
    if payload is not None:
        source = "market_payload(window='30d')"
        check_zero_voter_quality(report, payload, source)
        check_measured_zero_quality(report, payload, source)
        check_undefined_concentration(report, payload, source)

    try:
        from src.sharp import roster_percentage as _rp

        rp_payload = _rp.build_board()
    except Exception:
        rp_payload = None

    # --- TEP, the crowd population, and their effect ---
    ctx = check_tep_is_card_derived(report, args.league)
    check_unproven_scoring_fails_closed(report, ctx)
    check_dynasty_main_is_not_te_premium(report, ctx, args.league)
    check_comparable_population_before_after(report, ctx, args.league)

    crowd_market = None
    try:
        from src.trade.faab_history import build_crowd_market, load_crowd_history

        raw = load_crowd_history(args.league)
        if raw:
            crowd_market = build_crowd_market(raw, target=ctx.get("target"))
    except Exception:
        crowd_market = None
    check_idp_population_refusal(report, crowd_market)

    check_required_fields_exist(
        report,
        {
            "roster-percentage": rp_payload,
            "sharp-market": payload,
            "crowd-market": crowd_market.to_dict() if crowd_market is not None else None,
        },
    )

    # C8/C9 still go through the real endpoint, because the refusal reason and
    # the factor rows are assembled in server.py and not in the engine.
    if args.origin and args.add_player:
        cookie = os.environ.get("RISKIT_SESSION_COOKIE") or None
        try:
            code, faab = _http(
                f"{args.origin.rstrip('/')}/api/waiver/faab-recommend",
                cookie=cookie,
                body={"leagueKey": args.league, "addPlayerName": args.add_player},
            )
            if code == 200:
                source = "faab-recommend"
                check_crowd_refusal_reasons(report, faab, source)
                check_faab_recommendation_effect(report, faab, source)
            else:
                report.add(
                    Check("C8", "V1-129", "crowd-market refusal reasons", BLOCKED, f"HTTP {code}")
                )
        except Unauthenticated as exc:
            report.add(
                Check("C8", "V1-129", "crowd-market refusal reasons", UNVERIFIABLE, str(exc))
            )
    else:
        for cid, title in (
            ("C8", "crowd-market refusal reasons are specific and honest"),
            ("C9", "the crowd moves the bid only when it was actually admitted"),
        ):
            report.add(
                Check(
                    cid,
                    "V1-129",
                    title,
                    BLOCKED,
                    "these read server.py's assembled response, so they need --origin "
                    "(the local one is fine: http://127.0.0.1:8000) and --add-player "
                    "naming a real free agent.",
                )
            )

    # --- Lane 4 rows beyond #927 ---
    check_faab_history_timer(report)
    check_faab_history_artifact(report, args.league)
    check_ffpc_lane_is_honest(report)
    check_single_cohort_owner(report)
    check_league_population_difference(report)
    record_blocked_rows(report, None)


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("remote", "onbox"), required=True)
    parser.add_argument("--league", default="dynasty_main")
    parser.add_argument(
        "--origin",
        default="",
        help="deployed origin, e.g. https://chaseupside.com (required for --mode remote)",
    )
    parser.add_argument(
        "--add-player",
        default="",
        help="display name of a REAL free agent to price. Never invented by this script.",
    )
    parser.add_argument("--out", default="", help="write the JSON report here as well as stdout")
    args = parser.parse_args(argv)

    if args.mode == "remote" and not args.origin:
        parser.error("--mode remote needs --origin")

    report = Report(args.mode, args.league, args.origin or None)
    try:
        if args.mode == "remote":
            run_remote(report, args)
        else:
            run_onbox(report, args)
    except Exception as exc:  # pragma: no cover - last-resort guard
        report.add(Check("RUN", "-", "verification run", ERROR, repr(exc)))

    report.finalize()
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")

    code = report.exit_code()
    summary = " ".join(f"{k}={v}" for k, v in sorted(payload["counts"].items()))
    print(f"\n[lane4-verify] {summary} -> exit {code}", file=sys.stderr)
    if code == 3:
        incomplete = sorted({c.status for c in report.checks} & _PROVES_NOTHING) or [
            "no passing check"
        ]
        print(
            f"[lane4-verify] INCOMPLETE ({', '.join(incomplete)}): at least one question "
            "went unanswered, so this run is NOT a pass. Exit 0 is reserved for a run in "
            "which every check measured its case and passed.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
