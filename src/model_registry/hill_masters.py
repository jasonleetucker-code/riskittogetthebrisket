"""Hill scope masters as a registered model — shared by both drivers.

``scripts/model_registry.py`` (the human CLI) and
``scripts/auto_refit_hill_curves.py`` (the weekly refit) both need to
read the live constants, resolve the registry, and fingerprint the
training inputs.  Those helpers live here rather than in either script
so the two cannot drift into disagreeing about what "the champion" is —
a refit that resolved the champion differently from the CLI would
reintroduce the whole problem quietly.

Reading and writing ``player_valuation.py`` are deliberately separate
functions with very different call sites.  ``read_committed_constants``
is called freely.  ``write_committed_constants`` is called by exactly
one place — the CLI's ``apply``, driven by a human — and never by the
weekly refit.  That asymmetry IS the directive's "do not allow a model
to autonomously rewrite production code"; if a future change gives the
refit a path to the writer, the prohibition is gone.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.model_registry.holdout import source_roles
from src.model_registry.versioning import (
    ModelRegistry,
    ModelVersion,
    RegistryError,
    fingerprint_inputs,
)

REPO = Path(__file__).resolve().parents[2]
PLAYER_VALUATION = REPO / "src" / "canonical" / "player_valuation.py"

MODEL_ID = "hill_scope_masters"

CONSTANT_NAMES: tuple[str, ...] = (
    "HILL_GLOBAL_PERCENTILE_C",
    "HILL_GLOBAL_PERCENTILE_S",
    "HILL_PERCENTILE_C",
    "HILL_PERCENTILE_S",
    "IDP_HILL_PERCENTILE_C",
    "IDP_HILL_PERCENTILE_S",
    "HILL_ROOKIE_PERCENTILE_C",
    "HILL_ROOKIE_PERCENTILE_S",
)

# The pair the OFFENSE holdout actually scores.  Named so callers stop
# assuming "the model" is validated end to end: only these two of the
# eight have a genuine out-of-sample check today.
VALIDATED_PARAMS: tuple[str, str] = ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S")


def read_committed_constants(path: Path | None = None) -> dict[str, float]:
    """The eight constants currently live in ``player_valuation.py``."""
    target = path or PLAYER_VALUATION
    text = target.read_text()
    out: dict[str, float] = {}
    for name in CONSTANT_NAMES:
        m = re.search(rf"^{re.escape(name)}:\s*float\s*=\s*([0-9.]+)\s*$", text, re.MULTILINE)
        if not m:
            raise RegistryError(f"could not find {name!r} in {target}")
        out[name] = float(m.group(1))
    return out


def write_committed_constants(params: dict[str, float], path: Path | None = None) -> None:
    """Write the champion's constants into production.

    CALLED BY EXACTLY ONE PLACE: ``scripts/model_registry.py apply``,
    run by a human.  The weekly refit must never reach this.
    """
    target = path or PLAYER_VALUATION
    text = target.read_text()
    for name in CONSTANT_NAMES:
        if name not in params:
            raise RegistryError(f"champion params missing {name!r}")
        literal = f"{params[name]:.4f}" if name.endswith("_C") else f"{params[name]:.3f}"
        text, n = re.subn(
            rf"^({re.escape(name)}:\s*float\s*=\s*)[0-9.]+(\s*)$",
            rf"\g<1>{literal}\g<2>",
            text,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RegistryError(f"expected 1 match for {name!r}, got {n}")
    target.write_text(text)


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def training_input_paths() -> dict[str, Path]:
    """The CSVs the fit consumes, for provenance fingerprinting."""
    return {role.label: REPO / role.path for role in source_roles() if role.role == "train"}


def load_or_seed_registry(registry_dir: Path | None = None) -> ModelRegistry:
    """Resolve the registry, seeding from live constants on first use.

    Seeding records what is ALREADY live as v1 champion.  It is not a
    claim that those constants won anything — ``qualified`` stays False
    until someone evaluates them.
    """
    try:
        return ModelRegistry.load(MODEL_ID, registry_dir)
    except RegistryError:
        reg = ModelRegistry(MODEL_ID)
        reg.seed_champion(
            ModelVersion(
                model_id=MODEL_ID,
                version=1,
                params=read_committed_constants(),
                fitted_at="unknown",
                producer="seeded from committed constants in player_valuation.py",
                training_inputs=fingerprint_inputs(training_input_paths()),
                notes=(
                    "seeded, not validated: these constants were live before the "
                    "registry existed and carry no out-of-sample score",
                ),
            )
        )
        reg.save(registry_dir)
        return reg
