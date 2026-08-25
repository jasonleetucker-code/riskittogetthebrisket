"use client";

/**
 * trade-sections.jsx — presentational sections of the trade terminal.
 *
 * Extracted from app/trade/page.jsx in R4 so the page file holds state
 * and orchestration while these render it.  Every component here is
 * pure presentation: it receives already-computed values and handlers.
 *
 * NO trade math lives in this file.  Totals, gaps, adjustments, stack
 * effects and simulation results all arrive as props from lib/trade-logic
 * or the /api/trade/* responses.
 */

import { useRef, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Field,
  Icon,
  Input,
  Movement,
  Panel,
  Select,
  SkeletonText,
  StatTile,
} from "@/components/ds";
import { PlayerImage } from "@/components/ui";
import {
  defaultDestination,
  effectiveValue,
  formatBoardValue,
  isUnpricedBoardRow,
  unpricedAssetsOnSide,
  getPlayerEdge,
} from "@/lib/trade-logic";
import styles from "./trade.module.css";

// ── Shared bits ───────────────────────────────────────────────────────

export const SUGGESTION_RAIL_LABELS = {
  sellHigh: { label: "Sell High", hint: "These pieces have peaked — convert before the market cools." },
  buyLow: { label: "Buy Low", hint: "Undervalued by the consensus right now." },
  consolidation: { label: "Consolidation", hint: "Trade a pile of assets for a single anchor." },
  positionalUpgrades: { label: "Upgrade", hint: "Direct positional swaps that net you value." },
};

export const SUGG_TYPES = [
  { key: "sellHigh", label: "Sell High" },
  { key: "buyLow", label: "Buy Low" },
  { key: "consolidation", label: "Consolidation" },
  { key: "positionalUpgrades", label: "Upgrades" },
];

export function fairnessLabel(f) {
  if (f === "even") return "Even value";
  if (f === "lean") return "Slight lean";
  return "Stretch";
}

/** Fairness/confidence/edge all map onto Badge tones — the meaning is
 *  carried by the label text, tone is reinforcement. */
export function fairnessTone(f) {
  if (f === "even") return "positive";
  if (f === "lean") return "warning";
  return "negative";
}

export function confidenceMeta(c) {
  if (c === "high") return { label: "High consensus", tone: "positive" };
  if (c === "medium") return { label: "Moderate consensus", tone: "warning" };
  return { label: "Low consensus", tone: "neutral" };
}

export function edgeMeta(edge) {
  if (edge === "market_discount") return { text: "Buy Low", tone: "positive" };
  if (edge === "market_premium") return { text: "Sell High", tone: "negative" };
  if (edge === "high_dispersion") return { text: "Sources Disagree", tone: "warning" };
  return null;
}

function fmtSigned(n) {
  const v = Math.round(Number(n) || 0);
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString()}`;
}

/** A search result row, shared by the mobile quick-add and per-side search. */
function SearchResultRow({ row, settings, onPick, keyPrefix }) {
  return (
    <button
      key={`${keyPrefix}-${row.name}`}
      type="button"
      className="trade-side-search-result button-reset"
      onMouseDown={(e) => {
        // Prevent input blur so focus stays in the search field after a
        // tap — the mobile keyboard doesn't dismiss between additions.
        e.preventDefault();
        onPick(row);
      }}
      onTouchStart={(e) => {
        e.preventDefault();
        onPick(row);
      }}
    >
      <PlayerImage
        playerId={row.raw?.playerId}
        team={row.team}
        position={row.pos}
        name={row.name}
        size={26}
      />
      <div className="trade-side-search-result-body">
        <div className="trade-side-search-result-name">{row.name}</div>
        <div className="trade-side-search-result-meta">
          <Badge tone="outline">{row.pos}</Badge>
          <span className="muted">
            {row.blendedSourceRank != null ? `#${row.blendedSourceRank.toFixed(1)}` : "—"}
            {" · "}
            {formatBoardValue(row, settings)}
          </span>
        </div>
      </div>
    </button>
  );
}

// ── Mobile quick-add ──────────────────────────────────────────────────

/**
 * Mobile-only sticky quick-add bar.  The per-side search inputs live
 * deep in the page; on a 390px viewport that is ~600-800px of scroll
 * before a user can type a name.  This surfaces one search at the top
 * with an explicit active-side indicator and a one-tap side toggle.
 */
export function MobileQuickAddBar({
  activeSide,
  sides,
  onAddToActiveSide,
  searchAssets,
  settings,
  onSetActiveSide,
}) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const inputRef = useRef(null);

  const trimmed = query.trim();
  const results = focused && trimmed ? searchAssets(query) : [];
  const showResults = focused && trimmed.length > 0;
  const sideLabel = sides[activeSide]?.label || sides[0]?.label || "A";

  function handleAdd(row) {
    onAddToActiveSide(row);
    setQuery("");
    requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }));
  }

  return (
    <div
      className="mobile-quick-add mobile-only"
      role="region"
      aria-label="Quick add player to trade"
    >
      <div className="mobile-quick-add-row">
        <button
          type="button"
          className="mobile-quick-add-side-badge"
          onClick={() => {
            if (sides.length >= 2) onSetActiveSide((activeSide + 1) % sides.length);
          }}
          aria-label={`Currently adding to Side ${sideLabel}. Activate to switch sides.`}
          disabled={sides.length < 2}
        >
          <span className="mobile-quick-add-side-letter">{sideLabel}</span>
          {sides.length >= 2 ? (
            <Icon name="swap" aria-hidden="true" />
          ) : null}
        </button>
        <input
          ref={inputRef}
          className="input mobile-quick-add-input"
          placeholder={`Quick add to Side ${sideLabel}…`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 120)}
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          autoCorrect="off"
          spellCheck="false"
          aria-label={`Quick add a player to Side ${sideLabel}`}
        />
      </div>
      {showResults ? (
        <div className="mobile-quick-add-results">
          {results.length === 0 ? (
            <div className="mobile-quick-add-empty muted">No matches.</div>
          ) : (
            results.map((r) => (
              <SearchResultRow
                key={`mobile-quick-${r.name}`}
                row={r}
                settings={settings}
                onPick={handleAdd}
                keyPrefix="mobile-quick"
              />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

// ── Proactive suggestion rail ─────────────────────────────────────────

/**
 * Height-stable stand-in for ``ProactiveSuggestionsRail``.
 *
 * The rail's fetch is debounced 500ms and then round-trips, so it
 * always mounts well after the rest of /trade has painted.  Rendering
 * nothing until then inserted the whole 213px panel above the trade
 * controls and meter, pushing them down 229px.
 *
 * Reuses the REAL Panel with the REAL title/subtitle so the 59px
 * header is byte-identical between states; only the 152px card body
 * is skeleton bones.  Same reserve-then-collapse contract as the
 * dashboard's TopSignalsRail: if the fetch resolves with no ideas,
 * this unmounts and the slot collapses once (a one-time settle).
 */
export function SuggestionsRailPlaceholder() {
  return (
    <Panel
      dense
      title="Recommended right now"
      subtitle="Top idea per category — activate a card to load it into the builder."
      headingLevel={2}
    >
      <div className={styles.railGrid} aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className={styles.railCard} style={{ minHeight: 120 }}>
            <SkeletonText lines={4} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ProactiveSuggestionsRail({ suggestions, onApply }) {
  const cards = [];
  for (const [key, meta] of Object.entries(SUGGESTION_RAIL_LABELS)) {
    const list = suggestions[key] || [];
    if (list.length === 0) continue;
    cards.push({ key, meta, top: list[0], remaining: list.length - 1 });
  }
  if (cards.length === 0) return null;

  return (
    <Panel
      dense
      title="Recommended right now"
      subtitle="Top idea per category — activate a card to load it into the builder."
      headingLevel={2}
    >
      <div className={styles.railGrid}>
        {cards.map((c) => (
          <button
            key={c.key}
            type="button"
            className={styles.railCard}
            onClick={() => onApply(c.top)}
            title={c.meta.hint}
          >
            <span className={styles.railHead}>
              <Badge tone="accent">{c.meta.label}</Badge>
              {c.remaining > 0 ? (
                <span className={styles.railHint}>+{c.remaining} more</span>
              ) : null}
            </span>
            <span className={styles.railLine}>
              <span className={styles.railLineLabel}>Give: </span>
              {(c.top.give || []).map((p) => p.name).join(" + ") || "—"}
            </span>
            <span className={styles.railLine}>
              <span className={styles.railLineLabel}>Get: </span>
              {(c.top.receive || []).map((p) => p.name).join(" + ") || "—"}
            </span>
            <span className={styles.railHint}>{c.meta.hint}</span>
          </button>
        ))}
      </div>
    </Panel>
  );
}

// ── Simulation impact ─────────────────────────────────────────────────

const VERDICT_TONE = {
  accept: "positive",
  "lean accept": "positive",
  neutral: "neutral",
  "lean decline": "negative",
  decline: "negative",
};

/**
 * `finalRosterSimulation` refusal copy, keyed by the backend's own
 * `unavailableReason`.  The backend refuses for reasons that mean
 * genuinely different things to a user, so they are not collapsed into
 * one "unavailable" line.
 */
const FINAL_ROSTER_UNAVAILABLE_COPY = {
  capacity_uncertain:
    "taxi occupancy is unknown, so the forced-drop set is a range rather than a determined set — see Roster capacity above",
  starter_slots_unresolved:
    "the league's starting slots did not resolve, so no lineup could be solved",
};

/**
 * Why the final roster was not simulated.
 *
 * Reads BOTH shapes the backend can stamp: `{available: false,
 * unavailableReason}` for a deliberate refusal, and `{unavailable:
 * "<ExcType>"}` for an error — the second carries no `available` key at
 * all, which is why the caller tests `available === true` rather than
 * `available !== false`.
 */
function finalRosterUnavailableText(frs) {
  const reason = frs?.unavailableReason || frs?.unavailable || "reason not reported";
  return `Not simulated — ${FINAL_ROSTER_UNAVAILABLE_COPY[reason] || reason}.`;
}

/** Backend-stamped number for display. Missing stays missing, never 0. */
function strengthText(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

export function SimulationPanel({ simResult, simError, selectedTeam, onReset }) {
  if (!simResult && !simError) return null;

  const teamName =
    simResult?.team?.name || selectedTeam?.name || "your team";
  const ti = simResult?.teamImpact;
  const starterEntries = Object.entries(ti?.starterValueDelta || {}).filter(
    ([, v]) => v !== 0,
  );
  const unresolved = [
    ...(simResult?.unresolvedIn || []),
    ...(simResult?.unresolvedOut || []),
  ];
  const rc = simResult?.rosterCapacity;
  // V1-45 / V1-42. `rosterCapacity` says WHO must go; this says what the
  // roster IS once they have — the lineup re-solved over the post-trade,
  // post-cleanup roster. Absent (not null) whenever there is no resolved
  // team, and absent must render nothing at all.
  const frs = simResult?.finalRosterSimulation;

  return (
    <Panel
      title={`Impact on ${teamName}`}
      headingLevel={2}
      actions={
        <Button variant="ghost" size="sm" onClick={onReset}>
          Clear simulation
        </Button>
      }
    >
      {simError ? (
        <Banner tone="negative" title="Simulation failed">
          {simError}
        </Banner>
      ) : null}

      {simResult ? (
        <>
          <div className={styles.simGrid}>
            <StatTile
              label="Before"
              value={Math.round(simResult.before?.totalValue || 0).toLocaleString()}
            />
            <StatTile
              label="After"
              value={Math.round(simResult.after?.totalValue || 0).toLocaleString()}
            />
            <StatTile
              label="Change"
              value={fmtSigned(simResult.delta?.totalValue)}
              movement={
                <Movement
                  delta={simResult.delta?.totalValue || 0}
                  format={(n) => n.toLocaleString()}
                />
              }
            />
          </div>

          <div className={styles.simPosGrid} style={{ marginTop: "var(--space-3)" }}>
            {["QB", "RB", "WR", "TE"].map((pos) => {
              const row = simResult.delta?.byPosition?.[pos];
              if (!row) return null;
              return (
                <StatTile
                  key={pos}
                  label={pos}
                  value={fmtSigned(row.value)}
                  meta={row.count !== 0 ? `${row.count > 0 ? "+" : ""}${row.count} players` : null}
                />
              );
            })}
          </div>

          {ti ? (
            <div className={styles.simSection} style={{ marginTop: "var(--space-3)" }}>
              <div className={styles.simSectionHead}>
                <span className={styles.simSectionTitle}>Roster fit</span>
                <span className={styles.simVerdict}>
                  <Badge tone={VERDICT_TONE[ti.verdict] || "neutral"}>{ti.verdict}</Badge>
                  <span className={styles.simScore}>
                    {ti.compositeScore >= 0 ? "+" : ""}
                    {ti.compositeScore.toFixed(1)}
                  </span>
                </span>
              </div>
              <div className={styles.simGrid}>
                <StatTile
                  label="Fit"
                  value={`${ti.fitScore >= 0 ? "+" : ""}${ti.fitScore.toFixed(1)}`}
                />
                <StatTile
                  label="Equity"
                  value={`${ti.equityScore >= 0 ? "+" : ""}${ti.equityScore.toFixed(1)}`}
                />
                <StatTile
                  label={ti.posture || "Window"}
                  value={`${ti.windowFit >= 0 ? "+" : ""}${ti.windowFit.toFixed(2)}`}
                  meta="window fit"
                />
              </div>
              {starterEntries.length > 0 ? (
                <div className={styles.simStarterGrid}>
                  {starterEntries.map(([pos, dv]) => (
                    <StatTile
                      key={pos}
                      label={`${pos} starter`}
                      value={fmtSigned(dv)}
                      bare
                    />
                  ))}
                </div>
              ) : null}
              {ti.rationale?.length > 0 ? (
                <ul className={styles.simRationale}>
                  {ti.rationale.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              ) : null}
              {ti.redundancy?.length > 0 ? (
                <Banner tone="warning">
                  Redundant: {ti.redundancy.map((r) => `${r.name} (${r.pos})`).join(", ")}
                </Banner>
              ) : null}
            </div>
          ) : null}

          {rc && rc.requiresDrops === true ? (
            <Banner tone="warning" title="Roster capacity">
              {`Forces ${rc.forcedDrops.length} release${rc.forcedDrops.length === 1 ? "" : "s"}` +
                (rc.rosterLimit != null ? ` to fit the ${rc.rosterLimit}-man limit` : "") +
                (rc.forcedDropValue != null
                  ? ` — ${Math.round(rc.forcedDropValue).toLocaleString()} value released`
                  : "") +
                (rc.forcedDropsAreUpperBound ? " (worst case; taxi occupancy uncertain)" : "") +
                (rc.ladderExhausted ? " — no fully legal cleanup found" : "")}
              {rc.forcedDrops.length > 0 ? (
                <ul className={styles.simRationale}>
                  {rc.forcedDrops.map((d) => (
                    <li key={d.playerId || d.name}>
                      {d.name} ({d.position}) —{" "}
                      {d.value != null ? Math.round(d.value).toLocaleString() : "unpriced"}
                    </li>
                  ))}
                </ul>
              ) : null}
            </Banner>
          ) : null}

          {rc && rc.requiresDrops === null ? (
            <Banner tone="neutral" title="Roster capacity">
              {rc.rosterLimit == null
                ? "Roster capacity unknown for this league."
                : "Roster capacity uncertain — taxi occupancy unknown; this trade may or may not require a release."}
            </Banner>
          ) : null}

          {/* Final roster — renders AFTER the capacity blocks on purpose:
              the backend's own `capacity_uncertain` note says "see
              rosterCapacity", so it must read after what it refers to.
              Pure display of backend stamps; nothing here is derived. */}
          {frs ? (
            frs.available === true ? (
              <div className={styles.simSection} style={{ marginTop: "var(--space-3)" }}>
                <div className={styles.simSectionHead}>
                  <span className={styles.simSectionTitle}>Final roster</span>
                </div>
                <div className={styles.simGrid}>
                  <StatTile label="Strength before" value={strengthText(frs.strengthBefore?.total)} />
                  <StatTile label="Strength after" value={strengthText(frs.strengthAfter?.total)} />
                  <StatTile
                    label="Strength change"
                    /* The BACKEND's delta. Never `after - before`: this
                       file computes no trade math, and a client-side
                       subtraction would silently republish a different
                       quantity under a canonical field's name. */
                    value={
                      Number.isFinite(Number(frs.strengthDelta))
                        ? fmtSigned(frs.strengthDelta)
                        : "—"
                    }
                  />
                </div>

                {frs.promotions?.length > 0 ? (
                  <ul className={styles.simRationale}>
                    {frs.promotions.map((m) => (
                      <li key={`promo-${m.playerId || m.name}`}>
                        Promoted: {m.name} ({m.position}) →{" "}
                        {m.slotAfter || "lineup"}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {frs.displacements?.length > 0 ? (
                  <ul className={styles.simRationale}>
                    {frs.displacements.map((m) => (
                      <li key={`disp-${m.playerId || m.name}`}>
                        Displaced: {m.name} ({m.position}) — {m.slotBefore || "lineup"} → bench
                      </li>
                    ))}
                  </ul>
                ) : null}

                {/* Both directions, with equal weight. RosterSimulation's
                    own docstring: "A simulation that only showed what
                    improved would be an advocacy tool." */}
                {frs.needsFixed?.length > 0 || frs.needsCreated?.length > 0 ? (
                  <ul className={styles.simRationale}>
                    {frs.needsFixed?.length > 0 ? (
                      <li>Needs closed: {frs.needsFixed.join(", ")}</li>
                    ) : null}
                    {frs.needsCreated?.length > 0 ? (
                      <li>Needs opened: {frs.needsCreated.join(", ")}</li>
                    ) : null}
                  </ul>
                ) : null}

                {frs.cleanupApplied?.length > 0 ? (
                  <p className={styles.suggestMeta}>
                    {`Solved after ${frs.cleanupApplied.length} required release` +
                      `${frs.cleanupApplied.length === 1 ? "" : "s"} — named under Roster capacity.`}
                  </p>
                ) : null}

                {frs.unpricedIncoming?.length > 0 ? (
                  <p className={styles.suggestMeta}>
                    Incoming, not priced by the board: {frs.unpricedIncoming.join(", ")}
                  </p>
                ) : null}

                {frs.outgoingNotFound?.length > 0 ? (
                  <p className={styles.suggestMeta}>
                    Sent but not found on this roster: {frs.outgoingNotFound.join(", ")}
                  </p>
                ) : null}

                {frs.cleanupIsUpperBound ? (
                  <Banner tone="warning">
                    The releases this was solved against are a worst case, so this final
                    roster is one of a range rather than a determined set.
                  </Banner>
                ) : null}
              </div>
            ) : (
              <Banner tone="neutral" title="Final roster">
                {finalRosterUnavailableText(frs)}
              </Banner>
            )
          ) : null}

          {unresolved.length > 0 ? (
            <Banner tone="warning" title="Unresolved assets">
              {unresolved.join(", ")}
            </Banner>
          ) : null}

          <p className={styles.suggestMeta} style={{ marginTop: "var(--space-2)" }}>
            Equity (receiving − sending): {fmtSigned(simResult.equity)}
          </p>
        </>
      ) : null}
    </Panel>
  );
}

// ── KTC import ────────────────────────────────────────────────────────

export function KtcImportPanel({
  url,
  onUrlChange,
  busy,
  error,
  onSubmit,
  onCancel,
}) {
  return (
    <Panel
      title="Import from KeepTradeCut"
      headingLevel={2}
      subtitle="Replaces sides A and B; extra sides (3+ team trades) are left untouched."
    >
      <div className={styles.importRow}>
        <Input
          className={styles.importInput}
          type="text"
          placeholder="https://keeptradecut.com/trade-calculator?teamOne=…&teamTwo=…"
          value={url}
          onChange={(e) => onUrlChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy) onSubmit();
            if (e.key === "Escape") onCancel();
          }}
          disabled={busy}
          aria-label="KeepTradeCut trade-calculator URL"
          autoFocus
        />
        <Button
          variant="primary"
          onClick={onSubmit}
          disabled={busy || !url.trim()}
          loading={busy}
        >
          Load trade
        </Button>
        <Button onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
      <p className={styles.suggestMeta} style={{ marginTop: "var(--space-2)" }}>
        Unknown KTC IDs and players we can&apos;t match by name are reported here.
      </p>
      {error ? (
        <Banner tone="negative" title="Import failed">
          {error}
        </Banner>
      ) : null}
    </Panel>
  );
}

// ── Pick-team selectors ───────────────────────────────────────────────

export function PickTeamSelectors({
  sides,
  sleeperTeams,
  sideTeamNames,
  onSetTeam,
  stackGateUnmet,
}) {
  return (
    <Panel
      dense
      title="Draft-capital stacks"
      headingLevel={2}
      subtitle="Picks are in this trade — their worth depends on each team's stack. Select the team on each side."
    >
      <div className={styles.pickTeams}>
        {sides.map((s, i) => (
          <Field key={s.id ?? i} label={`Side ${s.label}`} id={`pick-team-${i}`}>
            <Select
              id={`pick-team-${i}`}
              value={sideTeamNames[i] ?? ""}
              onChange={(e) => onSetTeam(i, e.target.value || null)}
            >
              <option value="">— select team —</option>
              {sleeperTeams.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
        ))}
      </div>
      {stackGateUnmet ? (
        <Banner tone="info">
          Verdict is showing pure board value. Assign a team to every side a
          pick is traded to or from to apply the draft-capital stack effect.
        </Banner>
      ) : null}
    </Panel>
  );
}

// ── Side card ─────────────────────────────────────────────────────────

function AssetRow({
  row,
  sideIdx,
  sides,
  side,
  valueMode,
  settings,
  valueOverrides,
  onOpenPlayer,
  onSetValueOverride,
  onClearValueOverride,
  onRemove,
  onSetDestination,
}) {
  const edge = getPlayerEdge(row);
  // 3+-team trades give every asset an explicit destination so the
  // fairness bar can compute per-team NET flow.  For 2-team trades the
  // other side is implicit and the dropdown is hidden.
  const storedDest = side.destinations?.[row.name];
  const parsedDest = Number(storedDest);
  const currentDest =
    Number.isInteger(parsedDest) &&
    parsedDest >= 0 &&
    parsedDest < sides.length &&
    parsedDest !== sideIdx
      ? parsedDest
      : defaultDestination(sideIdx, sides.length);

  return (
    <div className={styles.assetRow}>
      <div className={styles.assetMain}>
        <PlayerImage
          playerId={row.raw?.playerId}
          team={row.team}
          position={row.pos}
          name={row.name}
          size={28}
        />
        <div className={styles.assetBody}>
          <span className={styles.assetName}>
            <button
              type="button"
              className={styles.assetNameButton}
              onClick={() => onOpenPlayer?.(row)}
            >
              {row.name}
            </button>
            {edge.signal ? (
              <Badge tone={edge.signal === "BUY" ? "positive" : "negative"}>
                {edge.signal} {edge.edgePct}%
              </Badge>
            ) : null}
          </span>
          <span className={styles.assetMeta}>
            <span className={styles.assetMetaText}>
              {row.pos} · Consensus{" "}
              {row.blendedSourceRank != null ? row.blendedSourceRank.toFixed(1) : "—"}
              {" · "}
              {Number.isFinite(row.sourceCount) ? row.sourceCount : 0} src
            </span>
            {row.confidenceBucket && row.confidenceBucket !== "high" ? (
              /* W08-F011 (V1-92): the trade builder priced every asset
                 with no visible signal for how thin the evidence behind
                 that price is. `confidenceBucket` already folds
                 freshness in as one of its five axes (see
                 src/api/confidence.py — freshness cannot be read alone
                 per-row, so the bucket IS the backend's per-row
                 freshness-aware truth), so surfacing it here needs no
                 new Date.now()-based staleness invented on the client.
                 Silent for "high" — the expected default — to avoid
                 badging every row in a trade. */
              <Badge
                tone={row.confidenceBucket === "medium" ? "warning" : "negative"}
                title={row.confidenceLabel || undefined}
              >
                {row.confidenceBucket === "none"
                  ? "no confidence data"
                  : `${row.confidenceBucket} confidence`}
              </Badge>
            ) : null}
            <input
              type="number"
              className="asset-value-override-input"
              value={valueOverrides[row.name] != null ? valueOverrides[row.name] : ""}
              placeholder={
                isUnpricedBoardRow(row)
                  ? "—"
                  : String(Math.round(effectiveValue(row, valueMode, settings)))
              }
              onChange={(e) => onSetValueOverride(row.name, e.target.value)}
              onBlur={(e) => {
                if (e.target.value === "") onClearValueOverride(row.name);
              }}
              aria-label={`Override ${row.name}'s value for this trade`}
              title="Override this player's value for this trade only"
            />
            {valueOverrides[row.name] != null ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onClearValueOverride(row.name)}
                aria-label={`Reset ${row.name} to the default value`}
              >
                Reset
              </Button>
            ) : null}
          </span>
        </div>
      </div>
      <div className={styles.assetActions}>
        {sides.length > 2 ? (
          <label className={styles.assetDest}>
            <span className="ds-visually-hidden">Destination for {row.name}</span>
            <Icon name="arrow-right" aria-hidden="true" />
            <Select
              className="trade-dest-select"
              value={currentDest}
              onChange={(e) => onSetDestination(sideIdx, row.name, e.target.value)}
              aria-label={`Send ${row.name} to which side`}
            >
              {sides.map((s, i) =>
                i === sideIdx ? null : (
                  <option key={i} value={i}>
                    Side {s.label}
                  </option>
                ),
              )}
            </Select>
          </label>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          className="trade-remove-btn"
          onClick={() => onRemove(row.name, sideIdx)}
          aria-label={`Remove ${row.name} from Side ${side.label}`}
        >
          Remove
        </Button>
      </div>
    </div>
  );
}

function IncomingRow({ asset, fromSideIdx, sides, valueMode, settings, valueOverrides, onOpenPlayer }) {
  const edge = getPlayerEdge(asset);
  return (
    <div className={`${styles.assetRow} ${styles.assetRowIncoming}`}>
      <div className={styles.assetMain}>
        <PlayerImage
          playerId={asset.raw?.playerId}
          team={asset.team}
          position={asset.pos}
          name={asset.name}
          size={24}
        />
        <div className={styles.assetBody}>
          <span className={styles.assetName}>
            <button
              type="button"
              className={styles.assetNameButton}
              onClick={() => onOpenPlayer?.(asset)}
            >
              {asset.name}
            </button>
            {edge.signal ? (
              <Badge tone={edge.signal === "BUY" ? "positive" : "negative"}>
                {edge.signal} {edge.edgePct}%
              </Badge>
            ) : null}
          </span>
          <span className={styles.assetMeta}>
            {asset.pos} · from Side {sides[fromSideIdx]?.label || "?"} ·{" "}
            {valueOverrides[asset.name] == null && isUnpricedBoardRow(asset)
              ? "not priced"
              : Math.round(
                  valueOverrides[asset.name] ??
                    effectiveValue(asset, valueMode, settings),
                ).toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}

export function SideCard({
  side,
  sideIdx,
  sides,
  total,
  isMySide,
  selectedTeam,
  sideQuery,
  isFocused,
  searchResults,
  settings,
  valueMode,
  valueOverrides,
  incoming,
  balancers,
  onSideQueryChange,
  onSideFocus,
  onSideBlur,
  onAddFromSearch,
  onOpenPlayer,
  onSetValueOverride,
  onClearValueOverride,
  onRemoveAsset,
  onSetDestination,
  onRemoveTeam,
  onAddBalancer,
  registerInputRef,
  canRemoveTeam,
}) {
  const showResults = isFocused && (sideQuery || "").trim().length > 0;
  // Assets the board declined to price contribute 0 to this side's
  // total — a legitimate arithmetic neutral inside the sum, but not
  // something a published total may stay quiet about. 282 of 1,094 live
  // rows are unpriced; without this the side reads as a complete
  // valuation of pieces we never valued.
  const unpriced = unpricedAssetsOnSide(side.assets);

  return (
    <Panel className={isMySide ? styles.mySide : undefined}>
      <div className={styles.sideHeader}>
        <div className={styles.sideHeaderLeft}>
          <h3 style={{ margin: 0 }}>Side {side.label}</h3>
          {isMySide && selectedTeam?.name ? (
            <Badge tone="accent">You · {selectedTeam.name}</Badge>
          ) : null}
          {canRemoveTeam ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemoveTeam(sideIdx)}
              aria-label={`Remove Side ${side.label}`}
            >
              Remove side
            </Button>
          ) : null}
        </div>
        <div className={styles.sideTotals}>
          <div className={styles.sideTotal}>
            {Math.round(total.adjusted).toLocaleString()}
          </div>
          {total.adjustment > 0 ? (
            <div
              className={styles.sideTotalMeta}
              title="Consolidation / roster-spot premium: the side with fewer pieces frees a roster spot, so KTC-style math adds this bonus on top of the raw total."
            >
              Raw {Math.round(total.raw).toLocaleString()} + VA{" "}
              {Math.round(total.adjustment).toLocaleString()}
            </div>
          ) : (
            <div className={styles.sideTotalMeta}>
              Raw {Math.round(total.raw).toLocaleString()}
            </div>
          )}
          {unpriced.length ? (
            <div
              className={styles.sideTotalMeta}
              title={`The board has no value for ${unpriced
                .map((r) => r.name)
                .join(", ")}. They are counted as 0 in this total, which is not the same as being worth 0.`}
            >
              Incomplete — {unpriced.length} unpriced
            </div>
          ) : null}
        </div>
      </div>

      {/* Inline search — type 2-3 letters, a compact dropdown of the top
          matches appears, tap one to add and keep typing. */}
      <div className="trade-side-search">
        <input
          ref={(el) => registerInputRef(sideIdx, el)}
          className="input trade-side-search-input"
          placeholder={`Search to add to Side ${side.label}…`}
          value={sideQuery || ""}
          onChange={(e) => onSideQueryChange(sideIdx, e.target.value)}
          onFocus={() => onSideFocus(sideIdx)}
          onBlur={() => onSideBlur(sideIdx)}
          aria-label={`Search to add a player to Side ${side.label}`}
        />
        {showResults ? (
          <div className="trade-side-search-results">
            {searchResults.length === 0 ? (
              <div className="trade-side-search-empty muted">No matches.</div>
            ) : (
              searchResults.map((r) => (
                <SearchResultRow
                  key={`search-${side.label}-${r.name}`}
                  row={r}
                  settings={settings}
                  onPick={(row) => onAddFromSearch(row, sideIdx)}
                  keyPrefix={`search-${side.label}`}
                />
              ))
            )}
          </div>
        ) : null}
      </div>

      {sides.length > 2 ? (
        <div className={styles.sideGroupLabel}>Giving</div>
      ) : null}

      <div className={styles.assetList}>
        {side.assets.map((r) => (
          <AssetRow
            key={`${side.label}-${r.name}`}
            row={r}
            side={side}
            sideIdx={sideIdx}
            sides={sides}
            valueMode={valueMode}
            settings={settings}
            valueOverrides={valueOverrides}
            onOpenPlayer={onOpenPlayer}
            onSetValueOverride={onSetValueOverride}
            onClearValueOverride={onClearValueOverride}
            onRemove={onRemoveAsset}
            onSetDestination={onSetDestination}
          />
        ))}
        {side.assets.length === 0 ? (
          <span className={styles.assetEmpty}>No assets yet.</span>
        ) : null}
      </div>

      {/* Receiving — 3+-team mode only, so each card answers both "what
          am I giving up?" and "what am I getting back?" in one place. */}
      {sides.length > 2 ? (
        <>
          <div className={styles.sideGroupLabel}>Receiving</div>
          <div className={styles.assetList}>
            {(incoming || []).length > 0 ? (
              incoming.map(({ asset, fromSideIdx }) => (
                <IncomingRow
                  key={`recv-${side.label}-${asset.name}`}
                  asset={asset}
                  fromSideIdx={fromSideIdx}
                  sides={sides}
                  valueMode={valueMode}
                  settings={settings}
                  valueOverrides={valueOverrides}
                  onOpenPlayer={onOpenPlayer}
                />
              ))
            ) : (
              <span className={styles.assetEmpty}>
                Nothing incoming. Assign a destination on another side to route here.
              </span>
            )}
          </div>
        </>
      ) : null}

      {balancers ? (
        <div className={styles.balancers}>
          <span className={styles.balancerLabel}>{balancers.label}</span>
          {balancers.list.map((b) => (
            <Button
              key={b.name}
              variant="ghost"
              size="sm"
              onClick={() => onAddBalancer(b.name, sideIdx)}
              /* The suggestion says what it LANDS ON, not just what it
                 is worth.  ``imbalanceAfter`` is measured through the
                 same adjusted-gap path the meter renders, so the number
                 here is checkable against the meter after the click
                 (defect #800). */
              title={
                Number.isFinite(b.imbalanceAfter)
                  ? `Leaves a gap of ${Math.round(b.imbalanceAfter).toLocaleString()} (now ${Math.round(b.imbalanceBefore).toLocaleString()})`
                  : undefined
              }
            >
              {b.name} ({b.pos}) · {b.value.toLocaleString()}
              {Number.isFinite(b.imbalanceAfter) ? (
                <span className={styles.balancerResidual}>
                  {" "}
                  → {Math.round(b.imbalanceAfter).toLocaleString()}
                </span>
              ) : null}
            </Button>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

// ── Suggestion desk ───────────────────────────────────────────────────

function SuggestionCard({ suggestion: s, index, onApply }) {
  const eb = edgeMeta(s.edge);
  const cb = confidenceMeta(s.confidence);
  const rs = s.rankScore;
  const isTopPick = index === 0 && rs && rs.total >= 12;

  return (
    <div
      className={`${styles.suggestCard} ${isTopPick ? styles.suggestCardTop : ""}`}
    >
      <div className={styles.suggestBody}>
        <div className={styles.suggestLines}>
          <span className={styles.suggestRank}>#{index + 1}</span>
          <div className={styles.suggestSides}>
            <div className={styles.suggestSide}>
              <span className={`${styles.suggestSideLabel} ${styles.suggestSideGive}`}>
                Give{" "}
              </span>
              {s.give.map((p, pi) => (
                <span key={pi}>
                  {pi > 0 ? " + " : ""}
                  {p.name}
                  <span className={styles.suggestPlayerMeta}>
                    {" "}
                    {p.position} {p.displayValue.toLocaleString()}
                  </span>
                </span>
              ))}
            </div>
            <div className={styles.suggestSide}>
              <span className={`${styles.suggestSideLabel} ${styles.suggestSideGet}`}>
                Get{" "}
              </span>
              {s.receive.map((p, pi) => (
                <span key={pi}>
                  {pi > 0 ? " + " : ""}
                  {p.name}
                  <span className={styles.suggestPlayerMeta}>
                    {" "}
                    {p.position} {p.displayValue.toLocaleString()}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className={styles.suggestBadges}>
          <Badge tone={fairnessTone(s.fairness)}>
            {fairnessLabel(s.fairness)}
            {s.gap !== 0
              ? ` (${s.gap > 0 ? "+" : ""}${s.gap.toLocaleString()})`
              : ""}
          </Badge>
          <Badge tone={cb.tone}>{cb.label}</Badge>
          {s.strategy !== "neutral" ? (
            <Badge tone="neutral">
              {s.strategy === "contender" ? "Contender move" : "Rebuilder move"}
            </Badge>
          ) : null}
          {eb ? <Badge tone={eb.tone}>{eb.text}</Badge> : null}
        </div>

        <div className={styles.suggestNotes}>
          <span>{s.rationale}</span>
          {s.whyThisHelps ? (
            <span className={styles.suggestWhy}>{s.whyThisHelps}</span>
          ) : null}
          {s.edgeExplanation ? <span>{s.edgeExplanation}</span> : null}
          {s.suggestedBalancers?.length > 0 ? (
            <span>
              To even it out, add:{" "}
              {s.suggestedBalancers
                .map((b) => `${b.name} (${b.displayValue.toLocaleString()})`)
                .join(", ")}
            </span>
          ) : null}
          {s.opponentFit ? (
            <span className={styles.suggestWhy}>{s.opponentFit}</span>
          ) : null}
        </div>

        {rs ? (
          <details>
            <summary className={styles.suggestMeta}>
              Why #{index + 1}? Score {rs.total}
            </summary>
            <div className={styles.suggestScore}>
              Value {rs.base_value} + Fairness {rs.fairness} + Consensus{" "}
              {rs.confidence}
              {rs.need_severity > 0 ? ` + Need ${rs.need_severity}` : ""}
              {rs.edge > 0 ? ` + Edge ${rs.edge}` : ""}
              {rs.opponent_fit > 0 ? ` + Partner ${rs.opponent_fit}` : ""} ={" "}
              {rs.total}
            </div>
          </details>
        ) : null}
      </div>

      <Button size="sm" onClick={() => onApply(s)}>
        Load trade
      </Button>
    </div>
  );
}

const EMPTY_SUGGESTION_COPY = {
  sellHigh:
    "No sell-high opportunities found. You may not have enough depth at any position to move a piece.",
  buyLow:
    "No buy-low targets found. Your surplus positions may not have tradeable pieces in the right value range.",
  consolidation:
    "No consolidation trades found. This requires 2+ depth pieces that combine into a single upgrade.",
  positionalUpgrades:
    "No positional upgrades found. Your starters may already be top-tier, or no upgrade targets match your depth value.",
};

export function SuggestionsDesk({
  sleeperTeams,
  selectedTeamIdx,
  onSelectTeam,
  leagueRosters,
  rosterInput,
  onRosterInputChange,
  onFetch,
  loading,
  error,
  suggestions,
  suggestionTab,
  onTabChange,
  suggestionCounts,
  rosterCount,
  onApply,
}) {
  const analysis = suggestions?.rosterAnalysis;
  const list = suggestions?.[suggestionTab] || [];

  return (
    <Panel
      title="Trade suggestions"
      headingLevel={2}
      subtitle={
        sleeperTeams
          ? "Select your team from the league, or enter a roster manually."
          : "Enter your roster to get roster-aware trade ideas."
      }
    >
      <div className={styles.suggestControls}>
        {sleeperTeams ? (
          <div className={styles.suggestRow}>
            <Field label="Your team" id="suggest-team">
              <Select
                id="suggest-team"
                value={selectedTeamIdx}
                onChange={(e) => onSelectTeam(e.target.value)}
              >
                <option value={-1}>Select your team…</option>
                {sleeperTeams.map((t, i) => (
                  <option key={i} value={i}>
                    {t.name} ({(t.players || []).length} players,{" "}
                    {(t.picks || []).length} picks)
                  </option>
                ))}
              </Select>
            </Field>
            {selectedTeamIdx >= 0 && sleeperTeams[selectedTeamIdx] ? (
              <span className={styles.suggestMeta}>
                Loaded {(sleeperTeams[selectedTeamIdx].players || []).length}{" "}
                players + {(sleeperTeams[selectedTeamIdx].picks || []).length}{" "}
                picks
                {leagueRosters ? ` · ${leagueRosters.length} opponents` : ""}
              </span>
            ) : null}
          </div>
        ) : null}

        <Field label="Roster" id="suggest-roster">
          <textarea
            id="suggest-roster"
            className={`ds-input ${styles.suggestTextarea}`}
            placeholder="Enter roster (comma or newline separated): Josh Allen, Bijan Robinson, Ja'Marr Chase, …"
            value={rosterInput}
            onChange={(e) => onRosterInputChange(e.target.value)}
            rows={3}
          />
        </Field>

        <div className={styles.suggestRow}>
          <Button variant="primary" onClick={onFetch} disabled={loading} loading={loading}>
            Get suggestions
          </Button>
          {suggestions ? (
            <span className={styles.suggestMeta}>
              {suggestions.totalSuggestions} suggestions ·{" "}
              {suggestions.metadata?.rosterMatched || 0}/{rosterCount} matched
              {(suggestions.metadata?.opponentRostersAnalyzed || 0) > 0
                ? ` · ${suggestions.metadata.opponentRostersAnalyzed} opponents analyzed`
                : ""}
            </span>
          ) : null}
        </div>

        {error ? (
          <Banner tone="negative" title="Suggestions failed">
            {error}
          </Banner>
        ) : null}

        {analysis ? (
          <div className={styles.suggestAnalysis}>
            {analysis.surplusPositions.length > 0 ? (
              <span>
                Can trade from{" "}
                <Badge tone="positive">{analysis.surplusPositions.join(", ")}</Badge>
              </span>
            ) : null}
            {analysis.needPositions.length > 0 ? (
              <span>
                Should target{" "}
                <Badge tone="negative">{analysis.needPositions.join(", ")}</Badge>
              </span>
            ) : null}
            {analysis.surplusPositions.length === 0 &&
            analysis.needPositions.length === 0 ? (
              <span className={styles.suggestMeta}>
                Roster is balanced — no clear surplus or need detected.
              </span>
            ) : null}
          </div>
        ) : null}

        {suggestions && suggestions.totalSuggestions > 0 ? (
          <>
            {/* Filter toggles, not tabs. These were `role="tablist"` +
                `role="tab"` + `aria-selected` with no `role="tabpanel"`
                and no `aria-controls` anywhere in the file — the list
                below is a plain div. A tab that controls nothing is not
                a tab: a screen reader announces "tab, 1 of 4" and then
                finds no tabpanel to move to, which is worse than plain
                buttons because it promises a structure that isn't there.
                Hand-adding `aria-controls` would have made it worse
                still, by naming a region that does not exist.
                These are pressed-state filters over one list, so that is
                what they now say. Guarded by
                __tests__/a11y-tab-roles.test.js. */}
            <div
              className={styles.suggestBadges}
              role="group"
              aria-label="Suggestion category"
            >
              {SUGG_TYPES.map((t) => {
                const count = suggestionCounts[t.key] || 0;
                const isActive = suggestionTab === t.key;
                return (
                  <Button
                    key={t.key}
                    size="sm"
                    variant={isActive ? "primary" : "ghost"}
                    aria-pressed={isActive}
                    onClick={() => onTabChange(t.key)}
                    disabled={count === 0 && !isActive}
                  >
                    {t.label}
                    {count > 0 ? ` (${count})` : ""}
                  </Button>
                );
              })}
            </div>

            <div className={styles.suggestList}>
              {list.map((s, i) => (
                <SuggestionCard
                  key={`${suggestionTab}-${i}`}
                  suggestion={s}
                  index={i}
                  onApply={onApply}
                />
              ))}
              {list.length === 0 ? (
                <p className={styles.suggestMeta}>
                  {EMPTY_SUGGESTION_COPY[suggestionTab]}
                </p>
              ) : null}
            </div>
          </>
        ) : null}

        {suggestions && suggestions.totalSuggestions === 0 ? (
          <Banner tone="info" title="No trade suggestions found">
            {suggestions.metadata?.rosterMatched < 5
              ? `Only ${suggestions.metadata?.rosterMatched || 0} of ${rosterCount} players matched our database. Check spelling or add more players.`
              : suggestions.rosterAnalysis?.surplusPositions?.length === 0
                ? "Your roster has no clear positional surplus. The engine needs at least one position with depth beyond starters to suggest trades."
                : "Your roster appears well-balanced. No actionable trades met our quality threshold."}
          </Banner>
        ) : null}
      </div>
    </Panel>
  );
}
