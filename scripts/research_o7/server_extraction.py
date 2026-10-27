"""O7 one-shot READ-ONLY extraction (owner-approved 2026-10-27).

Not runnable as committed: ``scripts/research_o7/prep_input.py`` renders it with the
embedded input.  Kept for reproducibility of
``docs/market_trades/O7_PRODUCTION_CANONICAL_HISTORY_COVERAGE_2026-10-27.md``.

Runs on the production box from stdin (``python3 -I -B -``) with cwd = the app
directory.  It writes NOTHING: no file is opened for writing, every SQLite connection
is ``mode=ro&immutable=1`` (no -wal / -shm / journal is created or touched, no lock is
taken) with ``PRAGMA query_only`` and ``PRAGMA temp_store=MEMORY`` (no temp-file
spill), ``-B`` + ``sys.dont_write_bytecode`` stop .pyc writes, and the only output is
one aggregate JSON document on stdout.

Point-in-time semantics are ``src.history.asof.batch_known_before`` itself (instant-
strict selection, origin priority, corrections, history floor).  The only thing
replaced is how its connection is opened (``asof._connect_readonly``), because
``mode=ro`` alone on a WAL database with no -shm present would let SQLite CREATE the
-shm file.

Two modes, both reported:
* ``strict`` (PRIMARY, preregistration §2.4): knowledge_cutoff = the trade instant, so an
  observation counts only if the ledger had RECORDED it by then (a later backfill /
  migration / correction is invisible).
* ``validTime`` (sensitivity, = the census's semantics): observed at/before the instant,
  whatever its recording time.

No value is compared, differenced or summarised: a value is used only as "present and
positive".  Order: pricing first (cheap, indexed), coverage census second (one
sequential scan, aggregated in Python), each under its own deadline; a deadline or
SQLite error still emits the aggregates gathered so far with an explicit status.
"""

from __future__ import annotations

import json
import os

try:
    import resource
except ImportError:  # local Windows dry run only
    resource = None
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
APP = Path.cwd()
sys.path.insert(0, str(APP))

T0 = time.perf_counter()
LOAD0 = os.getloadavg() if hasattr(os, "getloadavg") else None
PRICING_DEADLINE_S = 300.0
TOTAL_DEADLINE_S = 750.0
_END = [T0 + PRICING_DEADLINE_S]
SMALL = 5
AGE_GATE = 7
INPUT = json.loads("__O7_INPUT__")  # replaced by prep_input.py with the embedded input

from src.history import asof, store  # noqa: E402

_OVERRIDE = os.environ.get("O7_LEDGER_OVERRIDE")  # local dry run only; reported
LEDGER = Path(_OVERRIDE or store.DB_PATH)
BOARD_HISTORY = APP / "data" / "board_history.sqlite"
OWN_FORMAT_STORE = APP / "data" / "leagues" / "own_league_format_captures.sqlite"
LANES = (
    ("canonical", store.LANE_CANONICAL, ""),
    ("idptc", store.LANE_SOURCE, "idpTradeCalc"),
    ("ktc", store.LANE_SOURCE, "ktcSfTep"),
)


def _stat(p: Path) -> dict | None:
    try:
        s = p.stat()
    except FileNotFoundError:
        return None
    return {"size": s.st_size, "mtimeNs": s.st_mtime_ns}


def _header_journal(p: Path) -> str | None:
    try:
        with p.open("rb") as f:  # read-only byte read of the 100-byte header
            h = f.read(100)
    except FileNotFoundError:
        return None
    if not h.startswith(b"SQLite format 3\x00"):
        return "not_sqlite"
    return {(1, 1): "rollback", (2, 2): "wal"}.get((h[18], h[19]), f"other:{h[18]}/{h[19]}")


def _side_files(p: Path) -> dict:
    return {sfx: _stat(Path(str(p) + sfx)) for sfx in ("-wal", "-shm", "-journal")}


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=1")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.set_progress_handler(lambda: 1 if time.perf_counter() > _END[0] else 0, 10000)
    return conn


def _connect_immutable(path):
    target = Path(path or store.DB_PATH)
    if not target.exists():
        return None
    return _ro(target)


asof._connect_readonly = _connect_immutable  # same reads, no side files


def sup(n: int):
    """Small-cell suppression for published counts (0 stays exact)."""
    return n if n == 0 or n >= SMALL else f"<{SMALL}"


def quant(values, suppress=True):
    v = sorted(values)
    n = len(v)
    if n >= 8:
        q = statistics.quantiles(v, n=4, method="inclusive")
        return {"n": n, "p25": q[0], "median": statistics.median(v), "p75": q[2]}
    if n >= 5:
        return {"n": n, "median": statistics.median(v)}
    return {"n": sup(n) if suppress else n, "suppressed": suppress and n > 0}


def age_bucket(d) -> str:
    if d is None:
        return "unknown"
    for hi, name in ((0, "0"), (1, "1"), (3, "2-3"), (7, "4-7"), (14, "8-14"), (30, "15-30")):
        if d <= hi:
            return name
    return ">30"


def _finish(out: dict, status: str) -> None:
    post = {
        "ledger": {"stat": _stat(LEDGER), "side": _side_files(LEDGER)},
        "boardHistory": {"stat": _stat(BOARD_HISTORY), "side": _side_files(BOARD_HISTORY)},
    }
    pre = out["preflight"]
    changed = (
        pre["ledger"]["stat"] != post["ledger"]["stat"]
        or pre["ledger"]["side"] != post["ledger"]["side"]
    )
    out["postflight"] = post
    out["ledgerChangedDuringRead"] = changed
    out["status"] = "PARTIAL_CONCURRENT_WRITE" if (changed and status == "COMPLETE") else status
    ru = resource.getrusage(resource.RUSAGE_SELF) if resource else None
    out["resources"] = {"elapsedSeconds": round(time.perf_counter() - T0, 2)}
    if ru is not None:
        out["resources"].update(
            {
                "maxRssMb": round(ru.ru_maxrss / 1024, 1),
                "userCpuSeconds": round(ru.ru_utime, 2),
                "sysCpuSeconds": round(ru.ru_stime, 2),
                "blockReads": ru.ru_inblock,
                "blockWrites": ru.ru_oublock,
            }
        )
    out["resources"]["loadAvgBefore"] = LOAD0
    out["resources"]["loadAvgAfter"] = os.getloadavg() if hasattr(os, "getloadavg") else None
    out["resources"]["pythonDontWriteBytecode"] = sys.dont_write_bytecode
    out["ledgerOverrideUsed"] = bool(_OVERRIDE)
    text = json.dumps(out, sort_keys=True, default=str)
    assert "player:" not in text
    print(text)


# ── preflight ──────────────────────────────────────────────────────────────
pre = {
    "ledger": {
        "stat": _stat(LEDGER),
        "journal": _header_journal(LEDGER),
        "side": _side_files(LEDGER),
    },
    "boardHistory": {
        "stat": _stat(BOARD_HISTORY),
        "journal": _header_journal(BOARD_HISTORY),
        "side": _side_files(BOARD_HISTORY),
    },
}
out: dict = {
    "schema": "o7_aggregate/v2",
    "preflight": pre,
    "inputs": {
        "trades": len(INPUT["trades"]),
        "historyFloor": store.HISTORY_FLOOR,
        "ageGateDays": AGE_GATE,
        "smallCellSuppressionBelow": SMALL,
    },
}
abort = None
if pre["ledger"]["stat"] is None:
    abort = "ledger_missing"
else:
    wal = pre["ledger"]["side"]["-wal"]
    if wal is not None and wal["size"] > 0:
        abort = "ledger_wal_not_checkpointed"  # immutable read would miss committed rows
if abort:
    out["abortReason"] = abort
    _finish(out, "BLOCKED")
    raise SystemExit(0)

# ── pricing ────────────────────────────────────────────────────────────────
trades = INPUT["trades"]
for t in trades:
    t["_inst"] = datetime.fromisoformat(t["instant"]).astimezone(timezone.utc)
    t["_floor"] = t["_inst"].date().isoformat() >= store.HISTORY_FLOOR
seasons = sorted({t["season"] for t in trades})
out["inputs"]["seasons"] = seasons


def missing_reason(t, a, res):
    if not t["_floor"]:
        return "before_history_boundary"
    if a["kind"] == "pick":
        return "pick_unpriced_by_construction"
    if a["kind"] == "unresolved":
        return "unresolved_identity"
    if res and res.get("value") is not None and not (res["value"] > 0):
        return "non_positive_value"
    if (
        res
        and res.get("fidelity") in (asof.FIDELITY_EXACT, asof.FIDELITY_NEAREST_PRIOR)
        and res.get("value") is None
    ):
        return "observation_without_value"
    return (res or {}).get("missingReason") or "no_observation"


def price(mode: str):
    """mode strict|validTime -> per trade, per asset index, per lane: asof result."""
    out_ = [[{} for _ in t["assets"]] for t in trades]
    for lname, lane, skey in LANES:
        if mode == "strict":
            for ti, t in enumerate(trades):
                ais = [ai for ai, a in enumerate(t["assets"]) if a.get("key")]
                if not ais:
                    continue
                res = asof.batch_known_before(
                    [(t["assets"][ai]["key"], t["_inst"]) for ai in ais],
                    lane=lane,
                    source_key=skey,
                    path=LEDGER,
                    knowledge_cutoff=t["_inst"],
                )["results"]
                for ai, rr in zip(ais, res):
                    out_[ti][ai][lname] = rr
        else:
            flat = [
                (ti, ai)
                for ti, t in enumerate(trades)
                for ai, a in enumerate(t["assets"])
                if a.get("key")
            ]
            res = asof.batch_known_before(
                [(trades[ti]["assets"][ai]["key"], trades[ti]["_inst"]) for ti, ai in flat],
                lane=lane,
                source_key=skey,
                path=LEDGER,
            )["results"]
            for (ti, ai), rr in zip(flat, res):
                out_[ti][ai][lname] = rr
    return out_


def priced(rr, gate=None) -> bool:
    if not rr or rr.get("fidelity") not in (asof.FIDELITY_EXACT, asof.FIDELITY_NEAREST_PRIOR):
        return False
    v = rr.get("value")
    if v is None or not (v > 0):  # missing is never zero, and zero is never a price
        return False
    return gate is None or (rr.get("distanceDays") is not None and rr["distanceDays"] <= gate)


def full(t, pr, lanes, gate=None, same_snapshot=False) -> bool:
    """Census rule: every non-FAAB asset priced in every lane, and no FAAB component.
    ``same_snapshot`` adds preregistration §2.4: within each lane, every asset of the
    trade is priced from ONE observed date."""
    req = [i for i, a in enumerate(t["assets"]) if a["kind"] != "faab"]
    if not req or any(a["kind"] == "faab" for a in t["assets"]):
        return False
    if not all(priced(pr[i].get(ln), gate) for i in req for ln in lanes):
        return False
    if same_snapshot:
        for ln in lanes:
            if len({pr[i][ln]["observedDate"] for i in req}) != 1:
                return False
    return True


try:
    strict = price("strict")
    valid = price("validTime")
except sqlite3.Error as exc:  # deadline interrupt or a torn immutable read
    out["abortReason"] = f"pricing_{type(exc).__name__}: {exc}"[:200]
    _finish(out, "BLOCKED")
    raise SystemExit(0)
out["pricingSeconds"] = round(time.perf_counter() - T0, 2)


def fam_of(a) -> str:
    if a.get("family") in ("DL", "LB", "DB"):
        return "IDP"
    if a["kind"] == "pick":
        return "PICK"
    if a.get("family") in ("QB", "RB", "WR", "TE"):
        return "OFFENSE"
    return "OTHER"


# asset-level fidelity / age / origin / missingness (2026 season)
asset_rep = {}
for mode, pr in (("strict", strict), ("validTime", valid)):
    rep = {}
    for lname, _, _ in LANES:
        fid = Counter()
        reasons = Counter()
        ages = []
        origins = Counter()
        rec_after = 0
        by_fam = defaultdict(Counter)
        for ti, t in enumerate(trades):
            if t["season"] != "2026":
                continue
            for ai, a in enumerate(t["assets"]):
                if a["kind"] == "faab":
                    continue
                rr = pr[ti][ai].get(lname)
                fam = fam_of(a)
                if priced(rr):
                    fid[rr["fidelity"]] += 1
                    by_fam[fam]["priced"] += 1
                    if rr["distanceDays"] is not None and rr["distanceDays"] <= AGE_GATE:
                        by_fam[fam]["pricedWithinAgeGate"] += 1
                    ages.append(rr["distanceDays"])
                    prov = rr.get("provenance") or {}
                    origins[prov.get("origin")] += 1
                    rat = asof.parse_instant_utc(prov.get("recordedAt"))
                    if rat is None or rat > t["_inst"]:
                        rec_after += 1
                else:
                    fid["missing"] += 1
                    by_fam[fam]["missing"] += 1
                    reasons[missing_reason(t, a, rr)] += 1
        rep[lname] = {
            "season2026Assets": {k: sup(v) for k, v in fid.items()},
            "missingReasons": {k: sup(v) for k, v in reasons.items()},
            "byFamily": {f: {k: sup(v) for k, v in c.items()} for f, c in by_fam.items()},
            "ageDaysQuantiles": quant([x for x in ages if x is not None]),
            "ageBuckets": {k: sup(v) for k, v in Counter(age_bucket(x) for x in ages).items()},
            "selectedOrigin": {str(k): sup(v) for k, v in origins.items()},
            "selectedRecordedAfterTradeInstant": sup(rec_after),
        }
    asset_rep[mode] = rep
out["assets2026"] = asset_rep


def players_only(t) -> bool:
    return all(a["kind"] == "player" for a in t["assets"])


SUBSETS = {
    "all": lambda t: True,
    "containsIdp": lambda t: t["classes"]["containsIdp"],
    "offenseForIdp": lambda t: t["classes"]["offenseForIdp"],
    "idpForIdp": lambda t: t["classes"]["idpForIdp"],
    "oneForOnePlayersOnly": lambda t: t["classes"]["oneForOne"] and players_only(t),
    "idpOneForOnePlayersOnly": lambda t: t["classes"]["oneForOne"]
    and t["classes"]["containsIdp"]
    and players_only(t),
    "fitClean": lambda t: t["fit"] == "clean_1_for_1",
    "fitPackage": lambda t: t["fit"] == "package_va_required",
    "noPicksTwoTeamNoFaab": lambda t: not t["classes"]["containsPicks"]
    and not t["classes"]["multiTeam"]
    and not t["classes"]["containsFaab"],
}
counts = {}
for s in seasons:
    counts[s] = {}
    for name, pred in SUBSETS.items():
        idx = [ti for ti, t in enumerate(trades) if t["season"] == s and pred(t)]
        T, S_, V = trades, strict, valid
        c = {
            "trades": len(idx),
            "onOrAfterFloor": sum(1 for ti in idx if T[ti]["_floor"]),
            "fullCanonicalStrict": sum(1 for ti in idx if full(T[ti], S_[ti], ["canonical"])),
            "fullCanonicalStrictAge7": sum(
                1 for ti in idx if full(T[ti], S_[ti], ["canonical"], AGE_GATE)
            ),
            "fullCanonicalValidTime": sum(1 for ti in idx if full(T[ti], V[ti], ["canonical"])),
            "fullIdptcStrict": sum(1 for ti in idx if full(T[ti], S_[ti], ["idptc"])),
            "fullIdptcStrictAge7": sum(1 for ti in idx if full(T[ti], S_[ti], ["idptc"], AGE_GATE)),
            "fullIdptcValidTime": sum(1 for ti in idx if full(T[ti], V[ti], ["idptc"])),
            "fullCanonicalAndIdptcStrictAge7": sum(
                1 for ti in idx if full(T[ti], S_[ti], ["canonical", "idptc"], AGE_GATE)
            ),
            "fullCanonicalAndIdptcStrictAge7SameSnapshot": sum(
                1
                for ti in idx
                if full(T[ti], S_[ti], ["canonical", "idptc"], AGE_GATE, same_snapshot=True)
            ),
            "fullCanonicalStrictNotFullIdptcStrict": sum(
                1
                for ti in idx
                if full(T[ti], S_[ti], ["canonical"]) and not full(T[ti], S_[ti], ["idptc"])
            ),
            "anyAssetCanonicalStrict": sum(
                1
                for ti in idx
                if any(priced(S_[ti][ai].get("canonical")) for ai in range(len(T[ti]["assets"])))
            ),
        }
        counts[s][name] = {k: sup(v) for k, v in c.items()}
out["tradeCounts"] = counts


# H2 / H6d readiness (eligibility and coverage only; no residual is computed)
def h2_eligible(t) -> bool:
    return (
        t["season"] == "2026"
        and t["fit"] == "clean_1_for_1"
        and t["classes"]["oneForOne"]
        and not t["classes"]["multiTeam"]
        and players_only(t)
    )


h2_base = [ti for ti, t in enumerate(trades) if h2_eligible(t)]
idp26 = [ti for ti, t in enumerate(trades) if t["season"] == "2026" and t["classes"]["containsIdp"]]
idp_legs = [
    (ti, ai)
    for ti in idp26
    for ai, a in enumerate(trades[ti]["assets"])
    if a.get("family") in ("DL", "LB", "DB")
]
out["readiness"] = {
    "H2": {
        "nMin": 55,
        "structurallyEligible2026": sup(len(h2_base)),
        "pricedCanonicalAndIdptcStrictAge7": sup(
            sum(
                1
                for ti in h2_base
                if full(trades[ti], strict[ti], ["canonical", "idptc"], AGE_GATE)
            )
        ),
        "pricedCanonicalAndIdptcStrictAge7SameSnapshot": sup(
            sum(
                1
                for ti in h2_base
                if full(
                    trades[ti], strict[ti], ["canonical", "idptc"], AGE_GATE, same_snapshot=True
                )
            )
        ),
        "formatBracketConfirmation": (
            "store_present_not_evaluated"
            if OWN_FORMAT_STORE.exists()
            else "unavailable: own-league format capture store absent"
        ),
    },
    "H6d": {
        "idpAssetLegs2026": sup(len(idp_legs)),
        "idpAssetLegsCanonicalStrictAge7": sup(
            sum(1 for ti, ai in idp_legs if priced(strict[ti][ai].get("canonical"), AGE_GATE))
        ),
        "note": "the untraded comparison set needs the full canonical IDP board per trade date: see ledger.canonicalBoard.rowsPerDateByAssetClass",
    },
}

# ── coverage census: ONE sequential scan, aggregated in Python ─────────────
_END[0] = T0 + TOTAL_DEADLINE_S
status = "COMPLETE"
try:
    conn = _ro(LEDGER)
    try:
        lanes_days = defaultdict(Counter)  # lane -> date -> rows
        src_days = defaultdict(Counter)  # source_key -> date -> rows
        canon_by = defaultdict(Counter)  # date -> asset_class -> rows
        origin_rows = Counter()
        origin_days = defaultdict(set)
        origin_rec = {}
        zone = Counter()
        canon_assets = set()
        below_floor = 0
        cur = conn.execute(
            "SELECT lane, source_key, observed_date, asset_class, origin, observed_at_zone, recorded_at, asset_key "
            "FROM observations NOT INDEXED"
        )
        while True:
            rows = cur.fetchmany(20000)
            if not rows:
                break
            for lane, skey, d, cls, origin, z, rec, key in rows:
                lanes_days[lane][d] += 1
                if d < store.HISTORY_FLOOR:
                    below_floor += 1
                if lane == store.LANE_SOURCE:
                    src_days[skey][d] += 1
                elif lane == store.LANE_CANONICAL:
                    canon_by[d][cls] += 1
                    origin_rows[origin] += 1
                    origin_days[origin].add(d)
                    lo, hi = origin_rec.get(origin, (rec, rec))
                    origin_rec[origin] = (
                        min(lo, rec) if lo and rec else lo or rec,
                        max(hi, rec) if hi and rec else hi or rec,
                    )
                    zone[z or "none"] += 1
                    canon_assets.add(key)
        corrections = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}
    finally:
        conn.close()

    def _span(c: Counter) -> dict:
        ds = sorted(c)
        return {
            "rows": sum(c.values()),
            "days": len(ds),
            "firstDate": ds[0] if ds else None,
            "lastDate": ds[-1] if ds else None,
        }

    classes_seen = sorted({c for d in canon_by.values() for c in d})
    out["ledger"] = {
        "meta": {k: v for k, v in meta.items() if "version" in k or "floor" in k},
        "lanes": {ln: _span(c) for ln, c in lanes_days.items()},
        "sourceLanes": {
            k: _span(c)
            for k, c in src_days.items()
            if k in ("idpTradeCalc", "ktcSfTep", "ktcCrowdSfTep", "ktcTradesSfTep", "ktc")
        },
        "sourceLaneKeysCount": len(src_days),
        "rowsBelowHistoryFloor": below_floor,
        "canonicalBoard": {
            "distinctAssets": len(canon_assets),
            "rowsPerDateByAssetClass": {
                c: quant([canon_by[d].get(c, 0) for d in sorted(canon_by)], suppress=False)
                for c in classes_seen
            },
            "byOrigin": {
                o: {
                    "rows": n,
                    "days": len(origin_days[o]),
                    "firstDate": min(origin_days[o]),
                    "lastDate": max(origin_days[o]),
                    "firstRecordedAt": origin_rec[o][0],
                    "lastRecordedAt": origin_rec[o][1],
                }
                for o, n in origin_rows.items()
            },
            "observedAtZone": dict(zone),
        },
        "correctionsRows": corrections,
    }
    if BOARD_HISTORY.exists():
        bc = _ro(BOARD_HISTORY)
        try:
            days = Counter()
            for (d,) in bc.execute("SELECT as_of FROM board_history NOT INDEXED"):
                days[d] += 1
            out["boardHistory"] = _span(days)
        finally:
            bc.close()
    else:
        out["boardHistory"] = {"state": "unavailable", "reason": "file_absent"}
except sqlite3.Error as exc:
    out["coverageAbort"] = f"{type(exc).__name__}: {exc}"[:200]
    status = "PARTIAL_COVERAGE_INCOMPLETE"

_finish(out, status)
