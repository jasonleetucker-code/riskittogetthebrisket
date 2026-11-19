"""Opt-in off-box copy + restore drill (scripts/offbox_backup.py), local-dir target."""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "offbox_backup", REPO / "scripts" / "offbox_backup.py"
)
ob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ob)  # type: ignore[union-attr]
VERIFIER = ob._load_verifier()


def _make_generation(root: Path, stamp: str = "2026-11-18") -> Path:
    gen = root / "daily" / stamp
    (gen / "sqlite").mkdir(parents=True)
    (gen / "dirs").mkdir()
    db = root / "src.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table t(x)")
    con.execute("insert into t values (1)")
    con.commit()
    con.close()
    with open(db, "rb") as fin, gzip.open(gen / "sqlite" / "user_kv.sqlite.gz", "wb") as fout:
        shutil.copyfileobj(fin, fout)
    with tarfile.open(gen / "dirs" / "faab.tar.gz", "w:gz") as tar:
        data = b"hello"
        info = tarfile.TarInfo("a.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return gen


@pytest.fixture()
def env(tmp_path):
    gen = _make_generation(tmp_path / "local")
    return gen, tmp_path / "remote"


def test_disabled_without_target(capsys):
    assert ob.main(["copy"], env={}) == 0
    assert "disabled" in capsys.readouterr().out


def test_refuses_without_encryption_ack(env):
    gen, remote = env
    argv = ["copy", "--target", f"dir:{remote}", "--generation", str(gen)]
    assert ob.main(argv, env={}) == 1
    assert not remote.exists()


def test_copy_then_drill_roundtrip(env, capsys):
    gen, remote = env
    e = {ob.ENV_ACK: "1"}
    assert (
        ob.main(["copy", "--target", f"dir:{remote}", "--generation", str(gen), "--json"], env=e)
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["files"] == 2 and out["generation"] == "2026-11-18"
    assert (remote / "daily" / "2026-11-18" / ob.MANIFEST_NAME).is_file()
    assert ob.main(["drill", "--target", f"dir:{remote}", "--json"], env=e) == 0
    drill = json.loads(capsys.readouterr().out)
    assert drill["ok"] and drill["restore_verified"] == 2


def test_copy_refuses_corrupt_source(env):
    gen, remote = env
    (gen / "dirs" / "faab.tar.gz").write_bytes(b"not a tarball")
    argv = ["copy", "--target", f"dir:{remote}", "--generation", str(gen)]
    assert ob.main(argv, env={ob.ENV_ACK: "1"}) == 1
    assert not (remote / "daily").exists()


def test_copy_detects_corruption_on_target(env):
    gen, remote = env

    class Flaky(ob.DirTarget):
        def put_tree(self, src, name):
            super().put_tree(src, name)
            victim = self._gen(name) / "dirs" / "faab.tar.gz"
            victim.write_bytes(victim.read_bytes() + b"x")

    with pytest.raises(ob.OffboxError, match="did not verify"):
        ob.copy_newest(Flaky(remote), gen, verifier=VERIFIER)


def test_drill_detects_tampered_remote(env):
    gen, remote = env
    target = ob.DirTarget(remote)
    ob.copy_newest(target, gen, verifier=VERIFIER)
    victim = remote / "daily" / gen.name / "sqlite" / "user_kv.sqlite.gz"
    victim.write_bytes(victim.read_bytes()[:-4] + b"zzzz")
    with pytest.raises(ob.OffboxError, match="manifest"):
        ob.run_drill(target, verifier=VERIFIER)


def test_drill_requires_our_manifest(env):
    gen, remote = env
    shutil.copytree(gen, remote / "daily" / gen.name)
    with pytest.raises(ob.OffboxError, match=ob.MANIFEST_NAME):
        ob.run_drill(ob.DirTarget(remote), verifier=VERIFIER)


def test_drill_empty_target_is_exit_2(tmp_path):
    rc = ob.main(["drill", "--target", f"dir:{tmp_path / 'nothing'}"], env={ob.ENV_ACK: "1"})
    assert rc == 2


def test_drill_never_restores_into_protected_paths(env, tmp_path):
    gen, remote = env
    target = ob.DirTarget(remote)
    ob.copy_newest(target, gen, verifier=VERIFIER)
    with pytest.raises(ob.OffboxError, match="protected"):
        ob.run_drill(
            target,
            verifier=VERIFIER,
            scratch_parent=str(tmp_path),
            extra_protected=[str(tmp_path)],
        )
    assert not list(tmp_path.glob("riskit-offbox-drill-*"))


def test_bad_target_specs():
    for bad in ("", "dir:relative/path", "ftp:host/x", "rclone:"):
        with pytest.raises(ob.OffboxError):
            ob.parse_target(bad)


def test_rclone_target_commands_have_no_delete_and_roundtrip(env):
    """A fake rclone that maps ``r:`` onto a local dir proves the call shapes."""
    gen, remote = env
    calls: list[list[str]] = []

    def real(p: str) -> Path:
        return remote / p.split(":", 1)[1].lstrip("/") if p.startswith("r:") else Path(p)

    def fake(cmd):
        calls.append(list(cmd))
        sub = cmd[1]
        if sub == "copy":
            shutil.copytree(real(cmd[2]), real(cmd[3]), dirs_exist_ok=True)
        elif sub == "copyto":
            dst = real(cmd[3])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(real(cmd[2]), dst)
        elif sub == "lsf":
            d = real(cmd[-1])
            out = "".join(f"{p.name}/\n" for p in sorted(d.iterdir())) if d.is_dir() else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    target = ob.parse_target("rclone:r:bk", runner=fake)
    assert ob.copy_newest(target, gen, verifier=VERIFIER)["ok"]
    assert ob.run_drill(target, verifier=VERIFIER)["ok"]
    flat = " ".join(" ".join(c) for c in calls)
    assert "delete" not in flat and "sync" not in flat and "purge" not in flat


def test_rsync_commands_never_use_delete():
    seen: list[list[str]] = []

    def fake(cmd):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    t = ob.parse_target("rsync:u@h:bk", runner=fake)
    t.put_tree(Path("/x"), "2026-11-18")
    t.get_tree("2026-11-18", Path("/y"))
    assert all("--delete" not in c for c in seen)
    assert all("BatchMode=yes" in " ".join(c) for c in seen)


def test_timer_examples_are_not_auto_installed():
    d = REPO / "deploy" / "backup" / "offbox"
    names = sorted(p.name for p in d.iterdir())
    assert names and all(n.endswith(".example") for n in names)
    assert not list((REPO / "deploy" / "systemd").glob("*offbox*"))


# ── review fixes: target must not overlap the source; read-back space ───────
@pytest.mark.parametrize("where", ["root", "daily", "gen", "inside_root"])
def test_dir_target_overlapping_source_is_refused(env, where):
    gen, _ = env
    root = gen.parent.parent
    tgt = {"root": root, "daily": root / "daily", "gen": gen, "inside_root": root / "sub"}[where]
    argv = ["copy", "--target", f"dir:{tgt}", "--generation", str(gen), "--root", str(root)]
    before = sorted(p.name for p in gen.rglob("*"))
    assert ob.main(argv, env={ob.ENV_ACK: "1"}) == 1
    assert sorted(p.name for p in gen.rglob("*")) == before  # source untouched


def test_local_rsync_target_overlapping_source_is_refused(env):
    gen, _ = env
    tgt = ob.CommandTarget("rsync", str(gen.parent.parent), runner=lambda c: None)
    with pytest.raises(ob.OffboxError, match="refusing"):
        ob.copy_newest(tgt, gen, verifier=VERIFIER, roots=[str(gen.parent.parent)])


def test_remote_rsync_target_is_not_treated_as_local(env):
    gen, _ = env
    tgt = ob.CommandTarget("rsync", "me@host:/srv/x", runner=lambda c: None)
    assert tgt.local_root() is None
    ob.assert_target_disjoint(tgt, gen)


def test_protected_prefix_target_is_refused(env):
    gen, _ = env
    with pytest.raises(ob.OffboxError, match="refusing"):
        ob.assert_target_disjoint(ob.DirTarget(Path("/etc/offbox")), gen)


def test_readback_fails_closed_without_free_space(env, monkeypatch):
    gen, remote = env
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 10, 0))
    with pytest.raises(ob.OffboxError, match="temp space"):
        ob.copy_newest(ob.DirTarget(remote), gen, verifier=VERIFIER, roots=[str(gen.parent.parent)])
    assert not (remote / "daily" / gen.name).exists()  # nothing uploaded


def test_docstring_does_not_claim_nothing_is_deleted():
    assert "Nothing is ever" not in ob.__doc__
    assert "previous copy" in ob.__doc__


def test_verified_copy_records_a_health_marker_without_the_destination(env, capsys):
    gen, remote = env
    e = {ob.ENV_ACK: "1"}
    argv = ["copy", "--target", f"dir:{remote}", "--generation", str(gen), "--json"]
    assert ob.main(argv, env=e) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["health_marker"] == "ok"
    marker = (gen.parent.parent / "last_mirror").read_text(encoding="utf-8")
    assert "mirrored_at=" in marker and "generation=2026-11-18" in marker
    assert "dest=offbox_copy:dir" in marker
    assert str(remote) not in marker  # the destination never lands in the marker


def test_failed_copy_leaves_the_marker_untouched(env):
    gen, remote = env
    e = {ob.ENV_ACK: "1"}
    marker = gen.parent.parent / "last_mirror"
    marker.write_text("schema=1\nmirrored_at=2026-01-01T00:00:00Z\n", encoding="utf-8")
    (gen / "sqlite" / "user_kv.sqlite.gz").write_bytes(b"corrupt")
    argv = ["copy", "--target", f"dir:{remote}", "--generation", str(gen)]
    assert ob.main(argv, env=e) == 1
    assert "2026-01-01" in marker.read_text(encoding="utf-8")


def _dump_runner(payload: str, rc: int = 0):
    def run(cmd):
        return subprocess.CompletedProcess(cmd, rc, payload, "")

    return run


def test_encryption_evidence_is_observed_only_for_an_rclone_crypt_remote():
    crypt = _dump_runner('{"sec": {"type": "crypt", "password": "OBSCURED"}, "b2": {"type": "b2"}}')
    assert ob.parse_target("rclone:sec:bk", runner=crypt).encryption_evidence() == (
        "rclone_crypt_remote"
    )
    assert ob.parse_target("rclone:b2:bk", runner=crypt).encryption_evidence() == "not_verified"
    assert ob.parse_target("rclone:ghost:bk", runner=crypt).encryption_evidence() == "not_verified"
    for bad in (_dump_runner("not json"), _dump_runner("{}", rc=1)):
        assert ob.parse_target("rclone:sec:bk", runner=bad).encryption_evidence() == "not_verified"
    assert ob.parse_target("rsync:u@h:p", runner=crypt).encryption_evidence() == "not_verified"
    # the credential-bearing dump is never echoed
    assert "OBSCURED" not in repr(ob.parse_target("rclone:sec:bk", runner=crypt).describe())


def test_marker_write_failure_is_reported_not_fatal(env):
    gen, _ = env
    bad = gen.parent.parent.parent / "afile"  # a file where a directory is needed
    bad.write_text("x", encoding="utf-8")
    fake = bad / "daily" / "2026-11-18"
    result = ob.record_copy_marker(fake, {"target": "dir:/x"}, generations=1)
    assert result.startswith("not recorded")
