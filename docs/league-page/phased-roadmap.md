# League Page Phased Roadmap

## Guiding rule
Ship public value fast using truthful data. Do not block Phase 1 on impossible historical reconstruction.

## Phase 1 (practical launch scope)

### In scope
- Public contract foundation for League Page (`/api/public/league/*` family).
- Franchise registry and manual data stores:
- constitution
- money ledger
- media posts
- Public modules with real near-term value:
- Home (league identity + freshness)
- Franchises (current roster + pick inventory + recent trades)
- Draft (future pick ownership)
- Trades (recent timeline with explicit window)
- Constitution (manual content)
- Money (manual ledger metrics)
- League Media (manual archive and commissioner notes)
- Standings current-season support if ingestion is straightforward; otherwise explicit provisional state.

### Out of scope
- Full history/records/awards automation from inferred data.
- Full all-time trade/draft archives.
- Opponent-facing optimization views.

### Exit criteria
- Public endpoints are allowlist-safe and pass denylist tests.
- No private valuation internals exposed on public routes.
- Manual data domains are editable without code changes.
- Phase 1 modules publish truthful outputs with explicit data coverage notes.

## Post-spec implementation sequence (practical order)

1. Backend/data foundation
- Define public contract schemas and route skeletons.
- Add strict public allowlist transforms and private-field reject checks.
- Add franchise registry and manual domain file schema validators.

2. Ingestion/backfill
- Wire current authoritative league inputs into public transform:
- teams
- pickDetails
- recent trades
- Seed manual datasets:
- constitution rules/amendments
- money ledger
- media posts
- optional seeded championship/playoff summary rows

3. Derived metrics layer
- Franchise rollups (roster counts, pick counts, recent trade counts).
- Money formulas (net/ROI/per-playoff/per-title) from manual ledger + outcomes.
- Trade aggregates (activity and partner frequency).

4. Public routes
- Ship `/api/public/league/*` endpoints module by module.
- Add contract and exposure tests.

5. UI shells
- Implement locked nav with data-status aware shells.
- Render truthful placeholders where data is intentionally deferred.

6. Detailed components
- Fill module-specific components in this order:
- Franchises
- Draft
- Trades
- Constitution
- Money
- League Media
- Standings (if ready)

7. Commissioner admin tooling (minimum)
- Start with file-managed workflow + validation script gate.
- Add lightweight admin surfaces later only after public contract is stable.

## Phase 2 (high-level)
- Build historical backbone for standings/matchups/team-week outcomes.
- Expand History and Records with reproducible season-level coverage.
- Expand Draft to historical draft results.
- Expand Trades from rolling window toward deeper historical archive.

## Phase 3 (high-level)
- Enable formula-driven Awards publication (VORP-based) once ownership+scoring history integrity gates pass.
- Add advanced History/Records/Awards and richer League Media automation with commissioner approval.
- Add stronger commissioner admin interfaces for manual/public content domains.

