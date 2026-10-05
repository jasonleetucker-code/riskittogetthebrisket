"""Signals AUTHENTICATED native values — collector, selection hierarchy, store.

Owner addendum 2026-10-03: Signals is an ACTIVE canonical source.  These pin
the collection half (``src/sources/signals.py``, "Authenticated native
values"); the contract half is ``tests/api/test_signals_active_source.py``.

Every payload, player, value and token here is SYNTHETIC — no network, no
real Signals data, no real session.  The fake AppSync transport answers the
two real query shapes (aliased ``listSnapshotsByPlayer`` batches and paged
``listIdpDynastyValuesBySeason``) measured on 2026-10-03.
"""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.sources import signals as S

T0 = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
IDP_KEYS = ("signalsIdpDl", "signalsIdpLb", "signalsIdpDb")
TOKEN = "SYNTHETIC-ACCESS-TOKEN-never-real"
OFF = S.VALUE_DATASETS["offense"]
IDP = S.VALUE_DATASETS["idp"]


# ── fakes ────────────────────────────────────────────────────────────────


class FakeTokens:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.renewals = 0
        self.denied: list[str] = []

    def token(self) -> str:
        if self.unavailable:
            raise S.ValuesStop("auth_unavailable", "reconnect_required")
        return TOKEN

    def renew(self) -> None:
        self.renewals += 1

    def deny(self, reason: str) -> None:
        self.denied.append(reason)


def _snap(sid: str, date: str, value, pos_rank=None) -> dict:
    return {
        "playerId": sid,
        "date": date,
        "signalsDynastyValue": value,
        "signalsDynastyPosRank": pos_rank,
        "updatedAt": f"{date}T11:30:00.000Z",
    }


def _idp_item(sid: str, name: str, pos: str, value, *, season=2026, sk=None, pos_rank=1) -> dict:
    fam = {"CB": "DB", "S": "DB", "DT": "DL", "DE": "DL", "LB": "LB"}[pos]
    return {
        "playerId": sid,
        "sk": sk or f"{season}#dynasty",
        "season": season,
        "position": pos,
        "family": fam,
        "team": "SYN",
        "name": name,
        "sleeperPlayerId": sid,
        "value": value,
        "posRank": pos_rank,
        "sourceUpdatedAt": "2026-09-30T20:00:00.000Z",
        "updatedAt": "2026-09-30T20:05:00.000Z",
    }


class FakeAppSync:
    """Answers the two real query shapes; records every request."""

    def __init__(
        self,
        *,
        snapshots: dict[str, list[dict]] | None = None,
        idp_pages: list[list[dict]] | None = None,
        script: list | None = None,
    ) -> None:
        self.snapshots = snapshots or {}
        self.idp_pages = idp_pages or []
        self.script = list(script or [])  # pre-canned (status, headers, body) answers
        self.requests: list[dict] = []

    def __call__(self, url, headers, body, timeout):
        assert url == S.APPSYNC_URL
        doc = json.loads(body.decode("utf-8"))
        self.requests.append({"headers": dict(headers), "doc": doc})
        if self.script:
            answer = self.script.pop(0)
            if answer is not None:
                return answer
        q = doc["query"]
        if "listIdpDynastyValuesBySeason" in q:
            tok = doc["variables"].get("nextToken")
            idx = int(tok) if tok else 0
            nxt = str(idx + 1) if idx + 1 < len(self.idp_pages) else None
            data = {
                "listIdpDynastyValuesBySeason": {"items": self.idp_pages[idx], "nextToken": nxt}
            }
        else:
            data = {}
            for k, sid in doc["variables"].items():
                alias = "s" + k[1:]
                snaps = sorted(self.snapshots.get(sid, []), key=lambda s: s["date"], reverse=True)
                data[alias] = {"items": snaps[:2]}
        return 200, {}, json.dumps({"data": data}).encode()


def _universe(n: int) -> dict[str, dict]:
    pos = ("QB", "RB", "WR", "TE")
    return {
        str(1000 + i): {"name": f"Synthetic Off {i:03d}", "position": pos[i % 4]} for i in range(n)
    }


def _payload_with(universe: dict[str, dict]) -> dict:
    return {
        "players": {m["name"]: {"_sleeperId": sid} for sid, m in universe.items()},
        "sleeper": {"positions": {m["name"]: m["position"] for m in universe.values()}},
    }


def _write_payload(repo: Path, universe: dict[str, dict]) -> None:
    (repo / "data").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "dynasty_data_2026-10-03.json").write_text(
        json.dumps(_payload_with(universe)), encoding="utf-8"
    )


def _run(tmp_path: Path, fake: FakeAppSync, tokens=None, **kw) -> dict:
    return S.collect_values(
        tmp_path / "store",
        repo_root=tmp_path / "repo",
        state_dir=tmp_path / "state",
        tokens=tokens or FakeTokens(),
        http_post=fake,
        now=lambda: T0,
        sleep=lambda s: None,
        season=2026,
        **kw,
    )


def _csv_rows(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


@pytest.fixture(autouse=True)
def _small_board_floors(monkeypatch):
    """Synthetic boards are tens of rows; the real floors (400 / 330) are
    pinned against the contract in test_source_floor_invariant.py."""
    monkeypatch.setattr(S, "MIN_BOARD_ROWS", dict.fromkeys(("signalsSf", *IDP_KEYS), 5))


@pytest.fixture
def world(tmp_path):
    uni = _universe(60)
    _write_payload(tmp_path / "repo", uni)
    snaps = {}
    for i, sid in enumerate(sorted(uni)):
        snaps[sid] = [
            _snap(sid, "2026-10-03", 9000 - 100 * i, pos_rank=i // 4 + 1),
            _snap(sid, "2026-10-02", 8990 - 100 * i, pos_rank=i // 4 + 1),
        ]
    idp = [
        _idp_item(
            str(5000 + i),
            f"Synthetic Idp {i:03d}",
            ("CB", "S", "DT", "DE", "LB")[i % 5],
            4900 - 40 * i,
        )
        for i in range(70)
    ]
    return tmp_path, uni, snaps, idp


# ── the selection hierarchy (acceptance 1-4, 9, 10, 12) ──────────────────


class TestSelectionHierarchy:
    def _obs(self, sid, name, value=None, cross=None, positional=None):
        return {
            "sleeperId": sid,
            "name": name,
            "position": "WR",
            "rawPosition": None,
            "team": None,
            "nativeValue": value,
            "positionalRank": positional,
            "crossPositionRank": cross,
            "valueAsOf": "2026-10-03T11:30:00Z",
        }

    def test_value_is_the_vote_and_its_rank_is_derived_from_the_value_order(self):
        rows, excluded = S.build_board_rows(
            [
                self._obs("1", "Synthetic A", value=5000.0),
                self._obs("2", "Synthetic B", value=7000.0),
                self._obs("3", "Synthetic C", value=5000.0),
            ],
            OFF,
        )
        assert [(r["sleeper_id"], r["rank"], r["basis"], r["rank_derived"]) for r in rows] == [
            ("2", 1, "NATIVE_VALUE", 1),
            ("1", 2, "NATIVE_VALUE", 1),  # equal values share a rank
            ("3", 2, "NATIVE_VALUE", 1),
        ]
        assert excluded == {}

    def test_value_and_rank_together_cast_one_vote_the_value(self):
        rows, _ = S.build_board_rows([self._obs("1", "Synthetic A", value=4000.0, cross=9)], OFF)
        assert len(rows) == 1
        assert rows[0]["basis"] == S.BASIS_NATIVE_VALUE and rows[0]["value"] == 4000.0

    def test_no_value_but_a_cross_position_rank_is_the_rank_fallback(self):
        rows, _ = S.build_board_rows(
            [self._obs("1", "Synthetic A", value=6000.0), self._obs("2", "Synthetic B", cross=4)],
            OFF,
        )
        fb = [r for r in rows if r["sleeper_id"] == "2"][0]
        assert fb["basis"] == S.BASIS_CROSS_POSITION_RANK
        assert fb["rank"] == 4 and fb["value"] is None and fb["rank_derived"] == 0

    def test_positional_rank_alone_never_manufactures_an_order(self):
        """QB3 and RB3 are not equal values; a positional ordinal is never a vote."""
        rows, excluded = S.build_board_rows(
            [
                self._obs("1", "Synthetic QB3", positional=3),
                self._obs("2", "Synthetic RB3", positional=3),
            ],
            OFF,
        )
        assert rows == []
        assert excluded == {"no_value_no_cross_position_rank": 2}

    @pytest.mark.parametrize("bad", [None, 0, -5, "", float("nan"), True])
    def test_missing_or_invalid_value_is_missing_never_zero(self, bad):
        rows, excluded = S.build_board_rows([self._obs("1", "Synthetic A", value=bad)], OFF)
        assert rows == [] and excluded == {"no_value_no_cross_position_rank": 1}

    def test_homonyms_inside_a_dataset_are_withheld_not_guessed(self):
        rows, excluded = S.build_board_rows(
            [
                self._obs("1", "Synthetic Twin", value=5000.0),
                self._obs("2", "Synthetic Twin", value=3000.0),
                self._obs("3", "Synthetic Solo", value=1000.0),
            ],
            OFF,
        )
        assert [r["sleeper_id"] for r in rows] == ["3"]
        assert excluded == {"homonym_within_dataset": 2}

    def test_idp_is_ranked_within_family_never_across(self):
        """Review B1: Signals' IDP value is normalised per family.  A DB at
        4,754 and a DL at 4,880 are each their family's #1 — never #1 and #2
        of one shared order."""
        obs = [
            {**self._obs("1", "Synthetic Edge", value=4880.0), "position": "DL"},
            {**self._obs("2", "Synthetic Corner", value=4754.0), "position": "DB"},
            {**self._obs("3", "Synthetic Tackle", value=4100.0), "position": "DL"},
            {**self._obs("4", "Synthetic Backer", value=4913.0), "position": "LB"},
            {**self._obs("5", "Synthetic Rusher", value=4000.0), "position": "XX"},
        ]
        rows, excluded = S.build_board_rows(obs, IDP)
        got = {(r["sleeper_id"], IDP.board_key_for(r), r["rank"]) for r in rows}
        assert got == {
            ("1", "signalsIdpDl", 1),
            ("3", "signalsIdpDl", 2),
            ("2", "signalsIdpDb", 1),
            ("4", "signalsIdpLb", 1),
        }
        assert excluded == {"no_family_board": 1}

    def test_render_parses_through_the_contracts_rank_signal_reader(self, tmp_path):
        """The board CSV is read by the SAME parser every rank source uses:
        rank -> synthetic ordering value, native value preserved, Sleeper id
        captured for the ID-grade join; a fallback row carries no native."""
        from src.api.data_contract import _parse_source_csv_cached

        rows, _ = S.build_board_rows(
            [
                self._obs("11", "Synthetic Val", value=8123.5),
                self._obs("12", "Synthetic Fb", cross=7),
            ],
            OFF,
        )
        path = tmp_path / "signalsSf.csv"
        path.write_text(S.render_board_csv(rows), encoding="utf-8")
        lookup, err = _parse_source_csv_cached(path, "signalsSf", "rank", "x")
        assert err is None
        by_name = {e[0]: e for v in lookup.values() for e in v}
        name, synthetic, rank, native, sid = by_name["Synthetic Val"]
        assert (rank, native, sid) == (1.0, 8123.5, "11")
        assert by_name["Synthetic Fb"][2:] == (7.0, None, "12")
        assert by_name["Synthetic Val"][1] > by_name["Synthetic Fb"][1]


# ── IDP normalization (acceptance 3, IDP position owner) ─────────────────


class TestIdpNormalization:
    def test_raw_position_is_kept_and_mapped_only_by_the_canonical_owner(self):
        items = [
            _idp_item("1", "A", "CB", 3000),
            _idp_item("2", "B", "DT", 2000),
            _idp_item("3", "C", "LB", 1000),
        ]
        obs, errors, _, _x = S.normalize_idp_items(items, IDP, season=2026)
        assert errors == []
        assert [(o["rawPosition"], o["position"]) for o in obs] == [
            ("CB", "DB"),
            ("DT", "DL"),
            ("LB", "LB"),
        ]

    def test_a_non_dynasty_row_quarantines_the_release(self):
        items = [_idp_item("1", "A", "CB", 3000), _idp_item("2", "B", "S", 2000, sk="2026#redraft")]
        _obs, errors, _, _x = S.normalize_idp_items(items, IDP, season=2026)
        assert any("game type unverified" in e for e in errors)

    def test_a_vendor_slug_instead_of_a_sleeper_id_is_excluded_not_fatal(self):
        slug = _idp_item("1", "Synthetic Prospect", "LB", 900)
        slug["sleeperPlayerId"] = slug["playerId"] = "draft_2025_syntheticprospect"
        obs, errors, _, excluded = S.normalize_idp_items(
            [slug, _idp_item("2", "B", "LB", 1000)], IDP, season=2026
        )
        assert errors == [] and [o["sleeperId"] for o in obs] == ["2"]
        assert excluded == {"no_sleeper_id": 1}

    def test_a_vendor_family_that_disagrees_with_the_position_is_schema_drift(self):
        bad = _idp_item("1", "A", "CB", 3000)
        bad["family"] = "LB"
        _obs, errors, _w, _x = S.normalize_idp_items([bad], IDP, season=2026)
        assert any("vendor family" in e for e in errors)

    def test_duplicate_ids_and_unknown_positions_are_schema_drift(self):
        items = [_idp_item("1", "A", "CB", 3000), _idp_item("1", "B", "CB", 2000)]
        assert any("duplicate" in e for e in S.normalize_idp_items(items, IDP, season=2026)[1])
        bad = _idp_item("2", "C", "CB", 2000)
        bad["position"] = "EDGE"
        assert any(
            "unexpected position" in e for e in S.normalize_idp_items([bad], IDP, season=2026)[1]
        )


# ── offense publication (stale can never masquerade as current) ──────────


class TestOffensePublication:
    def test_one_publication_and_an_older_snapshot_is_not_carried_forward(self):
        uni = _universe(5)
        sids = sorted(uni)
        results = {sid: [_snap(sid, "2026-10-03", 5000 - i)] for i, sid in enumerate(sids[:4])}
        results[sids[4]] = [_snap(sids[4], "2026-09-20", 9999)]  # stale: Signals stopped valuing it
        obs, pub, errors, _w, excluded = S.normalize_offense_snapshots(results, uni, OFF)
        assert errors == [] and pub == "2026-10-03"
        assert sids[4] not in {o["sleeperId"] for o in obs}
        assert excluded["not_current_publication"] == 1

    def test_a_partly_written_day_falls_back_to_the_majority_publication(self):
        uni = _universe(10)
        sids = sorted(uni)
        results = {}
        for i, sid in enumerate(sids):
            snaps = [_snap(sid, "2026-10-02", 4000 - i)]
            if i < 3:  # today's snapshots only partly written
                snaps.insert(0, _snap(sid, "2026-10-03", 4100 - i))
            results[sid] = snaps
        obs, pub, errors, _w, _e = S.normalize_offense_snapshots(results, uni, OFF)
        assert errors == [] and pub == "2026-10-02" and len(obs) == 10

    def test_the_query_selects_dynasty_fields_only(self):
        q = S._offense_batch_query(3, "2026-09-26")
        assert "signalsDynastyValue" in q
        for forbidden in ("ktc", "Redraft", "Idp"):
            assert forbidden not in q
        with pytest.raises(ValueError):
            S._offense_batch_query(1, 'x"} } evil')


# ── end-to-end collection with a fake AppSync ─────────────────────────────


class TestCollection:
    def test_publishes_both_boards_privately_with_bounded_requests(self, world):
        tmp, uni, snaps, idp = world
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp[:40], idp[40:]])
        out = _run(tmp, fake)
        assert out["ok"] is True
        assert out["datasets"]["offense"]["outcome"] == "published"
        assert out["datasets"]["idp"]["outcome"] == "published"
        # 60 players in batches of 25 -> 3 requests; 2 IDP pages.
        assert len(fake.requests) == math.ceil(60 / S.OFFENSE_BATCH_SIZE) + 2
        assert len(fake.requests) <= S.MAX_VALUE_REQUESTS_PER_RUN
        store = tmp / "store"
        assert S.private_store_provisioned(store)
        off_rows = _csv_rows(S.board_csv_path(store, "signalsSf"))
        idp_boards = {k: _csv_rows(S.board_csv_path(store, k)) for k in IDP_KEYS}
        idp_rows = [r for rows in idp_boards.values() for r in rows]
        assert len(off_rows) == 60 and len(idp_rows) == 70
        assert list(off_rows[0]) == list(S.BOARD_CSV_COLUMNS)
        assert off_rows[0]["rank"] == "1" and off_rows[0]["basis"] == "NATIVE_VALUE"
        assert {r["dataset"] for r in idp_rows} == {"idp"}
        assert {r["raw_position"] for r in idp_rows} == {"CB", "S", "DT", "DE", "LB"}
        # one board per family, each ranked within itself from 1
        for key, fam, raws in (
            ("signalsIdpDl", "DL", {"DT", "DE"}),
            ("signalsIdpLb", "LB", {"LB"}),
            ("signalsIdpDb", "DB", {"CB", "S"}),
        ):
            rows = idp_boards[key]
            assert {r["position"] for r in rows} == {fam}
            assert {r["raw_position"] for r in rows} == raws
            assert [int(r["rank"]) for r in rows] == list(range(1, len(rows) + 1))
        # freshness clocks: success stamp + dataset state with the VENDOR clock
        state = tmp / "state"
        assert (state / "signalsSf_last_success").read_text().strip() == str(int(T0.timestamp()))
        for key in IDP_KEYS:
            ds = json.loads((state / f"{key}_dataset.json").read_text(encoding="utf-8"))
            assert ds["health"]["state"] == "HEALTHY"
            assert (state / f"{key}_last_success").is_file()
        assert not (state / "signalsIdp_dataset.json").exists()
        latest = json.loads((store / "values" / "idp" / "latest.json").read_text(encoding="utf-8"))
        assert latest["metadata"]["votes"] is True
        assert latest["observations"][0]["format"]["gameType"] == "DYNASTY"

    def test_the_offense_format_is_superflex_and_not_te_premium(self):
        fmt = S.value_dataset_metadata(OFF)["format"]
        assert fmt["superflex"] is True and fmt["tePremium"] is False
        assert fmt["leagueAdjusted"] is False
        assert fmt["superflexEvidence"] and fmt["tePremiumEvidence"]

    def test_unchanged_content_publishes_nothing_new_but_proves_freshness(self, world):
        tmp, uni, snaps, idp = world
        _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]))
        releases = list((tmp / "store" / "values" / "offense" / "releases").glob("*.json"))
        out = _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]), force=True)
        assert out["datasets"]["offense"]["outcome"] == "unchanged_content"
        assert list((tmp / "store" / "values" / "offense" / "releases").glob("*.json")) == releases

    def test_min_interval_skips_without_a_request(self, world):
        tmp, uni, snaps, idp = world
        _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]))
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp])
        out = _run(tmp, fake, min_interval_hours=5)
        assert out.get("skipped") and fake.requests == []

    def test_no_session_means_no_request_and_the_last_good_board_keeps_its_age(self, world):
        tmp, uni, snaps, idp = world
        _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]))
        csv_before = S.board_csv_path(tmp / "store", "signalsSf").read_bytes()
        stamp_before = (tmp / "state" / "signalsSf_last_success").read_text()
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp])
        later = datetime(2026, 10, 4, 14, tzinfo=timezone.utc)
        out = S.collect_values(
            tmp / "store",
            repo_root=tmp / "repo",
            state_dir=tmp / "state",
            tokens=FakeTokens(unavailable=True),
            http_post=fake,
            now=lambda: later,
            sleep=lambda s: None,
            season=2026,
        )
        assert out["ok"] is False and out["stopped"] == "auth_unavailable"
        assert fake.requests == []
        assert S.board_csv_path(tmp / "store", "signalsSf").read_bytes() == csv_before
        # No clock is refreshed from a cached copy: stale stays stale.
        assert (tmp / "state" / "signalsSf_last_success").read_text() == stamp_before
        marker = json.loads((tmp / "store" / "values" / S.PROVISIONED_MARKER).read_text())
        assert marker["lastRunOk"] is False

    def test_401_renews_once_then_succeeds(self, world):
        tmp, uni, snaps, idp = world
        tokens = FakeTokens()
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp], script=[(401, {}, b"{}")])
        out = _run(tmp, fake, tokens=tokens)
        assert out["ok"] is True and tokens.renewals == 1 and tokens.denied == []

    def test_a_refusal_that_survives_renewal_is_access_denied_and_stops(self, world):
        tmp, uni, snaps, idp = world
        tokens = FakeTokens()
        fake = FakeAppSync(
            snapshots=snaps, idp_pages=[idp], script=[(403, {}, b"{}"), (403, {}, b"{}")]
        )
        out = _run(tmp, fake, tokens=tokens)
        assert out["stopped"] == "access_denied"
        assert tokens.renewals == 1 and len(tokens.denied) == 1
        assert len(fake.requests) == 2  # no loop
        assert not S.board_csv_path(tmp / "store", "signalsSf").exists()

    def test_appsync_unauthorized_field_errors_take_the_same_path(self, world):
        tmp, uni, snaps, idp = world
        tokens = FakeTokens()
        unauthorized = (
            200,
            {},
            json.dumps({"errors": [{"errorType": "Unauthorized", "message": "nope"}]}).encode(),
        )
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp], script=[unauthorized, unauthorized])
        out = _run(tmp, fake, tokens=tokens)
        assert out["stopped"] == "access_denied" and tokens.renewals == 1

    def test_429_honours_retry_after_then_stops(self, world):
        tmp, uni, snaps, idp = world
        slept: list[float] = []
        limited = (429, {"retry-after": "7"}, b"")
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp], script=[limited, limited, limited])
        out = S.collect_values(
            tmp / "store",
            repo_root=tmp / "repo",
            state_dir=tmp / "state",
            tokens=FakeTokens(),
            http_post=fake,
            now=lambda: T0,
            sleep=slept.append,
            season=2026,
            datasets=("offense",),
        )
        assert out["datasets"]["offense"]["outcome"] == "rate_limited"
        assert slept[:2] == [7.0, 7.0] and len(fake.requests) == 3

    def test_schema_drift_quarantines_and_keeps_the_last_good_board(self, world):
        tmp, uni, snaps, idp = world
        _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]))
        good = S.board_csv_path(tmp / "store", "signalsIdpDb").read_bytes()
        drift = (
            200,
            {},
            json.dumps(
                {"errors": [{"errorType": "Validation", "message": "FieldUndefined"}]}
            ).encode(),
        )
        later = datetime(2026, 10, 4, 14, tzinfo=timezone.utc)
        out = S.collect_values(
            tmp / "store",
            repo_root=tmp / "repo",
            state_dir=tmp / "state",
            tokens=FakeTokens(),
            http_post=FakeAppSync(snapshots=snaps, idp_pages=[idp], script=[drift]),
            now=lambda: later,
            sleep=lambda s: None,
            season=2026,
            datasets=("idp",),
        )
        assert out["datasets"]["idp"]["outcome"] == "quarantined"
        assert S.board_csv_path(tmp / "store", "signalsIdpDb").read_bytes() == good
        ds = json.loads((tmp / "state" / "signalsIdpDb_dataset.json").read_text(encoding="utf-8"))
        assert ds["health"]["state"] == "DEGRADED"
        assert list((tmp / "store" / "values" / "idp" / "quarantine").glob("*.json"))

    def test_a_row_collapse_is_quarantined(self, world, monkeypatch):
        tmp, uni, snaps, idp = world
        monkeypatch.setattr(S, "MIN_BOARD_ROWS", dict.fromkeys(("signalsSf", *IDP_KEYS), 1))
        _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]))
        out = _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp[:10]]), force=True)
        assert out["datasets"]["idp"]["outcome"] == "quarantined"
        assert any("row-count collapse" in e for e in out["datasets"]["idp"]["errors"])

    def test_a_board_below_its_floor_is_quarantined(self, world, monkeypatch):
        tmp, uni, snaps, idp = world
        monkeypatch.setattr(
            S,
            "MIN_BOARD_ROWS",
            {"signalsSf": 5, "signalsIdpDl": 5, "signalsIdpLb": 5, "signalsIdpDb": 500},
        )
        out = _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=[idp]), datasets=("idp",))
        assert out["datasets"]["idp"]["outcome"] == "quarantined"
        assert "below board floor" in out["datasets"]["idp"]["errors"][0]
        assert not any(S.board_csv_path(tmp / "store", k).exists() for k in IDP_KEYS)

    def test_runaway_pagination_is_withheld_not_truncated(self, world):
        tmp, uni, snaps, idp = world
        pages = [idp[i : i + 5] for i in range(0, 35, 5)]  # 7 pages > IDP_MAX_PAGES
        out = _run(tmp, FakeAppSync(snapshots=snaps, idp_pages=pages), datasets=("idp",))
        assert out["datasets"]["idp"]["outcome"] == "quarantined"
        assert not any(S.board_csv_path(tmp / "store", k).exists() for k in IDP_KEYS)

    def test_the_request_budget_is_a_hard_cap(self, world):
        tmp, uni, snaps, idp = world
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp])
        out = _run(tmp, fake, max_requests=2)
        assert len(fake.requests) == 2
        assert out["datasets"]["offense"]["outcome"] == "request_budget_exhausted"


# ── privacy (acceptance 14) ──────────────────────────────────────────────


class TestPrivacy:
    def test_the_token_is_only_ever_a_request_header(self, world, capsys):
        tmp, uni, snaps, idp = world
        fake = FakeAppSync(snapshots=snaps, idp_pages=[idp])
        out = _run(tmp, fake)
        assert all(r["headers"]["Authorization"] == TOKEN for r in fake.requests)
        assert TOKEN not in json.dumps(out)
        for path in (tmp / "store").rglob("*"):
            if path.is_file() and path.suffix in (".json", ".csv"):
                assert TOKEN not in path.read_text(encoding="utf-8"), path
        for path in (tmp / "state").rglob("*"):
            if path.is_file():
                assert TOKEN not in path.read_text(encoding="utf-8"), path

    def test_the_store_is_gitignored_and_never_force_added(self):
        import subprocess

        repo = Path(__file__).resolve().parents[2]
        for rel in (
            "data/sources/signals/board/signalsSf.csv",
            "data/sources/signals/values/idp/latest.json",
            "data/scrape_state/signalsSf_dataset.json",
        ):
            res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo, capture_output=True)
            assert res.returncode == 0, f"{rel} is not gitignored"
        for wf in (repo / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text(encoding="utf-8")
            assert "data/sources" not in text, wf.name
        # Deploy scripts may BACK UP the box-local store (the nightly state
        # backup + its restore proof copy it off the app tree), but nothing
        # may stage it into git, and no script may touch the owner session.
        for sh in (repo / "deploy").rglob("*.sh"):
            text = sh.read_text(encoding="utf-8")
            for line in text.splitlines():
                code = line.split("#", 1)[0]
                if "sources/signals" in code:
                    assert "git " not in code, (sh.name, line)
        # The backup writer and its proof never name the session store.
        for sh in (repo / "deploy" / "backup").rglob("*.sh"):
            for line in sh.read_text(encoding="utf-8").splitlines():
                code = line.split("#", 1)[0]
                assert "signals-auth" not in code, (sh.name, line)
                assert "signals_auth" not in code, (sh.name, line)

    def test_ci_never_writes_signals_dataset_state(self):
        from scripts.record_source_datasets import PROD_TIMER_OWNED_KEYS

        assert {"signalsSf", *IDP_KEYS} <= set(PROD_TIMER_OWNED_KEYS)
