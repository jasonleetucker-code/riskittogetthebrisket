"""Independent-review follow-ups on #1910: one VID writer (M3), counted collector
failures (L3), malformed directory rows (L4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.identity import capture_evidence as ce
from src.identity import resolution as r
from src.identity import vendor_ids as v

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "scheduled-refresh.yml"
TS = "2026-11-04T02:00:00+00:00"


# ── M3: one writer for the append-only vendor-id map ────────────────────


def test_only_the_marked_process_writes_the_vendor_id_map():
    assert v.writer_enabled({v.WRITER_ENV: "1"}) is True
    for env in ({}, {v.WRITER_ENV: "0"}, {v.WRITER_ENV: "true"}, {"GITHUB_ACTIONS": "true"}):
        assert v.writer_enabled(env) is False


def test_the_refresh_scraper_step_is_the_writer_and_nothing_else_is():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Run scraper")
    step = text[start : text.index("run: |", start)]
    assert f'{v.WRITER_ENV}: "1"' in step
    assert text.count(v.WRITER_ENV) == 1  # no other step of the refresh
    for path in (REPO / "deploy").rglob("*"):
        if path.is_file() and path.suffix in {".service", ".sh", ".env", ".timer", ".conf"}:
            assert v.WRITER_ENV not in path.read_text(encoding="utf-8", errors="ignore"), path
    scraper = (REPO / "Dynasty Scraper.py").read_text(encoding="utf-8")
    gate = scraper.index("_vendor_ids.writer_enabled(os.environ)")
    assert gate < scraper.index("_vendor_ids.record_from_site_raw(")


# ── L3: swallowed collector failures are counted ────────────────────────


def test_census_counts_collector_failures():
    col = ce.CaptureEvidenceCollector()
    side = col.build_sidecar({}, scrape_timestamp=TS)
    assert side["census"]["collectorErrors"] == {"total": 0, "byMethod": {}}
    col.note_failure("record_entry_dicts")
    col.note_failure("record_entry_dicts")
    col.note_failure("attach")
    side = col.build_sidecar({}, scrape_timestamp=TS)
    assert side["census"]["collectorErrors"] == {
        "total": 3,
        "byMethod": {"attach": 1, "record_entry_dicts": 2},
    }
    col.reset_all()
    assert col.build_sidecar({}, scrape_timestamp=TS)["census"]["collectorErrors"]["total"] == 0


def test_the_scrapers_wrapper_counts_what_it_swallows():
    """The real ``_cev`` lifted from the scraper: a raising collector call is
    swallowed AND counted, and the count reaches the manifest."""
    import ast

    tree = ast.parse((REPO / "Dynasty Scraper.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_cev")
    col = ce.CaptureEvidenceCollector()
    ns = {"_CAPTURE_EVIDENCE": col, "DEBUG": False}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "scraper", "exec"), ns)  # noqa: S102
    assert ns["_cev"]("add_entry", "ktc", "A", 1, acquisition="not-a-path") is None
    assert ns["_cev"]("no_such_method") is None
    errors = col.build_sidecar({}, scrape_timestamp=TS)["census"]["collectorErrors"]
    assert errors == {"total": 2, "byMethod": {"add_entry": 1, "no_such_method": 1}}
    manifest = ce.build_manifest(
        col.build_sidecar({}, scrape_timestamp=TS),
        evidence_bytes=b"x",
        gzip_bytes=b"y",
        filename="f",
        artifact=None,
    )
    assert manifest["census"]["collectorErrors"]["total"] == 2


# ── L4: malformed directory rows are no evidence, never an error ────────


@pytest.mark.parametrize("raw", [7, "WR", None, {"x": 1}, 3.5, True])
def test_non_list_fantasy_positions_are_no_evidence_not_an_error(raw):
    index = r.build_sleeper_index(
        {"1": {"full_name": "A Player", "position": "WR", "fantasy_positions": raw}}
    )
    facts = index.facts_by_sleeper_id.get("1")
    assert facts is None or facts[1] == ()
    good = r.build_sleeper_index(
        {"1": {"full_name": "A Player", "position": "WR", "fantasy_positions": ["wr", "", None]}}
    )
    assert good.facts_by_sleeper_id["1"] == (None, ("WR",))
