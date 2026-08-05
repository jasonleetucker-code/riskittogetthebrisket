"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useApp } from "@/components/AppShell";
import { isTopRankedForEdgePremium } from "@/lib/edge-helpers";
import {
  isEligibleForAnalysis,
  idpMarketAction,
  isIdpInTopByIdptc,
} from "@/lib/display-helpers";
import ConfidenceValueScatter from "@/components/graphs/ConfidenceValueScatter";
import {
  EDGE_SECTION_LIMIT,
  EDGE_PREMIUM_LIMIT,
  EDGE_CAUTION_RANK_LIMIT,
  EDGE_PREMIUM_RANK_LIMIT,
  PREMIUM_SUMMARY_SPREAD,
  PREMIUM_SUMMARY_MAGNITUDE,
} from "@/lib/thresholds";
import { getRetailLabel } from "@/lib/dynasty-data";
import {
  Banner,
  DataTable,
  EmptyState,
  InfoTip,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
  StatTile,
  Tabs,
  tabPanelId,
  ValueBasisNote,
} from "@/components/ds";
import {
  colConfidence,
  colFlags,
  colGapDirection,
  colIdpGap,
  colPlayer,
  colPos,
  colRank,
  colSignal,
  colSpread,
  colValue,
} from "./edge-columns";
import styles from "./edge.module.css";

// ── EDGE (Redesign R3) ───────────────────────────────────────────────
// Source-agreement analysis as a trading screen. Every signal traces
// to a measurable property of the ranking sources — nothing here is
// predicted or editorialized.
//
// The pre-R3 page stacked eight equally-weighted sections in one wall
// of cards; nothing told you where to look. The signals actually fall
// into three families, so they're grouped that way and the actionable
// one leads:
//
//   Market gaps — where one market disagrees with the other and you
//                 can trade against it (offense vs KTC, IDP vs IDPTC)
//   Agreement   — the structure of consensus: safest anchors, and the
//                 widest disputes
//   Data caution— what to know before trusting a row
//
// Every dataset, threshold, filter, and limit is preserved verbatim.
// The tables gain sortability (they were static) and the IDP sections
// gain a visible Gap column — that magnitude already drove their
// ordering, it was just buried in a title attribute.

const IDP_TOP_LIMIT = 200;

const SIGNAL_TABS = [
  { id: "gaps", label: "Market gaps" },
  { id: "agreement", label: "Agreement" },
  { id: "caution", label: "Data caution" },
];

/** Pull the ordinal gap out of an idpMarketAction title, which is
 *  where the engine stamps it (e.g. "~34 ordinal spots"). */
function idpGapOf(action) {
  const m = action.title?.match(/~(\d+) ordinal/);
  return m ? Number(m[1]) : 0;
}

export default function EdgePage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const { openPlayerPopup } = useApp();

  const sleeperTeams = rawData?.sleeper?.teams || [];
  const [teamFilter, setTeamFilter] = useState("");
  const [tab, setTab] = useState("gaps");

  // Build a Set of player names on the selected team's roster.
  const rosterNames = useMemo(() => {
    if (!teamFilter) return null;
    const team = sleeperTeams.find((t) => t.name === teamFilter);
    if (!team) return null;
    const names = new Set();
    for (const p of team.players || []) names.add(p?.toLowerCase());
    return names;
  }, [teamFilter, sleeperTeams]);

  // Eligible: non-pick, ranked players — optionally scoped to a team.
  const eligible = useMemo(() => {
    let list = rows.filter(isEligibleForAnalysis);
    if (rosterNames) list = list.filter((r) => rosterNames.has(r.name?.toLowerCase()));
    return list;
  }, [rows, rosterNames]);

  // ── Section datasets (unchanged) ───────────────────────────────────
  const consensus = useMemo(
    () =>
      eligible
        .filter(
          (r) =>
            r.confidenceBucket === "high" && (r.sourceCount ?? 0) >= 2 && !r.quarantined,
        )
        .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  const disagreements = useMemo(
    () =>
      eligible
        .filter(
          (r) =>
            (r.sourceRankSpread ?? 0) > PREMIUM_SUMMARY_SPREAD &&
            (r.sourceCount ?? 0) >= 2 &&
            !r.quarantined,
        )
        .sort((a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  // AUDIT S-3 — these two panels display the SIGN of the market gap and
  // used to gate and sort on ``sourceRankSpread``, which measures how much
  // the sources disagree with EACH OTHER.  Two different quantities: a
  // clean, large retail-vs-consensus gap on a player every source agrees
  // about was excluded outright, while a negligible gap on a player the
  // sources were arguing over sorted to the top.  The spread gate also
  // barely filtered — measured on the live board it admitted 376 of the
  // 414 rows carrying a gap.
  //
  // ``marketGapMagnitude`` — the magnitude OF the direction being filtered
  // on — was stamped by the backend all along and read by nothing here.
  const premiumBy = (direction) =>
    eligible
      .filter(
        (r) =>
          r.marketGapDirection === direction &&
          (r.marketGapMagnitude ?? 0) >= PREMIUM_SUMMARY_MAGNITUDE &&
          !r.quarantined &&
          isTopRankedForEdgePremium(r),
      )
      .sort((a, b) => (b.marketGapMagnitude ?? 0) - (a.marketGapMagnitude ?? 0))
      .slice(0, EDGE_PREMIUM_LIMIT);

  const retailPremium = useMemo(() => premiumBy("retail_premium"), [eligible]);

  const consensusPremium = useMemo(() => premiumBy("consensus_premium"), [eligible]);

  // ── IDP Buy/Sell — IDPTC as the retail anchor ──────────────────────
  // KTC doesn't list IDP, so defenders never surface in the offense
  // sections above. These mirror that logic with IDPTC in KTC's role,
  // scoped to the top 200 by IDPTC (below that the IDP-expert
  // consensus is too noisy to trust).
  const idpEligible = useMemo(
    () => eligible.filter((r) => isIdpInTopByIdptc(r, IDP_TOP_LIMIT)),
    [eligible],
  );

  const idpRetailPremium = useMemo(
    () =>
      idpEligible
        .map((r) => ({ row: r, action: idpMarketAction(r) }))
        .filter(({ action }) => action.kind === "sell")
        .map(({ row, action }) => ({ ...row, __idpGap: idpGapOf(action) }))
        .sort((a, b) => b.__idpGap - a.__idpGap)
        .slice(0, EDGE_PREMIUM_LIMIT),
    [idpEligible],
  );

  const idpConsensusPremium = useMemo(
    () =>
      idpEligible
        .map((r) => ({ row: r, action: idpMarketAction(r) }))
        .filter(({ action }) => action.kind === "buy")
        .map(({ row, action }) => ({ ...row, __idpGap: idpGapOf(action) }))
        .sort((a, b) => b.__idpGap - a.__idpGap)
        .slice(0, EDGE_PREMIUM_LIMIT),
    [idpEligible],
  );

  const flagged = useMemo(
    () =>
      eligible
        .filter(
          (r) =>
            (r.anomalyFlags || []).length > 0 &&
            (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT,
        )
        .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  const singleSource = useMemo(
    () =>
      eligible
        .filter(
          (r) => r.isSingleSource && (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT,
        )
        .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  const stats = useMemo(
    () => ({
      total: eligible.length,
      multiSource: eligible.filter((r) => (r.sourceCount ?? 0) >= 2).length,
      highConf: eligible.filter((r) => r.confidenceBucket === "high").length,
      disagreementCount: eligible.filter(
        (r) => (r.sourceRankSpread ?? 0) > PREMIUM_SUMMARY_SPREAD && (r.sourceCount ?? 0) >= 2,
      ).length,
      flaggedCount: eligible.filter((r) => (r.anomalyFlags || []).length > 0).length,
      singleCount: eligible.filter((r) => r.isSingleSource).length,
    }),
    [eligible],
  );

  const retail = getRetailLabel();

  const teamSelect =
    sleeperTeams.length > 0 ? (
      <Select
        value={teamFilter}
        onChange={(e) => setTeamFilter(e.target.value)}
        aria-label="Scope signals to a team's roster"
      >
        <option value="">All teams (league-wide)</option>
        {sleeperTeams.map((t) => (
          <option key={t.name} value={t.name}>
            {t.name}
          </option>
        ))}
      </Select>
    ) : null;

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Market"
        title="Source Disagreement"
        description={
          <>
            Where the ranking sources agree and disagree.
            <InfoTip label="these signals">
              <p>
                Every signal here is derived from measurable properties of the
                data — how many sources cover a player, how closely they agree,
                how far apart the outliers sit.
              </p>
              <p>Nothing on this page is a prediction.</p>
            </InfoTip>
          </>
        }
        actions={teamSelect}
      />

      <ValueBasisNote contract={rawData} />

      {!!error && (
        <Banner tone="negative" title="Couldn't load edge data">
          {String(error)}
        </Banner>
      )}

      {loading && (
        <Panel title="Loading signals">
          <SkeletonTable rows={8} />
        </Panel>
      )}

      {!loading && !error && rows.length === 0 && (
        <Panel>
          <EmptyState
            title="No player data available"
            description="The backend may still be initializing — this page fills in as soon as the contract lands."
          />
        </Panel>
      )}

      {!loading && !error && eligible.length > 0 && (
        <>
          <div className={styles.stats}>
            <StatTile
              label="Analyzed"
              value={stats.total.toLocaleString()}
              meta={teamFilter || "league-wide"}
            />
            <StatTile label="High conf" value={stats.highConf.toLocaleString()} />
            <StatTile label="Multi-source" value={stats.multiSource.toLocaleString()} />
            <StatTile label="Disagree" value={stats.disagreementCount.toLocaleString()} />
            <StatTile label="Flagged" value={stats.flaggedCount.toLocaleString()} />
            <StatTile label="Single-source" value={stats.singleCount.toLocaleString()} />
          </div>

          <Panel
            title={
              <>
                Value vs. source spread
                <InfoTip label="this chart">
                  <p>
                    Each dot is a player: x is their value, y is how far apart
                    the sources ranked them.
                  </p>
                  <p>
                    High value plus high spread means a contested asset — worth
                    selling high or buying low depending on which market you
                    trust.
                  </p>
                </InfoTip>
              </>
            }
            subtitle="Top-200 ranked rows — the upper-right quadrant is the edge zone"
          >
            <ConfidenceValueScatter
              rows={eligible}
              topN={200}
              onPointClick={openPlayerPopup}
            />
          </Panel>

          <div className={styles.tabStrip}>
            <Tabs
              tabs={SIGNAL_TABS}
              active={tab}
              onChange={setTab}
              label="Signal family"
              idPrefix="edge-signals"
            />
          </div>

          <div
            id={tabPanelId("edge-signals", tab)}
            role="tabpanel"
            aria-label={SIGNAL_TABS.find((t) => t.id === tab)?.label}
            tabIndex={-1}
          >
            {tab === "gaps" && (
              <div className={styles.signalGrid}>
                <SignalPanel
                  title="Sell signals"
                  subtitle={`${retail} values these much higher than the expert consensus`}
                  note={`Inside the top ${EDGE_PREMIUM_RANK_LIMIT} on our blended board, so only trade-relevant gaps surface. Potential sells to retail-first partners.`}
                  rows={retailPremium}
                  caption={`Players the retail market ${retail} values above consensus`}
                  emptyText={`No sell signals in the top ${EDGE_PREMIUM_RANK_LIMIT}.`}
                  defaultSort={{ key: "spread", direction: "desc" }}
                  columns={[colRank(), colPlayer(openPlayerPopup), colPos(), colSpread(), colValue()]}
                />
                <SignalPanel
                  title="Buy signals"
                  subtitle={`The expert consensus values these much higher than ${retail}`}
                  note={`Inside the top ${EDGE_PREMIUM_RANK_LIMIT} on our blended board. Potential buys from retail-first partners.`}
                  rows={consensusPremium}
                  caption={`Players the expert consensus values above ${retail}`}
                  emptyText={`No buy signals in the top ${EDGE_PREMIUM_RANK_LIMIT}.`}
                  defaultSort={{ key: "spread", direction: "desc" }}
                  columns={[colRank(), colPlayer(openPlayerPopup), colPos(), colSpread(), colValue()]}
                />
                <SignalPanel
                  title="IDP sell signals"
                  subtitle="IDPTC ranks these defenders well above the IDP-expert consensus"
                  note={`Consensus = DLF IDP, IDP Show, FantasyPros IDP, FootballGuys IDP, DraftSharks IDP. Top ${IDP_TOP_LIMIT} by IDPTC only.`}
                  rows={idpRetailPremium}
                  caption="IDP players IDPTC values above the IDP-expert consensus"
                  emptyText={`No IDP sell signals inside the top ${IDP_TOP_LIMIT} by IDPTC.`}
                  defaultSort={{ key: "idpGap", direction: "desc" }}
                  columns={[colRank(), colPlayer(openPlayerPopup), colPos(), colIdpGap(), colValue()]}
                />
                <SignalPanel
                  title="IDP buy signals"
                  subtitle="The IDP-expert consensus ranks these defenders well above IDPTC"
                  note={`Top ${IDP_TOP_LIMIT} by IDPTC only. Potential buys from IDPTC-first partners.`}
                  rows={idpConsensusPremium}
                  caption="IDP players the IDP-expert consensus values above IDPTC"
                  emptyText={`No IDP buy signals inside the top ${IDP_TOP_LIMIT} by IDPTC.`}
                  defaultSort={{ key: "idpGap", direction: "desc" }}
                  columns={[colRank(), colPlayer(openPlayerPopup), colPos(), colIdpGap(), colValue()]}
                />
              </div>
            )}

            {tab === "agreement" && (
              <div className={styles.signalGrid}>
                <SignalPanel
                  title="Consensus assets"
                  subtitle="Highest-confidence players where the sources agree closely"
                  note="The safest trade anchors — what you price other deals against."
                  rows={consensus}
                  caption="High-confidence players with close source agreement"
                  emptyText="No high-confidence consensus assets found."
                  defaultSort={{ key: "rank", direction: "asc" }}
                  columns={[
                    colRank(),
                    colPlayer(openPlayerPopup),
                    colPos(),
                    colValue(),
                    colSpread(),
                    colConfidence(),
                  ]}
                />
                <SignalPanel
                  title="Biggest disagreements"
                  subtitle="Where the ranking sources diverge most"
                  note="One market may be wrong — which is exactly where opportunity lives."
                  rows={disagreements}
                  caption="Players with the widest source disagreement"
                  emptyText="No significant source disagreements."
                  defaultSort={{ key: "spread", direction: "desc" }}
                  columns={[
                    colRank(),
                    colPlayer(openPlayerPopup),
                    colPos(),
                    colSpread(),
                    colGapDirection(),
                    colSignal(),
                  ]}
                />
              </div>
            )}

            {tab === "caution" && (
              <div className={styles.signalGrid}>
                <SignalPanel
                  title="Flagged anomalies"
                  subtitle="Ranked players carrying data-quality flags"
                  note="Not necessarily bad — but worth knowing before you trade one."
                  rows={flagged}
                  caption="Ranked players with data-quality flags"
                  emptyText={`No flagged players in the top ${EDGE_CAUTION_RANK_LIMIT}.`}
                  defaultSort={{ key: "rank", direction: "asc" }}
                  columns={[
                    colRank(),
                    colPlayer(openPlayerPopup),
                    colPos(),
                    colFlags(),
                    colConfidence(),
                  ]}
                />
                <SignalPanel
                  title="Single-source players"
                  subtitle="Valued by exactly one ranking source"
                  note="Confidence is lower and the rank can move hard once a second source adds coverage."
                  rows={singleSource}
                  caption="Players valued by a single ranking source"
                  emptyText={`No single-source players in the top ${EDGE_CAUTION_RANK_LIMIT}.`}
                  defaultSort={{ key: "rank", direction: "asc" }}
                  columns={[
                    colRank(),
                    colPlayer(openPlayerPopup),
                    colPos(),
                    colValue(),
                    colSignal(),
                  ]}
                />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * One signal section: a Panel whose body is edge-to-edge DataTable,
 * with the methodology note in the footer where it stays available
 * without competing with the rows.
 */
function SignalPanel({
  title,
  subtitle,
  note,
  rows,
  columns,
  caption,
  emptyText,
  defaultSort,
}) {
  // The `note` used to render as a permanent footer paragraph under
  // every panel — eight of them on this page, so each section carried
  // title + subtitle + footnote and the methodology outweighed the
  // data.  It moves to an InfoTip on the title: same words, same
  // discoverability (the icon sits on the thing it explains), none of
  // the vertical space.
  return (
    <Panel
      title={
        note ? (
          <>
            {title}
            <InfoTip label={title}>{note}</InfoTip>
          </>
        ) : (
          title
        )
      }
      subtitle={subtitle}
      flush
      actions={
        rows.length > 0 ? (
          <span className={styles.methodNote}>{rows.length} shown</span>
        ) : null
      }
    >
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.name}
        caption={caption}
        density="compact"
        defaultSort={defaultSort}
        emptyState={<EmptyState title="Nothing here" description={emptyText} />}
      />
    </Panel>
  );
}
