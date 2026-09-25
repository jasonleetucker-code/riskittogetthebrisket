/**
 * game-day-view — presentation helpers for the Game Day surface.
 *
 * PURE RENDER HELPERS, NOT A SECOND ENGINE. Every number the Game Day page
 * shows is produced by the backend (`GET /api/matchup/intel`, assembled by
 * `src/api/matchup_intel.py` from the canonical simulation, lineup, scoring
 * and live-state owners). What lives here is formatting, labelling and
 * selection of backend fields:
 *
 *  - formatting a number the backend computed (never re-deriving one);
 *  - naming a backend state/reason in plain language;
 *  - choosing WHICH backend rows to show (filtering on a backend field and
 *    ordering by a backend field). No probability, lineup, score, margin,
 *    remaining-production or leverage arithmetic happens in this module —
 *    `tests: game-day-view.test.js` pins that the selectors only pass
 *    backend values through.
 *
 * MISSING IS NEVER ZERO. Every formatter returns `null` for a missing input,
 * and callers render an explicit "unavailable"/"paused" word for it, never
 * "0.0" or "0%".
 */

// ── Numbers ──────────────────────────────────────────────────────────────

export function formatPoints(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : null;
}

/** A backend percentage (0-100) to one decimal: "61.5%". */
export function formatPct(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : null;
}

/**
 * A backend lineup percentage (0-100) for a reader: whole numbers, with the
 * open ends kept honest — 99.6% is not "certain" and 0.3% is not "never".
 */
export function formatLineupPct(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value <= 0) return "0%";
  if (value >= 100) return "100%";
  if (value < 1) return "<1%";
  if (value > 99) return ">99%";
  return `${Math.round(value)}%`;
}

/**
 * The backend's own signed expected margin, as "Team A by 42.4". The sign
 * decides only WHICH name leads; the magnitude is the backend value.
 */
export function marginText(margin, teamName, opponentName) {
  if (typeof margin !== "number" || !Number.isFinite(margin)) return null;
  if (margin === 0) return "Dead even";
  const leader = margin > 0 ? teamName : opponentName;
  return `${leader || "—"} by ${Math.abs(margin).toFixed(1)}`;
}

// ── Time ─────────────────────────────────────────────────────────────────

/** Epoch seconds, epoch ms or an ISO string -> Date, else null. */
export function toDate(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Date(value < 1e12 ? value * 1000 : value);
  }
  const parsed = Date.parse(String(value));
  return Number.isNaN(parsed) ? null : new Date(parsed);
}

const ET = "America/New_York";

export function formatClockTime(value) {
  const d = toDate(value);
  if (!d) return null;
  try {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZone: ET,
      timeZoneName: "short",
    }).format(d);
  } catch {
    return null;
  }
}

export function formatKickoff(value) {
  const d = toDate(value);
  if (!d) return null;
  try {
    return new Intl.DateTimeFormat("en-US", {
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      timeZone: ET,
      timeZoneName: "short",
    }).format(d);
  } catch {
    return null;
  }
}

export function formatDateTime(value) {
  const d = toDate(value);
  if (!d) return null;
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: ET,
      timeZoneName: "short",
    }).format(d);
  } catch {
    return null;
  }
}

// ── Labels ───────────────────────────────────────────────────────────────

/** The matchup-level state machine (`payload.mode`), in the owner's words. */
export function matchupStateLabel(mode) {
  if (mode === "pregame") return "Upcoming";
  if (mode === "live") return "Live";
  if (mode === "final") return "Final";
  return "Status unknown";
}

const SLOT_LABELS = { SUPER_FLEX: "SF", REC_FLEX: "FLEX", IDP_FLEX: "IDP" };

export function slotLabel(slot) {
  return SLOT_LABELS[slot] || slot || "—";
}

export function positionLabel(player) {
  const positions = Array.isArray(player?.fantasyPositions) ? player.fantasyPositions : [];
  return positions.length ? positions.join("/") : null;
}

export function gameLabel(game) {
  if (!game) return null;
  return `${game.awayTeam || "?"} @ ${game.homeTeam || "?"}`;
}

function clockText(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function periodLabel(period) {
  if (typeof period !== "number" || period < 1) return null;
  return period > 4 ? "OT" : `Q${period}`;
}

/**
 * One NFL game's status line from the backend's observed phase / period /
 * clock (`nflSlate.games[]`). When no live phase was observed, the
 * schedule-derived `state` is named as such — never dressed up as live.
 */
export function gameStatusText(game) {
  if (!game) return "Status unknown";
  const phase = game.phase;
  const period = periodLabel(game.period);
  const kickoff = formatKickoff(game.kickoffAt);
  const stale = game.remainingReason === "stale_live_state" ? " · feed stale" : "";
  switch (phase) {
    case "SCHEDULED":
      return kickoff || "Scheduled";
    case "IN_PROGRESS": {
      const clock = clockText(game.clockSeconds);
      return [period, clock].filter(Boolean).join(" ") + stale || `In progress${stale}`;
    }
    case "END_PERIOD":
      return `${period ? `End ${period}` : "End of quarter"}${stale}`;
    case "HALFTIME":
      return `Halftime${stale}`;
    case "FINAL":
      return period === "OT" ? "Final/OT" : "Final";
    case "DELAYED":
      return "Delayed";
    case "POSTPONED":
      return "Postponed";
    case "CANCELED":
      return "Canceled";
    case "UNKNOWN":
      return "Status unknown";
    default:
      break;
  }
  if (game.state === "not_started") return kickoff || "Scheduled";
  if (game.state === "completed") return "Final";
  if (game.state === "in_progress") return "In progress";
  return "Status unknown";
}

/** "live" | "final" | "upcoming" | "halted" | "unknown" — for row emphasis. */
export function gamePhaseKind(game) {
  const phase = game?.phase;
  if (phase === "FINAL" || (!phase && game?.state === "completed")) return "final";
  if (phase === "DELAYED" || phase === "POSTPONED" || phase === "CANCELED") return "halted";
  if (phase === "SCHEDULED" || (!phase && game?.state === "not_started")) return "upcoming";
  if (
    phase === "IN_PROGRESS" ||
    phase === "END_PERIOD" ||
    phase === "HALFTIME" ||
    (!phase && game?.state === "in_progress")
  ) {
    return "live";
  }
  return "unknown";
}

//: Why a player's remaining production (and so the win chance) is withheld.
//: Keys are the backend reason vocabulary (`src/ros/game_day_week.py`,
//: `src/nfl_data/live_game_state.py`).
const REASON_TEXT = {
  overtime: "Overtime",
  overtime_possible: "Tied at the end of regulation (overtime possible)",
  delayed: "Delay",
  postponed: "Postponed",
  canceled: "Canceled",
  stale_live_state: "Live game feed is stale",
  clock_missing: "Game clock not reported",
  period_missing: "Quarter not reported",
  clock_out_of_range: "Game clock unreadable",
  live_progress_unknown: "Game progress unknown",
  wall_time_exhausted_without_observed_final: "Game ran long with no final observed",
  no_kickoff_evidence: "Kickoff time unknown",
};

export function reasonText(reason) {
  if (!reason) return null;
  if (REASON_TEXT[reason]) return REASON_TEXT[reason];
  if (String(reason).startsWith("unknown_status")) return "Unrecognized game status";
  return String(reason).replaceAll("_", " ");
}

const PLAYER_STATE_TEXT = {
  not_started: "Not started",
  in_progress: "Playing",
  completed: "Game finished",
  inactive: "Out",
  unknown: "Status unknown",
};

export function playerStateText(state) {
  return PLAYER_STATE_TEXT[state] || "Status unknown";
}

// ── Lookups over the payload ─────────────────────────────────────────────

export function slateGameById(payload) {
  const out = new Map();
  for (const g of payload?.nflSlate?.games || []) out.set(g.gameId, g);
  return out;
}

/** playerId -> { player, side: "team" | "opponent" } across both sides. */
export function playerIndex(payload) {
  const out = new Map();
  for (const sideKey of ["team", "opponent"]) {
    for (const p of payload?.[sideKey]?.players || []) {
      out.set(p.playerId, { player: p, side: sideKey });
    }
  }
  return out;
}

/**
 * Plain-language sentences for a withheld win chance: which football we
 * cannot see and why. Built from `progressUnavailableReasons`,
 * `unknownStatePlayerIds` and `probabilityState`; never a number.
 */
export function withheldProbabilityReasons(payload) {
  if (!payload || payload.mode === "final") return [];
  const state = payload.probabilityState;
  if (state === "AVAILABLE" || state === "FINAL") return [];
  const players = playerIndex(payload);
  const games = slateGameById(payload);
  const gamesFor = (ids) => {
    const labels = [];
    for (const id of ids || []) {
      const gid = players.get(id)?.player?.nflGameId;
      const label = gameLabel(games.get(gid));
      if (label && !labels.includes(label)) labels.push(label);
    }
    return labels;
  };
  const out = [];
  for (const [reason, ids] of Object.entries(payload.progressUnavailableReasons || {})) {
    const labels = gamesFor(ids);
    const where = labels.length ? ` in ${labels.join(", ")}` : "";
    out.push(`${reasonText(reason)}${where}: win chance paused.`);
  }
  const unknown = payload.unknownStatePlayerIds || [];
  if (unknown.length) {
    const labels = gamesFor(unknown);
    const where = labels.length ? ` for ${labels.join(", ")}` : "";
    const live = payload?.lineage?.liveGameState?.state;
    const why =
      live === "disabled"
        ? "the live game feed is off"
        : live === "unavailable"
          ? "the live game feed is unavailable"
          : live === "observed"
            ? "the live game feed did not report it"
            : "no live game status was observed";
    const named = labels.length ? "" : ` (${unknown.length} player${unknown.length === 1 ? "" : "s"})`;
    out.push(`Game status unknown${where}${named} — ${why}: win chance paused.`);
  }
  if (!out.length) {
    out.push(
      state === "UNAVAILABLE"
        ? "No projection could price this week: win chance unavailable."
        : "Game-state or scoring evidence is incomplete: win chance paused.",
    );
  }
  return out;
}

// ── Best-ball selections (filters + orderings on backend fields only) ────

/** Ids the canonical lineup says are counting now (live/final) or projected to (pregame). */
export function countingPlayerIds(side, mode) {
  const slots =
    mode === "pregame" ? side?.expectedLineup?.slots || [] : side?.actualLineup?.slots || [];
  return new Set(slots.map((s) => s.playerId));
}

function hasPct(p) {
  return typeof p?.finalLineupPct === "number" && Number.isFinite(p.finalLineupPct);
}

/**
 * "Could enter": players NOT in the current/illustrative lineup whose
 * simulated chance of making the FINAL best-ball lineup is above zero and
 * below certain. Ordered by that backend percentage, highest first.
 */
export function couldEnterPlayers(side, mode) {
  const counting = countingPlayerIds(side, mode);
  return (side?.players || [])
    .filter((p) => !counting.has(p.playerId) && hasPct(p))
    .filter((p) => p.finalLineupPct > 0 && p.finalLineupPct < 100)
    .sort((a, b) => b.finalLineupPct - a.finalLineupPct);
}

/**
 * Counting now but not certain to stay: players in the CURRENT scoring
 * lineup whose final-lineup percentage is below 100 (a teammate still to
 * play can displace them). Live only. Lowest percentage first.
 */
export function displaceablePlayers(side, mode) {
  if (mode !== "live") return [];
  const counting = countingPlayerIds(side, mode);
  return (side?.players || [])
    .filter((p) => counting.has(p.playerId) && hasPct(p) && p.finalLineupPct < 100)
    .sort((a, b) => a.finalLineupPct - b.finalLineupPct);
}

export function finishedPlayers(side) {
  return (side?.players || []).filter((p) => p.state === "completed");
}

/** Leverage rows with a stated leverage, in the backend's own order (strongest first). */
export function leverageGames(payload, limit = 3) {
  const games = slateGameById(payload);
  return (payload?.team?.outcome?.gameLeverage || [])
    .filter((row) => typeof row.leverage === "number" && Number.isFinite(row.leverage))
    .slice(0, limit)
    .map((row) => ({ ...row, game: games.get(row.gameId) || null }));
}

/**
 * What matters now — at most five evidence-backed items, every one read
 * from a backend field. Nothing is emitted that the payload cannot support.
 */
export function whatMattersNow(payload) {
  if (!payload || payload.mode === "final") return [];
  const items = [];
  const team = payload.team;
  const opponent = payload.opponent;
  for (const row of leverageGames(payload, 2)) {
    const label = gameLabel(row.game) || row.gameId;
    const mine = (row.teamPlayerIds || []).length;
    const theirs = (row.opponentPlayerIds || []).length;
    items.push({
      kind: "game",
      key: `game-${row.gameId}`,
      title: label,
      status: row.game ? gameStatusText(row.game) : null,
      detail:
        `Win chance ${formatPct(row.winPctWhenGameFavorsTeam) ?? "—"} if this game goes your way, ` +
        `${formatPct(row.winPctWhenGameFavorsOpponent) ?? "—"} if it goes theirs`,
      meta: `${mine} of yours · ${theirs} of theirs`,
    });
  }
  for (const p of couldEnterPlayers(team, payload.mode).slice(0, 2)) {
    items.push({
      kind: "could-enter",
      key: `enter-${p.playerId}`,
      title: p.name,
      status: playerStateText(p.state),
      detail: `Could enter: ${formatLineupPct(p.finalLineupPct)} to make your final lineup`,
      meta: positionLabel(p),
    });
  }
  const atRisk = displaceablePlayers(team, payload.mode)[0];
  if (atRisk) {
    items.push({
      kind: "at-risk",
      key: `risk-${atRisk.playerId}`,
      title: atRisk.name,
      status: playerStateText(atRisk.state),
      detail: `Counting now (${formatPoints(atRisk.pointsScored) ?? "score unavailable"}) — ${formatLineupPct(atRisk.finalLineupPct)} to stay in your final lineup`,
      meta: positionLabel(atRisk),
    });
  }
  const opponentThreat = couldEnterPlayers(opponent, payload.mode)[0];
  if (opponentThreat && items.length < 5) {
    items.push({
      kind: "opponent",
      key: `opp-${opponentThreat.playerId}`,
      title: opponentThreat.name,
      status: playerStateText(opponentThreat.state),
      detail: `Opponent could enter: ${formatLineupPct(opponentThreat.finalLineupPct)} to make their final lineup`,
      meta: positionLabel(opponentThreat),
    });
  }
  return items.slice(0, 5);
}

// ── Freshness ────────────────────────────────────────────────────────────

/**
 * One concise freshness line for the hero. Reads the collector's
 * `freshness` block when the payload carries one (Game Day U5), otherwise
 * the lineage the endpoint already publishes. Fetch time is never
 * presented as content freshness: the live feed's OBSERVED time is.
 */
export function freshnessLine(payload) {
  const f = payload?.freshness;
  if (f && typeof f === "object") {
    const at = formatClockTime(f.observedAt ?? f.computedAt ?? f.fetchedAt);
    const state = String(f.state || "").toLowerCase();
    const word =
      state === "fresh" || state === "current"
        ? "Updated"
        : state === "stale"
          ? "Stale — last updated"
          : state
            ? `${state[0].toUpperCase()}${state.slice(1)} — last updated`
            : "Updated";
    return { text: at ? `${word} ${at}` : `${word} (time unavailable)`, stale: state === "stale" };
  }
  const lineage = payload?.lineage || {};
  if (payload?.mode === "final") return { text: "Final scoring", stale: false };
  if (payload?.mode === "pregame") {
    const weekly = lineage.weeklyProjection || {};
    if (weekly.state === "ok") {
      const at = formatDateTime(weekly.asOf || weekly.observedAt);
      return { text: at ? `Projections as of ${at}` : "Weekly projections loaded", stale: false };
    }
    return { text: "Weekly projections unavailable — preseason fallback where priced", stale: true };
  }
  const live = lineage.liveGameState || {};
  const at = formatClockTime(live.observedAt);
  if (live.state === "observed" && live.stale) {
    return { text: `Live game feed stale${at ? ` since ${at}` : ""}`, stale: true };
  }
  if (live.state === "observed") {
    return { text: at ? `Live game status observed ${at}` : "Live game status observed", stale: false };
  }
  if (live.state === "disabled") {
    return { text: "Live game feed off — game status from the schedule only", stale: true };
  }
  return { text: "Live game feed unavailable — game status from the schedule only", stale: true };
}
