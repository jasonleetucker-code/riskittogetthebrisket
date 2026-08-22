"""Durable protection for canonical-value ownership.

The mobile/desktop incident had one shape: a **device-local setting**
selected a **non-canonical methodology**, and that methodology **wrote the
canonical field**. Three separate mechanisms had to line up, and any one
of them broken is enough to reproduce it.

``test_canonical_value_invariance.py`` proves the specific defects are
fixed. This file protects the *class* — it is the thing that has to keep
working after everyone who remembers the incident has moved on.

The invariants, and why each one is here rather than assumed:

  A  only approved producers write canonical value
  C  user source weighting cannot write canonical value
  D  device-local settings cannot change canonical value
  E  canonical aliases stay coherent with each other
  G  canonical history records canonical output only
  H  canonical API projections preserve the authoritative value

B (experimental-overlay isolation) and F (compact/array transport parity)
live in ``test_canonical_value_invariance.py`` beside the fixtures they
need; they are not repeated here.

Deliberately simple: repository scans and real function calls, no AST
framework. The scans are narrow and each one asserts non-vacuity, because
a static check that silently stops matching is worse than no check.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from src.api import data_contract as _data_contract
from src.api.data_contract import normalize_source_overrides
from src.league_intel import overlay

REPO = Path(__file__).resolve().parents[2]

#: Assignment to the canonical value field OR one of its three proven-
#: identical aliases, in Python or JS. Widened 2026-08-20 (V1-53 /
#: C5-ROS-01): the scan below only ever matched ``rankDerivedValue``
#: itself, so an unapproved module assigning ``values["overall"]``,
#: ``["finalAdjusted"]`` or ``["displayValue"]`` directly — the exact
#: three fields ``test_the_aliases_are_intentional_and_pinned`` proves
#: equal ``rankDerivedValue`` on every row — passed this gate silently.
#: Measured: only ``src/api/data_contract.py`` (the approved producer)
#: assigns any of the three across every tracked production `.py`/`.js`/
#: `.jsx` file, so widening the pattern introduces no false positive.
_CANONICAL_WRITE = re.compile(
    r"""(
        \[\s*["']rankDerivedValue["']\s*\]\s*=(?!=)   # d["rankDerivedValue"] =
      | \.rankDerivedValue\s*=(?!=)                    # obj.rankDerivedValue =
      | \[\s*["']overall["']\s*\]\s*=(?!=)             # values["overall"] =        (alias)
      | \.overall\s*=(?!=)                              # obj.overall =              (alias)
      | \[\s*["']finalAdjusted["']\s*\]\s*=(?!=)       # values["finalAdjusted"] =  (alias)
      | \.finalAdjusted\s*=(?!=)                        # obj.finalAdjusted =        (alias)
      | \[\s*["']displayValue["']\s*\]\s*=(?!=)        # values["displayValue"] =   (alias)
      | \.displayValue\s*=(?!=)                         # obj.displayValue =         (alias)
      | \[\s*EXPERIMENTAL_VALUE_FIELD\s*\]\s*=(?!=)    # never canonical, see below
    )""",
    re.VERBOSE,
)

#: Modules permitted to assign the canonical value field, each with the
#: reason it is allowed. Anything else that starts assigning it is a new
#: canonical producer and must argue with this list.
APPROVED_CANONICAL_WRITERS = {
    "src/api/data_contract.py": (
        "THE canonical producer — _compute_unified_rankings and its passes"
    ),
    "src/league_intel/overlay.py": (
        "writes ONLY its private scratch list, which never leaves the "
        "function; the returned rows carry canonical untouched"
    ),
}


def _tracked(*suffixes: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p and p.endswith(suffixes)]


def _production_sources() -> list[str]:
    """Shipped code only. Tests assert on canonical values by
    construction, and audit-evidence scripts are frozen records."""
    skip = ("tests/", "docs/", "scripts/", "frontend/__tests__/")
    return [p for p in _tracked(".py", ".js", ".jsx") if not p.startswith(skip)]


#: Indirect construction of the canonical field — a dict-literal key
#: (``{"rankDerivedValue": v}``), which also covers ``dict.update({...})``
#: since that is a dict literal passed as an argument. Added 2026-08-22
#: (V1-53 / C5-ROS-01 residual): the assignment scan above only ever
#: matched ``[...] =`` / ``.field =`` syntax, so a dict built directly with
#: the canonical key — never *assigned into* an existing dict — passed the
#: gate above silently.
#:
#: Deliberately scoped to ``rankDerivedValue`` ONLY, not the three aliases,
#: for this dict-literal form. Measured before widening (the same
#: discipline the alias widening above used): the three alias words collide
#: with real, unrelated production dict keys — an "overall" stats-summary
#: key in ``src/scoring/backtest.py`` and a legitimately different-schema
#: "displayValue" field in ``src/trade/suggestions.py`` (verified sourced
#: from ``row["rankDerivedValue"]`` via ``PlayerAsset.display_value``, not
#: an independent computation — see that module's own docstring, W29-F001).
#: ``rankDerivedValue`` itself has no such collision: measured zero
#: unapproved production hits. A ``.update(field=value)`` keyword-argument
#: form is not separately matched — measured zero occurrences of that form
#: for any of the four names anywhere in the repository, so a dedicated
#: pattern would add regex risk (colliding with an ordinary keyword
#: argument or local variable named ``rankDerivedValue``) for no measured
#: benefit. Python-only: JS/JSX object literals commonly use unquoted keys,
#: a structurally worse collision surface, and the residual's own wording
#: ("dict literal", ``dict.update(...)``, ``setattr(...)``) is Python
#: vocabulary — a JS-side indirect-construction gap is a distinct,
#: out-of-scope residual for a future unit.
_CANONICAL_INDIRECT_DICT_WRITE = re.compile(r"""["']rankDerivedValue["']\s*:""")

#: Indirect construction via ``setattr``. Unlike the dict-literal form
#: above, this is safe to widen to all four names: measured zero
#: occurrences of ``setattr(..., "rankDerivedValue"/"overall"/
#: "finalAdjusted"/"displayValue", ...)`` anywhere in the repository, so
#: there is no false-positive collision to reason about.
_CANONICAL_SETATTR_WRITE = re.compile(
    r"""setattr\(\s*[^,]+,\s*["'](rankDerivedValue|overall|finalAdjusted|displayValue)["']\s*,"""
)

#: The one measured, verified-harmless occurrence of a dict-literal
#: ``rankDerivedValue`` key outside the approved producers: the example
#: request body in ``/api/trade/simulate-mc``'s docstring
#: (``server.py``, ``post_trade_simulate_mc``), not executable code. Keyed
#: by file with the exact expected count — not a blanket file exemption —
#: so a *second*, real hit in the same file still fails the scan below,
#: and so a future edit that removes or duplicates the example is caught
#: by ``test_the_doc_example_allowance_is_exact`` rather than silently
#: drifting stale.
_KNOWN_DOC_EXAMPLE_HITS = {"server.py": 1}


# ── A — only approved producers write canonical value ──────────────────


def test_only_approved_modules_assign_the_canonical_value_field():
    offenders: list[tuple[str, int]] = []
    for rel in _production_sources():
        if rel in APPROVED_CANONICAL_WRITERS:
            continue
        try:
            body = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = len(_CANONICAL_WRITE.findall(body))
        if hits:
            offenders.append((rel, hits))

    assert not offenders, (
        "a module outside the approved canonical producers assigns "
        "rankDerivedValue or one of its overall/finalAdjusted/displayValue "
        "aliases. Canonical value has one owner; an experimental, custom, "
        "page-local or seasonal-lane writer is how one player came to have "
        "two values:\n" + "\n".join(f"  {rel}: {n} assignment(s)" for rel, n in offenders)
    )


def test_the_writer_scan_is_not_vacuous():
    """If the regex stops matching, the guard above passes forever."""
    producer = (REPO / "src/api/data_contract.py").read_text(encoding="utf-8")
    assert _CANONICAL_WRITE.findall(producer), (
        "the canonical-write pattern no longer matches the canonical "
        "producer itself, so it would not catch anyone else either"
    )
    assert _CANONICAL_WRITE.findall('row["rankDerivedValue"] = 1')
    assert _CANONICAL_WRITE.findall("next.rankDerivedValue = scale(v, f)")
    # The three aliases must be caught exactly as the canonical field is.
    assert _CANONICAL_WRITE.findall('vals["overall"] = rdv')
    assert _CANONICAL_WRITE.findall('vals["finalAdjusted"] = rdv')
    assert _CANONICAL_WRITE.findall('vals["displayValue"] = rdv')
    assert _CANONICAL_WRITE.findall("row.displayValue = seasonal_value")
    # An equality comparison is not a write.
    assert not _CANONICAL_WRITE.findall('if row["rankDerivedValue"] == 1:')
    assert not _CANONICAL_WRITE.findall('if vals["overall"] == 1:')


def test_only_approved_modules_construct_the_canonical_value_field_indirectly():
    """V1-53 / C5-ROS-01 residual — the assignment scan above cannot see a
    dict built directly with the canonical key, or a ``setattr`` call.
    Same producer allowlist as the assignment scan; the one documented,
    verified-harmless doc-example occurrence is subtracted by count, not by
    a blanket per-file exemption.
    """
    offenders: list[tuple[str, int]] = []
    for rel in _production_sources():
        if rel in APPROVED_CANONICAL_WRITERS:
            continue
        try:
            body = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = len(_CANONICAL_SETATTR_WRITE.findall(body))
        if rel.endswith(".py"):
            hits += len(_CANONICAL_INDIRECT_DICT_WRITE.findall(body))
        hits -= _KNOWN_DOC_EXAMPLE_HITS.get(rel, 0)
        if hits > 0:
            offenders.append((rel, hits))

    assert not offenders, (
        "a module outside the approved canonical producers constructs "
        "rankDerivedValue (or an alias, via setattr) indirectly — a dict "
        "literal, dict.update({...}), or setattr(). This is the same "
        "single-owner violation the assignment scan above catches, just "
        "via a syntax it cannot see:\n"
        + "\n".join(f"  {rel}: {n} occurrence(s)" for rel, n in offenders)
    )


def test_the_indirect_write_scan_is_not_vacuous():
    """Pins both what the new patterns catch and, just as important, the
    deliberate alias exclusion on the dict-literal form — so that scope
    decision is a verified fact, not an unchecked comment."""
    assert _CANONICAL_INDIRECT_DICT_WRITE.findall('{"rankDerivedValue": v}')
    assert _CANONICAL_INDIRECT_DICT_WRITE.findall('d.update({"rankDerivedValue": v})')
    # The three aliases are deliberately NOT covered by the dict-literal
    # form (see the comment above the pattern) — pin the exclusion itself.
    assert not _CANONICAL_INDIRECT_DICT_WRITE.findall('{"overall": v}')
    assert not _CANONICAL_INDIRECT_DICT_WRITE.findall('{"finalAdjusted": v}')
    assert not _CANONICAL_INDIRECT_DICT_WRITE.findall('{"displayValue": v}')

    assert _CANONICAL_SETATTR_WRITE.findall('setattr(row, "rankDerivedValue", v)')
    assert _CANONICAL_SETATTR_WRITE.findall('setattr(row, "overall", v)')
    assert _CANONICAL_SETATTR_WRITE.findall('setattr(row, "finalAdjusted", v)')
    assert _CANONICAL_SETATTR_WRITE.findall('setattr(row, "displayValue", v)')
    # A setattr writing an unrelated field is not a canonical write.
    assert not _CANONICAL_SETATTR_WRITE.findall('setattr(row, "boardRank", v)')


def test_the_doc_example_allowance_is_exact():
    """The allowance is a documented, counted exception, not a blanket
    exemption — if the docstring example changes shape, this must be
    updated deliberately rather than the guard silently drifting."""
    for rel, expected in _KNOWN_DOC_EXAMPLE_HITS.items():
        body = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        actual = len(_CANONICAL_INDIRECT_DICT_WRITE.findall(body))
        assert actual == expected, (
            f"{rel}: expected exactly {expected} known doc-example "
            f"occurrence(s) of a rankDerivedValue dict-literal key, found "
            f"{actual}. If this changed because the example was edited, "
            f"update _KNOWN_DOC_EXAMPLE_HITS; if it changed because a new, "
            f"real indirect write was added, that is the violation this "
            f"guard exists to catch."
        )


def test_no_seasonal_lane_module_assigns_a_canonical_alias():
    """V1-53 / C5-ROS-01 — the redraft/ROS seasonal lane must never write
    canonical dynasty value, and that includes the three aliases the write
    scan above widened to cover, not only ``rankDerivedValue`` by name.

    ``tests/ros/test_isolation.py`` already proves the seasonal lane cannot
    mutate ``_RANKING_SOURCES``/etc. by import side effect. This is the
    complementary direction: a direct write to the canonical field or an
    alias from inside the lane itself. Scoped narrowly to ``src/ros/``
    (plus its API surface) rather than repeating the whole-repo scan, so a
    failure here names the seasonal lane specifically rather than pointing
    back at the same generic assertion.
    """
    offenders: list[tuple[str, int]] = []
    for rel in _production_sources():
        if not rel.startswith("src/ros/"):
            continue
        body = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        hits = len(_CANONICAL_WRITE.findall(body))
        if hits:
            offenders.append((rel, hits))
    assert not offenders, (
        f"seasonal (redraft/ROS) module(s) assign canonical dynasty value or "
        f"an alias, breaching the source-domain boundary "
        f"(docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md §3): {offenders}"
    )


def test_no_seasonal_lane_module_constructs_a_canonical_alias_indirectly():
    """The indirect-construction complement of the test above — same
    reasoning, same scope, the dict-literal/setattr forms instead of
    assignment. Measured zero hits in ``src/ros/`` today; this closes the
    gap before it can be exploited, not after."""
    offenders: list[tuple[str, int]] = []
    for rel in _production_sources():
        if not rel.startswith("src/ros/"):
            continue
        body = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        hits = len(_CANONICAL_SETATTR_WRITE.findall(body))
        if rel.endswith(".py"):
            hits += len(_CANONICAL_INDIRECT_DICT_WRITE.findall(body))
        if hits:
            offenders.append((rel, hits))
    assert not offenders, (
        f"seasonal (redraft/ROS) module(s) construct canonical dynasty "
        f"value or an alias indirectly, breaching the source-domain "
        f"boundary (docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md §3): {offenders}"
    )


def test_the_approved_list_names_its_reasons():
    """An allowlist without reasons becomes a place to hide things."""
    for path, reason in APPROVED_CANONICAL_WRITERS.items():
        assert (REPO / path).is_file(), f"{path} no longer exists; prune the allowlist"
        assert len(reason) > 30, f"{path} is allowed without a real justification"


# ── C — user source weighting cannot write canonical value ─────────────


def test_posted_source_weights_are_ignored_by_the_authority():
    """Custom Mix is withdrawn at the server, not in the client.

    The client no longer sends a mix, but a stale bundle or a direct
    caller still can — and a user-weighted board returned under
    ``rankDerivedValue`` is a second canonical truth however it was
    requested.
    """
    out, warnings = normalize_source_overrides(
        {"ktcSfTep": {"include": False}, "dlfSf": {"weight": 4.0}}
    )
    assert out == {}, "posted source weights still reach the canonical pipeline"
    assert any("disabled" in w for w in warnings)


def test_the_withdrawal_is_a_declared_constant_not_an_accident():
    assert _data_contract._SOURCE_OVERRIDES_DISABLED is True


# ── D — device-local settings cannot change canonical value ────────────

#: Every legacy client shape a real browser could still be carrying.
#: Named for the settings blob they have in localStorage today.
LEGACY_CLIENTS = {
    "A: old market": {"valuationMode": "market"},
    "B: old league-adjusted": {"valuationMode": "leagueAdjusted"},
    "C: custom source mix": {"ktcSfTep": {"include": False}, "dlfSf": {"weight": 4.0}},
    "D: manual TEP": {"tep_multiplier": 1.45},
    "E: manual native TEP": {"tep_native_multiplier": 1.4},
    "F: fresh client": {},
}


@pytest.mark.parametrize("label", sorted(LEGACY_CLIENTS))
def test_no_legacy_client_can_obtain_a_different_board(label):
    """The six-client matrix, at the authority.

    Same league, same snapshot: every one of these bodies must produce
    the same canonical inputs, so no user has to clear localStorage to
    see the right number.
    """
    body = LEGACY_CLIENTS[label]
    overrides, _ = normalize_source_overrides(body)
    assert overrides == {}, (
        f"legacy client {label!r} still reprices the board through custom " "source weights"
    )


def test_a_manual_tep_multiplier_cannot_ride_the_override_path():
    """``tepMultiplier`` / ``tepNativeMultiplier`` are the same defect
    class as ``siteWeights`` — device-local, never synced, and they rode
    the identical endpoint.

    ``normalize_tep_multiplier`` still PARSES the field (it is retained
    for when Custom Mix returns), so the guarantee is that no override
    survives ``normalize_source_overrides`` to reach the blend.
    """
    body = {"tep_multiplier": 1.45, "ktcSfTep": {"weight": 0.0}}
    overrides, warnings = normalize_source_overrides(body)
    assert overrides == {}
    assert warnings, "the caller is not told its override was ignored"


def test_the_client_cannot_select_a_methodology():
    src = (REPO / "frontend/lib/valuation-mode.js").read_text(encoding="utf-8")
    body = src.split("export function readValuationMode()", 1)[-1].split("\n}", 1)[0]
    assert "localStorage" not in body


# ── E — canonical aliases stay coherent ────────────────────────────────

#: Measured on the live contract: ``values.overall`` /
#: ``values.finalAdjusted`` / ``values.displayValue`` equal
#: ``rankDerivedValue`` on all 1,092 rows. ``values.rawComposite`` differs
#: on 1,080 — it is the legacy scraper composite and is honestly named.
CANONICAL_ALIASES = ("overall", "finalAdjusted", "displayValue")


def test_the_aliases_are_intentional_and_pinned():
    """The server overlay used to scale ``rankDerivedValue`` and leave
    ``values.*`` at market, publishing a row that disagreed with itself.
    That is why this equality is asserted rather than assumed."""
    capture = REPO / "docs/master-site-audit/evidence/W06/contract-full.json"
    if not capture.exists():
        pytest.skip("no full-contract capture in this environment")
    import json

    rows = json.loads(capture.read_text(encoding="utf-8")).get("playersArray") or []
    assert len(rows) > 500, f"capture too small to be meaningful ({len(rows)})"

    disagreements = []
    for row in rows:
        canonical = row.get("rankDerivedValue")
        values = row.get("values") or {}
        for alias in CANONICAL_ALIASES:
            if alias in values and values[alias] != canonical:
                disagreements.append((row.get("displayName"), alias, values[alias], canonical))
    assert not disagreements, (
        f"{len(disagreements)} canonical alias disagreements, e.g. "
        f"{disagreements[:5]} — one row cannot carry two canonical numbers"
    )


def test_the_overlay_declares_which_fields_are_canonical():
    """So a future edit has to go through a named set rather than
    remembering which of four spellings mattered."""
    assert "rankDerivedValue" in overlay.CANONICAL_VALUE_FIELDS
    for alias in CANONICAL_ALIASES:
        assert (
            alias in overlay.CANONICAL_VALUE_FIELDS
        ), f"{alias} is a canonical alias but is not declared as one"


# ── G — canonical history records canonical output only ────────────────


def test_the_history_writer_records_the_canonical_field():
    """``board_history`` is the evidence a future methodology decision
    will rest on. An experimental or custom value written into it would
    corrupt that evidence silently and permanently."""
    src = (REPO / "src/snapshots/board_store.py").read_text(encoding="utf-8")
    assert "rank_derived_value" in src
    assert (
        overlay.EXPERIMENTAL_VALUE_FIELD not in src
    ), "the canonical history writer references the experimental field"


def test_the_history_writer_is_not_on_the_override_path():
    """Custom Mix never reached history, and must not start to."""
    server_src = (REPO / "server.py").read_text(encoding="utf-8")
    handler = server_src.split("async def post_rankings_overrides", 1)
    if len(handler) < 2:
        pytest.skip("override handler not found by name")
    body = handler[1].split("\n@app.", 1)[0]
    for writer in ("append_snapshot", "write_board"):
        assert writer not in body, (
            f"{writer} is called from the override handler; a custom board "
            "would be recorded as canonical history"
        )


# ── H — canonical API projections preserve the value ───────────────────


def test_the_public_projection_does_not_substitute_another_value():
    """``public_contract`` is the one place canonical value crosses into
    an anonymous surface. It may redact; it may not re-price."""
    src = (REPO / "src/public_league/public_contract.py").read_text(encoding="utf-8")
    assert overlay.EXPERIMENTAL_VALUE_FIELD not in src
    assert not _CANONICAL_WRITE.findall(src), (
        "the public projection assigns rankDerivedValue — a projection "
        "layer must pass the authoritative value through, not compute one"
    )


def test_the_experimental_field_never_appears_in_a_canonical_consumer():
    """The experimental board is diagnostic. If an engine starts reading
    it, the rejected methodology is back in production under a new name.
    """
    engines = [
        "src/trade/suggestions.py",
        "src/trade/finder.py",
        "src/trade/angle.py",
        "src/trade/waiver.py",
        "src/trade/faab_engine.py",
        "src/api/terminal.py",
        "src/api/trade_simulator.py",
    ]
    offenders = []
    for rel in engines:
        path = REPO / rel
        if not path.is_file():
            continue
        if overlay.EXPERIMENTAL_VALUE_FIELD in path.read_text(encoding="utf-8"):
            offenders.append(rel)
    assert not offenders, (
        f"engines read the experimental league-adjusted value: {offenders}. "
        "That methodology was rejected for canonical promotion; consuming it "
        "in an engine reinstates it under a different field name."
    )
