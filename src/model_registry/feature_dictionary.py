"""Versioned feature dictionary — definitions, never values (AL-0, plan §19.3).

One definition per concept, versioned, so two models cannot silently define "ROS
strength" or "source age" differently. Not a feature store: it holds no value of
any feature, only what each one MEANS, who owns its definition, when it is
known, and what its absence means.

Precedent: ``src/model_registry/training_manifest.py`` — one owner for which
evidence teaches the Hill curve, failing loudly when a hand-kept list diverges.

The committed dictionary is ``config/model_registry/feature_dictionary.json``.
Rules (each pinned by ``tests/model_registry/test_feature_dictionary.py``):

1. Every entry carries all of :data:`REQUIRED_FIELDS`. Missing semantics and a
   known-at rule are mandatory: a feature whose absence is undefined will be
   coerced to 0 by somebody.
2. ``definitionOwner`` names a real module under ``src/`` and a top-level name in
   it, resolved statically (AST — importing nothing).
3. **No redefinition under one version.** Each entry pins ``definitionHash`` — the
   hash of its own definition fields. Editing a definition without bumping its
   ``version`` breaks the pin and fails validation; two entries with the same
   ``(name, version)`` fail; a model manifest that restates a definition
   differently from the dictionary fails.
4. A model's feature manifest that references an undefined ``(name, version)``,
   or a consumer the entry does not allow, fails.

The validated manifest's hash is the ``featureManifestHash`` an evaluation
receipt pins.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DICTIONARY_PATH = REPO / "config" / "model_registry" / "feature_dictionary.json"
DICTIONARY_SCHEMA_VERSION: int = 1

#: The fields that ARE the definition (and so are hashed into ``definitionHash``).
DEFINITION_FIELDS: tuple[str, ...] = (
    "name",
    "version",
    "definitionOwner",
    "unit",
    "knownAtRule",
    "missingSemantics",
    "lineage",
    "allowedConsumers",
)
REQUIRED_FIELDS: tuple[str, ...] = (*DEFINITION_FIELDS, "definitionHash", "description")


class FeatureDictionaryError(ValueError):
    """The dictionary itself is malformed."""


class UndefinedFeatureError(FeatureDictionaryError):
    """A manifest references a feature the dictionary does not define."""


class FeatureRedefinitionError(FeatureDictionaryError):
    """An existing ``(name, version)`` defined a second, different way."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def definition_hash(entry: Mapping[str, Any]) -> str:
    """Hash of exactly the definition fields of an entry."""
    payload = {k: entry.get(k) for k in DEFINITION_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    version: int
    definition_owner: str
    unit: str
    known_at_rule: str
    missing_semantics: str
    lineage: str
    allowed_consumers: tuple[str, ...]
    description: str
    definition_hash: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.name, self.version)


def _owner_resolves(owner: str, root: Path) -> str | None:
    """``None`` when ``module.path:attr`` resolves statically; else why not."""
    if ":" not in owner:
        return f"definitionOwner {owner!r} must be 'module.path:attribute'"
    module, attr = owner.split(":", 1)
    if not module.startswith("src."):
        return f"definitionOwner {owner!r} must live under src/"
    path = root / Path(*module.split("."))
    file = path.with_suffix(".py")
    if not file.is_file():
        file = path / "__init__.py"
        if not file.is_file():
            return f"definitionOwner module {module!r} does not exist"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    head = attr.split(".")[0]
    if head not in names:
        return f"definitionOwner {owner!r}: {head!r} is not a top-level name in {module}"
    return None


def _entry(raw: Mapping[str, Any], *, root: Path) -> FeatureDefinition:
    missing = [k for k in REQUIRED_FIELDS if k not in raw]
    if missing:
        raise FeatureDictionaryError(f"feature {raw.get('name')!r} lacks {missing}")
    for k in ("name", "definitionOwner", "unit", "knownAtRule", "missingSemantics", "lineage"):
        if not isinstance(raw[k], str) or not raw[k].strip():
            raise FeatureDictionaryError(f"feature {raw.get('name')!r}: {k} must be non-empty text")
    version = raw["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise FeatureDictionaryError(f"feature {raw['name']!r}: version must be an int >= 1")
    consumers = raw["allowedConsumers"]
    if (
        not isinstance(consumers, list)
        or not consumers
        or not all(isinstance(c, str) for c in consumers)
    ):
        raise FeatureDictionaryError(
            f"feature {raw['name']!r}: allowedConsumers must name families"
        )
    why = _owner_resolves(raw["definitionOwner"], root)
    if why:
        raise FeatureDictionaryError(why)
    expected = definition_hash(raw)
    if raw["definitionHash"] != expected:
        raise FeatureRedefinitionError(
            f"feature {raw['name']!r} v{version}: its definition no longer matches its pinned "
            f"definitionHash. A changed definition is a NEW version — bump 'version' and keep "
            f"the old entry; never redefine an existing version in place."
        )
    return FeatureDefinition(
        name=raw["name"],
        version=version,
        definition_owner=raw["definitionOwner"],
        unit=raw["unit"],
        known_at_rule=raw["knownAtRule"],
        missing_semantics=raw["missingSemantics"],
        lineage=raw["lineage"],
        allowed_consumers=tuple(consumers),
        description=str(raw["description"]),
        definition_hash=expected,
    )


@dataclass(frozen=True)
class FeatureDictionary:
    version: int
    features: Mapping[tuple[str, int], FeatureDefinition]
    raw_hash: str

    def get(self, name: str, version: int) -> FeatureDefinition:
        try:
            return self.features[(name, version)]
        except KeyError:
            raise UndefinedFeatureError(f"feature {name!r} v{version} is not defined") from None


def build_dictionary(doc: Mapping[str, Any], *, root: Path = REPO) -> FeatureDictionary:
    if doc.get("schemaVersion") != DICTIONARY_SCHEMA_VERSION:
        raise FeatureDictionaryError(
            f"dictionary schemaVersion must be {DICTIONARY_SCHEMA_VERSION}, not {doc.get('schemaVersion')!r}"
        )
    version = doc.get("dictionaryVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise FeatureDictionaryError("dictionaryVersion must be an int >= 1")
    entries = doc.get("features")
    if not isinstance(entries, list) or not entries:
        raise FeatureDictionaryError("dictionary has no features")
    features: dict[tuple[str, int], FeatureDefinition] = {}
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise FeatureDictionaryError("each feature entry must be an object")
        f = _entry(raw, root=root)
        if f.key in features:
            raise FeatureRedefinitionError(
                f"feature {f.name!r} v{f.version} is defined twice; one version, one definition"
            )
        features[f.key] = f
    raw_hash = hashlib.sha256(_canonical(doc).encode("utf-8")).hexdigest()
    return FeatureDictionary(version=version, features=features, raw_hash=raw_hash)


def load_dictionary(
    path: Path = DEFAULT_DICTIONARY_PATH, *, root: Path = REPO
) -> FeatureDictionary:
    return build_dictionary(json.loads(Path(path).read_text(encoding="utf-8")), root=root)


def validate_manifest(
    dictionary: FeatureDictionary,
    *,
    consumer: str,
    features: Sequence[Mapping[str, Any]],
) -> str:
    """Validate a model's feature manifest and return its ``featureManifestHash``.

    Each item is ``{"name", "version"}``, optionally restating definition fields;
    a restatement that differs from the dictionary is a redefinition and fails."""
    if not features:
        raise FeatureDictionaryError("a feature manifest must list at least one feature")
    seen: set[tuple[str, int]] = set()
    resolved: list[dict[str, Any]] = []
    for item in features:
        name, version = item.get("name"), item.get("version")
        if not isinstance(name, str) or isinstance(version, bool) or not isinstance(version, int):
            raise FeatureDictionaryError(f"manifest item needs name + int version: {dict(item)!r}")
        d = dictionary.get(name, version)
        restated = {
            k: item[k] for k in DEFINITION_FIELDS if k in item and k not in ("name", "version")
        }
        for k, v in restated.items():
            mine = {
                "definitionOwner": d.definition_owner,
                "unit": d.unit,
                "knownAtRule": d.known_at_rule,
                "missingSemantics": d.missing_semantics,
                "lineage": d.lineage,
                "allowedConsumers": list(d.allowed_consumers),
            }[k]
            if v != mine:
                raise FeatureRedefinitionError(
                    f"manifest for {consumer!r} redefines {name!r} v{version} field {k!r}"
                )
        if consumer not in d.allowed_consumers:
            raise FeatureDictionaryError(
                f"{consumer!r} is not an allowed consumer of {name!r} v{version}"
            )
        if d.key in seen:
            raise FeatureDictionaryError(f"manifest lists {name!r} v{version} twice")
        seen.add(d.key)
        resolved.append({"name": name, "version": version, "definitionHash": d.definition_hash})
    resolved.sort(key=lambda r: (r["name"], r["version"]))
    payload = {"consumer": consumer, "dictionaryVersion": dictionary.version, "features": resolved}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
