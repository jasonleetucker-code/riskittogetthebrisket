// Insider Trading sell/buy modes.
//
// Pins the three things the product rules make load-bearing:
//   1. The two modes are OPPOSITE sides of one observation set — the
//      request direction and the rendered column both flip.
//   2. The lead score is never presented as a probability of
//      acceptance, and the payload's limitations always render.
//   3. Both the buy and sell counts are always visible, so a net-style
//      single number can never hide one-sided or contradictory
//      evidence.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";

import InsiderLeads from "@/components/InsiderLeads";

function lead(overrides = {}) {
  return {
    ownerId: "u1",
    displayName: "Manager One",
    leadScore: 61.2,
    components: {
      demonstratedInterest: 0.28,
      partnerFit: 0.13,
      positionalNeed: 0.11,
      valueMatch: 0.06,
      activity: 0.03,
      contradictionPenalty: -0.04,
      lowSamplePenalty: 0.0,
    },
    reasons: ["Traded for him 2x elsewhere", "Biggest positional gap"],
    cautions: [],
    ownsAsset: false,
    partnerFitScore: 18.4,
    partnerConfidence: 0.42,
    interest: { buys: 2, sells: 1, uniqueLeagues: 2, lastTs: 1_800_000_000_000 },
    ...overrides,
  };
}

function payload(overrides = {}) {
  return {
    leagueKey: "dynasty_main",
    assetId: "P1",
    mode: "sell",
    window: "90d",
    ownerOfAsset: null,
    poolSize: 11,
    leadsWithObservedInterest: 1,
    leads: [lead()],
    limitations: {
      statement: "A lead score ranks who to approach — it is not a prediction that anyone accepts.",
      coverageCaveat: "Absence of observed interest is not evidence of disinterest.",
      isNotAProbability: true,
    },
    ...overrides,
  };
}

let bodies;

beforeEach(() => {
  bodies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, init) => {
      const body = JSON.parse(init.body);
      bodies.push(body);
      return {
        ok: true,
        status: 200,
        json: async () => payload({ mode: body.mode === "buy" ? "buy" : "sell" }),
      };
    }),
  );
});

async function mount(props = {}) {
  const utils = render(<InsiderLeads assetId="P1" leagueKey="dynasty_main" {...props} />);
  await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
  return utils;
}

describe("InsiderLeads", () => {
  it("defaults to sell mode and sends the asset and league explicitly", async () => {
    await mount();
    expect(bodies[0]).toMatchObject({ mode: "sell", assetId: "P1", leagueKey: "dynasty_main" });
  });

  it("falls back to a name when there is no asset id", async () => {
    render(<InsiderLeads assetName="Some Player" leagueKey="dynasty_main" />);
    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    expect(bodies[0].name).toBe("Some Player");
    expect(bodies[0].assetId).toBeUndefined();
  });

  it("switching to buy mode refetches from the opposite side", async () => {
    await mount();
    await act(async () => {
      fireEvent.click(screen.getByText("I'm buying"));
    });
    await waitFor(() => expect(bodies.length).toBe(2));
    expect(bodies[1].mode).toBe("buy");
  });

  it("flips the observed-activity column with the mode", async () => {
    await mount();
    expect(await screen.findByText("Bought elsewhere")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByText("I'm buying"));
    });
    expect(await screen.findByText("Sold elsewhere")).toBeTruthy();
  });

  it("shows both sides of the evidence, not just the mode's side", async () => {
    // 2 buys / 1 sell must both be legible — a bare "+1" would hide
    // that this manager has also moved him off a roster.
    await mount();
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText(/1 opp/)).toBeTruthy();
  });

  it("renders the limitations rather than burying them", async () => {
    await mount();
    expect(await screen.findByText(/not a prediction that anyone accepts/)).toBeTruthy();
    expect(screen.getByText(/not evidence of disinterest/)).toBeTruthy();
  });

  it("never labels the score as a probability", async () => {
    const { container } = await mount();
    await screen.findByText("Manager One");
    expect(container.textContent.toLowerCase()).not.toContain("probability of acceptance");
    expect(container.textContent.toLowerCase()).not.toContain("% chance");
  });

  it("expands to a per-component breakdown so any score can be audited", async () => {
    await mount();
    const row = await screen.findByText("Manager One");
    await act(async () => {
      fireEvent.click(row.closest("tr"));
    });
    expect(await screen.findByText("Traded for/away elsewhere")).toBeTruthy();
    expect(screen.getByText("Trade-partner fit")).toBeTruthy();
    expect(screen.getByText("Thin-evidence penalty")).toBeTruthy();
  });

  it("marks the current owner in buy mode", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u, init) => {
        bodies.push(JSON.parse(init.body));
        return {
          ok: true,
          status: 200,
          json: async () =>
            payload({ mode: "buy", ownerOfAsset: "u1", leads: [lead({ ownsAsset: true })] }),
        };
      }),
    );
    render(<InsiderLeads assetId="P1" leagueKey="dynasty_main" />);
    expect(await screen.findByText("OWNER")).toBeTruthy();
  });

  it("shows an em dash rather than a zero when partner fit could not be computed", async () => {
    // A missing roster snapshot must abstain, not render as "0.0 fit",
    // which reads as a measured bad fit.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u, init) => {
        bodies.push(JSON.parse(init.body));
        return {
          ok: true,
          status: 200,
          json: async () =>
            payload({ leads: [lead({ partnerFitScore: null, interest: null })] }),
        };
      }),
    );
    const { container } = render(<InsiderLeads assetId="P1" leagueKey="dynasty_main" />);
    await screen.findByText("Manager One");
    const cells = container.querySelectorAll("tbody tr td");
    const dashes = Array.from(cells).filter((c) => c.textContent.trim() === "—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });

  it("degrades to a message instead of throwing when the endpoint fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({ error: "data_not_ready", message: "No snapshot yet." }),
      })),
    );
    render(<InsiderLeads assetId="P1" leagueKey="dynasty_main" />);
    expect(await screen.findByText(/No snapshot yet\./)).toBeTruthy();
  });

  it("states the pool size and how much of it has observed activity", async () => {
    await mount();
    expect(await screen.findByText(/11 league-mates ranked/)).toBeTruthy();
    expect(screen.getByText(/1 with observed cross-league activity/)).toBeTruthy();
  });
});
