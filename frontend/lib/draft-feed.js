/** One page's concurrent draft-capital consumers share one request and parse.
 * No result TTL: an explicit later sync still requests a fresh response.
 */
export function createDraftCapitalLoader(fetcher = (...args) => fetch(...args)) {
  const pending = new Map();
  return function loadDraftCapital(leagueKey = "") {
    if (pending.has(leagueKey)) return pending.get(leagueKey);
    const params = new URLSearchParams();
    if (leagueKey) params.set("leagueKey", leagueKey);
    const qs = params.toString();
    const promise = Promise.resolve()
      .then(() => fetcher(`/api/draft-capital${qs ? `?${qs}` : ""}`, { cache: "no-store" }))
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data?.error) throw new Error(data.error);
        return data;
      })
      .finally(() => {
        if (pending.get(leagueKey) === promise) pending.delete(leagueKey);
      });
    pending.set(leagueKey, promise);
    return promise;
  };
}

/** A missing/mismatched contract is pending, never an empty ready team map. */
export function draftTeamsFromContract(contract, leagueKey, loading = false) {
  if (loading || !contract || contract.meta?.sleeperDataReady === false) return null;
  const contractLeague = contract.meta?.leagueKey || contract.leagueKey || "";
  if (leagueKey && contractLeague && leagueKey !== contractLeague) return null;
  return Array.isArray(contract.sleeper?.teams) ? contract.sleeper.teams : null;
}
