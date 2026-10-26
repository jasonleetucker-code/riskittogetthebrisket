"""Create or verify the content-addressed CI release manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.api.build_identity import create_release_manifest, verify_release_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--build-dir", type=Path, default=Path("frontend/.next"))
    parser.add_argument("--manifest", type=Path, default=Path("release-manifest.json"))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--node-version")
    parser.add_argument("--run-id")
    parser.add_argument("--backend-archive", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    build_dir = root / args.build_dir
    manifest_path = root / args.manifest
    if args.action == "create":
        if not args.node_version:
            parser.error("create requires --node-version")
        manifest = create_release_manifest(
            root,
            build_dir,
            commit=args.commit,
            node_version=args.node_version,
            run_id=args.run_id,
            backend_archive=root / args.backend_archive if args.backend_archive else None,
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_release_manifest(
        manifest,
        root,
        build_dir,
        expected_commit=args.commit,
        backend_archive=root / args.backend_archive if args.backend_archive else None,
    )
    print(manifest["artifact_id"])


if __name__ == "__main__":
    main()
