# Chase Upside — Sports Network reference experiences

**Isolated prototype. Owner design approval pending. No production rollout.**

Three connected, functional screens from one prospective design system:

| Experience | Local preview | Primary task |
|---|---|---|
| Football Market Board | [Rankings](http://127.0.0.1:3100/rankings) | Search, filter, sort, compare and export the demonstration board |
| NFL Personnel Dossier | [Player File](http://127.0.0.1:3100/players/demo-01) | Inspect identity, value history, peers, research and news |
| Football Newsroom | [News Desk](http://127.0.0.1:3100/news) | Read, filter and contextualize fictional NFL developments |

## Run and verify

Use **Node 20** (same engine contract as the repository). From this directory:

```powershell
npm ci
npm run build
npm start
```

The server binds only `127.0.0.1:3100`. For iterative work use `npm run dev` instead. Stop the previous server before starting another on the same port.

```powershell
npm test
npx playwright install chromium
npm run test:e2e
```

The browser suite expects the production preview to be running. Tests use local fixture content and never boot the Python backend. On the author's Node-24 host the equivalent commands used `npx --yes --package=node@20 node` followed by the appropriate Next, Vitest or Playwright entrypoint; runtime/build/test execution therefore used Node 20. Dependency installation used the host npm and reported its engine warning; the lockfile pins the separate preview dependencies.

## Review the actual renders

[Nine-screen comparison](output/playwright/review-contact-sheet.jpg) · [Initial comparison before refinement](output/playwright/initial-contact-sheet.jpg) · [Critique and design specification](REVIEW.md) · [Verification receipt](output/playwright/verification.json)

| Screen | Desktop 1440 | Tablet 768 | Mobile 390 |
|---|---|---|---|
| Rankings | [Viewport](output/playwright/rankings-1440-viewport.png) / [Full](output/playwright/rankings-1440.png) | [Viewport](output/playwright/rankings-768-viewport.png) / [Full](output/playwright/rankings-768.png) | [Viewport](output/playwright/rankings-390-viewport.png) / [Full](output/playwright/rankings-390.png) |
| Player File | [Viewport](output/playwright/player-1440-viewport.png) / [Full](output/playwright/player-1440.png) | [Viewport](output/playwright/player-768-viewport.png) / [Full](output/playwright/player-768.png) | [Viewport](output/playwright/player-390-viewport.png) / [Full](output/playwright/player-390.png) |
| News Desk | [Viewport](output/playwright/news-1440-viewport.png) / [Full](output/playwright/news-1440.png) | [Viewport](output/playwright/news-768-viewport.png) / [Full](output/playwright/news-768.png) | [Viewport](output/playwright/news-390-viewport.png) / [Full](output/playwright/news-390.png) |

## What works, and what is simulated

- **Functional fixture behavior:** player/team search; conjunctive filters; numeric sort in both directions; predetermined format boards; focused columns; filtered CSV; three-player comparison; comparison persistence within this browser session; cross-screen links and board-return state; mobile row details; time ranges and keyboard/pointer history inspection; analytical tabs; story reading; source detail; news filters, roster scope and player timelines; manual ticker navigation.
- **Simulated research:** all player identities, values, ranks, movement, projections, roster membership, scouting observations, confirmation classes and news. The demonstration clock is fixed at **2026-11-07 18:00 UTC**. No fixture claims current NFL truth. Format ranks, position ranks and histories are checked-in data, not a valuation model.
- **Unavailable dependency:** real roster fit, trade fairness, package analysis, live recommendations and live refresh. Trade buttons open an honest demonstration handoff. Unavailable fields remain unavailable; history gaps remain gaps.
- **Proposed production integration:** the mappings below are documentation only. This preview neither imports production providers nor requests production endpoints.

Use the **Demo state** selector for deliberately held Loading, Empty and Unavailable presentations and recovery. Stale demonstrates rows whose **source coverage** is November 1 while the sample board remains dated November 7. Missing links to absent projection/source coverage and a missing historical observation.

## Future integration contract map

| Production path inspected | Preserve on later approved migration |
|---|---|
| Rankings → `useDynastyData` → `fetchDynastyData` → `/api/dynasty-data` / canonical data contract | Server-stamped values, source semantics, exact league context, overrides, exports, existing lenses/screens, offense and IDP |
| Player File → shared PlayerPopup research/ownership/value-chain sections and history/explanation endpoints | Canonical identity, ownership, real source coverage, history, explanations, realized production and league-specific research |
| News → shared `useNews` → news-service → `/api/news` → `server.py::get_news` → NewsService aggregation | Single-flighted fetching, roster relevance, ambiguity-safe player joins, digests, attribution, provider status and explicit unavailable behavior |
| Production navigation and public-route registry | Current route reachability, auth, private/public semantics, flags, specialist/hidden routes and share URLs |

In production, nginx sends `/api/*` to FastAPI; the existing Next news proxy is a local-development bridge. This prototype adds neither kind of API bridge. Its three similar route names belong to a **different local application** and do not replace deployed routes.

## Boundaries and provenance

- Original `chase_upside_sports_network.html` was not supplied or found. This is an interpretation of the documented owner motifs, not a claimed reproduction of a viewed reference.
- Owner authorization: approved implementation plan in chat; matching direction is proposed in **open PR #2112**. Its owner charter is unmerged at the implementation baseline. Intake and UI-ledger review pointers avoid importing or editing that branch. Integration should carry this review link into that charter when reconciling #2112.
- Barlow Condensed and IBM Plex Sans are locally subsetted OFL fonts; licenses and source/hash provenance are in `public/fonts/` and `public/asset-provenance.json`. Next's local-font loader preloads them without contacting a font CDN.
- The original generated editorial image represents a fictional athlete. It is illustrative and reused across dossiers, not a portrait of any listed player. No remote media are loaded.
- Security/quality engineering applicability: deterministic fixtures, provenance, reproducible assets, E2E, accessibility and request isolation **APPLY_NOW**. Production model evaluation, source ingestion, database migration, backend load testing and scheduled stewardship are **NOT_RELEVANT** to this local prototype. Production rollout and real contract wiring are **DEFERRED_BY_AUTHORITY**.

No merge, deployment, live styling change, public/private access change or production feature activation is included. Owner approval concerns the visual direction and reference experiences; it does not automatically authorize production migration.

## Final local verification

Production build, **11/11 correctness tests**, **16/16 browser tests**, nine populated-state axe scans and planning integrity passed. The browser cases observed zero external requests and no horizontal overflow. [Exact changed-file manifest](output/playwright/changed-files.txt) and [source-linked receipt](output/playwright/verification.json) preserve commands, source commit/blob IDs, actual results and limitations.

Local load samples: LCP **164–288 ms**, maximum CLS **0.0048**. Mobile rankings CLS fell from ~0.146 to **0.0023** by reserving the single-line headline while the condensed font loads. Input-to-second-render-frame sample: **27.7 ms**. These are local unthrottled samples, not production budgets or an INP score.
