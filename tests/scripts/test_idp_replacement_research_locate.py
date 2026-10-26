"""``scripts/idp_replacement_research.py::locate`` finds a wrapped call (LI-5 P3
review finding F-C).

The consumer table cites ``path:line`` for each place an anchor is read.  The
LI-5 wiring wrapped ``waiver_values_by_position(contract, ...)`` in
``src/draft/context.py`` across several lines, so the per-line regex returned
``src/draft/context.py:?``.  ``locate`` now searches the whole file.
"""

from __future__ import annotations

from scripts import idp_replacement_research as research


def test_locate_matches_a_call_wrapped_across_lines(tmp_path, monkeypatch):
    src = tmp_path / "mod.py"
    src.write_text(
        "x = 1\n\n"
        "    waiver_values = waiver_values_by_position(\n"
        "        contract, rostered_keys, auction_keys, population=population\n"
        "    )\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(research, "REPO", tmp_path)

    pattern = r"waiver_values = waiver_values_by_position\(\s*contract"
    assert research.locate("mod.py", pattern) == "mod.py:3"
    # The single-line form still resolves, to its own line.
    src.write_text(
        "a = 0\nwaiver_values = waiver_values_by_position(contract, k)\n", encoding="utf-8"
    )
    assert research.locate("mod.py", pattern) == "mod.py:2"


def test_locate_keeps_line_anchors_and_reports_a_miss_as_unknown(tmp_path, monkeypatch):
    (tmp_path / "mod.py").write_text(
        "# def waiver\n\ndef waiver_values_by_position():\n", encoding="utf-8"
    )
    monkeypatch.setattr(research, "REPO", tmp_path)

    assert research.locate("mod.py", r"^def waiver_values_by_position") == "mod.py:3"
    assert research.locate("mod.py", r"^def nope") == "mod.py:?"


def test_the_perfect_draft_context_citation_resolves_in_the_live_tree():
    path, pattern = next((p, rx) for _d, p, rx in research.CONSUMERS if p == "src/draft/context.py")
    assert not research.locate(path, pattern).endswith(":?")
