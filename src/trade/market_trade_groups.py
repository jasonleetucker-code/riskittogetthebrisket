"""Canonical UNDERLYING trades from raw observations — spec §19.4-19.8.

The raw archive may hold the same real-world trade several times: KTC and a
Sleeper crawl both saw it, two Sharp managers led us into the same league, a
crawl re-ran.  This module maps observations into underlying-trade groups and
says, per group, how sure it is.  Volume is counted per GROUP, never per
observation, and every group carries one stable ``underlyingTradeId`` so a
trade used for broad-market evidence and for Sharp-behaviour analysis is
recognisably ONE event in both places.

THE HIERARCHY, EXACTLY AS §19.5 WRITES IT
─────────────────────────────────────────
1. ``CONFIRMED SAME HOST TRANSACTION`` — same platform + league id + native
   transaction id.  Collapse.
2. ``CONFIRMED CROSS-SOURCE MATCH`` — an observation carries an explicit
   cross-reference (``crossRefs``) to the other's host transaction.  Collapse,
   keep both provenance records.  (KTC exposes no host transaction id, so a
   KTC row reaches this level only if a future feed supplies one.)
3. ``PROBABLE DUPLICATE`` — same host league, same canonical asset multiset
   per side (orientation-free), every asset resolved, dates within the
   tolerance, same team count — AND the match is unique on both sides.  One
   candidate group: counted once, never presented as proven.
4. ``POSSIBLE OVERLAP`` — similar but not provable (a league id missing on one
   side, an unresolved asset, a non-unique candidate).  NOT merged and NOT
   deleted: both groups survive, linked, and volume is reported as bounds.
5. ``DISTINCT`` — different host leagues, different host transactions, or
   dates apart.

**Never date + package alone.**  Two leagues trading the identical package on
the same day stay two trades: different host league ids are DISTINCT
evidence, and a package match with no league identity is at most POSSIBLE.

TWO RECORDING GAPS THAT MUST NOT MANUFACTURE A "DISTINCT"
────────────────────────────────────────────────────────
* **FAAB inside a trade.**  KTC records FAAB money as an asset; the Sleeper
  lanes cannot see it (caveat ``sleeper_trade_faab_component_not_recorded``).
  When either observation carries that caveat, packages are compared with
  FAAB stripped from BOTH sides — otherwise the same trade in the same league
  would read as two different packages and be counted twice.
* **Partial Sleeper records** (``partial_record_*`` / ``released_in_trade``
  caveats).  The record is known to be incomplete, so a package mismatch (or
  a team-count mismatch) against a same-league row that shares an asset is at
  most POSSIBLE, never DISTINCT.

BLOCKING (why this is not quadratic)
────────────────────────────────────
Candidate pairs are generated only where :func:`classify_pair` could answer
something other than DISTINCT, and the blocks are derived from its rules, so
blocking drops no pair it would have kept:

* same host transaction / explicit cross-reference — keyed by the host tx;
* same ``(host, leagueId)`` — dates within the tolerance, and never two rows
  that both carry a host tx id (same league + two tx ids is DISTINCT);
* a row with NO host league identity can only be POSSIBLE on a package match,
  so it is compared only within its FAAB-stripped package signature, dates
  within the tolerance.

Never by a single shared asset: a generic pick key (``mpick:2026:r1``) sits in
most trades, and blocking on it was O(n^2) — ~200M candidate tuples at 20k
rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

CONFIRMED_UNIQUE = "CONFIRMED_UNIQUE"
CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"
PROBABLE_DUPLICATE = "PROBABLE_DUPLICATE"
POSSIBLE_OVERLAP = "POSSIBLE_OVERLAP"
UNRESOLVED = "UNRESOLVED"

REL_SAME_HOST_TX = "confirmed_same_host_transaction"
REL_CROSS_SOURCE = "confirmed_cross_source_match"
REL_PROBABLE = "probable_duplicate"
REL_POSSIBLE = "possible_overlap"
REL_DISTINCT = "distinct"

#: KTC dates are DAY granularity in an unstated timezone, so a trade made late
#: on day D (UTC) can carry D or D+1.  One day either side, no more.
DEFAULT_DAY_TOLERANCE = 1

#: Preference when choosing whose format / sides represent a group: host
#: capture beats registry beats vendor summary.
_FORMAT_PREFERENCE = (
    "host_capture_via_discovery",
    "registry_and_scoring_card",
    "discovery_row_partial",
    "ktc_vendor_settings",
)


def underlying_trade_id_for_host_tx(host: str, league_id: str, tx_id: str) -> str:
    """The stable id of a host transaction.  Any analysis holding a Sleeper
    ``(league_id, transaction_id)`` can compute it, which is what lets two
    analyses of one event recognise each other (spec §19.7)."""
    return f"utrade:{host}:{league_id}:{tx_id}"


#: Sleeper lanes cannot see FAAB money that changes hands inside a trade.
FAAB_NOT_RECORDED_CAVEAT = "sleeper_trade_faab_component_not_recorded"
#: Caveats that say a Sleeper record is incomplete (``_sides_from_movements``).
PARTIAL_RECORD_CAVEAT_PREFIXES = ("partial_record_", "released_in_trade")


def _caveats(obs: Mapping[str, Any]) -> list[str]:
    return [str(c) for c in (obs.get("caveats") or [])]


def faab_unrecorded(obs: Mapping[str, Any]) -> bool:
    return FAAB_NOT_RECORDED_CAVEAT in _caveats(obs)


def partial_record(obs: Mapping[str, Any]) -> bool:
    return any(c.startswith(PARTIAL_RECORD_CAVEAT_PREFIXES) for c in _caveats(obs))


def _is_faab(asset: Mapping[str, Any]) -> bool:
    return asset.get("kind") == "faab" or str(asset.get("matchKey") or "").startswith("faab:")


def side_signature(
    side: Sequence[Mapping[str, Any]], *, strip_faab: bool = False
) -> tuple[str, ...]:
    return tuple(sorted(str(a["matchKey"]) for a in side if not (strip_faab and _is_faab(a))))


def package_signature(
    obs: Mapping[str, Any], *, strip_faab: bool = False
) -> tuple[tuple[str, ...], ...]:
    """Orientation-free: the multiset of side multisets.  A-for-B and B-for-A
    produce the same signature; empty sides (a team that only gave) count.
    ``strip_faab`` drops FAAB money from every side (used when either side of
    a comparison could not record it)."""
    return tuple(sorted(side_signature(s, strip_faab=strip_faab) for s in obs["sides"]))


def fully_resolved(obs: Mapping[str, Any]) -> bool:
    return all(
        a.get("canonicalId") is not None or a.get("kind") == "faab"
        for side in obs["sides"]
        for a in side
    )


def resolved_keys(obs: Mapping[str, Any]) -> set[str]:
    return {
        str(a["matchKey"])
        for side in obs["sides"]
        for a in side
        if a.get("canonicalId") is not None
    }


def _day(obs: Mapping[str, Any]) -> date | None:
    d = obs.get("occurredDate")
    try:
        return date.fromisoformat(str(d)) if d else None
    except ValueError:
        return None


def _host_key(obs: Mapping[str, Any]) -> tuple[str, str] | None:
    if obs.get("host") and obs.get("host") != "unknown" and obs.get("hostLeagueId"):
        return str(obs["host"]), str(obs["hostLeagueId"])
    return None


def _host_tx(obs: Mapping[str, Any]) -> tuple[str, str, str] | None:
    hk = _host_key(obs)
    if hk and obs.get("hostTxId"):
        return hk[0], hk[1], str(obs["hostTxId"])
    return None


def classify_pair(
    a: Mapping[str, Any], b: Mapping[str, Any], *, day_tolerance: int = DEFAULT_DAY_TOLERANCE
) -> tuple[str, str]:
    """``(relation, evidence)`` for two observations."""
    ta, tb = _host_tx(a), _host_tx(b)
    if ta and tb:
        if ta == tb:
            return REL_SAME_HOST_TX, "same platform + league + host transaction id"
        if ta[:2] == tb[:2]:
            return REL_DISTINCT, "same league, different host transaction ids"
    for x, y in ((a, b), (b, a)):
        ty = _host_tx(y)
        if ty and any(tuple(map(str, ref)) == ty for ref in (x.get("crossRefs") or [])):
            return REL_CROSS_SOURCE, "explicit cross-reference to the host transaction"

    ha, hb = _host_key(a), _host_key(b)
    if ha and hb and ha != hb:
        return REL_DISTINCT, "different host leagues"
    da, db = _day(a), _day(b)
    if da and db and abs((da - db).days) > day_tolerance:
        return REL_DISTINCT, f"dates {abs((da - db).days)} days apart"
    partial = partial_record(a) or partial_record(b)
    if a.get("teamCount") and b.get("teamCount") and a["teamCount"] != b["teamCount"]:
        # A partial record may be missing a roster, so its team count is not
        # evidence of a different trade.
        if not partial:
            return REL_DISTINCT, "different number of teams in the transaction"

    strip = faab_unrecorded(a) or faab_unrecorded(b)
    same_package = package_signature(a, strip_faab=strip) == package_signature(b, strip_faab=strip)
    both_resolved = fully_resolved(a) and fully_resolved(b)
    dated = da is not None and db is not None
    same_league = ha is not None and ha == hb

    if same_package and both_resolved and dated and same_league:
        return REL_PROBABLE, "same league, same canonical package, dates within tolerance"
    shared = resolved_keys(a) & resolved_keys(b)
    if not shared:
        return REL_DISTINCT, "no shared resolved asset"
    if same_package:
        if not same_league:
            return REL_POSSIBLE, "same package and day but league identity unproven"
        if not dated:
            return REL_POSSIBLE, "same league and package but an undated observation"
        return REL_POSSIBLE, "same league and package but an unresolved asset"
    if same_league and not (both_resolved):
        # Same league, overlapping assets, an unresolved reference could be
        # hiding the difference — not provable either way.
        return REL_POSSIBLE, "same league, overlapping assets, unresolved reference"
    if same_league and partial:
        # The Sleeper record is known to be incomplete (an add with no sender,
        # or an asset released inside the trade), so the mismatch may be the
        # recording gap rather than a different trade.
        return REL_POSSIBLE, "same league, overlapping assets, partial host record"
    return REL_DISTINCT, "packages differ"


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic root: lexicographically smallest.
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


@dataclass
class GroupingResult:
    groups: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    volume: dict[str, Any] = field(default_factory=dict)


def _window_partners(
    i: int,
    day_i: date | None,
    by_day: Mapping[date, Sequence[int]],
    undated: Sequence[int],
    everyone: Sequence[int],
    day_tolerance: int,
) -> Iterable[int]:
    """Members of one block whose dates could be within the tolerance of row
    ``i`` (an undated row on either side cannot be ruled out)."""
    if day_i is None:
        return everyone
    out: list[int] = list(undated)
    for k in range(-day_tolerance, day_tolerance + 1):
        out.extend(by_day.get(date.fromordinal(day_i.toordinal() + k), ()))
    return out


def _candidate_pairs(
    observations: Sequence[Mapping[str, Any]], day_tolerance: int
) -> set[tuple[int, int]]:
    """Pairs :func:`classify_pair` could relate; everything else is DISTINCT
    by construction (see BLOCKING in the module docstring)."""
    pairs: set[tuple[int, int]] = set()

    def add(i: int, j: int) -> None:
        if i != j:
            pairs.add((i, j) if i < j else (j, i))

    days = [_day(o) for o in observations]
    has_tx = [_host_tx(o) is not None for o in observations]

    # 1. Same host transaction, or an explicit cross-reference to one.
    by_tx: dict[tuple[str, ...], list[int]] = {}
    for i, obs in enumerate(observations):
        tx = _host_tx(obs)
        if tx:
            by_tx.setdefault(tx, []).append(i)
        for ref in obs.get("crossRefs") or []:
            by_tx.setdefault(tuple(map(str, ref)), []).append(i)
    for bucket in by_tx.values():
        for x in range(len(bucket)):
            for y in range(x + 1, len(bucket)):
                add(bucket[x], bucket[y])

    # 2. Same (host, league), dates within the tolerance.  Two rows that both
    #    carry a host tx id are skipped: same league + two ids is DISTINCT,
    #    and the same id was already paired in step 1.
    # 3. No league identity: only a package match can relate it, so block on
    #    the FAAB-stripped package signature (a superset of the exact one).
    by_league: dict[tuple[str, str], list[int]] = {}
    by_package: dict[tuple[tuple[str, ...], ...], list[int]] = {}
    for i, obs in enumerate(observations):
        hk = _host_key(obs)
        if hk is not None:
            by_league.setdefault(hk, []).append(i)
        by_package.setdefault(package_signature(obs, strip_faab=True), []).append(i)

    def index(members: Sequence[int]) -> tuple[dict[date, list[int]], list[int]]:
        by_day: dict[date, list[int]] = {}
        undated: list[int] = []
        for m in members:
            if days[m] is None:
                undated.append(m)
            else:
                by_day.setdefault(days[m], []).append(m)
        return by_day, undated

    for members in by_league.values():
        if len(members) < 2:
            continue
        by_day, undated = index(members)
        for i in members:
            if has_tx[i]:
                continue  # its tx-less partners reach it from their own side
            for j in _window_partners(i, days[i], by_day, undated, members, day_tolerance):
                add(i, j)

    for members in by_package.values():
        unkeyed = [m for m in members if _host_key(observations[m]) is None]
        if not unkeyed or len(members) < 2:
            continue
        by_day, undated = index(members)
        for i in unkeyed:
            for j in _window_partners(i, days[i], by_day, undated, members, day_tolerance):
                add(i, j)
    return pairs


def _group_id(members: Sequence[Mapping[str, Any]]) -> str:
    txs = sorted(t for t in (_host_tx(m) for m in members) if t)
    if txs:
        return underlying_trade_id_for_host_tx(*txs[0])
    natives = sorted(f"{m['sourceFamily']}:{m['sourceNativeId']}" for m in members)
    return f"utrade:{natives[0]}"


def _representative(members: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    def rank(m: Mapping[str, Any]) -> tuple:
        src = m.get("formatSource")
        pref = (
            _FORMAT_PREFERENCE.index(src) if src in _FORMAT_PREFERENCE else len(_FORMAT_PREFERENCE)
        )
        unresolved = sum(
            1
            for side in m["sides"]
            for a in side
            if a.get("canonicalId") is None and a.get("kind") != "faab"
        )
        return (unresolved, 0 if _host_tx(m) else 1, pref, m["observationId"])

    return sorted(members, key=rank)[0]


def group_observations(
    observations: Sequence[Mapping[str, Any]], *, day_tolerance: int = DEFAULT_DAY_TOLERANCE
) -> GroupingResult:
    ids = [str(o["observationId"]) for o in observations]
    if len(set(ids)) != len(ids):
        # The archive already collapses identical re-observations; a repeated
        # observation id here would mean a lane emitted one fact twice.
        seen: dict[str, int] = {}
        uniq: list[Mapping[str, Any]] = []
        for o in observations:
            if str(o["observationId"]) in seen:
                continue
            seen[str(o["observationId"])] = 1
            uniq.append(o)
        observations = uniq
        ids = [str(o["observationId"]) for o in observations]
    by_id = {str(o["observationId"]): o for o in observations}

    edges: list[dict[str, Any]] = []
    candidates = _candidate_pairs(observations, day_tolerance)
    for i, j in sorted(candidates):
        rel, evidence = classify_pair(observations[i], observations[j], day_tolerance=day_tolerance)
        if rel == REL_DISTINCT:
            continue
        edges.append({"a": ids[i], "b": ids[j], "relation": rel, "evidence": evidence})

    uf = _UnionFind(ids)
    for e in edges:
        if e["relation"] in (REL_SAME_HOST_TX, REL_CROSS_SOURCE):
            uf.union(e["a"], e["b"])

    # Probable edges merge only when the match is UNIQUE between the two
    # confirmed components; a component with two probable partners is
    # ambiguous (which of two identical trades is it?) and degrades to
    # POSSIBLE rather than guessing.
    partners: dict[str, set[str]] = {}
    for e in edges:
        if e["relation"] != REL_PROBABLE:
            continue
        ra, rb = uf.find(e["a"]), uf.find(e["b"])
        if ra == rb:
            continue
        partners.setdefault(ra, set()).add(rb)
        partners.setdefault(rb, set()).add(ra)
    accepted: list[tuple[str, str]] = []
    for e in edges:
        if e["relation"] != REL_PROBABLE:
            continue
        ra, rb = uf.find(e["a"]), uf.find(e["b"])
        if ra == rb:
            continue
        if len(partners.get(ra, ())) == 1 and len(partners.get(rb, ())) == 1:
            accepted.append((e["a"], e["b"]))
        else:
            e["relation"] = REL_POSSIBLE
            e["evidence"] += "; candidate not unique — not merged"
    for a, b in accepted:
        uf.union(a, b)

    components: dict[str, list[str]] = {}
    for oid in ids:
        components.setdefault(uf.find(oid), []).append(oid)

    root_to_gid: dict[str, str] = {}
    for root, members in components.items():
        root_to_gid[root] = _group_id([by_id[m] for m in members])

    internal_by_root: dict[str, list[dict[str, Any]]] = {}
    external_by_root: dict[str, set[str]] = {}
    for e in edges:
        ra, rb = uf.find(e["a"]), uf.find(e["b"])
        if ra == rb:
            internal_by_root.setdefault(ra, []).append(e)
        elif e["relation"] == REL_POSSIBLE:
            external_by_root.setdefault(ra, set()).add(rb)
            external_by_root.setdefault(rb, set()).add(ra)

    groups: list[dict[str, Any]] = []
    for root, member_ids in components.items():
        members = [by_id[m] for m in sorted(member_ids)]
        internal = internal_by_root.get(root, [])
        external = external_by_root.get(root, set())
        rels = {e["relation"] for e in internal}
        if len(members) > 1:
            state = PROBABLE_DUPLICATE if REL_PROBABLE in rels else CONFIRMED_DUPLICATE
        elif external:
            state = POSSIBLE_OVERLAP
        elif not resolved_keys(members[0]) and not _host_tx(members[0]):
            state = UNRESOLVED
        else:
            state = CONFIRMED_UNIQUE
        rep = _representative(members)
        related = sorted({root_to_gid[other] for other in external})
        flags: dict[str, Any] = {}
        for m in members:
            for k, v in (m.get("vendorFlags") or {}).items():
                if v is not None:
                    flags.setdefault(k, v)
        groups.append(
            {
                "underlyingTradeId": root_to_gid[root],
                "dedupeState": state,
                "members": [m["observationId"] for m in members],
                "observationCount": len(members),
                "sourceFamilies": sorted({m["sourceFamily"] for m in members}),
                "provenance": sorted({p for m in members for p in (m.get("provenance") or [])}),
                "relations": sorted(rels),
                "possibleOverlapWith": related,
                "representativeObservationId": rep["observationId"],
                "host": rep.get("host"),
                "hostLeagueId": rep.get("hostLeagueId"),
                "hostTxId": next((str(m["hostTxId"]) for m in members if m.get("hostTxId")), None),
                "occurredDate": rep.get("occurredDate"),
                "occurredAtMs": rep.get("occurredAtMs"),
                "teamCount": rep.get("teamCount"),
                "sides": rep["sides"],
                "formatSource": rep.get("formatSource"),
                "_format": rep.get("_format"),
                "marketFormat": rep.get("marketFormat"),
                "vendorFlags": flags,
                "sampleProvenance": [
                    m["sampleProvenance"] for m in members if m.get("sampleProvenance")
                ],
                "caveats": sorted({c for m in members for c in (m.get("caveats") or [])}),
                "leagueKey": rep.get("leagueKey"),
            }
        )
    groups.sort(key=lambda g: g["underlyingTradeId"])

    # Volume bounds (§19.6): never silently double count, never silently delete.
    confirmed_only = _UnionFind(ids)
    for e in edges:
        if e["relation"] in (REL_SAME_HOST_TX, REL_CROSS_SOURCE):
            confirmed_only.union(e["a"], e["b"])
    upper = len({confirmed_only.find(i) for i in ids})
    widest = _UnionFind(ids)
    for e in edges:
        widest.union(e["a"], e["b"])
    lower = len({widest.find(i) for i in ids})
    states: dict[str, int] = {}
    for g in groups:
        states[g["dedupeState"]] = states.get(g["dedupeState"], 0) + 1
    rel_counts: dict[str, int] = {}
    for e in edges:
        rel_counts[e["relation"]] = rel_counts.get(e["relation"], 0) + 1
    return GroupingResult(
        groups=groups,
        edges=edges,
        volume={
            "rawObservations": len(ids),
            "candidatePairsCompared": len(candidates),
            "underlyingTradesPointEstimate": len(groups),
            "underlyingTradesLowerBound": lower,
            "underlyingTradesUpperBound": upper,
            "groupsByState": states,
            "edgesByRelation": rel_counts,
        },
    )


def count_independent_events(
    votes: Iterable[Mapping[str, Any]], *, key: str = "underlyingTradeId"
) -> int:
    """How many INDEPENDENT events a set of downstream uses rests on.

    A trade that informs both broad-market pricing and Sharp-behaviour analysis
    appears twice in a list of uses and once here (spec §19.7, addendum item 2).
    """
    return len({v[key] for v in votes if v.get(key)})
