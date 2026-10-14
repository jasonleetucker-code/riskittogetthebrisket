"use client";

/**
 * /market/trade-database — the dynasty trade database (C3-CALC-01 / TC-08).
 *
 * Browse and filter recorded real dynasty trades from the canonical
 * underlying-trade ledger (GET /api/market/trades/database).  Rows are the
 * same projection the /trade "Recent real trades" panel renders, through the
 * same TradeRow, so the two surfaces cannot describe a trade differently.
 *
 * Facts only: nothing is valued or graded here.  A format filter hides rows
 * whose fact is unknown and the page SAYS how many — "no 12-team trades" and
 * "these trades' team count is not recorded" never read the same.
 *
 * Player filters resolve a board name to its Sleeper id from the loaded
 * board; a name two players share is left out of the picker rather than
 * guessed (identity is never resolved from an ambiguous name).  Deep links:
 * ?players=<ids>&picks=<board pick rows> pre-fill the asset filter.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { useDynastyData } from "@/components/useDynastyData";
import { useTeam } from "@/components/useTeam";
import { TradeRow } from "@/components/trade/RecentRealTrades";
import {
  databaseQueryString,
  excludedUnknownText,
  referenceFailureKind,
  uniquePlayerIndex,
  withheldText,
} from "@/lib/recent-real-trades";
import styles from "./trade-database.module.css";

const PAGE_SIZE = 25;

const EMPTY_FILTERS = {
  since: "",
  until: "",
  superflex: "any",
  teams: "",
  idp: "any",
  teScoringEdge: "any",
  ktcTepLevel: "any",
  source: "any",
  shape: "",
  assetMix: "any",
};

const YES_NO = [
  { value: "any", label: "Any" },
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
];

function initialFromUrl() {
  if (typeof window === "undefined") return { players: [], picks: [], filters: EMPTY_FILTERS };
  const sp = new URLSearchParams(window.location.search);
  const list = (k) =>
    (sp.get(k) || "")
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  const filters = { ...EMPTY_FILTERS };
  for (const key of Object.keys(EMPTY_FILTERS)) {
    if (sp.get(key)) filters[key] = sp.get(key);
  }
  return { players: list("players"), picks: list("picks"), filters };
}

export default function TradeDatabasePage() {
  const { rows } = useDynastyData();
  const { selectedLeagueKey } = useTeam();
  const playerIndex = useMemo(() => uniquePlayerIndex(rows), [rows]);
  const nameById = useMemo(() => {
    const m = new Map();
    for (const [name, id] of playerIndex) m.set(id, name);
    return m;
  }, [playerIndex]);
  const pickNames = useMemo(
    () =>
      (rows || [])
        .filter((r) => r && (r.assetClass === "pick" || r.pos === "PICK") && r.name)
        .map((r) => String(r.name)),
    [rows],
  );

  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [players, setPlayers] = useState([]);
  const [picks, setPicks] = useState([]);
  const [assetText, setAssetText] = useState("");
  const [assetNote, setAssetNote] = useState(null);
  const [applied, setApplied] = useState(null);
  // Cursor paging: `cursors` is the stack of page starts (null = newest).
  const [cursors, setCursors] = useState([null]);
  const cursor = cursors[cursors.length - 1];
  const [state, setState] = useState({ status: "idle", body: null });
  const seq = useRef(0);

  useEffect(() => {
    const init = initialFromUrl();
    setDraft(init.filters);
    setPlayers(init.players);
    setPicks(init.picks);
    setApplied({ filters: init.filters, players: init.players, picks: init.picks });
  }, []);

  const qs = useMemo(() => {
    if (!applied) return null;
    return databaseQueryString(
      {
        ...applied.filters,
        players: applied.players.join(","),
        picks: applied.picks.join(","),
        limit: PAGE_SIZE,
        beforeDate: cursor?.beforeDate || "",
        skip: cursor ? cursor.skip : "",
      },
      selectedLeagueKey || "",
    );
  }, [applied, cursor, selectedLeagueKey]);

  const load = useCallback(async (query) => {
    const mine = ++seq.current;
    setState((s) => ({ ...s, status: "loading" }));
    try {
      const res = await fetch(`/api/market/trades/database?${query}`, {
        credentials: "same-origin",
      });
      const body = await res.json().catch(() => null);
      if (mine !== seq.current) return;
      if (res.ok && body?.state === "no_assets") {
        setState({ status: "no_assets", body });
      } else if (!res.ok || !body || body.state !== "ok") {
        setState({ status: res.ok ? "unavailable" : referenceFailureKind(res.status), body });
      } else {
        setState({ status: "ok", body });
      }
    } catch {
      if (mine === seq.current) setState({ status: "unavailable", body: null });
    }
  }, []);

  useEffect(() => {
    if (qs !== null) void load(qs);
  }, [qs, load]);

  // A cursor names a position in one league's view; a league switch starts over.
  useEffect(() => {
    setCursors([null]);
  }, [selectedLeagueKey]);

  function addAsset() {
    const text = assetText.trim();
    if (!text) return;
    if (playerIndex.has(text)) {
      const id = playerIndex.get(text);
      setPlayers((p) => (p.includes(id) ? p : [...p, id]));
      setAssetNote(null);
    } else if (pickNames.includes(text)) {
      setPicks((p) => (p.includes(text) ? p : [...p, text]));
      setAssetNote(null);
    } else {
      setAssetNote(
        "Not found on the board, or a name two players share — pick an entry from the list.",
      );
      return;
    }
    setAssetText("");
  }

  function writeUrl(next) {
    // Keep the address a deep link to what is on screen.
    if (typeof window === "undefined" || !window.history?.replaceState) return;
    const qsNext = databaseQueryString({
      ...next.filters,
      players: next.players.join(","),
      picks: next.picks.join(","),
    });
    window.history.replaceState(null, "", qsNext ? `?${qsNext}` : window.location.pathname);
  }

  function apply(e) {
    e?.preventDefault?.();
    const next = { filters: draft, players, picks };
    setCursors([null]);
    setApplied(next);
    writeUrl(next);
  }

  function reset() {
    const next = { filters: EMPTY_FILTERS, players: [], picks: [] };
    setDraft(EMPTY_FILTERS);
    setPlayers([]);
    setPicks([]);
    setCursors([null]);
    setApplied(next);
    writeUrl(next);
  }

  const set = (key) => (e) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  const body = state.body;
  const trades = body?.trades || [];

  return (
    <div className={`${styles.page} psi-editorial`}>
      <PageHeader
        title="Trade Database"
        description="Recorded real dynasty trades, filterable by asset, date and league format. Facts only — nothing here is valued or graded."
      />
      <Panel title="Filters">
        <form className={styles.filters} onSubmit={apply}>
          <div className={styles.assetRow}>
            <Field label="Player or pick">
              <Input
                list="trade-db-assets"
                value={assetText}
                onChange={(e) => setAssetText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addAsset();
                  }
                }}
                placeholder="Search the board"
              />
            </Field>
            <datalist id="trade-db-assets">
              {[...playerIndex.keys(), ...pickNames].map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
            <Button type="button" variant="secondary" onClick={addAsset}>
              Add
            </Button>
          </div>
          {assetNote ? <p className={styles.note}>{assetNote}</p> : null}
          {players.length || picks.length ? (
            <ul className={styles.chips} aria-label="Asset filter">
              {players.map((id) => (
                <li key={`p-${id}`}>
                  <button
                    type="button"
                    className={styles.chip}
                    onClick={() => setPlayers((p) => p.filter((x) => x !== id))}
                    aria-label={`Remove ${nameById.get(id) || `player ${id}`}`}
                  >
                    {nameById.get(id) || `Player ${id}`} ×
                  </button>
                </li>
              ))}
              {picks.map((n) => (
                <li key={`k-${n}`}>
                  <button
                    type="button"
                    className={styles.chip}
                    onClick={() => setPicks((p) => p.filter((x) => x !== n))}
                    aria-label={`Remove ${n}`}
                  >
                    {n} ×
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className={styles.grid}>
            <Field label="From">
              <Input type="date" value={draft.since} onChange={set("since")} />
            </Field>
            <Field label="To">
              <Input type="date" value={draft.until} onChange={set("until")} />
            </Field>
            <Field label="QB format">
              <Select
                value={draft.superflex}
                onChange={set("superflex")}
                options={[
                  { value: "any", label: "Any" },
                  { value: "true", label: "Superflex" },
                  { value: "false", label: "1QB" },
                ]}
              />
            </Field>
            <Field label="Teams">
              <Input
                type="number"
                min="1"
                max="64"
                inputMode="numeric"
                value={draft.teams}
                onChange={set("teams")}
                placeholder="Any"
              />
            </Field>
            <Field label="IDP">
              <Select value={draft.idp} onChange={set("idp")} options={YES_NO} />
            </Field>
            <Field label="TE scoring premium">
              <Select value={draft.teScoringEdge} onChange={set("teScoringEdge")} options={YES_NO} />
            </Field>
            <Field label="KTC TEP setting">
              <Select
                value={draft.ktcTepLevel}
                onChange={set("ktcTepLevel")}
                options={[
                  { value: "any", label: "Any" },
                  { value: "0", label: "No TEP" },
                  { value: "1", label: "TE+" },
                  { value: "2", label: "TE++" },
                  { value: "3", label: "TE+++" },
                ]}
              />
            </Field>
            <Field label="Source">
              <Select
                value={draft.source}
                onChange={set("source")}
                options={[
                  { value: "any", label: "Any" },
                  { value: "ktc_trade_database", label: "KTC trade database" },
                  { value: "sleeper_sharp_discovery", label: "Sharp-discovered Sleeper" },
                  { value: "own_league_sleeper", label: "This league" },
                ]}
              />
            </Field>
            <Field label="Shape" hint="Assets per side, e.g. 2x1">
              <Input value={draft.shape} onChange={set("shape")} placeholder="Any" />
            </Field>
            <Field label="Assets">
              <Select
                value={draft.assetMix}
                onChange={set("assetMix")}
                options={[
                  { value: "any", label: "Any" },
                  { value: "players", label: "Players only" },
                  { value: "picks", label: "Picks only" },
                  { value: "mixed", label: "Players and picks" },
                ]}
              />
            </Field>
          </div>
          <div className={styles.actions}>
            <Button type="submit" variant="primary">
              Apply filters
            </Button>
            <Button type="button" variant="ghost" onClick={reset}>
              Reset
            </Button>
          </div>
        </form>
      </Panel>

      <Panel title="Trades">
        <Results
          state={state}
          trades={trades}
          page={cursors.length}
          onNewer={() => setCursors((c) => (c.length > 1 ? c.slice(0, -1) : c))}
          onOlder={(next) => setCursors((c) => [...c, next])}
        />
      </Panel>
    </div>
  );
}

function Results({ state, trades, page, onNewer, onOlder }) {
  const body = state.body;
  if (state.status === "idle" || state.status === "loading") {
    return (
      <div aria-busy="true" aria-label="Loading trades">
        <SkeletonTable rows={5} columns={3} />
      </div>
    );
  }
  if (state.status === "auth") {
    return (
      <Banner tone="warning" title="Sign in to see real trades">
        Recorded trades are only shown to signed-in members.
      </Banner>
    );
  }
  if (state.status === "request_error") {
    return (
      <Banner tone="warning" title="Filter not understood">
        {body?.message || "The server rejected these filters."} No trades were searched.
      </Banner>
    );
  }
  if (state.status === "no_assets") {
    return (
      <Banner tone="info" title="These assets could not be identified">
        None of the selected assets matched a recorded identity, so the ledger was not searched.
      </Banner>
    );
  }
  if (state.status === "unavailable") {
    return (
      <Banner tone="info" title="Trade database unavailable">
        The recorded-trade ledger could not be read on the server. This is missing evidence, not
        a sign that no trades happened.
      </Banner>
    );
  }
  const ledger = body.ledger || {};
  const excluded = excludedUnknownText(body.excludedUnknown);
  const notApplicable = body.excludedNotApplicable?.ktcTepLevel
    ? `${body.excludedNotApplicable.ktcTepLevel} non-KTC trades hidden: the KTC TEP setting does not apply to them.`
    : null;
  const withheld = withheldText(body.withheld);
  return (
    <div className={styles.results}>
      <p className={styles.note}>
        Verified-dynasty trades from {body.filters?.since}
        {body.filters?.until ? ` to ${body.filters.until}` : ""}
        {ledger.builtAt ? `; ledger rebuilt ${String(ledger.builtAt).slice(0, 10)}` : ""}.
        {(body.notes || []).some((n) => n.startsWith("since_clamped"))
          ? ` The database reaches back ${Math.round(body.maxLookbackDays / 365)} years; the start date was moved to fit.`
          : ""}
      </p>
      {trades.length === 0 ? (
        <EmptyState
          title={body.scanCapped ? "Search stopped before finishing" : "No matching trades"}
          description={
            body.scanCapped
              ? "This page reached the search limit before finding a match. Older trades have not been checked yet."
              : "No recorded trade matches these filters."
          }
        />
      ) : (
        <ol className={styles.list}>
          {trades.map((t) => (
            <TradeRow key={t.id} trade={t} />
          ))}
        </ol>
      )}
      {excluded ? <p className={styles.note}>{excluded}</p> : null}
      {notApplicable ? <p className={styles.note}>{notApplicable}</p> : null}
      {withheld ? <p className={styles.note}>{withheld}</p> : null}
      {body.scanCapped ? (
        <p className={styles.note}>
          This page stopped at the search limit; use Older to keep searching further back.
        </p>
      ) : null}
      <div className={styles.pager}>
        <Button type="button" variant="secondary" disabled={page <= 1} onClick={onNewer}>
          Newer
        </Button>
        <span className={styles.note}>{`Page ${page}`}</span>
        <Button
          type="button"
          variant="secondary"
          disabled={!body.hasMore || !body.nextCursor}
          onClick={() => onOlder(body.nextCursor)}
        >
          Older
        </Button>
      </div>
      <details className={styles.about}>
        <summary>About this sample</summary>
        <ul>
          {(body.samplingBiases || []).map((b) => (
            <li key={b}>{b}</li>
          ))}
          {Object.values(body.notSupported || {}).map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
