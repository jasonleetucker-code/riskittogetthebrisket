/**
 * useHydrated — false while React is hydrating server-rendered markup,
 * true once this component's event handlers are attached.  The ONE owner
 * of the ds "hydration gate".
 *
 * WHY: a server-rendered control is painted long before React has
 * attached its onClick.  On a slow network the page JavaScript can take
 * seconds to arrive, and a click in that window is a real DOM event with
 * no listener — React does not replay it once hydration finishes.  The
 * control looks live and silently does nothing.  The /arbitrage tool tabs
 * and research disclosure held two V1 production specs red this way; PR
 * #1867 taught the specs to wait, this gate fixes it for people.
 *
 * The ds primitives that own a click-only control — Tabs,
 * SegmentedControl, CollapsiblePanel's disclosure — render it `disabled`
 * with `aria-busy="true"` until this is true, so the pre-hydration state
 * is honest (visibly not ready, see the gate rule in app/ds.css) instead
 * of dead.  Native links, <select>s and inputs work without JavaScript and
 * are deliberately NOT gated.
 *
 * useSyncExternalStore, not useState + useEffect:
 *   - during SSR and hydration React uses the SERVER snapshot (false), so
 *     the hydrated markup matches the server markup exactly — no mismatch;
 *   - immediately after hydrating React re-renders with the CLIENT
 *     snapshot (true);
 *   - a component mounted by an ordinary client render (a soft
 *     navigation, a lazily shown panel, a Testing Library `render`) never
 *     sees false at all, so nothing already interactive flickers busy.
 * The store never changes, so the subscription is a no-op.
 */
"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

export function useHydrated() {
  return useSyncExternalStore(subscribe, clientSnapshot, serverSnapshot);
}
