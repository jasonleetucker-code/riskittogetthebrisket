// jsdom setup for the "components" vitest project only.
// Adds jest-dom matchers and tears down the DOM between tests so
// renders can't leak into one another.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
