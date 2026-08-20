"use client";

/**
 * Sharp Roster Percentage — which players the sharp cohort actually owns.
 *
 * Sibling of /market/sharp-tracker, and deliberately so: both boards
 * read the SAME cohort (`src/sharp/cohort.py::cohort_members`), so the
 * two answer different questions about one population rather than
 * describing two populations that happen to share a name. That is why
 * this page carries a Buy/Sell column — a player who is widely rostered
 * AND being sold tells a different story from one whose ownership is
 * climbing, and the join is the point.
 *
 * Everything numeric here is backend-computed. `lib/sharp-roster-percentage.js`
 * formats and reshapes; it never divides. The denominator rule is
 * per-player (a linebacker is measured against IDP leagues only), so a
 * client-side percentage would be wrong the moment that rule moves.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Banner, DataTable, Panel, PageHeader, Select, StatTile } from "@/components/ds";
import { LoadingState } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";
import {
  buildExclusionRows,
  buildTransparencyTiles,
  classifyEmptyState,
  describeBuySell,
  describeManagerConcentration,
  describeTrend,
  formatCount,
  formatDelta,
  formatPct,
  formatSample,
  formatTimestamp,
} from "@/lib/sharp-roster-percentage";

const PAGE_TITLE = "Sharp Roster Percentage";

const POSITIONS = [
  ["all", "All players"],
  ["QB", "Quarterbacks"],
  ["RB", "Running backs"],
  ["WR", "Wide receivers"],
  ["TE", "Tight ends"],
  ["DL", "Defensive line / EDGE"],
  ["LB", "Linebackers"],
  ["DB", "Defensive backs"],
  ["offense", "Offense only"],
  ["idp", "IDP only"],
];

const PLATFORMS = [
  ["all", "All supported platforms"],
  ["sleeper", "Sleeper only"],
  ["ffpc", "FFPC only"],
];

const FORMATS = [
  ["all", "All formats"],
  ["superflex", "Superflex leagues"],
  ["oneQb", "One-quarterback leagues"],
  ["tePremium", "Tight-end premium"],
  ["nonTePremium", "Non tight-end premium"],
];

const CONTENTION = [
  ["all", "All sharp rosters"],
  ["contending", "Contending rosters"],
  ["rebuilding", "Rebuilding rosters"],
];

const EXPERIENCE = [
  ["all", "Rookies and veterans"],
  ["rookies", "Rookies"],
  ["veterans", "Veterans"],
];

const SORTS = [
  ["rostered", "Most rostered by sharps"],
  ["advantage", "Largest positive sharp advantage"],
  ["negativeAdvantage", "Largest negative sharp advantage"],
  ["valueWithoutRosters", "High value, low sharp ownership"],
  ["rosteredWithoutValue", "Low rank, high sharp ownership"],
  ["trend", "Rising fastest (30 days)"],
];

const LIMITS = [
  ["25", "Top 25"],
  ["50", "Top 50"],
  ["100", "Top 100"],
  ["0", "All qualifying players"],
];

const AUTO_REFRESH_MS = 300_000;
const RETRYABLE_STATUSES = new Set([404, 502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Same fetch posture as /market/sharp-tracker: never a cached body, and
// a bounded retry for the transient 404 a cold backend route can return.
async function fetchFreshJson(path, params, { attempts = 3 } = {}) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const url = new URL(path, window.location.origin);
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value != null && value !== "") url.searchParams.set(key, String(value));
    });
    url.searchParams.set("_sharpRefresh", String(Date.now()));
    try {
      const response = await fetch(url.toString(), {
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Cache-Control": "no-cache, no-store, max-age=0", Pragma: "no-cache" },
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok) return payload;
      lastError = new Error(apiErrorMessage(payload, response.status));
      if (!RETRYABLE_STATUSES.has(response.status) || attempt === attempts) throw lastError;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(apiErrorMessage(error));
      if (attempt === attempts) throw lastError;
    }
    await sleep(attempt * 750);
  }
  throw lastError || new Error("Request failed");
}

function Dropdown({ label, value, onChange, options }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 190 }}>
      <span className="muted" style={{ fontSize: "0.68rem", textTransform: "uppercase" }}>
        {label}
      </span>
      <Select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </Select>
    </label>
  );
}

function TrendCell({ row, period }) {
  const trend = describeTrend(row.trend, period);
  if (!trend.available) {
    return (
      <span className="muted" title={trend.reason || undefined}>
        {trend.label}
      </span>
    );
  }
  return (
    <span
      title={`${trend.added} roster(s) added, ${trend.dropped} dropped`}
      style={{
        color:
          trend.tone === "positive"
            ? "var(--positive)"
            : trend.tone === "negative"
              ? "var(--negative)"
              : undefined,
      }}
    >
      {trend.label}
    </span>
  );
}

export default function SharpRosterPercentagePage() {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [position, setPosition] = useState("all");
  const [platform, setPlatform] = useState("all");
  const [format, setFormat] = useState("all");
  const [contention, setContention] = useState("all");
  const [experience, setExperience] = useState("all");
  const [sort, setSort] = useState("rostered");
  const [limit, setLimit] = useState("50");

  const load = useCallback(async () => {
    try {
      const data = await fetchFreshJson("/api/sharp/roster-percentage", {
        position,
        platform,
        format,
        contention,
        experience,
        sort,
        limit,
      });
      setPayload(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [position, platform, format, contention, experience, sort, limit]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(load, AUTO_REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const rows = payload?.players || [];
  const tiles = useMemo(() => buildTransparencyTiles(payload), [payload]);
  const exclusions = useMemo(() => buildExclusionRows(payload), [payload]);
  const marketAvailable = payload?.marketComparison?.available;
  const sampleWarning = payload?.sample?.warning;

  const columns = useMemo(() => {
    const base = [
      { key: "rank", header: "#", numeric: true, accessor: (row) => row.rank },
      {
        key: "displayName",
        header: "Player",
        accessor: (row) => row.displayName,
      },
      { key: "position", header: "Pos", accessor: (row) => row.position || "—" },
      { key: "nflTeam", header: "Team", accessor: (row) => row.nflTeam || "—" },
      {
        key: "sharpRosterPct",
        header: "Sharp roster %",
        numeric: true,
        headerInfo:
          "Unique eligible sharp rosters holding the player, divided by the eligible " +
          "sharp rosters whose league can field his position.",
        render: (row) => (
          <span title={row.sampleWarning?.message || undefined}>
            {formatPct(row.sharpRosterPct)}
            {row.sampleWarning ? " *" : ""}
          </span>
        ),
        sortAccessor: (row) => row.sharpRosterPct,
      },
      {
        key: "sample",
        header: "Sample",
        headerInfo:
          "Rosters holding the player / eligible rosters in his calculation. " +
          "A manager count in parens means those rosters are not all independent opinions.",
        render: (row) => (
          <span className="muted" title={describeManagerConcentration(row)}>
            {formatSample(row)}
          </span>
        ),
        sortAccessor: (row) => row.eligibleRosters,
      },
      {
        key: "marketRosterPct",
        header: "Dynasty roster %",
        numeric: true,
        headerInfo: marketAvailable
          ? "General dynasty roster percentage, for comparison."
          : "No general-dynasty ownership feed is ingested, so this is unavailable.",
        render: (row) => formatPct(row.marketRosterPct),
        sortAccessor: (row) => row.marketRosterPct ?? -1,
      },
      {
        key: "sharpRosterAdvantage",
        header: "Sharp advantage",
        numeric: true,
        headerInfo: "Sharp roster % minus general dynasty roster %.",
        render: (row) => formatDelta(row.sharpRosterAdvantage),
        sortAccessor: (row) => row.sharpRosterAdvantage ?? -Infinity,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        render: (row) => formatCount(row.value),
        sortAccessor: (row) => row.value ?? -1,
      },
      {
        key: "overallRank",
        header: "Board rank",
        numeric: true,
        render: (row) => formatCount(row.overallRank),
        sortAccessor: (row) => row.overallRank ?? Number.MAX_SAFE_INTEGER,
      },
      {
        key: "sevenDay",
        header: "7d",
        numeric: true,
        hideBelow: "lg",
        render: (row) => <TrendCell row={row} period="sevenDay" />,
      },
      {
        key: "thirtyDay",
        header: "30d",
        numeric: true,
        render: (row) => <TrendCell row={row} period="thirtyDay" />,
      },
      {
        key: "seasonToDate",
        header: "Season",
        numeric: true,
        hideBelow: "lg",
        render: (row) => <TrendCell row={row} period="seasonToDate" />,
      },
      {
        key: "buySell",
        header: "Sharp buy/sell",
        headerInfo: "Recent Sharp Buy/Sell Tracker activity from the same cohort.",
        render: (row) => {
          const item = describeBuySell(row.buySell);
          return (
            <span
              title={item.detail || undefined}
              style={{
                color:
                  item.tone === "positive"
                    ? "var(--positive)"
                    : item.tone === "negative"
                      ? "var(--negative)"
                      : undefined,
              }}
            >
              {item.label}
            </span>
          );
        },
      },
    ];
    return base;
  }, [marketAvailable]);

  const empty = classifyEmptyState(payload);

  return (
    <main className="page">
      <PageHeader
        title={PAGE_TITLE}
        description="Which players our verified sharp managers actually roster, across every league we can observe."
      />

      <Panel title="Filters" dense>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          <Dropdown label="Position" value={position} onChange={setPosition} options={POSITIONS} />
          <Dropdown label="Platform" value={platform} onChange={setPlatform} options={PLATFORMS} />
          <Dropdown label="League format" value={format} onChange={setFormat} options={FORMATS} />
          <Dropdown
            label="Roster stance"
            value={contention}
            onChange={setContention}
            options={CONTENTION}
          />
          <Dropdown
            label="Experience"
            value={experience}
            onChange={setExperience}
            options={EXPERIENCE}
          />
          <Dropdown label="Sort by" value={sort} onChange={setSort} options={SORTS} />
          <Dropdown label="Show" value={limit} onChange={setLimit} options={LIMITS} />
        </div>
      </Panel>

      <Panel title="Sample behind these numbers" dense>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
          {tiles.map((tile) => (
            <StatTile key={tile.key} label={tile.label} value={tile.value} meta={tile.note} />
          ))}
        </div>
      </Panel>

      {sampleWarning ? (
        <Banner
          tone={sampleWarning.level === "insufficient" ? "warning" : "info"}
          title={sampleWarning.level === "insufficient" ? "Sample too small" : "Limited sample"}
        >
          {sampleWarning.message}
        </Banner>
      ) : null}

      {!marketAvailable && payload?.marketComparison?.note ? (
        <Banner tone="info" title="No market comparison available">
          {payload.marketComparison.note}
        </Banner>
      ) : null}

      {error ? (
        <Banner tone="negative" title="Could not load the board">
          {error}
        </Banner>
      ) : null}

      {loading && !payload ? (
        <LoadingState />
      ) : (
        <Panel
          title="Most rostered by sharps"
          subtitle={
            payload
              ? `${formatCount(payload.totalQualifyingPlayers)} qualifying players · updated ${formatTimestamp(payload.lastUpdated)}`
              : null
          }
        >
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.assetId}
            caption="Players ranked by the share of eligible sharp rosters that hold them."
            density="compact"
            presorted
            emptyState={
              <div>
                <strong>{empty.title}</strong>
                <p className="muted">{empty.detail}</p>
              </div>
            }
          />
          <p className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
            A high roster percentage is not a buy signal on its own. Elite players are rostered
            almost everywhere, and ownership is also shaped by league depth, format, acquisition
            cost, age and positional scarcity. Rows marked * rest on a small denominator.
          </p>
        </Panel>
      )}

      {exclusions.length ? (
        <Panel
          title="Excluded rosters"
          subtitle="Nothing is silently discarded — every excluded roster keeps its reason."
          dense
          collapsible
          collapsed
        >
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {exclusions.map((item) => (
              <li key={item.reason}>
                {item.label}: <strong>{formatCount(item.count)}</strong>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </main>
  );
}
