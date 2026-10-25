const page = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chase Upside</title>
    <style>
      :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
      html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
      body { display: grid; min-height: 100vh; margin: 0; place-items: center; }
      main { max-width: 36rem; padding: 2rem; text-align: center; }
      button { cursor: pointer; font: inherit; padding: .7rem 1rem; }
    </style>
  </head>
  <body>
    <main>
      <h1>Chase Upside</h1>
      <p>Private, read-only fantasy football analysis for ChatGPT.</p>
      <p>Connect the Chase Upside plugin in ChatGPT to query rankings, league context, rosters, and trade decisions.</p>
    </main>
    <script>
    </script>
  </body>
</html>`;

export default {
  async fetch(request, env, ctx) {
    void ctx;

    const pathname = new URL(request.url).pathname;
    if (pathname === "/mcp") return handleMcp(request, env);
    if (pathname !== "/") {
      return new Response("Not found", { status: 404 });
    }

    return new Response(page, {
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  },
};

async function handleMcp(request, env) {
  if (request.method !== "POST") return jsonError(405, "method_not_allowed");

  const userId = request.headers.get("oai-authenticated-user-id") ?? "";
  const expectedUserId = env.CHASE_UPSIDE_CHATGPT_OWNER_USER_ID ?? "";
  if (!userId || !expectedUserId || userId !== expectedUserId) {
    return jsonError(403, "owner_access_required");
  }

  const backend = env.CHASE_UPSIDE_BACKEND_URL ?? "";
  const token = env.CHASE_UPSIDE_MCP_API_TOKEN ?? "";
  if (!backend || !token) return jsonError(503, "plugin_not_configured");

  const body = await request.arrayBuffer();
  if (body.byteLength > 64 * 1024) return jsonError(413, "request_too_large");

  let target;
  try {
    target = new URL("/api/chase-upside/mcp", backend);
  } catch {
    return jsonError(503, "plugin_not_configured");
  }
  if (target.protocol !== "https:") return jsonError(503, "https_backend_required");

  try {
    const response = await fetch(target, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Chase-Upside-Owner-Id": userId,
      },
      body,
      redirect: "error",
      signal: AbortSignal.timeout(20_000),
    });
    const responseBody = await response.arrayBuffer();
    if (responseBody.byteLength > 2 * 1024 * 1024) {
      return jsonError(502, "backend_response_too_large");
    }
    return new Response(responseBody, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return jsonError(502, "backend_unavailable");
  }
}

function jsonError(status, error) {
  return Response.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
}
