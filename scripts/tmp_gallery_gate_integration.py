from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    assert s.count(old) == 1, (path, old[:100], s.count(old))
    p.write_text(s.replace(old, new))

p = 'frontend/app/design/DesignGallery.jsx'
replace_once(p, 'const CHARTS = [1, 2, 3, 4, 5, 6];', '''const CHARTS = [1, 2, 3, 4, 5, 6];

// #1428: the inherited categorical colors are not approved for PSI cream plots.
// Keep only these reference previews gated; never infer acceptance from axe.
// No URL/env switch: enabling requires the separately recorded design decision,
// contrast proof and updated desktop/phone evidence. Product charts are untouched.
const CHART_PREVIEWS_APPROVED = false;''')
replace_once(p, '      {/* ── Color', '''      <Banner tone="warning" title="Chart previews unavailable">
        This reference is partially complete. Chart examples await an approved
        contrast-safe treatment (#1428). Fixture numbers remain available below;
        no replacement colors or chart-completion claim are implied.
      </Banner>

      {/* ── Color''')
replace_once(p, 'Chart series — existing fixed order; verify each plot surface', 'Chart token inventory — fixed order; plot acceptance pending #1428')
replace_once(p, '<Sparkline values={r.trend} label={`${r.name} 6-week trend`} series={1} />', '''CHART_PREVIEWS_APPROVED ? (
                  <Sparkline values={r.trend} label={`${r.name} 6-week trend`} series={1} />
                ) : (
                  <span className="ds-mono" aria-label={`${r.name} 6-week fixture values`}>
                    {r.trend.join(" → ")}
                  </span>
                )''')
replace_once(p, '''        subtitle="Sparkline + Meter. Larger charts compose lib/chart-primitives with the --chart-* slots."
      >
        <div className={styles.stack}>''', '''        subtitle="Sparkline + Meter previews are gated pending #1428. Existing fixture numbers are preserved."
      >
        {CHART_PREVIEWS_APPROVED ? <div className={styles.stack}>''')
replace_once(p, '''            <Meter value={2870} max={10000} label="Bench depth" series={4} />
          </div>
        </div>
      </Panel>''', '''            <Meter value={2870} max={10000} label="Bench depth" series={4} />
          </div>
        </div> : (
          <div className={styles.stack} data-testid="chart-preview-gate">
            <Banner tone="info" title="Chart treatment pending">
              These numerical fixtures are not an approved graphical chart reference.
            </Banner>
            <p className="ds-mono">Rising fixture: 20 → 24 → 22 → 30 → 34 → 33 → 40</p>
            <p className="ds-mono">Falling fixture: 40 → 38 → 39 → 31 → 28 → 26 → 22</p>
            <p className="ds-mono">Variable fixture: 10 → 14 → 8 → 16 → 12 → 18 → 13; baseline 12</p>
            <p className="ds-mono">Jefferson value: 9,541 / 10,000</p>
            <p className="ds-mono">Draft capital: 6,120 / 10,000</p>
            <p className="ds-mono">Bench depth: 2,870 / 10,000</p>
          </div>
        )}
      </Panel>''')
replace_once(p, '''          <Sparkline className={styles.drawerChart} values={[88, 90, 91, 93, 96, 97]} label="Jefferson 6-week value trend" width={360} height={48} />''', '''          {CHART_PREVIEWS_APPROVED ? (
            <Sparkline className={styles.drawerChart} values={[88, 90, 91, 93, 96, 97]} label="Jefferson 6-week value trend" width={360} height={48} />
          ) : (
            <div data-testid="drawer-chart-gate">
              <p className="ds-mono">Six-week fixture values: 88 → 90 → 91 → 93 → 96 → 97</p>
              <Banner tone="info">Chart preview unavailable pending approved treatment (#1428).</Banner>
            </div>
          )}''')

p = 'frontend/__tests__/components/ds/psi-gallery.test.jsx'
replace_once(p, '    expect(screen.getByText("Fixtures only")).toBeInTheDocument();', '''    expect(screen.getByText("Fixtures only")).toBeInTheDocument();
    expect(screen.getByText("Chart previews unavailable")).toBeInTheDocument();''')
replace_once(p, '  it("keeps the canonical player example and a responsive accessible drawer chart", async () => {', '  it("keeps the player example and honest numeric drawer detail while chart acceptance is pending", async () => {')
replace_once(p, '''    const plot = within(dialog).getByRole("img", { name: "Jefferson 6-week value trend" });
    expect(plot).toHaveAttribute("viewBox", "0 0 360 48");
    expect(plot.className.baseVal).toMatch(/drawerChart/);''', '''    expect(within(dialog).queryByRole("img", { name: "Jefferson 6-week value trend" })).toBeNull();
    expect(within(dialog).getByTestId("drawer-chart-gate")).toHaveTextContent("88 → 90 → 91 → 93 → 96 → 97");
    expect(within(dialog).getByText(/Chart preview unavailable/)).toBeInTheDocument();''')
s = Path(p).read_text()
needle = 'describe("PSI design reference", () => {'
s = s.replace(needle, needle + '''
  it("fails closed for every unapproved chart preview without discarding fixture numbers", async () => {
    const user = userEvent.setup();
    const { container } = render(<DesignGallery />);
    expect(container.querySelectorAll(".ds-sparkline, .ds-meter")).toHaveLength(0);
    expect(screen.getByTestId("chart-preview-gate")).toHaveTextContent("9,541 / 10,000");
    expect(screen.getByTestId("chart-preview-gate")).toHaveTextContent("2,870 / 10,000");
    const table = screen.getByRole("table", { name: /Fixture value board/ });
    expect(within(table).getByLabelText("Justin Jefferson 6-week fixture values")).toHaveTextContent("92 → 93 → 95 → 94 → 96 → 97");
    await user.click(screen.getByRole("button", { name: "Open drawer" }));
    expect(document.querySelectorAll(".ds-sparkline, .ds-meter")).toHaveLength(0);
    await user.keyboard("{Escape}");
  });
''')
Path(p).write_text(s)

p = 'tests/e2e/specs/psi-gallery.spec.js'
replace_once(p, '  await expect(page.getByText("Fixtures only")).toBeVisible();', '''  await expect(page.getByText("Fixtures only")).toBeVisible();
  await expect(page.getByText("Chart previews unavailable")).toBeVisible();
  await expect(page.locator(".ds-sparkline, .ds-meter")).toHaveCount(0);
  await expect(page.getByTestId("chart-preview-gate")).toContainText("9,541 / 10,000");''')
replace_once(p, '''      const chart = dialog.getByRole("img", { name: "Jefferson 6-week value trend" });
      const chartWidth = await chart.evaluate(node => node.getBoundingClientRect().width);
      const bodyWidth = await dialog.evaluate(node => node.clientWidth);
      expect(chartWidth).toBeLessThanOrEqual(bodyWidth);''', '''      const detail = dialog.getByTestId("drawer-chart-gate");
      await expect(detail).toContainText("88 → 90 → 91 → 93 → 96 → 97");
      await expect(detail).toContainText("Chart preview unavailable");
      await expect(page.locator(".ds-sparkline, .ds-meter")).toHaveCount(0);
      const detailWidth = await detail.evaluate(node => node.getBoundingClientRect().width);
      const bodyWidth = await dialog.evaluate(node => node.clientWidth);
      expect(detailWidth).toBeLessThanOrEqual(bodyWidth);''')

p = 'docs/WORK_CLAIMS.md'
s = Path(p).read_text()
old = [l for l in s.splitlines() if l.startswith('| **PSI gallery reference #1422')]
assert len(old) == 1
new = old[0].replace('checkpoint — code/CI/visual evidence recorded in draft PR #1429; #1428 blocks only chart acceptance. No continuously running worker or deployed acceptance claimed.', 'integration in progress — owner requested push/merge; releasing the non-chart gallery foundation with explicit fail-closed chart previews and numeric fixture detail. #1428 remains OPEN, route remains PARTIAL. Exact-tree frontend/E2E/evidence gates required; no production acceptance claimed.')
s = s.replace(old[0], new)
Path(p).write_text(s)

p = 'docs/ui/UI_PARALLEL_LEDGER.md'
s = Path(p).read_text()
s = s.replace('now draft PR #1429 with measured CI evidence. #1428 holds only chart-treatment acceptance; no deployment or continuously running worker is claimed.', 'PR #1429 in integration with chart previews explicitly gated. #1428 holds only chart-treatment acceptance; no deployment or continuously running worker is claimed.')
lines = s.splitlines()
idx = next(i for i, l in enumerate(lines) if l.startswith('| `/design` |'))
lines[idx] = '| `/design` | C8-U2/U3 | Static gallery / ds/token-contract.js; no private API | STABLE foundation; chart acceptance #1428 | MIGRATING — incremental non-chart foundation; charts explicitly gated | Integration proof required | Integration proof required | Earlier six axe scans/keyboard passed; gated release revalidation required; #1428 OPEN | Build/budget revalidation required; production NM | Gallery terminal copy retired; outer shell/FAB debt remains | Earlier CI PNGs retained as historical; fresh gated proof required; NO production proof | #1422 / PR #1429 integration | #1428 for chart previews only, not other UI | Validate and merge the gated foundation; keep chart decision and final production acceptance open |'
Path(p).write_text('\n'.join(lines) + '\n')

p = 'docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md'
s = Path(p).read_text()
start = s.index('## Current checkpoint')
end = s.index('## Copyable prompt')
s = s[:start] + '''## Current integration checkpoint — incremental foundation, not full chart acceptance

The owner subsequently requested push and merge. Governance #1426 is integrated.
PR #1429 releases only the independently usable gallery foundation: all unapproved
categorical previews are explicitly gated, with honest pending-state messaging and
numeric fixture history retained. No product chart, palette, DS owner or design
precedence is changed. #1428 remains OPEN; the gallery stays PARTIAL / MIGRATING,
not PSI_VERIFIED. Enabling previews requires separately approved treatment and proof.

Current-head integration validation, screenshot provenance and deployment status must
be read from PR #1429; old screenshots at 49e7fcf are historical, not the gated release.
The original 2,483-test / 14-budget / four-E2E / six-axe evidence remains historical.
Fresh desktop/phone and keyboard/axe proof is required before the gated state ships.
Production verification and shared shell outer-canvas/Screenshot-FAB debt remain open.
Continue dependency-safe populated Rankings/Player File test work while #1428 waits.
The prompt below is retained as historical scope, not permission to repeat completed
work or enable the chart gate. A branch does not imply a running background worker.

''' + s[end:]
Path(p).write_text(s)
print('Bounded chart gate, regression tests and honest integration records patched.')
