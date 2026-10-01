"""Signals Fantasy public dynasty boards — collection, store, second opinion.

One owner for everything Signals (#1555, Unit A).  The fetcher
``scripts/fetch_signals.py`` is a thin CLI over :func:`collect_board`; the
authenticated endpoint ``GET /api/second-opinion/signals`` is a thin wrapper
over :func:`build_second_opinion_payload`.

WHAT THIS IS
------------
Signals publishes two public, statically prerendered dynasty boards:

* ``/rankings/dynasty``      — QB / RB / WR / TE, 200 each (2026-10-01)
* ``/rankings/idp-dynasty``  — true defensive positions CB / S / DT / DE / LB

Each row is a POSITIONAL ordinal rank inside a tier band (S+ … F), plus a
"MKT QB4" badge giving Signals' own read of the market's positional rank.
There is **no value scale and no cross-position ordering** on these pages.

WHAT THIS IS NOT — load-bearing
-------------------------------
* NOT a voting source.  Nothing here is registered in ``_RANKING_SOURCES``,
  the game-type gate, the blend, confidence or any canonical field.  The
  only consumer is the Second Opinions surface, as a rank-only, non-voting
  row (``votes: False``).
* NOT a price.  A positional ordinal is never converted to a value, and
  QB3 and RB3 are never placed on one ladder — that would manufacture a
  cross-position ranking Signals did not publish.
* NOT league-adjusted.  The public board is a general board; Superflex /
  TE-premium / scoring are not stated, so they are recorded as unknown.

Evidence rules (MISSING IS NEVER ZERO, STALE IS NOT CURRENT)
------------------------------------------------------------
* A field the page does not carry is ``None`` — never guessed.
* A 304, an unchanged ETag, or an identical normalized content hash
  creates NO release and moves NO information clock.  Fetch time is
  recorded on the fetch clock only.
* Schema drift (missing section, unparseable rank, badge disagreeing with
  its section, declared section count disagreeing with the rows, row-count
  collapse against the last good release, unverified game type)
  QUARANTINES the release; the last good release keeps its real age.
* 401/403 stops collection and persists the stop; later runs refuse until
  an operator clears it (no retry loops).  429 honours ``Retry-After``.
* Publication is atomic per file (temp + rename); one board's failure
  never marks another board ok.

Storage (box-local, gitignored — ``data/`` is ignored repo-wide and no
workflow or push script force-adds ``data/sources/``)::

    data/sources/signals/<board>/raw/<rawSha256>.html.gz
    data/sources/signals/<board>/releases/<contentSha256>.json
    data/sources/signals/<board>/quarantine/<rawSha256>.json
    data/sources/signals/<board>/latest.json          last good release
    data/sources/signals/<board>/fetch_state.json     fetch clock + validators
    data/sources/signals/<board>/dataset_state.json   src.sources.dataset_state
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PROVIDER = "signalsFantasy"
PARSER_VERSION = "signals-html-v1"
SCHEMA_VERSION = 1
BASIS_POSITIONAL_RANK_ONLY = "POSITIONAL_RANK_ONLY"

USER_AGENT = (
    "ChaseUpsideCollector/1.0 (private dynasty analysis tool; "
    "owner-authorized read-only public board collection)"
)
HTTP_TIMEOUT_SECONDS = 60
#: Longest ``Retry-After`` we will honour before giving up for this run.
MAX_RETRY_AFTER_SECONDS = 300
#: Backoff before retrying a transient (network / 5xx) failure.
TRANSIENT_BACKOFF_SECONDS: tuple[float, ...] = (5.0, 20.0)
#: A release whose row count falls below this fraction of the last good
#: release is a collapse, not a publication.  Same fraction as
#: ``dataset_integrity.ROW_COLLAPSE_FRACTION``.
ROW_COLLAPSE_FRACTION = 0.5

_RANK_BADGE_RE = re.compile(r"^([A-Z]+)(\d+)$")
_MARKET_RE = re.compile(r"^MKT\s+([A-Z]+)(\d+)$")
_DECLARED_COUNT_RE = re.compile(r"^(\d+)\s+players?$")
_MARKET_THROUGH_RE = re.compile(r"^Market data through\s+(\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class BoardSpec:
    key: str
    source_key: str
    url: str
    route: str
    positions: tuple[str, ...]
    #: Exact heading text that proves the page is the DYNASTY board.
    heading: str
    population: str


BOARDS: dict[str, BoardSpec] = {
    "dynasty": BoardSpec(
        key="dynasty",
        source_key="signalsDynasty",
        url="https://signalsfantasy.com/rankings/dynasty",
        route="/rankings/dynasty",
        positions=("QB", "RB", "WR", "TE"),
        heading="// DYNASTY RANKINGS",
        population="offense: QB/RB/WR/TE, ranked within position only",
    ),
    "idp-dynasty": BoardSpec(
        key="idp-dynasty",
        source_key="signalsIdpDynasty",
        url="https://signalsfantasy.com/rankings/idp-dynasty",
        route="/rankings/idp-dynasty",
        positions=("CB", "S", "DT", "DE", "LB"),
        heading="// IDP DYNASTY RANKINGS",
        population="IDP: true positions CB/S/DT/DE/LB, ranked within position only",
    ),
}


def dataset_metadata(spec: BoardSpec) -> dict[str, Any]:
    """Declared, per-board dataset contract.  Static; the per-release
    evidence (heading, route) is re-verified on every parse."""
    return {
        "provider": PROVIDER,
        "family": PROVIDER,
        "sourceKey": spec.source_key,
        "board": spec.key,
        "url": spec.url,
        "gameType": "DYNASTY",
        "gameTypeEvidence": (
            f"route {spec.route} and page heading {spec.heading!r}, "
            "re-verified on every release; a release failing either is quarantined"
        ),
        "format": {
            "leagueAdjusted": False,
            "board": "public general board",
            "superflex": None,
            "tePremium": None,
            "scoring": None,
            "note": "QB format, TE premium and scoring are not stated on the public page",
        },
        "population": spec.population,
        "crossPositionOrdering": False,
        "horizon": "dynasty",
        "unit": "positional_ordinal_rank+tier",
        "valueScale": None,
        "basis": BASIS_POSITIONAL_RANK_ONLY,
        "intendedConsumer": "second_opinion_only",
        "votes": False,
        "visibility": "authenticated_only",
        "lineage": (
            "Signals says it aggregates unnamed community dynasty value markets and "
            "trade-implied values; treat as correlated with the KTC / FantasyCalc / "
            "Dynasty Daddy families until ancestry is disclosed"
        ),
    }


# ── Time helpers ──────────────────────────────────────────────────────────


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _http_date(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── HTML parser ───────────────────────────────────────────────────────────


@dataclass
class ParsedPage:
    title: str | None = None
    heading: str | None = None
    published_at: str | None = None
    market_data_through: str | None = None
    cadence_claim: str | None = None
    prerendered_at_ms: int | None = None
    nuxt_path: str | None = None
    declared_counts: dict[str, int] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_errors: list[str] = field(default_factory=list)


def _classes(attrs: Sequence[tuple[str, str | None]]) -> list[str]:
    for k, v in attrs:
        if k == "class" and v:
            return v.split()
    return []


def _attr(attrs: Sequence[tuple[str, str | None]], name: str) -> str | None:
    for k, v in attrs:
        if k == name:
            return v
    return None


class _SignalsHTMLParser(HTMLParser):
    """Deterministic, stdlib-only reader of the prerendered board markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = ParsedPage()
        self._svg_depth = 0
        # (tag, field) per open capturing element; endtags pop to their tag
        # so a stray unclosed element cannot misattribute later text.
        self._capture: list[tuple[str, str | None]] = []
        self._buf: dict[str, list[str]] = {}
        self._position: str | None = None
        self._in_position_header = False
        self._tier_class: str | None = None
        self._tier_label: str | None = None
        self._row: dict[str, Any] | None = None
        self._row_index = 0
        self._in_release_card = False
        self._in_title = False
        self._in_nuxt = False
        self._nuxt_chunks: list[str] = []

    # -- capture plumbing ------------------------------------------------
    def _open(self, tag: str, name: str | None) -> None:
        self._capture.append((tag, name))
        if name is not None:
            self._buf[name] = []

    def _close(self, tag: str) -> str | None:
        for i in range(len(self._capture) - 1, -1, -1):
            if self._capture[i][0] == tag:
                name = self._capture[i][1]
                del self._capture[i:]
                return name
        return None

    def _text_of(self, name: str) -> str:
        return " ".join("".join(self._buf.pop(name, [])).split())

    # -- tags -------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "svg":
            self._svg_depth += 1
            return
        if self._svg_depth:
            return
        cls = _classes(attrs)
        if tag == "title":
            self._in_title = True
            self._buf["title"] = []
        elif tag == "script" and _attr(attrs, "id") == "__NUXT_DATA__":
            self._in_nuxt = True
        elif tag == "aside" and "release-card" in cls:
            self._in_release_card = True
        elif tag == "time" and self._in_release_card:
            self.page.published_at = _attr(attrs, "datetime") or None
        elif tag == "header" and "position-header" in cls:
            self._in_position_header = True
        elif tag == "h2":
            hid = _attr(attrs, "id") or ""
            self._open(tag, "h2:" + hid if hid.startswith("position-") else None)
        elif tag == "h3":
            self._open(tag, "tier" if "tier-break" in cls else None)
        elif tag == "p":
            self._open(tag, "eyebrow" if "eyebrow" in cls and self.page.heading is None else None)
        elif tag == "section" and "tier-group" in cls:
            self._tier_class = next(
                (c for c in cls if c.startswith("tier-") and c != "tier-group"), None
            )
            self._tier_label = None
        elif tag == "li" and "player-row" in cls:
            self._row = {
                "documentIndex": self._row_index,
                "position": self._position,
                "tierClass": self._tier_class,
                "tier": self._tier_label,
                "rank_text": None,
                "name": None,
                "team": None,
                "badge": None,
                "market_text": None,
                "market_title": None,
                "market_classes": None,
            }
            self._row_index += 1
        elif tag == "strong":
            self._open(tag, "name" if self._row is not None else None)
        elif tag == "span":
            name: str | None = None
            if self._row is not None:
                if "rank" in cls:
                    name = "rank_text"
                elif "team-chip" in cls:
                    name = "team"
                elif "rank-badge" in cls:
                    name = "badge"
                elif "market" in cls:
                    name = "market_text"
                    self._row["market_title"] = _attr(attrs, "title")
                    self._row["market_classes"] = cls
            elif self._in_position_header:
                name = "declared"
            elif self._in_release_card:
                name = "release_span"
            self._open(tag, name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
            return
        if self._svg_depth:
            return
        if tag == "title" and self._in_title:
            self._in_title = False
            self.page.title = self._text_of("title") or None
        elif tag == "script" and self._in_nuxt:
            self._in_nuxt = False
            self._read_nuxt("".join(self._nuxt_chunks))
        elif tag == "aside":
            self._in_release_card = False
        elif tag == "header":
            self._in_position_header = False
        elif tag in ("h2", "h3", "p", "strong", "span"):
            name = self._close(tag)
            if name is None:
                return
            text = self._text_of(name)
            if name.startswith("h2:"):
                self._position = text or None
                if text:
                    self.page.sections.append(text)
            elif name == "tier":
                self._tier_label = re.sub(r"\s+Tier$", "", text) or None
            elif name == "eyebrow":
                self.page.heading = text or None
            elif name == "declared":
                m = _DECLARED_COUNT_RE.match(text)
                if m and self._position:
                    self.page.declared_counts[self._position] = int(m.group(1))
            elif name == "release_span":
                m = _MARKET_THROUGH_RE.match(text)
                if m:
                    self.page.market_data_through = m.group(1)
                elif text.lower().startswith("rebuilt"):
                    self.page.cadence_claim = text
            elif self._row is not None:
                if self._row.get(name) is None:
                    self._row[name] = text or None
        elif tag == "li" and self._row is not None:
            self.page.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_nuxt:
            self._nuxt_chunks.append(data)
            return
        if self._svg_depth:
            return
        if self._in_title:
            self._buf.setdefault("title", []).append(data)
            return
        for _tag, name in reversed(self._capture):
            if name is not None:
                self._buf.setdefault(name, []).append(data)
                break

    def _read_nuxt(self, text: str) -> None:
        """``__NUXT_DATA__`` is a devalue array: index 0 maps keys to slot
        indices.  Only ``prerenderedAt`` (a build stamp) and ``path`` are read."""
        try:
            arr = json.loads(text)
        except ValueError:
            return
        if not isinstance(arr, list) or not arr or not isinstance(arr[0], dict):
            return

        def slot(key: str) -> Any:
            idx = arr[0].get(key)
            if isinstance(idx, int) and 0 <= idx < len(arr):
                return arr[idx]
            return None

        pre = slot("prerenderedAt")
        if isinstance(pre, int) and not isinstance(pre, bool) and pre > 0:
            self.page.prerendered_at_ms = pre
        path = slot("path")
        if isinstance(path, str):
            self.page.nuxt_path = path


def _normalize_row(raw: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    idx = raw["documentIndex"]
    rank: int | None = None
    text = raw.get("rank_text")
    if text is not None and text.isdigit():
        rank = int(text)
    else:
        errors.append(f"row {idx}: unparseable rank {text!r}")
    name = raw.get("name")
    if not name:
        errors.append(f"row {idx}: missing name")
    badge = raw.get("badge")
    badge_pos = badge_rank = None
    if badge:
        m = _RANK_BADGE_RE.match(badge)
        if m:
            badge_pos, badge_rank = m.group(1), int(m.group(2))
    if badge_pos is not None and (badge_pos != raw.get("position") or badge_rank != rank):
        errors.append(
            f"row {idx}: badge {badge!r} disagrees with section {raw.get('position')!r} rank {rank!r}"
        )
    market_pos = market_rank = None
    mt = raw.get("market_text")
    if mt:
        m = _MARKET_RE.match(mt)
        if m:
            market_pos, market_rank = m.group(1), int(m.group(2))
    direction = None
    for c in raw.get("market_classes") or []:
        if c.startswith("market--"):
            direction = c[len("market--") :]
    tier_class = raw.get("tierClass")
    return {
        "documentIndex": idx,
        "position": raw.get("position"),
        "positionalRank": rank,
        "tier": raw.get("tier"),
        "tierClass": tier_class,
        "name": name,
        "team": raw.get("team"),
        "rankBadge": badge,
        "marketPosition": market_pos,
        "marketPositionalRank": market_rank,
        "marketDirection": direction,
        "marketTitle": raw.get("market_title"),
    }


def parse_board_html(html: str) -> ParsedPage:
    """Parse one board page.  Pure and deterministic."""
    parser = _SignalsHTMLParser()
    parser.feed(html)
    parser.close()
    page = parser.page
    errors: list[str] = []
    page.rows = [_normalize_row(r, errors) for r in page.rows]
    page.row_errors = errors
    return page


def validate_page(
    page: ParsedPage,
    spec: BoardSpec,
    *,
    last_good_row_count: int | None = None,
) -> tuple[list[str], list[str]]:
    """Structural validation.  Returns ``(errors, warnings)``; any error
    quarantines the release."""
    errors: list[str] = list(page.row_errors[:25])
    if len(page.row_errors) > 25:
        errors.append(f"... {len(page.row_errors) - 25} more row errors")
    warnings: list[str] = []
    if page.heading != spec.heading:
        errors.append(f"game type unverified: heading {page.heading!r} != {spec.heading!r}")
    if page.nuxt_path is not None and page.nuxt_path != spec.route:
        errors.append(f"route mismatch: page path {page.nuxt_path!r} != {spec.route!r}")
    if not page.rows:
        errors.append("no player rows")
    missing = [p for p in spec.positions if p not in page.sections]
    if missing:
        errors.append(f"missing position sections: {missing}")
    unexpected = sorted(set(page.sections) - set(spec.positions))
    if unexpected:
        errors.append(f"unexpected position sections: {unexpected}")
    by_pos: dict[str, list[int]] = {}
    for r in page.rows:
        if r["position"] is None:
            errors.append(f"row {r['documentIndex']}: outside any position section")
            continue
        if r["tier"] is None:
            errors.append(f"row {r['documentIndex']}: outside any tier")
        if r["positionalRank"] is not None:
            by_pos.setdefault(r["position"], []).append(r["positionalRank"])
    for pos, ranks in by_pos.items():
        if ranks != list(range(1, len(ranks) + 1)):
            errors.append(f"{pos}: positional ranks are not contiguous 1..{len(ranks)}")
        declared = page.declared_counts.get(pos)
        if declared is not None and declared != len(ranks):
            errors.append(f"{pos}: page declares {declared} players, parsed {len(ranks)}")
        if declared is None:
            warnings.append(f"{pos}: no declared player count on the page")
    if last_good_row_count and len(page.rows) < last_good_row_count * ROW_COLLAPSE_FRACTION:
        errors.append(f"row-count collapse: {len(page.rows)} vs last good {last_good_row_count}")
    if page.published_at is None:
        warnings.append("no Published timestamp on the page")
    if page.market_data_through is None:
        warnings.append("no 'Market data through' date on the page")
    return errors, warnings


def content_sha256(page: ParsedPage) -> str:
    """Hash of the MEANINGFUL content only — rows plus the page's own data
    stamps.  The Nuxt build id and ``prerenderedAt`` change on every site
    deploy without the rankings changing, so they are excluded."""
    body = {
        "publishedAt": page.published_at,
        "marketDataThrough": page.market_data_through,
        "rows": [
            [
                r["position"],
                r["positionalRank"],
                r["tier"],
                r["name"],
                r["team"],
                r["marketPosition"],
                r["marketPositionalRank"],
                r["marketDirection"],
            ]
            for r in page.rows
        ],
    }
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Store ─────────────────────────────────────────────────────────────────


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # The destination is untouched; never leave a half-written temp.
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    text = json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    atomic_write_bytes(path, text.encode("utf-8"))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class SignalsStore:
    """Box-local private store rooted at ``data/sources/signals``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def board_dir(self, board: str) -> Path:
        return self.root / board

    def latest(self, board: str) -> dict[str, Any] | None:
        data = _read_json(self.board_dir(board) / "latest.json")
        return data if isinstance(data, dict) else None

    def fetch_state(self, board: str) -> dict[str, Any]:
        data = _read_json(self.board_dir(board) / "fetch_state.json")
        return data if isinstance(data, dict) else {}

    def save_fetch_state(self, board: str, state: dict[str, Any]) -> None:
        atomic_write_json(self.board_dir(board) / "fetch_state.json", state)

    def write_raw(self, board: str, raw_sha: str, body: bytes) -> Path:
        path = self.board_dir(board) / "raw" / f"{raw_sha}.html.gz"
        if not path.exists():
            # mtime=0 keeps the gzip bytes a pure function of the content.
            atomic_write_bytes(path, gzip.compress(body, mtime=0))
        return path

    def publish_release(self, board: str, release: dict[str, Any]) -> None:
        d = self.board_dir(board)
        atomic_write_json(d / "releases" / f"{release['contentSha256']}.json", release)
        # latest.json is written LAST: a crash before this line leaves the
        # previous last-good release fully intact.
        atomic_write_json(d / "latest.json", release)

    def quarantine(self, board: str, raw_sha: str, record: dict[str, Any]) -> None:
        atomic_write_json(self.board_dir(board) / "quarantine" / f"{raw_sha}.json", record)


# ── HTTP ──────────────────────────────────────────────────────────────────

HttpResponse = tuple[int, dict[str, str], bytes]
HttpGet = Callable[[str, Mapping[str, str], float], HttpResponse]


def urllib_get(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    """Default transport.  Returns ``(status, lowercase headers, body)`` for
    every HTTP status; raises ``OSError`` only for transport failures."""
    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URLs
            status = resp.status
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
        body = exc.read() if exc.fp else b""
    if hdrs.get("content-encoding", "").lower() == "gzip" and body:
        body = gzip.decompress(body)
    return status, hdrs, body


def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    dt = _http_date(value)
    if dt is None:
        return None
    return max(0.0, (dt - now).total_seconds())


# ── Collection ────────────────────────────────────────────────────────────


def _dataset_state_observe(
    store: SignalsStore,
    spec: BoardSpec,
    page: ParsedPage,
    *,
    health: str,
    errors: list[str],
    warnings: list[str],
    at: datetime,
) -> None:
    """Fold this release into the shared three-clock dataset-state owner
    (``src.sources.dataset_state``).  A non-HEALTHY board records its health
    and moves no clock — the owner's own invariant."""
    from src.sources import dataset_state as DS  # noqa: PLC0415
    from src.sources.dataset_integrity import SUBSET_PLAYERS, ParsedBoard  # noqa: PLC0415

    board = ParsedBoard()
    board.header = ["position", "name", "rank", "tier", "market"]
    for r in page.rows:
        key = f"{r['position']}:{(r['name'] or '').casefold()}"
        board.rows[SUBSET_PLAYERS][key] = (
            f"{r['positionalRank']}|{r['tier']}|{r['marketPositionalRank']}"
        )
    board.row_count = board.named_rows = board.numeric_rows = len(page.rows)
    board.health = health
    board.errors = list(errors[:10])
    board.warnings = list(warnings[:10])
    path = store.board_dir(spec.key) / "dataset_state.json"
    state = DS.load_state(path)
    new = DS.observe(
        state,
        source_key=spec.source_key,
        board=board,
        observed_at=at,
        upstream_published_at=page.published_at,
        track_rows=False,
    )
    DS.save_state(path, new)


def collect_board(
    spec: BoardSpec,
    store: SignalsStore,
    *,
    http: HttpGet = urllib_get,
    now: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
    min_interval_hours: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Collect one board.  Returns an outcome dict; never raises for HTTP or
    parse failures (they are outcomes).  Outcomes:

    ``published`` · ``not_modified`` · ``unchanged_content`` · ``quarantined``
    · ``skipped_recent`` · ``auth_stopped`` · ``stopped`` · ``rate_limited``
    · ``fetch_failed``
    """
    state = store.fetch_state(spec.key)
    started = now()
    outcome: dict[str, Any] = {"board": spec.key, "sourceKey": spec.source_key}

    if state.get("stoppedAt") and not force:
        outcome.update(
            outcome="stopped",
            reason=f"collection stopped at {state['stoppedAt']} ({state.get('stopReason')}); "
            "clear with --clear-stop after resolving access",
        )
        return outcome
    last_attempt = parse_iso(state.get("lastAttemptAt"))
    if (
        min_interval_hours
        and not force
        and last_attempt is not None
        and (started - last_attempt).total_seconds() < min_interval_hours * 3600
    ):
        outcome.update(outcome="skipped_recent", lastAttemptAt=state.get("lastAttemptAt"))
        return outcome

    latest = store.latest(spec.key)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html",
        "Accept-Encoding": "gzip",
    }
    if latest is not None:
        # Conditional GET only once a good release exists: a validator
        # without the content it validates would 304 us into having nothing.
        if state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        if state.get("lastModified"):
            headers["If-Modified-Since"] = state["lastModified"]

    status: int | None = None
    resp_headers: dict[str, str] = {}
    body = b""
    transient_attempt = 0
    rate_attempt = 0
    while True:
        try:
            status, resp_headers, body = http(spec.url, headers, HTTP_TIMEOUT_SECONDS)
        except OSError as exc:
            status, resp_headers, body = None, {}, b""
            err = f"transport: {exc}"
        else:
            err = None
        if status == 429:
            wait = _retry_after_seconds(resp_headers.get("retry-after"), now())
            if wait is None:
                wait = TRANSIENT_BACKOFF_SECONDS[
                    min(rate_attempt, len(TRANSIENT_BACKOFF_SECONDS) - 1)
                ]
            if rate_attempt >= 2 or wait > MAX_RETRY_AFTER_SECONDS:
                outcome.update(outcome="rate_limited", retryAfterSeconds=wait)
                break
            rate_attempt += 1
            sleep(wait)
            continue
        if status is None or status >= 500:
            if transient_attempt < len(TRANSIENT_BACKOFF_SECONDS):
                sleep(TRANSIENT_BACKOFF_SECONDS[transient_attempt])
                transient_attempt += 1
                continue
            outcome.update(outcome="fetch_failed", reason=err or f"HTTP {status}")
            break
        break

    at = now()
    state["lastAttemptAt"] = iso(at)
    state["parserVersion"] = PARSER_VERSION

    if outcome.get("outcome") in ("rate_limited", "fetch_failed"):
        pass
    elif status in (401, 403):
        state["stoppedAt"] = iso(at)
        state["stopReason"] = f"HTTP {status}"
        outcome.update(outcome="auth_stopped", httpStatus=status)
    elif status == 304:
        state["lastVerifiedUnchangedAt"] = iso(at)
        outcome.update(outcome="not_modified")
    elif status != 200:
        outcome.update(outcome="fetch_failed", reason=f"HTTP {status}")
    else:
        outcome.update(_handle_200(spec, store, state, latest, resp_headers, body, at))

    state["lastOutcome"] = outcome.get("outcome")
    if outcome.get("outcome") in ("published", "not_modified", "unchanged_content"):
        state["consecutiveFailures"] = 0
    else:
        state["consecutiveFailures"] = int(state.get("consecutiveFailures") or 0) + 1
    store.save_fetch_state(spec.key, state)
    return outcome


def _handle_200(
    spec: BoardSpec,
    store: SignalsStore,
    state: dict[str, Any],
    latest: dict[str, Any] | None,
    resp_headers: Mapping[str, str],
    body: bytes,
    at: datetime,
) -> dict[str, Any]:
    raw_sha = hashlib.sha256(body).hexdigest()
    html = body.decode("utf-8", errors="replace")
    page = parse_board_html(html)
    last_count = (latest or {}).get("rowCount")
    errors, warnings = validate_page(page, spec, last_good_row_count=last_count)
    csha = content_sha256(page)
    etag = resp_headers.get("etag")
    last_modified = resp_headers.get("last-modified")

    if errors:
        store.write_raw(spec.key, raw_sha, body)
        store.quarantine(
            spec.key,
            raw_sha,
            {
                "board": spec.key,
                "quarantinedAt": iso(at),
                "rawSha256": raw_sha,
                "contentSha256": csha,
                "parserVersion": PARSER_VERSION,
                "rowCount": len(page.rows),
                "errors": errors,
                "warnings": warnings,
            },
        )
        _dataset_state_observe(
            store, spec, page, health="DEGRADED", errors=errors, warnings=warnings, at=at
        )
        # Validators are NOT advanced: the next run must re-fetch rather
        # than 304 its way past a page we refused.
        return {"outcome": "quarantined", "errors": errors[:10], "rawSha256": raw_sha}

    # Validators advance on any accepted 200 so the next run can 304.
    state["etag"] = etag
    state["lastModified"] = last_modified

    if latest is not None and latest.get("contentSha256") == csha:
        state["lastVerifiedUnchangedAt"] = iso(at)
        return {"outcome": "unchanged_content", "contentSha256": csha}

    store.write_raw(spec.key, raw_sha, body)
    prerendered = (
        iso(datetime.fromtimestamp(page.prerendered_at_ms / 1000, tz=timezone.utc))
        if page.prerendered_at_ms
        else None
    )
    position_counts: dict[str, int] = {}
    for r in page.rows:
        position_counts[r["position"]] = position_counts.get(r["position"], 0) + 1
    release = {
        "schemaVersion": SCHEMA_VERSION,
        "provider": PROVIDER,
        "board": spec.key,
        "sourceKey": spec.source_key,
        "url": spec.url,
        "dataset": dataset_metadata(spec),
        "pageTitle": page.title,
        "pageHeading": page.heading,
        "publishedAt": page.published_at,
        "marketDataThrough": page.market_data_through,
        "cadenceClaim": page.cadence_claim,
        "prerenderedAt": prerendered,
        "prerenderedAtMs": page.prerendered_at_ms,
        "lastModified": last_modified,
        "etag": etag,
        "fetchedAt": iso(at),
        "parserVersion": PARSER_VERSION,
        "rawSha256": raw_sha,
        "contentSha256": csha,
        "previousContentSha256": (latest or {}).get("contentSha256"),
        "rowCount": len(page.rows),
        "positionCounts": position_counts,
        "declaredPositionCounts": page.declared_counts,
        "warnings": warnings,
        "observations": page.rows,
    }
    store.publish_release(spec.key, release)
    state["lastGoodContentSha256"] = csha
    state["lastPublishedAt"] = iso(at)
    _dataset_state_observe(store, spec, page, health="HEALTHY", errors=[], warnings=warnings, at=at)
    return {
        "outcome": "published",
        "contentSha256": csha,
        "rawSha256": raw_sha,
        "rowCount": len(page.rows),
        "positionCounts": position_counts,
        "publishedAt": page.published_at,
        "marketDataThrough": page.market_data_through,
        "warnings": warnings,
    }


# ── Identity: CONTRACT_CSV_JOIN_V1 against the live board ────────────────


@dataclass
class JoinResult:
    #: board-row identity key → observation (with join provenance)
    matches: dict[str, dict[str, Any]] = field(default_factory=dict)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)


def row_identity_key(row: Mapping[str, Any]) -> str | None:
    pid = str(row.get("playerId") or "").strip()
    if pid:
        return f"pid:{pid}"
    name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
    return f"name:{name}" if name else None


def join_to_board(
    observations: Sequence[Mapping[str, Any]],
    players_array: Sequence[Mapping[str, Any]],
) -> JoinResult:
    """Resolve Signals rows onto canonical board rows through the identity
    owner's ``CONTRACT_CSV_JOIN_V1`` policy, with the SAME key functions the
    contract's CSV join injects (``_canonical_match_key`` +
    ``canonical_position_group``).

    Stricter than the CSV path, deliberately: Signals publishes TRUE
    positions, so each entry is keyed by its own position group and no
    ``name_star`` / ``single_group`` fallback exists.  Anything not provably
    one-to-one is quarantined with a reason — never best-guessed:

    * two Signals rows on one ``name::group`` key → ``ambiguous`` (both)
    * one entry claimed by several board rows   → ``ambiguous`` (board homonyms)
    * claimed by no board row                    → ``unresolved``
      (``position_group_mismatch`` when the name exists in another group,
      else ``no_board_row``)
    """
    from src.api.data_contract import _canonical_match_key  # noqa: PLC0415
    from src.identity.resolution import match_row_to_source_entry  # noqa: PLC0415
    from src.utils.name_clean import canonical_position_group  # noqa: PLC0415

    result = JoinResult()
    per_source: dict[str, dict[str, Any]] = {}
    collided: dict[str, list[Mapping[str, Any]]] = {}
    for obs in observations:
        cname = _canonical_match_key(str(obs.get("name") or ""))
        if not cname:
            result.unresolved.append(_quarantine_entry(obs, "unkeyable_name"))
            continue
        key = f"{cname}::{canonical_position_group(obs.get('position'))}"
        if key in collided:
            collided[key].append(obs)
        elif key in per_source:
            collided[key] = [per_source.pop(key)["obs"], obs]
        else:
            per_source[key] = {"obs": obs}
    for key, group in collided.items():
        for obs in group:
            result.ambiguous.append(
                _quarantine_entry(obs, "duplicate_on_signals_board", key=key, n=len(group))
            )

    claims: dict[str, list[Mapping[str, Any]]] = {}
    board_groups: dict[str, set[str]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        cname = _canonical_match_key(name) if name else ""
        if cname:
            board_groups.setdefault(cname, set()).add(canonical_position_group(row.get("position")))
        decision = match_row_to_source_entry(
            row_player_id=row.get("playerId"),
            row_name=name,
            row_position=row.get("position"),
            per_source=per_source,
            sid_index={},
            row_groups_by_key={},
            canonical_match_key=_canonical_match_key,
            position_group=canonical_position_group,
        )
        if decision.entry_key:
            claims.setdefault(decision.entry_key, []).append(row)

    for key, entry in per_source.items():
        obs = entry["obs"]
        rows = claims.get(key) or []
        if len(rows) == 1:
            rk = row_identity_key(rows[0])
            if rk is None:
                result.unresolved.append(_quarantine_entry(obs, "board_row_without_identity"))
                continue
            result.matches[rk] = {
                **dict(obs),
                "boardDisplayName": rows[0].get("displayName"),
                "boardPlayerId": rows[0].get("playerId"),
                "identityPolicy": "contract_csv_join_v1",
            }
        elif len(rows) > 1:
            result.ambiguous.append(
                _quarantine_entry(
                    obs,
                    "multiple_board_rows",
                    key=key,
                    candidates=sorted(str(r.get("playerId") or r.get("displayName")) for r in rows),
                )
            )
        else:
            cname = key.split("::", 1)[0]
            reason = "position_group_mismatch" if board_groups.get(cname) else "no_board_row"
            result.unresolved.append(_quarantine_entry(obs, reason, key=key))
    result.ambiguous.sort(
        key=lambda e: (e["board"] or "", e["position"] or "", e["positionalRank"] or 0)
    )
    result.unresolved.sort(
        key=lambda e: (e["board"] or "", e["position"] or "", e["positionalRank"] or 0)
    )
    return result


def _quarantine_entry(obs: Mapping[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "board": obs.get("board"),
        "name": obs.get("name"),
        "position": obs.get("position"),
        "positionalRank": obs.get("positionalRank"),
        "team": obs.get("team"),
        "reason": reason,
        **extra,
    }


# ── Serving ───────────────────────────────────────────────────────────────


def _board_status(store: SignalsStore, spec: BoardSpec, at: datetime) -> dict[str, Any]:
    latest = store.latest(spec.key)
    fstate = store.fetch_state(spec.key)
    base = {
        "board": spec.key,
        "sourceKey": spec.source_key,
        "dataset": dataset_metadata(spec),
        "lastAttemptAt": fstate.get("lastAttemptAt"),
        "lastOutcome": fstate.get("lastOutcome"),
        "stoppedAt": fstate.get("stoppedAt"),
    }
    if latest is None:
        return {**base, "status": "not_collected", "release": None}
    published = parse_iso(latest.get("publishedAt"))
    # Information age comes from the vendor's OWN publication stamp; a
    # missing stamp leaves the age unknown rather than borrowing fetch time.
    age_h = round((at - published).total_seconds() / 3600, 1) if published else None
    degraded = fstate.get("lastOutcome") in (
        "quarantined",
        "auth_stopped",
        "stopped",
        "fetch_failed",
        "rate_limited",
    )
    return {
        **base,
        "status": "last_good_degraded" if degraded else "ok",
        "release": {
            "publishedAt": latest.get("publishedAt"),
            "marketDataThrough": latest.get("marketDataThrough"),
            "cadenceClaim": latest.get("cadenceClaim"),
            "prerenderedAt": latest.get("prerenderedAt"),
            "lastModified": latest.get("lastModified"),
            "fetchedAt": latest.get("fetchedAt"),
            "lastVerifiedUnchangedAt": fstate.get("lastVerifiedUnchangedAt"),
            "informationAgeHours": age_h,
            "rowCount": latest.get("rowCount"),
            "positionCounts": latest.get("positionCounts"),
            "parserVersion": latest.get("parserVersion"),
            "contentSha256": latest.get("contentSha256"),
        },
    }


#: One-entry memo for the identity join, keyed by the releases' content
#: hashes plus the identity of the board rows it was joined against.
_JOIN_MEMO: dict[str, Any] = {"key": None, "result": None}


def _memo_join(
    observations: list[dict[str, Any]],
    players_array: Sequence[Mapping[str, Any]],
    content_key: tuple[Any, ...],
) -> JoinResult:
    first = players_array[0] if players_array else {}
    key = (content_key, id(players_array), len(players_array), first.get("displayName"))
    if _JOIN_MEMO["key"] != key:
        _JOIN_MEMO["result"] = join_to_board(observations, players_array)
        _JOIN_MEMO["key"] = key
    return _JOIN_MEMO["result"]


def build_second_opinion_payload(
    store_root: Path,
    players_array: Sequence[Mapping[str, Any]] | None,
    *,
    now: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    """The authenticated Second Opinions payload.  Rank-only and non-voting
    by construction: there is no value field anywhere in it."""
    store = SignalsStore(store_root)
    at = now()
    boards = {key: _board_status(store, spec, at) for key, spec in BOARDS.items()}
    observations: list[dict[str, Any]] = []
    content_key: list[Any] = []
    for key in BOARDS:
        latest = store.latest(key)
        content_key.append((latest or {}).get("contentSha256"))
        for obs in (latest or {}).get("observations") or []:
            observations.append({**obs, "board": key})
    collected = [k for k, b in boards.items() if b["status"] != "not_collected"]
    if not collected:
        status = "not_collected"
    elif len(collected) < len(BOARDS) or any(b["status"] != "ok" for b in boards.values()):
        status = "partial"
    else:
        status = "ok"
    payload: dict[str, Any] = {
        "provider": PROVIDER,
        "label": "Signals Fantasy",
        "status": status,
        "votes": False,
        "basis": BASIS_POSITIONAL_RANK_ONLY,
        "positionalRankOnly": True,
        "note": (
            "Positional rank and tier from Signals' public dynasty boards. Not a value, "
            "not league-adjusted, never ranked across positions, and not counted in "
            "any verdict or in Chase Upside values."
        ),
        "boards": boards,
        "generatedAt": iso(at),
        "signalsPositionalRank": {},
        "identity": None,
    }
    if not observations:
        return payload
    if not players_array:
        payload["identity"] = {"status": "board_not_loaded"}
        return payload
    join = _memo_join(observations, players_array, tuple(content_key))
    payload["signalsPositionalRank"] = {
        rk: {
            "board": o["board"],
            "position": o["position"],
            "positionalRank": o["positionalRank"],
            "tier": o["tier"],
            "team": o["team"],
            "name": o["name"],
            "marketPositionalRank": o["marketPositionalRank"],
            "marketDirection": o["marketDirection"],
        }
        for rk, o in sorted(join.matches.items())
    }
    payload["identity"] = {
        "status": "ok",
        "policy": "contract_csv_join_v1 (position-group strict)",
        "observations": len(observations),
        "resolved": len(join.matches),
        "ambiguous": join.ambiguous,
        "unresolved": join.unresolved,
    }
    return payload
