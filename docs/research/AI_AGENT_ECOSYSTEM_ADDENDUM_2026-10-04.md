# AI agent ecosystem research addendum — eight owner sources

**Linked record:** [AI agent ecosystem reconciliation on research PR #1629](https://github.com/jasonleetucker-code/riskittogetthebrisket/blob/chatgpt/ai-agent-ecosystem-reconciliation-2026-10-03/docs/research/AI_AGENT_ECOSYSTEM_RECONCILIATION_2026-10-03.md).
**Campaign owner:** [AI agent ecosystem implementation campaign](../engineering/AI_AGENT_ECOSYSTEM_CAMPAIGN_2026-10-03.md).
**Status:** research reconciliation; no new product, spend, model, source, merge, or deployment authority.

## Evidence boundary

On 2026-10-04, direct X page retrieval returned 403. The eight status IDs did return
post and article payloads through the public third-party FxTwitter syndication API.
That is **mirrored primary-authored content**, not a direct X read or independent
verification of its claims. Source 1 also has an independent [newsletter
quotation](https://www.dataengineeringweekly.com/p/data-engineering-weekly-281).
Links to first-party vendor documentation and repositories below establish that
an interface or feature is documented; they do not establish the posts' claimed
speed, price, adoption, accuracy, or production safety. No model or service was
called with Calculator data.

In the matrix, “current” means draft campaign work, not merged or production
verified. “Already” means the existing repository owner or mechanism was traced;
it does not imply that every proposed measurement is implemented.

| Source | Idea | Evidence | Existing Calculator owner | Already implemented? | Currently being implemented? | Missing delta | Operational cost | Security risk | Recommended disposition |
|---|---|---|---|---|---|---|---|---|---|
| [1. @beamnxw](https://x.com/beamnxw/status/2081022966645535079) | Harness / loop / graph diagnosis | Mirrored article and [independent newsletter quote](https://www.dataengineeringweekly.com/p/data-engineering-weekly-281); **inferred from mirror**, no measured gain | Agent OS; Steward routing/evals | Authority, loop and graph rules | Steward spans and eval bridge | Optional evidenced failure layer | Small schema/analysis cost | False attribution if mandatory | `IMPLEMENT_DELTA`; preserve UNKNOWN and existing categories |
| [2. @polydao](https://x.com/polydao/status/2104783226833186920) | Jev typed decisions; cheaper agent loop | Mirrored article; [first-party SDK](https://github.com/typesafe-ai/typesafe-sdk-python) confirms typed questions. “90%”, 193.6× and 444.6× are **unverified marketing** | Steward router/evals | Deterministic advisory route | Scorecards | Typed shadow port, held-out corpus | Adapter/calibration; hosted calls may spend | Private state to provider | `SHADOW_EVALUATE`; no hosted call or permission decision |
| [3. @beamnxw](https://x.com/beamnxw/status/2105370052786565450) | Persistent Dots coordinator | Mirrored article; [first-party OpenAI help](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot) confirms Dot/cloud computer. Business outcomes unverified | Steward, work claims, scheduled workflows | Repo continuity and authority | Receipt/eval loop | None for current campaign | Always-on service/connectors | Cross-app access | `ALREADY_STRONGER`; optional external coordinator `RESEARCH_ONLY` |
| [4. @0xmortyx](https://x.com/0xmortyx/status/2104566676222021954) | Persistent agent plus large swarm | Mirrored article; [Kimi docs](https://www.kimi.com/en/help/agent/agent-swarm) confirm feature. Scale/speed are **vendor claims**; two modes not automatically joined | Steward controller and Class-B plan | Claims and coordination | Class-B isolation planned | Enforced sandbox, then bounded fan-out/fan-in | Parallel compute/review | Shared workspace, secret/network escape | `CURRENT_CAMPAIGN_COVERS`; fan-out later `SHADOW_EVALUATE` |
| [5. @sairahul1](https://x.com/sairahul1/status/2105956783563120784) | Viktor business automation | Mirrored sponsored article; 3,200+ tools and 50,000+ workspaces **unsupported here** | Scheduled jobs, Steward, domain owners | Permissioned recurring work | No business-app integration | None | New service/connectors/spend | Broad business data access | `REJECT` direct dependency |
| [6. @asteri_eth](https://x.com/asteri_eth/status/2104901781725598103) | Local typed decision models | Mirrored article; [candidate repo](https://github.com/intikhab49/open-jev-typed-decision-engine) documents a 150M encoder and benchmark. Its speed/calibration and “shippable policy” conclusion are **author claims**, unreproduced on Calculator | Steward routing/evals | Baseline rules | Scorecards | Held-out local benchmark | Hardware, weights and maintenance | Untrusted weights/code, state leakage | `RESEARCH_ONLY` until baseline comparison |
| [7. @undefinedki](https://x.com/undefinedki/status/2104569496564367837) | Context/loop/decision/harness/eval layers | Mirrored conceptual tutorial with Viktor sponsorship; “five levels” **author framing** | Agent OS, Steward, agent-evals | Receipt/source mapping | Eval bridge | Trace behavior and real-failure cases | Corpus maintenance | Self-report mistaken for proof | `IMPLEMENT_DELTA`; reject sponsored shortcut |
| [8. @aisystems_hq](https://x.com/aisystems_hq/status/2100197575911502074) | Claude business workflows with approval | Mirrored article; 36% admin-time and ROI **unverified for Calculator** | Repo autonomy policy and domain owners | Deterministic authority gates | None for this use case | None | Connector maintenance/spend | Customer/financial data, unreviewed actions | `ALREADY_STRONGER` for gates; `REJECT` direct adoption |

## Tested conclusions and implementation order

1. **Useful now:** failure-layer vocabulary, measured context/tool coverage, and
   behavioral trace evaluations. Add these to existing Steward receipts,
   `agent-evals` and routing scorecards; do not start another telemetry database.
   Unknown observations remain null/unknown. The current receipt bridge verifies
   mapping to stored evidence, not the truth of every observation.
2. **Useful after a baseline:** a typed decision advisor is a possible shadow
   challenger for low-authority engineering questions. The deterministic router
   and an uncomplicated classifier are baselines. Questions should each address
   one decision and permit abstention. Any probability requires held-out,
   decision-family calibration. A probabilistic answer cannot grant capabilities,
   spend, merge/deploy, source activation, product methodology or trade actions.
3. **Later:** bounded fan-out needs the existing Class-B isolation and capability
   executor first. Start with read-only, separately scoped work and deterministic
   fan-in. Vendor swarm scale is not a target or a reason to share a worktree.
4. **Rejected:** new generic orchestrator, mandatory Jev/Kimi/Dots/Viktor
   dependency, model weights in CI, global tool-count threshold, universal
   confidence threshold, and any social-post benchmark as repository proof.

## Immediate implementation mapping

| Campaign unit | Addendum delta | Acceptance evidence |
|---|---|---|
| Steward routing scorecards | Group only like task class/profile/model/reasoning, count evaluated acceptance only with artifact evidence, expose metric coverage and nulls; report challengers without promotion. | Unit tests for missing evidence/cost, mixed profiles, no auto-promotion; real saved receipt still reports unavailable model tokens/cost as null. |
| Steward execution diagnostics | Add optional harness/loop/graph attribution beside existing diagnosis; retain UNKNOWN when cause is not evidenced. Count context/tool data only when observable. | A claimed layer without cause evidence remains UNKNOWN; negative guard test. |
| Agent evals | Add behavioral trace cases and actual prior-failure fixtures; keep exact-head and source-receipt verification. | Sabotage of completion/current-head/authority assertions fails the relevant case. |
| Decision advisor research | An offline typed task-profile shadow port compares file-supplied answers to current deterministic `classify`; no provider is connected. | Held-out labeled decisions, per-family calibration, risk/coverage, latency, memory and cost remain missing; no active provider or authority change until evidence and normal review. |
| Class-B then fan-out | Prove workspace/path/network/credential caps before any write-capable worker. | Denied-action tests and independent fan-in on exact artifacts. |

## Open evidence gaps

- Direct X page and article rendering, replies and attached media were not read.
- No post's performance, price or adoption numbers were benchmarked on Calculator.
- Current PRs #1630–#1637 are drafts; local/CI evidence is not merge, deploy or
  production verification. Research PR #1629 still owns the linked core record.
- The active `main` head moved during this research through routine data refresh.
  Any integration must classify intervening diffs under the repository's
  main-movement policy before claiming exact-head freshness.
