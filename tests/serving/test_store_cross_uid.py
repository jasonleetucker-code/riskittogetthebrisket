"""Real POSIX principal checks; Windows and non-root runs provide no proof."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="Requires POSIX root to drop child processes to distinct numeric UIDs",
)

_CHILD = r"""
import json, os, sys
from pathlib import Path
from src.serving.artifacts import ArtifactStore, RetentionPolicy
from src.serving.producer_status import (
    claim_source_refresh, pending_source_refresh, request_source_refresh,
)

base, uid, gid, action = sys.argv[1:]
uid, gid = int(uid), int(gid)
os.setgroups([gid])
os.setgid(gid)
os.setuid(uid)
assert os.geteuid() == uid and os.getegid() == gid and os.getgroups() == [gid]
base = Path(base)
store = ArtifactStore(base / "producer/store", reader_gid=gid,
    retention_policy=RetentionPolicy(min_free_bytes=0))
meta = {"modelVersion": "uid-test", "inputGenerations": {}, "configHash": "test"}

def denied(operation):
    try:
        operation()
    except PermissionError:
        return
    raise AssertionError("Operation unexpectedly authorized")

if action in {"first", "replacement"}:
    store.provision_access()
    if action == "replacement":
        assert claim_source_refresh(store)["outcome"] == "claimed"
        assert pending_source_refresh(store) is None
    result = store.publish("sample", "main", {"nested/value": action.encode()}, meta)
    assert store.read_current("sample", "main").generation_id == result.generation_id
    assert (base / "producer/private-key").read_bytes() == b"fixture-not-a-key"
    print(json.dumps({"generation": result.generation_id}))
elif action in {"read-first", "read-replacement"}:
    expected = action.removeprefix("read-").encode()
    current = store.read_current("sample", "main")
    assert current.files["nested/value"] == expected
    artifact = store.root / "sample/main/generations" / current.generation_id / "files/nested/value"
    denied(lambda: artifact.open("wb"))
    denied(lambda: (store.root / "sample/main/current.json").open("wb"))
    denied(lambda: (store.root / "unapproved").write_bytes(b"no"))
    denied(lambda: (base / "producer/private-key").read_bytes())
    assert (base / "public-pin").read_bytes() == b"fixture-public-pin"
    denied(lambda: (base / "public-pin").open("wb"))
    denied(lambda: (store.root / "store.lock").unlink())
    queued = request_source_refresh(store)
    assert request_source_refresh(store)["coalesced"]
    assert pending_source_refresh(store)["requestId"] == queued["requestId"]
    print(json.dumps({"generation": current.generation_id, "queued": True}))
elif action == "fifo":
    marker = store.request_root / "source-refresh.request"
    marker.unlink(missing_ok=True)
    os.mkfifo(marker, 0o660)
    assert pending_source_refresh(store) is None
    print(json.dumps({"fifoRefused": True}))
elif action == "claim-invalid":
    assert claim_source_refresh(store)["outcome"] == "invalid_request"
    assert pending_source_refresh(store) is None
    print(json.dumps({"invalidClaimed": True}))
else:
    raise AssertionError("Unknown action")
"""


def test_distinct_uid_publication_queue_and_credential_boundary():
    # No operating-system users or persistent paths are created. Every child
    # imports code before dropping privileges, but all tested I/O occurs after.
    producer_uid, web_uid, reader_gid = 60121, 60122, 60123
    repository = Path(__file__).resolve().parents[2]
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("RISKIT_SERVING_")
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="serving-cross-uid-") as directory:
        base = Path(directory)
        base.chmod(0o755)
        producer = base / "producer"
        producer.mkdir()
        os.chown(producer, producer_uid, reader_gid)
        producer.chmod(0o2750)
        private = producer / "private-key"
        private.write_bytes(b"fixture-not-a-key")
        os.chown(private, producer_uid, reader_gid)
        private.chmod(0o600)
        pin = base / "public-pin"
        pin.write_bytes(b"fixture-public-pin")
        pin.chmod(0o644)

        def run(uid, action):
            result = subprocess.run(
                [sys.executable, "-c", _CHILD, str(base), str(uid), str(reader_gid), action],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            return json.loads(result.stdout)

        first = run(producer_uid, "first")
        root = producer / "store"
        locks = {
            name: (root / name).stat().st_ino
            for name in ("store.lock", "source-request.lock", "league-request.lock")
        }
        assert run(web_uid, "read-first")["generation"] == first["generation"]
        replacement = run(producer_uid, "replacement")
        assert replacement["generation"] != first["generation"]
        assert run(web_uid, "read-replacement")["generation"] == replacement["generation"]
        assert run(web_uid, "fifo")["fifoRefused"]
        assert run(producer_uid, "claim-invalid")["invalidClaimed"]
        assert locks == {name: (root / name).stat().st_ino for name in locks}
        assert private.read_bytes() == b"fixture-not-a-key"
        assert pin.read_bytes() == b"fixture-public-pin"
