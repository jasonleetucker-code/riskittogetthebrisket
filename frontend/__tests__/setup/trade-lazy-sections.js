/**
 * The modules /trade loads through React.lazy (app/trade/page.jsx `dyn`).
 *
 * A test that drives the PAGE reveals these behind cold lazy boundaries.  The
 * first reveal in a file pays two costs inside Testing Library's default 1 s
 * wait — compiling the module on its first import (CPU-bound, so it grows with
 * the full suite's worker load) and React 19's Suspense reveal throttle
 * (FALLBACK_THROTTLE_MS = 300) — which is what made
 * trade-on-demand-sections-render.test.jsx flake under load.  Same fix as
 * dfs-workspace.test.jsx (#1792): compile every module before any timed wait,
 * and give a wait that crosses a COLD boundary an explicit budget.  A wait
 * still returns the moment its element appears; no assertion changes.
 *
 * Keep this list in step with the `dyn(...)` sections in app/trade/page.jsx.
 */
export const TRADE_LAZY_MODULES = {
  warRoom: () => import("@/components/trade/TradeWarRoom"),
  sourceBreakdown: () => import("@/components/trade/TradeSourceBreakdown"),
  rosFit: () => import("@/components/RosTradeFitPanel"),
  bdvm: () => import("@/components/BdvmTradePanel"),
  packageBreakdown: () => import("@/components/trade/TradePackageBreakdown"),
  decisionReasoning: () => import("@/components/trade/TradeDecisionReasoning"),
  assetSheet: () => import("@/app/trade/trade-asset-sheet"),
  multiFlow: () => import("@/components/graphs/MultiTradeFlow"),
  recentRealTrades: () => import("@/components/trade/RecentRealTrades"),
  opinionTally: () => import("@/components/trade/TradeOpinionTally"),
  nextActions: () => import("@/components/trade/TradeNextActions"),
  simulationPanel: () => import("@/app/trade/trade-simulation-panel"),
  ktcImport: () => import("@/app/trade/trade-ktc-import"),
  screenshotImport: () => import("@/app/trade/trade-screenshot-import"),
  suggestionsDesk: () => import("@/app/trade/trade-suggestions-desk"),
};

/**
 * Compile the page and its lazy modules.  `skip` names modules a test mocks to
 * FAIL (a missing chunk) — importing those here would throw.
 */
export async function prewarmTradeSections({ skip = [] } = {}) {
  await import("@/app/trade/page");
  await Promise.all(
    Object.entries(TRADE_LAZY_MODULES)
      .filter(([name]) => !skip.includes(name))
      .map(([, load]) => load()),
  );
}

/** Budget for a wait that reveals a lazy /trade section for the first time in a file. */
export const COLD_LAZY_REVEAL = { timeout: 10_000 };

/** Generous hook timeout for the prewarm itself. */
export const PREWARM_TIMEOUT_MS = 60_000;
