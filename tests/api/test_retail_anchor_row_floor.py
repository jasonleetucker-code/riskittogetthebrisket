"""The offense retail anchor must be watched by the row-count floors.

AUDIT FINDING F-10 (2026-08-18)
───────────────────────────────
``ktcSfTep`` is the board's single most load-bearing offense input:

* the only ``is_retail`` source in ``_RANKING_SOURCES``;
* the TE basis the whole board is anchored on (ADR-015 — every non-TEP
  TE row is *converted onto* it);
* half the pick anchor set (``pick_anchor = cross_market | {"ktcSfTep"}``);
* the head of the ``ktc`` correlation group.

Nothing watched it.  Measured on the 2026-08-18 board, with KTC's TE++
sub-board removed entirely and the base ``ktc`` CSV left intact — the
exact shape of the failure ``_ktc_extract_tep``'s own docstring records
("later code crashed on ``int(float({}))`` and silently skipped —
leaving ktcSfTep.csv empty"):

* ``validate_api_data_contract`` → ``ok=True``, ``status=degraded``,
  ``sourceHealthErrors=[]``;
* ``coverageAudit.offense`` → ``deficitPlayers=0``, ``missingBySite={}``,
  because ``expectedSites.offense`` names ``ktc`` — the display-only CSV
  that is deliberately NOT a blend voter (see ``_RANKING_SOURCES``);
* **444 of 468** comparable offense rows moved, median |Δ| 804,
  p90 3907, max 8405 (Joe Royer 1592 → 9997).

Both CI lanes passed and Deploy Production would have shipped it.  The
one thing that reddened the live-board mutation was an *incidental*
structural error — ``confidence_basis_contradicts_value:Travis Hunter``,
collateral of the two-way boost losing its offense input.  Removing that
one player from the same mutant restored ``ok=True``.  A coincidence is
not a guard.

IS THIS AN OBSERVED PRODUCTION INCIDENT?  NO — AND SAY SO
─────────────────────────────────────────────────────────
Scanned every committed export archive in the window: exactly one
carries zero ``ktcSfTep`` rows (``dynasty_export_20260816_190904``), and
that one was a **whole-KTC timeout** (``sourceRunSummary.timedOut:
["KTC"]``, ``sites`` playerCount 0), which the existing guards DID catch
— ``coverageAudit.offense`` reported ``deficitPlayers=300``.  It is the
2026-08-16 incident, not this one.

So F-10 is a **latent** hole, not a shipped board.  The asymmetric
failure it guards (base KTC fine, TE++ board gone) is documented in
``_ktc_extract_tep`` as having happened before this archive window, and
its blast radius is measured above — but no committed archive shows a
board published in that state, and this module must not be cited as
though one does.

WHY A FLOOR IS THE RIGHT REPAIR HERE
────────────────────────────────────
``source_missing:<key>`` is already a ``_SOURCE_HEALTH_ERROR_KINDS``
prefix, so a floor puts the condition in the *correct lane*: an upstream
provider returning less data blocks the deploy (FULL lane) without
turning every open PR red (structural lane).  That is the lane split
``docs/ops/STABILIZATION_2026-08-16.md`` established, used as designed.

The floor value is not invented: ``_DEFAULT_SOURCE_ROW_FLOORS``'s own
stated policy is "~80% of the current live baseline", the live baseline
is 501 rows, and 400 is both ~80% of it and the floor already carried by
``ktc`` — the twin board produced from the same KTC API payload with an
identical 501-row count.

WHAT THIS DOES **NOT** CLOSE
────────────────────────────
The scrape-promotion gate ``server.py::_missing_expected_sites`` still
watches ``ktc``, because ``ktcSfTep`` never reaches ``raw.sites`` at all:
``KTC_TEP`` is a sub-product held in ``FULL_DATA``, not a member of
``active_sites``, so ``sites_meta`` never emits it and ``_reported_rows``
could not find it.  That is census item S-2 (scraper-run names do not
round-trip onto registry keys, and a run-level "complete" does not
decompose into which boards arrived) and is tracked there, measured.
"""

from __future__ import annotations

import pytest

from src.api.data_contract import (
    _DEFAULT_SOURCE_ROW_FLOORS,
    _RANKING_SOURCES,
    _is_source_health_error,
    _load_source_row_floors,
    get_ranking_source_keys,
    validate_api_data_contract,
)

#: The board key this module exists to protect.  Read from the registry
#: rather than hardcoded, so renaming the retail source cannot leave this
#: test silently guarding a key that no longer exists.
_RETAIL_KEYS = tuple(
    str(s["key"]) for s in _RANKING_SOURCES if isinstance(s, dict) and s.get("is_retail")
)


def _contract_payload(*, retail_rows: int, total: int = 300) -> dict:
    """A schema-complete contract payload carrying ``retail_rows`` retail values.

    Synthetic on purpose (§3d): this is a statement about our code and
    must be provable with no live board, no scrape state and no network.

    Shape-complete deliberately.  ``validate_api_data_contract`` caps
    ``errors`` at 200, and a payload missing per-row keys floods that cap
    with schema noise before the source-health block is reached — which
    would make this test pass or fail on list truncation rather than on
    the condition it is asserting.
    """
    rows = []
    for i in range(total):
        sites = {"ktc": 5000 - i, "idpTradeCalc": 5000 - i}
        if i < retail_rows:
            for key in _RETAIL_KEYS:
                sites[key] = 5000 - i
        rows.append(
            {
                "displayName": f"P{i}",
                "canonicalName": f"p{i}",
                "playerId": str(1000 + i),
                "position": "WR",
                "team": "FA",
                "age": 25,
                "rookie": False,
                "sourceCount": 2,
                "confidenceBucket": "medium",
                "anomalyFlags": [],
                "values": {"rankDerivedValue": 5000 - i},
                "canonicalSiteValues": sites,
            }
        )
    return {
        "contractVersion": "2026-03-10.v2",
        "generatedAt": "2026-08-18T00:00:00+00:00",
        "maxValues": {"ktc": 9999, "ktcSfTep": 9999, "idpTradeCalc": 9999},
        "players": {r["displayName"]: {} for r in rows},
        "valueAuthority": {},
        "playersArray": rows,
        "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
    }


def _source_errors(payload: dict) -> list[str]:
    """Read the SOURCE-HEALTH LANE, not the flat ``errors`` list.

    The lane field is what CI actually routes on
    (``scripts/validate_api_contract.py --lane structural|full``), and it
    is the honest place to assert: an upstream provider returning less
    data is a source-health condition by definition.
    """
    health = validate_api_data_contract(payload)
    lane = health.get("sourceHealthErrors")
    if lane is None:  # older payload shape — fall back, still lane-filtered
        lane = [e for e in (health.get("errors") or []) if _is_source_health_error(e)]
    return list(lane)


def test_registry_still_has_exactly_one_retail_offense_source() -> None:
    """The premise of this module: one retail anchor, and it is KTC TE++.

    If a second retail source is registered, the floors below stop being
    the whole story and this module must be revisited rather than kept
    passing on a stale assumption.
    """
    assert _RETAIL_KEYS == ("ktcSfTep",), _RETAIL_KEYS


def test_every_retail_source_carries_a_row_floor() -> None:
    """Structural: a source the blend cannot function without must have a floor.

    ``source_missing`` is only ever emitted for keys present in the
    floors mapping, so a source with no floor can fall to zero rows in
    total silence.
    """
    floors = _load_source_row_floors()
    missing = [k for k in _RETAIL_KEYS if k not in floors]
    assert not missing, f"retail source(s) with no row floor: {missing}"


def test_retail_floor_is_not_weaker_than_its_twin_board() -> None:
    """``ktc`` and ``ktcSfTep`` are produced from ONE KTC API payload and
    carry identical row counts (501/501 on 2026-08-18).  The voting board
    must not be guarded more loosely than the display-only one.
    """
    floors = _load_source_row_floors()
    assert floors.get("ktcSfTep", 0) >= floors["ktc"]


def test_losing_the_retail_board_is_a_source_health_error() -> None:
    """The behavioural half: zero retail rows must be reported, in the
    source-health lane, with the retail key named."""
    errors = _source_errors(_contract_payload(retail_rows=0))
    assert f"source_missing:{_RETAIL_KEYS[0]}" in errors, errors


def test_a_populated_retail_board_reports_nothing() -> None:
    """The guard must not fire on a healthy board — otherwise it is noise
    and would be tuned back out."""
    payload = _contract_payload(retail_rows=300)
    errors = [e for e in _source_errors(payload) if _RETAIL_KEYS[0] in e]
    assert errors == [], errors


@pytest.mark.parametrize("retail_rows", [1, 100, 399])
def test_a_depleted_retail_board_is_reported_below_floor(retail_rows: int) -> None:
    """Between "gone" and "healthy" there is "partially arrived", and it
    must not read as healthy.  A warning rather than an error is correct
    here: a thinner board is a degradation, not an absence."""
    health = validate_api_data_contract(_contract_payload(retail_rows=retail_rows))
    warnings = [w for w in (health.get("warnings") or []) if _RETAIL_KEYS[0] in w]
    assert warnings, (health.get("warnings"), health.get("errors"))


def test_default_floors_carry_the_retail_key_not_only_the_json_override() -> None:
    """The floor must live in the CODE default, not only in
    ``config/weights/source_row_floors.json``.

    The JSON is the operator-tunable layer merged ON TOP of
    ``_DEFAULT_SOURCE_ROW_FLOORS``; a deployment whose JSON is absent,
    truncated or reverted must still watch the retail anchor.
    """
    for key in _RETAIL_KEYS:
        assert key in _DEFAULT_SOURCE_ROW_FLOORS


# ── The scraper half ────────────────────────────────────────────────────
#
# A contract floor only reports a board that already arrived empty.  The
# scraper floor is what stops the empty board OVERWRITING last-good in
# the first place, and the two are independent: defining the constant
# without wiring it into ``_site_raw_floors`` would leave the guard inert
# while every constant-reading test still passed.  So this reads the
# WIRING, from the AST, not from a comment or a name.


def _site_raw_floor_keys() -> set[str]:
    """Keys actually present in ``Dynasty Scraper.py``'s ``_site_raw_floors``.

    Parsed statically — the scraper does import-time work and needs
    network libraries, so it cannot be imported in the hard gate.
    """
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[2] / "Dynasty Scraper.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "_site_raw_floors" not in targets or not isinstance(node.value, ast.Dict):
            continue
        return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError("_site_raw_floors dict literal not found in Dynasty Scraper.py")


def test_retail_board_is_wired_into_the_scraper_site_raw_floors() -> None:
    """Defining the constant is not the guard; using it is."""
    keys = _site_raw_floor_keys()
    missing = [k for k in _RETAIL_KEYS if k not in keys]
    assert not missing, (
        f"retail source(s) absent from Dynasty Scraper.py::_site_raw_floors: "
        f"{missing} — a degraded board would overwrite last-good. Present: {sorted(keys)}"
    )


def test_the_twin_board_is_wired_too() -> None:
    """``ktc`` and ``ktcSfTep`` come from ONE KTC response; guarding only
    one of them lets the other overwrite last-good on the same failure."""
    keys = _site_raw_floor_keys()
    assert {"ktc", "ktcSfTep"} <= keys, sorted(keys)


# ── The premium-tier half ───────────────────────────────────────────────
#
# A row floor catches TOTAL loss.  It does not catch a board that still
# returns 480 rows but has stopped covering the top of the market — which
# is the failure ``config/weights/top50_coverage_floors.json`` exists for,
# and which matters more for the retail anchor than for anything else,
# because the whole board's TE basis and half its pick anchor set are
# read off it.  That map watched ``ktc`` and not ``ktcSfTep`` too.


def _top50_floors() -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "config/weights/top50_coverage_floors.json"
    return json.loads(path.read_text())


def test_retail_source_has_a_top50_offense_coverage_floor() -> None:
    floors = _top50_floors().get("offense") or {}
    missing = [k for k in _RETAIL_KEYS if k not in floors]
    assert not missing, f"retail source(s) with no top-50 offense floor: {missing}"


def test_retail_top50_floor_matches_its_twin() -> None:
    """Live top-50 offense coverage is 50/50 for both KTC boards, so the
    voting board must not be held to a looser premium-tier bar than the
    non-voting one."""
    floors = _top50_floors().get("offense") or {}
    assert floors.get("ktcSfTep", 0) >= floors["ktc"]


# ── The scrape-promotion anchor ─────────────────────────────────────────
#
# A CORRECTION TO THIS MODULE'S OWN F-10 RECORD.
#
# The original note said the scrape-promotion gate could not be repaired
# here: that ``ktcSfTep`` never reaches ``raw.sites``, so
# ``server.py::_missing_expected_sites`` could not resolve it if
# ``coverageAudit.expectedSites.offense`` named it.  The first clause is
# true; the conclusion was wrong.  That function reads ``siteStats`` as
# well as ``sites`` (``server.py:1179-1182``), and ``siteStats`` carries
# ``ktcSfTep`` with a real count — 644 on the 2026-08-18 board.
#
# So the anchor now names the board that actually votes, and the claim
# that it could not is retracted rather than left standing.
#
# Measured inert: replayed over all 176 committed export archives,
# ``["ktc"]`` and ``["ktcSfTep"]`` block the IDENTICAL 4 archives — the
# same set, not merely the same count.  Both CSVs come from one KTC API
# response, so they fail together; the anchors diverge only when the TE++
# extraction breaks on its own, which is exactly the case the old anchor
# missed.


def _scraper_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / "Dynasty Scraper.py").read_text()


def test_the_offense_anchor_names_a_voting_source() -> None:
    """The anchor must watch a board the blend actually depends on.

    Stated as a property — "is a registered voter" — rather than as the
    literal string, so promoting a different retail source keeps the guard
    meaningful instead of pinning a name.
    """
    import ast

    tree = ast.parse(_scraper_source())
    keys = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOP_OFF_EXPECTED_SITE_KEYS" for t in node.targets
        ):
            keys = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    assert keys, "TOP_OFF_EXPECTED_SITE_KEYS not found"

    registered = set(get_ranking_source_keys())
    non_voters = [k for k in keys if k not in registered]
    assert not non_voters, (
        f"the offense anchor watches non-voting source(s) {non_voters}; "
        f"registered voters include {sorted(_RETAIL_KEYS)}"
    )


def test_the_offense_anchor_stays_one_wide() -> None:
    """It is an ANCHOR-LOSS detector, not the health population — S-1 pinned
    that distinction and widening it here would quietly undo it."""
    import ast

    tree = ast.parse(_scraper_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOP_OFF_EXPECTED_SITE_KEYS" for t in node.targets
        ):
            assert len(node.value.elts) == 1, ast.dump(node.value)
