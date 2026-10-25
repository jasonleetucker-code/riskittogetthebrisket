"""Read-only enforcement for research scripts that run on the production host.

``install()`` registers a CPython audit hook (``sys.addaudithook``) that can
never be removed for the rest of the process, so the guarantee does not depend
on reviewing every line of application code a research script imports.  Once
installed, the process:

* cannot open any file for writing, appending, creating or truncating, and
  cannot remove / rename / move / chmod / chown / mkdir anything — except inside
  one private temporary directory the guard creates itself and deletes at exit
  (scratch space some libraries need; it is never inside the app directory);
* cannot open a SQLite database except read-only (``file:…?mode=ro`` URI) or
  ``:memory:``;
* cannot open a network connection or resolve a host;
* cannot start a subprocess, ``exec`` or ``fork``;
* never writes Python bytecode (``sys.dont_write_bytecode``), so importing the
  deployed ``src/`` leaves no ``__pycache__`` behind.

Any attempt raises ``PermissionError`` — the run fails closed rather than
writing.  ``denied()`` lists every refused attempt so a report can state that
none occurred.
"""

from __future__ import annotations

import atexit
import os
import sys
import tempfile

_STATE: dict = {"installed": False, "scratch": None, "denied": []}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_PATH_EVENTS = {
    "os.remove": (0,),
    "os.rename": (0, 1),
    "os.replace": (0, 1),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.truncate": (0,),
    "os.link": (0, 1),
    "os.symlink": (0, 1),
    "os.utime": (0,),
    "shutil.rmtree": (0,),
    "shutil.move": (0, 1),
    "shutil.copyfile": (1,),
    "shutil.copytree": (1,),
    "shutil.make_archive": (0,),
}
_FORBIDDEN_EVENTS = (
    "socket.connect",
    "socket.bind",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "os.forkpty",
    "os.kill",
    "ctypes.dlopen",
)


def _inside_scratch(path) -> bool:
    scratch = _STATE["scratch"]
    if scratch is None or path is None or isinstance(path, int):
        return False
    try:
        real = os.path.realpath(os.fsdecode(path))
    except (TypeError, ValueError):
        return False
    return real == scratch or real.startswith(scratch + os.sep)


def _caller() -> str:
    """The innermost non-stdlib, non-guard frame (``file:line``) — who asked."""
    frame = sys._getframe(2)
    stdlib = os.path.dirname(os.__file__)
    while frame is not None:
        fn = frame.f_code.co_filename
        if fn != __file__ and not fn.startswith(stdlib) and "site-packages" not in fn:
            return (
                f"{os.path.basename(os.path.dirname(fn))}/{os.path.basename(fn)}:{frame.f_lineno}"
            )
        frame = frame.f_back
    return "stdlib"


def _deny(event: str, detail) -> None:
    _STATE["denied"].append({"event": event, "detail": str(detail)[:200], "caller": _caller()})
    raise PermissionError(f"research read-only guard refused {event}: {detail!r}")


def _hook(event: str, args) -> None:
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        )
        if writes and not _inside_scratch(path):
            _deny(event, (path, mode, flags))
        return
    if event in _PATH_EVENTS:
        for i in _PATH_EVENTS[event]:
            if i < len(args) and not _inside_scratch(args[i]):
                _deny(event, args[i])
        return
    if event == "sqlite3.connect":
        db = args[0] if args else None
        text = os.fsdecode(db) if isinstance(db, (str, bytes, os.PathLike)) else str(db)
        if text == ":memory:" or (text.startswith("file:") and "mode=ro" in text):
            return
        _deny(event, text)
    if event.startswith(_FORBIDDEN_EVENTS):
        _deny(event, args[:1] if args else "")


def _cleanup() -> None:
    """Remove the private scratch dir at exit, by ABSOLUTE paths only.

    ``shutil.rmtree`` deletes entries by name relative to a directory fd, which
    the hook cannot place inside the scratch dir and so refuses — that left the
    scratch dir behind in /tmp whenever a library had written into it.  A
    symlink resolving outside the scratch dir is still refused, so nothing
    outside it can be deleted."""
    scratch = _STATE["scratch"]
    if not scratch or not os.path.isdir(scratch):
        return
    for root, dirs, files in os.walk(scratch, topdown=False):
        for name in files:
            try:
                os.remove(os.path.join(root, name))
            except (OSError, PermissionError):
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except (OSError, PermissionError):
                pass
    try:
        os.rmdir(scratch)
    except (OSError, PermissionError):
        pass


def install() -> str:
    """Install the guard (idempotent).  Returns the private scratch dir."""
    if _STATE["installed"]:
        return _STATE["scratch"]
    sys.dont_write_bytecode = True
    scratch = os.path.realpath(tempfile.mkdtemp(prefix="research-ro-"))
    _STATE["scratch"] = scratch
    os.environ["TMPDIR"] = scratch
    tempfile.tempdir = scratch
    atexit.register(_cleanup)
    sys.addaudithook(_hook)
    _STATE["installed"] = True
    return scratch


def denied() -> list[dict]:
    return list(_STATE["denied"])


def installed() -> bool:
    return bool(_STATE["installed"])
