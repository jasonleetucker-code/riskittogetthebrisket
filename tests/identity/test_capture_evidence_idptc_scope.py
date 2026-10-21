"""IDP Trade Calculator evidence wiring: the scope-shadowing regression (V2.1 U2/U2b).

``scrape_idptradecalc`` keeps a census dict of the value columns the numbers
were read from and hands it to the identity-evidence collector.  A nested
``def`` of the SAME NAME (the function that lists the value-column keys to
try) rebinds that local, so the collector received a *function* instead of the
census dict.  The failure was invisible by design: every collector call goes
through the best-effort ``_cev`` wrapper, which swallows exceptions so evidence
can never fail a scrape.  The result was silent loss of identity evidence:

* ``record_entry_dicts`` raised on the first keyed entry (item assignment on a
  function), so the capture kept ONE entry instead of all of them;
* ``record_checkbox_toggles`` raised, so the observed Superflex / TE state of
  the capture (U2b) was never recorded.

``Dynasty Scraper.py`` cannot be imported in a test (minutes of module-scope
work), so this lifts ``scrape_idptradecalc`` (+ the real ``_cev`` wrapper) out
with ``ast`` and runs it against a fake Playwright page, exactly like
``tests/sources/test_ktc_format_archive.py::_scrape_ktc_slice``.  Any global the
function grows a dependency on raises ``NameError`` here rather than silently
testing a stale copy.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

import pytest

from src.identity import capture_evidence as ce

REPO = Path(__file__).resolve().parents[2]
SCRAPER = REPO / "Dynasty Scraper.py"
TS = "2026-10-21T00:00:00+00:00"

#: Three entries across the sheets IDP Trade Calculator publishes.  The first
#: two carry position / team; the third carries neither (missing stays absent).
_PAYLOAD = {
    "Sheet1": [
        {"name": "Aidan Hutchinson", "value_sftep": 6100, "position": "DL", "team": "DET"},
        {"name": "Fred Warner", "value_sftep": 5200, "pos": "LB", "team": "SF"},
    ],
    "Sheet3": [
        {"name": "Jahmyr Gibbs", "value_sf": 9000},
    ],
}


def _function_nodes(*names: str) -> list[ast.AST]:
    tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []  # @retry is not under test
            out.append(node)
    assert {n.name for n in out} == set(names), "scraper slice is stale"
    return out


class _Resp:
    status = 200
    url = "https://script.googleusercontent.com/macros/echo?x=1"
    headers = {"content-type": "application/json"}

    def __init__(self, body: str) -> None:
        self._body = body

    async def text(self) -> str:
        return self._body


class _Page:
    """Just enough of a Playwright page for ``scrape_idptradecalc``."""

    def __init__(self, body: str, checked: object = True) -> None:
        self._handlers: list = []
        self._body = body
        self._checked = checked

    def on(self, _event, handler) -> None:
        self._handlers.append(handler)

    async def fire_first_response(self) -> None:
        await self._handlers[0](_Resp(self._body))

    async def wait_for_timeout(self, _ms) -> None:
        return None

    async def evaluate(self, script, *_a):
        text = str(script)
        if "document.getElementById('toggleButton" in text and text.strip().endswith(".checked"):
            return self._checked
        return None


class _FastAsyncio:
    """``asyncio`` with the production wait budgets collapsed to milliseconds."""

    Event = asyncio.Event
    TimeoutError = asyncio.TimeoutError

    @staticmethod
    async def wait_for(aw, timeout):
        return await asyncio.wait_for(aw, 0.05)


def _run_scrape(*, checked: object = True, payload: object = _PAYLOAD, collector=None):
    """Run the real ``scrape_idptradecalc`` slice; returns ``(results, collector)``."""
    collector = collector if collector is not None else ce.CaptureEvidenceCollector()
    body = json.dumps(payload) + " " * 600  # the interceptor ignores bodies <= 500 chars
    page = _Page(body, checked)

    async def safe_goto(p, _url, _name, wait_ms=0):
        await p.fire_first_response()
        return True

    def match_all(players, name_map, results, site_key=None):
        for p in players:
            if p in name_map:
                results[p] = name_map[p]

    ns = {
        "asyncio": _FastAsyncio,
        "re": re,
        "json": json,
        "DEBUG": False,
        "SUPERFLEX": True,
        "TEP": True,
        "FULL_DATA": {},
        "SLEEPER_PLAYERS": {},
        "IDP_AUTOCOMPLETE_ENABLE": False,  # return after the API-driven evidence
        "IDP_AUTOCOMPLETE_MAX": 0,
        "clean_name": lambda n: " ".join(str(n).split()),
        "safe_goto": safe_goto,
        "match_all": match_all,
        "page_dump": None,
        "_capture_evidence": ce,
        "_CAPTURE_EVIDENCE": collector,
    }
    module = ast.Module(body=_function_nodes("_cev", "scrape_idptradecalc"), type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SCRAPER), "exec"), ns)  # noqa: S102
    players = ["Aidan Hutchinson", "Fred Warner", "Jahmyr Gibbs"]
    results = asyncio.run(ns["scrape_idptradecalc"](page, players))
    return results, collector


def test_every_published_entry_is_recorded_not_just_the_first():
    _results, col = _run_scrape()
    side = col.build_sidecar({}, scrape_timestamp=TS)
    block = side["sources"]["idpTradeCalc"]
    assert block["entryCount"] == 3
    assert block["acquisition"] == {ce.ACQ_API_INTERCEPT: 3}


def test_the_value_column_census_reaches_the_collector_as_a_dict():
    _results, col = _run_scrape()
    toggles = col.build_sidecar({}, scrape_timestamp=TS)["sources"]["idpTradeCalc"]["toggles"]
    assert toggles is not None, "U2b toggles were never recorded"
    assert toggles["valueKeys"] == {"value_sf": 1, "value_sftep": 2}


def test_observed_format_state_is_the_page_checkbox_read_back():
    _results, col = _run_scrape(checked=True)
    toggles = col.build_sidecar({}, scrape_timestamp=TS)["sources"]["idpTradeCalc"]["toggles"]
    assert toggles["superflex"] == {"requested": True, "observed": True}
    assert toggles["tePremium"] == {"requested": True, "observed": True}


def test_an_unreadable_checkbox_is_unobserved_never_the_requested_state():
    _results, col = _run_scrape(checked="not-a-bool")
    toggles = col.build_sidecar({}, scrape_timestamp=TS)["sources"]["idpTradeCalc"]["toggles"]
    assert toggles["superflex"] == {"requested": True, "observed": None}
    assert toggles["tePremium"] == {"requested": True, "observed": None}


def test_missing_identity_fields_stay_absent():
    _results, col = _run_scrape()
    col.attach("idpTradeCalc", "Jahmyr Gibbs", "Jahmyr Gibbs", 9000, ["roster_exact"])
    col.attach("idpTradeCalc", "Fred Warner", "Fred Warner", 5200, ["roster_exact"])
    side = col.build_sidecar(
        {"Jahmyr Gibbs": {"idpTradeCalc": 9000}, "Fred Warner": {"idpTradeCalc": 5200}},
        scrape_timestamp=TS,
    )
    attached = side["sources"]["idpTradeCalc"]["attached"]
    gibbs, warner = attached["Jahmyr Gibbs"], attached["Fred Warner"]
    assert "position" not in gibbs and "team" not in gibbs  # not published -> absent, not ""
    assert (warner["position"], warner["team"]) == ("LB", "SF")  # ``pos`` alias read


def test_evidence_never_changes_the_returned_values():
    """A collector that raises on every call must not alter the scrape result."""
    with_evidence, _ = _run_scrape()
    broken = ce.CaptureEvidenceCollector()

    def boom(*_a, **_k):
        raise RuntimeError("evidence failure")

    for name in ("add_entry", "record_entry_dicts", "record_checkbox_toggles", "reset_source"):
        setattr(broken, name, boom)
    without_evidence, _ = _run_scrape(collector=broken)
    assert without_evidence == with_evidence
    assert with_evidence == {
        "Aidan Hutchinson": 6100.0,
        "Fred Warner": 5200.0,
        "Jahmyr Gibbs": 9000.0,
    }


# ── structural guard: the class of bug, not just this instance ──────────


def _scope_bindings(fn: ast.AST) -> dict[str, set[str]]:
    """``{name: kinds}`` bound directly in ``fn``'s own scope (not nested scopes)."""
    kinds: dict[str, set[str]] = {}

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kinds.setdefault(child.name, set()).add("def")
                continue  # do not descend: a nested scope binds its own names
            if isinstance(child, (ast.Lambda, ast.ClassDef)):
                if isinstance(child, ast.ClassDef):
                    kinds.setdefault(child.name, set()).add("class")
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                kinds.setdefault(child.id, set()).add("assign")
            visit(child)

    visit(fn)
    return kinds


@pytest.mark.parametrize("name", ["scrape_idptradecalc", "scrape_ktc", "run"])
def test_no_name_is_both_assigned_and_def_d_in_the_scrapers_evidence_scopes(name):
    node = next(
        n
        for n in ast.parse(SCRAPER.read_text(encoding="utf-8")).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    clashes = {k: v for k, v in _scope_bindings(node).items() if {"def", "assign"} <= v}
    assert not clashes, f"{name}: a local is bound as both a value and a function: {clashes}"
