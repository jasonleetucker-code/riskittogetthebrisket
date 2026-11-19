#!/usr/bin/env python3
"""Opt-in, provider-independent off-box copy of the newest VERIFIED state backup.

Two subcommands, stdlib only, one file (the nightly unit runs as root, so the
owner installs a root-owned copy of this file AND ``verify_state_backup_restore.py``
side by side under /usr/local/lib/riskit/ - never the checkout copy, same rule as
``deploy/backup/riskit-state-backup.sh``):

``copy``   pick the newest dated generation, restore-verify it locally, copy it to
           the owner's target, then prove the copy: every file is re-read from the
           target and its SHA-256 must equal the local one.  No ``--delete`` is
           ever passed and nothing outside this tool's own output is touched; the
           ONE thing replaced is this generation's own previous copy on a ``dir:``
           target (a same-day re-copy ``rmtree``s ``daily/<date>`` there before
           renaming the fresh copy in).  Because that is a delete, a ``dir:`` (or
           local-path rsync) target equal to or under any source/backup root or
           protected path is refused, and the read-back needs free temp space for
           the whole generation (checked first; fail closed).  Pruning older
           generations is the owner's call.
``drill``  pull the newest (or a named) generation FROM the target into a fresh
           temp directory, check every hash against the manifest, then run the same
           restore verification the nightly proof uses.  Never writes a production
           path: scratch under the app data dir or a backup root is refused.

DISABLED unless ``OFFBOX_BACKUP_TARGET`` is set.  Unset -> ``copy`` prints
``disabled`` and exits 0 (a timer that is installed before the owner configures a
target must not look like a failure).  No provider is chosen here.

Target grammar (``OFFBOX_BACKUP_TARGET`` or ``--target``):

  dir:/abs/path          a directory (mounted disk, NFS, sshfs, restic-fuse ...)
  rsync:user@host:path   rsync over non-interactive ssh  (needs rsync)
  rclone:remote:path     any rclone remote, ideally a ``crypt`` remote (needs rclone)

The generation holds session cookies and login state (secrets).  A target is
refused unless the owner states it is encrypted at rest:
``OFFBOX_BACKUP_ACK_ENCRYPTED_TARGET=1`` (or ``--ack-encrypted-target``).  That is
an acknowledgement the owner makes, not something this script can verify.

Exit: 0 ok / disabled, 1 failure, 2 no generation / nothing on the target.
Never prints a secret: only paths, sizes, counts and the first 12 hex of hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_TARGET = "OFFBOX_BACKUP_TARGET"
ENV_ACK = "OFFBOX_BACKUP_ACK_ENCRYPTED_TARGET"
MANIFEST_NAME = "OFFBOX_MANIFEST.json"
MANIFEST_SCHEMA = 1
DEFAULT_ROOTS = ("/var/backups/riskit-state", "/home/dynasty/backups/riskit-state")
# Paths a drill must never restore into (prefix match on the resolved scratch dir).
PROTECTED_PREFIXES = (
    "/home/dynasty/trade-calculator",
    "/var/backups/riskit-state",
    "/home/dynasty/backups",
    "/usr/local/lib/riskit",
    "/etc",
)
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHUNK = 1 << 20

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class OffboxError(Exception):
    """A refusal or failure; the message is safe to print."""


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


# ── target ──────────────────────────────────────────────────────────────────
class Target:
    """One place generations are copied to. Subclasses move whole trees."""

    kind = "abstract"

    def put_tree(self, src: Path, name: str) -> None:
        raise NotImplementedError

    def put_file(self, src: Path, name: str, relpath: str) -> None:
        raise NotImplementedError

    def get_tree(self, name: str, dest: Path) -> None:
        raise NotImplementedError

    def list_generations(self) -> list[str]:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def local_root(self) -> Path | None:
        """The local filesystem root this target writes under, if it is local."""
        return None


class DirTarget(Target):
    kind = "dir"

    def __init__(self, root: Path):
        self.root = root

    def describe(self) -> str:
        return f"dir:{self.root}"

    def local_root(self) -> Path | None:
        return self.root

    def _gen(self, name: str) -> Path:
        return self.root / "daily" / name

    def put_tree(self, src: Path, name: str) -> None:
        final = self._gen(name)
        part = final.with_name(final.name + ".partial")
        final.parent.mkdir(parents=True, exist_ok=True)
        if part.exists():
            shutil.rmtree(part)
        shutil.copytree(src, part)
        if final.exists():
            # Same-day re-copy: replace only OUR previous copy of this name.
            shutil.rmtree(final)
        part.rename(final)

    def put_file(self, src: Path, name: str, relpath: str) -> None:
        dest = self._gen(name) / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    def get_tree(self, name: str, dest: Path) -> None:
        src = self._gen(name)
        if not src.is_dir():
            raise OffboxError(f"generation {name} not found on target")
        shutil.copytree(src, dest, dirs_exist_ok=True)

    def list_generations(self) -> list[str]:
        daily = self.root / "daily"
        try:
            return sorted(n for n in os.listdir(daily) if _DATED.match(n) and (daily / n).is_dir())
        except OSError:
            return []


class CommandTarget(Target):
    """rsync/ssh and rclone share one shape: shell out, never ``--delete``."""

    def __init__(self, kind: str, spec: str, runner: Runner = _run):
        self.kind = kind
        self.spec = spec.rstrip("/")
        self._run = runner
        binary = "rsync" if kind == "rsync" else "rclone"
        if runner is _run and shutil.which(binary) is None:
            raise OffboxError(f"{binary} is not installed on this host")

    def describe(self) -> str:
        return f"{self.kind}:{self.spec}"

    def local_root(self) -> Path | None:
        # rsync:/abs/path (no host part) writes to the local disk.
        if self.kind == "rsync" and ":" not in self.spec and self.spec.startswith("/"):
            return Path(self.spec)
        return None

    def encryption_evidence(self) -> str:
        """What this tool can OBSERVE about encryption at rest, never a claim.

        ``rclone_crypt_remote`` only when ``rclone config dump`` says the remote is
        type ``crypt``.  The dump is parsed in memory for that one field and never
        printed (it holds obscured credentials).  Everything else, rsync included,
        is ``not_verified``: the owner's acknowledgement remains the only evidence.
        """
        if self.kind != "rclone":
            return "not_verified"
        name = self.spec.split(":", 1)[0]
        try:
            proc = self._run(["rclone", "config", "dump"])
            remotes = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
            kind = remotes.get(name, {}).get("type") if isinstance(remotes, dict) else None
        except (ValueError, AttributeError, OSError):
            return "not_verified"
        return "rclone_crypt_remote" if kind == "crypt" else "not_verified"

    def _remote(self, *parts: str) -> str:
        return "/".join([self.spec, *parts])

    def _check(self, proc: "subprocess.CompletedProcess[str]", what: str) -> None:
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
            raise OffboxError(
                f"{self.kind} {what} failed (exit {proc.returncode}): {tail[0][:200]}"
            )

    def put_tree(self, src: Path, name: str) -> None:
        dest = self._remote("daily", name)
        if self.kind == "rsync":
            cmd = ["rsync", "-a", "--partial", "-e", "ssh -o BatchMode=yes", f"{src}/", f"{dest}/"]
        else:
            cmd = ["rclone", "copy", str(src), dest]
        self._check(self._run(cmd), "upload")

    def put_file(self, src: Path, name: str, relpath: str) -> None:
        parent = "/".join(["daily", name, *relpath.split("/")[:-1]])
        dest = self._remote(parent)
        if self.kind == "rsync":
            cmd = ["rsync", "-a", "-e", "ssh -o BatchMode=yes", str(src), f"{dest}/"]
        else:
            cmd = ["rclone", "copyto", str(src), self._remote("daily", name, relpath)]
        self._check(self._run(cmd), "manifest upload")

    def get_tree(self, name: str, dest: Path) -> None:
        remote = self._remote("daily", name)
        if self.kind == "rsync":
            cmd = ["rsync", "-a", "-e", "ssh -o BatchMode=yes", f"{remote}/", f"{dest}/"]
        else:
            cmd = ["rclone", "copy", remote, str(dest)]
        self._check(self._run(cmd), "download")

    def list_generations(self) -> list[str]:
        remote = self._remote("daily")
        if self.kind == "rsync":
            cmd = ["rsync", "-e", "ssh -o BatchMode=yes", f"{remote}/"]
            proc = self._run(cmd)
            if proc.returncode != 0:
                return []
            names = [ln.split()[-1] for ln in proc.stdout.splitlines() if ln.startswith("d")]
        else:
            proc = self._run(["rclone", "lsf", "--dirs-only", remote])
            if proc.returncode != 0:
                return []
            names = [ln.strip().rstrip("/") for ln in proc.stdout.splitlines()]
        return sorted(n for n in names if _DATED.match(n))


def parse_target(spec: str, runner: Runner = _run) -> Target:
    kind, sep, rest = (spec or "").partition(":")
    if not sep or not rest:
        raise OffboxError(
            "target must look like dir:/path, rsync:user@host:path or rclone:remote:path"
        )
    if kind == "dir":
        path = Path(rest)
        if not path.is_absolute():
            raise OffboxError("dir: target must be an absolute path")
        return DirTarget(path)
    if kind in ("rsync", "rclone"):
        return CommandTarget(kind, rest, runner)
    raise OffboxError(f"unknown target kind {kind!r}")


# ── hashing / manifest ──────────────────────────────────────────────────────
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_manifest(gen: Path) -> dict[str, Any]:
    files = []
    for p in sorted(gen.rglob("*")):
        if p.is_file() and p.name != MANIFEST_NAME:
            files.append(
                {
                    "path": p.relative_to(gen).as_posix(),
                    "size": p.stat().st_size,
                    "sha256": sha256_file(p),
                }
            )
    return {
        "schema": MANIFEST_SCHEMA,
        "generation": gen.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def compare_to_manifest(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Problems found re-reading ``root`` against ``manifest`` (empty = identical)."""
    problems: list[str] = []
    expected = {f["path"]: f for f in manifest.get("files", [])}
    if not expected:
        return ["manifest lists no files"]
    for rel, meta in expected.items():
        p = root / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif p.stat().st_size != meta["size"]:
            problems.append(f"size mismatch {rel}")
        elif sha256_file(p) != meta["sha256"]:
            problems.append(f"hash mismatch {rel}")
    present = {
        q.relative_to(root).as_posix()
        for q in root.rglob("*")
        if q.is_file() and q.name != MANIFEST_NAME
    }
    for rel in sorted(present - set(expected)):
        problems.append(f"unexpected {rel}")
    return problems


# ── generation + local verification ─────────────────────────────────────────
def _load_verifier(path: Path | None = None) -> Any:
    here = path or Path(__file__).resolve().with_name("verify_state_backup_restore.py")
    if not here.is_file():
        raise OffboxError(f"restore verifier not found beside this script: {here}")
    spec = importlib.util.spec_from_file_location("_riskit_state_verifier", here)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def newest_generation(roots: Sequence[str]) -> Path | None:
    best: Path | None = None
    for root in roots:
        daily = Path(root) / "daily"
        try:
            names = sorted(n for n in os.listdir(daily) if _DATED.match(n))
        except OSError:
            continue
        for name in reversed(names):
            if (daily / name).is_dir():
                if best is None or name > best.name:
                    best = daily / name
                break
    return best


def _verify_tree(gen: Path, *, verifier: Any, full: bool) -> dict[str, Any]:
    scratch = Path(tempfile.mkdtemp(prefix="riskit-offbox-verify-"))
    try:
        return verifier.verify_generation(gen, scratch, full=full)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def require_ack(env: dict[str, str], flag: bool) -> None:
    if flag or env.get(ENV_ACK, "") in ("1", "true", "yes"):
        return
    raise OffboxError(
        "refusing: the backup holds session secrets. Set "
        f"{ENV_ACK}=1 only after the target is encrypted at rest"
    )


# ── copy ────────────────────────────────────────────────────────────────────
READBACK_HEADROOM = 1.10


def assert_target_disjoint(
    target: Target,
    gen: Path,
    roots: Sequence[str] = DEFAULT_ROOTS,
    extra_protected: Sequence[str] = (),
) -> None:
    """Refuse a local target that could overwrite or delete the source.

    A same-day re-copy removes ``<target>/daily/<date>``; if the target is (or is
    under, or contains) the source generation / a backup root / a protected
    prefix, that removal would destroy the thing being backed up.
    """
    root = target.local_root()
    if root is None:
        return
    tr = root.resolve()
    src = gen.resolve()
    final = tr / "daily" / gen.name
    forbidden = [Path(r).resolve() for r in (*roots, *PROTECTED_PREFIXES, *extra_protected)]
    forbidden += [src, src.parent, src.parent.parent]
    for pref in forbidden:
        if tr == pref or pref in tr.parents:
            raise OffboxError(f"refusing: target {tr} is equal to or under {pref}")
    if final == src or final in src.parents or src in final.parents:
        raise OffboxError(f"refusing: target generation path {final} overlaps the source")


def assert_readback_space(total_bytes: int, where: str | None = None) -> None:
    free = shutil.disk_usage(where or tempfile.gettempdir()).free
    need = int(total_bytes * READBACK_HEADROOM)
    if free < need:
        raise OffboxError(
            f"refusing: read-back verification needs ~{need} bytes of temp space, {free} free"
        )


def copy_newest(
    target: Target,
    gen: Path,
    *,
    verifier: Any,
    full_verify: bool = False,
    roots: Sequence[str] = DEFAULT_ROOTS,
) -> dict[str, Any]:
    assert_target_disjoint(target, gen, roots)
    local = _verify_tree(gen, verifier=verifier, full=full_verify)
    if not local["ok"]:
        raise OffboxError(
            f"source generation {gen.name} failed local verification: {local['failed']}"
        )
    manifest = build_manifest(gen)
    assert_readback_space(sum(f["size"] for f in manifest["files"]))
    target.put_tree(gen, gen.name)
    mdir = Path(tempfile.mkdtemp(prefix="riskit-offbox-manifest-"))
    try:
        mpath = mdir / MANIFEST_NAME
        mpath.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
        target.put_file(mpath, gen.name, MANIFEST_NAME)
    finally:
        shutil.rmtree(mdir, ignore_errors=True)
    # Proof: re-read from the target, never trust the upload exit code.
    back = Path(tempfile.mkdtemp(prefix="riskit-offbox-readback-"))
    try:
        target.get_tree(gen.name, back)
        problems = compare_to_manifest(back, manifest)
    finally:
        shutil.rmtree(back, ignore_errors=True)
    if problems:
        raise OffboxError(f"copy of {gen.name} did not verify: {problems[:5]}")
    return {
        "ok": True,
        "generation": gen.name,
        "target": target.describe(),
        "files": len(manifest["files"]),
        "bytes": sum(f["size"] for f in manifest["files"]),
        "local_verified": local["verified"],
        "manifest_sha_prefixes": {f["path"]: f["sha256"][:12] for f in manifest["files"][:3]},
    }


MIRROR_MARKER = "last_mirror"


def record_copy_marker(
    gen: Path, result: dict[str, Any], *, generations: int, now: datetime | None = None
) -> str:
    """Record a VERIFIED copy in ``<backup root>/last_mirror`` so backup health sees it.

    ``src/api/backup_health.py::_offbox_mirror`` reads ``mirrored_at`` from this
    file and reports its age, which the operator alert turns into a stale-copy
    notice.  Written only AFTER the read-back proved the copy, never on failure, so
    a failing target makes the age grow instead of resetting it.  The destination is
    never recorded (it can carry a host or a bucket): only its kind.  ``dest`` is
    deliberately not an rsync spec, so the nightly writer's ``--delete`` continuity
    check (which compares ``dest``) cannot mistake this for its own mirror and
    stays additive.  Best effort: a root this process cannot write is reported, not
    fatal, because the copy itself already succeeded.  Returns "ok" or a reason.
    """
    root = gen.parent.parent
    when = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kind = str(result.get("target", "")).split(":", 1)[0] or "unknown"
    body = (
        "schema=1\n"
        f"dest=offbox_copy:{kind}\n"
        f"generations={generations}\n"
        f"generation={result.get('generation', '')}\n"
        f"mirrored_at={when}\n"
    )
    try:
        tmp = root / f".{MIRROR_MARKER}.tmp"
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, root / MIRROR_MARKER)
    except OSError as exc:
        return f"not recorded ({type(exc).__name__})"
    return "ok"


# ── drill ───────────────────────────────────────────────────────────────────
def assert_scratch_is_safe(scratch: Path, extra_protected: Sequence[str] = ()) -> None:
    resolved = scratch.resolve()
    for prefix in (*PROTECTED_PREFIXES, *extra_protected):
        pref = Path(prefix).resolve()
        if resolved == pref or pref in resolved.parents:
            raise OffboxError(f"refusing to restore under protected path {pref}")


def run_drill(
    target: Target,
    *,
    verifier: Any,
    generation: str | None = None,
    scratch_parent: str | None = None,
    full_verify: bool = False,
    extra_protected: Sequence[str] = (),
) -> dict[str, Any]:
    names = target.list_generations()
    if not names:
        raise FileNotFoundError("no generation on the target")
    name = generation or names[-1]
    if name not in names:
        raise FileNotFoundError(f"generation {name} not on the target")
    scratch = Path(tempfile.mkdtemp(prefix="riskit-offbox-drill-", dir=scratch_parent))
    try:
        assert_scratch_is_safe(scratch, extra_protected)
        target.get_tree(name, scratch)
        mpath = scratch / MANIFEST_NAME
        if not mpath.is_file():
            raise OffboxError(f"{name} has no {MANIFEST_NAME}; it was not written by this tool")
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        problems = compare_to_manifest(scratch, manifest)
        if problems:
            raise OffboxError(f"restored {name} does not match its manifest: {problems[:5]}")
        report = _verify_tree(scratch, verifier=verifier, full=full_verify)
        if not report["ok"]:
            raise OffboxError(f"restored {name} failed restore verification: {report['failed']}")
        return {
            "ok": True,
            "generation": name,
            "target": target.describe(),
            "files": len(manifest["files"]),
            "restore_verified": report["verified"],
            "restored_into": "temporary directory (deleted)",
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ── CLI ─────────────────────────────────────────────────────────────────────
def _emit(obj: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, sort_keys=True))
    else:
        print(" ".join(f"{k}={v}" for k, v in obj.items() if not isinstance(v, (dict, list))))


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    env = dict(os.environ) if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("copy", "drill"):
        sp = sub.add_parser(name)
        sp.add_argument("--target", default=env.get(ENV_TARGET, ""))
        sp.add_argument("--ack-encrypted-target", action="store_true")
        sp.add_argument("--full", action="store_true", help="integrity_check, not quick_check")
        sp.add_argument("--json", action="store_true")
    cp = sub.choices["copy"]
    cp.add_argument("--root", action="append", help="local backup root (repeatable)")
    cp.add_argument("--generation", help="explicit local generation directory")
    dr = sub.choices["drill"]
    dr.add_argument("--generation", help="generation name on the target, e.g. 2026-11-18")
    dr.add_argument("--scratch-parent", default=None)
    args = ap.parse_args(argv)

    if not args.target:
        _emit({"ok": True, "status": "disabled", "reason": f"{ENV_TARGET} not set"}, args.json)
        return 0
    try:
        require_ack(env, args.ack_encrypted_target)
        target = parse_target(args.target)
        verifier = _load_verifier()
        if args.cmd == "copy":
            gen = (
                Path(args.generation)
                if args.generation
                else newest_generation(args.root or list(DEFAULT_ROOTS))
            )
            if gen is None or not gen.is_dir():
                print("no readable backup generation found", file=sys.stderr)
                return 2
            result = copy_newest(
                target,
                gen,
                verifier=verifier,
                full_verify=args.full,
                roots=args.root or list(DEFAULT_ROOTS),
            )
            probe = getattr(target, "encryption_evidence", None)
            result["encryption_evidence"] = probe() if probe else "not_verified"
            count = len([d for d in gen.parent.iterdir() if _DATED.match(d.name)])
            result["health_marker"] = record_copy_marker(gen, result, generations=count)
        else:
            result = run_drill(
                target,
                verifier=verifier,
                generation=args.generation,
                scratch_parent=args.scratch_parent,
                full_verify=args.full,
            )
    except FileNotFoundError as exc:
        print(f"[offbox] {exc}", file=sys.stderr)
        return 2
    except OffboxError as exc:
        print(f"[offbox][ERROR] {exc}", file=sys.stderr)
        return 1
    _emit(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
