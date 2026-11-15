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
import { render, screen, cleanup, act } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { useRef } from "react";
import { DataTable } from "@/components/ds/DataTable";
import { useRowWindow } from "@/components/ds/useRowWindow";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

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
  it("publishes changed geometry once instead of rerendering for identical row heights", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result } = windowFor({ rowCount: 1000 });
    const measure = (height) => {
      result.current.measure(0, { offsetTop: 0, isConnected: true });
      result.current.measure(1, { offsetTop: height, isConnected: true });
      act(() => frames.splice(0).forEach((callback) => callback()));
    };
    measure(42);
    const stable = result.current;
    expect(stable.padTop + (stable.end - stable.start) * 42 + stable.padBottom).toBeCloseTo(42000, 0);
    measure(42);
    expect(result.current).toBe(stable);
    // A real height change must still update geometry, including when
    // changed samples first move the median between two observed heights.
    measure(60);
    measure(60);
    expect(result.current).not.toBe(stable);
  });

  // The ref callback runs inside React's commit. Reading `offsetTop` there
  // forced a synchronous layout of the whole table on every commit, before
  // the browser could paint (~300 ms of the /rankings post-data window at
  // 4x CPU). The read belongs in the frame drain, in one pass.
  function rowWithTop(top, reads) {
    return {
      isConnected: true,
      get offsetTop() {
        reads.push(top);
        return top;
      },
    };
  }

  it("never reads layout inside the ref callback — only in the frame drain", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result } = windowFor({ rowCount: 1000 });
    const reads = [];
    result.current.measure(0, rowWithTop(0, reads));
    result.current.measure(1, rowWithTop(50, reads));
    expect(reads).toEqual([]);
    act(() => frames.splice(0).forEach((callback) => callback()));
    expect(reads.sort((a, b) => a - b)).toEqual([0, 50]);
    const r = result.current;
    expect(r.padTop + (r.end - r.start) * 50 + r.padBottom).toBeCloseTo(50000, 0);
  });

  function hookWith(initial) {
    return renderHook(
      (props) => {
        const tableRef = useRef(fakeTable(0));
        return useRowWindow({
          rowCount: 200,
          tableRef,
          scrollRef: null,
          hasBefore: () => false,
          hasAfter: () => false,
          ...props,
        });
      },
      { initialProps: initial },
    );
  }

  it("a table that never windows reads no layout at all", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result } = hookWith({ enabled: false, armed: false });
    const reads = [];
    for (let i = 0; i < 200; i += 1) result.current.measure(i, rowWithTop(i * 34, reads));
    act(() => frames.splice(0).forEach((callback) => callback()));
    expect(reads).toEqual([]);
    expect(frames).toEqual([]);
  });

  it("armed: the unwindowed board is read in its own commit and learned once windowing engages", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result, rerender } = hookWith({ enabled: false, armed: true });
    const reads = [];
    // The full board mounts while widths are being frozen: read now, in the
    // layout that commit's column freeze forces anyway.
    for (let i = 0; i < 200; i += 1) result.current.measure(i, rowWithTop(i * 40, reads));
    expect(reads).toHaveLength(200);
    // The freeze re-renders synchronously with windowing on, before the frame.
    rerender({ enabled: true, armed: false });
    act(() => frames.splice(0).forEach((callback) => callback()));
    const r = result.current;
    expect(r.windowed).toBe(true);
    expect(r.padTop + (r.end - r.start) * 40 + r.padBottom).toBeCloseTo(200 * 40, 0);
  });

  it("never pairs a commit-time offset with a frame-time offset from another layout", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result, rerender } = hookWith({ enabled: false, armed: true });
    const reads = [];
    result.current.measure(5, rowWithTop(0, reads));
    rerender({ enabled: true, armed: false });
    const before = result.current;
    // Row 6 is measured under the windowed layout, where spacers moved it.
    result.current.measure(6, rowWithTop(500, reads));
    act(() => frames.splice(0).forEach((callback) => callback()));
    // A 500 px "row" learned across layouts would reshape the whole map.
    expect(result.current.padBottom).toBe(before.padBottom);
    expect(result.current.end).toBe(before.end);
  });

  it("skips a row detached before the drain instead of reading it as 0", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result } = windowFor({ rowCount: 1000 });
    const before = result.current;
    const reads = [];
    const gone = rowWithTop(0, reads);
    result.current.measure(0, gone);
    result.current.measure(1, rowWithTop(40, reads));
    gone.isConnected = false;
    act(() => frames.splice(0).forEach((callback) => callback()));
    // The detached row is never read; the one connected row alone cannot
    // form a delta, so nothing is learned and geometry is unchanged.
    expect(reads).toEqual([40]);
    expect(result.current).toBe(before);
  });

  it("measures a re-indexed row only at its latest index", () => {
    const frames = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    const { result } = windowFor({ rowCount: 1000 });
    const before = result.current;
    const reads = [];
    const a = rowWithTop(0, reads);
    const b = rowWithTop(45, reads);
    // Commit 1 puts a/b at 7/8 (consecutive); a re-sort in the same frame
    // moves them to 0/3. Their stale 7/8 pairing must not teach a 45 px row.
    result.current.measure(7, a);
    result.current.measure(8, b);
    result.current.measure(0, a);
    result.current.measure(3, b);
    act(() => frames.splice(0).forEach((callback) => callback()));
    expect(result.current).toBe(before);
  });

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
