"use client";

import { useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useTeam } from "@/components/useTeam";
import {
  Badge,
  Banner,
  Button,
  DataTable,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
  StatTile,
} from "@/components/ds";
import { withValuationMode } from "@/lib/valuation-mode";
import styles from "./angle.module.css";

// ── /angle — the counter-pitch builder ────────────────────────────────
//
// Pick one or more players on your roster, optionally pick a target
// team, get back ranked counter-packages where the trade wins on your
// league's calibrated rankings (default ≥5%) but still looks fair-or-
// better on the market the counterparty consults (default ≤5%). Market
// is per-position: IDP Trade Calculator for DL/LB/DB, KTC for everyone
// else — the backend routes automatically.
//
// When players from the target team are selected the page switches to
// "acquire" mode: the backend finds what to give up from your roster to
// get those specific players back.
//
// Every package, value, and percentage on this page is computed by
// POST /api/angle/packages. Nothing here recomputes trade math.

const IDP_POS_RE = /^(?:DL|DE|DT|EDGE|NT|LB|ILB|OLB|MLB|DB|CB|S|SS|FS)$/i;

function marketSourceForPos(position) {
  return IDP_POS_RE.test(String(position || "").trim()) ? "idpTradeCalc" : "ktcSfTep";
}

function marketLabelForSource(source) {
  return source === "idpTradeCalc" ? "IDPTC" : "KTC";
}

function fmtValue(v) {
  return Number(v || 0).toLocaleString();
}

function fmtSignedPct(v) {
  const n = Number(v || 0);
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

// ── Roster picker ─────────────────────────────────────────────────────

function RosterPicker({
  names,
  valueByName,
  selected,
  onToggle,
  disabled,
  emptyMessage,
}) {
  if (names.length === 0) {
    return <div className={styles.rosterEmpty}>{emptyMessage}</div>;
  }
  return (
    <div className={styles.rosterList}>
      {names.map((name) => {
        const info = valueByName.get(name);
        const checked = selected.has(name);
        return (
          <label
            key={name}
            className={`${styles.rosterRow} ${
              checked ? styles.rosterRowSelected : ""
            }`}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => onToggle(name)}
              disabled={disabled}
            />
            <span className={styles.rosterName}>
              <span className={styles.rosterNameText}>{name}</span>
              <Badge tone="outline">{info?.position || "—"}</Badge>
            </span>
            {info?.my_value ? (
              <span className={styles.rosterValue}>
                {fmtValue(info.my_value)}
              </span>
            ) : null}
          </label>
        );
      })}
    </div>
  );
}

// ── Results ───────────────────────────────────────────────────────────

function PackagePlayers({ players }) {
  return (
    <div className={styles.packagePlayers}>
      {(players || []).map((p) => (
        <span key={p.name} className={styles.packagePlayer}>
          <Badge tone="outline">{p.position}</Badge>
          <span className={styles.packagePlayerName}>{p.name}</span>
          <span className={styles.packagePlayerValue}>
            {fmtValue(p.my_value)} · {fmtValue(p.market_value)}{" "}
            {marketLabelForSource(p.market_source)}
          </span>
        </span>
      ))}
    </div>
  );
}

function FixedSidePanel({ fixedSide, resultIsAcquire }) {
  if (!fixedSide) return null;
  return (
    <Panel
      title={resultIsAcquire ? "You receive" : "You send"}
      headingLevel={2}
    >
      <div className={styles.fixedSide}>
        <PackagePlayers players={fixedSide.players} />
        {fixedSide.my_total || fixedSide.market_total ? (
          <div className={styles.fixedTotals}>
            <StatTile label="My total" value={fmtValue(fixedSide.my_total)} />
            <StatTile
              label="Market total"
              value={fmtValue(fixedSide.market_total)}
            />
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

// ── Page ──────────────────────────────────────────────────────────────

export default function AnglePage() {
  const { loading: dataLoading, error: dataError, rawData, rows } = useDynastyData();
  const { selectedLeagueKey, selectedOwnerId: activeOwnerId } = useTeam();

  const teams = useMemo(() => {
    const list = rawData?.sleeper?.teams || [];
    return [...list].sort((a, b) =>
      String(a?.name || "").localeCompare(String(b?.name || "")),
    );
  }, [rawData]);

  // canonicalName → my-value, market-value, position.
  const valueByName = useMemo(() => {
    const m = new Map();
    for (const r of rows || []) {
      const name = r?.name || r?.canonicalName;
      if (!name) continue;
      const pos = r?.pos || r?.position || "";
      const source = marketSourceForPos(pos);
      m.set(name, {
        my_value: Number(r?.rankDerivedValue) || 0,
        market_value:
          Number(r?.canonicalSites?.[source]) || Number(r?.canonicalSites?.ktc) || 0,
        market_source: source,
        position: pos,
      });
    }
    return m;
  }, [rows]);

  const [ownerId, setOwnerId] = useState("");
  const [playerNames, setPlayerNames] = useState(() => new Set());
  const [playerSearch, setPlayerSearch] = useState("");
  const [targetOwnerId, setTargetOwnerId] = useState("");
  const [targetPlayerNames, setTargetPlayerNames] = useState(() => new Set());
  const [targetPlayerSearch, setTargetPlayerSearch] = useState("");
  const [minMyGainPct, setMinMyGainPct] = useState(5);
  const [maxMarketGainPct, setMaxMarketGainPct] = useState(5);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (ownerId) return;
    if (activeOwnerId && teams.some((t) => String(t.ownerId) === String(activeOwnerId))) {
      setOwnerId(String(activeOwnerId));
    } else if (teams.length > 0) {
      setOwnerId(String(teams[0].ownerId || ""));
    }
  }, [activeOwnerId, teams, ownerId]);

  const myTeam = useMemo(
    () => teams.find((t) => String(t.ownerId || "") === String(ownerId)),
    [teams, ownerId],
  );
  const opposingTeams = useMemo(
    () => teams.filter((t) => String(t.ownerId || "") !== String(ownerId)),
    [teams, ownerId],
  );
  const targetTeam = useMemo(
    () => teams.find((t) => String(t.ownerId || "") === String(targetOwnerId)),
    [teams, targetOwnerId],
  );

  const sortByValue = useMemo(
    () => (a, b) => {
      const av = valueByName.get(a)?.my_value || 0;
      const bv = valueByName.get(b)?.my_value || 0;
      return bv !== av ? bv - av : a.localeCompare(b);
    },
    [valueByName],
  );

  const roster = useMemo(() => {
    if (!myTeam) return [];
    const q = playerSearch.trim().toLowerCase();
    return [...(myTeam.players || [])]
      .filter((name) => !q || name.toLowerCase().includes(q))
      .sort(sortByValue);
  }, [myTeam, playerSearch, sortByValue]);

  const targetRoster = useMemo(() => {
    if (!targetTeam) return [];
    const q = targetPlayerSearch.trim().toLowerCase();
    return [...(targetTeam.players || [])]
      .filter((name) => !q || name.toLowerCase().includes(q))
      .sort(sortByValue);
  }, [targetTeam, targetPlayerSearch, sortByValue]);

  // Wipe selections + stale results when the user switches their own team.
  // targetPlayerNames must clear too — the new team may own some of those
  // players, and the backend silently drops self-owned acquire targets.
  // targetOwnerId clears when it now points at the newly selected team,
  // which would render the user's own roster as "players to acquire".
  useEffect(() => {
    setPlayerNames(new Set());
    setTargetPlayerNames(new Set());
    setTargetOwnerId((prev) => (prev === ownerId ? "" : prev));
    setResult(null);
    setErr(null);
  }, [ownerId]);

  useEffect(() => {
    setTargetPlayerNames(new Set());
    setTargetPlayerSearch("");
    setResult(null);
    setErr(null);
  }, [targetOwnerId]);

  function toggleIn(setter) {
    return (name) =>
      setter((prev) => {
        const next = new Set(prev);
        if (next.has(name)) next.delete(name);
        else next.add(name);
        return next;
      });
  }
  const togglePlayer = toggleIn(setPlayerNames);
  const toggleTargetPlayer = toggleIn(setTargetPlayerNames);

  const playerNameList = useMemo(() => Array.from(playerNames), [playerNames]);
  const targetPlayerNameList = useMemo(
    () => Array.from(targetPlayerNames),
    [targetPlayerNames],
  );

  // Acquire mode when the user picked target players to receive; offer
  // mode otherwise (find what to get back for your send players).
  const isAcquireMode = targetPlayerNameList.length > 0;

  const totalsFor = useMemo(
    () => (nameList) => {
      let my = 0;
      let market = 0;
      for (const name of nameList) {
        const info = valueByName.get(name);
        if (info) {
          my += info.my_value || 0;
          market += info.market_value || 0;
        }
      }
      return { my, market };
    },
    [valueByName],
  );
  const offerTotals = useMemo(
    () => totalsFor(playerNameList),
    [totalsFor, playerNameList],
  );
  const targetTotals = useMemo(
    () => totalsFor(targetPlayerNameList),
    [totalsFor, targetPlayerNameList],
  );

  async function findTrades() {
    if (!ownerId) {
      setErr("Pick your team.");
      return;
    }
    if (!isAcquireMode && playerNameList.length === 0) {
      setErr(
        "Pick at least one player on your roster to send, or select players from the target team to acquire.",
      );
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const body = isAcquireMode
        ? {
            mode: "acquire",
            ownerId,
            acquirePlayerNames: targetPlayerNameList,
            minMyGainPct: Number(minMyGainPct),
            maxMarketGainPct: Number(maxMarketGainPct),
          }
        : {
            mode: "offer",
            ownerId,
            playerNames: playerNameList,
            minMyGainPct: Number(minMyGainPct),
            maxMarketGainPct: Number(maxMarketGainPct),
          };
      if (targetOwnerId) body.targetTeamOwnerIds = [targetOwnerId];
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;

      const res = await fetch("/api/angle/packages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        // Our side of the arbitrage follows the selected board; the
        // market anchor the pitch rests on never does.
        body: JSON.stringify(withValuationMode(body)),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        setErr(
          res.status === 503
            ? "Roster data not loaded for this league yet — try again in a moment."
            : data?.error || `HTTP ${res.status}`,
        );
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (e) {
      setErr(e?.message || "Network error");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  // Drive result rendering from the mode stamped on the RESPONSE, not the
  // current UI selection — otherwise clearing a selection after a search
  // re-labels stale results.
  const resultIsAcquire = (result?.mode ?? null) === "acquire";
  const fixedSide = resultIsAcquire ? result?.acquire || null : result?.offer || null;
  const candidates = result?.candidates || [];
  const warnings = result?.warnings || [];

  const canSubmit = !!ownerId && (isAcquireMode || playerNameList.length > 0) && !loading;

  const packageColumns = useMemo(
    () => [
      {
        key: "players",
        header: "Package",
        accessor: (c) => (c.players || []).map((p) => p.name).join(", "),
        render: (c) => (
          <div className={styles.packageAssets}>
            <span className={styles.packageOrigin}>
              {resultIsAcquire
                ? `Give to ${targetTeam?.name || "them"}`
                : `From ${c.team || "(unknown)"}`}{" "}
              · {c.size} {c.size === 1 ? "player" : "players"}
            </span>
            <PackagePlayers players={c.players} />
          </div>
        ),
      },
      {
        key: "my_total",
        header: "My total",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (c) => c.my_total,
        render: (c) => fmtValue(c.my_total),
      },
      {
        key: "market_total",
        header: "Market total",
        numeric: true,
        sortable: true,
        hideBelow: "lg",
        accessor: (c) => c.market_total,
        render: (c) => fmtValue(c.market_total),
      },
      {
        key: "my_gain_pct",
        header: "My gain",
        numeric: true,
        sortable: true,
        accessor: (c) => c.my_gain_pct,
        render: (c) => fmtSignedPct(c.my_gain_pct),
        headerInfo: "How far the package beats your offer on your own board.",
      },
      {
        key: "market_gain_pct",
        header: "Market gap",
        numeric: true,
        sortable: true,
        accessor: (c) => c.market_gain_pct,
        render: (c) => fmtSignedPct(c.market_gain_pct),
        headerInfo: "How the package reads on the market the counterparty consults.",
      },
      {
        key: "arb_score",
        header: "Arb",
        numeric: true,
        sortable: true,
        accessor: (c) => c.arb_score,
        render: (c) => <Badge tone="accent">{fmtSignedPct(c.arb_score)}</Badge>,
        headerInfo: "Arbitrage edge — your gain net of the market gap.",
      },
    ],
    [resultIsAcquire, targetTeam],
  );

  if (dataLoading) {
    return (
      <main className={`main-shell ${styles.page}`}>
        <PageHeader eyebrow="Trades" title="Package Builder" />
        <Panel flush>
          <SkeletonTable rows={5} columns={4} />
        </Panel>
      </main>
    );
  }
  if (dataError) {
    return (
      <main className={`main-shell ${styles.page}`}>
        <PageHeader eyebrow="Trades" title="Package Builder" />
        <Banner tone="negative" title="Failed to load data">
          {String(dataError)}
        </Banner>
      </main>
    );
  }

  return (
    <main className={`main-shell ${styles.page} angle-page`}>
      <PageHeader
        eyebrow="Trades"
        title="Package Builder"
        description="Pick players to send and get ranked return packages — or pick players you want from a target team and find what you'd have to give up."
      />

      <Panel
        className="angle-form"
        title="Build the pitch"
        subtitle={
          isAcquireMode
            ? "Acquire mode — finding what you'd need to give up for the selected players."
            : "Offer mode — finding what you could get back."
        }
      >
        <div className={styles.formGrid}>
          {/* Column 1 — your team */}
          <div className={styles.field}>
            <Field label="Your team" id="angle-owner">
              <Select
                id="angle-owner"
                value={ownerId}
                onChange={(e) => setOwnerId(e.target.value)}
                disabled={loading || teams.length === 0}
              >
                {teams.length === 0 ? (
                  <option value="">No teams loaded</option>
                ) : (
                  teams.map((t) => (
                    <option key={t.ownerId} value={String(t.ownerId || "")}>
                      {t.name}
                    </option>
                  ))
                )}
              </Select>
            </Field>
          </div>

          {/* Column 2 — your players to send */}
          <div className={styles.field}>
            <span className={styles.fieldLabel}>
              Players to send
              <span className={styles.fieldCount}>
                {playerNameList.length} selected
              </span>
              {isAcquireMode ? <Badge tone="outline">optional</Badge> : null}
            </span>
            <Input
              type="search"
              placeholder="Search your roster…"
              value={playerSearch}
              onChange={(e) => setPlayerSearch(e.target.value)}
              disabled={loading || !myTeam}
              aria-label="Search your roster"
            />
            <RosterPicker
              names={roster}
              valueByName={valueByName}
              selected={playerNames}
              onToggle={togglePlayer}
              disabled={loading}
              emptyMessage={myTeam ? "No matches" : "No players on this roster"}
            />
            {playerNameList.length > 1 && offerTotals.my > 0 ? (
              <span className={styles.selectionTotal}>
                Offer total: {fmtValue(offerTotals.my)} my ·{" "}
                {fmtValue(offerTotals.market)} market
              </span>
            ) : null}
          </div>

          {/* Column 3 — counterparty + acquire targets + advanced */}
          <div className={styles.field}>
            <Field label="Trade with" id="angle-target">
              <Select
                id="angle-target"
                value={targetOwnerId}
                onChange={(e) => setTargetOwnerId(e.target.value)}
                disabled={loading || opposingTeams.length === 0}
              >
                <option value="">Any team</option>
                {opposingTeams.map((t) => (
                  <option key={t.ownerId} value={String(t.ownerId || "")}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>

            {targetTeam ? (
              <>
                <span className={styles.fieldLabel}>
                  Acquire from {targetTeam.name}
                  {targetPlayerNameList.length > 0 ? (
                    <span className={styles.fieldCount}>
                      {targetPlayerNameList.length} selected
                    </span>
                  ) : null}
                </span>
                <Input
                  type="search"
                  placeholder={`Search ${targetTeam.name}…`}
                  value={targetPlayerSearch}
                  onChange={(e) => setTargetPlayerSearch(e.target.value)}
                  disabled={loading}
                  aria-label={`Search ${targetTeam.name}`}
                />
                <RosterPicker
                  names={targetRoster}
                  valueByName={valueByName}
                  selected={targetPlayerNames}
                  onToggle={toggleTargetPlayer}
                  disabled={loading}
                  emptyMessage="No matches"
                />
                {targetPlayerNameList.length > 1 && targetTotals.my > 0 ? (
                  <span className={styles.selectionTotal}>
                    Target total: {fmtValue(targetTotals.my)} my ·{" "}
                    {fmtValue(targetTotals.market)} market
                  </span>
                ) : null}
              </>
            ) : null}

            <details>
              <summary>Advanced thresholds</summary>
              <div className={styles.advanced}>
                <Field
                  label="Min my-value gain %"
                  hint="Counter must beat the offer by at least this much on your board."
                  id="angle-min-gain"
                >
                  <Input
                    id="angle-min-gain"
                    type="number"
                    step="1"
                    min="0"
                    value={minMyGainPct}
                    onChange={(e) => setMinMyGainPct(e.target.value)}
                    disabled={loading}
                  />
                </Field>
                <Field
                  label="Max market gap %"
                  hint="KTC for offense, IDPTC for IDP."
                  id="angle-max-market"
                >
                  <Input
                    id="angle-max-market"
                    type="number"
                    step="1"
                    value={maxMarketGainPct}
                    onChange={(e) => setMaxMarketGainPct(e.target.value)}
                    disabled={loading}
                  />
                </Field>
              </div>
            </details>
          </div>
        </div>

        <div className={styles.actions}>
          <Button variant="primary" onClick={findTrades} disabled={!canSubmit} loading={loading}>
            {isAcquireMode
              ? `Find what to give up (${targetPlayerNameList.length})`
              : `Find return options${playerNameList.length ? ` (${playerNameList.length})` : ""}`}
          </Button>
          {(playerNameList.length > 0 || targetPlayerNameList.length > 0) && !loading ? (
            <Button
              onClick={() => {
                setPlayerNames(new Set());
                setTargetPlayerNames(new Set());
              }}
            >
              Clear selection
            </Button>
          ) : null}
        </div>

        {err ? (
          <Banner tone="negative" title="Couldn't find packages">
            {err}
          </Banner>
        ) : null}
      </Panel>

      {warnings.length > 0 ? (
        <Banner tone="warning" title="Note">
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Banner>
      ) : null}

      <FixedSidePanel fixedSide={fixedSide} resultIsAcquire={resultIsAcquire} />

      {result ? (
        <Panel
          flush
          title={
            resultIsAcquire
              ? `What to give up${targetTeam ? ` to ${targetTeam.name}` : ""}`
              : targetTeam
                ? `Return options from ${targetTeam.name}`
                : "Return options from any team"
          }
          subtitle={`Each package clears +${Number(minMyGainPct)}% on your board and stays within ±${Number(maxMarketGainPct)}% on the market the other side consults.`}
        >
          <DataTable
            caption="Ranked counter-packages, best arbitrage edge first"
            columns={packageColumns}
            rows={candidates}
            rowKey={(c, i) =>
              `${c.owner_id}-${i}-${(c.players || []).map((p) => p.name).join("|")}`
            }
            density="compact"
            defaultSort={{ key: "arb_score", direction: "desc" }}
            emptyState={
              <EmptyState
                title="No packages clear the bar"
                description={`Nothing hits +${Number(minMyGainPct)}% / ±${Number(maxMarketGainPct)}% with this selection${
                  targetTeam ? ` against ${targetTeam.name}` : ""
                }. Try a different selection, loosen the thresholds under Advanced, or remove the team filter.`}
              />
            }
          />
        </Panel>
      ) : null}
    </main>
  );
}
