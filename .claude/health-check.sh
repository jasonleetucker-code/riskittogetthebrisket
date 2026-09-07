#!/usr/bin/env bash
# Claude Code adapter. All substantive startup logic is model-neutral and lives
# in scripts/agent_session_start.sh so other LLM runtimes get the same checks.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec bash scripts/agent_session_start.sh
