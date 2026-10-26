"""As-known news metadata archive (Adaptive Learning G4): ``src/news/archive.py``.

Append-only, deduplicated by provider id, metadata only (never an article
body), identity never guessed, missing stays null, and an as-of read never
selects an item first seen later.  Plus the ``NewsService`` hook: it fires on a
real refresh only, and neither it nor its failure changes the served response.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.news import archive as na
from src.news.base import NewsItem, NewsProvider, PlayerMention
from src.news.service import NewsService
from src.utils import append_ledger as al

T1 = "2026-10-04T16:00:00+00:00"
T2 = "2026-10-04T16:10:00+00:00"

META = {
    "Alpha Player": {"position": "WR", "team": "BUF", "playerId": "100"},
    "Shared Name": {
        "position": None,
        "team": None,
        "playerId": None,
        "playerIdNullReason": "display_name_shared_by_multiple_player_ids",
    },
}


def _item(item_id, *, provider="espn", body="FULL ARTICLE BODY TEXT", **kw):
    base = dict(
        id=item_id,
        ts="2026-10-04T15:00:00+00:00",
        provider=provider,
        provider_label=provider.upper(),
        severity="watch",
        kind="injury",
        headline=f"headline {item_id}",
        body=body,
        players=[PlayerMention(name="Alpha Player", impact="negative")],
        url=f"https://example.test/{item_id}",
        tags=["injury"],
    )
    base.update(kw)
    return NewsItem(**base)


def _records(base):
    return list(al.iter_all_records(base))


def test_metadata_fields_and_no_body(tmp_path):
    na.archive([_item("a1")], fetched_at=T1, player_meta=META, base=tmp_path)
    [rec] = _records(tmp_path)
    assert rec["provider"] == "espn" and rec["providerItemId"] == "a1"
    assert rec["publishedAt"] == "2026-10-04T15:00:00+00:00"
    assert rec["fetchedAt"] == T1
    assert rec["headline"] == "headline a1"
    assert rec["url"] == "https://example.test/a1"
    assert rec["players"][0]["sleeperId"] == "100"
    assert rec["players"][0]["identityReason"] is None
    # Copyright: no article body under any name, anywhere in the file.
    assert "body" not in rec and "summary" not in rec
    raw = al.ledger_files(tmp_path)[0].read_text(encoding="utf-8")
    assert "FULL ARTICLE BODY TEXT" not in raw


def test_dedupe_by_provider_id_first_sighting_wins(tmp_path):
    assert na.archive([_item("a1")], fetched_at=T1, base=tmp_path) == 1
    # Re-served at the next refresh, even with an edited headline: no new row.
    assert na.archive([_item("a1", headline="edited")], fetched_at=T2, base=tmp_path) == 0
    [rec] = _records(tmp_path)
    assert rec["fetchedAt"] == T1 and rec["headline"] == "headline a1"
    # Same id from a DIFFERENT provider is a different item.
    assert na.archive([_item("a1", provider="cbs")], fetched_at=T2, base=tmp_path) == 1


def test_duplicate_inside_one_batch_is_written_once(tmp_path):
    assert na.archive([_item("a1"), _item("a1")], fetched_at=T1, base=tmp_path) == 1


def test_existing_lines_never_rewritten(tmp_path):
    na.archive([_item("a1")], fetched_at=T1, base=tmp_path)
    path = al.ledger_files(tmp_path)[0]
    before = path.read_bytes()
    na.archive([_item("a2"), _item("a1")], fetched_at=T2, base=tmp_path)
    assert path.read_bytes().startswith(before)
    assert [r["providerItemId"] for r in _records(tmp_path)] == ["a1", "a2"]


def test_identity_is_never_guessed(tmp_path):
    item = _item(
        "a1",
        players=[
            PlayerMention(name="Alpha Player"),
            PlayerMention(name="Alpha Player", ambiguous=True),
            PlayerMention(name="Nobody Known"),
            PlayerMention(name="Shared Name"),
        ],
    )
    na.archive([item], fetched_at=T1, player_meta=META, base=tmp_path)
    players = _records(tmp_path)[0]["players"]
    assert [p["sleeperId"] for p in players] == ["100", None, None, None]
    assert [p["identityReason"] for p in players] == [
        None,
        "ambiguous_mention",
        "name_not_on_board",
        "display_name_shared_by_multiple_player_ids",
    ]


def test_no_identity_map_keeps_mentions_unresolved(tmp_path):
    na.archive([_item("a1")], fetched_at=T1, player_meta=None, base=tmp_path)
    p = _records(tmp_path)[0]["players"][0]
    assert p["sleeperId"] is None and p["identityReason"] == "no_board_identity_map"


def test_missing_fields_stay_null(tmp_path):
    na.archive([_item("a1", url=None, ts="", headline="")], fetched_at=T1, base=tmp_path)
    rec = _records(tmp_path)[0]
    assert rec["url"] is None
    assert rec["publishedAt"] is None and rec["publishedAtParsed"] is None
    assert rec["headline"] is None
    na.archive([_item("a2", ts="yesterday-ish")], fetched_at=T1, base=tmp_path)
    rec2 = _records(tmp_path)[1]
    assert rec2["publishedAt"] == "yesterday-ish" and rec2["publishedAtParsed"] is None


def test_item_without_provider_id_is_not_keyed_on_a_guess(tmp_path):
    assert na.archive([_item("")], fetched_at=T1, base=tmp_path) == 0
    assert _records(tmp_path) == []


def test_known_at_never_selects_a_later_first_sighting(tmp_path):
    na.archive([_item("a1")], fetched_at=T1, base=tmp_path)
    # Published earlier than T1, but first SEEN at T2.
    na.archive([_item("a2", ts="2026-10-01T00:00:00+00:00")], fetched_at=T2, base=tmp_path)
    at_t1 = na.known_at(datetime(2026, 10, 4, 16, 5, tzinfo=timezone.utc), base=tmp_path)
    assert [r["providerItemId"] for r in at_t1] == ["a1"]
    assert [r["providerItemId"] for r in na.known_at(T2, base=tmp_path)] == ["a1", "a2"]
    assert na.known_at("2026-10-04T15:59:59+00:00", base=tmp_path) == []
    assert na.known_at("garbage", base=tmp_path) == []


def test_archive_safely_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert na.archive_safely([_item("a1")], fetched_at=T1, base=blocker / "sub") is None


def test_background_archive_writes_to_the_configured_store(tmp_path, monkeypatch):
    monkeypatch.setenv(na.ENV_DIR, str(tmp_path / "store"))
    thread = na.archive_in_background([_item("a1")], fetched_at=T1, player_meta=META)
    thread.join(timeout=10)
    assert len(_records(tmp_path / "store")) == 1


def test_default_dir_is_private_and_outside_force_added_paths():
    rel = na.DEFAULT_DIR.relative_to(na.REPO_ROOT).as_posix()
    assert rel == "data/news_archive"


# ── the NewsService hook ────────────────────────────────────────────


class _Provider(NewsProvider):
    name = "fake"
    label = "Fake"

    def __init__(self, items):
        self._items = items

    def fetch(self, *, player_names=None, limit=25):
        return list(self._items)


def _fresh_item(item_id):
    return _item(item_id, ts=datetime.now(timezone.utc).isoformat())


def test_hook_fires_on_refresh_only_and_does_not_change_the_response():
    calls = []

    def hook(items, *, fetched_at, player_meta):
        calls.append(([i.id for i in items], fetched_at, player_meta))

    items = [_fresh_item("a1")]
    plain = NewsService([_Provider(items)], cache_ttl_s=600)
    hooked = NewsService([_Provider(items)], cache_ttl_s=600, on_refresh=hook)

    first = hooked.aggregate(player_meta=META)
    second = hooked.aggregate(player_meta=META)  # cache hit
    assert len(calls) == 1
    assert calls[0][0] == ["a1"] and calls[0][1] == first.generated_at
    assert calls[0][2] is META
    assert second.cache_hit is True

    def shape(agg):
        d = agg.to_dict()
        d.pop("generatedAt")
        d["providerRuns"] = [
            {k: v for k, v in r.items() if k != "elapsedMs"} for r in d["providerRuns"]
        ]
        return json.dumps(d, sort_keys=True)

    assert shape(first) == shape(plain.aggregate(player_meta=META))


def test_hook_failure_never_reaches_the_response():
    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    svc = NewsService([_Provider([_fresh_item("a1")])], cache_ttl_s=0, on_refresh=boom)
    out = svc.aggregate()
    assert [i.id for i in out.items] == ["a1"]


def test_default_service_wires_the_archive():
    from src.news.service import build_default_service

    svc = build_default_service(enabled=())
    assert svc._on_refresh is na.archive_in_background
    assert build_default_service(enabled=(), archive_metadata=False)._on_refresh is None
