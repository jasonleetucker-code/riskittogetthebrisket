/**
 * FailureState's machine-readable code note must keep its text's contrast.
 *
 * It used to render at `opacity: 0.7`. On the PSI canvas that took the
 * EmptyState description's --text-tertiary (#6b6151, 5.13:1 on #f2ebdd)
 * down to an effective #948a7b — 2.86:1, a WCAG 1.4.3 failure measured by
 * axe on /admin/model-lab's 403 state (2026-10-08). The note is already
 * smaller (0.85em) and parenthesised; size and placement carry the
 * de-emphasis, not a contrast cut.
 */
import { afterEach, describe, expect, it } from "vitest";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { FailureState } from "@/components/ds/FailureState";

afterEach(cleanup);

const failure = { kind: "forbidden", code: "admin_required", message: "Allowlisted users only." };

describe("FailureState code note contrast", () => {
  it.each(["block", "banner"])("%s variant: no opacity on the code note", (variant) => {
    render(<FailureState failure={failure} variant={variant} context="Model Lab" />);
    const note = screen.getByTestId("failure-code");
    expect(note).toHaveTextContent("(admin_required)");
    expect(note.style.opacity).toBe("");
  });
});
