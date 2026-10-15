"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useDynastyData } from "@/components/useDynastyData";
import { useTeam } from "@/components/useTeam";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  Field,
  PageHeader,
  Panel,
  PlayerNameButton,
  SegmentedControl,
  Select,
  SkeletonTable,
  StatTile,
  canonicalPlayerId,
} from "@/components/ds";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildShareUrl } from "@/lib/trade-share";
import { buildArbitrageRows, rosterCapacityLine } from "@/lib/market-arbitrage";
import {
  emptyRefinement,
  loadRefinement,
  refinementKey,
  saveRefinement,
  toRequest,
  toggleExclude,
  toggleLock,
  toggleSkip,
} from "@/lib/trade-refinement";
import {
  IncomingSkip,
  OutgoingRefinement,
  RefinementBar,
} from "@/components/trade/RefinementControls";

// C3-CTX-01 — the same Team context / Asset only switch the Trade War Room
// uses.  ON lets this team's roster (needs, forced releases) shape the order;
// OFF ranks on asset value and market appeal alone.  Values never change.
const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];
import styles from "./arbitrage.module.css";
import BestOffersView from "./BestOffersView";
import GoldenUpgradesView from "./GoldenUpgradesView";
import PackageBuilderView from "./PackageBuilderView";
import TradeDeskView from "./TradeDeskView";

// The package layer has four views over the same team selection: the
// equal-count arbitrage scan (unchanged), Best Trade to Send Each Team
// (C7-BEST-TRADE), which allows a one-player difference and posture picks,
// Golden Upgrades (C7-GOLD-01), same-position 1-for-1 inversions, and the
// Package Builder (C7-PKGB-01), packages built to the user's own request.
// The Trade Desk (Part 12) is the user's private list of saved packages.
const VIEW_OPTIONS = [
  { value: "scan", label: "Package scan" },
  { value: "best", label: "Best offer by opponent" },
  { value: "golden", label: "Golden Upgrades" },
  { value: "builder", label: "Package Builder" },
  { value: "desk", label: "Trade Desk" },
];

// ── /arbitrage — board-vs-public-market arbitrage finder ─────────────
//
// Two layers intentionally live together here:
//   1. Player-level market inefficiencies — canonical board versus the public
//      transaction market a trade partner is likely to check (KTC for offense,
//      IDP Trade Calculator for IDP).
//   2. Package-level trade finder — src/trade/finder.py, which searches actual
//      roster-to-roster constructions through POST /api/trade/finder.
//
// Source disagreement is deliberately NOT a qualification rule for layer 1.
// "The sources disagree" and "our canonical value beats the public price" are
// different questions. /rankings retains the disagreement research lens.

const ARBITRAGE_CONTROL_KEY = "__arbitrageControl";

function fmt(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtSigned(v) {
  const n = Number(v || 0);
  return `${n > 0 ? "+" : ""}${fmt(Math.round(n))}`;
}

function fmtPct(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${Math.round(n * 100)}%`;
}

function edgeActionLabel(action) {
  if (action === "strong_buy") return "STRONG BUY";
  if (action === "buy") return "BUY";
  if (action === "strong_sell") return "STRONG SELL";
  if (action === "sell") return "SELL";
  return "HOLD";
}

const MARKET_LABEL = { ktcCrowdTradesSfTep: "KTC", ktcSfTep: "KTC", ktc: "KTC", idpTradeCalc: "IDPTC" };

function PlayerEdgeTable({ opportunities }) {
  if (!opportunities.length) {
    return (
      <EmptyState
        title="No player-level edges at this threshold"
        description="Missing public prices stay missing rather than becoming zero. Lower the threshold or switch asset class to inspect more of the board."
      />
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr>
            {[
              "Player",
              "Pos",
              "Our rank",
              "Our value",
              "Public market",
              "Public value",
              "Hidden surplus",
              "Edge",
              "Signal",
              "Confidence",
              "Public-friendly offer",
            ].map((label) => (
              <th
                key={label}
                style={{ textAlign: "left", padding: "10px 9px", borderBottom: "1px solid var(--border, #333)", whiteSpace: "nowrap" }}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {opportunities.map(({ row, edge }) => (
            <tr key={row.playerId || `${row.name}-${row.pos}`}>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>
                <strong>
                  <PlayerNameButton name={row.name} playerId={canonicalPlayerId(row)} />
                </strong>
              </td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{row.pos}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{row.rank ?? "—"}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{fmt(edge.ourValue)}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{edge.marketLabel}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{fmt(edge.marketValue)}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{fmtSigned(edge.edgePoints)}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{fmtPct(edge.edgeRatio)}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>
                <Badge tone={edge.edgeRatio > 0 ? "positive" : "warning"}>{edgeActionLabel(edge.action)}</Badge>
              </td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)" }}>{row.confidenceBucket || "unknown"}</td>
              <td style={{ padding: "10px 9px", borderBottom: "1px solid var(--border, #292929)", minWidth: 190 }}>
                {edge.winWin ? (
                  <>
                    <strong>{fmt(edge.publicFriendlyOfferCeiling)}</strong>
                    <div style={{ opacity: 0.7, marginTop: 2 }}>
                      public {fmtPct(edge.publicWinRatio)} · internal {fmtPct(edge.internalWinRatio)}
                    </div>
                  </>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AssetList({ assets, side, refine }) {
  if (!assets?.length) return <span className={styles.muted}>—</span>;
  return (
    <ul className={styles.assetList}>
      {assets.map((a, i) => (
        <li key={`${a.name}-${i}`} className={styles.asset}>
          <span className={styles.assetName}>{a.name}</span>
          <Badge tone="neutral">{a.position}</Badge>
          <span className={styles.assetValues}>
            board {fmt(a.modelValue)}
            {a.ktcValue == null
              ? " · unpriced"
              : a.marketDerivation
                ? ` · market ≈${fmt(a.ktcValue)} (KTC tier average — slot unknown)`
                : ` · market ${fmt(a.ktcValue)}`}
          </span>
          {refine && a.name && side === "give" ? (
            <OutgoingRefinement
              name={a.name}
              refinement={refine.refinement}
              onLock={refine.onLock}
              onExclude={refine.onExclude}
              disabled={refine.disabled}
            />
          ) : null}
          {refine && a.name && side === "receive" ? (
            <IncomingSkip
              name={a.name}
              refinement={refine.refinement}
              onSkip={refine.onSkip}
              disabled={refine.disabled}
            />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function TradeCard({ trade, myTeam, opponent, refine }) {
  const boardDelta = Number(trade.boardDelta || 0);
  const ktcDelta = Number(trade.ktcDelta || 0);
  const counterparty = trade.counterparty || (opponent && opponent !== "all" ? opponent : null);
  const mine = rosterCapacityLine(trade.rosterCapacity);
  const theirs = rosterCapacityLine(trade.counterpartyRosterCapacity);

  const openInCalculator = useMemo(() => {
    // A pick travels as its canonical board row ("2027 Round 1"), the name
    // the calculator can resolve — not the "2027 1st (Team)" display label.
    const asCalculatorName = (a) => a.boardRowName || a.name;
    const give = (trade.give || []).map(asCalculatorName).filter(Boolean);
    const receive = (trade.receive || []).map(asCalculatorName).filter(Boolean);
    if (!give.length && !receive.length) return null;
    try {
      return buildShareUrl({
        sides: [
          { name: myTeam || "You", players: give },
          { name: counterparty || "Them", players: receive },
        ],
      });
    } catch {
      return null;
    }
  }, [trade, myTeam, counterparty]);

  return (
    <Panel className={`${styles.tradeCard} arbitrage-trade-card`}>
      <div className={styles.tradeHead}>
        <span className={styles.score}>
          arbitrage {Number(trade.arbitrageScore || 0).toFixed(2)}
        </span>
        {trade.packageSize ? <Badge tone="neutral">{trade.packageSize}</Badge> : null}
        <span className={styles.deltas}>
          <span className={boardDelta >= 0 ? styles.good : styles.bad}>
            our board {fmtSigned(boardDelta)}
          </span>
          <span className={styles.sep}>/</span>
          <span className={ktcDelta >= 0 ? styles.good : styles.bad}>
            their market {fmtSigned(ktcDelta)}
          </span>
        </span>
        {trade.mixedMarket ? (
          <Badge tone="warning">
            spans {(trade.marketsUsed || []).map((m) => MARKET_LABEL[m] || m).join(" + ")}
          </Badge>
        ) : null}
      </div>
      {mine || theirs ? (
        <ul className={styles.capacityList} aria-label="Roster consequences">
          {mine ? <li>Your roster: {mine}</li> : null}
          {theirs ? (
            <li>
              {counterparty ? `${counterparty}'s` : "Their"} roster: {theirs}
            </li>
          ) : null}
        </ul>
      ) : null}
      <div className={styles.tradeBody}>
        <div className={styles.side}>
          <h4 className={styles.sideLabel}>You give</h4>
          <AssetList assets={trade.give} side="give" refine={refine} />
        </div>
        <div className={styles.side}>
          <h4 className={styles.sideLabel}>You get</h4>
          <AssetList assets={trade.receive} side="receive" refine={refine} />
        </div>
      </div>
      {openInCalculator ? (
        <div className={styles.tradeFoot}>
          <Button as={Link} href={openInCalculator} size="sm" variant="secondary">
            Open in Trade Calculator
          </Button>
        </div>
      ) : null}
    </Panel>
  );
}

function tradeContainsPlayer(trade, playerName) {
  return [...(trade?.give || []), ...(trade?.receive || [])].some(
    (asset) => String(asset?.name || "") === String(playerName || ""),
  );
}

export default function ArbitragePage() {
  const { loading: dataLoading, error: dataError, rawData, rows } = useDynastyData();
  const { selectedLeagueKey, selectedOwnerId } = useTeam();

  const teams = useMemo(() => {
    const list = rawData?.sleeper?.teams || [];
    return [...list].sort((a, b) => String(a?.name || "").localeCompare(String(b?.name || "")));
  }, [rawData]);

  const defaultTeam = useMemo(() => {
    if (!teams.length) return "";
    const mine = teams.find((t) => String(t?.ownerId || "") === String(selectedOwnerId || ""));
    return mine?.name || teams[0]?.name || "";
  }, [teams, selectedOwnerId]);

  const [myTeam, setMyTeam] = useState("");
  const [opponent, setOpponent] = useState("all");
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [edgeAction, setEdgeAction] = useState("buy");
  const [edgeClass, setEdgeClass] = useState("all");
  const [edgeFloor, setEdgeFloor] = useState(0.05);
  // C3-CON-03 LOCK / EXCLUDE (+ the incoming-only "Skip target").  Kept per
  // (team, league, scan context) in localStorage until cleared — never in the
  // persistent trade-protection store.
  const [refinement, setRefinement] = useState(emptyRefinement);
  const [useTeamContext, setUseTeamContext] = useState(true);
  const [packageView, setPackageView] = useState("scan");
  // Only the LATEST scan may write the result: a mode switch mid-scan starts a
  // new request, and a slower earlier response must not paint the other
  // mode's order under the current switch position.
  const scanSeq = useRef(0);

  const effectiveTeam = myTeam || defaultTeam;

  const storageKey = useMemo(
    () =>
      refinementKey({
        owner: selectedOwnerId,
        leagueKey: selectedLeagueKey,
        surface: "arbitrage",
        context: `${effectiveTeam}|${opponent}`,
      }),
    [selectedOwnerId, selectedLeagueKey, effectiveTeam, opponent],
  );

  useEffect(() => {
    setRefinement(loadRefinement(storageKey));
  }, [storageKey]);

  const playerEdges = useMemo(
    () =>
      buildArbitrageRows(rows, {
        action: edgeAction,
        assetClass: edgeClass,
        minEdge: edgeFloor,
      }),
    [rows, edgeAction, edgeClass, edgeFloor],
  );

  const buyCount = useMemo(
    () => buildArbitrageRows(rows, { action: "buy", minEdge: edgeFloor }).length,
    [rows, edgeFloor],
  );
  const sellCount = useMemo(
    () => buildArbitrageRows(rows, { action: "sell", minEdge: edgeFloor }).length,
    [rows, edgeFloor],
  );
  const winWinCount = useMemo(
    () => buildArbitrageRows(rows, { action: "winwin", minEdge: edgeFloor }).length,
    [rows, edgeFloor],
  );

  async function run(nextRefinement = refinement, teamContext = useTeamContext) {
    if (!effectiveTeam) return;
    const selectedOpponents =
      opponent === "all"
        ? teams.filter((t) => t.name !== effectiveTeam).map((t) => t.name)
        : [opponent];

    const seq = ++scanSeq.current;
    setRunning(true);
    setError("");
    try {
      const body = {
        myTeam: effectiveTeam,
        // The reserved control object carries this page's search policy
        // (equal-count shapes; incoming-only skipped targets).  LOCK / EXCLUDE
        // travel as `refinement`, validated and applied by the server's one
        // constraint owner during generation.
        opponentTeams: [
          ...selectedOpponents,
          {
            [ARBITRAGE_CONTROL_KEY]: {
              equalCountOnly: true,
              skipTargets: [...(nextRefinement?.skip || [])],
            },
          },
        ],
        refinement: toRequest(nextRefinement),
      };
      body.useTeamContext = teamContext !== false;
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
      const res = await fetch("/api/trade/finder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(withValuationMode(body)),
      });
      const data = await res.json().catch(() => ({}));
      if (seq !== scanSeq.current) return;
      if (!res.ok) {
        setError(data?.error || `Request failed (${res.status})`);
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (err) {
      if (seq !== scanSeq.current) return;
      setError(err?.message || "Request failed");
      setResult(null);
    } finally {
      if (seq === scanSeq.current) setRunning(false);
    }
  }

  // Every refinement change regenerates immediately (spec §3.3).  The rerun is
  // not a post-filter: the server applies the same refinement before package
  // enumeration.  A newly excluded / skipped player's stale cards are removed
  // at once so the page never shows a package the user just ruled out.
  function applyRefinement(next, removedName = null) {
    setRefinement(next);
    saveRefinement(storageKey, next);
    if (removedName) {
      setResult((prev) =>
        prev
          ? {
              ...prev,
              trades: (prev.trades || []).filter(
                (trade) => !tradeContainsPlayer(trade, removedName),
              ),
            }
          : prev,
      );
    }
    void run(next);
  }

  function lockPlayer(name) {
    applyRefinement(toggleLock(refinement, name));
  }

  function excludePlayer(name) {
    const next = toggleExclude(refinement, name);
    const nowExcluded = (next.exclude || []).includes(String(name || "").trim());
    applyRefinement(next, nowExcluded ? name : null);
  }

  function skipTarget(name) {
    const next = toggleSkip(refinement, name);
    const nowSkipped = (next.skip || []).includes(String(name || "").trim());
    applyRefinement(next, nowSkipped ? name : null);
  }

  function clearRefinements() {
    applyRefinement(emptyRefinement());
  }

  function resetPackageScan() {
    // The refinement for the new (team, opponent) context is loaded from
    // storage by the effect above; only the stale result is cleared here.
    setResult(null);
    setError("");
  }

  const refine = {
    refinement,
    onLock: lockPlayer,
    onExclude: excludePlayer,
    onSkip: skipTarget,
    disabled: running,
  };

  const meta = result?.metadata;

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Trades"
        title="Arbitrage"
        description="Find players our canonical board values above or below the public market, then turn those edges into trades that can still look fair to the counterparty."
      />

      {dataError ? <Banner tone="negative">{String(dataError)}</Banner> : null}

      <Panel>
        <h3 style={{ marginTop: 0 }}>Player-level inefficiencies</h3>
        <p className={styles.muted}>
          Offense is compared directly with KTC. IDP is compared directly with IDP Trade Calculator. Source disagreement is not required; that remains a separate Rankings research lens.
        </p>
        <div className={styles.controls}>
          <Field label="Signal">
            <Select value={edgeAction} onChange={(e) => setEdgeAction(e.target.value)}>
              <option value="buy">Buy arbitrage</option>
              <option value="sell">Sell arbitrage</option>
              <option value="winwin">Win-win on public market</option>
              <option value="all">All edges</option>
            </Select>
          </Field>
          <Field label="Player type">
            <Select value={edgeClass} onChange={(e) => setEdgeClass(e.target.value)}>
              <option value="all">All players</option>
              <option value="offense">Offense — KTC</option>
              <option value="idp">IDP — IDP Trade Calculator</option>
            </Select>
          </Field>
          <Field label="Minimum edge">
            <Select value={String(edgeFloor)} onChange={(e) => setEdgeFloor(Number(e.target.value))}>
              <option value="0.05">5%+</option>
              <option value="0.10">10%+</option>
              <option value="0.15">15%+</option>
              <option value="0.20">20%+</option>
            </Select>
          </Field>
        </div>
        <div className={styles.stats}>
          <StatTile label="Buy edges" value={fmt(buyCount)} />
          <StatTile label="Sell edges" value={fmt(sellCount)} />
          <StatTile label="Win-win offers" value={fmt(winWinCount)} />
          <StatTile label="Visible" value={fmt(playerEdges.length)} />
        </div>
        {dataLoading ? <SkeletonTable rows={5} /> : <PlayerEdgeTable opportunities={playerEdges} />}
      </Panel>

      <Panel>
        <h3 style={{ marginTop: 0 }}>Turn the edge into a trade</h3>
        <div className={styles.controls}>
          <SegmentedControl
            label="Package view"
            options={VIEW_OPTIONS}
            value={packageView}
            onChange={(v) => setPackageView(v)}
          />
          {packageView !== "scan" && packageView !== "desk" ? (
            <Field label="Your team">
              <Select
                value={effectiveTeam}
                onChange={(e) => {
                  setMyTeam(e.target.value);
                  resetPackageScan();
                }}
                disabled={dataLoading || !teams.length}
              >
                {teams.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
        </div>
      </Panel>

      {packageView === "best" ? (
        <Panel>
          <BestOffersView
            myTeam={effectiveTeam}
            leagueKey={selectedLeagueKey}
            ownerKey={selectedOwnerId}
            opponentNames={teams.filter((t) => t.name !== effectiveTeam).map((t) => t.name)}
          />
        </Panel>
      ) : null}

      {packageView === "golden" ? (
        <Panel>
          <GoldenUpgradesView
            myTeam={effectiveTeam}
            leagueKey={selectedLeagueKey}
            ownerKey={selectedOwnerId}
          />
        </Panel>
      ) : null}

      {packageView === "builder" ? (
        <Panel>
          <PackageBuilderView
            myTeam={effectiveTeam}
            leagueKey={selectedLeagueKey}
            ownerKey={selectedOwnerId}
            teams={teams}
          />
        </Panel>
      ) : null}

      {packageView === "desk" ? (
        <Panel>
          <TradeDeskView leagueKey={selectedLeagueKey} />
        </Panel>
      ) : null}

      {packageView === "scan" ? (
        <>
      <Panel>
        <p className={styles.muted}>
          This second layer scans actual rosters for 1-for-1 or 2-for-2 packages that gain on our board while remaining plausible on the counterparty market. On a player you would send, Lock keeps them in every regenerated package and Exclude keeps them out; on a player you would receive, Skip leaves them out of this scan. Locks and exclusions stay until you clear them and never change your saved trade protections.
        </p>
        <div className={styles.controls}>
          <Field label="Your team">
            <Select
              value={effectiveTeam}
              onChange={(e) => {
                setMyTeam(e.target.value);
                resetPackageScan();
              }}
              disabled={dataLoading || !teams.length}
            >
              {teams.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Opponent">
            <Select
              value={opponent}
              onChange={(e) => {
                setOpponent(e.target.value);
                resetPackageScan();
              }}
              disabled={dataLoading || !teams.length}
            >
              <option value="all">All teams</option>
              {teams
                .filter((t) => t.name !== effectiveTeam)
                .map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
            </Select>
          </Field>
          <SegmentedControl
            label="Analysis mode"
            options={CONTEXT_OPTIONS}
            value={useTeamContext ? "team" : "asset"}
            onChange={(v) => {
              const next = v === "team";
              setUseTeamContext(next);
              // Re-scan an existing result in the new mode; never silently
              // keep showing the other mode's order.
              if (result) run(refinement, next);
            }}
          />
          <Button onClick={() => run(refinement)} disabled={running || dataLoading || !effectiveTeam}>
            {running ? "Scanning…" : "Find trade packages"}
          </Button>
        </div>
        <RefinementBar
          refinement={refinement}
          onLock={lockPlayer}
          onExclude={excludePlayer}
          onSkip={skipTarget}
          onClear={clearRefinements}
          disabled={running}
        />
      </Panel>

      {error ? <Banner tone="negative">{error}</Banner> : null}

      {result?.warnings?.map((w, i) => (
        <Banner key={i} tone="warning">
          {w}
        </Banner>
      ))}

      {meta ? (
        <div className={styles.stats}>
          <StatTile label="Qualified" value={fmt(meta.totalQualified)} />
          <StatTile label="Shown" value={fmt(meta.returned)} />
          <StatTile label="Asset pool" value={fmt(meta.assetPoolSize)} />
          <StatTile label="Market coverage" value={`${meta.marketCoveragePercent ?? 0}%`} />
          <StatTile label="Unpriced by board" value={fmt(meta.assetsUnpricedByBoard)} />
          <StatTile label="Mixed-market" value={fmt(meta.mixedMarketTrades)} />
        </div>
      ) : null}

      {meta?.valueSource && meta.valueSource !== "rankDerivedValue" ? (
        <Banner tone="warning">
          This run valued assets off <code>{meta.valueSource}</code>, not the board you see. Results
          are not comparable to the rankings page.
        </Banner>
      ) : null}

      {running ? <SkeletonTable rows={4} /> : null}

      {!running && result && !result.trades?.length ? (
        <EmptyState
          title={meta?.noResultLabel || "No package arbitrage found"}
          description={
            meta?.noResultReason === "lock_conflicts_with_protection"
              ? "A locked player is also protected or excluded, so no package can include him. Unlock him or change the protection."
              : meta?.noResultReason === "locked_player_unavailable"
                ? "A locked player is not on this roster's tradeable list, so no package can include him."
                : "Every candidate either lost value on our board, used an excluded player, or looked too lopsided on the counterparty's market to be plausible."
          }
        />
      ) : null}

      {!running && result?.trades?.length ? (
        <div className={styles.trades}>
          {result.trades.map((t, i) => (
            <TradeCard
              key={i}
              trade={t}
              myTeam={effectiveTeam}
              opponent={opponent}
              refine={refine}
            />
          ))}
        </div>
      ) : null}

      {!result && !running ? (
        <EmptyState
          title="Package scan ready"
          description="The player-level opportunities above are live immediately. Choose your team and a counterparty to search actual trade constructions."
        />
      ) : null}
        </>
      ) : null}
    </div>
  );
}
