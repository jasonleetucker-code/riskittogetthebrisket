#!/usr/bin/env python3
"""Research: value dynamics and replacement cost of LOW-VALUE assets.

Owner research program 2026-10-20.  Question: are assets the canonical board
prices low (``rankDerivedValue`` roughly < 3,000 on 1-9999) mis-valued?  This
script studies value DYNAMICS and REPLACEMENT COST, not trades.  It changes no
production value, model, config or file outside its own ``--out`` path.

Four lanes, each labelled in the output:

A. **Canonical value aging — SENSITIVITY REPLAY.**  Boards are rebuilt with
   TODAY's code (``build_api_data_contract``) from each day's archived raw
   payload (``exports/archive``) plus the source CSVs *as committed at that
   moment* (git history, or the GitHub contents API when the local clone is
   shallow).  No dataset state is supplied, so freshness weighting is off —
   the documented replay posture ("never today's state applied to a past
   board").  These are NOT observed history: today's methodology on past
   inputs.  Value change by start-value band, position and asset class over
   14/30/60/90 days; drop-off (absent) and unpriced are reported separately
   (missing is never zero).

B. **Independent vendor lane.**  Raw KTC SF TEP (``ktcSfTep``) and IDP Trade
   Calculator values read straight out of the same archives — no rebuild — so
   the dynamics are not an artifact of our pipeline.

C. **Replacement cost from waiver markets.**  Waiver / free-agent adds and
   drops (with FAAB bids) from external dynasty leagues in the local intel
   ledger, joined by Sleeper id to the nearest rebuilt board (sensitivity
   replay, labelled).  Unjoined players are counted, never priced at 0.

D. **Curve check against ROS usefulness.**  Canonical value vs the local ROS
   aggregate (``data/ros/aggregate/history``) by value band.  ROS is the
   seasonal-intelligence lane; it is used here as a diagnostic only and never
   touches dynasty valuation.

Output: aggregates only (player names allowed; no league / user / roster ids).

Usage:
    python scripts/low_value_asset_value_dynamics.py \\
        --ledger /path/to/data/intel/ledger.sqlite3 \\
        --out docs/valuation/evidence/low_value_assets_2026-10-20/value_dynamics.json
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import math
import re
import sqlite3
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GH_REPO = "jasonleetucker-code/riskittogetthebrisket"
ARCHIVE_DIR = REPO_ROOT / "exports" / "archive"
ROS_HISTORY_DIR = REPO_ROOT / "data" / "ros" / "aggregate" / "history"
DEFAULT_OUT = (
    REPO_ROOT
    / "docs"
    / "valuation"
    / "evidence"
    / "low_value_assets_2026-10-20"
    / "value_dynamics.json"
)

BAND_EDGES = (0, 500, 1000, 1500, 2000, 3000, 4500, 6000)
BAND_LABELS = (
    "<500",
    "500-1000",
    "1000-1500",
    "1500-2000",
    "2000-3000",
    "3000-4500",
    "4500-6000",
    "6000+",
)
HORIZONS = (14, 30, 60, 90)
EARLY_END = date(2026, 8, 15)  # start <= this: early (mostly offseason / preseason)
LATE_START = date(2026, 9, 1)  # start >= this: late (in season)
NEAREST_TOLERANCE_DAYS = 2
VET_POSITIONS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")
OFFENSE = {"QB", "RB", "WR", "TE"}
IDP = {"DL", "LB", "DB"}

_PICK_RE = re.compile(r"^(20\d\d)\s")

log = logging.getLogger("low_value_dynamics")


# ── small numeric helpers ───────────────────────────────────────────────


def band_index(v: float | None) -> int | None:
    if v is None or not isinstance(v, (int, float)) or v <= 0:
        return None
    idx = 0
    for i, edge in enumerate(BAND_EDGES):
        if v >= edge:
            idx = i
    return idx


def _q(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def ols(xs: list[float], ys: list[float]) -> dict[str, Any]:
    n = len(xs)
    if n < 3:
        return {"n": n, "slope": None, "intercept": None}
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return {"n": n, "slope": None, "intercept": None}
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(e * e for e in resid) / (n - 2) / sxx) if n > 2 else None
    return {"n": n, "slope": _r(slope, 5), "slopeSE": _r(se, 5), "intercept": _r(intercept, 5)}


# ── archives ────────────────────────────────────────────────────────────


def archive_time(path: Path) -> datetime:
    _, _, day, hms = path.stem.split("_")
    return datetime.strptime(day + hms, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def day_archives() -> dict[date, Path]:
    """The LAST export archive of each day."""
    out: dict[date, Path] = {}
    for p in sorted(ARCHIVE_DIR.glob("dynasty_export_*.zip")):
        out[archive_time(p).date()] = p
    return out


def resolve_day(target: date, days: dict[date, Path]) -> date | None:
    if target in days:
        return target
    best = None
    for d in days:
        gap = abs((d - target).days)
        if gap <= NEAREST_TOLERANCE_DAYS and (best is None or gap < abs((best - target).days)):
            best = d
    return best


def load_raw(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        member = next(
            n for n in z.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        return json.loads(z.read(member))


def read_archive_csv(path: Path, name: str) -> dict[str, float] | None:
    with zipfile.ZipFile(path) as z:
        member = f"site_raw/{name}.csv"
        if member not in z.namelist():
            return None
        text = z.read(member).decode("utf-8", "replace")
    out: dict[str, float] = {}
    lines = text.splitlines()
    if not lines:
        return out
    header = [h.strip().lower() for h in lines[0].split(",")]
    if "name" not in header or "value" not in header:
        return None
    ni, vi = header.index("name"), header.index("value")
    for line in lines[1:]:
        parts = line.rsplit(",", len(header) - 1 - ni) if ni == 0 else line.split(",")
        if len(parts) <= max(ni, vi):
            continue
        try:
            v = float(parts[vi])
        except ValueError:
            continue
        nm = parts[ni].strip().strip('"')
        if nm and v > 0:
            out[nm] = v
    return out


# ── historical CSV trees (inputs as committed at the archive moment) ────


class CsvHistory:
    """``CSVs/site_raw`` exactly as committed at ``as_of``.

    ``git`` mode reads the local repository (requires non-shallow history
    covering the window).  ``gh`` mode reads the same commits through the
    GitHub REST API (``gh api``), caching blobs by sha.  The mode used and
    the commit chosen for each board are recorded in the output.
    """

    def __init__(self, mode: str, scratch: Path) -> None:
        self.scratch = scratch
        self.blob_dir = scratch / "blobs"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        if mode == "auto":
            shallow = self._git("rev-parse", "--is-shallow-repository").strip() == "true"
            mode = "gh" if shallow else "git"
        self.mode = mode
        self.api_calls = 0
        self._lock = threading.Lock()

    @staticmethod
    def _git(*args: str, binary: bool = False):
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True)
        return out.stdout if binary else out.stdout.decode()

    def _gh(self, endpoint: str) -> Any:
        with self._lock:
            self.api_calls += 1
        for attempt in range(4):
            res = subprocess.run(["gh", "api", endpoint], capture_output=True)
            if res.returncode == 0:
                return json.loads(res.stdout)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"gh api failed: {endpoint}: {res.stderr.decode()[:300]}")

    def build(self, root: Path, as_of: datetime) -> dict[str, Any]:
        root.mkdir(parents=True, exist_ok=True)
        if self.mode == "git":
            sha = self._git(
                "rev-list", "-1", f"--before={as_of.isoformat()}", "HEAD", "--", "CSVs/site_raw"
            ).strip()
            data = self._git("archive", sha, "CSVs/site_raw", binary=True)
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                tar.extractall(root)  # noqa: S202 — our own repository's archive
            stamp = self._git("show", "-s", "--format=%cI", sha).strip()
            files = sorted(p.name for p in (root / "CSVs" / "site_raw").glob("*"))
            return {"mode": "git", "commit": sha, "commitTime": stamp, "files": files}
        until = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
        commits = self._gh(f"repos/{GH_REPO}/commits?path=CSVs/site_raw&until={until}&per_page=1")
        sha = commits[0]["sha"]
        stamp = commits[0]["commit"]["committer"]["date"]
        listing = self._gh(f"repos/{GH_REPO}/contents/CSVs/site_raw?ref={sha}")
        dest = root / "CSVs" / "site_raw"
        dest.mkdir(parents=True, exist_ok=True)
        entries = [e for e in listing if e.get("type") == "file"]
        missing = [e for e in entries if not (self.blob_dir / e["sha"]).exists()]

        def fetch(entry: dict) -> None:
            blob = self._gh(f"repos/{GH_REPO}/git/blobs/{entry['sha']}")
            (self.blob_dir / entry["sha"]).write_bytes(base64.b64decode(blob["content"]))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch, missing))
        files = []
        for entry in entries:
            (dest / entry["name"]).write_bytes((self.blob_dir / entry["sha"]).read_bytes())
            files.append(entry["name"])
        return {"mode": "gh", "commit": sha, "commitTime": stamp, "files": sorted(files)}


# ── canonical board rebuild (sensitivity replay) ────────────────────────


def _player_key(row: dict) -> str:
    if row.get("assetClass") == "pick":
        return "pick:" + str(row.get("displayName"))
    pid = row.get("playerId")
    if pid:
        return "sid:" + str(pid)
    return "name:" + str(row.get("canonicalName") or row.get("displayName"))


def compact_board(contract: dict) -> dict[str, Any]:
    rows: dict[str, dict] = {}
    voting_sources: Counter = Counter()
    for r in contract.get("playersArray") or []:
        if not r.get("displayName"):
            continue
        v = r.get("rankDerivedValue")
        v = float(v) if isinstance(v, (int, float)) and v > 0 else None
        ranks = r.get("sourceRanks") or {}
        for k in ranks:
            voting_sources[k] += 1
        rows[_player_key(r)] = {
            "name": r.get("displayName"),
            "cname": r.get("canonicalName"),
            "cls": r.get("assetClass"),
            "pos": r.get("position"),
            "rookie": bool(r.get("rookie")),
            "age": r.get("age"),
            "yx": r.get("yearsExp"),
            "v": v,
            "rank": r.get("canonicalConsensusRank"),
            "nsrc": len(ranks),
            "pid": r.get("playerId"),
        }
    weighting = (
        contract.get("sourceWeighting") if isinstance(contract.get("sourceWeighting"), dict) else {}
    )
    return {
        "rows": rows,
        "votingSources": dict(voting_sources),
        "weightingUnavailableReason": weighting.get("unavailableReason"),
    }


def build_boards(
    dates: list[date],
    days: dict[date, Path],
    scratch: Path,
    csv_mode: str,
    *,
    exclude_sources: Iterable[str] = (),
    tag: str = "asPublished",
) -> tuple[dict[date, dict], dict[str, Any]]:
    """Rebuild one board per date.  ``exclude_sources`` turns sources off via
    the pipeline's own ``source_overrides`` (``include: False``), the same path
    the user-settings override uses, so a constant source panel can be held
    across the window."""
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    hist = CsvHistory(csv_mode, scratch)
    boards: dict[date, dict] = {}
    excluded = sorted(set(exclude_sources))
    overrides = {k: {"include": False} for k in excluded} or None
    meta: dict[str, Any] = {"csvHistoryMode": hist.mode, "excludedSources": excluded, "boards": {}}
    cache_dir = scratch / "boards"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for d in dates:
        arch = days[d]
        cache = cache_dir / f"{arch.stem}.{tag}.json"
        if cache.exists():
            entry = json.loads(cache.read_text())
        else:
            root = scratch / "trees" / arch.stem
            tree_meta = scratch / "trees" / f"{arch.stem}.tree.json"
            if tree_meta.exists():
                tree = json.loads(tree_meta.read_text())
            else:
                tree = hist.build(root, archive_time(arch))
                tree_meta.write_text(json.dumps(tree))
            raw = load_raw(arch)
            t0 = time.time()
            contract = build_api_data_contract(raw, csv_root=root, source_overrides=overrides)
            secs = time.time() - t0
            entry = compact_board(contract)
            entry["buildSeconds"] = round(secs, 2)
            entry["csvTree"] = {k: tree[k] for k in ("mode", "commit", "commitTime")}
            entry["csvFiles"] = tree["files"]
            entry["archive"] = arch.name
            entry["scrapeTimestamp"] = raw.get("scrapeTimestamp")
            cache.write_text(json.dumps(entry))
        boards[d] = entry
        rows = entry["rows"]
        priced = sorted((r["v"] for r in rows.values() if r["v"]), reverse=True)
        meta["boards"][d.isoformat()] = {
            "archive": entry["archive"],
            "scrapeTimestamp": entry.get("scrapeTimestamp"),
            "csvCommit": entry["csvTree"]["commit"][:12],
            "csvCommitTime": entry["csvTree"]["commitTime"],
            "csvFileCount": len(entry["csvFiles"]),
            "votingSourceCount": len(entry["votingSources"]),
            "votingSources": sorted(entry["votingSources"]),
            "weightingUnavailableReason": entry.get("weightingUnavailableReason"),
            "rows": len(rows),
            "priced": len(priced),
            "pricedByClass": dict(Counter(r["cls"] for r in rows.values() if r["v"])),
            "valueAtPricedRank": {
                str(k): (priced[k - 1] if len(priced) >= k else None)
                for k in (100, 200, 300, 400, 500, 600, 700, 800, 900)
            },
            "pricedBelow2000": sum(1 for v in priced if v < 2000),
            "pricedBelow3000": sum(1 for v in priced if v < 3000),
            "buildSeconds": entry.get("buildSeconds"),
        }
        print(
            f"  [{tag}] board {d} ({entry['archive']}): {len(rows)} rows, {len(priced)} priced, "
            f"{len(entry['votingSources'])} voting sources",
            flush=True,
        )
    meta["githubApiCalls"] = hist.api_calls
    return boards, meta


# ── lane A / B: value aging ─────────────────────────────────────────────


def asset_group(row: dict) -> str | None:
    cls, pos = row.get("cls"), row.get("pos")
    if cls == "pick":
        return "PICK"
    if row.get("rookie"):
        return "ROOKIE_OFF" if cls == "offense" else ("ROOKIE_IDP" if cls == "idp" else None)
    if pos in VET_POSITIONS:
        return pos
    return None


def family_of(group: str) -> list[str]:
    fams = ["ALL_ASSETS"]
    if group == "PICK":
        fams.append("PICKS")
    elif group.startswith("ROOKIE"):
        fams += ["ALL_PLAYERS", "ROOKIES"]
    elif group in OFFENSE:
        fams += ["ALL_PLAYERS", "VET_OFFENSE"]
    elif group in IDP:
        fams += ["ALL_PLAYERS", "VET_IDP"]
    return [group, *fams]


def _pick_year(name: str) -> int | None:
    m = _PICK_RE.match(name or "")
    return int(m.group(1)) if m else None


def pair_outcomes(
    start: dict[str, dict], end: dict[str, dict], lag: dict[str, dict] | None = None
) -> list[dict]:
    """One outcome per asset priced on the start board."""
    end_pick_years = {_pick_year(r["name"]) for r in end.values() if r.get("cls") == "pick"}
    out = []
    for key, s in start.items():
        if not s["v"]:
            continue
        group = asset_group(s)
        if group is None:
            continue
        band_basis = s["v"]
        if lag is not None:
            lr = lag.get(key)
            if not lr or not lr["v"]:
                continue
            band_basis = lr["v"]
        e = end.get(key)
        state = "priced"
        if e is None:
            state = "absent"
            if group == "PICK" and _pick_year(s["name"]) not in end_pick_years:
                state = "absent_class_retired"
        elif not e["v"]:
            state = "unpriced"
        o = {
            "group": group,
            "band": band_index(band_basis),
            "band0": band_index(s["v"]),
            "v0": s["v"],
            "state": state,
            "name": s["name"],
        }
        if state == "priced":
            o["v1"] = e["v"]
            o["band1"] = band_index(e["v"])
        out.append(o)
    return out


def summarize(outcomes: list[dict], *, start_band_key: str = "band0") -> dict[str, Any]:
    n = len(outcomes)
    priced = [o for o in outcomes if o["state"] == "priced"]
    deltas = [o["v1"] - o["v0"] for o in priced]
    logs = [math.log(o["v1"] / o["v0"]) for o in priced]
    up2 = sum(1 for o in priced if o["band1"] - o[start_band_key] >= 2)
    dn2 = sum(1 for o in priced if o["band1"] - o[start_band_key] <= -2)
    states = Counter(o["state"] for o in outcomes)
    return {
        "n": n,
        "nPricedAtEnd": len(priced),
        "meanDelta": _r(_mean(deltas), 1),
        "medianDelta": _r(_q(deltas, 0.5), 1),
        "meanLogRatio": _r(_mean(logs)),
        "medianLogRatio": _r(_q(logs, 0.5)),
        "p10LogRatio": _r(_q(logs, 0.1)),
        "p90LogRatio": _r(_q(logs, 0.9)),
        "shareAbsentAtEnd": _r(states["absent"] / n) if n else None,
        "shareClassRetiredAtEnd": _r(states["absent_class_retired"] / n) if n else None,
        "shareUnpricedAtEnd": _r(states["unpriced"] / n) if n else None,
        "shareUp2PlusBands": _r(up2 / n) if n else None,
        "shareDown2PlusBands": _r(dn2 / n) if n else None,
    }


AGG_FAMILIES = ("ALL_ASSETS", "ALL_PLAYERS", "VET_OFFENSE", "VET_IDP", "ROOKIES", "PICKS")


def aggregate_aging(
    pairs: list[tuple[date, date, int, list[dict]]],
    horizons_actual: list[dict],
    families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """window -> horizon -> family -> band -> summary."""
    keep = set(families) if families is not None else None
    result: dict[str, Any] = {}
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for start, _end, horizon, outs in pairs:
        windows = ["ALL"]
        if start <= EARLY_END:
            windows.append("EARLY")
        if start >= LATE_START:
            windows.append("LATE")
        for o in outs:
            for w in windows:
                if horizon == 14 and w != "LATE":
                    continue  # 14 days only where 30+ day pairs are scarce
                for fam in family_of(o["group"]):
                    if keep is not None and fam not in keep:
                        continue
                    if fam not in AGG_FAMILIES and w != "ALL":
                        continue  # per-position detail only for the pooled window
                    buckets[(w, horizon, fam, BAND_LABELS[o["band"]])].append(o)
                    buckets[(w, horizon, fam, "ALL_BANDS")].append(o)
                    if o["v0"] < 3000:
                        buckets[(w, horizon, fam, "<3000")].append(o)
                    else:
                        buckets[(w, horizon, fam, ">=3000")].append(o)
    for (w, h, fam, band), outs in sorted(buckets.items(), key=lambda kv: str(kv[0])):
        summary = summarize(outs)
        summary["nDistinctAssets"] = len({o["name"] for o in outs})
        result.setdefault(w, {}).setdefault(str(h), {}).setdefault(fam, {})[band] = summary
    # pooled regression of log-ratio on log start value, per window/horizon/family
    reg: dict[str, Any] = {}
    reg_buckets: dict[tuple, list[dict]] = defaultdict(list)
    for start, _end, horizon, outs in pairs:
        windows = (
            ["ALL"]
            + (["EARLY"] if start <= EARLY_END else [])
            + (["LATE"] if start >= LATE_START else [])
        )
        for o in outs:
            if o["state"] != "priced":
                continue
            for w in windows:
                for fam in family_of(o["group"]):
                    if keep is not None and fam not in keep:
                        continue
                    reg_buckets[(w, horizon, fam)].append(o)
    for (w, h, fam), outs in sorted(reg_buckets.items(), key=lambda kv: str(kv[0])):
        xs = [math.log(o["v0"]) for o in outs]
        ys = [math.log(o["v1"] / o["v0"]) for o in outs]
        reg.setdefault(w, {}).setdefault(str(h), {})[fam] = ols(xs, ys)
    return {
        "byWindowHorizonFamilyBand": result,
        "logRatioOnLogStartOLS": reg,
        "pairs": horizons_actual,
    }


def run_aging(
    boards: dict[date, dict],
    starts: list[date],
    resolver,
    *,
    lagged: bool = False,
    families: Iterable[str] | None = None,
) -> dict[str, Any]:
    pairs = []
    pair_meta = []
    for s in starts:
        if s not in boards:
            continue
        lag_board = None
        if lagged:
            ld = resolver(s - timedelta(days=7))
            if ld is None or ld not in boards or ld == s:
                continue
            lag_board = boards[ld]["rows"]
        for h in HORIZONS:
            e = resolver(s + timedelta(days=h))
            if e is None or e not in boards or e <= s:
                continue
            outs = pair_outcomes(boards[s]["rows"], boards[e]["rows"], lag_board)
            pairs.append((s, e, h, outs))
            pair_meta.append(
                {
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "horizon": h,
                    "actualDays": (e - s).days,
                    "n": len(outs),
                }
            )
    return aggregate_aging(pairs, pair_meta, families)


# ── lane B: vendor boards straight from the archives ────────────────────


def vendor_board(arch: Path, source: str, canon_rows: dict[str, dict]) -> dict[str, dict]:
    """``name -> row`` in the compact-board shape, positions borrowed from the
    canonical board of the same day by normalized name (unmatched rows are
    kept as 'unclassified' and reported)."""
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    values = read_archive_csv(arch, source)
    if values is None:
        raw = load_raw(arch)
        values = {
            n: float(p[source])
            for n, p in (raw.get("players") or {}).items()
            if isinstance(p, dict) and isinstance(p.get(source), (int, float)) and p[source] > 0
        }
    by_norm: dict[str, dict] = {}
    for r in canon_rows.values():
        if r.get("cls") == "pick":
            continue
        k = normalize_player_name(r.get("name"))
        if k:
            by_norm.setdefault(k, r)
    out: dict[str, dict] = {}
    for name, v in values.items():
        if _pick_year(name):
            out["pick:" + name] = {
                "name": name,
                "cls": "pick",
                "pos": "PICK",
                "rookie": False,
                "v": v,
            }
            continue
        c = by_norm.get(normalize_player_name(name))
        out["name:" + normalize_player_name(name)] = {
            "name": name,
            "cls": c.get("cls") if c else None,
            "pos": c.get("pos") if c else None,
            "rookie": bool(c.get("rookie")) if c else False,
            "v": v,
        }
    return out


def run_vendor_lane(
    boards: dict[date, dict], days: dict[date, Path], starts: list[date], resolver, source: str
) -> dict[str, Any]:
    vb: dict[date, dict] = {}
    needed = set()
    for s in starts:
        needed.add(s)
        for h in HORIZONS:
            e = resolver(s + timedelta(days=h))
            if e:
                needed.add(e)
    # canonical board for classification: same day if rebuilt, else nearest rebuilt
    built = sorted(boards)
    coverage = {}
    for d in sorted(needed):
        if d not in days:
            continue
        nearest = min(built, key=lambda b: abs((b - d).days))
        vb[d] = {"rows": vendor_board(days[d], source, boards[nearest]["rows"])}
        rows = vb[d]["rows"]
        coverage[d.isoformat()] = {
            "rows": len(rows),
            "unclassified": sum(1 for r in rows.values() if r["cls"] is None),
            "picks": sum(1 for r in rows.values() if r["cls"] == "pick"),
        }
    # content-change census between consecutive start dates
    changed = []
    sd = [d for d in sorted(vb)]
    for a, b in zip(sd, sd[1:]):
        ra, rb = vb[a]["rows"], vb[b]["rows"]
        common = set(ra) & set(rb)
        diff = sum(1 for k in common if ra[k]["v"] != rb[k]["v"])
        changed.append(
            {
                "from": a.isoformat(),
                "to": b.isoformat(),
                "common": len(common),
                "valueChanged": diff,
            }
        )
    agg = run_aging(vb, starts, resolver, families=AGG_FAMILIES)
    agg["coverage"] = coverage
    agg["contentChangeBetweenBoards"] = changed
    return agg


# ── lane C: waiver / FA replacement cost ────────────────────────────────


def _league_formats(con: sqlite3.Connection) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for lid, payload, captured in con.execute(
        "select league_id, payload_json, captured_ms from sharp_league_format_captures order by captured_ms"
    ):
        try:
            p = json.loads(payload)
        except (TypeError, ValueError):
            continue
        settings = p.get("settings") or {}
        slots = p.get("roster_positions") or []
        out[lid] = {
            "budget": settings.get("waiver_budget"),
            "idpStarters": sum(
                1
                for s in slots
                if s in ("DL", "LB", "DB", "IDP_FLEX", "DE", "DT", "CB", "S", "ILB", "OLB")
            ),
            "superflex": "SUPER_FLEX" in slots,
            "teams": p.get("total_rosters"),
        }
    return out


def run_waiver_lane(boards: dict[date, dict], ledger: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    league_type = {}
    for lid, sj in con.execute("select league_id, settings_json from leagues"):
        try:
            league_type[lid] = (json.loads(sj or "{}") or {}).get("type")
        except ValueError:
            league_type[lid] = None
    formats = _league_formats(con)
    built = sorted(boards)
    by_sid: dict[date, dict[str, dict]] = {}
    for d in built:
        idx = {}
        for r in boards[d]["rows"].values():
            if r.get("pid") and r.get("cls") != "pick":
                idx[str(r["pid"])] = r
        by_sid[d] = idx
    rows = con.execute(
        "select league_id, tx_type, action, asset_id, ts, faab_bid from asset_movements "
        "where asset_type='player' and tx_type in ('waiver','free_agent')"
    ).fetchall()
    leagues_seen = set()
    stats: dict[tuple, dict] = defaultdict(
        lambda: {
            "adds": 0,
            "faAdds": 0,
            "waiverAdds": 0,
            "waiverZeroBid": 0,
            "waiverPositiveBid": 0,
            "bidPct": [],
            "bidDollars": [],
            "drops": 0,
            "addPlayers": set(),
            "dropPlayers": set(),
            "addsInIdpLeagues": 0,
            "budgetUnknown": 0,
        }
    )
    join = Counter()
    board_used = Counter()
    example_bids: list[tuple] = []
    for lid, tx_type, action, sid, ts, bid in rows:
        if league_type.get(lid) != 2:
            join["skipped_non_dynasty_league"] += 1
            continue
        leagues_seen.add(lid)
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
        nb = min(built, key=lambda b: (abs((b - d).days), b))
        board_used[nb.isoformat()] += 1
        r = by_sid[nb].get(str(sid))
        if r is None:
            # off the canonical board entirely: missing, not zero
            band = "OFF_BOARD"
            pos = "UNKNOWN"
            join["off_board"] += 1
        elif not r["v"]:
            band = "ON_BOARD_UNPRICED"
            pos = r.get("pos") or "UNKNOWN"
            join["on_board_unpriced"] += 1
        else:
            band = BAND_LABELS[band_index(r["v"])]
            pos = r.get("pos") or "UNKNOWN"
            join["priced"] += 1
        group = "ROOKIE" if (r and r.get("rookie")) else pos
        fmt = formats.get(lid) or {}
        for key in ((band, "ALL"), (band, group)):
            st = stats[key]
            if action == "add":
                st["adds"] += 1
                st["addPlayers"].add(sid)
                if fmt.get("idpStarters"):
                    st["addsInIdpLeagues"] += 1
                if tx_type == "free_agent":
                    st["faAdds"] += 1
                else:
                    st["waiverAdds"] += 1
                    b = bid or 0
                    if b > 0:
                        st["waiverPositiveBid"] += 1
                    else:
                        st["waiverZeroBid"] += 1
                    budget = fmt.get("budget")
                    st["bidDollars"].append(b)
                    if isinstance(budget, (int, float)) and budget > 0:
                        st["bidPct"].append(100.0 * b / budget)
                    else:
                        st["budgetUnknown"] += 1
            else:
                st["drops"] += 1
                st["dropPlayers"].add(sid)
        if action == "add" and tx_type == "waiver" and r and r["v"] and (bid or 0) > 0:
            budget = fmt.get("budget")
            if isinstance(budget, (int, float)) and budget > 0:
                example_bids.append((r["v"], 100.0 * bid / budget, r["name"], r.get("pos")))
    # board population per band for rates
    newest = built[-1]
    pop = Counter()
    for r in boards[newest]["rows"].values():
        if r.get("cls") == "pick" or not r["v"]:
            continue
        pop[(BAND_LABELS[band_index(r["v"])], "ALL")] += 1
    out: dict[str, Any] = {}
    order = list(BAND_LABELS) + ["ON_BOARD_UNPRICED", "OFF_BOARD"]
    for (band, group), st in sorted(
        stats.items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1])
    ):
        bids = st["bidPct"]
        adds = st["adds"]
        entry = {
            "adds": adds,
            "distinctPlayersAdded": len(st["addPlayers"]),
            "freeAgentAdds": st["faAdds"],
            "waiverAdds": st["waiverAdds"],
            "waiverZeroBid": st["waiverZeroBid"],
            "waiverPositiveBid": st["waiverPositiveBid"],
            "shareAddsCostingZero": _r((st["faAdds"] + st["waiverZeroBid"]) / adds)
            if adds
            else None,
            "bidPctOfBudget_allWaiverAdds": {
                "n": len(bids),
                "mean": _r(_mean(bids), 3),
                "median": _r(_q(bids, 0.5), 3),
                "p75": _r(_q(bids, 0.75), 3),
                "p90": _r(_q(bids, 0.9), 3),
                "max": _r(max(bids), 3) if bids else None,
            },
            "bidPctOfBudget_positiveOnly": {
                "n": sum(1 for b in bids if b > 0),
                "median": _r(_q([b for b in bids if b > 0], 0.5), 3),
                "p90": _r(_q([b for b in bids if b > 0], 0.9), 3),
            },
            "waiverAddsBudgetUnknown": st["budgetUnknown"],
            "addsInLeaguesStartingIdp": st["addsInIdpLeagues"],
            "drops": st["drops"],
            "distinctPlayersDropped": len(st["dropPlayers"]),
            "dropsPerAdd": _r(st["drops"] / adds, 3) if adds else None,
        }
        if group == "ALL" and (band, "ALL") in pop:
            entry["boardPlayersInBandOnNewestBoard"] = pop[(band, "ALL")]
            entry["distinctAddedPerBoardPlayer"] = _r(len(st["addPlayers"]) / pop[(band, "ALL")], 3)
        out.setdefault(band, {})[group] = entry
    example_bids.sort(key=lambda t: -t[1])
    low = [e for e in example_bids if e[0] < 2000][:15]
    return {
        "label": (
            "Values are from the nearest REBUILT board (sensitivity replay: today's code on "
            "that day's archived inputs), not observed history."
        ),
        "dynastyLeaguesWithMovements": len(leagues_seen),
        "leaguesWithFormatCapture": sum(1 for lid in leagues_seen if lid in formats),
        "leaguesStartingIdp": sum(
            1 for lid in leagues_seen if (formats.get(lid) or {}).get("idpStarters")
        ),
        "leaguesSuperflex": sum(
            1 for lid in leagues_seen if (formats.get(lid) or {}).get("superflex")
        ),
        "movementsByJoinState": dict(join),
        "boardsUsed": dict(sorted(board_used.items())),
        "byBandAndGroup": out,
        "largestBidsOnPlayersValuedUnder2000": [
            {"value": int(v), "bidPctOfBudget": _r(p, 2), "player": n, "pos": pos}
            for v, p, n, pos in low
        ],
    }


# ── lane D: ROS usefulness vs canonical value ───────────────────────────


def _ros_snapshot_for(d: date) -> Path | None:
    files = sorted(ROS_HISTORY_DIR.glob("*.json"))
    best = None
    for f in files:
        try:
            fd = datetime.strptime(f.name[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if fd <= d:
            best = f
    return best


def run_ros_lane(boards: dict[date, dict], dates: list[date]) -> dict[str, Any]:
    from src.utils.name_clean import normalize_player_name, normalize_position  # noqa: PLC0415

    out: dict[str, Any] = {}
    for d in dates:
        snap = _ros_snapshot_for(d)
        if snap is None or d not in boards:
            continue
        ros = json.loads(snap.read_text()).get("players") or []
        ros_idx: dict[tuple, dict] = {}
        for p in ros:
            pos = normalize_position(p.get("position"))
            pos = {"S": "DB", "CB": "DB", "DE": "DL", "DT": "DL"}.get(pos, pos)
            ros_idx.setdefault((normalize_player_name(p.get("canonicalName")), pos), p)
        players = [
            r
            for r in boards[d]["rows"].values()
            if r.get("cls") in ("offense", "idp") and r["v"] and r.get("pos") in VET_POSITIONS
        ]
        joined = []
        for r in players:
            p = ros_idx.get((normalize_player_name(r.get("cname") or r.get("name")), r.get("pos")))
            joined.append((r, p))
        # quantile map: rank joined players by rosValue, give each the canonical
        # value at the same order statistic among the joined population.
        with_ros = [(r, p) for r, p in joined if p and isinstance(p.get("rosValue"), (int, float))]
        canon_sorted = sorted((r["v"] for r, _ in with_ros), reverse=True)
        by_ros = sorted(with_ros, key=lambda t: -t[1]["rosValue"])
        implied = {id(r): canon_sorted[i] for i, (r, _p) in enumerate(by_ros)}
        # same mapping within position (position-relative usefulness)
        implied_pos: dict[int, float] = {}
        for pos in VET_POSITIONS:
            grp = [(r, p) for r, p in with_ros if r["pos"] == pos]
            cs = sorted((r["v"] for r, _ in grp), reverse=True)
            for i, (r, _p) in enumerate(sorted(grp, key=lambda t: -t[1]["rosValue"])):
                implied_pos[id(r)] = cs[i]
        bands: dict[str, Any] = {}
        for fam in ("ALL", "OFFENSE", "IDP", "AGE<=24", "AGE>=25", "ROOKIE"):
            for bi, label in enumerate(BAND_LABELS):
                sel = []
                for r, p in joined:
                    if band_index(r["v"]) != bi:
                        continue
                    age = r.get("age") if isinstance(r.get("age"), (int, float)) else None
                    if fam == "OFFENSE" and r["cls"] != "offense":
                        continue
                    if fam == "IDP" and r["cls"] != "idp":
                        continue
                    if fam == "AGE<=24" and not (age is not None and age <= 24):
                        continue
                    if fam == "AGE>=25" and not (age is not None and age >= 25):
                        continue
                    if fam == "ROOKIE" and not r.get("rookie"):
                        continue
                    sel.append((r, p))
                if not sel:
                    continue
                has = [(r, p) for r, p in sel if p and isinstance(p.get("rosValue"), (int, float))]
                ratios = [r["v"] / implied[id(r)] for r, _ in has if implied.get(id(r))]
                ratios_pos = [r["v"] / implied_pos[id(r)] for r, _ in has if implied_pos.get(id(r))]
                bands.setdefault(fam, {})[label] = {
                    "n": len(sel),
                    "shareWithRosRow": _r(len(has) / len(sel)),
                    "medianRosValue": _r(_q([p["rosValue"] for _, p in has], 0.5), 2),
                    "medianRosPositionRank": _q(
                        [p.get("rosRankPosition") for _, p in has if p.get("rosRankPosition")], 0.5
                    ),
                    "medianCanonOverRosImplied_overall": _r(_q(ratios, 0.5), 3),
                    "medianCanonOverRosImplied_withinPosition": _r(_q(ratios_pos, 0.5), 3),
                    "shareCanonAboveRosImplied_withinPosition": _r(
                        sum(1 for x in ratios_pos if x > 1) / len(ratios_pos)
                    )
                    if ratios_pos
                    else None,
                }
        out[d.isoformat()] = {
            "rosSnapshot": snap.name,
            "canonicalPlayersPriced": len(players),
            "joinedToRos": len(with_ros),
            "rosRows": len(ros),
            "byFamilyAndBand": bands,
        }
    return {
        "label": (
            "Canonical values from REBUILT boards (sensitivity replay). ROS is the seasonal lane "
            "(redraft usefulness), diagnostic only. Players without a ROS row are reported as "
            "missing, never as zero usefulness. 'RosImplied' = canonical value at the same "
            "order statistic as the player's rosValue among joined players (quantile map)."
        ),
        "byDate": out,
    }


# ── headline extraction ─────────────────────────────────────────────────


def _pick_summary(agg: dict, window: str, horizon: int, fam: str, band: str) -> dict | None:
    s = (
        agg["byWindowHorizonFamilyBand"]
        .get(window, {})
        .get(str(horizon), {})
        .get(fam, {})
        .get(band)
    )
    if not s:
        return None
    return {
        "n": s["n"],
        "nDistinct": s.get("nDistinctAssets"),
        "medianLogRatio": s["medianLogRatio"],
        "meanLogRatio": s["meanLogRatio"],
        "shareAbsentOrUnpriced": _r((s["shareAbsentAtEnd"] or 0) + (s["shareUnpricedAtEnd"] or 0)),
        "shareClassRetired": s["shareClassRetiredAtEnd"],
    }


def build_headline(canon: dict, vendor: dict, waiver: dict) -> dict[str, Any]:
    out: dict[str, Any] = {"aging": {}}
    for window, horizon in (("EARLY", 30), ("EARLY", 60), ("EARLY", 90), ("LATE", 30), ("ALL", 30)):
        key = f"{window}_{horizon}d"
        block: dict[str, Any] = {}
        for fam in ("VET_OFFENSE", "VET_IDP", "ROOKIES", "PICKS"):
            for band in ("1000-1500", "1500-2000", "2000-3000", "<3000", ">=3000"):
                row = {"canonical_constantPanel": _pick_summary(canon, window, horizon, fam, band)}
                for src, agg in vendor.items():
                    row[src] = _pick_summary(agg, window, horizon, fam, band)
                block.setdefault(fam, {})[band] = row
        out["aging"][key] = block
    if isinstance(waiver.get("byBandAndGroup"), dict):
        out["waiver"] = {
            band: {
                k: g["ALL"].get(k)
                for k in (
                    "adds",
                    "distinctPlayersAdded",
                    "shareAddsCostingZero",
                    "boardPlayersInBandOnNewestBoard",
                    "distinctAddedPerBoardPlayer",
                    "drops",
                    "dropsPerAdd",
                )
            }
            | {
                "medianBidPctOfBudget": g["ALL"]["bidPctOfBudget_allWaiverAdds"]["median"],
                "p90BidPctOfBudget": g["ALL"]["bidPctOfBudget_allWaiverAdds"]["p90"],
            }
            for band, g in waiver["byBandAndGroup"].items()
            if "ALL" in g
        }
    return out


# ── main ────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--scratch", type=Path, default=None, help="scratch dir (default: a temp dir)"
    )
    parser.add_argument("--csv-history", choices=("auto", "git", "gh"), default="auto")
    parser.add_argument("--first-start", default="2026-07-15")
    parser.add_argument("--step-days", type=int, default=7)
    parser.add_argument(
        "--ledger", type=Path, default=REPO_ROOT / "data" / "intel" / "ledger.sqlite3"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger().setLevel(logging.ERROR)

    t_start = time.time()
    scratch = args.scratch or Path(tempfile.mkdtemp(prefix="lowvalue_dyn_"))
    scratch.mkdir(parents=True, exist_ok=True)
    days = day_archives()
    last_day = max(days)

    def resolver(target: date) -> date | None:
        if target > last_day + timedelta(days=NEAREST_TOLERANCE_DAYS):
            return None
        return resolve_day(target, days)

    starts: list[date] = []
    d = date.fromisoformat(args.first_start)
    while d <= last_day:
        r = resolver(d)
        if r is not None and r not in starts:
            starts.append(r)
        d += timedelta(days=args.step_days)
    needed: set[date] = set(starts)
    for s in starts:
        for h in HORIZONS:
            e = resolver(s + timedelta(days=h))
            if e is not None and e > s:
                needed.add(e)
    needed.add(last_day)
    build_dates = sorted(needed)
    print(f"rebuilding {len(build_dates)} boards (sensitivity replay) ...", flush=True)
    boards, board_meta = build_boards(build_dates, days, scratch, args.csv_history)
    panels = [set(b["votingSources"]) for b in boards.values()]
    common = set.intersection(*panels) if panels else set()
    varying = sorted(set.union(*panels) - common) if panels else []
    print(f"constant panel: {len(common)} sources; excluding {varying}", flush=True)
    cboards, cboard_meta = build_boards(
        build_dates, days, scratch, args.csv_history, exclude_sources=varying, tag="constantPanel"
    )

    print("lane A: canonical aging ...", flush=True)
    lane_a = {
        "constantPanel": run_aging(cboards, starts, resolver),
        "asPublishedPanel": run_aging(boards, starts, resolver, families=AGG_FAMILIES),
    }
    lane_a_lag = {
        "constantPanel": run_aging(cboards, starts, resolver, lagged=True, families=AGG_FAMILIES),
    }
    print("lane B: vendor aging ...", flush=True)
    lane_b = {
        src: run_vendor_lane(boards, days, starts, resolver, src)
        for src in ("ktcSfTep", "idpTradeCalc")
    }
    lane_c: dict[str, Any]
    if args.ledger.exists():
        print("lane C: waiver replacement cost ...", flush=True)
        lane_c = run_waiver_lane(boards, args.ledger)
    else:
        lane_c = {"unavailable": f"ledger not found at {args.ledger}"}
    print("lane D: ROS curve check ...", flush=True)
    ros_dates = [b for b in build_dates if b >= date(2026, 8, 1)]
    ros_pick = (
        sorted({ros_dates[0], ros_dates[len(ros_dates) // 2], ros_dates[-1]}) if ros_dates else []
    )
    lane_d = run_ros_lane(boards, ros_pick)

    head = (
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True)
        .stdout.decode()
        .strip()
    )
    headline = build_headline(lane_a["constantPanel"], lane_b, lane_c)
    result = {
        "schema": "low_value_asset_value_dynamics.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "codeRevision": head,
        "question": (
            "Are low-value assets (canonical rankDerivedValue < ~3000) mis-valued? Value dynamics "
            "and replacement cost, not trades."
        ),
        "labels": {
            "laneA": (
                "SENSITIVITY REPLAY - today's methodology on each day's archived raw payload plus "
                "the source CSVs as committed at that moment; no dataset state supplied, so "
                "freshness weighting is off for every board. NOT observed history."
            ),
            "laneB": "Vendor values read directly from the archives (no rebuild).",
            "missingIsNotZero": (
                "Assets absent from / unpriced on the end board are reported as shares, never "
                "valued at 0; log ratios are over assets priced on both boards."
            ),
        },
        "bands": list(BAND_LABELS),
        "horizonsDays": list(HORIZONS),
        "windows": {
            "EARLY": f"start <= {EARLY_END.isoformat()}",
            "LATE": f"start >= {LATE_START.isoformat()}",
            "ALL": "every start",
        },
        "caveats": [
            "Lane A boards are SENSITIVITY REPLAYS (today's code on past inputs), not observed history.",
            "Today's code votes KTC only through the ktcCrowdSfTep / ktcTradesSfTep CSVs, which the "
            "window's early CSV trees do not contain: replay boards before the split carry NO KTC "
            "vote. The constant panel therefore excludes KTC on every board.",
            "Freshness weighting is off on every replay board (no dataset state is reconstructed).",
            "Start dates are weekly, so pairs overlap: per-band n counts asset-start pairs, not "
            "independent observations (nDistinctAssets is reported beside n).",
            "The '<500' canonical band is dominated by floor-valued rows (single-source, deep "
            "tail); its large mean log ratios are floor exits, not market moves.",
            "Vendor lanes band each asset on the VENDOR's own 0-9999 value, not the canonical "
            "value; positions/rookie flags are borrowed from the nearest canonical board by name.",
            "KTC publishes its top ~500 rows only; 'absent' in the KTC lane is falling off KTC's "
            "board, not KTC pricing the player at zero. IDPTC content changes on few days.",
            "Lane C: 412 dynasty leagues, mostly superflex, few start IDP, so IDP replacement "
            "evidence is thin. Bids are % of each league's own waiver budget.",
            "Lane D quantile map is rank-preserving: it tests ORDER (is a band ranked above its ROS "
            "usefulness), not curve SHAPE; rosValue is a rank score, not points.",
        ],
        "headline": headline,
        "startDates": [s.isoformat() for s in starts],
        "nearestDayToleranceDays": NEAREST_TOLERANCE_DAYS,
        "boards": board_meta,
        "constantPanel": {
            "note": (
                "Sources voting on EVERY rebuilt board; the rest (sources the window's early "
                "CSV trees do not contain, incl. the KTC Crowd/Trades split) are disabled via "
                "source_overrides so value change is not a panel-composition artifact. The "
                "as-published panel is reported beside it."
            ),
            "sources": sorted(common),
            "excluded": varying,
            "boards": cboard_meta["boards"],
        },
        "laneA_canonicalAging": lane_a,
        "laneA_canonicalAging_laggedBanding": {
            "note": (
                "Band assigned by value 7 days BEFORE the start (instrument against "
                "regression-to-the-mean from banding on a noisy start value); outcome is still "
                "log(V_end / V_start)."
            ),
            **lane_a_lag,
        },
        "laneB_vendorAging": lane_b,
        "laneC_waiverReplacementCost": lane_c,
        "laneD_rosCurveCheck": lane_d,
        "runtimeSeconds": round(time.time() - t_start, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # one top-level key per line, compact inside: the lane blocks are large
    lines = [f" {json.dumps(k)}: {json.dumps(v, separators=(',', ':'))}" for k, v in result.items()]
    args.out.write_text("{\n" + ",\n".join(lines) + "\n}\n")
    print(f"wrote {args.out} in {result['runtimeSeconds']} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
