# Browser baseline protocol for Calculator #1338

The existing route baseline runner now retains every attempted cold/warm navigation, authentication failure and missing observation. Rankings requires a visible populated board; Trade requires visible controls and a real eligible result after the fixed `a` search. Trade timing therefore includes that search intent. Other inventory routes remain explicitly unsupported until their primary-data predicates are reviewed; their shells cannot pass.

Nearest-rank percentiles and threshold decisions use full precision. Cold is a fresh browser context; warm is the next full document navigation in that same context, not SPA navigation. Five samples give bounded observations, not robust tail estimates. Missing results fail closed. Normal/prefetched navigation, slowed profiles, personalized team experience, field metrics and campaign acceptance remain unmeasured.

## Authenticated production collection

The manual `baseline` suite in the existing authenticated-verification workflow reuses its canonical temporary guest pass, real login and always-revoke path. Exact approved HTTPS origin is checked before mint/login and again before credential use. Login and auth-status checks refuse redirects. Cookie files are bounded regular files with private Unix permissions. No test-session endpoint or production E2E bypass is used. No credential, payload, arbitrary URL, screenshot or trace is uploaded by this lane.

The job uses the existing production-deploy concurrency group. Check for other active or pending deployment/verification work before dispatch; do not displace another owner's queued deployment. It uses Node20, locked dependencies and a real browser against the currently deployed site. Verification checkout identity is distinct from unknown loaded production identity.

Independent review rejected the initial post-login-only origin check; the corrected pre-mint and redirect boundaries pass14Node and9workflow/classification tests. [Reviewed hashes and retained veto](evidence/browser-baseline-review-2026-09-26.json) describe the tested boundary. The existing local-test mode and api/browser/all production suites remain available with their prior authority.

## First production baseline — FAIL, not campaign acceptance

[Run36272764956](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/36272764956) collected all40 requested observations on Node20.20.2 / Chromium153.0.8010.12, unthrottled, before the foundation merge. Real login and pass revocation succeeded. Independent recomputation found zero discrepancies in counts, summaries or gates.

| Route/profile | Cold p95 ms (n5) | Warm document p95 ms (n5) |
| --- | ---: | ---: |
| Rankings desktop | 6692.1 | 1610.4 |
| Trade desktop | 2720.3 | 1989.9 |
| Rankings mobile | 3156.7 | 1604.1 |
| Trade mobile | 2628.5 | 2497.0 |

Both rankings cold gates and all warm gates fail; desktop rankings also exceeds5s. Every request reached the declared useful predicate, so missing samples did not cause these failures. The first desktop rankings cold attempt was the largest, but subsequent warm outliers prevent assigning the problem solely to first-request work. Five samples do not establish a robust tail distribution.

Cold page ResourceTiming body totals range roughly8–14MB decoded and1.35–2.55MB encoded by profile/route. These totals include multiple resources, can include cached bodies and are sampled after load; they are neither isolated API wire bytes nor causal attribution. Navigation usefulness includes browser-driver predicate observation lag and the declared Trade search intent. Authentication prechecks occur before timing and can warm the backend.

[Full sanitized report and independent review](evidence/production-browser-baseline-2026-09-26.json) preserve exact unrounded values and limitations. The next opt-in attribution separates API resource/fetch timing and body/JSON-promise work, with explicit observer controls. Global budgets remain cold<=3s, warm<=1s and useful/unavailable<=5s; normal SPA p95<=2s, prefetched/slowed/field and personalized-team acceptance remain unmeasured. Loaded production code identity is unproven; verification source SHA is not substituted.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Opt-in attribution

The same runner accepts `--diagnostics true`; the default remains disabled. Bounded browser observations classify auth, settings, league and data views, retaining fetch/header and body/JSON-promise completion timestamps plus ResourceTiming sizes. JSON promise time includes body waiting and scheduling as well as parsing. Resource categories are not exact request joins. Useful-boundary and post-load snapshots remain distinct; missing observer support, pending requests and dropped events are explicit.

Native fetch/JSON promises, values and errors are preserved. No URLs, queries, headers, credentials, identities or bodies enter the report. The workflow's manual boolean input only affects its existing baseline step. [Independent review](evidence/browser-attribution-review-2026-09-26.json) preserves two rejected attribution defects and their corrections: the real settings endpoint and failed-observer availability. Final 21 Node tests and 9 workflow/classification checks pass. Collector-on/off production measurements are still required; no new performance improvement is claimed.

## Remaining-route readiness predicates

The existing runner now recognizes public league overview and Game Day useful,
partial and unavailable states. Public league uses a fresh sessionless context;
the surrounding workflow can still warm the backend during guest provisioning.
Guest Game Day without a selected team is explicitly unavailable, never a passing
numerical timing observation. Zero scores/counts remain valid. Existing core
predicates and budgets are unchanged; the supplemental resolved-within-five-seconds
field does not make partial/unavailable observations pass numerical route gates.
The manual fixed `baseline_route_set` defaults to `core`; `league-game-day` adds
these two routes without accepting arbitrary shell or route input.

Independent review rejected four misleading state cases before approval; all
remain regression-tested. Final 33 Node/Chrome DOM tests and six workflow checks
pass. The Node/DOM tests run as a blocking E2E workflow step before stack startup.
This expands the existing route denominator; it adds no new diagnostic platform
and does not establish production acceptance. See the reviewed hash receipt in
`evidence/route-probes-review-2026-09-26.json`.
