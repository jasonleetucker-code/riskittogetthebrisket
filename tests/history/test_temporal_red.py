"""C1-U4 RED: the temporal-history defects measured on LIVE code paths
and REAL production data, before the canonical temporal ledger exists.

The C1-U4 execution-map REDs are (a) ``rankChange`` proven
non-deterministic — build N+1 diffs against build N's own output rather
than a stable historical observation — and (b) a historical pick value
being unrecoverable.  Both are reproduced here behaviorally, plus the
fidelity-class defects the census measured alongside them.

The fixture (``tests/fixtures/temporal_live_subset.json``) is unedited
production data: canonical contract rows built from two consecutive
retained archive bundles (2026-08-15 and 2026-08-16), so every rank,
value and pick in these tests is a number the site actually served.

Every test here asserts CURRENT behavior — i.e. each one PASSES by
demonstrating the defect.  They are regression-locks on the
measurement, in the same style as ``test_pick_identity_red.py``
(C1-U3): when a path is migrated onto the canonical temporal owner and
a defect becomes unrepresentable, the corresponding RED assertion is
updated in the same commit with a pointer to the GREEN test that
supersedes it.  The GREEN counterparts live in
``tests/history/test_temporal_ledger.py``.

RED index
─────────
RED-1  rankChange self-reference: a rebuild diffs against its own
       previous output, so the answer depends on build cadence, not on
       any dated observation.  (C1-HIST-03)
RED-2  rankChange namespace collision: the snapshot is keyed by bare
       ``canonicalName`` while the durable log keys
       ``name::assetClass`` — same concept, two keyings; cross-universe
       same-name players fabricate movement.  (C1-HIST-03)
RED-3  historical pick value unrecoverable: every current-year slot
       pick carries a real value and no rank, and the rank-gated
       durable log therefore never records it.  (C1-HIST-02)
RED-4  reconstruction indistinguishable from observation: rank-only
       history entries are valued through TODAY'S Hill constants and
       returned in the same field as contemporaneously recorded
       values, with no fidelity marker.  (C1-HIST-01)
RED-5  same-date rewrite: a later write for an already-recorded date
       silently destroys the earlier evidence — which is exactly what
       re-running ``scripts/backfill_rank_history.py`` under a changed
       pipeline would do to contemporaneous production entries.
       (C1-HIST-01)
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.api import data_contract, rank_history
from src.canonical.player_valuation import rank_to_value_for_scope

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "temporal_live_subset.json"


def _fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rows(fx: dict) -> list[dict]:
    # Deep-copy so mutation by the code under test never leaks between tests.
    return json.loads(json.dumps(fx["currentRows"]))


class TestRed1RankChangeSelfReference(unittest.TestCase):
    """THE execution-map RED — now a TOMBSTONE.

    As measured (B-audit residual H; 740 rows across two back-to-back
    identical builds): ``_stamp_rank_changes`` read
    ``data/snapshots/ranks_last.json``, stamped deltas against it, then
    unconditionally rewrote it — so build N+1 diffed against build N's
    own output, and every non-override build (scrape promotions,
    startup priming, the two daily offline recorder scripts, and even a
    stock ``/rankings`` override request — W03-F010) moved the
    baseline.

    The mechanism is DELETED: the cache path, its accessor and the
    ``write_snapshot`` parameter no longer exist, so the defect is
    unrepresentable rather than merely untriggered.  The GREEN
    counterpart is ``test_temporal_ledger.py::TestRankChangeDeterministic``
    (back-to-back identical builds, recording-today inertness, and the
    real 2026-08-15→16 movement reproduced deterministically)."""

    def test_self_referential_cache_mechanism_is_gone(self):
        self.assertFalse(hasattr(data_contract, "_RANK_SNAPSHOT_PATH"))
        self.assertFalse(hasattr(data_contract, "_get_rank_snapshot_path"))
        import inspect

        sig = inspect.signature(data_contract._stamp_rank_changes)
        self.assertNotIn("write_snapshot", sig.parameters)
        # The derivation is read-only by signature: it takes the board's
        # own date and a ledger path, and writes nothing anywhere.
        self.assertIn("board_date", sig.parameters)

    def test_stamp_writes_no_files(self):
        import tempfile

        fx = _fx()
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.sqlite"
            rows = _rows(fx)
            data_contract._stamp_rank_changes(rows, board_date="2026-08-16", ledger_path=ledger)
            # A build creates NOTHING — no cache, not even an empty
            # ledger file (reads must not mint stores).
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()), [])


class TestRed2RankChangeNamespaceCollision(unittest.TestCase):
    """TOMBSTONE.  The retired cache was keyed by bare
    ``canonicalName``, so the real cross-universe same-name pair the
    identity-validation code records (offense "James Williams" vs IDP
    "James Williams") collapsed to one slot and fabricated a ±300
    "move" for whichever player didn't win the last write.

    ``rankChange`` now keys through the canonical asset namespace
    (``src/history/keys.py``), where the collision is unrepresentable:
    the pair below yields two distinct keys, and the three namespace
    prefixes (``player:`` / ``name:`` / ``mpick:``) are disjoint.  The
    GREEN counterpart is
    ``test_temporal_ledger.py::TestRankChangeDeterministic::test_collision_keyed``."""

    ROWS = [
        {
            "canonicalName": "James Williams",
            "displayName": "James Williams",
            "assetClass": "offense",
            "position": "RB",
            "canonicalConsensusRank": 400,
            "rankDerivedValue": 1700,
        },
        {
            "canonicalName": "James Williams",
            "displayName": "James Williams",
            "assetClass": "idp",
            "position": "S",
            "canonicalConsensusRank": 700,
            "rankDerivedValue": 1100,
        },
    ]

    def test_same_name_pair_yields_distinct_canonical_keys(self):
        from src.history import keys as history_keys

        keyed = {history_keys.asset_key_for_contract_row(r) for r in self.ROWS}
        self.assertEqual(
            keyed,
            {
                ("name:james williams::OFFENSE", "offense"),
                ("name:james williams::IDP", "idp"),
            },
        )
        # The durable legacy log was already collision-safe; the defect
        # was the cache's DIVERGENT keying for the same concept.  That
        # log keying survives unchanged (raw evidence store).
        legacy = {rank_history._player_key(r) for r in self.ROWS}
        self.assertEqual(legacy, {"James Williams::offense", "James Williams::idp"})


class TestRed3HistoricalPickValueUnrecoverable(unittest.TestCase):
    """Every current-year slot pick on the real 2026-08-16 board
    carries a served ``rankDerivedValue`` and NO
    ``canonicalConsensusRank`` (the anchor pass clears slot-pick
    ranks).  The rank-gated durable log therefore never records them —
    72 of 144 pick rows on the live board, including 2026 Pick 1.01 at
    7,779 — and the fixture's prior-day block proves the value existed
    on 2026-08-15 too (7,778).  No current lookup path can answer
    "what was 2026 Pick 1.01 worth on 2026-08-15?"."""

    def test_slot_picks_with_real_values_never_enter_the_log(self):
        fx = _fx()
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "rank_history.jsonl"
            contract = {"playersArray": _rows(fx)}
            wrote = rank_history.append_snapshot(contract, date="2026-08-16", path=log)
            self.assertTrue(wrote)

            history = rank_history.load_history(days=30, path=log)

        # The value demonstrably existed (real board, real prior day)…
        slot = next(r for r in fx["currentRows"] if r["canonicalName"] == "2026 Pick 1.01")
        self.assertGreater(slot["rankDerivedValue"], 0)
        self.assertIn("2026 Pick 1.01", fx["priorSlotPickValues"])

        # …and is unrecoverable through the durable log: no series at
        # all for any slot pick.
        self.assertNotIn("2026 Pick 1.01::pick", history)
        self.assertNotIn("2026 Pick 1.02::pick", history)
        self.assertNotIn("2026 Pick 1.03::pick", history)

        # Partial coverage makes the exclusion precise: RANKED generic
        # future picks DO get a series.
        self.assertIn("2027 Early 1st::pick", history)


class TestRed4ReconstructionIndistinguishableFromObservation(unittest.TestCase):
    """A rank-only history entry (the pre-``values`` schema) is valued
    through TODAY'S Hill constants at read time and returned in the
    same ``val`` field as contemporaneously recorded values, with no
    fidelity marker.  The replay spec (§12) forbids presenting
    today's-model output as a historical observation; the current
    reader structurally cannot honor that."""

    def test_todays_curve_output_served_in_the_recorded_value_field(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "rank_history.jsonl"
            # Legacy-shape entry: ranks only — exactly what the log
            # held before the values block existed.
            log.write_text(
                json.dumps({"date": "2026-07-20", "ranks": {"A.J. Brown::offense": 72}})
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-07-21",
                        "ranks": {"A.J. Brown::offense": 72},
                        "values": {"A.J. Brown::offense": 4947},
                    }
                )
                + "\n"
            )
            series = rank_history.load_history(days=30, path=log)["A.J. Brown::offense"]

        reconstructed = next(p for p in series if p["date"] == "2026-07-20")
        recorded = next(p for p in series if p["date"] == "2026-07-21")

        # The 2026-07-20 "val" is today's curve applied to an old rank…
        self.assertEqual(reconstructed["val"], rank_to_value_for_scope(72.0, "offense"))
        # …and nothing distinguishes it from the recorded observation:
        # identical key sets, no fidelity field on either.
        self.assertEqual(set(reconstructed.keys()), set(recorded.keys()))
        self.assertNotIn("fidelity", reconstructed)


class TestRed5SameDateRewriteDestroysEvidence(unittest.TestCase):
    """``append_snapshot`` dedups per date with most-recent-wins, so a
    later write for an already-recorded date silently replaces the
    earlier evidence.  Combined with ``scripts/backfill_rank_history.py``
    — which replays archives through TODAY'S ``build_api_data_contract``
    — a backfill run under a changed pipeline would overwrite the
    contemporaneous entries production actually recorded, and nothing
    would show it happened."""

    def test_later_write_for_same_date_replaces_contemporaneous_entry(self):
        fx = _fx()
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "rank_history.jsonl"

            # The contemporaneous observation production recorded.
            rank_history.append_snapshot({"playersArray": _rows(fx)}, date="2026-08-16", path=log)
            before = rank_history.load_history(days=5, path=log)
            self.assertEqual(before["A.J. Brown::offense"][0]["val"], 4947)

            # A later rebuild of the same date under a drifted pipeline
            # (one rank different — the smallest possible drift).
            drifted = _rows(fx)
            for r in drifted:
                if r["canonicalName"] == "A.J. Brown":
                    r["canonicalConsensusRank"] = 75
                    r["rankDerivedValue"] = 4800
            rank_history.append_snapshot({"playersArray": drifted}, date="2026-08-16", path=log)
            after = rank_history.load_history(days=5, path=log)

        # RED: the original evidence is gone — same date, same key,
        # different number, no supersession record.
        self.assertEqual(after["A.J. Brown::offense"][0]["val"], 4800)
        self.assertEqual(len(after["A.J. Brown::offense"]), 1)


if __name__ == "__main__":
    unittest.main()
