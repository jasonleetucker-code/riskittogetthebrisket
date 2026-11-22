"""Forward validation scoreboard (DYN10 V1) on synthetic ledgers.

Every expectation is computed by hand from the data the test writes:

* one cohort: all players are WR (family RB_WR_TE) priced 1040..2600 at
  every origin (tier "mid"), so the cohort-excess return is the raw return
  minus one shared median, and Spearman(gap, excess) equals the rank
  correlation of the designed gap and return orders;
* a source value ``s = (p + 1) * exp(g) - 1`` makes CE's ``log_gap(s, p)``
  exactly ``g``;
* Spearman with no ties and one adjacent swap among n is
  ``1 - 6 * 2 / (n * (n**2 - 1))``.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from datetime import date
from pathlib import Path

import pytest

from src.backtesting import forward_scoreboard as fs
from src.consensus_edge import outcomes as oc
from src.history import asof, backfill, keys, store

D0, D1, D2 = "2026-08-01", "2026-08-31", "2026-09-30"
MARKET = fs.MARKET_KTC_HISTORICAL  # ktcSfTep: the offense market before the KTC split
SOURCE = fs.MARKET_IDP  # idpTradeCalc, a predictor for offense rows


def _obs(
    asset_key: str,
    day: str,
    value: float,
    *,
    lane: str = store.LANE_SOURCE,
    source_key: str = MARKET,
    asset_class: str = keys.ASSET_CLASS_OFFENSE,
    position: str = "WR",
) -> dict:
    return {
        "asset_key": asset_key,
        "asset_class": asset_class,
        "lane": lane,
        "source_key": source_key,
        "observed_date": day,
        "observed_at": None,
        "observed_at_zone": None,
        "value": value,
        "rank": None,
        "tier": None,
        "confidence": None,
        "display_name": asset_key,
        "position": position,
        "player_id": None,
        "scope": None,
        "pipeline_version": None,
        "origin": "test:synthetic",
    }


def _write(path: Path, rows: list[dict]) -> None:
    result = store.write_observations(rows, path=path)
    assert not result["rejected"], result["rejected"]
    assert not result["contentConflicts"]


def _price(i: int) -> float:
    return 1000.0 + 40.0 * i  # i = 1..40 -> 1040..2600, tier "mid"


def _source_value(price: float, gap: float) -> float:
    return (price + 1.0) * math.exp(gap) - 1.0


def _fold_rows(
    day_from: str,
    day_to: str,
    n: int,
    gaps: dict[int, float],
    returns: dict[int, float],
    *,
    position: str = "WR",
    first: int = 1,
    prices: dict[int, float] | None = None,
) -> list[dict]:
    """Market at both ends plus the predictor source at the origin."""
    rows = []
    for i in range(first, first + n):
        key = f"player:{i}"
        p = (prices or {}).get(i, _price(i))
        rows.append(_obs(key, day_from, p, position=position))
        rows.append(_obs(key, day_to, p * (1.0 + returns[i]), position=position))
        if i in gaps:
            rows.append(
                _obs(key, day_from, _source_value(p, gaps[i]), source_key=SOURCE, position=position)
            )
    return rows


@pytest.fixture()
def ledger(tmp_path: Path) -> Path:
    store._reset_setup_cache_for_tests()
    return tmp_path / "ledger.sqlite"


def _swap(order: list[int], a: int, b: int) -> list[int]:
    out = list(order)
    ia, ib = out.index(a), out.index(b)
    out[ia], out[ib] = out[ib], out[ia]
    return out


def _source_summary(result: dict, horizon: int, group: str, source: str = SOURCE) -> dict:
    return result["horizons"][str(horizon)]["sources"][source]["byGroup"][group]


# ── Hand-computed correlation ───────────────────────────────────────────


def test_one_adjacent_swap_gives_the_hand_computed_rho(ledger: Path) -> None:
    n = 40
    order = _swap(list(range(1, n + 1)), 10, 11)
    gaps = {i: 0.01 * order.index(i) for i in range(1, n + 1)}
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    _write(ledger, _fold_rows(D0, D1, n, gaps, returns))

    result = fs.measure(ledger, horizons=(30,))
    summary = _source_summary(result, 30, "WR")
    expected = 1.0 - 6.0 * 2 / (n * (n * n - 1))
    assert summary["foldsUsable"] == 1
    (fold,) = summary["spearmanByFold"]
    assert fold["n"] == n
    assert fold["rho"] == pytest.approx(expected, abs=1e-12)
    # ALL is the same cross-section here: every asset is a WR.
    assert _source_summary(result, 30, "ALL")["spearmanByFold"][0]["rho"] == pytest.approx(
        expected, abs=1e-12
    )
    # One usable origin: no verdict.
    assert summary["verdict"].startswith("no verdict")


def test_gap_is_the_ce_log_gap_and_market_is_named_per_fold(ledger: Path) -> None:
    n = 32
    gaps = {i: 0.02 * i for i in range(1, n + 1)}
    returns = {i: 0.002 * i for i in range(1, n + 1)}
    _write(ledger, _fold_rows(D0, D1, n, gaps, returns))
    result = fs.measure(ledger, horizons=(30,))
    (fold,) = result["horizons"]["30"]["folds"]
    assert fold["instruments"][keys.ASSET_CLASS_OFFENSE] == MARKET
    assert fold["instruments"][keys.ASSET_CLASS_IDP] is None
    assert _source_summary(result, 30, "WR")["spearmanByFold"][0]["rho"] == pytest.approx(1.0)


# ── Missing is never zero ───────────────────────────────────────────────


def test_missing_and_nonpositive_source_values_are_excluded_not_zero(ledger: Path) -> None:
    n = 40
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    # Assets 36..40 have no source observation; asset 35 publishes 0.
    gaps = {i: 0.01 * i for i in range(1, 35)}
    rows = _fold_rows(D0, D1, n, gaps, returns)
    rows.append(_obs("player:35", D0, 0.0, source_key=SOURCE))
    _write(ledger, rows)

    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    (fold,) = summary["spearmanByFold"]
    # 34 real values, perfectly ordered with the returns.  Had the six
    # missing values been read as 0 they would carry the most negative gap
    # beside the highest returns and pull rho well below 1.
    assert fold["n"] == 34
    assert fold["rho"] == pytest.approx(1.0)


def test_a_series_with_no_observation_at_the_origin_is_unusable_with_reason(
    ledger: Path,
) -> None:
    n = 32
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    rows = _fold_rows(D0, D1, n, {}, returns)
    # The predictor is observed only AFTER the origin.
    rows += [_obs(f"player:{i}", D1, 500.0 + i, source_key=SOURCE) for i in range(1, n + 1)]
    _write(ledger, rows)
    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    assert summary["foldsUsable"] == 0
    assert summary["originsUnusable"] == [
        {"origin": D0, "n": 0, "reason": fs.REASON_NO_OBSERVATION, "zeroGapShare": None}
    ]


def test_an_asset_without_a_horizon_price_is_attrition_not_a_zero_return(ledger: Path) -> None:
    n = 33
    gaps = {i: 0.01 * i for i in range(1, n + 1)}
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    rows = [
        r
        for r in _fold_rows(D0, D1, n, gaps, returns)
        if not (r["asset_key"] == "player:33" and r["observed_date"] == D1)
    ]
    _write(ledger, rows)
    result = fs.measure(ledger, horizons=(30,))
    (fold,) = result["horizons"]["30"]["folds"]
    assert fold["attrition"]["byReason"] == {oc.NO_FUTURE_PRICE: 1}
    assert _source_summary(result, 30, "WR")["spearmanByFold"][0]["n"] == 32


# ── Leakage ─────────────────────────────────────────────────────────────


def _leakage_base() -> list[dict]:
    n = 36
    order = _swap(list(range(1, n + 1)), 3, 4)
    gaps = {i: 0.01 * order.index(i) for i in range(1, n + 1)}
    returns = {i: 0.003 * ((i * 7) % n) for i in range(1, n + 1)}
    return _fold_rows(D0, D1, n, gaps, returns)


def test_no_observation_after_the_origin_changes_a_predictor(tmp_path: Path) -> None:
    store._reset_setup_cache_for_tests()
    clean = tmp_path / "clean.sqlite"
    noisy = tmp_path / "noisy.sqlite"
    _write(clean, _leakage_base())
    future = []
    for i in range(1, 37):
        key = f"player:{i}"
        # The predictor's own later values, wildly different, and a board
        # that exists only after the origin.
        future.append(_obs(key, "2026-08-02", 9000.0 - 200 * i, source_key=SOURCE))
        future.append(_obs(key, D1, 50.0 * i, source_key=SOURCE))
        future.append(_obs(key, D1, 3000.0, lane=store.LANE_CANONICAL, source_key=""))
    _write(noisy, _leakage_base() + future)

    a = fs.measure(clean, horizons=(30,))
    b = fs.measure(noisy, horizons=(30,))
    assert a["horizons"]["30"]["folds"][0]["horizon"] == b["horizons"]["30"]["folds"][0]["horizon"]
    sa, sb = _source_summary(a, 30, "WR"), _source_summary(b, 30, "WR")
    assert sa["spearmanByFold"] == sb["spearmanByFold"]
    # The future-only board is not a board at the origin.
    assert b["horizons"]["30"]["board"]["status"] == "unavailable"


def test_reads_after_the_origin_are_market_instruments_only(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(ledger, _leakage_base())
    seen: list[tuple[str, str, str | None]] = []
    real_census, real_batch = asof.assets_observed_on, asof.batch_as_of

    def census(on_date, *, lane, source_key=None, path=None):
        seen.append((store.as_of_date(on_date), lane, source_key))
        return real_census(on_date, lane=lane, source_key=source_key, path=path)

    def batch(asset_keys, on_date, *, lane, source_key="", max_age_days=None, path=None):
        assert max_age_days == 0, "a predictor must be an exact observation, never carried forward"
        seen.append((store.as_of_date(on_date), lane, source_key))
        return real_batch(
            asset_keys, on_date, lane=lane, source_key=source_key, max_age_days=0, path=path
        )

    monkeypatch.setattr(asof, "assets_observed_on", census)
    monkeypatch.setattr(asof, "batch_as_of", batch)
    fs.measure(ledger, horizons=(30,))
    later = {(lane, key) for day, lane, key in seen if day > D0}
    assert later, "the outcome must read the horizon"
    assert all(lane == store.LANE_SOURCE and key in fs._MARKET_KEYS for lane, key in later)


# ── Per origin, never pooled ────────────────────────────────────────────


def test_origins_are_separate_cross_sections_and_averaged(ledger: Path) -> None:
    n1, n2 = 40, 35
    ret1 = {i: 0.001 * i for i in range(1, n1 + 1)}
    rows = _fold_rows(D0, D1, n1, {i: 0.01 * i for i in range(1, n1 + 1)}, ret1)
    # Fold 2 starts from fold 1's horizon prices; its returns run the other way.
    prices_d1 = {i: _price(i) * (1.0 + ret1[i]) for i in range(1, n2 + 1)}
    ret2 = {i: -0.001 * i for i in range(1, n2 + 1)}
    for i in range(1, n2 + 1):
        key = f"player:{i}"
        rows.append(_obs(key, D2, prices_d1[i] * (1.0 + ret2[i])))
        rows.append(_obs(key, D1, _source_value(prices_d1[i], 0.01 * i), source_key=SOURCE))
    _write(ledger, rows)

    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    by_fold = summary["spearmanByFold"]
    assert [(f["origin"], f["n"]) for f in by_fold] == [(D0, n1), (D1, n2)]
    assert by_fold[0]["rho"] == pytest.approx(1.0)
    assert by_fold[1]["rho"] == pytest.approx(-1.0)
    assert summary["meanSpearman"] == pytest.approx(0.0, abs=1e-12)
    assert summary["foldsUsable"] == 2
    assert summary["foldsPositive"] == 1
    assert not summary["verdict"].startswith("no verdict")


# ── Horizon snapping ────────────────────────────────────────────────────


def test_horizon_snaps_forward_to_the_first_available_date(ledger: Path) -> None:
    n = 32
    gaps = {i: 0.01 * i for i in range(1, n + 1)}
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    snapped = "2026-09-03"  # 33 days after D0; 2026-08-31 has no observation
    rows = _fold_rows(D0, snapped, n, gaps, returns)
    rows += [_obs(f"player:{i}", "2026-08-20", _price(i)) for i in range(1, n + 1)]
    rows += [_obs(f"player:{i}", "2026-09-10", _price(i)) for i in range(1, n + 1)]
    _write(ledger, rows)

    result = fs.measure(ledger, horizons=(30,))
    folds = result["horizons"]["30"]["folds"]
    assert folds[0]["origin"] == D0
    assert folds[0]["horizon"] == snapped
    assert folds[0]["heldDays"] == 33
    available = [date.fromisoformat(d) for d in (D0, "2026-08-20", snapped, "2026-09-10")]
    assert oc.horizon_date(date.fromisoformat(D0), 30, available).isoformat() == snapped


def test_a_horizon_longer_than_the_panel_has_no_folds_and_no_verdict(ledger: Path) -> None:
    n = 32
    _write(ledger, _fold_rows(D0, D1, n, {}, {i: 0.0 for i in range(1, n + 1)}))
    block = fs.measure(ledger, horizons=(90,))["horizons"]["90"]
    assert block["foldsAttempted"] == 0
    assert "shorter than 90 days" in block["foldsNote"]
    assert block["sources"][MARKET]["byGroup"]["ALL"]["verdict"].startswith("no verdict")


# ── Minimum-pairs floor ─────────────────────────────────────────────────


def test_minimum_pairs_floor_per_group(ledger: Path) -> None:
    wr, te = fs.MIN_PAIRS, fs.MIN_PAIRS - 1
    returns = {i: 0.001 * i for i in range(1, wr + te + 1)}
    gaps = {i: 0.01 * i for i in range(1, wr + te + 1)}
    rows = _fold_rows(D0, D1, wr, gaps, returns)
    rows += _fold_rows(D0, D1, te, gaps, returns, position="TE", first=wr + 1)
    _write(ledger, rows)

    result = fs.measure(ledger, horizons=(30,))
    assert _source_summary(result, 30, "WR")["foldsUsable"] == 1
    te_summary = _source_summary(result, 30, "TE")
    assert te_summary["foldsUsable"] == 0
    assert te_summary["originsUnusable"][0]["reason"] == (
        f"only {te} paired rows (need {fs.MIN_PAIRS})"
    )
    persistence_te = result["horizons"]["30"]["folds"][0]["persistence"]["TE"]
    assert persistence_te["r2LogLevel"] is None and persistence_te["n"] == te


# ── Board, instruments, persistence ─────────────────────────────────────


def test_board_is_measured_when_the_ledger_holds_it(ledger: Path) -> None:
    n = 32
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    rows = _fold_rows(D0, D1, n, {}, returns)
    rows += [
        _obs(
            f"player:{i}",
            D0,
            _source_value(_price(i), -0.01 * i),
            lane=store.LANE_CANONICAL,
            source_key="",
        )
        for i in range(1, n + 1)
    ]
    _write(ledger, rows)
    board = fs.measure(ledger, horizons=(30,))["horizons"]["30"]["board"]
    assert board["status"] == "measured"
    assert board["byGroup"]["WR"]["spearmanByFold"][0]["rho"] == pytest.approx(-1.0)


def test_board_unavailable_names_the_reason(ledger: Path) -> None:
    n = 32
    _write(ledger, _fold_rows(D0, D1, n, {}, {i: 0.001 * i for i in range(1, n + 1)}))
    board = fs.measure(ledger, horizons=(30,))["horizons"]["30"]["board"]
    assert board["status"] == "unavailable"
    assert "canonical_board" in board["reason"]
    assert "byGroup" not in board


def test_a_source_that_is_the_market_instrument_is_not_scored_against_itself(
    ledger: Path,
) -> None:
    n = 32
    _write(ledger, _fold_rows(D0, D1, n, {}, {i: 0.001 * i for i in range(1, n + 1)}))
    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR", source=MARKET)
    assert summary["originsUnusable"][0]["reason"] == fs.REASON_IS_TARGET


def test_instrument_chain_per_asset_class() -> None:
    observed = {
        (fs.MARKET_KTC, D0): {keys.ASSET_CLASS_OFFENSE, keys.ASSET_CLASS_PICK},
        (fs.MARKET_KTC, D1): {keys.ASSET_CLASS_OFFENSE, keys.ASSET_CLASS_PICK},
        (fs.MARKET_KTC_HISTORICAL, D0): {keys.ASSET_CLASS_OFFENSE},
        (fs.MARKET_KTC_HISTORICAL, D1): {keys.ASSET_CLASS_OFFENSE},
        ("ktc", D0): {keys.ASSET_CLASS_OFFENSE, keys.ASSET_CLASS_PICK},
        ("ktc", D1): {keys.ASSET_CLASS_OFFENSE, keys.ASSET_CLASS_PICK},
        (fs.MARKET_IDP, D0): {keys.ASSET_CLASS_IDP},
    }

    def classes_on(inst: str, day: str) -> set[str]:
        return observed.get((inst, day), set())

    both = fs.fold_instruments(D0, D1, classes_on)
    assert both[keys.ASSET_CLASS_OFFENSE] == fs.MARKET_KTC
    assert both[keys.ASSET_CLASS_PICK] == fs.MARKET_KTC
    # IDP observed at the origin only: no instrument rather than a mix.
    assert both[keys.ASSET_CLASS_IDP] is None

    del observed[(fs.MARKET_KTC, D1)]  # KTC Market missing at the horizon
    fallback = fs.fold_instruments(D0, D1, classes_on)
    assert fallback[keys.ASSET_CLASS_OFFENSE] == fs.MARKET_KTC_HISTORICAL
    # ktcSfTep carries no picks in the archive; picks fall through to ktc.
    assert fallback[keys.ASSET_CLASS_PICK] == "ktc"


def test_persistence_is_one_when_the_market_does_not_move() -> None:
    prices = {f"player:{i}": _price(i) for i in range(1, 41)}
    out = fs.persistence(prices, prices, {k: v * 1.05 for k, v in prices.items()})
    assert out["n"] == 40
    assert out["spearmanLevel"] == pytest.approx(1.0)
    assert out["r2LogLevel"] == pytest.approx(1.0)
    assert out["medianAbsLogReturn"] == pytest.approx(math.log(1.05))
    assert out["unchangedShare"] == 0.0
    frozen = fs.persistence(prices, prices, prices)
    assert frozen["unchangedShare"] == 1.0 and frozen["medianAbsLogReturn"] == 0.0


def test_increment_over_persistence_is_the_ols_identity() -> None:
    ks = [f"player:{i}" for i in range(1, 41)]
    pd = {k: _price(i) for i, k in enumerate(ks, start=1)}
    gaps = {k: ((i * 13) % 40) / 40.0 for i, k in enumerate(ks, start=1)}
    ph = {k: pd[k] * math.exp(0.05 * gaps[k] + 0.001 * ((i * 7) % 11)) for i, k in enumerate(ks, 1)}
    inc = fs.increment_over_persistence(ks, gaps, pd, ph)

    # Reference: R2 of log(ph) on [1, log(pd), gap] minus R2 on [1, log(pd)],
    # by explicit normal equations.
    def r2(cols: list[list[float]], y: list[float]) -> float:
        n, k = len(y), len(cols)
        x = [[1.0] + [c[r] for c in cols] for r in range(n)]
        xtx = [
            [sum(x[r][i] * x[r][j] for r in range(n)) for j in range(k + 1)] for i in range(k + 1)
        ]
        xty = [sum(x[r][i] * y[r] for r in range(n)) for i in range(k + 1)]
        m = [row[:] + [v] for row, v in zip(xtx, xty)]
        size = k + 1
        for c in range(size):
            piv = max(range(c, size), key=lambda r: abs(m[r][c]))
            m[c], m[piv] = m[piv], m[c]
            for r in range(size):
                if r != c:
                    f = m[r][c] / m[c][c]
                    m[r] = [a - f * b for a, b in zip(m[r], m[c])]
        beta = [m[i][size] / m[i][i] for i in range(size)]
        fit = [sum(b * xi for b, xi in zip(beta, x[r])) for r in range(n)]
        my = sum(y) / n
        ss_res = sum((yv - fv) ** 2 for yv, fv in zip(y, fit))
        ss_tot = sum((yv - my) ** 2 for yv in y)
        return 1.0 - ss_res / ss_tot

    y = [math.log(ph[k]) for k in ks]
    x0 = [math.log(pd[k]) for k in ks]
    g = [gaps[k] for k in ks]
    assert inc["r2Persistence"] == pytest.approx(r2([x0], y), abs=1e-9)
    assert inc["deltaR2"] == pytest.approx(r2([x0, g], y) - r2([x0], y), abs=1e-9)
    assert inc["partialR"] > 0


# ── Archive build (site_raw ingest) ─────────────────────────────────────


def _bundle(path: Path, day: str, *, fresh: list[str]) -> None:
    raw = {
        "date": day,
        "scrapeTimestamp": f"{day}T20:00:00",
        "players": {
            "Alpha Player": {"ktcSfTep": 5000, "_sleeperId": "111"},
            "2027 Early 1st": {"ktc": 6000},
        },
        "sleeper": {"positions": {"Alpha Player": "WR"}},
    }
    market_csv = "name,value,rank,player_id,position,team\n"
    market_csv += "Alpha Player,5050,1,9,WR,AAA\n2027 Early 1st,6100,2,10,RDP,FA\n"
    market_csv += "Nobody Known,120,3,11,WR,BBB\nZero Value,0,4,12,WR,CCC\n"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"date": day, "siteRawFresh": fresh}))
        z.writestr(f"dynasty_data_{day}.json", json.dumps(raw))
        z.writestr("site_raw/ktcCrowdTradesSfTep.csv", market_csv)
        z.writestr("site_raw/ktcTradesSfTep.csv", market_csv)
        # Payload-stage CSVs: their freshness gates the backfill's values.
        z.writestr("site_raw/ktcSfTep.csv", "name,value,position,team\n")
        z.writestr("site_raw/ktc.csv", "name,value,position,team\n")


def test_archive_build_keys_csv_rows_like_the_payload_and_skips_stale_csvs(
    tmp_path: Path,
) -> None:
    store._reset_setup_cache_for_tests()
    archive = tmp_path / "archive"
    archive.mkdir()
    stamp = "20260910_200000"  # a synthetic bundle written to tmp_path, not the archive
    _bundle(
        archive / f"dynasty_export_{stamp}.zip",
        "2026-09-10",
        fresh=["ktcCrowdTradesSfTep.csv", "ktc.csv"],
    )
    ledger = tmp_path / "ledger.sqlite"
    build = fs.build_archive_ledger(archive, ledger)

    market = asof.assets_observed_on(
        "2026-09-10", lane=store.LANE_SOURCE, source_key=fs.MARKET_KTC, path=ledger
    )
    pick_key = keys.pick_asset_key("2027 Early 1st")
    assert "player:111" in market and pick_key in market

    # The CSV rows and the backfill's payload rows for the same names share
    # keys: the player through its _sleeperId, the pick through the pick owner.
    def payload(source_key: str) -> set[str]:
        return set(
            asof.assets_observed_on(
                "2026-09-10", lane=store.LANE_SOURCE, source_key=source_key, path=ledger
            )
        )

    assert payload("ktcSfTep") == {"player:111"}
    assert payload("ktc") == {pick_key}
    assert market["player:111"]["assetClass"] == keys.ASSET_CLASS_OFFENSE
    assert market[pick_key]["assetClass"] == keys.ASSET_CLASS_PICK
    # An unknown name gets the identity-grade name key, never a guess; a zero
    # value is missing.
    assert any(k.startswith(keys.NAME_PREFIX) for k in market)
    by_source = build["siteRawIngest"]["bySource"]
    assert by_source[fs.MARKET_KTC]["nonPositiveOrBlank"] == 1
    assert by_source[fs.MARKET_KTC]["nameKeyed"] == 1
    # ktcTradesSfTep is in the bundle but not freshly fetched: skipped.
    assert by_source[fs.KTC_TRADES_KEY] == {"skippedNotFresh": 1}
    assert (
        asof.observed_dates(lane=store.LANE_SOURCE, source_key=fs.KTC_TRADES_KEY, path=ledger) == []
    )
    assert build["archive"]["zipCount"] == 1
    # Same bundle selection as the backfill.
    assert [d for d, _ in backfill._select_by_date(archive)] == ["2026-09-10"]

    # Payload freshness gate: the bundle carries ktcSfTep.csv but does not
    # list it as fresh, so the backfill's ktcSfTep values that day are a
    # carry-forward and read as missing.  ktc.csv is fresh; idpTradeCalc.csv
    # is absent (nothing to gate).
    assert build["notFresh"] == [["2026-09-10", "ktcSfTep"]]
    masked = fs._LedgerReader(ledger, build["notFresh"])
    assert masked.exact("2026-09-10", store.LANE_SOURCE, "ktcSfTep") == {}
    assert set(masked.exact("2026-09-10", store.LANE_SOURCE, "ktc")) == {pick_key}
    assert set(fs._LedgerReader(ledger).exact("2026-09-10", store.LANE_SOURCE, "ktcSfTep")) == {
        "player:111"
    }


def test_archive_build_refuses_the_production_ledger(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="production ledger"):
        fs.build_archive_ledger(tmp_path, store.DB_PATH)
    with pytest.raises(ValueError, match="production ledger"):
        fs.ingest_site_raw_market_modes(tmp_path, path=store.DB_PATH)


def test_archive_build_without_bundles_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(fs.ArchiveUnavailable):
        fs.build_archive_ledger(tmp_path / "missing", tmp_path / "l.sqlite")


# ── CLI ─────────────────────────────────────────────────────────────────


def _cli():
    from scripts import forward_validation_scoreboard as cli

    return cli


def test_cli_refuses_reserved_inputs_and_bad_horizons(tmp_path: Path) -> None:
    cli = _cli()
    forbidden = cli.REPO / "data" / "market_trades" / "anything"
    assert cli.main(["--archive-dir", str(forbidden), "--dry-run"]) == 2
    assert cli.main(["--ledger", str(cli.REPO / "docs" / "market_trades"), "--dry-run"]) == 2
    assert cli.main(["--horizons", "0", "--dry-run"]) == 2
    assert cli.main(["--archive-dir", str(tmp_path / "none"), "--dry-run"]) == 1


def test_cli_ledger_mode_reads_a_copy_and_writes_both_outputs(tmp_path: Path) -> None:
    store._reset_setup_cache_for_tests()
    source = tmp_path / "source.sqlite"
    n = 32
    gaps = {i: 0.01 * i for i in range(1, n + 1)}
    _write(source, _fold_rows(D0, D1, n, gaps, {i: 0.001 * i for i in range(1, n + 1)}))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    out = tmp_path / "out" / "fs.json"
    assert _cli().main(["--ledger", str(source), "--horizons", "30", "--out", str(out)]) == 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["inputs"]["mode"] == "ledger"
    assert payload["inputs"]["ledgerCorrections"] == 0
    assert payload["realizedPoints"]["state"] == "unavailable"
    assert payload["independentValidationCandidate"]["registered"] is False
    md = out.with_suffix(".md").read_text(encoding="utf-8")
    assert "Board: unavailable" in md and "Horizon 30 days" in md


def test_render_markdown_handles_an_empty_result() -> None:
    text = fs.render_markdown({"horizons": {}, "caveats": ["c"]}, title="t")
    assert text.startswith("# t") and "- c" in text
    assert isinstance(io.StringIO(text).read(), str)


# ── Informative rows ────────────────────────────────────────────────────


def test_an_all_zero_gap_group_is_unusable(ledger: Path) -> None:
    n = 40
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    rows = _fold_rows(D0, D1, n, {i: 0.0 for i in range(1, n + 1)}, returns)
    _write(ledger, rows)
    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    assert summary["foldsUsable"] == 0
    (unusable,) = summary["originsUnusable"]
    assert unusable["n"] == n
    assert unusable["reason"] == f"only 0 distinct non-zero gaps (need {fs.MIN_PAIRS})"
    assert unusable["zeroGapShare"] == 1.0


def test_a_near_constant_gap_group_is_unusable_and_reports_its_zero_share(
    ledger: Path,
) -> None:
    # 40 pairs, but the source equals the market on 35 of them: only 5 rows
    # carry information, below the floor, although the pair count passes it.
    n = 40
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    gaps = {i: (0.01 * i if i > 35 else 0.0) for i in range(1, n + 1)}
    _write(ledger, _fold_rows(D0, D1, n, gaps, returns))
    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    assert summary["foldsUsable"] == 0
    (unusable,) = summary["originsUnusable"]
    assert unusable["reason"] == f"only 5 distinct non-zero gaps (need {fs.MIN_PAIRS})"
    assert unusable["zeroGapShare"] == pytest.approx(35 / 40)


def test_a_usable_cell_reports_its_zero_gap_share(ledger: Path) -> None:
    n = 40
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    gaps = {i: (0.01 * i if i > 8 else 0.0) for i in range(1, n + 1)}  # 32 informative
    _write(ledger, _fold_rows(D0, D1, n, gaps, returns))
    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    (fold,) = summary["spearmanByFold"]
    assert fold["distinctNonZeroGaps"] == 32
    assert fold["zeroGapShare"] == pytest.approx(8 / 40)
    assert summary["meanZeroGapShare"] == pytest.approx(8 / 40)


@pytest.mark.parametrize(("zeros", "usable"), [(32, True), (33, False)])
def test_a_majority_zero_gap_cell_is_unusable(ledger: Path, zeros: int, usable: bool) -> None:
    # 32 informative rows always pass the distinct-gap floor.  With 32 zero
    # rows the zero-gap share is exactly 0.5 (allowed); with 33 it is
    # 33 / 65 > 0.5, and the cell no longer measures disagreement.
    informative = 32
    n = zeros + informative
    returns = {i: 0.001 * i for i in range(1, n + 1)}
    gaps = {i: (0.0 if i <= zeros else 0.01 * i) for i in range(1, n + 1)}
    _write(ledger, _fold_rows(D0, D1, n, gaps, returns))
    summary = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")
    assert summary["foldsUsable"] == (1 if usable else 0)
    if usable:
        assert summary["spearmanByFold"][0]["zeroGapShare"] == pytest.approx(0.5)
    else:
        (unusable,) = summary["originsUnusable"]
        assert unusable["n"] == n
        assert unusable["zeroGapShare"] == pytest.approx(zeros / n)
        assert unusable["reason"].startswith(
            f"zero-gap share {zeros / n:.3f} exceeds {fs.MAX_ZERO_GAP_SHARE}"
        )


# ── Momentum control ────────────────────────────────────────────────────

DP, DD, DH = "2026-07-15", "2026-08-14", "2026-09-13"  # 30 days apart


def _momentum_rows(*, stale_source: bool, seed: int = 20261122) -> list[dict]:
    """120 WR in one cohort.  The market moves m from DP to DD, then about
    m / 2 more to DH (momentum).  A stale source repeats the DP price with
    a little noise, so its gap is about -m; a genuine source carries
    information independent of m that the outcome also loads on."""
    import random

    rng = random.Random(seed)
    rows: list[dict] = []
    for i in range(1, 121):
        key = f"player:{i}"
        p0 = 1100.0 + 14.0 * i  # 1114..2780, so 1060..2923 after m: tier "mid" throughout
        m = 0.05 * rng.uniform(-1.0, 1.0)
        info = 0.05 * rng.uniform(-1.0, 1.0)
        p1 = p0 * math.exp(m)
        if stale_source:
            source = p0 * math.exp(0.01 * rng.gauss(0.0, 1.0))
            r = 0.5 * m + 0.01 * rng.gauss(0.0, 1.0)
        else:
            source = _source_value(p1, info)
            r = 0.5 * m + 0.5 * info + 0.01 * rng.gauss(0.0, 1.0)
        rows.append(_obs(key, DP, p0))
        rows.append(_obs(key, DD, p1))
        rows.append(_obs(key, DH, p1 * (1.0 + r)))
        rows.append(_obs(key, DD, source, source_key=SOURCE))
    return rows


def test_a_stale_source_gap_is_momentum_and_its_partial_is_near_zero(ledger: Path) -> None:
    _write(ledger, _momentum_rows(stale_source=True))
    result = fs.measure(ledger, horizons=(30,))
    folds = result["horizons"]["30"]["folds"]
    assert [f["origin"] for f in folds] == [DP, DD]
    assert folds[0]["momentum"]["priorDate"] is None  # first origin: no lookback
    assert folds[1]["momentum"]["priorDate"] == DP
    summary = _source_summary(result, 30, "WR")
    (fold,) = summary["spearmanByFold"]  # the source exists only at DD
    assert fold["origin"] == DD
    # The raw gap looks strongly predictive -- with the wrong sign for a
    # "market moves toward the source" story -- because it IS minus the
    # market's past move, and the market has momentum.
    assert fold["rho"] < -0.6
    assert fold["rhoGapVsPriorReturn"] < -0.9
    assert fold["rhoMomentum"] > 0.8
    assert fold["momentumN"] == 120
    assert abs(fold["partialRhoGivenMomentum"]) < 0.15
    # One origin with a momentum control: no verdict.
    assert summary["momentumControl"]["originsMeasured"] == 1
    assert summary["momentumControl"]["verdict"].startswith("no verdict")


def test_a_genuine_edge_survives_the_momentum_control(ledger: Path) -> None:
    _write(ledger, _momentum_rows(stale_source=False))
    (fold,) = _source_summary(fs.measure(ledger, horizons=(30,)), 30, "WR")["spearmanByFold"]
    assert abs(fold["rhoGapVsPriorReturn"]) < 0.3
    assert fold["partialRhoGivenMomentum"] > 0.6


def test_predictor_staleness_is_measured_against_the_lookback_date(ledger: Path) -> None:
    rows = _momentum_rows(stale_source=False)
    # The source also reported at DP: identical values on 30 of 120 assets.
    for i in range(1, 121):
        key = f"player:{i}"
        at_dd = next(r for r in rows if r["asset_key"] == key and r["source_key"] == SOURCE)
        value = at_dd["value"] if i <= 30 else at_dd["value"] * 1.1
        rows.append(_obs(key, DP, value, source_key=SOURCE))
    _write(ledger, rows)
    folds = fs.measure(ledger, horizons=(30,))["horizons"]["30"]["folds"]
    staleness = folds[1]["predictorStaleness"][SOURCE]
    assert staleness == {"n": 120, "unchangedShare": pytest.approx(30 / 120)}
    assert folds[0]["predictorStaleness"][SOURCE] == {"n": 0, "unchangedShare": None}


def test_prior_date_snaps_backward() -> None:
    available = [date(2026, 7, 14), date(2026, 7, 20), date(2026, 8, 13)]
    assert fs.prior_date(date(2026, 8, 13), 30, available) == date(2026, 7, 14)
    assert fs.prior_date(date(2026, 8, 25), 30, available) == date(2026, 7, 20)
    assert fs.prior_date(date(2026, 8, 12), 30, available) is None


def test_partial_rank_correlation_refuses_a_collinear_control() -> None:
    xs = [float(i) for i in range(40)]
    ys = [float((i * 7) % 40) for i in range(40)]
    assert fs.partial_rank_correlation(xs, ys, [-x for x in xs]) is None
    # With an unrelated control the partial is close to the plain rho.
    zs = [float((i * 13) % 40) for i in range(40)]
    plain = fs.bt.spearman(xs, ys)
    assert fs.partial_rank_correlation(xs, ys, zs) == pytest.approx(plain, abs=0.2)
