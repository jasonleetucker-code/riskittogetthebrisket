"""A minimal JSON-Schema (draft-07 subset) validator for the committed schema.

``jsonschema`` is not a declared dependency, so the fixture test must not rely
on it.  Supported keywords: type, enum, const, required, properties,
additionalProperties, items, minItems, maxItems, anyOf, $ref (local).  Any
other keyword in the schema is an error, so the subset cannot silently ignore
a constraint.
"""

from __future__ import annotations

from typing import Any

_SUPPORTED = {
    "$schema",
    "$id",
    "title",
    "description",
    "definitions",
    "type",
    "enum",
    "const",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "anyOf",
    "$ref",
}
_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is_type(value: Any, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(value: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    root = root or schema
    errors: list[str] = []
    unknown = set(schema) - _SUPPORTED
    if unknown:
        return [f"{path}: unsupported schema keywords {sorted(unknown)}"]
    if "$ref" in schema:
        node: Any = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate(value, node, root, path)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return [f"{path}: {value!r} is not of type {names}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: {value!r} != const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if "anyOf" in schema and not any(not validate(value, s, root, path) for s in schema["anyOf"]):
        errors.append(f"{path}: matches none of anyOf")
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                errors.append(f"{path}: missing required {key!r}")
        props = schema.get("properties", {})
        for key, sub in value.items():
            if key in props:
                errors += validate(sub, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors += validate(sub, schema["additionalProperties"], root, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], root, f"{path}[{i}]")
    return errors
