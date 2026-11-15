"""Feature census: execution surfaces mapped to the tests that reference them.

Evidence tooling for the continuous-verification standard
(``docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md`` section 2).
It is NOT an inventory owner and NOT a roadmap: it only answers "which test
files mention this route / page / flag / job by string?".

Honesty rules baked into the output:

* "no test reference found" means exactly that - no test file matched by the
  recorded string rules.  It does NOT prove the item is untested (a test may
  exercise it through a helper, a client fixture or a dynamic path).
* a match is a string match, never proof of an assertion.  Every match records
  HOW it matched (``literal-path`` / ``template-prefix`` / ``handler-name`` /
  ``route-import`` / ``quoted-flag-name`` ...) so a reader can judge it.

Reused (not re-implemented): ``src.api.flag_reachability`` (transitive
flag -> route reachability, real repo only), the committed page-access
inventory ``docs/ui/evidence/route_inventory_2026-11-01.json`` (derived from
``frontend/lib/public-routes.js`` and pinned to it by a vitest), and
``scripts.verify_owner_held_flags.OWNER_HELD_FLAGS`` (read statically).

Offline and static: never starts the server, never imports ``server``,
never touches the network.  Deterministic: sorted output, no timestamps
(only ``asOfCommit``, which ``--check`` ignores), repo-relative paths only.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = "docs/audits/remediation_2026-11-06"
SCHEMA = "feature_census.v1"

_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_DIRS = {"node_modules", ".next", "__pycache__", ".git", ".claude"}

# Path segments that mark value / money / probability producing surfaces.
VALUE_KEYWORDS = frozenset(
    {
        "trade",
        "trades",
        "draft",
        "faab",
        "waiver",
        "waivers",
        "bdvm",
        "valuation",
        "ros",
        "rankings",
        "ranking",
        "auction",
        "forecast",
        "simulate",
        "analyze",
        "finder",
        "gameplan",
        "values",
    }
)
_ADMIN_NAME = re.compile(
    r"^(_?require_admin\w*|\w*admin_session\w*|_?authori[sz]e\w*|_authorizer)$"
)
_ROUTE_HINT = re.compile(r"@\w+\.(?:get|post|put|patch|delete|head|options)\(|add_api_route")
_PARAM = re.compile(r"\{[^}]*\}|\[[^\]]*\]")
_API_TOKEN = re.compile(r"/api/[A-Za-z0-9_\-/.\[\]{}$:]*")
_PAGE_TOKEN = re.compile(r"(?<=[\"'`])/[A-Za-z0-9_\-/.\[\]{}$:]*")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTED_IDENT = re.compile(r"[\"'`]([A-Za-z][A-Za-z0-9_]+)[\"'`]")
_CLASS_RANK = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}
CLASS_LABELS = {
    "a": "mutating / auth / admin route",
    "b": "value / money / probability surface",
    "c": "flag default-ON",
    "d": "scheduled job",
    "e": "other",
}
WEAK_KINDS = frozenset({"template-prefix", "handler-name", "bare-identifier", "enumerating-file"})
# A test file that matches at least this many items of one surface is treated as
# a registry-wide enumeration (it lists everything), not a test of that item.
ENUMERATION_THRESHOLD = {"backendRoute": 40, "bridgeRoute": 40, "page": 30, "flag": 20, "job": 15}
_KIND_STRENGTH = [
    "literal-path",
    "literal-template",
    "template-pattern",
    "route-import",
    "page-import",
    "quoted-flag-name",
    "env-var",
    "unit-name",
    "workflow-file",
    "exec-script",
    "handler-name",
    "template-prefix",
    "bare-identifier",
    "enumerating-file",
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _walk_files(base: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    if not base.is_dir():
        return out
    for pat in patterns:
        for p in base.rglob(pat):
            if p.is_file() and not (set(p.relative_to(base).parts) & _SKIP_DIRS):
                out.append(p)
    return sorted(set(out))


def _segments(path: str) -> set[str]:
    return {s for s in re.split(r"[/\-_\[\]{}]+", path.lower()) if s}


def has_value_keyword(path: str) -> bool:
    return bool(_segments(path) & VALUE_KEYWORDS)


def template_prefix(path: str) -> str | None:
    """Static prefix before the first ``{param}`` / ``[param]`` segment, else None."""
    m = _PARAM.search(path)
    return path[: m.start()] if m else None


def _norm_token(tok: str) -> str:
    tok = tok.rstrip(".:,")
    return tok.rstrip("/") if len(tok) > 1 else tok


def git_head(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# --------------------------------------------------------------------------
# test corpus
# --------------------------------------------------------------------------


class TestFile:
    __test__ = False  # not a pytest class

    def __init__(self, rel: str, framework: str, text: str) -> None:
        self.rel = rel
        self.framework = framework
        self.text = text
        self.api_tokens = {_norm_token(t) for t in _API_TOKEN.findall(text)}
        self.page_tokens = {_norm_token(t) for t in _PAGE_TOKEN.findall(text)}
        self.idents = set(_IDENT.findall(text))
        self.quoted = set(_QUOTED_IDENT.findall(text))


def _framework(rel: str) -> str:
    if rel.endswith(".py"):
        return "pytest"
    if "/specs/" in rel and ".spec." in rel:
        return "playwright"
    return "vitest"


def load_test_corpus(root: Path) -> list[TestFile]:
    files: list[Path] = []
    for base in ("tests", "frontend"):
        files += _walk_files(root / base, ("test_*.py", "*_test.py"))
        files += _walk_files(root / base, ("*.test.*", "*.spec.*"))
    out = []
    for p in sorted(set(files)):
        rel = _rel(root, p)
        out.append(TestFile(rel, _framework(rel), _read(p)))
    return out


def _best_kind(refs: list[dict]) -> str | None:
    for kind in _KIND_STRENGTH:
        if any(kind in r["kinds"] for r in refs):
            return kind
    return None


def _template_regex(url: str) -> re.Pattern[str]:
    parts = []
    for seg in url.split("/"):
        parts.append("[^/]+" if ("{" in seg or "[" in seg) else re.escape(seg))
    return re.compile("/".join(parts))


def _collect(matches: dict[str, set[str]]) -> tuple[list[dict], str | None]:
    refs = [{"file": f, "kinds": sorted(k)} for f, k in sorted(matches.items())]
    best = None
    for kind in _KIND_STRENGTH:
        if any(kind in k for k in matches.values()):
            best = kind
            break
    return refs, best


def match_url(
    corpus: list[TestFile], url: str, *, handler: str | None = None, import_stem: str | None = None
) -> tuple[list[dict], str | None]:
    """Match a URL path (``/api/x`` or a page path) against the corpus."""
    matches: dict[str, set[str]] = {}
    prefix = template_prefix(url)
    norm = _norm_token(url)
    pattern = _template_regex(norm) if prefix is not None else None
    is_api = url.startswith("/api/")
    for tf in corpus:
        kinds: set[str] = set()
        toks = tf.api_tokens if is_api else tf.page_tokens
        if norm != "/" and norm in toks:
            kinds.add("literal-template" if prefix is not None else "literal-path")
        if pattern is not None and any(pattern.fullmatch(t) for t in toks):
            kinds.add("template-pattern")
        elif prefix is not None and prefix.rstrip("/") not in ("", "/api"):
            stem = prefix
            if any(t.startswith(stem) and len(t) > len(stem) for t in toks):
                kinds.add("template-prefix")
        if import_stem and import_stem in tf.text:
            kinds.add("route-import" if is_api else "page-import")
        if handler and handler in tf.idents:
            kinds.add("handler-name")
        if kinds:
            matches[tf.rel] = kinds
    return _collect(matches)


def match_flag(corpus: list[TestFile], flag: str) -> tuple[list[dict], str | None]:
    env = "RISKIT_FEATURE_" + flag.upper()
    matches: dict[str, set[str]] = {}
    for tf in corpus:
        kinds: set[str] = set()
        if flag in tf.quoted:
            kinds.add("quoted-flag-name")
        elif flag in tf.idents:
            kinds.add("bare-identifier")
        if env in tf.idents:
            kinds.add("env-var")
        if kinds:
            matches[tf.rel] = kinds
    return _collect(matches)


def match_words(corpus: list[TestFile], needles: dict[str, str]) -> tuple[list[dict], str | None]:
    """``needles`` maps kind -> substring searched in test text."""
    matches: dict[str, set[str]] = {}
    for tf in corpus:
        kinds = {kind for kind, needle in needles.items() if needle and needle in tf.text}
        if kinds:
            matches[tf.rel] = kinds
    return _collect(matches)


# --------------------------------------------------------------------------
# backend routes
# --------------------------------------------------------------------------


def _str_consts(node: ast.AST) -> set[str]:
    return {
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _server_auth_sets(root: Path) -> dict[str, set[str]]:
    sets = {"public_exact": set(), "self_authed": set(), "public_prefix": set()}
    names = {
        "_PUBLIC_API_EXACT": "public_exact",
        "_SELF_AUTHED_API_EXACT": "self_authed",
        "_PUBLIC_API_PREFIXES": "public_prefix",
    }
    try:
        tree = ast.parse(_read(root / "server.py"))
    except SyntaxError:
        return sets
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in names:
                    sets[names[tgt.id]] |= _str_consts(node.value)
    return sets


def _router_prefixes(tree: ast.Module) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if fname not in ("APIRouter", "FastAPI"):
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = str(kw.value.value)
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                prefixes[tgt.id] = prefix
    return prefixes


def _handler_facts(fn: ast.AST) -> dict:
    admin = False
    gates: set[str] = set()
    for sub in ast.walk(fn):
        ident = sub.id if isinstance(sub, ast.Name) else getattr(sub, "attr", None)
        if isinstance(sub, (ast.Name, ast.Attribute)) and ident and _ADMIN_NAME.match(ident):
            admin = True
        if isinstance(sub, ast.Call):
            f = sub.func
            fname = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if (
                fname == "is_enabled"
                and sub.args
                and isinstance(sub.args[0], ast.Constant)
                and isinstance(sub.args[0].value, str)
            ):
                gates.add(sub.args[0].value)
    return {"admin": admin, "gates": gates}


def scan_backend(root: Path) -> list[dict]:
    """Every HTTP route the source registers (``@app.x``, routers, ``add_api_route``)."""
    files = [root / "server.py", *_walk_files(root / "src", ("*.py",))]
    routes: dict[tuple[str, str], dict] = {}

    def add(method, path, module, raw, handler, facts):
        key = (method, path)
        rec = routes.setdefault(
            key,
            {
                "method": method,
                "path": path,
                "module": module,
                "rawPath": raw,
                "handlers": set(),
                "admin": False,
                "gates": set(),
            },
        )
        rec["handlers"].add(handler)
        rec["admin"] = rec["admin"] or facts["admin"]
        rec["gates"] |= facts["gates"]

    for f in files:
        if not f.is_file():
            continue
        text = _read(f)
        if not _ROUTE_HINT.search(text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        module = _rel(root, f)
        prefixes = _router_prefixes(tree)
        funcs: dict[str, ast.AST] = {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.setdefault(n.name, n)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not n.decorator_list:
                    continue
                facts = None
                for dec in n.decorator_list:
                    if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                        continue
                    verb = dec.func.attr.lower()
                    if verb not in _VERBS or not dec.args:
                        continue
                    a0 = dec.args[0]
                    if not (
                        isinstance(a0, ast.Constant)
                        and isinstance(a0.value, str)
                        and a0.value.startswith("/")
                    ):
                        continue
                    if facts is None:
                        facts = _handler_facts(n)
                    recv = dec.func.value
                    prefix = prefixes.get(recv.id, "") if isinstance(recv, ast.Name) else ""
                    dec_admin = any(
                        _ADMIN_NAME.match(getattr(s, "id", getattr(s, "attr", "")) or "")
                        for s in ast.walk(dec)
                        if isinstance(s, (ast.Name, ast.Attribute))
                    )
                    fx = {"admin": facts["admin"] or dec_admin, "gates": facts["gates"]}
                    add(verb.upper(), prefix + a0.value, module, a0.value, n.name, fx)
            elif (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_api_route"
                and len(n.args) >= 2
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)
                and isinstance(n.args[1], ast.Name)
            ):
                methods = ["GET"]
                for kw in n.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        methods = [
                            str(e.value).upper()
                            for e in kw.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        ] or methods
                hname = n.args[1].id
                fx = (
                    _handler_facts(funcs[hname])
                    if hname in funcs
                    else {"admin": False, "gates": set()}
                )
                for m in methods:
                    add(m, n.args[0].value, module, n.args[0].value, hname, fx)
    return [routes[k] for k in sorted(routes, key=lambda k: (k[1], k[0]))]


def classify_auth(path: str, admin: bool, auth: dict[str, set[str]]) -> str:
    if not path.startswith("/api/"):
        return "non-api"
    if path.startswith("/api/test/") or path == "/api/test":
        return "test-only"
    if admin or "/admin" in path:
        return "admin"
    if path in auth["self_authed"]:
        return "self-authed"
    if path in auth["public_exact"]:
        return "public"
    for pre in auth["public_prefix"]:
        if path == pre or path.startswith(pre + "/"):
            return "public"
    return "private"


def _transitive_flags(root: Path, flags: list[str]) -> dict[str, set[str]]:
    """raw decorator path -> flags reaching it (name-based over-approximation).

    Reuses ``src.api.flag_reachability`` which is hard-wired to the real repo,
    so it only runs against the real checkout.
    """
    if root.resolve() != REPO_ROOT.resolve():
        return {}
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from src.api import flag_reachability as fr  # noqa: PLC0415

        idx = fr._build_index()
        out: dict[str, set[str]] = {}
        for flag in flags:
            for raw in fr.reachable_routes_for_flag(flag, idx):
                out.setdefault(raw, set()).add(flag)
        return out
    except Exception:  # pragma: no cover - evidence tooling must not crash the census
        return {}
    finally:
        if sys.path and sys.path[0] == str(REPO_ROOT):
            sys.path.pop(0)


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------


def _page_url(parts: tuple[str, ...]) -> str:
    segs = [p for p in parts if not (p.startswith("(") and p.endswith(")"))]
    return "/" + "/".join(segs) if segs else "/"


def scan_pages(root: Path) -> list[dict]:
    app = root / "frontend" / "app"
    inv: dict[str, str] = {}
    inv_path = root / "docs" / "ui" / "evidence" / "route_inventory_2026-11-01.json"
    if inv_path.is_file():
        try:
            for r in json.loads(_read(inv_path)).get("routes", []):
                inv[r["route"]] = r.get("access", "unknown")
        except (ValueError, KeyError, TypeError):
            inv = {}
    out = []
    for p in _walk_files(app, ("page.js", "page.jsx", "page.ts", "page.tsx")):
        rel = p.relative_to(app)
        if rel.parts and rel.parts[0] == "api":
            continue
        url = _page_url(rel.parts[:-1])
        out.append(
            {
                "url": url,
                "file": _rel(root, p),
                "access": inv.get(url, "unknown"),
                "importStem": _rel(root, p).rsplit(".", 1)[0].replace("frontend/", "", 1),
            }
        )
    return sorted(out, key=lambda r: r["url"])


def scan_bridges(root: Path) -> list[dict]:
    app = root / "frontend" / "app"
    out = []
    for p in _walk_files(app / "api", ("route.js", "route.jsx", "route.ts", "route.tsx")):
        rel = p.relative_to(app)
        url = _page_url(rel.parts[:-1])
        methods = sorted(
            set(
                re.findall(
                    r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD)\b", _read(p)
                )
                + re.findall(r"export\s+const\s+(GET|POST|PUT|PATCH|DELETE|HEAD)\b", _read(p))
            )
        )
        out.append(
            {
                "url": url,
                "file": _rel(root, p),
                "methods": methods or ["UNKNOWN"],
                "importStem": _rel(root, p).rsplit(".", 1)[0].replace("frontend/", "", 1),
            }
        )
    return sorted(out, key=lambda r: r["url"])


# --------------------------------------------------------------------------
# flags
# --------------------------------------------------------------------------


def _dict_assign(tree: ast.Module, name: str) -> ast.Dict | None:
    for node in tree.body:
        tgt = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tgt, val = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            tgt, val = (t.id if isinstance(t, ast.Name) else None), node.value
        if tgt == name and isinstance(val, ast.Dict):
            return val
    return None


def scan_flags(root: Path) -> list[dict]:
    src = _read(root / "src" / "api" / "feature_flags.py")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    str_consts = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            str_consts[node.targets[0].id] = node.value.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            str_consts[node.target.id] = node.value.value
    defaults: dict[str, bool] = {}
    d = _dict_assign(tree, "_DEFAULTS")
    if d:
        for k, v in zip(d.keys, d.values, strict=True):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                defaults[str(k.value)] = bool(v.value)
    gate: dict[str, str] = {}
    g = _dict_assign(tree, "_GATE_STATUS")
    if g:
        for k, v in zip(g.keys, g.values, strict=True):
            if isinstance(k, ast.Constant):
                if isinstance(v, ast.Name):
                    gate[str(k.value)] = str_consts.get(v.id, v.id)
                elif isinstance(v, ast.Constant):
                    gate[str(k.value)] = str(v.value)
    held: dict[str, dict] = {}
    held_path = root / "scripts" / "verify_owner_held_flags.py"
    if held_path.is_file():
        try:
            ht = ast.parse(_read(held_path))
            hd = _dict_assign(ht, "OWNER_HELD_FLAGS")
            if hd:
                for k, v in zip(hd.keys, hd.values, strict=True):
                    req, why, _bad = ast.literal_eval(v)
                    held[str(k.value)] = {"requiredState": bool(req), "decision": why}
        except (SyntaxError, ValueError):
            held = {}
    return [
        {
            "name": n,
            "default": defaults[n],
            "gateStatus": gate.get(n, "UNKNOWN"),
            "ownerHeld": held.get(n),
        }
        for n in sorted(defaults)
    ]


# --------------------------------------------------------------------------
# scheduled jobs
# --------------------------------------------------------------------------


def _unit_stem(name: str) -> str:
    for suf in (".template", ".timer", ".service"):
        if name.endswith(suf):
            name = name[: -len(suf)]
    return name


def scan_jobs(root: Path) -> list[dict]:
    jobs = []
    sd = root / "deploy" / "systemd"
    for p in _walk_files(sd, ("*.timer", "*.timer.template")):
        stem = _unit_stem(p.name)
        timer = _read(p)
        sched = sorted(
            {
                ln.split("=", 1)[1].strip()
                for ln in timer.splitlines()
                if ln.split("=", 1)[0].strip()
                in ("OnCalendar", "OnBootSec", "OnUnitActiveSec", "OnUnitInactiveSec")
                and "=" in ln
                and not ln.lstrip().startswith("#")
            }
        )
        svc_text = ""
        for cand in (f"{stem}.service.template", f"{stem}.service"):
            if (sd / cand).is_file():
                svc_text = _read(sd / cand)
                break
        scripts = sorted(
            set(re.findall(r"(?:scripts|deploy)/[A-Za-z0-9_\-./]+\.(?:py|sh)", svc_text))
        )
        jobs.append(
            {
                "kind": "systemd-timer",
                "name": stem,
                "file": _rel(root, p),
                "schedule": sched,
                "execScripts": scripts,
            }
        )
    wf = root / ".github" / "workflows"
    for p in _walk_files(wf, ("*.yml", "*.yaml")):
        text = _read(p)
        if not re.search(r"^\s*schedule:\s*$", text, re.M):
            continue
        crons = sorted(
            set(re.findall(r"^\s*-\s*cron:\s*[\"']?([^\"'\n#]+?)[\"']?\s*(?:#.*)?$", text, re.M))
        )
        jobs.append(
            {
                "kind": "github-workflow-schedule",
                "name": p.name,
                "file": _rel(root, p),
                "schedule": crons,
                "execScripts": sorted(
                    set(re.findall(r"scripts/[A-Za-z0-9_\-./]+\.(?:py|sh)", text))
                ),
            }
        )
    return sorted(jobs, key=lambda j: (j["kind"], j["name"]))


# --------------------------------------------------------------------------
# census assembly + ranking
# --------------------------------------------------------------------------


def _risk(item: dict) -> tuple[str, int, list[str]]:
    """(class letter, subscore, reasons) for a surface item."""
    s = item["surface"]
    reasons: list[str] = []
    score = 0
    if s in ("backendRoute", "bridgeRoute"):
        methods = [item["method"]] if s == "backendRoute" else item["methods"]
        path = item["path"] if s == "backendRoute" else item["url"]
        mut = any(m in MUTATING for m in methods)
        auth = item.get("auth", "")
        is_a = mut or auth in ("admin", "self-authed", "test-only") or "/auth" in path
        val = has_value_keyword(path)
        if mut:
            score += 4
            reasons.append("mutating")
        if auth in ("admin", "self-authed", "test-only"):
            score += 2
            reasons.append(auth)
        if "/auth" in path:
            score += 1
            reasons.append("auth path")
        if val:
            score += 1
            reasons.append("value-producing path")
        if item.get("flagGate"):
            reasons.append("flag-gated")
        if is_a:
            return "a", score, reasons
        if val:
            return "b", score, reasons
        return "e", score, reasons
    if s == "page":
        if has_value_keyword(item["url"]):
            return "b", 1, ["value-producing page"]
        return "e", 0, []
    if s == "flag":
        if item["default"]:
            return (
                "c",
                1 + (1 if item["gateStatus"] == "LIVE" else 0),
                ["default ON", item["gateStatus"]],
            )
        return "e", 0, []
    if s == "job":
        return "d", 1, [item["kind"]]
    return "e", 0, []


def build_census(root: Path = REPO_ROOT, *, use_reachability: bool = False) -> dict:
    root = Path(root)
    corpus = load_test_corpus(root)
    auth = _server_auth_sets(root)
    flags = scan_flags(root)
    flag_names = [f["name"] for f in flags]
    transitive = _transitive_flags(root, flag_names) if use_reachability else {}

    items: list[dict] = []

    for r in scan_backend(root):
        handlers = sorted(r["handlers"])
        refs, best = match_url(corpus, r["path"], handler=handlers[0] if handlers else None)
        trans = sorted(transitive.get(r["rawPath"], set()) - r["gates"])
        item = {
            "surface": "backendRoute",
            "id": f"{r['method']} {r['path']}",
            "method": r["method"],
            "path": r["path"],
            "module": r["module"],
            "handlers": handlers,
            "auth": classify_auth(r["path"], r["admin"], auth),
            "flagGate": {"direct": sorted(r["gates"]), "transitiveNameBased": trans}
            if (r["gates"] or trans)
            else None,
            "testRefs": refs,
            "bestMatchKind": best,
        }
        items.append(item)

    for pg in scan_pages(root):
        refs, best = match_url(corpus, pg["url"], import_stem=pg["importStem"])
        items.append(
            {
                "surface": "page",
                "id": f"PAGE {pg['url']}",
                "url": pg["url"],
                "file": pg["file"],
                "access": pg["access"],
                "testRefs": refs,
                "bestMatchKind": best,
            }
        )

    for br in scan_bridges(root):
        refs, best = match_url(corpus, br["url"], import_stem=br["importStem"])
        items.append(
            {
                "surface": "bridgeRoute",
                "id": f"BRIDGE {'|'.join(br['methods'])} {br['url']}",
                "url": br["url"],
                "file": br["file"],
                "methods": br["methods"],
                "auth": "bridge (enforced by backend)",
                "testRefs": refs,
                "bestMatchKind": best,
            }
        )

    for fl in flags:
        refs, best = match_flag(corpus, fl["name"])
        items.append(
            {
                "surface": "flag",
                "id": f"FLAG {fl['name']}",
                "name": fl["name"],
                "default": fl["default"],
                "gateStatus": fl["gateStatus"],
                "ownerHeld": fl["ownerHeld"],
                "testRefs": refs,
                "bestMatchKind": best,
            }
        )

    for jb in scan_jobs(root):
        needles = {}
        if jb["kind"] == "systemd-timer":
            needles["unit-name"] = jb["name"]
        else:
            needles["workflow-file"] = jb["name"]
        refs, best = match_words(corpus, needles)
        script_refs: dict[str, set[str]] = {r["file"]: set(r["kinds"]) for r in refs}
        for sc in jb["execScripts"]:
            stem = sc.rsplit(".", 1)[0].replace("/", ".")
            for tf in corpus:
                if sc in tf.text or stem in tf.text:
                    script_refs.setdefault(tf.rel, set()).add("exec-script")
        refs, best = _collect(script_refs)
        items.append(
            {
                "surface": "job",
                "id": f"JOB {jb['kind']} {jb['name']}",
                "kind": jb["kind"],
                "name": jb["name"],
                "file": jb["file"],
                "schedule": jb["schedule"],
                "execScripts": jb["execScripts"],
                "testRefs": refs,
                "bestMatchKind": best,
            }
        )

    enumerating: dict[str, dict[str, int]] = {}
    for surf, thr in ENUMERATION_THRESHOLD.items():
        counts: dict[str, int] = {}
        for it in items:
            if it["surface"] == surf:
                for r in it["testRefs"]:
                    counts[r["file"]] = counts.get(r["file"], 0) + 1
        big = {f: c for f, c in sorted(counts.items()) if c >= thr}
        if big:
            enumerating[surf] = big
        for it in items:
            if it["surface"] == surf:
                for r in it["testRefs"]:
                    if r["file"] in big:
                        r["kinds"] = ["enumerating-file"]
                it["bestMatchKind"] = _best_kind(it["testRefs"])

    for it in items:
        cls, score, reasons = _risk(it)
        it["riskClass"] = cls
        it["riskScore"] = score
        it["riskReasons"] = reasons
        it["testRefCount"] = len(it["testRefs"])
        it["evidence"] = (
            "none"
            if not it["testRefs"]
            else (
                "strong"
                if any(set(r["kinds"]) - WEAK_KINDS for r in it["testRefs"])
                else "weak-only"
            )
        )
        it["testFrameworks"] = sorted({_framework(r["file"]) for r in it["testRefs"]})

    surfaces = ["backendRoute", "page", "bridgeRoute", "flag", "job"]
    totals = {}
    for s in surfaces:
        sub = [i for i in items if i["surface"] == s]
        totals[s] = {
            "total": len(sub),
            "withTestRef": sum(1 for i in sub if i["testRefCount"]),
            "noTestRefFound": sum(1 for i in sub if not i["testRefCount"]),
            "weakMatchOnly": sum(1 for i in sub if i["evidence"] == "weak-only"),
        }
    by_class = {}
    for c in sorted(_CLASS_RANK):
        sub = [i for i in items if i["riskClass"] == c]
        by_class[c] = {
            "label": CLASS_LABELS[c],
            "total": len(sub),
            "noTestRefFound": sum(1 for i in sub if not i["testRefCount"]),
            "weakMatchOnly": sum(1 for i in sub if i["evidence"] == "weak-only"),
        }
    gaps = ranked_gaps(items)
    return {
        "schema": SCHEMA,
        "asOfCommit": git_head(root),
        "testFileCount": len(corpus),
        "enumeratingTestFiles": enumerating,
        "totals": totals,
        "byClass": by_class,
        "rankedGapIds": [g["id"] for g in gaps],
        "items": sorted(items, key=lambda i: (surfaces.index(i["surface"]), i["id"])),
    }


def ranked_gaps(items: list[dict]) -> list[dict]:
    gaps = [i for i in items if i["evidence"] in ("none", "weak-only")]
    ev = {"none": 0, "weak-only": 1}
    order = {"backendRoute": 0, "bridgeRoute": 1, "page": 2, "flag": 3, "job": 4}
    return sorted(
        gaps,
        key=lambda i: (
            ev[i["evidence"]],
            _CLASS_RANK[i["riskClass"]],
            -i["riskScore"],
            order[i["surface"]],
            i["id"],
        ),
    )


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------

_MD_COMMIT_PREFIX = "As of commit: "


def render_md(census: dict, top_n: int = 60) -> str:
    items = census["items"]
    gaps = ranked_gaps(items)
    L: list[str] = []
    L.append("# Feature census (generated)")
    L.append("")
    L.append(f"{_MD_COMMIT_PREFIX}`{census['asOfCommit']}`")
    L.append("")
    L.append(
        "Generated by `python scripts/feature_census.py` (offline, static). Full data: "
        "`feature_census.json`. This is evidence tooling for the continuous-verification "
        "standard; it is not a roadmap, not an inventory owner, and creates no work items."
    )
    L.append("")
    L.append("## How to read this")
    L.append("")
    L.append(
        '- **"no test reference found" is NOT "untested".** It means no test file matched the '
        "recorded string rules. A test may reach the item through a helper, a fixture, a client "
        "wrapper or a dynamic path."
    )
    L.append(
        "- **A reference is a string match, not an assertion.** Each match records how it matched "
        "(strongest first): `literal-path` / `literal-template`, `route-import` / `page-import`, "
        "`quoted-flag-name`, `env-var`, `unit-name`, `workflow-file`, `exec-script`, "
        "`template-pattern` (templated route matched with params as wildcards), "
        "`handler-name` (function name referenced; weak for generic names), `template-prefix` "
        "(static prefix of a templated route; weak), `bare-identifier` (flag name as a bare word; weak), "
        "`enumerating-file` (file that lists the whole registry; weak). "
        "Weak-only items appear in the ranked list after every zero-reference item."
    )
    L.append(
        "- Backend route matching is by path only, not by HTTP method: a test of `GET /x` also "
        "marks `POST /x` as referenced. Page `/` is matched only by import (a bare `/` is too ambiguous)."
    )
    L.append(
        '- Flag gating on routes: `direct` = `is_enabled("flag")` in the handler body; '
        "`transitiveNameBased` = `src.api.flag_reachability` name-based over-approximation, populated only with `--transitive-flags` (slow; not run by default or by `--check`)."
    )
    L.append(
        f"- Risk classes: a = {CLASS_LABELS['a']}; b = {CLASS_LABELS['b']} "
        f"(trade/draft/faab/waiver/bdvm/valuation/ros/rankings and similar path segments); "
        f"c = {CLASS_LABELS['c']}; d = {CLASS_LABELS['d']}; e = {CLASS_LABELS['e']}. "
        "An item is in its lowest-lettered applicable class."
    )
    L.append("")
    L.append(f"Test files scanned: {census['testFileCount']}.")
    L.append("")
    L.append("## Totals per surface")
    L.append("")
    L.append(
        "| surface | total | with test reference | no test reference found "
        "| weak match only (subset of with-reference) |"
    )
    L.append("|---|---:|---:|---:|---:|")
    for s, t in census["totals"].items():
        L.append(
            f"| {s} | {t['total']} | {t['withTestRef']} | {t['noTestRefFound']} "
            f"| {t['weakMatchOnly']} |"
        )
    L.append("")
    L.append("## Totals per risk class")
    L.append("")
    L.append("| class | meaning | total | no test reference found | weak match only |")
    L.append("|---|---|---:|---:|---:|")
    for c, t in census["byClass"].items():
        L.append(
            f"| {c} | {t['label']} | {t['total']} | {t['noTestRefFound']} | {t['weakMatchOnly']} |"
        )
    L.append("")
    L.append("### No-reference items by class and surface")
    L.append("")
    L.append("| class | " + " | ".join(census["totals"]) + " |")
    L.append("|---|" + "---:|" * len(census["totals"]))
    for c in census["byClass"]:
        row = []
        for s in census["totals"]:
            row.append(
                str(
                    sum(
                        1
                        for i in items
                        if i["riskClass"] == c and i["surface"] == s and not i["testRefCount"]
                    )
                )
            )
        L.append(f"| {c} | " + " | ".join(row) + " |")
    L.append("")
    L.append(
        f"## Top {min(top_n, len(gaps))} highest-risk gaps (no reference first, then weak-only)"
    )
    L.append("")
    L.append(
        "Ranked: evidence (none, then weak-only), class (a, b, c, d, e), risk score, surface, id."
    )
    L.append("")
    L.append("| # | evidence | class | item | why |")
    L.append("|---:|---|---|---|---|")
    for n, g in enumerate(gaps[:top_n], 1):
        extra = ""
        if g["surface"] == "backendRoute":
            extra = g["module"] if g["auth"] in g["riskReasons"] else f"{g['auth']}; {g['module']}"
        elif g["surface"] == "page":
            extra = g["access"]
        elif g["surface"] == "flag":
            extra = "" if g["default"] else f"default OFF, gate {g['gateStatus']}"
        elif g["surface"] == "job":
            extra = ", ".join(g["schedule"][:1])
        why = ", ".join(g["riskReasons"] + ([extra] if extra else []))
        L.append(f"| {n} | {g['evidence']} | {g['riskClass']} | `{g['id']}` | {why} |")
    L.append("")
    rest = gaps[top_n:]
    L.append(f"## Remaining gaps ({len(rest)}) summarised by class")
    L.append("")
    for evk in ("none", "weak-only"):
        for c in sorted(_CLASS_RANK):
            sub = [g for g in rest if g["riskClass"] == c and g["evidence"] == evk]
            if not sub:
                continue
            per = {}
            for g in sub:
                per[g["surface"]] = per.get(g["surface"], 0) + 1
            L.append(
                f"- {evk}, class {c} ({CLASS_LABELS[c]}): {len(sub)} - "
                + ", ".join(f"{k} {v}" for k, v in sorted(per.items()))
            )
    L.append("")
    enum = census.get("enumeratingTestFiles", {})
    L.append("## Registry-enumerating test files (demoted to weak evidence)")
    L.append("")
    L.append(
        "A file matching many items of one surface lists the registry rather than testing each item; "
        "its matches are recorded as `enumerating-file` (weak). Thresholds: "
        + ", ".join(f"{k} >= {v}" for k, v in sorted(ENUMERATION_THRESHOLD.items()))
        + "."
    )
    L.append("")
    for surf in sorted(enum):
        for f, c in sorted(enum[surf].items()):
            L.append(f"- {surf}: `{f}` ({c} items)")
    if not enum:
        L.append("- none")
    L.append("")
    L.append("## Flags default-ON with no or weak-only test evidence")
    L.append("")
    fl = [
        i
        for i in items
        if i["surface"] == "flag" and i["default"] and i["evidence"] in ("none", "weak-only")
    ]
    for i in fl[:40]:
        held = " (owner-held)" if i["ownerHeld"] else ""
        L.append(f"- `{i['name']}` gate {i['gateStatus']}{held} ({i['evidence']})")
    if len(fl) > 40:
        L.append(f"- ... {len(fl) - 40} more in the JSON")
    if not fl:
        L.append("- none")
    L.append("")
    L.append("## Scheduled jobs with no test reference found")
    L.append("")
    jb = [i for i in items if i["surface"] == "job" and not i["testRefCount"]]
    for i in jb[:40]:
        L.append(
            f"- `{i['name']}` ({i['kind']}; {', '.join(i['schedule'][:1]) or 'no schedule parsed'})"
        )
    if len(jb) > 40:
        L.append(f"- ... {len(jb) - 40} more in the JSON")
    if not jb:
        L.append("- none")
    L.append("")
    L.append("## Match-strength profile (items WITH a reference)")
    L.append("")
    L.append("| surface | strongest match kind | items |")
    L.append("|---|---|---:|")
    prof: dict[tuple[str, str], int] = {}
    for i in items:
        if i["testRefCount"]:
            prof[(i["surface"], i["bestMatchKind"] or "?")] = (
                prof.get((i["surface"], i["bestMatchKind"] or "?"), 0) + 1
            )
    for (s, k), n in sorted(prof.items()):
        L.append(f"| {s} | {k} | {n} |")
    L.append("")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _strip_commit_json(census: dict) -> dict:
    return {k: v for k, v in census.items() if k != "asOfCommit"}


def _strip_commit_md(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith(_MD_COMMIT_PREFIX))


def render_json(census: dict) -> str:
    return json.dumps(census, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--root", default=str(REPO_ROOT), help="repository root (tests use fixtures)")
    ap.add_argument("--check", action="store_true", help="exit 1 if committed output is stale")
    ap.add_argument(
        "--transitive-flags",
        action="store_true",
        help="also run src.api.flag_reachability for transitive flag gating (adds ~1 minute)",
    )
    args = ap.parse_args(argv)
    root = Path(args.root)
    out = Path(args.out_dir)
    if not out.is_absolute():
        out = root / out
    census = build_census(root, use_reachability=args.transitive_flags)
    js, md = render_json(census), render_md(census)
    jpath, mpath = out / "feature_census.json", out / "FEATURE_CENSUS.md"
    if args.check:
        try:
            old_j = json.loads(jpath.read_text(encoding="utf-8"))
            old_m = mpath.read_text(encoding="utf-8")
        except (OSError, ValueError):
            print("feature census: committed output missing or unreadable", file=sys.stderr)
            return 1
        if _strip_commit_json(old_j) != _strip_commit_json(census) or _strip_commit_md(
            old_m
        ) != _strip_commit_md(md):
            print("feature census: STALE - rerun scripts/feature_census.py", file=sys.stderr)
            return 1
        print("feature census: up to date")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    jpath.write_text(js, encoding="utf-8")
    mpath.write_text(md, encoding="utf-8")
    t = census["totals"]
    print(
        "feature census: "
        + ", ".join(f"{s}={v['total']} (no-ref {v['noTestRefFound']})" for s, v in t.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
