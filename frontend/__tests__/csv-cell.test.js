/**
 * lib/csv-cell — the client CSV formula-injection owner.
 *
 * Three things are pinned here:
 *
 *   1. PARITY with the Python owner (src/public_league/csv_export.py).  The
 *      expected values live in tests/fixtures/csv_formula_cases.json, which
 *      tests/api/test_task13_security_hardening.py reads too, so one rule is
 *      enforced in both languages byte for byte.
 *   2. Every client CSV builder neutralizes a formula-shaped name and leaves
 *      a number a number.
 *   3. A GUARD: a new `text/csv` download in frontend/app, frontend/lib or
 *      frontend/components that does not route its cells through csv-cell
 *      fails here, by file name.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import fixture from "../../tests/fixtures/csv_formula_cases.json";
import { csvCell, csvField, csvLine, neutralizeCsvText } from "../lib/csv-cell.js";
import { tradeWorkspaceToCSV } from "../lib/trade-logic.js";
import { draftReviewToCsv } from "../lib/draft-logic.js";

describe("csv-cell parity with the Python owner", () => {
  it("the fixture is not empty (an empty file would pass vacuously)", () => {
    expect(fixture.neutralize.length).toBeGreaterThan(20);
    expect(fixture.cell.length).toBeGreaterThan(15);
  });

  for (const c of fixture.neutralize) {
    it(`neutralizeCsvText(${JSON.stringify(c.input)})`, () => {
      expect(neutralizeCsvText(c.input)).toBe(c.expected);
    });
  }

  for (const c of fixture.cell) {
    it(`csvCell(${JSON.stringify(c.input)})`, () => {
      expect(csvCell(c.input)).toBe(c.expected);
    });
  }
});

describe("csv-cell behaviour", () => {
  it("numbers stay numbers, including negatives", () => {
    expect(csvCell(-3.5)).toBe("-3.5");
    expect(csvField(-7)).toBe("-7");
    expect(csvLine(["=x", -2, 3])).toBe("'=x,-2,3");
  });

  it("a non-finite number is an empty cell — never 'NaN', never 0", () => {
    expect(csvCell(NaN)).toBe("");
    expect(csvCell(Infinity)).toBe("");
    expect(csvCell(-Infinity)).toBe("");
    expect(csvCell([NaN, 1])).toBe(" | 1");
  });

  it("missing is an empty cell", () => {
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
  });

  it("quotes after neutralizing, so the prefix sits inside the quotes", () => {
    expect(csvField('=HYPERLINK("x")')).toBe('"\'=HYPERLINK(""x"")"');
    expect(csvField("a,b")).toBe('"a,b"');
    expect(csvField("line\nbreak")).toBe('"line\nbreak"');
    expect(csvField("\r=1")).toBe('"\'\r=1"');
    expect(csvField("plain")).toBe("plain");
  });
});

describe("every client CSV builder neutralizes formulas", () => {
  it("trade workspace: a Sleeper team name cannot execute", () => {
    const sides = [
      {
        label: '=HYPERLINK("http://evil","x")',
        assets: [{ name: "@SUM(A1)", pos: "QB", team: "+BUF", values: { full: -12 } }],
      },
    ];
    const line = tradeWorkspaceToCSV(sides, "full", "-basis").trim().split("\n")[1];
    expect(line).toBe(
      '"\'=HYPERLINK(""http://evil"",""x"")",\'@SUM(A1),QB,\'+BUF,-12,\'-basis,',
    );
  });

  it("draft review: manager / team names are neutralized, deltas stay numbers", () => {
    const csv = draftReviewToCsv({
      csvHeader: ["Team", "Player", "Delta"],
      csvBody: [["=cmd|' /C calc'!A0", "Jeremiyah Love", -5]],
    });
    expect(csv.split("\n")[1]).toBe("'=cmd|' /C calc'!A0,Jeremiyah Love,-5");
  });
});

// ── Guard ────────────────────────────────────────────────────────────
const FRONTEND = path.resolve(__dirname, "..");
const OWNER = "lib/csv-cell.js";
const SCAN_DIRS = ["app", "lib", "components"];

/**
 * Pages that trigger a download whose CSV TEXT is built by a library
 * function.  The page itself holds only the `text/csv` MIME string; the
 * named builder must live in the named module, which must import csv-cell.
 */
const DELEGATES = {
  "app/trade/page.jsx": { module: "lib/trade-logic.js", builder: "tradeWorkspaceToCSV" },
  "app/draft/page.jsx": { module: "lib/draft-logic.js", builder: "draftReviewToCsv" },
};

/**
 * Exempt with a reason.  The DFS lineup files are DraftKings upload
 * templates produced server-side (src/dfs/export.py, src/dfs/entries.py) and
 * deliberately not neutralized there — a leading `'` would break the
 * DraftKings import.  The client only saves the server's bytes
 * (lib/dfs-download.js) or reads a user's own file (`accept="text/csv"`).
 */
const EXEMPT_PREFIXES = {
  "components/dfs/": "DFS: reads user-supplied CSV files; builds none",
  "lib/dfs-download.js": "DFS: saves the server's DraftKings CSV verbatim",
};

function walk(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...walk(full));
    else if (/\.(js|jsx|mjs|ts|tsx)$/.test(ent.name)) out.push(full);
  }
  return out;
}

function sourceFiles() {
  return SCAN_DIRS.flatMap((d) => walk(path.join(FRONTEND, d))).map((full) => ({
    rel: path.relative(FRONTEND, full).split(path.sep).join("/"),
    text: fs.readFileSync(full, "utf8"),
  }));
}

const IMPORTS_CSV_CELL = /from\s+["'](?:@\/lib\/|\.\/|\.\.\/(?:\.\.\/)*lib\/)csv-cell(?:\.js)?["']/;
/** A CSV MIME literal used to BUILD a download, not a file picker's accept=. */
function buildsCsvDownload(text) {
  return text.split("\n").some((line) => /text\/csv/.test(line) && !/accept=/.test(line));
}
/** A hand-rolled RFC 4180 quote: the sign of a builder bypassing the owner. */
const HAND_ROLLED_QUOTE = /\.replace\(\/"\/g,\s*['"`]""['"`]\)/;

describe("guard: no client CSV download bypasses csv-cell", () => {
  const files = sourceFiles();
  const exempt = (rel) => Object.keys(EXEMPT_PREFIXES).some((p) => rel.startsWith(p));

  it("finds the known builders (the scan is not vacuous)", () => {
    const builders = files.filter((f) => buildsCsvDownload(f.text)).map((f) => f.rel);
    for (const known of [
      "app/rankings/page.jsx",
      "app/idptc-rookies/page.jsx",
      "app/trade/page.jsx",
      "app/draft/page.jsx",
    ]) {
      expect(builders).toContain(known);
    }
  });

  it("every text/csv download imports csv-cell or delegates to a builder that does", () => {
    const offenders = [];
    for (const f of files) {
      if (f.rel === OWNER || exempt(f.rel) || !buildsCsvDownload(f.text)) continue;
      if (IMPORTS_CSV_CELL.test(f.text)) continue;
      const d = DELEGATES[f.rel];
      if (d) {
        const mod = files.find((m) => m.rel === d.module);
        const ok =
          f.text.includes(d.builder) &&
          mod &&
          IMPORTS_CSV_CELL.test(mod.text) &&
          new RegExp(`export function ${d.builder}\\b`).test(mod.text);
        if (ok) continue;
        offenders.push(`${f.rel} (delegate ${d.module}::${d.builder} no longer routes through csv-cell)`);
        continue;
      }
      offenders.push(f.rel);
    }
    expect(
      offenders,
      "a client CSV download must build its cells with lib/csv-cell (csvField / csvLine) " +
        "so a team or player name cannot execute as a spreadsheet formula",
    ).toEqual([]);
  });

  it("no CSV builder keeps a hand-rolled quote beside the owner", () => {
    const offenders = files
      .filter((f) => f.rel !== OWNER && !exempt(f.rel))
      .filter((f) => HAND_ROLLED_QUOTE.test(f.text))
      .map((f) => f.rel);
    expect(offenders).toEqual([]);
  });

  it("every delegate entry still names a real page and builder (no stale exemptions)", () => {
    for (const [rel, d] of Object.entries(DELEGATES)) {
      const page = files.find((f) => f.rel === rel);
      expect(page, `${rel} is gone: delete its DELEGATES entry`).toBeTruthy();
      expect(page.text.includes(d.builder), `${rel} no longer calls ${d.builder}`).toBe(true);
    }
  });
});
