"""Signals IDP collection: truthful PER-FAMILY status, clocks and quarantine.

Plan PR-H (owner directive 2026-10-19,
docs/owner/ on release train 13; plan §1.2 / §5.7 "Collection"):

* every collection outcome reports ``boardStatus`` per registry key — a
  family withheld because a SIBLING failed says so, it does not read broken;
* each family's upstream clock is its OWN rows' newest vendor stamp — a
  family never inherits a sibling's freshness;
* ``_last_success`` is written only for boards actually verified this run;
* family-scoped quarantine sits behind ``signals_idp_family_quarantine``
  (default OFF), falls back to release-level quarantine on any internal
  error, and never touches offense publication.

Every player, value and token here is SYNTHETIC (no network, no Signals data).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.api import feature_flags
from src.sources import signals as S
from tests.sources.test_signals_values import (
    IDP_KEYS,
    T0,
    FakeAppSync,
    FakeTokens,
    _idp_item,
    _run,
    _snap,
    _universe,
    _write_payload,
)

T1 = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)
FLAG_ENV = "RISKIT_FEATURE_SIGNALS_IDP_FAMILY_QUARANTINE"


@pytest.fixture(autouse=True)
def _floors(monkeypatch):
    monkeypatch.setattr(S, "MIN_BOARD_ROWS", dict.fromkeys(("signalsSf", *IDP_KEYS), 5))


@pytest.fixture
def family_flag(monkeypatch):
    def _set(on: bool) -> None:
        monkeypatch.setenv(FLAG_ENV, "1" if on else "0")
        feature_flags.reload()

    yield _set
    monkeypatch.delenv(FLAG_ENV, raising=False)
    feature_flags.reload()


def _idp(n: int = 70, *, stamps: dict[str, str] | None = None) -> list[dict]:
    """Synthetic IDP rows cycling CB/S/DT/DE/LB; ``stamps`` overrides the
    vendor stamp per raw position (``""`` = no stamp)."""
    out = []
    for i in range(n):
        pos = ("CB", "S", "DT", "DE", "LB")[i % 5]
        item = _idp_item(str(5000 + i), f"Synthetic Idp {i:03d}", pos, 4900 - 40 * i)
        if stamps and pos in stamps:
            item["sourceUpdatedAt"] = stamps[pos] or None
            item["updatedAt"] = stamps[pos] or None
        out.append(item)
    return out


def _only(items: list[dict], drop_family: str, keep: int) -> list[dict]:
    """Keep only ``keep`` rows of one family (to push it under its floor)."""
    fam = {"CB": "DB", "S": "DB", "DT": "DL", "DE": "DL", "LB": "LB"}
    kept, out = 0, []
    for it in items:
        if fam[it["position"]] == drop_family:
            if kept >= keep:
                continue
            kept += 1
        out.append(it)
    return out


def _ds(tmp, key):
    return json.loads((tmp / "state" / f"{key}_dataset.json").read_text(encoding="utf-8"))


def _idp_run(tmp, items, *, at=T0, **kw):
    return S.collect_values(
        tmp / "store",
        repo_root=tmp / "repo",
        state_dir=tmp / "state",
        tokens=FakeTokens(),
        http_post=FakeAppSync(idp_pages=[items]),
        now=lambda: at,
        sleep=lambda s: None,
        season=2026,
        datasets=("idp",),
        **kw,
    )


def _csv(tmp, key):
    path = S.board_csv_path(tmp / "store", key)
    return path.read_bytes() if path.exists() else None


# ── per-family status (default path) ─────────────────────────────────────


class TestBoardStatus:
    def test_a_clean_release_reports_every_family_accepted(self, tmp_path, family_flag):
        family_flag(False)
        out = _idp_run(tmp_path, _idp())
        status = out["datasets"]["idp"]["boardStatus"]
        assert set(status) == set(IDP_KEYS)
        assert {v["state"] for v in status.values()} == {S.BOARD_ACCEPTED}
        assert {status[k]["family"] for k in IDP_KEYS} == {"DL", "LB", "DB"}
        assert sum(v["rows"] for v in status.values()) == 70
        marker = json.loads(
            (tmp_path / "store" / "values" / S.PROVISIONED_MARKER).read_text(encoding="utf-8")
        )
        assert set(marker["boardStatus"]) == set(IDP_KEYS)
        fetch = json.loads(
            (tmp_path / "store" / "values" / "idp" / "fetch_state.json").read_text("utf-8")
        )
        assert fetch["lastBoardStatus"]["signalsIdpDb"]["state"] == S.BOARD_ACCEPTED

    def test_release_level_quarantine_names_the_failing_family_and_its_siblings(
        self, tmp_path, family_flag
    ):
        family_flag(False)
        out = _idp_run(tmp_path, _only(_idp(), "DB", 2))
        ds = out["datasets"]["idp"]
        assert ds["outcome"] == "quarantined"
        status = ds["boardStatus"]
        assert status["signalsIdpDb"]["state"] == S.BOARD_QUARANTINED
        assert status["signalsIdpDb"]["reason"] == "below_floor"
        assert status["signalsIdpDl"]["state"] == S.BOARD_WITHHELD_BY_SIBLING
        assert status["signalsIdpLb"]["state"] == S.BOARD_WITHHELD_BY_SIBLING
        # nothing verified -> no success stamp, no CSV, every clock DEGRADED
        for key in IDP_KEYS:
            assert not (tmp_path / "state" / f"{key}_last_success").exists()
            assert _csv(tmp_path, key) is None
            assert _ds(tmp_path, key)["health"]["state"] == "DEGRADED"

    def test_a_release_level_error_withholds_every_family_as_release(self, tmp_path, family_flag):
        family_flag(True)  # the flag never applies to a release-level error
        items = _idp()
        items[3]["sk"] = "2026#redraft"
        out = _idp_run(tmp_path, items)
        ds = out["datasets"]["idp"]
        assert ds["outcome"] == "quarantined"
        assert {v["state"] for v in ds["boardStatus"].values()} == {S.BOARD_WITHHELD_BY_RELEASE}

    def test_an_auth_stop_reports_not_collected(self, tmp_path, family_flag):
        family_flag(False)
        out = S.collect_values(
            tmp_path / "store",
            repo_root=tmp_path / "repo",
            state_dir=tmp_path / "state",
            tokens=FakeTokens(unavailable=True),
            http_post=FakeAppSync(idp_pages=[_idp()]),
            now=lambda: T0,
            sleep=lambda s: None,
            season=2026,
            datasets=("idp",),
        )
        ds = out["datasets"]["idp"]
        assert ds["outcome"] == "auth_unavailable"
        # the stop is re-raised before boardStatus reaches the summary, but the
        # fetch state records it
        fetch = json.loads(
            (tmp_path / "store" / "values" / "idp" / "fetch_state.json").read_text("utf-8")
        )
        assert {v["state"] for v in fetch["lastBoardStatus"].values()} == {S.BOARD_NOT_COLLECTED}


# ── per-family clocks ────────────────────────────────────────────────────


class TestPerFamilyClocks:
    def test_each_family_carries_its_own_vendor_clock(self, tmp_path, family_flag):
        family_flag(False)
        stamps = {
            "DT": "2026-09-20T10:00:00.000Z",
            "DE": "2026-09-21T10:00:00.000Z",
            "LB": "2026-09-25T10:00:00.000Z",
            "CB": "2026-09-30T20:00:00.000Z",
            "S": "2026-09-29T20:00:00.000Z",
        }
        out = _idp_run(tmp_path, _idp(stamps=stamps))
        status = out["datasets"]["idp"]["boardStatus"]
        assert status["signalsIdpDl"]["asOf"] == stamps["DE"]
        assert status["signalsIdpLb"]["asOf"] == stamps["LB"]
        assert status["signalsIdpDb"]["asOf"] == stamps["CB"]
        assert _ds(tmp_path, "signalsIdpDl")["upstream"]["publishedAt"] == stamps["DE"]
        assert _ds(tmp_path, "signalsIdpLb")["upstream"]["publishedAt"] == stamps["LB"]
        assert _ds(tmp_path, "signalsIdpDb")["upstream"]["publishedAt"] == stamps["CB"]

    def test_a_family_with_no_stamp_never_borrows_a_siblings_clock(self, tmp_path, family_flag):
        family_flag(False)
        stamps = {"DT": "", "DE": "", "LB": "2026-09-25T10:00:00.000Z"}
        out = _idp_run(tmp_path, _idp(stamps=stamps))
        status = out["datasets"]["idp"]["boardStatus"]
        assert status["signalsIdpDl"]["asOf"] is None
        assert _ds(tmp_path, "signalsIdpDl")["upstream"]["publishedAt"] is None
        assert _ds(tmp_path, "signalsIdpDb")["upstream"]["publishedAt"] is not None


# ── family-scoped quarantine (flag) ──────────────────────────────────────


class TestFamilyScopedQuarantine:
    def test_off_by_default(self):
        feature_flags.reload()
        assert feature_flags._DEFAULTS["signals_idp_family_quarantine"] is False
        assert S.family_quarantine_enabled() is False

    def test_first_run_publishes_passing_families_and_leaves_the_failed_one_absent(
        self, tmp_path, family_flag
    ):
        family_flag(True)
        out = _idp_run(tmp_path, _only(_idp(), "DB", 2))
        ds = out["datasets"]["idp"]
        assert ds["outcome"] == "partially_quarantined"
        assert ds["familiesQuarantined"] == ["signalsIdpDb"]
        assert out["ok"] is False
        status = ds["boardStatus"]
        assert status["signalsIdpDb"]["state"] == S.BOARD_QUARANTINED
        assert status["signalsIdpDb"]["rows"] == 0  # nothing carried: absent, never empty
        assert status["signalsIdpDl"]["state"] == S.BOARD_ACCEPTED
        assert _csv(tmp_path, "signalsIdpDb") is None
        for key in ("signalsIdpDl", "signalsIdpLb"):
            assert _csv(tmp_path, key) is not None
            assert (tmp_path / "state" / f"{key}_last_success").is_file()
            assert _ds(tmp_path, key)["health"]["state"] == "HEALTHY"
        assert not (tmp_path / "state" / "signalsIdpDb_last_success").exists()
        assert _ds(tmp_path, "signalsIdpDb")["health"]["state"] == "DEGRADED"
        latest = json.loads(
            (tmp_path / "store" / "values" / "idp" / "latest.json").read_text("utf-8")
        )
        assert latest["familyScope"]["quarantinedFamilies"] == ["signalsIdpDb"]
        q = list((tmp_path / "store" / "values" / "idp" / "quarantine").glob("*.json"))
        assert q and json.loads(q[0].read_text("utf-8"))["scope"] == "family"

    def test_a_failed_family_keeps_its_last_good_board_clock_and_stamp(self, tmp_path, family_flag):
        family_flag(True)
        good = _idp()
        _idp_run(tmp_path, good)
        db_csv = _csv(tmp_path, "signalsIdpDb")
        db_stamp = (tmp_path / "state" / "signalsIdpDb_last_success").read_text(encoding="utf-8")
        db_upstream = _ds(tmp_path, "signalsIdpDb")["upstream"]["publishedAt"]
        dl_before = _csv(tmp_path, "signalsIdpDl")

        later = _idp(stamps={"DT": "2026-10-03T10:00:00.000Z", "DE": "2026-10-03T10:00:00.000Z"})
        for it in later:  # a genuine DL/LB change
            it["value"] = it["value"] + 1
        out = _idp_run(tmp_path, _only(later, "DB", 2), at=T1)
        ds = out["datasets"]["idp"]
        assert ds["outcome"] == "partially_quarantined"
        # failed family: same bytes, same stamp, same upstream clock
        assert _csv(tmp_path, "signalsIdpDb") == db_csv
        assert (tmp_path / "state" / "signalsIdpDb_last_success").read_text(
            encoding="utf-8"
        ) == db_stamp
        assert _ds(tmp_path, "signalsIdpDb")["upstream"]["publishedAt"] == db_upstream
        assert ds["boardStatus"]["signalsIdpDb"]["rows"] == 28  # carried last good count
        # passing families moved on, with their own clock
        assert _csv(tmp_path, "signalsIdpDl") != dl_before
        assert (tmp_path / "state" / "signalsIdpDl_last_success").read_text(
            encoding="utf-8"
        ).strip() == str(int(T1.timestamp()))
        latest = json.loads(
            (tmp_path / "store" / "values" / "idp" / "latest.json").read_text("utf-8")
        )
        # latest.json stays the exact source of every CSV
        for key in IDP_KEYS:
            rows = [
                r for r in latest["boardRows"] if S.VALUE_DATASETS["idp"].board_key_for(r) == key
            ]
            assert S.render_board_csv(rows).encode("utf-8") == _csv(tmp_path, key)
        assert latest["boardRowCounts"]["signalsIdpDb"] == 28

        # recovery: the collapse guard compares against the carried GOOD count
        out3 = _idp_run(tmp_path, later, at=datetime(2026, 10, 5, 14, tzinfo=timezone.utc))
        assert out3["datasets"]["idp"]["outcome"] == "published"

    def test_internal_error_falls_back_to_release_level_quarantine(
        self, tmp_path, family_flag, monkeypatch
    ):
        family_flag(True)

        def boom(*a, **k):
            raise RuntimeError("synthetic planning failure")

        monkeypatch.setattr(S, "_family_scoped_plan", boom)
        out = _idp_run(tmp_path, _only(_idp(), "DB", 2))
        ds = out["datasets"]["idp"]
        assert ds["outcome"] == "quarantined"
        assert ds["familyQuarantineFallback"] == "RuntimeError"
        for key in IDP_KEYS:
            assert _csv(tmp_path, key) is None
            assert not (tmp_path / "state" / f"{key}_last_success").exists()

    def test_flag_on_and_all_families_passing_is_byte_identical_to_flag_off(
        self, tmp_path, family_flag
    ):
        results = {}
        for on in (False, True):
            family_flag(on)
            root = tmp_path / ("on" if on else "off")
            out = _idp_run(root, _idp())
            latest = json.loads(
                (root / "store" / "values" / "idp" / "latest.json").read_text(encoding="utf-8")
            )
            results[on] = (
                out["datasets"]["idp"]["outcome"],
                {k: _csv(root, k) for k in IDP_KEYS},
                latest["contentSha256"],
                latest["boardRows"],
            )
        assert results[False] == results[True]

    def test_offense_publication_is_unaffected(self, tmp_path, family_flag):
        uni = _universe(60)
        snaps = {
            sid: [_snap(sid, "2026-10-03", 9000 - 100 * i, pos_rank=i // 4 + 1)]
            for i, sid in enumerate(sorted(uni))
        }
        seen = {}
        for on in (False, True):
            family_flag(on)
            root = tmp_path / ("on" if on else "off")
            _write_payload(root / "repo", uni)
            out = _run(root, FakeAppSync(snapshots=snaps, idp_pages=[_only(_idp(), "DB", 2)]))
            off = out["datasets"]["offense"]
            assert off["outcome"] == "published"
            assert off["boardStatus"]["signalsSf"]["state"] == S.BOARD_ACCEPTED
            assert (root / "state" / "signalsSf_last_success").is_file()
            seen[on] = (
                _csv(root, "signalsSf"),
                off["contentSha256"],
                _ds(root, "signalsSf")["upstream"]["publishedAt"],
            )
            assert out["datasets"]["idp"]["outcome"] == (
                "partially_quarantined" if on else "quarantined"
            )
        assert seen[False] == seen[True]


def test_the_cli_exits_2_on_a_partial_quarantine(monkeypatch):
    from scripts import fetch_signals_values as F

    monkeypatch.setattr(
        F.S,
        "collect_values",
        lambda *a, **k: {
            "datasets": {
                "offense": {"outcome": "published"},
                "idp": {"outcome": "partially_quarantined"},
            }
        },
    )
    monkeypatch.setattr(F.S, "SignalsAuthTokens", lambda *a, **k: None)
    assert F.main([]) == 2


def test_a_family_clock_is_never_fresher_than_the_release_clock():
    """Per-family clocks can only make a family's evidence OLDER than the
    release-wide stamp it used to inherit — never fresher."""
    import random

    rng = random.Random(20261019)
    for _ in range(50):
        rows = [
            {
                "position": rng.choice(["DL", "LB", "DB"]),
                "value_as_of": rng.choice(
                    [
                        "",
                        "2026-09-20T10:00:00.000Z",
                        "2026-09-28T10:00:00.000Z",
                        "2026-10-01T09:00:00.000Z",
                    ]
                ),
            }
            for _ in range(30)
        ]
        release = S._board_as_of(rows)
        for fam in ("DL", "LB", "DB"):
            clock = S._board_as_of([r for r in rows if r["position"] == fam])
            assert clock is None or (release is not None and clock <= release)
