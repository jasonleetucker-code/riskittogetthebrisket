# Repository Agent Entry

Read `AI_INSTRUCTIONS.md` first. Every model follows the same canonical
`docs/AGENT_OPERATING_SYSTEM.md`, current execution authority and
`ASSISTANT_COORDINATION.md`. Provider adapters grant no unique authority.

## Working Copy

Active working copy: `C:\Users\jason\code\riskittogetthebrisket`.
GitHub main is shared repository truth. Inspect current HEAD, fetch main,
check claims/open PRs, and use a task branch for material changes.
Do not edit OneDrive copies or overlap another assistant's active files.

## Permanent Rules

- Inspect before modifying; trace the live execution path before claiming completion.
- One concept, one canonical owner. Reuse correct architecture and preserve working behavior.
- Missing is not zero; unknown stays unknown; stale evidence is not current truth.
- Preserve source authority, provenance, privacy and exact league semantics.
- Obey owner/governance boundaries; capability never grants merge/deploy or spending authority.
- Use the least expensive sufficient available profile; escalate on evidence.
- Plan shared foundations and compatible work together; keep rollback and review boundaries clear.
- Completion requires matching acceptance evidence, not code existence or agent confidence.
- Keep literal launch gates; never silently weaken tests, acceptance or production requirements.
- Do not exfiltrate data or perform unauthorized destructive actions.
- Be explicit before production, deployment, credential or public-output actions.

## Progressive Workflow

Run `bash scripts/agent_session_start.sh`. For campaign coordination load
`docs/agent-operating-system/STEWARD_RUNTIME.md` and use the existing Steward
brief, state and router. Read domain procedures only when relevant.

Main movement is classified under `ASSISTANT_COORDINATION.md`:
`BENIGN_AUTOMATION_MOVE` preserves unaffected implementation evidence;
`RELEVANT_BASE_MOVE` requires affected reconciliation. Unknown requires inspection.
Never overwrite newer generated data with stale branch output.

Report exact files, live paths, tests and unresolved acceptance gaps.
Separate implementation, integration, deployment and production verification.
