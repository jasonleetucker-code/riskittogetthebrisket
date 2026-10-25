# Chase Upside ChatGPT MCP host

This private ChatGPT Site is the Plus-compatible MCP host. Its `/mcp` route checks the Site-authenticated owner ID and forwards JSON-RPC requests to the existing Chase Upside FastAPI service. It does not contain rankings or trade logic.

## Runtime settings

- `CHASE_UPSIDE_BACKEND_URL`: HTTPS origin of the Chase Upside API.
- `CHASE_UPSIDE_MCP_API_TOKEN`: backend service token; configure as a Site secret only, never commit or expose it to the browser.
- `CHASE_UPSIDE_CHATGPT_OWNER_USER_ID`: the owner ID returned by the newly created Site's access policy.

The API must receive the same token as `CHASE_UPSIDE_MCP_API_TOKEN` and the same owner ID as `CHASE_UPSIDE_MCP_OWNER_USER_ID`. Keep the Site owner-only. Do not publish or deploy this Site until the source PR has review approval and required checks pass.
