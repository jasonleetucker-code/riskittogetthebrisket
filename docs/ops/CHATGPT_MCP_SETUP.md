# Chase Upside ChatGPT MCP setup

The implementation adds a private ChatGPT Site MCP proxy and an authenticated FastAPI MCP endpoint. Both remain unusable until their runtime secrets are configured. Sites authenticates MCP requests and applies Site access policy before supplying `oai-authenticated-user-id`; the Worker compares that platform-provided ID with its server-only owner ID, then FastAPI independently checks the matching owner ID and a 32+ character service token. The MCP response set uses private cache scope and `no-store` HTTP headers.

## Post-review setup

1. After the source PR is reviewed and the backend change is approved for production, create or update the private ChatGPT Site from `sites/chase-upside-mcp/`. Do not publish it before the source review and required checks pass.
2. Read the new Site's access policy. Set its owner account ID as `CHASE_UPSIDE_CHATGPT_OWNER_USER_ID` in the Site runtime and as `CHASE_UPSIDE_MCP_OWNER_USER_ID` in the FastAPI service environment. These IDs are Site-scoped and must be read from the created Site; do not copy an ID from another Site.
3. Generate a unique 32-byte random token, then configure it as `CHASE_UPSIDE_MCP_API_TOKEN` in both the backend service environment and the Site runtime secret store. Do not put it in Git, a browser bundle, a ChatGPT conversation, or deployment logs. Restart the FastAPI process after changing its environment.
4. Set `CHASE_UPSIDE_BACKEND_URL` in the Site to `https://chaseupside.com`. The Worker rejects other hosts, non-origin URL parts, and non-HTTPS schemes before using the backend token. Keep the Site access policy restricted to the owner, and publish only after production approval. Site publication creates the private MCP app/plugin.
5. Verify `server/discover`, `tools/list`, and read-only calls for rankings, identity, league context, roster, and a sample trade against the deployed FastAPI response. Confirm that unauthenticated and non-owner requests fail, missing/stale data is labelled, and no write tools are registered.
6. In ChatGPT, open **Plugins → Personal → Created by you**, install/connect the Chase Upside plugin, then start a new conversation and select it with `@Chase Upside` or the composer plugin picker. Sites-hosted plugins are available on any ChatGPT plan; direct custom MCP server connections have separate plan requirements.

The `oai-authenticated-user-id` header is trustworthy only on the documented Sites request path, after the Sites access policy check. Do not expose the Worker as a public Site or bypass the Sites ingress with direct calls. The prepublication code review cannot verify the eventual Site's live access policy; verify it in the Site settings before publication and perform the owner/non-owner probe after publication.

This setup is intentionally a later step. The current development branch and PR do not deploy the Site, set production secrets, or publish/install the plugin.

## Tools (server version 1.1.0) and the owner each one reads

| Tool | Answers from | Missing / refusal states |
|---|---|---|
| `get_player_rankings` | the loaded canonical contract, ordered by `canonicalConsensusRank`; `limit` ≤ 100, `offset`, `nextOffset` | `rankings_not_ready`, `league_scoring_mismatch` (via `server._scoring_identity_error`), `unknown_league`, `inactive_league`; unranked rows are counted in `unrankedRowsExcluded`, never shown as ranked |
| `resolve_player_identity` | `src/identity/resolution.resolve_canonical_v2` | `unresolved` with `reason` + `candidates`; never a fuzzy guess |
| `get_league_context` | `league_registry` (`public_dict`, no Sleeper ids) + `scoring_evidence_state` | registry carries no updated-at stamp; stated as missing |
| `get_team_roster` | the contract's own `sleeper` block for the loaded league, else `merge_cross_league_sleeper_block` over a live overlay; freshness from `roster_freshness`; pick values from `pick_value_resolution.resolve_pick_asset_value` | unpriced players / picks are `value: null` + reason; `pickOwnership.state: unavailable` keeps `picks: null`; stale rosters are labelled; another league's rosters are never substituted (`league_roster_overlay_unavailable`) |
| `analyze_trade` | `trade_ledger.snapshot_for` + `validate_ledger` (canonical ids `p:<sleeperId>` / `pick:...`, ownership verified against one snapshot) + `analyze_service.analyze_trade_n` | the ledger's own reason codes (`asset_not_owned`, `unknown_asset`, …); 3+ teams stay behind `trade_multi_team_analysis`; nothing is recorded (`recorded: false`) |
| `get_value_history` | `src/history/asof` (`series` / `value_as_of`), `canonical_board` lane only, ≤ 400 points | `before_history_boundary`, `no_prior_observation`; gaps are never interpolated |

**Licensing boundary.** Responses are built from an allowlist of canonical
fields. No per-source value or rank (`canonicalSiteValues`, `rawSourceValues`,
`sourceNativeValues`, `sourceRanks`, `ktcMarket`, the `source_value` history
lane) leaves the endpoint; source NAMES and freshness states do. Pinned by
`tests/api/test_chase_upside_mcp_tools.py`.

**Argument validation.** The published `inputSchema` is the validator
(`_check`); a schema keyword the validator does not implement is refused at
import, so the advertised and enforced schemas cannot drift.

## Follow-on read-only tools — designed, not built

Each reuses one existing owner and must keep the licensing boundary above.

- **Source comparison** — blocked on licensing: it would expose per-source
  ranks/values. Needs an owner decision on which sources' published ranks may
  be shown to the owner through ChatGPT before any build.
- **Draft capital** — `server._fetch_draft_capital` / the canonical
  rookie-auction generation reader. Needs a server-side helper that does not
  require a request/session (coordinator hook; `server.py` is not edited here).
- **ROS projections / waiver analysis / FAAB** — `src/ros/api.py`,
  `src/trade/faab_engine.recommend` with its crowd + bid-history inputs. Each
  needs its route's input assembly factored out of `server.py` first so the
  MCP does not become a second assembler.
- **League market context / trade-decision explanation** — the explanation is
  already inside `analyze_trade` (`includeDetail: true` returns the full
  `analysis` + `simulation`); a separate tool is not needed yet.

## Release gates (none are satisfied by a code PR)

1. Exact-head required CI green (PR Validation L2) and independent review.
2. Owner approval to merge to `main` (that merge auto-deploys the backend
   route; the endpoint stays unusable until step 4).
3. Owner approval to create and publish the private ChatGPT Site, with the Site
   access policy verified owner-only and no direct/bypass ingress.
4. Owner-held secrets: `CHASE_UPSIDE_MCP_API_TOKEN` (backend + Site) and the
   Site-scoped owner ids, set by the owner; FastAPI restart.
5. Post-publication probes: unauthenticated and non-owner requests fail; each
   tool answers against production with labelled missing/stale states.
6. ChatGPT plugin install by the owner.
