#!/usr/bin/env python3
"""Signals native league-value probe — READ-ONLY (plan §3.2-§3.4, PR-P).

Owner directive 2026-10-19, Phase 3: does Signals' authenticated app produce a
retrievable, same-scale, league-specific valuation for offense AND IDP?  This
probe gathers the evidence; the admission decision is the FIXED rule
``DECISION_RULE`` below, written before the probe ever ran and pinned by hash
(``tests/scripts/test_probe_signals_native.py``).

Modes
-----
``--mode bundle`` (Tier 0, OFF-BOX, the CI runner): unauthenticated GETs of
    Signals' public web-app bundle (<= 40 GETs, <= 32 MB).  No credentials
    are read or sent.  Prints only the public projection (operation COUNTS,
    booleans, host CLASSES) — operation names, field names and exact hosts
    are never printed (AppSync / Cognito hostnames embed pool identifiers).
``--mode native-probe`` (box, from the DEPLOYED checkout, ``main`` only):
    P preflight -> 0 (private extraction) -> P -> 1b -> [1c] -> wait >= 120 s
    -> P -> 2.  At most 30 AppSync requests and 10 minutes in total.

Hard safety requirements (plan §3.2)
------------------------------------
* The request layer :class:`NonRecordingAppSync` NEVER records: a 401/403,
  an AppSync ``Unauthorized`` field error, a 429 or any other refusal is a
  probe stop — no ``renew_for_retry``, no ``deny``, no ``record_failure``.
  The voting collector's ``AppSyncClient`` records a second refusal as
  ``access_denied``, which would halt the voting offense source.
* No token renewal: the stored access token is used only when it is ALREADY
  fresh for the whole window, read through
  ``signals_auth.peek_fresh_access_token`` (read-only, no lock, no write).
* Mutation and subscription documents are refused before anything is sent.
* No new infrastructure: no unit, no timer; a failed preflight is BLOCKED.
* Tier 1c (a league-list read, which widens the authenticated footprint)
  runs only with ``--allow-league-footprint`` (owner decision 6) and an
  operator-authored private ops file; it is otherwise ``skipped``.

Privacy: stdout carries only :func:`public_projection` (allowlisted paths,
identifier-shaped leaves, guarded by ``signals_health.assert_public_safe``).
The full report — operation names, key names, hashes, rank correlations — is
written 0600 under ``data/sources/signals/reports/`` on the box; in ``bundle``
mode on the runner there is no private store, so private detail is discarded.
"""

from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.sources import signals as S  # noqa: E402
from src.sources import signals_auth as SA  # noqa: E402
from src.sources.signals_health import (  # noqa: E402
    PublicLeak,
    _project,
    _prune,
    assert_public_safe,
)

WEBAPP_ORIGIN = SA.WEBAPP_ORIGIN
MAX_BUNDLE_GETS = 40
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_APPSYNC_REQUESTS = 30
TIER_BUDGETS = {"1b": 15, "1c": 8, "2": 15}
MAX_WALL_SECONDS = 600
DETERMINISM_GAP_SECONDS = 120
PREFLIGHT_MARGIN_SECONDS = 300
TIMERS = ("dynasty-signals-values", "dynasty-signals-auth-renew")
IDP_RAW_POSITIONS = ("DT", "DE", "LB", "CB", "S")
RAW_TO_FAMILY = {"DT": "DL", "DE": "DL", "LB": "LB", "CB": "DB", "S": "DB"}
#: Variables Tier 1b may fill on its own; any other REQUIRED variable skips
#: the operation (never guessed).
SAFE_FILL: dict[str, Callable[[datetime], Any]] = {
    "season": lambda now: S.default_season(now),
    "limit": lambda now: 5,
    "nextToken": lambda now: None,
}

# ── the decision rule, fixed BEFORE the probe ran (plan §3.4) ────────────
#
# Editing this text after a probe result exists is exactly the
# forking-paths failure the preregistration forbids; the test pins its hash.
DECISION_RULE = """\
Admit a native candidate N to evaluation only if ALL hold:
1. server observation, reachable through an operation the shipped app issues;
2. covers DT, DE, LB, CB and S at or above the family floors;
3. inputs are scoring and lineup settings only, no roster dependence
   (only then can it be keyed by scoring_fingerprint);
4. deterministic (Tier 2) and changes only with a publication;
5. S1 not falsified: family tops NOT within 5% of each other, and normalised
   curves NOT within +/-5% at k = 12 and 24;
6. a dynasty trade value, not a projection: age/horizon gradient consistent
   with dynasty value, rookies priced at all, DYNASTY game type proven per
   endpoint (unverified game type fails closed);
7. lineage established by observed code paths, never by similarity; the IDP
   half must not be a FantasyCalc or KTC derivative;
8. licence: the attestation scope covers canonical use of a league-specific
   value (unclear -> owner decision 6).
Questions 5 (scarcity / replacement applied?) and 6 (server vs browser) are
always answered.  If condition 3 fails, N is leagueKey-scoped and cannot be a
canonical vote: REJECT.  Any other FAIL: REJECT the native route explicitly.
Any UNKNOWN: INSUFFICIENT (not admitted).  Its absence never blocks F.
"""
DECISION_CONDITIONS = (
    "c1_server_observation",
    "c2_idp_coverage",
    "c3_scoring_only_inputs",
    "c4_deterministic",
    "c5_s1_not_falsified",
    "c6_dynasty_not_projection",
    "c7_lineage_observed",
    "c8_licence",
)
#: Conditions the probe cannot establish mechanically; only reviewer
#: evidence (``--review-evidence``) can move them off UNKNOWN.
REVIEW_ONLY = frozenset({"c6_dynasty_not_projection", "c7_lineage_observed", "c8_licence"})
PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"


def decision_rule_sha256() -> str:
    return hashlib.sha256(DECISION_RULE.encode("utf-8")).hexdigest()


def evaluate_decision(
    findings: Mapping[str, Any], review: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Apply ``DECISION_RULE`` to the probe findings (+ optional reviewer
    evidence for the review-only conditions).  Pure."""
    t0 = findings.get("tier0") or {}
    t1c = findings.get("tier1c") or {}
    t2 = findings.get("tier2") or {}
    cond: dict[str, str] = dict.fromkeys(DECISION_CONDITIONS, UNKNOWN)

    if t0.get("ran") and t0.get("serverLeagueValueQuery") is False:
        cond["c1_server_observation"] = FAIL
    elif t0.get("serverLeagueValueQuery") and t1c.get("ok"):
        cond["c1_server_observation"] = PASS

    cov = t1c.get("idpCoverage") if t1c.get("ok") else None
    if isinstance(cov, Mapping):
        fam = {"DL": 0, "LB": 0, "DB": 0}
        for raw, n in cov.items():
            if raw in RAW_TO_FAMILY:
                fam[RAW_TO_FAMILY[raw]] += int(n or 0)
        floors = {f: S.MIN_BOARD_ROWS[k] for f, k in S.IDP_FAMILY_BOARDS.items()}
        missing_raw = [p for p in IDP_RAW_POSITIONS if not cov.get(p)]
        ok = not missing_raw and all(fam[f] >= floors[f] for f in fam)
        cond["c2_idp_coverage"] = PASS if ok else FAIL

    if t1c.get("ok"):
        if t1c.get("rosterInputs"):
            cond["c3_scoring_only_inputs"] = FAIL
        elif t1c.get("scoringInputs") or t1c.get("settingsInputs"):
            cond["c3_scoring_only_inputs"] = PASS

    if t2.get("ran") and t2.get("publicationBetween") is False:
        cond["c4_deterministic"] = PASS if t2.get("equal") else FAIL

    s1 = t1c.get("s1") if t1c.get("ok") else None
    if isinstance(s1, Mapping) and s1.get("familyTopsWithin5pct") is not None:
        falsified = bool(s1.get("familyTopsWithin5pct")) or bool(s1.get("curvesWithin5pct"))
        cond["c5_s1_not_falsified"] = FAIL if falsified else PASS

    for key in REVIEW_ONLY:
        v = (review or {}).get(key)
        if v in (PASS, FAIL):
            cond[key] = v

    if cond["c3_scoring_only_inputs"] == FAIL:
        verdict = "REJECT_LEAGUE_SCOPED"
    elif FAIL in cond.values():
        verdict = "REJECT"
    elif UNKNOWN in cond.values():
        verdict = "INSUFFICIENT"
    else:
        verdict = "ADMIT"
    return {
        "ruleSha256": decision_rule_sha256()[:12],
        "conditions": cond,
        "verdict": verdict,
        "q5ScarcityOrReplacementMarkers": bool(t0.get("scarcityMarkers")),
        "q6ValueComputedWhere": (
            "server_query_present"
            if t0.get("serverLeagueValueQuery")
            else ("browser_computed" if t0.get("leagueValueModulePresent") else "unknown")
        ),
    }


# ── the request layer that never records ─────────────────────────────────


class ProbeStop(Exception):
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        super().__init__(outcome)


_STRING_LIT = re.compile(r'"""(?:.|\n)*?"""|"(?:\\.|[^"\\])*"')
_COMMENT = re.compile(r"#[^\n]*")
_FORBIDDEN_OP = re.compile(r"(?:^|[\s}])(mutation|subscription)\b")


def assert_read_only(document: str) -> None:
    """Refuse any GraphQL document that is not purely a query."""
    stripped = _COMMENT.sub(" ", _STRING_LIT.sub('""', str(document or "")))
    if _FORBIDDEN_OP.search(" " + stripped):
        raise ProbeStop("refused_non_query_document")
    head = stripped.lstrip()
    if not (head.startswith("query") or head.startswith("{") or head.startswith("fragment")):
        raise ProbeStop("refused_non_query_document")


class NonRecordingAppSync:
    """Bounded AppSync reads that can never write auth state.

    Contrast ``signals.AppSyncClient``: that one renews once on 401/403 and
    records ``access_denied`` on a second refusal.  This one does neither —
    any refusal is a :class:`ProbeStop` and nothing else happens."""

    def __init__(
        self,
        token: str,
        *,
        http_post: S.HttpPost = S.urllib_post,
        max_requests: int = MAX_APPSYNC_REQUESTS,
        deadline: float,
        clock: Callable[[], float] = time.monotonic,
        url: str = S.APPSYNC_URL,
    ) -> None:
        self._token = token
        self.http_post = http_post
        self.max_requests = max_requests
        self.deadline = deadline
        self.clock = clock
        self.url = url
        self.requests = 0

    def query(self, document: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        assert_read_only(document)
        if self.requests >= self.max_requests:
            raise ProbeStop("request_budget_exhausted")
        if self.clock() >= self.deadline:
            raise ProbeStop("wall_clock_exhausted")
        body = json.dumps({"query": document, "variables": dict(variables)}).encode("utf-8")
        headers = {
            "Authorization": self._token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": S.USER_AGENT_VALUES,
        }
        self.requests += 1
        try:
            status, _hdrs, data = self.http_post(self.url, headers, body, S.HTTP_TIMEOUT_SECONDS)
        except S.BodyTooLarge:
            raise ProbeStop("oversize") from None
        except OSError:
            raise ProbeStop("transport_error") from None
        if status in (401, 403):
            raise ProbeStop("refused")
        if status == 429:
            raise ProbeStop("rate_limited")
        if status != 200:
            raise ProbeStop(f"http_{int(status)}")
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise ProbeStop("not_json") from None
        if not isinstance(doc, dict):
            raise ProbeStop("not_an_object")
        errors = [e for e in (doc.get("errors") or []) if isinstance(e, Mapping)]
        if any("unauthorized" in str(e.get("errorType") or "").lower() for e in errors):
            raise ProbeStop("refused")
        return {"data": doc.get("data"), "errorCount": len(errors)}


# ── Tier 0: the public bundle ────────────────────────────────────────────


class _ScriptSrc(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.srcs.append(str(a["src"]))
        if tag == "link" and a.get("href") and "modulepreload" in str(a.get("rel") or ""):
            self.srcs.append(str(a["href"]))


_CHUNK_REF = re.compile(r"""["'`](/?(?:assets|static/js|_next/static)/[A-Za-z0-9_./-]+\.js)["'`]""")
_OP_DEF = re.compile(
    r"\b(query|mutation|subscription)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*\{"
)
_HOST = re.compile(r"https?://([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", re.IGNORECASE)
_LEAGUE_VALUE = re.compile(
    r"(?i)league[A-Za-z_]{0,24}value|value[A-Za-z_]{0,24}league|leagueAdjusted|leagueExact"
)
_IDP = re.compile(r"(?i)\bidp|IdpDynasty|defensiveValue")
_SCARCITY = re.compile(r"(?i)replacement[A-Za-z_]{0,12}level|\bvorp\b|scarcity")
_SCORING = re.compile(r"(?i)scoring")
_ROSTER = re.compile(r"(?i)roster")
_SETTINGS = re.compile(r"(?i)settings|lineup|starters|positions")


def host_class(host: str) -> str:
    h = host.lower()
    if "fantasycalc" in h:
        return "fantasycalc"
    if "keeptradecut" in h:
        return "ktc"
    if "sleeper" in h:
        return "sleeper"
    if "appsync-api" in h:
        return "appsync"
    if "cognito" in h:
        return "cognito"
    if h.endswith("signalsfantasy.com"):
        return "signals"
    return "other"


def _same_origin(url: str, origin: str) -> bool:
    return urllib.parse.urlsplit(url).netloc == urllib.parse.urlsplit(origin).netloc


def fetch_bundle(
    http_get: S.HttpGet = S.urllib_get, *, origin: str = WEBAPP_ORIGIN
) -> dict[str, Any]:
    """BFS over the shipped app's own script chunks, bounded by
    ``MAX_BUNDLE_GETS`` and ``MAX_BUNDLE_BYTES``.  Same-origin only."""
    headers = {"User-Agent": S.USER_AGENT, "Accept-Encoding": "gzip"}
    gets = total = 0
    texts: dict[str, str] = {}
    status, _h, body = http_get(origin + "/", headers, S.HTTP_TIMEOUT_SECONDS)
    gets += 1
    total += len(body)
    if status != 200:
        return {"ok": False, "reason": f"http_{int(status)}", "gets": gets, "bytes": total}
    parser = _ScriptSrc()
    parser.feed(body.decode("utf-8", "replace"))
    queue = [urllib.parse.urljoin(origin + "/", s) for s in parser.srcs]
    seen: set[str] = set()
    truncated = False
    while queue:
        url = queue.pop(0)
        if url in seen or not _same_origin(url, origin):
            continue
        if gets >= MAX_BUNDLE_GETS or total >= MAX_BUNDLE_BYTES:
            truncated = True
            break
        seen.add(url)
        try:
            st, _h, js = http_get(url, headers, S.HTTP_TIMEOUT_SECONDS)
        except (OSError, S.BodyTooLarge):
            gets += 1
            continue
        gets += 1
        total += len(js)
        if st != 200:
            continue
        text = js.decode("utf-8", "replace")
        texts[url] = text
        for ref in _CHUNK_REF.findall(text):
            queue.append(urllib.parse.urljoin(origin + "/", ref))
    return {"ok": True, "gets": gets, "bytes": total, "truncated": truncated, "texts": texts}


def _extract_document(text: str, start: int) -> str:
    """The balanced ``{...}`` operation body starting at the match."""
    i = text.find("{", start)
    depth = 0
    for j in range(i, min(len(text), i + 20000)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
    return text[start : i + 1]


def analyse_bundle(texts: Mapping[str, str]) -> dict[str, Any]:
    """Private findings from the bundle: operations, hosts, markers."""
    ops: dict[str, dict[str, Any]] = {}
    hosts: set[str] = set()
    league_module = idp_branch = scarcity = False
    for text in texts.values():
        for m in _OP_DEF.finditer(text):
            kind, name, var_decl = m.group(1), m.group(2), m.group(3) or ""
            if name in ops:
                continue
            ops[name] = {
                "type": kind,
                "variables": var_decl,
                "document": _extract_document(text, m.start()),
            }
        hosts.update(h.lower() for h in _HOST.findall(text))
        for lm in _LEAGUE_VALUE.finditer(text):
            league_module = True
            window = text[max(0, lm.start() - 2000) : lm.end() + 2000]
            idp_branch = idp_branch or bool(_IDP.search(window))
            scarcity = scarcity or bool(_SCARCITY.search(window))
    server_league = any(
        o["type"] == "query"
        and re.search(r"(?i)league", name + o["document"])
        and re.search(r"(?i)value", name + o["document"])
        for name, o in ops.items()
    )
    counts = {"query": 0, "mutation": 0, "subscription": 0}
    for o in ops.values():
        counts[o["type"]] += 1
    classes = {c: False for c in ("fantasycalc", "ktc", "sleeper", "appsync", "cognito", "other")}
    for h in hosts:
        c = host_class(h)
        if c in classes:
            classes[c] = True
    return {
        "ran": True,
        "operationCounts": counts,
        "leagueValueModulePresent": league_module,
        "idpBranchPresent": idp_branch,
        "serverLeagueValueQuery": bool(server_league),
        "scarcityMarkers": scarcity,
        "hostClasses": classes,
        "_operations": ops,
        "_hosts": sorted(hosts),
    }


# ── Tiers 1b / 1c / 2 ────────────────────────────────────────────────────

_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^,)=]+?)(\s*=\s*[^,)]+)?\s*(?:,|\)|$)")


def required_variables(var_decl: str) -> list[str]:
    return [
        name
        for name, typ, default in _VAR.findall(var_decl or "")
        if typ.strip().endswith("!") and not default
    ]


def tier1b_candidates(ops: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for name in sorted(ops):
        o = ops[name]
        if o.get("type") != "query":
            continue
        if not re.search(r"(?i)value|dynasty|idp", name + str(o.get("document") or "")):
            continue
        if any(v not in SAFE_FILL for v in required_variables(str(o.get("variables") or ""))):
            continue
        out.append((name, dict(o)))
    return out[: TIER_BUDGETS["1b"]]


def _key_names(data: Any) -> set[str]:
    keys: set[str] = set()
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            keys.update(str(k) for k in node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node[:3])
    return keys


def _canonical_sha(data: Any) -> str:
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_ops(
    client: NonRecordingAppSync,
    ops: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    now: datetime,
    budget: int,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    stop = None
    for name, o in ops[:budget]:
        variables = {
            v: SAFE_FILL[v](now)
            for v in re.findall(r"\$([A-Za-z_]\w*)", str(o.get("variables") or ""))
            if v in SAFE_FILL
        }
        variables.update(o.get("fixedVariables") or {})
        try:
            res = client.query(str(o["document"]), variables)
        except ProbeStop as exc:
            stop = exc.outcome
            break
        results[name] = {
            "ok": res.get("errorCount") == 0 and res.get("data") is not None,
            "keys": sorted(_key_names(res.get("data"))),
            "sha256": _canonical_sha(res.get("data")),
            "_data": res.get("data"),
        }
    return {"results": results, "stop": stop}


def _items(data: Any) -> list[Mapping[str, Any]]:
    """Every dict in any list inside ``data`` (bounded)."""
    out: list[Mapping[str, Any]] = []
    stack = [data]
    while stack and len(out) < 20000:
        node = stack.pop()
        if isinstance(node, list):
            out.extend(x for x in node if isinstance(x, Mapping))
            stack.extend(x for x in node if isinstance(x, (list, Mapping)))
        elif isinstance(node, Mapping):
            stack.extend(v for v in node.values() if isinstance(v, (list, Mapping)))
    return out


def s1_from_items(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """S1 on the probed values: family tops within 5%? curves within +/-5% at
    k = 12 and 24?  ``None`` when a family has too few valued rows."""
    fams: dict[str, list[float]] = {"DL": [], "LB": [], "DB": []}
    for it in items:
        fam = RAW_TO_FAMILY.get(str(it.get("position") or "").upper())
        v = S._positive_number(it.get("value"))
        if fam and v is not None:
            fams[fam].append(v)
    for f in fams:
        fams[f].sort(reverse=True)
    if any(len(v) < 24 for v in fams.values()):
        return {"familyTopsWithin5pct": None, "curvesWithin5pct": None}
    tops = [v[0] for v in fams.values()]
    tops_close = (max(tops) - min(tops)) / max(tops) <= 0.05

    def _close(k: int) -> bool:
        shapes = [v[k - 1] / v[0] for v in fams.values()]
        return max(shapes) - min(shapes) <= 0.05

    return {"familyTopsWithin5pct": tops_close, "curvesWithin5pct": _close(12) and _close(24)}


def tier1c_findings(run: Mapping[str, Any], ops: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    results = run.get("results") or {}
    if not results or not all(r.get("ok") for r in results.values()):
        return {"ran": True, "ok": False, "stop": run.get("stop")}
    var_text = " ".join(
        str(o.get("variables") or "") + str(o.get("document") or "")[:400] for o in ops.values()
    )
    items = [it for r in results.values() for it in _items(r.get("_data"))]
    cov = {p: 0 for p in IDP_RAW_POSITIONS}
    for it in items:
        p = str(it.get("position") or "").upper()
        if p in cov:
            cov[p] += 1
    return {
        "ran": True,
        "ok": True,
        "scoringInputs": bool(_SCORING.search(var_text)),
        "rosterInputs": bool(_ROSTER.search(var_text)),
        "settingsInputs": bool(_SETTINGS.search(var_text)),
        "idpCoverage": cov,
        "s1": s1_from_items(items),
    }


# ── preflight ────────────────────────────────────────────────────────────

ShowFn = Callable[[str, tuple[str, ...]], Mapping[str, str]]


def _usec_realtime(text: Any) -> datetime | None:
    s = str(text or "").strip()
    if not s or s in ("n/a", "0"):
        return None
    if s.isdigit():
        return datetime.fromtimestamp(int(s) / 1e6, tz=timezone.utc)
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", s)
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00") if m else None


def _ident(text: Any) -> str:
    out = re.sub(r"[^A-Za-z0-9_]", "_", str(text or "unknown"))[:60]
    return out if out[:1].isalpha() else f"r_{out}"[:60]


def preflight(
    *,
    now: datetime,
    show: ShowFn,
    auth_store: Any,
    window_seconds: float,
    getuid: Callable[[], int] = os.getuid,
) -> tuple[dict[str, Any], str | None]:
    """Plan §3.3 tier P.  Returns ``(public checks, token-or-None)``.

    Every check fails CLOSED: an unreadable timer, an unknown service state,
    an auth store owned by another user or a token that would expire inside
    the window is BLOCKED — the probe never works around it."""
    checks: dict[str, Any] = {}
    reasons: list[str] = []
    try:
        owned = os.stat(auth_store.root).st_uid == getuid()
    except (OSError, AttributeError):
        owned = False
    checks["authStoreOwnedByRunner"] = owned
    if not owned:
        reasons.append("auth_store_owner_mismatch")
    margin = window_seconds + PREFLIGHT_MARGIN_SECONDS
    for unit in TIMERS:
        role = "collector" if "values" in unit else "renewal"
        t = show(f"{unit}.timer", ("NextElapseUSecRealtime",))
        svc = show(f"{unit}.service", ("ActiveState",))
        nxt = _usec_realtime(t.get("NextElapseUSecRealtime"))
        clear = nxt is not None and (nxt - now).total_seconds() > margin
        idle = svc.get("ActiveState") not in ("active", "activating", "deactivating", None)
        checks[f"{role}TimerClear"] = clear
        checks[f"{role}ServiceIdle"] = idle
        if not clear:
            reasons.append(f"{role}_timer_due")
        if not idle:
            reasons.append(f"{role}_service_running")
    if owned:
        token, why = SA.peek_fresh_access_token(
            auth_store, min_remaining_seconds=margin, now_fn=lambda: now.timestamp()
        )
    else:
        token, why = None, "not_read"
    checks["tokenFreshForWindow"] = token is not None
    checks["tokenReason"] = _ident(why)
    if token is None:
        reasons.append(_ident(f"token_{why}"))
    checks["ok"] = not reasons
    checks["reasons"] = sorted(reasons)
    return checks, token if not reasons else None


# ── orchestration ────────────────────────────────────────────────────────


def run_bundle_mode(http_get: S.HttpGet = S.urllib_get) -> dict[str, Any]:
    b = fetch_bundle(http_get)
    if not b.get("ok"):
        return {"mode": "bundle", "tier0": {"ran": True, "ok": False, "reason": b.get("reason")}}
    t0 = analyse_bundle(b["texts"])
    t0.update(
        ok=True, gets=b["gets"], megabytes=round(b["bytes"] / 1e6, 1), truncated=b["truncated"]
    )
    return {"mode": "bundle", "tier0": t0}


def run_native_probe(
    *,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    show: ShowFn,
    auth_store: Any,
    http_get: S.HttpGet = S.urllib_get,
    http_post: S.HttpPost = S.urllib_post,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    store_root: Path | None = None,
    league_ops: Mapping[str, Mapping[str, Any]] | None = None,
    allow_league_footprint: bool = False,
    review: Mapping[str, Any] | None = None,
    getuid: Callable[[], int] = os.getuid,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "mode": "native_probe",
        "decisionRuleSha256": decision_rule_sha256()[:12],
    }
    deadline = monotonic() + MAX_WALL_SECONDS

    def _pf(label: str) -> str | None:
        checks, token = preflight(
            now=now_fn(),
            show=show,
            auth_store=auth_store,
            window_seconds=MAX_WALL_SECONDS,
            getuid=getuid,
        )
        report.setdefault("preflight", {})[label] = checks
        return token

    token = _pf("start")
    if token is None:
        report["status"] = "BLOCKED"
        report["decision"] = evaluate_decision(report, review)
        return report

    bundle = run_bundle_mode(http_get)
    report["tier0"] = bundle["tier0"]
    ops = (bundle["tier0"] or {}).get("_operations") or {}

    token = _pf("before_1b")
    if token is None:
        report["status"] = "BLOCKED"
        report["decision"] = evaluate_decision(report, review)
        return report
    client = NonRecordingAppSync(token, http_post=http_post, deadline=deadline, clock=monotonic)
    cands = tier1b_candidates(ops)
    r1b = run_ops(client, cands, now=now_fn(), budget=TIER_BUDGETS["1b"])
    report["tier1b"] = {
        "ran": True,
        "candidates": len(cands),
        "attempted": len(r1b["results"]),
        "ok": sum(1 for r in r1b["results"].values() if r["ok"]),
        "keyNameCount": len({k for r in r1b["results"].values() for k in r["keys"]}),
        "stop": r1b["stop"],
        "_results": {
            k: {kk: v[kk] for kk in ("ok", "keys", "sha256")} for k, v in r1b["results"].items()
        },
    }

    r1c = None
    if not (bundle["tier0"] or {}).get("serverLeagueValueQuery"):
        report["tier1c"] = {"ran": False, "skipped": "no_server_league_value_query"}
    elif not allow_league_footprint:
        report["tier1c"] = {"ran": False, "skipped": "owner_decision_6_not_given"}
    elif not league_ops:
        report["tier1c"] = {"ran": False, "skipped": "no_private_ops_file"}
    else:
        listed = [(n, dict(o)) for n, o in sorted(league_ops.items())]
        for _n, o in listed:
            assert_read_only(str(o.get("document") or ""))
        r1c = run_ops(client, listed, now=now_fn(), budget=TIER_BUDGETS["1c"])
        report["tier1c"] = tier1c_findings(r1c, league_ops)

    board_before = _idp_content_sha(store_root)
    remaining = deadline - monotonic()
    if remaining < DETERMINISM_GAP_SECONDS + 60:
        report["tier2"] = {"ran": False, "skipped": "wall_clock"}
    else:
        sleep(DETERMINISM_GAP_SECONDS)
        token = _pf("before_2")
        if token is None:
            report["tier2"] = {"ran": False, "skipped": "preflight_failed"}
        else:
            client._token = token
            again = [(n, o) for n, o in cands if n in r1b["results"]]
            if r1c is not None:
                again += [(n, dict(o)) for n, o in sorted((league_ops or {}).items())]
            r2 = run_ops(client, again, now=now_fn(), budget=TIER_BUDGETS["2"])
            first = {**r1b["results"], **((r1c or {}).get("results") or {})}
            changed = sum(
                1 for n, r in r2["results"].items() if first.get(n, {}).get("sha256") != r["sha256"]
            )
            board_after = _idp_content_sha(store_root)
            report["tier2"] = {
                "ran": True,
                "compared": len(r2["results"]),
                "equal": changed == 0 and bool(r2["results"]),
                "changedOps": changed,
                "publicationBetween": (
                    None
                    if board_before is None or board_after is None
                    else board_before != board_after
                ),
                "stop": r2["stop"],
                "_boardSha12": [(board_before or "")[:12], (board_after or "")[:12]],
            }
    report["appsyncRequests"] = client.requests
    report["status"] = "COMPLETE"
    report["decision"] = evaluate_decision(report, review)
    return report


def _idp_content_sha(store_root: Path | None) -> str | None:
    if store_root is None:
        return None
    try:
        latest = json.loads((S.values_root(store_root) / "idp" / "latest.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return latest.get("contentSha256") if isinstance(latest, dict) else None


PUBLIC_PATHS: tuple[str, ...] = (
    "mode",
    "status",
    "decisionRuleSha256",
    "appsyncRequests",
    "preflight.*.*",
    "tier0.ran",
    "tier0.ok",
    "tier0.reason",
    "tier0.gets",
    "tier0.megabytes",
    "tier0.truncated",
    "tier0.operationCounts.*",
    "tier0.leagueValueModulePresent",
    "tier0.idpBranchPresent",
    "tier0.serverLeagueValueQuery",
    "tier0.scarcityMarkers",
    "tier0.hostClasses.*",
    "tier1b.ran",
    "tier1b.candidates",
    "tier1b.attempted",
    "tier1b.ok",
    "tier1b.keyNameCount",
    "tier1b.stop",
    "tier1c.ran",
    "tier1c.ok",
    "tier1c.skipped",
    "tier1c.stop",
    "tier1c.scoringInputs",
    "tier1c.rosterInputs",
    "tier1c.settingsInputs",
    "tier1c.idpCoverage.*",
    "tier1c.s1.*",
    "tier2.ran",
    "tier2.skipped",
    "tier2.compared",
    "tier2.equal",
    "tier2.changedOps",
    "tier2.publicationBetween",
    "tier2.stop",
    "decision.ruleSha256",
    "decision.conditions.*",
    "decision.verdict",
    "decision.q5ScarcityOrReplacementMarkers",
    "decision.q6ValueComputedWhere",
)


def public_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in PUBLIC_PATHS:
        _project(report, path.split("."), out)
    out = _prune(out)
    # preflight reasons are a list of enums: flatten to booleans
    for label, checks in (out.get("preflight") or {}).items():
        if isinstance(checks, dict) and isinstance(checks.get("reasons"), list):
            checks["reasons"] = {r: True for r in checks["reasons"]}
    assert_public_safe(out)
    return out


# ── CLI ──────────────────────────────────────────────────────────────────


def _write_private(path: Path, obj: Any) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)


def _load_private_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("bundle", "native-probe"), required=True)
    ap.add_argument("--app-dir", type=Path, default=REPO)
    ap.add_argument("--auth-dir", default=None)
    ap.add_argument(
        "--allow-league-footprint",
        action="store_true",
        help="Tier 1c: owner decision 6 recorded (widens the authenticated footprint)",
    )
    ap.add_argument("--league-ops", type=Path, default=None, help="private Tier 1c ops file")
    ap.add_argument("--review-evidence", type=Path, default=None)
    args = ap.parse_args(argv)
    logging.getLogger().handlers[:] = [logging.NullHandler()]
    try:
        if args.mode == "bundle":
            report = run_bundle_mode()
            public = public_projection(report)
        else:
            app_dir = args.app_dir.resolve()
            reports = app_dir / "data" / "sources" / "signals" / "reports"
            reports.mkdir(mode=0o700, parents=True, exist_ok=True)
            utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log = reports / f"native-probe-{utc}.log"
            handler = logging.FileHandler(log, encoding="utf-8")
            os.chmod(log, 0o600)
            logging.getLogger().handlers[:] = [handler]
            from src.sources.signals_health import systemd_show  # noqa: PLC0415

            report = run_native_probe(
                show=systemd_show,
                auth_store=SA.SignalsStore.open(args.auth_dir),
                store_root=app_dir / "data" / "sources" / "signals",
                league_ops=_load_private_json(args.league_ops),
                allow_league_footprint=args.allow_league_footprint,
                review=_load_private_json(args.review_evidence),
            )
            _write_private(reports / f"native_probe_{utc}.json", report)
            public = public_projection(report)
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 — class name only
        logging.getLogger("signals-native-probe").error("failed", exc_info=True)
        print(json.dumps({"error": type(exc).__name__}), flush=True)
        return 1
    print(json.dumps(public, sort_keys=True), flush=True)
    return 0 if public.get("status") != "BLOCKED" else 3


__all__ = ["PublicLeak", "evaluate_decision", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
