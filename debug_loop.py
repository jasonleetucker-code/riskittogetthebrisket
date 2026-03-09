"""
Continuous smoke-debug loop for the Dynasty Trade Calculator.

Usage examples:
  python debug_loop.py
  python debug_loop.py --iterations 10 --sleep-sec 20
  python debug_loop.py --run-scraper --iterations 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright


BENIGN_CONSOLE_ERRORS = (
    "Fetch API cannot load file:///",
    "Failed to load resource: net::ERR_FILE_NOT_FOUND",
)

# Coverage diagnostics: treat "not_in_source" as expected noise, fail on
# scraper/matching regressions or near-total coverage collapse.
COVERAGE_BENIGN_MISSING_REASONS = {"not_in_source"}
COVERAGE_MAX_DEFICIT_RATIO = {"offense": 0.85, "idp": 0.90}
COVERAGE_MIN_PASS_FLOOR = {"offense": 120, "idp": 50}
COVERAGE_SEVERE_REASON_RATIO_MAX = 0.08


def latest_data_file(root: Path) -> Path:
    candidates = sorted(root.glob("dynasty_data_*.json"), reverse=True)
    data_dir = root / "data"
    candidates += sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not candidates:
        raise FileNotFoundError("No dynasty_data_*.json found in root or data/ directory.")
    return candidates[0]


def run_scraper_once(root: Path) -> None:
    cmd = [sys.executable, str(root / "Dynasty Scraper.py")]
    subprocess.run(cmd, cwd=str(root), check=True)


async def run_ui_smoke(root: Path, data_path: Path) -> dict[str, Any]:
    html_path = root / "Static" / "index.html"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    checks: dict[str, Any] = {}
    failures: list[str] = []
    errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        def on_console(msg):
            if msg.type != "error":
                return
            txt = msg.text or ""
            if any(x in txt for x in BENIGN_CONSOLE_ERRORS):
                return
            errors.append(f"console.error: {txt}")

        page.on("console", on_console)

        await page.goto(html_path.as_uri())
        ok = await page.evaluate("(d) => loadJsonData(d)", data)
        if not ok:
            failures.append("loadJsonData returned false")

        await page.evaluate("computeSiteStats();")

        checks = await page.evaluate(
            """
            () => {
              const out = {};
              out.playerCount = Object.keys(loadedData?.players || {}).length;

              // Source coverage checks
              let dsCount = 0;
              for (const v of Object.values(loadedData?.players || {})) {
                if (typeof v?.draftSharks === 'number' && isFinite(v.draftSharks)) dsCount++;
              }
              out.draftSharksCount = dsCount;
              out.sleeperIdCount = 0;
              out.offCompositeCount = 0;
              out.idpCompositeCount = 0;
              out.topComposite = 0;
              const offPos = new Set(['QB', 'RB', 'WR', 'TE', 'K']);
              const idpPos = new Set(['LB', 'DL', 'DE', 'DT', 'CB', 'S', 'DB', 'EDGE']);
              for (const [name, v] of Object.entries(loadedData?.players || {})) {
                const sid = v?._sleeperId;
                if ((typeof sid === 'string' || typeof sid === 'number') && String(sid).trim()) {
                  out.sleeperIdCount++;
                }
                const comp = Number(v?._composite);
                if (!isFinite(comp) || comp <= 0) continue;
                if (parsePickToken(name)) continue;
                if (comp > out.topComposite) out.topComposite = comp;
                const pos = (getPlayerPosition(name) || '').toUpperCase();
                if (offPos.has(pos)) out.offCompositeCount++;
                else if (idpPos.has(pos)) out.idpCompositeCount++;
              }
              out.joshSleeperId = getSleeperIdForName('Josh Allen') || '';
              out.ddBijan = loadedData?.players?.['Bijan Robinson']?.dynastyDaddy || null;
              out.ddChase = loadedData?.players?.["Ja'Marr Chase"]?.dynastyDaddy || null;

              // Pick valuation checks
              const picks = ['2026 Pick 1.03', '2026 Early 1st', '2027 Mid 2nd', '2028 Late 4th'];
              out.pickValues = {};
              for (const p of picks) out.pickValues[p] = getTradeItemValue(p)?.metaValue || 0;

              // Rankings "my roster only" check
              const teams = (typeof sleeperTeams !== 'undefined' && Array.isArray(sleeperTeams)) ? sleeperTeams : [];
              out.teamCount = teams.length;
              const teamName = teams[0]?.name || '';
              out.teamName = teamName;

              const sel = document.getElementById('rosterMyTeam');
              if (sel && teamName) sel.value = teamName;
              const cb = document.getElementById('rankingsMyRosterToggle');
              if (cb) cb.checked = true;
              buildFullRankings();
              const rows = Array.from(document.querySelectorAll('#rookieBody tr'))
                .filter(r => r.style.display !== 'none' && !r.classList.contains('tier-separator'));
              out.rosterRows = rows.length;
              const extractRowName = (row) => {
                const anchor = row.querySelector('td:nth-child(2) a');
                if (anchor && (anchor.textContent || '').trim()) return (anchor.textContent || '').trim();
                return (row.children[1]?.innerText || '').trim();
              };
              const shown = rows.map(extractRowName).filter(Boolean);
              const rosterSet = new Set((teams[0]?.players || []).map(n => n.toLowerCase()));
              out.offRosterShown = shown.filter(n => !rosterSet.has(n.toLowerCase())).slice(0, 10);

              // KTC baseline population check on full rankings view.
              const rosterCb = document.getElementById('rankingsMyRosterToggle');
              if (rosterCb) rosterCb.checked = false;
              const rookieCb = document.getElementById('rankingsRookieToggle');
              if (rookieCb) rookieCb.checked = false;
              const searchInp = document.getElementById('rankingsSearch');
              if (searchInp) searchInp.value = '';
              if (typeof currentRankingsFilter !== 'undefined') currentRankingsFilter = 'ALL';
              buildFullRankings();
              const allRows = Array.from(document.querySelectorAll('#rookieBody tr'))
                .filter(r => r.style.display !== 'none' && !r.classList.contains('tier-separator'));
              const allShown = new Set(allRows.map(extractRowName).filter(Boolean));
              const topKtc = Object.entries(loadedData?.players || {})
                .filter(([name, p]) => {
                  const kv = Number(p?.ktc);
                  if (!isFinite(kv) || kv <= 0) return false;
                  return !parsePickToken(name);
                })
                .sort((a, b) => Number(b[1].ktc) - Number(a[1].ktc))
                .slice(0, 400)
                .map(([name]) => name);
              out.ktcBaselineTarget = topKtc.length;
              out.ktcBaselineShown = topKtc.filter(n => allShown.has(n)).length;

              // Trade suggestion should include player suggestions (not only picks)
              const teamA = teams[0]?.name || '';
              const teamB = teams[1]?.name || '';
              const selA = document.getElementById('teamFilterA');
              const selB = document.getElementById('teamFilterB');
              if (selA) selA.value = teamA;
              if (selB) selB.value = teamB;
              updateTeamFilter();

              const aRow = document.querySelector('#sideABody tr');
              const bRow = document.querySelector('#sideBBody tr');
              if (aRow) {
                const inp = aRow.querySelector('.player-name-input');
                if (inp) inp.value = 'Josh Allen';
                autoFillRow(aRow);
              }
              if (bRow) {
                const inp = bRow.querySelector('.player-name-input');
                if (inp) inp.value = 'Jalen Tolbert';
                autoFillRow(bRow);
              }
              recalculate();

              const sugg = document.getElementById('tradeSuggestion');
              const btns = sugg ? Array.from(sugg.querySelectorAll('button')) : [];
              out.suggestionButtonCount = btns.length;
              out.nonPickSuggestionCount = btns.filter(b => !/\\bPICK\\b/i.test(b.innerText || '')).length;
              out.suggestionPreview = (sugg?.innerText || '').slice(0, 200);

              // Row clear behavior: deleting player name should clear all values/meta in that row
              const clearRow = document.querySelector('#sideABody tr');
              let clearOk = false;
              if (clearRow) {
                const nameInp = clearRow.querySelector('.player-name-input');
                if (nameInp) {
                  nameInp.value = 'Josh Allen';
                  autoFillRow(clearRow);
                  recalculate();
                  nameInp.value = '';
                  nameInp.dispatchEvent(new Event('input', { bubbles: true }));
                  const siteVals = Array.from(clearRow.querySelectorAll('.site-input')).map(i => (i.value || '').trim());
                  const mv = (clearRow.querySelector('.meta-value')?.innerText || '').trim();
                  clearOk = siteVals.every(v => v === '') && mv === '';
                }
              }
              out.clearRowOk = clearOk;

              // KTC URL import sanity
              out.ktcImportWorked = null;
              out.ktcImportA = '';
              out.ktcImportB = '';
              const ktcIds = Object.keys(ktcIdToPlayer || {});
              if (ktcIds.length >= 2) {
                const i0 = encodeURIComponent(ktcIds[0]);
                const i1 = encodeURIComponent(ktcIds[1]);
                const sampleUrl = `https://keeptradecut.com/dynasty/trade-calculator?teamOne=%5B%22${i0}%22%5D&teamTwo=%5B%22${i1}%22%5D`;
                const importInp = document.getElementById('ktcImportUrl');
                if (importInp) importInp.value = sampleUrl;
                importKtcTradeUrl();
                out.ktcImportA = (document.querySelector('#sideABody tr .player-name-input')?.value || '').trim();
                out.ktcImportB = (document.querySelector('#sideBBody tr .player-name-input')?.value || '').trim();
                out.ktcImportWorked = !!out.ktcImportA && !!out.ktcImportB;
              }

              // IDP sanity guardrail: top IDP should not exceed anchor range by large margin
              out.idpMeta = computeMetaValueForPlayer('Will Anderson')?.metaValue || 0;
              // Power rankings numeric sort sanity (QB column should sort true numeric asc/desc)
              out.powerSortOk = null;
              out.powerQbDescSample = [];
              out.powerQbAscSample = [];
              try {
                if (typeof switchLeagueSub === 'function') switchLeagueSub('heatmap');
                if (typeof buildPowerRankingsHeatmap === 'function') buildPowerRankingsHeatmap();
                const table = document.querySelector('#powerRankingsHeatmap table');
                if (table) {
                  const headers = Array.from(table.querySelectorAll('thead th'));
                  const qbIdx = headers.findIndex(h => ((h.textContent || '').trim().toUpperCase() === 'QB'));
                  if (qbIdx >= 0) {
                    const th = headers[qbIdx];
                    if (typeof sortTableByHeader === 'function') {
                      sortTableByHeader(th); // desc for numeric on first click
                      const valsDesc = Array.from(table.querySelectorAll('tbody tr'))
                        .map(r => parseInt(((r.children[qbIdx]?.innerText || '').trim()), 10))
                        .filter(v => Number.isFinite(v));
                      const okDesc = valsDesc.every((v, i) => i === 0 || valsDesc[i - 1] >= v);
                      sortTableByHeader(th); // asc on second click
                      const valsAsc = Array.from(table.querySelectorAll('tbody tr'))
                        .map(r => parseInt(((r.children[qbIdx]?.innerText || '').trim()), 10))
                        .filter(v => Number.isFinite(v));
                      const okAsc = valsAsc.every((v, i) => i === 0 || valsAsc[i - 1] <= v);
                      out.powerQbDescSample = valsDesc.slice(0, 12);
                      out.powerQbAscSample = valsAsc.slice(0, 12);
                      out.powerSortOk = !!okDesc && !!okAsc;
                    }
                  }
                }
              } catch (e) {
                out.powerSortOk = false;
              }
              out.coverageAudit = loadedData?.coverageAudit || null;
              return out;
            }
            """
        )

        await browser.close()

    coverage_audit = data.get("coverageAudit") if isinstance(data, dict) else None
    checks["coverageAuditPresent"] = isinstance(coverage_audit, dict)
    if isinstance(coverage_audit, dict):
        off_cov = coverage_audit.get("offense") if isinstance(coverage_audit.get("offense"), dict) else {}
        idp_cov = coverage_audit.get("idp") if isinstance(coverage_audit.get("idp"), dict) else {}
        off_reasons = off_cov.get("missingReasons") if isinstance(off_cov.get("missingReasons"), dict) else {}
        idp_reasons = idp_cov.get("missingReasons") if isinstance(idp_cov.get("missingReasons"), dict) else {}
        checks["offCoverageEvaluated"] = int(off_cov.get("evaluated", 0) or 0)
        checks["offCoverageDeficits"] = int(off_cov.get("deficitPlayers", 0) or 0)
        checks["offCoverageRequired"] = int(off_cov.get("requiredSources", 0) or 0)
        checks["offCoverageMissingReasons"] = off_reasons
        checks["offCoverageSevereReasons"] = {
            str(k): int(v)
            for k, v in off_reasons.items()
            if str(k) not in COVERAGE_BENIGN_MISSING_REASONS and int(v or 0) > 0
        }
        checks["offCoverageSevereMissing"] = int(sum(checks["offCoverageSevereReasons"].values()))
        checks["idpCoverageEvaluated"] = int(idp_cov.get("evaluated", 0) or 0)
        checks["idpCoverageDeficits"] = int(idp_cov.get("deficitPlayers", 0) or 0)
        checks["idpCoverageRequired"] = int(idp_cov.get("requiredSources", 0) or 0)
        checks["idpCoverageMissingReasons"] = idp_reasons
        checks["idpCoverageSevereReasons"] = {
            str(k): int(v)
            for k, v in idp_reasons.items()
            if str(k) not in COVERAGE_BENIGN_MISSING_REASONS and int(v or 0) > 0
        }
        checks["idpCoverageSevereMissing"] = int(sum(checks["idpCoverageSevereReasons"].values()))
        checks["offCoverageSample"] = (off_cov.get("deficitSample") or [])[:3]
        checks["idpCoverageSample"] = (idp_cov.get("deficitSample") or [])[:3]
    else:
        checks["offCoverageEvaluated"] = 0
        checks["offCoverageDeficits"] = 0
        checks["offCoverageRequired"] = 0
        checks["offCoverageMissingReasons"] = {}
        checks["offCoverageSevereReasons"] = {}
        checks["offCoverageSevereMissing"] = 0
        checks["idpCoverageEvaluated"] = 0
        checks["idpCoverageDeficits"] = 0
        checks["idpCoverageRequired"] = 0
        checks["idpCoverageMissingReasons"] = {}
        checks["idpCoverageSevereReasons"] = {}
        checks["idpCoverageSevereMissing"] = 0
        checks["offCoverageSample"] = []
        checks["idpCoverageSample"] = []

    # Assertions
    if checks.get("playerCount", 0) < 500:
        failures.append(f"playerCount too low: {checks.get('playerCount')}")
    if checks.get("draftSharksCount", 0) < 450:
        failures.append(f"draftSharksCount too low: {checks.get('draftSharksCount')}")
    if checks.get("sleeperIdCount", 0) < 700:
        failures.append(f"sleeperIdCount too low: {checks.get('sleeperIdCount')}")
    if checks.get("offCompositeCount", 0) < 350:
        failures.append(f"offCompositeCount too low: {checks.get('offCompositeCount')}")
    if checks.get("idpCompositeCount", 0) < 275:
        failures.append(f"idpCompositeCount too low: {checks.get('idpCompositeCount')}")
    if checks.get("topComposite", 0) < 9000:
        failures.append(f"topComposite unexpectedly low: {checks.get('topComposite')}")
    if not checks.get("joshSleeperId"):
        failures.append("missing Sleeper ID mapping for Josh Allen")
    dd_bijan = checks.get("ddBijan")
    dd_chase = checks.get("ddChase")
    if isinstance(dd_bijan, (int, float)) and isinstance(dd_chase, (int, float)) and dd_bijan == dd_chase:
        if dd_bijan >= 10000:
            checks["dynastyDaddyTopTieWarning"] = f"top-end tie at ceiling-like value {dd_bijan}"
        else:
            failures.append(f"DynastyDaddy tie detected for Bijan/Chase: {dd_bijan}")
    if checks.get("teamCount", 0) < 10:
        failures.append(f"teamCount too low: {checks.get('teamCount')}")
    if checks.get("rosterRows", 0) == 0:
        failures.append("rankings my-roster-only produced 0 rows")
    if checks.get("offRosterShown"):
        failures.append(f"my-roster-only showed off-roster names: {checks['offRosterShown'][:3]}")
    if checks.get("ktcBaselineTarget", 0) > 0 and checks.get("ktcBaselineShown", 0) < checks.get("ktcBaselineTarget", 0):
        failures.append(
            f"rankings missing KTC baseline players: shown={checks.get('ktcBaselineShown')} "
            f"target={checks.get('ktcBaselineTarget')}"
        )

    pick_values = checks.get("pickValues", {})
    for k, v in pick_values.items():
        if not isinstance(v, (int, float)) or v < 250:
            failures.append(f"pick value too low/invalid for {k}: {v}")

    if checks.get("suggestionButtonCount", 0) == 0:
        failures.append("trade suggestion returned no buttons")
    if checks.get("nonPickSuggestionCount", 0) == 0:
        failures.append("trade suggestion returned only pick buttons")
    if checks.get("ktcImportWorked") is False:
        failures.append(
            f"KTC URL import failed (A='{checks.get('ktcImportA')}', B='{checks.get('ktcImportB')}')"
        )
    if not checks.get("clearRowOk", False):
        failures.append("row clear behavior failed: deleting name did not clear row values/meta")
    if checks.get("idpMeta", 0) > 6500:
        failures.append(f"IDP sanity failed: Will Anderson composite too high ({checks.get('idpMeta')})")
    if checks.get("powerSortOk") is False:
        failures.append(
            "power rankings sort failed numeric monotonicity "
            f"(desc={checks.get('powerQbDescSample')}, asc={checks.get('powerQbAscSample')})"
        )
    if not checks.get("coverageAuditPresent", False):
        failures.append("coverageAudit missing from dynasty_data JSON")
    for prefix, label in (("off", "offense"), ("idp", "idp")):
        evaluated = int(checks.get(f"{prefix}CoverageEvaluated", 0) or 0)
        deficits = int(checks.get(f"{prefix}CoverageDeficits", 0) or 0)
        severe_missing = int(checks.get(f"{prefix}CoverageSevereMissing", 0) or 0)
        severe_reasons = checks.get(f"{prefix}CoverageSevereReasons", {}) or {}
        if evaluated <= 0:
            continue
        deficit_ratio = deficits / evaluated
        pass_count = evaluated - deficits
        severe_ratio = severe_missing / evaluated
        max_deficit_ratio = COVERAGE_MAX_DEFICIT_RATIO["offense" if prefix == "off" else "idp"]
        min_pass_floor = COVERAGE_MIN_PASS_FLOOR["offense" if prefix == "off" else "idp"]
        if deficit_ratio > max_deficit_ratio and pass_count < min_pass_floor:
            failures.append(
                f"{label} coverage collapse: deficits={deficits}/{evaluated} "
                f"(ratio={deficit_ratio:.1%}, pass={pass_count}, floor={min_pass_floor})"
            )
        if severe_ratio > COVERAGE_SEVERE_REASON_RATIO_MAX:
            failures.append(
                f"{label} severe coverage regressions: severe_missing={severe_missing}/{evaluated} "
                f"(ratio={severe_ratio:.1%}, reasons={severe_reasons})"
            )

    return {"checks": checks, "failures": failures, "errors": errors}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=5)
    ap.add_argument("--required-passes", type=int, default=2)
    ap.add_argument("--sleep-sec", type=int, default=10)
    ap.add_argument("--run-scraper", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    consecutive_passes = 0
    last_report: dict[str, Any] | None = None

    for i in range(1, args.iterations + 1):
        print(f"\\n=== Debug Iteration {i}/{args.iterations} ===")
        try:
            if args.run_scraper:
                print("Running scraper...")
                run_scraper_once(root)

            data_path = latest_data_file(root)
            print(f"Using data file: {data_path.name}")

            report = await run_ui_smoke(root, data_path)
            last_report = report
            checks = report["checks"]
            failures = report["failures"]
            errors = report["errors"]

            print(f"Checks: playerCount={checks.get('playerCount')} draftSharksCount={checks.get('draftSharksCount')} "
                  f"sleeperIds={checks.get('sleeperIdCount')} off={checks.get('offCompositeCount')} "
                  f"idp={checks.get('idpCompositeCount')} top={checks.get('topComposite')} "
                  f"teams={checks.get('teamCount')} rosterRows={checks.get('rosterRows')} idpMeta={checks.get('idpMeta')} "
                  f"offCovDef={checks.get('offCoverageDeficits')}/{checks.get('offCoverageEvaluated')} "
                  f"idpCovDef={checks.get('idpCoverageDeficits')}/{checks.get('idpCoverageEvaluated')} "
                  f"offCovSevere={checks.get('offCoverageSevereMissing')} "
                  f"idpCovSevere={checks.get('idpCoverageSevereMissing')} "
                  f"ktcShown={checks.get('ktcBaselineShown')}/{checks.get('ktcBaselineTarget')} "
                  f"powerSortOk={checks.get('powerSortOk')}")
            print(f"Pick values: {checks.get('pickValues')}")
            print(f"Suggestions: buttons={checks.get('suggestionButtonCount')} nonPick={checks.get('nonPickSuggestionCount')} "
                  f"clearRowOk={checks.get('clearRowOk')} ktcImport={checks.get('ktcImportWorked')}")
            if checks.get("offCoverageSample"):
                print(f"Offense coverage sample: {checks.get('offCoverageSample')}")
            if checks.get("offCoverageSevereReasons"):
                print(f"Offense severe coverage reasons: {checks.get('offCoverageSevereReasons')}")
            if checks.get("idpCoverageSample"):
                print(f"IDP coverage sample: {checks.get('idpCoverageSample')}")
            if checks.get("idpCoverageSevereReasons"):
                print(f"IDP severe coverage reasons: {checks.get('idpCoverageSevereReasons')}")
            if checks.get("dynastyDaddyTopTieWarning"):
                print(f"Warning: {checks.get('dynastyDaddyTopTieWarning')}")

            if errors:
                print("Runtime errors:")
                for e in errors[:20]:
                    print(" -", e)
            if failures:
                print("Failures:")
                for f in failures:
                    print(" -", f)

            if not errors and not failures:
                consecutive_passes += 1
                print(f"Iteration PASS ({consecutive_passes} consecutive)")
            else:
                consecutive_passes = 0
                print("Iteration FAIL")

            if consecutive_passes >= args.required_passes:
                print("\\nDebug loop complete: required consecutive passes reached.")
                return 0

        except Exception as e:
            consecutive_passes = 0
            print(f"Iteration crashed: {type(e).__name__}: {e}")

        if i < args.iterations:
            time.sleep(args.sleep_sec)

    print("\\nDebug loop ended without reaching required consecutive passes.")
    if last_report:
        print("Last suggestion preview:", last_report.get("checks", {}).get("suggestionPreview", ""))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
