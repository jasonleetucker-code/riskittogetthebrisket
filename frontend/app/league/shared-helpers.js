// Pure (non-React, non-client-only) helpers shared between server-
// rendered pages and client components.  No "use client" directive —
// these can be imported from server components freely.
//
// shared.jsx (the client-component bundle) re-exports these for
// convenience so client-side callers can grab everything from one
// module.

export function buildManagerLookup(league) {
  const map = new Map();
  for (const m of league?.managers || []) {
    map.set(String(m.ownerId), m);
  }
  return map;
}

export function nameFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  return mgr?.displayName || mgr?.currentTeamName || ownerId || "Unknown";
}

export function avatarUrlFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  if (!mgr || !mgr.avatar) return "";
  const avatar = String(mgr.avatar);
  if (avatar.startsWith("http")) return avatar;
  return `https://sleepercdn.com/avatars/thumbs/${avatar}`;
}

export function fmtNumber(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPoints(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(1);
}

export function fmtPercent(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return `${Math.round(Number(n) * 100)}%`;
}
