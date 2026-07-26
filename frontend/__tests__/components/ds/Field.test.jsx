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

  it("merges a child's pre-existing aria-describedby with the hint id", () => {
    render(
      <>
        <Field label="Bio" hint="Max 200 characters">
          <Input aria-describedby="char-counter" />
        </Field>
        <span id="char-counter">42 / 200</span>
      </>
    );
    const input = screen.getByLabelText("Bio");
    const described = input.getAttribute("aria-describedby").split(" ");
    expect(described).toHaveLength(2);
    expect(described[0]).toBe("char-counter"); // child's ids kept, first
    expect(document.getElementById(described[1])).toHaveTextContent(
      "Max 200 characters"
    );
  });

  it("keeps the child's own aria-describedby when Field has no hint or error", () => {
    render(
      <Field label="Bio">
        <Input aria-describedby="char-counter" />
      </Field>
    );
    expect(screen.getByLabelText("Bio")).toHaveAttribute(
      "aria-describedby",
      "char-counter"
    );
  });

  it("appends error AND hint ids after the child's own, deduped", () => {
    render(
      <Field label="Bio" hint="Max 200 characters" error="Too long">
        <Input aria-describedby="char-counter extra-note" />
      </Field>
    );
    const input = screen.getByLabelText("Bio");
    const described = input.getAttribute("aria-describedby").split(" ");
    expect(described).toHaveLength(4);
    expect(described.slice(0, 2)).toEqual(["char-counter", "extra-note"]);
    expect(document.getElementById(described[2])).toHaveTextContent("Too long");
    expect(document.getElementById(described[3])).toHaveTextContent(
      "Max 200 characters"
    );
    expect(new Set(described).size).toBe(4);
  });

  it("preserves the child's own aria-invalid when Field has no error", () => {
    render(
      <Field label="Bio">
        <Input aria-invalid="true" />
      </Field>
    );
    expect(screen.getByLabelText("Bio")).toHaveAttribute(
      "aria-invalid",
      "true"
    );
  });

  it("a Field error forces aria-invalid true over the child's own value", () => {
    render(
      <Field label="Bio" error="Required">
        <Input aria-invalid={false} />
      </Field>
    );
    expect(screen.getByLabelText("Bio")).toHaveAttribute(
      "aria-invalid",
      "true"
    );
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
