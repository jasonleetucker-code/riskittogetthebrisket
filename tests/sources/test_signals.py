"""Signals Fantasy collection + rank-only second opinion (#1555, Unit A).

Every page in this file is LABELLED SYNTHETIC markup built by
:func:`synthetic_board` — a minimal reproduction of the public board's
STRUCTURE (position sections, tier groups, player rows with a jersey SVG,
rank / name / team / rank-badge / market spans, release card, Nuxt data).
No real Signals page or row is committed; no test touches the network.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.sources import signals as S

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)

# (position, rank, tier label, tier class, name, team, market "QB2" | None, direction)
OFFENSE_ROWS = [
    ("QB", 1, "S+", "tier-splus", "Synthetic Alpha", "BUF", "QB1", "neutral"),
    ("QB", 2, "S", "tier-s", "Synthetic Bravo", "KC", "QB4", "up-strong"),
    ("RB", 1, "S+", "tier-splus", "Synthetic Charlie", "ATL", None, None),
    ("WR", 1, "S+", "tier-splus", "Synthetic Delta", "MIN", "WR2", "up"),
    ("TE", 1, "A", "tier-a", "Synthetic Echo", "FA", "TE1", "down"),
]
IDP_ROWS = [
    ("CB", 1, "S+", "tier-splus", "Synthetic Foxtrot", "HOU", "CB3", "up"),
    ("S", 1, "S+", "tier-splus", "Synthetic Golf", "DET", "S1", "neutral"),
    ("DT", 1, "A", "tier-a", "Synthetic Hotel", "PHI", None, None),
    ("DE", 1, "S", "tier-s", "Synthetic India", "CLE", "DE2", "up"),
    ("LB", 1, "B", "tier-b", "Synthetic Juliet", "SF", "LB1", "neutral"),
]


def synthetic_board(
    rows,
    *,
    heading="// DYNASTY RANKINGS",
    path="/rankings/dynasty",
    published="2026-10-01T01:31:48.554Z",
    market_through="2026-09-30",
    prerendered_ms=1790818661697,
    declared=None,
    drop_positions=(),
    badge_override=None,
):
    """SYNTHETIC page with the public board's markup structure."""
    positions: list[str] = []
    for r in rows:
        if r[0] not in positions:
            positions.append(r[0])
    out = [
        "<!DOCTYPE html><html><head><title>SYNTHETIC Rankings | Signals</title></head><body>",
        '<nav><p class="eyebrow-nav">nav</p></nav>',
        f'<p class="eyebrow" data-v-x>{heading}</p><h1>SYNTHETIC</h1>',
        '<aside class="release-card" aria-label="Ranking freshness"><span>Season 2026</span>',
    ]
    if published:
        out.append(f'<strong>Published <time datetime="{published}">Oct 1</time></strong>')
    if market_through:
        out.append(f"<span>Market data through {market_through}</span>")
    out.append("<span>Rebuilt weekly after the market and model refreshes.</span></aside>")
    out.append('<aside class="cta-card"><p class="eyebrow">// CONNECT A LEAGUE FREE</p></aside>')
    out.append('<div class="position-grid">')
    for pos in positions:
        if pos in drop_positions:
            continue
        prow = [r for r in rows if r[0] == pos]
        count = (declared or {}).get(pos, len(prow))
        out.append(
            f'<section class="position-board" aria-labelledby="position-{pos}">'
            f'<header class="position-header"><h2 id="position-{pos}">{pos}</h2>'
            f'<span>{count} players</span></header><div class="tier-stack">'
        )
        current = None
        for _pos, rank, tier, tcls, name, team, mkt, direction in prow:
            if tier != current:
                if current is not None:
                    out.append("</ol></section>")
                out.append(
                    f'<section class="{tcls} tier-group"><h3 class="tier-break">{tier} Tier</h3>'
                    '<ol class="player-list">'
                )
                current = tier
            badge = (badge_override or {}).get((pos, rank), f"{pos}{rank}")
            market = ""
            if mkt:
                market = (
                    f'<span class="market--{direction} market" '
                    f'title="Signals {pos}{rank} vs market {mkt} - synthetic.">MKT {mkt}</span>'
                )
            out.append(
                '<li class="player-row" data-v-x>'
                f'<span class="rank">{rank}</span>'
                '<span class="jersey-tile"><svg class="jersey"><defs><clipPath id="c">'
                '<path d="M0"></path></clipPath></defs><text>99</text>'
                "<strong>not a name</strong></svg></span>"
                f'<span class="player-main"><strong style="font-size:13px;">{name}</strong>'
                f'<span class="player-meta"><span class="team-chip">{team}</span>'
                f'<span class="rank-badge">{badge}</span>{market}</span></span></li>'
            )
        if current is not None:
            out.append("</ol></section>")
        out.append("</div></section>")
    out.append("</div>")
    nuxt = [
        {"state": 1, "serverRendered": 2, "path": 3, "prerenderedAt": 4},
        {},
        True,
        path,
        prerendered_ms,
    ]
    out.append(
        '<script type="application/json" id="__NUXT_DATA__">' + json.dumps(nuxt) + "</script>"
    )
    out.append("</body></html>")
    return "".join(out)


def offense_html(**kw):
    return synthetic_board(OFFENSE_ROWS, **kw)


def idp_html(**kw):
    kw.setdefault("heading", "// IDP DYNASTY RANKINGS")
    kw.setdefault("path", "/rankings/idp-dynasty")
    return synthetic_board(IDP_ROWS, **kw)


class FakeHttp:
    """Scripted transport: a queue of responses per URL, plus a call log."""

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        item = self.script[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(html: str, etag='W/"e1"', lm="Thu, 01 Oct 2026 01:38:26 GMT"):
    return 200, {"etag": etag, "last-modified": lm}, html.encode("utf-8")


DYN = S.BOARDS["dynasty"]
IDP = S.BOARDS["idp-dynasty"]


@pytest.fixture
def store(tmp_path: Path) -> S.SignalsStore:
    return S.SignalsStore(tmp_path / "signals")


def _clock(*times):
    it = iter(times)
    last = [None]

    def now():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return now


# ── Parser ───────────────────────────────────────────────────────────────


def test_parser_reads_sections_tiers_market_and_stamps():
    page = S.parse_board_html(offense_html())
    assert page.heading == "// DYNASTY RANKINGS"
    assert page.published_at == "2026-10-01T01:31:48.554Z"
    assert page.market_data_through == "2026-09-30"
    assert page.cadence_claim.startswith("Rebuilt weekly")
    assert page.prerendered_at_ms == 1790818661697
    assert page.nuxt_path == "/rankings/dynasty"
    assert page.sections == ["QB", "RB", "WR", "TE"]
    assert page.declared_counts == {"QB": 2, "RB": 1, "WR": 1, "TE": 1}
    assert page.row_errors == []
    names = [r["name"] for r in page.rows]
    # SVG text (a <strong> inside the jersey) never leaks into a name.
    assert names == [r[4] for r in OFFENSE_ROWS]
    bravo = page.rows[1]
    assert bravo == {
        "documentIndex": 1,
        "position": "QB",
        "positionalRank": 2,
        "tier": "S",
        "tierClass": "tier-s",
        "name": "Synthetic Bravo",
        "team": "KC",
        "rankBadge": "QB2",
        "marketPosition": "QB",
        "marketPositionalRank": 4,
        "marketDirection": "up-strong",
        "marketTitle": "Signals QB2 vs market QB4 - synthetic.",
    }
    charlie = page.rows[2]
    # No market badge on the page → null, never guessed.
    assert charlie["marketPositionalRank"] is None
    assert charlie["marketDirection"] is None
    assert page.rows[4]["team"] == "FA"


def test_parser_is_deterministic():
    html = offense_html()
    a, b = S.parse_board_html(html), S.parse_board_html(html)
    assert a.rows == b.rows
    assert S.content_sha256(a) == S.content_sha256(b)


def test_content_hash_ignores_build_stamp_but_not_rankings():
    base = S.content_sha256(S.parse_board_html(offense_html()))
    rebuilt = S.content_sha256(S.parse_board_html(offense_html(prerendered_ms=1790900000000)))
    assert rebuilt == base
    moved = list(OFFENSE_ROWS)
    moved[0], moved[1] = (
        ("QB", 1, "S+", "tier-splus", "Synthetic Bravo", "KC", "QB4", "up-strong"),
        ("QB", 2, "S", "tier-s", "Synthetic Alpha", "BUF", "QB1", "neutral"),
    )
    assert S.content_sha256(S.parse_board_html(synthetic_board(moved))) != base


def test_idp_board_keeps_true_positions():
    page = S.parse_board_html(idp_html())
    errors, _ = S.validate_page(page, IDP)
    assert errors == []
    assert [r["position"] for r in page.rows] == ["CB", "S", "DT", "DE", "LB"]


# ── Structural validation / schema drift ────────────────────────────────


def test_clean_page_validates():
    errors, warnings = S.validate_page(S.parse_board_html(offense_html()), DYN)
    assert errors == [] and warnings == []


@pytest.mark.parametrize(
    "kwargs, needle",
    [
        ({"drop_positions": ("TE",)}, "missing position sections"),
        ({"heading": "// REDRAFT RANKINGS"}, "game type unverified"),
        ({"path": "/rankings/redraft"}, "route mismatch"),
        ({"declared": {"QB": 3}}, "declares 3 players"),
        ({"badge_override": {("QB", 2): "QB7"}}, "disagrees with section"),
    ],
)
def test_schema_drift_is_an_error(kwargs, needle):
    errors, _ = S.validate_page(S.parse_board_html(offense_html(**kwargs)), DYN)
    assert any(needle in e for e in errors), errors


def test_unparseable_rank_is_an_error():
    html = offense_html().replace('<span class="rank">1</span>', '<span class="rank">#1</span>', 1)
    errors, _ = S.validate_page(S.parse_board_html(html), DYN)
    assert any("unparseable rank" in e for e in errors)


def test_row_collapse_against_last_good():
    errors, _ = S.validate_page(S.parse_board_html(offense_html()), DYN, last_good_row_count=40)
    assert any("row-count collapse" in e for e in errors)


def test_missing_stamps_are_warnings_not_guesses():
    page = S.parse_board_html(offense_html(published=None, market_through=None))
    errors, warnings = S.validate_page(page, DYN)
    assert errors == []
    assert page.published_at is None and page.market_data_through is None
    assert len(warnings) == 2


# ── Collection ───────────────────────────────────────────────────────────


def test_first_fetch_publishes_atomically_and_privately(store):
    http = FakeHttp({DYN.url: [ok(offense_html())]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert out["outcome"] == "published"
    assert out["rowCount"] == 5
    # Unconditional first GET: no validators without content to validate.
    assert "If-None-Match" not in http.calls[0][1]
    d = store.board_dir("dynasty")
    latest = json.loads((d / "latest.json").read_text(encoding="utf-8"))
    assert latest["contentSha256"] == out["contentSha256"]
    assert latest["dataset"]["gameType"] == "DYNASTY"
    assert latest["dataset"]["votes"] is False
    assert latest["dataset"]["valueScale"] is None
    assert latest["prerenderedAt"] == "2026-10-01T01:37:41.697000Z"
    assert (d / "releases" / f"{out['contentSha256']}.json").exists()
    raw = d / "raw" / f"{out['rawSha256']}.html.gz"
    assert gzip.decompress(raw.read_bytes()).decode("utf-8") == offense_html()
    assert not list(d.rglob("*.tmp"))
    ds = json.loads((d / "dataset_state.json").read_text(encoding="utf-8"))
    assert ds["sourceKey"] == "signalsDynasty"
    assert ds["upstream"]["publishedAt"] == "2026-10-01T01:31:48.554Z"


def test_304_creates_no_release_and_moves_no_information_clock(store):
    later = T0 + timedelta(hours=6)
    http = FakeHttp({DYN.url: [ok(offense_html()), (304, {}, b"")]})
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    before = store.latest("dynasty")
    out = S.collect_board(DYN, store, http=http, now=_clock(later), sleep=lambda s: None)
    assert out["outcome"] == "not_modified"
    assert http.calls[1][1]["If-None-Match"] == 'W/"e1"'
    assert http.calls[1][1]["If-Modified-Since"] == "Thu, 01 Oct 2026 01:38:26 GMT"
    assert store.latest("dynasty") == before
    assert len(list((store.board_dir("dynasty") / "releases").iterdir())) == 1
    state = store.fetch_state("dynasty")
    assert state["lastVerifiedUnchangedAt"] == S.iso(later)
    # Information age is the vendor's publication stamp, not our fetch.
    payload = S.build_second_opinion_payload(store.root, [], now=lambda: later)
    assert payload["boards"]["dynasty"]["release"]["fetchedAt"] == S.iso(T0)


def test_identical_content_new_build_is_not_a_release(store):
    http = FakeHttp(
        {
            DYN.url: [
                ok(offense_html()),
                ok(offense_html(prerendered_ms=1790999999999), etag='W/"e2"'),
            ]
        }
    )
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    out = S.collect_board(
        DYN, store, http=http, now=_clock(T0 + timedelta(hours=6)), sleep=lambda s: None
    )
    assert out["outcome"] == "unchanged_content"
    assert store.latest("dynasty")["fetchedAt"] == S.iso(T0)
    assert store.fetch_state("dynasty")["etag"] == 'W/"e2"'
    assert len(list((store.board_dir("dynasty") / "releases").iterdir())) == 1


def test_drift_quarantines_and_keeps_last_good(store):
    http = FakeHttp(
        {DYN.url: [ok(offense_html()), ok(offense_html(drop_positions=("WR",)), etag='W/"bad"')]}
    )
    first = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    out = S.collect_board(
        DYN, store, http=http, now=_clock(T0 + timedelta(hours=6)), sleep=lambda s: None
    )
    assert out["outcome"] == "quarantined"
    assert store.latest("dynasty")["contentSha256"] == first["contentSha256"]
    q = list((store.board_dir("dynasty") / "quarantine").iterdir())
    assert len(q) == 1
    # Validators NOT advanced past a refused page.
    assert store.fetch_state("dynasty")["etag"] == 'W/"e1"'
    payload = S.build_second_opinion_payload(store.root, [], now=lambda: T0)
    assert payload["boards"]["dynasty"]["status"] == "last_good_degraded"
    ds = json.loads((store.board_dir("dynasty") / "dataset_state.json").read_text(encoding="utf-8"))
    assert ds["health"]["state"] == "DEGRADED"


def test_row_collapse_quarantines(store):
    many = [
        ("QB", i, "B", "tier-b", f"Synthetic Q{i}", "NYJ", None, None) for i in range(1, 21)
    ] + [r for r in OFFENSE_ROWS if r[0] != "QB"]
    http = FakeHttp({DYN.url: [ok(synthetic_board(many)), ok(offense_html(), etag='W/"x"')]})
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert out["outcome"] == "quarantined"
    assert any("row-count collapse" in e for e in out["errors"])


@pytest.mark.parametrize(
    "location",
    [
        "https://signalsfantasy.com/login?next=/rankings/dynasty",
        "https://evil.example/x",
        "http://signalsfantasy.com/rankings/dynasty",
    ],
)
def test_redirect_to_an_access_wall_or_other_origin_stops_without_following(store, location):
    http = FakeHttp({DYN.url: [(302, {"location": location}, b"")]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert out["outcome"] == "auth_stopped"
    assert len(http.calls) == 1 and http.calls[0][0] == DYN.url  # never followed
    assert store.latest(DYN.key) is None


def test_same_origin_redirect_is_not_followed_and_not_a_stop(store):
    http = FakeHttp({DYN.url: [(301, {"location": "/rankings/dynasty/"}, b"")]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert out["outcome"] == "fetch_failed" and "redirect" in out["reason"]
    assert not store.fetch_state(DYN.key).get("stoppedAt")


def test_oversize_response_fails_once_without_retry(store):
    http = FakeHttp({DYN.url: [S.BodyTooLarge("too big")]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert out["outcome"] == "fetch_failed" and out["reason"].startswith("oversize")
    assert len(http.calls) == 1


def test_bounded_gunzip_refuses_a_decompression_bomb(monkeypatch):
    monkeypatch.setattr(S, "MAX_DECOMPRESSED_BYTES", 1000)
    with pytest.raises(S.BodyTooLarge):
        S._bounded_gunzip(gzip.compress(b"x" * 100_000))
    assert S._bounded_gunzip(gzip.compress(b"ok")) == b"ok"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_stops_and_persists(store, status):
    http = FakeHttp({DYN.url: [(status, {}, b"no")]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert out["outcome"] == "auth_stopped"
    assert len(http.calls) == 1  # no retry loop
    again = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert again["outcome"] == "stopped"
    assert len(http.calls) == 1  # refused without touching the network


def test_429_honours_retry_after(store):
    slept: list[float] = []
    http = FakeHttp({DYN.url: [(429, {"retry-after": "7"}, b""), ok(offense_html())]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=slept.append)
    assert out["outcome"] == "published"
    assert slept == [7.0]


def test_429_beyond_cap_gives_up_without_sleeping(store):
    slept: list[float] = []
    http = FakeHttp({DYN.url: [(429, {"retry-after": "3600"}, b"")]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=slept.append)
    assert out["outcome"] == "rate_limited"
    assert slept == []
    assert store.latest("dynasty") is None


def test_transient_failure_backs_off_then_recovers(store):
    slept: list[float] = []
    http = FakeHttp({DYN.url: [OSError("reset"), (503, {}, b""), ok(offense_html())]})
    out = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=slept.append)
    assert out["outcome"] == "published"
    assert slept == list(S.TRANSIENT_BACKOFF_SECONDS)


def test_min_interval_skips_without_request(store):
    http = FakeHttp({DYN.url: [ok(offense_html())]})
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    out = S.collect_board(
        DYN,
        store,
        http=http,
        now=_clock(T0 + timedelta(hours=1)),
        sleep=lambda s: None,
        min_interval_hours=5,
    )
    assert out["outcome"] == "skipped_recent"
    assert len(http.calls) == 1


def test_one_board_failing_does_not_mark_the_other(store):
    http = FakeHttp({DYN.url: [(403, {}, b"")], IDP.url: [ok(idp_html())]})
    a = S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    b = S.collect_board(IDP, store, http=http, now=_clock(T0), sleep=lambda s: None)
    assert (a["outcome"], b["outcome"]) == ("auth_stopped", "published")
    payload = S.build_second_opinion_payload(store.root, [], now=lambda: T0)
    assert payload["status"] == "partial"
    assert payload["boards"]["dynasty"]["status"] == "not_collected"
    assert payload["boards"]["idp-dynasty"]["status"] == "ok"


def test_failed_latest_write_leaves_previous_release_intact(store, monkeypatch):
    http = FakeHttp({DYN.url: [ok(offense_html())]})
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    before = (store.board_dir("dynasty") / "latest.json").read_bytes()

    real_replace = S.os.replace

    def boom(src, dst):
        if str(dst).endswith("latest.json"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(S.os, "replace", boom)
    moved = list(OFFENSE_ROWS)
    moved[4] = ("TE", 1, "A", "tier-a", "Synthetic Zulu", "FA", None, None)
    http2 = FakeHttp({DYN.url: [ok(synthetic_board(moved), etag='W/"e9"')]})
    with pytest.raises(OSError):
        S.collect_board(DYN, store, http=http2, now=_clock(T0), sleep=lambda s: None)
    assert (store.board_dir("dynasty") / "latest.json").read_bytes() == before
    assert not list(store.board_dir("dynasty").rglob("*.tmp"))


# ── Identity (CONTRACT_CSV_JOIN_V1, position-group strict) ───────────────


def _obs(board, pos, rank, name):
    return {"board": board, "position": pos, "positionalRank": rank, "name": name, "team": None}


def test_identity_join_quarantines_instead_of_guessing():
    observations = [
        _obs("dynasty", "QB", 1, "Synthetic Alpha"),
        _obs("dynasty", "WR", 1, "Synthetic Twin"),  # two board homonyms
        _obs("dynasty", "RB", 1, "Synthetic Dup"),
        _obs("dynasty", "RB", 2, "Synthetic Dup"),  # duplicate on Signals
        _obs("dynasty", "TE", 1, "Synthetic Ghost"),  # not on our board
        _obs("dynasty", "WR", 2, "Synthetic Switch"),  # ours is IDP
        _obs("idp-dynasty", "DT", 1, "Synthetic Hotel"),
    ]
    board = [
        {"displayName": "Synthetic Alpha", "position": "QB", "playerId": "100"},
        {"displayName": "Synthetic Twin", "position": "WR", "playerId": "201"},
        {"displayName": "Synthetic Twin", "position": "TE", "playerId": "202"},
        {"displayName": "Synthetic Dup", "position": "RB", "playerId": "300"},
        {"displayName": "Synthetic Switch", "position": "LB", "playerId": "400"},
        {"displayName": "Synthetic Hotel", "position": "DL", "playerId": "500"},
        {"displayName": "2026 Pick 1.01", "position": "PICK"},
    ]
    res = S.join_to_board(observations, board)
    assert set(res.matches) == {"pid:100", "pid:500"}
    assert res.matches["pid:500"]["position"] == "DT"  # true position kept
    reasons = sorted((e["name"], e["reason"]) for e in res.ambiguous + res.unresolved)
    assert reasons == [
        ("Synthetic Dup", "duplicate_on_signals_board"),
        ("Synthetic Dup", "duplicate_on_signals_board"),
        ("Synthetic Ghost", "no_board_row"),
        ("Synthetic Switch", "position_group_mismatch"),
        ("Synthetic Twin", "multiple_board_rows"),
    ]


# ── Serving payload / privacy ────────────────────────────────────────────


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_payload_not_collected_when_store_missing(tmp_path):
    payload = S.build_second_opinion_payload(tmp_path / "nothing", [], now=lambda: T0)
    assert payload["status"] == "not_collected"
    assert payload["votes"] is False
    assert payload["signalsPositionalRank"] == {}
    assert all(b["status"] == "not_collected" for b in payload["boards"].values())


def test_payload_is_rank_only_and_non_voting(store):
    http = FakeHttp({DYN.url: [ok(offense_html())], IDP.url: [ok(idp_html())]})
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    S.collect_board(IDP, store, http=http, now=_clock(T0), sleep=lambda s: None)
    board = [
        {"displayName": "Synthetic Alpha", "position": "QB", "playerId": "100"},
        {"displayName": "Synthetic Foxtrot", "position": "DB", "playerId": "600"},
    ]
    payload = S.build_second_opinion_payload(store.root, board, now=lambda: T0)
    assert payload["status"] == "ok"
    assert payload["basis"] == "POSITIONAL_RANK_ONLY"
    assert payload["signalsPositionalRank"]["pid:100"]["positionalRank"] == 1
    assert payload["signalsPositionalRank"]["pid:600"]["position"] == "CB"
    assert payload["identity"]["resolved"] == 2
    keys = {k.lower() for k in _keys(payload)}
    for forbidden in ("value", "rankderivedvalue", "overallrank", "canonicalconsensusrank"):
        assert forbidden not in keys
    age = payload["boards"]["dynasty"]["release"]["informationAgeHours"]
    assert age == pytest.approx(0.5, abs=0.01)  # from Published, not fetch


def test_signals_is_not_a_registered_ranking_source():
    from src.api.data_contract import _RANKING_SOURCES

    keys = {str(s.get("key", "")).lower() for s in _RANKING_SOURCES}
    assert not any("signals" in k for k in keys)


def test_public_payload_guard_blocks_signals_field():
    from src.public_league.public_contract import assert_public_payload_safe

    with pytest.raises(AssertionError):
        assert_public_payload_safe({"x": {"signalsPositionalRank": {}}})


def test_endpoint_is_private_and_serves_the_store(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    assert client.get("/api/second-opinion/signals").status_code == 401
    assert not server._is_public_api_path("/api/second-opinion/signals")

    data_dir = tmp_path / "data"
    store = S.SignalsStore(data_dir / "sources" / "signals")
    http = FakeHttp({DYN.url: [ok(offense_html())]})
    S.collect_board(DYN, store, http=http, now=_clock(T0), sleep=lambda s: None)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    res = client.get("/api/second-opinion/signals")
    assert res.status_code == 200
    body = res.json()
    assert body["votes"] is False
    assert body["boards"]["dynasty"]["status"] in ("ok", "last_good_degraded")
    assert res.headers["cache-control"] == "private, no-store"
