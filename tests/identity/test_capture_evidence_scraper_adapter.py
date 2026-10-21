"""The scraper is an ADAPTER over the U2 / U2b collector, never a second owner.

``Dynasty Scraper.py`` cannot be imported in a test (minutes of module-scope
work), so these are AST checks over its source:

* every collector call goes through the best-effort ``_cev`` wrapper (or sits
  inside a ``try``), so identity evidence can never raise into a value path;
* every method name handed to ``_cev`` exists on the collector — a typo would
  otherwise be swallowed by the wrapper and silently record nothing;
* the U3 site_raw writer appends only the owner's identity columns, after the
  value, and only for the stamped sources;
* the sidecar is written beside the payload, never into ``dashboard_json``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.identity import capture_evidence as ce

REPO = Path(__file__).resolve().parents[2]
SCRAPER = REPO / "Dynasty Scraper.py"


def _tree():
    return ast.parse(SCRAPER.read_text(encoding="utf-8"))


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def test_every_collector_call_is_wrapped():
    tree = _tree()
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id != "_CAPTURE_EVIDENCE":
                continue
            cur, safe = node, False
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.Try) or (
                    isinstance(cur, ast.FunctionDef) and cur.name == "_cev"
                ):
                    safe = True
                    break
            assert safe, f"unwrapped collector call at line {node.lineno}"


def test_every_cev_method_exists_on_the_collector():
    names = set()
    for node in ast.walk(_tree()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_cev"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(node.args[0].value)
    assert names, "the scraper records no identity evidence"
    for name in names:
        assert callable(getattr(ce.CaptureEvidenceCollector, name, None)), name
    # the capture, attach, merge and output sides are all wired
    assert {
        "reset_all",
        "reset_source",
        "add_entry",
        "record_ktc_capture",
        "record_cache_capture",
        "record_entry_dicts",
        "record_checkbox_toggles",
        "mark_recovered_partial",
        "attach",
        "merge",
        "entry_fields",
    } <= names


def test_u3_site_raw_columns_are_the_owners_and_trail_the_value():
    text = SCRAPER.read_text(encoding="utf-8")
    assert '["name", "value", *(_capture_evidence.IDENTITY_CSV_COLUMNS if _u3 else ())]' in text
    assert "_u3 = dash_key in _capture_evidence.STAMPED_SOURCES" in text


def test_the_sidecar_never_enters_the_payload():
    text = SCRAPER.read_text(encoding="utf-8")
    assert 'dashboard_json["identityCaptureEvidence"]' not in text
    assert "_capture_evidence.write_evidence(" in text
    assert ce.MANIFEST_REL.as_posix() == "data/scrape_state/identity_capture_manifest.json"
    assert ce.EVIDENCE_DIR_REL.as_posix() == "data/identity_capture_evidence"


def test_only_the_manifest_is_archived_and_only_this_runs():
    """The bundle (git-tracked ``exports/archive``) gets the small manifest, never
    the full evidence, and only when THIS run wrote it."""
    text = SCRAPER.read_text(encoding="utf-8")
    start = text.index("copy_paths = [")
    block = text[start : text.index("for p in copy_paths:", start)]
    assert "_identity_manifest_path" in block
    assert "if _cev_manifest is not None:" in block
    assert "identity_capture_evidence" not in block.replace("_identity_manifest_path", "")
    assert "_cev_manifest = None" in text[: text.index("_cev_manifest = _capture_evidence.write")]
