# Chase Upside ChatGPT MCP setup

The implementation adds a private ChatGPT Site MCP proxy and an authenticated FastAPI MCP endpoint. Both remain unusable until their runtime secrets are configured. The Site must remain owner-only; its `/mcp` worker checks the Site-authenticated user ID before proxying, and FastAPI independently checks the matching owner ID and a 32+ character service token.

## Post-review setup

1. After the source PR is reviewed and the backend change is approved for production, create or update the private ChatGPT Site from `sites/chase-upside-mcp/`. Do not publish it before the source review and required checks pass.
2. Read the new Site's access policy. Set its owner account ID as `CHASE_UPSIDE_CHATGPT_OWNER_USER_ID` in the Site runtime and as `CHASE_UPSIDE_MCP_OWNER_USER_ID` in the FastAPI service environment. These IDs are Site-scoped and must be read from the created Site; do not copy an ID from another Site.
3. Generate a unique 32-byte random token, then configure it as `CHASE_UPSIDE_MCP_API_TOKEN` in both the backend service environment and the Site runtime secret store. Do not put it in Git, a browser bundle, a ChatGPT conversation, or deployment logs. Restart the FastAPI process after changing its environment.
4. Set `CHASE_UPSIDE_BACKEND_URL` in the Site to the existing HTTPS API origin, keep the Site access policy restricted to the owner, and publish only after production approval. Site publication creates the private MCP app/plugin.
5. Verify `server/discover`, `tools/list`, and read-only calls for rankings, identity, league context, roster, and a sample trade against the deployed FastAPI response. Confirm that unauthenticated and non-owner requests fail, missing/stale data is labelled, and no write tools are registered.
6. In ChatGPT, open **Plugins → Personal → Created by you**, install/connect the Chase Upside plugin, then start a new conversation and select it with `@Chase Upside` or the composer plugin picker. Sites-hosted plugins are available on any ChatGPT plan; direct custom MCP server connections have separate plan requirements.

This setup is intentionally a later step. The current development branch and PR do not deploy the Site, set production secrets, or publish/install the plugin.
