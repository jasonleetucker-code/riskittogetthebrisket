/**
 * Field spec — label/hint/error wiring. The invalid state must keep the
 * hint on screen (guidance matters most while fixing input) and
 * aria-describedby must reference only rendered ids, error first.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { Field, Input } from "@/components/ds";

describe("Field", () => {
  it("wires the label to the control", () => {
    render(
      <Field label="Team name">
        <Input />
      </Field>
    );
    expect(screen.getByLabelText("Team name")).toBeInTheDocument();
  });

  it("hint-only: hint is rendered and referenced", () => {
    render(
      <Field label="Bid" hint="Whole dollars">
        <Input />
      </Field>
    );
    const input = screen.getByLabelText("Bid");
    const hint = screen.getByText("Whole dollars");
    expect(input).toHaveAttribute("aria-describedby", hint.id);
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("renders BOTH error and hint when both exist, error first", () => {
    render(
      <Field label="Bid" hint="Whole dollars" error="Must be a number">
        <Input />
      </Field>
    );
    const error = screen.getByText("Must be a number");
    const hint = screen.getByText("Whole dollars");
    expect(error).toBeInTheDocument();
    expect(hint).toBeInTheDocument();
    // visual order: error immediately above the hint
    expect(
      error.compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("aria-describedby references only rendered ids, error-then-hint", () => {
    render(
      <Field label="Bid" hint="Whole dollars" error="Must be a number">
        <Input />
      </Field>
    );
    const input = screen.getByLabelText("Bid");
    const described = input.getAttribute("aria-describedby").split(" ");
    expect(described).toHaveLength(2);
    const [errorId, hintId] = described;
    expect(document.getElementById(errorId)).toHaveTextContent(
      "Must be a number"
    );
    expect(document.getElementById(hintId)).toHaveTextContent("Whole dollars");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("error-only: no dangling hint reference", () => {
    render(
      <Field label="Bid" error="Required">
        <Input />
      </Field>
    );
    const input = screen.getByLabelText("Bid");
    const described = input.getAttribute("aria-describedby").split(" ");
    expect(described).toHaveLength(1);
    expect(document.getElementById(described[0])).toHaveTextContent("Required");
  });
});
