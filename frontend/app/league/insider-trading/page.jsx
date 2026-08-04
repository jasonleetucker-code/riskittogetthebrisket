"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { useLeague } from "@/components/useLeague";
import InsiderLeads from "@/components/InsiderLeads";

// ── Insider Trading ──────────────────────────────────────────────────
// LEAGUE-SCOPED trade leads: what the managers in your selected league
// have been buying and selling in their OTHER Sleeper leagues, so you
// know who already wants a player before you offer.
//
// This is NOT Sharp Tracker.  Sharp Tracker (/market/sharp-tracker) is
// a global market signal from a qualified manager cohort and is not
// tied to your league.  This page's cohort is exactly "the other
// managers in this league" — no skill filter is applied or implied.
//
// Backed by GET /api/intel/summary (board), GET /api/intel/player
// (member-exposure drill-down) and POST /api/intel/leads (sell/buy mode
// lead ranking).  All numbers are computed server-side; this page is a
// pure renderer.

// Insider Trading defaults to ONE uncluttered window; the others are
// explicit filters.  These are overlapping views of the same rows, never
// additive buckets — a movement 15 days old appears under 30d AND 90d
// because it is one movement seen twice.  Nothing sums them.
const WINDOW_OPTIONS = [
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
];

const SORT_OPTIONS = [
  { key: "net", label: "Net" },
  { key: "volume", label: "Volume" },
  { key: "buys", label: "Most bought" },
  { key: "sells", label: "Most sold" },
];

const CONFIDENCE_STYLE = {
  high: { label: "High", color: "var(--green)" },
  medium: { label: "Medium", color: "var(--amber)" },
  low: { label: "Low", color: "var(--subtext)" },
  insufficient: { label: "—", color: "var(--subtext)" },
};

// Snapshot older than this renders the amber staleness banner.  The
// cron refreshes daily, so >30h means at least one missed run.
const STALE_WARN_HOURS = 30;

function fmtNet(net) {
  if (net > 0) return `+${net}`;
  return String(net);
}

function netColor(net) {
  if (net > 0) return "var(--green)";
  if (net < 0) return "var(--red)";
  return "var(--subtext)";
}

function ConfidenceBadge({ confidence }) {
  const style = CONFIDENCE_STYLE[confidence] || CONFIDENCE_STYLE.insufficient;
  return (
    <span
      className="badge"
      style={{ fontSize: "0.62rem", color: style.color, borderColor: style.color }}
      title="Sample strength: how much evidence sits behind this signal, not how strong the direction is."
    >
      {style.label}
    </span>
  );
}

function FilterGroup({ label, options, value, onChange, hint }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span
        className="muted"
        style={{ fontSize: "0.64rem", textTransform: "uppercase", letterSpacing: "0.04em" }}
        title={hint}
      >
        {label}
      </span>
      <div style={{ display: "flex", gap: 3 }}>
        {options.map((opt) => {
          const active = opt.key === value;
          return (
            <button
              key={opt.key}
              onClick={() => onChange(opt.key)}
              className={active ? "button" : "button-outline"}
              style={{
                fontSize: "0.72rem",
                padding: "3px 9px",
                minHeight: 30,
                opacity: active ? 1 : 0.75,
              }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StalenessBanner({ staleHours, generatedAt }) {
  if (staleHours == null) {
    return (
      <div
        className="card"
        style={{ marginBottom: 10, borderColor: "var(--amber)", fontSize: "0.78rem" }}
      >
        No intel snapshot yet — the first crawl hasn&apos;t run. Trigger a refresh or wait
        for the daily cron.
      </div>
    );
  }
  if (staleHours <= STALE_WARN_HOURS) return null;
  return (
    <div
      className="card"
      style={{ marginBottom: 10, borderColor: "var(--amber)", fontSize: "0.78rem" }}
    >
      <strong style={{ color: "var(--amber)" }}>Stale intel:</strong>{" "}
      snapshot is {Math.round(staleHours)}h old
      {generatedAt ? ` (generated ${new Date(generatedAt).toLocaleString()})` : ""} — the
      daily refresh may have failed.
    </div>
  );
}

function MemberExposure({ assetId, leagueKey }) {
  const [detail, setDetail] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setDetail(null);
    setFailed(false);
    const params = new URLSearchParams({ playerId: assetId });
    if (leagueKey) params.set("leagueKey", leagueKey);
    fetch(`/api/intel/player?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        if (!active) return;
        if (payload) setDetail(payload);
        else setFailed(true);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [assetId, leagueKey]);

  if (failed) {
    return (
      <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
        No member detail available for this asset.
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
        Loading member exposure…
      </div>
    );
  }
  const exposure = detail.memberExposure || [];
  const movements = detail.movements || [];
  const win = detail.windows?.[detail.window || "30d"] || {};
  if (exposure.length === 0 && movements.length === 0) {
    return (
      <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
        No league-mate holds or traded this asset in the tracked pool.
      </div>
    );
  }
  return (
    <div style={{ padding: "4px 0 8px" }}>
      <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>
        {detail.holderCount} league-mate{detail.holderCount === 1 ? "" : "s"} currently hold this
        asset across {detail.heldLeagueCount} league
        {detail.heldLeagueCount === 1 ? "" : "s"} · {win.volume || 0} trade movement
        {(win.volume || 0) === 1 ? "" : "s"} in the last {detail.window || "30d"}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>League-mate</th>
              <th style={{ textAlign: "right" }} title="Leagues where they currently roster the asset">
                Holds in
              </th>
              <th style={{ textAlign: "right" }}>Bought</th>
              <th style={{ textAlign: "right" }}>Sold</th>
              <th style={{ textAlign: "right" }}>Net</th>
              <th style={{ textAlign: "right" }} title="Leagues the trades happened in">
                Traded in
              </th>
            </tr>
          </thead>
          <tbody>
            {exposure.map((m) => (
              <tr key={m.ownerId}>
                <td style={{ fontWeight: 600 }}>{m.displayName || `Owner ${m.ownerId}`}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                  {m.heldLeagueCount}
                </td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--green)" }}>
                  {m.buys}
                </td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--red)" }}>
                  {m.sells}
                </td>
                <td
                  style={{
                    textAlign: "right",
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                    color: netColor(m.net),
                  }}
                >
                  {fmtNet(m.net)}
                </td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                  {m.tradedLeagueCount}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* The receipts.  Every count above is auditable back to the
          individual movements that produced it — the brief's "allow a
          transaction detail list so users can verify the count". */}
      {movements.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="muted" style={{ fontSize: "0.7rem", cursor: "pointer" }}>
            {movements.length} underlying trade movement
            {movements.length === 1 ? "" : "s"} — verify the count
          </summary>
          <div className="table-wrap" style={{ marginTop: 6 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>When</th>
                  <th style={{ textAlign: "left" }}>Manager</th>
                  <th style={{ textAlign: "left" }}>Direction</th>
                </tr>
              </thead>
              <tbody>
                {movements.map((mv) => (
                  <tr key={mv.movementId}>
                    <td style={{ fontFamily: "var(--mono)", fontSize: "0.7rem" }}>
                      {new Date(mv.ts).toLocaleDateString()}
                    </td>
                    <td style={{ fontSize: "0.72rem" }}>
                      {detail.memberExposure?.find((m) => m.ownerId === mv.userId)?.displayName ||
                        `Owner ${mv.userId}`}
                    </td>
                    <td
                      style={{
                        fontSize: "0.72rem",
                        color: mv.action === "add" ? "var(--green)" : "var(--red)",
                      }}
                    >
                      {mv.action === "add" ? "bought" : "sold"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

// The drill-down answers two different questions about one asset, so
// they are tabs rather than a single stacked wall: EVIDENCE is "what
// actually happened" (raw movements, verifiable), LEADS is "who to call
// about it" (a ranking derived from that evidence plus roster shape).
// Keeping them separate keeps the observation/inference line visible.
function AssetDetail({ assetId, displayName, leagueKey }) {
  const [tab, setTab] = useState("evidence");
  return (
    <div>
      <div style={{ display: "flex", gap: 4, padding: "6px 0 0" }}>
        {[
          { key: "evidence", label: "Evidence", hint: "Who holds it and the underlying trades." },
          { key: "leads", label: "Trade leads", hint: "Who to approach, and why." },
        ].map((opt) => (
          <button
            key={opt.key}
            onClick={() => setTab(opt.key)}
            className={opt.key === tab ? "button" : "button-outline"}
            style={{ fontSize: "0.7rem", padding: "3px 10px", minHeight: 26 }}
            title={opt.hint}
          >
            {opt.label}
          </button>
        ))}
      </div>
      {tab === "evidence" ? (
        <MemberExposure assetId={assetId} leagueKey={leagueKey} />
      ) : (
        <InsiderLeads assetId={assetId} assetName={displayName} leagueKey={leagueKey} />
      )}
    </div>
  );
}

// The board only carries assets that MOVED somewhere. The common trade
// question is about a player nobody has traded recently, so leads must
// be reachable without a board row — this resolves a typed name
// server-side (`name` in the request body) rather than filtering the
// board client-side.
function LeadLookup({ leagueKey }) {
  const [draft, setDraft] = useState("");
  const [target, setTarget] = useState(null);

  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const name = draft.trim();
          setTarget(name ? { name } : null);
        }}
        style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}
      >
        <label style={{ display: "flex", flexDirection: "column", gap: 3, flex: "1 1 240px" }}>
          <span
            className="muted"
            style={{ fontSize: "0.64rem", textTransform: "uppercase", letterSpacing: "0.04em" }}
          >
            Trade leads for any player
          </span>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Player name — who should I call about him?"
            style={{ fontSize: "0.78rem", padding: "5px 8px", minHeight: 34 }}
          />
        </label>
        <button type="submit" className="button" style={{ fontSize: "0.76rem", minHeight: 34 }}>
          Find leads
        </button>
        {target && (
          <button
            type="button"
            className="button-outline"
            onClick={() => {
              setTarget(null);
              setDraft("");
            }}
            style={{ fontSize: "0.76rem", minHeight: 34 }}
          >
            Clear
          </button>
        )}
      </form>
      {target && (
        <InsiderLeads key={target.name} assetName={target.name} leagueKey={leagueKey} />
      )}
    </div>
  );
}

export default function IntelPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedAsset, setExpandedAsset] = useState(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [window_, setWindow] = useState("30d");
  const [sort, setSort] = useState("net");
  const [direction, setDirection] = useState("all");
  const [search, setSearch] = useState("");

  // League binding: follow the league switcher's selection (same
  // useLeague subscription other league-aware pages use — it re-reads
  // on the ``league:changed`` event, so switching leagues while this
  // page is mounted re-fetches).  The key is passed EXPLICITLY on
  // every request so a navigation race can never fetch the previous
  // server-side preference.
  const { selectedLeagueKey, loading: leagueLoading } = useLeague();
  // Monotonic request id — a stale response from a previous league
  // can never overwrite a newer league's board.
  const requestSeq = useRef(0);

  const load = useCallback((leagueKey, activeWindow, activeSort) => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    // Window and sort are applied SERVER-SIDE: each window is its own
    // indexed ledger query, so the client must not try to derive one
    // window from another.
    const params = new URLSearchParams({ limit: "200", window: activeWindow, sort: activeSort });
    if (leagueKey) params.set("leagueKey", leagueKey);
    fetch(`/api/intel/summary?${params.toString()}`)
      .then(async (r) => {
        if (r.ok) return r.json();
        // 503 data_not_ready = this league has no snapshot yet —
        // render the "no snapshot" banner state, not an error.
        if (r.status === 503) {
          const body = await r.json().catch(() => null);
          if (body?.error === "data_not_ready") {
            return {
              assets: [],
              staleHours: null,
              generatedAt: null,
              memberCount: 0,
              leagueCount: 0,
              truncatedMemberCount: 0,
            };
          }
        }
        throw new Error(`HTTP ${r.status}`);
      })
      .then((payload) => {
        if (seq !== requestSeq.current) return; // stale response
        setData(payload);
        setLoading(false);
      })
      .catch((err) => {
        if (seq !== requestSeq.current) return;
        setError(String(err?.message || err));
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (leagueLoading) return; // wait for the resolved league key
    setExpandedAsset(null); // drill-down belongs to the old league
    load(selectedLeagueKey, window_, sort);
  }, [leagueLoading, selectedLeagueKey, window_, sort, load]);

  // Asset-type, direction and search are pure display filters over the
  // rows the server already scoped and ordered — they never recompute a
  // count.
  const assets = useMemo(() => {
    let rows = data?.assets || [];
    const active = data?.window || window_;
    if (typeFilter !== "all") rows = rows.filter((a) => a.assetType === typeFilter);
    if (direction === "buy") {
      rows = rows.filter((a) => (a.windows?.[active]?.net || 0) > 0);
    } else if (direction === "sell") {
      rows = rows.filter((a) => (a.windows?.[active]?.net || 0) < 0);
    }
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter((a) => String(a.displayName || "").toLowerCase().includes(q));
    return rows;
  }, [data, typeFilter, direction, search, window_]);

  if (loading) return <LoadingState message="Loading Insider Trading…" />;
  if (error) {
    return (
      <section>
        <PageHeader title="Insider Trading" subtitle="Trade leads from your league-mates' activity elsewhere." />
        <div className="card">
          <EmptyState title="Couldn't load insider activity" message={error} />
        </div>
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        title="Insider Trading"
        subtitle={
          `Trades your league-mates made in their OTHER Sleeper leagues — ` +
          `${data?.memberCount ?? 0} managers, ${data?.leagueCount ?? 0} leagues observed. ` +
          `These are the managers in this league, not a skill-filtered cohort.`
        }
      />

      <StalenessBanner staleHours={data?.staleHours} generatedAt={data?.generatedAt} />

      <LeadLookup leagueKey={selectedLeagueKey} />

      {data?.truncatedMemberCount > 0 && (
        <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 8 }}>
          {data.truncatedMemberCount} manager{data.truncatedMemberCount === 1 ? "" : "s"} above
          the 25-league crawl cap — their deepest leagues aren&apos;t tracked.
        </div>
      )}

      <div
        className="card"
        style={{ marginBottom: 10, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}
      >
        <FilterGroup
          label="Window"
          options={WINDOW_OPTIONS}
          value={window_}
          onChange={setWindow}
          hint="Overlapping views of the same trades — never added together."
        />
        <FilterGroup
          label="Sort"
          options={SORT_OPTIONS}
          value={sort}
          onChange={setSort}
        />
        <FilterGroup
          label="Direction"
          options={[
            { key: "all", label: "All" },
            { key: "buy", label: "Buying" },
            { key: "sell", label: "Selling" },
          ]}
          value={direction}
          onChange={setDirection}
        />
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span className="muted" style={{ fontSize: "0.64rem", textTransform: "uppercase" }}>
            Search
          </span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Player or pick…"
            style={{ fontSize: "0.74rem", padding: "4px 8px", minHeight: 32 }}
          />
        </label>
      </div>

      <div className="card" style={{ marginBottom: 10, display: "flex", gap: 4, flexWrap: "wrap" }}>
        {[
          { key: "all", label: "All assets" },
          { key: "player", label: "Players" },
          { key: "pick", label: "Picks" },
        ].map((opt) => {
          const active = opt.key === typeFilter;
          return (
            <button
              key={opt.key}
              onClick={() => setTypeFilter(opt.key)}
              className={active ? "button" : "button-outline"}
              style={{ fontSize: "0.74rem", padding: "4px 10px", minHeight: 32, opacity: active ? 1 : 0.78 }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {assets.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No tracked activity yet"
            message="No buy/sell events in the rolling windows. Check back after the next crawl."
          />
        </div>
      ) : (
        <div className="card">
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 6 }}>
            {assets.length} asset{assets.length === 1 ? "" : "s"} · trades only, last{" "}
            {data?.window || "30d"} · sorted by {SORT_OPTIONS.find((s) => s.key === sort)?.label}
            {" "}· click a row for the managers and the underlying trades
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Asset</th>
                  <th style={{ textAlign: "right" }} title="Buys minus sells">Net</th>
                  <th
                    style={{ textAlign: "right" }}
                    title="Buys plus sells — the evidence behind the direction. Net is never shown without it."
                  >
                    Volume
                  </th>
                  <th style={{ textAlign: "right" }}>Buys</th>
                  <th style={{ textAlign: "right" }}>Sells</th>
                  <th style={{ textAlign: "right" }} title="Distinct managers involved">Mgrs</th>
                  <th
                    style={{ textAlign: "right" }}
                    title="Distinct leagues the trades happened in (not leagues where the asset is merely rostered)"
                  >
                    Leagues
                  </th>
                  <th style={{ textAlign: "right" }}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((asset) => {
                  const expanded = expandedAsset === asset.assetId;
                  const win = asset.windows?.[data?.window || "30d"] || {};
                  return [
                    <tr
                      key={asset.assetId}
                      onClick={() => setExpandedAsset(expanded ? null : asset.assetId)}
                      style={{ cursor: "pointer" }}
                    >
                      <td style={{ fontWeight: 600 }}>
                        <span style={{ marginRight: 6 }}>{expanded ? "▼" : "▶"}</span>
                        {asset.displayName}
                        {asset.assetType === "pick" && (
                          <span className="badge" style={{ marginLeft: 6, fontSize: "0.64rem" }}>
                            PICK
                          </span>
                        )}
                      </td>
                      <td
                        style={{
                          textAlign: "right",
                          fontFamily: "var(--mono)",
                          fontWeight: 700,
                          color: netColor(win.net || 0),
                        }}
                      >
                        {fmtNet(win.net || 0)}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>
                        {win.volume || 0}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--green)" }}>
                        {win.buys || 0}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--red)" }}>
                        {win.sells || 0}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {win.uniqueManagers || 0}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {win.uniqueLeagues || 0}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <ConfidenceBadge confidence={asset.confidence} />
                      </td>
                    </tr>,
                    expanded ? (
                      <tr key={`${asset.assetId}::detail`}>
                        <td colSpan={8} style={{ background: "rgba(255,255,255,0.02)" }}>
                          <AssetDetail
                            assetId={asset.assetId}
                            displayName={asset.displayName}
                            leagueKey={selectedLeagueKey}
                          />
                        </td>
                      </tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
