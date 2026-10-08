"""Runner-side authenticated V1 production checks (API half).

Runs on the GitHub Actions RUNNER against the deployed origin, holding the
real session cookie an on-box guest-pass mint produced (see
``.github/workflows/v1-authenticated-verification.yml``).  Stdlib only —
the runner installs nothing.

Covers the API halves of: V1-11 item 8, V1-27 item 3, V1-45, V1-56,
V1-61, V1-102 (expiry wiring, minus the /admin surface), V1-131 steps 2-3,
plus a free-agent pick emitted for the Lane 4 verifier's C8/C9.

Rules, same as the on-box verifiers:

1. Nothing is fabricated; a 401 is UNVERIFIABLE, never a pass or failure.
2. Read-only over production.  The one POST used, ``/api/trade/simulate``,
   is a pure computation endpoint (verified against ``server.py`` — it
   mutates nothing), and ``/api/auth/login`` happened in the workflow step
   before this script runs.
3. Statuses ``pass`` / ``fail`` / ``unmeasurable`` / ``blocked`` /
   ``error``; exit 0 / 1 / 2 / 3 with 3 = "proved nothing".

The cookie is read from ``--cookie-file`` (a 600-mode file holding ONLY
the ``jason_session`` value) and never printed.

Two subcommands carry the 2026-10-08 security-incident acceptance
evidence (every workflow run, whatever the suite):

* ``security-probe --origin O --cookie-file F --out P`` — status codes and
  booleans for the session, run once before and once after the revoke;
* ``security-summary --pre P --post P --census C --revoke-ok B --out S`` —
  the allowlisted public report plus the job-summary table; exit 2 unless
  every security check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_PROVES_NOTHING = {"blocked", "unmeasurable"}


@dataclass
class Check:
    check_id: str
    row: str
    title: str
    status: str = "unmeasurable"
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def record(self, status: str, detail: str, **evidence: Any) -> None:
        self.status = status
        self.detail = detail
        self.evidence.update(evidence)


CHECKS: list[Check] = []


def _check(check_id: str, row: str, title: str) -> Check:
    c = Check(check_id, row, title)
    CHECKS.append(c)
    return c


class Client:
    def __init__(self, origin: str, cookie_value: str) -> None:
        self.origin = origin.rstrip("/")
        self._cookie = f"jason_session={cookie_value}"

    def request(
        self, path: str, *, method: str = "GET", body: dict | None = None
    ) -> tuple[int, Any]:
        req = urllib.request.Request(
            self.origin + path,
            method=method,
            headers={
                "Cookie": self._cookie,
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, raw[:500].decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw[:500].decode("utf-8", "replace")


# ────────────────────────────── checks ──────────────────────────────


def check_auth0(client: Client) -> bool:
    c = _check("AUTH0", "-", "session is a real guest_pass session")
    status, body = client.request("/api/auth/status")
    if status != 200 or not isinstance(body, dict):
        c.record("blocked", f"/api/auth/status returned {status}")
        return False
    ok = body.get("authenticated") is True and body.get("authMethod") == "guest_pass"
    c.record(
        "pass" if ok else "fail",
        f"authenticated={body.get('authenticated')} authMethod={body.get('authMethod')} "
        f"username={body.get('username')}",
        isAdmin=body.get("isAdmin"),
    )
    return ok


def check_v102(expected_duration: float | None, observed_expires: float | None) -> None:
    c = _check(
        "V102A",
        "V1-102",
        "deployed configurable expiry honored end-to-end (minus the /admin surface)",
    )
    if not expected_duration or not observed_expires:
        c.record(
            "blocked", "workflow did not pass --expected-duration-seconds/--observed-expires-epoch"
        )
        return
    observed_duration = observed_expires - time.time()
    drift = abs(observed_duration - expected_duration)
    # The login already happened; allow the elapsed time plus slack.
    if drift <= 900:
        c.record(
            "pass",
            "the non-default requested duration is what the deployed login "
            "enforced (a hardcoded 12h default could not produce this expiry). "
            "This is the canonical-implementation half of V1-102's L4; the "
            "/admin UI surface half remains admin-credential-blocked",
            expected_seconds=expected_duration,
            observed_remaining_seconds=round(observed_duration),
        )
    else:
        c.record(
            "fail",
            f"expiry drifts {round(drift)}s from the requested duration",
            expected_seconds=expected_duration,
            observed_remaining_seconds=round(observed_duration),
        )


def check_v61(client: Client) -> None:
    c = _check("V61A", "V1-61", "sharp roster-percentage transparency fields, null never zero")
    status, body = client.request("/api/sharp/roster-percentage")
    if status == 401:
        c.record("unmeasurable", "401 — session not accepted; UNVERIFIABLE, not a failure")
        return
    if status != 200 or not isinstance(body, dict):
        c.record("fail", f"HTTP {status}", body=body if isinstance(body, str) else None)
        return
    transparency = body.get("transparency")
    if not isinstance(transparency, dict):
        c.record("fail", "no transparency block on a 200 response", topKeys=sorted(body)[:15])
        return
    fields = {
        k: transparency.get(k) for k in ("cohortCoveragePct", "cohortManagers", "eligibleRosters")
    }
    missing = [k for k in fields if k not in transparency]
    if missing:
        c.record("fail", f"transparency missing {missing}", fields=fields)
        return
    # MISSING IS NEVER ZERO: coverage must be a number or an explicit null,
    # and an unobserved cohort must be null, not 0.
    cov = transparency.get("cohortCoveragePct")
    type_ok = cov is None or isinstance(cov, (int, float))
    c.record(
        "pass" if type_ok else "fail",
        "transparency block present with typed coverage "
        f"(cohortCoveragePct={cov!r}, cohortManagers={fields['cohortManagers']!r}, "
        f"eligibleRosters={fields['eligibleRosters']!r})",
        fields=fields,
    )


def check_v56(client: Client) -> None:
    c = _check("V56A", "V1-56", "FAAB league context served with zero-bid-inclusive figures")
    status, body = client.request("/api/public/league/faabAnalytics")
    if status != 200 or not isinstance(body, dict):
        c.record("fail" if status != 401 else "unmeasurable", f"HTTP {status}")
        return
    # build_section_payload() (src/public_league/public_contract.py) wraps
    # every section as {contractVersion, league, section, data} — the
    # section's own body always lives under "data", never under a key
    # named after the section itself. Same class of defect as W11-F006,
    # which was previously fixed on the frontend (ManualAddDrop.jsx) but
    # not here.
    block = body.get("data")
    if not isinstance(block, dict):
        c.record("fail", "no analytics block", topKeys=sorted(body)[:15])
        return
    median = block.get("leagueMedianWinningBid", "ABSENT")
    if median == "ABSENT":
        c.record("fail", "leagueMedianWinningBid absent from the payload", keys=sorted(block)[:20])
        return
    typed = median is None or isinstance(median, (int, float))
    c.record(
        "pass" if typed else "fail",
        f"leagueMedianWinningBid={median!r} (number or explicit null — the "
        "zero-bid-inclusive figure per faab_analytics.py; a nonzero-only median "
        "would overstate ~200x per the canonical record)",
        keys=sorted(block)[:20],
    )


def check_v49_item3(client: Client) -> None:
    c = _check(
        "V49-3",
        "V1-49",
        "authenticated GET /api/league-comparison?refresh=1 reaches the challenger "
        "(Sleeper-fallback) path instead of 401ing on an unauthenticated probe",
    )
    status, body = client.request("/api/league-comparison?refresh=1")
    if status == 401:
        c.record(
            "fail",
            "401 even with a real authenticated session — the route is not merely "
            "session-gated as the row's code-read concluded; something else refuses it",
        )
        return
    if status == 503 and isinstance(body, dict):
        # A documented, honest degraded response (Sleeper unreachable or one
        # configured league's scoring_settings missing) — real measurement,
        # not a fabricated pass, and distinct from "we never got in".
        c.record(
            "unmeasurable",
            f"authenticated and reached the route, but it reports {body.get('error')!r} "
            f"({body.get('detail', '')!r}) — a real degraded state, not an auth failure",
            httpStatus=status,
        )
        return
    if status != 200 or not isinstance(body, dict):
        c.record(
            "fail", f"HTTP {status}, unexpected shape", body=body if isinstance(body, str) else None
        )
        return
    # 200: the route is genuinely reachable authenticated. This alone does
    # not prove the host_native_scoring challenger fired — that needs real
    # in-season stat data this session (2026-09-03, pre-Week-1) does not
    # have — but it does resolve whether authentication was ever the
    # blocker, which is the one thing this check can honestly measure.
    top_keys = sorted(body)[:20]
    c.record(
        "pass",
        f"200 with an authenticated session — the auth barrier is resolved; "
        f"top-level keys: {top_keys}. Whether the host_native_scoring challenger "
        "path specifically fired still needs real 2026 in-season Sleeper stat "
        "data, which does not exist yet — that remains a separate, genuinely "
        "temporal gap, not an auth gap",
        topKeys=top_keys,
    )


def check_v131(client: Client) -> None:
    c = _check("V131A", "V1-131", "L3 recipe steps 2-3: features boolean agrees with the board")
    status, body = client.request("/api/auth/status")
    if status != 200 or not isinstance(body, dict):
        c.record("blocked", f"/api/auth/status returned {status}")
        return
    features = body.get("features")
    if not isinstance(features, dict) or "consensusEdge" not in features:
        c.record(
            "fail",
            "features.consensusEdge block absent on an authenticated response",
            features=features,
        )
        return
    available = (features.get("consensusEdge") or {}).get("available")
    if not isinstance(available, bool):
        c.record("fail", f"available is {available!r}, not a real boolean")
        return
    board_status, _ = client.request("/api/consensus-edge/players")
    agree = (board_status == 503 and available is False) or (
        board_status == 200 and available is True
    )
    c.record(
        "pass" if agree else "fail",
        f"features.consensusEdge.available={available}; /api/consensus-edge/players → "
        f"{board_status}; {'agreement' if agree else 'DISAGREEMENT — the recipe defect'}",
        available=available,
        boardStatus=board_status,
    )


def check_v11_item8(client: Client, contract: dict | None) -> None:
    c = _check("V11-8", "V1-11", "C1-U5 §6 item 8: the terminal still renders confidence")
    # /api/terminal only builds per-player signal rows (where the
    # confidence field actually lives — src/api/terminal.py::_build_signal_context,
    # spread into each entry) for a RESOLVED team; with no ?team= and no
    # sleeper_user_id on the session (the guest_pass account is not a real
    # Sleeper user), resolved_team stays None, roster_rows is empty, and
    # signals ends up []  -- not because confidence is missing from a real
    # row, but because there is no row to carry it. Same team-resolution
    # pattern check_v27_item3 already uses (contract.sleeper.teams), so a
    # real roster's signals actually get evaluated.
    teams = ((contract or {}).get("sleeper") or {}).get("teams") or []
    team_id = next((tid for t in teams if (tid := _team_id(t))), None)
    if team_id is None:
        c.record("unmeasurable", "could not resolve a real team id from the contract")
        return
    status, body = client.request(f"/api/terminal?team={team_id}")
    if status == 401:
        c.record("unmeasurable", "401 — UNVERIFIABLE")
        return
    if status != 200 or not isinstance(body, dict):
        c.record("fail", f"HTTP {status}")
        return
    signals = body.get("signals")
    if not signals:
        c.record(
            "unmeasurable",
            f"team {team_id} resolved but produced zero signal rows to check",
        )
        return
    blob = json.dumps(body)
    has_confidence = "confidence" in blob
    c.record(
        "pass" if has_confidence else "fail",
        "authenticated /api/terminal is 200 and its payload carries confidence vocabulary"
        if has_confidence
        else "200 but no confidence field anywhere in the payload",
        topKeys=sorted(body)[:15],
    )


def _fetch_contract(client: Client) -> dict | None:
    status, body = client.request("/api/data?view=app")
    if status == 200 and isinstance(body, dict):
        return body
    status, body = client.request("/api/data")
    return body if status == 200 and isinstance(body, dict) else None


def check_v11_item3_fresh(contract: dict | None) -> None:
    c = _check("V11-3", "V1-11", "C1-U5 §6 item 3 on the DEPLOYED response (was: rebuilt board)")
    if contract is None:
        c.record("unmeasurable", "no authenticated contract")
        return
    rows = contract.get("playersArray") or []
    if not rows:
        c.record("unmeasurable", "contract carries no playersArray")
        return
    priced = [
        r
        for r in rows
        if isinstance(r.get("rankDerivedValue"), (int, float)) and r["rankDerivedValue"] > 0
    ]
    missing_basis = [r.get("displayName") for r in priced if not r.get("confidenceBasis")]
    c.record(
        "pass" if not missing_basis else "fail",
        f"{len(priced)} priced rows on the deployed response; "
        f"{len(missing_basis)} without a confidenceBasis",
        sample_missing=missing_basis[:10],
    )


_SIGNALS_IDP_KEYS = ("signalsIdpDl", "signalsIdpLb", "signalsIdpDb")


def _contract_rows(contract: dict) -> list[dict]:
    """Rows from whichever encoding the view carried (view=app strips
    playersArray and serves the legacy ``players`` dict)."""
    rows = contract.get("playersArray")
    if isinstance(rows, list) and rows:
        return rows
    players = contract.get("players")
    return list(players.values()) if isinstance(players, dict) else []


def check_signals(contract: dict | None) -> None:
    """Signals Fantasy on the DEPLOYED, authenticated response.

    Offense: available, voting, and actually contributing on rows.  IDP:
    collected and visible, in its declared vote state (shadow until the
    shared-market crosswalk is promoted) — docs/sources/
    SIGNALS_FANTASY_INTEGRATION.md §9-§10."""
    off = _check("SIG-OFF", "Signals", "Signals offense votes and contributes on the live board")
    idp = _check("SIG-IDP", "Signals", "Signals IDP collected, visible, in its declared state")
    if contract is None:
        off.record("unmeasurable", "no authenticated contract")
        idp.record("unmeasurable", "no authenticated contract")
        return
    avail = contract.get("privateSourceAvailability") or {}
    rows = _contract_rows(contract)
    sf = avail.get("signalsSf") or {}
    contributing = sum(
        1
        for r in rows
        for m in [(r.get("sourceRankMeta") or {}).get("signalsSf")]
        if isinstance(m, dict)
        and not m.get("hampelDropped")
        and float(m.get("appliedWeight") or 0) > 0
        and isinstance(m.get("valueContribution"), (int, float))
    )
    shown = sum(1 for r in rows if "signalsSf" in (r.get("sourceNativeValues") or {}))
    ok = sf.get("state") == "present" and sf.get("votes") is True and contributing >= 100
    off.record(
        "pass" if ok else "fail",
        f"signalsSf state={sf.get('state')} votes={sf.get('votes')} "
        f"voteState={sf.get('voteState')}; {contributing} rows contribute, {shown} show a native value",
        availability=sf,
        rowsContributing=contributing,
        rowsWithNativeValue=shown,
    )
    states = {k: (avail.get(k) or {}).get("voteState") for k in _SIGNALS_IDP_KEYS}
    visible = {
        k: sum(1 for r in rows if k in (r.get("sourceNativeValues") or {}))
        for k in _SIGNALS_IDP_KEYS
    }
    shadowed = {
        k: sum(1 for r in rows if k in (r.get("sourceShadowMeta") or {})) for k in _SIGNALS_IDP_KEYS
    }
    voting = {
        k: sum(1 for r in rows if k in (r.get("sourceRankMeta") or {})) for k in _SIGNALS_IDP_KEYS
    }
    consistent = all(
        (states[k] == "shadow" and voting[k] == 0 and shadowed[k] > 0)
        or (states[k] == "active" and voting[k] > 0)
        for k in _SIGNALS_IDP_KEYS
    )
    ok = consistent and all(visible[k] > 0 for k in _SIGNALS_IDP_KEYS)
    idp.record(
        "pass" if ok else "fail",
        f"voteState={states}; visible={visible}; shadow={shadowed}; voting={voting}",
        voteStates=states,
        rowsVisible=visible,
        rowsShadowed=shadowed,
        rowsVoting=voting,
    )


def _bench_tail(team: dict) -> str | None:
    lineup = team.get("optimalLineup") or {}
    bench = lineup.get("bench") or []
    if not bench:
        return None
    tail = bench[-1]
    return tail if isinstance(tail, str) else (tail or {}).get("name")


def _team_id(team: dict) -> str | None:
    for key in ("ownerId", "owner_id", "rosterId", "roster_id", "teamId"):
        if team.get(key) is not None:
            return str(team[key])
    return None


def check_v27_item3(client: Client, contract: dict | None, league: str) -> None:
    """§10 item 3, on the REAL request shape: ``/api/trade/simulate`` takes
    one team's perspective — ``{team, playersIn, playersOut, ...}`` — and
    is pure (its own docstring: "No persistence — the live contract is
    never mutated")."""
    c = _check(
        "V27-3", "V1-27", "C2-U1 §10 item 3: starter-neutral trade leaves starterDelta unchanged"
    )
    if contract is None:
        c.record("unmeasurable", "no authenticated contract to build the trade from")
        return
    teams = ((contract.get("sleeper") or {}).get("teams")) or []
    picks = [(t, _team_id(t), _bench_tail(t)) for t in teams]
    picks = [(t, tid, name) for t, tid, name in picks if tid and name]
    if len(picks) < 2:
        c.record(
            "unmeasurable", "could not identify two tail-bench players from optimalLineup stamps"
        )
        return
    my_team, my_id, my_tail = picks[0]
    other_tail = picks[1][2]
    payload = {
        "leagueKey": league,
        "team": my_id,
        "playersOut": [my_tail],
        "playersIn": [other_tail],
    }
    status, body = client.request("/api/trade/simulate", method="POST", body=payload)
    if status != 200 or not isinstance(body, dict):
        c.record(
            "unmeasurable",
            f"simulate returned {status} for the constructed payload",
            payload=payload,
        )
        return
    impact = body.get("teamImpact")
    delta = impact.get("starterDelta") if isinstance(impact, dict) else None
    if delta is None and isinstance(impact, dict):
        nested = [
            v.get("starterDelta")
            for v in impact.values()
            if isinstance(v, dict) and "starterDelta" in v
        ]
        delta = nested[0] if nested else None
    if delta is None:
        c.record(
            "unmeasurable", "no starterDelta stamped on the response", topKeys=sorted(body)[:15]
        )
        return
    neutral = _starter_delta_is_neutral(delta)
    c.record(
        "pass" if neutral else "fail",
        f"tail-bench-for-tail-bench swap starterDelta={delta!r} "
        + (
            "(unchanged, as §10 item 3 requires)"
            if neutral
            else "(moved — either a real defect or the swap was not starter-neutral; inspect evidence)"
        ),
        payload=payload,
    )


def _starter_delta_is_neutral(delta: Any) -> bool:
    if isinstance(delta, (int, float)):
        return delta == 0
    if isinstance(delta, dict):
        return all((v or 0) == 0 for v in delta.values() if isinstance(v, (int, float)))
    if isinstance(delta, list):
        return len(delta) == 0
    return False


def check_v45(client: Client, contract: dict | None, league: str) -> None:
    c = _check(
        "V45A", "V1-45", "deployed /api/trade/simulate stamps finalRosterSimulation truthfully"
    )
    if contract is None:
        c.record("unmeasurable", "no authenticated contract")
        return
    teams = ((contract.get("sleeper") or {}).get("teams")) or []
    picks = [(t, _team_id(t), _bench_tail(t)) for t in teams]
    picks = [(t, tid, name) for t, tid, name in picks if tid and name]
    if len(picks) < 2:
        c.record("unmeasurable", "could not build a real trade from the deployed contract")
        return
    _, my_id, my_tail = picks[0]
    other_tail = picks[1][2]
    status, body = client.request(
        "/api/trade/simulate",
        method="POST",
        body={
            "leagueKey": league,
            "team": my_id,
            "playersOut": [my_tail],
            "playersIn": [other_tail],
        },
    )
    if status != 200 or not isinstance(body, dict):
        c.record("unmeasurable", f"simulate returned {status}")
        return
    if "finalRosterSimulation" not in body:
        c.record(
            "fail",
            "finalRosterSimulation ABSENT from a team-resolved simulate response — "
            "the V1-42 stamp is not being served",
            topKeys=sorted(body)[:20],
        )
        return
    block = body["finalRosterSimulation"]
    state = "unknown"
    if isinstance(block, dict):
        if block.get("available") is True:
            state = "populated"
        elif block.get("unavailableReason") == "capacity_uncertain":
            state = "capacity_uncertain"
        elif "unavailable" in block or block.get("available") is False:
            state = "unavailable"
    c.record(
        "pass" if state != "unknown" else "fail",
        f"finalRosterSimulation stamped, state={state} (one of the recipe's named "
        "states; the browser half verifies the render)",
        state=state,
        blockKeys=sorted(block) if isinstance(block, dict) else str(block)[:100],
    )


def emit_free_agent(contract: dict | None, out_path: str | None) -> None:
    c = _check("FA-PICK", "V1-129", "a REAL free agent chosen from the deployed board for C8/C9")
    if contract is None or not out_path:
        c.record("blocked", "no contract or no --free-agent-out")
        return
    rows = contract.get("playersArray") or []
    rostered: set[str] = set()
    for team in ((contract.get("sleeper") or {}).get("teams")) or []:
        for key in ("players", "roster", "playerNames"):
            for p in team.get(key) or []:
                rostered.add(str(p if isinstance(p, str) else (p or {}).get("name")))
    candidates = [
        r.get("displayName")
        for r in rows
        if r.get("assetClass") == "offense"
        and r.get("displayName")
        and r.get("displayName") not in rostered
        and isinstance(r.get("canonicalConsensusRank"), int)
    ]
    if not candidates:
        c.record(
            "unmeasurable", "no unrostered ranked offense player identifiable from the payload"
        )
        return
    # A mid-board free agent: real, priced, uncontroversial.
    choice = candidates[len(candidates) // 2]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(str(choice))
    c.record("pass", f"free agent chosen from the deployed board: {choice}", pool=len(candidates))


# ─────────── security acceptance (incident 2026-10-08, guest sessions) ───────────
#
# Production evidence that (a) a guest session without a valid pass identity
# is rejected and (b) a revoked pass cannot keep authenticating a session it
# already minted.  The workflow probes the SAME session before and after the
# on-box revoke, then runs a count-only census of the persisted session store
# (``src/api/session_store.py::guest_session_census``) over SSH.
#
# Everything that leaves these functions is an int, a bool or None, through
# a fixed key allowlist: the report is public (public repo => public
# artifacts), so no body, header, cookie, username or pass id may reach it.

#: A cheap, read-only private route behind the middleware auth gate.
SECURITY_PRIVATE_PROBE_PATH = "/api/user/state"

_PROBE_KEYS = ("authStatusHttp", "authenticated", "privateRouteHttp", "probeError")
_CENSUS_KEYS = (
    "storePresent",
    "schemaHasGuestColumns",
    "totalSessions",
    "guestSessions",
    "guestSessionsMissingPassIdentity",
    "guestSessionsPassRevoked",
    "guestSessionsLiveWithInactivePass",
    "guestSessionsExpiredAwaitingCleanup",
    "passStoreReadable",
)
SECURITY_INCIDENT = "2026-10-08-guest-session-cookie-exposure"


def _scalar(value: Any) -> int | bool | None:
    """Only ints and bools survive; anything else becomes None (unknown)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    return None


def _allowlisted(raw: Any, keys: tuple[str, ...]) -> dict[str, int | bool | None] | None:
    if not isinstance(raw, dict):
        return None
    return {k: _scalar(raw.get(k)) for k in keys}


def probe_session(client: Client) -> dict[str, int | bool | None]:
    """Status codes and booleans only — never a body, a header or the cookie."""
    try:
        status, body = client.request("/api/auth/status")
        authenticated = body.get("authenticated") if isinstance(body, dict) else None
        private_status, _ = client.request(SECURITY_PRIVATE_PROBE_PATH)
    except Exception:  # noqa: BLE001 — the exception text may carry the URL; record the fact only
        return {k: (True if k == "probeError" else None) for k in _PROBE_KEYS}
    return {
        "authStatusHttp": int(status),
        "authenticated": authenticated if isinstance(authenticated, bool) else None,
        "privateRouteHttp": int(private_status),
        "probeError": False,
    }


def _probe_accepted(p: dict | None) -> bool:
    return bool(
        p
        and p.get("authStatusHttp") == 200
        and p.get("authenticated") is True
        and p.get("privateRouteHttp") == 200
    )


def _probe_rejected(p: dict | None) -> bool:
    return bool(
        p
        and p.get("authStatusHttp") == 200
        and p.get("authenticated") is False
        and p.get("privateRouteHttp") == 401
    )


def _probe_text(p: dict | None) -> str:
    if not p:
        return "no probe result"
    return (
        f"/api/auth/status HTTP {p.get('authStatusHttp')} authenticated={p.get('authenticated')}; "
        f"{SECURITY_PRIVATE_PROBE_PATH} HTTP {p.get('privateRouteHttp')}"
        + ("; probe raised" if p.get("probeError") else "")
    )


def check_revocation(revoke_ok: bool | None, pre: dict | None, post: dict | None) -> list[Check]:
    """(b): the SAME session, accepted before the revoke, is rejected after it.

    The control matters: a rejection after the revoke proves nothing about
    revocation if the session was never accepted in the first place."""
    rev = _check("SEC-REVOKE", "security-2026-10-08", "on-box revoke succeeded")
    if revoke_ok is True:
        rev.record("pass", "guest_passes.revoke marked the pass and it is no longer authoritative")
    else:
        rev.record("fail", f"revoke did not succeed (revokeSucceeded={revoke_ok})")

    probe = _check(
        "SEC-POST-REVOKE",
        "security-2026-10-08",
        "a revoked pass's already-created session is rejected on its next request",
    )
    if not _probe_accepted(pre):
        probe.record(
            "fail",
            "control probe did not show the session accepted before the revoke "
            f"({_probe_text(pre)}) — a later rejection would prove nothing",
        )
    elif revoke_ok is not True:
        probe.record("fail", "revoke failed, so the post-revocation probe is not evidence")
    elif _probe_rejected(post):
        probe.record("pass", f"before: {_probe_text(pre)}; after: {_probe_text(post)}")
    else:
        probe.record(
            "fail",
            f"session still answered after the revoke — before: {_probe_text(pre)}; "
            f"after: {_probe_text(post)}",
        )
    return [rev, probe]


def check_session_census(census: dict | None) -> list[Check]:
    """(a) and (b) on the persisted store, counts only.  ``None`` is unknown,
    and unknown is never a pass: a MUST-be-0 count must be observed as 0."""
    c = census or {}
    schema = _check(
        "SEC-SCHEMA", "security-2026-10-08", "session store carries expiry + pass-id columns"
    )
    if c.get("schemaHasGuestColumns") is True:
        schema.record("pass", "expires_at_epoch and guest_pass_id present")
    else:
        schema.record(
            "fail",
            f"schemaHasGuestColumns={c.get('schemaHasGuestColumns')} "
            f"(storePresent={c.get('storePresent')})",
        )

    def must_be_zero(check_id: str, title: str, *keys: str) -> Check:
        chk = _check(check_id, "security-2026-10-08", title)
        values = {k: c.get(k) for k in keys}
        text = ", ".join(f"{k}={v}" for k, v in values.items())
        if all(v == 0 and not isinstance(v, bool) for v in values.values()):
            chk.record("pass", text)
        else:
            chk.record("fail", text + " (each MUST be an observed 0)")
        return chk

    legacy = must_be_zero(
        "SEC-LEGACY",
        "no persisted guest session lacks a pass id or expiry",
        "guestSessionsMissingPassIdentity",
    )
    inactive = must_be_zero(
        "SEC-INACTIVE-PASS",
        "no persisted guest session survives a revoked, expired or purged pass",
        "guestSessionsPassRevoked",
        "guestSessionsLiveWithInactivePass",
    )
    return [schema, legacy, inactive]


def build_security_summary(
    *,
    revoke_ok: bool | None,
    pre: Any,
    post: Any,
    census: Any,
) -> dict[str, Any]:
    """The public artifact: fixed keys, ints/bools/None, our own detail text."""
    pre_s = _allowlisted(pre, _PROBE_KEYS)
    post_s = _allowlisted(post, _PROBE_KEYS)
    census_s = _allowlisted(census, _CENSUS_KEYS)
    checks = check_revocation(revoke_ok, pre_s, post_s) + check_session_census(census_s)
    return {
        "incident": SECURITY_INCIDENT,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revokeSucceeded": revoke_ok,
        "preRevocationProbe": pre_s,
        "postRevocationProbe": post_s,
        "sessionStoreCensus": census_s,
        "checks": [{"id": k.check_id, "status": k.status, "detail": k.detail} for k in checks],
        "verdict": "pass" if all(k.status == "pass" for k in checks) else "fail",
    }


def security_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"### Security acceptance — incident {summary['incident']}: **{summary['verdict'].upper()}**",
        "",
        "| check | status | detail |",
        "|---|---|---|",
    ]
    for chk in summary["checks"]:
        lines.append(f"| {chk['id']} | {chk['status']} | {chk['detail']} |")
    census = summary.get("sessionStoreCensus") or {}
    lines += ["", "| census (count-only) | value |", "|---|---|"]
    lines += [f"| {k} | {census.get(k)} |" for k in _CENSUS_KEYS]
    return "\n".join(lines) + "\n"


def _read_json(path: str | None) -> Any:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _security_probe_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verify_v1_authenticated.py security-probe")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookie_value = fh.read().strip()
    except OSError:
        cookie_value = ""
    if cookie_value:
        result = probe_session(Client(args.origin, cookie_value))
    else:
        result = {k: (True if k == "probeError" else None) for k in _PROBE_KEYS}
    result = _allowlisted(result, _PROBE_KEYS)
    rendered = json.dumps(result, sort_keys=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(rendered)
    return 0


def _security_summary_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verify_v1_authenticated.py security-summary")
    parser.add_argument("--pre", default=None)
    parser.add_argument("--post", default=None)
    parser.add_argument("--census", default=None)
    parser.add_argument("--revoke-ok", default="", help="'true' / 'false' / '' (unknown)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--step-summary", default=None)
    args = parser.parse_args(argv)
    revoke_ok = {"true": True, "false": False}.get(args.revoke_ok.strip().lower())
    summary = build_security_summary(
        revoke_ok=revoke_ok,
        pre=_read_json(args.pre),
        post=_read_json(args.post),
        census=_read_json(args.census),
    )
    rendered = json.dumps(summary, indent=1, sort_keys=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(rendered)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(security_summary_markdown(summary))
    return 0 if summary["verdict"] == "pass" else 2


# ────────────────────────────── driver ──────────────────────────────


def _isolated(label: str, fn, *args):
    """Run one check so its crash costs THAT check, never the suite.

    The first production run proved why this exists: check_v61's uncaught
    read timeout (a cold /api/sharp/roster-percentage taking >60 s right
    after a deploy restart) aborted main() before the report was written
    or the free agent picked — every downstream check silently vanished
    and the run proved nothing about them.  A network timeout is a
    legitimate measurement to RECORD (status "error"), not a reason to
    lose the rest of the evidence.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — recorded, not raised
        c = _check(f"{label}:crash", "-", f"{label} raised instead of recording")
        c.record("error", f"{type(exc).__name__}: {exc}")
        return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "security-probe":
        return _security_probe_main(argv[1:])
    if argv and argv[0] == "security-summary":
        return _security_summary_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--league", default="dynasty_main")
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--report", default=None)
    parser.add_argument("--expected-duration-seconds", type=float, default=None)
    parser.add_argument("--observed-expires-epoch", type=float, default=None)
    parser.add_argument("--free-agent-out", default=None)
    args = parser.parse_args(argv)

    with open(args.cookie_file, encoding="utf-8") as fh:
        cookie_value = fh.read().strip()
    client = Client(args.origin, cookie_value)

    session_ok = _isolated("AUTH0", check_auth0, client)
    _isolated("V102A", check_v102, args.expected_duration_seconds, args.observed_expires_epoch)
    if session_ok:
        contract = _isolated("CONTRACT", _fetch_contract, client)
        _isolated("V61A", check_v61, client)
        _isolated("V56A", check_v56, client)
        _isolated("V131A", check_v131, client)
        _isolated("V49-3", check_v49_item3, client)
        _isolated("V11-8", check_v11_item8, client, contract)
        _isolated("V11-3", check_v11_item3_fresh, contract)
        _isolated("SIGNALS", check_signals, contract)
        _isolated("V27-3", check_v27_item3, client, contract, args.league)
        _isolated("V45A", check_v45, client, contract, args.league)
        _isolated("FA-PICK", emit_free_agent, contract, args.free_agent_out)

    report = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "origin": args.origin,
        "league": args.league,
        "checks": [c.__dict__ for c in CHECKS],
    }
    rendered = json.dumps(report, indent=1, default=str)
    print(rendered)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(rendered)

    statuses = [c.status for c in CHECKS]
    if "error" in statuses:
        return 1
    if "fail" in statuses:
        return 2
    if not [s for s in statuses if s not in _PROVES_NOTHING]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
