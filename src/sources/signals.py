"""Signals Fantasy — public boards (second opinion) AND authenticated values (a voter).

One owner for everything Signals (#1555, Unit A; owner addendum 2026-10-03).
Two distinct halves, one provider family:

* **Public positional boards** (this docstring, top half of the module) —
  ``scripts/fetch_signals.py`` is a thin CLI over :func:`collect_board`; the
  authenticated endpoint ``GET /api/second-opinion/signals`` wraps
  :func:`build_second_opinion_payload`.  Rank-only, and they NEVER vote.
* **Authenticated native values** (the "Authenticated native values" section
  at the bottom) — ``scripts/fetch_signals_values.py`` is a thin CLI over
  :func:`collect_values`.  Since 2026-10-03 these are an ACTIVE canonical
  source: registry keys ``signalsSf`` (offense) and ``signalsIdp`` (IDP) in
  ``src/api/data_contract.py``, voting as a value-ordered rank signal inside
  the FantasyCalc B10 family.  Read that section before touching either half.

WHAT THE PUBLIC BOARDS ARE
--------------------------
Signals publishes two public, statically prerendered dynasty boards:

* ``/rankings/dynasty``      — QB / RB / WR / TE, 200 each (2026-10-01)
* ``/rankings/idp-dynasty``  — true defensive positions CB / S / DT / DE / LB

Each row is a POSITIONAL ordinal rank inside a tier band (S+ … F), plus a
"MKT QB4" badge giving Signals' own read of the market's positional rank.
There is **no value scale and no cross-position ordering** on these pages.

WHAT THE PUBLIC BOARDS ARE NOT — load-bearing
---------------------------------------------
* NOT a voting source.  The public boards' keys (``signalsDynasty`` /
  ``signalsIdpDynasty``) are not registered in ``_RANKING_SOURCES``, the
  blend, confidence or any canonical field.  Their only consumer is the
  Second Opinions surface, as a rank-only, non-voting row (``votes: False``).
  The VOTING Signals observation is the authenticated native value
  (``signalsSf`` / ``signalsIdp``), never these positional ranks.
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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
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
        # The PUBLIC positional board never votes.  Signals' voting
        # observation is the authenticated native value (``signalsSf`` /
        # ``signalsIdp``, :func:`value_dataset_metadata`), owner 2026-10-03.
        "intendedConsumer": "second_opinion_only",
        "votes": False,
        "votingObservation": "authenticated native value (signalsSf / signalsIdp)",
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


#: Hard caps on what one response may cost us.  The real pages are ~1 MB.
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024


class BodyTooLarge(Exception):
    """A response exceeded :data:`MAX_BODY_BYTES` / :data:`MAX_DECOMPRESSED_BYTES`."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: a 3xx is returned to the caller as a status,
    so a bounce to a login wall or another host cannot be fetched silently."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _bounded_read(stream: Any) -> bytes:
    body = stream.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise BodyTooLarge(f"response exceeds {MAX_BODY_BYTES} bytes")
    return body


def _bounded_gunzip(body: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(body, MAX_DECOMPRESSED_BYTES + 1)
    if len(out) > MAX_DECOMPRESSED_BYTES or d.unconsumed_tail:
        raise BodyTooLarge(f"decompressed response exceeds {MAX_DECOMPRESSED_BYTES} bytes")
    return out


def urllib_get(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    """Default transport.  Returns ``(status, lowercase headers, body)`` for
    every HTTP status, including 3xx (redirects are never followed); raises
    ``OSError`` for transport failures and :class:`BodyTooLarge` past the caps."""
    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URLs
            status = resp.status
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            body = _bounded_read(resp)
    except urllib.error.HTTPError as exc:
        status = exc.code
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
        body = _bounded_read(exc) if exc.fp else b""
    if hdrs.get("content-encoding", "").lower() == "gzip" and body:
        body = _bounded_gunzip(body)
    return status, hdrs, body


_AUTH_PATH_HINTS = ("login", "signin", "sign-in", "auth", "account", "subscribe", "paywall")


def _redirect_is_access_wall(source_url: str, location: str | None) -> bool:
    """A redirect off the board's origin, to a non-https URL, or to an
    auth/paywall-looking path is treated like 401/403 (stop), never followed."""
    if not location:
        return False
    target = urllib.parse.urlsplit(urllib.parse.urljoin(source_url, location))
    origin = urllib.parse.urlsplit(source_url)
    if target.scheme != "https" or target.netloc.lower() != origin.netloc.lower():
        return True
    return any(h in target.path.lower() for h in _AUTH_PATH_HINTS)


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
        except BodyTooLarge as exc:
            # Not transient: retrying an oversize page costs the same again.
            outcome.update(outcome="fetch_failed", reason=f"oversize: {exc}")
            break
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
    elif status is not None and 300 <= status < 400 and status != 304:
        location = resp_headers.get("location")
        if _redirect_is_access_wall(spec.url, location):
            state["stoppedAt"] = iso(at)
            state["stopReason"] = f"HTTP {status} redirect to an access wall or another origin"
            outcome.update(outcome="auth_stopped", httpStatus=status)
        else:
            outcome.update(outcome="fetch_failed", reason=f"HTTP {status} redirect not followed")
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
#: hashes plus a CONTENT fingerprint of the board rows it was joined against
#: (never ``id()``, which a freed list can hand to its successor).  Key and
#: result are replaced together under a lock: request handlers run on
#: threadpool workers.
_JOIN_MEMO: tuple[Any, JoinResult] | None = None
_JOIN_MEMO_LOCK = threading.Lock()


def _board_fingerprint(players_array: Sequence[Mapping[str, Any]]) -> str:
    h = hashlib.sha256()
    for row in players_array:
        h.update(f"{row.get('playerId')}|{row.get('displayName')}|{row.get('position')}\n".encode())
    return h.hexdigest()


def _memo_join(
    observations: list[dict[str, Any]],
    players_array: Sequence[Mapping[str, Any]],
    content_key: tuple[Any, ...],
) -> JoinResult:
    global _JOIN_MEMO
    key = (content_key, _board_fingerprint(players_array))
    with _JOIN_MEMO_LOCK:
        if _JOIN_MEMO is not None and _JOIN_MEMO[0] == key:
            return _JOIN_MEMO[1]
        result = join_to_board(observations, players_array)
        _JOIN_MEMO = (key, result)
        return result


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
            "any verdict. Signals' authenticated native values are a separate, voting "
            "observation (the Signals columns on /rankings)."
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


# ══ Authenticated native values — the ACTIVE canonical source ═══════════
#
# Owner addendum 2026-10-03 (``docs/sources/SIGNALS_FANTASY_INTEGRATION.md``
# §9).  Signals' authenticated native dynasty VALUES vote in the canonical
# board for offense (QB/RB/WR/TE) and IDP — through the SAME rank-signal
# path FantasyCalc and Dynasty Daddy use: Signals' own cross-position value
# ORDERING becomes a rank, and the rank travels rank -> percentile -> Hill.
# The native values are retained (private release + ``sourceNativeValues``)
# and shown; the rank is labelled DERIVED from that value ordering, because
# Signals did not publish it.
#
# One provider family, one active observation per player:
#
# * the PUBLIC positional boards above never vote (``votes: False`` stays
#   true for them) — a positional ordinal has no cross-position order;
# * the authenticated VALUE is the vote (selection rung 2 of the owner
#   hierarchy: the stored Dynasty + Superflex preset.  Rung 1, exact league
#   settings, is computed CLIENT-side by Signals' app over a FantasyCalc
#   fetch, so it is not a server observation and is not reimplemented);
# * a row with no value votes through an authenticated CROSS-POSITION rank
#   only when the payload carries one (rung 3).  Today neither dataset
#   publishes one — positional ranks are retained as provenance and NEVER
#   turned into an overall order — so such rows are MISSING, never zero.
#
# Privacy (§2): the raw responses, releases and the board-ready CSV live in
# the box-local, gitignored ``data/sources/signals/`` store.  The board CSV
# is read by the contract build on the box; on a host where the authenticated
# collector has never run (CI, local dev, a fresh box) the source is
# NOT PROVISIONED — absent, never zero, and never a red CI lane
# (``data_contract.private_source_availability``).
#
# Storage (box-local, gitignored)::
#
#     data/sources/signals/values/collector_state.json      provisioning marker
#     data/sources/signals/values/<dataset>/raw/<sha>.json.gz
#     data/sources/signals/values/<dataset>/releases/<contentSha>.json
#     data/sources/signals/values/<dataset>/quarantine/<sha>.json
#     data/sources/signals/values/<dataset>/latest.json      last good release
#     data/sources/signals/values/<dataset>/fetch_state.json
#     data/sources/signals/board/<sourceKey>.csv             board-ready vote

APPSYNC_URL = "https://itesc4ls2vhgtlole3nhy245wa.appsync-api.us-east-2.amazonaws.com/graphql"
VALUES_PARSER_VERSION = "signals-appsync-values-v1"
VALUES_SCHEMA_VERSION = 1
VALUES_DIR = "values"
BOARD_DIR = "board"
#: Written by EVERY authenticated-collector run (including an auth stop), so
#: its presence is the proof that this host is meant to carry the private
#: source.  Read by ``private_store_provisioned``.
PROVISIONED_MARKER = "collector_state.json"

BASIS_NATIVE_VALUE = "NATIVE_VALUE"
BASIS_CROSS_POSITION_RANK = "CROSS_POSITION_RANK"

USER_AGENT_VALUES = (
    "ChaseUpsideCollector/1.0 (private dynasty analysis tool; "
    "owner-authorized read-only authenticated value collection)"
)
#: Aliased ``listSnapshotsByPlayer`` fields per GraphQL request.  Measured
#: 2026-10-03: 25 aliases answer in ~0.75 s, so the whole offense universe
#: (~517 players) is ~21 requests.
OFFENSE_BATCH_SIZE = 25
#: Hard cap on HTTP requests one run may spend across both datasets.
MAX_VALUE_REQUESTS_PER_RUN = 60
IDP_PAGE_LIMIT = 1000
#: The IDP season board measured 1,072 rows (2 pages).  More than this many
#: pages is runaway pagination: the release is withheld, never truncated.
IDP_MAX_PAGES = 5
#: Pause between requests.
REQUEST_PAUSE_SECONDS = 1.0
#: How far back a player's newest snapshot may sit and still be READ.  It is
#: not a currency rule — only the run's publication date (below) is current.
OFFENSE_LOOKBACK_DAYS = 7
#: A publication is the newest snapshot date the vendor wrote for MORE THAN
#: HALF of the valued players — the same fraction the collapse guard uses.
#: Rows dated before the publication are not current and are excluded.
PUBLICATION_MAJORITY = ROW_COLLAPSE_FRACTION

#: Fail-loud, preserve-last-good board floors, aligned with (>=) the
#: contract's ``_DEFAULT_SOURCE_ROW_FLOORS`` (pinned by
#: ``tests/api/test_source_floor_invariant.py``).  A release with fewer
#: voting rows is quarantined and the last good board keeps voting with its
#: true age.  Measured 2026-10-03: 509 offense board rows; IDP per family
#: (DL / LB / DB) — see ``IDP_FAMILY_BOARDS``.
MIN_BOARD_ROWS: dict[str, int] = {
    "signalsSf": 400,
    "signalsIdpDl": 330,
    "signalsIdpLb": 150,
    "signalsIdpDb": 300,
}

#: Signals' IDP ``value`` is a strictly monotone function of its per-FAMILY
#: composite (Spearman 1.000; independent review of #1627, 2026-10-03): each
#: family is normalised on its own scale (tops DL / LB / DB within 4% of each
#: other, near-identical curves at #12 and #24).  It is therefore NOT a
#: cross-family price, and its top-100 is half DBs.  Ordering it across
#: families would manufacture exactly the shared DL/LB/DB order the owner
#: addendum forbids ("DE4 and LB4 must NOT be manufactured into a shared
#: overall rank").  So each family is ranked ONLY within itself and written
#: to its own board, which votes through the positional IDP path
#: (``SOURCE_SCOPE_POSITION_IDP`` + the backbone's per-family ladder).
IDP_FAMILY_BOARDS: dict[str, str] = {
    "DL": "signalsIdpDl",
    "LB": "signalsIdpLb",
    "DB": "signalsIdpDb",
}

BOARD_CSV_COLUMNS: tuple[str, ...] = (
    "name",
    "rank",
    "value",
    "sleeper_id",
    "position",
    "raw_position",
    "team",
    "basis",
    "rank_derived",
    "value_as_of",
    "dataset",
)

_SID_RE = re.compile(r"^[0-9]{1,9}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ValueDatasetSpec:
    key: str
    source_key: str
    dataset: str
    positions: tuple[str, ...]
    population: str
    game_type_evidence: str
    #: Format of the observation, recorded on every observation.
    format: dict[str, Any] = field(default_factory=dict)
    #: Payload field carrying an authenticated CROSS-POSITION rank, if any.
    #: ``None`` for both datasets today: positional ranks never qualify.
    cross_position_rank_field: str | None = None
    #: ``{family: source_key}`` when the dataset is ranked WITHIN families
    #: and written as one board per family (IDP); empty = one board,
    #: ``source_key``, ranked across the whole dataset (offense).
    family_boards: dict[str, str] = field(default_factory=dict)

    def output_keys(self) -> tuple[str, ...]:
        """The registry keys this dataset's boards vote under."""
        return tuple(self.family_boards.values()) or (self.source_key,)

    def board_key_for(self, row: Mapping[str, Any]) -> str | None:
        if not self.family_boards:
            return self.source_key
        return self.family_boards.get(str(row.get("position") or ""))


_OFFENSE_FORMAT = {
    "gameType": "DYNASTY",
    "superflex": True,
    "tePremium": False,
    "leagueAdjusted": False,
    "basis": BASIS_NATIVE_VALUE,
    "preset": "Signals stored Dynasty value, Superflex (PlayerValueSnapshot.signalsDynastyValue)",
    "superflexEvidence": (
        "measured 2026-10-03: Josh Allen priced above Jaxon Smith-Njigba, and Caleb "
        "Williams / Lamar Jackson / Joe Burrow priced as top-12 assets; a 1QB board puts "
        "those QBs near half of WR1"
    ),
    "tePremiumEvidence": (
        "measured 2026-10-03: the TE1 is priced below WRs FantasyCalc prices equally; no "
        "TE premium and no TEP control on the stored value"
    ),
    "exactLeagueSettings": (
        "not a server observation: Signals' app computes league-exact values client-side "
        "over a FantasyCalc fetch, so they are not collected and not reimplemented"
    ),
}
_IDP_FORMAT = {
    "gameType": "DYNASTY",
    "superflex": None,
    "tePremium": None,
    "leagueAdjusted": False,
    "basis": BASIS_NATIVE_VALUE,
    "preset": "Signals IDP dynasty season board (IdpDynastyValueEntry.value, sk '<season>#dynasty')",
    "scale": "per family (DL / LB / DB); not comparable across families",
    "superflexEvidence": "not applicable: an IDP-only board",
    "tePremiumEvidence": "not applicable: an IDP-only board",
    "exactLeagueSettings": "not exposed",
}

VALUE_DATASETS: dict[str, ValueDatasetSpec] = {
    "offense": ValueDatasetSpec(
        key="offense",
        source_key="signalsSf",
        dataset="offense",
        positions=("QB", "RB", "WR", "TE"),
        population="offense: QB/RB/WR/TE native Superflex dynasty values, one daily snapshot",
        game_type_evidence=(
            "PlayerValueSnapshot.signalsDynastyValue: the DYNASTY value field, distinct from "
            "the snapshot's signalsRedraft* fields, which are never read"
        ),
        format=_OFFENSE_FORMAT,
    ),
    "idp": ValueDatasetSpec(
        key="idp",
        # The dataset id (store ``values/idp``); NOT a registry key — the
        # boards vote under ``IDP_FAMILY_BOARDS``.
        source_key="signalsIdp",
        dataset="idp",
        positions=("CB", "S", "DT", "DE", "LB"),
        population=(
            "IDP: true positions CB/S/DT/DE/LB; values normalised WITHIN Signals' family "
            "(DL / LB / DB), so ranked within family only"
        ),
        game_type_evidence=(
            "listIdpDynastyValuesBySeason rows keyed sk '<season>#dynasty', re-verified on "
            "every row of every release; a release failing it is quarantined"
        ),
        format=_IDP_FORMAT,
        family_boards=IDP_FAMILY_BOARDS,
    ),
}


def value_dataset_metadata(spec: ValueDatasetSpec) -> dict[str, Any]:
    """Declared contract of one authenticated value dataset (it VOTES)."""
    return {
        "provider": PROVIDER,
        "family": PROVIDER,
        "sourceKey": spec.source_key,
        "registryKeys": list(spec.output_keys()),
        "dataset": spec.dataset,
        "gameType": "DYNASTY",
        "gameTypeEvidence": spec.game_type_evidence,
        "format": dict(spec.format),
        "population": spec.population,
        "crossPositionOrdering": not spec.family_boards,
        "horizon": "dynasty",
        "unit": "native_value",
        "basis": BASIS_NATIVE_VALUE,
        "voteBasis": (
            "value-ordered rank WITHIN family (derived) -> backbone family ladder -> IDP Hill"
            if spec.family_boards
            else "value-ordered rank (derived) -> percentile -> Hill"
        ),
        "intendedConsumer": "canonical_rank_signal",
        "votes": True,
        "visibility": "authenticated_only",
        "lineage": (
            "one Signals provider family, declared inside FantasyCalc's B10 group: Signals' "
            "app falls back to FantasyCalc values for its offense dynasty baseline (no "
            "independence bonus on offense).  FantasyCalc publishes no IDP, so on IDP rows the "
            "group is Signals alone — its IDP value is model-derived from per-snap features "
            "with no market input"
        ),
    }


def values_root(store_root: Path) -> Path:
    return Path(store_root) / VALUES_DIR


def board_csv_path(store_root: Path, source_key: str) -> Path:
    return Path(store_root) / BOARD_DIR / f"{source_key}.csv"


def private_store_provisioned(store_root: Path) -> bool:
    """True once the authenticated collector has run on this host."""
    return (values_root(store_root) / PROVISIONED_MARKER).is_file()


# ── Offense universe (whose snapshots are read) ──────────────────────────


def newest_raw_payload(repo_root: Path) -> tuple[dict[str, Any] | None, Path | None]:
    """The newest raw scrape payload on this host (runtime cache, then the
    checked-out export) — the universe the board can rank at all."""
    candidates: list[Path] = []
    for d in (Path(repo_root) / "data", Path(repo_root) / "exports" / "latest"):
        candidates.extend(d.glob("dynasty_data_*.json"))
    for path in sorted(candidates, key=lambda p: (p.name, str(p.parent)), reverse=True):
        data = _read_json(path)
        if isinstance(data, dict) and isinstance(data.get("players"), dict):
            return data, path
    return None, None


def offense_universe_from_payload(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """``{sleeperId: {name, position}}`` for every offense player the raw
    payload carries with a Sleeper id.  A player the board cannot hold is not
    queried; anything not queried is MISSING, never zero."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(payload, Mapping):
        return out
    players = payload.get("players") or {}
    sleeper = payload.get("sleeper") or {}
    positions = sleeper.get("positions") or {} if isinstance(sleeper, Mapping) else {}
    if not isinstance(players, Mapping):
        return out
    for name, pdata in players.items():
        if not isinstance(pdata, Mapping):
            continue
        sid = str(pdata.get("_sleeperId") or "").strip()
        pos = str(positions.get(name) or "").strip().upper()
        if not _SID_RE.match(sid) or pos not in VALUE_DATASETS["offense"].positions:
            continue
        out.setdefault(sid, {"name": str(name), "position": pos})
    return out


# ── Normalization + the selection hierarchy ──────────────────────────────


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        return None
    return number


def _positive_int(value: Any) -> int | None:
    number = _positive_number(value)
    if number is None or number != int(number):
        return None
    return int(number)


def normalize_idp_items(
    items: Sequence[Mapping[str, Any]],
    spec: ValueDatasetSpec,
    *,
    season: int,
) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, int]]:
    """Signals IDP season rows -> observations.  Returns ``(obs, errors,
    warnings, excluded)``; any error quarantines the release.

    The raw Signals position (CB / S / DT / DE / LB) is kept as provenance
    and mapped to DL / LB / DB only through the canonical owner
    (``src.utils.name_clean.normalize_position``).

    A row whose id is not a Sleeper player id is EXCLUDED with a reason, not
    a schema error: the season board carries draft-prospect rows keyed by a
    vendor slug (2 of 1,072 measured 2026-10-03, ``draft_2025_<name>``) that
    no board row can be joined to by id.  Never name-guessed."""
    from src.utils.name_clean import normalize_position  # noqa: PLC0415

    errors: list[str] = []
    warnings: list[str] = []
    excluded: dict[str, int] = {}
    obs: list[dict[str, Any]] = []
    seen: set[str] = set()
    want_sk = f"{season}#dynasty"
    for idx, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"row {idx}: not an object")
            continue
        sid = str(item.get("sleeperPlayerId") or "").strip()
        raw_pos = str(item.get("position") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if item.get("sk") != want_sk or str(item.get("season")) != str(season):
            errors.append(
                f"row {idx}: game type unverified (sk {item.get('sk')!r}, season "
                f"{item.get('season')!r}; expected {want_sk!r})"
            )
            continue
        if not _SID_RE.match(sid):
            excluded["no_sleeper_id"] = excluded.get("no_sleeper_id", 0) + 1
            continue
        if sid in seen:
            errors.append(f"row {idx}: duplicate sleeperPlayerId {sid}")
            continue
        seen.add(sid)
        if raw_pos not in spec.positions:
            errors.append(f"row {idx}: unexpected position {raw_pos!r}")
            continue
        family = normalize_position(raw_pos)
        if spec.family_boards and str(item.get("family") or "") != family:
            # Signals' own family must be the canonical owner's mapping of
            # its raw position — the per-family boards depend on it.
            errors.append(
                f"row {idx}: vendor family {item.get('family')!r} disagrees with "
                f"{raw_pos!r} -> {family!r}"
            )
            continue
        if not name:
            errors.append(f"row {idx}: missing name")
            continue
        raw_value = item.get("value")
        value = _positive_number(raw_value)
        if raw_value not in (None, "") and value is None:
            errors.append(f"row {idx}: non-positive or non-numeric value")
            continue
        as_of = item.get("sourceUpdatedAt") or item.get("updatedAt")
        obs.append(
            {
                "sleeperId": sid,
                "name": name,
                "rawPosition": raw_pos,
                "position": family,
                "signalsFamily": item.get("family"),
                "team": item.get("team"),
                "nativeValue": value,
                "positionalRank": _positive_int(item.get("posRank")),
                "crossPositionRank": (
                    _positive_int(item.get(spec.cross_position_rank_field))
                    if spec.cross_position_rank_field
                    else None
                ),
                "valueAsOf": str(as_of) if as_of else None,
                "format": dict(spec.format),
            }
        )
    if not obs and not errors:
        errors.append("no IDP rows for the season board")
    return obs, errors, warnings, excluded


def normalize_offense_snapshots(
    results: Mapping[str, Sequence[Mapping[str, Any]]],
    universe: Mapping[str, Mapping[str, Any]],
    spec: ValueDatasetSpec,
) -> tuple[list[dict[str, Any]], str | None, list[str], list[str], dict[str, int]]:
    """``{sleeperId: [newest snapshots]}`` -> observations of ONE publication.

    The publication date is the newest date covering more than half of the
    players that have any snapshot in the window.  A player whose snapshots
    do not include that date is NOT current and is excluded (counted) —
    never carried forward at an older date.
    """
    errors: list[str] = []
    warnings: list[str] = []
    excluded: dict[str, int] = {}
    by_player: dict[str, dict[str, Mapping[str, Any]]] = {}
    for sid, snaps in results.items():
        for snap in snaps or ():
            if not isinstance(snap, Mapping):
                errors.append(f"{sid}: snapshot is not an object")
                continue
            if str(snap.get("playerId") or "") != sid:
                errors.append(f"{sid}: snapshot answered for another player")
                continue
            date = str(snap.get("date") or "")
            if not _DATE_RE.match(date):
                errors.append(f"{sid}: unparseable snapshot date {date!r}")
                continue
            by_player.setdefault(sid, {})[date] = snap
    if errors:
        return [], None, errors[:25], warnings, excluded
    if not by_player:
        return [], None, ["no snapshots in the lookback window"], warnings, excluded
    counts: dict[str, int] = {}
    for dates in by_player.values():
        for d in dates:
            counts[d] = counts.get(d, 0) + 1
    publication = next(
        (
            d
            for d in sorted(counts, reverse=True)
            if counts[d] > PUBLICATION_MAJORITY * len(by_player)
        ),
        None,
    )
    if publication is None:
        return [], None, ["no snapshot date covers a majority of players"], warnings, excluded
    obs: list[dict[str, Any]] = []
    for sid in sorted(by_player):
        snap = by_player[sid].get(publication)
        if snap is None:
            excluded["not_current_publication"] = excluded.get("not_current_publication", 0) + 1
            continue
        raw_value = snap.get("signalsDynastyValue")
        value = _positive_number(raw_value)
        if raw_value not in (None, "") and value is None:
            errors.append(f"{sid}: non-positive or non-numeric value")
            continue
        meta = universe.get(sid) or {}
        obs.append(
            {
                "sleeperId": sid,
                "name": str(meta.get("name") or ""),
                "rawPosition": None,
                "position": str(meta.get("position") or ""),
                "signalsFamily": None,
                "team": None,
                "nativeValue": value,
                "positionalRank": _positive_int(snap.get("signalsDynastyPosRank")),
                "crossPositionRank": (
                    _positive_int(snap.get(spec.cross_position_rank_field))
                    if spec.cross_position_rank_field
                    else None
                ),
                "valueAsOf": str(snap.get("updatedAt") or publication),
                "format": dict(spec.format),
            }
        )
    missing = len(universe) - len(by_player)
    if missing > 0:
        excluded["no_snapshot_in_window"] = missing
    return obs, publication, errors[:25], warnings, excluded


def build_board_rows(
    observations: Sequence[Mapping[str, Any]],
    spec: ValueDatasetSpec,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply the owner's selection hierarchy: ONE active observation per player.

    * native value present           -> VALUE; the rank is DERIVED from the
      value ordering (competition rank: equal values share a rank);
    * no value, cross-position rank  -> RANK fallback at the published rank;
    * otherwise (a positional rank at most) -> MISSING: never zero, and
      never a manufactured cross-position order.

    A dataset with ``family_boards`` (IDP) is ranked WITHIN each family only:
    every family's board starts at rank 1 and no row is ever ordered
    against another family's.  A row whose family has no board is excluded.

    Players whose canonical name collides inside the dataset are withheld
    (both): the CSV join falls back to the name, and would otherwise attach
    one player's value to the other.
    """
    from src.api.data_contract import _canonical_match_key  # noqa: PLC0415

    excluded: dict[str, int] = {}
    name_counts: dict[str, int] = {}
    keyed: list[tuple[str, Mapping[str, Any]]] = []
    for o in observations:
        k = _canonical_match_key(str(o.get("name") or ""))
        keyed.append((k, o))
        name_counts[k] = name_counts.get(k, 0) + 1
    valued: list[Mapping[str, Any]] = []
    ranked: list[Mapping[str, Any]] = []
    for k, o in keyed:
        if not k:
            excluded["unkeyable_name"] = excluded.get("unkeyable_name", 0) + 1
        elif name_counts.get(k, 0) > 1:
            excluded["homonym_within_dataset"] = excluded.get("homonym_within_dataset", 0) + 1
        elif spec.board_key_for(o) is None:
            excluded["no_family_board"] = excluded.get("no_family_board", 0) + 1
        elif _positive_number(o.get("nativeValue")) is not None:
            valued.append(o)
        elif _positive_int(o.get("crossPositionRank")) is not None:
            ranked.append(o)
        else:
            excluded["no_value_no_cross_position_rank"] = (
                excluded.get("no_value_no_cross_position_rank", 0) + 1
            )
    rows: list[dict[str, Any]] = []
    for board in spec.output_keys():
        group = [o for o in valued if spec.board_key_for(o) == board]
        group.sort(
            key=lambda o: (
                -float(o["nativeValue"]),
                str(o.get("name") or "").casefold(),
                str(o.get("sleeperId") or ""),
            )
        )
        prev_value: float | None = None
        prev_rank = 0
        for idx, o in enumerate(group, start=1):
            value = float(o["nativeValue"])
            rank = prev_rank if value == prev_value else idx
            prev_value, prev_rank = value, rank
            rows.append(_board_row(o, spec, rank=rank, value=value, basis=BASIS_NATIVE_VALUE))
    for o in sorted(
        ranked,
        key=lambda o: (
            str(spec.board_key_for(o)),
            int(o["crossPositionRank"]),
            str(o.get("sleeperId") or ""),
        ),
    ):
        rows.append(
            _board_row(
                o,
                spec,
                rank=int(o["crossPositionRank"]),
                value=None,
                basis=BASIS_CROSS_POSITION_RANK,
            )
        )
    return rows, excluded


def _board_row(
    o: Mapping[str, Any], spec: ValueDatasetSpec, *, rank: int, value: float | None, basis: str
) -> dict[str, Any]:
    return {
        "name": o.get("name") or "",
        "rank": rank,
        "value": value,
        "sleeper_id": o.get("sleeperId") or "",
        "position": o.get("position") or "",
        "raw_position": o.get("rawPosition") or "",
        "team": o.get("team") or "",
        "basis": basis,
        "rank_derived": 1 if basis == BASIS_NATIVE_VALUE else 0,
        "value_as_of": o.get("valueAsOf") or "",
        "dataset": spec.dataset,
    }


def render_board_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    import csv as _csv  # noqa: PLC0415
    import io  # noqa: PLC0415

    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=list(BOARD_CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        out = {k: row.get(k, "") for k in BOARD_CSV_COLUMNS}
        v = row.get("value")
        if v is None:
            out["value"] = ""
        elif float(v) == int(float(v)):
            out["value"] = int(float(v))
        writer.writerow(out)
    return buf.getvalue()


def board_content_sha256(rows: Sequence[Mapping[str, Any]], as_of: str | None) -> str:
    blob = json.dumps(
        {"asOf": as_of, "rows": [[r.get(k) for k in BOARD_CSV_COLUMNS] for r in rows]},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── AppSync transport ────────────────────────────────────────────────────

HttpPost = Callable[[str, Mapping[str, str], bytes, float], HttpResponse]


def urllib_post(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> HttpResponse:
    """Default POST transport: the same no-redirect / size caps as GETs."""
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
            status = resp.status
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            data = _bounded_read(resp)
    except urllib.error.HTTPError as exc:
        status = exc.code
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
        data = _bounded_read(exc) if exc.fp else b""
    if hdrs.get("content-encoding", "").lower() == "gzip" and data:
        data = _bounded_gunzip(data)
    return status, hdrs, data


class ValuesStop(Exception):
    """A run-level stop.  ``outcome`` is the recorded collection outcome."""

    def __init__(self, outcome: str, reason: str) -> None:
        self.outcome = outcome
        self.reason = reason
        super().__init__(f"{outcome}: {reason}")


class SignalsAuthTokens:
    """Token provider over the owner session (``src.sources.signals_auth``).

    The access token goes into the ``Authorization`` header and nowhere else:
    never logged, never written by the collector."""

    def __init__(self, auth_dir: str | os.PathLike[str] | None = None) -> None:
        from src.sources import signals_auth as SA  # noqa: PLC0415

        self._sa = SA
        self._store = SA.SignalsStore.open(auth_dir)

    def token(self) -> str:
        try:
            return self._sa.get_access_token(self._store)
        except self._sa.SignalsAuthError as exc:
            raise ValuesStop("auth_unavailable", exc.failure_class) from None

    def renew(self) -> None:
        try:
            self._sa.renew_for_retry(self._store)
        except self._sa.SignalsAuthError as exc:
            raise ValuesStop("auth_unavailable", exc.failure_class) from None

    def deny(self, reason: str) -> None:
        with self._store.lock():
            self._sa.record_failure(self._store, self._sa.ACCESS_DENIED, reason)


class AppSyncClient:
    """Bounded GraphQL client.  It stops (``ValuesStop``); it never loops.

    401/403 (and AppSync's HTTP-200 ``Unauthorized`` field errors) get ONE
    fresh renewal through the auth owner's ``classify_data_response``; a
    refusal that survives it is ``access_denied`` and is recorded once.
    429 honours Retry-After (capped), 5xx / transport errors back off a
    bounded number of times, and a hard request budget caps every run.
    """

    def __init__(
        self,
        tokens: Any,
        *,
        http_post: HttpPost = urllib_post,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = utc_now,
        max_requests: int = MAX_VALUE_REQUESTS_PER_RUN,
        url: str = APPSYNC_URL,
    ) -> None:
        self.tokens = tokens
        self.http_post = http_post
        self.sleep = sleep
        self.now = now
        self.max_requests = max_requests
        self.url = url
        self.requests = 0
        self.renewed = False

    def _auth_refused(self, status: int) -> None:
        from src.sources import signals_auth as SA  # noqa: PLC0415

        verdict = SA.classify_data_response(status, renewal_attempted=self.renewed)
        if verdict == SA.DATA_RENEW_AND_RETRY:
            self.renewed = True
            self.tokens.renew()
            return
        self.tokens.deny(f"appsync HTTP {status} after a fresh renewal")
        raise ValuesStop("access_denied", f"HTTP {status} after renewal")

    def query(self, document: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": document, "variables": dict(variables)}).encode("utf-8")
        rate_attempt = transient_attempt = 0
        while True:
            if self.requests >= self.max_requests:
                raise ValuesStop("request_budget_exhausted", f"{self.requests} requests")
            headers = {
                "Authorization": self.tokens.token(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": USER_AGENT_VALUES,
            }
            self.requests += 1
            try:
                status, resp_headers, data = self.http_post(
                    self.url, headers, body, HTTP_TIMEOUT_SECONDS
                )
            except BodyTooLarge as exc:
                raise ValuesStop("fetch_failed", f"oversize: {exc}") from None
            except OSError as exc:
                status, resp_headers, data = None, {}, b""
                reason = f"transport: {type(exc).__name__}"
            else:
                reason = f"HTTP {status}"
            if status == 429:
                wait = _retry_after_seconds(resp_headers.get("retry-after"), self.now())
                if wait is None:
                    wait = TRANSIENT_BACKOFF_SECONDS[
                        min(rate_attempt, len(TRANSIENT_BACKOFF_SECONDS) - 1)
                    ]
                if rate_attempt >= 2 or wait > MAX_RETRY_AFTER_SECONDS:
                    raise ValuesStop("rate_limited", f"Retry-After {wait}")
                rate_attempt += 1
                self.sleep(wait)
                continue
            if status is None or status >= 500:
                if transient_attempt < len(TRANSIENT_BACKOFF_SECONDS):
                    self.sleep(TRANSIENT_BACKOFF_SECONDS[transient_attempt])
                    transient_attempt += 1
                    continue
                raise ValuesStop("fetch_failed", reason)
            if status in (401, 403):
                self._auth_refused(status)
                continue
            if status != 200:
                raise ValuesStop("fetch_failed", reason)
            try:
                doc = json.loads(data.decode("utf-8"))
            except (UnicodeError, ValueError):
                raise ValuesStop("schema_drift", "response is not JSON") from None
            if not isinstance(doc, dict):
                raise ValuesStop("schema_drift", "response is not an object")
            gql_errors = [e for e in (doc.get("errors") or []) if isinstance(e, Mapping)]
            if any("unauthorized" in str(e.get("errorType") or "").lower() for e in gql_errors):
                # AppSync answers field-level auth failures with HTTP 200.
                self._auth_refused(401)
                continue
            if gql_errors:
                msgs = sorted({str(e.get("message") or "")[:160] for e in gql_errors})
                raise ValuesStop("schema_drift", "; ".join(msgs[:3]))
            out = doc.get("data")
            if not isinstance(out, dict):
                raise ValuesStop("schema_drift", "response carries no data object")
            return out


_IDP_QUERY = (
    "query SignalsIdpValues($season: Int!, $limit: Int, $nextToken: String) { "
    "listIdpDynastyValuesBySeason(season: $season, limit: $limit, nextToken: $nextToken) "
    "{ items { playerId sk season position family team name sleeperPlayerId value posRank "
    "sourceUpdatedAt updatedAt } nextToken } }"
)
#: Only the dynasty fields.  The snapshot's KTC and redraft fields are never
#: selected: KTC is its own registered source, redraft is the seasonal lane.
_OFFENSE_FIELDS = "playerId date signalsDynastyValue signalsDynastyPosRank updatedAt"


def _offense_batch_query(n: int, since: str) -> str:
    if not _DATE_RE.match(since):
        raise ValueError(f"bad lookback date {since!r}")
    decl = ", ".join(f"$p{i}: String!" for i in range(n))
    fields = " ".join(
        f's{i}: listSnapshotsByPlayer(playerId: $p{i}, date: {{ge: "{since}"}}, '
        f"sortDirection: DESC, limit: 2) {{ items {{ {_OFFENSE_FIELDS} }} }}"
        for i in range(n)
    )
    return f"query SignalsOffenseValues({decl}) {{ {fields} }}"


def fetch_idp_items(
    client: AppSyncClient, *, season: int, sleep: Callable[[float], None] = time.sleep
) -> tuple[list[dict[str, Any]], list[Any]]:
    items: list[dict[str, Any]] = []
    raw_pages: list[Any] = []
    token: str | None = None
    for page in range(IDP_MAX_PAGES):
        if page:
            sleep(REQUEST_PAUSE_SECONDS)
        data = client.query(
            _IDP_QUERY, {"season": season, "limit": IDP_PAGE_LIMIT, "nextToken": token}
        )
        raw_pages.append(data)
        conn = data.get("listIdpDynastyValuesBySeason")
        if not isinstance(conn, Mapping) or not isinstance(conn.get("items"), list):
            raise ValuesStop("schema_drift", "listIdpDynastyValuesBySeason shape changed")
        items.extend(i for i in conn["items"] if i is not None)
        token = conn.get("nextToken") or None
        if not token:
            return items, raw_pages
    raise ValuesStop("pagination_unbounded", f"more than {IDP_MAX_PAGES} pages")


def fetch_offense_snapshots(
    client: AppSyncClient,
    player_ids: Sequence[str],
    *,
    since: str,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, list[dict[str, Any]]], list[Any]]:
    results: dict[str, list[dict[str, Any]]] = {}
    raw_pages: list[Any] = []
    ids = [str(p) for p in player_ids if _SID_RE.match(str(p))]
    for start in range(0, len(ids), OFFENSE_BATCH_SIZE):
        if start:
            sleep(REQUEST_PAUSE_SECONDS)
        batch = ids[start : start + OFFENSE_BATCH_SIZE]
        data = client.query(
            _offense_batch_query(len(batch), since), {f"p{i}": sid for i, sid in enumerate(batch)}
        )
        raw_pages.append(data)
        for i, sid in enumerate(batch):
            conn = data.get(f"s{i}")
            if conn is None:
                continue
            if not isinstance(conn, Mapping) or not isinstance(conn.get("items"), list):
                raise ValuesStop("schema_drift", "listSnapshotsByPlayer shape changed")
            snaps = [s for s in conn["items"] if s is not None]
            if snaps:
                results[sid] = snaps
    return results, raw_pages


# ── Collection ────────────────────────────────────────────────────────────


def default_season(now: datetime) -> int:
    """The dynasty season board in force: the calendar year from March on
    (the board keyed ``2026#dynasty`` was live on 2026-10-03).  An empty
    board for this season quarantines rather than guessing another one."""
    return now.year if now.month >= 3 else now.year - 1


def _value_board_key(spec: ValueDatasetSpec) -> str:
    return f"{VALUES_DIR}/{spec.key}"


def _record_value_dataset_state(
    source_key: str,
    *,
    state_dir: Path,
    csv_path: Path,
    health: str,
    at: datetime,
    upstream_published_at: str | None,
    errors: Sequence[str] = (),
) -> None:
    """Fold into the shared three-clock owner (``src.sources.dataset_state``).

    HEALTHY reads the board CSV just written, with the vendor's own stamp as
    the upstream clock.  A quarantine records DEGRADED and moves no clock, so
    the last good board keeps its true age.  Rows are not tracked."""
    from src.sources import dataset_state as DS  # noqa: PLC0415
    from src.sources.dataset_integrity import ParsedBoard  # noqa: PLC0415

    if health == "HEALTHY":
        DS.record_source_file(
            source_key=source_key,
            csv_path=csv_path,
            signal="rank",
            state_dir=state_dir,
            observed_at=at,
            upstream_published_at=upstream_published_at,
            track_rows=False,
        )
        return
    board = ParsedBoard(health=health, errors=list(errors)[:10])
    path = DS.state_path(state_dir, source_key)
    DS.save_state(
        path,
        DS.observe(
            DS.load_state(path),
            source_key=source_key,
            board=board,
            observed_at=at,
            track_rows=False,
        ),
    )


def _write_last_success(state_dir: Path, source_key: str, at: datetime) -> None:
    atomic_write_bytes(
        Path(state_dir) / f"{source_key}_last_success",
        f"{int(at.timestamp())}\n".encode("ascii"),
    )


def _write_raw_values(store: SignalsStore, board_key: str, raw_sha: str, blob: bytes) -> None:
    path = store.board_dir(board_key) / "raw" / f"{raw_sha}.json.gz"
    if not path.exists():
        atomic_write_bytes(path, gzip.compress(blob, mtime=0))


def collect_value_dataset(
    spec: ValueDatasetSpec,
    store_root: Path,
    client: AppSyncClient,
    *,
    state_dir: Path,
    universe: Mapping[str, Mapping[str, Any]] | None = None,
    season: int | None = None,
    now: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect one authenticated value dataset.

    HTTP, auth and schema failures are OUTCOMES, never exceptions — except
    an auth stop, which is recorded and then re-raised so the caller stops
    the whole run.  A refused release leaves the last good board CSV (and
    its true age) untouched.

    Outcomes: ``published`` · ``unchanged_content`` · ``quarantined`` ·
    ``auth_unavailable`` · ``access_denied`` · ``rate_limited`` ·
    ``fetch_failed`` · ``request_budget_exhausted`` · ``no_universe``
    """
    store = SignalsStore(Path(store_root))
    board_key = _value_board_key(spec)
    fstate = store.fetch_state(board_key)
    latest = store.latest(board_key)
    started = now()
    outcome: dict[str, Any] = {"dataset": spec.key, "sourceKey": spec.source_key}
    csv_paths = {k: board_csv_path(Path(store_root), k) for k in spec.output_keys()}
    raw_pages: list[Any] = []
    stop: ValuesStop | None = None
    obs: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    excluded: dict[str, int] = {}
    as_of: str | None = None
    publication: str | None = None
    try:
        if spec.key == "idp":
            season = season if season is not None else default_season(started)
            items, raw_pages = fetch_idp_items(client, season=season, sleep=sleep)
            obs, errors, warnings, excluded = normalize_idp_items(items, spec, season=season)
            stamps = [str(o["valueAsOf"]) for o in obs if o.get("valueAsOf")]
            as_of = max(stamps) if stamps else None
        else:
            if not universe:
                raise ValuesStop("no_universe", "no raw payload with offense Sleeper ids")
            since = datetime.fromordinal(started.date().toordinal() - OFFENSE_LOOKBACK_DAYS)
            results, raw_pages = fetch_offense_snapshots(
                client, sorted(universe), since=since.date().isoformat(), sleep=sleep
            )
            obs, publication, errors, warnings, excluded = normalize_offense_snapshots(
                results, universe, spec
            )
            stamps = [str(o["valueAsOf"]) for o in obs if o.get("valueAsOf")]
            as_of = max(stamps) if stamps else publication
    except ValuesStop as exc:
        stop = exc
        if exc.outcome in ("schema_drift", "pagination_unbounded"):
            errors = [f"{exc.outcome}: {exc.reason}"]
    at = now()
    fstate["lastAttemptAt"] = iso(at)
    fstate["parserVersion"] = VALUES_PARSER_VERSION

    raw_blob = json.dumps(raw_pages, sort_keys=True, ensure_ascii=False).encode("utf-8")
    raw_sha = hashlib.sha256(raw_blob).hexdigest()
    rows: list[dict[str, Any]] = []
    boards: dict[str, list[dict[str, Any]]] = {k: [] for k in csv_paths}
    if not errors and stop is None:
        rows, more = build_board_rows(obs, spec)
        for k, v in more.items():
            excluded[k] = excluded.get(k, 0) + v
        for r in rows:
            boards[str(spec.board_key_for(r))].append(r)
        last_counts = (latest or {}).get("boardRowCounts") or {}
        # Every board must stand on its own: one family collapsing withholds
        # the whole release (all boards keep their last good copy).
        for key, board_rows in boards.items():
            floor = MIN_BOARD_ROWS.get(key, 1)
            last_count = last_counts.get(key)
            if not board_rows:
                errors.append(f"{key}: no voting rows after the selection hierarchy")
            elif len(board_rows) < floor:
                errors.append(f"{key}: below board floor: {len(board_rows)} voting rows < {floor}")
            elif last_count and len(board_rows) < last_count * ROW_COLLAPSE_FRACTION:
                errors.append(
                    f"{key}: row-count collapse: {len(board_rows)} vs last good {last_count}"
                )

    if errors:
        if raw_pages:
            _write_raw_values(store, board_key, raw_sha, raw_blob)
        store.quarantine(
            board_key,
            raw_sha,
            {
                "dataset": spec.key,
                "quarantinedAt": iso(at),
                "rawSha256": raw_sha if raw_pages else None,
                "parserVersion": VALUES_PARSER_VERSION,
                "observationCount": len(obs),
                "errors": errors[:25],
                "warnings": warnings[:25],
            },
        )
        for key, path in csv_paths.items():
            _record_value_dataset_state(
                key,
                state_dir=state_dir,
                csv_path=path,
                health="DEGRADED",
                at=at,
                upstream_published_at=None,
                errors=errors,
            )
        outcome.update(outcome="quarantined", errors=errors[:10])
    elif stop is not None:
        outcome.update(outcome=stop.outcome, reason=stop.reason)
    else:
        csha = board_content_sha256(rows, as_of)
        counts: dict[str, int] = {}
        for r in rows:
            counts[str(r["basis"])] = counts.get(str(r["basis"]), 0) + 1
        if (
            latest is not None
            and latest.get("contentSha256") == csha
            and all(p.is_file() for p in csv_paths.values())
        ):
            fstate["lastVerifiedUnchangedAt"] = iso(at)
            outcome.update(outcome="unchanged_content", contentSha256=csha, rowCount=len(rows))
        else:
            _write_raw_values(store, board_key, raw_sha, raw_blob)
            release = {
                "schemaVersion": VALUES_SCHEMA_VERSION,
                "provider": PROVIDER,
                "dataset": spec.key,
                "sourceKey": spec.source_key,
                "metadata": value_dataset_metadata(spec),
                "season": season,
                "publicationDate": publication,
                "asOf": as_of,
                "fetchedAt": iso(at),
                "parserVersion": VALUES_PARSER_VERSION,
                "rawSha256": raw_sha,
                "contentSha256": csha,
                "previousContentSha256": (latest or {}).get("contentSha256"),
                "rowCount": len(rows),
                "boardRowCounts": {k: len(v) for k, v in boards.items()},
                "basisCounts": counts,
                "excluded": excluded,
                "warnings": warnings[:25],
                "observations": obs,
                "boardRows": rows,
            }
            # The CSV is written before latest.json: a crash between the two
            # leaves latest.json at the previous release, so the next run
            # republishes instead of trusting a CSV latest.json does not match.
            for key, path in csv_paths.items():
                atomic_write_bytes(path, render_board_csv(boards[key]).encode("utf-8"))
            store.publish_release(board_key, release)
            fstate["lastGoodContentSha256"] = csha
            fstate["lastPublishedAt"] = iso(at)
            outcome.update(
                outcome="published",
                contentSha256=csha,
                rowCount=len(rows),
                boardRowCounts={k: len(v) for k, v in boards.items()},
                basisCounts=counts,
                excluded=excluded,
            )
        outcome["asOf"] = as_of
        for key, path in csv_paths.items():
            _record_value_dataset_state(
                key,
                state_dir=state_dir,
                csv_path=path,
                health="HEALTHY",
                at=at,
                upstream_published_at=as_of,
            )
            _write_last_success(state_dir, key, at)

    fstate["lastOutcome"] = outcome.get("outcome")
    if outcome.get("outcome") in ("published", "unchanged_content"):
        fstate["consecutiveFailures"] = 0
    else:
        fstate["consecutiveFailures"] = int(fstate.get("consecutiveFailures") or 0) + 1
    store.save_fetch_state(board_key, fstate)
    if stop is not None and stop.outcome in ("auth_unavailable", "access_denied"):
        raise stop
    return outcome


def collect_values(
    store_root: Path,
    *,
    repo_root: Path,
    state_dir: Path,
    tokens: Any = None,
    http_post: HttpPost = urllib_post,
    datasets: Sequence[str] = ("offense", "idp"),
    season: int | None = None,
    now: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
    min_interval_hours: float | None = None,
    force: bool = False,
    max_requests: int = MAX_VALUE_REQUESTS_PER_RUN,
) -> dict[str, Any]:
    """One authenticated collection run.  Writes the provisioning marker on
    every run that reaches the network decision, including an auth stop."""
    root = values_root(Path(store_root))
    marker = root / PROVISIONED_MARKER
    prior = _read_json(marker) if marker.exists() else None
    prior = prior if isinstance(prior, dict) else {}
    started = now()
    last_ok = parse_iso(prior.get("lastSuccessAt"))
    summary: dict[str, Any] = {"startedAt": iso(started), "datasets": {}}
    if (
        min_interval_hours
        and not force
        and last_ok is not None
        and (started - last_ok).total_seconds() < min_interval_hours * 3600
    ):
        summary["skipped"] = f"last successful run {iso(last_ok)}"
        summary["ok"] = True
        return summary
    if tokens is None:
        tokens = SignalsAuthTokens()
    client = AppSyncClient(
        tokens, http_post=http_post, sleep=sleep, now=now, max_requests=max_requests
    )
    universe: dict[str, dict[str, Any]] | None = None
    if "offense" in datasets:
        payload, payload_path = newest_raw_payload(repo_root)
        universe = offense_universe_from_payload(payload)
        summary["offenseUniverse"] = {
            "players": len(universe),
            "payload": payload_path.name if payload_path else None,
        }
    for key in datasets:
        try:
            summary["datasets"][key] = collect_value_dataset(
                VALUE_DATASETS[key],
                Path(store_root),
                client,
                state_dir=state_dir,
                universe=universe,
                season=season,
                now=now,
                sleep=sleep,
            )
        except ValuesStop as exc:
            summary["datasets"][key] = {"outcome": exc.outcome, "reason": exc.reason}
            summary["stopped"] = exc.outcome
            break
    ok = len(summary["datasets"]) == len(datasets) and all(
        d.get("outcome") in ("published", "unchanged_content") for d in summary["datasets"].values()
    )
    summary["requests"] = client.requests
    summary["ok"] = ok
    atomic_write_json(
        marker,
        {
            "schemaVersion": VALUES_SCHEMA_VERSION,
            "provider": PROVIDER,
            "lastRunAt": summary["startedAt"],
            "lastRunOk": ok,
            "lastSuccessAt": summary["startedAt"] if ok else prior.get("lastSuccessAt"),
            "datasets": {
                k: {kk: v.get(kk) for kk in ("outcome", "reason", "rowCount", "asOf")}
                for k, v in summary["datasets"].items()
            },
            "requests": client.requests,
        },
    )
    return summary
