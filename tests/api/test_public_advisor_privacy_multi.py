"""Lane E: public Trade Advisor privacy for the N-team product -- M1, M2, M3,
M5, M6, the recursive value-free scan, the no-writes proof, the canonical
public ordering rule (§4.2), the public error codes (§4.5) and the
forbidden-word scan (§4.4).  TEST-ONLY (spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §7, Lane E row).

The M-numbers are the privacy findings in
``docs/trade/advisor_evidence/PRIVACY_ABUSE_VERIFICATION.md`` /
``BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md``; the spec cites them as:

* **M1** asset-only market fairness: Team Context (posture, projections,
  roster capacity, forced drops) never reaches the public path (SD-3, I11).
* **M2** no value order: the only asset order is ``position_alpha`` (§4.2, SD-8).
* **M3** coarse output only: FAIR / NOT FAIR / UNABLE and fixed copy -- no band
  level, gap, percentage, magnitude or direction (SD-4).
* **M5** ``send_and_receive`` participation: gifts and one-sided shapes are
  refused before any evaluation (SD-5), so no zero anchor can be probed.
* **M6** all teams in ONE response: a perspective only selects the default view.

Everything runs through the REAL routes on the Lane E scenario boards (eleven
boards x 2/3/4-team seeded ledgers; ``tests/parity/surface_harness.py``), not
on the one clean league the older suites use.

Already pinned elsewhere -- NOT repeated here:

* ``test_public_trade_advisor_privacy.py``: sentinel + vocabulary scan of the
  clean ``main`` league (12 fixed trades), no-store, same body from every
  perspective, order/shuffle independence, posture + projection invariance,
  a pure-function asset order (one randomised board), ``sort`` allowlist,
  function-level value-free assertion, schema introspection, copy tables,
  reducer isolation, writer tripwires, bounded error echo, floor, limiter.
* ``test_public_trade_advisor_validation.py``: each ledger reason once, schema
  400s, 409 without the owner, launch gate, flag-off.
* ``tests/trade/test_public_advisor_*.py``: reduction == private fairness on
  fixed shapes (I11), withheld-value fail-closed, client copy parity.

What this module adds:

1. a **closed-world recursive scan** of every public route from every
   perspective: every numeric leaf is an allowlisted roster/season/limit int,
   every string key is classified (enum, fixed copy, identity or pattern), every
   reason is in the §4.4 / §4.5 allowlists, no internal engine code, no raw
   Sleeper id, and -- differentially -- no number the PRIVATE engine computed for
   the same ledger (gap, VA, utility, percentage, value) appears in the body,
   on boards whose values are unmistakable sentinels;
2. **M1** at the object boundary: the engine result the reducer is handed carries
   no capacity, posture, roster utility or final roster, with every Team Context
   entry point booby-trapped on every board including over-cap;
3. **M2** against an independent §4.2 oracle on a hostile roster (ties, case,
   unknown positions, ids) and under value / roster-order / quarantine churn;
4. **M3** magnitude and direction invariance: same ledger, wildly different
   gaps -> byte-identical body;
5. **M5** across every one-sided shape at N = 2, 3, 4, and the zero-anchor
   corollary (an unpriced asset yields UNABLE, never a verdict);
6. **M6** perspective probing;
7. a **no-writes** proof at the OS level (files, directories, SQLite, the
   decision log) with a private control that does write;
8. the **§4.5 table** executed row by row, the "never a 500 or a trace" rule at
   every handler seam, and the **§4.4 forbidden-word scan** of the server copy
   and of the League Hub client sources.
"""

from __future__ import annotations

import builtins
import collections
import contextlib
import copy
import io
import json
import os
import random
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.api import public_trade_advisor_api as api
from src.trade import analyze_service as svc
from src.trade import public_advisor
from tests.parity import surface_harness as H
from tests.parity.surface_harness import (  # noqa: F401 -- pytest fixtures, used by name
    surface_client_fixture,
    world_factory_fixture,
)
from tests.trade import multi_team_support as mts
from tests.trade import test_multi_team_properties as P
from tests.trade.test_multi_team_properties import _pinned  # noqa: F401 -- autouse pins

REPO = Path(__file__).resolve().parents[2]
TEAMS_URL = H.TEAMS_URL
ANALYZE = H.ANALYZE
TEAM_COUNTS = (2, 3, 4)


def assets_url(rid: Any, *query: str) -> str:
    url = f"{TEAMS_URL}/{rid}/assets"
    return url + ("?" + "&".join(query) if query else "")


def leg(asset: str, frm: int, to: int) -> dict[str, Any]:
    return {"id": asset, "from": frm, "to": to}


# ══ Spec literals (§4.3 / §4.4 / §4.5), written from the spec, not the code ═══

#: §4.3 "Numbers allowed in public payloads".  ``perspectiveRosterId`` and the
#: leg endpoints ``from`` / ``to`` are roster ids by the §4.3 request/response
#: examples.
SPEC_INT_KEYS = frozenset(
    {
        "rosterId",
        "rosterIds",
        "originRosterId",
        "teamCount",
        "season",
        "round",
        "minTeams",
        "maxTeams",
        "maxLegs",
        "retryAfterSeconds",
        "maxBytes",
        "perspectiveRosterId",
        "from",
        "to",
    }
)
SPEC_TEAM_TEXT = {
    "within_fairness_threshold": "This trade is within our fairness threshold for this team.",
    "outside_fairness_threshold": "This trade falls outside our fairness threshold for this team.",
    "asset_not_evaluable": (
        "One or more assets this team sends or receives can't be valued right now."
    ),
    "ownership_unverifiable": (
        "We couldn't confirm who owns every asset this team sends or receives."
    ),
    "evaluation_unavailable": "This trade can't be evaluated reliably right now.",
}
SPEC_OVERALL_TEXT = {
    "all_teams_fair": "The trade is within our fairness threshold for every team.",
    "not_all_teams_fair": "The trade falls outside our fairness threshold for at least one team.",
    "evidence_insufficient": "There isn't enough reliable information to judge this whole trade.",
}
SPEC_MULTI_TEAM_NOTE = (
    "A trade with more than two teams is fair only when it is fair for every team."
)
SPEC_OVERALL_LABEL = {
    "FAIR": "FAIR TRADE",
    "NOT_FAIR": "NOT FAIR",
    "UNABLE_TO_DETERMINE": "UNABLE TO DETERMINE",
}
SPEC_TEAM_LABEL = {
    "FAIR": "FAIR FOR THIS TEAM",
    "NOT_FAIR": "NOT FAIR FOR THIS TEAM",
    "UNABLE_TO_DETERMINE": "UNABLE TO DETERMINE",
}
SPEC_TEAM_REASONS_BY_RESULT = {
    "FAIR": {"within_fairness_threshold"},
    "NOT_FAIR": {"outside_fairness_threshold"},
    "UNABLE_TO_DETERMINE": {
        "asset_not_evaluable",
        "ownership_unverifiable",
        "evaluation_unavailable",
    },
}
SPEC_OVERALL_REASON_BY_RESULT = {
    "FAIR": "all_teams_fair",
    "NOT_FAIR": "not_all_teams_fair",
    "UNABLE_TO_DETERMINE": "evidence_insufficient",
}
SPEC_LEDGER_REASONS = (
    "too_few_teams",
    "duplicate_team",
    "too_many_teams",
    "team_not_in_league",
    "empty_trade",
    "too_many_assets",
    "unknown_asset",
    "duplicate_asset",
    "invalid_origin",
    "invalid_destination",
    "destination_is_origin",
    "idle_team",
    "one_sided_trade",
)
#: §4.5, one row per ``(status, error, reason)``.  The spec's "400 / 404" row
#: is, per the league-key predicate and the GET path rule: unknown and
#: inactive league 400, no public snapshot 404, unknown roster id 404.
SPEC_ERROR_ROWS = frozenset(
    {
        (400, "invalid_request", "invalid_json"),
        (400, "invalid_request", "schema"),
        (400, "invalid_request", "unsupported_sort"),
        (400, "invalid_request", "invalid_roster_id"),
        (400, "invalid_trade", "perspective_not_in_trade"),
        *((400, "invalid_trade", r) for r in SPEC_LEDGER_REASONS),
        (409, "stale_assets", "asset_not_owned"),
        (400, "unknown_league", None),
        (400, "inactive_league", None),
        (404, "league_not_public", None),
        (404, "unknown_team", None),
        (413, "payload_too_large", None),
        (415, "unsupported_media_type", None),
        (429, "rate_limited", None),
        (503, "advisor_unavailable", "disabled"),
        (503, "advisor_unavailable", "not_ready"),
        (503, "advisor_unavailable", "upstream_unavailable"),
    }
)
#: §6.3 admission control: retryable 503s with their own reasons.
SPEC_ADMISSION_ROWS = frozenset(
    {(503, "advisor_unavailable", "busy"), (503, "advisor_unavailable", "timeout")}
)
SPEC_ERROR_CODES = {e for _s, e, _r in SPEC_ERROR_ROWS | SPEC_ADMISSION_ROWS}
SPEC_ERROR_REASONS = {r for _s, _e, r in SPEC_ERROR_ROWS | SPEC_ADMISSION_ROWS if r}
#: §4.2 position order; "then any other".
SPEC_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
SPEC_SIDE = {
    **dict.fromkeys(("QB", "RB", "WR", "TE", "K"), "offense"),
    **dict.fromkeys(("DL", "LB", "DB"), "defense"),
}


#: Private engine / decision vocabulary that must never surface in a public
#: analyze or error body (read from the owners, so a new code is covered).
def _internal_tokens() -> frozenset[str]:
    from src.trade import team_verdicts, trade_decision

    public = (
        set(SPEC_TEAM_TEXT)
        | set(SPEC_OVERALL_TEXT)
        | SPEC_ERROR_CODES
        | SPEC_ERROR_REASONS
        | {"success", "current", "stale", "unknown", "observed", "unavailable"}
    )
    internal = {
        *trade_decision.ASSET_EVIDENCE_GATE_CODES,
        *team_verdicts._GAP_REASON,
        *svc.VALUE_STATES,
        *team_verdicts.CATEGORIES,
        "roster_limit",
        "posture_unknown",
        "roster_unknown",
        "owner_identity_ambiguous",
        "team_not_in_league_bundle",
        "not_computed_multi_team",
        "not_requested_market_fairness",
        "executionGate",
        "NO_TOO_CLOSE",
        "NOT_ENOUGH_EVIDENCE",
        "slight",
        "unfair",
        "lopsided",
        "geom_q078_v1",
        "ktc_2026_04",
    }
    return frozenset(t.lower() for t in internal if t not in public)


INTERNAL_TOKENS = _internal_tokens()

ASSET_ID = re.compile(r"^(?:p:[A-Za-z0-9]{1,16}|pick:[A-Za-z0-9_-]{1,32}:\d{4}:r\d{1,2}:o\d{1,2})$")
ASSET_ID_IN_TEXT = re.compile(r"\b(?:p:[A-Za-z0-9]+|pick:[A-Za-z0-9:_-]+)")
#: §4.5 P3: an error echoes only request-supplied ids of the inbound pattern.
ECHO_ID = re.compile(r"^[A-Za-z0-9:_-]{1,64}$")
GENERATION = re.compile(r"^[0-9a-f]{16}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELD_PATH = re.compile(r"^[A-Za-z0-9_.]{1,64}$")
#: Identifiers that must never appear in a public body: the registry's raw
#: Sleeper league ids, and the synthetic owner / user ids.
RAW_IDS = ("L-SYNTH-7731", "L-SIDE-0042", "L-RET-0043", "owner1", "owner2", "owner3", "owner4")
RAW_ID_KEYS = frozenset(
    k.lower()
    for k in (
        "leagueId",
        "rootLeagueId",
        "leagueIds",
        "currentLeagueId",
        "previousLeagueId",
        "stoppedAtLeagueId",
        "failedLeagueId",
        "draftId",
        "ownerId",
        "owner_id",
        "userId",
        "user_id",
        "sleeperUserId",
        "sleeperLeagueId",
        "sleeper_league_id",
    )
)
#: Keys no advisor body may carry (spec §4.6 item 3) plus the value-bearing and
#: Team Context names this suite adds.
FORBIDDEN_KEYS = frozenset(
    {
        *public_advisor.ADVISOR_KEY_BLOCKLIST,
        "values",
        "rankDerivedValue",
        "adjusted",
        "va",
        "utility",
        "utilities",
        "pct",
        "percent",
        "percentage",
        "magnitude",
        "direction",
        "posture",
        "competitivePosture",
        "projections",
        "rosterCapacity",
        "rosterLimit",
        "forcedDrops",
        "capacity",
        "confidence",
        "confidenceBucket",
        "rank",
        "tier",
    }
)


# ══ The closed-world recursive scan ════════════════════════════════════════════


def _leaves(obj: Any, key: str = "$", path: str = "$"):
    """``(path, key, leaf)`` for every leaf; a list item inherits its list's key."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, str(k), f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _leaves(v, key, f"{path}[{i}]")
    else:
        yield path, key, obj


def _all_keys(obj: Any, path: str = "$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", str(k)
            yield from _all_keys(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _all_keys(v, f"{path}[{i}]")


def token_present(text: str, token: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z.]){re.escape(token)}(?![0-9A-Za-z])", text) is not None


def _scrub(text: str) -> str:
    """Remove the by-design identifiers (asset ids, the opaque generation, the
    roster-freshness date) before number tokens are searched for."""
    text = ASSET_ID_IN_TEXT.sub(" ", text)
    text = re.sub(r'"generation":\s*"[^"]*"', '"generation": ""', text)
    return re.sub(r'"asOf":\s*"[^"]*"', '"asOf": ""', text)


def _check_string(key: str, value: str, path: str, *, kind: str, ctx: Any) -> None:
    where = (ctx, path, key, value)
    if key in ("status",):
        assert value == "success", where
    elif key == "leagueKey":
        assert value == H.KEY or value in ("side", "retired"), where
    elif key == "generation":
        assert GENERATION.match(value), where
    elif key == "fairnessVersion":
        assert re.fullmatch(r"fairness_bands_v\d+", value), where
    elif key == "state":  # rosters.state
        assert value in ("current", "stale", "unknown"), where
    elif key == "asOf":
        assert ISO_DATE.match(value), where
    elif key == "result":
        assert value in SPEC_OVERALL_LABEL, where
    elif key == "reasonCode":
        assert ".overall." in path + "." or ".teams[" in path, where
        allowed = set(SPEC_OVERALL_TEXT) if ".overall." in path + "." else set(SPEC_TEAM_TEXT)
        assert value in allowed, where
    elif key == "reason":
        assert value in SPEC_ERROR_REASONS, where
    elif key == "error":
        assert value in SPEC_ERROR_CODES, where
    elif key == "field":
        assert FIELD_PATH.match(value) and not value.isdigit(), where
    elif key in ("reasonText", "message", "note", "label") and kind in ("analyze", "error"):
        assert value in public_advisor.FIXED_TEXT, where
        assert not re.search(r"[0-9%$]", value), where  # no proprietary number in copy
    elif key == "assetIds":  # error echo: request-supplied, inbound pattern only (P3)
        assert kind == "error" and ECHO_ID.match(value), where
    elif key in ("id", "unavailableAssetIds"):
        assert ASSET_ID.match(value), where
    elif key == "sort":
        assert value == "position_alpha", where
    elif key == "pickOwnership":
        assert value in ("observed", "unavailable"), where
    elif key == "kind":
        assert value in ("player", "pick"), where
    elif key == "side":
        assert value in ("offense", "defense", "other", "pick"), where
    elif key == "projection":
        raise AssertionError(("a pick projection label is OFF (OD-2)", *where))
    elif key in ("position", "nflTeam", "displayName", "teamName", "label") and kind == "list":
        pass  # league identity data (names / positions), never a value
    else:
        raise AssertionError(("unclassified string field", *where))


def scan_json(body: Any, *, kind: str, ctx: Any = None) -> None:
    """The closed-world value-free scan of one advisor body.

    ``kind`` is ``analyze`` / ``error`` / ``list``.  Independent of
    ``public_advisor.assert_advisor_payload_value_free`` (and cross-checked
    against it by :func:`scan_response`)."""
    for path, key in _all_keys(body):
        assert key not in FORBIDDEN_KEYS, (ctx, "forbidden key", path)
        assert key.lower() not in RAW_ID_KEYS, (ctx, "raw id key", path)
    for path, key, leaf in _leaves(body):
        if leaf is None or isinstance(leaf, bool):
            continue
        assert not isinstance(leaf, float), (ctx, "float", path)
        if isinstance(leaf, int):
            assert key in SPEC_INT_KEYS, (ctx, "non-allowlisted number", path, leaf)
            assert 0 <= leaf <= 100000, (ctx, path, leaf)
        elif isinstance(leaf, str):
            _check_string(key, leaf, path, kind=kind, ctx=ctx)
        else:
            raise AssertionError((ctx, "unexpected leaf type", path, type(leaf)))
    if kind != "analyze":
        return
    # Self-consistency of the public vocabulary (spec §4.3 / §2.9).
    overall, teams = body["overall"], body["teams"]
    assert overall["label"] == SPEC_OVERALL_LABEL[overall["result"]], ctx
    assert overall["reasonCode"] == SPEC_OVERALL_REASON_BY_RESULT[overall["result"]], ctx
    assert overall["reasonText"] == SPEC_OVERALL_TEXT[overall["reasonCode"]], ctx
    assert (overall["note"] == SPEC_MULTI_TEAM_NOTE) == (body["teamCount"] >= 3), ctx
    assert overall["note"] in (None, SPEC_MULTI_TEAM_NOTE), ctx
    for row in teams:
        assert row["label"] == SPEC_TEAM_LABEL[row["result"]], (ctx, row)
        assert row["reasonCode"] in SPEC_TEAM_REASONS_BY_RESULT[row["result"]], (ctx, row)
        assert row["reasonText"] == SPEC_TEAM_TEXT[row["reasonCode"]], (ctx, row)
        assert row["unavailableAssetIds"] == sorted(row["unavailableAssetIds"]), (ctx, row)
        if row["reasonCode"] not in ("asset_not_evaluable", "ownership_unverifiable"):
            assert row["unavailableAssetIds"] == [], (ctx, row)
    results = [r["result"] for r in teams]
    kleene = (
        "NOT_FAIR"
        if "NOT_FAIR" in results
        else "UNABLE_TO_DETERMINE"
        if "UNABLE_TO_DETERMINE" in results
        else "FAIR"
    )
    assert overall["result"] == kleene, (ctx, results, overall)  # §2.9
    # No token of the private vocabulary anywhere in an analyze body.
    for path, _key, leaf in _leaves(body):
        if isinstance(leaf, str) and not ASSET_ID.match(leaf):
            for tok in re.findall(r"[A-Za-z_]+", leaf):
                assert tok.lower() not in INTERNAL_TOKENS, (ctx, "internal token", path, tok)


def _numbers(obj: Any):
    for _path, _key, leaf in _leaves(obj):
        if isinstance(leaf, (int, float)) and not isinstance(leaf, bool):
            yield leaf


def private_number_tokens(private_body: Any, public_body: Any) -> set[str]:
    """Every number the PRIVATE engine published for a ledger (values, gaps,
    VA, utilities, percentages, ...) that the public body is not itself
    entitled to carry, as the decimal strings a leak would print."""
    # Entitled: roster ids / counts (< 100), seasons, and the declared limits.
    # A big number under an allowlisted key is NOT entitled -- it is the leak
    # the closed-world key check cannot see.
    entitled = {
        leaf
        for _p, key, leaf in _leaves(public_body)
        if isinstance(leaf, int)
        and not isinstance(leaf, bool)
        and (leaf < 100 or 2000 <= leaf <= 2100 or key in ("maxBytes", "maxLegs"))
    }
    out: set[str] = set()
    for n in _numbers(private_body):
        # Whole numbers from 100 up (values, gaps, sums); any fraction from 1
        # up (percentages, utilities).  Smaller whole numbers are ids/counts.
        if n in entitled or not (abs(n) >= 100 or (not float(n).is_integer() and abs(n) >= 1)):
            continue
        out.add(str(int(n)) if float(n).is_integer() else repr(float(n)))
        out.add(f"{abs(float(n)):.0f}")
        if not float(n).is_integer():
            out.add(f"{abs(float(n)):.1f}")
            out.add(f"{abs(float(n)):.2f}")
    return {t for t in out if len(t) >= 3}


def scan_response(
    res: Any,
    *,
    kind: str,
    ctx: Any,
    board_tokens: frozenset[str] = frozenset(),
    private_body: Any = None,
) -> Any:
    """Scan one HTTP response: headers, body JSON (closed world), raw ids, the
    sentinel board numbers and -- when given -- every number the private
    engine computed for the same ledger."""
    lowered = {k.lower() for k in res.headers}
    assert res.headers.get("cache-control") == "no-store", (ctx, res.status_code)
    assert not {"server-timing", "set-cookie", "x-powered-by"} & lowered, (ctx, lowered)
    body = res.json()
    scan_json(body, kind=kind, ctx=ctx)
    public_advisor.assert_advisor_payload_value_free(body, kind=kind)  # the module agrees
    blob = res.text + "\n" + "\n".join(f"{k}: {v}" for k, v in res.headers.items())
    for ident in RAW_IDS:
        assert ident not in blob, (ctx, "raw id", ident)
    scrubbed = _scrub(res.text)
    for token in board_tokens:
        assert not token_present(scrubbed, token), (ctx, "board value", token)
    if private_body is not None:
        for token in private_number_tokens(private_body, body):
            assert not token_present(scrubbed, token), (ctx, "private number", token)
    return body


# ══ Sentinel boards ════════════════════════════════════════════════════════════


def sentinelize(contract: dict[str, Any]) -> None:
    """Scale every board value to an unmistakable 4-6 digit sentinel (x17.31,
    plus a per-row offset): gaps keep their relative size, so FAIR / NOT FAIR
    still occur, but no board value can be mistaken for an id or a count."""
    n = 0
    for row in contract["playersArray"]:
        v = row.get("rankDerivedValue")
        if isinstance(v, (int, float)) and v > 0:
            n += 1
            nv = float(round(v * 17.31) + n)
            row["rankDerivedValue"] = nv
            if isinstance(row.get("values"), dict) and row["values"]:
                row["values"] = {"full": nv}


def board_tokens(contract: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        str(int(r["rankDerivedValue"]))
        for r in contract["playersArray"]
        if isinstance(r.get("rankDerivedValue"), (int, float)) and r["rankDerivedValue"] > 0
    )


# ══ 1. The recursive value-free scan: every route, every perspective ═══════════


def test_the_scan_covers_exactly_the_public_routes_the_spec_lists():
    import server

    paths = {
        p: sorted(m.upper() for m in ops)
        for p, ops in server.app.openapi()["paths"].items()
        if p.startswith("/api/public/league/trade-advisor")
    }
    assert paths == {
        "/api/public/league/trade-advisor/teams": ["GET"],
        "/api/public/league/trade-advisor/teams/{rosterId}/assets": ["GET"],
        "/api/public/league/trade-advisor/analyze": ["POST"],
    }


def test_the_scan_allowlist_is_the_spec_allowlist():
    assert public_advisor.ALLOWED_INT_KEYS == SPEC_INT_KEYS
    assert (
        set(SPEC_TEAM_TEXT.values()) | set(SPEC_OVERALL_TEXT.values()) | {SPEC_MULTI_TEAM_NOTE}
        <= public_advisor.FIXED_TEXT
    )
    assert public_advisor.TEAM_REASON_TEXT == SPEC_TEAM_TEXT
    assert public_advisor.OVERALL_REASON_TEXT == SPEC_OVERALL_TEXT
    assert public_advisor.OVERALL_LABELS == SPEC_OVERALL_LABEL
    assert public_advisor.TEAM_LABELS == SPEC_TEAM_LABEL
    assert INTERNAL_TOKENS >= {"quarantined_values", "stale_values", "off_board", "roster_limit"}


def test_the_scanner_has_teeth_on_each_leak_class():
    """A scanner that cannot fail proves nothing: seed one body per leak class."""
    ok = {
        "status": "success",
        "leagueKey": "synth",
        "generation": "0123456789abcdef",
        "fairnessVersion": "fairness_bands_v2",
        "snapshotChanged": None,
        "rosters": {"state": "current", "asOf": "2026-10-20"},
        "teamCount": 2,
        "perspectiveRosterId": 1,
        "overall": {
            "result": "FAIR",
            "label": "FAIR TRADE",
            "reasonCode": "all_teams_fair",
            "reasonText": SPEC_OVERALL_TEXT["all_teams_fair"],
            "note": None,
        },
        "teams": [
            {
                "rosterId": r,
                "result": "FAIR",
                "label": "FAIR FOR THIS TEAM",
                "reasonCode": "within_fairness_threshold",
                "reasonText": SPEC_TEAM_TEXT["within_fairness_threshold"],
                "unavailableAssetIds": [],
            }
            for r in (1, 2)
        ],
        "trade": [{"id": "p:101", "from": 1, "to": 2}, {"id": "p:201", "from": 2, "to": 1}],
    }
    scan_json(ok, kind="analyze")

    def with_team(**kw):
        b = copy.deepcopy(ok)
        b["teams"][0].update(kw)
        return b

    leaks = {
        "value key": with_team(value=4312),
        "gap key": {**ok, "gap": 4},
        "float": {**ok, "teamCount": 2.0},
        "unlisted int": {**ok, "extra": 3},
        "internal reason code": with_team(reasonCode="quarantined_values"),
        "reason not in result class": with_team(reasonCode="outside_fairness_threshold"),
        "non-spec text": with_team(reasonText="This trade is close."),
        "number in copy": with_team(reasonText="Within 250 points."),
        "raw sleeper key": {**ok, "leagueId": "1312006700437352448"},
        "owner key": {**ok, "ownerId": "x"},
        "private vocabulary": with_team(label="ACCEPT"),
        "projection label": {**ok, "projection": "mid"},
        "inconsistent overall": {**ok, "overall": {**ok["overall"], "result": "NOT_FAIR"}},
        "unsorted unavailable ids": with_team(
            result="UNABLE_TO_DETERMINE",
            label="UNABLE TO DETERMINE",
            reasonCode="asset_not_evaluable",
            reasonText=SPEC_TEAM_TEXT["asset_not_evaluable"],
            unavailableAssetIds=["p:2", "p:1"],
        ),
    }
    for name, body in leaks.items():
        with pytest.raises(AssertionError):
            scan_json(body, kind="analyze", ctx=name)
    assert token_present('{"a": 4314, "b": "x"}', "4314")
    assert not token_present('{"id": "ab4314cd"}', "4314")
    assert not token_present('{"x": 14314}', "4314")

    # The differential net catches a private number hiding under an allowlisted
    # key (the closed-world scan alone would pass ``rosterId: 4314``).
    class _Res:
        status_code = 200
        headers = {"cache-control": "no-store"}
        text = '{"teams": [{"rosterId": 4314}]}'

        def json(self):
            return json.loads(self.text)

    scan_response(_Res(), kind="list", ctx="control")
    with pytest.raises(AssertionError):
        scan_response(_Res(), kind="list", ctx="control", private_body={"net": {"gap": 4314}})
    with pytest.raises(AssertionError):
        scan_response(_Res(), kind="list", ctx="control", board_tokens=frozenset({"4314"}))
    # The differential harvest: private numbers the public body is not
    # entitled to (a season the body itself carries is entitled).
    priv = {"a": {"gap": 4314, "relativePct": 34.04, "v": [12673.76, 2026, 7]}}
    tokens = private_number_tokens(priv, {"season": 2026, "teamCount": 2})
    assert {"4314", "34.04", "12673.76", "12674"} <= tokens
    assert "2026" not in tokens and "7" not in tokens


def test_recursive_value_free_scan_of_every_route_from_every_perspective(world_factory):
    """Every public route, every perspective, 2/3/4 teams, every Lane E board,
    on SENTINEL values: closed-world scan + raw ids + sentinel numbers + (for
    analyze) every number the private engine computed for the same ledger."""
    seen_team_reasons: set[str] = set()
    seen_overall: set[str] = set()
    seen_results: set[str] = set()
    pick_states: set[str] = set()
    harvest_sizes: list[int] = []
    scanned = collections.Counter()
    for scenario in H.SCENARIOS:
        w = world_factory(scenario, mutate=sentinelize)
        tokens = board_tokens(w.contract)
        assert len(tokens) >= 10

        def check(res, kind, ctx, private=None, _w=w, _tokens=tokens):
            body = scan_response(
                res, kind=kind, ctx=ctx, board_tokens=_tokens, private_body=private
            )
            scanned[kind] += 1
            return body

        # Lists: teams (default and explicit league), every roster's assets.
        teams_body = check(w.client.get(TEAMS_URL), "list", (scenario, "teams"))
        assert [t["rosterId"] for t in teams_body["teams"]] and teams_body["leagueKey"] == H.KEY
        check(w.client.get(TEAMS_URL + f"?leagueKey={H.KEY}"), "list", (scenario, "teams-key"))
        for rid in (1, 2, 3, 4):
            body = check(w.client.get(assets_url(rid)), "list", (scenario, "assets", rid))
            pick_states.add(body["pickOwnership"])
            check(
                w.client.get(assets_url(rid, "sort=position_alpha")),
                "list",
                (scenario, "assets-sorted", rid),
            )
        for bad in (assets_url(9), assets_url("x"), assets_url(1, "sort=value_desc")):
            check(w.client.get(bad), "error", (scenario, bad))
        # Analyze: seeded ledgers, every perspective.
        for n in TEAM_COUNTS:
            for teams, legs in H.corpus(w, n, tag="scan"):
                private = w.private(teams, legs, team_context=True)
                harvest_sizes.append(len(private_number_tokens(private, {"teamCount": n})))
                for perspective in teams:
                    ctx = (scenario, n, teams, legs, perspective)
                    body = check(
                        w.public_response(teams, legs, perspective), "analyze", ctx, private
                    )
                    seen_results |= {t["result"] for t in body["teams"]}
                    seen_team_reasons |= {t["reasonCode"] for t in body["teams"]}
                    seen_overall.add(body["overall"]["reasonCode"])
        # Refusals on the same board.
        check(w.public_response([1, 2], [leg("p:101", 1, 2)], 1), "error", (scenario, "one-sided"))
        check(
            w.public_response([1, 2], [leg("p:201", 1, 2), leg("p:102", 2, 1)], 1),
            "error",
            (scenario, "stale"),
        )
    assert seen_results == {"FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"}
    assert seen_overall == set(SPEC_OVERALL_TEXT)
    assert seen_team_reasons == set(SPEC_TEAM_TEXT)
    assert pick_states == {"observed", "unavailable"}
    assert scanned["analyze"] >= 150 and scanned["list"] >= 100 and scanned["error"] >= 40
    # The differential scan had real private numbers to look for every time.
    assert min(harvest_sizes) >= 6, min(harvest_sizes)


# ══ M1: Team Context never reaches the public path (SD-3, I11) ═════════════════

#: Every Team Context entry point.  ``setattr`` is strict (``raising=True``): a
#: renamed seam fails loudly here instead of silently un-booby-trapping.
TEAM_CONTEXT_SEAMS = (
    ("src.api.trade_simulator", "competitive_posture_for"),
    ("src.api.trade_simulator", "league_posture_bundle"),
    ("src.api.gameplan", "league_competitive_postures"),
    ("src.roster_intel.best_ball_utility", "evaluate_trade_utility"),
    ("src.trade.roster_capacity", "build_capacity_context"),
    ("src.trade.roster_capacity", "evaluate_final_roster_utility"),
    ("src.trade.roster_capacity", "league_scarcity"),
)
M1_SCENARIOS = ("clean", "over_cap", "traded_picks", "quarantined", "pick_unknown")


@contextlib.contextmanager
def _capturing_engine(monkeypatch):
    """Record ``(mode, ledger, engine result)`` for every ``analyze_trade_n``
    call made inside the block."""
    calls: list[tuple[Any, Any, Any]] = []
    real = svc.analyze_trade_n

    def spy(snap, ledger, **kw):
        out = real(snap, ledger, **kw)
        calls.append((kw.get("mode"), ledger, out))
        return out

    with monkeypatch.context() as m:
        m.setattr(svc, "analyze_trade_n", spy)
        yield calls


def test_m1_every_team_context_entry_point_is_unreachable_from_the_public_route(
    world_factory, monkeypatch
):
    import importlib

    controls = 0
    for scenario in M1_SCENARIOS:
        w = world_factory(scenario)
        cases = [c for n in TEAM_COUNTS for c in H.corpus(w, n, tag="m1")]
        reference = [w.public(t, lg, t[0]) for t, lg in cases]
        reached: list[str] = []
        with monkeypatch.context() as m:
            for module, attr in TEAM_CONTEXT_SEAMS:
                m.setattr(
                    importlib.import_module(module),
                    attr,
                    lambda *a, _n=f"{module}.{attr}", **k: reached.append(_n),
                )
            with _capturing_engine(m) as calls:
                got = [w.public(t, lg, t[0]) for t, lg in cases]
        assert reached == [], (scenario, reached)
        assert got == reference, scenario
        assert len(calls) == len(cases)
        for mode, _ledger, out in calls:
            assert mode == "market_fairness"
            for rid, entry in out["teams"].items():
                sim = entry["simulation"]
                ctx = (scenario, rid)
                # Team Context is absent from the object the reducer is handed.
                assert sim.get("rosterCapacity") is None, ctx
                assert sim.get("finalRosterSimulation") is None, ctx
                assert sim.get("rosterUtility") is None, ctx
                assert sim["competitivePosture"] == {
                    "available": False,
                    "unavailableReason": "not_requested_market_fairness",
                }, ctx
                assert sim["teamContext"] == {"applied": False, "mode": "asset_only"}, ctx
        # Control: the SAME ledger in a private mode does carry capacity.
        teams, legs = cases[0]
        asset_only = w.engine(w.ledger(teams, legs), "asset_only")
        controls += any(
            e["simulation"].get("rosterCapacity") is not None for e in asset_only["teams"].values()
        )
    assert controls == len(M1_SCENARIOS)


def test_m1_forced_drops_are_privately_real_and_publicly_invisible(world_factory):
    """Roster size 3 on four-to-five-player rosters: the private route reports
    forced drops, and nothing about them -- no word, key or number -- reaches
    the public body, which equals the one from a roster that fits."""
    base = world_factory("clean")
    tight = world_factory(
        "clean", settings=base.settings | {"rosterSize": 3}, contract=base.contract
    )
    banned = re.compile(
        r"roster[ _]?limit|forced|release|\bdrop|\bcut\b|capacity|posture|projection|"
        r"retool|rebuild|contend|\bpush\b",
        re.I,
    )
    forced = 0
    for n in TEAM_COUNTS:
        for teams, legs in H.corpus(tight, n, tag="m1-drops"):
            private = tight.private(teams, legs, team_context=True, counterfactuals=False)
            forced += sum(
                bool((t["simulation"].get("rosterCapacity") or {}).get("forcedDrops"))
                for t in private["teams"]
            )
            res = tight.public_response(teams, legs, teams[0])
            body = scan_response(res, kind="analyze", ctx=(n, teams, legs), private_body=private)
            assert not banned.search(json.dumps(body)), (teams, legs)
            fits = base.public(teams, legs, teams[0])
            assert body == fits, (teams, legs)
    assert forced > 0, "no forced drop occurred, so the invariance above proved nothing"


# ══ M2: no value order (§4.2, SD-8) ════════════════════════════════════════════

#: (playerId, display name, position, board value).  Ties on label, case and
#: casefold; unknown and missing positions; the DL / DB aliases; ids that sort
#: differently as text and as numbers.
HOSTILE_ROSTER = (
    ("7001", "Twin Name", "WR", 1000.0),
    ("7002", "Twin Name", "WR", 9000.0),
    ("7003", "alpha one", "WR", 10.0),
    ("7004", "Alpha Two", "WR", 20.0),
    ("7005", "ALPHA ONE", "WR", 5000.0),
    ("7006", "Ärger Zed", "TE", 100.0),
    ("7007", "Zed Ärger", "TE", 8000.0),
    ("7008", "Edge Rusher", "EDGE", 4000.0),
    ("7009", "Safety Man", "S", 300.0),
    ("7010", "Kicker One", "K", 50.0),
    ("7011", "Punter Pete", "PK", 60.0),
    ("7012", "Fullback Fred", "FB", 70.0),
    ("7013", "Unknown Pos", None, 80.0),
    ("7014", "Another Unknown", "XYZ", 90.0),
    ("900", "Same Label", "RB", 400.0),
    ("1000", "Same Label", "RB", 400.0),
)


def add_hostile_roster(contract: dict[str, Any]) -> None:
    team = contract["sleeper"]["teams"][0]  # roster 1
    for pid, name, pos, value in HOSTILE_ROSTER:
        contract["playersArray"].append(mts._row(pid, name, pos, value))
        team["playerIds"].append(pid)
        team["players"].append(name)


def spec_order(assets: list[dict[str, Any]]) -> list[str]:
    """§4.2 written from the spec: players by (side group, position, casefold
    label, id), then picks by (season, round, origin, id)."""
    side_rank = {"offense": 0, "defense": 1, "other": 2}

    def player_key(a: dict[str, Any]):
        pos = a["position"] or ""
        rank = SPEC_POSITIONS.index(pos) if pos in SPEC_POSITIONS else len(SPEC_POSITIONS)
        return (side_rank[a["side"]], rank, pos, a["label"].casefold(), a["id"])

    players = sorted((a for a in assets if a["kind"] == "player"), key=player_key)
    picks = sorted(
        (a for a in assets if a["kind"] == "pick"),
        key=lambda a: (a["season"], a["round"], a["originRosterId"], a["id"]),
    )
    return [a["id"] for a in players] + [a["id"] for a in picks]


def _assets(w: H.World, rid: int, *query: str) -> dict[str, Any]:
    res = w.client.get(assets_url(rid, *query))
    assert res.status_code == 200, res.text
    return scan_response(res, kind="list", ctx=("assets", rid))


def test_m2_asset_order_is_the_spec_order_on_a_hostile_roster(world_factory):
    w = world_factory("traded_picks", mutate=add_hostile_roster)
    body = _assets(w, 1)
    assets = body["assets"]
    ids = [a["id"] for a in assets]
    assert ids == spec_order(assets)
    assert len(ids) >= len(HOSTILE_ROSTER) + 4
    by_id = {a["id"]: a for a in assets}
    # Side is a function of position (spec §4.2); everything unknown is "other".
    for a in assets:
        if a["kind"] == "player":
            assert a["side"] == SPEC_SIDE.get(a["position"], "other"), a
        else:
            assert a["side"] == "pick", a
    assert by_id["p:7008"]["position"] == "DL" and by_id["p:7008"]["side"] == "defense"
    assert by_id["p:7009"]["position"] == "DB" and by_id["p:7009"]["side"] == "defense"
    assert by_id["p:7013"]["side"] == "other" and by_id["p:7013"]["position"] is None
    # Ties: casefold-equal labels fall to id; text id order, not numeric.
    assert ids.index("p:7001") < ids.index("p:7002")
    assert ids.index("p:7003") < ids.index("p:7005")  # "alpha one" == "ALPHA ONE"
    assert ids.index("p:1000") < ids.index("p:900")
    # Offense -> defense -> other, then picks last.
    sides = [a["side"] for a in assets]
    assert sides == sorted(sides, key=["offense", "defense", "other", "pick"].index)
    picks = [a for a in assets if a["kind"] == "pick"]
    assert len(picks) >= 3 and ids[-len(picks) :] == [p["id"] for p in picks]
    assert len({p["originRosterId"] for p in picks}) >= 2  # origin, not holder, orders them


def test_m2_every_board_orders_every_roster_by_the_spec_order(world_factory):
    for scenario in H.SCENARIOS:
        w = world_factory(scenario)
        for rid in (1, 2, 3, 4):
            assets = _assets(w, rid)["assets"]
            assert [a["id"] for a in assets] == spec_order(assets), (scenario, rid)


def _scramble(rng: random.Random, *, positive_only: bool):
    def mutate(contract: dict[str, Any]) -> None:
        add_hostile_roster(contract)
        for row in contract["playersArray"]:
            if "rankDerivedValue" not in row:
                continue
            if positive_only and not row["rankDerivedValue"]:
                continue  # an unpriced row stays unpriced: same priced pattern
            roll = rng.random()
            if not positive_only and roll < 0.25:
                row["rankDerivedValue"], row["values"] = None, {}
            elif not positive_only and roll < 0.35:
                row["quarantined"] = True
                row["anomalyFlags"] = ["no_valid_source_values"]
            else:
                v = float(rng.randint(1, 99999))
                row["rankDerivedValue"], row["values"] = v, {"full": v}
        # Roster and pick-inventory ORDER too (ids and names stay paired).
        for team in contract["sleeper"]["teams"]:
            pairs = list(zip(team["playerIds"], team["players"]))
            rng.shuffle(pairs)
            team["playerIds"], team["players"] = [p for p, _n in pairs], [n for _p, n in pairs]
            if team.get("pickDetails"):
                rng.shuffle(team["pickDetails"])

    return mutate


def test_m2_order_is_independent_of_board_values_roster_order_and_quarantine(world_factory):
    base = world_factory("traded_picks", mutate=add_hostile_roster)
    reference = {rid: _assets(base, rid) for rid in (1, 2, 3, 4)}
    rng = random.Random("m2-churn")
    for trial in range(6):
        positive = trial < 3
        w = world_factory("traded_picks", mutate=_scramble(rng, positive_only=positive))
        for rid in (1, 2, 3, 4):
            got = _assets(w, rid)
            assert [a["id"] for a in got["assets"]] == [
                a["id"] for a in reference[rid]["assets"]
            ], (trial, rid)
            if positive:
                # Same priced pattern, wildly different values: the WHOLE body
                # (labels, flags, order) is byte-identical.
                assert got == reference[rid], (trial, rid)


@pytest.mark.parametrize(
    "sort",
    [
        "value_desc",
        "value_asc",
        "VALUE_DESC",
        "value",
        "-value",
        "rank",
        "ktc",
        "adp",
        "alpha",
        "position",
        "POSITION_ALPHA",
        "position_alpha,value_desc",
        "position_alpha;value_desc",
        "position_alpha%00",
        "position_alpha%20",
        "%20position_alpha",
        "",
    ],
)
def test_m2_no_sort_value_selects_a_value_order(world_factory, sort):
    w = world_factory("clean")
    res = w.client.get(assets_url(1, f"sort={sort}"))
    assert res.status_code == 400, (sort, res.text)
    body = scan_response(res, kind="error", ctx=("sort", sort))
    assert body["reason"] == "unsupported_sort" and body["field"] == "sort"
    assert body["message"] == public_advisor.ERROR_MESSAGES[("invalid_request", "unsupported_sort")]


def test_m2_a_repeated_sort_parameter_still_cannot_select_a_value_order(world_factory):
    """The LAST value wins in the framework; either way the only answers are a
    400 or the one allowed order."""
    w = world_factory("clean")
    for query, status in (
        ("sort=value_desc&sort=position_alpha", 200),
        ("sort=position_alpha&sort=value_desc", 400),
        ("sort=position_alpha&sort=position_alpha", 200),
    ):
        res = w.client.get(assets_url(1, query))
        assert res.status_code == status, (query, res.text)
        body = res.json()
        if status == 200:
            assert body["sort"] == "position_alpha"
            assert [a["id"] for a in body["assets"]] == spec_order(body["assets"])


# ══ M3: coarse output only (SD-4) ══════════════════════════════════════════════

TOP_KEYS = {
    "status",
    "leagueKey",
    "generation",
    "fairnessVersion",
    "snapshotChanged",
    "rosters",
    "teamCount",
    "perspectiveRosterId",
    "overall",
    "teams",
    "trade",
}
OVERALL_KEYS = {"result", "label", "reasonCode", "reasonText", "note"}
TEAM_KEYS = {"rosterId", "result", "label", "reasonCode", "reasonText", "unavailableAssetIds"}
LEG_KEYS = {"id", "from", "to"}


def _set_values(contract: dict[str, Any], values: dict[str, float]) -> None:
    for row in contract["playersArray"]:
        if row.get("playerId") in values:
            v = float(values[row["playerId"]])
            row["rankDerivedValue"], row["values"] = v, {"full": v}


def test_m3_gap_size_and_direction_never_reach_the_public_body(world_factory):
    """One ledger (A's 101 for B's 201), values swept so the private gap goes
    from nothing to 15x the larger package, in BOTH directions, through every
    band level: the public body takes exactly two shapes -- FAIR and NOT FAIR --
    and nothing else (no magnitude, no band level, no direction)."""
    base = H.contract_for("clean")
    teams, legs = [1, 2], [leg("p:101", 1, 2), leg("p:201", 2, 1)]
    sweep = [
        (6000, 6000),
        (6000, 6050),
        (6000, 6200),
        (6200, 6000),
        (6000, 6500),
        (6000, 7000),
        (6000, 9000),
        (6000, 12000),
        (6000, 30000),
        (6000, 90000),
        (9000, 6000),
        (30000, 6000),
        (90000, 6000),
    ]
    bodies: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    levels: set[str] = set()
    signs: set[int] = set()
    for v101, v201 in sweep:
        contract = copy.deepcopy(base)
        _set_values(contract, {"101": v101, "201": v201})
        w = world_factory("clean", contract=contract)
        pub = w.public(teams, legs, 1)
        private = w.private(teams, legs, team_context=False)
        gap = private["teams"][0]["fairness"]["gap"]
        levels.add(private["teams"][0]["fairness"]["level"])
        signs.add((gap > 0) - (gap < 0))
        bodies[pub["overall"]["result"]].append(pub)
    assert levels == {"fair", "slight", "unfair", "lopsided"}, levels  # the sweep is real
    assert signs == {-1, 0, 1}, signs
    assert set(bodies) == {"FAIR", "NOT_FAIR"}
    for result, group in bodies.items():
        assert len(group) >= 3, result
        assert all(b == group[0] for b in group), result  # byte-identical, whatever the gap


def test_m3_the_body_has_exactly_the_spec_key_sets_and_a_three_valued_result(world_factory):
    results: set[str] = set()
    for scenario in H.SCENARIOS:
        w = world_factory(scenario)
        for n in TEAM_COUNTS:
            for teams, legs in H.corpus(w, n, tag="m3"):
                body = w.public(teams, legs, teams[0])
                ctx = (scenario, n, teams, legs)
                assert set(body) == TOP_KEYS, ctx
                assert set(body["overall"]) == OVERALL_KEYS, ctx
                assert set(body["rosters"]) == {"state", "asOf"}, ctx
                assert all(set(t) == TEAM_KEYS for t in body["teams"]), ctx
                assert all(set(x) == LEG_KEYS for x in body["trade"]), ctx
                results |= {t["result"] for t in body["teams"]} | {body["overall"]["result"]}
    assert results == {"FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"}


# ══ M5: send-and-receive refuses gifts before any evaluation (SD-5) ════════════


def _violators(teams: list[int], legs: list[dict[str, Any]]) -> list[int]:
    senders = {x["from"] for x in legs}
    receivers = {x["to"] for x in legs}
    return sorted(t for t in teams if t not in senders or t not in receivers)


def test_m5_every_one_sided_shape_is_refused_before_evaluation_and_privately_evaluated(
    world_factory, monkeypatch
):
    refused: collections.Counter = collections.Counter()
    for scenario in ("clean", "off_board", "traded_picks", "stale_rosters"):
        w = world_factory(scenario)
        rng = random.Random(f"m5|{scenario}")
        for n in TEAM_COUNTS:
            for _ in range(10):
                teams, legs = P.gen_ledger(w.snap, rng, n_teams=n, gifts=True)
                bad = _violators(teams, legs)
                if not bad:
                    continue
                ctx = (scenario, n, teams, legs)
                with _capturing_engine(monkeypatch) as calls:
                    res = w.public_response(teams, legs, teams[0])
                assert res.status_code == 400, (ctx, res.text)
                body = scan_response(res, kind="error", ctx=ctx)
                assert body == {
                    "error": "invalid_trade",
                    "message": public_advisor.ERROR_MESSAGES[("invalid_trade", "one_sided_trade")],
                    "reason": "one_sided_trade",
                    "rosterIds": bad,
                }, ctx
                assert calls == [], ctx  # refused before any evaluation
                # The same ledger is an ordinary private trade (any_leg): the
                # refusal is the public PRODUCT RULE, not a validity problem.
                private = w.private_response(teams, legs, team_context=False)
                assert private.status_code == 200, (ctx, private.text)
                refused[n] += 1
    assert all(refused[n] >= 3 for n in TEAM_COUNTS), refused


def test_m5_the_refusal_is_independent_of_asset_value(world_factory):
    """A 100-value gift and a 100,000-value gift get the SAME refusal, so the
    refusal itself cannot be used to read a price."""
    legs = [leg("p:101", 1, 2)]
    bodies = []
    for factor in (1.0, 0.02, 17.31):
        contract = copy.deepcopy(H.contract_for("clean"))
        for row in contract["playersArray"]:
            if isinstance(row.get("rankDerivedValue"), (int, float)) and row["rankDerivedValue"]:
                v = round(row["rankDerivedValue"] * factor, 2)
                row["rankDerivedValue"], row["values"] = v, {"full": v}
        w = world_factory("clean", contract=contract)
        res = w.public_response([1, 2], legs, 1)
        assert res.status_code == 400
        bodies.append(res.json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_m5_an_unpriced_asset_is_not_a_zero_anchor(world_factory):
    """With gifts refused, the only way to price one asset against ~nothing is
    to trade it for an asset the board does not price.  That must read UNABLE
    for BOTH teams (missing is never zero), never a FAIR / NOT FAIR verdict
    about the priced side."""
    off = world_factory("off_board")  # p:106 is rostered by team 1 with no board row
    anchored = off.public([1, 2], [leg("p:106", 1, 2), leg("p:202", 2, 1)], 1)
    assert anchored["overall"]["result"] == "UNABLE_TO_DETERMINE"
    assert [t["result"] for t in anchored["teams"]] == ["UNABLE_TO_DETERMINE"] * 2
    assert {t["reasonCode"] for t in anchored["teams"]} == {"asset_not_evaluable"}
    assert [t["unavailableAssetIds"] for t in anchored["teams"]] == [["p:106"], ["p:106"]]
    # Control: the same shape with a PRICED stand-in does return a verdict.
    priced = off.public([1, 2], [leg("p:104", 1, 2), leg("p:202", 2, 1)], 1)
    assert priced["overall"]["result"] in ("FAIR", "NOT_FAIR")
    # An unpriced PICK is no better an anchor.
    unpriced_pick = world_factory("pick_unpriced")
    body = unpriced_pick.public(
        [1, 2], [leg(f"pick:{H.KEY}:2027:r2:o1", 1, 2), leg("p:202", 2, 1)], 1
    )
    assert body["overall"]["result"] == "UNABLE_TO_DETERMINE"
    assert {t["reasonCode"] for t in body["teams"]} == {"asset_not_evaluable"}


# ══ M6: all teams in ONE response; the perspective selects only the default view ═


def test_m6_one_response_carries_every_team_and_the_perspective_only_selects_the_echo(
    world_factory, monkeypatch
):
    for scenario in H.SCENARIOS:
        w = world_factory(scenario)
        for n in TEAM_COUNTS:
            for teams, legs in H.corpus(w, n, tag="m6"):
                ctx = (scenario, n, teams, legs)
                bodies: dict[int, dict[str, Any]] = {}
                for perspective in teams:
                    with _capturing_engine(monkeypatch) as calls:
                        bodies[perspective] = w.public(teams, legs, perspective)
                    assert len(calls) == 1, ctx  # one evaluation per request, never one per team
                    body = bodies[perspective]
                    assert body["perspectiveRosterId"] == perspective, ctx
                    assert [t["rosterId"] for t in body["teams"]] == sorted(teams), ctx
                    assert len(body["trade"]) == len(legs) and body["teamCount"] == n, ctx
                echo_free = [
                    {k: v for k, v in b.items() if k != "perspectiveRosterId"}
                    for b in bodies.values()
                ]
                assert all(b == echo_free[0] for b in echo_free), ctx
                # Every other team's row in this body IS that team's own row.
                for body in bodies.values():
                    for row in body["teams"]:
                        assert row == next(
                            r
                            for r in bodies[row["rosterId"]]["teams"]
                            if r["rosterId"] == row["rosterId"]
                        ), ctx


def test_every_analyze_array_is_canonical_whatever_the_request_order(world_factory):
    """§4.3 P1: ``teams[]`` ascending by roster id, ``trade[]`` by asset id,
    ``unavailableAssetIds`` sorted -- so permuting the request's teams or
    assets, or moving the perspective within the trade, changes only the echo."""
    rng = random.Random("canonical-order")
    for scenario in H.SCENARIOS:
        w = world_factory(scenario)
        for n in TEAM_COUNTS:
            for teams, legs in H.corpus(w, n, tag="order"):
                ctx = (scenario, n, teams, legs)
                base = w.public(teams, legs, teams[0])
                assert [t["rosterId"] for t in base["teams"]] == sorted(teams), ctx
                assert [x["id"] for x in base["trade"]] == sorted(x["id"] for x in legs), ctx
                for _ in range(2):
                    shuffled_teams, shuffled_legs = list(teams), list(legs)
                    rng.shuffle(shuffled_teams)
                    rng.shuffle(shuffled_legs)
                    got = w.public(shuffled_teams, shuffled_legs, rng.choice(teams))
                    assert {k: v for k, v in got.items() if k != "perspectiveRosterId"} == {
                        k: v for k, v in base.items() if k != "perspectiveRosterId"
                    }, ctx


def test_m6_probing_perspectives_reveals_nothing_a_listed_team_does_not(world_factory):
    w = world_factory("clean")
    teams, legs = [1, 2], [leg("p:101", 1, 2), leg("p:201", 2, 1)]
    # A real league team that is not in the trade and a roster id that does not
    # exist answer with the SAME refusal (apart from the echoed request id).
    real_outsider = w.public_response(teams, legs, 3)
    no_such_team = w.public_response(teams, legs, 99)
    assert real_outsider.status_code == no_such_team.status_code == 400
    a, b = real_outsider.json(), no_such_team.json()
    assert a["reason"] == b["reason"] == "perspective_not_in_trade"
    assert a["rosterIds"] == [3] and b["rosterIds"] == [99]
    assert {k: v for k, v in a.items() if k != "rosterIds"} == {
        k: v for k, v in b.items() if k != "rosterIds"
    }
    scan_response(real_outsider, kind="error", ctx="outsider")
    # The perspective is REQUIRED (it cannot be dropped to see a neutral body).
    res = w.client.post(ANALYZE, json={"teams": teams, "assets": legs})
    assert res.status_code == 400 and res.json()["field"] == "perspectiveRosterId"


# ══ Public analyze persists nothing ════════════════════════════════════════════

_FS_MUTATORS = (
    ("os", "replace"),
    ("os", "rename"),
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "mkdir"),
    ("os", "makedirs"),
    ("os", "rmdir"),
    ("shutil", "copyfile"),
    ("shutil", "copy"),
    ("shutil", "copy2"),
    ("shutil", "move"),
    ("shutil", "rmtree"),
)


class _Persist(str):
    """One recorded persistence attempt, with the code path that made it."""

    background: bool

    def __new__(cls, text: str, frames: list[str]):
        obj = super().__new__(cls, text)
        # The server's lifespan starts the auction runtime, an asyncio task that
        # polls ITS OWN database on a timer, whatever requests arrive.  It is
        # attributed by its stack and nothing else is excused.
        obj.background = any(re.search(r"[\\/]src[\\/]auction[\\/]", f) for f in frames)
        obj.tail = " <- ".join(f.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for f in frames[-6:])
        return obj


@contextlib.contextmanager
def recorded_persistence(monkeypatch):
    """Record, process-wide (every thread, the request's included), anything
    that could persist state: write-mode ``open`` / ``io.open`` / ``os.open``,
    file-system mutators, and any file-backed SQLite connection."""
    import traceback

    events: list[_Persist] = []
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    real_connect = sqlite3.connect

    def note(text: str) -> None:
        events.append(_Persist(text, [f.filename for f in traceback.extract_stack()]))

    def writes(mode: Any) -> bool:
        return isinstance(mode, str) and bool(set("wax+") & set(mode))

    def open_(file, mode="r", *a, **k):
        if writes(mode):
            note(f"open[{mode}] {file}")
        return real_open(file, mode, *a, **k)

    def io_open_(file, mode="r", *a, **k):
        if writes(mode):
            note(f"io.open[{mode}] {file}")
        return real_io_open(file, mode, *a, **k)

    def os_open_(path, flags, *a, **k):
        if flags & write_flags:
            note(f"os.open[{flags}] {path}")
        return real_os_open(path, flags, *a, **k)

    def connect(database, *a, **k):
        if str(database) != ":memory:":
            note(f"sqlite3.connect {database}")
        return real_connect(database, *a, **k)

    def wrap(owner: Any, name: str):
        real = getattr(owner, name)

        def inner(*a, **k):
            note(f"{owner.__name__}.{name} {a[:2]}")
            return real(*a, **k)

        return inner

    with monkeypatch.context() as m:
        m.setattr(builtins, "open", open_)
        m.setattr(io, "open", io_open_)
        m.setattr(os, "open", os_open_)
        m.setattr(sqlite3, "connect", connect)
        for owner, name in _FS_MUTATORS:
            target = {"os": os, "shutil": shutil}[owner]
            m.setattr(target, name, wrap(target, name))
        yield events


def test_the_recorder_sees_every_way_to_persist(monkeypatch, tmp_path):
    """Control for the control: each mutator class is detected."""
    with recorded_persistence(monkeypatch) as events:
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        with open(tmp_path / "b.txt", "w", encoding="utf-8") as fh:
            fh.write("y")
        os.makedirs(tmp_path / "d", exist_ok=True)
        shutil.copyfile(tmp_path / "a.txt", tmp_path / "c.txt")
        os.replace(tmp_path / "c.txt", tmp_path / "e.txt")
        sqlite3.connect(tmp_path / "x.sqlite").close()
        (tmp_path / "e.txt").unlink()
    kinds = " ".join(events)
    for needle in ("open[w]", "makedirs", "copyfile", "replace", "sqlite3.connect", "unlink"):
        assert needle in kinds, (needle, events)
    with recorded_persistence(monkeypatch) as quiet:
        (tmp_path / "a.txt").read_text(encoding="utf-8")
    assert quiet == []


def test_public_analyze_persists_nothing_while_the_private_route_does(
    world_factory, monkeypatch, tmp_path
):
    log_dir = tmp_path / "decision-log"
    monkeypatch.setenv("RISKIT_TRADE_DECISION_LOG_DIR", str(log_dir))
    w = world_factory("over_cap")
    cases = [c for n in TEAM_COUNTS for c in H.corpus(w, n, tag="writes")]
    # Warm-up: first requests import lazily and fill in-memory caches (allowed).
    w.public(cases[0][0], cases[0][1], cases[0][0][0])
    before = json.dumps(w.contract, sort_keys=True, default=str)

    with recorded_persistence(monkeypatch) as events:
        for teams, legs in cases:
            for perspective in teams:
                assert w.public_response(teams, legs, perspective).status_code == 200
        for rid in (1, 2, 3, 4):
            assert w.client.get(assets_url(rid)).status_code == 200
        assert w.client.get(TEAMS_URL).status_code == 200
        # Refusals persist nothing either.
        assert w.public_response([1, 2], [leg("p:101", 1, 2)], 1).status_code == 400
        assert (
            w.public_response([1, 2], [leg("p:201", 1, 2), leg("p:102", 2, 1)], 1).status_code
            == 409
        )
    # Nothing the request path did persisted.  (The auction runtime's own
    # timer poll of its own database is excused by stack attribution -- see
    # ``_Persist`` -- and is not a request effect.)
    unexplained = [f"{e}  [{e.tail}]" for e in events if not e.background]
    assert unexplained == [], unexplained
    assert not log_dir.exists() or not [p for p in log_dir.rglob("*") if p.is_file()]
    assert json.dumps(w.contract, sort_keys=True, default=str) == before  # board untouched

    # Control: the PRIVATE route, same ledger, same process, DOES persist (its
    # decision receipts), so the silence above is not a blind recorder.
    teams, legs = cases[0]
    with recorded_persistence(monkeypatch) as control:
        w.private(teams, legs, team_context=False)
    assert [
        e for e in control if not e.background
    ], "the private route wrote nothing: the recorder is blind to receipts"
    assert [p for p in log_dir.rglob("*") if p.is_file()], "no decision receipt was written"


# ══ The §4.5 error table, executed row by row ═════════════════════════════════

JSON_HEADERS = {"Content-Type": "application/json"}


def test_the_error_table_is_executed_row_by_row_with_fixed_copy(world_factory, monkeypatch):
    from src.api import feature_flags

    w = world_factory("clean")
    two = [leg("p:101", 1, 2), leg("p:201", 2, 1)]
    seen: set[tuple[Any, ...]] = set()

    def record(label: str, res: Any, row: tuple[Any, ...]) -> None:
        body = scan_response(res, kind="error", ctx=label)
        got = (res.status_code, body["error"], body.get("reason"))
        assert got == row, (label, got, body)
        assert body["message"] == public_advisor.ERROR_MESSAGES[(row[1], row[2])], label
        assert set(body) <= {
            "error",
            "message",
            "reason",
            "field",
            "assetIds",
            "rosterIds",
            "leagueKey",
            "maxBytes",
            "retryAfterSeconds",
        }, (label, body)
        seen.add(row)

    def post(body: Any) -> Any:
        return w.client.post(ANALYZE, json=body)

    cases = [
        (
            "invalid_json",
            lambda: w.client.post(ANALYZE, content=b"{bad", headers=JSON_HEADERS),
            (400, "invalid_request", "invalid_json"),
        ),
        (
            "schema",
            lambda: post({"perspectiveRosterId": "1", "teams": [1, 2], "assets": []}),
            (400, "invalid_request", "schema"),
        ),
        (
            "unsupported_sort",
            lambda: w.client.get(assets_url(1, "sort=value_desc")),
            (400, "invalid_request", "unsupported_sort"),
        ),
        (
            "invalid_roster_id",
            lambda: w.client.get(assets_url("x")),
            (400, "invalid_request", "invalid_roster_id"),
        ),
        (
            "perspective_not_in_trade",
            lambda: w.public_response([1, 2], two, 3),
            (400, "invalid_trade", "perspective_not_in_trade"),
        ),
        (
            "too_few_teams",
            lambda: w.public_response([1, 1], two, 1),
            (400, "invalid_trade", "too_few_teams"),
        ),
        (
            "duplicate_team",
            lambda: w.public_response([1, 2, 2], two, 1),
            (400, "invalid_trade", "duplicate_team"),
        ),
        (
            "team_not_in_league",
            lambda: w.public_response([1, 7], [leg("p:101", 1, 7), leg("p:201", 7, 1)], 1),
            (400, "invalid_trade", "team_not_in_league"),
        ),
        (
            "empty_trade",
            lambda: w.public_response([1, 2], [], 1),
            (400, "invalid_trade", "empty_trade"),
        ),
        (
            "unknown_asset",
            lambda: w.public_response([1, 2], [leg("p:101", 1, 2), leg("q:201", 2, 1)], 1),
            (400, "invalid_trade", "unknown_asset"),
        ),
        (
            "duplicate_asset",
            lambda: w.public_response([1, 2], [two[0], two[0], two[1]], 1),
            (400, "invalid_trade", "duplicate_asset"),
        ),
        (
            "invalid_origin",
            lambda: w.public_response([1, 2], [leg("p:101", 3, 2), two[1]], 1),
            (400, "invalid_trade", "invalid_origin"),
        ),
        (
            "invalid_destination",
            lambda: w.public_response([1, 2], [leg("p:101", 1, 3), two[1]], 1),
            (400, "invalid_trade", "invalid_destination"),
        ),
        (
            "destination_is_origin",
            lambda: w.public_response([1, 2], [leg("p:101", 1, 1), two[1]], 1),
            (400, "invalid_trade", "destination_is_origin"),
        ),
        (
            "idle_team",
            lambda: w.public_response([1, 2, 3], two, 1),
            (400, "invalid_trade", "idle_team"),
        ),
        (
            "one_sided_trade",
            lambda: w.public_response([1, 2], [two[0]], 1),
            (400, "invalid_trade", "one_sided_trade"),
        ),
        (
            "asset_not_owned",
            lambda: w.public_response([1, 2], [leg("p:201", 1, 2), leg("p:102", 2, 1)], 1),
            (409, "stale_assets", "asset_not_owned"),
        ),
        (
            "unknown_league",
            lambda: w.client.get(TEAMS_URL + "?leagueKey=nope"),
            (400, "unknown_league", None),
        ),
        (
            "inactive_league",
            lambda: w.client.get(TEAMS_URL + "?leagueKey=retired"),
            (400, "inactive_league", None),
        ),
        (
            "league_not_public",
            lambda: w.client.get(TEAMS_URL + "?leagueKey=side"),
            (404, "league_not_public", None),
        ),
        (
            "unknown_team",
            lambda: w.client.get(assets_url(9)),
            (404, "unknown_team", None),
        ),
        (
            "payload_too_large",
            lambda: w.client.post(
                ANALYZE, content=b"{" + b" " * 20000 + b"}", headers=JSON_HEADERS
            ),
            (413, "payload_too_large", None),
        ),
        (
            "unsupported_media_type",
            lambda: w.client.post(ANALYZE, content=b"{}", headers={"Content-Type": "text/plain"}),
            (415, "unsupported_media_type", None),
        ),
    ]
    for label, call, row in cases:
        record(label, call(), row)

    # Rows that need the configuration or a seam moved.
    cfg = copy.deepcopy(api.advisor_config())
    with monkeypatch.context() as m:
        wide = copy.deepcopy(cfg)
        wide["limits"]["maxTeams"] = 12
        m.setattr(api, "advisor_config", lambda: wide)
        record(
            "too_many_teams",
            w.public_response([1, 2, 3, 4, 5], two, 1),
            (400, "invalid_trade", "too_many_teams"),
        )
    with monkeypatch.context() as m:
        small = copy.deepcopy(cfg)
        small["limits"]["maxLegs"] = 3
        m.setattr(api, "advisor_config", lambda: small)
        legs4 = [leg("p:101", 1, 2), leg("p:102", 1, 2), leg("p:103", 1, 2), leg("p:201", 2, 1)]
        record(
            "too_many_assets",
            w.public_response([1, 2], legs4, 1),
            (400, "invalid_trade", "too_many_assets"),
        )
    with monkeypatch.context() as m:
        tight = copy.deepcopy(cfg)
        tight["rateLimits"]["perKeyBurst"] = {"capacity": 1, "windowSeconds": 600}
        m.setattr(api, "advisor_config", lambda: tight)
        api.reset_for_tests()
        assert w.public_response([1, 2], two, 1).status_code == 200
        limited = w.public_response([1, 2], two, 1)
        record("rate_limited", limited, (429, "rate_limited", None))
        assert limited.headers["retry-after"] == str(limited.json()["retryAfterSeconds"])
    api.reset_for_tests()
    with monkeypatch.context() as m:
        m.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "0")
        feature_flags.reload()
        record(
            "disabled", w.public_response([1, 2], two, 1), (503, "advisor_unavailable", "disabled")
        )
        record("disabled-list", w.client.get(TEAMS_URL), (503, "advisor_unavailable", "disabled"))
    feature_flags.reload()
    with monkeypatch.context() as m:
        m.setattr(api, "_launch_gate_reason", lambda: "lane_e_gate_closed")
        record(
            "not_ready",
            w.public_response([1, 2], two, 1),
            (503, "advisor_unavailable", "not_ready"),
        )
    with monkeypatch.context() as m:
        m.setattr(
            public_advisor,
            "evaluate",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine exploded 987654")),
        )
        record(
            "upstream_unavailable",
            w.public_response([1, 2], two, 1),
            (503, "advisor_unavailable", "upstream_unavailable"),
        )

    # The table is exactly the spec's table, and has fixed copy for every row.
    assert seen == SPEC_ERROR_ROWS, (SPEC_ERROR_ROWS - seen, seen - SPEC_ERROR_ROWS)
    assert set(public_advisor.ERROR_MESSAGES) == {
        (e, r) for _s, e, r in SPEC_ERROR_ROWS | SPEC_ADMISSION_ROWS
    }
    # Removed by the spec (§4.5): no multi-team refusal and no roster-limit reason.
    flat = " ".join(f"{e} {r}" for e, r in public_advisor.ERROR_MESSAGES).lower()
    for gone in ("multi_team_unsupported", "roster_limit"):
        assert gone not in flat
    # The ledger's own reason was renamed so it cannot be mistaken for the GET 404 (R16c).
    assert ("invalid_trade", "team_not_in_league") in public_advisor.ERROR_MESSAGES
    assert ("invalid_trade", "unknown_team") not in public_advisor.ERROR_MESSAGES


def test_a_409_never_reveals_the_actual_owner_on_any_board(world_factory):
    """Echo bounds (P3): only request-supplied, well-formed asset ids; never the
    holder's roster id -- on every board where ownership is provable."""
    for scenario in ("clean", "off_board", "quarantined", "over_cap", "traded_picks"):
        w = world_factory(scenario)
        # Team 2's asset claimed as team 1's; team 1's asset claimed as team 2's.
        res = w.public_response([1, 2], [leg("p:201", 1, 2), leg("p:102", 2, 1)], 1)
        assert res.status_code == 409, (scenario, res.text)
        body = scan_response(res, kind="error", ctx=scenario)
        assert set(body) == {"error", "message", "reason", "assetIds"}, (scenario, body)
        assert body["assetIds"] == ["p:102", "p:201"] and "rosterIds" not in body


SECRET = "SECRET-7781-do-not-leak"


def test_a_public_route_never_returns_a_500_or_a_trace_at_any_seam(
    world_factory, monkeypatch, caplog
):
    import logging

    w = world_factory("clean")
    two = [leg("p:101", 1, 2), leg("p:201", 2, 1)]

    def boom(*_a, **_k):
        raise RuntimeError(f"engine exploded {SECRET} value 987654")

    def get_teams():
        return w.client.get(TEAMS_URL)

    def get_assets():
        return w.client.get(assets_url(1))

    def analyze():
        return w.public_response([1, 2], two, 1)

    seams = [
        ("teams/snapshot", public_advisor, "snapshot", get_teams),
        ("teams/list_teams", public_advisor, "list_teams", get_teams),
        ("teams/public_generation", public_advisor, "public_generation", get_teams),
        ("assets/snapshot", public_advisor, "snapshot", get_assets),
        ("assets/list_team_assets", public_advisor, "list_team_assets", get_assets),
        ("analyze/snapshot", public_advisor, "snapshot", analyze),
        ("analyze/validate", public_advisor, "validate", analyze),
        ("analyze/evaluate", public_advisor, "evaluate", analyze),
        ("analyze/body", api, "_analyze_body", analyze),
        ("analyze/limiter", api, "_limiter", analyze),
        ("gate/league", api, "_league_error", get_teams),
        ("gate/launch", api, "_launch_gate_reason", analyze),
    ]
    for label, owner, attr, call in seams:
        with monkeypatch.context() as m, caplog.at_level(logging.ERROR):
            m.setattr(owner, attr, boom)
            res = call()
        assert res.status_code == 503, (label, res.status_code, res.text)
        assert res.headers["cache-control"] == "no-store", label
        assert res.json() == {
            "error": "advisor_unavailable",
            "message": public_advisor.ERROR_MESSAGES[
                ("advisor_unavailable", "upstream_unavailable")
            ],
            "reason": "upstream_unavailable",
        }, label
        for needle in (SECRET, "Traceback", "RuntimeError", "987654", ".py"):
            assert needle not in res.text, (label, needle)
    # The seams work again once the fault is gone (nothing was left broken).
    assert analyze().status_code == 200 and get_teams().status_code == 200


# ══ §4.4 forbidden-word scan: server copy and League Hub client copy ═══════════

#: Personalised-recommendation and advice words (§4.4), with inflections.
#: ``win`` / ``lose`` are listed by form so "window" and "within" are not hits.
FORBIDDEN_COPY = re.compile(
    r"\b(?:accept(?:s|ed|ing|ance)?|decline[sd]?|declining|approv(?:e|es|ed|ing|al)|"
    r"den(?:y|ies|ied|ying)|reject(?:s|ed|ing)?|should(?:n't)?|recommend(?:s|ed|ing|ation|ations)?|"
    r"advice|advis(?:e|es|ed|ing)|(?:un)?favou?rable|win(?:s|ning|ner|ners)?|"
    r"los(?:e|es|ing)|loser|smash|fleece|your (?:roster|lineup))\b",
    re.IGNORECASE,
)
#: The private headline / advice vocabulary (case-sensitive: "NO" the headline,
#: not "no" in a sentence).
FORBIDDEN_HEADLINES = re.compile(
    r"\b(?:YES|NO|NO_TOO_CLOSE|NOT_ENOUGH_EVIDENCE|ACCEPT|DECLINE|APPROVE|DENY)\b"
)
#: §4.4 copy rules: no closeness / magnitude wording.
FORBIDDEN_MAGNITUDE = re.compile(
    r"\b(?:narrow(?:ly)?|barely|slightly|heavily|massively|by a lot|close(?:ly)?|"
    r"lopsided|steal|robbery|landslide)\b",
    re.IGNORECASE,
)
NUMBER_IN_COPY = re.compile(r"[0-9%$]")


def copy_problems(text: str, *, magnitude: bool = True) -> list[str]:
    """Problems in one public text.  ``magnitude`` applies the §4.4 "no
    closeness or magnitude wording" copy rule, which governs the RESULT copy
    (the server table); UI chrome such as a "Close" button is not result copy."""
    rules = [("recommendation word", FORBIDDEN_COPY), ("headline vocabulary", FORBIDDEN_HEADLINES)]
    if magnitude:
        rules.append(("magnitude wording", FORBIDDEN_MAGNITUDE))
    out = []
    for name, rx in rules:
        m = rx.search(text)
        if m:
            out.append(f"{name} {m.group(0)!r}")
    return out


def _js_strings_and_code(src: str) -> tuple[list[str], str]:
    """``(string literals, source with comments and literals blanked)``."""
    strings: list[str] = []
    code: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c, nxt = src[i], src[i + 1 : i + 2]
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            code.append(" " * (j - i))
            i = j
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            code.append(" " * (j - i))
            i = j
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            strings.append(src[i + 1 : j])
            code.append(" " * (j + 1 - i))
            i = j + 1
        elif c == "`":
            j, depth, buf = i + 1, 0, []
            while j < n:
                ch = src[j]
                if ch == "\\":
                    buf.append(src[j : j + 2])
                    j += 2
                    continue
                if depth == 0 and ch == "`":
                    break
                if ch == "$" and src[j + 1 : j + 2] == "{":
                    depth += 1
                    j += 2
                    continue
                if depth and ch == "{":
                    depth += 1
                elif depth and ch == "}":
                    depth -= 1
                elif depth == 0:
                    buf.append(ch)
                j += 1
            strings.append("".join(buf))
            code.append(" " * (j + 1 - i))
            i = j + 1
        else:
            code.append(c)
            i += 1
    return strings, "".join(code)


_JSX_TEXT = re.compile(r"[>}]([^<>{}()=;]*)[<{]")


def visible_copy(src: str) -> list[str]:
    """What a person can read in a JS / JSX source: string literals and JSX text
    nodes (comments and code excluded).  An HTTP header NAME (``Accept``) is not
    copy."""
    strings, code = _js_strings_and_code(src)
    jsx = [t.strip() for t in _JSX_TEXT.findall(code) if len(re.findall(r"[A-Za-z]", t)) >= 3]
    return [
        s for s in [*strings, *jsx] if s.strip() and not re.fullmatch(r"Accept(?:-[A-Za-z-]+)?", s)
    ]


FRONTEND_ADVISOR_FILES = [
    *sorted(REPO.glob("frontend/app/league/sections/trade-advisor*.jsx")),
    *sorted(REPO.glob("frontend/app/league/sections/_advisor-*.jsx")),
    REPO / "frontend/lib/trade-advisor.js",
    REPO / "frontend/lib/trade-advisor-client.js",
    REPO / "frontend/app/league/advisor-bootstrap.js",
    REPO / "frontend/app/league/tabs.js",
]
#: Shared surfaces: only the copy that names the advisor is the advisor's.
FRONTEND_SHARED_FILES = [
    REPO / "frontend/app/HomeClient.jsx",
    REPO / "frontend/app/page.jsx",
    REPO / "frontend/app/sitemap.js",
    REPO / "frontend/app/league/page.jsx",
]


def test_the_copy_scanner_has_teeth():
    bad = {
        "recommend": "You should take this deal.",
        "accept": "Accept this trade",
        "decline": "decline",
        "approve": "Approved",
        "headline": "YES",
        "headline token": "NO_TOO_CLOSE",
        "magnitude": "Narrowly outside the threshold",
        "lopsided": "A lopsided offer",
        "winner": "Team 2 wins this trade",
        "lineup": "Check your lineup first",
    }
    for name, text in bad.items():
        assert copy_problems(text), name
    for ok in (
        "This trade is within our fairness threshold for this team.",
        "The window is open.",
        "No players on this team.",
        "Brisket Trade Advisor",
    ):
        assert copy_problems(ok) == [], ok
    jsx = """
      // we should never say accept in a comment
      const A = "Accept";                   /* header name, excluded */
      const t = `Decline ${x} offers`;
      export default () => (<p>Take this deal</p>);
      /* recommend */
    """
    found = visible_copy(jsx)
    assert "Decline  offers" in found or any("Decline" in s for s in found)
    assert "Take this deal" in found
    assert not any("never say" in s or s == "recommend" for s in found)
    assert "Accept" not in found


def test_server_copy_has_no_recommendation_headline_magnitude_or_number():
    texts = set(public_advisor.FIXED_TEXT)
    assert texts >= set(SPEC_TEAM_TEXT.values()) | set(SPEC_OVERALL_TEXT.values())
    assert texts >= set(SPEC_OVERALL_LABEL.values()) | set(SPEC_TEAM_LABEL.values())
    assert len(texts) >= 35
    problems = {t: copy_problems(t) for t in sorted(texts) if copy_problems(t)}
    assert problems == {}, problems
    for t in sorted(texts):
        assert not NUMBER_IN_COPY.search(t), t  # no proprietary number in any public copy
        assert len(t) <= 160, t


def test_league_hub_client_copy_has_no_recommendation_headline_or_magnitude_words():
    scanned = 0
    for path in FRONTEND_ADVISOR_FILES:
        assert path.exists(), path
        copy_nodes = visible_copy(path.read_text(encoding="utf-8"))
        scanned += len(copy_nodes)
        for node in copy_nodes:
            problems = copy_problems(node, magnitude=False)
            assert problems == [], (path.name, node, problems)
            # No proprietary number in sentence-like copy (CSS / media strings excluded).
            if re.match(r"^[A-Z][^()]*\s", node):
                assert not re.search(r"\d{3,}|%|\$", node), (path.name, node)
    for path in FRONTEND_SHARED_FILES:
        assert path.exists(), path
        for node in visible_copy(path.read_text(encoding="utf-8")):
            if "advisor" in node.lower():
                assert copy_problems(node, magnitude=False) == [], (path.name, node)
    assert scanned >= 150, scanned  # the extractor really saw the components' copy
    client = visible_copy((REPO / "frontend/lib/trade-advisor-client.js").read_text("utf-8"))
    assert public_advisor.ERROR_MESSAGES[("invalid_trade", "one_sided_trade")] in client
