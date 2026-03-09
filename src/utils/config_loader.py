from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for p in [here, *here.parents]:
        if (p / ".git").exists():
            return p
    return Path.cwd().resolve()


def canonical_data_dir(root: Path) -> Path:
    env_override = os.getenv("CANONICAL_DATA_DIR", "").strip()
    if env_override:
        return Path(env_override).resolve()
    return (root / "data").resolve()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)

