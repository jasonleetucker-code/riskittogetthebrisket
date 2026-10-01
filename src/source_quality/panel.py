"""Point-in-time observation panel: what each source PUBLISHED, and when we knew it.

The unit of evidence is one *version* of a source's own published board, stamped
with ``known_at`` -- the instant the repository recorded it (the git committer
time of the CSV change, or a temporal-ledger observation instant).  A version is
selectable for a question asked at time ``t`` only when ``known_at <= t``; there
is no API that returns a later version, and :meth:`ObservationPanel.truncated`
removes every later version outright so a learner handed a truncated panel
cannot see the future even by accident.

Nothing here rebuilds a board.  Observations are parsed from the CSV bytes as
they were committed: today's Hill curve and today's pipeline never touch them.
TODAY's name normalizer DOES: :func:`parse_csv` keys every historical row with
the current ``resolve_canonical_name``, so an alias added to the name registry
after a version was published is applied to that version retroactively -- a
mild identity look-ahead.  The 2026-10-01 preregistration names this key in §3
"Identity", but its "Never reconstructed" bullet ("no archived board is rebuilt
with today's ... identity resolver") reads as if it were not applied; the
run's report corrects that in its post-hoc notes.  It changes which rows JOIN across sources (and can create a
duplicate key, which is then withheld and counted), never a vendor's published
order -- but it is not strictly as-of.  Two unavoidable choices are disclosed:

* **identity** -- rows are joined across sources by the deterministic
  (current) ``resolve_canonical_name`` key (no fuzzy matching) plus a universe
  (OFFENSE / IDP / PICK).  A source covering several universes without a
  position column (the IDP Trade Calculator) is classified per date by
  co-observation in single-universe sources AS OF THE SAME DATE; a name seen in
  both universes is AMBIGUOUS and withheld; a name seen in neither is
  UNCLASSIFIED and withheld.  Both are counted, never guessed.
* **scale** -- each version is reduced to the rank of each row within its
  universe (ties averaged), and evidence is compared as ``-log(rank)``.  Ranks
  agree across boards of different depth for every row both boards cover, so no
  curve is needed.  Rookie-only boards are NOT on that scale (rookie #1 is not
  overall #1); they are parsed but contribute no evidence in this version and
  are reported as such.

Commit time is an UPPER bound on when the observation existed: committing later
than the fetch only delays it, which is conservative.  A commit that rewrites a
CSV records what was known at that commit, not earlier.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = "CSVs/site_raw"

OFFENSE, IDP, PICK = "OFFENSE", "IDP", "PICK"
UNIVERSES: tuple[str, ...] = (OFFENSE, IDP, PICK)

_NAME_COLUMNS = ("name", "Name", "Player", "player")
_RANK_COLUMNS = ("rank", "Rank", "effectiveRank")
_VALUE_COLUMNS = ("value", "Value", "boone_value", "3D Value +", "normalizedValue")
_POSITION_COLUMNS = ("position", "Pos", "pos", "Fantasy Position")


@dataclass(frozen=True)
class SourceSpec:
    """One evaluable source: its file, how its order is published, its family."""

    key: str
    family: str
    csv_file: str
    signal: str  # "rank" (lower is better) | "value" (higher is better)
    universes: frozenset[str]
    rookie_only: bool = False
    cadence_hours: float | None = None

    @property
    def single_universe(self) -> str | None:
        players = self.universes - {PICK}
        return next(iter(players)) if len(players) == 1 else None


@dataclass(frozen=True)
class Row:
    name: str  # canonical name key
    order: float  # sort key; smaller is better
    position_group: str | None
    is_pick: bool


@dataclass(frozen=True)
class Version:
    source: str
    known_at: datetime  # tz-aware UTC
    origin: str  # "git:<sha>" | "ledger"
    rows: tuple[Row, ...]
    parse: Mapping[str, int] = field(default_factory=dict)
    content_hash: str = ""


# ── eligibility ──────────────────────────────────────────────────────────


def load_census(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def eligible_specs(
    census: Mapping[str, Any],
    registry: Sequence[Mapping[str, Any]],
    csv_paths: Mapping[str, Any],
) -> tuple[list[SourceSpec], dict[str, str]]:
    """Sources the census says may be evaluated, plus why every other one may not.

    Eligible means: VOTING, game type verified DYNASTY (unverified fails closed),
    and the census's out-of-sample data prerequisites met.  The census is the
    single owner of those three facts; nothing is re-derived here.
    """
    reg = {str(s.get("key")): s for s in registry if s.get("key")}
    specs: list[SourceSpec] = []
    excluded: dict[str, str] = {}
    for entry in census.get("sources") or []:
        key = str(entry.get("key"))
        oos = (entry.get("outOfSampleEvaluation") or {}).get("state")
        if entry.get("votingStatus") != "VOTING":
            excluded[key] = f"not_voting:{entry.get('nonVotingClass')}"
            continue
        if entry.get("gameType") != "DYNASTY":
            excluded[key] = f"game_type_not_verified_dynasty:{entry.get('gameType')}"
            continue
        if oos != "DATA_PREREQUISITES_MET":
            excluded[key] = (
                f"oos_blocked:{','.join((entry.get('outOfSampleEvaluation') or {}).get('blockers') or [])}"
            )
            continue
        cfg = csv_paths.get(key)
        if cfg is None:
            excluded[key] = "no_registered_csv"
            continue
        path = cfg["path"] if isinstance(cfg, dict) else str(cfg)
        signal = (cfg.get("signal") if isinstance(cfg, dict) else None) or "value"
        pop = entry.get("population") or {}
        universes = {
            u for u, flag in ((OFFENSE, "offense"), (IDP, "idp"), (PICK, "picks")) if pop.get(flag)
        }
        r = reg.get(key) or {}
        specs.append(
            SourceSpec(
                key=key,
                family=str((entry.get("family") or {}).get("correlationGroup") or key),
                csv_file=Path(path).name,
                signal="rank" if signal == "rank" else "value",
                universes=frozenset(universes),
                rookie_only=bool(r.get("needs_rookie_translation")),
                cadence_hours=(entry.get("freshness") or {}).get("expectedCadenceHours"),
            )
        )
    return sorted(specs, key=lambda s: s.key), excluded


# ── parsing (as published) ───────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def parse_csv(text: str, spec: SourceSpec) -> tuple[list[Row], dict[str, int]]:
    """Rows of one committed CSV version, ordered as the vendor published them."""
    from src.identity.picks import is_pick_name
    from src.utils.name_clean import canonical_position_group, resolve_canonical_name

    stats = {"rows": 0, "noName": 0, "noOrder": 0, "kept": 0}
    reader = csv.DictReader(io.StringIO(text))
    cols = list(reader.fieldnames or [])
    ncol = next((c for c in _NAME_COLUMNS if c in cols), None)
    rcol = next((c for c in _RANK_COLUMNS if c in cols), None)
    vcol = next((c for c in _VALUE_COLUMNS if c in cols), None)
    pcol = next((c for c in _POSITION_COLUMNS if c in cols), None)
    # The registry's signal decides which column carries the published order;
    # an old version missing that column falls back to the other one (counted).
    use_rank = (spec.signal == "rank" and rcol is not None) or (vcol is None and rcol is not None)
    if ncol is None or (rcol is None and vcol is None):
        stats["schemaUnreadable"] = 1
        return [], stats
    if (spec.signal == "rank") != use_rank:
        stats["signalColumnFallback"] = 1
    out: list[Row] = []
    for raw in reader:
        stats["rows"] += 1
        name = str(raw.get(ncol) or "").strip()
        if not name:
            stats["noName"] += 1
            continue
        x = _num(raw.get(rcol if use_rank else vcol))
        if x is None:
            stats["noOrder"] += 1
            continue
        pick = bool(is_pick_name(name))
        key = " ".join(name.split()) if pick else resolve_canonical_name(name)
        if not key:
            stats["noName"] += 1
            continue
        group = None
        pos = str(raw.get(pcol) or "").strip() if pcol else ""
        if pos and not pick:
            g = canonical_position_group(pos)
            if g not in (OFFENSE, IDP):
                # A stated non-fantasy position (K, DST, ...) is not a player in
                # any evaluated universe; never defaulted into one.
                stats["nonFantasyPosition"] = stats.get("nonFantasyPosition", 0) + 1
                continue
            group = g
        out.append(Row(key, x if use_rank else -x, group, pick))
    stats["kept"] = len(out)
    return out, stats


def _hash_rows(rows: Iterable[Row]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r.name}|{r.order}|{r.position_group}|{int(r.is_pick)}\n".encode())
    return h.hexdigest()


# ── git history ──────────────────────────────────────────────────────────


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    out = subprocess.run(
        ["git", "-C", str(root), *args], input=stdin, capture_output=True, timeout=600
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {out.stderr.decode(errors='replace')[:400]}"
        )
    return out.stdout


def _utc(stamp: str) -> datetime:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)


def git_csv_commits(root: Path, files: Iterable[str]) -> dict[str, list[tuple[datetime, str]]]:
    """``{csv file: [(committer time UTC, sha), ...] ascending}`` from ONE git log."""
    wanted = set(files)
    text = _git(root, "log", "--format=@%H %cI", "--name-only", "--", CSV_DIR).decode()
    out: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    sha, when = None, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("@"):
            sha, stamp = line[1:].split(" ", 1)
            when = _utc(stamp)
        elif line and sha and when:
            name = Path(line).name
            if name in wanted and Path(line).parent.as_posix() == CSV_DIR:
                out[name].append((when, sha))
    return {k: sorted(v) for k, v in out.items()}


def last_commit_per_day(commits: Sequence[tuple[datetime, str]]) -> list[tuple[datetime, str]]:
    """Keep the LAST version recorded on each UTC day.

    Lossless for a daily as-of grid: the answer at the end of day D is the last
    version recorded at or before that instant, which is the last one of the
    latest day <= D.
    """
    by_day: dict[date, tuple[datetime, str]] = {}
    for when, sha in commits:
        cur = by_day.get(when.date())
        if cur is None or when >= cur[0]:
            by_day[when.date()] = (when, sha)
    return [by_day[d] for d in sorted(by_day)]


def read_blobs(root: Path, specs: Sequence[tuple[str, str]]) -> list[bytes | None]:
    """``git cat-file --batch`` for ``[(sha, path), ...]`` in one process."""
    if not specs:
        return []
    req = "".join(f"{sha}:{path}\n" for sha, path in specs).encode()
    raw = _git(root, "cat-file", "--batch", stdin=req)
    out: list[bytes | None] = []
    i = 0
    for _ in specs:
        nl = raw.index(b"\n", i)
        header = raw[i:nl].split()
        i = nl + 1
        if len(header) == 2 and header[1] == b"missing":
            out.append(None)
            continue
        size = int(header[2])
        out.append(raw[i : i + size])
        i += size + 1
    return out


def versions_from_git(root: Path, specs: Sequence[SourceSpec]) -> dict[str, list[Version]]:
    commits = git_csv_commits(root, (s.csv_file for s in specs))
    plan: list[tuple[SourceSpec, datetime, str]] = []
    for spec in specs:
        for when, sha in last_commit_per_day(commits.get(spec.csv_file, [])):
            plan.append((spec, when, sha))
    blobs = read_blobs(root, [(sha, f"{CSV_DIR}/{s.csv_file}") for s, _w, sha in plan])
    out: dict[str, list[Version]] = defaultdict(list)
    for (spec, when, sha), blob in zip(plan, blobs):
        if blob is None:
            continue
        rows, stats = parse_csv(blob.decode("utf-8", errors="replace"), spec)
        out[spec.key].append(
            Version(spec.key, when, f"git:{sha[:12]}", tuple(rows), stats, _hash_rows(rows))
        )
    return {k: _dedupe(v) for k, v in out.items()}


def _dedupe(versions: list[Version]) -> list[Version]:
    """Ascending by known_at; a version whose content repeats its predecessor adds
    nothing (its information was already known) and is dropped."""
    out: list[Version] = []
    for v in sorted(versions, key=lambda v: v.known_at):
        if out and out[-1].content_hash == v.content_hash:
            continue
        out.append(v)
    return out


# ── optional temporal ledger (production box) ────────────────────────────


def versions_from_ledger(path: Path, specs: Sequence[SourceSpec]) -> dict[str, list[Version]]:
    """Read the ``source_value`` lane of the temporal ledger, read-only.

    A row with a known ``observed_at`` is known at that instant; a row with only
    a date is known at the END of that date (an unknown same-day instant is
    conservatively late -- the ``value_known_before`` rule).
    """
    from src.identity.picks import is_pick_name
    from src.utils.name_clean import canonical_position_group, resolve_canonical_name

    keys = {s.key for s in specs}
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT source_key, observed_date, observed_at, display_name, position, value "
            "FROM observations WHERE lane = 'source_value' AND value IS NOT NULL"
        )
        grouped: dict[tuple[str, datetime], list[Row]] = defaultdict(list)
        for skey, odate, oat, name, pos, value in cur:
            if skey not in keys or not name:
                continue
            when = (
                _utc(oat)
                if oat
                else datetime.combine(
                    date.fromisoformat(odate), time(23, 59, 59), tzinfo=timezone.utc
                )
            )
            pick = bool(is_pick_name(str(name)))
            g = canonical_position_group(str(pos or "")) if pos and not pick else None
            grouped[(skey, when)].append(
                Row(
                    " ".join(str(name).split()) if pick else resolve_canonical_name(str(name)),
                    -float(value),
                    g if g in (OFFENSE, IDP) else None,
                    pick,
                )
            )
    finally:
        conn.close()
    out: dict[str, list[Version]] = defaultdict(list)
    for (skey, when), rows in grouped.items():
        rows.sort(key=lambda r: (r.order, r.name))
        out[skey].append(
            Version(skey, when, "ledger", tuple(rows), {"kept": len(rows)}, _hash_rows(rows))
        )
    return {k: _dedupe(v) for k, v in out.items()}


# ── the panel ────────────────────────────────────────────────────────────


def day_end(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


class ObservationPanel:
    """Versions per source with a strictly-past as-of selector."""

    def __init__(self, specs: Sequence[SourceSpec], versions: Mapping[str, Sequence[Version]]):
        self.specs = {s.key: s for s in specs}
        self.versions: dict[str, list[Version]] = {
            k: sorted(v, key=lambda x: x.known_at) for k, v in versions.items() if k in self.specs
        }
        for k, vs in self.versions.items():
            for v in vs:
                if v.known_at.tzinfo is None:
                    raise ValueError(f"{k}: naive known_at")

    def as_of(self, source: str, t: datetime) -> Version | None:
        """Latest version with ``known_at <= t``; never a later one."""
        if t.tzinfo is None:
            raise ValueError("as_of needs a tz-aware instant")
        best = None
        for v in self.versions.get(source, ()):
            if v.known_at <= t:
                best = v
            else:
                break
        return best

    def truncated(self, cutoff: datetime) -> ObservationPanel:
        """A panel holding ONLY versions known at or before ``cutoff``."""
        return ObservationPanel(
            list(self.specs.values()),
            {k: [v for v in vs if v.known_at <= cutoff] for k, vs in self.versions.items()},
        )

    def span(self) -> tuple[date, date] | None:
        stamps = [v.known_at.date() for vs in self.versions.values() for v in vs]
        return (min(stamps), max(stamps)) if stamps else None

    def families(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for s in self.specs.values():
            out[s.family].append(s.key)
        return {f: sorted(m) for f, m in sorted(out.items())}


def _rank_within(rows: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Average ranks (1 = best) for ``[(key, order)]``, smaller order better."""
    ordered = sorted(rows, key=lambda r: r[1])
    out: dict[str, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[ordered[k][0]] = avg
        i = j + 1
    return out


@dataclass
class Matrix:
    """Dense daily panel: ``obs[source]`` is (assets x dates) of ``-log(rank)``."""

    assets: list[str]
    universe: np.ndarray  # (A,) of str
    dates: list[date]
    obs: dict[str, np.ndarray]
    age_days: dict[str, np.ndarray]  # (D,) age of the as-of version, NaN if none
    rookie: np.ndarray  # (A, D) bool: on a rookie-only board as of that date
    identity: dict[str, dict[str, int]]
    specs: dict[str, SourceSpec]

    def family_members(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for k, s in self.specs.items():
            if k in self.obs and not s.rookie_only:
                out[s.family].append(k)
        return {f: sorted(m) for f, m in sorted(out.items())}

    def family_matrix(self) -> dict[str, np.ndarray]:
        """One score per (asset, date) per FAMILY: the mean of its members present.

        A family is one piece of evidence however many products it publishes;
        averaging (never summing) its members is what keeps correlated products
        from multiplying its say.
        """
        out = {}
        for fam, members in self.family_members().items():
            stack = np.stack([self.obs[m] for m in members])
            with np.errstate(invalid="ignore"), _quiet():
                out[fam] = np.nanmean(stack, axis=0)
        return out


class _quiet:
    def __enter__(self):
        import warnings

        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore", category=RuntimeWarning)

    def __exit__(self, *exc):
        self._w.__exit__(*exc)


def build_matrix(panel: ObservationPanel, dates: Sequence[date]) -> Matrix:
    """Daily as-of snapshots -> dense matrix.  Every cell uses ``as_of(day_end(d))``."""
    specs = panel.specs
    single = {k: s.single_universe for k, s in specs.items()}
    per_day: list[dict[str, dict[str, float]]] = []
    ages: dict[str, list[float]] = {k: [] for k in specs}
    rookie_names: list[set[str]] = []
    identity: dict[str, dict[str, int]] = {k: defaultdict(int) for k in specs}  # type: ignore[assignment]
    cache: dict[tuple[str, str], dict[str, float]] = {}
    for d in dates:
        t = day_end(d)
        current = {k: panel.as_of(k, t) for k in specs}
        for k, v in current.items():
            ages[k].append((t - v.known_at).total_seconds() / 86400 if v else float("nan"))
        # Names each single-universe source places in each universe AS OF t.
        seen: dict[str, set[str]] = {OFFENSE: set(), IDP: set()}
        for k, v in current.items():
            u = single[k]
            if v is None or u is None:
                continue
            for r in v.rows:
                if not r.is_pick:
                    seen[r.position_group or u].add(r.name)
        rookies = {r.name for k, v in current.items() if v and specs[k].rookie_only for r in v.rows}
        rookie_names.append(rookies)
        snap: dict[str, dict[str, float]] = {}
        for k, v in current.items():
            if v is None:
                continue
            ck = (k, v.content_hash)
            if single[k] is not None and ck in cache:
                snap[k] = cache[ck]
                continue
            buckets: dict[str, list[tuple[str, float]]] = defaultdict(list)
            counts: dict[str, int] = defaultdict(int)
            for r in v.rows:
                if r.is_pick:
                    if PICK in specs[k].universes:
                        buckets[PICK].append((r.name, r.order))
                    continue
                u = r.position_group or single[k]
                if u is None:  # multi-universe source without a position column
                    in_o, in_i = r.name in seen[OFFENSE], r.name in seen[IDP]
                    if in_o and in_i:
                        counts["ambiguousUniverse"] += 1
                        continue
                    if not (in_o or in_i):
                        counts["unclassifiedUniverse"] += 1
                        continue
                    u = OFFENSE if in_o else IDP
                if u not in specs[k].universes:
                    counts["outOfPopulation"] += 1
                    continue
                buckets[u].append((r.name, r.order))
            ranks: dict[str, float] = {}
            for u, rows in buckets.items():
                names = [n for n, _ in rows]
                dup = (
                    {n for n in names if names.count(n) > 1}
                    if len(names) != len(set(names))
                    else set()
                )
                if dup:
                    counts["duplicateKey"] += len([n for n in names if n in dup])
                clean = [(n, o) for n, o in rows if n not in dup]
                for n, rank in _rank_within(clean).items():
                    ranks[f"{n}::{u}"] = rank
            if single[k] is not None:
                cache[ck] = ranks
                if counts:
                    for c, n in counts.items():
                        identity[k][c] = max(identity[k][c], n)
            else:
                for c, n in counts.items():
                    identity[k][c] = max(identity[k][c], n)
            snap[k] = ranks
        per_day.append(snap)
    assets = sorted({a for snap in per_day for ranks in snap.values() for a in ranks})
    index = {a: i for i, a in enumerate(assets)}
    A, D = len(assets), len(dates)
    obs: dict[str, np.ndarray] = {}
    for k in specs:
        arr = np.full((A, D), np.nan, dtype=np.float64)
        for j, snap in enumerate(per_day):
            ranks = snap.get(k)
            if not ranks:
                continue
            idx = np.fromiter((index[a] for a in ranks), dtype=np.int64, count=len(ranks))
            arr[idx, j] = -np.log(np.fromiter(ranks.values(), dtype=np.float64, count=len(ranks)))
        if np.isfinite(arr).any():
            obs[k] = arr
    rookie = np.zeros((A, D), dtype=bool)
    for j, names in enumerate(rookie_names):
        for a, i in index.items():
            if a.endswith(f"::{OFFENSE}") or a.endswith(f"::{IDP}"):
                if a.rsplit("::", 1)[0] in names:
                    rookie[i, j] = True
    universe = np.array([a.rsplit("::", 1)[1] for a in assets])
    return Matrix(
        assets=assets,
        universe=universe,
        dates=list(dates),
        obs=obs,
        age_days={k: np.array(v) for k, v in ages.items()},
        rookie=rookie,
        identity={k: dict(v) for k, v in identity.items()},
        specs=dict(specs),
    )


def daily_grid(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def readiness(panel: ObservationPanel) -> dict[str, Any]:
    """Data-readiness facts (exploratory, disclosed): versions and span per source."""
    out = {}
    for k, s in sorted(panel.specs.items()):
        vs = panel.versions.get(k, [])
        days = sorted({v.known_at.date() for v in vs})
        out[k] = {
            "family": s.family,
            "universes": sorted(s.universes),
            "rookieOnly": s.rookie_only,
            "distinctVersions": len(vs),
            "first": days[0].isoformat() if days else None,
            "last": days[-1].isoformat() if days else None,
            "medianRows": int(np.median([len(v.rows) for v in vs])) if vs else 0,
            "unreadableVersions": sum(1 for v in vs if v.parse.get("schemaUnreadable")),
        }
    return out
