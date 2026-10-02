"""AL-0 learning receipt contract: A1 (point in time), A2 (append-only store),
A5 (no promotion record), A8 (drift triggers nothing).

The property tests use a seeded ``random.Random`` over thousands of generated
cases rather than a property-testing library: the repo pins no such dependency
and AL-0 adds none (plan §23 applicability: no new dependency). The seed is fixed
so a failure is reproducible.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.model_registry import learning_receipt as lr
from src.model_registry import receipt_store as rs

BASE = datetime(2026, 7, 14, tzinfo=timezone.utc)
SEED = 20261001


def _ref(known_at, role=lr.ROLE_INPUT, key="k"):
    return lr.StoreRef(
        store="temporal_ledger",
        key=key,
        role=role,
        known_at=known_at,
        fidelity="exact" if known_at is not None else "unavailable",
    )


def _receipt(
    *,
    cutoff=None,
    target=None,
    slots=None,
    refs=(),
    kind=lr.KIND_OBSERVATION,
    native="n1",
    body=None,
    producer="test_producer",
):
    return lr.LearningReceipt(
        kind=kind,
        producer=producer,
        native_id=native,
        model_family="test_family",
        model_version_id=lr.model_version_id("test_family", "v1"),
        slots=slots if slots is not None else {"obs": lr.Unobserved("none")},
        refs=refs,
        cutoff=cutoff,
        target_event_at=target,
        body=body or {},
    )


def _instant(rng: random.Random) -> datetime:
    return BASE + timedelta(seconds=rng.randrange(0, 200 * 86400))


# ── A1: point in time ───────────────────────────────────────────────────────


class TestPointInTimeProperty:
    def test_an_input_is_selectable_iff_known_at_or_before_the_cutoff(self):
        rng = random.Random(SEED)
        accepted = refused = 0
        for _ in range(5000):
            cutoff, known = _instant(rng), _instant(rng)
            if rng.random() < 0.05:
                known = cutoff  # the boundary is inclusive
            r = _receipt(cutoff=cutoff, slots={"obs": _ref(known)})
            if known <= cutoff:
                lr.validate_receipt(r)
                accepted += 1
            else:
                with pytest.raises(lr.PointInTimeViolation):
                    lr.validate_receipt(r)
                refused += 1
        assert accepted > 1000 and refused > 1000

    def test_one_future_input_among_many_poisons_the_receipt(self):
        rng = random.Random(SEED + 1)
        for _ in range(500):
            cutoff = _instant(rng)
            past = [
                _ref(cutoff - timedelta(seconds=rng.randrange(0, 10**6)), key=f"p{i}")
                for i in range(rng.randrange(1, 8))
            ]
            future = _ref(cutoff + timedelta(seconds=rng.randrange(1, 10**6)), key="future")
            refs = past + [future]
            rng.shuffle(refs)
            with pytest.raises(lr.PointInTimeViolation):
                lr.validate_receipt(
                    _receipt(cutoff=cutoff, slots={"obs": refs[0]}, refs=tuple(refs[1:]))
                )

    def test_an_outcome_is_refused_iff_dated_before_its_target_event(self):
        rng = random.Random(SEED + 2)
        for _ in range(3000):
            target, known = _instant(rng), _instant(rng)
            r = _receipt(
                kind=lr.KIND_OUTCOME,
                target=target,
                slots={"outcome": _ref(known, role=lr.ROLE_OUTCOME)},
            )
            if known >= target:
                lr.validate_receipt(r)
            else:
                with pytest.raises(lr.PointInTimeViolation):
                    lr.validate_receipt(r)

    def test_an_input_without_a_cutoff_or_without_an_instant_is_refused(self):
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(_receipt(cutoff=None, slots={"obs": _ref(BASE)}))
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(_receipt(cutoff=BASE, slots={"obs": _ref(None)}))

    @pytest.mark.parametrize("stamp", ["2026-09-30", "2026-09-30T12:00:00", "", None, "garbage"])
    def test_an_unproven_instant_is_refused_never_assumed(self, stamp):
        with pytest.raises(lr.ReceiptError):
            lr.parse_instant(stamp, what="t")

    def test_reconstructed_fidelity_is_refused(self):
        with pytest.raises(lr.ReceiptError, match="reconstructed"):
            lr.StoreRef(
                store="temporal_ledger",
                key="k",
                role=lr.ROLE_INPUT,
                known_at=BASE,
                fidelity="reconstructed",
            )

    def test_an_unregistered_store_is_refused(self):
        with pytest.raises(lr.ReceiptError, match="unregistered"):
            lr.StoreRef(
                store="somewhere_else", key="k", role=lr.ROLE_INPUT, known_at=BASE, fidelity="exact"
            )


class TestRoleCannotDodgeTheGuard:
    """Finding 2: the A1 guard must not trust the caller-declared role."""

    def test_probe_future_ledger_ref_labelled_artifact_on_a_prediction_is_refused(self):
        # The reviewer's bypass: a temporal-ledger observation known a day after the
        # cutoff, labelled 'artifact' so the time guard would skip it.
        with pytest.raises(lr.ReceiptError, match="cannot be an 'artifact'"):
            lr.validate_receipt(
                _receipt(
                    kind=lr.KIND_PREDICTION,
                    cutoff=BASE,
                    slots={"inputs": _ref(BASE + timedelta(days=1), role=lr.ROLE_ARTIFACT)},
                )
            )

    @pytest.mark.parametrize(
        "store",
        sorted(set(lr.NATIVE_STORES) - lr.ARTIFACT_STORES),
    )
    def test_no_evidence_store_may_be_an_artifact(self, store):
        assert store in {
            "temporal_ledger",
            "repo_file",
            "board_snapshot",
            "source_quality_panel",
            "dataset_state",
        }
        with pytest.raises(lr.ReceiptError, match="cannot be an 'artifact'"):
            lr.StoreRef(
                store=store, key="k", role=lr.ROLE_ARTIFACT, known_at=BASE, fidelity="exact"
            )

    def test_artifact_stores_are_registered_native_stores(self):
        assert lr.ARTIFACT_STORES <= set(lr.NATIVE_STORES)
        assert "temporal_ledger" not in lr.ARTIFACT_STORES
        assert "dataset_state" not in lr.ARTIFACT_STORES

    @pytest.mark.parametrize("kind", sorted(lr.INPUT_ONLY_KINDS))
    def test_observation_and_features_accept_inputs_only(self, kind):
        artifact = lr.StoreRef(
            store="model_registry",
            key="m#v1",
            role=lr.ROLE_ARTIFACT,
            known_at=BASE + timedelta(days=9),
            fidelity="exact",
        )
        with pytest.raises(lr.PointInTimeViolation, match="must be an 'input'"):
            lr.validate_receipt(_receipt(kind=kind, cutoff=BASE, slots={"x": artifact}))

    @pytest.mark.parametrize("kind", sorted(lr.PRE_CUTOFF_KINDS))
    def test_no_pre_cutoff_kind_may_point_at_an_outcome(self, kind):
        outcome = _ref(BASE + timedelta(days=2), role=lr.ROLE_OUTCOME)
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(
                _receipt(
                    kind=kind, cutoff=BASE, target=BASE + timedelta(days=1), slots={"o": outcome}
                )
            )

    def test_a_producers_own_artifact_on_a_prediction_is_still_accepted(self):
        own = _artifact("source_quality_results", BASE + timedelta(hours=1), produced_for="run-7")
        lr.validate_receipt(
            _receipt(
                kind=lr.KIND_PREDICTION,
                producer="source_quality_eval",
                native="run-7",
                cutoff=BASE,
                slots={"inputs": _ref(BASE), "predictionSet": own},
            )
        )


def _artifact(store, known_at, *, produced_for=None, key="a#1"):
    return lr.StoreRef(
        store=store,
        key=key,
        role=lr.ROLE_ARTIFACT,
        known_at=known_at,
        fidelity="exact" if known_at is not None else "unavailable",
        produced_for=produced_for,
    )


class TestArtifactTimeBound:
    """Round-2 finding 5: the artifact exemption is for the receipt's OWN output
    only — same (registered-writer) producer AND the same native run."""

    LATE = BASE + timedelta(days=3)

    def _prediction(self, ref, *, producer="test_producer", native="n1"):
        return _receipt(
            kind=lr.KIND_PREDICTION,
            producer=producer,
            native=native,
            cutoff=BASE,
            slots={"inputs": _ref(BASE), "cited": ref},
        )

    @pytest.mark.parametrize("store", ["model_registry", "source_quality_results"])
    def test_a_later_artifact_of_another_producer_is_refused(self, store):
        with pytest.raises(lr.PointInTimeViolation, match="not this receipt's own output"):
            lr.validate_receipt(self._prediction(_artifact(store, self.LATE, produced_for="n1")))

    def test_a_later_artifact_naming_no_run_is_refused_even_for_its_writer(self):
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(
                self._prediction(
                    _artifact("model_registry", self.LATE),
                    producer="hill_model_registry",
                    native="v9",
                )
            )

    def test_a_later_artifact_of_a_different_run_is_refused(self):
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(
                self._prediction(
                    _artifact("model_registry", self.LATE, produced_for="v10"),
                    producer="hill_model_registry",
                    native="v9",
                )
            )

    def test_the_writers_own_later_artifact_for_this_run_is_accepted(self):
        lr.validate_receipt(
            self._prediction(
                _artifact("model_registry", self.LATE, produced_for="v9"),
                producer="hill_model_registry",
                native="v9",
            )
        )

    def test_a_store_with_no_registered_writer_is_never_exempt(self):
        assert lr.ARTIFACT_STORE_WRITERS["preregistration"] == frozenset()
        for producer in ("test_producer", "robust_filter_shadow", "sparse_evidence_shadow"):
            with pytest.raises(lr.PointInTimeViolation):
                lr.validate_receipt(
                    self._prediction(
                        _artifact("preregistration", self.LATE, produced_for="n1"),
                        producer=producer,
                    )
                )

    @pytest.mark.parametrize(
        "store", ["robust_filter_shadow_ledger", "sparse_evidence_shadow_ledger"]
    )
    def test_a_shadow_ledger_is_exempt_only_for_its_own_writer(self, store):
        """AL-1a registered the shadow producers as writers of their own ledgers;
        any other producer citing a later line is still held to the cutoff."""
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(self._prediction(_artifact(store, self.LATE, produced_for="n1")))
        (writer,) = lr.ARTIFACT_STORE_WRITERS[store]
        lr.validate_receipt(
            self._prediction(_artifact(store, self.LATE, produced_for="n1"), producer=writer)
        )

    def test_an_artifact_at_or_before_the_cutoff_needs_no_claim(self):
        for at in (BASE, BASE - timedelta(days=1)):
            lr.validate_receipt(self._prediction(_artifact("model_registry", at)))

    # ── round-3 finding D3: a non-own artifact must be COMPARABLE with a cutoff ──

    @pytest.mark.parametrize("store", sorted(lr.ARTIFACT_STORES))
    def test_a_non_own_artifact_with_no_proven_instant_is_refused(self, store):
        """No knownAt asserts no instant, and an instant that cannot be compared
        cannot be proven to precede the cutoff. Was: silently not compared."""
        with pytest.raises(lr.PointInTimeViolation, match="no proven knownAt"):
            lr.validate_receipt(self._prediction(_artifact(store, None)))

    def test_a_non_own_artifact_on_a_receipt_with_no_cutoff_is_refused(self):
        for at in (BASE, None):
            r = _receipt(
                kind=lr.KIND_MODEL,
                slots={"cited": _artifact("model_registry", at, produced_for="other-run")},
            )
            with pytest.raises(lr.PointInTimeViolation, match="no cutoff to bound it"):
                lr.validate_receipt(r)

    def test_the_writers_own_artifact_may_omit_its_write_time(self):
        """Only the receipt's own output is exempt — and that exemption is decided
        by (registered writer, producedFor == nativeId), never by the role label."""
        own = _artifact("model_registry", None, produced_for="v9")
        lr.validate_receipt(self._prediction(own, producer="hill_model_registry", native="v9"))
        lr.validate_receipt(
            _receipt(
                kind=lr.KIND_MODEL,
                producer="hill_model_registry",
                native="v9",
                slots={"registryVersion": own},
            )
        )
        with pytest.raises(lr.PointInTimeViolation):  # same ref, another producer
            lr.validate_receipt(self._prediction(own, producer="test_producer", native="v9"))

    def test_property_exempt_iff_own_writer_and_own_run(self):
        rng = random.Random(SEED + 9)
        producers = ["hill_model_registry", "source_quality_eval", "test_producer"]
        for _ in range(2000):
            store = rng.choice(sorted(lr.ARTIFACT_STORES))
            producer = rng.choice(producers)
            native = rng.choice(["r1", "r2"])
            produced_for = rng.choice([None, "r1", "r2"])
            known = BASE + timedelta(seconds=rng.randrange(-86400, 86400))
            r = self._prediction(
                _artifact(store, known, produced_for=produced_for),
                producer=producer,
                native=native,
            )
            own = produced_for == native and producer in lr.ARTIFACT_STORE_WRITERS[store]
            if known <= BASE or own:
                lr.validate_receipt(r)
            else:
                with pytest.raises(lr.PointInTimeViolation):
                    lr.validate_receipt(r)

    def test_produced_for_is_only_for_artifacts(self):
        with pytest.raises(lr.ReceiptError, match="only an 'artifact'"):
            lr.StoreRef(
                store="temporal_ledger",
                key="k",
                role=lr.ROLE_INPUT,
                known_at=BASE,
                fidelity="exact",
                produced_for="n1",
            )

    def test_every_artifact_store_declares_its_writers(self):
        assert set(lr.ARTIFACT_STORE_WRITERS) == set(lr.ARTIFACT_STORES)


class TestOutcomeTiming:
    def test_an_outcome_may_not_precede_the_prediction_cutoff(self):
        with pytest.raises(lr.PointInTimeViolation):
            lr.validate_receipt(
                _receipt(
                    kind=lr.KIND_OUTCOME,
                    cutoff=BASE,
                    target=BASE - timedelta(days=1),
                    slots={"o": _ref(BASE - timedelta(hours=1), role=lr.ROLE_OUTCOME)},
                )
            )

    def test_a_target_event_before_the_cutoff_is_refused(self):
        with pytest.raises(lr.PointInTimeViolation, match="precedes the cutoff"):
            lr.validate_receipt(
                _receipt(kind=lr.KIND_OUTCOME, cutoff=BASE, target=BASE - timedelta(seconds=1))
            )


class TestContract:
    def test_twelve_kinds_exactly(self):
        assert len(lr.RECEIPT_KINDS) == 12 == len(set(lr.RECEIPT_KINDS))

    def test_absence_must_say_why(self):
        with pytest.raises(lr.ReceiptError):
            lr.validate_receipt(_receipt(slots={"obs": lr.Unobserved("")}))
        with pytest.raises(lr.ReceiptError):
            lr.validate_receipt(_receipt(slots={"obs": None}))

    def test_identity_and_content_hash_carry_no_wall_clock(self):
        a = _receipt(cutoff=BASE, slots={"obs": _ref(BASE)})
        b = _receipt(cutoff=BASE, slots={"obs": _ref(BASE)})
        assert a.receipt_id == b.receipt_id and a.content_hash() == b.content_hash()


# ── A5: no promotion record ─────────────────────────────────────────────────


class TestNoPromotion:
    def test_a_promotion_record_cannot_be_built(self):
        with pytest.raises(lr.PromotionNotPermitted):
            lr.build_receipt(**_receipt(kind=lr.KIND_PROMOTION_RECORD).__dict__)

    def test_the_store_refuses_one_even_if_handed_one(self, tmp_path):
        r = _receipt(kind=lr.KIND_PROMOTION_RECORD)
        out = rs.append_receipts([r], path=tmp_path / "r.sqlite")
        assert out["written"] == 0 and out["rejected"]

    def test_the_database_refuses_one_even_bypassing_the_module(self, tmp_path):
        conn = rs.connect(tmp_path / "r.sqlite")
        with pytest.raises(sqlite3.DatabaseError, match="PROMOTION"):
            conn.execute(
                "INSERT INTO receipts VALUES ('x','PROMOTION_RECORD',1,'p','f',NULL,NULL,NULL,'h','{}','t')"
            )
        conn.close()


# ── A2: append-only, idempotent, conflict-surfacing ─────────────────────────


class TestStore:
    def test_identical_rewrite_is_a_noop_and_conflict_is_surfaced_not_applied(self, tmp_path):
        path = tmp_path / "r.sqlite"
        first = _receipt(body={"v": 1})
        assert rs.append_receipts([first], path=path)["written"] == 1
        again = rs.append_receipts([_receipt(body={"v": 1})], path=path)
        assert again == {"written": 0, "duplicates": 1, "contentConflicts": [], "rejected": []}
        clash = rs.append_receipts([_receipt(body={"v": 2})], path=path)
        assert clash["written"] == 0 and len(clash["contentConflicts"]) == 1
        stored = list(rs.iter_receipts(path))
        assert len(stored) == 1 and stored[0]["body"] == {"v": 1}

    def test_property_any_interleaving_keeps_the_first_writer(self, tmp_path):
        rng = random.Random(SEED + 3)
        for trial in range(20):
            path = tmp_path / f"r{trial}.sqlite"
            natives = [f"n{i}" for i in range(rng.randrange(1, 12))]
            stream = []
            for _ in range(rng.randrange(5, 60)):
                stream.append(_receipt(native=rng.choice(natives), body={"v": rng.randrange(3)}))
            first: dict[str, dict] = {}
            for r in stream:
                first.setdefault(r.receipt_id, dict(r.body))
            out = rs.append_receipts(stream, path=path)
            assert out["written"] == len(first)
            assert out["written"] + out["duplicates"] + len(out["contentConflicts"]) == len(stream)
            stored = {s["receiptId"]: s["body"] for s in rs.iter_receipts(path)}
            assert stored == first

    def test_update_and_delete_are_refused_by_the_database(self, tmp_path):
        path = tmp_path / "r.sqlite"
        rs.append_receipts([_receipt()], path=path)
        conn = rs.connect(path)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE receipts SET receipt_json = '{}'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM receipts")
        conn.close()

    def test_a_point_in_time_violation_is_rejected_not_stored(self, tmp_path):
        bad = _receipt(cutoff=BASE, slots={"obs": _ref(BASE + timedelta(days=1))})
        out = rs.append_receipts([bad], path=tmp_path / "r.sqlite")
        assert out["written"] == 0 and "after the cutoff" in out["rejected"][0]["reason"]

    def test_the_store_may_not_live_under_data_ros(self):
        with pytest.raises(rs.StorePathError):
            rs.connect(rs.REPO / "data" / "ros" / "receipts.sqlite")

    @pytest.mark.parametrize(
        "rel",
        ["data/temporal_ledger.sqlite", "data/receipts.sqlite", "config/receipts.sqlite"],
    )
    def test_the_store_refuses_any_other_sqlite_path(self, rel):
        target = rs.REPO / rel
        existed = target.exists()
        with pytest.raises(rs.StorePathError, match="data/learning"):
            rs.connect(target)
        with pytest.raises(rs.StorePathError):
            list(rs.iter_receipts(target))
        assert target.exists() == existed  # nothing created

    def test_there_is_no_implicit_temp_dir_allowance(self, tmp_path, monkeypatch):
        """Round-2 finding 1: without an explicit opt-in a temp path is refused —
        on a production host that allowance admitted anything in /tmp."""
        monkeypatch.setattr(rs, "EXTRA_ALLOWED_ROOTS", ())
        target = tmp_path / "r.sqlite"
        with pytest.raises(rs.StorePathError, match="outside the repository"):
            rs.connect(target)
        assert not target.exists()

    @pytest.mark.parametrize(
        "rel, allowed",
        [
            ("config/receipts.sqlite", False),
            ("data/temporal_ledger.sqlite", False),
            ("data/receipts.sqlite", False),
            ("receipts.sqlite", False),
            ("data/ros/receipts.sqlite", False),
            ("data/learning/receipts.sqlite", True),
            ("data/learning/sub/r.sqlite", True),
        ],
    )
    def test_a_checkout_under_a_temp_dir_gains_nothing(self, tmp_path, monkeypatch, rel, allowed):
        """Round-2 finding 1: simulate a repo root that itself lives under an
        allowed temp root. The in-repo rule must run first, so only data/learning
        is accepted inside it — whatever directory the checkout happens to be in."""
        repo = tmp_path / "checkout"
        monkeypatch.setattr(rs, "REPO", repo)
        monkeypatch.setattr(rs, "STORE_TREE", repo / "data" / "learning")
        monkeypatch.setattr(rs, "_FORBIDDEN_TREE", repo / "data" / "ros")
        monkeypatch.setattr(rs, "EXTRA_ALLOWED_ROOTS", (tmp_path,))
        target = repo / rel
        if allowed:
            rs.connect(target).close()
            assert target.exists()
        else:
            with pytest.raises(rs.StorePathError):
                rs.connect(target)
            with pytest.raises(rs.StorePathError):
                list(rs.iter_receipts(target))
            assert not target.exists()
        # outside the simulated checkout, the explicit opt-in still applies
        rs.connect(tmp_path / "elsewhere" / "r.sqlite").close()

    def test_an_opted_in_root_inside_the_repo_is_ignored(self, monkeypatch):
        monkeypatch.setattr(rs, "EXTRA_ALLOWED_ROOTS", (rs.REPO, rs.REPO / "config"))
        target = rs.REPO / "config" / "receipts.sqlite"
        existed = target.exists()
        with pytest.raises(rs.StorePathError, match="data/learning"):
            rs.connect(target)
        assert target.exists() == existed

    def test_meta_is_insert_only(self, tmp_path):
        path = tmp_path / "r.sqlite"
        conn = rs.connect(path)
        for sql in (
            "UPDATE meta SET value = '99' WHERE key = 'schema_version'",
            "DELETE FROM meta",
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '99')",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="insert-only"):
                conn.execute(sql)
        conn.close()
        conn = rs.connect(path)  # reconnecting does not rewrite meta either
        assert conn.execute("SELECT value FROM meta").fetchall()[0][0] == str(
            rs.STORE_SCHEMA_VERSION
        )
        conn.close()

    @pytest.mark.parametrize("verb", ["INSERT OR REPLACE", "INSERT OR IGNORE", "INSERT"])
    def test_a_raw_rewrite_aborts_loudly_and_changes_nothing(self, tmp_path, verb):
        """Round-2 finding 3: a raw insert that bypasses the module must fail, not
        be silently dropped (the v1 trigger was RAISE(IGNORE))."""
        path = tmp_path / "r.sqlite"
        r = _receipt(body={"v": 1})
        rs.append_receipts([r], path=path)
        conn = rs.connect(path)
        with pytest.raises(sqlite3.DatabaseError, match="never replaced"):
            conn.execute(
                f"{verb} INTO receipts VALUES (?,'OBSERVATION',1,'p','f',NULL,NULL,NULL,'h','{{}}','t')",
                (r.receipt_id,),
            )
        conn.close()
        stored = list(rs.iter_receipts(path))
        assert len(stored) == 1 and stored[0]["body"] == {"v": 1}

    def test_module_rewrites_are_classified_never_dropped(self, tmp_path):
        path = tmp_path / "r.sqlite"
        r = _receipt(body={"v": 1})
        assert rs.append_receipts([r], path=path)["written"] == 1
        same = rs.append_receipts([_receipt(body={"v": 1})], path=path)
        assert (same["written"], same["duplicates"], same["contentConflicts"]) == (0, 1, [])
        clash = rs.append_receipts([_receipt(body={"v": 2})], path=path)
        assert clash["written"] == 0 and clash["duplicates"] == 0
        (conflict,) = clash["contentConflicts"]
        assert conflict["receiptId"] == r.receipt_id
        assert conflict["storedHash"] == r.content_hash()
        assert conflict["incomingHash"] == _receipt(body={"v": 2}).content_hash()
        assert [s["body"] for s in rs.iter_receipts(path)] == [{"v": 1}]

    def test_a_store_of_another_schema_version_is_refused_untouched(self, tmp_path):
        path = tmp_path / "old.sqlite"
        raw = sqlite3.connect(str(path))
        raw.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '1');"
        )
        raw.commit()
        raw.close()
        with pytest.raises(lr.ReceiptError, match="explicit migration"):
            rs.connect(path)
        raw = sqlite3.connect(str(path))
        names = {r[0] for r in raw.execute("SELECT name FROM sqlite_master")}
        raw.close()
        assert "receipts" not in names and "corrections" not in names

    def test_default_store_is_gitignored_data_learning(self):
        assert (
            rs.DEFAULT_STORE_PATH.relative_to(rs.REPO).as_posix() == "data/learning/receipts.sqlite"
        )


# ── A8: drift ───────────────────────────────────────────────────────────────


class TestDrift:
    @pytest.mark.parametrize("cls", lr.DRIFT_CLASSES)
    def test_each_of_the_six_classes_builds_an_inert_receipt(self, cls):
        r = lr.build_drift_receipt(
            producer="test_producer",
            model_family="test_family",
            drift_class=cls,
            signal="coverage fell",
            observed_at=BASE,
            evidence=[_ref(BASE)],
        )
        assert r.kind == lr.KIND_DRIFT
        assert r.body["driftClass"] == cls
        assert r.body["automaticActions"] == []
        assert r.body["response"] == "reevaluation_recommended"

    def test_exactly_six_classes_and_nothing_else(self):
        assert len(lr.DRIFT_CLASSES) == 6
        with pytest.raises(lr.ReceiptError):
            lr.build_drift_receipt(
                producer="p",
                model_family="f",
                drift_class="vibes",
                signal="s",
                observed_at=BASE,
                evidence=[_ref(BASE)],
            )

    def test_drift_needs_evidence(self):
        with pytest.raises(lr.ReceiptError):
            lr.build_drift_receipt(
                producer="p",
                model_family="f",
                drift_class="source",
                signal="s",
                observed_at=BASE,
                evidence=[],
            )

    def test_storing_drift_triggers_nothing(self, tmp_path, monkeypatch):
        """No retrain, refit, evaluation or promotion is reachable from a drift receipt."""
        import src.model_registry.autopilot as autopilot
        import src.model_registry.promotion as promotion
        import src.model_registry.training_run as training_run

        def _boom(*_a, **_k):
            raise AssertionError("drift must trigger nothing")

        for mod, names in (
            (training_run, ("execute", "replay")),
            (promotion, ("decide_promotion",)),
            (autopilot, ("decide", "compose_offense_only")),
        ):
            for name in names:
                monkeypatch.setattr(mod, name, _boom)
        r = lr.build_drift_receipt(
            producer="p",
            model_family="f",
            drift_class="performance",
            signal="holdout error rose",
            observed_at=BASE,
            evidence=[_ref(BASE)],
        )
        out = rs.append_receipts([r], path=tmp_path / "r.sqlite")
        assert out["written"] == 1


# ── corrections: revisions, never overwrites ────────────────────────────────


def _outcome(revision=None, known=BASE + timedelta(days=2)):
    return lr.LearningReceipt(
        kind=lr.KIND_OUTCOME,
        producer="test_producer",
        native_id="game-1",
        model_family="test_family",
        model_version_id=None,
        slots={"result": _ref(known, role=lr.ROLE_OUTCOME)},
        cutoff=BASE,
        target_event_at=BASE + timedelta(days=1),
        revision=revision,
        body={"revision": revision},
    )


class TestCorrections:
    def test_a_corrected_outcome_is_a_new_receipt_not_a_conflict(self, tmp_path):
        path = tmp_path / "r.sqlite"
        orig, fixed = _outcome(), _outcome("stat-correction-1")
        assert orig.receipt_id != fixed.receipt_id
        out = rs.append_receipts([orig, fixed], path=path)
        assert out["written"] == 2 and not out["contentConflicts"]
        assert rs.record_correction(
            orig.receipt_id, fixed.receipt_id, "NFL stat correction", path=path
        ) == {"recorded": True}
        # idempotent
        assert rs.record_correction(
            orig.receipt_id, fixed.receipt_id, "NFL stat correction", path=path
        ) == {"recorded": False}
        all_ids = {r["receiptId"] for r in rs.iter_receipts(path)}
        live_ids = {r["receiptId"] for r in rs.iter_receipts(path, live_only=True)}
        assert all_ids == {orig.receipt_id, fixed.receipt_id}  # the original is retained
        assert live_ids == {fixed.receipt_id}

    def test_a_chain_of_corrections_and_no_fork_or_cycle(self, tmp_path):
        path = tmp_path / "r.sqlite"
        r0, r1, r2, r3 = _outcome(), _outcome("rev1"), _outcome("rev2"), _outcome("rev3")
        rs.append_receipts([r0, r1, r2, r3], path=path)
        rs.record_correction(r0.receipt_id, r1.receipt_id, "first", path=path)
        with pytest.raises(rs.CorrectionError, match="already superseded"):
            rs.record_correction(r0.receipt_id, r2.receipt_id, "fork", path=path)
        with pytest.raises(rs.CorrectionError, match="new, non-empty revision"):
            rs.record_correction(r1.receipt_id, r0.receipt_id, "back to the original", path=path)
        rs.record_correction(r1.receipt_id, r2.receipt_id, "second", path=path)
        with pytest.raises(rs.CorrectionError, match="itself superseded"):
            rs.record_correction(r3.receipt_id, r1.receipt_id, "cycle", path=path)
        live = {r["receiptId"] for r in rs.iter_receipts(path, live_only=True)}
        assert live == {r2.receipt_id, r3.receipt_id}

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_a_correction_needs_a_reason(self, tmp_path, reason):
        with pytest.raises(rs.CorrectionError, match="reason"):
            rs.record_correction("a", "b", reason, path=tmp_path / "r.sqlite")

    def test_a_correction_must_be_a_revision_of_the_same_receipt(self, tmp_path):
        path = tmp_path / "r.sqlite"
        orig = _outcome()
        other = _receipt(native="something-else", body={"x": 1})
        no_rev = _receipt(kind=lr.KIND_OBSERVATION, native="n9")
        rs.append_receipts([orig, other, no_rev, _outcome("r1")], path=path)
        with pytest.raises(rs.CorrectionError, match="same receipt"):
            rs.record_correction(orig.receipt_id, other.receipt_id, "x", path=path)
        with pytest.raises(rs.CorrectionError, match="itself"):
            rs.record_correction(orig.receipt_id, orig.receipt_id, "x", path=path)
        with pytest.raises(rs.CorrectionError, match="missing"):
            rs.record_correction(orig.receipt_id, "rcpt:outcome:nope", "x", path=path)

    def test_corrections_are_append_only_in_the_database(self, tmp_path):
        path = tmp_path / "r.sqlite"
        orig, fixed = _outcome(), _outcome("r1")
        rs.append_receipts([orig, fixed], path=path)
        rs.record_correction(orig.receipt_id, fixed.receipt_id, "fix", path=path)
        conn = rs.connect(path)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE corrections SET reason = 'x'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM corrections")
        with pytest.raises(sqlite3.DatabaseError, match="at most once"):
            conn.execute(
                "INSERT OR REPLACE INTO corrections VALUES (?, ?, 'y', 't')",
                (orig.receipt_id, fixed.receipt_id),
            )
        conn.close()

    def test_an_empty_revision_is_refused(self):
        with pytest.raises(lr.ReceiptError, match="revision"):
            lr.validate_receipt(_outcome("  "))

    # ── round-2 finding 4: the database enforces the correction rules itself ──

    def _stored(self, tmp_path, *revisions):
        path = tmp_path / "r.sqlite"
        rows = [_outcome(rev) for rev in revisions]
        rs.append_receipts(rows, path=path)
        return path, [r.receipt_id for r in rows]

    def _raw_correct(self, path, superseded, superseding):
        conn = rs.connect(path)
        try:
            conn.execute(
                "INSERT INTO corrections VALUES (?, ?, 'raw', 't')", (superseded, superseding)
            )
            conn.commit()
        finally:
            conn.close()

    def test_a_raw_two_cycle_is_aborted_by_the_database(self, tmp_path):
        path, (x, y) = self._stored(tmp_path, None, "r1")
        self._raw_correct(path, x, y)
        with pytest.raises(sqlite3.DatabaseError, match="cannot supersede"):
            self._raw_correct(path, y, x)

    def test_a_raw_superseded_receipt_cannot_supersede(self, tmp_path):
        path, (a, b, c) = self._stored(tmp_path, None, "r1", "r2")
        self._raw_correct(path, a, b)
        with pytest.raises(sqlite3.DatabaseError, match="cannot supersede"):
            self._raw_correct(path, c, a)
        self._raw_correct(path, b, c)  # extending at the head is the legitimate move

    def test_a_raw_self_supersession_is_aborted(self, tmp_path):
        path, (a,) = self._stored(tmp_path, None)
        with pytest.raises(sqlite3.DatabaseError, match="cannot supersede"):
            self._raw_correct(path, a, a)

    def test_foreign_keys_are_enforced_on_every_connection(self, tmp_path):
        path, (a,) = self._stored(tmp_path, None)
        conn = rs.connect(path)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        conn.close()
        with pytest.raises(sqlite3.IntegrityError, match="two stored receipts|FOREIGN KEY"):
            self._raw_correct(path, a, "rcpt:outcome:not-stored")

    # ── round-3 finding D4: existence holds on a RAW connection too ──

    def test_a_raw_connection_cannot_link_a_receipt_that_is_not_stored(self, tmp_path):
        """SQLite enables foreign keys per connection and defaults them OFF, so the
        REFERENCES clauses bind only connections opened by rs.connect. A raw
        connection must still be unable to record a correction naming a ghost —
        otherwise live_only hides the stored receipt behind it."""
        path, (x,) = self._stored(tmp_path, None)
        raw = sqlite3.connect(str(path))
        try:
            assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
            for superseded, superseding in ((x, "ghost"), ("ghost", x), ("ghost", "ghost2")):
                with pytest.raises(sqlite3.IntegrityError, match="two stored receipts"):
                    raw.execute(
                        "INSERT INTO corrections VALUES (?, ?, 'raw', 't')",
                        (superseded, superseding),
                    )
            raw.rollback()
        finally:
            raw.close()
        live = {r["receiptId"] for r in rs.iter_receipts(path, live_only=True)}
        assert live == {x}  # the stored receipt is still live: nothing hid it

    def test_live_only_is_the_newest_revision_in_each_chain(self, tmp_path):
        path, (r0, r1, r2, loose) = self._stored(tmp_path, None, "rev1", "rev2", "unlinked")
        rs.record_correction(r0, r1, "first", path=path)
        rs.record_correction(r1, r2, "second", path=path)
        live = [r["receiptId"] for r in rs.iter_receipts(path, live_only=True)]
        # r0 -> r1 -> r2 collapses to r2; an uncorrected revision is its own chain
        assert sorted(live) == sorted([r2, loose])
        assert len(list(rs.iter_receipts(path))) == 4  # nothing removed
        kind_live = {
            r["receiptId"] for r in rs.iter_receipts(path, kind=lr.KIND_OUTCOME, live_only=True)
        }
        assert kind_live == {r2, loose}

    def test_re_recording_an_older_link_after_the_chain_grew_is_a_noop(self, tmp_path):
        path, (r0, r1, r2) = self._stored(tmp_path, None, "rev1", "rev2")
        rs.record_correction(r0, r1, "first", path=path)
        rs.record_correction(r1, r2, "second", path=path)
        assert rs.record_correction(r0, r1, "first", path=path) == {"recorded": False}
