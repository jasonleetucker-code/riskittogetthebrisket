"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthContext } from "@/app/AppShellWrapper";
import {
  DRAFT_STORAGE_KEY,
  DEFAULT_AGGRESSION,
  DEFAULT_ENFORCE_PCT,
  TIER_DEFS,
  addPlayer,
  bidStatus,
  computeDraftStats,
  createDefaultWorkspace,
  hydrateWorkspace,
  mergeDraftCapitalTeams,
  playerSlug,
  recordPick,
  removePick,
  removePlayer,
  undoLastPick,
  updatePlayerPreDraft,
  updateSettings,
  updateTeam,
  workspaceIsPristine,
} from "@/lib/draft-logic";

const TIER_LABELS = Object.fromEntries(TIER_DEFS.map((t) => [t.key, t.label]));

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

function StatsStrip({ stats }) {
  const stat = (label, value, title, extraClass = "") => (
    <div
      className={`draft-stat ${extraClass}`.trim()}
      title={title || undefined}
    >
      <div className="draft-stat-label">{label}</div>
      <div className="draft-stat-value">{value}</div>
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
        "RemainingLeague$ / (TotalAuction$ − Σ soldPreDraft). >1.00 means the remaining market is cheaper than projected; <1.00 means the remaining market got hot.",
        inflationClass,
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
        </div>
        {stats.teamStats.map((t) => {
          const effLow = t.effectiveBudget < 5;
          const slotsEmpty = t.slotsRemaining <= 0;
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

function DraftModal({ player, workspace, stats, onClose, onSubmit }) {
  const existingPick = player?.pick;
  const [teamIdx, setTeamIdx] = useState(
    existingPick?.teamIdx ?? workspace.settings?.myTeamIdx ?? 0,
  );
  const [amount, setAmount] = useState(existingPick?.amount ?? "");
  const [liveBid, setLiveBid] = useState("");
  const liveStatus = useMemo(() => bidStatus(player, liveBid), [player, liveBid]);

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
  showDrafted,
  onShowDraftedChange,
  query,
  onQueryChange,
  onAdd,
}) {
  const [sort, setSort] = useState({ col: "myMaxBid", asc: false });

  const filtered = useMemo(() => {
    let list = stats.enrichedPlayers;
    if (!showDrafted) list = list.filter((p) => !p.drafted);
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
        case "final":
          return (
            ((a.pick?.amount ?? -1) - (b.pick?.amount ?? -1)) * dir
          );
        default:
          return 0;
      }
    });
  }, [stats.enrichedPlayers, sort, query, showDrafted]);

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

  return (
    <div className="card">
      <div className="draft-board-head">
        <h3 style={{ margin: 0 }}>Rookie board</h3>
        <div className="draft-board-controls">
          <input
            className="input"
            placeholder="Search player…"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            style={{ width: 180 }}
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
      <div className="draft-table-wrap">
        <table className="draft-table">
          <thead>
            <tr>
              {th("#", "rank", 40)}
              <th style={{ width: 44 }} title="Tier by PreDraft $: S=$60+, A=$25-59, B=$8-24, C=$3-7, D=$1-2">
                Tier
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
            {filtered.map((p) => {
              const capped = p.myWinningBid < p.theoreticalMaxBid;
              return (
              <tr
                key={p.id}
                className={`draft-row${p.drafted ? " draft-row-drafted" : ""}${
                  p.mine ? " draft-row-mine" : ""
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
              </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={11}
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

      <StatsStrip stats={stats} />

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

      <RookieBoard
        stats={stats}
        workspace={workspace}
        onDraft={(p) => setModalPlayer(p)}
        onEditPreDraft={onEditPreDraft}
        onRemovePlayer={onRemovePlayer}
        showDrafted={showDrafted}
        onShowDraftedChange={setShowDrafted}
        query={query}
        onQueryChange={setQuery}
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
