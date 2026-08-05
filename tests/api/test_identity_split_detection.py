"""The board's identity detectors, and the class they could not see.

Two real players occupy two board rows each — a resolved row carrying a
Sleeper id and an unresolved ghost carrying the other spelling — because
the merge key is a canonical NAME and the alias table knows neither
"Matt"↔"Matthew" nor "Jam"↔"Jamarion".  Vendor votes land on whichever
spelling that vendor used, so the priced row blends 8 of the 11 votes
the pipeline actually loaded for Hibner (audit W06-F001).

Neither detector on the contract could fire.  Check 0 keys on exact
``<name>::<position_group>`` equality, and a split exists precisely
because the two keys differ.  The near-name rule that would have seen it
was retired for false positives and replaced with a literal
``"nearNameMismatchCount": 0`` — so ``scripts/audit_identity.py``
printed "(none)" on a board that demonstrably carried a split, and the
wrong value shipped with a "validated" stamp (W06-F002).

These tests pin the replacement predicate: same surname, near-identical
first name, exactly one side unresolved.  Detection only — merging two
rows on a name similarity is the failure mode this pipeline refuses.
"""

from __future__ import annotations

from src.api.data_contract import _validate_and_quarantine_rows


def _row(name, position="TE", *, player_id=None, sources=None, asset_class="offense"):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": asset_class,
        "playerId": player_id,
        "canonicalSiteValues": dict(sources or {}),
        "anomalyFlags": [],
        "confidenceBucket": "medium",
        "confidenceLabel": "",
        "rankDerivedValue": 1737,
    }


def test_the_hibner_split_is_detected():
    rows = [
        _row(
            "Matt Hibner",
            player_id="13324",
            sources={"ktcSfTep": 1458, "idpTradeCalc": 1129},
        ),
        _row(
            "Matthew Hibner",
            player_id=None,
            sources={"ktcSfTep": 1458, "dlfSf": 250, "flockFantasySf": 383, "draftSharks": 400},
        ),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 1
    pair = summary["nearNameMismatches"][0]
    assert pair["resolvedName"] == "Matt Hibner"
    assert pair["resolvedPlayerId"] == "13324"
    assert pair["unresolvedName"] == "Matthew Hibner"
    # The actual harm: the votes stranded on the ghost row.
    assert pair["sourcesOnlyOnUnresolved"] == ["dlfSf", "draftSharks", "flockFantasySf"]
    for row in rows:
        assert "near_name_identity_split" in row["anomalyFlags"]


def test_a_truncated_first_name_is_detected_below_the_similarity_floor():
    """"jam miller" vs "jamarion miller" scores 0.80 — under the 0.85
    floor.  The strict-prefix clause is what catches it."""
    rows = [
        _row("Jam Miller", "RB", player_id="13403"),
        _row("Jamarion Miller", "RB", player_id=None),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 1
    assert summary["nearNameMismatches"][0]["firstNamePrefix"] is True
    assert summary["nearNameMismatches"][0]["similarity"] < 0.85


def test_two_resolved_rows_are_two_people():
    """Sleeper's directory gave each of these a DIFFERENT id, which
    settles it — near names are not evidence against a stable id."""
    rows = [
        _row("Kenneth Walker", "RB", player_id="8151"),
        _row("Kenny Walker", "RB", player_id="9999"),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 0


def test_two_unresolved_rows_are_not_evidence():
    rows = [
        _row("Matt Hibner", player_id=None),
        _row("Matthew Hibner", player_id=None),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 0


def test_a_shared_surname_alone_does_not_fire():
    """The retired rule flagged 40+ of these a build.  Bijan Robinson and
    Chop Robinson are two people and always were."""
    rows = [
        _row("Bijan Robinson", "RB", player_id="9509"),
        _row("Chop Robinson", "DL", player_id=None, asset_class="idp"),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 0
    for row in rows:
        assert "near_name_identity_split" not in row["anomalyFlags"]


def test_a_different_surname_never_fires():
    rows = [
        _row("Tevin Coleman", "RB", player_id="2216"),
        _row("Kevin Colemann", "WR", player_id=None),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 0


def test_picks_are_out_of_scope():
    """"2026 Pick 1.02" and "2027 Pick 1.02" share a surname token and
    carry no playerId by design."""
    rows = [
        {**_row("2026 Pick 1.02", "PICK", asset_class="pick"), "playerId": "x"},
        _row("2027 Pick 1.02", "PICK", asset_class="pick"),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["nearNameMismatchCount"] == 0


def test_two_rows_on_one_stable_id_are_a_duplicate_and_are_quarantined():
    """Zero on today's board — pinned because nothing was watching the
    ID key at all.  Unlike a name match this is not a judgement call."""
    rows = [
        _row("A.J. Brown", "WR", player_id="5859"),
        _row("AJ Brown", "WR", player_id="5859"),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["duplicateSleeperIdCount"] == 1
    assert summary["duplicateSleeperIdPairs"][0]["playerId"] == "5859"
    for row in rows:
        assert "duplicate_sleeper_id" in row["anomalyFlags"]
        assert row["quarantined"] is True


def test_distinct_ids_are_not_duplicates():
    rows = [
        _row("A.J. Brown", "WR", player_id="5859"),
        _row("Marquise Brown", "WR", player_id="6794"),
    ]
    summary = _validate_and_quarantine_rows(rows)
    assert summary["duplicateSleeperIdCount"] == 0
