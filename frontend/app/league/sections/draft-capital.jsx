"use client";

// DraftCapitalSection — public /league tab view.
// Shows the live auction-dollar draft capital board from /api/draft-capital.
// Purely public data (same endpoint powered the old /draft-capital page).
// When this tab is the default, /league mobile users land here.
//
// Year selector (owner request 2026-10-01): "All Years | <season>...".  The
// selection lives in the URL (`?year=2027`, owned by LeagueClient), so it
// survives reload, back/forward and direct links.  The selector changes WHICH
// picks are shown, never HOW they are valued — per-season capital and ranks
// are the backend's `teamTotalsByYear` (src/api/draft_capital_years.py), the
// sum of the same per-pick dollars the All Years total is made of.  See
// lib/draft-capital-years.js.

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { LoadingState, EmptyState } from "@/components/ui";
import { SegmentedControl } from "@/components/ds/SegmentedControl";
import { EmptyCard } from "../shared.jsx";
import { effectiveAuctionPower } from "@/lib/auction-power";
import {
  ALL_YEARS,
  availableDraftCapitalYears,
  draftCapitalPickLabel,
  draftCapitalPicksForYear,
  draftCapitalSlotsAreStandIns,
  draftCapitalTeamRows,
  draftCapitalYearSummary,
  isUnpricedPick,
  parseDraftCapitalYear,
} from "@/lib/draft-capital-years";

// Dynamically import the trade simulator so its JS goes into a
// separate chunk (loaded on demand when DraftCapital tab renders)
// instead of inflating the /league page bundle.
const TradeSimulator = dynamic(() => import("./_trade-simulator.jsx"), {
  ssr: false,
});

// Same treatment as the simulator: its own chunk, loaded when this tab
// renders rather than inflating the /league bundle.
const PickProjectorPanel = dynamic(() => import("./_pick-projector.jsx"), {
  ssr: false,
});

function fmtDollar(v) {
  if (v == null) return "$0";
  const n = Number(v);
  if (!Number.isFinite(n)) return "$0";
  // Match the Google Sheet's display: currency format with 0 decimals
  // rounds half-dollars up ($1.5 → $2, $28.5 → $29).  The underlying
  // value the server returns stays half-dollar so team-totals math
  // remains accurate; only the per-cell display is rounded.
  return `$${Math.round(n)}`;
}

// A capital figure that may be UNKNOWN (every pick behind it unpriced).
// Never rendered as $0 — MISSING IS NEVER ZERO.
function fmtCapital(v) {
  const n = typeof v === "number" ? v : NaN;
  return Number.isFinite(n) ? fmtDollar(n) : "—";
}

function pickDollar(p) {
  return isUnpricedPick(p) ? null : (p.adjustedDollarValue ?? p.dollarValue);
}

function sumPriced(picks) {
  return (picks || []).reduce((s, p) => s + (pickDollar(p) ?? 0), 0);
}

export default function DraftCapitalSection({ yearParam = "", setYear } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        setLoading(true);
        const res = await fetch("/api/draft-capital");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!active) return;
        if (json.error) {
          setError(json.error);
        } else {
          setData(json);
        }
      } catch (err) {
        if (active) setError(err?.message || "Failed to load draft capital.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  const years = useMemo(() => availableDraftCapitalYears(data), [data]);
  const selectedYear = parseDraftCapitalYear(yearParam, years);

  // An invalid or obsolete `?year=` (a retired class, garbage) renders All
  // Years; once the payload has said which seasons exist, drop the stale
  // param so a copied link does not carry it forward.
  useEffect(() => {
    if (!data || !yearParam || !setYear) return;
    if (parseDraftCapitalYear(yearParam, years) === null) setYear(null);
  }, [data, yearParam, years, setYear]);

  if (loading) return <LoadingState message="Loading draft capital..." />;
  if (error) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="Draft capital unavailable" message={error} />
      </div>
    );
  }
  if (!data) return <EmptyCard label="Draft capital" />;

  // Picks for the season the header claims to be describing. Rows carry
  // `season`; when none do (the workbook path, one season only) this is the
  // whole list, so the filter is inert there rather than emptying the page.
  const currentSeasonPicks = (() => {
    const all = data.picks || [];
    const season = Number(data.season);
    if (!Number.isFinite(season)) return all;
    const scoped = all.filter((p) => Number(p?.season) === season);
    return scoped.length > 0 ? scoped : all;
  })();

  const slotsAreStandIns = draftCapitalSlotsAreStandIns(data);
  const multiYear = years.length > 1;
  const teamRows = draftCapitalTeamRows(data, selectedYear);
  const summary = draftCapitalYearSummary(data, selectedYear);
  // Team pick lists show every pick their figure is made of: All Years →
  // every season's picks (the total spans all of them), a season → its own.
  const listPicks = draftCapitalPicksForYear(data.picks, selectedYear, data.season);
  // The round grids below describe ONE draft: the selected season, or the
  // current season under All Years (unchanged).
  const gridPicks = selectedYear == null ? currentSeasonPicks : listPicks;
  const unpricedCount =
    selectedYear == null
      ? (data.picks || []).filter(isUnpricedPick).length
      : (summary?.unpricedPickCount ?? listPicks.filter(isUnpricedPick).length);
  const viewPickCount = selectedYear == null ? (data.picks || []).length : listPicks.length;

  const scopeLabel =
    selectedYear != null
      ? `${selectedYear} picks`
      : multiYear
        ? `${years[0]}–${years[years.length - 1]} picks`
        : `${data.season} draft`;
  const budgetLabel =
    selectedYear != null && summary
      ? `${fmtCapital(summary.totalDollars)} of the $${data.totalBudget} pool`
      : `$${data.totalBudget} total budget`;

  const yearOptions = [
    { value: ALL_YEARS, label: "All Years" },
    ...years.map((y) => ({ value: String(y), label: String(y) })),
  ];

  return (
    <>
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--space-sm)",
            marginBottom: 4,
          }}
        >
          <div style={{ fontWeight: 700 }}>Draft Capital</div>
          {years.length > 0 && (
            <SegmentedControl
              label="Draft year"
              value={selectedYear == null ? ALL_YEARS : String(selectedYear)}
              onChange={(v) => setYear?.(v === ALL_YEARS ? null : v)}
              options={yearOptions}
            />
          )}
        </div>
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--subtext)",
            marginBottom: 10,
          }}
        >
          {scopeLabel} · {data.numTeams} teams · {data.draftRounds} rounds ·{" "}
          {budgetLabel}
        </div>
        {(selectedYear != null || multiYear || slotsAreStandIns || unpricedCount > 0) && (
          <ul
            data-testid="draft-capital-notes"
            style={{
              margin: "0 0 10px",
              paddingLeft: 16,
              fontSize: "0.66rem",
              color: "var(--muted)",
              lineHeight: 1.5,
            }}
          >
            {(selectedYear != null || multiYear) && (
              <li>
                One ${data.totalBudget} pool is spread across every listed pick; a
                year view adds up that year&apos;s share of it. Values are not
                rescaled per year.
              </li>
            )}
            {slotsAreStandIns && (
              <li>
                Estimated: future draft order is not known yet, so picks show
                their round only and carry that round&apos;s average value.
              </li>
            )}
            {unpricedCount > 0 && (
              <li style={{ color: "var(--amber)" }}>
                {unpricedCount} of {viewPickCount} picks could not be priced —
                left out of the totals, not counted as $0.
              </li>
            )}
          </ul>
        )}
        <div
          style={{
            fontSize: "0.66rem",
            color: "var(--muted)",
            marginBottom: 10,
          }}
        >
          <span style={{ color: "var(--green)", fontWeight: 700 }}>green</span>{" "}
          = raw auction $ ·{" "}
          <span style={{ color: "var(--cyan)", fontWeight: 700 }}>▲ cyan</span>{" "}
          = effective auction power (stacking-adjusted, zero-sum)
        </div>
        {selectedYear != null && summary && summary.pickCount === 0 ? (
          <EmptyState
            title={`No ${selectedYear} picks`}
            message={`No team in this league holds a ${selectedYear} pick.`}
          />
        ) : (
          <TeamTotalsChart
            teamTotals={teamRows}
            picks={listPicks}
            totalBudget={data.totalBudget}
            numTeams={data.numTeams}
            draftRounds={data.draftRounds}
            seasonLabel={selectedYear ?? (multiYear ? scopeLabel : data.season)}
            selectedYear={selectedYear}
            years={years}
            slotsAreStandIns={slotsAreStandIns}
          />
        )}
      </div>

      {/* The Sleeper-derived path builds BOTH the current season and the next
          into one flat picks array (it stamps `coveredPickYears` to say so),
          and every grid below groups by round with no season filter — so each
          round rendered twice, with duplicate "1.01" labels and a doubled
          round total. The workbook path carries one season and is unaffected,
          which is why nothing caught it. Filter once, here, and pass ONE
          season's picks down: the selected year, else the current season. */}
      <PickValueGrid
        picks={gridPicks}
        draftRounds={data.draftRounds}
        numTeams={data.numTeams}
        slotsAreStandIns={slotsAreStandIns}
      />

      {/* Future picks — where they land, not what they are worth. The
          grid above is the current season's actual draft; this is the
          projection for the ones after it. */}
      <PickProjectorPanel />

      <TradeSimulator picks={currentSeasonPicks} teamTotals={data.teamTotals} />

      <PicksByRound
        picks={gridPicks}
        draftRounds={data.draftRounds}
        slotsAreStandIns={slotsAreStandIns}
      />
    </>
  );
}

/* ── Team totals bar chart ─────────────────────────────────────────────── */
function TeamTotalsChart({
  teamTotals,
  picks,
  totalBudget,
  numTeams,
  draftRounds,
  seasonLabel,
  selectedYear = null,
  years = [],
  slotsAreStandIns = false,
}) {
  const rows = teamTotals || [];
  const known = rows.filter((t) => Number.isFinite(t.auctionDollars));
  const maxDollars = Math.max(...known.map((t) => t.auctionDollars), 1);
  const multiYear = years.length > 1;
  const showBreakdown = selectedYear == null && multiYear;

  // Effective auction power is a presentation lens computed client-side
  // from the raw per-team dollars (zero-sum; src/api/auction_power.py
  // is the source of truth).  No extra backend payload.  Computed over
  // the rows on screen; a team whose capital is unknown is left out
  // rather than entered as $0.
  const effectiveByTeam = effectiveAuctionPower(
    Object.fromEntries(known.map((t) => [t.team, t.auctionDollars])),
  );

  return (
    <div style={{ marginTop: "var(--space-md)" }}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-sm)",
        }}
      >
        {rows.map((team, i) => {
          const capital = team.auctionDollars;
          const capitalKnown = Number.isFinite(capital);
          const pct = capitalKnown ? (capital / maxDollars) * 100 : 0;
          const effectiveDollars = capitalKnown ? effectiveByTeam[team.team] : undefined;
          const teamPicks = (picks || [])
            .filter((p) => p.currentOwner === team.team)
            .sort(
              (a, b) =>
                (Number(a.season) || 0) - (Number(b.season) || 0) ||
                (a.overallPick ?? 0) - (b.overallPick ?? 0),
            );
          const tradedCount = teamPicks.filter((p) => p.isTraded).length;
          const unpriced = Number.isFinite(team.unpricedPickCount)
            ? team.unpricedPickCount
            : teamPicks.filter(isUnpricedPick).length;
          const rank = selectedYear == null ? i + 1 : (team.rank ?? "—");

          return (
            <div
              key={team.team}
              data-testid="draft-capital-team-row"
              style={{
                padding: "var(--space-sm) var(--space-md)",
                borderRadius: "var(--radius-sm)",
                background:
                  i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-sm)",
                }}
              >
                <span
                  className="font-mono"
                  style={{
                    width: 22,
                    fontSize: "0.68rem",
                    color: "var(--muted)",
                    textAlign: "right",
                    flexShrink: 0,
                  }}
                >
                  {rank}
                </span>

                <span
                  className="truncate"
                  style={{
                    minWidth: 100,
                    maxWidth: 140,
                    fontSize: "0.82rem",
                    fontWeight: 600,
                  }}
                >
                  {team.team}
                </span>

                <div
                  style={{
                    flex: 1,
                    background: "var(--bg-soft)",
                    borderRadius: "var(--radius-sm)",
                    height: 20,
                    overflow: "hidden",
                    border: "1px solid rgba(255,255,255,0.04)",
                  }}
                >
                  <div
                    style={{
                      width: `${pct}%`,
                      height: "100%",
                      background:
                        "linear-gradient(90deg, var(--cyan), rgba(79, 155, 236, 0.6))",
                      borderRadius: "var(--radius-sm)",
                      transition: "width 0.4s ease-out",
                      boxShadow:
                        pct > 30 ? "0 0 12px rgba(79, 155, 236, 0.15)" : "none",
                    }}
                  />
                </div>

                <span
                  className="font-mono"
                  title={capitalKnown ? undefined : "None of these picks could be priced"}
                  style={{
                    minWidth: 48,
                    textAlign: "right",
                    fontSize: "0.82rem",
                    fontWeight: 700,
                    color: capitalKnown ? "var(--green)" : "var(--muted)",
                  }}
                >
                  {fmtCapital(capital)}
                </span>

                {Number.isFinite(effectiveDollars) &&
                  effectiveDollars !== capital && (
                    <span
                      className="font-mono"
                      title={
                        "Effective auction power: raw capital adjusted for stacking. " +
                        "A clearly-biggest stack is worth more than its linear sum " +
                        "(you can outbid the field for the #1 rookie); an " +
                        "already-dominant stack saturates (extra picks worth less). " +
                        "Zero-sum across the league."
                      }
                      style={{
                        minWidth: 52,
                        textAlign: "right",
                        fontSize: "0.74rem",
                        fontWeight: 600,
                        color:
                          effectiveDollars > capital
                            ? "var(--cyan)"
                            : "var(--muted)",
                      }}
                    >
                      {effectiveDollars > capital ? "▲" : "▼"}
                      {fmtDollar(effectiveDollars)}
                    </span>
                  )}

                <span
                  className="badge badge-cyan"
                  style={{ fontSize: "0.64rem", padding: "1px 6px" }}
                >
                  {Number.isFinite(team.pickCount) ? team.pickCount : teamPicks.length}pk
                </span>
              </div>

              <div
                style={{
                  marginTop: 3,
                  marginLeft: 30,
                  fontSize: "0.68rem",
                  color: "var(--muted)",
                  lineHeight: 1.6,
                }}
              >
                {teamPicks.length === 0 && (
                  <span data-testid="draft-capital-no-picks">
                    {selectedYear != null ? `No ${selectedYear} picks` : "No picks"}
                  </span>
                )}
                {teamPicks.map((p, j) => {
                  const unpricedPick = isUnpricedPick(p);
                  return (
                    // inline-block: each pick is a wrap point.  The labels and
                    // middle-dot separators carry no break opportunity, so a
                    // long list ran as one unbreakable word past 375px.
                    <span
                      key={`${p.season ?? ""}:${p.round}:${p.pick}:${p.originalOwner}:${j}`}
                      style={{ display: "inline-block" }}
                    >
                      {j > 0 && (
                        <span style={{ margin: "0 2px", opacity: 0.3 }}>·</span>
                      )}
                      <span
                        title={`${p.season ?? ""} round ${p.round}, originally ${p.originalOwner}${
                          unpricedPick ? " — unpriced" : ""
                        }`.trim()}
                        style={p.isTraded ? { color: "var(--amber)" } : undefined}
                      >
                        {draftCapitalPickLabel(p, {
                          slotsAreStandIns,
                          withSeason: selectedYear == null && multiYear,
                        })}
                        {p.isTraded ? "*" : ""}
                        {unpricedPick ? "?" : ""}
                      </span>
                    </span>
                  );
                })}
                {tradedCount > 0 && (
                  <span
                    style={{
                      marginLeft: 6,
                      color: "var(--amber)",
                      opacity: 0.7,
                    }}
                  >
                    ({tradedCount} traded)
                  </span>
                )}
                {unpriced > 0 && (
                  <span style={{ marginLeft: 6 }}>({unpriced} unpriced)</span>
                )}
              </div>

              {showBreakdown && team.draftCapitalByYear && (
                <div
                  className="font-mono"
                  data-testid="draft-capital-year-breakdown"
                  style={{
                    marginTop: 1,
                    marginLeft: 30,
                    fontSize: "0.66rem",
                    color: "var(--subtext)",
                  }}
                >
                  {years
                    .map((y) => {
                      const v = team.draftCapitalByYear[String(y)];
                      return `${y} ${v == null ? "unpriced" : fmtDollar(v)}`;
                    })
                    .join(" · ")}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: "var(--space-md)",
          padding: "var(--space-sm) var(--space-md)",
          fontSize: "0.72rem",
          color: "var(--muted)",
          borderTop: "1px solid var(--border)",
        }}
      >
        ${totalBudget} total budget across {numTeams} teams, {draftRounds}{" "}
        rounds ({seasonLabel}). <span style={{ color: "var(--amber)" }}>*</span> =
        traded pick.
        {(picks || []).some(isUnpricedPick) && <> ? = unpriced pick.</>}
      </div>
    </div>
  );
}

function PickValueGrid({ picks, draftRounds, numTeams, slotsAreStandIns = false }) {
  if (!picks || !picks.length) return null;
  const rounds = [];
  for (let r = 1; r <= (draftRounds || 6); r++) {
    rounds.push((picks || []).filter((p) => p.round === r));
  }
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "baseline",
          gap: "var(--space-sm)",
          marginBottom: "var(--space-sm)",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>
          Pick Values
        </span>
        <span className="text-xs muted">
          {slotsAreStandIns
            ? "Estimated — draft order not known yet: columns are original-team order and every pick in a round carries that round's value"
            : "Adjusted values used for team totals (expansion picks 1 & 2 averaged)"}
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 70 }}>Round</th>
              {Array.from({ length: numTeams || 12 }, (_, i) => (
                <th
                  key={i}
                  style={{
                    textAlign: "right",
                    fontSize: "0.72rem",
                    minWidth: 44,
                  }}
                >
                  {slotsAreStandIns ? `T${i + 1}` : `Pk ${i + 1}`}
                </th>
              ))}
              <th style={{ textAlign: "right", fontWeight: 700, minWidth: 50 }}>
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((rp, ri) => {
              const total = sumPriced(rp);
              return (
                <tr key={ri}>
                  <td className="font-mono font-bold">R{ri + 1}</td>
                  {rp.map((p, j) => (
                    <td
                      key={j}
                      className="font-mono"
                      style={{
                        textAlign: "right",
                        fontSize: "0.76rem",
                        color: p.isExpansion ? "var(--amber)" : undefined,
                      }}
                    >
                      {fmtCapital(pickDollar(p))}
                    </td>
                  ))}
                  <td
                    className="font-mono font-bold text-green"
                    style={{ textAlign: "right" }}
                  >
                    {fmtDollar(total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PicksByRound({ picks, draftRounds, slotsAreStandIns = false }) {
  const rounds = [];
  for (let round = 1; round <= (draftRounds || 4); round++) {
    const roundPicks = (picks || []).filter((p) => p.round === round);
    rounds.push({
      round,
      picks: roundPicks,
      total: sumPriced(roundPicks),
      unpriced: roundPicks.filter(isUnpricedPick).length,
    });
  }

  return (
    <>
      {rounds.map(({ round, picks: roundPicks, total, unpriced }) => (
        <div
          key={round}
          className="card"
          style={{ marginTop: "var(--space-md)" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--space-sm)",
              marginBottom: "var(--space-sm)",
            }}
          >
            <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>
              Round {round}
            </span>
            <span className="badge badge-green" style={{ fontSize: "0.64rem" }}>
              {fmtDollar(total)}
            </span>
            <span className="text-xs muted">
              {roundPicks.length} picks
              {unpriced > 0 ? ` · ${unpriced} unpriced` : ""}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Pick</th>
                  <th style={{ width: 60 }}>Value</th>
                  <th>Owner</th>
                  <th>Original</th>
                </tr>
              </thead>
              <tbody>
                {roundPicks.map((pick, idx) => (
                  <tr key={idx}>
                    <td className="font-mono font-bold">
                      {draftCapitalPickLabel(pick, { slotsAreStandIns })}
                    </td>
                    <td className="font-mono font-bold text-green">
                      {isUnpricedPick(pick) ? (
                        <span className="muted">unpriced</span>
                      ) : (
                        fmtDollar(pickDollar(pick))
                      )}
                    </td>
                    <td style={{ fontWeight: 600 }}>{pick.currentOwner}</td>
                    <td>
                      {pick.isTraded ? (
                        <span
                          className="badge badge-amber"
                          style={{ fontSize: "0.64rem" }}
                        >
                          {pick.originalOwner}
                        </span>
                      ) : (
                        <span className="muted">&mdash;</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}
