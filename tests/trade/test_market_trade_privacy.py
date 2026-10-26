"""The trade ledger stays on the box and never feeds a canonical value.

* Privacy: the repo is public.  Vendor trade rows and the host league ids in
  them live under ``data/market_trades/`` — gitignored — and no workflow or
  deploy/push script may force-add that path.
* Inertness: raw trades must not rewrite canonical values (spec §3/§18; Batch 3
  §N "never let completed trades rewrite values before dedupe and topology
  are validated").  So no module on the valuation path may import the ledger
  family, checked statically and at runtime.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

LEDGER_MODULES = (
    "src.sources.ktc_trades",
    "src.trade.market_trade_archive",
    "src.trade.market_trade_normalize",
    "src.trade.market_trade_groups",
    "src.trade.market_trade_format",
    "src.trade.market_trade_eval",
    "src.trade.market_trade_report",
    "src.trade.market_trade_reference",
)

VALUATION_PATH = (
    "src/api/data_contract.py",
    "src/api/pick_value_resolution.py",
    "src/canonical/player_valuation.py",
    "src/canonical/calibration.py",
    "src/api/confidence.py",
    "Dynasty Scraper.py",
)


STORE_PATHS = (
    "data/market_trades/archive.sqlite",
    "data/market_trades/underlying_trades.sqlite",
    "data/market_trades/.underlying_trades.sqlite.1234.tmp",
    "data/market_trades/ktc_fetch_state.json",
    "data/market_trades/reports/latest.json",
    "data/market_trades/reports/market_trade_ledger_2026-10-01.json",
    "data/market_trades/quarantine/ktc/x.html.gz",
)


def test_store_paths_are_gitignored_by_the_repos_own_gitignore():
    """``git check-ignore`` semantics, but the deciding rule must come from a
    TRACKED ``.gitignore`` in this repo — a developer's global excludes file or
    ``.git/info/exclude`` would make this pass locally while CI, the box and
    every other clone publish the store.  ``--no-index`` asks about the rules,
    not about what happens to be tracked today."""
    tracked_ignores = set(
        subprocess.run(
            ["git", "ls-files", "--", ".gitignore", "*/.gitignore"],
            cwd=REPO,
            capture_output=True,
            text=True,
        ).stdout.split()
    )
    assert ".gitignore" in tracked_ignores
    for rel in STORE_PATHS:
        res = subprocess.run(
            ["git", "check-ignore", "-v", "--no-index", rel],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"{rel} is not gitignored — a public repo would publish it"
        # Output: "<source>:<line>:<pattern>\t<path>"; a negated (!) pattern
        # would mean "explicitly NOT ignored" and never exits 0 here.
        source = res.stdout.split(":", 1)[0].replace("\\", "/")
        assert (
            source in tracked_ignores
        ), f"{rel} is ignored only by {source!r}, which is not a tracked repo .gitignore"


# ── Forced adds: parse the commands, do not grep for a string ─────────────

_SEPARATORS = {"&&", "||", ";", "|", "&"}


def _forced_add_pathspecs(text: str) -> list[list[str]]:
    """Every ``git add`` invocation in shell-ish ``text`` that FORCES past
    .gitignore, as its pathspec list (``[]`` = no pathspec = whole tree when
    combined with -A/--all).  Line continuations are joined; comments skipped."""
    import shlex

    joined = re.sub(r"\\\r?\n", " ", text)
    out: list[list[str]] = []
    for line in joined.splitlines():
        if "git" not in line or "add" not in line or line.lstrip().startswith("#"):
            continue
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except ValueError:
            tokens = line.split()
        for k in range(len(tokens) - 1):
            if tokens[k] != "git" or tokens[k + 1] != "add":
                continue
            args: list[str] = []
            for t in tokens[k + 2 :]:
                if t in _SEPARATORS:
                    break
                args.append(t)
            force = False
            specs: list[str] = []
            after_dashdash = False
            for a in args:
                if after_dashdash or not a.startswith("-"):
                    specs.append(a)
                elif a == "--":
                    after_dashdash = True
                elif a == "--force" or (not a.startswith("--") and "f" in a[1:]):
                    force = True
            if force:
                out.append(specs)
    return out


def _spec_could_cover_store(spec: str) -> bool:
    """Whether a forced pathspec could reach ``data/market_trades/``.  An opaque
    (variable) pathspec is answered by the caller."""
    s = spec.strip("\"'")
    s = s[2:] if s.startswith("./") else s
    if s.startswith(":/"):
        s = s[2:]
    if s in ("", ".", "*", "data", "data/"):
        return True
    for target in STORE_PATHS:
        base = s.rstrip("/")
        if target == s or target.startswith(base + "/"):
            return True
        if any(ch in s for ch in "*?[") and (
            fnmatch.fnmatch(target, s) or fnmatch.fnmatch(target, base + "/*")
        ):
            return True
    return False


def _publishers() -> list[Path]:
    roots = [REPO / ".github" / "workflows", REPO / "deploy", REPO / "scripts"]
    files: list[Path] = [p for p in REPO.glob("*.bat")] + [p for p in REPO.glob("*.sh")]
    for root in roots:
        for pattern in ("*.y*ml", "*.sh", "*.bat", "*.template"):
            files.extend(root.rglob(pattern))
    return sorted(set(files))


def _store_publishing_offenders(path: Path, text: str) -> list[str]:
    found = []
    for specs in _forced_add_pathspecs(text):
        if not specs:
            found.append(f"{path.name}: forced whole-tree add")
        for spec in specs:
            if "$" in spec or "`" in spec:
                # Opaque at rest: acceptable only if nothing in the file could
                # put the store into the variable.
                if "market_trades" in text:
                    found.append(f"{path.name}: forced add of {spec} beside a store reference")
            elif _spec_could_cover_store(spec):
                found.append(f"{path.name}: forced add of {spec}")
    return found


def test_forced_add_parser_positive_and_negative_controls():
    def offends(cmd: str, extra: str = "") -> bool:
        return bool(_store_publishing_offenders(Path("x.sh"), cmd + "\n" + extra))

    assert offends("git add -f data/")
    assert offends("git add --force data")
    assert offends("git add -Af .")
    assert offends("git add -A --force")
    assert offends("cd repo && git add -f -- data/*")
    assert offends("git add -f data/market_trades/archive.sqlite")
    assert offends('git add -f "data/market_trades/"')
    assert offends("git add -f \\\n  data/")
    assert offends('git add -f -- "$p"', "# loops over data/market_trades")
    assert not offends("git add -f data/scrape_state/")
    assert not offends("git add data/")  # not forced: .gitignore still applies
    assert not offends("# git add -f data/")
    assert not offends("git add -f -- data/ops/sharp-production-smoke.json")
    assert not offends('git add -f -- "${STAGED[@]}"')


def test_nothing_tracks_or_force_adds_the_store():
    tracked = subprocess.run(
        ["git", "ls-files", "data/market_trades"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    assert tracked == "", f"tracked trade-ledger files: {tracked}"
    files = _publishers()
    assert any(p.suffix in (".yml", ".yaml") for p in files), "non-vacuity: workflows scanned"
    offenders: list[str] = []
    forced_seen = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        forced_seen += len(_forced_add_pathspecs(text))
        offenders += _store_publishing_offenders(path, text)
    # Non-vacuity: the repo DOES force-add other data/ paths (scrape_state,
    # ops smoke, dated snapshots); the parser must be seeing them.
    assert forced_seen >= 3, forced_seen
    # Python publishers: a subprocess ``git add`` is opaque to the shell parser,
    # so any such script must not reference the store at all.
    for path in list((REPO / "scripts").rglob("*.py")) + list((REPO / "deploy").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"[\"']git[\"']\s*,\s*[\"']add[\"']", text) and "market_trades" in text:
            offenders.append(f"{path.name}: subprocess git add beside a store reference")
    assert not offenders, f"a workflow/script could publish the trade ledger: {offenders}"


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_valuation_path_never_imports_the_trade_ledger():
    offenders = [
        rel
        for rel in VALUATION_PATH
        if (REPO / rel).exists() and any(m.startswith(LEDGER_MODULES) for m in _imports(REPO / rel))
    ]
    assert not offenders, f"canonical valuation imports the trade ledger: {offenders}"


def test_building_a_contract_does_not_load_the_trade_ledger():
    probe = (
        "import sys; import src.api.data_contract;"
        f"mods={LEDGER_MODULES!r};"
        "leaked=[m for m in sys.modules if m.startswith(mods)];"
        "print('LEAKED' if leaked else 'CLEAN', leaked)"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO, capture_output=True, text=True, timeout=180
    )
    assert res.returncode == 0, res.stderr[-2000:]
    assert res.stdout.startswith("CLEAN"), res.stdout


def test_the_ledger_family_writes_no_canonical_value_field():
    for mod in LEDGER_MODULES:
        path = REPO / (mod.replace(".", "/") + ".py")
        text = path.read_text(encoding="utf-8")
        assert '["rankDerivedValue"] =' not in text and "'rankDerivedValue'] =" not in text, mod
