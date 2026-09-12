"""Explicit asset dependencies and deterministic rebuild planning.

This is a registry, not a scheduler. Freshness/priority/consumer metadata describes
existing producers; it never starts them. A coordinator records a build's input
fingerprint only after its output has passed validation and been published.
Observation timestamps are deliberately absent from computation fingerprints.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


class DependencyError(ValueError):
    """An asset registry or supplied generation identity is incomplete."""


@dataclass(frozen=True)
class AssetSpec:
    name: str
    inputs: tuple[str, ...] = ()
    producer: str = ""
    version: str = ""
    freshness_seconds: int | None = None
    priority: int = 0
    consumers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("name", "producer", "version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise DependencyError(f"{field_name} must be a nonempty string")
        for field_name in ("inputs", "consumers"):
            values = getattr(self, field_name)
            if isinstance(values, str):
                raise DependencyError(f"{field_name} must be an iterable of names")
            values = tuple(values)
            if any(not isinstance(value, str) or not value for value in values):
                raise DependencyError(f"{field_name} must be an iterable of names")
            object.__setattr__(self, field_name, values)
        if len(set(self.inputs)) != len(self.inputs):
            raise DependencyError(f"Duplicate dependencies for {self.name}")
        if self.freshness_seconds is not None and (
            type(self.freshness_seconds) is not int or self.freshness_seconds < 0
        ):
            raise DependencyError("freshness_seconds must be a nonnegative integer or None")
        if type(self.priority) is not int:
            raise DependencyError("priority must be an integer")


class DependencyRegistry:
    def __init__(self, specs: Iterable[AssetSpec]):
        assets = {}
        for spec in specs:
            if spec.name in assets:
                raise DependencyError(f"Duplicate asset: {spec.name}")
            assets[spec.name] = spec
        children: dict[str, set[str]] = {name: set() for name in assets}
        remaining = {}
        for name, spec in assets.items():
            missing = set(spec.inputs).difference(assets)
            if missing:
                raise DependencyError(f"Missing dependencies for {name}: {sorted(missing)}")
            remaining[name] = len(spec.inputs)
            for dependency in spec.inputs:
                children[dependency].add(name)
        ready = [(-assets[name].priority, name) for name, count in remaining.items() if count == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            _, name = heapq.heappop(ready)
            order.append(name)
            for dependent in sorted(children[name]):
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    heapq.heappush(ready, (-assets[dependent].priority, dependent))
        if len(order) != len(assets):
            raise DependencyError(f"Dependency cycle: {sorted(set(assets).difference(order))}")
        self.assets: Mapping[str, AssetSpec] = MappingProxyType(assets)
        self.order = tuple(order)
        self._children = {name: frozenset(values) for name, values in children.items()}

    def _spec(self, name: str) -> AssetSpec:
        try:
            return self.assets[name]
        except KeyError as exc:
            raise DependencyError(f"Unknown asset: {name}") from exc

    def descendants(self, changed: Iterable[str]) -> tuple[str, ...]:
        """Affected consumers once each, in dependency order, excluding roots."""
        roots = set(changed)
        for name in roots:
            self._spec(name)
        pending = list(roots)
        visited = set(roots)
        while pending:
            for child in self._children[pending.pop()]:
                if child not in visited:
                    visited.add(child)
                    pending.append(child)
        return tuple(name for name in self.order if name in visited - roots)

    def fingerprint(
        self, name: str, generations: Mapping[str, str], config_hash: str = "none"
    ) -> str:
        spec = self._spec(name)
        if not isinstance(config_hash, str) or not config_hash:
            raise DependencyError("config_hash must be a nonempty string")
        inputs = {}
        for dependency in sorted(spec.inputs):
            value = generations.get(dependency)
            if not isinstance(value, str) or not value:
                raise DependencyError(f"Missing generation for {name} input: {dependency}")
            inputs[dependency] = value
        identity = {
            "asset": name,
            "producer": spec.producer,
            "modelVersion": spec.version,
            "configHash": config_hash,
            "inputGenerations": inputs,
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def plan(
        self,
        generations: Mapping[str, str],
        accepted_fingerprints: Mapping[str, str],
        config_hashes: Mapping[str, str] | None = None,
    ) -> tuple[str, ...]:
        """Return builds whose inputs/config/model changed, plus descendants.

        ``generations`` names actual accepted output identities. Source freshness
        observations can change without changing these identities. Pending parents
        are built before children; child fingerprints must be taken again using
        the newly accepted parent outputs at execution time. No accepted state is
        mutated by planning or by a failed producer.
        """
        configs = config_hashes or {}
        pending: set[str] = set()
        for name in self.assets.keys() & generations.keys():
            if not isinstance(generations[name], str) or not generations[name]:
                raise DependencyError(f"Invalid output generation for {name}")
        for name in self.order:
            spec = self.assets[name]
            if not generations.get(name) or pending.intersection(spec.inputs):
                pending.add(name)
                continue
            expected = self.fingerprint(name, generations, configs.get(name, "none"))
            if accepted_fingerprints.get(name) != expected:
                pending.add(name)
        return tuple(name for name in self.order if name in pending)
