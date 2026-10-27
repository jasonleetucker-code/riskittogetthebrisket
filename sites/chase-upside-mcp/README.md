# Chase Upside ChatGPT MCP host

This private ChatGPT Site is the Plus-compatible MCP host. Sites authenticates MCP requests, applies the Site access policy, and supplies the `oai-authenticated-user-id` request header. The `/mcp` route treats that header as a platform assertion, matches it to the Site-scoped owner ID kept in server-only settings, and forwards only the MCP protocol headers needed by the existing FastAPI endpoint. It does not contain rankings or trade logic.

## Runtime settings

- `CHASE_UPSIDE_BACKEND_URL`: `https://chaseupside.com` only; the Worker rejects other hosts, credentials, paths, queries, and fragments so it cannot forward the backend token to an arbitrary HTTPS destination.
- `CHASE_UPSIDE_MCP_API_TOKEN`: backend service token; configure as a Site secret only, never commit or expose it to the browser.
- `CHASE_UPSIDE_CHATGPT_OWNER_USER_ID`: the owner ID returned by the newly created Site's access policy.

The API must receive the same token as `CHASE_UPSIDE_MCP_API_TOKEN` and the same owner ID as `CHASE_UPSIDE_MCP_OWNER_USER_ID`. Keep the Site owner-only: the owner comparison in the Worker is defense in depth, while the Sites access policy is the authenticated ingress boundary. Do not publish or deploy this Site until the source PR has review approval and required checks pass.
