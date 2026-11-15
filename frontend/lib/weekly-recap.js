// Single owner of the weekly-recap lookup.  The backend publishes only
// ``weeklyRecap.weeks`` (each entry carries ``season`` and ``week``); the
// former duplicate ``byKey`` map was removed from the public payload.
// Key format is ``"<season>:<week>"``; on a (never observed) duplicate key
// the later entry wins, matching the retired backend map.

export function weeklyRecapKey(season, week) {
  return `${season}:${week}`;
}

export function indexWeeklyRecaps(data) {
  const index = {};
  const weeks = Array.isArray(data?.weeks) ? data.weeks : [];
  for (const recap of weeks) {
    if (!recap || recap.season == null || recap.week == null) continue;
    index[weeklyRecapKey(recap.season, recap.week)] = recap;
  }
  return index;
}

export function findWeeklyRecap(data, season, week) {
  return indexWeeklyRecaps(data)[weeklyRecapKey(season, week)] || null;
}
