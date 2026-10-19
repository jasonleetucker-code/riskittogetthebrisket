"""Persistent holdout reserve (G15) -- code only; the real draw happens on the
box after owner decision Q2.  Synthetic component ids only.  Pins: the
committed config is valid and NOT yet approved, the draw refuses to persist
until it is, assignments are deterministic and append-only, a lock is never
lost (merge inheritance, X13), a merge never newly locks trained evidence, and
every read of a sub-reserve is ledgered first."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from src.trade import market_trade_reserve as R

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def cfg():
    return replace(R.load_reserve_config(), status=R.STATUS_APPROVED)


@pytest.fixture
def conn(tmp_path):
    c = R.connect(tmp_path / "model" / "reserve.sqlite")
    yield c
    c.close()


def comps(n, prefix="SYN-C"):
    return {f"{prefix}{i:04d}": [f"m:{prefix}{i:04d}"] for i in range(n)}


def test_committed_config_is_valid_and_awaiting_the_owner():
    c = R.load_reserve_config()
    assert c.status != R.STATUS_APPROVED, "Q2 is an owner decision; never pre-approved"
    assert len(c.salt) == 64 and abs(c.reserve_fraction - 0.2) < 1e-12
    assert {name for name, _ in c.sub_reserves} == {"R-act", "R-hill", "R-D8", "R-AL1", "R-AL2b"}


def test_unapproved_draw_refuses_to_persist(conn):
    with pytest.raises(R.ReserveNotApproved):
        R.draw_reserve(comps(3), conn=conn)
    assert R.assignment_snapshot(conn) == {}


def test_dry_run_writes_nothing_and_needs_no_approval(conn):
    res = R.draw_reserve(comps(50), conn=conn, dry_run=True)
    assert res.dry_run and res.new_assignments == 50
    assert R.assignment_snapshot(conn) == {}


def test_draw_is_deterministic_and_roughly_the_declared_fraction(cfg):
    a = R.draw_reserve(comps(4000), cfg=cfg, dry_run=True).by_assignment
    b = R.draw_reserve(comps(4000), cfg=cfg, dry_run=True).by_assignment
    assert a == b
    locked = sum(v for k, v in a.items() if k != R.TRAIN)
    assert 0.17 < locked / 4000 < 0.23
    assert 0.33 < a["R-act"] / locked < 0.47


def test_a_different_salt_draws_a_different_reserve(cfg):
    other = replace(cfg, salt="0" * 64)
    ids = list(comps(200))
    assert [R.drawn_assignment(i, cfg) for i in ids] != [R.drawn_assignment(i, other) for i in ids]


def test_assignment_is_append_only(conn, cfg):
    R.draw_reserve(comps(100), conn=conn, cfg=cfg)
    before = R.assignment_snapshot(conn)
    # A later draw under a changed fraction cannot move an existing component.
    changed = replace(cfg, reserve_fraction=0.9)
    res = R.draw_reserve(comps(100), conn=conn, cfg=changed)
    assert res.already_assigned == 100 and res.new_assignments == 0
    assert R.assignment_snapshot(conn) == before
    assert R.locked_to_train_violations(before, R.assignment_snapshot(conn)) == []


def test_merge_inherits_a_lock_and_never_newly_locks_train(conn, cfg):
    ids = list(comps(400))
    R.draw_reserve(comps(400), conn=conn, cfg=cfg)
    snap = R.assignment_snapshot(conn)
    locked = next(i for i in ids if snap[i] != R.TRAIN)
    trained = [i for i in ids if snap[i] == R.TRAIN][:2]
    merged = {
        "SYN-MERGED-L": [f"m:{locked}", f"m:{trained[0]}"],
        "SYN-MERGED-T": [f"m:{trained[0]}", f"m:{trained[1]}"],
    }
    res = R.draw_reserve(merged, conn=conn, cfg=cfg)
    after = R.assignment_snapshot(conn)
    assert after["SYN-MERGED-L"] == snap[locked]
    assert after["SYN-MERGED-T"] == R.TRAIN
    assert res.inherited_from_merge == 2


def test_parts_locked_to_different_sub_reserves_conflict_but_stay_locked(conn, cfg):
    ids = list(comps(400))
    R.draw_reserve(comps(400), conn=conn, cfg=cfg)
    snap = R.assignment_snapshot(conn)
    by: dict[str, str] = {}
    for i in ids:
        if snap[i] != R.TRAIN:
            by.setdefault(snap[i], i)
    a, b = list(by.values())[:2]
    res = R.draw_reserve({"SYN-MERGED-X": [f"m:{a}", f"m:{b}"]}, conn=conn, cfg=cfg)
    assert R.assignment_snapshot(conn)["SYN-MERGED-X"] == R.MERGED_CONFLICT
    assert res.merge_conflicts == 1


def test_a_merge_keeping_an_existing_id_cannot_silently_lose_a_lock(conn, cfg):
    # Union-find keeps the smallest member's id, so a merged component often
    # REUSES an assigned id.  Absorbing a differently assigned part must fail
    # closed (dry run: counted), never leave a locked member under train.
    snap = {c: R.drawn_assignment(c, cfg) for c in (f"SYN-{i}" for i in range(200))}
    locked = next(c for c, lbl in snap.items() if lbl != R.TRAIN)
    train = next(c for c, lbl in snap.items() if lbl == R.TRAIN)
    R.draw_reserve({locked: [f"m:{locked}"], train: [f"m:{train}"]}, conn=conn, cfg=cfg)
    merged = {train: [f"m:{train}", f"m:{locked}"]}
    assert R.draw_reserve(merged, conn=conn, cfg=cfg, dry_run=True).absorbed_conflicts == 1
    with pytest.raises(R.ReserveIntegrityError):
        R.draw_reserve(merged, conn=conn, cfg=cfg)
    assert R.assignment_snapshot(conn) == {locked: snap[locked], train: R.TRAIN}


def test_locked_to_train_check_catches_a_lost_lock():
    assert R.locked_to_train_violations({"c1": "R-act", "c2": R.TRAIN}, {"c1": R.TRAIN}) == ["c1"]
    assert R.locked_to_train_violations({"c1": "R-act"}, {}) == ["c1"]


def test_every_read_is_ledgered_first(conn, cfg):
    R.draw_reserve(comps(300), conn=conn, cfg=cfg)
    with pytest.raises(ValueError):
        R.read_sub_reserve(conn, "R-act", hypothesis="", actor="x")
    ids = R.read_sub_reserve(conn, "R-act", hypothesis="X3 activation endpoint", actor="test")
    assert ids and all(R.assignment_snapshot(conn)[i] == "R-act" for i in ids)
    assert R.access_counts(conn) == {"R-act": 1}


def test_config_validation_rejects_ambiguity(tmp_path):
    good = json.loads(R.CONFIG_PATH.read_text())
    for patch in (
        {"salt": "short"},
        {"reserveFraction": 1.5},
        {"subReserves": {"R-act": 0.5, "R-hill": 0.4}},
        {"subReserves": {"train": 1.0}},
    ):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({**good, **patch}))
        with pytest.raises(ValueError):
            R.load_reserve_config(p)


def test_store_is_private_and_writes_only_its_tables(tmp_path):
    p = tmp_path / "model" / "reserve.sqlite"
    R.connect(p).close()
    assert (p.stat().st_mode & 0o077) == 0
    src = (REPO / "src/trade/market_trade_reserve.py").read_text(encoding="utf-8")
    targets = set(re.findall(r"INSERT(?:\s+OR\s+IGNORE)?\s+INTO\s+(\w+)", src, re.I))
    assert targets <= set(R.WRITE_TABLES)
    assert not re.search(r"\b(UPDATE|DELETE\s+FROM)\b", src)


def test_the_default_store_is_gitignored_box_local_data():
    import subprocess

    rel = R.default_path().relative_to(REPO)
    out = subprocess.run(["git", "check-ignore", "-q", str(rel)], cwd=REPO, capture_output=True)
    assert out.returncode == 0, f"{rel} must be gitignored"
