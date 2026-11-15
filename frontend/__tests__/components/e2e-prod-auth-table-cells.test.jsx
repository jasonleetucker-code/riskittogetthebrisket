/**
 * Regression guard for V1 authenticated run 39380287586 (build
 * 9d07b9cebf): two prod-auth specs failed against correct product markup.
 *
 * #1849 (CQ-30) gave DataTable disclosure rows a visually hidden
 * `<button class="ds-table__disclosure" aria-expanded>` as the first child
 * of the first never-hidden column.  It is clipped, not `display: none`,
 * so it stays in innerText and in substring text matches:
 *
 *   - v1-111 read the whole `td[data-col="rank"]` and parsed
 *     "Source breakdown for <name>1" — NaN, not rank #1;
 *   - v1-62 matched the top row's name with `getByText(name,
 *     { exact: false })` and hit both the hidden toggle and the visible
 *     name link — a Playwright strict-mode violation.
 *
 * This file pins (a) the shared cell reader the specs now use, against the
 * REAL DataTable + PlayerNameButton markup, and (b) that neither spec goes
 * back to the read that broke.  Playwright cannot run here (the specs need
 * a production session), so the reader is exercised in jsdom; jsdom has no
 * `innerText`, and `textContent` stands in for what Chromium returned
 * (the toggle's text is included either way — verified with Chromium on
 * the exact ds.css rule while diagnosing the failure).
 */
import { describe, expect, it } from "vitest";
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { render, within } from "@testing-library/react";
import { DataTable } from "@/components/ds";
import { PlayerNameButton } from "@/components/ds/PlayerNameButton";

const require = createRequire(import.meta.url);
const PROD_AUTH_DIR = path.resolve(
  __dirname,
  "../../../tests/e2e/specs/prod-auth",
);
const {
  DISCLOSURE_SELECTOR,
  cellTextWithoutDisclosure,
  readCellText,
} = require(path.join(PROD_AUTH_DIR, "table-cells.js"));

// ── /rankings shape: disclosure in the rank column ──────────────────
const RANK_COLUMNS = [
  {
    key: "rank",
    header: "#",
    render: (row) => <span>{row.rank || "—"}</span>,
  },
  { key: "name", header: "Player" },
  { key: "tier", header: "Tier", hideBelow: "md" },
];
const RANK_ROWS = [
  { name: "Josh Allen", rank: 1, tier: 1 },
  { name: "Unranked Guy", rank: null, tier: null },
];

function renderRankings() {
  return render(
    <DataTable
      caption="board"
      columns={RANK_COLUMNS}
      rows={RANK_ROWS}
      rowKey={(r) => r.name}
      onRowClick={() => {}}
      isRowExpanded={() => false}
      rowExpandLabel={(row) => `Source breakdown for ${row.name}`}
    />,
  );
}

// ── /market/sharp-tracker shape: disclosure + name link, one cell ───
const SHARP_COLUMNS = [
  {
    key: "displayName",
    header: "Player",
    render: (row) => (
      <div>
        <div>
          <PlayerNameButton
            name={row.displayName || row.assetId}
            playerId={row.playerId}
          />
        </div>
        <div className="muted">{row.position}</div>
      </div>
    ),
  },
  { key: "signalStrength", header: "Signal" },
];
const SHARP_ROWS = [
  {
    assetId: "a1",
    displayName: "Ja'Marr Chase",
    playerId: "7564",
    position: "WR",
    signalStrength: 9,
  },
  {
    assetId: "a2",
    displayName: "No Id Guy",
    playerId: null,
    position: "RB",
    signalStrength: 3,
  },
];

function renderSharp() {
  return render(
    <DataTable
      caption="market"
      columns={SHARP_COLUMNS}
      rows={SHARP_ROWS}
      rowKey={(r) => r.assetId}
      onRowClick={() => {}}
      isRowExpanded={() => false}
      rowExpandLabel={(row) =>
        `Source breakdown for ${row.displayName || row.assetId}`
      }
    />,
  );
}

describe("prod-auth table-cells reader vs real DataTable disclosure markup", () => {
  it("the selector is DataTable's actual disclosure class", () => {
    const { container } = renderRankings();
    expect(container.querySelectorAll(DISCLOSURE_SELECTOR)).toHaveLength(
      RANK_ROWS.length,
    );
  });

  it("whole-cell text includes the hidden toggle — the read that failed", () => {
    const { container } = renderRankings();
    const cell = container.querySelector('tbody tr td[data-col="rank"]');
    expect(cell.textContent).toBe("Source breakdown for Josh Allen1");
    expect(Number.isNaN(parseInt(cell.textContent, 10))).toBe(true);
  });

  it("reads the visible rank only, so rank #1 parses as 1", () => {
    const { container } = renderRankings();
    const cell = container.querySelector('tbody tr td[data-col="rank"]');
    const text = cellTextWithoutDisclosure(cell);
    expect(text).toBe("1");
    expect(parseInt(text, 10)).toBe(1);
  });

  it("an unranked row still reads as the em-dash partial-data state", () => {
    const { container } = renderRankings();
    const cell = container.querySelectorAll('tbody tr td[data-col="rank"]')[1];
    expect(cellTextWithoutDisclosure(cell).startsWith("—")).toBe(true);
  });

  it("is a no-op on a cell with no disclosure toggle", () => {
    const { container } = renderRankings();
    const cell = container.querySelector('tbody tr td[data-col="name"]');
    expect(cell.querySelector(DISCLOSURE_SELECTOR)).toBeNull();
    expect(cellTextWithoutDisclosure(cell)).toBe(cell.textContent.trim());
  });

  it("strips a toggle nested below the cell's direct children", () => {
    const td = document.createElement("td");
    td.innerHTML =
      '<div><button class="ds-table__disclosure">Source breakdown for X</button><span>7</span></div>';
    expect(cellTextWithoutDisclosure(td)).toBe("7");
  });

  it("survives Playwright's serialization (no closure over module scope)", () => {
    const { container } = renderRankings();
    const cell = container.querySelector('tbody tr td[data-col="rank"]');
    // locator.evaluate ships fn.toString() into the page.
    const shipped = new Function(
      `return (${cellTextWithoutDisclosure.toString()})`,
    )();
    expect(shipped(cell, DISCLOSURE_SELECTOR)).toBe("1");
    expect(shipped(cell)).toBe("1");
  });

  it("readCellText evaluates the reader on the cell with the selector", async () => {
    const { container } = renderRankings();
    const cell = container.querySelector('tbody tr td[data-col="rank"]');
    const fakeLocator = { evaluate: async (fn, arg) => fn(cell, arg) };
    await expect(readCellText(fakeLocator)).resolves.toBe("1");
  });
});

describe("sharp-tracker top-row name match", () => {
  it("a substring name match hits the hidden toggle AND the name — the strict-mode failure", () => {
    const { container } = renderSharp();
    const topRow = container.querySelector("tbody tr");
    expect(
      within(topRow).getAllByText("Ja'Marr Chase", { exact: false }),
    ).toHaveLength(2);
  });

  it("an exact match inside the Player cell resolves to the visible name link only", () => {
    const { container } = renderSharp();
    const cell = container.querySelector('tbody tr td[data-col="displayName"]');
    const matches = within(cell).getAllByText("Ja'Marr Chase", { exact: true });
    expect(matches).toHaveLength(1);
    expect(matches[0].tagName).toBe("A");
    expect(matches[0]).toHaveClass("ds-player-name");
    const toggle = cell.querySelector(DISCLOSURE_SELECTOR);
    expect(toggle).toHaveTextContent("Source breakdown for Ja'Marr Chase");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("a row without a player id (plain span) still resolves exactly once", () => {
    const { container } = renderSharp();
    const cell = container.querySelectorAll(
      'tbody tr td[data-col="displayName"]',
    )[1];
    const matches = within(cell).getAllByText("No Id Guy", { exact: true });
    expect(matches).toHaveLength(1);
    expect(matches[0].tagName).toBe("SPAN");
  });
});

describe("the prod-auth specs do not return to the reads that broke", () => {
  const read = (name) =>
    fs.readFileSync(path.join(PROD_AUTH_DIR, name), "utf-8");

  it("v1-111 reads rank cells through readCellText, never raw innerText", () => {
    const src = read("v1-111-premium-rankings.spec.js");
    expect(src).not.toMatch(/td\[data-col="rank"\]'\)\s*\.innerText\(/);
    expect(src.match(/readCellText\(/g) || []).toHaveLength(2);
    expect(src).toMatch(/locator\(DISCLOSURE_SELECTOR\)/);
    expect(src).toMatch(/toHaveAttribute\("aria-expanded", "false"\)/);
  });

  it("v1-62 matches the top-row name exactly in its column and asserts the toggle", () => {
    const src = read("v1-62-sharp-tracker.spec.js");
    expect(src).not.toMatch(/topRow\.getByText\([^)]*exact:\s*false/);
    expect(src).toMatch(/playerCell\.getByText\(topName, \{ exact: true \}\)/);
    expect(src).toMatch(/locator\(DISCLOSURE_SELECTOR\)/);
    expect(src).toMatch(/toHaveAttribute\("aria-expanded", "false"\)/);
  });
});
