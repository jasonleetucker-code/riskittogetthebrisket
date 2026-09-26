# Browser baseline protocol for Calculator #1338

The existing route baseline runner now retains every attempted cold/warm navigation, authentication failure and missing observation. Rankings requires a visible populated board; Trade requires visible controls and a real eligible result after the fixed `a` search. Trade timing therefore includes that search intent. Other inventory routes remain explicitly unsupported until their primary-data predicates are reviewed; their shells cannot pass.

Nearest-rank percentiles and threshold decisions use full precision. Cold is a fresh browser context; warm is the next full document navigation in that same context, not SPA navigation. Five samples give bounded observations, not robust tail estimates. Missing results fail closed. Normal/prefetched navigation, slowed profiles, personalized team experience, field metrics and campaign acceptance remain unmeasured.

## Authenticated production collection

The manual `baseline` suite in the existing authenticated-verification workflow reuses its canonical temporary guest pass, real login and always-revoke path. Exact approved HTTPS origin is checked before mint/login and again before credential use. Login and auth-status checks refuse redirects. Cookie files are bounded regular files with private Unix permissions. No test-session endpoint or production E2E bypass is used. No credential, payload, arbitrary URL, screenshot or trace is uploaded by this lane.

The job uses the existing production-deploy concurrency group. Check for other active or pending deployment/verification work before dispatch; do not displace another owner's queued deployment. It uses Node20, locked dependencies and a real browser against the currently deployed site. Verification checkout identity is distinct from unknown loaded production identity.

Independent review rejected the initial post-login-only origin check; the corrected pre-mint and redirect boundaries pass14Node and9workflow/classification tests. [Reviewed hashes and retained veto](evidence/browser-baseline-review-2026-09-26.json) describe the tested boundary. The existing local-test mode and api/browser/all production suites remain available with their prior authority.

No production speed result is claimed by this implementation record. Global budgets remain cold<=3s, warm<=1s and every useful/unavailable state<=5s; normal p95<=2s remains a separate required measurement. The aggregate report never labels these bounded observations complete campaign acceptance.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
