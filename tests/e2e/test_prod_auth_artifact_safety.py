"""Production data never lands in a public artifact or log (security S3).

This repository is PUBLIC: its Actions logs and uploaded artifacts are
readable by anyone.  Two workflows drive Playwright against PRODUCTION:

* ``v1-authenticated-verification.yml`` — ``tests/e2e/prod-auth.config.js``
  with a REAL session cookie (an ephemeral guest pass);
* ``prod-e2e-smoke.yml`` — ``tests/e2e/playwright.config.js`` with
  ``E2E_BASE_URL`` set to the production origin (anonymous, public pages).

Measured before this guard: artifact 11517431856 of the failed V1 run
37690745794 carried the ``jason_session`` cookie 154 times in
``trace.zip``'s network log, full private response bodies, and videos /
screenshots of private pages — uploaded from ``tests/e2e/test-results-prod-auth/``.

Pinned here:

* the prod-auth config captures nothing (trace / screenshot / video ``off``)
  and runs only the sanitized reporter (no ``list`` / ``json`` / ``html``);
* the default config turns capture off for a non-loopback ``E2E_BASE_URL``;
* neither workflow uploads a Playwright output directory, trace, video or
  screenshot; the V1 workflow's browser contribution is the sanitized JSON
  report only.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PROD_AUTH_CONFIG = E2E_DIR / "prod-auth.config.js"
DEFAULT_CONFIG = E2E_DIR / "playwright.config.js"
V1_WORKFLOW = WORKFLOWS / "v1-authenticated-verification.yml"
SMOKE_WORKFLOW = WORKFLOWS / "prod-e2e-smoke.yml"

#: Upload paths that may carry captured production data.
_FORBIDDEN_UPLOAD = re.compile(
    r"test-results|playwright-report-prod-auth|trace|\.zip\b|\.webm\b|\.png\b|video|screenshot",
    re.I,
)


def _code(src: str) -> str:
    """JS minus line comments (prose may name what the code must not do)."""
    return "\n".join(re.sub(r"(^|\s)//[^\n]*", "", line) for line in src.splitlines())


def _upload_paths(workflow: str) -> list[str]:
    """Every ``path:`` entry of every ``actions/upload-artifact`` step."""
    out: list[str] = []
    for block in re.split(r"\n\s*- name:", workflow):
        if "actions/upload-artifact" not in block:
            continue
        m = re.search(r"\n\s*path:\s*(\|?)\s*\n?(.*?)(\n\s*[a-z-]+:|\Z)", block, re.S)
        if not m:
            continue
        for line in m.group(2).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


class TestProdAuthCapturesNothing(unittest.TestCase):
    def test_trace_screenshot_video_are_off(self) -> None:
        code = _code(PROD_AUTH_CONFIG.read_text(encoding="utf-8"))
        for key in ("trace", "screenshot", "video"):
            values = re.findall(rf"\b{key}\s*:\s*\"([^\"]+)\"", code)
            self.assertEqual(
                values, ["off"], f"prod-auth {key} must be exactly 'off', saw {values}"
            )
        self.assertNotIn("recordVideo", code)
        self.assertNotIn("tracing.start", code)

    def test_only_the_sanitized_reporter_runs(self) -> None:
        code = _code(PROD_AUTH_CONFIG.read_text(encoding="utf-8"))
        block = code[code.index("reporter:") :]
        block = block[: block.index("],") + 2]
        self.assertIn("prod-auth-safe-reporter.js", block)
        for unsafe in ('"list"', '"json"', '"html"', '"line"', '"dot"', '"blob"', '"github"'):
            self.assertNotIn(unsafe, block, f"prod-auth must not run the {unsafe} reporter")

    def test_no_prod_auth_spec_captures_by_hand(self) -> None:
        offenders = []
        for spec in sorted((E2E_DIR / "specs" / "prod-auth").glob("*.js")):
            code = _code(spec.read_text(encoding="utf-8"))
            for pat in (
                r"\.screenshot\(",
                r"tracing\.start",
                r"recordVideo",
                r"testInfo\.attach\(",
            ):
                if re.search(pat, code):
                    offenders.append(f"{spec.name}: {pat}")
        self.assertEqual(
            offenders, [], "a prod-auth spec captures production data:\n" + "\n".join(offenders)
        )


class TestDefaultConfigAgainstAnExternalOrigin(unittest.TestCase):
    def test_capture_is_off_for_a_non_loopback_base_url(self) -> None:
        code = _code(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        self.assertIn("targetsExternalOrigin", code)
        for key in ("trace", "screenshot", "video"):
            self.assertRegex(
                code,
                rf"\b{key}\s*:\s*targetsExternalOrigin\s*\?\s*\"off\"",
                f"default config {key} must be 'off' for an external E2E_BASE_URL",
            )


class TestWorkflowsUploadNoCapture(unittest.TestCase):
    def test_v1_workflow_uploads_only_the_sanitized_report_from_the_browser_suite(self) -> None:
        paths = _upload_paths(V1_WORKFLOW.read_text(encoding="utf-8"))
        self.assertTrue(paths, "found no upload paths — the parser stopped matching")
        bad = [p for p in paths if _FORBIDDEN_UPLOAD.search(p)]
        self.assertEqual(bad, [], f"V1 workflow uploads captured production data: {bad}")
        self.assertIn("tests/e2e/prod-auth-results.json", paths)
        browser = [p for p in paths if p.startswith("tests/e2e/")]
        self.assertEqual(browser, ["tests/e2e/prod-auth-results.json"])

    def test_prod_smoke_uploads_no_capture_directory(self) -> None:
        paths = _upload_paths(SMOKE_WORKFLOW.read_text(encoding="utf-8"))
        self.assertTrue(paths, "found no upload paths — the parser stopped matching")
        bad = [
            p
            for p in paths
            if re.search(r"test-results|trace|video|screenshot|\.zip|\.webm|\.png", p, re.I)
        ]
        self.assertEqual(bad, [], f"prod smoke uploads captured production data: {bad}")

    def test_parser_sees_a_forbidden_path(self) -> None:
        """Non-vacuity: the parser and the pattern catch the original defect."""
        legacy = (
            "      - name: Upload\n        uses: actions/upload-artifact@v7\n        with:\n"
            "          path: |\n            tests/e2e/prod-auth-results.json\n"
            "            tests/e2e/test-results-prod-auth/\n          retention-days: 30\n"
        )
        paths = _upload_paths(legacy)
        self.assertEqual(
            paths, ["tests/e2e/prod-auth-results.json", "tests/e2e/test-results-prod-auth/"]
        )
        self.assertTrue(any(_FORBIDDEN_UPLOAD.search(p) for p in paths))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
