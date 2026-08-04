import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const page = fs.readFileSync(
  path.join(process.cwd(), "app/market/sharp-tracker/page.jsx"),
  "utf8",
);

describe("Sharp Tracker provisional FFPC labeling", () => {
  it("offers a real provisional source filter", () => {
    expect(page).toContain('<option value="provisional">Provisional FFPC only</option>');
  });

  it("does not present public FFPC activity as Sharp Score v2", () => {
    expect(page).toContain("Provisional public FFPC activity");
    expect(page).toContain("it is never presented as sharp-v2 qualification");
  });
});
