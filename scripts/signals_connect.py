#!/usr/bin/env python3
"""Owner-controlled Signals account connection.

Signals signs in with an emailed one-time code.  YOU type your email and the
code into a dedicated browser window this script opens; the script captures
only the Signals Cognito session from that window and stores it outside the
checkout.  Nothing is ever pasted into chat, an issue or a commit, and nothing
here can send a login email on its own.  Full record:
``docs/sources/SIGNALS_ACCOUNT_CONNECTION.md``.

Subcommands
-----------
  connect     open the real Signals login in a fresh, non-persistent browser
              context; capture the session once you have signed in
  reconnect   the same, replacing an existing (dead) session
  status      authentication health + source-data freshness (redacted)
  renew       renew now if due (``--force``: one deliberate attempt)
  disconnect  delete the local session (``--revoke``: also revoke it at Cognito)
  provision   copy the local session to the prod box over SSH stdin, then
              (by default) delete the local copy so the box is the ONE renewal
              owner
  import-session  (runs ON the box) read a session JSON from stdin

Exit codes: 0 ok / nothing to do; 1 transient or operational error;
2 stopped — owner action needed (reconnect_required, access_denied,
refresh_refused) or not connected where a session was required.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources import signals_auth as SA  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
#: The collector's store (Unit A).  Read-only here — freshness is owned there.
SIGNALS_DATA_ROOT = REPO / "data" / "sources" / "signals"
SIGNALS_BOARDS = ("dynasty", "idp-dynasty")

DEFAULT_REMOTE_APP_DIR = "/home/dynasty/trade-calculator"
DEFAULT_REMOTE_PYTHON = "/home/dynasty/.venvs/trade-calculator/bin/python"
DEFAULT_REMOTE_STORE = "/var/lib/signals-auth"

#: In-page extractor: returns ONLY the Signals Cognito keys for the signed-in
#: user.  Other localStorage entries (analytics etc.) never reach Python.
_EXTRACT_JS = """
(prefix) => {
  const out = {};
  const keys = Object.keys(window.localStorage);
  const last = keys.find(k => k.startsWith(prefix + '.') && k.endsWith('.LastAuthUser'));
  if (!last) return null;
  const clientId = last.slice(prefix.length + 1, -'.LastAuthUser'.length);
  const username = window.localStorage.getItem(last);
  if (!username) return null;
  const base = prefix + '.' + clientId + '.' + username + '.';
  const want = ['accessToken','idToken','refreshToken','deviceKey','deviceGroupKey',
                'randomPasswordKey','clockDrift'];
  for (const k of want) {
    const v = window.localStorage.getItem(base + k);
    if (v) out[k] = v;
  }
  if (!out.refreshToken || !out.accessToken) return null;
  out.clientId = clientId;
  out.username = username;
  return out;
}
"""


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def _store(args: argparse.Namespace) -> SA.SignalsStore:
    return SA.SignalsStore.open(args.store_dir)


# ── data freshness (read, never recomputed) ─────────────────────────────────


def data_freshness(root: Path = SIGNALS_DATA_ROOT) -> dict[str, Any]:
    """What the collector's own store says.  Missing store → not collected."""
    if not root.is_dir():
        return {"state": "not_collected", "storeDir": str(root)}
    boards: dict[str, Any] = {}
    for board in SIGNALS_BOARDS:
        d = root / board
        if not d.is_dir():
            boards[board] = {"state": "not_collected"}
            continue
        entry: dict[str, Any] = {"state": "collected"}
        try:
            ds = json.loads((d / "dataset_state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ds = None
        if isinstance(ds, dict):
            health = ds.get("health") or {}
            entry["health"] = health.get("state")
            entry["healthSince"] = health.get("since")
            entry["upstreamPublishedAt"] = (ds.get("upstream") or {}).get("publishedAt")
        else:
            entry["health"] = None
        entry["latestReleasePresent"] = (d / "latest.json").is_file()
        boards[board] = entry
    return {"state": "collected", "storeDir": str(root), "boards": boards}


# ── connect ─────────────────────────────────────────────────────────────────


def capture_via_browser(
    *, timeout_s: float, url: str, dry_run: bool, headless: bool
) -> dict | None:
    """Open the real login in a FRESH non-persistent context and wait.

    Never types, never clicks, never submits.  The owner does the sign-in.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        print("Playwright is not installed: pip install playwright && playwright install chromium")
        raise SystemExit(1) from None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context()  # fresh profile: no other cookies or logins
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if dry_run:
                page.wait_for_timeout(3000)
                has_email = page.query_selector("input[type=email]") is not None
                _print(
                    {
                        "dryRun": True,
                        "url": page.url,
                        "emailFieldPresent": has_email,
                        "signedIn": page.evaluate(_EXTRACT_JS, SA.AMPLIFY_KEY_PREFIX) is not None,
                    }
                )
                return None
            print(
                "\nA browser window is open on the real Signals sign-in page.\n"
                "  1. Type your Signals email address in THAT window and continue.\n"
                "  2. Signals emails you a one-time code. Type the code in THAT window.\n"
                "  3. Wait here. This script never sees your email code.\n"
                f"Waiting up to {int(timeout_s)} s for the sign-in to complete...\n"
            )
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if page.is_closed():
                    print("The browser window was closed before sign-in completed.")
                    return None
                try:
                    captured = page.evaluate(_EXTRACT_JS, SA.AMPLIFY_KEY_PREFIX)
                except Exception:  # noqa: BLE001 - navigation in progress
                    captured = None
                if captured and _on_signals_origin(page.url):
                    return captured
                page.wait_for_timeout(1500)
            print("Timed out waiting for sign-in. Nothing was stored.")
            return None
        finally:
            # Close WITHOUT signing out: a sign-out would revoke the session.
            browser.close()


def cmd_connect(args: argparse.Namespace, *, replace: bool) -> int:
    store = _store(args)
    if not args.dry_run:
        existing = SA.status(store)
        if existing["state"] != SA.STATE_NOT_CONNECTED and not replace:
            print(
                f"A Signals session already exists (state={existing['state']}). "
                "Use `reconnect` to replace it."
            )
            return 1
    captured = capture_via_browser(
        timeout_s=args.timeout, url=args.url, dry_run=args.dry_run, headless=args.headless
    )
    if args.dry_run:
        return 0
    if not captured:
        return 2
    try:
        SA.import_session(store, captured)
    except SA.SignalsAuthError as exc:
        print(f"Capture rejected: {exc}")
        return 2
    print("Signals session stored.")
    _print(SA.status(store))
    return 0


# ── status / renew / disconnect ─────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    store = _store(args)
    _print(
        {
            "authentication": SA.status(store),
            "sourceDataFreshness": data_freshness(Path(args.data_root)),
        }
    )
    return 0


def cmd_renew(args: argparse.Namespace) -> int:
    store = _store(args)
    if store.read_session() is None:
        _print({"state": SA.STATE_NOT_CONNECTED, "action": "nothing to renew"})
        return 0
    try:
        SA.renew(store, force=args.force, skew_seconds=args.skew)
    except SA.SignalsAuthError as exc:
        notice = None
        if exc.failure_class != SA.TRANSIENT:
            # Prompt owner push the moment collection stops (the daily sweep is
            # the backstop and adds SMTP).  Runs after renew() released the
            # lock; best effort -- an unreachable ntfy never fails this run.
            from src.utils import owner_notify  # noqa: PLC0415

            notice = SA.deliver_reconnect_notice(
                store=store, channels=[("ntfy", owner_notify.channel())]
            )
        _print(
            {
                "state": exc.failure_class,
                "reason": exc.reason,
                "status": SA.status(store),
                "notice": notice,
            }
        )
        return 1 if exc.failure_class == SA.TRANSIENT else 2
    _print(SA.status(store))
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.revoke:
        try:
            revoked = SA.revoke_remote(store)
        except SA.SignalsAuthError as exc:
            print(f"Remote revoke failed ({exc}); the local session was NOT deleted.")
            return 1
        print("Revoked at Cognito." if revoked else "No local session to revoke.")
    removed = SA.disconnect(store)
    print("Local Signals session deleted." if removed else "No local Signals session.")
    return 0


def _on_signals_origin(url: str) -> bool:
    """Capture only while the tab is on the Signals web app itself."""
    parts = urllib.parse.urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}".lower() == SA.WEBAPP_ORIGIN


# ── provisioning ────────────────────────────────────────────────────────────

_SSH_HOST = re.compile(r"[A-Za-z0-9._@-]+")


def remote_import_command(args: argparse.Namespace) -> list[str]:
    """The remote command line.  Carries NO secret: the session goes on stdin."""
    q = shlex.quote
    script = f"{args.remote_app_dir}/scripts/signals_connect.py"
    store = q(args.remote_store)
    # Create the store 0700 owned by the importing user when it does not exist
    # (the box's app user has NOPASSWD `install`); an existing dir is left as is.
    inner = (
        f'[ -d {store} ] || sudo -n install -d -m 0700 -o "$(id -un)" -g "$(id -gn)" {store}; '
        f"RISKIT_SIGNALS_AUTH_DIR={store} {q(args.remote_python)} {q(script)} import-session"
    )
    if args.sudo_user:
        # Single-quoted so $(id -un) expands as the TARGET user, not the SSH user.
        inner = f"sudo -n -u {q(args.sudo_user)} sh -c {q(inner)}"
    if not _SSH_HOST.fullmatch(args.host or "") or args.host.startswith("-"):
        raise SystemExit(f"refusing --host {args.host!r}: expected an SSH alias or user@host")
    return ["ssh", "-o", "BatchMode=yes", "--", args.host, inner]


def cmd_provision(args: argparse.Namespace) -> int:
    store = _store(args)
    session = store.read_session()
    if session is None:
        print("No local Signals session. Run `connect` first.")
        return 2
    payload = json.dumps(session).encode("utf-8")
    cmd = remote_import_command(args)
    print(f"Provisioning via: {' '.join(cmd[:-1])} '<remote import-session>' (session on stdin)")
    proc = subprocess.run(cmd, input=payload, capture_output=True, timeout=120)  # noqa: S603
    out = proc.stdout.decode("utf-8", "replace")
    print(out.strip())
    if proc.returncode != 0:
        print(
            f"Remote import failed (exit {proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:500]}"
        )
        return 1
    if not args.keep_local:
        SA.disconnect(store)
        print(
            "Local copy deleted (NOT revoked): the box is now the one renewal owner, "
            "so a rotated refresh token cannot be lost between two holders."
        )
    return 0


def cmd_import_session(args: argparse.Namespace) -> int:
    raw = sys.stdin.buffer.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print("import-session: stdin is not JSON")
        return 2
    if not isinstance(data, dict):
        print("import-session: expected a JSON object")
        return 2
    store = _store(args)
    try:
        SA.import_session(store, data)
    except SA.SignalsAuthError as exc:
        print(f"import-session rejected: {exc}")
        return 2
    _print({"imported": True, "status": SA.status(store)})
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--store-dir", default=None, help=f"session store (default: ${SA.AUTH_DIR_ENV} or per-OS)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("connect", "reconnect"):
        c = sub.add_parser(name, help=f"{name} the Signals account in a dedicated browser")
        c.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for sign-in")
        c.add_argument("--url", default=SA.WEBAPP_ORIGIN, help=argparse.SUPPRESS)
        c.add_argument(
            "--dry-run", action="store_true", help="open the page, report, close; store nothing"
        )
        c.add_argument("--headless", action="store_true", help="only meaningful with --dry-run")
    s = sub.add_parser("status", help="auth health + data freshness (redacted)")
    s.add_argument("--data-root", default=str(SIGNALS_DATA_ROOT))
    r = sub.add_parser("renew", help="renew now if due")
    r.add_argument(
        "--force", action="store_true", help="one deliberate attempt even if not due/stopped"
    )
    r.add_argument("--skew", type=float, default=SA.DEFAULT_SKEW_SECONDS)
    d = sub.add_parser("disconnect", help="delete the local session")
    d.add_argument(
        "--revoke", action="store_true", help="also revoke at Cognito (kills every copy)"
    )
    v = sub.add_parser("provision", help="copy the session to the box over SSH stdin")
    v.add_argument("--host", required=True, help="an SSH config Host alias")
    v.add_argument("--remote-app-dir", default=DEFAULT_REMOTE_APP_DIR)
    v.add_argument("--remote-python", default=DEFAULT_REMOTE_PYTHON)
    v.add_argument("--remote-store", default=DEFAULT_REMOTE_STORE)
    v.add_argument(
        "--sudo-user", default=None, help="run the remote import as this user (e.g. dynasty)"
    )
    v.add_argument(
        "--keep-local", action="store_true", help="keep the local copy (two holders: not advised)"
    )
    sub.add_parser("import-session", help="(on the box) read a session JSON from stdin")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "connect":
            return cmd_connect(args, replace=False)
        if args.cmd == "reconnect":
            return cmd_connect(args, replace=True)
        if args.cmd == "status":
            return cmd_status(args)
        if args.cmd == "renew":
            return cmd_renew(args)
        if args.cmd == "disconnect":
            return cmd_disconnect(args)
        if args.cmd == "provision":
            return cmd_provision(args)
        if args.cmd == "import-session":
            return cmd_import_session(args)
    except SA.StorePathError as exc:
        print(f"Unsafe store location: {exc}")
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
