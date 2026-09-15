"""Content identities for serving inputs, with completeness stated explicitly.

Canonical provenance is intentionally incomplete: its existing builder still
resolves live/cached league context and clock-dependent freshness/history. A
partial inventory must never authorize a skipped canonical build.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from types import MappingProxyType

from src.serving.dependencies import AssetSpec, DependencyRegistry

MANIFEST_VERSION = "serving-inputs-v1"
REPO_DIR = Path(__file__).resolve().parents[2]
CANONICAL_UNKNOWNS = (
    "live_or_process_cached_league_context: data_contract._resolve_league_context",
    "clock_semantics: source freshness, fallback draft year, rank-history windows",
    "mutable_history_snapshot: temporal SQLite/WAL and post-acceptance history writes",
    "process_cached_configuration: effective caches are not represented by disk alone",
)
LEAGUE_CODE_FILES = (
    "src/serving/league_views.py",
    "src/serving/projections.py",
    "src/serving/builder.py",
    "src/serving/runtime.py",
    "src/serving/artifacts.py",
    "src/serving/coordinator.py",
    "src/serving/input_manifest.py",
    "src/api/data_contract.py",
    "src/api/sleeper_overlay.py",
    "src/api/league_registry.py",
    "src/ros/lineup.py",
    "src/league_comparison/sleeper_scoring.py",
    "src/data_models/contracts.py",
)


def _league_code(repo):
    return {
        name: file_identity(repo / name)
        for name in (
            *LEAGUE_CODE_FILES,
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
        )
    }


def content_identity(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_identity(path: Path) -> str:
    """Hash contents even when size/mtime were preserved; missing is an identity."""
    try:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise OSError("input changed while hashing")
        return digest.hexdigest()
    except FileNotFoundError:
        return "missing"


def _tree(root: Path, pattern="*") -> dict[str, str]:
    if not root.exists():
        return {".": "missing"}
    return {
        path.relative_to(root).as_posix(): file_identity(path)
        for path in sorted(root.rglob(pattern))
        if path.is_file()
    }


def _registered_sources(repo: Path) -> dict[str, str]:
    # Read the actual registry without importing the contract's mutable caches.
    tree = ast.parse((repo / "src/api/data_contract.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_SOURCE_CSV_PATHS"
        ):
            registry = ast.literal_eval(node.value)
            return {
                key: (value["path"] if isinstance(value, dict) else value)
                for key, value in registry.items()
            }
    raise ValueError("registered source paths were not found")


@dataclass(frozen=True)
class InputManifest:
    asset: str
    generations: Mapping[str, str]
    complete: bool
    unknowns: tuple[str, ...] = ()
    verify: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "generations", MappingProxyType(dict(self.generations)))
        object.__setattr__(self, "unknowns", tuple(self.unknowns))
        if self.complete and self.unknowns:
            raise ValueError("complete input manifest cannot contain unknown dependencies")

    @property
    def fingerprint(self) -> str:
        specs = [
            AssetSpec(name, producer="input-observation", version=MANIFEST_VERSION)
            for name in self.generations
        ]
        specs.append(
            AssetSpec(
                self.asset,
                tuple(sorted(self.generations)),
                producer="serving-coordinator",
                version=MANIFEST_VERSION,
            )
        )
        return DependencyRegistry(specs).fingerprint(self.asset, self.generations)

    @property
    def input_generations(self) -> dict[str, str]:
        return {
            **self.generations,
            "dependencyFingerprint": self.fingerprint,
            "inputManifestComplete": "true" if self.complete else "false",
            "inputManifestUnknowns": content_identity(self.unknowns),
        }

    def as_dict(self) -> dict:
        return {
            "version": MANIFEST_VERSION,
            "asset": self.asset,
            "complete": self.complete,
            "unknowns": list(self.unknowns),
            "fingerprint": self.fingerprint,
            "inputGenerations": dict(self.generations),
        }


def capture_canonical_inputs(raw: dict, *, repo_dir: Path = REPO_DIR) -> InputManifest:
    """Conservative bounded inventory, explicitly NOT sufficient for canonical skip.

    Includes every config/model registry and Python owner, current source CSVs,
    identity/pick inputs, factual scoring snapshots and current history ledgers.
    Never traverses data archives, exports, caches or the whole data directory.
    """
    repo = Path(repo_dir)
    unknowns = list(CANONICAL_UNKNOWNS)
    generations = {
        "rawContent": content_identity(
            {key: value for key, value in raw.items() if key != "scrapeTimestamp"}
        )
    }

    def capture(name, collect):
        try:
            generations[name] = content_identity(collect())
        except (OSError, ValueError, SyntaxError, TypeError) as exc:
            generations[name] = content_identity({"unavailable": type(exc).__name__})
            unknowns.append(f"{name}: inventory unavailable ({type(exc).__name__})")

    capture("producerCode", lambda: _tree(repo / "src", "*.py"))
    capture("configurationAndModels", lambda: _tree(repo / "config"))
    capture(
        "registeredSourceCSVs",
        lambda: {
            key: {"path": path, "content": file_identity(repo / path)}
            for key, path in _registered_sources(repo).items()
        },
    )
    # Cover fallback metadata and newly added source mirrors conservatively.
    capture(
        "sourceAndPickFiles",
        lambda: {
            path.relative_to(repo).as_posix(): file_identity(path)
            for path in sorted((repo / "CSVs").rglob("*"))
            if path.is_file()
        },
    )
    capture("sourceObservations", lambda: _tree(repo / "data/scrape_state"))
    capture(
        "factualScoringSnapshots",
        lambda: {
            path.name: file_identity(path)
            for path in sorted((repo / "data/leagues").glob("scoring_*.json"))
        },
    )
    capture(
        "currentHistory",
        lambda: {
            name: file_identity(repo / "data" / name)
            for name in (
                "rank_history.jsonl",
                "source_value_history.jsonl",
                "temporal_ledger.sqlite",
                "temporal_ledger.sqlite-wal",
                "temporal_ledger.sqlite-shm",
            )
        },
    )
    # Only relevant noncredential settings; values are represented by hashes.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("RISKIT_FEATURE_")
        or key
        in (
            "SLEEPER_LEAGUE_ID",
            "SLEEPER_LEAGUE_NAME",
            "LEAGUE_REGISTRY_PATH",
            "LEAGUE_SCORING_SNAPSHOT_DIR",
        )
    }
    generations["runtimeConfiguration"] = content_identity(environment)
    if environment.get("LEAGUE_REGISTRY_PATH"):
        capture(
            "registryOverride", lambda: file_identity(Path(environment["LEAGUE_REGISTRY_PATH"]))
        )
    if environment.get("LEAGUE_SCORING_SNAPSHOT_DIR"):
        capture(
            "scoringOverride",
            lambda: _tree(Path(environment["LEAGUE_SCORING_SNAPSHOT_DIR"]), "scoring_*.json"),
        )
    return InputManifest("canonical-serving", generations, False, tuple(unknowns))


def league_input_manifest(
    board,
    cfg,
    overlay: dict,
    *,
    factual_scoring_fingerprint: str | None,
    registry_defaults: dict | None,
    repo_dir: Path = REPO_DIR,
) -> InputManifest:
    """Complete for the supplied league projection, after factual collection.

    Preserve full overlay content except the root observation timestamp. Trade
    windows, transactions, settings, IDs, roster membership and nested timestamps
    remain inputs. Use logical board identity, not observation/provenance identity.
    """
    repo = Path(repo_dir)
    cfg_value = asdict(cfg) if is_dataclass(cfg) else dict(cfg)
    code = _league_code(repo)
    unknowns = []
    if any(code[path] == "missing" for path in LEAGUE_CODE_FILES):
        unknowns.append("required league projection implementation unavailable")
    if not factual_scoring_fingerprint:
        unknowns.append("factual scoring identity unavailable")
    if registry_defaults is None:
        unknowns.append("effective requested-league registry lineup settings unavailable")
    inputs = {
        "board": board.generation_id,
        "leagueConfiguration": content_identity(cfg_value),
        "factualScoring": factual_scoring_fingerprint or "unknown",
        "registryLineupSettings": content_identity(registry_defaults),
        "leagueOverlay": content_identity(
            {key: value for key, value in overlay.items() if key != "overlayFetchedAt"}
        ),
        "producerCode": content_identity(code),
    }

    # Recheck code before publishing or reobserving; an in-place deployment must
    # not certify a manifest that belonged to a different algorithm revision.
    def verify():
        return (
            _league_code(repo) == code
            and content_identity(asdict(cfg) if is_dataclass(cfg) else dict(cfg))
            == inputs["leagueConfiguration"]
            and content_identity(registry_defaults) == inputs["registryLineupSettings"]
            and content_identity(
                {key: value for key, value in overlay.items() if key != "overlayFetchedAt"}
            )
            == inputs["leagueOverlay"]
        )

    return InputManifest("league-serving", inputs, not unknowns, tuple(unknowns), verify=verify)
