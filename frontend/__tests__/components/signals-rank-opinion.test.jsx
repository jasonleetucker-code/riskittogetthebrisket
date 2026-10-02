/**
 * Signals Fantasy — rank-only, NON-VOTING second opinion (#1555, Unit A).
 *
 * Payloads here are LABELLED SYNTHETIC (no real Signals rows). Pinned:
 *   - the POSITIONAL_RANK_ONLY basis is compatible with nothing (never
 *     summed, never mixed with canonical or vendor-native values);
 *   - an opinion never carries a value and never votes;
 *   - picks are out of scope by the boards' DECLARED population;
 *   - "not collected" (our gap) and "not ranked / unresolved" (vendor
 *     silence or quarantined identity) are distinct, never a rank;
 *   - the component renders positional rank + tier only and never enters
 *     the Second Opinions tally.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, waitFor } from "@testing-library/react";

import SignalsRankOpinion, {
  _resetSignalsCache,
} from "@/components/trade/SignalsRankOpinion";
import {
  ASSET_COVERAGE,
  VALUE_BASIS,
  basesAreCompatible,
  rankOnlyOpinionFor,
  rankOnlyProviderState,
  summariseSide,
} from "@/lib/second-opinions";

const SYNTHETIC_PAYLOAD = {
  status: "ok",
  votes: false,
  basis: "POSITIONAL_RANK_ONLY",
  boards: {
    dynasty: { status: "ok", release: { publishedAt: "2026-10-01T01:31:48.554Z" } },
    "idp-dynasty": { status: "ok", release: {} },
  },
  signalsPositionalRank: {
    "pid:100": { board: "dynasty", position: "QB", positionalRank: 3, tier: "S" },
    "name:Synthetic Name Only": {
      board: "idp-dynasty",
      position: "DT",
      positionalRank: 7,
      tier: "A",
    },
  },
};

const qb = { name: "Synthetic Alpha", playerId: "100", assetClass: "offense" };
const dt = { name: "Synthetic Name Only", playerId: null, assetClass: "idp" };
const unranked = { name: "Synthetic Ghost", playerId: "999", assetClass: "offense" };
const pick = { name: "2027 Round 1", playerId: null, assetClass: "pick" };

describe("rank-only basis", () => {
  it("is compatible with nothing, including itself", () => {
    const b = VALUE_BASIS.POSITIONAL_RANK_ONLY;
    for (const other of Object.values(VALUE_BASIS)) {
      expect(basesAreCompatible(b, other)).toBe(false);
      expect(basesAreCompatible(other, b)).toBe(false);
    }
  });

  it("never yields a summable value", () => {
    const op = rankOnlyOpinionFor(qb, SYNTHETIC_PAYLOAD);
    expect(op.status).toBe(ASSET_COVERAGE.NATIVE);
    expect(op.value).toBeNull();
    expect(op.votes).toBe(false);
    expect(op.entry.positionalRank).toBe(3);
    const side = summariseSide([op]);
    expect(side.values).toEqual([]);
    expect(side.incomplete).toBe(true);
  });
});

describe("rankOnlyOpinionFor states", () => {
  it("joins by playerId first, then by display name", () => {
    expect(rankOnlyOpinionFor(dt, SYNTHETIC_PAYLOAD).entry.position).toBe("DT");
  });

  it("treats picks as out of scope by declared population", () => {
    expect(rankOnlyOpinionFor(pick, SYNTHETIC_PAYLOAD).status).toBe(
      ASSET_COVERAGE.OUT_OF_SCOPE,
    );
  });

  it("keeps not-collected distinct from not-ranked", () => {
    const ranked = rankOnlyOpinionFor(unranked, SYNTHETIC_PAYLOAD);
    expect(ranked.status).toBe(ASSET_COVERAGE.NOT_PUBLISHED);
    expect(ranked.detail).toBe("not_ranked_or_unresolved");
    const empty = {
      status: "partial",
      boards: { dynasty: { status: "not_collected" } },
      signalsPositionalRank: {},
    };
    expect(rankOnlyOpinionFor(unranked, empty).detail).toBe("not_collected");
    expect(rankOnlyOpinionFor(null, SYNTHETIC_PAYLOAD).status).toBe(
      ASSET_COVERAGE.UNRESOLVED,
    );
  });

  it("maps unknown payloads to unavailable, never ok", () => {
    expect(rankOnlyProviderState(null)).toBe("unavailable");
    expect(rankOnlyProviderState({ error: "auth_required" })).toBe("unavailable");
    expect(rankOnlyProviderState({ status: "not_collected" })).toBe("not_collected");
  });
});

describe("SignalsRankOpinion", () => {
  afterEach(() => {
    _resetSignalsCache();
    vi.unstubAllGlobals();
  });

  const sides = [
    { label: "A", assets: [qb, pick] },
    { label: "B", assets: [unranked] },
  ];

  it("renders positional rank + tier only, labelled not counted", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => SYNTHETIC_PAYLOAD })),
    );
    const { findByTestId } = render(<SignalsRankOpinion sides={sides} />);
    const el = await findByTestId("signals-rank-opinion");
    const text = el.textContent;
    expect(text).toContain("positional rank only · not counted");
    expect(text).toContain("QB3 · S");
    expect(text).toContain("not ranked by Signals"); // the pick
    expect(text).toContain("not ranked / unresolved");
    // No side totals, winners or values.
    expect(text).not.toMatch(/Winner|wins|value|total/i);
  });

  it("shows an explicit not-collected state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ status: "not_collected", boards: {}, signalsPositionalRank: {} }),
      })),
    );
    const { findByTestId } = render(<SignalsRankOpinion sides={sides} />);
    expect((await findByTestId("signals-not-collected")).textContent).toContain(
      "not collected",
    );
  });

  it("vanishes when the endpoint is unreachable", async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<SignalsRankOpinion sides={sides} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="signals-rank-opinion"]')).toBeNull();
  });
});
