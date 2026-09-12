"""Validate serving retention and optionally prune private artifact generations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.serving.artifacts import ArtifactError, ArtifactStore, RetentionPolicy  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Defaults to RISKIT_SERVING_DIR")
    parser.add_argument(
        "--apply", action="store_true", help="Delete only validated eligible generations"
    )
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--min-free-bytes", type=int)
    parser.add_argument("--keep-hours", type=float, default=48)
    parser.add_argument("--pin", nargs=4, metavar=("ASSET", "KEY", "GENERATION", "LABEL"))
    parser.add_argument("--unpin", metavar="LABEL")
    parser.add_argument(
        "--provision-access",
        action="store_true",
        help="Create missing opt-in reader-group layout; refuses incompatible existing permissions",
    )
    args = parser.parse_args(argv)
    if args.pin and args.unpin:
        parser.error("choose pin or unpin, not both")
    if (args.pin or args.unpin) and not args.apply:
        parser.error("pin changes require --apply")
    if args.provision_access and (not args.apply or args.pin or args.unpin):
        parser.error("access provisioning requires --apply and cannot change pins")
    try:
        environment = RetentionPolicy.from_environment()
        policy = RetentionPolicy(
            keep_seconds=args.keep_hours * 3600,
            max_bytes=args.max_bytes if args.max_bytes is not None else environment.max_bytes,
            min_free_bytes=args.min_free_bytes
            if args.min_free_bytes is not None
            else environment.min_free_bytes,
        )
        store = ArtifactStore(args.root, retention_policy=policy)
        if args.provision_access:
            store.provision_access()
            print(json.dumps({"schemaVersion": 1, "status": "provisioned"}))
            return 0
        if args.pin:
            store.pin(*args.pin)
        if args.unpin:
            store.unpin(args.unpin)
        report = store.retention(apply=args.apply)
        print(json.dumps(report, sort_keys=True))
        return 2 if report["blocked"] else 0
    except (ArtifactError, OSError, ValueError) as exc:
        print(json.dumps({"schemaVersion": 1, "status": "blocked", "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
