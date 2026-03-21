# League Page Constitution Spec

## Scope
Public League Page `Constitution` section only.

This is planning/spec work only.

## Repo-grounded facts (current state)
- There is no existing constitution/rules data store in live runtime payloads.
- There is no commissioner CMS/editor in the repo today.
- Current architecture is file-artifact centric (JSON/CSV/MD), with FastAPI serving payloads (`server.py`).
- Blueprint identifies constitution as a manual-first domain that should be commissioner-managed.

## Storage strategy

Use versioned file storage first, compatible with current architecture:
- `data/league/manual/constitution/current.md`
- `data/league/manual/constitution/ruleset.current.json`
- `data/league/manual/constitution/amendments.jsonl`
- `data/league/manual/constitution/rule_change_log.jsonl`

Rationale:
- Matches repo's existing file-based workflow.
- Supports auditability and git history.
- Avoids introducing a parallel DB system before the public contract is defined.

## Searchable rule/ruleset structure

`ruleset.current.json` should be an array of rule objects:
- `rule_id` (stable, immutable; e.g., `ARTICLE-04-SECTION-02`)
- `article`
- `section`
- `title`
- `body_markdown`
- `tags` (e.g., `trade`, `waivers`, `playoffs`, `dues`)
- `status` (`active`, `repealed`, `superseded`)
- `effective_season`
- `last_amendment_id`
- `supersedes_rule_id` (nullable)
- `public_visibility` (bool; default `true`)
- `updated_at_utc`

## Amendment history format

`amendments.jsonl` (append-only, one JSON object per amendment):
- `amendment_id`
- `proposal_title`
- `proposal_summary`
- `proposed_by`
- `proposed_at_utc`
- `vote_open_at_utc`
- `vote_close_at_utc`
- `vote_result` (`passed`, `failed`, `withdrawn`)
- `votes_for`
- `votes_against`
- `votes_abstain`
- `effective_season`
- `affected_rule_ids` (array)
- `notes`

## Rule change log format

`rule_change_log.jsonl` (append-only operational log):
- `event_id`
- `event_type` (`create_rule`, `edit_rule`, `repeal_rule`, `restore_rule`)
- `rule_id`
- `amendment_id` (nullable for non-amendment administrative edits)
- `change_summary`
- `editor`
- `edited_at_utc`
- `diff_ref` (path/hash to previous/new snapshots)

## Commissioner-managed editing approach

Phase-appropriate approach for current repo:
- Commissioner (or delegated maintainer) edits source files in `data/league/manual/constitution/*`.
- Changes go through git commit/PR with explicit changelog updates.
- Publish step validates schema + append-only logs before exposing updated public data.

This keeps governance explicit without requiring new admin UI now.

## Public-safe constraints
- Constitution content is public narrative/rules content.
- Must not include private credentials, private valuation settings, or strategic trade-engine internals.
- Any rule referencing private tools should describe policy at a high level, not implementation math.

## Feasibility status
- Storage and schema design: **Fully feasible now**.
- Commissioner web editor UI: **Not implemented** (would require additional build work).
- Search API wiring: **Partially feasible** (schema-ready, route not implemented yet).

