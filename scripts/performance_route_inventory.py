"""Bounded source inventory, not a benchmark or a proof of runtime reachability."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs")
TOKEN = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|"
    r"`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|\.\.\.|[^\s]"
)


def literal(token):
    if len(token) < 2 or token[0] not in "'\"`" or token[-1] != token[0]:
        return None
    value = token[1:-1]
    return None if "\\" in value or "${" in value else value


def exported_methods(source):
    tokens = [m.group() for m in TOKEN.finditer(source) if not m.group().startswith(("//", "/*"))]
    methods = set()
    for i, token in enumerate(tokens):
        if token != "export":
            continue
        rest = tokens[i + 1 :]
        if rest[:1] == ["async"]:
            rest = rest[1:]
        if (
            len(rest) >= 3
            and rest[0] == "function"
            and rest[2] == "("
            and rest[1] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        ):
            methods.add(rest[1])
    return sorted(methods)


def call_arguments(tokens, start):
    """Split a lexical call at its outer commas; malformed calls stay unknown."""
    stack, args, current = [")"], [], []
    pairs = {"(": ")", "[": "]", "{": "}"}
    for token in tokens[start + 1 :]:
        if token in pairs:
            stack.append(pairs[token])
        elif token in (")", "]", "}"):
            if not stack or token != stack.pop():
                return None
            if not stack:
                return args + [current]
        if token == "," and len(stack) == 1:
            args.append(current)
            current = []
        else:
            current.append(token)
    return None


def request(tokens, index):
    args = call_arguments(tokens, index + 1)
    target = literal(args[0][0]) if args and len(args[0]) == 1 else None
    # Never serialize query values, external URLs, dynamic expressions or request bodies.
    path = target.split("?", 1)[0].split("#", 1)[0] if target else None
    if not path or not re.fullmatch(r"/api/[A-Za-z0-9_/.[\]-]+", path):
        path = None
    method = "GET" if args and len(args) == 1 else None
    if args and len(args) == 2:
        options = args[1]
        # Only a plain options object with no spread/computed keys is locally provable.
        if options[:1] == ["{"] and options[-1:] == ["}"] and "..." not in options:
            props = call_arguments(["("] + options[1:-1] + [")"], 0)
            methods = []
            safe = True
            for prop in props or []:
                if not prop:
                    continue
                if len(prop) < 3 or prop[1] != ":":
                    safe = False
                    continue
                key = literal(prop[0]) or prop[0]
                if key == "method":
                    methods.append(literal(prop[2]) if len(prop) == 3 else None)
            if safe and not methods:
                method = "GET"
            elif (
                safe
                and len(methods) == 1
                and methods[0] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            ):
                method = methods[0]
    return {
        "target": path,
        "method": method,
        "targetStatus": "LITERAL" if path else "UNKNOWN",
        "operationClassification": "UNKNOWN",
        "runtimeReachability": "UNKNOWN",
    }


def inspect_js(source):
    tokens = [m.group() for m in TOKEN.finditer(source) if not m.group().startswith(("//", "/*"))]
    imports, requests, hooks = set(), [], set()
    unknown_import = False
    for index, token in enumerate(tokens):
        following = tokens[index + 1 : index + 3]
        if token == "from" and following:
            spec = literal(following[0])
            if spec:
                imports.add(spec)
        if token in {"import", "require"}:
            if following and literal(following[0]) is not None:
                imports.add(literal(following[0]))
            elif following[:1] == ["("]:
                args = call_arguments(tokens, index + 1)
                spec = literal(args[0][0]) if args and len(args[0]) == 1 else None
                if spec:
                    imports.add(spec)
                else:
                    unknown_import = True
        if following[:1] == ["("] and token == "fetch":
            requests.append(request(tokens, index))
        if following[:1] == ["("] and re.fullmatch(r"use[A-Z]\w*", token):
            hooks.add(token)
    return sorted(imports), requests, sorted(hooks), unknown_import


def inventory(root: Path, *, max_files=4096, max_bytes=1_000_000, max_depth=32):
    root = root.resolve()
    frontend, app = root / "frontend", root / "frontend/app"
    paths = sorted(
        p
        for p in app.rglob("*")
        if p.is_file() and p.suffix in EXTENSIONS and p.stem in {"page", "route"}
    )
    truncated = len(paths) > max_files
    paths = paths[:max_files]
    modules, problems = {}, []

    def relative(path):
        return path.relative_to(root).as_posix()

    def resolve(spec, parent):
        candidate = frontend / spec[2:] if spec.startswith("@/") else parent.parent / spec
        if not (spec.startswith("@/") or spec.startswith(".")):
            return None, "EXTERNAL_PACKAGE"
        candidates = (
            [candidate]
            if candidate.suffix
            else [
                *(Path(str(candidate) + ext) for ext in EXTENSIONS),
                *(candidate / ("index" + ext) for ext in EXTENSIONS),
            ]
        )
        for item in candidates:
            item = item.resolve()
            if not item.is_relative_to(root):
                return None, "OUTSIDE_ROOT"
            if item.is_file():
                return (item, None) if item.suffix in EXTENSIONS else (None, "NON_CODE_ASSET")
        return None, "UNRESOLVED"

    def visit(path, depth):
        name = relative(path)
        if name in modules:
            return
        if depth > max_depth or len(modules) >= max_files:
            problems.append({"path": name, "reason": "GRAPH_LIMIT"})
            return
        if path.stat().st_size > max_bytes:
            problems.append({"path": name, "reason": "FILE_SIZE_LIMIT"})
            return
        data = path.read_bytes()
        source = data.decode("utf-8")
        imports, requests, hooks, dynamic = inspect_js(source)
        node = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "imports": [],
            "requests": requests,
            "hooks": hooks,
            "dynamicImportUnknown": dynamic,
            "bffExportMethods": exported_methods(source),
        }
        modules[name] = node  # Insert before recursion: cycles are bounded.
        for spec in imports:
            resolved, reason = resolve(spec, path)
            node["imports"].append(
                {"path": relative(resolved) if resolved else None, "status": reason or "RESOLVED"}
            )
            if resolved:
                visit(resolved, depth + 1)

    routes = []
    for path in paths:
        if not path.resolve().is_relative_to(root):
            problems.append({"reason": "OUTSIDE_ROOT"})
            continue
        visit(path, 0)
        name = relative(path)
        layouts = []
        if path.stem == "page":
            for parent in (path.parent, *path.parent.parents):
                if not parent.is_relative_to(app):
                    break
                for ext in EXTENSIONS:
                    layout = parent / ("layout" + ext)
                    if layout.is_file() and layout.resolve().is_relative_to(root):
                        visit(layout, 0)
                        layouts.append(relative(layout))
        reachable, pending = set(), [name, *layouts]
        while pending:
            current = pending.pop()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(
                i["path"] for i in modules.get(current, {}).get("imports", []) if i["path"]
            )
        segments = path.parent.relative_to(app).parts
        intercepted = any(segment.startswith(("(.)", "(..)", "(...)")) for segment in segments)
        route = (
            None
            if intercepted
            else "/"
            + "/".join(
                segment
                for segment in segments
                if not segment.startswith("@")
                and not (segment.startswith("(") and segment.endswith(")"))
            )
        )
        routes.append(
            {
                "template": route,
                "templateStatus": "UNKNOWN_INTERCEPTION" if intercepted else "FILESYSTEM_TEMPLATE",
                "kind": "PAGE" if path.stem == "page" else "BFF",
                "source": name,
                "ancestorLayouts": layouts,
                "moduleClosure": sorted(reachable),
                "requests": [
                    {"source": p, **r}
                    for p in sorted(reachable)
                    for r in modules.get(p, {}).get("requests", [])
                ],
                "runtimePathComplete": False,
            }
        )
    backend = []
    server = root / "server.py"
    if server.is_file() and server.stat().st_size <= max_bytes * 4:
        data = server.read_bytes()
        tree = ast.parse(data)
        constructors = {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi"
            for alias in node.names
            if alias.name in {"FastAPI", "APIRouter"}
        }
        owners = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in constructors
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id in owners
                    and dec.func.attr
                    in {"get", "post", "put", "patch", "delete", "head", "options"}
                ):
                    path = dec.args[0] if dec.args else None
                    backend.append(
                        {
                            "method": dec.func.attr.upper(),
                            "handler": node.name,
                            "path": path.value
                            if isinstance(path, ast.Constant)
                            and isinstance(path.value, str)
                            and re.fullmatch(r"/api/[A-Za-z0-9_/.[\]{}:-]+", path.value)
                            else None,
                            "prefixResolution": "UNKNOWN",
                            "line": node.lineno,
                        }
                    )
        backend_hash = hashlib.sha256(data).hexdigest()
    else:
        backend_hash = None
    return {
        "schemaVersion": 1,
        "pageTemplates": sum(r["kind"] == "PAGE" for r in routes),
        "bffTemplates": sum(r["kind"] == "BFF" for r in routes),
        "routes": routes,
        "modules": modules,
        "backendServerDecorators": backend,
        "serverSha256": backend_hash,
        "inventoryTruncated": truncated,
        "problems": problems,
        "limitations": [
            "Lexical JS inventory, not a JS parser or runtime call graph.",
            "Layouts are included conservatively; conditional providers, aliases other than @/, computed calls and external packages require review.",
            "All imported modules are possible dependencies, not proof their calls execute.",
            "Backend mounted-router prefixes and runtime registration remain unresolved.",
            "No timing, payload, provider-call or completeness claim.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(inventory(args.root), indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
