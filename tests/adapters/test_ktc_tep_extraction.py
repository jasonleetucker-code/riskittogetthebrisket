"""KTC TE-premium extraction: which level we ask for, and which we read.

T4-3. The scraper requested ``tep=3`` (TE+++) from KTC while every
extractor key names ``tepp`` (TE++, level 2), and while CLAUDE.md
documents ``ktcSfTep`` as the TE++ board. Two identifiers for two
different levels in one code path is the kind of mismatch that stays
latent until something else moves.

MEASURED 2026-07-27 rather than assumed: KTC's inline ``playersArray``
is identical under ``tep=0``, ``tep=2`` and ``tep=3`` — every level
ships in every response. Brock Bowers reads base 8167 / tep 9038 /
tepp 9876 / teppp 9999 under all three. So the URL param never affected
what the payload extractors read.

It affected the RENDERED DOM, which the scraper's last-resort fallback
reads and assigns to the base-SuperFlex ``ktc`` source. Under ``tep=3``
that path wrote TE+++ numbers into a source documented as carrying no TE
premium — 9999 instead of 8167 for Bowers, a 22% inflation on every
tight end, on a path that produces no error and no log line.

These tests pin both halves: the request asks for the level the base
source wants, and the extractor reads the level ``ktcSfTep`` wants.
"""

from __future__ import annotations

import ast
import functools
import re
import types
from pathlib import Path

_SCRAPER = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"


def _scraper_source() -> str:
    return _SCRAPER.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _load_scraper():
    """Extract just the TE-premium helpers, without running the scraper.

    Importing ``Dynasty Scraper.py`` executes it, and that costs four
    MINUTES — it does real work at module scope. A unit test that slow
    stops being run, which is a worse outcome than not having it.

    So this lifts the two constant tuples and ``_ktc_extract_tep`` out
    of the source with ast and execs only those into a bare namespace.
    The function is self-contained apart from ``SUPERFLEX``, which the
    tests set. If it ever grows a dependency this raises rather than
    silently testing a stale copy.
    """
    tree = ast.parse(_scraper_source())
    wanted_funcs = {"_ktc_extract_tep"}
    wanted_names = {"_KTC_TEP_FIELD_KEYS", "_KTC_TEP_TOPLEVEL_KEYS"}
    chunks: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            chunks.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in wanted_names for t in node.targets
        ):
            chunks.append(node)
    missing = wanted_funcs - {n.name for n in chunks if isinstance(n, ast.FunctionDef)}
    assert not missing, f"scraper no longer defines {missing}; this test is stale"

    ns: dict = {"SUPERFLEX": True}
    exec(compile(ast.Module(body=chunks, type_ignores=[]), "<scraper-slice>", "exec"), ns)
    return types.SimpleNamespace(**ns)


# ── The request ──────────────────────────────────────────────────────


def test_the_ktc_url_requests_the_base_te_level():
    """``tep=0``.

    The rendered DOM is the only thing this parameter changes, and the
    only consumer of the rendered DOM is the fallback that populates the
    BASE SuperFlex source. Asking for any premium level there
    contaminates a source that is defined as having none.

    Asserting the exact parameter rather than "the URL contains tep"
    is the point — a substring check would have passed against the
    tep=3 this test exists to prevent, which is ORCHESTRATION.md 6.15's
    recurring substring-for-identity gap.
    """
    src = _scraper_source()
    urls = re.findall(r"keeptradecut\.com/dynasty-rankings\?[^\"']+", src)
    assert urls, "no KTC rankings URL found in the scraper"
    for url in urls:
        assert "tep=0" in url, f"KTC URL requests a TE-premium level: {url}"
        assert "tep=3" not in url
        assert "tep=2" not in url


# ── The extraction ───────────────────────────────────────────────────


def test_the_extractor_reads_te_plus_plus_not_whatever_the_url_asked_for():
    """``ktcSfTep`` is documented as TE++ (level 2). The extractor must
    name that level explicitly, because the payload carries all four and
    picking by position or by "the first one present" would silently
    track KTC's key ordering."""
    scraper = _load_scraper()
    item = {
        "playerName": "Brock Bowers",
        "position": "TE",
        "superflexValues": {
            "value": 8167,
            "tep": {"value": 9038, "rank": 12},
            "tepp": {"value": 9876, "rank": 8},
            "teppp": {"value": 9999, "rank": 1},
        },
    }
    assert scraper._ktc_extract_tep(item) == 9876


def test_the_extractor_resolves_a_nested_dict_not_the_dict_itself():
    """A prior version returned the whole ``tepp`` dict; downstream
    ``int(float({}))`` then raised and the row was skipped, leaving
    ktcSfTep.csv empty. Empty and 'this source has no data' are
    indistinguishable to every consumer."""
    scraper = _load_scraper()
    nested = {"superflexValues": {"value": 100, "tepp": {"value": 250, "rank": 4}}}
    scalar = {"superflexValues": {"value": 100, "tepp": 250}}
    assert scraper._ktc_extract_tep(nested) == 250
    assert scraper._ktc_extract_tep(scalar) == 250


def test_a_payload_without_any_te_level_returns_none_rather_than_a_guess():
    """None is honest: the row simply carries no TE++ value. Falling
    back to the base value would publish a TE with no premium onto a
    board defined as having one."""
    scraper = _load_scraper()
    assert scraper._ktc_extract_tep({"superflexValues": {"value": 8167}}) is None
    assert scraper._ktc_extract_tep({}) is None
    assert scraper._ktc_extract_tep(None) is None


def test_the_extractor_never_returns_the_teppp_level():
    """TE+++ is a real key in the payload and is NOT what this repo
    ingests. If ``tepp`` is absent the answer is None, never the next
    level up — silently promoting a level is how the URL bug would have
    expressed itself in the payload path too."""
    scraper = _load_scraper()
    item = {"superflexValues": {"value": 8167, "teppp": {"value": 9999}}}
    assert scraper._ktc_extract_tep(item) is None
