# Engineering Reliability Priorities — 2026-09-06

**Status:** model-neutral engineering-improvement backlog and design guidance.  
**Product authority:** none.  
**Purpose:** preserve the high-value findings from the 2026-09-06 internet-wide engineering research so Claude, Codex, Gemini, ChatGPT, or any future agent can act on the same priorities without repeating the research.

This is not permission to start broad work during an active higher-priority completion tranche. `docs/EXECUTION_PLAN.md` and active owner-authorized contracts still control timing and authorization.

## Core conclusion

The repository's agent/orchestration layer is comparatively mature. The next six-month engineering gains should come primarily from making the **application substrate** more mechanically reproducible, typed, observable, contract-driven, adversarially tested, and artifact-identifiable rather than adding more agent personalities.

## Priority 1 — External-source deterministic replay

**Goal:** preserve real upstream behavior as replayable evidence.

Build a general pattern for important third-party sources:
- live capture;
- secret/token scrubbing;
- immutable sanitized HTTP/HTML/JSON fixture;
- deterministic parser replay;
- scheduled live drift/canary check;
- explicit source/provenance/as-of metadata.

Use VCR-style HTTP recording where appropriate and saved HTML/JSON for browser-only sources.

This should prevent upstream changes from becoming irreproducible parser incidents.

## Priority 2 — Typed API contract spine

Move important FastAPI request/response boundaries toward explicit Pydantic schemas and `response_model` contracts.

Target chain:

`Pydantic models -> OpenAPI -> generated frontend types -> contract/adversarial API tests`

Add Schemathesis or an equivalent OpenAPI-driven test lane once enough critical endpoints have accurate schemas.

Do not fabricate schemas around endpoints whose semantics are not settled.

## Priority 3 — Reproducible dependency/build/artifact identity

The repository already proves exact Git heads strongly. Extend that truthfulness to the built runtime.

Desired chain:

`Git SHA -> exact dependency lock -> CI-built artifact -> artifact digest/attestation -> deploy exact artifact -> production fingerprint`

Key work:
- adopt a committed exact Python dependency lock (for example uv or equivalent) rather than relying only on compatible-release resolution;
- keep npm lock usage exact;
- stop allowing CI and production to independently resolve materially different dependency trees;
- move toward build-once/deploy-the-tested-artifact instead of rebuilding Next/Python environment independently on the VPS;
- produce hashes/attestations/SBOM where practical;
- verify production serves the expected artifact identity.

## Priority 4 — Property-based and mutation testing

Use property-based tests for canonical invariants that examples can miss.

Candidate properties:
- missing never becomes numeric zero;
- unknown never becomes false;
- stale cannot become current;
- input ordering cannot change order-independent identities/results;
- serialize/deserialize round trips preserve canonical state;
- same snapshot + same methodology yields deterministic output;
- source absence cannot increase confidence;
- best-ball lineup remains legal under generated roster/eligibility combinations;
- independent implementations that are required to be equivalent remain equivalent.

Use targeted mutation testing on critical canonical modules. Prefer scheduled/nightly targeted mutation lanes over slowing every PR with whole-repo mutation.

## Priority 5 — Progressive static-typing ratchet

Activate the existing mypy scaffold incrementally instead of a repository-wide flag day.

Start with high-leverage/shared modules:
- `src/data_models/`
- `src/canonical/`
- `src/scoring/`
- `src/packages/`
- API request/response schemas

Add modules to the required CI typing set only after they are green.

For frontend JavaScript, prefer incremental `checkJs` / JSDoc / selective TypeScript boundaries over a broad rewrite.

## Priority 6 — End-to-end observability and SLOs

Introduce an OpenTelemetry-compatible observability layer for important paths.

Carry/correlate where possible:
- request ID;
- trace ID;
- deploy/commit/artifact identity;
- source generation/snapshot IDs;
- route;
- important pipeline stage.

Trace useful path shapes such as:

`browser -> Next bridge -> backend endpoint -> source/API -> canonical pipeline -> storage -> response`

Define a small set of user-facing SLOs:
- public availability;
- authenticated core-flow success;
- data freshness;
- API latency;
- frontend Core Web Vitals.

Use error-budget/burn-rate alerting rather than treating every isolated error as equivalent.

## Priority 7 — Field frontend performance

Keep existing bundle/build budgets, and add real-user or production-synthetic experience measurements.

Priorities:
- LCP;
- INP;
- CLS;
- route-level latency;
- deploy SHA attribution;
- coarse device/PWA/browser class without private league/user content.

Add Lighthouse CI on a small critical route set when it can be made stable enough to be actionable.

## Priority 8 — Repo-specific agent/harness evals

Create `agent-evals/` from historical real repository tasks.

Evaluate **model + harness together**, not model reputation.

Candidate tasks:
- find a missing->zero bug;
- diagnose a hydration race;
- trace canonical owner;
- reject stale evidence;
- repair a parser from a captured source change;
- produce a bounded PR without forbidden-file edits;
- refuse methodology invention;
- distinguish merged/deployed/verified correctly.

Grade with deterministic evidence where possible:
- tests;
- static checks;
- changed-file scope;
- canonical-owner violations;
- false verification claims;
- corrective turns;
- tool calls/runtime/cost;
- root-cause success;
- independent reviewer outcome.

Material Agent OS/skill/model-routing changes should eventually be evaluated against this suite before becoming canonical.

## Priority 9 — Faster CI without weaker evidence

Do not start by dropping tests.

Split independent gates into required parallel jobs:
- Python static/governance;
- Python full tests;
- frontend tests/build;
- security/contracts;
- final aggregator.

Enable dependency caches for pip/uv/npm where safe.

Consider test prioritization that still runs the entire required suite, so likely failures surface earlier without reducing coverage.

## Priority 10 — Machine-enforced architecture boundaries

Add import/dependency contracts where they can encode existing ONE CONCEPT / ONE CANONICAL OWNER rules.

Examples:
- domain/canonical modules cannot depend on API/UI adapters;
- public/private boundaries cannot import forbidden internals;
- canonical owner packages cannot be bypassed by sibling reimplementations;
- selected layers remain acyclic.

Prefer a narrow first set of high-confidence contracts over a giant architecture policy.

## Priority 11 — Supply-chain security ratchet

Evaluate and add, where repository/platform support permits:
- CodeQL;
- dependency review on PRs;
- pip/OSV-style dependency vulnerability checks;
- minimal GitHub Actions token permissions;
- pin third-party Actions to immutable commit SHAs where practical;
- artifact provenance/attestation;
- SBOM generation;
- verify GitHub secret scanning/push protection posture rather than duplicating platform controls.

Do not add noisy gates that will be ignored; start with high-confidence checks.

## Priority 12 — Versioned SQLite migration ownership

The repository has multiple mature SQLite stores with local runtime schema setup/migrations. Standardize migration history so persistent stores can prove:
- current schema version;
- ordered upgrade path;
- fresh-database reproducibility;
- rollback/forward-only policy;
- migration idempotency;
- production revision.

A lightweight numbered raw-SQL/Python migration runner may fit better than introducing a heavy ORM solely for migrations.

## Useful compound systems

### Contract spine
`Pydantic -> OpenAPI -> generated frontend types -> Schemathesis -> JS/TS checking`

### Source reliability
`live capture -> sanitized replay fixture -> property/parser tests -> scheduled drift check -> freshness telemetry`

### Production truth chain
`Git SHA -> lock -> tested artifact -> digest/attestation -> exact deploy -> production fingerprint`

### Verification stack
`canonical invariants -> Hypothesis -> targeted mutation -> normal suite -> E2E -> production smoke`

### Diagnostics
`request ID + trace ID + deploy/artifact ID + source generation -> telemetry -> SLO -> replay`

### Agent improvement flywheel
`Agent-OS receipt -> repo task eval -> deterministic grading -> model/harness comparison -> targeted harness change`

## Experimental, not yet canonical

- token-budgeted generated repo map / dependency-symbol context pack;
- test ordering that prioritizes impacted/likely-failing tests while still running all required tests;
- controlled fault injection for upstream timeout/429/503, malformed source, SQLite lock, stale snapshot, and partial artifact;
- privacy-reviewed client session replay after basic tracing/Web Vitals are established.

## Explicit non-goals

Do not treat these as default recommendations:
- Kubernetes;
- microservice decomposition for its own sake;
- a full frontend TypeScript rewrite;
- 100% line-coverage as a quality goal;
- impacted-test selection that silently stops running the full protected suite;
- a vector database merely to give agents “memory”;
- more agent personalities as a substitute for deterministic engineering;
- broad new autonomous runners without the Agent OS activation gate.

## Sources used in the research pass

Primary/high-signal references included:
- FastAPI response models: https://fastapi.tiangolo.com/tutorial/response-model/
- Schemathesis: https://schemathesis.readthedocs.io/
- Hypothesis: https://hypothesis.readthedocs.io/
- mutmut: https://mutmut.readthedocs.io/
- VCR.py: https://vcrpy.readthedocs.io/
- mypy existing-code guidance: https://mypy.readthedocs.io/en/stable/existing_code.html
- TypeScript checkJs: https://www.typescriptlang.org/tsconfig/checkJs.html
- OpenAPI TypeScript: https://github.com/openapi-ts/openapi-typescript
- uv locking/syncing: https://docs.astral.sh/uv/
- GitHub artifact attestations: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations
- GitHub Actions secure-use guidance: https://docs.github.com/en/actions/reference/security/secure-use
- GitHub Dependency Review: https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/configure-dependency-review-action
- OpenTelemetry Python: https://opentelemetry.io/docs/languages/python/
- Google SRE SLO guidance: https://sre.google/sre-book/service-level-objectives/
- web-vitals: https://github.com/GoogleChrome/web-vitals
- Lighthouse CI: https://github.com/GoogleChrome/lighthouse-ci
- Import Linter: https://import-linter.readthedocs.io/
- Anthropic agent eval guidance: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Aider repo map: https://aider.chat/docs/repomap.html

## How agents should use this document

When authorized to improve engineering infrastructure:
1. inspect current implementation first;
2. mark each candidate `ALREADY IMPLEMENTED`, `PARTIAL`, `NEW-HIGH-VALUE`, `EXPERIMENTAL`, or `NOT USEFUL`;
3. claim one bounded unit;
4. implement the smallest measurable improvement;
5. prove benefit without weakening existing evidence gates;
6. record measured results;
7. do not convert this backlog into a second product roadmap.
