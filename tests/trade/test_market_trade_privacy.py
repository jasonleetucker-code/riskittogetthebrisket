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
)

VALUATION_PATH = (
    "src/api/data_contract.py",
    "src/api/pick_value_resolution.py",
    "src/canonical/player_valuation.py",
    "src/canonical/calibration.py",
    "src/api/confidence.py",
    "Dynasty Scraper.py",
)


def test_store_paths_are_gitignored():
    for rel in (
        "data/market_trades/archive.sqlite",
        "data/market_trades/underlying_trades.sqlite",
        "data/market_trades/ktc_fetch_state.json",
        "data/market_trades/reports/latest.json",
        "data/market_trades/quarantine/ktc/x.html.gz",
    ):
        res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO, capture_output=True)
        assert res.returncode == 0, f"{rel} is not gitignored — a public repo would publish it"


def test_nothing_tracks_or_force_adds_the_store():
    tracked = subprocess.run(
        ["git", "ls-files", "data/market_trades"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    assert tracked == "", f"tracked trade-ledger files: {tracked}"
    offenders = []
    for path in list((REPO / ".github" / "workflows").glob("*.y*ml")) + list(
        (REPO / "deploy").rglob("*.sh")
    ):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "market_trades" in text and "git add" in text:
            offenders.append(str(path.relative_to(REPO)))
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
