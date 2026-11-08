"""CW-40 / master-site-audit P1 re-adjudication, BATCH M1 (value pipeline / sources / scoring identity).

Fresh adjudication of 17 findings the 2026-11-06 recount could not adjudicate
(see ``docs/audits/remediation_2026-11-06/CW40_P1_BATCH_M1.md`` for the per-finding verdicts).

Everything here is offline and deterministic:

* the board is built by the real ``build_api_data_contract`` from the PINNED, git-tracked archive
  ``exports/archive/dynasty_export_20261106_194518.zip`` (never ``exports/latest`` and never a live
  board, so the 2-hourly refresh cannot move any assertion);
* scoring / league-identity checks use the committed audit fixtures under
  ``docs/master-site-audit/evidence/``;
* the remaining checks are pure functions on synthetic inputs or source-shape scans.

Layout: tests that PASS pin a CLOSED_VERIFIED (or the closed half of a PARTIAL) behaviour; tests marked
``xfail(strict=True)`` pin the still-open half and flip (XPASS -> failure) when a repair lands, forcing
whoever repairs it to retire the xfail.  Nothing in this file changes served behaviour.
"""

from __future__ import annotations

import datetime as _dt
import json
import statistics
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20261106_194518.zip"
EVIDENCE = REPO / "docs" / "master-site-audit" / "evidence"
IDP = {"DL", "LB", "DB", "DE", "DT", "CB", "S", "SS", "FS", "EDGE"}
_cache: dict = {}


def _board() -> dict:
    if "board" not in _cache:
        if not ARCHIVE.is_file():
            pytest.skip("pinned archive bundle absent")
        from src.api.data_contract import build_api_data_contract

        with zipfile.ZipFile(ARCHIVE) as zf:
            name = next(
                n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            raw = json.loads(zf.read(name))
        _cache["board"] = build_api_data_contract(raw)
    return _cache["board"]


def _rows() -> list[dict]:
    return _board()["playersArray"]


def _card(fixture: str) -> dict:
    doc = json.loads((EVIDENCE / "W18" / fixture).read_text(encoding="utf-8"))
    return doc.get("scoring_settings") or {}


# ---------------------------------------------------------------------------
# W02-F001  IDP-only sources priced on the wrong Hill master      CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w02_f001_translated_idp_votes_sit_near_the_anchor_not_at_half_of_it():
    """August: dlfIdp/idpShow/fantasyProsIdp contributed a median 0.46-0.49 of idpTradeCalc's value
    on the same row.  Coordinate-pool routing (``rank_coordinates``) now prices a shared-market rank on
    the shared-market (GLOBAL) master.  Pinned: every translated rank_hill source's median ratio to the
    anchor is far from the defective ~0.48 (and well within the offense cluster's band)."""
    ratios: dict[str, list[float]] = {}
    for row in _rows():
        if row.get("position") not in IDP:
            continue
        meta = row.get("sourceRankMeta") or {}
        anchor = (meta.get("idpTradeCalc") or {}).get("valueContribution")
        if not anchor:
            continue
        for key, m in meta.items():
            if (
                key != "idpTradeCalc"
                and isinstance(m, dict)
                and m.get("valueContributionPath") == "rank_hill"
                and m.get("valueContribution")
            ):
                ratios.setdefault(key, []).append(m["valueContribution"] / anchor)
    assert ratios, "no IDP rank_hill sources on the pinned board"
    for key, vals in ratios.items():
        assert len(vals) >= 50, (key, len(vals))
        med = statistics.median(vals)
        assert 0.8 <= med <= 1.5, f"{key}: median contribution/anchor {med:.3f}"


def test_w02_f001_every_translated_rank_is_stamped_with_the_shared_market_pool():
    n = 0
    for row in _rows():
        for key, m in (row.get("sourceRankMeta") or {}).items():
            if isinstance(m, dict) and m.get("sharedMarketTranslated") is True:
                n += 1
                assert m.get("rankCoordinatePool") == "shared_market", (key, row["displayName"])
    assert n > 100


# ---------------------------------------------------------------------------
# W02-F002  Hampel ejects the IDP anchor                          CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w02_f002_idp_anchor_is_not_ejected_at_scale():
    eligible = ejected = 0
    for row in _rows():
        if row.get("position") not in IDP:
            continue
        meta = row.get("sourceRankMeta") or {}
        if "idpTradeCalc" not in meta or len(meta) < 4:
            continue
        eligible += 1
        if "idpTradeCalc" in (row.get("droppedSources") or []):
            ejected += 1
    assert eligible > 100
    # August: 52 / 177 (29.4%).  The claim's own bar is "low single digit".
    assert 100.0 * ejected / eligible <= 5.0, (ejected, eligible)


# ---------------------------------------------------------------------------
# W02-F003  market corridor clamp                  CLOSED_VERIFIED (deleted, invariant pinned)
# ---------------------------------------------------------------------------


def test_w02_f003_corridor_machinery_is_gone_from_the_module():
    from src.api import data_contract as dc

    for name in (
        "_apply_market_corridor_clamp",
        "_market_anchor_for_row",
        "_MARKET_ANCHOR_BY_ASSET_CLASS",
        "_MARKET_CORRIDOR_PERCENTILE",
        "_MARKET_CORRIDOR_MIN_BUCKET_N",
        "_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS",
    ):
        assert not hasattr(dc, name), f"{name} came back"


def test_w02_f003_no_idp_row_is_snapped_to_anchor_times_085_or_115():
    """August: 43.3% of ranked IDP rows were rewritten to exactly idpTradeCalc x 0.85 / x 1.15."""
    seen = snapped = 0
    for row in _rows():
        if row.get("position") not in IDP:
            continue
        anchor = ((row.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}).get(
            "valueContribution"
        )
        value = row.get("rankDerivedValue")
        if not anchor or not value:
            continue
        seen += 1
        if abs(value - anchor * 0.85) <= 1 or abs(value - anchor * 1.15) <= 1:
            snapped += 1
    assert seen > 200
    assert snapped == 0


def test_w02_f003_the_protected_invariant_is_the_blend_hull_and_it_is_enforced():
    """What the clamp was FOR (a published blend that leaves its own contributions' range) is now a
    hull DETECTOR that abstains (quarantine flag) instead of coercing.  Pinned: the detector exists,
    its flag is quarantine-level, and the pinned board trips none (existing deeper pins:
    ``tests/api/test_blend_integrity.py``)."""
    from src.api import data_contract as dc

    assert callable(dc._detect_blend_integrity_violations)
    assert "blend_integrity_violation" in dc._QUARANTINE_FLAGS
    flagged = [r for r in _rows() if "blend_integrity_violation" in (r.get("anomalyFlags") or [])]
    assert flagged == []


# ---------------------------------------------------------------------------
# W03-F004  confidence rises when sources disappear               CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w03_f004_overall_confidence_is_the_weakest_axis_on_the_pinned_board():
    """B11 contract: overall = the weakest of five axes, no range statistic.  A bucket that is a pure
    function of percentile spread (the August defect) cannot satisfy this on 890 real rows."""
    order = {"low": 0, "medium": 1, "high": 2}
    checked = 0
    for row in _rows():
        axes = row.get("confidenceAxes")
        if not isinstance(axes, dict) or row.get("assetClass") == "pick":
            continue
        if any(v not in order for v in axes.values()):
            continue
        checked += 1
        assert order.get(row["confidenceBucket"]) == min(order[v] for v in axes.values()), row[
            "displayName"
        ]
    assert checked > 500


def test_w03_f004_range_is_not_the_deciding_statistic():
    """The retired 0.08 / 0.20 spread buckets: ``assess_confidence`` must not read the spread."""
    import inspect

    from src.api import confidence

    body = inspect.getsource(confidence.assess_confidence)
    assert "sourceRankPercentileSpread" not in body
    assert "percentile_spread" not in body


# ---------------------------------------------------------------------------
# W05-F001  /tools/source-health lists 4 of 21 sources            CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w05_f001_idptradecalc_count_is_looked_up_under_its_registry_key():
    import server as srv
    from src.api.data_contract import get_ranking_source_keys

    registry = sorted(get_ranking_source_keys())
    payload = {
        "sites": [{"key": "ktc", "playerCount": 500}],
        "settings": {"sourceRunSummary": {"enabledSources": ["KTC", "IDPTradeCalc"]}},
    }
    coverage = {k: 100 for k in registry}
    coverage["idpTradeCalc"] = 911
    snap = srv._build_source_health_snapshot(payload, coverage=coverage)
    assert snap["registered_sources"] == registry
    assert len(registry) > 20, "the population is the registry, not the 4 scraper run names"
    assert snap["source_counts"]["idpTradeCalc"] == 911  # August: rendered 0 (case mismatch)


def test_w05_f001_page_rows_come_from_registered_sources_not_scraper_run_names():
    text = (REPO / "frontend" / "components" / "SourceHealthStrip.jsx").read_text(encoding="utf-8")
    assert "health.registered_sources" in text
    assert (
        "const enabled = registered.length\n      ? registered" in text
    ), "registry population must be preferred over the scraper-run list"


# ---------------------------------------------------------------------------
# W05-F003  zero-row / renamed-header CSV is silent                      CLOSED
# ---------------------------------------------------------------------------


def _enrich_one(tmp_path: Path, key: str, body: str) -> list[dict]:
    from src.api import data_contract as dc

    rel = dc._SOURCE_CSV_PATHS[key]
    rel = rel if isinstance(rel, str) else rel["path"]
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    errors: list[dict] = []
    rows = [{"canonicalName": "josh allen", "displayName": "Josh Allen", "position": "QB"}]
    dc._enrich_from_source_csvs(rows, parse_errors=errors, csv_root=tmp_path)
    return [e for e in errors if e.get("source") == key]


def test_w05_f003_control_probed_source_with_renamed_header_is_reported(tmp_path):
    errs = _enrich_one(tmp_path, "dlfSf", "colA,colB\nJosh Allen,1\n")
    assert [e["error"] for e in errs] == ["schema_mismatch"]


def test_w05_f003_control_missing_file_is_reported(tmp_path):
    from src.api import data_contract as dc

    errors: list[dict] = []
    dc._enrich_from_source_csvs(
        [{"canonicalName": "josh allen", "displayName": "Josh Allen", "position": "QB"}],
        parse_errors=errors,
        csv_root=tmp_path,
    )
    assert any(e["source"] == "ktcSfTep" and e["error"] == "file_not_found" for e in errors)


def test_w05_f003_renamed_header_on_an_unprobed_source_is_reported(tmp_path):
    errs = _enrich_one(tmp_path, "ktcSfTep", "colA,colB\nJosh Allen,9000\n")
    assert errs, "schema drift on ktcSfTep produced no parse error"


def test_w05_f003_header_only_csv_is_reported_as_a_parse_error(tmp_path):
    errs = _enrich_one(tmp_path, "ktcSfTep", "name,value\n")
    assert errs, "an empty-but-valid CSV produced no parse error"


def test_w05_f003_downstream_zero_rows_is_a_hard_error_for_every_registered_source():
    """The mitigation that makes the silent parse path survivable: ``source_missing`` for ANY registry
    key (also pinned in ``tests/api/test_registered_voter_zero_check.py``)."""
    from src.api import data_contract as dc

    text = Path(dc.__file__).read_text(encoding="utf-8")
    assert "watched_keys = set(get_ranking_source_keys()) | set(row_floors)" in text
    assert 'errors.append(f"source_missing:{src_key}")' in text


# ---------------------------------------------------------------------------
# W05-F004  sources with no row-count floor                              CLOSED
# ---------------------------------------------------------------------------


def test_w05_f004_retail_anchor_now_has_a_floor_and_zero_is_a_hard_error():
    from src.api.data_contract import _load_source_row_floors

    floors = _load_source_row_floors()
    assert floors["ktcSfTep"] >= 400
    assert floors["idpTradeCalc"] >= 700


def test_w05_f004_every_registered_source_declares_a_thin_floor():
    from src.api.data_contract import _load_source_row_floors, get_ranking_source_keys

    unfloored = sorted(set(get_ranking_source_keys()) - set(_load_source_row_floors()))
    assert not unfloored, f"no row-count floor: {unfloored}"


# ---------------------------------------------------------------------------
# W05-F006  pick voting breadth / single-source slot picks               PARTIAL
# ---------------------------------------------------------------------------


def test_w05_f006_slot_picks_are_no_longer_anchored_on_one_vendor():
    slot = [
        r for r in _rows() if r.get("assetClass") == "pick" and " Pick " in str(r["displayName"])
    ]
    assert len(slot) == 72
    # Current-year slot picks inherit the merged rookie pool (owner-documented Phase 5.2b tether).
    assert {(r.get("pickValueProvenance") or {}).get("class") for r in slot} == {
        "rookie_pool_tether"
    }


def test_w05_f006_ktc_now_votes_on_pick_rows():
    voters: dict[str, int] = {}
    for row in _rows():
        if row.get("assetClass") != "pick":
            continue
        for key, m in (row.get("sourceRankMeta") or {}).items():
            if isinstance(m, dict) and m.get("valueContribution"):
                voters[key] = voters.get(key, 0) + 1
    assert voters.get("ktcCrowdSfTep", 0) >= 30 and voters.get("ktcTradesSfTep", 0) >= 30
    assert voters.get("idpTradeCalc", 0) >= 30
    assert set(voters) <= {"ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc"}  # two PROVIDERS


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W05-F006 PARTIAL: dlfRookieSf's synthetic 'Pick R.SS' stamps still land in canonicalSiteValues "
    "on pick rows while the registry comment claims they flow into pick rankDerivedValue directly; "
    "no pick row carries it as a vote.",
)
def test_w05_f006_dlf_rookie_pick_stamps_are_not_a_dead_write():
    wrote = voted = 0
    for row in _rows():
        if row.get("assetClass") != "pick":
            continue
        if (row.get("canonicalSiteValues") or {}).get("dlfRookieSf"):
            wrote += 1
        if "dlfRookieSf" in (row.get("sourceRankMeta") or {}):
            voted += 1
    assert wrote > 0
    assert voted > 0, f"{wrote} pick rows carry a dlfRookieSf stamp, {voted} count it as a vote"


# ---------------------------------------------------------------------------
# W12-F008  KTC on both sides of "KTC vs expert consensus"        CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w12_f008_market_gap_is_model_vs_ktc_market_not_source_vs_source():
    from src.api import data_contract as dc

    assert dc._retail_source_keys() == frozenset({"ktcCrowdSfTep", "ktcTradesSfTep"})
    rows = [r for r in _rows() if r.get("marketGapDirection") not in (None, "none")]
    assert rows
    for r in rows:
        assert (r.get("ktcMarket") or {}).get("normalizedValue") is not None, r["displayName"]


def test_w12_f008_fantasy_navigator_and_idptc_cannot_move_the_market_side():
    from src.api import data_contract
    from src.sources import ktc_market

    def stamp(extra: dict) -> dict:
        rows = [
            {
                "displayName": "Anchor QB",
                "position": "QB",
                "rankDerivedValue": 9999.0,
                "canonicalSiteValues": {ktc_market.KTC_MARKET_KEY: 9999.0},
            },
            {
                "displayName": "Probe WR",
                "position": "WR",
                "rankDerivedValue": 5000.0,
                "canonicalSiteValues": {ktc_market.KTC_MARKET_KEY: 6000.0, **extra},
            },
        ]
        data_contract._stamp_ktc_market_benchmark(rows)
        return rows[1]

    base = stamp({})
    moved = stamp({"fantasyNavigatorSf": 1500.0, "idpTradeCalc": 900.0, "ktcSfTep": 100.0})
    assert base["marketGapDirection"] == moved["marketGapDirection"]
    assert base["marketGapValueRatio"] == moved["marketGapValueRatio"]
    assert base["ktcMarket"] == moved["ktcMarket"]


# ---------------------------------------------------------------------------
# W13-F001  BDVM "exact league scoring" drops six reception bands        PARTIAL
# W18-F003  realized_points disagrees with the league host
# ---------------------------------------------------------------------------

_BANDS = ("rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39", "rec_40p")


def test_w13_f001_the_live_card_still_pays_all_six_bands():
    card = _card("sleeper_league_1312006700437352448.json")
    assert [card[k] for k in _BANDS] == [0.17, 0.42, 0.67, 0.92, 1.17, 1.92]


def test_w13_f001_realized_path_scores_the_bands_when_the_pbp_supplement_is_attached():
    """Closed half: the play-by-play supplement (``PBP_SUPPLEMENT_ROW_KEY``) now carries the six band
    counts and the canonical dot product scores them; BDVM's baseline and actuals attach it
    (``src/bdvm/baseline.py``, ``src/bdvm/actuals.py``, ``scripts/bdvm_build_baseline.py``)."""
    from src.nfl_data.realized_points import PBP_SUPPLEMENT_ROW_KEY, compute_weekly_points

    card = _card("sleeper_league_1312006700437352448.json")
    row = {"receptions": 6, "receiving_yards": 80}
    bare = compute_weekly_points(row, card, position="WR")
    with_pbp = compute_weekly_points(
        {
            **row,
            PBP_SUPPLEMENT_ROW_KEY: {
                "rec_0_4": 1,
                "rec_5_9": 1,
                "rec_10_19": 2,
                "rec_20_29": 1,
                "rec_40p": 1,
            },
        },
        card,
        position="WR",
    )
    expected = 0.17 + 0.42 + 2 * 0.67 + 0.92 + 1.92
    assert with_pbp.fantasy_points - bare.fantasy_points == pytest.approx(expected, abs=1e-6)
    # And a line WITHOUT the supplement discloses the rules as unscored instead of silently dropping them.
    assert {k for k, _ in bare.unscored} >= set(_BANDS)


def test_w13_f001_projection_path_discloses_the_unscored_bands():
    from src.bdvm.scoring import score_stat_line_per_game_breakdown

    card = _card("sleeper_league_1312006700437352448.json")
    scored = score_stat_line_per_game_breakdown(
        {"receptions": 6, "receiving_yards": 80, "receiving_tds": 0.5}, card, position="WR"
    )
    assert set(_BANDS) <= set(scored.unscored)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W13-F001 PARTIAL: a PROJECTED stat line (Clay / IDP Show / manual CSV) still scores none of the "
    "six reception-distance rules (disclosed in `unscored`, never a mapping fix per scoring_census); "
    "filling them needs a measured per-player reception-depth shape = value-moving, owner-gated.",
)
def test_w13_f001_projected_line_scores_reception_distance_rules():
    from src.bdvm.scoring import score_stat_line_per_game_breakdown

    card = _card("sleeper_league_1312006700437352448.json")
    scored = score_stat_line_per_game_breakdown(
        {"receptions": 6, "receiving_yards": 80, "receiving_tds": 0.5}, card, position="WR"
    )
    assert not set(_BANDS) & set(scored.unscored)


def test_w18_f003_renamed_nflverse_columns_are_read():
    """Closed: pass_int / pass_sack / fum_lost read the 2025 unified-release column names (-4/-1/-4)."""
    from src.nfl_data.realized_points import compute_weekly_points

    card = _card("sleeper_league_1312006700437352448.json")
    for key, column in (
        ("pass_int", "passing_interceptions"),
        ("pass_sack", "sacks_suffered"),
        ("fum_lost", "fumbles_lost_total"),
    ):
        with_rule = compute_weekly_points({column: 2}, {key: card[key]}, position="QB")
        assert with_rule.fantasy_points == pytest.approx(2 * card[key]), key


def test_w18_f003_kicker_rules_score():
    from src.nfl_data.realized_points import compute_weekly_points

    card = _card("sleeper_league_1312006700437352448.json")
    row = {
        "fg_made": 2,
        "fg_made_20_29": 1,
        "fg_made_30_39": 1,
        "fg_made_distance": 65,
        "pat_made": 3,
        "pat_missed": 0,
    }
    out = compute_weekly_points(row, card, position="K")
    assert out.fantasy_points == pytest.approx(3 * card["xpm"] + 65 * card["fgm_yds"], abs=1e-6)


# ---------------------------------------------------------------------------
# W18-F001 / W18-F002   scoring identity & chimeric overlay              CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w18_f001_same_label_different_scoring_has_different_identity():
    from src.league_comparison.sleeper_scoring import scoring_fingerprint

    main = _card("sleeper_league_1312006700437352448.json")
    new = _card("sleeper_league_dynasty_new.json")
    registry = json.loads((REPO / "config" / "leagues" / "registry.json").read_text("utf-8"))
    profiles = {
        entry["key"]: entry.get("scoringProfile")
        for entry in registry["leagues"]
        if entry.get("scoringProfile")
    }
    # The August premise: hand-typed labels collide ...
    assert len(set(profiles.values())) < len(profiles), profiles
    # ... while the factual identity (derived from the real card) does not.
    fp_main, fp_new = scoring_fingerprint(main), scoring_fingerprint(new)
    assert fp_main and fp_new and fp_main != fp_new
    differing = [k for k in set(main) & set(new) if main[k] != new[k]]
    assert len(differing) >= 30  # August: 35 of 48 shared keys


def test_w18_f001_no_card_is_unproven_not_a_hash_of_nothing():
    from src.league_comparison.sleeper_scoring import scoring_fingerprint

    assert scoring_fingerprint(None) is None
    assert scoring_fingerprint({}) is None


def test_w18_f001_the_server_gate_routes_through_the_one_owner():
    text = (REPO / "server.py").read_text(encoding="utf-8")
    assert "def _scoring_identity_error" in text
    assert "_contract_scoring_fingerprint(contract)" in text
    assert "scoring_fingerprint_for_league(league_cfg)" in text


def test_w18_f002_chimera_cannot_be_published_ready():
    from src.api.sleeper_overlay import merge_cross_league_sleeper_block

    loaded = {
        "leagueId": "AAA",
        "teams": [{"rosterId": 1}],
        "positions": {"x": "QB"},
        "playerIds": {"x": "1"},
        "idToPlayer": {"1": "x"},
        "scoringSettings": {"rec": 1.0},
        "rosterPositions": ["QB", "BN"],
        "leagueSettings": {"num_teams": 12},
    }
    overlay = {"leagueId": "BBB", "teams": [{"rosterId": 9}], "trades": [], "waivers": []}
    block, ready = merge_cross_league_sleeper_block(
        loaded_sleeper=loaded, overlay=overlay, requested_league_config=None
    )
    assert ready is False
    for field in ("scoringSettings", "rosterPositions", "leagueSettings"):
        assert block.get(field) is None, f"{field} inherited from the loaded league"
    assert block["teams"] == overlay["teams"]


def test_w18_f002_the_server_stamps_readiness_from_the_merge_result():
    text = (REPO / "server.py").read_text(encoding="utf-8")
    assert 'meta["sleeperDataReady"] = bool(sleeper_matches or cross_league_ready)' in text


# ---------------------------------------------------------------------------
# W21-F001  injury impact is a direct news -> value multiplier               OPEN
# ---------------------------------------------------------------------------


def _bijan_headline_item() -> dict:
    items = json.loads((EVIDENCE / "W21" / "api-news.json").read_text(encoding="utf-8"))["items"]
    item = dict(next(i for i in items if i["id"] == "cbs-0e03f499b141"))
    item["ts"] = "2026-11-01T12:00:00+00:00"
    return item


_NOW = int(_dt.datetime(2026, 11, 1, 12, 0, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def test_w21_f001_control_classifier_now_labels_the_headline_a_positive_transaction():
    """The classifier half improved: a FRESH classification of the August headline is
    ('watch','transaction','positive'), not an injury 'alert'.  The recorded August row (alert / injury /
    negative) is kept as the fixture of the downstream mechanism below."""
    from src.news.providers._rss import classify

    assert classify(
        "Which teams won the MLB trade deadline; Bijan Robinson becomes NFL's highest-paid RB\n"
    ) == ("watch", "transaction", "positive")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W21-F001 OPEN: apply_injury_impact (terminal.py:1662) still multiplies rankDerivedValue by "
    "adjustedPct from a single item's severity -- no structured claim, corroboration, confidence or "
    "module input. Repair is owner methodology (delete injuryAdjustedValue or route via the BDVM "
    "news_events module-input path).",
)
def test_w21_f001_a_single_headline_never_reprices_a_value():
    from src.api.injury_impact import apply_injury_impact

    out = apply_injury_impact(
        row={"pos": "RB", "age": 24, "rankDerivedValue": 9706, "rookie": False},
        news_for_player=[_bijan_headline_item()],
        now_ms=_NOW,
    )
    assert out["adjustedValue"] in (None, 9706), out


# ---------------------------------------------------------------------------
# W29-F001 / W29-F002   two value concepts / withdrawn lens               CLOSED_VERIFIED
# ---------------------------------------------------------------------------


def test_w29_f001_no_row_carries_a_second_board_value():
    assert not [r for r in _rows() if "offenseOnlyRankDerivedValue" in r]
    assert not [
        r for r in _board().get("players", {}).values() if "offenseOnlyRankDerivedValue" in r
    ]


def test_w29_f001_suggestions_cannot_carry_or_serialize_a_second_board():
    import dataclasses
    import inspect

    from src.trade import suggestions

    assert not [f for f in dataclasses.fields(suggestions.PlayerAsset) if "offense_only" in f.name]
    assert "offense_only" not in inspect.signature(suggestions._serialize_player).parameters
    assert "offenseOnlyRankDerivedValue" not in Path(suggestions.__file__).read_text(
        encoding="utf-8"
    ).replace("offenseOnlyRankDerivedValue`", "")


def test_w29_f002_league_adjusted_lens_is_withdrawn_and_never_writes_a_canonical_field():
    from src.league_intel import overlay

    server_text = (REPO / "server.py").read_text(encoding="utf-8")
    assert "league_adjusted_withdrawn: not_canonical" in server_text
    # The lens (when computed at all) writes ONLY experimental fields.
    src = Path(overlay.__file__).read_text(encoding="utf-8")
    assert "experimentalLeagueAdjustedValue" in src
    assert 'copy["rankDerivedValue"] =' not in src
    from src.api import data_contract

    assert not hasattr(data_contract, "apply_valuation_factors")
