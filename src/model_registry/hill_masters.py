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
    """Every material input the model set is fitted from.

    A recorded version carries EIGHT constants across four scopes, so a
    provenance record covering only the six OFFENSE CSVs answers "what
    produced ``HILL_PERCENTILE_C``" while appearing to answer for all of
    them. Until B1.2 that is exactly what it did — GLOBAL's IDPTradeCalc,
    IDP's DraftSharks-IDP and the board snapshot behind the IDP slice and
    every rookie slice were unrecorded, so a challenger could not be
    reproduced from its own record.

    Derived from the fitter's own source tables rather than mirrored here.
    A hand-maintained parallel list stops covering the thing it mirrors —
    the B1 pin instrument had this same defect and named three of six
    OFFENSE sources within a day of being written.
    """
    out: dict[str, Path] = {}
    seen: set[Path] = set()

    def _record(label: str, path: Path) -> None:
        # Keyed by resolved PATH, not label: several sources appear under
        # more than one name (DraftSharks-SF is both an OFFENSE source and
        # half of GLOBAL's concatenated pair), and fingerprinting one file
        # twice under two keys makes a stored record look like it covers
        # more inputs than it does.
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        out[label] = path

    for role in source_roles():
        if role.role == "train":
            _record(role.label, REPO / role.path)

    fitter = _fitter_module()
    for table, scope in (
        (getattr(fitter, "OFFENSE_SOURCES", {}), "OFFENSE"),
        (getattr(fitter, "GLOBAL_SOURCES", {}), "GLOBAL"),
        (getattr(fitter, "IDP_CSV_SOURCES", {}), "IDP"),
    ):
        for label, (rel, _column) in table.items():
            _record(f"{scope}:{label}", REPO / rel)

    # GLOBAL builds DraftSharks-Combined by concatenating the SF and IDP
    # slices in code, so it appears in no source table at all. Both halves
    # are already recorded above under their own scopes; this only catches
    # the case where one of them is dropped from a table but still
    # concatenated.
    for rel in ("CSVs/site_raw/draftSharksSf.csv", "CSVs/site_raw/draftSharksIdp.csv"):
        _record(f"GLOBAL:DraftSharks-Combined:{Path(rel).name}", REPO / rel)

    snapshot = _resolve_fit_snapshot(fitter)
    if snapshot is not None:
        _record("boardSnapshot", snapshot)
    return out


def _fitter_module():
    """Import the fit script as a module, tolerating its ``argparse`` main."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fit_hill_curve_percentile_provenance", REPO / "scripts/fit_hill_curve_percentile.py"
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # pragma: no cover - only if the script grows a main guard
        pass
    return module


def _resolve_fit_snapshot(fitter) -> Path | None:
    """The board snapshot the fit WOULD use, resolved the same way it does.

    Returns ``None`` rather than raising when nothing resolves: a missing
    snapshot should surface as an absent provenance entry, not as an
    exception inside a registry read.
    """
    try:
        return fitter._latest_snapshot()
    except SystemExit:
        # `RISKIT_FIT_SNAPSHOT` names a file that does not exist. The fit
        # itself will refuse for the same reason; provenance should not be
        # the thing that reports it.
        return None
    except Exception:  # noqa: BLE001
        return None


def load_or_seed_registry(registry_dir: Path | None = None) -> ModelRegistry:
    """Resolve the registry, seeding from live constants on first use.

    Seeding records what is ALREADY live as v1 champion.  It is not a
    claim that those constants won anything — ``qualified`` stays False
    until someone evaluates them.
    """
    path = ModelRegistry.path_for(MODEL_ID, registry_dir)
    if path.exists():
        # An existing registry that will not load is a PROBLEM, not an
        # absence.  This used to be a bare `except RegistryError` around
        # `load()`, which made the two indistinguishable: any structural
        # failure — a duplicate version, two champions, a schema the code
        # no longer understands — fell into the seed branch and `save()`
        # replaced the file with a single fresh v1.  The one artifact
        # recording every promotion and rollback decision was one
        # validation error away from being silently destroyed, and it was
        # reproduced live during B1.2: a guard that made `load()` raise
        # replaced the real three-version registry with a seeded
        # single-version one inside one test run.
        #
        # Same defect class as the closure harness in Phase A, which is
        # why ARCHITECTURE_HANDOFF invariant 6 says to assume a third
        # exists.  This is the third.
        return ModelRegistry.load(MODEL_ID, registry_dir)

    reg = ModelRegistry(MODEL_ID)
    reg.seed_champion(
        ModelVersion(
            model_id=MODEL_ID,
            version=1,
            params=read_committed_constants(),
            fitted_at="unknown",
            producer="seeded from committed constants in player_valuation.py",
            training_inputs=fingerprint_inputs(training_input_paths()),
            # The constants ARE live at seed time — that is what seeding
            # records — but the moment they were written is not
            # reconstructable, and inventing one would be worse than saying
            # so (ADR-008 lifecycle; §39).
            applied_at="UNKNOWN_HISTORICAL_APPLY_TIME",
            notes=(
                "seeded, not validated: these constants were live before the "
                "registry existed and carry no out-of-sample score",
            ),
        )
    )
    reg.save(registry_dir)
    return reg
