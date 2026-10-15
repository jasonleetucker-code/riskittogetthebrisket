/**
 * Trade Desk (Part 12) — client for `/api/user/trade-desk`.
 *
 * The backend owner is `src/trade/trade_desk.py`. Statuses are what the user
 * marked; the app cannot see whether a trade was sent, accepted or rejected,
 * so nothing here sets a status on the user's behalf. `rosterCheck` is the
 * one thing the app observes (are the players still where the package needs
 * them?) and it never rewrites a status.
 */

export const DESK_ENDPOINT = "/api/user/trade-desk";

export const DESK_STATUSES = [
  { value: "idea", label: "Idea" },
  { value: "candidate", label: "Candidate" },
  { value: "evaluated", label: "Evaluated" },
  { value: "saved", label: "Saved" },
  { value: "manually_sent", label: "Manually sent" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
];

const STATUS_LABEL = Object.fromEntries(
  DESK_STATUSES.map((s) => [s.value, s.label]),
);

export function statusLabel(value) {
  return STATUS_LABEL[value] || "Unknown";
}

function deskAsset(a) {
  const out = { name: a.name, isPick: Boolean(a.isPick) };
  if (a.assetId) out.assetId = a.assetId;
  if (a.boardRowName) out.boardRowName = a.boardRowName;
  if (a.position) out.position = a.position;
  return out;
}

/** The create body for one generated package (send = what you give). */
export function deskBodyFromOffer(
  offer,
  { leagueKey, myTeam, opponent, source, runId },
) {
  const body = {
    leagueKey,
    myTeam,
    opponent,
    source,
    send: (offer?.send || []).map(deskAsset),
    receive: (offer?.receive || []).map(deskAsset),
  };
  if (runId) body.sourceRunId = runId;
  return body;
}

const ERROR_TEXT = {
  duplicate: "Already on your Trade Desk.",
  desk_full: "Your Trade Desk is full; remove an item first.",
  guest_read_only: "Guest passes cannot save a Trade Desk.",
  auth_required: "Sign in to use the Trade Desk.",
  data_not_ready: "This league's teams are not loaded yet; nothing was saved.",
  unknown_team: "That team is not in this league.",
  not_found: "That item is no longer on your Trade Desk.",
  network: "Could not reach the server; nothing was changed.",
};

export function deskErrorText(code) {
  return ERROR_TEXT[code] || "The Trade Desk could not be updated.";
}

async function call(url, init) {
  let res;
  try {
    res = await fetch(url, { credentials: "include", ...init });
  } catch {
    // A network failure is an answer too: callers must never hang on it.
    return { ok: false, code: "network", status: 0 };
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const code =
      (body && body.error) || (res.status === 401 ? "auth_required" : "error");
    return { ok: false, code, status: res.status };
  }
  return { ok: true, desk: body, status: res.status };
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export function loadDesk(leagueKey) {
  return call(`${DESK_ENDPOINT}?leagueKey=${encodeURIComponent(leagueKey)}`);
}

export function saveToDesk(body) {
  return call(DESK_ENDPOINT, json("POST", body));
}

export function updateDeskItem(leagueKey, id, patch) {
  return call(
    `${DESK_ENDPOINT}/${encodeURIComponent(id)}`,
    json("PATCH", { leagueKey, ...patch }),
  );
}

export function removeDeskItem(leagueKey, id) {
  return call(
    `${DESK_ENDPOINT}/${encodeURIComponent(id)}?leagueKey=${encodeURIComponent(leagueKey)}`,
    { method: "DELETE" },
  );
}

/** One line describing the roster evidence; never a status. */
export function rosterCheckText(check) {
  if (!check || check.state === "unknown") return "Roster check unavailable";
  if (check.state === "current") {
    return check.picksNotChecked
      ? "Players still in place (picks not checked)"
      : "Players still in place";
  }
  const moved = (check.noLongerInPlace || []).join(", ");
  return `Roster changed: ${moved} no longer in place`;
}

/** The last time the user changed the status, for "you marked … on …". */
export function lastMarked(item) {
  const history = Array.isArray(item?.statusHistory) ? item.statusHistory : [];
  return history.length ? history[history.length - 1] : null;
}

/** A stable identity for one package, for keying per-package UI state. */
export function packageIdentity(body) {
  const names = (side) =>
    (body?.[side] || [])
      .map((a) => String(a.assetId || a.name || "").toLowerCase())
      .sort()
      .join("|");
  return [
    body?.leagueKey,
    body?.myTeam,
    body?.opponent,
    names("send"),
    names("receive"),
  ].join("::");
}
