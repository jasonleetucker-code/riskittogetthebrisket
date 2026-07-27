/**
 * The hydration gap in `useSettings`, exercised through a real
 * server-render + hydrate cycle rather than described in a comment.
 *
 * `renderToString` is what the pre-fix bug actually looked like: React
 * calls `getServerSnapshot` for the SSR pass AND the hydration pass, so
 * markup shipped to a user whose persisted lens is "leagueAdjusted"
 * carried `aria-checked="true"` on **Market**. The first paint asserted
 * the wrong value basis, and only the post-hydration re-render corrected
 * it.
 *
 * So the guard is on the SERVER STRING, not on the settled DOM. Asserting
 * the settled DOM passes with or without the fix — it was always correct
 * once React caught up. That is the whole defect: the wrong state is
 * transient, and a test that only looks at the end never sees it.
 */
import { describe, expect, it, beforeEach } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import { render, screen } from "@testing-library/react";
import { SegmentedControl } from "@/components/ds/SegmentedControl";
import { useSettings } from "@/components/useSettings";
import { SETTINGS_KEY } from "@/lib/trade-logic";

const OPTIONS = [
  { value: "market", label: "Market" },
  { value: "leagueAdjusted", label: "My league" },
];

/** The two call sites on /rankings and /trade, reduced to their shape. */
function ValuationToggle() {
  const { settings, hydrated } = useSettings();
  return (
    <SegmentedControl
      label="Value basis"
      value={hydrated ? settings.valuationMode || "market" : null}
      options={OPTIONS}
      onChange={() => {}}
    />
  );
}

/** The pre-fix call site, kept as the control for the assertions below. */
function UngatedToggle() {
  const { settings } = useSettings();
  return (
    <SegmentedControl
      label="Value basis"
      value={settings.valuationMode || "market"}
      options={OPTIONS}
      onChange={() => {}}
    />
  );
}

/**
 * The store memoizes in a module-level `cached` that only a write through
 * `update()` or a cross-tab storage event invalidates. Tests mutate
 * localStorage directly, so they must fire the store's own invalidation
 * path afterwards rather than reaching into its internals.
 */
function syncStore() {
  window.dispatchEvent(new StorageEvent("storage", { key: SETTINGS_KEY }));
}

function persistLeagueAdjusted() {
  window.localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({ valuationMode: "leagueAdjusted", tepDefaultV3Applied: true })
  );
  syncStore();
}

describe("useSettings hydration gate", () => {
  beforeEach(() => {
    window.localStorage.clear();
    syncStore();
  });

  it("the server render claims no value basis at all", () => {
    persistLeagueAdjusted();
    const html = renderToString(<ValuationToggle />);
    expect(html).not.toContain('aria-checked="true"');
  });

  it("the UNGATED render is the bug: it asserts Market on the server", () => {
    // The control case. If this ever stops containing a checked option,
    // the hydration gap has closed some other way and the gate above is
    // no longer load-bearing — which is worth finding out from a failing
    // test rather than assuming.
    persistLeagueAdjusted();
    const html = renderToString(<UngatedToggle />);
    expect(html).toContain('aria-checked="true"');
    // And specifically the WRONG one: Market, not the persisted lens.
    const marketIdx = html.indexOf("Market");
    const leagueIdx = html.indexOf("My league");
    const checkedIdx = html.indexOf('aria-checked="true"');
    expect(checkedIdx).toBeLessThan(marketIdx);
    expect(checkedIdx).toBeLessThan(leagueIdx);
  });

  it("settles on the persisted lens on the client", () => {
    persistLeagueAdjusted();
    render(<ValuationToggle />);
    expect(screen.getByRole("radio", { name: "My league" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
  });

  it("settles on the default when nothing is persisted", () => {
    render(<ValuationToggle />);
    expect(screen.getByRole("radio", { name: "Market" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
  });

  it("hydrated is false on the server and true on the client", () => {
    function Probe() {
      const { hydrated } = useSettings();
      return <span data-testid="h">{String(hydrated)}</span>;
    }
    expect(renderToString(<Probe />)).toContain(">false<");
    render(<Probe />);
    expect(screen.getByTestId("h")).toHaveTextContent("true");
  });
});
