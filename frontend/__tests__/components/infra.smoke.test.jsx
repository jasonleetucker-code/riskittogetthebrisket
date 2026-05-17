// Infra smoke test: proves the "components" project is wired —
// jsdom env + @vitejs/plugin-react JSX transform + Testing Library
// render/query + jest-dom matchers + afterEach cleanup. Real
// component coverage (PlayerPopup, rankings, trade) lands in the
// next PR on top of this.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

function Hello({ name }) {
  return <p>Hello {name}</p>;
}

describe("component-test infra", () => {
  it("renders a React component in jsdom and matches with jest-dom", () => {
    render(<Hello name="Brisket" />);
    expect(screen.getByText("Hello Brisket")).toBeInTheDocument();
  });
});
