// The ONE frontend reader of a private source's vote state (backend
// ``privateSourceAvailability[*].voteState``, src/api/data_contract.py
// ``_private_source_vote_state``).  The backend decides whether a source
// votes; this only names the state the way the owner asked the pages to
// (Rankings columns and audit card, Settings source table).

export const VOTE_STATE_LABELS = {
  active: "Active",
  shadow: "Shadow — not voting",
  held: "Collected — not voting",
  rolled_back: "Rolled back — not voting",
  unavailable: "Unavailable",
};

/** The backend vote state, with a fallback for payloads that predate it. */
export function sourceVoteState(avail) {
  if (!avail) return null;
  if (avail.voteState) return avail.voteState;
  if (avail.votes) return "active";
  if (avail.rolledBack) return "rolled_back";
  if (avail.heldFromVote) return "held";
  return "unavailable";
}

/** True only when the backend says this private source does NOT vote. */
export function sourceIsNonVoting(avail) {
  const state = sourceVoteState(avail);
  return state != null && state !== "active";
}

/**
 * The fields a source table needs to render a private source's state:
 * the state, whether it is NON-voting (no include/weight control may be
 * offered for it — a control would imply it moves the blend), and the
 * owner-worded label.  Public sources (no availability entry) are voting
 * sources and get ``nonVoting: false``.
 */
export function sourceVoteFields(avail) {
  const voteState = sourceVoteState(avail);
  return {
    voteState,
    nonVoting: voteState != null && voteState !== "active",
    voteLabel: voteState ? VOTE_STATE_LABELS[voteState] || voteState : null,
  };
}
