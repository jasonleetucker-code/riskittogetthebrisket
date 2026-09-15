import { _resetBaseContractCache, materializePlayerDetail } from "./dynasty-data.js";

const details = new Map();
const requests = new Map();
const refreshedGenerations = new Set();
let epoch = 0;

export function resetPreparedDetails(clearRefreshes = true) {
  epoch += 1;
  details.clear();
  requests.clear();
  if (clearRefreshes) refreshedGenerations.clear();
}

if (typeof window !== "undefined") {
  window.addEventListener("auth:changed", resetPreparedDetails);
  window.addEventListener("league:changed", resetPreparedDetails);
  window.addEventListener("read-model:generation-changed", () => resetPreparedDetails(false));
}

export function refreshPreparedBoard() {
  _resetBaseContractCache();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("read-model:generation-changed"));
  } else resetPreparedDetails();
}

export async function fetchPreparedPlayerDetail(row, contract) {
  const generation = contract?.meta?.readModelGeneration;
  const leagueKey = contract?.meta?.leagueKey || "";
  const playerKey = row?.readModelKey || row?.raw?.readModelKey;
  if (!generation || !playerKey) throw new Error("Player details are unavailable. Refresh the board.");
  const cacheKey = JSON.stringify([leagueKey, generation, playerKey]);
  let payload = details.get(cacheKey);
  if (!payload) {
    let request = requests.get(cacheKey);
    if (!request) {
      const requestEpoch = epoch;
      request = (async () => {
        const query = new URLSearchParams({ generation });
        if (leagueKey) query.set("leagueKey", leagueKey);
        const response = await fetch(`/api/read-models/players/${encodeURIComponent(playerKey)}?${query}`, { cache: "no-cache" });
        const body = await response.json();
        if (!response.ok) {
          const refreshKey = JSON.stringify([leagueKey, generation]);
          if (response.status === 409 && (body.error === "generation_changed" || body.code === "generation_changed") && !refreshedGenerations.has(refreshKey)) {
            refreshedGenerations.add(refreshKey);
            if (refreshedGenerations.size > 16) refreshedGenerations.delete(refreshedGenerations.values().next().value);
            refreshPreparedBoard();
          }
          const error = new Error(response.status === 409 ? "The board changed. Try again to refresh player data." : "Player details could not load. Try again.");
          error.status = response.status;
          error.body = body;
          throw error;
        }
        if (body.schemaVersion !== 1 || body.generation !== generation || !body.player || body.player.readModelKey !== playerKey || (body.meta?.leagueKey && body.meta.leagueKey !== leagueKey)) {
          throw new Error("Player details did not match this board. Refresh the board.");
        }
        if (requestEpoch !== epoch) throw new Error("Player context changed. Open the player again.");
        details.set(cacheKey, body);
        if (details.size > 64) details.delete(details.keys().next().value);
        return body;
      })();
      requests.set(cacheKey, request);
      // Remove only our own request; auth/league changes may replace it.
      request.finally(() => { if (requests.get(cacheKey) === request) requests.delete(cacheKey); }).catch(() => {});
    }
    payload = await request;
  }
  return materializePlayerDetail(row, payload.player);
}
