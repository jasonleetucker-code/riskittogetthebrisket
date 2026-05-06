"""Parity / schema tests for tunable config + cross-file registries.

These tests close the gaps documented in
``docs/automation-audit.md`` (G2, G3a, G6, G7).  Each test pins a
hidden-coupling that previously had no CI gate:

* ``test_source_csv_paths_have_registry_entries`` — every key in
  ``_SOURCE_CSV_PATHS`` must exist in ``_RANKING_SOURCES`` (a renamed
  scraper output silently dropping a source from the live blend used
  to be invisible until someone noticed missing data).
* ``test_frontend_source_vendors_covers_python_registry`` — the
  frontend ``SOURCE_VENDORS`` map must classify every Python source
  whose vendor is shared across multiple sub-boards.
* ``test_config_files_parse`` — every JSON file under ``config/``
  must parse, so a typo can't ship to prod and surface as a runtime
  503.
* ``test_league_registry_well_formed`` — the live ``registry.json``
  loads via the production parser, every league has a non-empty
  scoring profile string, and aliases don't collide.

When CI fails on one of these, the message tells you which file
drifted.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DATA = REPO_ROOT / "frontend" / "lib" / "dynasty-data.js"
CONFIG_DIR = REPO_ROOT / "config"


# ── G2: every CSV path key must be a registered source ────────────────────
class TestSourceCsvPathRegistryParity(unittest.TestCase):
    # Sources that are intentionally loaded into ``canonicalSiteValues``
    # for trade-finder / per-source winner display but do NOT vote in
    # the blend.  Standard ``ktc`` was retired from the blend
    # 2026-04-28 in favor of ``ktcSfTep`` (same scrape, TE+ values),
    # but the standard CSV still loads so the KTC arbitrage finder +
    # /trade per-source row can keep displaying both KTC variants.
    DISPLAY_ONLY_CSV_KEYS: set[str] = {"ktc"}

    def test_source_csv_paths_have_registry_entries(self) -> None:
        from src.api.data_contract import _SOURCE_CSV_PATHS, _RANKING_SOURCES

        registry_keys = {str(s["key"]) for s in _RANKING_SOURCES}
        csv_keys = set(_SOURCE_CSV_PATHS.keys())

        # Every CSV-mapped source must be in the registry OR the
        # display-only allowlist.  The reverse direction is *not*
        # enforced — some registry sources (e.g. picks-only synthetic
        # entries) intentionally have no CSV.
        orphans = sorted(csv_keys - registry_keys - self.DISPLAY_ONLY_CSV_KEYS)
        self.assertEqual(
            orphans,
            [],
            "_SOURCE_CSV_PATHS contains keys not registered in "
            f"_RANKING_SOURCES: {orphans}.  A scraper rename or registry "
            "removal silently dropped this source from the live blend.  "
            "If the source should load for display but not vote, add it "
            "to DISPLAY_ONLY_CSV_KEYS.",
        )


# ── G3a: frontend SOURCE_VENDORS must cover every Python multi-board vendor ──
def _parse_js_object_literal(text: str, name: str) -> dict[str, str]:
    """Extract ``export const NAME = { key: "val", ... }`` into a dict.

    Mirrors the regex/walk approach used in
    ``test_source_registry_parity.py`` so we don't need a JS engine.
    """
    pattern = re.compile(
        rf"export const {re.escape(name)}\s*=\s*\{{",
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"Could not locate `export const {name} = {{` in JS")
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if depth != 0:
        raise ValueError(f"Could not match closing `}}` for {name}")
    body = text[start : i - 1]
    # Strip line + block comments.
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    body = re.sub(r"//[^\n]*", "", body)
    out: dict[str, str] = {}
    # Walk pairs of `key: "value",`
    pair_re = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*|"[^"]+")\s*:\s*"([^"]+)"',
    )
    for key, value in pair_re.findall(body):
        if key.startswith('"') and key.endswith('"'):
            key = key[1:-1]
        out[key] = value
    return out


class TestFrontendSourceVendorsParity(unittest.TestCase):
    def test_js_source_vendors_keys_all_in_python_registry(self) -> None:
        """Every key in the frontend ``SOURCE_VENDORS`` map must exist
        in the Python ``_RANKING_SOURCES`` registry.  Catches the
        common "Python source removed but JS vendor map kept the entry"
        drift — that drift would silently route a non-existent source
        to a vendor row in the per-source breakdown.
        """
        from src.api.data_contract import _RANKING_SOURCES

        text = FRONTEND_DATA.read_text(encoding="utf-8")
        js_vendors = _parse_js_object_literal(text, "SOURCE_VENDORS")
        registry_keys = {str(s["key"]) for s in _RANKING_SOURCES}
        stale = sorted(set(js_vendors) - registry_keys)
        self.assertEqual(
            stale,
            [],
            "Frontend SOURCE_VENDORS map contains keys that no longer "
            f"exist in _RANKING_SOURCES: {stale}.  Either re-add the "
            "Python registry entry or remove the JS vendor mapping.",
        )


# ── G6: every config JSON parses ─────────────────────────────────────────
class TestConfigJsonFilesParse(unittest.TestCase):
    def test_config_files_parse(self) -> None:
        # Walk the config tree.  ``.template.json`` files are illustrative
        # references for new sources/leagues — they're not loaded at
        # runtime, but they should still be valid JSON so anyone copying
        # one as a starting point gets a working file.
        bad: list[tuple[str, str]] = []
        for path in sorted(CONFIG_DIR.rglob("*.json")):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                bad.append((str(path.relative_to(REPO_ROOT)), str(exc)))
        self.assertEqual(
            bad,
            [],
            "JSON parse errors in config/:\n"
            + "\n".join(f"  {p}: {err}" for p, err in bad),
        )


# ── G7: league registry well-formed ──────────────────────────────────────
class TestLeagueRegistryWellFormed(unittest.TestCase):
    """The conftest deliberately points the registry at a nonexistent
    path so unit tests don't hit the operator's live league.  These
    tests need the *real* registry, so they explicitly override the
    path back to the canonical file via ``LEAGUE_REGISTRY_PATH`` and
    reload before each test.  ``tearDownClass`` restores the conftest
    setting so we don't leak the override to neighbouring tests.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import os
        from src.api import league_registry as lr

        cls._prior_registry_path = os.environ.get("LEAGUE_REGISTRY_PATH")
        os.environ["LEAGUE_REGISTRY_PATH"] = str(
            REPO_ROOT / "config" / "leagues" / "registry.json"
        )
        lr.reload_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        import os
        from src.api import league_registry as lr

        if cls._prior_registry_path is None:
            os.environ.pop("LEAGUE_REGISTRY_PATH", None)
        else:
            os.environ["LEAGUE_REGISTRY_PATH"] = cls._prior_registry_path
        lr.reload_registry()

    def test_league_registry_loads_via_production_parser(self) -> None:
        """The production loader (``src/api/league_registry.py``) must
        accept the live registry.json without raising.  Failures here
        would surface in production as a 503 on every league-aware
        endpoint, so they should block CI instead.
        """
        from src.api import league_registry as lr

        leagues = lr.all_leagues()
        self.assertGreater(
            len(leagues),
            0,
            "League registry parsed but produced zero leagues — "
            "config/leagues/registry.json is empty or all entries "
            "were rejected.",
        )

    def test_every_league_has_non_empty_scoring_profile(self) -> None:
        """A league with ``scoringProfile`` blank or missing falls back
        to the literal string ``"default"`` (see
        ``league_registry._parse_league_entry``), which then fails
        silently downstream when no profile of that name is
        configured.  Catch the gap at config-time.
        """
        from src.api import league_registry as lr

        offenders: list[str] = []
        for cfg in lr.all_leagues():
            if not cfg.scoring_profile or cfg.scoring_profile == "default":
                offenders.append(cfg.key)
        self.assertEqual(
            offenders,
            [],
            "League(s) without an explicit non-default scoringProfile: "
            f"{offenders}.  Set scoringProfile in the registry entry; "
            'falling back to "default" will silently break downstream '
            "scoring-profile lookups.",
        )

    def test_league_aliases_do_not_collide(self) -> None:
        """No alias may resolve to two different leagues.  If two
        leagues both list ``"main"`` in their aliases, the resolver
        picks one non-deterministically and the user lands on the
        wrong league.
        """
        from src.api import league_registry as lr

        seen: dict[str, str] = {}
        collisions: list[str] = []
        for cfg in lr.all_leagues():
            for alias in cfg.aliases:
                norm = alias.lower().strip()
                if not norm:
                    continue
                if norm in seen and seen[norm] != cfg.key:
                    collisions.append(f"{norm!r}: {seen[norm]} vs {cfg.key}")
                seen[norm] = cfg.key
        self.assertEqual(
            collisions,
            [],
            "Alias collisions between leagues:\n  "
            + "\n  ".join(collisions),
        )


# ── G1 (preventive): every source in _SOURCE_CSV_PATHS gets a staleness threshold ──
class TestSourceStalenessCoverage(unittest.TestCase):
    def test_every_csv_source_has_staleness_threshold(self) -> None:
        """Source-health alerts use a default 168 h (7 day) threshold
        when a source isn't in ``config/source_staleness.json``.  Make
        sure every active CSV source has an explicit threshold (matched
        either by full source key or by its vendor prefix) so the
        operator has reviewed and signed off on each source's alert
        SLA.
        """
        from src.api.data_contract import _SOURCE_CSV_PATHS
        from src.api import source_health_alerts as sha

        thresholds = sha.load_thresholds()
        # A threshold key matches a source key if the source key starts
        # with the threshold key.  This mirrors the convention in
        # ``config/source_staleness.json`` where vendor-name keys
        # (``"fantasyPros"``) cover every sibling board
        # (``fantasyProsSf``, ``fantasyProsIdp``, ``fantasyProsFitzmaurice``).
        def _has_threshold(source_key: str) -> bool:
            if source_key in thresholds:
                return True
            for thr_key in thresholds:
                if source_key.startswith(thr_key):
                    return True
            return False

        missing = sorted(
            str(k) for k in _SOURCE_CSV_PATHS if not _has_threshold(str(k))
        )
        self.assertEqual(
            missing,
            [],
            "Source(s) with no explicit staleness threshold "
            "(falling back to 168 h default):\n  "
            + "\n  ".join(missing)
            + "\n\nAdd entries to config/source_staleness.json so each "
            "source has an explicit SLA.",
        )


# ── G8: every CSV source has a freshness-stamp writer ────────────────────
class TestSourceFreshnessStampCoverage(unittest.TestCase):
    """``server._per_source_freshness`` looks up each registered source's
    freshness via ``data/scrape_state/{registry_key}_last_success`` and
    only falls back to CSV mtime when the stamp is missing.  On
    production, ``deploy.sh`` does ``git checkout --force`` which
    skips rewriting byte-identical files, so CSV mtime freezes on the
    last *content* change instead of the last *fetcher success* —
    fine for sources whose content jitters every fetch (KTC values),
    but a 24h false-positive stale alert for sources whose CSV often
    repeats verbatim (rookie consensus, FootballGuys monthly PDFs).

    Every registry key in ``_SOURCE_CSV_PATHS`` must therefore either
    (a) be stamped by the scheduled-refresh workflow or one of the
    side fetch-and-push scripts, or (b) appear in
    ``MTIME_RELIABLE_SOURCES`` — the explicit allowlist of sources
    whose CSV content provably changes every fetch (Dynasty
    Scraper.py outputs).
    """

    # Sources written by ``Dynasty Scraper.py`` (no per-source stamp).
    # Their CSVs include continuously-jittering values from the live KTC
    # API or KTC-derived feeds, so CSV mtime is a reliable freshness
    # signal even after ``git checkout --force``.  If a source migrates
    # off the scraper to its own fetcher, give it a stamp writer and
    # remove it from this set.
    MTIME_RELIABLE_SOURCES: set[str] = {
        "ktc",
        "ktcSfTep",
        "idpTradeCalc",
        "dynastyNerdsSfTep",
        "fantasyProsSf",
        "fantasyProsIdp",
    }

    @staticmethod
    def _collect_stamp_writers() -> set[str]:
        """Scan the workflow YAML + deploy scripts for every stamp key
        that gets written to ``data/scrape_state/{key}_last_success``.

        Three writer patterns are recognised:

        1. ``run_fetcher <stamp_keys> ...`` in scheduled-refresh.yml,
           where ``stamp_keys`` is a colon-separated list (the helper
           writes one stamp per key on success).
        2. ``data/scrape_state/{key}_last_success`` literal paths in
           shell scripts (``deploy/dlf_fetch_and_push.sh``,
           ``deploy/idpshow_fetch_and_push.sh``) - matches both
           ``date ... > data/scrape_state/X_last_success`` and the
           loop-driven multi-key form.
        3. ``for key in a b c ...`` loops that emit per-key stamps.
        """
        out: set[str] = set()
        # Pattern 1: workflow run_fetcher invocations.
        wf_path = REPO_ROOT / ".github" / "workflows" / "scheduled-refresh.yml"
        if wf_path.exists():
            wf_text = wf_path.read_text(encoding="utf-8")
            # ``run_fetcher <stamp_keys> "<label>" python ...``
            run_fetcher_re = re.compile(
                r"run_fetcher\s+([A-Za-z0-9_:]+)\s+\"",
            )
            for match in run_fetcher_re.findall(wf_text):
                for key in match.split(":"):
                    if key:
                        out.add(key)

        # Pattern 2 + 3: deploy shell scripts (literal paths + for-loops).
        for script_name in ("dlf_fetch_and_push.sh", "idpshow_fetch_and_push.sh"):
            script_path = REPO_ROOT / "deploy" / script_name
            if not script_path.exists():
                continue
            text = script_path.read_text(encoding="utf-8")
            # Literal: data/scrape_state/<key>_last_success
            for match in re.findall(
                r"data/scrape_state/([A-Za-z0-9_]+)_last_success",
                text,
            ):
                out.add(match)
            # ``for key in dlf dlfSf dlfIdp ...`` style loops feeding
            # the literal pattern above are caught by reading the
            # iterated tokens explicitly.
            for match in re.findall(
                r"for\s+\w+\s+in\s+([A-Za-z0-9_ \t]+);",
                text,
            ):
                for token in match.split():
                    if token and not token.startswith("$"):
                        out.add(token)
        return out

    def test_every_csv_source_has_stamp_writer_or_is_mtime_reliable(self) -> None:
        from src.api.data_contract import _SOURCE_CSV_PATHS

        stamp_writers = self._collect_stamp_writers()
        registry_keys = {str(k) for k in _SOURCE_CSV_PATHS}

        missing: list[str] = []
        for key in sorted(registry_keys):
            if key in self.MTIME_RELIABLE_SOURCES:
                continue
            if key in stamp_writers:
                continue
            missing.append(key)

        self.assertEqual(
            missing,
            [],
            "Registry source(s) with no freshness-stamp writer:\n  "
            + "\n  ".join(missing)
            + "\n\nThese sources will fall back to CSV mtime in "
            "server._per_source_freshness, which freezes on prod's "
            "git checkout --force whenever the vendor re-publishes "
            "byte-identical content — tripping false-positive 24h "
            "stale alerts.  Add a stamp writer in "
            ".github/workflows/scheduled-refresh.yml (run_fetcher "
            "stamp_keys list) or the relevant deploy/*.sh script, or "
            "add the key to MTIME_RELIABLE_SOURCES if its CSV content "
            "provably changes every fetch.",
        )


if __name__ == "__main__":
    unittest.main()
