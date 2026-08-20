/**
 * Row windowing: the geometry, the refusal, and the accessibility
 * contract that windowing would otherwise break.
 *
 * WHAT THESE CAN AND CANNOT COVER
 * ───────────────────────────────
 * jsdom has no layout engine: every `getBoundingClientRect().width` is 0,
 * so `DataTable`'s width-freeze pass never completes there and windowing —
 * which REQUIRES it — never turns on through the component. That is not a
 * gap to paper over with a mock that reports fake widths; it would make
 * the test agree with itself rather than with a browser.
 *
 * So the split is deliberate:
 *   * the hook's arithmetic is tested directly, with a stubbed table rect
 *     standing in for layout;
 *   * `DataTable`'s REFUSAL to virtualize without the prerequisite is
 *     tested through the component, because that path does not need
 *     layout;
 *   * the windowed board itself is covered in the browser, by
 *     `tests/e2e/specs/journey-rankings.spec.js` and `mobile-smoke.spec.js`
 *     via `journey.js::boardRowCount`, plus the FPS harness.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { useRef } from "react";
import { DataTable } from "@/components/ds/DataTable";
import { useRowWindow } from "@/components/ds/useRowWindow";

afterEach(cleanup);

const ROW_H = 34; // the hook's declared bootstrap height

/** A table element whose top is `top` px above the viewport. */
function fakeTable(top) {
  const el = document.createElement("table");
  el.getBoundingClientRect = () => ({
    top,
    bottom: 0,
    left: 0,
    right: 0,
    width: 0,
    height: 0,
    x: 0,
    y: top,
  });
  return el;
}

function windowFor({ rowCount, scrolledPast = 0, viewportHeight = 800 }) {
  window.innerHeight = viewportHeight;
  return renderHook(() => {
    const tableRef = useRef(fakeTable(-scrolledPast));
    return useRowWindow({
      rowCount,
      enabled: true,
      tableRef,
      scrollRef: null,
      hasBefore: () => false,
      hasAfter: () => false,
    });
  });
}

describe("useRowWindow", () => {
  it("mounts a viewport's worth of rows, not the whole board", () => {
    const { result } = windowFor({ rowCount: 1000, viewportHeight: 800 });
    const mounted = result.current.end - result.current.start;
    expect(result.current.windowed).toBe(true);
    // ~24 rows of viewport + overscan either side. The assertion is a
    // BAND, not a number: pinning the exact count would fail on any
    // overscan change without anything being wrong.
    expect(mounted).toBeGreaterThan(10);
    expect(mounted).toBeLessThan(100);
  });

  it("keeps the scrollable height intact — spacers replace the rows they stand in for", () => {
    const { result } = windowFor({ rowCount: 1000 });
    const { start, end, padTop, padBottom } = result.current;
    const mountedHeight = (end - start) * ROW_H;
    // Total height the browser sees must still be the whole board.
    // Getting this wrong is what makes a scrollbar jump under the thumb.
    expect(padTop + mountedHeight + padBottom).toBeCloseTo(1000 * ROW_H, 0);
  });

  it("moves the window when the table has been scrolled past", () => {
    const top = windowFor({ rowCount: 1000, scrolledPast: 0 });
    const deep = windowFor({ rowCount: 1000, scrolledPast: 400 * ROW_H });
    expect(top.result.current.start).toBe(0);
    expect(deep.result.current.start).toBeGreaterThan(350);
    expect(deep.result.current.padTop).toBeGreaterThan(0);
  });

  it("never renders past the end of the board", () => {
    const { result } = windowFor({ rowCount: 12, viewportHeight: 4000 });
    expect(result.current.end).toBeLessThanOrEqual(12);
    expect(result.current.padBottom).toBe(0);
  });

  it("is inert when disabled — every row, no spacers", () => {
    const { result } = renderHook(() => {
      const tableRef = useRef(fakeTable(0));
      return useRowWindow({
        rowCount: 500,
        enabled: false,
        tableRef,
        scrollRef: null,
        hasBefore: () => false,
        hasAfter: () => false,
      });
    });
    expect(result.current.windowed).toBe(false);
    expect(result.current.start).toBe(0);
    expect(result.current.end).toBe(500);
    expect(result.current.padTop).toBe(0);
    expect(result.current.padBottom).toBe(0);
  });

  it("reserves space for caller-injected rows instead of ignoring them", () => {
    // A board with a tier separator before every 10th row is TALLER than
    // one without, and the map has to know that or the spacer below is
    // short by one separator per group — which is exactly how a windowed
    // list drifts as you scroll.
    const withSeparators = renderHook(() => {
      const tableRef = useRef(fakeTable(0));
      return useRowWindow({
        rowCount: 200,
        enabled: true,
        tableRef,
        scrollRef: null,
        hasBefore: (i) => i % 10 === 0,
        hasAfter: () => false,
      });
    });
    const plain = windowFor({ rowCount: 200 });
    const totalOf = (r) =>
      r.padTop + (r.end - r.start) * ROW_H + r.padBottom;
    expect(totalOf(withSeparators.result.current)).toBeGreaterThan(
      totalOf(plain.result.current),
    );
  });
});

describe("DataTable virtualize prop", () => {
  const columns = [{ key: "name", header: "Name" }];
  const rows = Array.from({ length: 300 }, (_, i) => ({
    id: i,
    name: `Player ${i}`,
  }));

  it("refuses to virtualize without freezeColumnWidths, and says so once", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<DataTable caption="c" columns={columns} rows={rows} virtualize />);
    // All rows render: a table that works is a better failure than a
    // table whose columns resize under the user's cursor.
    expect(screen.getAllByText(/^Player \d+$/)).toHaveLength(300);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toMatch(/freezeColumnWidths/);
    warn.mockRestore();
  });

  it("declares no aria-rowcount when it is not windowing", () => {
    // Publishing a count the DOM already tells the truth about is one
    // more thing to drift out of sync.
    const { container } = render(
      <DataTable caption="c" columns={columns} rows={rows.slice(0, 5)} />,
    );
    expect(container.querySelector("table")).not.toHaveAttribute("aria-rowcount");
  });
});
