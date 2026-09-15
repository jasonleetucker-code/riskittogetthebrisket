"""Save existing offline measurement views for a private, deterministic browser replay."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    target = args.output_dir.resolve()
    if "private_serving" not in target.parts:
        parser.error("Replay payloads must remain under an ignored private_serving directory")
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    os.environ.setdefault("RISKIT_FEATURE_LEDGER_RANK_CHANGE", "0")
    from src.serving import builder

    build = builder.build_generation
    captured = []

    def capture(*build_args, **build_kwargs):
        candidate = build(*build_args, **build_kwargs)
        captured.append(candidate)
        return candidate

    # Reuse the exact existing measurement's offline setup and producer call.
    # It validates the candidate and writes only its compact evidence report.
    builder.build_generation = capture
    target.mkdir(parents=True, exist_ok=True)
    sys.argv = [
        "measure_prepared_payloads.py",
        "--input",
        str(args.input.resolve()),
        "--output",
        str(target / "measurement.json"),
        "--offline",
    ]
    try:
        runpy.run_path(str(root / "scripts" / "measure_prepared_payloads.py"), run_name="__main__")
    finally:
        builder.build_generation = build
    if len(captured) != 1:
        raise RuntimeError("Expected one validated offline generation")
    candidate = captured[0]
    files = {}
    for name, view in candidate.views.items():
        (target / f"{name}.json").write_bytes(view.raw)
        (target / f"{name}.json.gz").write_bytes(view.gzip)
        files[name] = {
            "file": f"{name}.json",
            "gzipFile": f"{name}.json.gz",
            "sha256": hashlib.sha256(view.raw).hexdigest(),
            "bytes": len(view.raw),
        }
    (target / "player-index.json").write_bytes(builder.json_bytes(candidate.indexes["players"]))
    shutil.copyfile(args.input, target / "raw-input.json")
    manifest = {
        "schemaVersion": 1,
        "privateReplay": True,
        "generation": candidate.generation_id,
        "rows": len(candidate.contract["playersArray"]),
        "views": files,
        "playerIndexFile": "player-index.json",
        "rawInputFile": "raw-input.json",
    }
    (target / "replay.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"privateReplayExported": True, "rows": manifest["rows"], "views": list(files)})
    )


if __name__ == "__main__":
    main()
