"""AL-P3 — KTC format variants archived from the payload we already fetch.

What these tests pin, in the order the unit's acceptance lists them:

1. variant extraction from a fixture payload shaped like the live one
   (``playersArray`` with ``oneQBValues`` / ``superflexValues``, each with
   ``{value, tep, tepp, teppp}`` and all three Value Source modes — key layout
   verified against the live page 2026-10-01);
2. append-only and idempotent archive writes;
3. zero extra network calls — exactly one in-page ``evaluate`` and no
   navigation / fetch / route method is ever touched;
4. no served-value change — the canonical board is identical whether or not
   the archive holds a full KTC ladder, and the selected-board capture plus
   its CSV bytes are identical with the archive step run in between;
5. an archived variant is not readable as a ranking source;
6. failure isolation — nothing the archive does can raise into the scrape.

The JavaScript projection is executed for real in Node (the same harness
pattern as ``test_ktc_value_source_projection.py``); no live HTTP request is
made by any test here.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import shutil
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from src.source_archive import store as archive_store
from src.source_archive.store import ArchivedBoard, read_boards
from src.sources import ktc_format_archive as kfa
from src.sources import ktc_value_sources as kvs

REPO = Path(__file__).resolve().parents[2]
CAPTURED_AT = "2026-10-01T19:00:00+00:00"
RUN_ID = f"ktc:{CAPTURED_AT}"
ENV_ON = {kfa.ENV_SWITCH: "1"}

# ── fixture payload ────────────────────────────────────────────────────────

_LEVEL_OFFSET = {"off": 0, "tep": 1, "tepp": 2, "teppp": 3}
_GROUP_OFFSET = {"oneQBValues": 0, "superflexValues": 1}


def _block(group: str, level: str, i: int) -> dict:
    """One KTC value block.  Every number is unique per (group, level, mode),
    so a cell landing in the wrong slot cannot pass by coincidence."""
    g, lv = _GROUP_OFFSET[group], _LEVEL_OFFSET[level]
    crowd = 9000 - 3 * i - 400 * g + 50 * lv
    return {
        "value": crowd,
        "rank": i + 1,
        "positionalRank": i // 4 + 1,
        "overallTier": i // 50 + 1,
        "pickRank": i + 1,
        "history": [{"d": "2026-09-30", "v": crowd - 1}] * 3,
        "vftValue": crowd - 7,
        "vftRank": i + 2,
        "vftPositionalRank": i // 4 + 2,
        "vftOverallTier": i // 50 + 2,
        "vftHistory": [{"d": "2026-09-30", "v": crowd - 8}] * 3,
        "blendValue": crowd - 3,
        "blendRank": i + 3,
        "blendPositionalRank": i // 4 + 3,
        "blendOverallTier": i // 50 + 3,
        "blendHistory": [],
    }


def _group(group: str, i: int) -> dict:
    out = _block(group, "off", i)
    out.update(
        {
            "startSitValue": 1,
            "kept": 2,
            "traded": 3,
            "cut": 4,
            "tep": _block(group, "tep", i),
            "tepp": _block(group, "tepp", i),
            "teppp": _block(group, "teppp", i),
        }
    )
    return out


def _payload(count: int = 300) -> list[dict]:
    return [
        {
            "playerName": f"Player {i}",
            "playerID": 1000 + i,
            "slug": f"player-{i}",
            "position": "TE" if i % 5 == 0 else ("RDP" if i % 7 == 0 else "WR"),
            "team": "FA",
            "oneQBValues": _group("oneQBValues", i),
            "superflexValues": _group("superflexValues", i),
            "birthday": "1999-01-01",
        }
        for i in range(count)
    ]


# ── Node harness (real projection JavaScript, no browser) ──────────────────

_NODE_RUNNER = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sandbox = { window: {}, document: { querySelectorAll() {
  const controls = input.controls || [];
  return controls;
} } };
if (input.lookup === 'window') sandbox.window.playersArray = input.rows;
else sandbox.playersArray = input.rows;
const context = vm.createContext(sandbox);
const before = JSON.stringify(input.rows);
const result = vm.runInContext('"use strict"; (' + input.script + ')()', context, {timeout: 5000});
if (before !== JSON.stringify(input.rows)) throw new Error('Projection mutated its source');
process.stdout.write(JSON.stringify(result));
"""

_NETWORK_METHODS = (
    "goto",
    "reload",
    "go_back",
    "go_forward",
    "request",
    "route",
    "wait_for_response",
    "expect_response",
    "wait_for_request",
    "expect_request",
    "set_content",
    "wait_for_load_state",
    "wait_for_url",
)


class _CountingPage:
    """Counts ``evaluate`` calls and FAILS on any navigation/network method.

    Network methods are defined as attributes that record the call and raise,
    so even a caller that swallowed the exception would still leave a count.
    """

    url = "https://keeptradecut.com/dynasty-rankings?sf=true&tep=0"

    def __init__(self, rows, *, lookup="global", controls=None):
        self.rows = rows
        self.lookup = lookup
        self.controls = controls
        self.evaluate_calls: list[str] = []
        self.network_calls: list[str] = []
        self.output_bytes: list[int] = []
        for name in _NETWORK_METHODS:
            setattr(self, name, self._network(name))

    def _network(self, name):
        async def _fail(*_a, **_k):
            self.network_calls.append(name)
            raise AssertionError(f"network method {name} called")

        return _fail

    async def evaluate(self, script):
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node is required to execute the production projection JavaScript")
        self.evaluate_calls.append(script)
        result = subprocess.run(
            [node, "-e", _NODE_RUNNER],
            input=json.dumps(
                {
                    "rows": self.rows,
                    "lookup": self.lookup,
                    "controls": self.controls,
                    "script": script,
                }
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=True,
        )
        self.output_bytes.append(len(result.stdout.encode("utf-8")))
        return json.loads(result.stdout)


@pytest.fixture(scope="module")
def projection() -> dict:
    page = _CountingPage(_payload())
    return asyncio.run(kfa.project_format_variants(page))


def _boards(projection, **kw):
    return kfa.boards_from_projection(
        projection,
        run_id=kw.pop("run_id", RUN_ID),
        captured_at=kw.pop("captured_at", CAPTURED_AT),
        page_url="https://keeptradecut.com/dynasty-rankings?sf=true&tep=0",
        **kw,
    )


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    archive_store._reset_setup_cache_for_tests()
    yield
    archive_store._reset_setup_cache_for_tests()


# ── 1. variant extraction ──────────────────────────────────────────────────


class TestVariantExtraction:
    def test_all_eight_format_variants_are_cut_from_one_payload(self, projection):
        boards, skipped = _boards(projection)
        assert skipped == {}
        assert [b.format_key for b in boards] == list(kfa.VARIANT_KEYS)
        assert set(kfa.VARIANT_KEYS) == {
            f"{fmt}_{lvl}" for fmt in ("1qb", "sf") for lvl in ("off", "tep", "tepp", "teppp")
        }

    @pytest.mark.parametrize("variant", kfa.VARIANT_KEYS)
    def test_each_cell_lands_in_its_own_variant(self, projection, variant):
        fmt, level = variant.split("_")
        group = "oneQBValues" if fmt == "1qb" else "superflexValues"
        board = {b.format_key: b for b in _boards(projection)[0]}[variant]
        for i in (0, 17, 299):
            want = _block(group, level, i)
            rec = next(r for r in board.records if r.source_player_id == str(1000 + i))
            assert board.rows[f"Player {i}"] == want["value"]
            assert rec.value == want["value"]
            assert rec.overall_rank == want["rank"]
            assert rec.positional_rank == want["positionalRank"]
            assert rec.tier == str(want["overallTier"])
            # Trades / Crowd+Trades travel under KTC's own field names.
            for field in (
                "vftValue",
                "vftRank",
                "vftPositionalRank",
                "blendValue",
                "blendRank",
                "blendPositionalRank",
            ):
                assert rec.native[field] == want[field], field
            assert rec.native["vftOverallTier"] == str(want["vftOverallTier"])
            assert rec.native["blendOverallTier"] == str(want["blendOverallTier"])

    def test_1qb_and_superflex_are_distinct_boards(self, projection):
        boards = {b.format_key: b for b in _boards(projection)[0]}
        assert boards["1qb_off"].rows != boards["sf_off"].rows
        assert boards["sf_tep"].rows != boards["sf_teppp"].rows

    def test_agrees_with_the_selected_capture_parser_on_shared_cells(self, projection):
        """The two owners read the same payload: where they overlap (SF Off
        and SF TE++, all three modes) they must agree exactly."""
        rows = _payload()
        boards = {b.format_key: b for b in _boards(projection)[0]}
        native_tepp = {r.source_name: r.native for r in boards["sf_tepp"].records}
        native_off = {r.source_name: r.native for r in boards["sf_off"].records}
        for source, field in (
            (kvs.KTC_CROWD, None),
            (kvs.KTC_TRADES, "vftValue"),
            (kvs.KTC_CROWD_TRADES, "blendValue"),
        ):
            for obs in kvs.observations_from_players_array(rows, source):
                if field is None:
                    assert boards["sf_tepp"].rows[obs.name] == obs.tepp_value
                    assert boards["sf_off"].rows[obs.name] == obs.base_value
                else:
                    assert native_tepp[obs.name][field] == obs.tepp_value
                    assert native_off[obs.name][field] == obs.base_value

    def test_history_arrays_are_never_transferred(self):
        lean = _payload()
        heavy = copy.deepcopy(lean)
        for row in heavy:
            for group in ("oneQBValues", "superflexValues"):
                row[group]["history"] = [{"d": "x", "v": 1}] * 400
                row[group]["tepp"]["vftHistory"] = [{"d": "x", "v": 1}] * 400
        lean_page, heavy_page = _CountingPage(lean), _CountingPage(heavy)
        a = asyncio.run(kfa.project_format_variants(lean_page))
        b = asyncio.run(kfa.project_format_variants(heavy_page))
        assert a == b
        assert lean_page.output_bytes == heavy_page.output_bytes

    def test_window_scoped_players_array_is_found(self):
        page = _CountingPage(_payload(), lookup="window")
        out = asyncio.run(kfa.project_format_variants(page))
        assert len(out["rows"]) == 300

    def test_provenance_carries_fetch_time_hash_label_and_source(self, projection):
        boards, _ = _boards(projection, selected_capture_hashes={"crowd": "abc"})
        digest = kfa.payload_hash(projection)
        by_key = {b.format_key: b for b in boards}
        prov = by_key["sf_teppp"].provenance
        assert prov["fetchedAt"] == CAPTURED_AT
        assert prov["payloadHash"] == digest
        assert prov["variantLabel"] == "Superflex TE+++"
        assert prov["tePremiumLevel"] == 3
        assert prov["qbFormat"] == "superflex"
        assert prov["pageUrl"].startswith("https://keeptradecut.com/")
        assert prov["extraRequests"] == 0
        assert prov["productionEligible"] is False
        assert prov["selectedCaptureHashes"] == {"crowd": "abc"}
        assert by_key["1qb_off"].provenance["variantLabel"] == "1QB Off"
        assert {b.provider_family for b in boards} == {"ktc"}
        assert {b.run_id for b in boards} == {RUN_ID}
        assert {b.game_type for b in boards} == {"DYNASTY"}


class TestMissingIsNeverZero:
    def _project(self, rows):
        return asyncio.run(kfa.project_format_variants(_CountingPage(rows)))

    def test_zero_and_garbage_values_are_absent_not_zero(self):
        rows = _payload()
        rows[0]["superflexValues"]["tep"]["value"] = 0
        rows[1]["superflexValues"]["tep"]["value"] = "n/a"
        rows[2]["superflexValues"]["tep"]["rank"] = 0
        rows[3]["superflexValues"]["tep"]["vftValue"] = None
        board = {b.format_key: b for b in _boards(self._project(rows))[0]}["sf_tep"]
        recs = {r.source_name: r for r in board.records}
        assert "Player 0" not in board.rows and recs["Player 0"].value is None
        assert "Player 1" not in board.rows and recs["Player 1"].value is None
        assert recs["Player 2"].overall_rank is None
        assert "vftValue" not in recs["Player 3"].native
        assert all(v > 0 for v in board.rows.values())

    def test_a_level_ktc_stops_shipping_is_skipped_not_archived_empty(self):
        rows = _payload()
        for row in rows:
            row["oneQBValues"].pop("teppp")
        boards, skipped = _boards(self._project(rows))
        assert "1qb_teppp" not in {b.format_key for b in boards}
        assert skipped["1qb_teppp"].startswith("partial:priced=0")
        assert len(boards) == 7

    def test_a_layout_change_fails_closed(self, projection):
        bad = dict(projection, fields=list(projection["fields"])[::-1])
        with pytest.raises(kfa.KtcFormatArchiveError, match="layout changed"):
            _boards(bad)


# ── 2. append-only and idempotent ──────────────────────────────────────────


class TestAppendOnly:
    def test_archive_then_reread(self, projection, tmp_path):
        db = tmp_path / "a.sqlite"
        out = kfa.archive_projection(
            projection, run_id=RUN_ID, captured_at=CAPTURED_AT, page_url="u", path=db
        )
        assert out["archived"] == list(kfa.VARIANT_KEYS)
        boards = read_boards(provider_family="ktc", path=db)
        assert {b.format_key for b in boards} == set(kfa.VARIANT_KEYS)
        assert all(b.provenance["payloadHash"] == out["payloadHash"] for b in boards)
        assert all(len(b.records) == 300 for b in boards)

    def test_reingesting_the_same_run_is_a_no_op(self, projection, tmp_path):
        db = tmp_path / "a.sqlite"
        kw = dict(run_id=RUN_ID, captured_at=CAPTURED_AT, page_url="u", path=db)
        kfa.archive_projection(projection, **kw)
        again = kfa.archive_projection(projection, **kw)
        assert again["archived"] == [] and again["unchanged"] == list(kfa.VARIANT_KEYS)
        assert len(read_boards(path=db)) == 8

    def test_conflicting_content_is_surfaced_never_applied(self, projection, tmp_path):
        db = tmp_path / "a.sqlite"
        kw = dict(run_id=RUN_ID, captured_at=CAPTURED_AT, page_url="u", path=db)
        kfa.archive_projection(projection, **kw)
        tampered = copy.deepcopy(projection)
        tampered["rows"][0][3][0] = 1.0  # 1qb_off crowd value of the first row
        out = kfa.archive_projection(tampered, **kw)
        assert out["conflicts"] == ["1qb_off"]
        kept = {b.format_key: b for b in read_boards(path=db)}["1qb_off"]
        assert kept.rows["Player 0"] == _block("oneQBValues", "off", 0)["value"]

    def test_a_new_run_appends_and_keeps_the_old_one(self, projection, tmp_path):
        db = tmp_path / "a.sqlite"
        kfa.archive_projection(
            projection, run_id="ktc:r1", captured_at=CAPTURED_AT, page_url="u", path=db
        )
        kfa.archive_projection(
            projection, run_id="ktc:r2", captured_at=CAPTURED_AT, page_url="u", path=db
        )
        assert {b.run_id for b in read_boards(path=db)} == {"ktc:r1", "ktc:r2"}
        assert len(read_boards(path=db)) == 16

    def test_a_v2_database_migrates_additively(self, tmp_path):
        db = tmp_path / "v2.sqlite"
        conn = sqlite3.connect(db)
        conn.executescript(archive_store._SCHEMA.replace("    provenance_json TEXT,\n", ""))
        conn.execute(
            "INSERT INTO archived_boards VALUES "
            "('ktc','ktc','e','sf_off','DYNASTY','r0','2026-09-30','2026-09-30T00:00:00',"
            "NULL,1,'{\"A\":1.0}',NULL,'h','2026-09-30T00:00:00')"
        )
        conn.commit()
        conn.close()
        archive_store.archive_board(
            ArchivedBoard(
                provider="ktc",
                provider_family="ktc",
                endpoint="e",
                format_key="sf_tep",
                game_type="DYNASTY",
                run_id="r1",
                rows={"A": 2.0},
                provenance={"payloadHash": "p"},
            ),
            path=db,
        )
        got = {b.format_key: b for b in read_boards(path=db)}
        assert got["sf_off"].provenance == {}
        assert got["sf_tep"].provenance == {"payloadHash": "p"}

    def test_provenance_does_not_change_the_content_hash(self):
        a = ArchivedBoard("ktc", "ktc", "e", "sf_off", "DYNASTY", "r", {"A": 1.0})
        b = replace(a, provenance={"payloadHash": "different"})
        assert a.compute_hash() == b.compute_hash()


# ── 3. zero extra network calls; cadence ───────────────────────────────────


class TestNoExtraRequests:
    def test_exactly_one_in_page_read_and_no_network_method(self, tmp_path):
        page = _CountingPage(_payload())
        out = asyncio.run(
            kfa.archive_variants_safely(
                page, captured_at=CAPTURED_AT, path=tmp_path / "a.sqlite", environ=ENV_ON
            )
        )
        assert out["ok"] is True, out
        assert len(page.evaluate_calls) == 1
        assert page.network_calls == []

    def test_the_projection_script_issues_no_request_in_page(self):
        js = kfa._PROJECTION_JS
        for token in ("fetch(", "XMLHttpRequest", "import(", "location", "navigator.sendBeacon"):
            assert token not in js, token

    def test_daily_cadence_skips_before_any_page_read(self, tmp_path):
        db = tmp_path / "a.sqlite"
        first = _CountingPage(_payload())
        asyncio.run(
            kfa.archive_variants_safely(first, captured_at=CAPTURED_AT, path=db, environ=ENV_ON)
        )
        second = _CountingPage(_payload())
        out = asyncio.run(
            kfa.archive_variants_safely(
                second, captured_at="2026-10-01T21:00:00+00:00", path=db, environ=ENV_ON
            )
        )
        assert out == {
            "ok": True,
            "skippedRun": "already_archived_today",
            "runId": "ktc:2026-10-01T21:00:00+00:00",
        }
        assert second.evaluate_calls == [] and second.network_calls == []

    def test_next_day_archives_again(self, tmp_path):
        db = tmp_path / "a.sqlite"
        for when in (CAPTURED_AT, "2026-10-02T01:00:00+00:00"):
            asyncio.run(
                kfa.archive_variants_safely(
                    _CountingPage(_payload()), captured_at=when, path=db, environ=ENV_ON
                )
            )
        assert len({b.run_id for b in read_boards(path=db)}) == 2

    def test_every_run_cadence_archives_each_run(self, tmp_path):
        db = tmp_path / "a.sqlite"
        env = {**ENV_ON, kfa.CADENCE_SWITCH: "every_run"}
        for when in (CAPTURED_AT, "2026-10-01T21:00:00+00:00"):
            asyncio.run(
                kfa.archive_variants_safely(
                    _CountingPage(_payload()), captured_at=when, path=db, environ=env
                )
            )
        assert len({b.run_id for b in read_boards(path=db)}) == 2

    def test_a_partial_day_does_not_block_completion(self, projection, tmp_path):
        db = tmp_path / "a.sqlite"
        boards, _ = _boards(projection)
        archive_store.archive_board(boards[0], path=db)
        assert kfa.already_archived_today(CAPTURED_AT, path=db) is False

    @pytest.mark.parametrize(
        ("env", "enabled", "why"),
        [
            ({}, True, "enabled:default"),
            ({"GITHUB_ACTIONS": "true"}, False, "disabled:ephemeral_ci_runner"),
            ({"GITHUB_ACTIONS": "true", kfa.ENV_SWITCH: "1"}, True, "enabled:explicit"),
            ({kfa.ENV_SWITCH: "0"}, False, f"disabled:{kfa.ENV_SWITCH}=0"),
        ],
    )
    def test_env_gate(self, env, enabled, why):
        assert kfa.archive_enabled(env) == (enabled, why)

    def test_a_disabled_run_touches_nothing(self, tmp_path):
        page = _CountingPage(_payload())
        out = asyncio.run(
            kfa.archive_variants_safely(
                page, path=tmp_path / "a.sqlite", environ={kfa.ENV_SWITCH: "off"}
            )
        )
        assert out["skippedRun"].startswith("disabled:")
        assert page.evaluate_calls == [] and not (tmp_path / "a.sqlite").exists()


# ── 4. no served-value change ──────────────────────────────────────────────


def _selected_controls():
    return [
        {
            "value": "2",
            "options": [
                {"textContent": kvs.KTC_VALUE_SOURCE_LABELS[s], "value": v}
                for s, v in kvs.KTC_CONTROL_VALUES.items()
            ],
        }
    ]


class TestNoServedValueChange:
    def test_selected_capture_and_csv_bytes_identical_with_archive_in_between(self, tmp_path):
        """The scraper's voting artifacts are produced from the captures it
        already holds; running the archive between capture and write must not
        change a byte of them, nor mutate the captures."""
        rows = _payload(500)

        def capture():
            page = _CountingPage(rows, controls=_selected_controls())
            return asyncio.run(kvs.capture_all_value_sources(page)), page

        baseline, _ = capture()
        kvs.write_capture_artifacts(
            baseline,
            site_raw_dir=tmp_path / "plain" / "site_raw",
            provenance_path=tmp_path / "plain" / "prov.json",
        )

        captures, page = capture()
        frozen = copy.deepcopy(captures)
        out = asyncio.run(
            kfa.archive_variants_safely(
                page,
                captured_at=captures[kvs.KTC_CROWD].captured_at,
                selected_capture_hashes=kfa.selected_hashes(captures),
                path=tmp_path / "a.sqlite",
                environ=ENV_ON,
            )
        )
        assert out["ok"] is True, out
        assert captures == frozen
        kvs.write_capture_artifacts(
            captures,
            site_raw_dir=tmp_path / "archived" / "site_raw",
            provenance_path=tmp_path / "archived" / "prov.json",
        )
        for path in sorted((tmp_path / "plain" / "site_raw").iterdir()):
            other = tmp_path / "archived" / "site_raw" / path.name
            assert path.read_bytes() == other.read_bytes(), path.name
        # The archive writes nothing beside its own database (+ SQLite WAL files).
        others = {p.name for p in tmp_path.iterdir() if not p.name.startswith("a.sqlite")}
        assert others == {"archived", "plain"}

    def test_canonical_board_is_identical_with_a_populated_archive(
        self, projection, tmp_path, monkeypatch
    ):
        from src.api.data_contract import build_api_data_contract
        from tests.archive_fixtures import newest_complete_raw_payload

        raw, archive = newest_complete_raw_payload()
        if raw is None:
            pytest.skip("no complete archived scrape available")

        def board(contract):
            return {
                (r.get("displayName"), r.get("assetClass")): (
                    r.get("rankDerivedValue"),
                    r.get("canonicalConsensusRank"),
                    r.get("canonicalTierId"),
                )
                for r in contract.get("playersArray") or []
            }

        before = board(build_api_data_contract(copy.deepcopy(raw)))
        db = tmp_path / "boards.sqlite"
        monkeypatch.setattr(archive_store, "DB_PATH", db)
        kfa.archive_projection(projection, run_id=RUN_ID, captured_at=CAPTURED_AT, page_url="u")
        assert db.exists() and len(read_boards()) == 8
        after = board(build_api_data_contract(copy.deepcopy(raw)))
        assert before, archive
        assert after == before


# ── 5. not a ranking source ────────────────────────────────────────────────


class TestNotARankingSource:
    def _data_contract_imports(self) -> set[str]:
        tree = ast.parse((REPO / "src/api/data_contract.py").read_text(encoding="utf-8"))
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                out.add(node.module)
            elif isinstance(node, ast.Import):
                out.update(a.name for a in node.names)
        return out

    def test_data_contract_cannot_reach_the_variant_archive(self):
        imported = self._data_contract_imports()
        assert "src.sources.ktc_format_archive" not in imported
        assert not any(m.startswith("src.source_archive") for m in imported)
        text = (REPO / "src/api/data_contract.py").read_text(encoding="utf-8")
        assert "ktc_format_archive" not in text
        assert "boards.sqlite" not in text

    def test_no_variant_key_or_label_is_a_registered_source(self):
        from src.api.data_contract import _RANKING_SOURCES

        # A registry key IS its CSV stem (CSVs/site_raw/<key>.csv).
        registered = {str(s.get("key")) for s in _RANKING_SOURCES}
        for variant in kfa.VARIANT_KEYS:
            for candidate in (variant, f"ktc:{variant}", f"ktc_{variant}", f"ktc{variant}"):
                assert candidate not in registered, candidate
        assert not (archive_store.ARCHIVE_ELIGIBLE & registered)
        assert archive_store.PRODUCTION_ELIGIBLE == frozenset()

    def test_every_variant_is_archive_eligible_and_none_production_eligible(self):
        for variant in kfa.VARIANT_KEYS:
            assert f"ktc:{variant}" in archive_store.ARCHIVE_ELIGIBLE
            assert f"ktc:{variant}" not in archive_store.PRODUCTION_ELIGIBLE

    def test_the_selected_capture_file_keys_are_unchanged(self):
        assert dict(kvs.KTC_SOURCE_FILE_KEYS) == {
            kvs.KTC_CROWD: "ktcCrowdSfTep",
            kvs.KTC_TRADES: "ktcTradesSfTep",
            kvs.KTC_CROWD_TRADES: "ktcCrowdTradesSfTep",
        }

    def test_archiving_the_ladder_adds_no_independent_family(self, projection, tmp_path):
        from src.api.data_contract import _RANKING_SOURCES, correlation_group_for

        before = {correlation_group_for(s["key"]) for s in _RANKING_SOURCES}
        kfa.archive_projection(
            projection, run_id=RUN_ID, captured_at=CAPTURED_AT, page_url="u", path=tmp_path / "a"
        )
        assert {correlation_group_for(s["key"]) for s in _RANKING_SOURCES} == before

    def test_the_module_writes_no_csv_and_touches_no_full_data(self):
        """Code only — the docstrings legitimately NAME what it must not touch."""
        tree = ast.parse((REPO / "src/sources/ktc_format_archive.py").read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    docstrings.add(id(body[0].value))
        names, strings, imports = set(), [], set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings:
                    strings.append(node.value)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
        assert not ({"open", "FULL_DATA", "_RANKING_SOURCES", "write_text", "write_bytes"} & names)
        assert "csv" not in imports and "src.api.data_contract" not in imports
        assert not any("site_raw" in s or s.endswith(".csv") for s in strings)
        # The only store it reaches is the archive owner.
        assert {m for m in imports if m.startswith("src.")} == {
            "src.source_archive.records",
            "src.source_archive.store",
        }


# ── 6. failure isolation ───────────────────────────────────────────────────


class _BrokenPage:
    url = "u"

    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def evaluate(self, _script):
        if self.behaviour == "raise":
            raise RuntimeError("Target page, context or browser has been closed")
        if self.behaviour == "hang":
            await asyncio.sleep(30)
        if self.behaviour == "not_object":
            return [1, 2, 3]
        if self.behaviour == "bad_layout":
            return {"groups": [], "levels": [], "fields": [], "rows": []}
        raise AssertionError(self.behaviour)


class TestFailureIsolation:
    @pytest.mark.parametrize("behaviour", ["raise", "not_object", "bad_layout"])
    def test_page_failures_never_raise(self, behaviour, tmp_path):
        out = asyncio.run(
            kfa.archive_variants_safely(
                _BrokenPage(behaviour), path=tmp_path / "a.sqlite", environ=ENV_ON
            )
        )
        assert out["ok"] is False and out["error"]

    def test_a_hung_page_is_abandoned_within_the_timeout(self, tmp_path):
        out = asyncio.run(
            kfa.archive_variants_safely(
                _BrokenPage("hang"), path=tmp_path / "a.sqlite", environ=ENV_ON, timeout_s=0.2
            )
        )
        assert out["ok"] is False and "Timeout" in out["error"]

    def test_a_store_failure_never_raises(self, monkeypatch, tmp_path):
        def boom(*_a, **_k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(archive_store, "archive_board", boom)
        out = asyncio.run(
            kfa.archive_variants_safely(
                _CountingPage(_payload()), path=tmp_path / "a.sqlite", environ=ENV_ON
            )
        )
        assert out["ok"] is False and "locked" in out["error"]

    def test_an_unwritable_archive_path_never_raises(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        out = asyncio.run(
            kfa.archive_variants_safely(
                _CountingPage(_payload()),
                path=blocker / "nested" / "a.sqlite",
                environ=ENV_ON,
            )
        )
        assert out["ok"] is False

    def test_selected_hashes_never_raises(self):
        class Weird:
            def items(self):
                raise RuntimeError("no")

        assert kfa.selected_hashes(Weird()) == {}

    def test_the_scraper_call_site_is_guarded_and_after_the_capture(self):
        """Structural: the scraper imports the archive defensively, awaits it
        inside ``try/except Exception``, and only after the selected capture
        has been stored — so it can neither block the import nor precede or
        replace the capture."""
        src = (REPO / "Dynasty Scraper.py").read_text(encoding="utf-8")
        tree = ast.parse(src)

        guarded_import = False
        guarded_await = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            catches_exception = any(
                isinstance(h.type, ast.Name) and h.type.id == "Exception" for h in node.handlers
            )
            if not catches_exception:
                continue
            for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if (
                    isinstance(inner, ast.ImportFrom)
                    and inner.module == "src.sources.ktc_format_archive"
                ):
                    guarded_import = True
                if (
                    isinstance(inner, ast.Await)
                    and isinstance(inner.value, ast.Call)
                    and isinstance(inner.value.func, ast.Name)
                    and inner.value.func.id == "_archive_ktc_format_variants"
                ):
                    guarded_await = True
        assert guarded_import, "the archive import must be inside try/except Exception"
        assert guarded_await, "the archive call must be awaited inside try/except Exception"
        assert src.index("_KTC_VALUE_SOURCE_CAPTURES.update(_captures)") < src.index(
            "await _archive_ktc_format_variants("
        )
