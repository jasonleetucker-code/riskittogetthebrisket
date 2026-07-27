"""Versioned BDVM parameter sets.

Parameters live in ``config/bdvm/params_v*.json`` — never in code.  A
parameter set is identified by ``param_set_id``, a content hash of the
canonical JSON, so *any* edit produces a new id and every stored value
row remains traceable to the exact constants that produced it
(BDVM master prompt §6.2 / reference §9.6).

Select a non-default set with ``BDVM_PARAM_SET=params_v2`` (file stem
under ``config/bdvm/``).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PARAMS_DIR = REPO_ROOT / "config" / "bdvm"
DEFAULT_PARAM_SET = "params_v1"
_ENV_VAR = "BDVM_PARAM_SET"

_lock = threading.Lock()
_cache: dict[str, "ParamSet"] = {}


class ParamSetError(RuntimeError):
    """Raised when a parameter set is missing or malformed."""


def _canonical_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


class ParamSet:
    """Read-only view over one parameter JSON file.

    Access raw sections with ``ps["age_curves"]``; helpers below cover
    the lookups the engine does in hot loops.
    """

    def __init__(self, name: str, payload: dict[str, Any]):
        self.name = name
        self._payload = payload
        self.param_set_id = f"{name}:{_canonical_hash(payload)}"
        self.model_version = str(payload.get("model_version", "1.0.0"))
        self.label = str(payload.get("label", name))
        # Pre-index hot lookups.
        self._age_curves: dict[str, tuple[float, float, float]] = {
            k: (float(v[0]), float(v[1]), float(v[2]))
            for k, v in payload["age_curves"].items()
            if not k.startswith("_")
        }
        self._mileage: dict[str, tuple[str, float, float, float]] = {
            k: (str(v[0]), float(v[1]), float(v[2]), float(v[3]))
            for k, v in payload["mileage"].items()
            if not k.startswith("_")
        }
        self._base_hazard: dict[str, list[tuple[float, float]]] = {
            k: [(float(a), float(h)) for a, h in v]
            for k, v in payload["base_hazard"].items()
            if not k.startswith("_")
        }
        self._cv_base = {k: float(v) for k, v in payload["cv_base"].items()}
        self._drift_vol = {k: float(v) for k, v in payload["drift_vol"].items()}

    def __getitem__(self, key: str) -> Any:
        try:
            return self._payload[key]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ParamSetError(f"parameter section missing: {key!r} in {self.name}") from exc

    def get(self, key: str, default: Any = None) -> Any:
        return self._payload.get(key, default)

    # -- hot-loop helpers ---------------------------------------------------
    def age_curve(self, curve_key: str) -> tuple[float, float, float]:
        try:
            return self._age_curves[curve_key]
        except KeyError as exc:
            raise ParamSetError(f"no age curve for {curve_key!r}") from exc

    def has_age_curve(self, curve_key: str) -> bool:
        return curve_key in self._age_curves

    def mileage(self, pos: str) -> tuple[str, float, float, float] | None:
        return self._mileage.get(pos)

    def base_hazard_schedule(self, pos: str) -> list[tuple[float, float]]:
        try:
            return self._base_hazard[pos]
        except KeyError as exc:
            raise ParamSetError(f"no hazard schedule for {pos!r}") from exc

    def cv_base(self, pos: str) -> float:
        try:
            return self._cv_base[pos]
        except KeyError as exc:
            raise ParamSetError(f"no cv_base for {pos!r}") from exc

    def drift_vol(self, pos: str) -> float:
        try:
            return self._drift_vol[pos]
        except KeyError as exc:
            raise ParamSetError(f"no drift_vol for {pos!r}") from exc

    def modelling_position(self, platform_group_or_pos: str) -> str:
        """Map a platform lineup group (DL/LB/DB) or true position to the
        position used for curves/hazard/CV.  True positions map to
        themselves."""
        pos = platform_group_or_pos.upper()
        if pos in self._cv_base:
            return pos
        fallback = self["platform_group_fallback_position"].get(pos)
        if fallback is None:
            raise ParamSetError(f"unmodellable position/group: {platform_group_or_pos!r}")
        return str(fallback)

    def strategy_names(self) -> list[str]:
        return [k for k in self["strategies"] if not k.startswith("_")]

    def strategy(self, name: str) -> dict[str, Any]:
        try:
            return self["strategies"][name]
        except KeyError as exc:
            raise ParamSetError(f"unknown strategy profile: {name!r}") from exc

    def to_meta(self) -> dict[str, Any]:
        return {
            "paramSetId": self.param_set_id,
            "label": self.label,
            "modelVersion": self.model_version,
        }


def load_param_set(name: str | None = None) -> ParamSet:
    """Load (and cache) a parameter set by file stem."""
    resolved = name or os.getenv(_ENV_VAR) or DEFAULT_PARAM_SET
    with _lock:
        cached = _cache.get(resolved)
        if cached is not None:
            return cached
    path = PARAMS_DIR / f"{resolved}.json"
    if not path.exists():
        raise ParamSetError(f"parameter set not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParamSetError(f"unreadable parameter set {path}: {exc}") from exc
    ps = ParamSet(resolved, payload)
    with _lock:
        _cache[resolved] = ps
    return ps


def reload() -> None:
    """Test hook: drop the cache so env/file changes are picked up."""
    with _lock:
        _cache.clear()
