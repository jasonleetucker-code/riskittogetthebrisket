"""Execute production evaluate scripts in Node, not mocked projected results.

This exercises JavaScript projection plus the real Python source owner. Node's
VM/JSON bridge is not Chromium, Playwright's transport, or the production cgroup.
No live HTTP requests or production mutations are performed.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
import json
import shutil
import subprocess

import pytest

from src.sources import ktc_value_sources as ktc


_NODE_RUNNER = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sandbox = {
  window: {},
  fixtureRows: input.rows,
  document: { querySelectorAll(selector) {
    if (selector !== 'select') throw new Error('Unexpected DOM selector: ' + selector);
    return input.controls;
  }}
};
const context = vm.createContext(sandbox);
if (input.lookup === 'lexical') {
  vm.runInContext('const playersArray = fixtureRows;', context);
} else if (input.lookup === 'global') {
  sandbox.playersArray = input.rows;
} else if (input.lookup === 'window') {
  sandbox.window.playersArray = input.rows;
} else if (input.lookup === 'shadowed') {
  sandbox.playersArray = 'not an array';
  sandbox.window.playersArray = input.rows;
}
if (input.before) vm.runInContext(input.before, context, {timeout: 3000});
const before = input.checkUnchanged ? JSON.stringify(input.rows) : null;
const result = vm.runInContext('"use strict"; (' + input.script + ')()', context, {timeout: 3000});
if (input.checkUnchanged && before !== JSON.stringify(input.rows)) {
  throw new Error('Projection mutated its source');
}
process.stdout.write(JSON.stringify(result));
"""


def _controls():
    return [
        {
            "value": "2",
            "options": [
                {"textContent": ktc.KTC_VALUE_SOURCE_LABELS[source], "value": value}
                for source, value in ktc.KTC_CONTROL_VALUES.items()
            ],
        }
    ]


def _values(index=0):
    return {
        "value": 7000 - index,
        "rank": 10 + index,
        "blendValue": 7200 - index,
        "blendRank": 8 + index,
        "vftValue": 7400 - index,
        "vftRank": 6 + index,
    }


def _board(count=500):
    return [
        {
            "playerID": 1000 + i,
            "playerName": f"Synthetic Player {i}",
            "position": "TE" if i % 5 == 0 else "WR",
            "superflexValues": {**_values(i), "tepp": _values(i + 1)},
        }
        for i in range(count)
    ]


class _NodePage:
    url = "https://keeptradecut.com/dynasty-rankings?sf=true&tep=0"

    def __init__(self, rows, *, lookup="global", controls=None, before="", unchanged=False):
        self.rows = rows
        self.lookup = lookup
        self.controls = _controls() if controls is None else controls
        self.before = before
        self.unchanged = unchanged
        self.calls = []
        self.output_bytes = []

    async def evaluate(self, script):
        node = shutil.which("node")
        assert node is not None, "These tests require Node to execute production JavaScript"
        self.calls.append(script)
        result = subprocess.run(
            [node, "-e", _NODE_RUNNER],
            input=json.dumps(
                {
                    "rows": self.rows,
                    "lookup": self.lookup,
                    "controls": self.controls,
                    "before": self.before,
                    "checkUnchanged": self.unchanged,
                    "script": script,
                }
            ),
            text=True,
            capture_output=True,
            timeout=15,
            check=True,
        )
        self.output_bytes.append(len(result.stdout.encode("utf-8")))
        return json.loads(result.stdout)


def _capture(page):
    return asyncio.run(ktc.capture_all_value_sources(page))


def _project(rows, **kwargs):
    page = _NodePage(rows, **kwargs)
    projected = asyncio.run(ktc.selected_players_array(page))
    assert len(page.calls) == 1
    return projected


def _edge_board():
    rows = _board()
    rows[0]["superflexValues"]["tepp"] = None
    rows[0]["tepp"] = _values(200)
    rows[1]["superflexValues"]["tepp"] = 0
    rows[1]["tepp"] = _values(210)
    rows[2]["superflexValues"]["tepp"] = 555
    rows[3]["superflexValues"] = None
    rows[3]["tepp"] = _values(220)
    rows[4]["superflexValues"] = []
    rows[4]["tepp"] = 666
    rows[5]["playerName"] = ""
    rows[5]["name"] = "  Alias Name  "
    rows[5]["position"] = " RDP "
    rows[5]["playerID"] = "001709"
    for group in (rows[6]["superflexValues"], rows[6]["superflexValues"]["tepp"]):
        for field in list(_values()):
            inner = "rank" if field == "rank" or field.endswith("Rank") else "value"
            group[field] = {inner: group[field], "unused": [0] * 500}
    rows[7]["superflexValues"]["vftValue"] = None
    rows[7]["superflexValues"]["tepp"]["vftValue"] = 0
    rows[8]["superflexValues"]["tepp"] = ""
    rows[8]["tepp"] = _values(230)
    rows[9]["superflexValues"]["tepp"] = False
    rows[9]["tepp"] = _values(240)
    rows[10]["superflexValues"].pop("tepp")
    rows[10]["tepp"] = _values(250)
    rows[11]["playerID"] = "not an id"
    rows[11]["position"] = None
    rows[12:17] = [None, "not a row", [], 4, {"notAName": "ignored"}]
    return rows


@pytest.mark.parametrize("source", ktc.KTC_VALUE_SOURCES)
@pytest.mark.parametrize("lookup", ["global", "lexical", "window", "shadowed"])
def test_projection_matches_parser_and_hash(source, lookup):
    original = _edge_board()
    projected = _project(original, lookup=lookup, unchanged=True)
    expected = ktc.observations_from_players_array(original, source)
    actual = ktc.observations_from_players_array(projected, source)
    assert actual == expected
    assert ktc._content_hash(actual) == ktc._content_hash(expected)
    assert len(projected) == len(original)


def test_native_trade_value_is_not_replaced_with_blend():
    rows = _board()
    projected = _project(rows)
    actual = ktc.observations_from_players_array(projected, ktc.KTC_TRADES)[0]
    assert actual.base_value == rows[0]["superflexValues"]["vftValue"]
    assert actual.tepp_value == rows[0]["superflexValues"]["tepp"]["vftValue"]
    assert actual.tepp_value != rows[0]["superflexValues"]["tepp"]["blendValue"]


def test_top_level_tepp_fallback_and_zero_do_not_change():
    rows = _edge_board()
    projected = _project(rows)
    for source in ktc.KTC_VALUE_SOURCES:
        actual = ktc.observations_from_players_array(projected, source)
        expected = ktc.observations_from_players_array(rows, source)
        assert actual[0].tepp_value == expected[0].tepp_value
        assert actual[0].tepp_value is not None
        assert actual[1].tepp_value is None
        assert actual[8].tepp_value is None
        assert actual[9].tepp_value is None


def test_payload_size_does_not_scale_with_unused_fields():
    lean = _board()
    heavy = copy.deepcopy(lean)
    for row in heavy:
        row["unusedHistory"] = "x" * 8192
        row["superflexValues"]["unusedHistory"] = "y" * 8192
        row["superflexValues"]["tepp"]["unusedHistory"] = "z" * 8192
    lean_page = _NodePage(lean)
    heavy_page = _NodePage(heavy)
    lean_result = asyncio.run(ktc.selected_players_array(lean_page))
    heavy_result = asyncio.run(ktc.selected_players_array(heavy_page))
    assert heavy_result == lean_result
    assert heavy_page.output_bytes == lean_page.output_bytes
    assert len(heavy_result) == 500
    assert [row["playerID"] for row in heavy_result] == list(range(1000, 1500))
    assert heavy_page.output_bytes[0] < 250_000


def test_unused_getters_are_never_traversed_or_transferred():
    before = r"""
    const poison = target => Object.defineProperty(target, 'unusedHistory', {
      enumerable: true, get() { throw new Error('UNUSED_PROPERTY_TRAVERSED'); }
    });
    for (const row of fixtureRows) {
      poison(row);
      poison(row.superflexValues);
      poison(row.superflexValues.tepp);
      row.superflexValues.value = {value: row.superflexValues.value};
      poison(row.superflexValues.value);
    }
    """
    projected = _project(_board(), before=before)
    assert len(projected) == 500
    assert projected[0]["superflexValues"]["value"] == {"value": 7000}


@pytest.mark.parametrize("count", [0, 1, 99])
def test_missing_partial_array_is_rejected(count):
    with pytest.raises(ktc.KtcValueSourceError, match="missing/partial"):
        _project(_board(count))


@pytest.mark.parametrize("lookup", ["absent", "global", "window"])
def test_absent_or_non_array_is_rejected(lookup):
    with pytest.raises(ktc.KtcValueSourceError, match="missing/partial"):
        _project({"not": "an array"}, lookup=lookup)


def test_source_array_is_not_mutated():
    before = r"""
    const freeze = obj => {
      if (obj && typeof obj === 'object') {
        Object.values(obj).forEach(freeze);
        Object.freeze(obj);
      }
    };
    freeze(fixtureRows);
    """
    _project(_board(), before=before, unchanged=True)


def test_three_source_capture_preserves_provenance_and_two_evaluations():
    original = _board()
    page = _NodePage(original)
    captures = _capture(page)
    assert len(page.calls) == 2
    assert len({c.captured_at for c in captures.values()}) == 1
    for source, capture in captures.items():
        expected = ktc.observations_from_players_array(original, source)
        assert capture.rows == expected
        assert capture.content_hash == ktc._content_hash(expected)
        assert capture.selected_value == ktc.KTC_CONTROL_VALUES[source]
        assert capture.selected_label == ktc.KTC_VALUE_SOURCE_LABELS[source]
        assert capture.row_count == 500
        assert capture.priced_count == 500
        assert capture.superflex is True
        assert capture.te_premium_level == 2
        assert capture.te_premium == "TE++"
        assert capture.page_url == page.url


def test_missing_source_control_fails_before_array_transfer():
    controls = _controls()
    controls[0]["options"].pop()
    page = _NodePage(_board(), controls=controls)
    with pytest.raises(ktc.KtcValueSourceError, match="three-mode Value Source control"):
        _capture(page)
    assert len(page.calls) == 1


def test_changed_control_encoding_fails_closed():
    controls = _controls()
    controls[0]["options"][0]["value"] = "changed"
    with pytest.raises(ktc.KtcValueSourceError, match="control value changed"):
        _capture(_NodePage(_board(), controls=controls))


def test_identical_mode_boards_are_rejected():
    rows = _board()
    for row in rows:
        for block in (row["superflexValues"], row["superflexValues"]["tepp"]):
            block["blendValue"] = block["vftValue"] = block["value"]
            block["blendRank"] = block["vftRank"] = block["rank"]
    with pytest.raises(ktc.KtcValueSourceError, match="byte-equivalent"):
        _capture(_NodePage(rows))


@pytest.mark.parametrize(
    ("source", "field"),
    [(ktc.KTC_CROWD, "value"), (ktc.KTC_TRADES, "vftValue"), (ktc.KTC_CROWD_TRADES, "blendValue")],
)
def test_partial_source_coverage_is_rejected(source, field):
    rows = _board()
    for row in rows:
        row["superflexValues"]["tepp"][field] = None
    with pytest.raises(ktc.KtcValueSourceError, match=f"KTC {source} board is partial"):
        _capture(_NodePage(rows))


def test_capture_artifact_bytes_match_unprojected_observations(tmp_path):
    original = _board()
    captures = _capture(_NodePage(original))
    expected = {}
    for source, capture in captures.items():
        rows = ktc.observations_from_players_array(original, source)
        expected[source] = replace(capture, rows=rows, content_hash=ktc._content_hash(rows))
    for name, data in (("projected", captures), ("unprojected", expected)):
        ktc.write_capture_artifacts(
            data,
            site_raw_dir=tmp_path / name / "site_raw",
            provenance_path=tmp_path / name / "provenance.json",
        )
    for path in (tmp_path / "projected").rglob("*"):
        if path.is_file():
            other = tmp_path / "unprojected" / path.relative_to(tmp_path / "projected")
            assert path.read_bytes() == other.read_bytes()
