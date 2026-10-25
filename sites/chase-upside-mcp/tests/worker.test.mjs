import assert from "node:assert/strict";
import test from "node:test";

import worker from "../worker/index.js";

test("MCP proxy refuses callers that do not match the Site owner", async () => {
  let called = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    called = true;
    throw new Error("must not call backend");
  };
  try {
    const response = await worker.fetch(
      new Request("https://site.test/mcp", { method: "POST", body: "{}" }),
      { CHASE_UPSIDE_CHATGPT_OWNER_USER_ID: "owner-1" },
      {},
    );
    assert.equal(response.status, 403);
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("MCP proxy forwards only to configured HTTPS backend with the service token", async () => {
  const originalFetch = globalThis.fetch;
  let observed;
  globalThis.fetch = async (url, init) => {
    observed = { url: String(url), init };
    return Response.json({ jsonrpc: "2.0", id: 1, result: { tools: [] } });
  };
  try {
    const response = await worker.fetch(
      new Request("https://site.test/mcp", {
        method: "POST",
        headers: { "oai-authenticated-user-id": "owner-1" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      }),
      {
        CHASE_UPSIDE_CHATGPT_OWNER_USER_ID: "owner-1",
        CHASE_UPSIDE_BACKEND_URL: "https://chaseupside.com",
        CHASE_UPSIDE_MCP_API_TOKEN: "secret-test-token",
      },
      {},
    );
    assert.equal(response.status, 200);
    assert.equal(observed.url, "https://chaseupside.com/api/chase-upside/mcp");
    assert.equal(observed.init.headers.Authorization, "Bearer secret-test-token");
    assert.equal(observed.init.headers["X-Chase-Upside-Owner-Id"], "owner-1");
    assert.deepEqual(await response.json(), { jsonrpc: "2.0", id: 1, result: { tools: [] } });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("MCP proxy rejects HTTP backend configuration", async () => {
  const response = await worker.fetch(
    new Request("https://site.test/mcp", {
      method: "POST",
      headers: { "oai-authenticated-user-id": "owner-1" },
      body: "{}",
    }),
    {
      CHASE_UPSIDE_CHATGPT_OWNER_USER_ID: "owner-1",
      CHASE_UPSIDE_BACKEND_URL: "http://chaseupside.com",
      CHASE_UPSIDE_MCP_API_TOKEN: "secret-test-token",
    },
    {},
  );
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "https_backend_required" });
});
