## Model-migration hygiene

When Claude/Codex model behavior changes materially, treat the harness like code that is being migrated.

### Migration checklist

1. Freeze a small representative baseline task set and record current quality/cost/latency observations where measurable.
2. Audit prompts, skills, tool descriptions, hooks, and always-loaded instructions for old-model compensations.
   - Treat instruction debt like code debt: quantify unnecessary always-loaded context where practical, remove stale recipes, and preserve only durable domain truth.
3. When the current vendor supplies a prompt-migration audit (for example, Anthropic's `/claude-api prompt-audit` when available), run it as **evidence, not authority**; review every proposed deletion against repo domain invariants.
4. Re-sweep model/effort routing instead of assuming the previous "best" tier remains optimal.
5. Check model/API compatibility changes that can break the harness: unsupported forced-tool settings, prefill/format hacks, thinking/history behavior, and deprecated configuration.
6. If the harness directly manages conversation history for a model with prefix-bound thinking, treat accepted history as append-only; prefer a new turn or turn-scoped reminder over editing earlier accepted content.
7. Rerun the baseline and inspect quality, silent failure modes, cost, and latency before declaring the migration better.
8. Keep a rollback path until the new harness is proven.

Also:
- audit old anti-undertrigger instructions;
- audit repeated “MUST/CRITICAL/always verify again” wording;
- test whether those instructions now cause over-triggering/over-verification;
- preserve actual domain truths;
- prefer normal direct language where stronger models already comply;
- re-check skill routing overlap;
- audit verification rituals and reasoning scaffolds that duplicate capabilities the current model/runtime already provides.

Do not assume a prompt that helped the previous model is neutral on the new one.

