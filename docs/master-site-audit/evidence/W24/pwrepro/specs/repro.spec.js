const { test, expect } = require("@playwright/test");
test.describe("Chart visual regression (repro of describe-body skip)", () => {
  test.skip(!!process.env.SKIP_VISUAL_REGRESSION, "Set SKIP_VISUAL_REGRESSION=1 to skip this suite locally");
  test("structural assertion (NOT a screenshot)", async () => { expect(1).toBe(1); });
  test("pixel assertion", async () => { expect(2).toBe(2); });
});
