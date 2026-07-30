"""Tests for ``scripts/audit_identity_matches.py``.

Covers three things:

1. The alias collision-delta check: ``CANONICAL_NAME_ALIASES`` must
   never merge two DISTINCT pool players onto one canonical key.
   Unit-tested both ways — a clean pool reports zero collisions, and
   a pool that actually contains BOTH spellings of an aliased pair
   (the failure mode a bad alias would create) is detected.
2. The per-source match audit logic on a synthetic pool + CSV set.
3. A regression run against the COMMITTED source CSVs + export
   payload: the script must execute end-to-end, exit 0, produce a
   well-formed report for every registered source, and report zero
   alias-introduced collisions on the live board.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_identity_matches.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_identity_matches", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()


def _latest_export() -> Path | None:
    candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
    return candidates[-1] if candidates else None


# ── alias collision-delta invariant ──────────────────────────────────


class TestAliasCollisionDelta:
    def test_distinct_players_same_surname_do_not_collide(self):
        pool = [
            {"canonicalName": "Kenneth Walker III", "position": "RB"},
            {"canonicalName": "Quay Walker", "position": "LB"},
            {"canonicalName": "Patrick Mahomes", "position": "QB"},
        ]
        assert _mod.alias_collision_delta(pool) == []

    def test_alias_pair_with_single_pool_row_is_clean(self):
        # The healthy state: the pool carries ONE spelling and the
        # alias just re-labels vendor CSV rows onto it.
        pool = [
            {"canonicalName": "Kenny Gainwell", "position": "RB"},
        ]
        assert _mod.alias_collision_delta(pool) == []

    def test_alias_merging_two_real_pool_rows_is_detected(self):
        # The failure mode the invariant exists for: if the pool ever
        # contains BOTH spellings as separate rows (two real entities),
        # the alias would silently merge their votes.  The check must
        # surface it.
        pool = [
            {"canonicalName": "Kenneth Gainwell", "position": "RB"},
            {"canonicalName": "Kenny Gainwell", "position": "RB"},
        ]
        collisions = _mod.alias_collision_delta(pool)
        assert len(collisions) == 1
        assert sorted(collisions[0]["mergedNames"]) == ["Kenneth Gainwell", "Kenny Gainwell"]
        assert collisions[0]["crossFamily"] is False

    def test_cross_family_merge_is_detected(self):
        # Regression for the detector's original blind spot.  A
        # group-keyed check reported this pool clean because the two
        # rows land on different ``name::group`` keys — but the CSV
        # join is name-only and REPLICATES a matched entry across every
        # position group sharing the canonical name, so the hypothetical
        # WR would absorb the CB's draftSharksIdp vote.  Cross-family
        # merges must be reported, and flagged as such.
        pool = [
            {"canonicalName": "Michael Jackson", "position": "WR"},
            {"canonicalName": "Mike Jackson", "position": "CB"},
        ]
        collisions = _mod.alias_collision_delta(pool)
        assert len(collisions) == 1
        assert collisions[0]["crossFamily"] is True
        assert collisions[0]["positionGroups"] == ["IDP", "OFFENSE"]
        assert sorted(collisions[0]["mergedNames"]) == ["Michael Jackson", "Mike Jackson"]

    def test_preexisting_name_collision_is_not_alias_introduced(self):
        # "DJ Turner" (WR) and "DJ Turner II" (CB) collapse to the same
        # normalized name WITHOUT any alias — the suffix stripper does
        # it.  This is a delta check, so that pre-existing class must
        # not be attributed to the alias table (the position-aware
        # canonical_player_key is what keeps those two apart).
        pool = [
            {"canonicalName": "DJ Turner", "position": "WR"},
            {"canonicalName": "DJ Turner II", "position": "CB"},
        ]
        assert _mod.alias_collision_delta(pool) == []


# ── synthetic audit run ──────────────────────────────────────────────


class TestAuditSources:
    def test_alias_recovers_vendor_spelling(self):
        pool = [
            {"canonicalName": "Kenny Gainwell", "position": "RB", "playerId": "7567"},
            {"canonicalName": "Justin Jefferson", "position": "WR", "playerId": "6794"},
        ]
        report = _mod.audit_sources(pool)
        assert report["poolRows"] == 2
        # Vendor spelling from an actual committed CSV row must land
        # on the pool key via the alias table.
        assert _mod._canonical_match_key("Kenneth Gainwell") == _mod._canonical_match_key(
            "Kenny Gainwell"
        )

    def test_report_shape_per_source(self):
        report = _mod.audit_sources([{"canonicalName": "Patrick Mahomes", "position": "QB"}])
        assert set(report) == {"poolRows", "poolKeys", "sources"}
        for info in report["sources"].values():
            if "error" in info:
                continue
            for field in (
                "csvRows",
                "parsedRows",
                "matchedRows",
                "matchedKeys",
                "idOnlyMatchedRows",
                "unmatchedRows",
                "matchRate",
                "unmatched",
            ):
                assert field in info


# ── regression: script runs against the committed CSVs ───────────────


class TestCommittedDataRegression:
    @pytest.mark.skipif(_latest_export() is None, reason="no committed export payload")
    def test_script_end_to_end_exit_zero(self, tmp_path):
        out = tmp_path / "report.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--json-path",
                str(_latest_export()),
                "--json",
                str(out),
                "--limit",
                "1",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=600,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        report = json.loads(out.read_text(encoding="utf-8"))
        # Every registered source produced an entry.
        from src.api.data_contract import _SOURCE_CSV_PATHS

        assert set(report["sources"]) == set(_SOURCE_CSV_PATHS)
        # The live board must never contain an alias-introduced
        # collision — the collision-delta invariant.
        #
        # Verified same-player pool duplicates are excluded, which is
        # the carve-out `alias_collision_delta`'s docstring already
        # described ("unless the pool genuinely contains one player
        # twice") and the code did not implement until 2026-07-30.
        # They are still reported and still printed in the summary;
        # only the GATE ignores them. Every other collision fails, so
        # this cannot quietly absorb a genuine WR-absorbs-CB merge.
        unexpected = [c for c in report["aliasCollisions"] if not c.get("knownPoolDuplicate")]
        assert unexpected == []

    def test_gate_exits_zero_under_the_flag_ci_actually_passes(self, tmp_path):
        """The CI invocation, verbatim — including ``--fail-on-collision``.

        Every other end-to-end test here omits that flag, so none of them
        exercised the GATE.  That gap is not hypothetical: the
        ``_KNOWN_POOL_DUPLICATES`` carve-out landed on 2026-07-30 stamping
        ``knownPoolDuplicate`` on the report while the gate ignored the
        stamp, so the whole suite stayed green and
        ``Audit Identity Matches`` went red on ``main`` anyway.  A test
        that does not pass the flag cannot see that.
        """
        out = tmp_path / "report.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--json-path",
                str(_latest_export()),
                "--json",
                str(out),
                "--limit",
                "10",
                "--fail-on-collision",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=600,
        )
        assert proc.returncode == 0, (
            "identity audit gate failed:\n" + proc.stdout[-3000:] + proc.stderr[-2000:]
        )
        # Allow-listed collisions stay VISIBLE — marked, not hidden.
        report = json.loads(out.read_text(encoding="utf-8"))
        known = [c for c in report["aliasCollisions"] if c.get("knownPoolDuplicate")]
        if known:
            assert "::notice title=Known pool duplicate" in proc.stdout
            assert "::error title=Alias collision" not in proc.stdout

    def test_gate_still_fails_on_a_collision_outside_the_allowlist(self, tmp_path):
        """The exemption must not become a blanket pass.

        Feeds a payload whose pool carries two genuinely different
        players that an alias merges, with the name absent from
        ``_KNOWN_POOL_DUPLICATES``.  Exit MUST be 1.
        """
        # The same cross-family pair the unit test above uses: an alias
        # merges a WR and a CB onto one canonical name, which is the
        # vote-replication hazard this gate exists for.
        assert "michael jackson" not in _mod._KNOWN_POOL_DUPLICATES
        payload = {
            "players": {
                "Michael Jackson": {"pos": "WR", "_finalAdjusted": 5000},
                "Mike Jackson": {"pos": "CB", "_finalAdjusted": 4000},
            }
        }
        payload_path = tmp_path / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--json-path",
                str(payload_path),
                "--json",
                str(tmp_path / "r.json"),
                "--limit",
                "1",
                "--fail-on-collision",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=600,
        )
        assert proc.returncode == 1, (
            "an un-allow-listed cross-family collision did NOT fail the "
            "gate:\n" + proc.stdout[-3000:]
        )
        assert "::error title=Alias collision" in proc.stdout

    def test_the_duplicate_allowlist_only_holds_real_collisions(self, tmp_path):
        """An allowlist entry that no longer collides is dead weight.

        Guards the guard: if a refresh drops the duplicate pool row,
        this fails and the entry gets removed, rather than sitting
        there widening the exemption for a future name that happens to
        normalize the same way.
        """
        from scripts.audit_identity_matches import _KNOWN_POOL_DUPLICATES

        out = tmp_path / "report.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--json-path",
                str(_latest_export()),
                "--json",
                str(out),
                "--limit",
                "1",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=600,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        report = json.loads(out.read_text(encoding="utf-8"))
        colliding = {c["canonicalName"] for c in report["aliasCollisions"]}
        stale = sorted(_KNOWN_POOL_DUPLICATES - colliding)
        assert stale == [], (
            f"allowlisted names that no longer collide: {stale}. "
            "Drop them from _KNOWN_POOL_DUPLICATES — a stale exemption "
            "silently covers whatever normalizes to that name next."
        )
