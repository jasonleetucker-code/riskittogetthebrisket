"""Word boxes -> lines -> trade sides.

Tesseract reads words; it does not know that a screenshot is two lists side
by side.  This module rebuilds that structure from geometry, and it is
deliberately conservative: when the evidence for which side a line belongs to
is weak, the line goes to ``unassigned`` for the person to place.  It never
guesses a side.

Evidence, strongest first:

1. **Side-label anchors** — "You give / You get", "Send / Receive",
   "Team A / Team B", "Team 1 gets... / Team 2 gets...", ... .  Two anchors
   side by side -> ``two_column``; one above the other -> ``stacked``.
   A pair of anchors also defines the TRADE REGION: one container per side,
   derived from geometry alone (see :func:`_side_containers`).  Only lines
   inside a container can be assets; everything else on the page — browser
   chrome, site navigation, recommendation / insight widgets, ads — goes to
   ``ignored`` as ``outside_trade_region`` and is never offered as
   "needs a side".  This is what makes an ordinary uncropped screenshot
   work without manual cropping.  ONE anchor (the other was not read) is
   weaker: only lines left-aligned under it take its side, and the rest stay
   unassigned — no second side is inferred from position.
2. **Column geometry** — with no anchors, a clean two-cluster split of line
   left edges whose rows overlap vertically -> ``two_column`` with
   ``label_source="position"`` and a confidence just above the floor.
3. Anything else -> ``single`` / ``unknown`` below the 0.6 floor: no sides,
   every candidate line ``unassigned``.

Noise never becomes an item: value numbers ("4,512", "+312"), percentages,
grades, totals/verdict labels, navigation chrome, and everything below an
equalizer header ("Suggested", "Add to even", ...) in the same side go to
``ignored`` WITH a reason, so nothing disappears silently.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from src.trade.screenshot_import.ocr import Word

CONFIDENCE_FLOOR = 0.6
SEGMENT_GAP_FACTOR = 1.8  # x median word height: a wider gap starts a new segment

# Trade-region geometry, all in multiples of the page's median line height so
# nothing depends on one screenshot's resolution.
REGION_EDGE_TOLERANCE = 2.5  # a container reaches this far past its column
REGION_GAP_FACTOR = 8.0  # a vertical gap this large ends a side's container

REASON_OUTSIDE_REGION = "outside_trade_region"

KIND_TWO_COLUMN = "two_column"
KIND_STACKED = "stacked"
KIND_SINGLE = "single"
KIND_UNKNOWN = "unknown"

LABEL_ANCHOR = "anchor"
LABEL_POSITION = "position"
LABEL_NONE = "none"


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]
    row: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def left(self) -> int:
        return min(w.left for w in self.words)

    @property
    def right(self) -> int:
        return max(w.right for w in self.words)

    @property
    def top(self) -> int:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> int:
        return max(w.bottom for w in self.words)

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def conf(self) -> float:
        """Mean word confidence on a 0..1 scale."""
        return round(sum(w.conf for w in self.words) / (100.0 * len(self.words)), 3)


@dataclass(frozen=True)
class SideBlock:
    label: str
    label_source: str
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class Layout:
    kind: str
    confidence: float
    sides: tuple[SideBlock, ...] = ()
    unassigned: tuple[Line, ...] = ()
    ignored: tuple[tuple[Line, str], ...] = ()
    anchors: tuple[Line, ...] = field(default=())


# ── Lines ───────────────────────────────────────────────────────────────


def _median(values: Iterable[float], default: float = 1.0) -> float:
    vals = [v for v in values if v > 0]
    return float(statistics.median(vals)) if vals else default


def build_lines(words: Sequence[Word]) -> list[Line]:
    """Group words into visual rows, then split each row into segments at
    gaps wider than ``SEGMENT_GAP_FACTOR`` x the median word height — so one
    visual row of a two-column screenshot yields two segments.  Returned in
    reading order (row, then left)."""
    ws = [w for w in words if w.text.strip() and w.width > 0 and w.height > 0]
    if not ws:
        return []
    med_h = _median(w.height for w in ws)
    rows: list[list[Word]] = []
    row_cy: list[float] = []
    row_h: list[float] = []
    for w in sorted(ws, key=lambda w: (w.top + w.height / 2.0, w.left)):
        wcy = w.top + w.height / 2.0
        best = None
        best_d = None
        for i in range(max(0, len(rows) - 4), len(rows)):
            d = abs(wcy - row_cy[i])
            if d <= 0.5 * max(w.height, row_h[i]) and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is None:
            rows.append([w])
            row_cy.append(wcy)
            row_h.append(float(w.height))
        else:
            rows[best].append(w)
            n = len(rows[best])
            row_cy[best] = row_cy[best] + (wcy - row_cy[best]) / n
            row_h[best] = row_h[best] + (w.height - row_h[best]) / n
    order = sorted(range(len(rows)), key=lambda i: row_cy[i])
    lines: list[Line] = []
    for row_idx, i in enumerate(order):
        row_words = sorted(rows[i], key=lambda w: w.left)
        seg: list[Word] = [row_words[0]]
        for w in row_words[1:]:
            gap = w.left - max(x.right for x in seg)
            if gap > SEGMENT_GAP_FACTOR * med_h:
                lines.append(Line(tuple(seg), row_idx))
                seg = [w]
            else:
                seg.append(w)
        lines.append(Line(tuple(seg), row_idx))
    lines.sort(key=lambda ln: (ln.row, ln.left))
    return lines


# ── Text classification ─────────────────────────────────────────────────

_ANCHOR_FAMILIES: tuple[tuple[str, str], ...] = (
    ("you give", "you get"),
    ("they give", "they get"),
    ("give", "get"),
    ("you send", "you receive"),
    ("send", "receive"),
    ("sending", "receiving"),
    ("team a", "team b"),
    ("team 1", "team 2"),
    ("trade away", "trade for"),
    ("side a", "side b"),
    ("giving", "getting"),
    ("you trade", "you receive"),
)
_ANCHOR_TAIL_OK = frozenset(
    {"gives", "gets", "give", "get", "receives", "receive", "sends", "send", "trades", "total"}
)
_EQUALIZER_PREFIXES = (
    "suggested",
    "suggestion",
    "recommended",
    "add to even",
    "players to balance",
    "assets to balance",
    "equalizer",
    "to even it",
    "balance the trade",
    "even it out",
)
_LABEL_WORDS = frozenset(
    {
        "total",
        "totals",
        "value",
        "values",
        "value adjustment",
        "trade value",
        "adjustment",
        "adjusted value",
        "difference",
        "net",
        "fair",
        "fair trade",
        "win win",
        "accept",
        "decline",
        "submit",
        "clear",
        "reset",
        "share",
        "save",
        "cancel",
        "swap",
        "swap sides",
        "trade",
        "trade calculator",
        "calculator",
        "vs",
        "players",
        "picks",
        "add player",
        "add players",
        "add asset",
        "add assets",
        "search",
        "filter",
        "grade",
        "trade grade",
        "verdict",
        "analysis",
        "analyze",
        "evaluate",
        "propose",
        "propose trade",
        "send trade",
        "counter",
        "lopsided",
        "even",
        "slightly favors",
    }
)
_LABEL_PREFIXES = (
    "total",
    "value adjustment",
    "trade value",
    "value",
    "grade",
    "difference",
    "net",
    "adjustment",
    "favors",
    "slightly favors",
)
_NAV_WORDS = frozenset(
    {
        "home",
        "settings",
        "login",
        "log in",
        "logout",
        "log out",
        "sign in",
        "sign up",
        "menu",
        "back",
        "profile",
        "account",
        "rankings",
        "leagues",
        "more",
        "help",
        "close",
        "done",
        "next",
    }
)
# Lines that END a side's container: the totals row, the verdict, and the
# action buttons every calculator puts under the lists.  Matched on the
# normalised text's leading words (or, for totals, a "total" word with only
# counts / units around it), never on a single short word inside a name.
_BOUNDARY_PREFIXES = (
    "fair trade",
    "this trade",
    "trade is",
    "even trade",
    "favors",
    "slightly favors",
    "you win",
    "you lose",
    "win win",
    "lopsided",
    "great trade",
    "good trade",
    "bad trade",
    "copy trade",
    "copy link",
    "share trade",
    "clear calculator",
    "clear trade",
    "clear all",
    "reset trade",
    "swap sides",
    "propose trade",
    "send trade",
    "submit trade",
    "save trade",
    "accept",
    "decline",
)
_TOTAL_UNITS = frozenset(
    {"total", "totals", "pieces", "piece", "assets", "players", "picks", "value", "items"}
)
_SEARCH_PREFIXES = (
    "search for",
    "search player",
    "search players",
    "search a player",
    "add a player",
)
_VALUE_LINE_RE = re.compile(r"^[+\-−±~≈]?\s?\$?[\d][\d,\.\s]*[kK]?$")
_PERCENT_RE = re.compile(r"^[+\-−±]?\s?\d+(?:[\.,]\d+)?\s?%$")
_GRADE_RE = re.compile(r"^[A-F][+\-−]?$")
_YEAR_LEAD_RE = re.compile(r"^\s*20\d{2}\s")


def _norm(text: str) -> str:
    s = text.lower().replace("-", " ").replace("–", " ").replace("—", " ")
    s = re.sub(r"[^a-z0-9%+ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_anchor(text: str) -> tuple[int, int] | None:
    """``(family_index, slot)`` when ``text`` is a side label, else None.
    ``slot`` 0 is the family's first side ("give"), 1 its second ("get")."""
    tokens = _norm(text).replace("+", " ").split()
    if not tokens:
        return None
    best: tuple[int, int, int] | None = None  # (phrase_len, family, slot)
    for fam, pair in enumerate(_ANCHOR_FAMILIES):
        for slot, phrase in enumerate(pair):
            ptoks = phrase.split()
            if tokens[: len(ptoks)] != ptoks:
                continue
            tail = tokens[len(ptoks) :]
            if all(t.isdigit() or t in _ANCHOR_TAIL_OK for t in tail):
                if best is None or len(ptoks) > best[0]:
                    best = (len(ptoks), fam, slot)
    return (best[1], best[2]) if best else None


def is_total_line(text: str) -> bool:
    """``"1 Total Pieces"``, ``"Total: 7,200"``, ``"Totals"`` — a totals row."""
    toks = _norm(text).replace("+", " ").split()
    if not any(t in ("total", "totals") for t in toks):
        return False
    return all(t in _TOTAL_UNITS or t.replace(",", "").isdigit() for t in toks)


def is_region_boundary(text: str) -> bool:
    """True for a line that closes a side's container (totals, verdict,
    action buttons)."""
    if is_total_line(text):
        return True
    n = _norm(text)
    return any(n == p or n.startswith(p + " ") for p in _BOUNDARY_PREFIXES)


def is_equalizer_header(text: str) -> bool:
    n = _norm(text)
    return any(n.startswith(p) for p in _EQUALIZER_PREFIXES)


def classify_noise(text: str) -> str | None:
    """Why a line is noise (``value_number``, ``percentage``, ``grade``,
    ``label``, ``navigation``), or None when it might be an asset."""
    raw = text.strip()
    if not raw:
        return "empty"
    compact = raw.replace(" ", "")
    if _PERCENT_RE.match(raw) or (
        "%" in raw and sum(c.isalpha() for c in raw) <= 2 and any(c.isdigit() for c in raw)
    ):
        return "percentage"
    if (
        _VALUE_LINE_RE.match(raw)
        and any(c.isdigit() for c in raw)
        # "2028 1.05" is a pick slot, not a value: a leading draft year
        # followed by more tokens is left for the pick parser.
        and not (_YEAR_LEAD_RE.match(raw) and len(raw.split()) >= 2)
    ):
        return "value_number"
    if _GRADE_RE.match(compact):
        return "grade"
    n = _norm(raw)
    if n in _NAV_WORDS:
        return "navigation"
    if any(n == p or n.startswith(p + " ") for p in _SEARCH_PREFIXES):
        return "search_placeholder"
    if is_total_line(raw):
        return "label"
    if n in _LABEL_WORDS:
        return "label"
    for p in _LABEL_PREFIXES:
        if n.startswith(p + " "):
            tail = n[len(p) :].split()
            # "Total 7 200", "Value Adjustment +312", "Grade A+" — a label
            # followed only by numbers / short marks, never by another word.
            if not any(sum(c.isalpha() for c in t) >= 3 for t in tail):
                return "label"
    return None


# ── Layout ──────────────────────────────────────────────────────────────


def _split_line_at(line: Line, x: float) -> tuple[Line, Line] | None:
    left = tuple(w for w in line.words if w.right <= x)
    right = tuple(w for w in line.words if w.left >= x)
    if left and right and len(left) + len(right) == len(line.words):
        return Line(left, line.row), Line(right, line.row)
    return None


def _split_double_anchor(line: Line) -> tuple[Line, Line] | None:
    """``"You give You get"`` read as one segment -> two anchor lines."""
    words = line.words
    for k in range(1, len(words)):
        a, b = Line(words[:k], line.row), Line(words[k:], line.row)
        ma, mb = match_anchor(a.text), match_anchor(b.text)
        if ma and mb and ma != mb:
            return a, b
    return None


def _clusters_by_left(lines: Sequence[Line], width: float) -> tuple[list[Line], list[Line]] | None:
    """Two left-edge clusters separated by a gap >= 20% of the width, each
    tightly aligned, else None."""
    if len(lines) < 2:
        return None
    ordered = sorted(lines, key=lambda ln: ln.left)
    gaps = [(ordered[i + 1].left - ordered[i].left, i) for i in range(len(ordered) - 1)]
    gap, idx = max(gaps)
    if gap < 0.2 * width:
        return None
    left, right = ordered[: idx + 1], ordered[idx + 1 :]
    for cluster in (left, right):
        lefts = [ln.left for ln in cluster]
        if max(lefts) - min(lefts) > 0.15 * width:
            return None
    return left, right


def _vertical_overlap(a: Sequence[Line], b: Sequence[Line], tol: float) -> float:
    a_top, a_bot = min(ln.top for ln in a), max(ln.bottom for ln in a)
    b_top, b_bot = min(ln.top for ln in b), max(ln.bottom for ln in b)
    overlap = min(a_bot, b_bot) - max(a_top, b_top) + tol
    shortest = min(a_bot - a_top, b_bot - b_top) + tol
    return max(0.0, overlap) / shortest if shortest > 0 else 0.0


# ── Trade region ────────────────────────────────────────────────────────

OUTSIDE = -1  # assign() key: inside a detected trade region's page, outside every container


@dataclass(frozen=True)
class Container:
    """One side's container: lines whose LEFT edge is in ``[x0, x1)`` and
    whose top is in ``[top, bottom)``."""

    x0: float
    x1: float
    top: float
    bottom: float

    def contains(self, ln: Line) -> bool:
        return self.x0 <= ln.left < self.x1 and self.top <= ln.top < self.bottom


def _overlaps_x(ln: Line, x0: float, x1: float) -> bool:
    return min(ln.right, x1) - max(ln.left, x0) > 0


def _container_bottom(
    lines: Sequence[Line],
    x0: float,
    x1: float,
    start: float,
    limit: float,
    med_h: float,
) -> tuple[float, bool]:
    """Where a side's container ends below ``start`` (the header's bottom):
    the first region boundary (totals / verdict / buttons) overlapping the
    column, or the first vertical gap wider than ``REGION_GAP_FACTOR`` line
    heights between lines of the column, else ``limit``.  Returns
    ``(bottom, ended_on_boundary)``."""
    below = sorted((ln for ln in lines if ln.top > start and ln.top < limit), key=lambda ln: ln.top)
    bottom = limit
    by_boundary = False
    for ln in below:
        if _overlaps_x(ln, x0, x1) and is_region_boundary(ln.text):
            bottom, by_boundary = ln.top, True
            break
    prev = start
    for ln in below:
        if ln.top >= bottom:
            break
        if not (x0 <= ln.left < x1):
            continue
        if ln.top - prev > REGION_GAP_FACTOR * med_h:
            return ln.top, False
        prev = max(prev, ln.bottom)
    return bottom, by_boundary


def _side_containers(
    a: Line,
    b: Line,
    side_by_side: bool,
    lines: Sequence[Line],
    width: float,
    med_h: float,
    is_asset: Callable[[str], bool],
) -> tuple[Container, Container]:
    """The two sides' containers, from the two side labels' geometry only.

    Side by side: the columns are centred on the labels, split half-way
    between the label centres, each as wide as the label pitch (plus a
    tolerance) — so a left-aligned list under a left-aligned label and a
    list under a centred label both fall inside, and a widget beside the
    second column (insights, ads) falls outside.  Stacked: one full-width
    column, the first side ending where the second label starts.  Both end
    at the first boundary line / large gap below their label (a side with
    no boundary of its own shares the other side's, which is how a
    calculator draws one totals row under both lists).

    When the list under a label is LEFT-ALIGNED with it (an asset line
    starts within the tolerance of the label's left edge), that column's
    left edge tightens to the label's, so a navigation sidebar beside the
    first column stays out.
    """
    tol = REGION_EDGE_TOLERANCE * med_h
    inf = float("inf")
    if side_by_side:
        pitch = max(b.cx - a.cx, 1.0)
        split = (a.cx + b.cx) / 2.0
        spans = ((a.cx - pitch / 2.0 - tol, split), (split, b.cx + pitch / 2.0 + tol))
        top = min(a.top, b.top) - 0.5 * med_h
        start = max(a.bottom, b.bottom)
        ends = [_container_bottom(lines, x0, x1, start, inf, med_h) for x0, x1 in spans]
        shared = [bot for bot, by_boundary in ends if by_boundary]
        bottoms = []
        for bot, by_boundary in ends:
            if not by_boundary and shared:
                bot = min(bot, min(shared))
            bottoms.append(bot)
        out = []
        for (x0, x1), bot, hdr in zip(spans, bottoms, (a, b)):
            aligned = any(
                abs(ln.left - hdr.left) <= tol
                and x0 <= ln.left < x1
                and hdr.bottom < ln.top < bot
                and is_asset(ln.text)
                for ln in lines
            )
            out.append(Container(max(x0, hdr.left - tol) if aligned else x0, x1, top, bot))
        return out[0], out[1]
    x0 = min(a.left, b.left) - tol
    x1 = width + 1.0
    a_top, b_top = a.top - 0.5 * med_h, b.top - 0.5 * med_h
    a_bot, _ = _container_bottom(lines, x0, x1, a.bottom, b_top, med_h)
    b_bot, _ = _container_bottom(lines, x0, x1, b.bottom, inf, med_h)
    return Container(x0, x1, a_top, a_bot), Container(x0, x1, b_top, b_bot)


def _single_container(anc: Line, lines: Sequence[Line], width: float, med_h: float) -> Container:
    """The container under ONE side label (the other was not read)."""
    tol = REGION_EDGE_TOLERANCE * med_h
    x0 = anc.left - tol
    bottom, _ = _container_bottom(lines, x0, width + 1.0, anc.bottom, float("inf"), med_h)
    return Container(x0, width + 1.0, anc.top - 0.5 * med_h, bottom)


def _container_assigner(
    containers: Sequence[Container], split_x: float | None
) -> Callable[[Line], list[int | None]]:
    def assign(ln: Line) -> list[int | None]:
        hits = [i for i, c in enumerate(containers) if c.contains(ln)]
        if hits:
            return hits[:1]
        if (
            split_x is not None
            and len(containers) == 2
            and ln.left < split_x < ln.right
            and (ln.right - split_x) > 0.25 * (ln.right - ln.left)
            and containers[0].top <= ln.top < max(c.bottom for c in containers)
        ):
            return [0, 1]  # straddles both columns (only meaningful for headers)
        return [OUTSIDE]

    return assign


def _default_asset_like(text: str) -> bool:
    from src.trade.screenshot_import.parse import is_asset_like  # noqa: PLC0415

    return is_asset_like(text)


def _clean_label(text: str) -> str:
    s = re.sub(r"[\s:]*[+\-−]?\$?[\d,\.]+\s*$", "", text).strip(" :|-")
    return s or text.strip()


def detect_layout(
    lines: Sequence[Line],
    image_width: int,
    *,
    asset_like: Callable[[str], bool] | None = None,
) -> Layout:
    """Assign candidate lines to sides; see the module docstring."""
    is_asset = asset_like or _default_asset_like
    width = float(max(1, image_width))
    med_h = _median((ln.height for ln in lines), default=10.0)

    # Split "You give You get" segments into two anchors first.
    expanded: list[Line] = []
    for ln in lines:
        pair = (
            _split_double_anchor(ln) if len(ln.words) >= 2 and not match_anchor(ln.text) else None
        )
        expanded.extend(pair if pair else (ln,))

    anchors: list[tuple[Line, int, int]] = []
    headers: list[Line] = []
    ignored: list[tuple[Line, str]] = []
    candidates: list[Line] = []
    for ln in expanded:
        m = match_anchor(ln.text)
        if m is not None:
            anchors.append((ln, m[0], m[1]))
            continue
        if is_equalizer_header(ln.text):
            headers.append(ln)
            continue
        reason = classify_noise(ln.text)
        if reason is not None:
            ignored.append((ln, reason))
            continue
        candidates.append(ln)

    # ── Choose the anchor pair ──
    pair: tuple[tuple[Line, int, int], tuple[Line, int, int]] | None = None
    same_family = False
    for i, a in enumerate(anchors):
        for b in anchors[i + 1 :]:
            if a[1] == b[1] and a[2] != b[2]:
                pair, same_family = (a, b), True
                break
        if pair:
            break
    if pair is None:
        for i, a in enumerate(anchors):
            for b in anchors[i + 1 :]:
                if _norm(a[0].text) != _norm(b[0].text):
                    pair = (a, b)
                    break
            if pair:
                break
    used = {id(p[0]) for p in pair} if pair else set()
    lone_anchor = anchors[0][0] if (pair is None and anchors) else None
    if lone_anchor is not None:
        used.add(id(lone_anchor))
    for a in anchors:
        if id(a[0]) not in used:
            ignored.append((a[0], "side_label_unused"))

    kind = KIND_UNKNOWN
    confidence = 0.3
    side_specs: list[tuple[str, str]] = []  # (label, label_source)
    assign: Callable[[Line], list[int | None]]

    def _unassigned(_ln: Line) -> list[int | None]:
        return [None]

    assign = _unassigned
    split_x: float | None = None

    if pair is not None:
        a, b = pair[0][0], pair[1][0]
        side_by_side = abs(a.cy - b.cy) <= 1.5 * med_h
        if side_by_side:
            if b.left < a.left:
                a, b = b, a
            kind = KIND_TWO_COLUMN
            confidence = 0.95 if same_family else 0.75
        else:
            if b.cy < a.cy:
                a, b = b, a
            kind = KIND_STACKED
            confidence = 0.9 if same_family else 0.75
        side_specs = [
            (_clean_label(a.text), LABEL_ANCHOR),
            (_clean_label(b.text), LABEL_ANCHOR),
        ]
        others = [ln for ln in expanded if id(ln) not in used]
        containers = _side_containers(a, b, side_by_side, others, width, med_h, is_asset)
        if side_by_side:
            split_x = containers[0].x1
        assign = _container_assigner(containers, split_x)

    elif lone_anchor is not None:
        # One label is weaker evidence than a pair: the other side's label may
        # simply not have been read, and its assets may sit anywhere on the
        # page.  So only lines LEFT-ALIGNED under this label, inside its
        # container, take its side; everything else stays unassigned for the
        # person to place.  No second side is inferred from position here — a
        # full page always has some other column (a sidebar, an insights
        # widget) that would pass for one.
        anc = lone_anchor
        kind = KIND_SINGLE
        confidence = 0.7
        side_specs = [(_clean_label(anc.text), LABEL_ANCHOR)]
        tol = REGION_EDGE_TOLERANCE * med_h
        col = _single_container(anc, [ln for ln in expanded if ln is not anc], width, med_h)

        def assign(ln: Line, _c=col, _x=anc.left, _tol=tol) -> list[int | None]:
            if _c.contains(ln) and abs(ln.left - _x) <= _tol:
                return [0]
            return [None]

    else:
        assets = [ln for ln in candidates if is_asset(ln.text)]
        clusters = _clusters_by_left(assets, width)
        if clusters and _vertical_overlap(clusters[0], clusters[1], med_h) >= 0.5:
            left_c, right_c = clusters
            split_x = (max(ln.left for ln in left_c) + min(ln.left for ln in right_c)) / 2.0
            kind = KIND_TWO_COLUMN
            confidence = 0.62
            side_specs = [("Side A", LABEL_POSITION), ("Side B", LABEL_POSITION)]

            def assign(ln: Line, _s=split_x) -> list[int | None]:
                if ln.left < _s < ln.right and (ln.right - _s) > 0.25 * (ln.right - ln.left):
                    return [0, 1]
                return [0] if ln.left < _s else [1]

        elif assets and _clusters_by_left(assets, width) is None and len(assets) >= 1:
            lefts = [ln.left for ln in assets]
            aligned = max(lefts) - min(lefts) <= 0.15 * width
            kind = KIND_SINGLE if aligned else KIND_UNKNOWN
            confidence = 0.5 if aligned else 0.3
        else:
            kind = KIND_UNKNOWN
            confidence = 0.3

    if confidence < CONFIDENCE_FLOOR:
        side_specs = []
        assign = _unassigned

    # Two-column: split candidate segments that straddle the column boundary.
    if split_x is not None and side_specs:
        split_cands: list[Line] = []
        for ln in candidates:
            parts = _split_line_at(ln, split_x) if ln.left < split_x < ln.right else None
            split_cands.extend(parts if parts else (ln,))
        candidates = split_cands

    n_sides = len(side_specs)
    regions: dict[int | None, list[Line]] = {i: [] for i in range(n_sides)}
    regions[None] = []
    for ln in candidates:
        for key in assign(ln)[:1]:
            if key == OUTSIDE:
                ignored.append((ln, REASON_OUTSIDE_REGION))
                continue
            regions[key if key is None or key < n_sides else None].append(ln)
    header_regions: dict[int | None, list[Line]] = {k: [] for k in regions}
    for hd in headers:
        ignored.append((hd, "equalizer_header"))
        for key in assign(hd):
            if key == OUTSIDE:
                continue
            header_regions[key if key is None or key < n_sides else None].append(hd)

    # Equalizer regions: everything after a header within the same side.
    for key, region in regions.items():
        hds = header_regions.get(key) or []
        if not hds:
            continue
        keep: list[Line] = []
        for ln in region:
            masked = False
            for hd in hds:
                if ln.top <= hd.top:
                    continue
                if key is None:
                    lo, hi = hd.left - 0.25 * width, hd.right + 0.25 * width
                    if not (lo <= ln.cx <= hi):
                        continue
                masked = True
                break
            if masked:
                ignored.append((ln, "equalizer_region"))
            else:
                keep.append(ln)
        regions[key] = keep

    def _ordered(ls: Iterable[Line]) -> tuple[Line, ...]:
        return tuple(sorted(ls, key=lambda ln: (ln.row, ln.left)))

    sides = tuple(
        SideBlock(label=label, label_source=src, lines=_ordered(regions[i]))
        for i, (label, src) in enumerate(side_specs)
    )
    used_anchor_lines = (
        tuple(p[0] for p in pair) if pair else ((lone_anchor,) if lone_anchor else ())
    )
    return Layout(
        kind=kind,
        confidence=round(confidence, 3),
        sides=sides,
        unassigned=_ordered(regions[None]),
        ignored=tuple(sorted(ignored, key=lambda it: (it[0].row, it[0].left))),
        anchors=used_anchor_lines,
    )
