/**
 * /admin/model-lab — the Model Lab workspace (IC-6).
 *
 * States pinned here, each one distinct:
 *   list        every family from a REAL backend payload
 *   detail      champion vs challengers, evidence, served side, rollback text
 *   unobserved  rendered as its label + reason, never 0 / blank
 *   403         a signed-in non-admin sees the shared "not available" state,
 *               with no retry and no crash
 *   401 / empty / unknown family / refresh failure
 *   read-only   no promote / apply / rollback control; every request a GET
 *               of the Lab itself
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import payload from "../fixtures/model-lab-payload.json";

const mockSearchParams = { value: new URLSearchParams() };
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams.value,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/admin/model-lab",
}));

import ModelLabWorkspace from "@/components/model-lab/ModelLabWorkspace";

const clone = (x) => JSON.parse(JSON.stringify(x));

// The family view is a React.lazy chunk; under a loaded full-suite run its
// first resolve can outlast findBy's 1 s default.
const LAZY = { timeout: 8000 };

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

let fetchMock;

function serve(...responses) {
  const queue = [...responses];
  fetchMock = vi.fn(async () => {
    const next = queue.length > 1 ? queue.shift() : queue[0];
    if (next instanceof Error) throw next;
    return next;
  });
  vi.stubGlobal("fetch", fetchMock);
}

function at(search) {
  mockSearchParams.value = new URLSearchParams(search);
}

/** Every request the Lab made: a GET of /api/model-lab, nothing else. */
function expectOnlyLabGets() {
  expect(fetchMock).toHaveBeenCalled();
  for (const [url, init] of fetchMock.mock.calls) {
    expect(url).toBe("/api/model-lab");
    expect(String(init?.method || "GET").toUpperCase()).toBe("GET");
    expect(init?.body).toBeUndefined();
  }
}

const WRITE_CONTROL = /promote|apply|roll ?back|activate|retire|reject/i;

function expectNoWriteControls() {
  for (const btn of screen.queryAllByRole("button")) {
    expect(btn.textContent, `button "${btn.textContent}"`).not.toMatch(WRITE_CONTROL);
  }
  for (const link of screen.queryAllByRole("link")) {
    expect(link.getAttribute("href") || "").not.toMatch(/promote|apply|rollback/i);
  }
}

beforeEach(() => {
  at("");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("family list", () => {
  it("lists every family the backend reports, linking to its detail", async () => {
    serve(jsonResponse(200, clone(payload)));
    render(<ModelLabWorkspace />);
    const table = await screen.findByRole("table", { name: /model families/i });
    for (const fam of payload.families) {
      const link = within(table).getByRole("link", { name: fam.name });
      expect(link.getAttribute("href")).toBe(`/admin/model-lab?family=${fam.family}`);
    }
    // The decision reason is the backend's sentence, verbatim.
    expect(within(table).getByText(payload.families[0].decisionReason)).toBeInTheDocument();
    expect(screen.getByTestId("read-only-banner")).toHaveTextContent(/cannot promote, apply or roll back/i);
    expectOnlyLabGets();
    expectNoWriteControls();
  });

  it("renders unobserved fields as their label + reason, never 0 or blank", async () => {
    serve(jsonResponse(200, clone(payload)));
    render(<ModelLabWorkspace />);
    await screen.findByRole("table", { name: /model families/i });
    // receiptStore is unobserved on the fixture host.
    const blocks = screen.getAllByTestId("state-block");
    expect(blocks.length).toBeGreaterThan(0);
    for (const b of blocks) {
      expect(b.textContent).toMatch(/Unobserved|Not applicable|Unmeasured/);
      // a reason travels with every block
      expect(b.textContent.replace(/Unobserved|Not applicable|Unmeasured/, "").trim().length).toBeGreaterThan(0);
    }
    expect(
      screen.getAllByText(payload.receiptStore.reason).length,
    ).toBeGreaterThan(0);
    // Consensus Edge serves no champion: the backend's not_applicable reason shows.
    expect(screen.getAllByText(/no Consensus Edge model is served/i).length).toBeGreaterThan(0);
  });

  it("an empty families list is an honest empty state, not a failure", async () => {
    serve(jsonResponse(200, { ...clone(payload), families: [] }));
    render(<ModelLabWorkspace />);
    expect(await screen.findByText("No model families listed")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names families whose builder failed", async () => {
    serve(
      jsonResponse(200, {
        ...clone(payload),
        builderErrors: { bdvm_params: "ValueError: bad params" },
      }),
    );
    render(<ModelLabWorkspace />);
    expect(await screen.findByText(/could not be assembled/i)).toBeInTheDocument();
    expect(screen.getByText(/ValueError: bad params/)).toBeInTheDocument();
  });
});

describe("access", () => {
  it("a signed-in non-admin sees a clean 403 state, no retry, no crash", async () => {
    serve(jsonResponse(403, { error: "admin_required", message: "Allowlisted users only." }));
    render(<ModelLabWorkspace />);
    expect(await screen.findByText(/Not available to this account — Model Lab/)).toBeInTheDocument();
    expect(screen.getByText(/Allowlisted users only\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expectOnlyLabGets();
  });

  it("a signed-out caller sees the sign-in state", async () => {
    serve(jsonResponse(401, { error: "auth_required", message: "Sign-in required." }));
    render(<ModelLabWorkspace />);
    expect(await screen.findByText(/Sign-in required — Model Lab/)).toBeInTheDocument();
  });

  it("a dropped connection is not reported as a permissions problem", async () => {
    serve(new TypeError("Failed to fetch"));
    render(<ModelLabWorkspace />);
    expect(await screen.findByText(/Could not reach the server — Model Lab/)).toBeInTheDocument();
    expect(screen.queryByText(/Not available to this account/)).toBeNull();
  });
});

describe("family detail", () => {
  it("shows champion vs challengers, evidence windows, sample sizes, verdict and rollback", async () => {
    at("family=hill_scope_masters");
    serve(jsonResponse(200, clone(payload)));
    render(<ModelLabWorkspace />);
    const hill = payload.families.find((f) => f.family === "hill_scope_masters");

    expect(await screen.findByRole("heading", { name: hill.name }, LAZY)).toBeInTheDocument();
    // Why: the backend's decision reason, verbatim.
    expect(screen.getAllByText(hill.decisionReason).length).toBeGreaterThan(0);
    // Served now + how to roll back — the command is TEXT, not a control.
    expect(screen.getByText(hill.rollback.command)).toBeInTheDocument();
    expect(screen.getByTestId("read-only-note")).toBeInTheDocument();
    // Champion block: training / validation windows and sample sizes.
    expect(screen.getAllByText("Training window").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Validation windows").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Rows per holdout board").length).toBeGreaterThan(0);
    // Challenger table: 60 rows on the fixture, one page of 25 shown, newest first.
    const table = screen.getByRole("table", { name: /challenger versions/i });
    const bodyRows = within(table).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(25);
    expect(bodyRows[0].textContent).toContain(String(hill.challengers[hill.challengers.length - 1].version));
    expect(screen.getByText(/Showing/).textContent).toMatch(/Showing\s*25\s*of\s*60/);
    expectOnlyLabGets();
    expectNoWriteControls();
  });

  it("filters challengers by lab state and pages without new requests", async () => {
    at("family=hill_scope_masters");
    serve(jsonResponse(200, clone(payload)));
    const user = userEvent.setup();
    render(<ModelLabWorkspace />);
    const select = await screen.findByLabelText("Lab state", undefined, LAZY);
    const callsBefore = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: /show 25 more/i }));
    await user.click(screen.getByRole("button", { name: /show 10 more/i }));
    expect(screen.getByText(/Showing/).textContent).toMatch(/Showing\s*60\s*of\s*60/);

    await user.selectOptions(select, "REJECTED");
    const table = screen.getByRole("table", { name: /challenger versions/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(24);
    for (const r of rows) expect(r.textContent).toMatch(/Rejected/);

    await user.selectOptions(select, "SHADOW");
    expect(screen.getByText(/No challenger in the shadow state/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });

  it("lab-state counts show a real zero as 0", async () => {
    at("family=hill_scope_masters");
    serve(jsonResponse(200, clone(payload)));
    render(<ModelLabWorkspace />);
    await screen.findByRole("heading", { name: /Hill scope masters/ }, LAZY);
    const shadowItem = screen.getAllByText(/^shadow$/i, { exact: false })
      .map((n) => n.closest("li"))
      .find(Boolean);
    expect(shadowItem.textContent).toMatch(/^0\s*shadow$/i);
  });

  it("renders the #1708 shape: flags list, served note, unobserved champion and decision", async () => {
    at("family=sparse_evidence_estimator");
    const data = clone(payload);
    const sparse = data.families.find((f) => f.family === "sparse_evidence_estimator");
    const unread = "served side unobserved: the sparse_evidence_estimator flag could not be read (boom)";
    sparse.champion = { state: "unobserved", reason: unread };
    sparse.decisionReason = { state: "unobserved", reason: unread };
    sparse.productionState = {
      flag: "sparse_evidence_estimator",
      state: "unobserved",
      reason: "flag unreadable: RuntimeError: boom",
      servedPath: { state: "unobserved", reason: unread },
      servedNote: unread,
      flags: [
        { flag: "sparse_evidence_estimator", state: "unobserved", reason: "flag unreadable: RuntimeError: boom" },
        { flag: "joint_sparse_limited_evidence", enabled: false, gateStatus: "LIVE" },
      ],
    };
    serve(jsonResponse(200, data));
    render(<ModelLabWorkspace />);
    expect(await screen.findByRole("heading", { name: sparse.name }, LAZY)).toBeInTheDocument();
    // The unreadable flag's reason is shown; nothing claims it is OFF.
    expect(screen.getAllByText(unread).length).toBeGreaterThan(1);
    expect(screen.getAllByText("flag unreadable: RuntimeError: boom").length).toBeGreaterThan(0);
    // Every "Champion" fact that is unobserved renders the block, not "0" / "".
    const blocks = screen.getAllByTestId("state-block");
    expect(blocks.some((b) => b.textContent.includes(unread))).toBe(true);
  });

  it("an unknown family id is an honest not-found, with a way back", async () => {
    at("family=no_such_family");
    serve(jsonResponse(200, clone(payload)));
    render(<ModelLabWorkspace />);
    expect(await screen.findByText("No such model family", undefined, LAZY)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All model families" }).getAttribute("href")).toBe(
      "/admin/model-lab",
    );
  });
});

describe("refresh", () => {
  it("a failed refresh keeps the content and says so above it", async () => {
    serve(
      jsonResponse(200, clone(payload)),
      jsonResponse(503, { error: "model_lab_unavailable", detail: "timeout" }),
    );
    const user = userEvent.setup();
    render(<ModelLabWorkspace />);
    await screen.findByRole("table", { name: /model families/i });
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() =>
      expect(screen.getByText(/Model Lab refresh/)).toBeInTheDocument(),
    );
    // prior content survives
    expect(screen.getByRole("table", { name: /model families/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expectOnlyLabGets();
  });
});
