const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl } = require("../helpers/journey");

test("browser leagues fetch keeps one trace through Next and FastAPI", async ({ authedPage }) => {
  // A fresh document avoids the per-tab one-minute leagues cache populated
  // by the auth fixture's initial page.
  const page = await authedPage.context().newPage();
  try {
    const requestPromise = page.waitForRequest((request) =>
      new URL(request.url()).pathname === "/api/leagues"
    );
    const responsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/leagues"
    );
    await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    const request = await requestPromise;
    const response = await responsePromise;
    const traceparent = request.headers()["traceparent"];
    expect(traceparent).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
    expect(response.status()).toBe(200);
    expect(response.headers()["x-trace-id"]).toBe(traceparent.split("-")[1]);
    expect(response.headers()["x-request-id"]).toBeTruthy();
  } finally {
    await page.close();
  }
});
