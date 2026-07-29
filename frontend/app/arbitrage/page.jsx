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
import styles from "./arbitrage.module.css";

// ── /arbitrage — the board-vs-market arbitrage finder ─────────────────
//
// This is the UI caller for src/trade/finder.py, which had none. The
// engine was built, audited (per-market top-150 gating, marketCoverage,
// assetsUnpricedByBoard, valueSource stamping), exposed at
// POST /api/trade/finder — and never invoked by anything. Backlog #6.
//
// WHY THIS IS NOT ON /finder, despite the name. /finder is a board
// filter: five presets that sort the board on sourceRankSpread /
// confidenceBucket / isSingleSource / rookie. It computes no
// board-versus-market comparison at all. A stale header comment there
// once called it "the arbitrage blotter", and that single word is what
// made an earlier audit record a phantom second implementation
// competing with this engine. Putting a real arbitrage view on that
// route would recreate exactly that confusion.
//
// Everything below is rendered verbatim from the backend response. This
// file computes no trade values, no deltas, and no scores — same rule as
// buildRows. The one thing it derives is display formatting.

function fmt(v) {
  return Number(v || 0).toLocaleString();
}

function fmtSigned(v) {
  const n = Number(v || 0);
  return `${n > 0 ? "+" : ""}${fmt(Math.round(n))}`;
}

const MARKET_LABEL = { ktcSfTep: "KTC", ktc: "KTC", idpTradeCalc: "IDPTC" };

function AssetList({ assets, tone }) {
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

  // A found trade was a dead end: the engine surfaced it, and then you
  // retyped both sides into the calculator by hand.  The share encoder
  // already round-trips exactly this shape, so the hand-off is a link.
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
      // A trade we cannot encode simply loses the shortcut; the card
      // itself still renders.
      return null;
    }
  }, [trade, myTeam, opponent]);

  return (
    <Panel className={styles.tradeCard}>
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
        {/* The backend stamps ``mixedMarket`` itself rather than making
            the client infer it. A mixed delta adds two publishers'
            numbers; they are directly comparable (median cross-board
            ratio 1.000) but disagree +/-10% at p10-p90, so a delta
            smaller than that is not distinguishable from the boards
            simply disagreeing. Surfacing it is the point. */}
        {trade.mixedMarket ? (
          <Badge tone="warning">
            spans {(trade.marketsUsed || []).map((m) => MARKET_LABEL[m] || m).join(" + ")}
          </Badge>
        ) : null}
      </div>
      <div className={styles.tradeBody}>
        <div className={styles.side}>
          <h4 className={styles.sideLabel}>You give</h4>
          <AssetList assets={trade.give} tone="give" />
        </div>
        <div className={styles.side}>
          <h4 className={styles.sideLabel}>You get</h4>
          <AssetList assets={trade.receive} tone="receive" />
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
  const { loading: dataLoading, error: dataError, rawData } = useDynastyData();
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

  const effectiveTeam = myTeam || defaultTeam;

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
        // Our side of the arbitrage follows the selected board; the
        // market anchor it is measured against never does.
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
        title="Arbitrage"
        description="Trades that gain on our blended board while still reading as fair on the market your counterparty checks."
      />

      {dataError ? <Banner tone="negative">{String(dataError)}</Banner> : null}

      <Panel>
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
            {running ? "Scanning…" : "Find arbitrage"}
          </Button>
        </div>
      </Panel>

      {error ? <Banner tone="negative">{error}</Banner> : null}

      {/* Backend warnings are rendered verbatim. The engine emits a real
          one when an IDP league has no priced IDP assets, which is the
          regression that made this engine silently offense-only. */}
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
          {/* Assets the board declines to price leave the engine's
              universe entirely. Surfaced because "not shown" and
              "not priced" are different states — 202 on a real payload. */}
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
          title="No arbitrage found"
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
          title="Pick a team and scan"
          description="Choose your team and a counterparty above, then run the scan to surface trades the market prices differently than our board does."
        />
      ) : null}
    </div>
  );
}
