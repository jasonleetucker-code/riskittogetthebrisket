/**
 * FailureState must never point at an absent reason (Rankings banner,
 * production 2026-10-05: "declining this request for the reason above" with
 * nothing above it).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { classifyContractFailure } from "@/lib/contract-failure";
import { FailureState } from "@/components/ds/FailureState";

function renderedText(failure) {
  const { container, unmount } = render(
    <FailureState failure={failure} context="rankings" onRetry={() => {}} />,
  );
  const text = container.textContent;
  unmount();
  return text;
}

describe("FailureState never points at an absent reason", () => {
  for (const body of [
    { error: "No data available yet. First scrape may still be running." },
    { error: "contract_build_failed" },
    { error: "brand_new_refusal" },
    { error: "data_not_ready", message: "Scoring not proven." },
  ]) {
    it(`503 ${JSON.stringify(body)}`, () => {
      const text = renderedText(classifyContractFailure(503, body));
      expect(text).not.toMatch(/reason above/i);
      expect(text).toMatch(/Serving degraded — rankings/);
      // A real sentence explains it.
      expect(text.length).toBeGreaterThan("Serving degraded — rankings".length + 20);
    });
  }

  it("shows the code next to the explanation, not instead of it", () => {
    render(<FailureState failure={classifyContractFailure(503, { error: "contract_build_failed" })} />);
    expect(screen.getByTestId("failure-code")).toHaveTextContent("(contract_build_failed)");
    expect(screen.getByRole("alert")).toHaveTextContent(/latest rankings build failed/);
  });
});
