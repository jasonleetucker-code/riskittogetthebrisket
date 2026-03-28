"""Tests that "Refresh Values" button is wired to the live pipeline, not file upload.

These are static-analysis tests that verify the frontend JS files maintain the
correct wiring: the loadDataBtn must trigger triggerScrape() (live pipeline),
never a file-picker click.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[2] / "Static"
BOOTSTRAP_JS = STATIC_DIR / "js" / "runtime" / "50-bootstrap.js"
RUNTIME_JS = STATIC_DIR / "js" / "runtime" / "40-runtime-features.js"
INDEX_HTML = STATIC_DIR / "index.html"


class TestRefreshButtonWiring:
    """The 'Refresh Values' button must never be swapped to a file picker."""

    def test_bootstrap_does_not_hijack_button_to_file_upload(self):
        """50-bootstrap.js must not set loadDataBtn.onclick to jsonFileInput.click()."""
        src = BOOTSTRAP_JS.read_text()
        assert "jsonFileInput" not in src, (
            "Bootstrap JS still references jsonFileInput — "
            "the button should not be wired to file upload"
        )

    def test_bootstrap_does_not_set_button_text_to_update_values(self):
        """50-bootstrap.js must not rename the button to '📊 Update Values'."""
        src = BOOTSTRAP_JS.read_text()
        assert "Update Values" not in src, (
            "Bootstrap JS still sets button text to 'Update Values' — "
            "it should remain 'Refresh Values'"
        )

    def test_html_button_default_is_refresh_values(self):
        """The HTML default for loadDataBtn should be 'Refresh Values' with triggerScrape()."""
        src = INDEX_HTML.read_text()
        # Find the button element
        match = re.search(r'id="loadDataBtn"[^>]*>(.*?)</button>', src)
        assert match is not None, "loadDataBtn not found in index.html"
        btn_text = match.group(1)
        assert "Refresh Values" in btn_text, (
            f"Button default text is '{btn_text}', expected 'Refresh Values'"
        )
        # Verify onclick is triggerScrape, not file upload
        btn_tag = re.search(r'<button[^>]*id="loadDataBtn"[^>]*>', src)
        assert btn_tag is not None
        assert "triggerScrape" in btn_tag.group(0), (
            "loadDataBtn onclick should be triggerScrape()"
        )

    def test_trigger_scrape_does_not_guard_on_server_mode(self):
        """triggerScrape() must not silently return when serverMode is false."""
        src = RUNTIME_JS.read_text()
        # Find the triggerScrape function body
        match = re.search(r'async function triggerScrape\(\)\s*\{', src)
        assert match is not None, "triggerScrape function not found"
        # The old guard was: if (!serverMode) return;
        # It should no longer be the first meaningful line
        func_start = match.end()
        # Get the first ~200 chars of the function body
        snippet = src[func_start:func_start + 300]
        assert "if (!serverMode) return" not in snippet, (
            "triggerScrape still has the serverMode early-return guard — "
            "it should attempt the server call regardless"
        )


class TestHelpTextConsistency:
    """User-facing help text should reference 'Refresh Values', not 'Update Values'."""

    def test_index_html_help_text(self):
        src = INDEX_HTML.read_text()
        # The quick-use card help text
        assert "Update Values" not in src, (
            "index.html still references 'Update Values' in help text"
        )

    def test_runtime_js_alert_messages(self):
        """Alert/placeholder messages should say 'Refresh Values'."""
        for js_file in (STATIC_DIR / "js" / "runtime").glob("*.js"):
            src = js_file.read_text()
            # handleJsonLoad in 20-data-and-calculator.js is allowed to say
            # "Import File" since it's the separate manual-import path
            lines_with_update = [
                (i + 1, line)
                for i, line in enumerate(src.splitlines())
                if "Update Values" in line
                and "handleJsonLoad" not in line  # exclude the import handler
            ]
            assert not lines_with_update, (
                f"{js_file.name} still references 'Update Values' at "
                f"line(s) {[ln for ln, _ in lines_with_update]}"
            )
