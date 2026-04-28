"""Tests for identity validation, quarantine, and contamination detection.

Covers:
  - Offense-to-IDP contamination (offense player with only IDP source values)
  - IDP-to-offense contamination (IDP player with only offense source values)
  - Cross-universe normalized-name collisions
  - Near-name value mismatches
  - Unsupported position detection
  - No-source-value orphan detection
  - Quarantine degradation (confidence bucket downgrade)
  - Identity confidence scoring
  - Validation summary in contract payload
"""
from __future__ import annotations

import unittest

from src.api.data_contract import (
    _compute_identity_confidence,
    _validate_and_quarantine_rows,
    _normalize_for_collision,
    build_api_data_contract,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_player(name, position, *, ktc=None, idp=None, team="TST",
                 sleeper_id=None):
    """Build a minimal raw player dict for contract builder tests."""
    sites = {}
    if ktc is not None:
        # Standard ``ktc`` was retired from the blend 2026-04-28;
        # ``ktcSfTep`` is the canonical KTC offense source.  The
        # ``ktc`` parameter name preserved for fixture ergonomics.
        sites["ktcSfTep"] = ktc
    if idp is not None:
        sites["idpTradeCalc"] = idp
    p = {
        "_composite": max(ktc or 0, idp or 0),
        "_rawComposite": max(ktc or 0, idp or 0),
        "_finalAdjusted": max(ktc or 0, idp or 0),
        "_sites": (1 if ktc else 0) + (1 if idp else 0),
        "position": position,
        "team": team,
        "_canonicalSiteValues": sites,
    }
    if sleeper_id:
        p["_sleeperId"] = sleeper_id
    return {name: p}


def _payload_with_players(*player_dicts):
    players = {}
    positions = {}
    for d in player_dicts:
        for name, pdata in d.items():
            players[name] = pdata
            positions[name] = pdata["position"]
    return {
        "players": players,
        "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktcSfTep": 9999},
        "sleeper": {"positions": positions},
    }


def _build_and_find(payload, player_name):
    contract = build_api_data_contract(payload)
    for row in contract["playersArray"]:
        if row["canonicalName"] == player_name:
            return row, contract
    return None, contract


# ── Offense-to-IDP contamination ────────────────────────────────────────────

class TestOffenseToIdpContamination(unittest.TestCase):
    """An offense-position player with only IDP source values should be flagged."""

    def test_offense_player_with_only_idp_values_gets_flagged(self):
        # WR with only idpTradeCalc value — classic contamination
        payload = _payload_with_players(
            _make_player("Zzz Fake WR Contaminated", "WR", idp=5000),
        )
        row, _ = _build_and_find(payload, "Zzz Fake WR Contaminated")
        self.assertIsNotNone(row)
        flags = row.get("anomalyFlags") or []
        self.assertIn("position_source_contradiction", flags)
        self.assertTrue(row.get("quarantined"))

    def test_offense_player_with_offense_values_not_flagged(self):
        payload = _payload_with_players(
            _make_player("Zzz Clean Offense QB", "QB", ktc=9000),
        )
        row, _ = _build_and_find(payload, "Zzz Clean Offense QB")
        self.assertIsNotNone(row)
        flags = row.get("anomalyFlags") or []
        self.assertNotIn("position_source_contradiction", flags)
        self.assertFalse(row.get("quarantined"))


# ── IDP-to-offense contamination ────────────────────────────────────────────

class TestIdpToOffenseContamination(unittest.TestCase):
    """An IDP-position player with only offense source values should be flagged."""

    def test_idp_player_with_only_offense_values_gets_flagged(self):
        payload = _payload_with_players(
            _make_player("Zzz Fake LB Contaminated", "LB", ktc=4000),
        )
        row, _ = _build_and_find(payload, "Zzz Fake LB Contaminated")
        self.assertIsNotNone(row)
        flags = row.get("anomalyFlags") or []
        self.assertIn("position_source_contradiction", flags)
        self.assertTrue(row.get("quarantined"))

    def test_idp_player_with_idp_values_not_flagged(self):
        payload = _payload_with_players(
            _make_player("Zzz Clean IDP LB", "LB", idp=6000),
        )
        row, _ = _build_and_find(payload, "Zzz Clean IDP LB")
        self.assertIsNotNone(row)
        flags = row.get("anomalyFlags") or []
        self.assertNotIn("position_source_contradiction", flags)


# ── Cross-universe name collisions ──────────────────────────────────────────

class TestCrossUniverseCollision(unittest.TestCase):
    """Same name appearing in both offense and IDP should be flagged."""

    def test_same_name_offense_and_idp_both_flagged(self):
        # Two players with the same name but different positions
        payload = _payload_with_players(
            _make_player("Zzz James Williams", "WR", ktc=7000),
            _make_player("Zzz James Williams", "LB", idp=3000),
        )
        # dict keys collide → only one survives in players dict.
        # But if the scraper produces different entries, they'd have
        # different canonical names.  Test the validation function directly.
        pass

    def test_collision_detection_via_validation_function(self):
        """Directly test _validate_and_quarantine_rows with crafted rows.

        Two distinct people sharing a normalized name across the
        offense/IDP universes are surfaced via
        ``name_collision_cross_universe`` for visibility, but they are
        NOT auto-quarantined — they are usually two genuinely different
        people (e.g. a journeyman QB and a draft prospect S who happen
        to share a name).  Auto-quarantine is reserved for the position-
        aware ``duplicate_canonical_identity`` flag, which only fires
        when both rows share the same ``<name>::<group>`` key.
        """
        rows = [
            {
                "canonicalName": "James Williams",
                "displayName": "James Williams",
                "position": "WR",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 7000},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 5000,
            },
            {
                "canonicalName": "James Williams",
                "displayName": "James Williams",
                "position": "LB",
                "assetClass": "idp",
                "playerId": None,
                "canonicalSiteValues": {"idpTradeCalc": 3000},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 2000,
            },
        ]
        summary = _validate_and_quarantine_rows(rows)
        self.assertGreaterEqual(summary["crossUniverseCollisionCount"], 1)

        # Both rows should carry the surfacing flag, but neither should
        # be auto-quarantined since the position groups differ.
        for row in rows:
            self.assertIn("name_collision_cross_universe", row["anomalyFlags"])

    def test_duplicate_canonical_identity_quarantines(self):
        """Two rows sharing the same position-aware canonical key
        means we genuinely created two rows for the same player —
        the entity-resolution failure case the build-time assertion
        also catches.  Both rows are flagged and quarantined.
        """
        rows = [
            {
                "canonicalName": "Patrick Mahomes",
                "displayName": "Patrick Mahomes",
                "position": "QB",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 9000},
                "anomalyFlags": [],
                "confidenceBucket": "high",
                "confidenceLabel": "",
                "rankDerivedValue": 9000,
            },
            {
                "canonicalName": "Patrick Mahomes",
                "displayName": "Patrick Mahomes",
                "position": "QB",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"idpTradeCalc": 6500},
                "anomalyFlags": [],
                "confidenceBucket": "high",
                "confidenceLabel": "",
                "rankDerivedValue": 6500,
            },
        ]
        summary = _validate_and_quarantine_rows(rows)
        self.assertGreaterEqual(summary["duplicateCanonicalIdentityCount"], 1)
        for row in rows:
            self.assertIn("duplicate_canonical_identity", row["anomalyFlags"])
            self.assertTrue(row["quarantined"])


# ── Near-name value mismatch (legacy) ───────────────────────────────────────
#
# The historical "same last name + cross universe + value ratio > 3"
# rule was a noise generator: every star offense player got paired
# with every bench IDP that happened to share a surname (Bijan Robinson
# vs Chop Robinson, Josh Allen vs CJ Allen / Jonathan Allen / Zach
# Allen, Caleb Williams vs Leonard Williams / Mykel Williams, …) for
# 40+ false positives per build, all of them legitimate distinct
# people.  The flag has been removed in favor of the position-aware
# ``duplicate_canonical_identity`` check.  These tests pin the new
# behavior so the noise can never come back without a deliberate
# code change.

class TestNearNameMismatch(unittest.TestCase):
    """The legacy ``near_name_value_mismatch`` flag is permanently disabled.

    The rule produced only false positives; real entity collisions
    are now caught by the position-aware duplicate-identity check
    (``duplicate_canonical_identity``).
    """

    def test_same_lastname_different_universe_no_longer_fires(self):
        rows = [
            {
                "canonicalName": "Jameson Williams",
                "displayName": "Jameson Williams",
                "position": "WR",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 8000},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 8000,
            },
            {
                "canonicalName": "Milton Williams",
                "displayName": "Milton Williams",
                "position": "DL",
                "assetClass": "idp",
                "playerId": None,
                "canonicalSiteValues": {"idpTradeCalc": 1500},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 1500,
            },
        ]
        summary = _validate_and_quarantine_rows(rows)
        # Two genuinely distinct people sharing a surname must NOT
        # trip any flag; they are not the same canonical entity.
        self.assertEqual(summary["nearNameMismatchCount"], 0)
        for row in rows:
            self.assertNotIn("near_name_value_mismatch", row["anomalyFlags"])

    def test_same_lastname_close_values_also_not_flagged(self):
        rows = [
            {
                "canonicalName": "Josh Allen",
                "displayName": "Josh Allen",
                "position": "QB",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 9000},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 9000,
            },
            {
                "canonicalName": "Brandon Allen",
                "displayName": "Brandon Allen",
                "position": "DL",
                "assetClass": "idp",
                "playerId": None,
                "canonicalSiteValues": {"idpTradeCalc": 5000},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 5000,
            },
        ]
        summary = _validate_and_quarantine_rows(rows)
        self.assertEqual(summary["nearNameMismatchCount"], 0)


# ── Unsupported position ────────────────────────────────────────────────────

class TestUnsupportedPosition(unittest.TestCase):

    def test_ol_position_flagged_as_unsupported(self):
        rows = [
            {
                "canonicalName": "Joe Lineman",
                "displayName": "Joe Lineman",
                "position": "OL",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 1000},
                "anomalyFlags": [],
                "confidenceBucket": "none",
                "confidenceLabel": "",
                "rankDerivedValue": None,
            },
        ]
        _validate_and_quarantine_rows(rows)
        self.assertIn("unsupported_position", rows[0]["anomalyFlags"])
        self.assertTrue(rows[0]["quarantined"])

    def test_supported_positions_not_flagged(self):
        for pos in ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICK"]:
            rows = [
                {
                    "canonicalName": f"Player {pos}",
                    "displayName": f"Player {pos}",
                    "position": pos,
                    "assetClass": "offense" if pos in {"QB", "RB", "WR", "TE"} else "idp",
                    "playerId": None,
                    "canonicalSiteValues": {},
                    "anomalyFlags": [],
                    "confidenceBucket": "none",
                    "confidenceLabel": "",
                    "rankDerivedValue": None,
                },
            ]
            _validate_and_quarantine_rows(rows)
            self.assertNotIn("unsupported_position", rows[0]["anomalyFlags"],
                             f"{pos} should not be flagged as unsupported")


# ── Quarantine degradation ──────────────────────────────────────────────────

class TestQuarantineDegradation(unittest.TestCase):

    def test_high_confidence_degraded_when_quarantined(self):
        rows = [
            {
                "canonicalName": "Bad Player",
                "displayName": "Bad Player",
                "position": "OT",  # unsupported → quarantine
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {},
                "anomalyFlags": [],
                "confidenceBucket": "high",
                "confidenceLabel": "High — multi-source",
                "rankDerivedValue": None,
            },
        ]
        _validate_and_quarantine_rows(rows)
        self.assertEqual(rows[0]["confidenceBucket"], "low")
        self.assertIn("quarantined", rows[0]["confidenceLabel"].lower())

    def test_low_confidence_stays_low(self):
        rows = [
            {
                "canonicalName": "Already Low",
                "displayName": "Already Low",
                "position": "OG",  # unsupported → quarantine
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "Low — single source",
                "rankDerivedValue": None,
            },
        ]
        _validate_and_quarantine_rows(rows)
        self.assertEqual(rows[0]["confidenceBucket"], "low")

    def test_clean_row_not_quarantined(self):
        rows = [
            {
                "canonicalName": "Clean QB",
                "displayName": "Clean QB",
                "position": "QB",
                "assetClass": "offense",
                "playerId": "12345",
                "canonicalSiteValues": {"ktcSfTep": 9000},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 9000,
            },
        ]
        _validate_and_quarantine_rows(rows)
        self.assertFalse(rows[0]["quarantined"])
        self.assertEqual(rows[0]["anomalyFlags"], [])


# ── Identity confidence ─────────────────────────────────────────────────────

class TestIdentityConfidence(unittest.TestCase):

    def test_canonical_id_gives_1_0(self):
        row = {
            "playerId": "SLEEPER123",
            "position": "QB",
            "assetClass": "offense",
            "canonicalSiteValues": {"ktcSfTep": 9000},
        }
        score, method = _compute_identity_confidence(row)
        self.assertEqual(score, 1.00)
        self.assertEqual(method, "canonical_id")

    def test_position_source_aligned_gives_0_95(self):
        row = {
            "playerId": "",
            "position": "QB",
            "assetClass": "offense",
            "canonicalSiteValues": {"ktcSfTep": 9000},
        }
        score, method = _compute_identity_confidence(row)
        self.assertEqual(score, 0.95)
        self.assertEqual(method, "position_source_aligned")

    def test_partial_evidence_gives_0_85(self):
        # IDP position but offense source values — partial evidence
        row = {
            "playerId": "",
            "position": "LB",
            "assetClass": "idp",
            "canonicalSiteValues": {"ktcSfTep": 5000},
        }
        score, method = _compute_identity_confidence(row)
        self.assertEqual(score, 0.85)
        self.assertEqual(method, "partial_evidence")

    def test_name_only_gives_0_70(self):
        row = {
            "playerId": "",
            "position": "QB",
            "assetClass": "offense",
            "canonicalSiteValues": {},
        }
        score, method = _compute_identity_confidence(row)
        self.assertEqual(score, 0.70)
        self.assertEqual(method, "name_only")


# ── Contract-level validation summary ───────────────────────────────────────

class TestValidationSummaryInContract(unittest.TestCase):

    def test_validation_summary_present_in_contract(self):
        payload = _payload_with_players(
            _make_player("Zzz Test QB Only", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        vs = contract.get("validationSummary")
        self.assertIsNotNone(vs)
        self.assertIn("quarantineCount", vs)
        self.assertIn("crossUniverseCollisions", vs)
        self.assertIn("nearNameMismatches", vs)

    def test_identity_fields_on_every_row(self):
        payload = _payload_with_players(
            _make_player("Zzz Identity Test QB", "QB", ktc=7500),
        )
        contract = build_api_data_contract(payload)
        for row in contract["playersArray"]:
            self.assertIn("identityConfidence", row)
            self.assertIn("identityMethod", row)
            self.assertIn("quarantined", row)
            self.assertIsInstance(row["identityConfidence"], float)
            self.assertIsInstance(row["quarantined"], bool)


# ── Single-source false positives ───────────────────────────────────────────

class TestSingleSourceFalsePositive(unittest.TestCase):
    """A player with only one source should be flagged as low confidence
    but not quarantined unless there's an additional identity issue."""

    def test_single_source_not_quarantined_alone(self):
        payload = _payload_with_players(
            _make_player("Zzz Single Source Only", "QB", ktc=6000),
        )
        row, _ = _build_and_find(payload, "Zzz Single Source Only")
        self.assertIsNotNone(row)
        self.assertEqual(row["confidenceBucket"], "low")
        # Single source alone is NOT a quarantine condition
        self.assertFalse(row.get("quarantined"))


# ── Normalize for collision ─────────────────────────────────────────────────

class TestNormalizeForCollision(unittest.TestCase):

    def test_basic_normalization(self):
        self.assertEqual(
            _normalize_for_collision("Jameson Williams"),
            _normalize_for_collision("jameson williams"),
        )

    def test_suffix_stripping(self):
        self.assertEqual(
            _normalize_for_collision("Patrick Mahomes Jr."),
            _normalize_for_collision("Patrick Mahomes"),
        )


# ── Exception-set gap: IDP with only offense source ───────────────────────

class TestExceptionSetCoverage(unittest.TestCase):
    """IDP players with only offense source data should be quarantined unless
    explicitly in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS."""

    def test_idp_db_with_only_ktc_gets_quarantined(self):
        """Regression: Elijah Mitchell (DB) had only KTC data — was
        incorrectly excepted from quarantine."""
        payload = _payload_with_players(
            _make_player("Zzz Fake DB Only KTC", "DB", ktc=963),
        )
        row, _ = _build_and_find(payload, "Zzz Fake DB Only KTC")
        self.assertIsNotNone(row)
        flags = row.get("anomalyFlags") or []
        self.assertIn("position_source_contradiction", flags)
        self.assertTrue(row.get("quarantined"))

    def test_excepted_name_bypasses_contradiction_when_collision_also_flagged(self):
        """Names in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS only bypass
        ``position_source_contradiction`` when they also trip the
        upstream cross-universe collision flag.  This is the post-hygiene
        behaviour: the exception set is a narrow override for verified
        collisions only, not a blanket suppression of evidence errors.
        """
        from src.api.data_contract import OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS
        if not OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS:
            self.skipTest("Exception set is empty")
        exc_name = next(iter(sorted(OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS)))
        # Two rows that share the excepted name: one offense, one IDP.
        # Check 1 stamps both with ``name_collision_cross_universe``,
        # after which Check 2 is suppressed on the IDP row because it
        # is a verified exception sitting on top of a live collision.
        rows = [
            {
                "canonicalName": exc_name,
                "displayName": exc_name,
                "position": "QB",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 4200},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 4200,
            },
            {
                "canonicalName": exc_name,
                "displayName": exc_name,
                "position": "DL",
                "assetClass": "idp",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 685},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 500,
            },
        ]
        _validate_and_quarantine_rows(rows)
        flags_qb = rows[0].get("anomalyFlags") or []
        flags_dl = rows[1].get("anomalyFlags") or []
        # Both rows carry the collision flag from Check 1.
        self.assertIn("name_collision_cross_universe", flags_qb)
        self.assertIn("name_collision_cross_universe", flags_dl)
        # And Check 2 is suppressed on both sides — the collision flag
        # alone is enough to quarantine; double-flagging is false-positive
        # inflation.
        self.assertNotIn("position_source_contradiction", flags_qb)
        self.assertNotIn("position_source_contradiction", flags_dl)

    def test_excepted_name_without_collision_still_fires_contradiction(self):
        """Without a live cross-universe collision the exception list
        does NOT blanket-suppress the contradiction flag.  A single IDP
        row with only offense evidence (the pre-hygiene bug) is still a
        data-quality error and must be quarantined.
        """
        from src.api.data_contract import OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS
        if not OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS:
            self.skipTest("Exception set is empty")
        exc_name = next(iter(sorted(OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS)))
        rows = [
            {
                "canonicalName": exc_name,
                "displayName": exc_name,
                "position": "DL",
                "assetClass": "idp",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 685},
                "anomalyFlags": [],
                "confidenceBucket": "low",
                "confidenceLabel": "",
                "rankDerivedValue": 500,
            },
        ]
        _validate_and_quarantine_rows(rows)
        flags = rows[0].get("anomalyFlags") or []
        self.assertIn("position_source_contradiction", flags)


# ── Age field scaffolding ──────────────────────────────────────────────────

class TestAgeFieldScaffolding(unittest.TestCase):

    def test_age_null_when_not_provided(self):
        payload = _payload_with_players(
            _make_player("Zzz No Age Player", "QB", ktc=8000),
        )
        row, _ = _build_and_find(payload, "Zzz No Age Player")
        self.assertIsNotNone(row)
        self.assertIn("age", row)
        self.assertIsNone(row["age"])

    def test_age_present_when_provided(self):
        """When raw player data includes age, it should appear on the row."""
        players = _make_player("Zzz Aged Player", "QB", ktc=7000)
        players["Zzz Aged Player"]["age"] = 26
        payload = _payload_with_players(players)
        row, _ = _build_and_find(payload, "Zzz Aged Player")
        self.assertIsNotNone(row)
        self.assertEqual(row["age"], 26)


# ── Name collision guardrail: sleeper map tagging conflicts source signals ──

class TestSleeperMapCollisionGuardrail(unittest.TestCase):
    """When the sleeper positions map is contaminated by a name collision
    (e.g. DJ Turner WR and DJ Turner II CB clean to the same key), the
    row's adapter data may have no position but the sleeper map tags it
    with the wrong family. _derive_player_row must use source signals to
    refuse the mismatched tag rather than silently emitting it.
    """

    def _build_row(self, *, sleeper_pos, sites):
        """Build a payload with sleeper map saying sleeper_pos but player
        row having position=None and canonical site values = sites."""
        player_data = {
            "_composite": max(sites.values()),
            "_rawComposite": max(sites.values()),
            "_finalAdjusted": max(sites.values()),
            "_sites": len(sites),
            "position": None,
            "team": None,
            "_canonicalSiteValues": dict(sites),
        }
        payload = {
            "players": {"Zzz Name Collide": player_data},
            "sites": [{"key": k} for k in sites],
            "maxValues": {k: 9999 for k in sites},
            "sleeper": {"positions": {"Zzz Name Collide": sleeper_pos}},
        }
        contract = build_api_data_contract(payload)
        for row in contract["playersArray"]:
            if row["canonicalName"] == "Zzz Name Collide":
                return row, contract
        return None, contract

    def test_offense_signals_reject_sleeper_idp_tag(self):
        """The DJ Turner case: sleeper map says DB (from II collision),
        player row has only offensive source signals. Row must NOT come
        out tagged DB."""
        row, contract = self._build_row(
            sleeper_pos="DB",
            sites={"ktcSfTep": 3000},
        )
        self.assertIsNotNone(row)
        self.assertNotIn(row.get("position"), {"DB", "DL", "LB"})
        # And the contract validator must not flag the offense→IDP mismatch.
        status = (contract.get("_meta") or {}).get("contract_status")
        if status is None:
            status = (contract.get("meta") or {}).get("contract_status")
        self.assertNotEqual(status, "error")

    def test_idp_signals_reject_sleeper_offense_tag(self):
        """Symmetric: sleeper says WR (from an offensive collision) but
        the row has only IDP source signals."""
        row, _ = self._build_row(
            sleeper_pos="WR",
            sites={"idpTradeCalc": 3000},
        )
        self.assertIsNotNone(row)
        self.assertNotIn(row.get("position"), {"QB", "RB", "WR", "TE"})

    def test_signals_on_both_sides_keep_sleeper_position(self):
        """When both offense AND IDP signals are present, we cannot tell
        which is the real player — don't override; keep sleeper's tag so
        downstream collision flagging fires correctly."""
        row, _ = self._build_row(
            sleeper_pos="DB",
            sites={"ktcSfTep": 3000, "idpTradeCalc": 3000},
        )
        self.assertIsNotNone(row)
        # Sleeper tag preserved — the collision flag elsewhere handles this.
        self.assertEqual(row.get("position"), "DB")

    def test_post_enrichment_strip_when_signals_arrive_via_csv(self):
        """Regression for the live-board failure: DJ Turner has no
        _canonicalSiteValues in the scraper payload (legacy shape), gets
        tagged DB from the sleeper-map name collision, and then
        _enrich_from_source_csvs injects KTC/FootballGuys values on top.
        The in-row guardrail in _derive_player_row can't see the
        signals at derive-time, so the post-enrichment pass has to
        clear the tag — but ONLY when the position came from the
        sleeper map (not when an adapter set it explicitly).
        """
        from src.api.data_contract import _strip_mismatched_family_tags

        rows = [
            {
                "canonicalName": "Zzz Post Enrich DB",
                "displayName": "Zzz Post Enrich DB",
                "position": "DB",
                "assetClass": "idp",
                "_positionFromSleeperOnly": True,
                "canonicalSiteValues": {"ktcSfTep": 3000, "footballGuysSf": 2800},
            },
        ]
        _strip_mismatched_family_tags(rows)
        self.assertIsNone(rows[0]["position"])
        self.assertEqual(rows[0]["assetClass"], "offense")

    def test_post_enrichment_preserves_correctly_tagged_row(self):
        from src.api.data_contract import _strip_mismatched_family_tags

        rows = [
            {
                "canonicalName": "Zzz Valid DB",
                "displayName": "Zzz Valid DB",
                "position": "DB",
                "assetClass": "idp",
                "_positionFromSleeperOnly": True,
                "canonicalSiteValues": {"idpTradeCalc": 2500},
            },
            {
                "canonicalName": "Zzz Valid WR",
                "displayName": "Zzz Valid WR",
                "position": "WR",
                "assetClass": "offense",
                "_positionFromSleeperOnly": False,
                "canonicalSiteValues": {"ktcSfTep": 4500},
            },
        ]
        _strip_mismatched_family_tags(rows)
        self.assertEqual(rows[0]["position"], "DB")
        self.assertEqual(rows[1]["position"], "WR")

    def test_post_enrichment_skips_adapter_sourced_position(self):
        """Adapter-sourced position tags are NOT stripped even when the
        site values contradict — those are legitimate contamination
        signals for the downstream ``position_source_contradiction``
        flagger to raise."""
        from src.api.data_contract import _strip_mismatched_family_tags

        rows = [
            {
                "canonicalName": "Zzz Adapter WR",
                "displayName": "Zzz Adapter WR",
                "position": "WR",
                "assetClass": "offense",
                "_positionFromSleeperOnly": False,
                "canonicalSiteValues": {"idpTradeCalc": 5000},
            },
        ]
        _strip_mismatched_family_tags(rows)
        self.assertEqual(rows[0]["position"], "WR")


if __name__ == "__main__":
    unittest.main()
