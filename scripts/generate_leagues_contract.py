"""Generate the frontend leagues contract from FastAPI's OpenAPI response schema."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend/lib/generated/leagues-contract.js"
MODELS = (
    "PublicLeague",
    "AuthenticatedLeague",
    "UserDefaultTeam",
    "PublicLeaguesResponse",
    "AuthenticatedLeaguesResponse",
)


def _field_type(schema: dict) -> str:
    if "anyOf" in schema:
        return "|".join(_field_type(part) for part in schema["anyOf"])
    if "$ref" in schema:
        return "model:" + schema["$ref"].split("/")[-1]
    kind = schema.get("type")
    if kind == "array":
        return "array:" + _field_type(schema["items"])
    if kind in {"string", "number", "integer", "boolean", "object", "null"}:
        return kind
    raise ValueError(f"unsupported OpenAPI field shape: {schema}")


def _jsdoc_type(kind: str) -> str:
    parts = []
    for member in kind.split("|"):
        if member.startswith("array:"):
            parts.append(f"Array<{_jsdoc_type(member.removeprefix('array:'))}>")
        elif member.startswith("model:"):
            parts.append(member.removeprefix("model:"))
        elif member == "object":
            parts.append("Record<string, unknown>")
        elif member == "integer":
            parts.append("number")
        else:
            parts.append(member)
    return "|".join(parts)


def _render(document: dict) -> str:
    response = document["paths"]["/api/leagues"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    views = {part["$ref"].split("/")[-1] for part in response["anyOf"]}
    if views != {"PublicLeaguesResponse", "AuthenticatedLeaguesResponse"}:
        raise ValueError("/api/leagues OpenAPI views changed")
    components = document["components"]["schemas"]
    relevant = {name: components[name] for name in MODELS}
    fingerprint = hashlib.sha256(
        json.dumps({"response": response, "models": relevant}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    specs = {}
    typedefs = []
    for name in MODELS:
        schema = relevant[name]
        if schema.get("additionalProperties") is not False:
            raise ValueError(f"{name} no longer forbids undeclared fields")
        required = schema.get("required", [])
        fields = {key: _field_type(value) for key, value in schema["properties"].items()}
        specs[name] = {"required": sorted(required), "fields": fields}
        lines = ["/**", f" * @typedef {{Object}} {name}"]
        for key, kind in fields.items():
            label = key if key in required else f"[{key}]"
            lines.append(f" * @property {{{_jsdoc_type(kind)}}} {label}")
        lines.append(" */")
        typedefs.append("\n".join(lines))
    typedefs.append(
        "/** @typedef {PublicLeaguesResponse|AuthenticatedLeaguesResponse} LeaguesResponse */"
    )
    metadata = json.dumps(specs, sort_keys=True, indent=2)
    return (
        "// Generated from GET /api/leagues OpenAPI by scripts/generate_leagues_contract.py.\n"
        "// Do not edit; run python -m scripts.generate_leagues_contract.\n"
        f'export const LEAGUES_SCHEMA_SHA256 = "{fingerprint}";\n\n'
        + "\n\n".join(typedefs)
        + "\n\n"
        + f"const MODELS = {metadata};\n\n"
        + """function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function matchesKind(value, kind) {
  if (kind.includes("|")) return kind.split("|").some((part) => matchesKind(value, part));
  if (kind === "null") return value === null;
  if (kind === "object") return isRecord(value);
  if (kind === "integer") return Number.isInteger(value);
  if (kind === "number") return typeof value === "number" && Number.isFinite(value);
  if (kind.startsWith("model:")) return matchesModel(value, kind.slice(6));
  if (kind.startsWith("array:")) {
    return Array.isArray(value) && value.every((item) => matchesKind(item, kind.slice(6)));
  }
  return typeof value === kind;
}

function matchesModel(value, name) {
  if (!isRecord(value)) return false;
  const model = MODELS[name];
  if (!model) return false;
  return model.required.every((field) => Object.hasOwn(value, field)) &&
    Object.entries(value).every(([field, item]) =>
      Object.hasOwn(model.fields, field) && matchesKind(item, model.fields[field]));
}

/** @param {unknown} value @returns {LeaguesResponse} */
export function parseLeaguesResponse(value) {
  const model = isRecord(value) && Object.hasOwn(value, "userDefaultKey")
    ? "AuthenticatedLeaguesResponse" : "PublicLeaguesResponse";
  if (!matchesModel(value, model)) throw new Error("invalid_leagues_contract");
  return /** @type {LeaguesResponse} */ (value);
}
"""
    )


def generate(*, check: bool = False) -> None:
    from server import app

    expected = _render(app.openapi())
    if check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("generated leagues contract is stale; regenerate and commit it")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generate(check=args.check)


if __name__ == "__main__":
    main()
