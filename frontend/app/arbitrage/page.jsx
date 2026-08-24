"use client";

import { useMemo, useState } from "react";
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
  Select,
  SkeletonTable,
  StatTile,
} from "@/components/ds";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildShareUrl } from "@/lib/trade-share";
import { buildArbitrageRows } from "@/lib/market-arbitrage";
import styles from "./arbitrage.module.css";

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

const MARKET_LABEL = { ktcSfTep: "KTC", ktc: "KTC", idpTradeCalc: "IDPTC" };

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
                <strong>{row.name}</strong>
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

function AssetList({ assets }) {
  if (!assets?.length) return <span className={styles.muted}>—</span>;
  return (
    <ul className={styles.assetList}>
      {assets.map((a, i) => (
        <li key={`${a.name}-${i}`} className={styles.asset}>
          <span className={styles.assetName}>{a.name}</span>
          <Badge tone="neutral">{a.position}</Badge>
          <span className={styles.assetValues}>
            board {fmt(a.modelValue)}
            {a.ktcValue != null ? ` · market ${fmt(a.ktcValue)}` : " · unpriced"}
          </span>
        </li>
      ))}
    </ul>
  );
}

function TradeCard({ trade, myTeam, opponent }) {
  const boardDelta = Number(trade.boardDelta || 0);
  const ktcDelta = Number(trade.ktcDelta || 0);

  const openInCalculator = useMemo(() => {
    const give = (trade.give || []).map((a) => a.name).filter(Boolean);
    const receive = (trade.receive || []).map((a) => a.name).filter(Boolean);
    if (!give.length && !receive.length) return null;
    try {
      return buildShareUrl({
        sides: [
          { name: myTeam || "You", players: give },
          { name: opponent && opponent !== "all" ? opponent : "Them", players: receive },
        ],
      });
    } catch {
      return null;
    }
  }, [trade, myTeam, opponent]);

  return (
    <Panel className={`${styles.tradeCard} arbitrage-trade-card`}>
      <div className={styles.tradeHead}>
        <span className={styles.score}>
          arbitrage {Number(trade.arbitrageScore || 0).toFixed(2)}
        </span>
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
      <div className={styles.tradeBody}>
        <div className={styles.side}>
          <h4 className={styles.sideLabel}>You give</h4>
          <AssetList assets={trade.give} />
        </div>
        <div className={styles.side}>
          <h4 className={styles.sideLabel}>You get</h4>
          <AssetList assets={trade.receive} />
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

  const effectiveTeam = myTeam || defaultTeam;

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

  async function run() {
    if (!effectiveTeam) return;
    setRunning(true);
    setError("");
    try {
      const body = {
        myTeam: effectiveTeam,
        opponentTeams: opponent === "all" ? ["all"] : [opponent],
      };
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
      const res = await fetch("/api/trade/finder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(withValuationMode(body)),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data?.error || `Request failed (${res.status})`);
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(err?.message || "Request failed");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  const meta = result?.metadata;

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Trades"
        title="Market Arbitrage Finder"
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
        <p className={styles.muted}>
          This second layer scans actual rosters for packages that gain on our board while remaining plausible on the counterparty market.
        </p>
        <div className={styles.controls}>
          <Field label="Your team">
            <Select
              value={effectiveTeam}
              onChange={(e) => setMyTeam(e.target.value)}
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
              onChange={(e) => setOpponent(e.target.value)}
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
          <Button onClick={run} disabled={running || dataLoading || !effectiveTeam}>
            {running ? "Scanning…" : "Find trade packages"}
          </Button>
        </div>
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
          title="No package arbitrage found"
          description="Every candidate either lost value on our board or looked too lopsided on the counterparty's market to be plausible."
        />
      ) : null}

      {!running && result?.trades?.length ? (
        <div className={styles.trades}>
          {result.trades.map((t, i) => (
            <TradeCard key={i} trade={t} myTeam={effectiveTeam} opponent={opponent} />
          ))}
        </div>
      ) : null}

      {!result && !running ? (
        <EmptyState
          title="Package scan ready"
          description="The player-level opportunities above are live immediately. Choose your team and a counterparty to search actual trade constructions."
        />
      ) : null}
    </div>
  );
}
