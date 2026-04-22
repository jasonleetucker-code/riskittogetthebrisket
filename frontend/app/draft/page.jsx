"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthContext } from "@/app/AppShellWrapper";
import {
  DRAFT_STORAGE_KEY,
  DEFAULT_AGGRESSION,
  DEFAULT_ENFORCE_PCT,
  TAG_AVOID,
  TAG_TARGET,
  TIER_DEFS,
  addPlayer,
  bidStatus,
  computeDraftStats,
  computeHistorySeries,
  createDefaultWorkspace,
  cycleTag,
  hydrateWorkspace,
  mergeDraftCapitalTeams,
  nextBestTargets,
  nominationCandidates,
  playerRecommendation,
  playerSlug,
  recordPick,
  removePick,
  removePlayer,
  setPlayerTag,
  undoLastPick,
  updatePlayerPreDraft,
  updateSettings,
  updateTeam,
  workspaceIsPristine,
} from "@/lib/draft-logic";

const TIER_LABELS = Object.fromEntries(TIER_DEFS.map((t) => [t.key, t.label]));

// Short labels + CSS classes for the recommendation chip on each row.
// Kept in one place so the color language is consistent between the
// board, the Next Best Target sidebar, and the draft modal.
const REC_CHIP = {
  lock: { text: "LOCK", cls: "draft-rec-lock" },
  steal: { text: "STEAL", cls: "draft-rec-steal" },
  push: { text: "PUSH", cls: "draft-rec-push" },
  buy: { text: "BUY", cls: "draft-rec-buy" },
  spend: { text: "SPEND", cls: "draft-rec-spend" },
  avoid: { text: "AVOID", cls: "draft-rec-avoid" },
  neutral: { text: "—", cls: "draft-rec-neutral" },
};

/* ── Utility formatters ───────────────────────────────────────────── */

function fmt$(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "−" : "";
  return `${sign}$${Math.round(Math.abs(n)).toLocaleString()}`;
}

function fmtPct(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtMultiplier(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n.toFixed(2)}×`;
}

/* ── Inflation stats strip ────────────────────────────────────────── */

function StatsStrip({ stats, historySeries }) {
  const stat = (label, value, title, extraClass = "", extra = null) => (
    <div
      className={`draft-stat ${extraClass}`.trim()}
      title={title || undefined}
    >
      <div className="draft-stat-label">{label}</div>
      <div className="draft-stat-value">{value}</div>
      {extra}
    </div>
  );

  const inflationClass =
    stats.inflation > 1.05
      ? "draft-stat-green"
      : stats.inflation < 0.95
        ? "draft-stat-red"
        : "";

  // Phase: 0 at draft start, →1 as my last pick approaches.  Shown as
  // "N of M slots left · P% pressure" so both the absolute slot count
  // and the pressure % are visible at a glance.
  const slotsPart = `${stats.mySlotsRemaining} of ${stats.myInitialSlots} slots`;
  const pressurePart = `${Math.round((stats.slotPressure || 0) * 100)}% pressure`;

  // Top rival ceiling — the real competitor cap driving myWinningBid.
  // Surfacing it in the strip teaches the user "this is the number to
  // beat, not some hypothetical".
  const rivalClass =
    stats.topCompetitorMax < 10
      ? "draft-stat-green" // rivals broke, I can steal anything
      : stats.topCompetitorMax > 150
        ? "draft-stat-red"
        : "";

  return (
    <div className="draft-stats">
      {stat(
        "Inflation",
        fmtMultiplier(stats.inflation),
        "RemainingLeague$ / (TotalAuction$ − Σ soldPreDraft). >1.00 means the remaining market is cheaper than projected; <1.00 means the remaining market got hot.  Sparkline shows trajectory over picks.",
        inflationClass,
        <InflationSparkline series={historySeries} width={138} height={28} />,
      )}
      {stat(
        "My remaining",
        fmt$(stats.myRemaining),
        `Starting ${fmt$(stats.myStarting)} − spent ${fmt$(stats.mySpent)} · ${slotsPart} left`,
      )}
      {stat(
        "Budget advantage",
        fmtMultiplier(stats.budgetAdvantage),
        `My remaining / avg per other team (${fmt$(stats.avgPerOtherTeam)}). Above 1.0 = I can afford to outbid the field average.`,
      )}
      {stat(
        "Top rival ceiling",
        fmt$(stats.topCompetitorMax),
        `The richest OTHER team can bid up to this much (slot-adjusted). Bid $1 above this to lock a player — anything more is overpay.`,
        rivalClass,
      )}
      {stat(
        "Phase",
        `${slotsPart}`,
        `${pressurePart}. MaxBid scales by phaseMultiplier ${fmtMultiplier(stats.phaseMultiplier)} to prevent unused $ at end of draft.`,
      )}
      {stat(
        "League $ left",
        fmt$(stats.remainingLeague),
        `Total auction $ still unspent across all teams. Starts at ${fmt$(
          stats.totalBudget,
        )}; drops as picks are recorded.`,
      )}
    </div>
  );
}

/* ── Team budgets panel ───────────────────────────────────────────── */

function TeamPanel({
  stats,
  workspace,
  onSettings,
  onTeam,
  onLoadCapital,
  capitalStatus,
}) {
  const confirmAndLoad = () => {
    const hasPicks = (workspace.picks || []).length > 0;
    if (hasPicks) {
      const ok =
        typeof window !== "undefined" &&
        window.confirm(
          "The draft is already in progress.  Loading fresh budgets from Draft Capital will reset every team's Initial $ to their carry-over balances — your picks stay, but any manual budget edits will be overwritten.  Continue?",
        );
      if (!ok) return;
      onLoadCapital({ force: true });
    } else {
      onLoadCapital({ force: true });
    }
  };

  return (
    <div className="card draft-team-panel">
      <div className="draft-panel-header">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          <div>
            <h3 style={{ margin: "0 0 4px" }}>Teams & budgets</h3>
            <div className="muted" style={{ fontSize: "0.72rem" }}>
              Budgets pre-fill from the live Draft Capital feed. Edit
              any row to match your carry-over balances; click{" "}
              <strong>Load from Draft Capital</strong> to re-pull.
            </div>
          </div>
          <button
            className="button"
            onClick={confirmAndLoad}
            disabled={capitalStatus.loading}
            title="Re-pull per-team auction $ from /api/draft-capital"
            style={{ borderColor: "var(--cyan)", color: "var(--cyan)" }}
          >
            {capitalStatus.loading ? "Loading…" : "↻ Load from Draft Capital"}
          </button>
        </div>
        {capitalStatus.info && (
          <div
            className="muted"
            style={{
              fontSize: "0.72rem",
              marginTop: 6,
              color: "var(--green)",
            }}
          >
            {capitalStatus.info}
          </div>
        )}
        {capitalStatus.error && (
          <div
            style={{
              fontSize: "0.72rem",
              marginTop: 6,
              color: "var(--red)",
            }}
          >
            Draft Capital error: {capitalStatus.error}
          </div>
        )}
        {capitalStatus.source?.season && !capitalStatus.error && (
          <div
            className="muted"
            style={{ fontSize: "0.68rem", marginTop: 4 }}
          >
            Source: {capitalStatus.source.season} Draft Capital · $
            {capitalStatus.source.totalBudget} total
          </div>
        )}
      </div>
      <div className="draft-team-list">
        <div className="draft-team-row draft-team-row-head">
          <span>Mine</span>
          <span>Team</span>
          <span>Initial</span>
          <span>Spent</span>
          <span>Remaining</span>
          <span title="Slots drafted / initial slots owned">Slots</span>
          <span
            title="Slot-adjusted effective $ — max single-bid this team can actually afford while still filling their other slots at $1 each."
          >
            Eff $
          </span>
          <span
            title="Marginal Dollar Value = remaining $ / slots remaining.  Higher = more $ per pick = buying power.  Shaded by pressure tier."
          >
            MDV
          </span>
          <span
            title="Overpay index = (Σ paid − Σ preDraft at pick time) / Σ preDraft. >0 overpayer, <0 value hunter, ~0 market-rational."
          >
            Over%
          </span>
        </div>
        {stats.teamStats.map((t) => {
          const effLow = t.effectiveBudget < 5;
          const slotsEmpty = t.slotsRemaining <= 0;
          // MDV heatmap: compare each team's MDV to the median across
          // non-bankrupt teams.  Red = meaningfully below median
          // (pressed for $); green = meaningfully above (flush).
          // Gray = near median.
          const mdvClass =
            slotsEmpty
              ? "draft-mdv-empty"
              : t.mdv >= 40
                ? "draft-mdv-high"
                : t.mdv >= 15
                  ? "draft-mdv-mid"
                  : "draft-mdv-low";
          const overpayClass =
            t.overpayIndex == null
              ? "muted"
              : t.overpayIndex > 0.1
                ? "draft-money-overpay"
                : t.overpayIndex < -0.1
                  ? "draft-money-value"
                  : "draft-money";
          const overpayText =
            t.overpayIndex == null
              ? "—"
              : `${t.overpayIndex > 0 ? "+" : ""}${(t.overpayIndex * 100).toFixed(0)}%`;
          return (
            <div
              key={t.idx}
              className={`draft-team-row${t.isMine ? " draft-team-mine" : ""}`}
            >
              <label className="draft-radio">
                <input
                  type="radio"
                  name="myTeam"
                  checked={t.isMine}
                  onChange={() => onSettings({ myTeamIdx: t.idx })}
                />
              </label>
              <input
                className="draft-inline-input"
                value={workspace.teams[t.idx]?.name ?? ""}
                onChange={(e) => onTeam(t.idx, { name: e.target.value })}
                placeholder={`Team ${t.idx + 1}`}
              />
              <input
                className="draft-inline-input draft-money-input"
                type="number"
                min="0"
                value={workspace.teams[t.idx]?.initialBudget ?? 0}
                onChange={(e) =>
                  onTeam(t.idx, {
                    initialBudget: Math.max(0, Number(e.target.value) || 0),
                  })
                }
              />
              <span className="draft-money">{fmt$(t.spent)}</span>
              <span
                className={`draft-money${
                  t.remaining < t.initialBudget * 0.25 ? " draft-money-low" : ""
                }`}
              >
                {fmt$(t.remaining)}
              </span>
              <span
                className={`draft-money${slotsEmpty ? " draft-money-low" : ""}`}
                title={`${t.slotsDrafted} drafted of ${t.initialSlots} owned`}
              >
                {t.slotsDrafted}/{t.initialSlots}
              </span>
              <span
                className={`draft-money${effLow ? " draft-money-low" : ""}`}
                title="Slot-adjusted effective $: what this team can actually bid on a single player while reserving $1 each for their remaining slots."
              >
                {fmt$(t.effectiveBudget)}
              </span>
              <span
                className={`draft-money draft-mdv ${mdvClass}`}
                title={`Marginal $/slot: ${fmt$(t.mdv)} over ${t.slotsRemaining} slot${t.slotsRemaining === 1 ? "" : "s"}`}
              >
                {slotsEmpty ? "—" : fmt$(t.mdv)}
              </span>
              <span
                className={overpayClass}
                style={{
                  fontFamily: "var(--mono, monospace)",
                  textAlign: "right",
                  fontSize: "0.76rem",
                }}
                title={
                  t.overpayIndex == null
                    ? "No picks yet"
                    : `Paid ${fmt$(t.spent)} vs expected ${fmt$(t.preDraftSum)}`
                }
              >
                {overpayText}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Bid-tuning sliders ───────────────────────────────────────────── */

function BidKnobs({ settings, onSettings }) {
  const aggression = Number.isFinite(settings.aggression)
    ? settings.aggression
    : DEFAULT_AGGRESSION;
  const enforcePct = Number.isFinite(settings.enforcePct)
    ? settings.enforcePct
    : DEFAULT_ENFORCE_PCT;
  return (
    <div className="card draft-knobs">
      <h3>Bid knobs</h3>
      <div className="draft-knob-row">
        <label>
          <span>
            Aggression{" "}
            <span className="muted" style={{ fontSize: "0.7rem" }}>
              — how much of the budget advantage to spend on stars
            </span>
          </span>
          <div className="draft-knob-control">
            <input
              type="range"
              min="0"
              max="0.3"
              step="0.01"
              value={aggression}
              onChange={(e) =>
                onSettings({ aggression: Number(e.target.value) })
              }
            />
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={aggression}
              onChange={(e) =>
                onSettings({ aggression: Number(e.target.value) })
              }
              className="draft-knob-number"
            />
          </div>
        </label>
      </div>
      <div className="draft-knob-row">
        <label>
          <span>
            Enforce % of fair{" "}
            <span className="muted" style={{ fontSize: "0.7rem" }}>
              — bid up to this fraction of fair to keep prices honest
            </span>
          </span>
          <div className="draft-knob-control">
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={enforcePct}
              onChange={(e) =>
                onSettings({ enforcePct: Number(e.target.value) })
              }
            />
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={enforcePct}
              onChange={(e) =>
                onSettings({ enforcePct: Number(e.target.value) })
              }
              className="draft-knob-number"
            />
          </div>
        </label>
      </div>
    </div>
  );
}

/* ── Draft-pick modal ─────────────────────────────────────────────── */

/**
 * One-line before → after preview for the bid simulator.  Color-
 * codes the delta: green when the change improves my position
 * (more $, higher BA, more slots), red when it hurts.  For
 * inflation the sign is inverted (lower inflation means my
 * money buys more later, so a negative delta renders green).
 */
function SimRow({ label, before, after, formatter, rawDelta = false }) {
  const delta = (Number(after) || 0) - (Number(before) || 0);
  let direction = 0;
  if (Math.abs(delta) > 0.001) direction = delta > 0 ? 1 : -1;
  const cls = rawDelta
    ? "draft-sim-delta-muted"
    : direction > 0
      ? "draft-sim-delta-up"
      : direction < 0
        ? "draft-sim-delta-down"
        : "";
  const signPrefix = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const magnitude = formatter(Math.abs(delta));
  const deltaText = direction === 0 ? "" : `(${signPrefix}${magnitude})`;
  return (
    <div className="draft-sim-row">
      <span className="muted">{label}</span>
      <span className="draft-money">{formatter(before)}</span>
      <span className="draft-sim-arrow">→</span>
      <span className="draft-money">{formatter(after)}</span>
      <span className={`draft-sim-delta ${cls}`}>{deltaText}</span>
    </div>
  );
}

function DraftModal({ player, workspace, stats, onClose, onSubmit }) {
  const existingPick = player?.pick;
  const [teamIdx, setTeamIdx] = useState(
    existingPick?.teamIdx ?? workspace.settings?.myTeamIdx ?? 0,
  );
  const [amount, setAmount] = useState(existingPick?.amount ?? "");
  const [liveBid, setLiveBid] = useState("");
  const liveStatus = useMemo(() => bidStatus(player, liveBid), [player, liveBid]);

  // Bid simulator: project the workspace forward with this pick
  // applied so the user can see the downstream effect before
  // committing.  Uses the SAME math path as the rest of the app
  // (computeDraftStats(recordPick(...))) so numbers match the live
  // board exactly post-commit.  Skips computation when amount is 0
  // or the pick is just being re-recorded unchanged (existing edit
  // that didn't move the needle).
  const simulated = useMemo(() => {
    const amt = Math.max(0, Number(amount) || 0);
    if (amt <= 0 || !player) return null;
    if (
      existingPick &&
      existingPick.teamIdx === Number(teamIdx) &&
      existingPick.amount === amt
    ) {
      return null;
    }
    const nextWs = recordPick(workspace, {
      playerId: player.id,
      teamIdx: Number(teamIdx),
      amount: amt,
    });
    return computeDraftStats(nextWs);
  }, [workspace, player, teamIdx, amount, existingPick]);

  // Re-focus the amount input on open so the user can start typing.
  useEffect(() => {
    const el = document.getElementById("draft-modal-amount");
    if (el) el.focus();
  }, []);

  if (!player) return null;

  function submit(e) {
    e?.preventDefault();
    const amt = Math.max(0, Number(amount) || 0);
    if (amt <= 0) {
      onClose();
      return;
    }
    onSubmit({ playerId: player.id, teamIdx: Number(teamIdx), amount: amt });
  }

  return (
    <div
      className="draft-modal-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <form
        className="draft-modal card"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
      >
        <div className="draft-modal-header">
          <h3>
            {existingPick ? "Edit pick" : "Mark drafted"}: {player.name}
          </h3>
          <button
            type="button"
            className="button-reset draft-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="draft-modal-body">
          <div className="draft-modal-refs">
            <div>
              <span className="muted">Tier · PreDraft $</span>
              <span className="draft-money">
                <span
                  className={`draft-tier-chip draft-tier-${player.tier}`}
                  style={{ marginRight: 6 }}
                >
                  {player.tier}
                </span>
                {fmt$(player.preDraft)}
              </span>
            </div>
            <div>
              <span className="muted">Inflated fair</span>
              <span className="draft-money">{fmt$(player.inflatedFair)}</span>
            </div>
            <div>
              <span className="muted">Win at</span>
              <span className="draft-money draft-money-win">
                {fmt$(player.myWinningBid)}
              </span>
            </div>
            <div>
              <span className="muted">My max bid (theoretical)</span>
              <span className="draft-money">{fmt$(player.myMaxBid)}</span>
            </div>
            <div>
              <span className="muted">Enforce up to</span>
              <span className="draft-money">{fmt$(player.enforceUpTo)}</span>
            </div>
            <div>
              <span className="muted">Top rival ceiling</span>
              <span className="draft-money">
                {fmt$(stats.topCompetitorMax)}
              </span>
            </div>
          </div>

          <label className="draft-modal-field">
            <span>Drafted to</span>
            <select
              className="select"
              value={teamIdx}
              onChange={(e) => setTeamIdx(Number(e.target.value))}
            >
              {workspace.teams.map((t, i) => (
                <option key={i} value={i}>
                  {t.name || `Team ${i + 1}`}
                  {i === workspace.settings?.myTeamIdx ? " (mine)" : ""}
                </option>
              ))}
            </select>
          </label>

          <label className="draft-modal-field">
            <span>Final price $</span>
            <input
              id="draft-modal-amount"
              type="number"
              className="input"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="e.g. 120"
            />
          </label>

          {(() => {
            // Overpay warning: red banner when the amount is going on
            // MY team AND exceeds myWinningBid.  No warning when
            // recording picks on rival teams (they overpaid, not me).
            const amt = Math.max(0, Number(amount) || 0);
            const isMine = Number(teamIdx) === workspace.settings?.myTeamIdx;
            const myCeiling = Number.isFinite(player.myWinningBid)
              ? player.myWinningBid
              : player.myMaxBid;
            if (amt > 0 && isMine && amt > myCeiling) {
              const diff = amt - myCeiling;
              return (
                <div className="draft-modal-warn">
                  <strong>Overpay.</strong> ${amt} is ${diff} above your
                  winning bid (${myCeiling}). The top rival can only
                  bid ${fmt$(stats.topCompetitorMax)} — you don't need
                  to pay more than ${myCeiling} to lock this player.
                </div>
              );
            }
            return null;
          })()}

          {/* Bid simulator — before/after preview of the key numbers
              this pick would change.  Surfaces "if I commit this, my
              BA drops from 5.85× to 3.24×" BEFORE you click Record,
              so regrets become rare. */}
          {simulated && (
            <div className="draft-modal-sim">
              <div
                className="muted"
                style={{ fontSize: "0.68rem", marginBottom: 4 }}
              >
                If recorded:
              </div>
              <div className="draft-sim-grid">
                <SimRow
                  label="League $ left"
                  before={stats.remainingLeague}
                  after={simulated.remainingLeague}
                  formatter={fmt$}
                />
                <SimRow
                  label="My remaining"
                  before={stats.myRemaining}
                  after={simulated.myRemaining}
                  formatter={fmt$}
                />
                <SimRow
                  label="My BA"
                  before={stats.budgetAdvantage}
                  after={simulated.budgetAdvantage}
                  formatter={(n) => `${n.toFixed(2)}×`}
                  rawDelta
                />
                <SimRow
                  label="Inflation"
                  before={stats.inflation}
                  after={simulated.inflation}
                  formatter={(n) => `${n.toFixed(2)}×`}
                  rawDelta
                />
                <SimRow
                  label="Top rival $"
                  before={stats.topCompetitorMax}
                  after={simulated.topCompetitorMax}
                  formatter={fmt$}
                />
                <SimRow
                  label="My slots left"
                  before={stats.mySlotsRemaining}
                  after={simulated.mySlotsRemaining}
                  formatter={(n) => `${n}`}
                  rawDelta
                />
              </div>
            </div>
          )}

          <div className="draft-modal-live">
            <div className="muted" style={{ fontSize: "0.72rem" }}>
              Or simulate a live bid to see the recommendation:
            </div>
            <div className="draft-live-row">
              <input
                type="number"
                className="input"
                min="0"
                value={liveBid}
                onChange={(e) => setLiveBid(e.target.value)}
                placeholder="Live bid $"
              />
              <span className={`draft-live-badge draft-live-${liveStatus.level}`}>
                {liveStatus.label || "—"}
              </span>
            </div>
          </div>
        </div>
        <div className="draft-modal-footer">
          {existingPick && (
            <button
              type="button"
              className="button button-danger"
              onClick={() => {
                onSubmit({ _remove: true, playerId: player.id });
              }}
            >
              Clear pick
            </button>
          )}
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          {(() => {
            const amt = Math.max(0, Number(amount) || 0);
            const isMine = Number(teamIdx) === workspace.settings?.myTeamIdx;
            const myCeiling = Number.isFinite(player.myWinningBid)
              ? player.myWinningBid
              : player.myMaxBid;
            const danger = amt > 0 && isMine && amt > myCeiling;
            return (
              <button
                type="submit"
                className="button"
                style={{
                  borderColor: danger ? "var(--red)" : "var(--cyan)",
                  color: danger ? "var(--red)" : "var(--cyan)",
                }}
                title={
                  danger
                    ? "You're about to overpay — double-check before committing."
                    : ""
                }
              >
                {existingPick
                  ? "Save"
                  : danger
                    ? "Record (overpay!)"
                    : "Record pick"}
              </button>
            );
          })()}
        </div>
      </form>
    </div>
  );
}

/* ── Rookie board ─────────────────────────────────────────────────── */

function RookieBoard({
  stats,
  workspace,
  onDraft,
  onEditPreDraft,
  onRemovePlayer,
  onCycleTag,
  searchInputRef,
  showDrafted,
  onShowDraftedChange,
  query,
  onQueryChange,
  tagFilter,
  onTagFilterChange,
  onAdd,
}) {
  const [sort, setSort] = useState({ col: "myWinningBid", asc: false });

  // Tag tabs — quick filter so the user can focus on targets during
  // live drafting without scrolling past everything.
  const tagCounts = useMemo(() => {
    let target = 0;
    let avoid = 0;
    let untagged = 0;
    for (const p of stats.enrichedPlayers) {
      if (p.drafted) continue;
      if (p.userTag === TAG_TARGET) target += 1;
      else if (p.userTag === TAG_AVOID) avoid += 1;
      else untagged += 1;
    }
    return { target, avoid, untagged, all: target + avoid + untagged };
  }, [stats.enrichedPlayers]);

  const filtered = useMemo(() => {
    let list = stats.enrichedPlayers;
    if (!showDrafted) list = list.filter((p) => !p.drafted);

    // Tag filter applies only to undrafted rows; drafted rows still
    // surface when ``showDrafted`` is on so history stays visible.
    if (tagFilter === "target") {
      list = list.filter((p) => p.drafted || p.userTag === TAG_TARGET);
    } else if (tagFilter === "avoid") {
      list = list.filter((p) => p.drafted || p.userTag === TAG_AVOID);
    } else if (tagFilter === "untagged") {
      list = list.filter((p) => p.drafted || !p.userTag);
    }

    const q = (query || "").trim().toLowerCase();
    if (q) list = list.filter((p) => p.name.toLowerCase().includes(q));
    const dir = sort.asc ? 1 : -1;
    return [...list].sort((a, b) => {
      switch (sort.col) {
        case "rank":
          return (a.rank - b.rank) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "preDraft":
          return (a.preDraft - b.preDraft) * dir;
        case "inflatedFair":
          return (a.inflatedFair - b.inflatedFair) * dir;
        case "enforceUpTo":
          return (a.enforceUpTo - b.enforceUpTo) * dir;
        case "myMaxBid":
          return (a.myMaxBid - b.myMaxBid) * dir;
        case "myWinningBid":
          return (a.myWinningBid - b.myWinningBid) * dir;
        case "final":
          return (
            ((a.pick?.amount ?? -1) - (b.pick?.amount ?? -1)) * dir
          );
        default:
          return 0;
      }
    });
  }, [stats.enrichedPlayers, sort, query, showDrafted, tagFilter]);

  // Tier-separator rows — only when the current sort groups by tier
  // naturally (rank or preDraft descending/ascending).  Scatter sorts
  // (win bid, fair) skip the dividers to avoid noise.
  const showTierDividers =
    (sort.col === "rank" && sort.asc) ||
    (sort.col === "preDraft" && !sort.asc);

  const teamName = (idx) =>
    workspace.teams[idx]?.name || `Team ${idx + 1}`;

  function th(label, col, width) {
    const active = sort.col === col;
    return (
      <th
        style={{ width, cursor: "pointer", userSelect: "none" }}
        onClick={() =>
          setSort((s) =>
            s.col === col ? { col, asc: !s.asc } : { col, asc: false },
          )
        }
      >
        {label}
        {active ? (sort.asc ? " ▲" : " ▼") : ""}
      </th>
    );
  }

  const tagTab = (key, label, count, color) => {
    const active = tagFilter === key;
    return (
      <button
        type="button"
        className={`draft-tag-tab${active ? " draft-tag-tab-active" : ""}`}
        style={{
          borderColor: active ? color : "var(--border)",
          color: active ? color : "var(--muted)",
        }}
        onClick={() => onTagFilterChange(key)}
      >
        {label}
        <span className="draft-tag-tab-count">{count}</span>
      </button>
    );
  };

  return (
    <div className="card">
      <div className="draft-board-head">
        <h3 style={{ margin: 0 }}>Rookie board</h3>
        <div className="draft-board-controls">
          <input
            ref={searchInputRef}
            className="input"
            placeholder="Search player… (press / )"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            style={{ width: 200 }}
          />
          <label className="draft-check">
            <input
              type="checkbox"
              checked={showDrafted}
              onChange={(e) => onShowDraftedChange(e.target.checked)}
            />
            Show drafted
          </label>
          <AddPlayerInline onAdd={onAdd} />
        </div>
      </div>
      <div className="draft-tag-tabs">
        {tagTab("all", "All", tagCounts.all, "var(--cyan)")}
        {tagTab("target", "Targets", tagCounts.target, "var(--green)")}
        {tagTab("avoid", "Avoid", tagCounts.avoid, "var(--red)")}
        {tagTab("untagged", "Untagged", tagCounts.untagged, "var(--muted)")}
      </div>
      <div className="draft-table-wrap">
        <table className="draft-table">
          <thead>
            <tr>
              {th("#", "rank", 40)}
              <th
                style={{ width: 44 }}
                title="Tier by PreDraft $: S=$60+, A=$25-59, B=$8-24, C=$3-7, D=$1-2"
              >
                Tier
              </th>
              <th
                style={{ width: 70 }}
                title="Click to cycle: neutral → target → avoid → neutral"
              >
                Tag
              </th>
              <th style={{ width: 86 }} title="Draft-time recommendation">
                Rec
              </th>
              {th("Player", "name")}
              {th("PreDraft", "preDraft", 82)}
              {th("Fair", "inflatedFair", 70)}
              {th("Enforce", "enforceUpTo", 70)}
              {th("Win at", "myWinningBid", 80)}
              {th("Max Bid", "myMaxBid", 80)}
              {th("Final", "final", 100)}
              <th style={{ width: 180 }}>Drafted to</th>
              <th style={{ width: 110 }}></th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              const rendered = [];
              let lastTier = null;
              for (const p of filtered) {
                if (showTierDividers && p.tier !== lastTier) {
                  const info = stats.tierStats?.[p.tier];
                  rendered.push(
                    <tr
                      key={`tier-${p.tier}`}
                      className="draft-tier-divider"
                    >
                      <td colSpan={13}>
                        <span
                          className={`draft-tier-chip draft-tier-${p.tier}`}
                          style={{ marginRight: 8 }}
                        >
                          {p.tier}
                        </span>
                        <strong>
                          {TIER_LABELS[p.tier] || p.tier} tier
                        </strong>
                        {info && (
                          <span
                            className="muted"
                            style={{ marginLeft: 8, fontSize: "0.72rem" }}
                          >
                            {info.remaining} of {info.total} left
                            {info.heat != null &&
                              info.confidence > 0 &&
                              ` · heat ${info.heat.toFixed(2)}×`}
                          </span>
                        )}
                      </td>
                    </tr>,
                  );
                  lastTier = p.tier;
                }
                const capped = p.myWinningBid < p.theoreticalMaxBid;
                const rec = playerRecommendation(p, stats);
                const recInfo = rec ? REC_CHIP[rec.level] : null;
                rendered.push(
              <tr
                key={p.id}
                className={`draft-row${p.drafted ? " draft-row-drafted" : ""}${
                  p.mine ? " draft-row-mine" : ""
                }${p.userTag === TAG_TARGET ? " draft-row-target" : ""}${
                  p.userTag === TAG_AVOID ? " draft-row-avoid" : ""
                }`}
              >
                <td className="draft-money">{p.rank}</td>
                <td>
                  <span
                    className={`draft-tier-chip draft-tier-${p.tier}`}
                    title={`${TIER_LABELS[p.tier] || p.tier} tier`}
                  >
                    {p.tier}
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    className={`draft-tag-chip${p.userTag ? ` draft-tag-${p.userTag}` : ""}`}
                    onClick={() => onCycleTag(p.id)}
                    disabled={p.drafted}
                    title={
                      p.userTag === TAG_TARGET
                        ? "Target — click to cycle to avoid"
                        : p.userTag === TAG_AVOID
                          ? "Avoid — click to clear"
                          : "Click to mark target"
                    }
                  >
                    {p.userTag === TAG_TARGET
                      ? "★"
                      : p.userTag === TAG_AVOID
                        ? "⊘"
                        : "+"}
                  </button>
                </td>
                <td>
                  {recInfo ? (
                    <span
                      className={`draft-rec-chip ${recInfo.cls}`}
                      title={rec.rationale || rec.label}
                    >
                      {recInfo.text}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>{p.name}</td>
                <td>
                  <input
                    type="number"
                    className="draft-inline-input draft-money-input"
                    min="0"
                    value={p.preDraft}
                    onChange={(e) =>
                      onEditPreDraft(p.id, Number(e.target.value) || 0)
                    }
                    disabled={p.drafted}
                  />
                </td>
                <td className="draft-money">{fmt$(p.inflatedFair)}</td>
                <td className="draft-money">{fmt$(p.enforceUpTo)}</td>
                <td
                  className="draft-money draft-money-win"
                  title={
                    capped
                      ? `Capped by top rival ceiling (${fmt$(
                          stats.topCompetitorMax,
                        )} + $1). Theoretical max was ${fmt$(
                          p.theoreticalMaxBid,
                        )}.`
                      : `Limited by my theoretical max (${fmt$(
                          p.theoreticalMaxBid,
                        )})`
                  }
                >
                  {fmt$(p.myWinningBid)}
                  {capped && (
                    <span
                      style={{
                        marginLeft: 4,
                        fontSize: "0.64rem",
                        color: "var(--green)",
                      }}
                    >
                      ✓
                    </span>
                  )}
                </td>
                <td className="draft-money draft-money-max" title="Theoretical max bid if forced all the way to the ceiling.">
                  {fmt$(p.myMaxBid)}
                </td>
                <td className="draft-money">
                  {p.drafted ? fmt$(p.pick.amount) : "—"}
                  {p.drafted && p.valueVsFair != null && (
                    <span
                      className={`draft-vs-fair ${
                        p.valueVsFair > 0
                          ? "draft-vs-fair-win"
                          : p.valueVsFair < 0
                            ? "draft-vs-fair-lose"
                            : ""
                      }`}
                      title={`Inflated fair ${fmt$(
                        p.inflatedFair,
                      )} − final ${fmt$(p.pick.amount)}`}
                    >
                      {p.valueVsFair > 0 ? "+" : ""}
                      {fmt$(p.valueVsFair)}
                    </span>
                  )}
                </td>
                <td>
                  {p.drafted ? (
                    <span
                      className={`draft-tag${p.mine ? " draft-tag-mine" : ""}`}
                    >
                      {teamName(p.pick.teamIdx)}
                    </span>
                  ) : (
                    <span className="muted" style={{ fontSize: "0.72rem" }}>
                      —
                    </span>
                  )}
                </td>
                <td>
                  <div className="draft-row-actions">
                    <button
                      className="button"
                      style={{ fontSize: "0.72rem", padding: "3px 8px" }}
                      onClick={() => onDraft(p)}
                    >
                      {p.drafted ? "Edit" : "Draft"}
                    </button>
                    {!p.drafted && (
                      <button
                        className="button-reset draft-remove-btn"
                        onClick={() => {
                          if (
                            typeof window !== "undefined" &&
                            window.confirm(`Remove ${p.name} from the board?`)
                          ) {
                            onRemovePlayer(p.id);
                          }
                        }}
                        title="Remove from board"
                      >
                        ×
                      </button>
                    )}
                  </div>
                </td>
              </tr>,
                );
              }
              return rendered;
            })()}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={13}
                  className="muted"
                  style={{ padding: 14, textAlign: "center" }}
                >
                  No rookies match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Next Best Target sidebar ─────────────────────────────────────── */

/**
 * Top-N EV-ranked undrafted targets, always visible.  Answers "what
 * should I focus on right now?" without the user having to scroll
 * or re-sort.  Clicking a row opens the draft modal pre-loaded with
 * that player; clicking the star cycles the tag.
 */
/* ── Inflation sparkline ──────────────────────────────────────────── */

/**
 * Tiny SVG sparkline of inflation (y-axis) over picks (x-axis).
 * Renders inline in the stats strip so the user can see "inflation
 * has been climbing 3 picks straight" at a glance without scrolling
 * back through the pick log.
 *
 * Draws a horizontal reference line at 1.00×; the main path is a
 * polyline over the ``series``, color-coded by the most recent
 * direction (green = above 1.0, red = below, muted when flat).
 */
function InflationSparkline({ series, width = 140, height = 36 }) {
  if (!Array.isArray(series) || series.length < 2) {
    return (
      <span className="muted" style={{ fontSize: "0.68rem" }}>
        (sparkline populates after first pick)
      </span>
    );
  }
  const values = series.map((s) => s.inflation);
  const minV = Math.min(0.7, ...values);
  const maxV = Math.max(1.3, ...values);
  const range = Math.max(0.01, maxV - minV);
  const padX = 2;
  const padY = 2;
  const w = width - padX * 2;
  const h = height - padY * 2;

  const pts = values.map((v, i) => {
    const x = padX + (i / Math.max(1, series.length - 1)) * w;
    const y = padY + h - ((v - minV) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  // Reference line at 1.00×.
  const refY = padY + h - ((1 - minV) / range) * h;

  const last = values[values.length - 1];
  const color =
    last > 1.03
      ? "var(--green)"
      : last < 0.97
        ? "var(--red)"
        : "var(--muted)";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="draft-sparkline"
      role="img"
      aria-label={`Inflation trajectory, currently ${last.toFixed(2)}×`}
    >
      <line
        x1={padX}
        y1={refY}
        x2={width - padX}
        y2={refY}
        stroke="rgba(153,166,200,0.3)"
        strokeWidth="0.5"
        strokeDasharray="2 2"
      />
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={padX + w}
        cy={refY - ((last - 1) / range) * h}
        r="2"
        fill={color}
      />
    </svg>
  );
}

/* ── Nomination optimizer sidebar ─────────────────────────────────── */

/**
 * "Good to nominate" list.  Players I don't want (or am happy
 * without) whose expected clearing price is high enough to drain
 * rival budgets.  Companion to ``NextBestTargets``; both live just
 * above the rookie board so decisions are in peripheral vision.
 */
function NominationCandidates({ stats, onDraft, onCycleTag }) {
  const list = useMemo(
    () => nominationCandidates(stats, { limit: 5 }),
    [stats],
  );

  if (list.length === 0) {
    return (
      <div className="card draft-nbt">
        <h3 style={{ margin: "0 0 4px" }}>Good to nominate</h3>
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          No drain candidates — rivals are too tight or everyone is
          already tagged as target.
        </div>
      </div>
    );
  }

  return (
    <div className="card draft-nbt">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0 }}>Good to nominate</h3>
        <span className="muted" style={{ fontSize: "0.68rem" }}>
          Drain rival $ without risking a target
        </span>
      </div>
      <div className="draft-nbt-list">
        {list.map(({ player, score, drain, rationale }, i) => (
          <div
            key={player.id}
            className={`draft-nbt-row${player.userTag === TAG_AVOID ? " draft-nbt-avoid" : ""}`}
            title={rationale}
          >
            <span className="draft-nbt-rank">#{i + 1}</span>
            <button
              type="button"
              className={`draft-tag-chip${
                player.userTag ? ` draft-tag-${player.userTag}` : ""
              }`}
              onClick={() => onCycleTag(player.id)}
              title="Cycle tag"
            >
              {player.userTag === TAG_TARGET
                ? "★"
                : player.userTag === TAG_AVOID
                  ? "⊘"
                  : "+"}
            </button>
            <span
              className={`draft-tier-chip draft-tier-${player.tier}`}
              title={`${TIER_LABELS[player.tier] || player.tier} tier`}
            >
              {player.tier}
            </span>
            <span className="draft-nbt-name" onClick={() => onDraft(player)}>
              {player.name}
            </span>
            <span className="draft-money">fair {fmt$(player.inflatedFair)}</span>
            <span className="muted" style={{ fontSize: "0.68rem" }}>
              drain {fmt$(drain)}
            </span>
            <span
              className={`draft-rec-chip ${
                player.userTag === TAG_AVOID
                  ? "draft-rec-avoid"
                  : "draft-rec-neutral"
              }`}
            >
              {player.userTag === TAG_AVOID ? "AVOID" : "DRAIN"}
            </span>
            <span className="muted" style={{ fontSize: "0.66rem" }}>
              S {Math.round(score)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function NextBestTargets({ stats, onDraft, onCycleTag, workspace }) {
  const top = useMemo(
    () => nextBestTargets(stats, { limit: 5 }),
    [stats],
  );

  if (top.length === 0) {
    return (
      <div className="card draft-nbt">
        <h3 style={{ margin: "0 0 4px" }}>Next Best Targets</h3>
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          Nothing to flag yet — tag a few players as <strong>★ target</strong>{" "}
          to seed EV ranking.
        </div>
      </div>
    );
  }

  return (
    <div className="card draft-nbt">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0 }}>Next Best Targets</h3>
        <span className="muted" style={{ fontSize: "0.68rem" }}>
          EV = (fair − winBid) × tag weight + scarcity boost
        </span>
      </div>
      <div className="draft-nbt-list">
        {top.map(({ player, ev, rec }, i) => {
          const recInfo = rec ? REC_CHIP[rec.level] : null;
          return (
            <div
              key={player.id}
              className={`draft-nbt-row${player.userTag === TAG_TARGET ? " draft-nbt-target" : ""}`}
              title={rec?.rationale || rec?.label || ""}
            >
              <span className="draft-nbt-rank">#{i + 1}</span>
              <button
                type="button"
                className={`draft-tag-chip${
                  player.userTag ? ` draft-tag-${player.userTag}` : ""
                }`}
                onClick={() => onCycleTag(player.id)}
                title="Cycle tag"
              >
                {player.userTag === TAG_TARGET
                  ? "★"
                  : player.userTag === TAG_AVOID
                    ? "⊘"
                    : "+"}
              </button>
              <span
                className={`draft-tier-chip draft-tier-${player.tier}`}
                title={`${TIER_LABELS[player.tier] || player.tier} tier`}
              >
                {player.tier}
              </span>
              <span className="draft-nbt-name" onClick={() => onDraft(player)}>
                {player.name}
              </span>
              <span className="draft-money draft-money-win">
                {fmt$(player.myWinningBid)}
              </span>
              <span className="muted" style={{ fontSize: "0.68rem" }}>
                fair {fmt$(player.inflatedFair)}
              </span>
              {recInfo && (
                <span className={`draft-rec-chip ${recInfo.cls}`}>
                  {recInfo.text}
                </span>
              )}
              <span className="muted" style={{ fontSize: "0.66rem" }}>
                EV {ev.toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AddPlayerInline({ onAdd }) {
  const [name, setName] = useState("");
  const [pd, setPd] = useState("");
  function submit(e) {
    e?.preventDefault();
    if (!name.trim()) return;
    onAdd({ name: name.trim(), preDraft: Number(pd) || 0 });
    setName("");
    setPd("");
  }
  return (
    <form className="draft-add-inline" onSubmit={submit}>
      <input
        className="input"
        placeholder="Add rookie…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        style={{ width: 140 }}
      />
      <input
        className="input"
        type="number"
        placeholder="$"
        value={pd}
        onChange={(e) => setPd(e.target.value)}
        min="0"
        style={{ width: 60 }}
      />
      <button
        type="submit"
        className="button"
        style={{ fontSize: "0.72rem", padding: "3px 8px" }}
      >
        +
      </button>
    </form>
  );
}

/* ── Main page ────────────────────────────────────────────────────── */

export default function DraftDashboardPage() {
  const router = useRouter();
  const { authenticated, checking } = useAuthContext();

  const [workspace, setWorkspace] = useState(() => createDefaultWorkspace());
  const [hydrated, setHydrated] = useState(false);
  const [modalPlayer, setModalPlayer] = useState(null);
  const [showDrafted, setShowDrafted] = useState(false);
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("all"); // all | target | avoid | untagged
  // Late-draft triage mode: when my slotPressure crosses 0.7, auto-
  // flip the board filter to "Targets" so I see only the players I
  // still want.  Tracked so a user who manually changes the filter
  // AFTER auto-switch isn't fought by the effect every re-render.
  const [triageApplied, setTriageApplied] = useState(false);
  const [triageDismissed, setTriageDismissed] = useState(false);
  const searchInputRef = useRef(null);
  const [capitalStatus, setCapitalStatus] = useState({
    loading: false,
    error: "",
    info: "",
    source: null, // { season, totalBudget, fetchedAt }
  });

  // Gate on auth: unauthenticated users bounce to /login with a return path.
  useEffect(() => {
    if (checking) return;
    if (authenticated === false) {
      router.push("/login?next=/draft");
    }
  }, [checking, authenticated, router]);

  // Hydrate workspace from localStorage on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        setWorkspace(hydrateWorkspace(parsed));
      }
    } catch {
      /* ignore */
    }
    setHydrated(true);
  }, []);

  // Persist on every change.
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(workspace));
    } catch {
      /* ignore */
    }
  }, [workspace, hydrated]);

  const stats = useMemo(() => computeDraftStats(workspace), [workspace]);
  // Retrospective inflation trajectory — O(N²) in pick count, but
  // N caps at ~72 so negligible.  Feeds the sparkline in the stats
  // strip and any future "how did we get here" retrospectives.
  const historySeries = useMemo(
    () => computeHistorySeries(workspace),
    [workspace],
  );

  // Late-draft triage: when my slot pressure crosses 0.7, auto-flip
  // the tag filter to "target" so only players I still want appear
  // on the board.  Only fires ONCE (via triageApplied) so a user
  // who manually changes the filter after the flip isn't fought by
  // the effect.  triageDismissed lets the user opt out explicitly.
  const LATE_DRAFT_THRESHOLD = 0.7;
  useEffect(() => {
    if (triageApplied || triageDismissed) return;
    if ((stats.slotPressure || 0) >= LATE_DRAFT_THRESHOLD) {
      setTagFilter("target");
      setTriageApplied(true);
    }
  }, [stats.slotPressure, triageApplied, triageDismissed]);

  // "/" focuses the search input (skip when already typing).
  useEffect(() => {
    function onKey(e) {
      if (e.key !== "/") return;
      const tag = (e.target?.tagName || "").toLowerCase();
      const editable =
        tag === "input" || tag === "textarea" || tag === "select";
      if (editable) return;
      e.preventDefault();
      searchInputRef.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Pull per-team auction $ budgets from /api/draft-capital.  The
  // dashboard needs this to mirror real carry-over balances without
  // forcing the user to re-enter every team's budget by hand.  When
  // ``quiet`` is true we don't flash a status banner on success —
  // used for the silent auto-populate on first page load.
  const fetchDraftCapital = useCallback(
    async ({ quiet = false, force = false } = {}) => {
      setCapitalStatus((s) => ({ ...s, loading: true, error: "", info: "" }));
      try {
        const res = await fetch("/api/draft-capital", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data?.error) throw new Error(data.error);
        const teamTotals = Array.isArray(data?.teamTotals) ? data.teamTotals : [];
        if (teamTotals.length === 0) {
          throw new Error("Draft capital feed had no team totals.");
        }
        // Raw picks array — used to derive per-team initial slot
        // counts (how many rookie picks each team currently owns).
        // Feeds into the slot-adjusted effectiveBudget calculation
        // so MaxBid / WinningBid reflect real opponent bidding power.
        const picksArray = Array.isArray(data?.picks) ? data.picks : [];

        setWorkspace((ws) => {
          // Non-force fetches are gated: if the user has already
          // recorded picks or tuned team budgets, don't clobber.
          if (!force && !workspaceIsPristine(ws)) return ws;
          const { workspace: next, matched, added } = mergeDraftCapitalTeams(
            ws,
            teamTotals,
            { picks: picksArray },
          );
          if (!quiet) {
            setCapitalStatus((s) => ({
              ...s,
              info: `Loaded ${matched} team budgets${
                added > 0 ? ` (${added} new)` : ""
              }${picksArray.length > 0 ? ` · ${picksArray.length} picks tracked` : ""}.`,
            }));
          }
          return next;
        });

        setCapitalStatus((s) => ({
          ...s,
          loading: false,
          source: {
            season: data.season,
            totalBudget: data.totalBudget,
            fetchedAt: new Date().toISOString(),
          },
        }));
      } catch (err) {
        setCapitalStatus((s) => ({
          ...s,
          loading: false,
          error: err?.message || "Failed to load draft capital.",
        }));
      }
    },
    [],
  );

  // Auto-populate on first load when the workspace is still at
  // defaults — gives the user a pre-seeded team list without a click,
  // but never overwrites a workspace already in progress.
  useEffect(() => {
    if (!hydrated || authenticated !== true) return;
    if (!workspaceIsPristine(workspace)) return;
    fetchDraftCapital({ quiet: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, authenticated]);

  const onSettings = useCallback(
    (patch) => setWorkspace((ws) => updateSettings(ws, patch)),
    [],
  );
  const onTeam = useCallback(
    (idx, patch) => setWorkspace((ws) => updateTeam(ws, idx, patch)),
    [],
  );
  const onEditPreDraft = useCallback(
    (id, v) => setWorkspace((ws) => updatePlayerPreDraft(ws, id, v)),
    [],
  );
  const onAdd = useCallback(
    (p) => setWorkspace((ws) => addPlayer(ws, p)),
    [],
  );
  const onRemovePlayer = useCallback(
    (id) => setWorkspace((ws) => removePlayer(ws, id)),
    [],
  );
  const onCycleTag = useCallback(
    (id) =>
      setWorkspace((ws) => {
        const current = ws.tags?.[id] || null;
        return setPlayerTag(ws, id, cycleTag(current));
      }),
    [],
  );

  const handleModalSubmit = useCallback(
    (payload) => {
      if (payload?._remove) {
        setWorkspace((ws) => removePick(ws, payload.playerId));
      } else {
        setWorkspace((ws) => recordPick(ws, payload));
      }
      setModalPlayer(null);
    },
    [],
  );

  function handleReset() {
    if (
      typeof window !== "undefined" &&
      window.confirm(
        "Reset the draft board? This clears every pick and restores default values.",
      )
    ) {
      setWorkspace(createDefaultWorkspace());
    }
  }

  if (checking || authenticated == null) {
    return (
      <section className="card">
        <h1 style={{ marginTop: 0 }}>Draft board</h1>
        <p className="muted">Checking session…</p>
      </section>
    );
  }
  if (authenticated === false) {
    return null;
  }

  // Re-enrich the modal player against current stats each render so the
  // modal's reference prices stay in sync with live inflation as other
  // picks are recorded.
  const modalPlayerEnriched = modalPlayer
    ? stats.enrichedPlayers.find((p) => p.id === modalPlayer.id) || null
    : null;

  return (
    <section className="card">
      <div className="draft-page-head">
        <div>
          <h1 style={{ marginTop: 0, marginBottom: 4 }}>Draft board</h1>
          <p className="muted" style={{ marginTop: 0 }}>
            Live inflation-aware rookie auction dashboard.  Every pick
            you record updates the per-player bid ceiling immediately.
          </p>
        </div>
        <div className="draft-page-actions">
          <button
            className="button"
            onClick={() => setWorkspace((ws) => undoLastPick(ws))}
            disabled={(workspace.picks || []).length === 0}
            title="Undo the most recent pick"
          >
            ↶ Undo last
          </button>
          <button
            className="button button-danger"
            onClick={handleReset}
            title="Reset the entire draft board"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Draft progress bar — picks drafted vs total slots in the
          draft (sum of initialSlots across all teams, normally 72).
          Sits above the stats strip so the user has constant
          peripheral awareness of "how far in are we?" — which drives
          every late-draft decision. */}
      <div className="draft-progress" title={`${stats.totalPicksMade} of ${stats.totalInitialSlots} picks recorded`}>
        <div className="draft-progress-bar">
          <div
            className="draft-progress-fill"
            style={{ width: `${Math.min(100, stats.draftProgress * 100)}%` }}
          />
        </div>
        <div className="draft-progress-labels">
          <span>
            Pick <strong>{stats.totalPicksMade}</strong> of{" "}
            <strong>{stats.totalInitialSlots}</strong>
          </span>
          <span>{Math.round(stats.draftProgress * 100)}% through draft</span>
        </div>
      </div>

      <StatsStrip stats={stats} historySeries={historySeries} />

      <div className="draft-top-grid">
        <TeamPanel
          stats={stats}
          workspace={workspace}
          onSettings={onSettings}
          onTeam={onTeam}
          onLoadCapital={fetchDraftCapital}
          capitalStatus={capitalStatus}
        />
        <BidKnobs settings={workspace.settings || {}} onSettings={onSettings} />
      </div>

      {/* Late-draft triage banner — visible once the auto-filter
          fires.  Tells the user what just happened and offers an
          "escape hatch" back to the full view.  Dismiss persists
          within the session; reload resets to auto-behavior. */}
      {triageApplied && !triageDismissed && (
        <div className="draft-triage-banner">
          <strong>LATE-DRAFT TRIAGE</strong>
          <span>
            Slot pressure {Math.round((stats.slotPressure || 0) * 100)}% —
            auto-filtered to your Targets so you only see players you
            still want.
          </span>
          <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            <button
              className="button"
              style={{ fontSize: "0.7rem", padding: "2px 8px" }}
              onClick={() => {
                setTagFilter("all");
                setTriageDismissed(true);
              }}
              title="Go back to the full board"
            >
              Show all
            </button>
            <button
              className="button"
              style={{ fontSize: "0.7rem", padding: "2px 8px" }}
              onClick={() => setTriageDismissed(true)}
              title="Keep the filter but dismiss this banner"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      <div className="draft-sidebar-grid">
        <NextBestTargets
          stats={stats}
          onDraft={(p) => setModalPlayer(p)}
          onCycleTag={onCycleTag}
          workspace={workspace}
        />
        <NominationCandidates
          stats={stats}
          onDraft={(p) => setModalPlayer(p)}
          onCycleTag={onCycleTag}
        />
      </div>

      <RookieBoard
        stats={stats}
        workspace={workspace}
        onDraft={(p) => setModalPlayer(p)}
        onEditPreDraft={onEditPreDraft}
        onRemovePlayer={onRemovePlayer}
        onCycleTag={onCycleTag}
        searchInputRef={searchInputRef}
        showDrafted={showDrafted}
        onShowDraftedChange={setShowDrafted}
        query={query}
        onQueryChange={setQuery}
        tagFilter={tagFilter}
        onTagFilterChange={setTagFilter}
        onAdd={onAdd}
      />

      {modalPlayerEnriched && (
        <DraftModal
          player={modalPlayerEnriched}
          workspace={workspace}
          stats={stats}
          onClose={() => setModalPlayer(null)}
          onSubmit={handleModalSubmit}
        />
      )}
    </section>
  );
}
