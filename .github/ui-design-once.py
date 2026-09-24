"""Temporary #1422 application helper; never retained in the final tree."""
from pathlib import Path
import json
import os
import subprocess
import textwrap
import urllib.request

ROOT = Path.cwd()
REPO = 'jasonleetucker-code/riskittogetthebrisket'
BRANCH = 'codex/psi-design-reference'
PARENT = '07a6d1e76e6a7126cf4a91084af6ce7fcd507805'
GALLERY = 'frontend/app/design/DesignGallery.jsx'
CSS = 'frontend/app/design/design.module.css'
PAGE = 'frontend/app/design/page.jsx'
UNIT = 'frontend/__tests__/components/ds/psi-gallery.test.jsx'
E2E = 'tests/e2e/specs/psi-gallery.spec.js'
PATHS = {GALLERY, CSS, PAGE, UNIT, E2E}


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def request(endpoint):
    req = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + endpoint,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def pages(endpoint):
    rows = []
    for page in range(1, 101):
        sep = '&' if '?' in endpoint else '?'
        batch = request(endpoint + sep + f'per_page=100&page={page}')
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError('Incomplete pagination; no UI writes permitted')


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def put(path, content):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content).strip() + '\n', encoding='utf-8')


def replace(path, old, new):
    text = read(path)
    if old not in text:
        raise RuntimeError(f'Inspected anchor changed in {path}: {old[:80]}')
    (ROOT / path).write_text(text.replace(old, new, 1), encoding='utf-8')


if os.environ.get('GITHUB_REF_NAME') != BRANCH or os.environ.get('GITHUB_REPOSITORY') != REPO:
    raise SystemExit('Wrong branch or repository')
for path, expected in {
    GALLERY: 'f5224f88e4482e23ab1d370411c242f340cf33f4',
    CSS: 'd7d6c8a42a833fc85d9ecf6fb4a7281957d2a997',
    PAGE: '5d053919cc29fd2c57be70ffa812d55fae76a409',
}.items():
    if git('hash-object', path) != expected:
        raise SystemExit(f'Inspected file changed: {path}')
for path in (UNIT, E2E):
    if (ROOT / path).exists():
        raise SystemExit(f'Test now exists; reconcile rather than overwrite: {path}')

# Live changed-file evidence, not the earlier audit's stale PR snapshot.
conflicts = []
active = []
for pr in pages('pulls?state=open'):
    if pr['head']['ref'] == BRANCH:
        continue
    files = {row['filename'] for row in pages(f"pulls/{pr['number']}/files")}
    overlap = sorted(PATHS & files)
    active.append({'number': pr['number'], 'head': pr['head']['sha'], 'overlap': overlap})
    if overlap:
        conflicts.append({'pr': pr['number'], 'files': overlap})
main = request('branches/main')['commit']['sha']
comparison = request(f'compare/a3c29639aeb61c2af4fd169b75ccb9429011109b...{main}')
if len(comparison.get('files', [])) >= 300:
    raise SystemExit('Main comparison reached API file limit; inspect complete diff before writing')
main_overlap = sorted(PATHS & {row['filename'] for row in comparison.get('files', [])})
evidence = Path('/tmp/psi-gallery-evidence')
evidence.mkdir(exist_ok=True)
(evidence / 'live-claim-audit.json').write_text(json.dumps({'main': main, 'active_prs': active, 'conflicts': conflicts, 'main_overlap': main_overlap}, indent=2), encoding='utf-8')
if conflicts or main_overlap:
    raise SystemExit(f'UI paths changed or claimed: {conflicts}; main: {main_overlap}')

# Activate the existing reservation before touching implementation files.
replace('docs/WORK_CLAIMS.md',
    'queued — not a running worker; recheck current PRs/claims before starting. No backend/shared-style/dependency paths reserved.',
    'open — #1422 bounded gallery implementation session on its own branch; live PR/main file overlap rechecked. No backend/shared-style/dependency edits.')
git('add', 'docs/WORK_CLAIMS.md')
git('commit', '-m', 'chore(ui): activate disjoint PSI gallery work claim #1422')

replace(GALLERY, '<div className={styles.page}>', '<div className={`psi-editorial ${styles.page}`} data-testid="psi-gallery">')
replace(GALLERY, '      <PageHeader\n', '      <PageHeader\n        className={styles.hero}\n')
replace(GALLERY,
    'description="Premium Sports Intelligence: near-black cool neutrals, ONE franchise-gold accent reserved for interactive and identity roles, market direction on a CVD-validated blue/orange pair, near-zero radii, data in a tabular mono face. Every ramp and component state on this page is the live system — if it renders here, it is what ships."',
    'description="Premium Sports Intelligence / Direction A. Warm editorial surfaces, strong ink, one burnt-red interactive accent, thin rules and tabular data. These are shared implementation references, not a separate product or a new design direction."')
replace(GALLERY, 'actions={<Badge tone="outline">docs/DESIGN-SYSTEM.md</Badge>}', 'actions={<Badge tone="outline">PSI / Direction A</Badge>}')
replace(GALLERY, '      {/* ── Color', '''      <Banner tone="info" title="Fixtures only">
        Values, source states and actions below are deterministic examples, not live
        league data. Example actions do not send, save or export anything.
      </Banner>

      {/* ── Color''')
for old, new in (
    ('primary · 15.7:1', 'primary ink'), ('secondary · 8.4:1', 'secondary ink'),
    ('tertiary · 5.9:1', 'tertiary ink'), ('accent (franchise gold)', 'accent (burnt red)'),
    ('muted wash', 'muted selected state'), ('Text (contrast on --surface-1)', 'Text roles'),
    ('Market / state semantics (terminal-restrained, never neon)', 'System states — distinct from market movement'),
    ('Chart series — CVD-validated fixed order, never cycled', 'Chart series — existing fixed order; verify each plot surface'),
    ('JetBrains Mono throughout, via next/font. Inter survives only inside .ds-prose — see the prose exception in tokens.css. Eight sizes, there is no ninth.', 'Existing --font-display for editorial hierarchy, --font-ui for controls and --font-data for comparable numbers. Use the approved eight-size scale; no new font assets.'),
    ('4px grid · four radii · three shadows. Motion: 120/180/280ms, zeroed under prefers-reduced-motion.', 'Token spacing; 2px controls and tiles, 3px panels, circles only for round indicators. Shadow examples are for overlays, not normal panels. Motion respects reduced-motion preferences.'),
    ('Px-sized to content — zero layout shift.', 'Stable placeholder dimensions; preserve useful content while refreshing.'),
    ('Sample value board: rank, player, position, value, 7-day movement and trend', 'Fixture value board: rank, player, position, value, 7-day movement and trend'),
):
    replace(GALLERY, old, new)
replace(GALLERY, '          {TYPE_SCALE.map', '''          <div className={styles.typeRow}>
            <span className={styles.typeTag}>--font-display</span>
            <span className={styles.displaySample}>Personnel &amp; market intelligence</span>
          </div>
          {TYPE_SCALE.map''')
replace(GALLERY, 'className={styles.radiusChip} style={{ borderRadius:', 'className={`${styles.radiusChip} ${r === "full" ? styles.roundIndicator : ""}`} style={{ borderRadius:')
replace(GALLERY, '        title="DataTable"', '        title="DataTable"\n        className={styles.tablePanel}')
replace(GALLERY, '            <Banner tone="positive">Board exported.</Banner>', '''            <Banner tone="positive">Example export completed.</Banner>
            <Banner tone="info" title="Value unavailable">
              No example observation is available. Missing is never zero.
            </Banner>
            <Banner tone="warning" title="Partial coverage">
              Two of three example sources are available. The missing source is not counted as zero.
            </Banner>
            <Banner tone="info" title="Actual zero">
              Reported movement: 0. This is an observed zero, not missing data.
            </Banner>''')
replace(GALLERY, 'title="Confirm trade proposal"', 'title="Trade proposal example"')
replace(GALLERY, 'Send Jefferson + 2027 2nd for Chase + 2026 1st? This posts the offer to your league.', 'Demonstration only. No trade offer is sent or saved.')
replace(GALLERY, '>Send offer</Button>', '>Close example</Button>')
replace(GALLERY, '<Sparkline values={[88, 90, 91, 93, 96, 97]}', '<Sparkline className={styles.drawerChart} values={[88, 90, 91, 93, 96, 97]}')
replace(GALLERY, '<Banner tone="info">Drawer replaces PlayerPopup in R2.</Banner>', '<Banner tone="info">Example player detail only. Real player links converge on the canonical Player File.</Banner>')

replace(CSS, '  max-width: 1080px;', '  max-width: 1080px;\n  width: 100%;\n  min-width: 0;\n  box-sizing: border-box;\n  background: var(--surface-0);\n  color: var(--text-primary);')
replace(CSS, '  gap: 2px;', '  gap: var(--space-1);')
replace(CSS, '  border-radius: 2px;', '  border-radius: var(--radius-1);')
replace(CSS, '.typeRow {\n  display: flex;', '.typeRow {\n  display: flex;\n  flex-wrap: wrap;\n  min-width: 0;')
(ROOT / CSS).write_text(read(CSS) + '''
/* Same editorial headline role as the approved Rankings reference. */
.hero :global(.ds-page-header__title) {
  font-family: var(--font-display);
  font-size: var(--font-size-3xl);
  font-style: italic;
}
.hero :global(.ds-page-header__eyebrow) {
  font-family: var(--font-data);
}
.displaySample {
  font-family: var(--font-display);
  font-size: var(--font-size-2xl);
  font-style: italic;
  line-height: var(--line-height-tight);
}
.roundIndicator {
  width: var(--space-10);
  height: var(--space-10);
}
.drawerChart {
  width: 100%;
  height: auto;
  max-width: 100%;
}
.swatchName {
  overflow-wrap: anywhere;
}
@media (max-width: 480px) {
  .page {
    padding: var(--space-4) var(--space-3) var(--space-7);
  }
  .cols2,
  .cols3,
  .cols4 {
    grid-template-columns: minmax(0, 1fr);
  }
  .tablePanel :global(.ds-panel__header) {
    flex-wrap: wrap;
  }
}
''', encoding='utf-8')
replace(PAGE, '/design — living style reference for the R0 design system.', '/design — living implementation reference for approved PSI / Direction A.')
replace(PAGE, 'the system at a glance. This page is the first impression of the new\n * design language — keep it as disciplined as the system it documents.', 'the system at a glance. Isolated examples are fixtures, not live product\n * data. Reuse the approved direction; this route does not authorize a redesign.')

put(UNIT, '''
import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DesignGallery from "@/app/design/DesignGallery";

// Real shared primitives, not mocks: this reference must preserve their APIs.
describe("PSI design reference", () => {
  it("uses the approved scope and labels deterministic examples truthfully", () => {
    render(<DesignGallery />);
    expect(screen.getByTestId("psi-gallery")).toHaveClass("psi-editorial");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText("Fixtures only")).toBeInTheDocument();
    expect(screen.getByText("Personnel & market intelligence")).toBeInTheDocument();
    expect(screen.getByText("Value unavailable")).toBeInTheDocument();
    expect(screen.getByText("Partial coverage")).toBeInTheDocument();
    expect(screen.getByText("Actual zero")).toBeInTheDocument();
    expect(screen.queryByText(/franchise-gold|posts the offer to your league/)).toBeNull();
    // The shell owns main; a reference page must not introduce nested landmarks.
    expect(screen.queryByRole("main")).toBeNull();
  });

  it("retains complete fixture identity, sorting and density controls", async () => {
    const user = userEvent.setup();
    render(<DesignGallery />);
    const table = screen.getByRole("table", { name: /Fixture value board/ });
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    expect(within(table).getByText("Justin Jefferson")).toBeInTheDocument();
    expect(within(table).getByText("Ja'Marr Chase")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Value" })).toHaveAttribute("aria-sort", "descending");
    await user.click(within(table).getByRole("button", { name: "Value" }));
    expect(within(table).getByRole("columnheader", { name: "Value" })).toHaveAttribute("aria-sort", "ascending");
    await user.click(within(screen.getByRole("radiogroup", { name: "Density" })).getByRole("radio", { name: "Compact" }));
    expect(table).toHaveClass("ds-table--compact");
  });

  it("preserves modal keyboard closure and opener focus without a real trade action", async () => {
    const user = userEvent.setup();
    render(<DesignGallery />);
    const opener = screen.getByRole("button", { name: "Open modal" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Trade proposal example" });
    expect(within(dialog).getByText("Demonstration only. No trade offer is sent or saved.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Send offer" })).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("keeps the canonical player example and a responsive accessible drawer chart", async () => {
    const user = userEvent.setup();
    render(<DesignGallery />);
    const opener = screen.getByRole("button", { name: "Open drawer" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Justin Jefferson" });
    const plot = within(dialog).getByRole("img", { name: "Jefferson 6-week value trend" });
    expect(plot).toHaveAttribute("viewBox", "0 0 360 48");
    expect(plot.className.baseVal).toMatch(/drawerChart/);
    expect(within(dialog).getByText(/canonical Player File/)).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});
''')
put(E2E, '''
/** Populated PSI reference, keyboard/axe and visual evidence on real viewports. */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function ready(page) {
  await page.goto(pageUrl("/design"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByTestId("psi-gallery")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Design system" })).toBeVisible();
  await expect(page.getByRole("table", { name: /Fixture value board/ }).locator("tbody tr")).toHaveCount(5);
  await page.evaluate(() => document.fonts.ready);
}

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "Only the controlled table region may scroll horizontally").toBeLessThanOrEqual(sizes.viewport + 1);
}

async function scan(page, testInfo, name) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  await testInfo.attach(name + "-axe", {
    body: JSON.stringify(results.violations, null, 2), contentType: "application/json",
  });
  expect(results.violations, name + " must have no WCAG A/AA violations").toEqual([]);
}

async function image(page, testInfo, name, fullPage = false) {
  const file = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: file, fullPage, animations: "disabled" });
  await testInfo.attach(name, { path: file, contentType: "image/png" });
}

test("PSI gallery: populated reference, table access and desktop/phone evidence", async ({ authedPage: page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const started = Date.now();
  await ready(page);
  const usefulMs = Date.now() - started;
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByText("Fixtures only")).toBeVisible();
  await noPageOverflow(page);
  const scope = await page.getByTestId("psi-gallery").evaluate(element => {
    const style = getComputedStyle(element);
    return { surface: style.getPropertyValue("--surface-0").trim(), accent: style.getPropertyValue("--accent").trim(), display: style.getPropertyValue("--font-display").trim() };
  });
  expect(scope.surface).toBe("#f2ebdd");
  expect(scope.accent).toBe("#a3341c");
  expect(scope.display).toContain("Georgia");
  await scan(page, testInfo, "populated");
  await image(page, testInfo, "reference-top");
  await image(page, testInfo, "reference-full", true);

  const table = page.getByRole("table", { name: /Fixture value board/ });
  await table.scrollIntoViewIfNeeded();
  await expect(table.getByText("Justin Jefferson", { exact: true })).toBeVisible();
  await table.getByRole("button", { name: "Value", exact: true }).click();
  await expect(table.getByRole("columnheader", { name: "Value", exact: true })).toHaveAttribute("aria-sort", "ascending");
  await page.getByRole("radiogroup", { name: "Density" }).getByRole("radio", { name: "Compact" }).click();
  await expect(table).toHaveClass(/ds-table--compact/);
  const region = table.locator("..");
  await region.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  await expect(table.getByRole("columnheader", { name: "Trend", exact: true })).toBeInViewport();
  await noPageOverflow(page);
  await image(page, testInfo, "table-secondary-fields");
  await testInfo.attach("measurement-context", {
    body: JSON.stringify({ sha: process.env.EVIDENCE_SHA || "unrecorded", origin: page.url(), viewport: page.viewportSize(), usefulMs, context: "CI built reference; not production SLO proof", scope }, null, 2),
    contentType: "application/json",
  });
  expect(errors).toEqual([]);
});

test("PSI gallery: accessible modal/drawer and keyboard focus under reduced motion", async ({ authedPage: page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await ready(page);
  for (const [button, title, name] of [
    ["Open modal", "Trade proposal example", "modal"],
    ["Open drawer", "Justin Jefferson", "drawer"],
  ]) {
    const opener = page.getByRole("button", { name: button, exact: true });
    await opener.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: title, exact: true });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
    await noPageOverflow(page);
    if (name === "drawer") {
      const chart = dialog.getByRole("img", { name: "Jefferson 6-week value trend" });
      const chartWidth = await chart.evaluate(node => node.getBoundingClientRect().width);
      const bodyWidth = await dialog.evaluate(node => node.clientWidth);
      expect(chartWidth).toBeLessThanOrEqual(bodyWidth);
    }
    await scan(page, testInfo, name);
    await image(page, testInfo, name);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  }
  expect(errors).toEqual([]);
});
''')

replace('docs/ui/UI_PARALLEL_LEDGER.md',
    '#1422 `codex/psi-design-reference` is the selected NEXT/queued reference\nunit until a worker starts; do not equate an issue/branch with a running session.',
    '#1422 `codex/psi-design-reference` is now an implementation branch for the bounded\nreference unit. Tests and visual evidence are separate gates; this is not deployment.')
replace('docs/ui/UI_PARALLEL_LEDGER.md', 'AUDITED — Legacy gallery; #1422 selected', 'MIGRATING — existing PSI scope applied; proof pending')
replace('docs/ui/UI_PARALLEL_LEDGER.md', '| #1422 queued |', '| #1422 implementation branch |')
replace('docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md', 'Initial status NEXT/queued, not running or verified.', 'Initial reservation has advanced to implementation; inspect the current PR/evidence before resuming. Deployment and production proof remain separate gates.')
print('Gallery/reference changes prepared after live overlap check and claim activation. No shared runtime, dependency, token or backend edits.')
