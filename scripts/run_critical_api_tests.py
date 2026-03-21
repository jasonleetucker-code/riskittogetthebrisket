from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CRITICAL_TEST_MODULES = [
    ("tests/api/test_value_pipeline_golden.py", "tests.api.test_value_pipeline_golden"),
    ("tests/api/test_value_authority_guardrails.py", "tests.api.test_value_authority_guardrails"),
    ("tests/api/test_trade_scoring_api.py", "tests.api.test_trade_scoring_api"),
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run critical value/trade authority API tests when present.",
    )
    parser.add_argument("--repo", default=".", help="Repository root path.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Use verbose unittest output.")
    return parser.parse_args()


def main() -> int:
    args = _args()
    repo_root = Path(args.repo).resolve()

    selected_modules: list[str] = []
    for rel_path, module in CRITICAL_TEST_MODULES:
        if (repo_root / rel_path).exists():
            selected_modules.append(module)

    if not selected_modules:
        print("[critical-tests] no critical test modules present; failing to avoid false green")
        return 2

    cmd = [sys.executable, "-m", "unittest", *selected_modules]
    if args.verbose:
        cmd.append("-v")

    print(f"[critical-tests] running modules: {', '.join(selected_modules)}")
    proc = subprocess.run(cmd, cwd=repo_root, check=False)
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
