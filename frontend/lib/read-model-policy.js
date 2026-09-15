// Build-time rollout gate. Keep legacy routes on their existing representation
// until prepared/full consumer parity and browser measurements are accepted.
export function preparedReadModelsEnabled() {
  return process.env.NEXT_PUBLIC_PREPARED_READ_MODELS === "1";
}

export function preparedReadModel(value) {
  return preparedReadModelsEnabled() && ["rankings", "trade", "catalog"].includes(value)
    ? value : null;
}

export function readModelForRoute(pathname) {
  if (pathname === "/rankings") return preparedReadModel("rankings");
  if (pathname === "/trade") return preparedReadModel("trade");
  return null;
}

export function usesIntentCatalog(pathname) {
  return preparedReadModelsEnabled() &&
    ["/bdvm", "/game-day", "/league-comparison"].includes(pathname);
}

export const READ_MODEL_URLS = {
  rankings: "/api/read-models/rankings",
  trade: "/api/read-models/trade/context",
  catalog: "/api/read-models/players/catalog",
};
