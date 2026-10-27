#!/usr/bin/env python3
"""Own-league historical trade and draft census (IDP market directive, Phase 1, Lane A).

RESEARCH ONLY.  No runtime wiring, no ``src/`` behaviour change, no route.  Nothing
in ``src/`` may import this script (``tests/league_valuation/test_isolation.py``).

What it does, in order:

1. **Collect** (read-only, public Sleeper API) — walks the WHOLE
   ``previous_league_id`` chain from ``dynasty_main`` through
   ``sleeper_client.walk_league_chain_status`` and, per season league, fetches
   the league object, users, rosters, ``/traded_picks``, every
   ``/transactions/{week}`` for weeks 0..18 plus a probe of weeks 19..25 (any
   extra leg the host exposes), every draft and its picks.  Every call goes
   through the client's CLASSIFIED fetchers, paced (default 0.2 s) and retried
   on 429 with a bounded backoff, so "Sleeper refused us" never reads as "no
   transactions".  The raw responses are written as ONE private bundle under
   the gitignored ``data/research/own_league_census/``; ``--bundle`` replays a
   saved bundle with no network.
2. **Validate** — dedupe by ``transaction_id`` across weeks and seasons, keep
   ``type == "trade"`` and ``status == "complete"`` only (exclusions counted),
   account for every leg (adds / drops / picks / FAAB vs ``roster_ids``),
   replay every pick transfer chronologically against default ownership and
   check it against each season league's ``/traded_picks`` folded by the ONE
   ownership owner (``src.identity.picks.build_pick_ownership``), and resolve
   every player id through ``src.identity.resolution`` (canonical V2, via
   ``market_trade_normalize.IdentityContext`` — no second matcher).
3. **Classify** — each trade becomes the normalized own-league observation
   shape (``market_trade_normalize._own_asset``) and goes through the existing
   grouping (``market_trade_groups.group_observations``), topology
   (``market_trade_eval.classify_topology``) and fit gate
   (``market_trade_eval.fit_suitability``).  IDP family (DL / LB / DB) uses the
   position the player was DRAFTED at in a chain draft at or before the trade
   season where one exists, else the current Sleeper directory (basis counted).
4. **Price coverage** — every asset at the trade instant (``status_updated``,
   else ``created``) through ``src.history.asof.batch_known_before``:
   instant-strict, never a later observation, never today's value, never 0.
   Lanes: ``canonical_board``, ``source_value:idpTradeCalc``,
   ``source_value:ktcSfTep``.  Missing carries one structured reason:
   ``before_history_boundary`` / ``no_observation`` / ``unresolved_identity`` /
   ``pick_unpriced``.
5. **Format validation** — each season's league object through
   ``market_trade_format.format_from_sleeper_league`` and ``compare_formats``
   against today's league.
6. **Write** — (a) transaction-level PRIVATE evidence (roster / user /
   transaction ids) to ``data/research/own_league_census/`` only; (b) committed
   anonymized aggregates (JSON + Markdown).  Teams appear as ``T01..Tnn``
   (roster-id order, per season).  The committed text is scanned before it is
   written: any digit run of 9+ characters that is not one of the chain's
   league ids, or any league member's display / team name, refuses the write.

Exit codes: 0 census written, every validation clean; 1 census written with
validation findings (named in the output); 2 collection incomplete (a fetch
failed or the chain did not verify) — no committed output written; 3 bad
arguments, unreadable input, or the anonymization scan refused the write.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.history import asof  # noqa: E402
from src.history.store import HISTORY_FLOOR, LANE_CANONICAL, LANE_SOURCE  # noqa: E402
from src.identity.picks import (  # noqa: E402
    LeaguePickIdentity,
    MarketPickRef,
    build_pick_ownership,
    traded_picks_observation,
)
from src.public_league import sleeper_client as sc  # noqa: E402
from src.trade import market_trade_eval as mte  # noqa: E402
from src.trade import market_trade_format as mtf  # noqa: E402
from src.trade import market_trade_groups as grp  # noqa: E402
from src.trade import market_trade_normalize as mtn  # noqa: E402
from src.utils.name_clean import normalize_position  # noqa: E402

SCHEMA = "own_league_history_census/v1"
DEFAULT_LEAGUE_ID = "1312006700437352448"
DEFAULT_LEAGUE_KEY = "dynasty_main"
DEFAULT_PRIVATE_DIR = REPO / "data" / "research" / "own_league_census"
DEFAULT_DOC_MD = REPO / "docs" / "market_trades" / "OWN_LEAGUE_HISTORY_CENSUS_2026-10-27.md"
DEFAULT_DOC_JSON = (
    REPO / "docs" / "market_trades" / "evidence" / "own_league_census_2026-10-27.json"
)
#: The archive the 107-trade count in
#: ``docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md`` §5.4 was read
#: from (pinned in that run's ``disclosure_shadow.json``).
DEFAULT_RECONCILE_ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20261020_052241.zip"

WEEKS = tuple(range(0, 19))
PROBE_WEEKS = tuple(range(19, 26))

OFFENSE = ("QB", "RB", "WR", "TE")
IDP = ("DL", "LB", "DB")
FAMILY_ORDER = (*OFFENSE, *IDP, "K", "OTHER", "UNKNOWN")

LANES: tuple[tuple[str, str, str], ...] = (
    ("canonical", LANE_CANONICAL, ""),
    ("idptc", LANE_SOURCE, "idpTradeCalc"),
    ("ktc", LANE_SOURCE, "ktcSfTep"),
)

REASON_BOUNDARY = "before_history_boundary"
REASON_NO_OBS = "no_observation"
REASON_UNRESOLVED = "unresolved_identity"
REASON_PICK = "pick_unpriced"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_INCOMPLETE = 2
EXIT_BAD_INPUT = 3


# ── Collection ───────────────────────────────────────────────────────────


class Fetcher:
    """Paced, bounded-retry wrapper over the client's CLASSIFIED fetchers.

    ``sleeper_client`` has no pacing of its own and maps a 429 to
    ``rate_limited``; this adds the pause between calls and a bounded backoff,
    and records every outcome so an incomplete collection is never silent.
    """

    def __init__(self, pace: float = 0.2, retries: int = 3, sleep: Callable = time.sleep):
        self.pace = pace
        self.retries = retries
        self.sleep = sleep
        self.calls: Counter[str] = Counter()
        self.failures: list[dict[str, Any]] = []

    def __call__(self, label: str, fn: Callable[..., tuple[str, Any]], *args: Any) -> Any:
        backoff = 2.0
        for attempt in range(self.retries + 1):
            if self.pace:
                self.sleep(self.pace)
            kind, payload = fn(*args)
            self.calls[kind] += 1
            if kind == sc.FETCH_OK:
                return payload
            if kind == sc.FETCH_RATE_LIMITED and attempt < self.retries:
                self.sleep(backoff)
                backoff *= 2
                continue
            self.failures.append({"call": label, "args": [str(a) for a in args], "kind": kind})
            return None
        return None  # pragma: no cover - loop always returns


def collect(start_league_id: str, fetch: Fetcher) -> dict[str, Any]:
    """Every raw response the census reads, keyed by season league id."""

    def _league(lid: str) -> tuple[str, Any]:
        if fetch.pace:
            fetch.sleep(fetch.pace)
        kind, payload = sc.fetch_league_classified(lid)
        fetch.calls[kind] += 1
        return kind, payload

    chain, coverage = sc.walk_league_chain_status(start_league_id, fetch_league_fn=_league)
    seasons: dict[str, Any] = {}
    for league in chain:
        lid = str(league["league_id"])
        tx: dict[str, Any] = {}
        for week in (*WEEKS, *PROBE_WEEKS):
            tx[str(week)] = fetch(
                f"transactions:{week}", sc.fetch_transactions_classified, lid, week
            )
        drafts = fetch("drafts", sc.fetch_drafts_classified, lid)
        picks: dict[str, Any] = {}
        for d in drafts or []:
            did = str(d.get("draft_id"))
            picks[did] = fetch("draft_picks", sc.fetch_draft_picks_classified, did)
        seasons[lid] = {
            "league": league,
            "users": fetch("users", sc.fetch_league_users_classified, lid),
            "rosters": fetch("rosters", sc.fetch_rosters_classified, lid),
            "tradedPicks": fetch("traded_picks", sc.fetch_traded_picks_classified, lid),
            "transactions": tx,
            "drafts": drafts,
            "draftPicks": picks,
        }
    return {
        "schema": "own_league_census_raw/v1",
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "startLeagueId": start_league_id,
        "chainCoverage": coverage,
        "chainOrder": [str(lg["league_id"]) for lg in chain],
        "seasons": seasons,
        "fetch": {"calls": dict(fetch.calls), "failures": fetch.failures},
    }


def attach_player_subset(bundle: dict[str, Any], directory: Mapping[str, Any]) -> None:
    """Keep only the directory rows the bundle references (ids from trades and drafts)."""
    ids: set[str] = set()
    for s in bundle["seasons"].values():
        for txs in (s.get("transactions") or {}).values():
            for t in txs or []:
                ids.update(str(k) for k in (t.get("adds") or {}))
                ids.update(str(k) for k in (t.get("drops") or {}))
        for plist in (s.get("draftPicks") or {}).values():
            for p in plist or []:
                if p.get("player_id"):
                    ids.add(str(p["player_id"]))
    keep = ("player_id", "full_name", "first_name", "last_name", "position", "team")
    keep += ("fantasy_positions", "years_exp", "status", "search_full_name")
    bundle["players"] = {
        pid: {k: directory[pid].get(k) for k in keep if k in directory[pid]}
        for pid in sorted(ids)
        if isinstance(directory.get(pid), Mapping)
    }
    bundle["playersDirectoryState"] = "available" if directory else "unavailable"


# ── Small helpers ────────────────────────────────────────────────────────


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _iso_ms(ms: Any) -> str | None:
    m = _int(ms)
    return datetime.fromtimestamp(m / 1000, tz=timezone.utc).isoformat() if m else None


def family_of(position: Any) -> str:
    fam = normalize_position(position)
    if fam in OFFENSE or fam in IDP or fam == "K":
        return fam
    return "UNKNOWN" if not fam else "OTHER"


def _quantiles(values: Sequence[float]) -> dict[str, Any] | None:
    vals = sorted(values)
    if not vals:
        return None
    out: dict[str, Any] = {
        "n": len(vals),
        "min": vals[0],
        "median": statistics.median(vals),
        "max": vals[-1],
    }
    if len(vals) >= 4:
        q = statistics.quantiles(vals, n=4, method="inclusive")
        out["p25"], out["p75"] = q[0], q[2]
    return out


def team_labels(roster_ids: Iterable[Any]) -> dict[int, str]:
    """``T01..Tnn`` by roster-id order — stable within one season, never an id."""
    rids = sorted({r for r in (_int(x) for x in roster_ids) if r is not None})
    return {rid: f"T{i + 1:02d}" for i, rid in enumerate(rids)}


# ── Transactions: dedupe, status, legs ───────────────────────────────────


def season_transactions(season: Mapping[str, Any]) -> tuple[list[dict], dict[str, Any]]:
    """Every transaction of one season league, deduped by ``transaction_id``.

    Returns ``(unique_transactions, stats)``.  A week whose fetch failed is
    ``None`` and counted, never read as an empty week.
    """
    seen: dict[str, str] = {}
    out: list[dict] = []
    weeks_failed: list[int] = []
    dup_within = 0
    by_week: Counter[int] = Counter()
    for wk, txs in sorted((season.get("transactions") or {}).items(), key=lambda kv: int(kv[0])):
        if txs is None:
            weeks_failed.append(int(wk))
            continue
        for t in txs:
            tid = str(t.get("transaction_id") or "")
            if not tid:
                tid = f"noid:{wk}:{t.get('created')}:{sorted(t.get('roster_ids') or [])}"
            if tid in seen:
                dup_within += 1
                continue
            seen[tid] = wk
            row = dict(t)
            row["_week"] = int(wk)
            row["_txid"] = tid
            out.append(row)
            by_week[int(wk)] += 1
    return out, {
        "weeksFailed": weeks_failed,
        "duplicatesAcrossWeeks": dup_within,
        "transactionsByWeek": dict(sorted(by_week.items())),
    }


def leg_findings(t: Mapping[str, Any]) -> list[str]:
    """Every leg of a trade accounted for against its ``roster_ids``."""
    parties = {r for r in (_int(x) for x in t.get("roster_ids") or []) if r is not None}
    adds = {str(k): _int(v) for k, v in (t.get("adds") or {}).items()}
    drops = {str(k): _int(v) for k, v in (t.get("drops") or {}).items()}
    out: list[str] = []
    for pid, rid in adds.items():
        if rid not in parties:
            out.append("add_roster_not_party")
        if pid not in drops:
            out.append("add_without_sender")
        elif drops[pid] == rid:
            out.append("add_from_own_roster")
    for pid, rid in drops.items():
        if rid not in parties:
            out.append("drop_roster_not_party")
        if pid not in adds:
            out.append("released_in_trade")
    for p in t.get("draft_picks") or []:
        owner, prev = _int(p.get("owner_id")), _int(p.get("previous_owner_id"))
        if owner not in parties:
            out.append("pick_receiver_not_party")
        if prev not in parties:
            out.append("pick_sender_not_party")
        if owner is not None and owner == prev:
            out.append("pick_self_transfer")
        if _int(p.get("round")) is None or _int(p.get("season")) is None:
            out.append("pick_identity_incomplete")
    for w in t.get("waiver_budget") or []:
        if _int(w.get("sender")) not in parties or _int(w.get("receiver")) not in parties:
            out.append("faab_party_not_party")
        if not _int(w.get("amount")):
            out.append("faab_amount_missing_or_zero")
    received = set(adds.values()) | {_int(p.get("owner_id")) for p in t.get("draft_picks") or []}
    received |= {_int(w.get("receiver")) for w in t.get("waiver_budget") or []}
    sent = set(drops.values()) | {
        _int(p.get("previous_owner_id")) for p in t.get("draft_picks") or []
    }
    sent |= {_int(w.get("sender")) for w in t.get("waiver_budget") or []}
    for rid in parties:
        if rid not in received and rid not in sent:
            out.append("party_moves_nothing")
        elif rid not in received:
            out.append("party_receives_nothing")
    return out


# ── Pick-ownership replay ────────────────────────────────────────────────


def pick_replay(
    ordered_seasons: Sequence[Mapping[str, Any]],
    *,
    league_key: str,
) -> dict[str, Any]:
    """Replay every pick transfer (trades AND commissioner moves) oldest-first
    from default ownership; check each transfer's sender is the tracked owner,
    and each season league's ``/traded_picks`` (folded by the ONE ownership
    owner) against the replay state at the end of that league's transactions.

    ``ordered_seasons`` = ``[{"season", "leagueId", "transactions", "rosters",
    "tradedPicks", "draftRounds"}]`` oldest -> newest.
    """
    state: dict[tuple[int, int, int], int] = {}
    transfers = 0
    inconsistent: list[dict[str, Any]] = []
    by_type: Counter[str] = Counter()
    checkpoints: list[dict[str, Any]] = []
    for s in ordered_seasons:
        rows = []
        for t in s["transactions"]:
            if t.get("status") != "complete" or not t.get("draft_picks"):
                continue
            rows.append(t)
        rows.sort(key=lambda t: (_int(t.get("status_updated")) or 0, _int(t.get("created")) or 0))
        for t in rows:
            for p in t.get("draft_picks") or []:
                season, rnd, origin = (
                    _int(p.get("season")),
                    _int(p.get("round")),
                    _int(p.get("roster_id")),
                )
                owner, prev = _int(p.get("owner_id")), _int(p.get("previous_owner_id"))
                if None in (season, rnd, origin, owner):
                    continue
                key = (season, rnd, origin)
                tracked = state.get(key, origin)
                transfers += 1
                by_type[str(t.get("type"))] += 1
                if prev is not None and prev != tracked:
                    inconsistent.append(
                        {
                            "txid": t.get("_txid") or t.get("transaction_id"),
                            "type": t.get("type"),
                            "pick": list(key),
                            "previousOwnerStated": prev,
                            "trackedOwner": tracked,
                        }
                    )
                state[key] = owner
        observed = traded_picks_observation(s.get("tradedPicks"))
        rids = sorted(
            {r for r in (_int(x.get("roster_id")) for x in s.get("rosters") or []) if r is not None}
        )
        if observed is None or not rids:
            checkpoints.append(
                {
                    "season": s["season"],
                    "state": "unavailable",
                    "reason": "traded_picks_not_observed" if observed is None else "no_rosters",
                }
            )
            continue
        seasons = sorted({_int(r.get("season")) for r in observed} - {None})
        rounds = max(
            [_int(s.get("draftRounds")) or 0] + [_int(r.get("round")) or 0 for r in observed]
        )
        owned = build_pick_ownership(
            league_key, rids, observed, seasons=seasons, rounds=max(1, rounds)
        )
        mismatches = []
        for op in owned:
            ident = op.identity
            key = (ident.season, ident.round_num, ident.origin_roster_id)
            replayed = state.get(key, ident.origin_roster_id)
            if replayed != op.state.owner_roster_id:
                mismatches.append(
                    {
                        "pick": list(key),
                        "hostOwner": op.state.owner_roster_id,
                        "replayedOwner": replayed,
                    }
                )
        checkpoints.append(
            {
                "season": s["season"],
                "state": "compared",
                "pickSeasonsCompared": seasons,
                "rounds": rounds,
                "picksCompared": len(owned),
                "mismatches": len(mismatches),
                "_mismatchDetail": mismatches,
            }
        )
    return {
        "transfersReplayed": transfers,
        "transfersByTransactionType": dict(sorted(by_type.items())),
        "inconsistentTransfers": len(inconsistent),
        "_inconsistentDetail": inconsistent,
        "checkpoints": checkpoints,
    }


# ── Drafts ───────────────────────────────────────────────────────────────

PLAYER_TYPE_LABEL = {0: "all_players", 1: "rookies_only", 2: "veterans_only"}


def draft_kind(draft: Mapping[str, Any], picks: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    """``(kind, basis)`` — rookie / startup / unclassified, with the evidence named."""
    settings = draft.get("settings") or {}
    ptype = _int(settings.get("player_type"))
    if ptype == 1:
        return "rookie", "settings.player_type=1 (rookies only)"
    if ptype == 2:
        return "startup_veteran", "settings.player_type=2 (veterans only)"
    yrs = [_int((p.get("metadata") or {}).get("years_exp")) for p in picks]
    known = [y for y in yrs if y is not None]
    if known:
        share = sum(1 for y in known if y == 0) / len(known)
        if share >= 0.5:
            return "rookie", f"player_type={ptype}; {share:.0%} of picks years_exp=0"
        return "startup_veteran", f"player_type={ptype}; {share:.0%} of picks years_exp=0"
    return "unclassified", f"player_type={ptype}; no picks"


def draft_census(
    seasons: Sequence[Mapping[str, Any]], players: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, list[tuple[int, str]]]]:
    """Aggregates per draft plus ``player_id -> [(season, drafted position)]``
    (as-of position evidence for trade classification)."""
    drafted_pos: dict[str, list[tuple[int, str]]] = defaultdict(list)
    per_draft: list[dict[str, Any]] = []
    for s in seasons:
        for d_idx, d in enumerate(s.get("drafts") or [], start=1):
            did = str(d.get("draft_id"))
            plist = (s.get("draftPicks") or {}).get(did)
            picks = list(plist or [])
            kind, basis = draft_kind(d, picks)
            settings = d.get("settings") or {}
            dtype = str(d.get("type") or "unknown")
            by_round: dict[int, Counter[str]] = defaultdict(Counter)
            amounts_by_family: dict[str, list[int]] = defaultdict(list)
            idp_order: dict[str, list[int]] = defaultdict(list)
            amount_states: Counter[str] = Counter()
            pos_disagree = 0
            for p in picks:
                meta = p.get("metadata") or {}
                fam = family_of(meta.get("position"))
                rnd = _int(p.get("round")) or 0
                by_round[rnd][fam] += 1
                pid = str(p.get("player_id") or "")
                season_i = _int(d.get("season")) or _int(s.get("season")) or 0
                if pid and meta.get("position"):
                    drafted_pos[pid].append((season_i, fam))
                    cur = family_of((players.get(pid) or {}).get("position"))
                    if cur not in ("UNKNOWN",) and cur != fam:
                        pos_disagree += 1
                # ``amount`` is the auction price; a snake / linear draft has
                # none, which is ``None`` — never 0.
                amt = _int(meta.get("amount")) if dtype == "auction" else None
                if dtype == "auction":
                    amount_states["recorded" if amt is not None else "missing"] += 1
                    if amt is not None:
                        amounts_by_family[fam].append(amt)
                else:
                    amount_states["not_applicable_non_auction"] += 1
                pick_no = _int(p.get("pick_no"))
                if fam in IDP and pick_no is not None:
                    idp_order[fam].append(pick_no)
            all_idp = sorted(n for v in idp_order.values() for n in v)
            n = len(picks)
            rounds = sorted(by_round)
            per_draft.append(
                {
                    "season": s["season"],
                    "draftRef": f"{s['season']}-D{d_idx}",
                    "type": dtype,
                    "status": d.get("status"),
                    "kind": kind,
                    "kindBasis": basis,
                    "playerType": PLAYER_TYPE_LABEL.get(
                        _int(settings.get("player_type")), "unknown"
                    ),
                    "rounds": _int(settings.get("rounds")),
                    "teams": _int(settings.get("teams")),
                    "picks": n,
                    "picksState": "observed" if plist is not None else "fetch_failed",
                    "draftOrderPublished": bool(d.get("draft_order")),
                    "slotToRosterPublished": bool(d.get("slot_to_roster_id")),
                    "picksByRoundAndFamily": {
                        str(r): {f: by_round[r][f] for f in FAMILY_ORDER if by_round[r][f]}
                        for r in rounds
                    },
                    "picksByFamily": {
                        f: sum(by_round[r][f] for r in rounds)
                        for f in FAMILY_ORDER
                        if sum(by_round[r][f] for r in rounds)
                    },
                    "offenseVsIdpByRound": {
                        str(r): {
                            "offense": sum(by_round[r][f] for f in OFFENSE),
                            "idp": sum(by_round[r][f] for f in IDP),
                            "other": sum(
                                c for f, c in by_round[r].items() if f not in OFFENSE + IDP
                            ),
                        }
                        for r in rounds
                    },
                    "idpShare": round(len(all_idp) / n, 4) if n else None,
                    "idpSelectionOrder": {
                        "allIdp": _quantiles(all_idp),
                        **{f: _quantiles(idp_order[f]) for f in IDP},
                        "firstIdpPickNo": all_idp[0] if all_idp else None,
                        "basis": "pick_no (overall selection order; in an auction, the order lots were won)",
                    },
                    "draftedPositionDiffersFromCurrentDirectory": pos_disagree,
                    "auction": (
                        {
                            "amountStates": dict(amount_states),
                            "budgetSetting": _int(settings.get("budget")),
                            # No recorded amount is not $0 spent.
                            "totalSpent": (
                                sum(sum(v) for v in amounts_by_family.values())
                                if amounts_by_family
                                else None
                            ),
                            "byFamily": {
                                f: {
                                    "picks": len(v),
                                    "total": sum(v),
                                    **(_quantiles(v) or {}),
                                }
                                for f, v in sorted(amounts_by_family.items())
                            },
                            "idpTotal": (
                                sum(sum(amounts_by_family[f]) for f in IDP)
                                if amounts_by_family
                                else None
                            ),
                            "offenseTotal": (
                                sum(sum(amounts_by_family[f]) for f in OFFENSE)
                                if amounts_by_family
                                else None
                            ),
                        }
                        if dtype == "auction"
                        else {"amountStates": dict(amount_states)}
                    ),
                }
            )
    rookie = [d for d in per_draft if d["kind"] == "rookie" and d["picks"]]
    changes = [
        {
            "season": d["season"],
            "draftRef": d["draftRef"],
            "type": d["type"],
            "picks": d["picks"],
            "idpShare": d["idpShare"],
            "firstIdpPickNo": d["idpSelectionOrder"]["firstIdpPickNo"],
            "idpMedianPickNo": (d["idpSelectionOrder"]["allIdp"] or {}).get("median"),
        }
        for d in sorted(rookie, key=lambda d: d["season"])
    ]
    return {"drafts": per_draft, "rookieDraftChanges": changes}, drafted_pos


# ── Prices ───────────────────────────────────────────────────────────────


def price_assets(
    requests: Sequence[dict[str, Any]], ledger: Path | None
) -> dict[str, list[dict[str, Any]]]:
    """Per lane, one result per request (request order).

    ``requests`` = ``[{"kind", "key" (history key or None), "instant", "pickTierKeys"}]``.
    A request without a key is never looked up: its reason is decided here
    (``unresolved_identity`` / ``pick_unpriced``), and the boundary still wins.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for lane_name, lane, skey in LANES:
        lookups = [(i, r) for i, r in enumerate(requests) if r.get("key")]
        got: dict[int, dict[str, Any]] = {}
        if lookups:
            res = asof.batch_known_before(
                [(r["key"], r["instant"]) for _, r in lookups],
                lane=lane,
                source_key=skey,
                path=ledger,
            )["results"]
            got = {i: res[j] for j, (i, _) in enumerate(lookups)}
        tier_hits: dict[int, int] = {}
        tier_reqs = [
            (i, k, r["instant"])
            for i, r in enumerate(requests)
            for k in r.get("pickTierKeys") or []
        ]
        if tier_reqs and lane == LANE_SOURCE:
            res = asof.batch_known_before(
                [(k, inst) for _, k, inst in tier_reqs], lane=lane, source_key=skey, path=ledger
            )["results"]
            for (i, _, _), rr in zip(tier_reqs, res):
                if rr["fidelity"] in (asof.FIDELITY_EXACT, asof.FIDELITY_NEAREST_PRIOR):
                    tier_hits[i] = tier_hits.get(i, 0) + 1
        lane_out: list[dict[str, Any]] = []
        for i, r in enumerate(requests):
            before_floor = r["instant"].date().isoformat() < HISTORY_FLOOR
            if i in got and got[i]["fidelity"] in (
                asof.FIDELITY_EXACT,
                asof.FIDELITY_NEAREST_PRIOR,
            ):
                g = got[i]
                lane_out.append(
                    {
                        "fidelity": g["fidelity"],
                        "value": g["value"],
                        "observedDate": g["observedDate"],
                        "ageDays": g["distanceDays"],
                        "reason": None,
                    }
                )
                continue
            if before_floor:
                reason = REASON_BOUNDARY
            elif r["kind"] == "pick":
                reason = REASON_PICK
            elif r["kind"] == "unresolved":
                reason = REASON_UNRESOLVED
            else:
                reason = REASON_NO_OBS
            item = {"fidelity": "missing", "value": None, "reason": reason}
            if r["kind"] == "pick":
                item["pickDetail"] = r.get("pickDetail")
                item["tierEvidenceKnownBefore"] = tier_hits.get(i, 0)
            lane_out.append(item)
        out[lane_name] = lane_out
    return out


# ── The census ───────────────────────────────────────────────────────────


def _season_view(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Season leagues oldest -> newest with their deduped transactions."""
    out = []
    for lid in reversed(bundle.get("chainOrder") or []):
        s = bundle["seasons"][lid]
        league = s.get("league") or {}
        txs, stats = season_transactions(s)
        out.append(
            {
                **s,
                "leagueId": lid,
                "season": str(league.get("season")),
                "teams": _int(league.get("total_rosters")),
                "draftRounds": _int((league.get("settings") or {}).get("draft_rounds")),
                "txs": txs,
                "txStats": stats,
            }
        )
    return out


def _asof_position(
    pid: str, season: int, drafted: Mapping[str, list[tuple[int, str]]], players: Mapping
) -> tuple[str, str]:
    prior = [(s, f) for s, f in drafted.get(pid, []) if s <= season]
    if prior:
        s, fam = max(prior)
        return fam, f"chain_draft_metadata_{s}"
    row = players.get(pid)
    if row:
        return family_of(row.get("position")), "current_sleeper_directory"
    return "UNKNOWN", "player_not_in_directory"


def build_census(
    bundle: Mapping[str, Any],
    *,
    ledger: Path | None,
    league_key: str = DEFAULT_LEAGUE_KEY,
    reconcile_trades: Sequence[Mapping[str, Any]] | None = None,
    reconcile_meta: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(committed_aggregates, private_evidence)`` from one raw bundle."""
    players: Mapping[str, Any] = bundle.get("players") or {}
    ctx = mtn.IdentityContext.from_directory(players or None, source="census_bundle_subset")
    seasons = _season_view(bundle)
    if not seasons:
        raise ValueError("bundle has no season leagues")
    today = seasons[-1]
    today_fmt = mtf.format_from_sleeper_league(today["league"])
    drafts, drafted = draft_census(seasons, players)

    # -- transactions, statuses, cross-season dedupe ------------------------
    seen_global: dict[str, str] = {}
    dup_across_seasons = 0
    trades: list[dict[str, Any]] = []
    tx_summary: dict[str, Any] = {}
    for s in seasons:
        types: Counter[str] = Counter()
        trade_status: Counter[str] = Counter()
        legs: Counter[str] = Counter()
        weeks_with_trades: Counter[int] = Counter()
        for t in s["txs"]:
            if t["_txid"] in seen_global:
                dup_across_seasons += 1
                continue
            seen_global[t["_txid"]] = s["season"]
            types[str(t.get("type"))] += 1
            if t.get("type") != "trade":
                continue
            trade_status[str(t.get("status"))] += 1
            if t.get("status") != "complete":
                continue
            weeks_with_trades[t["_week"]] += 1
            legs[f"week{t['_week']}:leg{t.get('leg')}"] += 1
            trades.append({"season": s["season"], "leagueId": s["leagueId"], "tx": t})
        offseason = sum(
            1
            for tr in trades
            if tr["season"] == s["season"]
            and (_int(tr["tx"].get("created")) or 0) < _season_week1_floor_ms(s)
        )
        tx_summary[s["season"]] = {
            "weeksFetched": sorted(int(w) for w in (s.get("transactions") or {})),
            "weeksFailed": s["txStats"]["weeksFailed"],
            "duplicatesAcrossWeeks": s["txStats"]["duplicatesAcrossWeeks"],
            "transactionsByType": dict(sorted(types.items())),
            "tradeStatuses": dict(sorted(trade_status.items())),
            "completedTradesByWeek": {str(k): v for k, v in sorted(weeks_with_trades.items())},
            "weekLegPairs": dict(sorted(legs.items())),
            "weeksBeyond18WithAnyTransaction": sorted(
                w for w, n in s["txStats"]["transactionsByWeek"].items() if w > 18 and n
            ),
            "week0Transactions": s["txStats"]["transactionsByWeek"].get(0, 0),
            "completedTradesCreatedBeforeSeptember": offseason,
        }

    # -- per-trade records --------------------------------------------------
    roster_owner: dict[tuple[str, int], str | None] = {}
    for s in seasons:
        for r in s.get("rosters") or []:
            rid = _int(r.get("roster_id"))
            if rid is not None:
                roster_owner[(s["season"], rid)] = r.get("owner_id")
    labels = {
        s["season"]: team_labels(r.get("roster_id") for r in s.get("rosters") or [])
        for s in seasons
    }

    records: list[dict[str, Any]] = []
    price_requests: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    unresolved_ids: set[str] = set()
    for tr in trades:
        t, season = tr["tx"], tr["season"]
        season_i = int(season)
        ms = _int(t.get("status_updated")) or _int(t.get("created"))
        instant = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        basis = "status_updated" if _int(t.get("status_updated")) else "created"
        parties = sorted({r for r in (_int(x) for x in t.get("roster_ids") or []) if r is not None})
        adds = {str(k): _int(v) for k, v in (t.get("adds") or {}).items()}
        drops = {str(k): _int(v) for k, v in (t.get("drops") or {}).items()}
        assets: list[dict[str, Any]] = []
        for pid, rid in adds.items():
            res = ctx.resolve_sleeper_id(pid)
            resolved = res is not None and res.status == "resolved"
            if not resolved:
                unresolved_ids.add(pid)
            fam, pbasis = _asof_position(pid, season_i, drafted, players)
            assets.append(
                {
                    "kind": "player" if resolved else "unresolved",
                    "playerId": pid,
                    "family": fam,
                    "positionBasis": pbasis,
                    "to": rid,
                    "from": drops.get(pid),
                }
            )
        for p in t.get("draft_picks") or []:
            ps, rnd, origin = _int(p.get("season")), _int(p.get("round")), _int(p.get("roster_id"))
            assets.append(
                {
                    "kind": "pick",
                    "pick": {"season": ps, "round": rnd, "origin": origin},
                    "family": "PICK",
                    "to": _int(p.get("owner_id")),
                    "from": _int(p.get("previous_owner_id")),
                }
            )
        for w in t.get("waiver_budget") or []:
            assets.append(
                {
                    "kind": "faab",
                    "amount": _int(w.get("amount")),
                    "family": "FAAB",
                    "to": _int(w.get("receiver")),
                    "from": _int(w.get("sender")),
                }
            )
        sides_by_rid: dict[int, list[dict[str, Any]]] = {rid: [] for rid in parties}
        for a in assets:
            if a["kind"] == "faab":
                norm = {"kind": "faab", "canonicalId": None, "amount": a["amount"]}
            elif a["kind"] == "pick":
                pk = a["pick"]
                try:
                    lid_ = LeaguePickIdentity(league_key, pk["season"], pk["round"], pk["origin"])
                    norm = mtn._own_asset(lid_.canonical_id, "pick", ctx)
                except (TypeError, ValueError):
                    norm = mtn._own_asset("unparseable", "pick", ctx)
            else:
                norm = mtn._own_asset(f"player:{a['playerId']}", "player", ctx)
                norm["position"] = a["family"] if a["family"] not in ("UNKNOWN", "OTHER") else None
            sides_by_rid.setdefault(a["to"], []).append(norm)
        sides = [sides_by_rid[rid] for rid in sorted(sides_by_rid)]
        obs = {
            "observationId": f"own_league_census:{tr['leagueId']}:{t['_txid']}",
            "sourceFamily": mtn.SOURCE_OWN_LEAGUE,
            "host": "sleeper",
            "hostLeagueId": tr["leagueId"],
            "hostTxId": t["_txid"],
            "leagueKey": league_key,
            "occurredDate": instant.date().isoformat(),
            "occurredAtMs": ms,
            "teamCount": len(parties),
            "sides": sides,
            "provenance": [mtn.PROVENANCE_BY_SOURCE[mtn.SOURCE_OWN_LEAGUE]],
            "caveats": [],
            "observationChannel": mtn.CHANNEL_SLEEPER,
            "marketFormat": mtf.format_from_sleeper_league(
                next(x for x in seasons if x["season"] == season)["league"]
            ).to_dict(),
        }
        observations.append(obs)
        rec = {
            "season": season,
            "txid": t["_txid"],
            "leagueId": tr["leagueId"],
            "week": t["_week"],
            "leg": t.get("leg"),
            "instant": instant.isoformat(),
            "instantBasis": basis,
            "createdAt": _iso_ms(t.get("created")),
            "statusUpdatedAt": _iso_ms(t.get("status_updated")),
            "rosterIds": parties,
            "managerIds": sorted(
                str(roster_owner.get((season, rid)))
                for rid in parties
                if roster_owner.get((season, rid))
            ),
            "teamLabels": [labels[season].get(rid, "T??") for rid in parties],
            "assets": assets,
            "legFindings": leg_findings(t),
            "observationId": obs["observationId"],
        }
        for a in assets:
            if a["kind"] == "faab":
                a["priceRequest"] = None
                continue
            if a["kind"] == "pick":
                pk = a["pick"]
                key, tiers, detail = None, [], "generic_grade_has_no_history_series"
                if pk["round"] is not None and pk["season"] is not None:
                    if 1 <= pk["round"] <= 6:
                        tiers = [
                            MarketPickRef(pk["season"], pk["round"], tier=tr_).canonical_id
                            for tr_ in ("early", "mid", "late")
                        ]
                    else:
                        detail = "round_beyond_market_grammar"
                else:
                    detail = "pick_identity_incomplete"
                req = {
                    "kind": "pick",
                    "key": key,
                    "instant": instant,
                    "pickTierKeys": tiers,
                    "pickDetail": detail,
                }
            elif a["kind"] == "unresolved":
                req = {"kind": "unresolved", "key": None, "instant": instant}
            else:
                req = {"kind": "player", "key": f"player:{a['playerId']}", "instant": instant}
            a["priceRequest"] = len(price_requests)
            price_requests.append(req)
        records.append(rec)

    prices = price_assets(price_requests, ledger)
    for rec in records:
        for a in rec["assets"]:
            idx = a.pop("priceRequest", None)
            if idx is not None:
                a["prices"] = {lane: prices[lane][idx] for lane in prices}

    # -- grouping / topology / fit (existing owners) ------------------------
    grouping = grp.group_observations(observations)
    group_by_obs = {m: g for g in grouping.groups for m in g["members"]}
    for rec in records:
        g = group_by_obs[rec["observationId"]]
        rec["dedupeState"] = g["dedupeState"]
        topo = mte.classify_topology(g)
        rec["topology"] = topo
        rec["fit"] = mte.fit_suitability(g, topo)
        rec["classes"] = classify_trade(rec)

    pick_check = pick_replay(
        [
            {
                "season": s["season"],
                "leagueId": s["leagueId"],
                "transactions": [t for t in s["txs"]],
                "rosters": s.get("rosters"),
                "tradedPicks": s.get("tradedPicks"),
                "draftRounds": s["draftRounds"],
            }
            for s in seasons
        ],
        league_key=league_key,
    )

    agg = aggregate(
        bundle,
        seasons,
        records,
        tx_summary,
        dup_across_seasons,
        grouping,
        pick_check,
        drafts,
        today_fmt,
        unresolved_ids,
        ledger,
        reconcile_trades,
        reconcile_meta,
    )
    private = {
        "schema": "own_league_history_census_private/v1",
        "warning": "PRIVATE: roster ids, manager user ids and transaction ids. Never commit.",
        "trades": records,
        "pickReplay": pick_check,
        "teamLabelMaps": {s: {str(k): v for k, v in m.items()} for s, m in labels.items()},
        "unresolvedPlayerIds": sorted(unresolved_ids),
    }
    return agg, private


def _season_week1_floor_ms(s: Mapping[str, Any]) -> int:
    """Sept 1 of the season year (UTC) — a coarse offseason marker for reporting only."""
    try:
        return int(datetime(int(s["season"]), 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def classify_trade(rec: Mapping[str, Any]) -> dict[str, Any]:
    """Census classes of one trade (definitions stated in the committed output)."""
    assets = rec["assets"]
    players = [a for a in assets if a["kind"] in ("player", "unresolved")]
    picks = [a for a in assets if a["kind"] == "pick"]
    faab = [a for a in assets if a["kind"] == "faab"]
    idp_fams = sorted({a["family"] for a in players if a["family"] in IDP})
    recv_idp = {a["to"] for a in players if a["family"] in IDP}
    recv_off = {a["to"] for a in players if a["family"] in OFFENSE}
    teams = len(rec["rosterIds"])
    off_for_idp = bool(recv_idp and recv_off and (recv_idp - recv_off or recv_off - recv_idp))
    idp_for_idp = bool(len(recv_idp) >= 2 and not recv_off)
    per_side = Counter(a["to"] for a in assets)
    one_for_one = (
        teams == 2 and not faab and len(per_side) == 2 and all(n == 1 for n in per_side.values())
    )
    multi_player = any(n >= 2 for n in Counter(a["to"] for a in players).values())
    structural_unpriceable = [a for a in assets if a["kind"] in ("unresolved", "faab")] + [
        a for a in picks if (a["pick"].get("round") or 0) > 6
    ]
    return {
        "teams": teams,
        "multiTeam": teams >= 3,
        "oneForOne": one_for_one,
        "package": teams == 2 and not one_for_one,
        "multiPlayerPackage": multi_player,
        "containsPicks": bool(picks),
        "containsFaab": bool(faab),
        "containsIdp": bool(idp_fams),
        "idpFamilies": idp_fams,
        "offenseForIdp": off_for_idp,
        "idpForIdp": idp_for_idp,
        "structurallyUnpriceable": bool(structural_unpriceable),
    }


def _trade_lane_state(rec: Mapping[str, Any], lane: str) -> str:
    """``full`` / ``partial`` / ``none`` over the trade's priceable assets."""
    priced = [a for a in rec["assets"] if "prices" in a]
    if not priced:
        return "none"
    ok = sum(1 for a in priced if a["prices"][lane]["fidelity"] != "missing")
    if ok == len(priced) and not any(a["kind"] == "faab" for a in rec["assets"]):
        return "full"
    return "partial" if ok else "none"


def aggregate(
    bundle: Mapping[str, Any],
    seasons: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    tx_summary: Mapping[str, Any],
    dup_across_seasons: int,
    grouping: Any,
    pick_check: Mapping[str, Any],
    drafts: Mapping[str, Any],
    today_fmt: Any,
    unresolved_ids: set[str],
    ledger: Path | None,
    reconcile_trades: Sequence[Mapping[str, Any]] | None,
    reconcile_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    season_names = [s["season"] for s in seasons]
    by_season: dict[str, list[Mapping[str, Any]]] = {s: [] for s in season_names}
    for r in records:
        by_season[r["season"]].append(r)

    def _count(pred: Callable[[Mapping[str, Any]], bool]) -> dict[str, Any]:
        per = {s: sum(1 for r in by_season[s] if pred(r)) for s in season_names}
        return {"total": sum(per.values()), "bySeason": per}

    cls = lambda key: _count(lambda r: bool(r["classes"][key]))  # noqa: E731

    # -- chain + format ------------------------------------------------------
    chain = []
    fmt_validation = {}
    for s in seasons:
        lg = s["league"]
        fmt = mtf.format_from_sleeper_league(lg)
        axes = mtf.compare_formats(fmt, today_fmt)
        auth = mtf.format_authority(axes)
        starters = Counter(
            p for p in (lg.get("roster_positions") or []) if p not in ("BN", "IR", "TAXI")
        )
        chain.append(
            {
                "season": s["season"],
                "leagueId": s["leagueId"],
                "status": lg.get("status"),
                "leagueType": (lg.get("settings") or {}).get("type"),
                "teams": s["teams"],
                "rosterSlots": len(lg.get("roster_positions") or []),
                "starterSlots": dict(sorted(starters.items())),
                "taxiSlots": (lg.get("settings") or {}).get("taxi_slots"),
                "draftRounds": s["draftRounds"],
                "scoringKeys": len(lg.get("scoring_settings") or {}),
                "scoringCardHash": fmt.card_hash,
                "formatFingerprint": fmt.to_dict()["fingerprint"],
                "waiverBudget": (lg.get("settings") or {}).get("waiver_budget"),
            }
        )
        diff_detail = {
            n: {k: v for k, v in axes[n].items() if k in ("source", "target", "detail")}
            for n in auth["differentAxes"]
        }
        fmt_validation[s["season"]] = {
            "matchedAxes": auth["matchedAxes"],
            "differentAxes": auth["differentAxes"],
            "unknownAxes": auth["unknownAxes"],
            "differences": diff_detail,
            "allAxesMatchToday": not auth["differentAxes"] and not auth["unknownAxes"],
            "timing": (
                "current_league_settings_at_fetch"
                if s is seasons[-1]
                else mtf.REASON_SEASON_FINAL_SETTINGS
            ),
        }

    # -- price coverage -------------------------------------------------------
    coverage: dict[str, Any] = {}
    for lane, _, _ in LANES:
        lane_cov: dict[str, Any] = {}
        for s in season_names:
            items = [a["prices"][lane] for r in by_season[s] for a in r["assets"] if "prices" in a]
            fid = Counter(i["fidelity"] for i in items)
            reasons = Counter(i["reason"] for i in items if i["reason"])
            ages = [i["ageDays"] for i in items if i["fidelity"] == asof.FIDELITY_NEAREST_PRIOR]
            tier_ev = sum(
                1
                for i in items
                if i.get("pickDetail") and (i.get("tierEvidenceKnownBefore") or 0) == 3
            )
            lane_cov[s] = {
                "assets": len(items),
                "exact": fid.get(asof.FIDELITY_EXACT, 0),
                "nearestPrior": fid.get(asof.FIDELITY_NEAREST_PRIOR, 0),
                "missing": fid.get("missing", 0),
                "missingReasons": dict(sorted(reasons.items())),
                "nearestPriorAgeDays": _quantiles(ages),
                "picksWithAllThreeTierObservationsKnownBefore": tier_ev,
                "tradesFullyPriced": sum(
                    1 for r in by_season[s] if _trade_lane_state(r, lane) == "full"
                ),
                "tradesPartiallyPriced": sum(
                    1 for r in by_season[s] if _trade_lane_state(r, lane) == "partial"
                ),
                "tradesUnpriced": sum(
                    1 for r in by_season[s] if _trade_lane_state(r, lane) == "none"
                ),
            }
        coverage[lane] = lane_cov

    # -- suitability for each proposed analysis --------------------------------
    post_floor = lambda r: r["instant"][:10] >= HISTORY_FLOOR  # noqa: E731

    def _assets_priced(r: Mapping[str, Any], lanes: Sequence[str]) -> bool:
        priced = [a for a in r["assets"] if "prices" in a]
        if not priced or any(a["kind"] == "faab" for a in r["assets"]):
            return False
        return all(a["prices"][ln]["fidelity"] != "missing" for a in priced for ln in lanes)

    one4one_players = lambda r: r["classes"]["oneForOne"] and all(  # noqa: E731
        a["kind"] == "player" for a in r["assets"]
    )
    suit = {}
    for name, pred in {
        "oneForOneSourceRelativeGap": lambda r: r["fit"]["fit"] == mte.FIT_CLEAN,
        "multiAssetPackageBenchmark": lambda r: r["fit"]["fit"] == mte.FIT_PACKAGE,
        "idpPositionPremium": lambda r: r["classes"]["offenseForIdp"]
        and not r["classes"]["multiTeam"],
        "tierPremium_idpUpperBound": lambda r: r["classes"]["containsIdp"]
        and not r["classes"]["multiTeam"],
    }.items():
        base = [r for r in records if pred(r)]
        suit[name] = {
            "structurallyEligible": len(base),
            "structurallyEligibleBySeason": {
                s: sum(1 for r in base if r["season"] == s) for s in season_names
            },
            "onOrAfterHistoryFloor": sum(1 for r in base if post_floor(r)),
            "fullyPricedIdptc": sum(1 for r in base if _assets_priced(r, ["idptc"])),
            "fullyPricedKtc": sum(1 for r in base if _assets_priced(r, ["ktc"])),
            "fullyPricedCanonical": sum(1 for r in base if _assets_priced(r, ["canonical"])),
            "fullyPricedCanonicalAndIdptc": sum(
                1 for r in base if _assets_priced(r, ["canonical", "idptc"])
            ),
        }
    fit_reasons = Counter(rr for r in records for rr in r["fit"]["reasons"])

    idp_1for1 = [r for r in records if one4one_players(r) and r["classes"]["containsIdp"]]
    effective = {
        "idpOneForOnePlayerSwaps": len(idp_1for1),
        "idpOneForOneOnOrAfterFloor": sum(1 for r in idp_1for1 if post_floor(r)),
        "idpOneForOneWithIdptcBothAssets": sum(
            1 for r in idp_1for1 if _assets_priced(r, ["idptc"])
        ),
        "idpOneForOneWithCanonicalAndIdptcBothAssets": sum(
            1 for r in idp_1for1 if _assets_priced(r, ["canonical", "idptc"])
        ),
        "allOneForOnePlayerSwapsWithIdptcBothAssets": sum(
            1 for r in records if one4one_players(r) and _assets_priced(r, ["idptc"])
        ),
        "allTradesFullyPricedIdptc": sum(1 for r in records if _assets_priced(r, ["idptc"])),
        "allTradesFullyPricedCanonical": sum(
            1 for r in records if _assets_priced(r, ["canonical"])
        ),
        "tradesOnOrAfterFloor": sum(1 for r in records if post_floor(r)),
    }

    # -- distinct entities -----------------------------------------------------
    managers = {m for r in records for m in r["managerIds"]}
    priced_idptc = [r for r in records if _assets_priced(r, ["idptc"])]
    per_mgr = Counter(m for r in priced_idptc for m in r["managerIds"])
    effective["managersInFullyIdptcPricedTrades"] = len(per_mgr)
    effective["maxFullyIdptcPricedTradesPerManager"] = max(per_mgr.values()) if per_mgr else 0
    effective["medianFullyIdptcPricedTradesPerManager"] = (
        statistics.median(per_mgr.values()) if per_mgr else 0
    )
    distinct_players = {a["playerId"] for r in records for a in r["assets"] if a.get("playerId")}
    distinct_picks = {
        (a["pick"]["season"], a["pick"]["round"], a["pick"]["origin"])
        for r in records
        for a in r["assets"]
        if a["kind"] == "pick"
    }
    pos_basis = Counter(
        a["positionBasis"] for r in records for a in r["assets"] if a.get("positionBasis")
    )
    leg_counts = Counter(f for r in records for f in r["legFindings"])
    per_team = {
        s: dict(sorted(Counter(lbl for r in by_season[s] for lbl in r["teamLabels"]).items()))
        for s in season_names
    }

    idp_family_counts = {
        fam: _count(lambda r, fam=fam: fam in r["classes"]["idpFamilies"]) for fam in IDP
    }

    # -- reconciliation --------------------------------------------------------
    recon = reconcile(records, reconcile_trades, reconcile_meta)

    findings = []
    if dup_across_seasons:
        findings.append(f"duplicate_transaction_ids_across_seasons:{dup_across_seasons}")
    if pick_check["inconsistentTransfers"]:
        findings.append(f"pick_transfer_sender_mismatch:{pick_check['inconsistentTransfers']}")
    for cp in pick_check["checkpoints"]:
        if cp.get("mismatches"):
            findings.append(f"pick_ownership_mismatch_season_{cp['season']}:{cp['mismatches']}")
    if unresolved_ids:
        findings.append(f"unresolved_player_ids:{len(unresolved_ids)}")
    if grouping.volume["groupsByState"].get(grp.CONFIRMED_UNIQUE, 0) != len(records):
        findings.append("grouping_found_non_unique_trades")
    for s, v in tx_summary.items():
        if v["weeksFailed"]:
            findings.append(f"weeks_failed_{s}:{v['weeksFailed']}")
    blocking_legs = {
        k: v
        for k, v in leg_counts.items()
        # Real host shapes, reported but not defects: a one-sided dump, an
        # add with no sender, a player released inside the trade.
        if k not in ("released_in_trade", "add_without_sender", "party_receives_nothing")
    }
    if blocking_legs:
        findings.append(f"leg_findings:{dict(sorted(blocking_legs.items()))}")

    checkpoints_public = []
    for cp in pick_check["checkpoints"]:
        pub = {k: v for k, v in cp.items() if not k.startswith("_")}
        if cp.get("_mismatchDetail") is not None:
            pub["mismatchesByPickSeasonRound"] = dict(
                sorted(
                    Counter(
                        f"{m['pick'][0]}-r{m['pick'][1]}" for m in cp["_mismatchDetail"]
                    ).items()
                )
            )
        checkpoints_public.append(pub)
    sender_mismatch = dict(
        sorted(
            Counter(
                f"{m['pick'][0]}-r{m['pick'][1]}" for m in pick_check["_inconsistentDetail"]
            ).items()
        )
    )
    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "inputs": {
            "collectedAt": bundle.get("collectedAt"),
            "sleeperFetch": {
                "calls": (bundle.get("fetch") or {}).get("calls"),
                "failures": len((bundle.get("fetch") or {}).get("failures") or []),
            },
            "playersDirectory": bundle.get("playersDirectoryState"),
            "temporalLedger": _ledger_summary(ledger),
            "historyFloor": HISTORY_FLOOR,
            "priceInstant": "trade status_updated (completion); created when absent",
        },
        "chain": {"coverage": bundle.get("chainCoverage"), "seasons": chain},
        "formatValidation": fmt_validation,
        "transactions": tx_summary,
        "validation": {
            "duplicateTransactionIdsAcrossSeasons": dup_across_seasons,
            "groupingStates": grouping.volume["groupsByState"],
            "legFindings": dict(sorted(leg_counts.items())),
            "playerIds": {
                "distinctInTrades": len(distinct_players),
                "unresolved": len(unresolved_ids),
            },
            "pickReplay": {
                "transfersReplayed": pick_check["transfersReplayed"],
                "transfersByTransactionType": pick_check["transfersByTransactionType"],
                "senderMismatches": pick_check["inconsistentTransfers"],
                "senderMismatchesByPickSeasonRound": sender_mismatch,
                "checkpoints": checkpoints_public,
            },
            "positionBasisForTradedPlayers": dict(sorted(pos_basis.items())),
            "findings": findings,
        },
        "deliverableA": {
            "seasonsRecovered": season_names,
            "historicalLeagueIds": {s["season"]: s["leagueId"] for s in seasons},
            "completedTradesBySeason": {s: len(by_season[s]) for s in season_names},
            "completedTradesTotal": len(records),
            "idpTradesByFamily": idp_family_counts,
            "idpTradesAny": cls("containsIdp"),
            "offenseForIdpTrades": cls("offenseForIdp"),
            "idpForIdpTrades": cls("idpForIdp"),
            "tradesWithPicks": cls("containsPicks"),
            "tradesWithFaab": cls("containsFaab"),
            "multiTeamTrades": cls("multiTeam"),
            "tradesWithStructurallyUnpriceableAssets": cls("structurallyUnpriceable"),
            "tradesWithAnyAssetUnpricedAtTradeTime": {
                lane: _count(lambda r, lane=lane: _trade_lane_state(r, lane) != "full")
                for lane, _, _ in LANES
            },
            "oneForOneSwaps": cls("oneForOne"),
            "oneForOnePlayerForPlayer": _count(one4one_players),
            "packages": cls("package"),
            "multiPlayerPackages": cls("multiPlayerPackage"),
            "historicalValueCoverage": coverage,
            "distinctTradingManagers": len(managers),
            "distinctTradingManagersBasis": "distinct roster owner user ids of trade parties, from each season league's rosters (final ownership of that season)",
            "distinctPlayers": len(distinct_players),
            "distinctLeaguePicks": len(distinct_picks),
            "tradesPerTeamLabel": per_team,
            "suitabilityByAnalysis": suit,
            "fitSuitabilityReasons": dict(sorted(fit_reasons.items())),
            "topology": dict(sorted(Counter(r["topology"]["topology"] for r in records).items())),
            "coverageAfterFormatValidation": {
                "tradesInSeasonsMatchingTodayOnEveryAxis": sum(
                    len(by_season[s])
                    for s in season_names
                    if fmt_validation[s]["allAxesMatchToday"]
                ),
                "tradesInSeasonsWithDifferentAxes": {
                    s: {
                        "trades": len(by_season[s]),
                        "differentAxes": fmt_validation[s]["differentAxes"],
                    }
                    for s in season_names
                    if not fmt_validation[s]["allAxesMatchToday"]
                },
                "idpTradesInMatchingSeasons": sum(
                    1
                    for s in season_names
                    if fmt_validation[s]["allAxesMatchToday"]
                    for r in by_season[s]
                    if r["classes"]["containsIdp"]
                ),
                "idpOneForOneInMatchingSeasonsWithIdptc": sum(
                    1
                    for r in idp_1for1
                    if fmt_validation[r["season"]]["allAxesMatchToday"]
                    and _assets_priced(r, ["idptc"])
                ),
            },
        },
        "effectiveSample": effective,
        "reconciliation": recon,
        "draftCensus": drafts,
        "definitions": DEFINITIONS,
    }


DEFINITIONS = {
    "completedTrade": "Sleeper transaction with type == 'trade' and status == 'complete', unique by transaction_id across every week and season league",
    "idpTrade": "at least one moving player whose as-of position family is DL, LB or DB",
    "offenseForIdp": "some team receives an IDP player and a different team receives an offense (QB/RB/WR/TE) player",
    "idpForIdp": "IDP players received by at least two teams and no offense player in the trade",
    "oneForOne": "two teams, each receives exactly one asset (player or pick), no FAAB",
    "package": "two-team trade that is not one-for-one",
    "multiPlayerPackage": "some team receives two or more players",
    "structurallyUnpriceable": "contains an unresolved player id, FAAB money, or a pick beyond round 6 (outside the market pick grammar)",
    "asOfPosition": "position at the latest chain draft (at or before the trade season) the player was taken in; otherwise the current Sleeper directory",
    "fidelity": "exact = an observation on the trade's UTC date provably before the trade instant; nearest-prior = latest earlier observation (age stated); missing = none, with one reason",
    "fullyPriced": "every non-FAAB asset priced in the lane and no FAAB component",
}


def _ledger_summary(ledger: Path | None) -> dict[str, Any]:
    cov = asof.source_lane_coverage(ledger)
    return {
        "path": ledger.name if ledger else None,
        "exists": cov.get("exists"),
        "sourceValueLane": cov.get("sources"),
        "canonicalBoardLane": (
            "not present: the exports/archive backfill writes source_value and scraper_blend "
            "rows only (src/history/backfill.py; audit W04-F009); canonical board history lives "
            "in the box-only board_history.sqlite, not read here (owner: no box run)"
        ),
    }


# ── Reconciliation with the 107-trade count ──────────────────────────────


def load_archive_trades(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import zipfile  # noqa: PLC0415

    with zipfile.ZipFile(path) as z:
        name = next(
            n for n in z.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        raw = json.loads(z.read(name))
    sleeper = raw.get("sleeper") or {}
    return list(sleeper.get("trades") or []), {
        "archive": path.name,
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "tradeWindowCutoff": _iso_ms(sleeper.get("tradeWindowCutoffMs")),
        "tradeWindowCutoffMs": sleeper.get("tradeWindowCutoffMs"),
    }


def reconcile(
    records: Sequence[Mapping[str, Any]],
    archive_trades: Sequence[Mapping[str, Any]] | None,
    meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if archive_trades is None:
        return {"state": "unavailable", "reason": "no reconciliation archive supplied"}
    cutoff = _int((meta or {}).get("tradeWindowCutoffMs")) or 0
    scrape = (meta or {}).get("scrapeTimestamp")
    scrape_ms = None
    if scrape:
        try:
            dt = datetime.fromisoformat(str(scrape))
            scrape_ms = int(
                (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp() * 1000
            )
        except ValueError:
            scrape_ms = None

    def _key(league: Any, ms: Any, rids: Iterable[Any]) -> tuple:
        return (str(league), _int(ms), tuple(sorted(_int(r) for r in rids)))

    census_keys = {}
    for r in records:
        created = r["createdAt"]
        ms = int(datetime.fromisoformat(created).timestamp() * 1000) if created else None
        census_keys[_key(r["leagueId"], ms, r["rosterIds"])] = r
    arch_keys = {
        _key(
            t.get("leagueId"), t.get("timestamp"), [s.get("rosterId") for s in t.get("sides") or []]
        ): t
        for t in archive_trades
    }
    in_window = {
        k: r
        for k, r in census_keys.items()
        if k[1] is not None and k[1] >= cutoff and (scrape_ms is None or k[1] <= scrape_ms)
    }
    matched = set(arch_keys) & set(census_keys)
    by_league = Counter(str(t.get("leagueId")) for t in archive_trades)
    return {
        "state": "compared",
        **{k: v for k, v in (meta or {}).items() if k != "tradeWindowCutoffMs"},
        "archiveTrades": len(archive_trades),
        "archiveTradesBySeasonLeague": dict(sorted(by_league.items())),
        "archiveTradesMatchedToCensus": len(matched),
        "archiveTradesNotInCensus": len(set(arch_keys) - set(census_keys)),
        "censusTradesInsideArchiveWindow": len(in_window),
        "censusTradesInsideWindowMissingFromArchive": len(set(in_window) - set(arch_keys)),
        "censusTradesOutsideArchiveWindow": len(census_keys) - len(in_window),
        "matchKey": "(season league id, transaction created ms, sorted roster ids)",
        "explanation": (
            "The 107 is the scraper's sleeper.trades block, a rolling window "
            "(SLEEPER_TRADE_HISTORY_DAYS, default 365 days before the scrape) over the first four chain "
            "leagues; the census has no window and walks the whole chain."
        ),
    }


# ── Anonymization guard ──────────────────────────────────────────────────

#: 9+ digits not preceded by a digit or a decimal point (a scoring weight such as
#: ``0.0333333333`` is a fraction, not an id).
_LONG_DIGITS = re.compile(r"(?<![\d.])\d{9,}(?!\d)")


def identifier_leaks(text: str, *, allowed_ids: Iterable[str], names: Iterable[str]) -> list[str]:
    """Every Sleeper-id-shaped digit run (9+) not in ``allowed_ids`` and every
    league member name found in ``text``."""
    allowed = {str(a) for a in allowed_ids}
    leaks = sorted({m for m in _LONG_DIGITS.findall(text) if m not in allowed})
    low = text.lower()
    for n in sorted({str(x).strip() for x in names if x and len(str(x).strip()) >= 3}):
        if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", low):
            leaks.append(f"name:{n}")
    return leaks


def member_names(bundle: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for s in bundle["seasons"].values():
        for u in s.get("users") or []:
            for k in ("display_name", "username"):
                if u.get(k):
                    out.add(str(u[k]))
            team = (u.get("metadata") or {}).get("team_name")
            if team:
                out.add(str(team))
    return out


# ── Markdown ─────────────────────────────────────────────────────────────


def _fmt_by_season(c: Mapping[str, Any]) -> str:
    per = " / ".join(f"{s}: {n}" for s, n in c["bySeason"].items())
    return f"**{c['total']}** ({per})"


def render_markdown(agg: Mapping[str, Any]) -> str:
    A = agg["deliverableA"]
    V = agg["validation"]
    E = agg["effectiveSample"]
    R = agg["reconciliation"]
    seasons = A["seasonsRecovered"]
    L: list[str] = []
    w = L.append
    w("# Own-league historical trade and draft census — dynasty_main")
    w("")
    w(
        "Phase 1, Lane A of the owner directive *IDP Market Pricing, Acquisition Intelligence, "
        "Historical Trade Research, and Draft Strategy* (2026-10-26). Research only: nothing "
        "here changes a value, a vote, a verdict or a route. Generated by "
        "`scripts/own_league_history_census.py`; every number below is in "
        "`docs/market_trades/evidence/own_league_census_2026-10-27.json`."
    )
    w("")
    w("No hypothesis (H1-H7) is tested here. Phase 2 tests them after a preregistration.")
    w("")
    w("## 1. Method")
    w("")
    w(
        "- **Source.** Sleeper's public read-only v1 API, walked locally across the whole "
        "`previous_league_id` chain (`sleeper_client.walk_league_chain_status`). Calls are paced "
        "0.2 s apart, with a bounded retry on HTTP 429. "
        f"Fetch outcomes: `{agg['inputs']['sleeperFetch']['calls']}`; failures: "
        f"{agg['inputs']['sleeperFetch']['failures']}."
    )
    w(
        "- **Weeks.** Every season league's `/transactions/{week}` for weeks 0-18, plus a probe "
        "of weeks 19-25."
    )
    w(
        "- **Trades.** Deduped by `transaction_id` across weeks and seasons. Only `type == trade` "
        "and `status == complete` are kept."
    )
    w(
        "- **Prices.** `src.history.asof.batch_known_before` on a scratch temporal ledger built "
        "from the tracked `exports/archive/` by `scripts/build_temporal_ledger.py --skip-migrations "
        "--ledger <scratch>`. The lookup is instant-strict at the trade's completion time, so a "
        "later observation is never selected. Today's value is never used. Missing is never 0."
    )
    w(
        "- **Reuse.** Grouping, topology and fit come from `market_trade_groups` / "
        "`market_trade_eval`; formats from `market_trade_format`; picks from `src.identity.picks`; "
        "players from `src.identity.resolution` via `market_trade_normalize.IdentityContext`."
    )
    w(
        "- **Privacy.** Transaction-level evidence with roster, user and transaction ids is "
        "written only to the gitignored `data/research/own_league_census/`. This file and its JSON "
        "carry counts and `T01..Tnn` labels only. The script refuses to write them if it finds any "
        "9+ digit run other than the three league ids, or any league member's name."
    )
    w("")
    w("## 2. Seasons recovered")
    w("")
    cov = agg["chain"]["coverage"] or {}
    w(
        f"Chain walk: **{cov.get('state')}** ({cov.get('seasonsWalked')} seasons, "
        f"stop reason `{cov.get('reason')}`). Sleeper's terminator was reached; there is no older "
        "dynasty season."
    )
    w("")
    w(
        "| season | league id | status | teams | roster slots | starters (IDP) | draft rounds | FAAB budget | completed trades |"
    )
    w("|---|---|---|---:|---:|---|---:|---:|---:|")
    for c in agg["chain"]["seasons"]:
        st = c["starterSlots"]
        idp = ", ".join(f"{k} {st[k]}" for k in ("DL", "LB", "DB", "IDP_FLEX") if k in st)
        w(
            f"| {c['season']} | {c['leagueId']} | {c['status']} | {c['teams']} | {c['rosterSlots']} | "
            f"{sum(st.values())} ({idp}) | {c['draftRounds']} | {c['waiverBudget']} | "
            f"{A['completedTradesBySeason'][c['season']]} |"
        )
    w("")
    w("## 3. Format validation against today's league")
    w("")
    w(
        "Each season's league object compared with the 2026 league by "
        "`market_trade_format.compare_formats`. A completed season's object is its final settings "
        "(`season_final_settings`), so a mid-season change cannot be ruled out."
    )
    w("")
    w("| season | axes that differ from today | unknown axes |")
    w("|---|---|---|")
    for s in seasons:
        f = agg["formatValidation"][s]
        w(
            f"| {s} | {', '.join(f['differentAxes']) or 'none'} | {', '.join(f['unknownAxes']) or 'none'} |"
        )
    w("")
    ca = A["coverageAfterFormatValidation"]
    w(
        f"Coverage after format validation: **{ca['tradesInSeasonsMatchingTodayOnEveryAxis']}** "
        "trades sit in a season whose format matches today's on every axis. "
        f"IDP trades among them: {ca['idpTradesInMatchingSeasons']}. IDP one-for-one swaps among "
        f"them with IDPTC prices on both assets: {ca['idpOneForOneInMatchingSeasonsWithIdptc']}."
    )
    w("")
    w("## 4. Transactions and validation")
    w("")
    w(
        "| season | week-0 transactions | weeks > 18 with any transaction | completed trades by week | trades created before Sept 1 | duplicate ids across weeks |"
    )
    w("|---|---:|---|---|---:|---:|")
    for s in seasons:
        t = agg["transactions"][s]
        weeks = ", ".join(f"w{k}:{v}" for k, v in t["completedTradesByWeek"].items())
        w(
            f"| {s} | {t['week0Transactions']} | {t['weeksBeyond18WithAnyTransaction'] or 'none'} | "
            f"{weeks} | {t['completedTradesCreatedBeforeSeptember']} | {t['duplicatesAcrossWeeks']} |"
        )
    w("")
    w(
        "**Where offseason trades sit.** Week 0 is empty in every season. Pre-draft and offseason "
        "trades come back under week 1 (`leg 1`), from January of the season year. No week past 18 "
        "returned anything."
    )
    w("")
    pr = V["pickReplay"]
    w(
        f"- **Duplicate transaction ids across seasons:** {V['duplicateTransactionIdsAcrossSeasons']}. "
        f"Grouping states: `{V['groupingStates']}`."
    )
    w(f"- **Legs:** `{V['legFindings'] or 'every leg accounted for'}`.")
    w(
        f"- **Player ids:** {V['playerIds']['distinctInTrades']} distinct in trades, "
        f"{V['playerIds']['unresolved']} unresolved."
    )
    w(
        f"- **Pick transfers:** {pr['transfersReplayed']} replayed oldest-first "
        f"(`{pr['transfersByTransactionType']}`), {pr['senderMismatches']} whose stated sender "
        "differs from the tracked owner."
    )
    for cp in pr["checkpoints"]:
        if cp["state"] == "compared":
            w(
                f"  - {cp['season']} league `/traded_picks` vs replay: {cp['picksCompared']} picks "
                f"(seasons {cp['pickSeasonsCompared']}, rounds 1-{cp['rounds']}), "
                f"**{cp['mismatches']} mismatches**."
            )
        else:
            w(f"  - {cp['season']}: {cp['state']} ({cp.get('reason')}).")
    w(
        "  - The sender mismatches and checkpoint mismatches by pick class: "
        f"`{pr['senderMismatchesByPickSeasonRound']}`; "
        + "; ".join(
            f"{cp['season']}: `{cp.get('mismatchesByPickSeasonRound')}`"
            for cp in pr["checkpoints"]
            if cp.get("mismatches")
        )
        + ". No transaction in the chain explains them: Sleeper exposes no commissioner pick move "
        "here (every replayed transfer is a `trade`). They are consistent with host-side edits "
        "that leave no transaction, such as a draft-board or round-count edit. The census reports "
        "them and corrects neither side."
    )
    w(
        "- **Completeness.** Sleeper's `/transactions/{week}` has no cursor; each week answers in "
        "full. Two independent checks bound what could be missing: the pick replay above, and the "
        "107-of-107 archive reconciliation in section 7."
    )
    w(f"- **As-of position basis (player legs):** `{V['positionBasisForTradedPlayers']}`.")
    w(f"- **Findings:** `{V['findings'] or 'none'}`.")
    w("")
    w("## 5. Deliverable A")
    w("")
    w("| item | value |")
    w("|---|---|")
    w(f"| Seasons recovered | {', '.join(seasons)} |")
    w(
        f"| Historical league ids | {', '.join(f'{s}: {i}' for s, i in A['historicalLeagueIds'].items())} |"
    )
    w(
        f"| Completed trades | **{A['completedTradesTotal']}** ({' / '.join(f'{s}: {n}' for s, n in A['completedTradesBySeason'].items())}) |"
    )
    for fam in IDP:
        w(f"| IDP trades with a {fam} | {_fmt_by_season(A['idpTradesByFamily'][fam])} |")
    w(f"| IDP trades (any family) | {_fmt_by_season(A['idpTradesAny'])} |")
    w(f"| Offense-for-IDP trades | {_fmt_by_season(A['offenseForIdpTrades'])} |")
    w(f"| IDP-for-IDP trades | {_fmt_by_season(A['idpForIdpTrades'])} |")
    w(f"| Trades with picks | {_fmt_by_season(A['tradesWithPicks'])} |")
    w(f"| Trades with FAAB | {_fmt_by_season(A['tradesWithFaab'])} |")
    w(f"| Multi-team trades | {_fmt_by_season(A['multiTeamTrades'])} |")
    w(
        f"| Trades with a structurally unpriceable asset | {_fmt_by_season(A['tradesWithStructurallyUnpriceableAssets'])} |"
    )
    for lane, c in A["tradesWithAnyAssetUnpricedAtTradeTime"].items():
        w(f"| Trades not fully priced at trade time, {lane} | {_fmt_by_season(c)} |")
    w(f"| One-for-one swaps (any asset) | {_fmt_by_season(A['oneForOneSwaps'])} |")
    w(f"| One-for-one player-for-player | {_fmt_by_season(A['oneForOnePlayerForPlayer'])} |")
    w(f"| Packages (two-team, not one-for-one) | {_fmt_by_season(A['packages'])} |")
    w(f"| Multiple-player packages | {_fmt_by_season(A['multiPlayerPackages'])} |")
    w(f"| Distinct trading managers | {A['distinctTradingManagers']} |")
    w(
        f"| Distinct players / league picks traded | {A['distinctPlayers']} / {A['distinctLeaguePicks']} |"
    )
    w(f"| Topology (`classify_topology`) | `{A['topology']}` |")
    w(f"| Fit exclusions (`fit_suitability` reasons) | `{A['fitSuitabilityReasons']}` |")
    w("")
    w("Trades per team label (`T01..Tnn` in roster-id order, per season):")
    w("")
    for s, m in A["tradesPerTeamLabel"].items():
        w(f"- {s}: " + ", ".join(f"{k} {v}" for k, v in m.items()))
    w("")
    w("### 5.1 Historical-value coverage (per asset, at the trade instant)")
    w("")
    for lane, per in A["historicalValueCoverage"].items():
        w(f"**{lane}**")
        w("")
        w(
            "| season | assets | exact | nearest-prior (median age, days) | missing | missing reasons | trades fully / partly / not priced |"
        )
        w("|---|---:|---:|---:|---:|---|---|")
        for s, c in per.items():
            age = (c["nearestPriorAgeDays"] or {}).get("median")
            w(
                f"| {s} | {c['assets']} | {c['exact']} | {c['nearestPrior']} ({age if age is not None else '-'}) | "
                f"{c['missing']} | `{c['missingReasons']}` | {c['tradesFullyPriced']} / "
                f"{c['tradesPartiallyPriced']} / {c['tradesUnpriced']} |"
            )
        w("")
    w(f"Canonical board lane: {agg['inputs']['temporalLedger']['canonicalBoardLane']}.")
    w("")
    tier = {
        s: c["picksWithAllThreeTierObservationsKnownBefore"]
        for s, c in A["historicalValueCoverage"]["idptc"].items()
    }
    w(
        f"Traded picks whose early / mid / late IDPTC observations were all known before the trade: `{tier}`."
    )
    w("")
    w(
        "Picks are never priced here. Sleeper records a traded pick as season + round + origin "
        "team, which is the GENERIC market grade; history records only slot and tier grades. "
        "The JSON counts the picks whose three tier observations (early / mid / late) were all "
        "known before the trade (`picksWithAllThreeTierObservationsKnownBefore`). That is evidence "
        "a Phase-2 rule *could* use. It is not a price."
    )
    w("")
    w("### 5.2 Trades suitable for each proposed analysis")
    w("")
    w(
        "| analysis | structurally eligible | on/after 2026-07-14 | fully priced IDPTC | fully priced KTC | fully priced canonical | canonical + IDPTC |"
    )
    w("|---|---:|---:|---:|---:|---:|---:|")
    for name, c in A["suitabilityByAnalysis"].items():
        w(
            f"| {name} | {c['structurallyEligible']} | {c['onOrAfterHistoryFloor']} | {c['fullyPricedIdptc']} | "
            f"{c['fullyPricedKtc']} | {c['fullyPricedCanonical']} | {c['fullyPricedCanonicalAndIdptc']} |"
        )
    w("")
    w("- *oneForOneSourceRelativeGap* = `fit_suitability` `clean_1_for_1`.")
    w("- *multiAssetPackageBenchmark* = `package_va_required`.")
    w("- *idpPositionPremium* = two-team offense-for-IDP.")
    w(
        "- *tierPremium_idpUpperBound* = every two-team trade with an IDP. The tier definition "
        "belongs to the preregistration, so this is an upper bound, not a tier sample."
    )
    w("")
    w("## 6. Effective sample for price tests")
    w("")
    w("| quantity | count |")
    w("|---|---:|")
    for k, v in E.items():
        w(f"| {k} | {v} |")
    w("")
    w("## 7. Reconciliation with the 107-trade count")
    w("")
    if R.get("state") == "compared":
        w(
            f"`docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md` §5.4 reads "
            f"`sleeper.trades` from `{R['archive']}` (scraped {R['scrapeTimestamp']})."
        )
        w("")
        w(
            f"- That archive holds **{R['archiveTrades']}** trades (`{R['archiveTradesBySeasonLeague']}`)."
        )
        w(
            f"- **{R['archiveTradesMatchedToCensus']}** match a census trade on {R['matchKey']}; "
            f"{R['archiveTradesNotInCensus']} do not."
        )
        w(
            f"- The archive's trade window starts {R['tradeWindowCutoff']}. "
            f"**{R['censusTradesInsideArchiveWindow']}** census trades fall inside it; "
            f"{R['censusTradesInsideWindowMissingFromArchive']} of those are missing from the archive."
        )
        w(f"- **{R['censusTradesOutsideArchiveWindow']}** census trades fall outside it.")
        w("")
        w(R["explanation"])
    else:
        w(f"Unavailable: {R.get('reason')}.")
    w("")
    w("## 8. Draft census")
    w("")
    D = agg["draftCensus"]
    w(
        "| season | draft | type | kind (basis) | status | picks | IDP share | first IDP pick | IDP median pick | DL / LB / DB | auction $ IDP / offense |"
    )
    w("|---|---|---|---|---|---:|---:|---:|---:|---|---|")
    for d in D["drafts"]:
        fam = d["picksByFamily"]
        io = d["idpSelectionOrder"]
        auc = d["auction"]
        if d["type"] != "auction":
            money = "n/a (no auction)"
        elif auc.get("idpTotal") is None:
            money = "unavailable: no picks recorded"
        else:
            money = f"{auc['idpTotal']} / {auc['offenseTotal']}"
        w(
            f"| {d['season']} | {d['draftRef']} | {d['type']} | {d['kind']} ({d['kindBasis']}) | {d['status']} | "
            f"{d['picks']} | {d['idpShare'] if d['idpShare'] is not None else '-'} | "
            f"{io['firstIdpPickNo'] if io['firstIdpPickNo'] is not None else '-'} | "
            f"{(io['allIdp'] or {}).get('median', '-')} | "
            f"{fam.get('DL', 0)} / {fam.get('LB', 0)} / {fam.get('DB', 0)} | {money} |"
        )
    w("")
    w("Offense vs IDP by round (picks):")
    w("")
    for d in D["drafts"]:
        if not d["picks"]:
            continue
        parts = ", ".join(
            f"R{r}: {v['offense']}/{v['idp']}" + (f"/+{v['other']}" if v["other"] else "")
            for r, v in d["offenseVsIdpByRound"].items()
        )
        w(f"- {d['draftRef']} ({d['kind']}, offense/IDP[/other]): {parts}")
    w("")
    w("Rookie-draft changes between seasons:")
    w("")
    for c in D["rookieDraftChanges"]:
        w(
            f"- {c['season']} ({c['type']}, {c['picks']} picks): IDP share {c['idpShare']}, "
            f"first IDP at pick {c['firstIdpPickNo']}, IDP median pick {c['idpMedianPickNo']}"
        )
    w("")
    w(
        "`amount` is the auction price; on a snake or linear draft it is `None`, never 0. "
        "In an auction, `pick_no` is the order lots were won, not a draft slot."
    )
    w("")
    w("## 9. Blockers for H1-H7 (Phase 2 must preregister around these)")
    w("")
    for h, text in hypothesis_blockers(agg).items():
        w(f"- **{h}.** {text}")
    w("")
    w("## 10. Limitations")
    w("")
    for item in LIMITATIONS:
        w(f"- {item}")
    w("")
    return "\n".join(L) + "\n"


LIMITATIONS = [
    "Every trade before 2026-07-14 has no point-in-time price in any lane (`before_history_boundary`). "
    "The external-archive survey (step 3b) is a separate deliverable; nothing from it is ingested.",
    "The canonical board lane is absent locally. Archives carry no canonical fields, and the box-only "
    "recorder store was not read (owner: no box run). So no trade has a canonical at-the-time price here.",
    "KTC (`ktcSfTep`) prices no IDP player; IDP price tests can only use IDPTC in this ledger.",
    "Picks stay unpriced: Sleeper's traded pick is generic-grade, and history holds only slot/tier rows.",
    "As-of position comes from chain draft metadata where the player was drafted in the chain; "
    "otherwise it is the CURRENT Sleeper directory, which may differ from the trade-time position.",
    "Format comparison uses each season league's settings as fetched now: final settings for "
    "completed seasons, current settings for 2026. A mid-season change is not ruled out.",
    "Manager counts use each season league's final roster ownership; an in-season orphan change "
    "is not visible.",
    "The ledger keeps one archive bundle per UTC date, so same-day intraday revisions are invisible.",
]


def hypothesis_blockers(agg: Mapping[str, Any]) -> dict[str, str]:
    E = agg["effectiveSample"]
    A = agg["deliverableA"]
    suit = A["suitabilityByAnalysis"]
    return {
        "H1 (IDPTC approximates league prices)": (
            f"{E['idpOneForOnePlayerSwaps']} IDP one-for-one player swaps exist in total; "
            f"{E['idpOneForOneWithIdptcBothAssets']} have IDPTC prices on both assets. Across all "
            f"positions, {E['allOneForOnePlayerSwapsWithIdptcBothAssets']} one-for-one player swaps "
            f"have IDPTC prices on both sides, and {E['allTradesFullyPricedIdptc']} trades are fully "
            "IDPTC-priced. Every one of them is on or after 2026-07-14, a single ~3-month window."
        ),
        "H2 (canonical values track behaviour better)": (
            f"0 trades carry a canonical at-the-time price locally ({E['allTradesFullyPricedCanonical']}). "
            "This needs the box-only canonical board history, or an approved reconstruction."
        ),
        "H3 (position premiums)": (
            f"{suit['idpPositionPremium']['structurallyEligible']} two-team offense-for-IDP trades exist; "
            f"{suit['idpPositionPremium']['fullyPricedIdptc']} are fully IDPTC-priced."
        ),
        "H4 (tier premiums, elite IDP)": (
            f"Upper bound {suit['tierPremium_idpUpperBound']['fullyPricedIdptc']} fully IDPTC-priced "
            "two-team IDP trades before any tier split. The tier definition is not set yet."
        ),
        "H5 (manager heterogeneity)": (
            f"{A['distinctTradingManagers']} distinct trading managers over all trades; "
            f"{E['managersInFullyIdptcPricedTrades']} appear in a fully IDPTC-priced trade, with at most "
            f"{E['maxFullyIdptcPricedTradesPerManager']} such trades each (median "
            f"{E['medianFullyIdptcPricedTradesPerManager']})."
        ),
        "H6 (packages, picks, staleness, selection)": (
            f"{suit['multiAssetPackageBenchmark']['structurallyEligible']} package trades are eligible; "
            f"{suit['multiAssetPackageBenchmark']['fullyPricedIdptc']} are fully IDPTC-priced. Picks are "
            "unpriced (generic grade), so pick-bearing trades cannot be benchmarked yet."
        ),
        "H7 (insufficient sample)": (
            "This census does not decide H7. On these counts it remains a live outcome, to be judged "
            "against the preregistered power analysis."
        ),
    }


# ── CLI ──────────────────────────────────────────────────────────────────


def _code_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--league-id", default=DEFAULT_LEAGUE_ID)
    ap.add_argument("--league-key", default=DEFAULT_LEAGUE_KEY)
    ap.add_argument(
        "--bundle", type=Path, default=None, help="replay a saved raw bundle (no network)"
    )
    ap.add_argument("--ledger", type=Path, default=None, help="temporal ledger (a scratch build)")
    ap.add_argument("--private-dir", type=Path, default=DEFAULT_PRIVATE_DIR)
    ap.add_argument("--doc-md", type=Path, default=DEFAULT_DOC_MD)
    ap.add_argument("--doc-json", type=Path, default=DEFAULT_DOC_JSON)
    ap.add_argument("--reconcile-archive", type=Path, default=DEFAULT_RECONCILE_ARCHIVE)
    ap.add_argument("--pace", type=float, default=0.2, help="seconds between Sleeper calls")
    ap.add_argument("--no-docs", action="store_true", help="write the private evidence only")
    args = ap.parse_args(argv)

    if args.ledger is not None and not args.ledger.exists():
        print(f"ledger not found: {args.ledger}", file=sys.stderr)
        return EXIT_BAD_INPUT
    args.private_dir.mkdir(parents=True, exist_ok=True)

    if args.bundle:
        try:
            bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"unreadable bundle: {exc}", file=sys.stderr)
            return EXIT_BAD_INPUT
    else:
        fetch = Fetcher(pace=args.pace)
        bundle = collect(args.league_id, fetch)
        attach_player_subset(bundle, sc.fetch_nfl_players())
        (args.private_dir / "raw_bundle.json").write_text(
            json.dumps(bundle, sort_keys=True), encoding="utf-8", newline="\n"
        )
    cov = bundle.get("chainCoverage") or {}
    failures = (bundle.get("fetch") or {}).get("failures") or []
    if cov.get("state") != sc.CHAIN_COMPLETE or failures:
        print(f"collection incomplete: chain={cov} failures={len(failures)}", file=sys.stderr)
        return EXIT_INCOMPLETE

    recon_trades, recon_meta = None, None
    if args.reconcile_archive and args.reconcile_archive.exists():
        recon_trades, recon_meta = load_archive_trades(args.reconcile_archive)

    agg, private = build_census(
        bundle,
        ledger=args.ledger,
        league_key=args.league_key,
        reconcile_trades=recon_trades,
        reconcile_meta=recon_meta,
    )
    agg["inputs"]["codeSha"] = _code_sha()
    (args.private_dir / "census_private.json").write_text(
        json.dumps(private, indent=1, sort_keys=True, default=str), encoding="utf-8", newline="\n"
    )
    if args.no_docs:
        return EXIT_FINDINGS if agg["validation"]["findings"] else EXIT_OK

    body_json = json.dumps(agg, indent=1, sort_keys=True, default=str) + "\n"
    body_md = render_markdown(agg)
    allowed = list(agg["deliverableA"]["historicalLeagueIds"].values())
    names = member_names(bundle)
    leaks = identifier_leaks(body_json + body_md, allowed_ids=allowed, names=names)
    if leaks:
        print(f"anonymization scan refused the write: {len(leaks)} leak(s)", file=sys.stderr)
        return EXIT_BAD_INPUT
    args.doc_json.parent.mkdir(parents=True, exist_ok=True)
    args.doc_md.parent.mkdir(parents=True, exist_ok=True)
    args.doc_json.write_text(body_json, encoding="utf-8", newline="\n")
    args.doc_md.write_text(body_md, encoding="utf-8", newline="\n")
    print(
        f"census: {agg['deliverableA']['completedTradesTotal']} trades, "
        f"findings={agg['validation']['findings']}"
    )
    return EXIT_FINDINGS if agg["validation"]["findings"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
