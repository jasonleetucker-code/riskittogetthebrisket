"""``scripts/forced_drop_fix_replay.py --box`` — the read-only production-box mode.

PREPARED, NOT RUN on the box (record ``docs/trade/FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md``).
These tests are synthetic: no network, no board, no application import.  The
audit-hook guard cannot be uninstalled from a process, so it is exercised in a
SUBPROCESS (``--box --box-selftest``, which installs the guard exactly as a real
run does and then attempts the forbidden operations).  The output-safety check,
the pins, the argument refusals and the resource caps live in the stdlib-only
``scripts/forced_drop_box_support.py``.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

if sys.platform == "win32":
    # The box support module imports ``resource`` (POSIX rlimits) at module
    # level and the box mode only runs on the Linux production host.
    # Never skipped on Linux/CI.
    pytest.skip("box mode imports the POSIX-only resource module", allow_module_level=True)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "forced_drop_fix_replay.py"
SUPPORT = REPO / "scripts" / "forced_drop_box_support.py"


def _load_support():
    spec = importlib.util.spec_from_file_location("forced_drop_box_support_t", SUPPORT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forced_drop_box_support_t"] = mod
    spec.loader.exec_module(mod)
    return mod


SUP = _load_support()


# ── the guard, in a subprocess ───────────────────────────────────────────


def test_box_selftest_refuses_writes_outside_scratch_network_and_processes(tmp_path):
    env = {**os.environ, "RISKIT_APP_DIR": str(REPO)}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--box", "--box-selftest"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["guardInstalled"] is True
    # Forbidden: writing or creating anything outside the private scratch dir,
    # the network, a subprocess, a read-write SQLite database.
    assert report["writeOutsideScratch"] == "refused"
    assert report["mkdirOutsideScratch"] == "refused"
    assert report["networkConnect"] == "refused"
    assert report["subprocess"] == "refused"
    assert report["sqliteReadWrite"] == "refused"
    # Allowed: the guard's own scratch directory.
    assert report["writeInsideScratch"] == "allowed"
    refused = set(report["refusedEvents"])
    assert "open" in refused and "subprocess.Popen" in refused
    assert any(e.startswith("socket.") for e in refused)
    # And nothing actually landed outside the scratch directory.
    tmp_root = Path(os.environ.get("TMPDIR") or "/tmp")
    assert not (tmp_root / ".fdr_selftest").exists()
    assert not (tmp_root / ".fdr_selftest_dir").exists()


def test_guard_is_installed_before_any_application_import():
    """Source order: the guard install precedes every ``src`` import of the
    script (the whole point of installing it at module top)."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    install_line = None
    first_src_import = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "install"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "GUARD"
        ):
            install_line = min(install_line or node.lineno, node.lineno)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src"):
            first_src_import = min(first_src_import or node.lineno, node.lineno)
    assert install_line is not None and first_src_import is not None
    assert install_line < first_src_import
    # ... and so does the loading of every sibling script that imports the app.
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.index("GUARD.install()") < text.index('D = _load("low_value_asset_forced_drop')


def test_box_main_writes_no_file_and_prints_only_the_aggregate_report():
    """``box_main`` is stdout-only: no ``open``/``write_text``/``write_bytes``/
    ``mkdir`` call anywhere in it, and the report is written with ``sys.stdout``
    only after ``assert_box_output_safe`` passed."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    box_main = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "box_main"
    )
    banned = {"open", "write_text", "write_bytes", "mkdir", "makedirs", "unlink", "rename"}
    for node in ast.walk(box_main):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            assert name not in banned, f"box_main calls {name}"
    src = ast.get_source_segment(SCRIPT.read_text(encoding="utf-8"), box_main)
    assert src.index("assert_box_output_safe") < src.index("sys.stdout.write")
    assert "EXIT_OUTPUT_REFUSED" in src


# ── non-aggregate output is refused ──────────────────────────────────────

CONTRACT = {
    "sleeper": {
        "leagueId": "1234567890123456789",
        "teams": [
            {"name": "Gridiron Gurus", "ownerId": "98765432109876543", "rosterId": 3},
            {
                "name": "Fourth And Long",
                "username": "someManager77",
                "ownerId": "11122233344455566",
            },
        ],
    }
}


def _ok_result():
    return {
        "census": {"counts": {"trades": 278, "publicCategoryChanged": 125}},
        "scarcityObserved": {"min": 0.9, "max": 1.12, "inert": False},
        "provenance": {
            "deployedCodeSha": "a" * 40,
            "archiveSha256": "b" * 64,
            "archiveMemberSha256": "f" * 64,
            "csvRev": "e" * 40,
            "builtBoardSha256": "c" * 64,
            "configSha256": {"config/trade/package_model.json": "d" * 64},
            "pinsMatch": True,
        },
        "note": "Quan Martin (DB, 227) is an NFL player name and is allowed",
    }


def test_an_aggregate_report_is_accepted():
    SUP.assert_box_output_safe(_ok_result(), forbidden=SUP.forbidden_tokens(CONTRACT))


def test_forbidden_tokens_come_from_the_replayed_contract():
    tokens = SUP.forbidden_tokens(CONTRACT)
    assert {"1234567890123456789", "Gridiron Gurus", "Fourth And Long", "someManager77"} <= tokens
    assert "98765432109876543" in tokens
    assert "3" not in tokens  # a short roster index is a number, not an identity


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["census"].update(ownerId="x"),  # identifier key
        lambda r: r["census"].update(displayName="x"),
        lambda r: r["census"].update(note="league 1234567890123456789"),  # 9+ digit id
        lambda r: r["census"].update(note="owned by Gridiron Gurus"),  # team name
        lambda r: r["census"].update(note="manager someManager77"),  # username
        lambda r: r["census"].update(digest="e" * 64),  # long hex outside provenance
        lambda r: r["census"].update(blob="x" * 5000),  # a dumped payload
        lambda r: r["census"].update(asset="player:12345"),  # canonical asset id
        lambda r: r["provenance"].update(archiveSha256="not-a-digest"),  # malformed pin
        lambda r: r["provenance"]["configSha256"].update(f="zz"),  # malformed map value
        lambda r: r["census"].update({"Gridiron Gurus": 1}),  # team name as a key
    ],
)
def test_a_non_aggregate_report_is_refused_without_echoing_the_value(mutate):
    result = _ok_result()
    mutate(result)
    with pytest.raises(SUP.OutputRefused) as exc:
        SUP.assert_box_output_safe(result, forbidden=SUP.forbidden_tokens(CONTRACT))
    message = str(exc.value)
    for secret in ("Gridiron Gurus", "someManager77", "1234567890123456789", "98765432109876543"):
        assert secret not in message


# ── pins and arguments ───────────────────────────────────────────────────


def _args(**kw):
    base = dict(
        box=True, box_selftest=False, out=None, archive="exports/archive/x.zip",
        archive_sha256="a" * 64, csv_root="/tmp/fdr-csv", csv_rev="d" * 40,
        csv_tree_sha256="b" * 64, expect_code_sha="c" * 40,
    )  # fmt: skip
    base.update(kw)
    return Namespace(**base)


def test_box_arguments_require_every_pin_and_refuse_out():
    assert SUP.validate_box_args(_args()) == []
    assert any("--out" in p for p in SUP.validate_box_args(_args(out="x.json")))
    for flag in ("archive", "archive_sha256", "csv_root", "csv_rev", "csv_tree_sha256",
                 "expect_code_sha"):  # fmt: skip
        problems = SUP.validate_box_args(_args(**{flag: None}))
        assert any(flag.replace("_", "-") in p for p in problems), flag
    assert any("ABSOLUTE" in p for p in SUP.validate_box_args(_args(csv_root="relative/dir")))


def test_pin_mismatches_fail_closed():
    observed = {"archiveSha256": "a", "csvTreeSha256": "b", "codeSha": None}
    assert SUP.pin_mismatches(observed, {"archiveSha256": "a", "csvTreeSha256": "b"}) == []
    assert SUP.pin_mismatches(observed, {"archiveSha256": "x"}) == ["archiveSha256"]
    # An unreadable pin is not a match; an unprovided expectation is not checked.
    assert SUP.pin_mismatches(observed, {"codeSha": "c" * 40}) == ["codeSha"]
    assert SUP.pin_mismatches(observed, {"codeSha": None}) == []


def test_tree_digest_is_content_pinned_and_order_independent(tmp_path):
    (tmp_path / "CSVs").mkdir()
    (tmp_path / "config" / "weights").mkdir(parents=True)
    (tmp_path / "CSVs" / "a.csv").write_text("1,2\n", encoding="utf-8")
    (tmp_path / "config" / "weights" / "w.json").write_text("{}", encoding="utf-8")
    paths = ("CSVs", "data/scrape_state", "config/weights")
    d1 = SUP.tree_content_sha256(tmp_path, paths)

    # The replay's digest definition, written independently here.
    h = hashlib.sha256()
    for top in paths:
        base = tmp_path / top
        if base.exists():
            for p in sorted(x for x in base.rglob("*") if x.is_file()):
                h.update(p.relative_to(tmp_path).as_posix().encode() + b"\0")
                h.update(hashlib.sha256(p.read_bytes()).digest())
    assert d1 == h.hexdigest()
    (tmp_path / "CSVs" / "a.csv").write_text("1,3\n", encoding="utf-8")
    assert SUP.tree_content_sha256(tmp_path, paths) != d1


def test_config_hashes_record_a_missing_file_instead_of_guessing(tmp_path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    out = SUP.config_hashes(tmp_path, ["a.json", "b.json"])
    assert out["a.json"] == hashlib.sha256(b"{}").hexdigest()
    assert out["b.json"] == "NOT_PROVIDED"


# ── resource caps (in a subprocess: rlimits are process-wide) ────────────


def test_memory_cap_stops_an_over_allocation():
    code = (
        "import importlib.util,sys;"
        f"s=importlib.util.spec_from_file_location('sup',{str(SUPPORT)!r});"
        "m=importlib.util.module_from_spec(s);sys.modules['sup']=m;s.loader.exec_module(m);"
        "caps=m.apply_resource_caps(max_mem_gib=1.5,max_cpu_seconds=600,wall_seconds=600);"
        "assert caps['addressSpaceGiB']==1.5;"
        "\ntry:\n    bytearray(3<<30)\n    print('allocated')\nexcept MemoryError:\n    print('capped')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert proc.stdout.strip().endswith("capped")


def test_wall_clock_cap_raises_timeout():
    code = (
        "import importlib.util,sys,time;"
        f"s=importlib.util.spec_from_file_location('sup',{str(SUPPORT)!r});"
        "m=importlib.util.module_from_spec(s);sys.modules['sup']=m;s.loader.exec_module(m);"
        "m.apply_resource_caps(max_mem_gib=2,max_cpu_seconds=600,wall_seconds=1);"
        "\ntry:\n    time.sleep(5)\n    print('slept')\nexcept TimeoutError:\n    print('timeout')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert proc.stdout.strip().endswith("timeout")


# ── 2026-10-21 review follow-up: V5 vs V5-R regret and tie census ─────────


def _pure_helpers():
    """The replay's pure regret helpers, extracted by name and run in
    isolation (no application import, same posture as the tests above)."""
    import statistics
    from collections import Counter

    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {
        "_r", "_match_pool", "_sum_c", "_incoming_above_own_c", "_tie_of",
        "regret_row", "_dist", "_regret_summary",
    }  # fmt: skip
    ns = {"statistics": statistics, "Counter": Counter}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module([node], []), str(SCRIPT), "exec"), ns)  # noqa: S102
    assert names <= set(ns), names - set(ns)
    return ns


def _pool():
    # name, acquired flag, release value c
    return [
        {"name": "keep", "acquired": False, "release": 900.0},
        {"name": "e1", "acquired": False, "release": 500.0},
        {"name": "inc", "acquired": True, "release": 700.0},
    ]


def test_regret_summary_measures_both_directions_and_flags_wrong_signs():
    h = _pure_helpers()
    pool = _pool()
    # (name, pos, value, releaseCost/charge, acquired) as drops_of() emits
    v5 = [("inc", "WR", 700.0, 426.0, True)]  # V5 releases the dearer incoming piece
    v5r = [("e1", "WR", 500.0, 500.0, False)]  # V5-R releases the cheaper existing one
    row = h["regret_row"](pool, v5, v5r, 426.0, 500.0, 6000.0, None)
    out = h["_regret_summary"]([row])
    assert out["assetValueRegretV5MinusV5R"]["median"] == 200.0
    assert out["chargeRegretV5RMinusV5"]["median"] == 74.0
    assert out["chargeRegretPctOfBandBase"]["median"] == round(100 * 74 / 6000, 1)
    assert out["assetValueRegretV5MinusV5R"]["negativeDefect"] == 0
    assert out["chargeRegretV5RMinusV5"]["negativeDefect"] == 0
    # A V5-R set with a HIGHER sum c, or a LOWER charge than V5, is a defect
    # and must be counted, never averaged away.
    bad = h["regret_row"](pool, v5r, v5, 500.0, 426.0, 6000.0, None)
    out = h["_regret_summary"]([bad])
    assert out["assetValueRegretV5MinusV5R"]["negativeDefect"] == 1
    assert out["chargeRegretV5RMinusV5"]["negativeDefect"] == 1


def test_tie_census_and_incoming_charged_above_own_c():
    h = _pure_helpers()
    pool = _pool()
    over = [("inc", "WR", 700.0, 760.0, True)]  # charged above its own c (700)
    tie = {"tiedMinimumSets": 2, "chargeSpread": 220.0, "resolvedBy": "lowest_charge"}
    out = h["_regret_summary"]([h["regret_row"](pool, over, over, 760.0, 760.0, 0, tie)])
    assert out["incomingChargedAboveOwnC"] == {"V5": 1, "V5-R": 1}
    assert out["tieCensusV5R"]["tieBreakApplied"] == 1
    assert out["tieCensusV5R"]["resolvedBy"] == {"lowest_charge": 1}
    assert out["tieCensusV5R"]["chargeSpread"]["max"] == 220.0
    # Unmatched drops are counted, not silently treated as zero.
    out = h["_regret_summary"](
        [h["regret_row"](pool, [("ghost", "WR", 1.0, 1.0, False)], over, 1.0, 760.0, 0, None)]
    )
    assert out["assetValueRegretV5MinusV5R"]["unmatched"] == 1


def test_box_report_carries_the_review_follow_up_fields():
    src = SCRIPT.read_text(encoding="utf-8")
    for key in ('"unpricedRosterCensus"', '"v5VsRosterRationalRegret"', '"interplay"'):
        assert key in src, key
