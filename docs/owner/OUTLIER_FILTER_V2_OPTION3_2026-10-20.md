OWNER DECISION — PR #1817 / DLF IDP / OUTLIER FILTER (2026-10-20), verbatim

I'm choosing Option 3: Wait for a preregistered Version 2 of the outlier filter.
Do NOT accept the current filter's 34–54% valuation changes, and do NOT activate a replacement filter that failed three of its six mandatory adversarial tests.
Here are my instructions:

1. Keep DLF IDP voting disabled behind the temporary, explicitly labeled flag until a corrected outlier filter passes every mandatory test. Make sure rebases, merges, deployments, and default configuration cannot accidentally enable it.
2. Continue releasing the safe portions of PR #1817, including the rejected-rule removals, DLF Values voting, FantasyPros freshness improvements, and Travis Hunter's two-way valuation correction.
3. Develop outlier-filter Version 2 immediately, using an isolated research branch/worktree. Preregister its algorithm, expected behavior, and acceptance criteria before testing.
4. Require all six existing adversarial tests to pass, along with additional regression coverage for Trevin Wallace, Myles Garrett, and every defensive player whose valid votes were incorrectly discarded. Do not weaken tests to make the new algorithm pass.
5. The new filter must correctly distinguish legitimate source disagreements from actual outliers. It cannot arbitrarily remove valid Draft Sharks, FantasyPros, IDP Trade Calculator, or DLF opinions simply because sources disagree.
6. Verify mathematical consistency, deterministic behavior, source-family voting caps, and proper handling of small sample sizes. Produce an exact before/after valuation report, including every significant player-value change and its underlying source contributions.
7. Run the corrected filter in shadow mode against the current production board before recommending activation. Any unexpected large valuation movement must be explained and reviewed.
8. Once Version 2 passes all mandatory gates, prepare DLF IDP activation for my explicit approval. Do not silently enable it.
9. Continue Train 12, Train 13, V1 verification, and all other authorized engineering work in parallel without unnecessary blocking.
10. Keep the production stability investigation separate but high priority. The reported 2.6 GB memory peak above the 2.5 GB soft limit is a plausible contributor to the restart, not yet definitive proof of root cause. Have W8 verify the actual failure mechanism, address cache growth safely, and validate any proposed memory-limit change against the 8 GB server's available capacity.

My standing priority is accurate, trustworthy valuations over rushing features into production.
I want every legitimate source to have its appropriate voting power, but I will not allow a defective outlier filter to distort our player values.
Continue implementation autonomously within our existing engineering and release policies. Only return to me for an owner-reserved production decision or an actual blocker.
