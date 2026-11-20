#!/usr/bin/env bash
# One push to the owner's private ntfy topic (repo secret NOTIFY_WEBHOOK_URL).
#
# THE single implementation every GitHub-side alert uses -- health-check.yml
# (health + SLO trackers), scheduled-refresh.yml and prod-e2e-smoke.yml.  Each
# of them used to carry its own inline copy; three copies of "how to push" is
# how one of them ends up printing the URL or hanging on a dead server.
#
# Usage:
#   bash scripts/notify_owner.sh [--issue N] TITLE MESSAGE
#   bash scripts/notify_owner.sh --retry-pending N TITLE MESSAGE
#
# N is an issue number or the issue URL ``gh issue create`` prints.
#
# Exit codes (a push that did not go out is NEVER exit 0, except "unset"):
#   0   the ntfy server accepted the push; or NOTIFY_WEBHOOK_URL is unset or
#       empty (a ::notice says nothing was sent -- an unconfigured channel is
#       the owner's choice, not a delivery failure); or --retry-pending found
#       no pending push on the issue.
#   1   the POST failed (DNS, TLS, non-2xx, the 10 s timeout), or the issue
#       could not be read for --retry-pending.
#   2   NOTIFY_WEBHOOK_URL is set but rejected (src/utils/owner_notify.py's
#       validator when the checkout carries it, else "not https://").  Refused:
#       the topic name IS the secret, and plain http would send it in clear.
#       The reason is a code (scheme, userinfo, ...), never the value.
#   64  usage error.
#
# --issue N           the rolling tracker issue this push announces.  When the
#                     push does not go out (exit 1 or 2) the marker
#                     ``<!-- owner-push: pending -->`` is appended to that
#                     issue's body; when it does go out, an existing marker is
#                     removed.  The tracker steps retry a marked issue on their
#                     next run (``--retry-pending``), so a push lost to an ntfy
#                     blip is delivered late instead of never -- a tracker that
#                     already exists takes the comment branch, which never
#                     pushes, so without the marker a failed first push was
#                     simply lost (COV-DEPLOYLAG).
# --retry-pending N   push only when issue N's body carries the marker, and
#                     clear it on success.
#
# Both issue modes need ``gh`` with GH_TOKEN and a repository context (a
# checkout, or GH_REPO).
#
# NEVER prints, logs or echoes the URL: curl's stderr is discarded (it can
# name the host and path), and every message names the secret, not its value.

set -Eeuo pipefail

MARKER='<!-- owner-push: pending -->'

usage() {
  echo "usage: notify_owner.sh [--issue N | --retry-pending N] TITLE MESSAGE" >&2
  exit 64
}

issue=""
mode="push"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue | --retry-pending)
      [[ $# -ge 2 ]] || usage
      [[ "$1" == "--retry-pending" ]] && mode="retry"
      # A number, or the issue URL ``gh issue create`` prints (…/issues/N).
      issue="${2##*/}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*) usage ;;
    *) break ;;
  esac
done
[[ $# -eq 2 ]] || usage
title="$1"
message="$2"
if [[ -n "$issue" && ! "$issue" =~ ^[0-9]+$ ]]; then
  usage
fi
if [[ "$mode" == "retry" && -z "$issue" ]]; then
  usage
fi

url="${NOTIFY_WEBHOOK_URL:-}"
if [[ -z "$url" ]]; then
  echo "::notice title=Owner push not configured::NOTIFY_WEBHOOK_URL is unset; '${title}' was not sent"
  exit 0
fi

issue_body() {
  gh issue view "$issue" --json body --jq '.body // ""'
}

write_body() {
  # $1: the new body.  A file, not --body: bodies carry backticks, quotes and
  # newlines, and an argv round-trip is one more place for them to break.
  local tmp
  tmp="$(mktemp)"
  printf '%s' "$1" >"$tmp"
  if gh issue edit "$issue" --body-file "$tmp" >/dev/null; then
    rm -f "$tmp"
    return 0
  fi
  rm -f "$tmp"
  return 1
}

mark_pending() {
  local body
  if ! body="$(issue_body)"; then
    echo "::warning title=Owner push not marked pending::could not read #${issue}; the next run will NOT retry '${title}'"
    return 0
  fi
  if [[ "$body" == *"$MARKER"* ]]; then
    echo "#${issue} already carries the pending owner-push marker"
    return 0
  fi
  if write_body "${body}"$'\n\n'"${MARKER}"; then
    echo "#${issue} marked: owner push pending (the next run retries it)"
  else
    echo "::warning title=Owner push not marked pending::could not edit #${issue}; the next run will NOT retry '${title}'"
  fi
}

clear_pending() {
  local body cleaned
  if ! body="$(issue_body)"; then
    echo "::warning title=Pending marker not cleared::could not read #${issue}; a later run may push '${title}' again"
    return 0
  fi
  [[ "$body" == *"$MARKER"* ]] || return 0
  cleaned="$(printf '%s\n' "$body" | grep -vF -- "$MARKER" || true)"
  if write_body "$cleaned"; then
    echo "#${issue}: pending owner-push marker cleared"
  else
    echo "::warning title=Pending marker not cleared::could not edit #${issue}; a later run may push '${title}' again"
  fi
}

if [[ "$mode" == "retry" ]]; then
  if ! current="$(issue_body)"; then
    echo "::warning title=Owner push retry skipped::could not read #${issue}; a pending push (if any) stays pending"
    exit 1
  fi
  if [[ "$current" != *"$MARKER"* ]]; then
    echo "no owner push pending on #${issue}"
    exit 0
  fi
  echo "#${issue} carries an undelivered owner push; retrying"
fi

# THE webhook validator is src/utils/owner_notify.py (``--check``: exit 0 ok,
# 1 rejected, 3 unset).  It is stdlib-only and run BY PATH under ``-I``, so a
# checkout that carries just that one file (health-check.yml's sparse checkout)
# can judge the value.  A checkout without it (the other pushing workflows'
# sparse checkouts) or without python3 keeps the old https:// test.  Either way
# the answer is a reason CODE, never any part of the value.
validator="$(dirname "${BASH_SOURCE[0]}")/../src/utils/owner_notify.py"
reject_reason=""
if [[ -f "$validator" ]] && command -v python3 >/dev/null 2>&1; then
  check_rc=0
  check_out="$(python3 -I "$validator" --check 2>&1 >/dev/null)" || check_rc=$?
  if [[ "$check_rc" == "1" ]]; then
    reject_reason="${check_out##*rejected:}"
    [[ "$reject_reason" =~ ^[a-z_]+$ ]] || reject_reason="unknown"
  fi
elif [[ "$url" != https://* ]]; then
  reject_reason="scheme"
fi

rc=0
if [[ -n "$reject_reason" ]]; then
  echo "::error title=Owner push misconfigured::NOTIFY_WEBHOOK_URL is set but rejected (${reject_reason}); '${title}' was NOT sent"
  rc=2
else
  # A header cannot carry a line break: one would end the header early.
  header_title="${title//$'\r'/ }"
  header_title="${header_title//$'\n'/ }"
  # The message goes on stdin (@-), never as a literal argument: curl reads a
  # --data-binary value that starts with "@" as a FILE NAME.
  curl_rc=0
  printf '%s' "$message" |
    curl -fsS --max-time 10 -H "Title: ${header_title}" --data-binary @- "$url" \
      >/dev/null 2>&1 || curl_rc=$?
  if [[ "$curl_rc" == "0" ]]; then
    echo "owner push sent: ${title}"
  else
    echo "::warning title=Owner push failed::the ntfy POST for '${title}' did not succeed (curl exit ${curl_rc})"
    rc=1
  fi
fi

if [[ -n "$issue" ]]; then
  if [[ "$rc" == "0" ]]; then
    clear_pending
  else
    mark_pending
  fi
fi
exit "$rc"
