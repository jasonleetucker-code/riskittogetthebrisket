"use client";

/**
 * PerfectWaiversPanel — the jointly optimal add/drop COMBINATION (C7-WAIV-01).
 *
 * Display only.  The plan is solved server-side by
 * ``src/trade/perfect_waivers.py`` (POST /api/waiver/perfect) against the
 * canonical board, the exact lineup solver, the cut-ladder owner, roster
 * capacity, the FAAB engine and the user's trade protections.  This file
 * formats that payload and decides nothing: no value, bid, legality or stop
 * decision is computed here (the no-frontend-engine rule).
 *
 * Loaded on demand from /waivers (React.lazy, per-panel Suspense,
 * ResilientSection recovery="reload") so it costs the page's initial chunk
 * nothing.  Advice only — it never submits a claim.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  DataTable,
  EmptyState,
  FailureState,
  Panel,
  SkeletonTable,
} from "@/components/ds";
import styles from "@/app/waivers/waivers.module.css";

const ENDPOINT = "/api/waiver/perfect";

const POOL_REASON_LABEL = {
  below_min_value: "below the value floor",
  single_source: "single-source",
  kicker_def_excluded: "K/DEF",
  rookie_gate: "pre-draft rookies",
  unpriced: "unpriced",
  position_not_offered: "other positions",
};

const FAILURE_COPY = {
  data_not_ready: "This league's rosters haven't loaded yet.",
  unknown_team: "That team isn't in this league's rosters.",
  team_required: "Pick your team to plan waivers.",
  perfect_waivers_unavailable: "The waiver optimizer couldn't finish this plan.",
};

/** Fetch one team's plan.  Any failure is a stated state, never a blank. */
export function usePerfectWaivers({ leagueKey, ownerId, enabled = true } = {}) {
  const identity = JSON.stringify([leagueKey || "", ownerId || "", enabled]);
  const [state, setState] = useState({ identity: null, payload: null, failure: null });

  useEffect(() => {
    if (!enabled || !ownerId) {
      setState({ identity, payload: null, failure: null });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    setState({ identity, payload: null, failure: null, loading: true });
    (async () => {
      try {
        const res = await fetch(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ctl.signal,
          body: JSON.stringify({ leagueKey: leagueKey || undefined, teamOwnerId: ownerId }),
        });
        const json = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !json || typeof json !== "object") {
          const code = json?.error || "";
          setState({
            identity,
            payload: null,
            failure: {
              kind: res.status === 401 ? "auth" : res.status >= 500 ? "unavailable" : "degraded",
              message: FAILURE_COPY[code] || (code ? `Unavailable (${code}).` : "Unavailable."),
            },
          });
          return;
        }
        // A late answer for a different league or team must never render.
        const stale =
          (leagueKey && json.leagueKey && json.leagueKey !== leagueKey) ||
          (json.team?.ownerId && String(json.team.ownerId) !== String(ownerId));
        setState({ identity, payload: stale ? null : json, failure: null });
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState({
          identity,
          payload: null,
          failure: { kind: "offline", message: "Couldn't reach the waiver optimizer." },
        });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, leagueKey, ownerId, identity]);

  const current = state.identity === identity;
  return {
    payload: current ? state.payload : null,
    failure: current ? state.failure : null,
    loading: Boolean(enabled && ownerId) && (!current || Boolean(state.loading)),
  };
}

function fmtValue(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

function fmtGain(v) {
  const n = Math.round(Number(v));
  if (!Number.isFinite(n)) return "—";
  return n > 0 ? `+${n.toLocaleString()}` : n.toLocaleString();
}

function fmtPct(v) {
  const n = Number(v);
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
}

function fmtDollars(v) {
  const n = Number(v);
  return Number.isFinite(n) ? `$${Math.round(n)}` : "—";
}

function PlayerCell({ player }) {
  if (!player) return <span className={styles.playerMeta}>—</span>;
  return (
    <span className={styles.playerCell}>
      <Badge tone="outline">{player.position || "?"}</Badge>
      <span className={styles.playerName}>{player.name || "—"}</span>
      <span className={styles.playerMeta}>{fmtValue(player.value)}</span>
    </span>
  );
}

function ReleaseCell({ release }) {
  if (release?.kind === "openSpot") {
    return <span className={styles.playerMeta}>Open roster spot</span>;
  }
  return <PlayerCell player={release} />;
}

function stopSentence(stopRule) {
  const ratio = Number(stopRule?.agreementRatio);
  const band = Number.isFinite(ratio) ? `${Math.round(ratio * 100)}%` : "declared";
  const next = stopRule?.nextBestMove;
  if (!next) return `Stopped: no free agent left that improves the roster.`;
  const release =
    next.release?.kind === "openSpot" ? "an open spot" : next.release?.name || "a roster player";
  if (next.reason === "within_uncertainty") {
    return (
      `Stopped: the next best move — add ${next.add?.name} for ${release} — gains ` +
      `${fmtGain(next.gain)}, but the two are ${fmtPct(next.relativeGap)} apart, inside the ` +
      `${band} stop band, where the two values are too close to call.`
    );
  }
  return (
    `Stopped: the next best move — add ${next.add?.name} for ${release} — would not gain ` +
    `value (${fmtGain(next.gain)}).`
  );
}

export default function PerfectWaiversPanel({ leagueKey, ownerId }) {
  const { payload, failure, loading } = usePerfectWaivers({ leagueKey, ownerId });

  const columns = useMemo(
    () => [
      {
        key: "rank",
        header: "#",
        numeric: true,
        align: "center",
        render: (_m, i) => i + 1,
      },
      {
        key: "add",
        header: "Add",
        accessor: (m) => m.add?.name,
        render: (m) => <PlayerCell player={m.add} />,
      },
      {
        key: "release",
        header: "In place of",
        accessor: (m) => m.release?.name || "",
        render: (m) => <ReleaseCell release={m.release} />,
      },
      {
        key: "gain",
        header: "Gain",
        numeric: true,
        accessor: (m) => m.gain,
        render: (m) => fmtGain(m.gain),
      },
      {
        key: "bid",
        header: "Bid",
        numeric: true,
        accessor: (m) => m.add?.bid?.recommended,
        render: (m) => fmtDollars(m.add?.bid?.recommended),
        headerInfo:
          "The FAAB engine's recommended bid for this add on its own. The plan keeps the sum of these within your balance.",
      },
      {
        key: "gap",
        header: "Apart",
        numeric: true,
        hideBelow: "md",
        accessor: (m) => m.relativeGap,
        render: (m) => (m.relativeGap == null ? "—" : fmtPct(m.relativeGap)),
        headerInfo:
          "How far apart the add and the release are in value. Every move clears the declared stop band; an add into an open spot has nothing to compare.",
      },
    ],
    [],
  );

  function renderBody() {
    if (failure) return <FailureState variant="block" failure={failure} />;
    if (loading || !payload) return <SkeletonTable rows={4} columns={5} />;

    const plan = payload.plan || {};
    const moves = Array.isArray(plan.moves) ? plan.moves : [];
    const solver = payload.solver || {};
    const budget = payload.budget || {};
    const unpriced = payload.unpriced || {};
    const unpricedRoster = Array.isArray(unpriced.rosterPlayers) ? unpriced.rosterPlayers : [];
    const notes = Array.isArray(payload.notes) ? payload.notes : [];
    const protectedRows = payload.constraints?.protectedOnRoster || [];
    const poolFilters = payload.freeAgentExclusions?.waiverPool || {};
    const poolFiltered = Object.entries(poolFilters).filter(([, n]) => Number(n) > 0);
    const ambiguous = payload.freeAgentExclusions?.identityAmbiguous || [];
    const unpaired = moves.filter((m) => m.standsAlone === false).length;

    const budgetText =
      budget.state === "known"
        ? `${fmtDollars(plan.totalRecommendedBid)} of ${fmtDollars(budget.balance)} FAAB`
        : "FAAB balance unknown — paid claims withheld";

    return (
      <>
        {solver.provenOptimal === false ? (
          <Banner tone="warning" title="Best plan found, not proven optimal">
            The search reached its limit before it could prove nothing better exists.
          </Banner>
        ) : null}
        {notes.length > 0 ? (
          <Banner tone="info" title="Read before claiming">
            <ul className={styles.notes}>
              {notes.map((n) => (
                <li key={n} className={styles.note}>
                  {n}
                </li>
              ))}
            </ul>
          </Banner>
        ) : null}
        <div className={styles.freshness} data-testid="perfect-waivers-summary">
          <span>
            Net gain <strong className="ds-mono">{fmtGain(plan.netValueGain)}</strong>
          </span>
          <span>
            {fmtValue(plan.addCount)} add{plan.addCount === 1 ? "" : "s"} · {fmtValue(plan.dropCount)} drop
            {plan.dropCount === 1 ? "" : "s"}
          </span>
          <span>{budgetText}</span>
          <span>
            Starters filled {plan.startersFilledBefore}→{plan.startersFilledAfter} of{" "}
            {plan.starterSlots}
          </span>
          {solver.provenOptimal ? <Badge tone="positive">Proven optimal</Badge> : null}
        </div>
        <DataTable
          caption="Perfect Waivers plan: each add paired with the release it replaces, best gain first"
          columns={columns}
          rows={moves}
          rowKey={(m) => `${m.add?.playerId}::${m.release?.playerId || "open"}`}
          density="compact"
          presorted
          emptyState={
            <EmptyState
              title="No move clears the bar"
              description="Nothing on the wire beats a roster spot by more than the declared stop band."
            />
          }
        />
        <p className={styles.explanation}>{stopSentence(payload.stopRule)}</p>
        <ul className={styles.notes}>
          {protectedRows.length > 0 ? (
            <li className={styles.note}>
              Protected, never proposed as drops: {protectedRows.map((r) => r.name).join(", ")}.
            </li>
          ) : null}
          {unpricedRoster.length > 0 ? (
            <li className={styles.note}>
              Unpriced on your roster — value unknown, never proposed as drops:{" "}
              {unpricedRoster.map((r) => r.name).join(", ")}.
            </li>
          ) : null}
          {poolFiltered.length > 0 ? (
            <li className={styles.note}>
              Outside the waiver pool&apos;s rules (not considered):{" "}
              {poolFiltered
                .map(([reason, n]) => `${n} ${POOL_REASON_LABEL[reason] || reason}`)
                .join(", ")}
              .
            </li>
          ) : null}
          {ambiguous.length > 0 ? (
            <li className={styles.note}>
              Not considered — name matches more than one player: {ambiguous.join(", ")}.
            </li>
          ) : null}
          {Number(unpriced.freeAgents) > 0 ? (
            <li className={styles.note}>
              {unpriced.freeAgents} free agent{Number(unpriced.freeAgents) === 1 ? "" : "s"} the
              board has not priced were not considered.
            </li>
          ) : null}
          <li className={styles.note}>
            {unpaired > 0
              ? `${unpaired} pair${unpaired === 1 ? "" : "s"} could not be matched so that each claim stands alone — submit those together.`
              : "Each pair is matched so that if only that claim fails, or only that claim wins, your lineup still fills as many starting slots."}{" "}
            Advice only — no claim is submitted.
          </li>
        </ul>
      </>
    );
  }

  return (
    <Panel
      flush
      title="Perfect Waivers"
      subtitle="The best combination of adds and drops for your whole roster, within your FAAB."
    >
      {renderBody()}
    </Panel>
  );
}
