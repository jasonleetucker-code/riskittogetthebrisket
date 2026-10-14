"use client";

/**
 * trade-suggestions-desk.jsx — the "Trade suggestions" desk.
 *
 * Split out of ./trade-sections.jsx so /trade can load it on demand
 * (React.lazy in app/trade/page.jsx): it sits at the foot of the page, below the builder,
 * the verdict and Second opinions.
 * Pure presentation, moved verbatim — no trade math lives here.
 */

import { Badge, Banner, Button, Field, Panel, Select } from "@/components/ds";
import { SUGG_TYPES } from "./trade-sections";
import styles from "./trade.module.css";

// ── Suggestion card helpers ───────────────────────────────────────────

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

// `_confidence_from_sources` (src/trade/suggestions.py) buckets a SOURCE
// COUNT (6+ / 3-5 / fewer) — the thinner-covered piece of a sell-high or
// buy-low swap, the target of a consolidation or upgrade. It does not
// measure whether those sources agree, so the label names coverage, not
// consensus.
export function confidenceMeta(c) {
  if (c === "high") return { label: "6+ sources", tone: "positive" };
  if (c === "medium") return { label: "3–5 sources", tone: "warning" };
  return { label: "Under 3 sources", tone: "neutral" };
}

export function edgeMeta(edge) {
  if (edge === "market_discount") return { text: "Buy Low", tone: "positive" };
  if (edge === "market_premium") return { text: "Sell High", tone: "negative" };
  if (edge === "high_dispersion") return { text: "Sources Disagree", tone: "warning" };
  return null;
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
