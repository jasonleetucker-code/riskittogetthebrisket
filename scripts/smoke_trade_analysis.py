#!/usr/bin/env python3
"""Post-deploy smoke: authenticated 2-team and 3-team trade analysis.

Runs on the GitHub Actions RUNNER against the deployed origin, holding the
guest-pass session cookie the V1 authenticated verification workflow already
mints (``.github/workflows/v1-authenticated-verification.yml``).  Stdlib only.

Why it exists: two production defects (the multi-team War Room being off, and a
board on which every asset of a 3-team trade read "withheld (stale)") were found
only through screenshots, because no post-deploy check ever called
``/api/trade/analyze`` or ``/api/trade/analyze-multi``.

What it does
------------
1. Reads the live league through ``GET /api/data?view=app`` (the read the
   ``/trade`` page itself uses).
2. Builds, deterministically, a 2-team trade and a 3-team routed ring from
   currently-owned assets: each team's top-valued priced player (``p:<sleeperId>``).
3. POSTs (asset-only, ``useTeamContext: false``: the market/asset-evidence path
   the 2026-11-17 incident hit, independent of roster projections and
   starter-slot evidence that can be legitimately absent) ``/api/trade/analyze`` and ``/api/trade/analyze-multi``, both sending
   ``X-Chase-Smoke: 1``.  The servers honor that header ONLY for a guest-pass
   session and then skip the decision-receipt append, so the smoke never writes
   into the AL-P5 decision ledger.  Both routes are otherwise analysis-only.
4. Asserts HTTP 200, the response schema, that the header was honored (no
   decision run id), and that the board is not withheld wholesale.

Pass / fail predicate (per call)
--------------------------------
PASS only when ALL hold:
* HTTP 200 with a JSON object;
* schema: every requested team has a result; each carries a ``category`` in the
  published set, a ``fairness.state`` in {FAIR, NOT_FAIR, UNABLE}, a decision
  ``headline`` in {YES, NO, NO_TOO_CLOSE, NOT_ENOUGH_EVIDENCE}, and per asset a
  ``valueState`` (analyze-multi) or the evidence fields (analyze);
* NOT all-withheld: at least one asset is priced (``valueState == "priced"``
  with a positive value; analyze: positive value, not quarantined, freshness
  not ``low``), AND not every team is ``UNAVAILABLE`` / ``NOT_ENOUGH_EVIDENCE``;
* the smoke header was honored (``decisionRunId`` / every ``decisionRunIds``
  entry is ``null``).
A missing field is a failure (missing is never zero, never "assumed fine").

Failure classes (``code``): ``flag_off``, ``auth_failure``, ``data_not_ready``,
``package_model_unavailable``, ``busy``, ``ownership_refused:<reason>``,
``refused:<error>[:<reason>]``, ``schema_drift:<what>``, ``all_withheld``,
``insufficient_evidence``, ``smoke_not_honored``, ``network_error``,
``http_<status>``, ``cannot_build_trade:<why>``.

Exit codes: 0 pass, 2 any failure, 1 usage / unreadable cookie file.
The printed JSON carries roster ids, asset ids, statuses and counts only: never
a cookie, token, player or manager name.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

SMOKE_HEADER = "X-Chase-Smoke"

# Pinned against src/trade/team_verdicts.py and trade_decision.py by
# tests/scripts/test_smoke_trade_analysis.py (this script stays stdlib-only).
CATEGORIES = (
    "STRONGLY_FAVORABLE",
    "FAVORABLE",
    "APPROXIMATELY_EVEN",
    "UNFAVORABLE",
    "STRONGLY_UNFAVORABLE",
    "UNAVAILABLE",
)
FAIRNESS_STATES = ("FAIR", "NOT_FAIR", "UNABLE")
HEADLINES = ("YES", "NO", "NO_TOO_CLOSE", "NOT_ENOUGH_EVIDENCE")

EXIT_PASS = 0
EXIT_USAGE = 1
EXIT_FAIL = 2


class BuildError(Exception):
    """The live board cannot yield a smoke trade (reported, never guessed)."""


# ───────────────────────────── trade construction ─────────────────────────────


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _rid(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None
    for key in ("roster_id", "rosterId"):
        try:
            rid = int(team.get(key))
        except (TypeError, ValueError):
            continue
        if rid >= 1:
            return rid
    return None


def _named_rows(contract: dict) -> list[tuple[Any, dict]]:
    """``(name, row)`` from whichever encoding the view carried: ``playersArray``
    rows name themselves; the legacy ``players`` dict (all ``view=app`` serves)
    is keyed by name."""
    arr = contract.get("playersArray")
    if isinstance(arr, list) and arr:
        return [(r.get("displayName") or r.get("name"), r) for r in arr if isinstance(r, dict)]
    players = contract.get("players")
    if isinstance(players, dict):
        return [(k, r) for k, r in players.items() if isinstance(r, dict)]
    return []


def _value_by_name(contract: dict) -> dict[str, float | None]:
    """name -> ``rankDerivedValue``; a name carried by two rows is ambiguous
    (None): identity is never a guess."""
    out: dict[str, float | None] = {}
    for name, r in _named_rows(contract):
        if not isinstance(name, str) or not name:
            continue
        v = r.get("rankDerivedValue")
        val = float(v) if _is_num(v) and v > 0 else None
        out[name] = None if name in out else val
    return out


def top_players(contract: dict) -> list[dict[str, Any]]:
    """One entry per roster (ascending ``rosterId``) that holds a priced
    player: its single top-valued player (ties broken by Sleeper id)."""
    sleeper = contract.get("sleeper") if isinstance(contract, dict) else None
    teams = sleeper.get("teams") if isinstance(sleeper, dict) else None
    if not isinstance(teams, list) or not teams:
        raise BuildError("no_league_rosters")
    id_to_player = sleeper.get("idToPlayer") if isinstance(sleeper.get("idToPlayer"), dict) else {}
    values = _value_by_name(contract)
    by_rid: dict[int, dict] = {}
    for t in teams:
        rid = _rid(t)
        if rid is not None and rid not in by_rid:
            by_rid[rid] = t
    held: dict[str, int] = {}
    for rid, t in by_rid.items():
        for pid in t.get("playerIds") or []:
            held[str(pid)] = held.get(str(pid), 0) + 1
    out = []
    for rid in sorted(by_rid):
        t = by_rid[rid]
        best: tuple[float, str, str] | None = None
        for pid in t.get("playerIds") or []:
            sid = str(pid or "").strip()
            name = id_to_player.get(sid)
            if not sid or held.get(sid, 0) != 1 or not isinstance(name, str):
                continue  # held by several rosters / unnamed: not verifiable
            val = values.get(name)
            if val is None:
                continue
            cand = (val, sid, name)
            if best is None or (-cand[0], cand[1]) < (-best[0], best[1]):
                best = cand
        if best is not None:
            owner = t.get("ownerId")
            out.append(
                {
                    "rosterId": rid,
                    "sleeperId": best[1],
                    "playerName": best[2],
                    "ownerId": str(owner) if owner not in (None, "") else None,
                    "teamName": t.get("name") if isinstance(t.get("name"), str) else None,
                }
            )
    return out


def build_trades(contract: dict, league: str) -> dict[str, Any]:
    """``{"two": analyze body, "three": analyze-multi body, "meta": ...}``."""
    tops = top_players(contract)
    if len(tops) < 3:
        raise BuildError(f"fewer_than_3_rosters_with_a_priced_player({len(tops)})")
    a, b, c = tops[0], tops[1], tops[2]
    if a["ownerId"]:
        who: dict[str, Any] = {"team": a["ownerId"]}
    elif a["teamName"]:
        who = {"teamName": a["teamName"]}
    else:
        raise BuildError("team_a_has_no_owner_id_or_name")
    two = {
        "leagueKey": league,
        **who,
        "playersIn": [b["playerName"]],
        "playerIdsIn": [b["sleeperId"]],
        "playersOut": [a["playerName"]],
        "playerIdsOut": [a["sleeperId"]],
        "useTeamContext": False,
    }
    three = {
        "leagueKey": league,
        "teams": [a["rosterId"], b["rosterId"], c["rosterId"]],
        "assets": [
            {"id": f"p:{a['sleeperId']}", "from": a["rosterId"], "to": b["rosterId"]},
            {"id": f"p:{b['sleeperId']}", "from": b["rosterId"], "to": c["rosterId"]},
            {"id": f"p:{c['sleeperId']}", "from": c["rosterId"], "to": a["rosterId"]},
        ],
        "useTeamContext": False,
        "counterfactuals": False,
    }
    return {
        "two": two,
        "three": three,
        "meta": {
            "twoTeamRosterIds": [a["rosterId"], b["rosterId"]],
            "threeTeamRosterIds": [a["rosterId"], b["rosterId"], c["rosterId"]],
            "assetIds": [x["id"] for x in three["assets"]],
        },
    }


# ───────────────────────────────── classifier ─────────────────────────────────


def _fail(code: str, **extra: Any) -> dict[str, Any]:
    return {"status": "fail", "code": code, **extra}


_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}")


def _vocab(value: Any) -> str | None:
    """A server error/reason code, only if it is a short snake_case token: the
    summary is a PUBLIC artifact, so no free text from a response may reach it."""
    return value if isinstance(value, str) and _SAFE_CODE.fullmatch(value) else None


def _refusal(status: int, body: Any) -> dict[str, Any]:
    """Classify a non-200 answer from either route."""
    raw_err = body.get("error") if isinstance(body, dict) else None
    err = _vocab(raw_err)
    reason = _vocab(body.get("reason") if isinstance(body, dict) else None)
    ids = body.get("rosterIds") if isinstance(body, dict) else None
    extra: dict[str, Any] = {"http": status}
    if isinstance(ids, list):
        extra["rosterIds"] = [i for i in ids if isinstance(i, int)]
    if status in (401, 403) or err == "auth_required":
        return _fail("auth_failure", **extra)
    if err == "multi_team_analysis_disabled":
        return _fail("flag_off", **extra)
    if err == "data_not_ready" or (
        status == 503 and isinstance(raw_err, str) and raw_err.startswith("No data available")
    ):
        return _fail("data_not_ready", **extra)
    if err == "package_model_unavailable":
        return _fail("package_model_unavailable", **extra)
    if err in ("analysis_busy", "analysis_timeout"):
        return _fail("busy", **extra)
    if reason in ("asset_not_owned", "unknown_asset"):
        return _fail(f"ownership_refused:{reason}", **extra)
    if err is not None:
        return _fail(f"refused:{err}" + (f":{reason}" if reason is not None else ""), **extra)
    return _fail(f"http_{status}", **extra)


def _row_priced_multi(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and row.get("valueState") == "priced"
        and _is_num(row.get("value"))
        and row["value"] > 0
    )


def _asset_priced_two(asset: Any) -> bool:
    return (
        isinstance(asset, dict)
        and _is_num(asset.get("value"))
        and asset["value"] > 0
        and asset.get("quarantined") is not True
        and asset.get("valueFreshness") != "low"
    )


def classify_multi(status: int, body: Any, requested: list[int]) -> dict[str, Any]:
    """Verdict for one ``/api/trade/analyze-multi`` answer."""
    if status != 200:
        return _refusal(status, body)
    if not isinstance(body, dict):
        return _fail("schema_drift:body_not_object", http=status)
    teams = body.get("teams")
    if not isinstance(teams, list):
        return _fail("schema_drift:teams", http=status)
    got = sorted(t.get("rosterId") for t in teams if isinstance(t, dict))
    if got != sorted(requested):
        return _fail("schema_drift:team_set", http=status, rosterIds=got)
    priced = 0
    rows = 0
    unavailable = 0
    cats: dict[str, int] = {}
    for t in teams:
        cat = t.get("category")
        if cat not in CATEGORIES:
            return _fail("schema_drift:category", http=status, rosterIds=[t.get("rosterId")])
        fair = t.get("fairness")
        if not isinstance(fair, dict) or fair.get("state") not in FAIRNESS_STATES:
            return _fail("schema_drift:fairness", http=status, rosterIds=[t.get("rosterId")])
        analysis = t.get("analysis")
        decision = analysis.get("decision") if isinstance(analysis, dict) else None
        headline = decision.get("headline") if isinstance(decision, dict) else None
        if headline not in HEADLINES:
            return _fail("schema_drift:decision", http=status, rosterIds=[t.get("rosterId")])
        for side in ("gives", "receives"):
            side_rows = t.get(side)
            if not isinstance(side_rows, list) or not side_rows:
                return _fail(f"schema_drift:{side}", http=status, rosterIds=[t.get("rosterId")])
            for row in side_rows:
                if not isinstance(row, dict) or not isinstance(row.get("valueState"), str):
                    return _fail(
                        f"schema_drift:{side}.valueState",
                        http=status,
                        rosterIds=[t.get("rosterId")],
                    )
                rows += 1
                priced += 1 if _row_priced_multi(row) else 0
        cats[cat] = cats.get(cat, 0) + 1
        if cat == "UNAVAILABLE" or headline == "NOT_ENOUGH_EVIDENCE":
            unavailable += 1
    if not isinstance(body.get("summary"), dict):
        return _fail("schema_drift:summary", http=status)
    census = {"assetRows": rows, "pricedRows": priced, "categories": cats}
    if priced == 0:
        return _fail("all_withheld", http=status, **census)
    if unavailable == len(teams):
        return _fail("insufficient_evidence", http=status, **census)
    run_ids = body.get("decisionRunIds")
    if not isinstance(run_ids, dict):
        return _fail("schema_drift:decisionRunIds", http=status)
    if any(v is not None for v in run_ids.values()):
        return _fail("smoke_not_honored", http=status)
    rosters = body.get("rosters")
    state = rosters.get("state") if isinstance(rosters, dict) else None
    state = state if state in ("current", "stale", "unknown") else None
    return {"status": "pass", "code": "ok", "http": status, "rostersState": state, **census}


def classify_two(status: int, body: Any) -> dict[str, Any]:
    """Verdict for one ``/api/trade/analyze`` answer."""
    if status != 200:
        return _refusal(status, body)
    if not isinstance(body, dict):
        return _fail("schema_drift:body_not_object", http=status)
    sending, receiving = body.get("sending"), body.get("receiving")
    if not (isinstance(sending, list) and sending and isinstance(receiving, list) and receiving):
        return _fail("schema_drift:sending_receiving", http=status)
    analysis = body.get("analysis")
    decision = analysis.get("decision") if isinstance(analysis, dict) else None
    headline = decision.get("headline") if isinstance(decision, dict) else None
    if headline not in HEADLINES:
        return _fail("schema_drift:decision", http=status)
    if "decisionRunId" not in analysis:
        return _fail("schema_drift:decisionRunId", http=status)
    assets = [*sending, *receiving]
    priced = sum(1 for a in assets if _asset_priced_two(a))
    census = {"assetRows": len(assets), "pricedRows": priced, "headline": headline}
    if priced == 0:
        return _fail("all_withheld", http=status, **census)
    if headline == "NOT_ENOUGH_EVIDENCE":
        return _fail("insufficient_evidence", http=status, **census)
    if analysis.get("decisionRunId") is not None:
        return _fail("smoke_not_honored", http=status)
    return {"status": "pass", "code": "ok", "http": status, **census}


# ──────────────────────────────────── HTTP ────────────────────────────────────


class Client:
    def __init__(self, origin: str, cookie_value: str, timeout: float, log: Callable[[str], None]):
        self.origin = origin.rstrip("/")
        self._cookie = f"jason_session={cookie_value}"
        self.timeout = timeout
        self._log = log

    def request(self, path: str, body: dict | None = None) -> tuple[int | None, Any]:
        """``(status, json)``.  ONE retry, for network errors only (never for
        an HTTP status), logged without the URL query or any credential."""
        headers = {"Cookie": self._cookie, "Accept": "application/json", SMOKE_HEADER: "1"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in (1, 2):
            req = urllib.request.Request(
                self.origin + path,
                method="POST" if body is not None else "GET",
                headers=headers,
                data=json.dumps(body).encode() if body is not None else None,
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, _json(resp.read())
            except urllib.error.HTTPError as exc:
                return exc.code, _json(exc.read())
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                self._log(
                    f"network error on {path.split('?')[0]} (attempt {attempt}): {type(exc).__name__}"
                )
                if attempt == 2:
                    return None, None
                time.sleep(3)
        return None, None  # pragma: no cover


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return None


# ───────────────────────────────────── main ───────────────────────────────────


def run(client: Client, league: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    status, contract = client.request(f"/api/data?view=app&leagueKey={league}")
    if status is None:
        checks.append({"id": "read_league", **_fail("network_error")})
        return _summary(league, checks)
    if status != 200 or not isinstance(contract, dict):
        checks.append({"id": "read_league", **_refusal(status, contract)})
        return _summary(league, checks)
    try:
        built = build_trades(contract, league)
    except BuildError as exc:
        checks.append({"id": "build_trades", **_fail(f"cannot_build_trade:{exc}")})
        return _summary(league, checks)
    meta = built["meta"]

    status, body = client.request("/api/trade/analyze", built["two"])
    verdict = _fail("network_error") if status is None else classify_two(status, body)
    checks.append({"id": "analyze_2team", "rosterIds": meta["twoTeamRosterIds"], **verdict})

    status, body = client.request("/api/trade/analyze-multi", built["three"])
    verdict = (
        _fail("network_error")
        if status is None
        else classify_multi(status, body, meta["threeTeamRosterIds"])
    )
    checks.append(
        {
            "id": "analyze_multi_3team",
            "rosterIds": meta["threeTeamRosterIds"],
            "assetIds": meta["assetIds"],
            **verdict,
        }
    )
    return _summary(league, checks)


def _summary(league: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    ok = bool(checks) and all(c.get("status") == "pass" for c in checks) and len(checks) == 2
    return {"ok": ok, "league": league, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--origin", required=True)
    p.add_argument("--cookie-file", required=True)
    p.add_argument("--league", default="dynasty_main")
    p.add_argument("--timeout", type=float, default=120.0, help="per-request seconds")
    p.add_argument("--out", help="also write the JSON summary here")
    args = p.parse_args(argv)
    try:
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookie = fh.read().strip()
    except OSError:
        cookie = ""
    if not cookie:
        print("smoke_trade_analysis: unreadable or empty cookie file", file=sys.stderr)
        return EXIT_USAGE
    client = Client(args.origin, cookie, args.timeout, lambda m: print(m, file=sys.stderr))
    summary = run(client, args.league)
    text = json.dumps(summary, sort_keys=True)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    for c in summary["checks"]:
        if c.get("status") != "pass":
            print(f"::error title=Trade smoke::{c['id']} failed: {c.get('code')}", file=sys.stderr)
    return EXIT_PASS if summary["ok"] else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
