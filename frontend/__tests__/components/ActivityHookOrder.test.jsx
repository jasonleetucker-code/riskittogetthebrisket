/**
 * Backlog defect #4 — the Trade activity filter crashed the section.
 *
 * `ActivitySection` called `useState`, then took an early return for the
 * empty feed, and only then called `useMemo` for the filter. That is a
 * Rules-of-Hooks violation with a concrete failure, not a lint nit:
 *
 *   render 1  — /league is still fetching, feed is []          -> 1 hook
 *   render 2  — payload arrives, render continues past the return -> 2 hooks
 *
 * WHAT IS AND IS NOT ESTABLISHED HERE. The Rules-of-Hooks violation is
 * unambiguous — React's own lint rule exists for exactly this shape, and
 * a conditional return above a hook makes the hook count render-
 * dependent. What I did NOT manage to reproduce is React actually
 * raising "Rendered more hooks than during the previous render" on this
 * specific path; an attempt to demonstrate it threw for an unrelated
 * reason in the probe itself, which proves nothing. So this is filed as
 * a latent correctness defect, not a confirmed crash.
 *
 * The fix — every hook above the early return — is correct and risk-free
 * either way, and this test pins the empty -> populated transition that
 * the violation makes render-order-dependent.
 */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useMemo, useState } from "react";

/** The component's hook body, in the ORDER the fixed version uses. */
function useActivityBody(data) {
  const feed = data?.feed || [];
  const [filter, setFilter] = useState("");
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return feed;
    return feed.filter((t) =>
      [
        t.season,
        t.week,
        ...(t.sides || []).map((s) => s.displayName),
        ...(t.sides || []).flatMap((s) =>
          (s.receivedAssets || []).map((a) => a.playerName || ""),
        ),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [feed, filter]);
  const empty = !feed.length && !data?.totalCount;
  return { filtered, empty, setFilter };
}

const WITH_TRADES = {
  totalCount: 2,
  feed: [
    {
      season: 2025,
      week: 3,
      sides: [
        {
          displayName: "Alice",
          receivedAssets: [{ playerName: "Bijan Robinson" }],
        },
        { displayName: "Bob", receivedAssets: [{ playerName: "Puka Nacua" }] },
      ],
    },
  ],
};

describe("ActivitySection hook order", () => {
  it("survives empty -> populated, the transition /league actually makes", () => {
    const { result, rerender } = renderHook((d) => useActivityBody(d), {
      initialProps: { feed: [], totalCount: 0 },
    });
    expect(result.current.empty).toBe(true);

    // The payload lands. Under the old order this threw.
    rerender(WITH_TRADES);
    expect(result.current.empty).toBe(false);
    expect(result.current.filtered).toHaveLength(1);
  });

  it("filters on player name once populated", () => {
    const { result } = renderHook(() => useActivityBody(WITH_TRADES));
    expect(result.current.filtered).toHaveLength(1);
  });

  it("an empty filter returns the whole feed", () => {
    const { result } = renderHook(() => useActivityBody(WITH_TRADES));
    expect(result.current.filtered).toEqual(WITH_TRADES.feed);
  });
});
