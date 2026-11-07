"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  players,
  stories,
  formats,
  positions,
  number,
  signed,
  selectPlayers,
  selectStories,
  tickerStories,
  csvFor,
  tradeScenarios,
} from "../lib/model";

const OPTIONS = [
  "Populated",
  "Loading",
  "Empty",
  "Unavailable",
  "Stale",
  "Missing",
];
const defaultBoard = {
  query: "",
  pos: "All",
  movement: "All",
  format: "Superflex",
  sort: "rank",
  direction: "asc",
  columns: "Research",
};
const stamp = (value) =>
  new Date(value).toLocaleString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }) + " UTC";

function Select({ label, value, onChange, options, className = "", ...props }) {
  return (
    <label className={`field ${className}`}>
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        {...props}
      >
        {options.map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
    </label>
  );
}
function Spark({ data, label, down = false }) {
  const values = data.map((p) => p.value).filter((v) => v != null);
  const min = Math.min(...values) - 30,
    range = Math.max(...values) - min + 30;
  let path = "",
    pen = false;
  const start = Date.parse(data[0].date),
    end = Date.parse(data.at(-1).date);
  data.forEach((p) => {
    if (p.value == null) {
      pen = false;
      return;
    }
    path += `${pen ? "L" : "M"}${((Date.parse(p.date) - start) / (end - start)) * 84},${30 - ((p.value - min) / range) * 25} `;
    pen = true;
  });
  return (
    <svg
      className={`spark ${down ? "negative" : ""}`}
      viewBox="0 0 84 34"
      role="img"
      aria-label={label}
    >
      <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}
function HistoryChart({ player, range, onRange }) {
  const [point, setPoint] = useState(7);
  const end = Date.parse("2026-11-07T18:00:00Z");
  const cutoff = end - Number(range.slice(0, -1)) * 86400000;
  const data = player.history.filter((p) => Date.parse(p.date) >= cutoff);
  const x = (date) => 60 + ((Date.parse(date) - cutoff) / (end - cutoff)) * 650;
  const current = Math.max(0, Math.min(point, data.length - 1));
  const values = data.map((p) => p.value).filter((v) => v != null);
  const min = Math.floor((Math.min(...values) - 150) / 250) * 250;
  const max = Math.ceil((Math.max(...values) + 150) / 250) * 250;
  let path = "",
    pen = false;
  data.forEach((p) => {
    if (p.value == null) {
      pen = false;
      return;
    }
    path += `${pen ? "L" : "M"}${x(p.date)},${220 - ((p.value - min) / (max - min)) * 180} `;
    pen = true;
  });
  const active = data[current];
  return (
    <section className="history-section" aria-label="Historical dynasty value">
      <div className="section-heading">
        <div>
          <p className="eyebrow">THE LONG VIEW</p>
          <h2>Opportunity meets conviction.</h2>
        </div>
        <div className="segmented" aria-label="History range">
          {["30D", "60D", "90D"].map((v) => (
            <button
              key={v}
              aria-pressed={range === v}
              onClick={() => {
                onRange(v);
                setPoint(7);
              }}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
      <div className="chart-readout">
        <strong>{number(active.value)}</strong>
        <span>{active.date} · Synthetic dynasty value</span>
      </div>
      <svg
        className="history-chart"
        viewBox="0 0 760 270"
        role="img"
        aria-label={`${player.name} historical value, ${range}; sample points below`}
      >
        <title>Historical dynasty value, synthetic demonstration</title>
        {[0, 1, 2, 3].map((i) => (
          <g key={i}>
            <line
              x1="60"
              x2="710"
              y1={40 + i * 60}
              y2={40 + i * 60}
              stroke="var(--rule)"
              strokeDasharray="3 5"
            />
            <text x="0" y={44 + i * 60}>
              {number(Math.round(max - (i * (max - min)) / 3))}
            </text>
          </g>
        ))}
        <path d={path} stroke="var(--coral)" strokeWidth="3" fill="none" />
        {data.map(
          (p, i) =>
            p.value != null && (
              <circle
                key={p.date}
                cx={x(p.date)}
                cy={220 - ((p.value - min) / (max - min)) * 180}
                r={i === current ? 6 : 3}
                fill={i === current ? "var(--navy)" : "var(--coral)"}
                onPointerEnter={() => setPoint(i)}
              />
            ),
        )}
        <text x="60" y="255">
          {new Date(cutoff).toISOString().slice(0, 10)}
        </text>
        <text x="710" y="255" textAnchor="end">
          2026-11-07
        </text>
      </svg>
      <label className="chart-inspector">
        Inspect history point{" "}
        <input
          type="range"
          min="0"
          max={data.length - 1}
          value={current}
          onChange={(e) => setPoint(Number(e.target.value))}
          aria-valuetext={`${active.date}, ${number(active.value)}`}
        />
      </label>
      <p className="caption">
        Value units · Gaps mean unavailable observations. No interpolation
        across missing data.
      </p>
    </section>
  );
}
function Modal({ title, children, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    const trigger = document.activeElement;
    d.showModal();
    return () => {
      d.close();
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus();
    };
  }, []);
  function keepFocus(event) {
    if (event.key !== "Tab") return;
    const targets = [
      ...ref.current.querySelectorAll(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex="0"]',
      ),
    ].filter((el) => el.getClientRects().length);
    const first = targets[0],
      last = targets.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
  return (
    <dialog
      ref={ref}
      className="drawer"
      onKeyDown={keepFocus}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      aria-labelledby="drawer-title"
    >
      <div className="drawer-head">
        <p className="eyebrow">CHASE UPSIDE / DEMONSTRATION</p>
        <button onClick={onClose} aria-label="Close dialog">
          ✕
        </button>
      </div>
      <h2 id="drawer-title">{title}</h2>
      {children}
      <button className="button dark" onClick={onClose}>
        Back to research
      </button>
    </dialog>
  );
}

export default function Experience({ screen, playerId = "demo-01" }) {
  const [board, setBoard] = useState(defaultBoard);
  const [scenario, setScenario] = useState("Populated");
  const [selected, setSelected] = useState([]);
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState(null);
  const [ticker, setTicker] = useState(0);
  const [expanded, setExpanded] = useState(null);
  const [range, setRange] = useState("90D");
  const [tab, setTab] = useState("Overview");
  const [news, setNews] = useState({
    query: "",
    team: "All",
    pos: "All",
    category: "All",
    source: "All",
    scope: "All",
  });
  const [newsView, setNewsView] = useState("Headlines");
  const [ready, setReady] = useState(false);
  const [refine, setRefine] = useState(false);
  const [newsRefine, setNewsRefine] = useState(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initial = { ...defaultBoard };
    Object.keys(initial).forEach((key) => {
      if (params.has(key)) initial[key] = params.get(key);
    });
    if (!formats.includes(initial.format)) initial.format = "Superflex";
    if (!["All", ...positions].includes(initial.pos)) initial.pos = "All";
    if (!["All", "Risers", "Fallers", "Unchanged"].includes(initial.movement))
      initial.movement = "All";
    if (
      !["rank", "name", "value", "movement", "disagreement"].includes(
        initial.sort,
      )
    )
      initial.sort = "rank";
    if (!["asc", "desc"].includes(initial.direction)) initial.direction = "asc";
    if (!["Research", "Focused"].includes(initial.columns))
      initial.columns = "Research";
    setBoard(initial);
    try {
      const ids = JSON.parse(sessionStorage.getItem("cu-demo-compare") || "[]");
      setSelected(
        Array.isArray(ids)
          ? [...new Set(ids)]
              .filter((id) => players.some((p) => p.id === id))
              .slice(0, 3)
          : [],
      );
    } catch {}
    setReady(true);
  }, []);
  useEffect(() => {
    if (ready)
      sessionStorage.setItem("cu-demo-compare", JSON.stringify(selected));
  }, [selected, ready]);
  function updateBoard(key, value) {
    const next = { ...board, [key]: value };
    setBoard(next);
    const params = new URLSearchParams();
    Object.entries(next).forEach(([k, v]) => {
      if (v !== defaultBoard[k]) params.set(k, v);
    });
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${params.size ? "?" + params : ""}`,
    );
  }
  function resetBoard() {
    setBoard(defaultBoard);
    window.history.replaceState(null, "", "/rankings");
  }
  function toggleCompare(id) {
    if (selected.includes(id)) {
      setSelected(selected.filter((x) => x !== id));
      setNotice("Player removed from comparison.");
    } else if (selected.length < 3) {
      setSelected([...selected, id]);
      setNotice("Player added to comparison.");
    } else setNotice("Compare up to three players. Remove one to add another.");
  }
  const boardPlayers = useMemo(
    () => selectPlayers({ format: board.format }),
    [board.format],
  );
  const player = boardPlayers.find((p) => p.id === playerId);
  const rows = useMemo(() => selectPlayers(board), [board]);
  const filteredNews = useMemo(() => selectStories(news), [news]);
  const tape = tickerStories();
  const story = tape[ticker % tape.length];
  const boardParams = new URLSearchParams(
    Object.entries(board).filter(([k, v]) => v !== defaultBoard[k]),
  ).toString();
  const boardHref = `/rankings${boardParams ? "?" + boardParams : ""}`;
  let returnTo = "/rankings";
  if (ready && typeof window !== "undefined") {
    const raw = new URLSearchParams(window.location.search).get("returnTo");
    if (raw && /^\/rankings(?:\?|$)/.test(raw)) returnTo = raw;
  }
  const playerHref = (p) =>
    `/players/${p.id}?returnTo=${encodeURIComponent(screen === "rankings" ? boardHref : returnTo)}&format=${encodeURIComponent(board.format)}`;
  const isUnavailable = ["Loading", "Empty", "Unavailable"].includes(scenario);
  function exportCSV() {
    const blob = new Blob([csvFor(rows, board.format)], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "chase-upside-SYNTHETIC-rankings.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice(`${rows.length} synthetic rows exported.`);
  }
  const goStory = (s) => setModal({ type: "story", story: s });
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="demo-bar">
        <span>
          <b>DESIGN STUDY 01</b> · Synthetic data & fictional players. Not live.
        </span>
        <Select
          label="Demo state"
          value={scenario}
          onChange={setScenario}
          options={OPTIONS}
        />
      </div>
      <header className="masthead">
        <a
          className="brand"
          href="/rankings"
          aria-label="Chase Upside rankings"
        >
          <span className="cu">
            CU<span>↗</span>
          </span>
          <span>
            CHASE
            <br />
            UPSIDE<span className="brand-dot">.</span>
          </span>
        </a>
        <nav aria-label="Primary">
          <a
            aria-current={screen === "rankings" ? "page" : undefined}
            href="/rankings"
          >
            Rankings
          </a>
          <a
            aria-current={screen === "player" ? "page" : undefined}
            href="/players/demo-01"
          >
            Player File
          </a>
          <a aria-current={screen === "news" ? "page" : undefined} href="/news">
            News Desk
          </a>
        </nav>
        <div className="masthead-right">
          <span className="edition">
            FOOTBALL INTELLIGENCE
            <br />
            <b>THE SATURDAY EDITION</b>
          </span>
          <button
            className="compare-nav"
            onClick={() => setModal({ type: "compare" })}
          >
            Compare <span>{selected.length}</span>
          </button>
        </div>
      </header>
      <div className="tape">
        <span className="tape-label">
          THE WIRE <span aria-hidden="true">↗</span>
        </span>
        <button className="tape-story" onClick={() => goStory(story)}>
          <span className="tape-category">
            DEMO / {story.category.toUpperCase()}
          </span>
          {story.headline}
          <span className="tape-time">{stamp(story.publishedAt)}</span>
        </button>
        <div className="tape-arrows">
          <button
            aria-label="Previous wire item"
            onClick={() => setTicker((ticker - 1 + tape.length) % tape.length)}
          >
            ←
          </button>
          <button
            aria-label="Next wire item"
            onClick={() => setTicker((ticker + 1) % tape.length)}
          >
            →
          </button>
        </div>
      </div>
      <main id="main">
        {scenario === "Stale" && (
          <div className="state-banner" role="status">
            STALE SOURCE EXAMPLE · The demo board is dated Nov 07. Rows marked
            Stale have source coverage from Nov 01; those sources are not
            current.
          </div>
        )}
        {scenario === "Missing" && (
          <div className="state-banner" role="status">
            MISSING DATA EXAMPLE · Open player{" "}
            <a href="/players/demo-05">Cameron Hayes</a> for unavailable
            projections and source disagreement; Vale&apos;s history has a
            missing observation.
          </div>
        )}
        {isUnavailable ? (
          <section className="state-panel" aria-busy={scenario === "Loading"}>
            <p className="eyebrow">{screen.toUpperCase()} / DEMO STATE</p>
            <h1>
              {scenario === "Loading"
                ? "Gathering the research."
                : scenario === "Empty"
                  ? "Nothing on the board."
                  : "The desk is unavailable."}
            </h1>
            <p>
              {scenario === "Loading"
                ? "This deliberately held loading state lets you inspect the presentation."
                : scenario === "Empty"
                  ? "No demonstration records match this scenario. Your research can start again below."
                  : "Simulated service interruption. No stale fixtures are silently substituted."}
            </p>
            <button
              className="button dark"
              onClick={() => setScenario("Populated")}
            >
              {scenario === "Unavailable"
                ? "Retry demonstration"
                : "Restore dataset"}
            </button>
          </section>
        ) : (
          <>
            {screen === "rankings" && (
              <>
                <section className="board-intro">
                  <div>
                    <p className="eyebrow">
                      THE FOOTBALL MARKET BOARD / DYNASTY
                    </p>
                    <h1>
                      KNOW THE FIELD<span className="coral">.</span>
                    </h1>
                    <p>
                      Find the player. Read the movement. Make your next move.
                    </p>
                  </div>
                  <aside>
                    <span className="snapshot-label">
                      DEMONSTRATION SNAPSHOT
                    </span>
                    <strong>
                      NOV 07 <span>/ 2026</span>
                    </strong>
                    <span>64 players · offense + IDP · 18:00 UTC</span>
                  </aside>
                </section>
                <div className="market-notes">
                  <span>
                    <b>01 / MOVING UP</b> Vale&apos;s expanded role, in focus{" "}
                    <strong className="positive">+284</strong>
                  </span>
                  <span>
                    <b>02 / THE QUESTION</b> Is opportunity becoming production?
                  </span>
                  <button onClick={() => goStory(stories[0])}>
                    Read the briefing <span>↗</span>
                  </button>
                </div>
                <section
                  className="board-workspace"
                  aria-label="Rankings research"
                >
                  <div
                    id="board-filters"
                    className={`toolbar ${refine ? "is-refined" : ""}`}
                  >
                    <label className="field search">
                      <span>Find your next edge</span>
                      <input
                        placeholder="Search player or NFL team…"
                        aria-label="Search players"
                        value={board.query}
                        onChange={(e) => updateBoard("query", e.target.value)}
                      />
                    </label>
                    <Select
                      label="League format"
                      value={board.format}
                      onChange={(v) => updateBoard("format", v)}
                      options={formats}
                    />
                    <Select
                      className="advanced-field"
                      label="Movement · 7 days"
                      value={board.movement}
                      onChange={(v) => updateBoard("movement", v)}
                      options={["All", "Risers", "Fallers", "Unchanged"]}
                    />
                    <Select
                      className="advanced-field"
                      label="Columns"
                      value={board.columns}
                      onChange={(v) => updateBoard("columns", v)}
                      options={["Research", "Focused"]}
                    />
                    <button
                      className="text-button refine-button"
                      aria-expanded={refine}
                      aria-controls="board-filters"
                      onClick={() => setRefine(!refine)}
                    >
                      {refine ? "Fewer filters −" : "More filters ＋"}
                    </button>
                    <button className="text-button" onClick={resetBoard}>
                      Reset
                    </button>
                  </div>
                  <div className="board-subbar">
                    <div
                      className="position-tabs"
                      aria-label="Position filters"
                    >
                      {["All", ...positions].map((pos) => (
                        <button
                          key={pos}
                          aria-pressed={board.pos === pos}
                          onClick={() => updateBoard("pos", pos)}
                        >
                          {pos === "All" ? "ALL PLAYERS" : pos}
                        </button>
                      ))}
                    </div>
                    <button className="text-button export" onClick={exportCSV}>
                      Export CSV ↓
                    </button>
                  </div>
                  <div className="table-meta">
                    <span>
                      <b>{rows.length}</b> PLAYERS /{" "}
                      {board.format.toUpperCase()}
                    </span>
                    <span>Value units · 7-day change · Synthetic snapshot</span>
                  </div>
                  <div
                    className={`table-scroll ${board.columns === "Focused" ? "focused" : ""}`}
                  >
                    <table className="rank-table">
                      <caption className="sr-only">
                        Synthetic dynasty player rankings. Sort columns with
                        their heading buttons.
                      </caption>
                      <thead>
                        <tr>
                          <th className="choose">
                            <span className="sr-only">Compare</span>
                          </th>
                          {[
                            ["rank", "RK"],
                            ["name", "PLAYER"],
                            ["value", "VALUE"],
                            ["movement", "7D CHANGE"],
                          ].map(([key, label]) => (
                            <th
                              key={key}
                              aria-sort={
                                board.sort === key
                                  ? board.direction === "asc"
                                    ? "ascending"
                                    : "descending"
                                  : "none"
                              }
                            >
                              <button
                                onClick={() => {
                                  const next = {
                                    ...board,
                                    sort: key,
                                    direction:
                                      board.sort === key &&
                                      board.direction === "asc"
                                        ? "desc"
                                        : "asc",
                                  };
                                  setBoard(next);
                                  const p = new URLSearchParams(
                                    Object.entries(next).filter(
                                      ([k, v]) => v !== defaultBoard[k],
                                    ),
                                  );
                                  window.history.replaceState(
                                    null,
                                    "",
                                    "/rankings?" + p,
                                  );
                                }}
                              >
                                {label}{" "}
                                <span aria-hidden="true">
                                  {board.sort === key
                                    ? board.direction === "asc"
                                      ? "↑"
                                      : "↓"
                                    : "↕"}
                                </span>
                              </button>
                            </th>
                          ))}
                          <th className="research">90D TREND</th>
                          <th
                            className="research"
                            aria-sort={
                              board.sort === "disagreement"
                                ? board.direction === "asc"
                                  ? "ascending"
                                  : "descending"
                                : "none"
                            }
                          >
                            <button
                              onClick={() => {
                                const direction =
                                  board.sort === "disagreement" &&
                                  board.direction === "asc"
                                    ? "desc"
                                    : "asc";
                                const next = {
                                  ...board,
                                  sort: "disagreement",
                                  direction,
                                };
                                setBoard(next);
                                const params = new URLSearchParams(
                                  Object.entries(next).filter(
                                    ([k, v]) => v !== defaultBoard[k],
                                  ),
                                );
                                window.history.replaceState(
                                  null,
                                  "",
                                  "/rankings?" + params,
                                );
                              }}
                            >
                              SOURCE SPREAD
                            </button>
                          </th>
                          <th className="research">FRESHNESS</th>
                          <th className="mobile-more">
                            <span className="sr-only">Details</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((p) => (
                          <RankRow
                            key={p.id}
                            player={p}
                            format={board.format}
                            selected={selected.includes(p.id)}
                            onSelect={() => toggleCompare(p.id)}
                            href={playerHref(p)}
                            expanded={expanded === p.id}
                            onExpand={() =>
                              setExpanded(expanded === p.id ? null : p.id)
                            }
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!rows.length && (
                    <div className="empty-result">
                      <h2>No players found.</h2>
                      <p>Try another name or remove a filter.</p>
                      <button className="button dark" onClick={resetBoard}>
                        Clear filters
                      </button>
                    </div>
                  )}
                  <div className="table-bottom">
                    <span>
                      END OF DEMONSTRATION BOARD · {rows.length} PLAYERS
                    </span>
                    <a href="#main">Back to top ↑</a>
                  </div>
                </section>
                <section className="research-footer">
                  <div>
                    <p className="eyebrow">LOOK BEYOND THE NUMBER</p>
                    <h2>
                      The value is a starting point.
                      <br />
                      The research is your advantage.
                    </h2>
                  </div>
                  <p>
                    This sample board separates market movement, source
                    disagreement and player context. Open a Player File to put
                    the pieces together.
                  </p>
                  <a className="button cream" href="/players/demo-01">
                    Inside the Player File ↗
                  </a>
                </section>
              </>
            )}
            {screen === "player" &&
              (!player ? (
                <section className="state-panel">
                  <h1>Player not found.</h1>
                  <p>This ID is outside the demonstration dataset.</p>
                  <a href="/rankings" className="button dark">
                    Back to rankings
                  </a>
                </section>
              ) : (
                <>
                  <div className="player-breadcrumb">
                    <a href={returnTo}>← Back to rankings</a>
                    <span>
                      PLAYER FILE / {player.pos} / {player.team}
                    </span>
                    <span>DEMO DOSSIER № {player.id.slice(-2)}</span>
                  </div>
                  <section className="player-hero">
                    <div className="player-identity">
                      <p className="eyebrow">
                        {player.team} / #{player.jersey} / {player.pos} / AGE{" "}
                        {player.age}
                      </p>
                      <h1>
                        {player.name.split(" ")[0]}
                        <br />
                        <span>{player.name.split(" ").slice(1).join(" ")}</span>
                        <span className="coral">.</span>
                      </h1>
                      <p className="player-deck">
                        The role is growing.
                        <br />
                        Now comes the next question.
                      </p>
                      <div className="hero-actions">
                        <button
                          className="button coral-button"
                          onClick={() => setModal({ type: "trade", player })}
                        >
                          Explore a trade ↗
                        </button>
                        <button
                          className="button outline"
                          aria-pressed={selected.includes(player.id)}
                          onClick={() => toggleCompare(player.id)}
                        >
                          {selected.includes(player.id)
                            ? "Remove comparison"
                            : "＋ Compare player"}
                        </button>
                      </div>
                    </div>
                    <div className="player-art">
                      <img src="/media/football-editorial.webp" alt="" />
                      <span className="image-caption">
                        GENERATED ILLUSTRATION / NOT A PLAYER PORTRAIT
                      </span>
                      <span className="jersey-outline" aria-hidden="true">
                        {player.jersey}
                      </span>
                    </div>
                    <aside className="player-value">
                      <span className="eyebrow">
                        DYNASTY VALUE / {board.format.toUpperCase()}
                      </span>
                      <strong
                        className={
                          player.values[board.format] == null
                            ? "unavailable-value"
                            : ""
                        }
                      >
                        {number(player.values[board.format])}
                      </strong>
                      <div>
                        <span
                          className={
                            player.movement < 0 ? "negative" : "positive"
                          }
                        >
                          {signed(player.movement)}
                        </span>{" "}
                        / 7 DAYS
                      </div>
                      <dl>
                        <div>
                          <dt>Overall rank</dt>
                          <dd>#{player.rank}</dd>
                        </div>
                        <div>
                          <dt>Position rank</dt>
                          <dd>
                            {player.pos}
                            {player.posRank}
                          </dd>
                        </div>
                        <div>
                          <dt>Role</dt>
                          <dd>{player.role}</dd>
                        </div>
                        <div>
                          <dt>As of</dt>
                          <dd>Nov 07 · demo</dd>
                        </div>
                      </dl>
                      <button
                        className="definition"
                        onClick={() => setModal({ type: "definition" })}
                      >
                        What does this value mean? ↗
                      </button>
                    </aside>
                  </section>
                  <div className="player-news-strip">
                    <span className="eyebrow">THE LATEST / DEMO</span>
                    <button
                      onClick={() => {
                        const report = stories.find(
                          (s) => s.playerId === player.id,
                        );
                        if (report) goStory(report);
                        else window.location.assign("/news");
                      }}
                    >
                      {stories.find((s) => s.playerId === player.id)
                        ?.headline ||
                        "No player-specific report. Browse the demonstration newsroom."}{" "}
                      <span>Read the report ↗</span>
                    </button>
                  </div>
                  <div className="player-analysis">
                    <div className="analysis-main">
                      <div
                        className="analysis-tabs"
                        role="tablist"
                        aria-label="Player research views"
                      >
                        {[
                          "Overview",
                          "Scouting",
                          "Projections",
                          "News timeline",
                        ].map((t) => (
                          <button
                            key={t}
                            role="tab"
                            id={`tab-${t.replaceAll(" ", "-")}`}
                            aria-controls="research-panel"
                            aria-selected={tab === t}
                            tabIndex={tab === t ? 0 : -1}
                            onKeyDown={(e) => {
                              if (
                                [
                                  "ArrowLeft",
                                  "ArrowRight",
                                  "Home",
                                  "End",
                                ].includes(e.key)
                              ) {
                                e.preventDefault();
                                const ts = [
                                  "Overview",
                                  "Scouting",
                                  "Projections",
                                  "News timeline",
                                ];
                                const idx =
                                  e.key === "Home"
                                    ? 0
                                    : e.key === "End"
                                      ? 3
                                      : (ts.indexOf(t) +
                                          (e.key === "ArrowRight" ? 1 : 3)) %
                                        4;
                                setTab(ts[idx]);
                                document
                                  .getElementById(
                                    `tab-${ts[idx].replaceAll(" ", "-")}`,
                                  )
                                  ?.focus();
                              }
                            }}
                            onClick={() => setTab(t)}
                          >
                            {t}
                          </button>
                        ))}
                      </div>
                      <div
                        id="research-panel"
                        role="tabpanel"
                        aria-labelledby={`tab-${tab.replaceAll(" ", "-")}`}
                        tabIndex="0"
                      >
                        {tab === "Overview" && (
                          <>
                            <HistoryChart
                              player={player}
                              range={range}
                              onRange={setRange}
                            />
                            <div className="scouting-note">
                              <p className="eyebrow">
                                THE SCOUTING NOTE / SYNTHETIC ANALYSIS
                              </p>
                              <h2>Follow the opportunity.</h2>
                              <p>
                                Volume creates the opening. Sustained
                                involvement makes the case. In this
                                demonstration, {player.name.split(" ")[0]}
                                &apos;s role is the signal to study alongside
                                the market&apos;s reaction.
                              </p>
                              <button
                                className="text-button"
                                onClick={() => setTab("Scouting")}
                              >
                                Read the full assessment ↗
                              </button>
                            </div>
                          </>
                        )}
                        {tab === "Scouting" && (
                          <section className="reading-section">
                            <p className="eyebrow">
                              DEMONSTRATION SCOUTING REPORT
                            </p>
                            <h2>A role worth investigating.</h2>
                            <p>
                              {player.role}. The sample dossier emphasizes
                              opportunity, positional context and the difference
                              between a promising observation and an established
                              trend.
                            </p>
                            <h3>What to watch</h3>
                            <ul>
                              <li>
                                Whether participation sustains over multiple
                                games.
                              </li>
                              <li>
                                How the role changes in scoring situations.
                              </li>
                              <li>
                                Whether the market already prices in the
                                improvement.
                              </li>
                            </ul>
                            <h3>What remains uncertain</h3>
                            <p>
                              Coaching usage, health and future production
                              remain uncertain. No real scouting grade,
                              prediction or recommendation is established by
                              this fixture.
                            </p>
                          </section>
                        )}
                        {tab === "Projections" && (
                          <section className="reading-section">
                            <p className="eyebrow">
                              PREDETERMINED DEMONSTRATION / PPR
                            </p>
                            <h2>Range before certainty.</h2>
                            {player.projection ? (
                              <>
                                <div className="projection">
                                  <strong>{player.projection.points}</strong>
                                  <span>sample weekly points</span>
                                </div>
                                <p>
                                  Illustrative lower / upper scenario:{" "}
                                  <b>
                                    {player.projection.low}–
                                    {player.projection.high} points
                                  </b>
                                  . These are fixed scenario examples, not
                                  calibrated probability intervals.
                                </p>
                              </>
                            ) : (
                              <p className="state-banner">
                                Projection unavailable. Missing coverage is not
                                zero production.
                              </p>
                            )}
                            <p>
                              Roster fit and league-specific production analysis
                              require the canonical backend. No live
                              recommendation is available here.
                            </p>
                          </section>
                        )}
                        {tab === "News timeline" && (
                          <section className="reading-section">
                            <p className="eyebrow">
                              PLAYER TIMELINE / DEMONSTRATION
                            </p>
                            <h2>How the story developed.</h2>
                            {stories
                              .filter((s) => s.playerId === player.id)
                              .map((s) => (
                                <StoryLine
                                  key={s.id}
                                  story={s}
                                  onOpen={() => goStory(s)}
                                />
                              ))}
                            {!stories.some((s) => s.playerId === player.id) && (
                              <p>
                                No player-specific news is available in this
                                fixture.
                              </p>
                            )}
                          </section>
                        )}
                      </div>
                    </div>
                    <aside className="peer-rail">
                      <p className="eyebrow">THE POSITIONAL PICTURE</p>
                      <h2>
                        Same position.
                        <br />
                        Different cases.
                      </h2>
                      {boardPlayers
                        .filter(
                          (p) => p.pos === player.pos && p.id !== player.id,
                        )
                        .slice(0, 4)
                        .map((p) => (
                          <div className="peer" key={p.id}>
                            <span className="peer-rank">
                              {p.pos}
                              {p.posRank}
                            </span>
                            <a href={playerHref(p)}>
                              {p.name}
                              <small>
                                {p.team} · AGE {p.age}
                              </small>
                            </a>
                            <strong>{number(p.values[board.format])}</strong>
                            <button
                              aria-label={`Compare ${p.name}`}
                              aria-pressed={selected.includes(p.id)}
                              onClick={() => toggleCompare(p.id)}
                            >
                              ＋
                            </button>
                          </div>
                        ))}
                      <div className="rail-note">
                        <p className="eyebrow">EVIDENCE / NOT CERTAINTY</p>
                        <h3>Read the disagreement.</h3>
                        <p>
                          {player.disagreement == null
                            ? "Source disagreement unavailable for this player."
                            : `The sample source rank spread is ${player.disagreement} places. It describes disagreement, not confidence or predictive accuracy.`}
                        </p>
                        <span className="freshness">
                          {player.freshness === "stale"
                            ? "◷ Stale source coverage"
                            : "✓ Sample coverage current as of demo clock"}
                        </span>
                      </div>
                    </aside>
                  </div>
                </>
              ))}
            {screen === "news" && (
              <>
                <section className="news-title">
                  <div>
                    <p className="eyebrow">
                      NFL NEWS INTELLIGENCE / SATURDAY, NOVEMBER 07
                    </p>
                    <h1>
                      THE FOOTBALL
                      <br />
                      NEWSROOM<span className="coral">.</span>
                    </h1>
                  </div>
                  <p>
                    The report.
                    <br />
                    The context.
                    <br />
                    <b>The next question.</b>
                  </p>
                </section>
                <div
                  id="news-filters"
                  className={`news-filters ${newsRefine ? "is-refined" : ""}`}
                >
                  <label className="field search">
                    <span>Search the desk</span>
                    <input
                      aria-label="Search news"
                      placeholder="Player, headline or development…"
                      value={news.query}
                      onChange={(e) =>
                        setNews({ ...news, query: e.target.value })
                      }
                    />
                  </label>
                  <Select
                    label="NFL team"
                    value={news.team}
                    onChange={(v) => setNews({ ...news, team: v })}
                    options={["All", ...new Set(players.map((p) => p.team))]}
                  />
                  <Select
                    className="advanced-field"
                    label="Position"
                    value={news.pos}
                    onChange={(v) => setNews({ ...news, pos: v })}
                    options={["All", ...positions]}
                  />
                  <Select
                    label="Coverage"
                    value={news.category}
                    onChange={(v) => setNews({ ...news, category: v })}
                    options={[
                      "All",
                      ...new Set(stories.map((s) => s.category)),
                    ]}
                  />
                  <Select
                    className="advanced-field"
                    label="Source"
                    value={news.source}
                    onChange={(v) => setNews({ ...news, source: v })}
                    options={["All", ...new Set(stories.map((s) => s.source))]}
                  />
                  <Select
                    className="advanced-field"
                    label="Relevance"
                    value={news.scope}
                    onChange={(v) => setNews({ ...news, scope: v })}
                    options={["All", "Demo roster"]}
                  />
                  <button
                    className="text-button refine-button"
                    aria-expanded={newsRefine}
                    aria-controls="news-filters"
                    onClick={() => setNewsRefine(!newsRefine)}
                  >
                    {newsRefine ? "Fewer filters −" : "Refine the desk ＋"}
                  </button>
                </div>
                <div className="news-view">
                  <div className="segmented">
                    {["Headlines", "Player timelines"].map((v) => (
                      <button
                        key={v}
                        aria-pressed={newsView === v}
                        onClick={() => setNewsView(v)}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                  <span>
                    {filteredNews.length} STORIES · FIXTURE AS OF 18:00 UTC{" "}
                    <button
                      className="text-button"
                      onClick={() => {
                        setNotice(
                          "Demonstration restored from the fixed November 7 snapshot. This is not a live refresh.",
                        );
                        setNews({
                          query: "",
                          team: "All",
                          pos: "All",
                          category: "All",
                          source: "All",
                          scope: "All",
                        });
                      }}
                    >
                      Reset desk ↻
                    </button>
                  </span>
                </div>
                {!filteredNews.length ? (
                  <section className="empty-result">
                    <h2>No matching reports.</h2>
                    <p>
                      Broaden the filters to return to the demonstration feed.
                    </p>
                  </section>
                ) : newsView === "Player timelines" ? (
                  <section className="timeline-grid">
                    {players
                      .filter((p) =>
                        filteredNews.some((s) => s.playerId === p.id),
                      )
                      .map((p) => (
                        <section key={p.id}>
                          <p className="eyebrow">
                            {p.team} / {p.pos}
                          </p>
                          <h2>
                            <a href={playerHref(p)}>{p.name} ↗</a>
                          </h2>
                          {filteredNews
                            .filter((s) => s.playerId === p.id)
                            .map((s) => (
                              <StoryLine
                                key={s.id}
                                story={s}
                                onOpen={() => goStory(s)}
                              />
                            ))}
                        </section>
                      ))}
                  </section>
                ) : (
                  <>
                    <section className="news-lead-grid">
                      <article className="lead-story">
                        <div className="lead-image">
                          <img src="/media/football-editorial.webp" alt="" />
                          <span>GENERATED DEMONSTRATION IMAGE</span>
                        </div>
                        <div className="lead-copy">
                          <p className="eyebrow">
                            THE LEAD /{" "}
                            {filteredNews[0].classification.toUpperCase()}
                          </p>
                          <button onClick={() => goStory(filteredNews[0])}>
                            <h2>{filteredNews[0].headline}</h2>
                          </button>
                          <p>{filteredNews[0].summary}</p>
                          <div className="story-meta">
                            {filteredNews[0].source} ·{" "}
                            {stamp(filteredNews[0].publishedAt)}
                          </div>
                          <button
                            className="text-button"
                            onClick={() => goStory(filteredNews[0])}
                          >
                            Read the report & context ↗
                          </button>
                        </div>
                      </article>
                      <aside className="news-priority">
                        <p className="eyebrow">THE SHORT LIST / DEMO</p>
                        <h2>
                          WHAT
                          <br />
                          MATTERS
                          <br />
                          NEXT<span>.</span>
                        </h2>
                        {filteredNews.slice(1, 4).map((s, i) => (
                          <article key={s.id}>
                            <span className="short-number">0{i + 1}</span>
                            <div>
                              <p className="eyebrow">
                                {s.category} / {s.classification}
                              </p>
                              <button onClick={() => goStory(s)}>
                                <h3>{s.headline}</h3>
                              </button>
                              <p className="story-meta">
                                {stamp(s.publishedAt)}
                              </p>
                            </div>
                          </article>
                        ))}
                      </aside>
                    </section>
                    <section className="news-lower">
                      <div>
                        <div className="section-heading">
                          <div>
                            <p className="eyebrow">AROUND THE LEAGUE</p>
                            <h2>Keep the whole field in view.</h2>
                          </div>
                          <span className="caption">
                            LATEST FIRST / DEMONSTRATION
                          </span>
                        </div>
                        {filteredNews.slice(1).map((s) => (
                          <StoryLine
                            key={s.id}
                            story={s}
                            onOpen={() => goStory(s)}
                            playerLink={playerHref(
                              players.find((p) => p.id === s.playerId),
                            )}
                          />
                        ))}
                      </div>
                      <aside className="front-office">
                        <p className="eyebrow">FROM THE FRONT OFFICE</p>
                        <h2>
                          A headline
                          <br />
                          is the start.
                          <br />
                          <span>Do the work.</span>
                        </h2>
                        <p>
                          Put the latest development beside the player&apos;s
                          value, historical movement and positional peers.
                        </p>
                        <a className="button cream" href="/players/demo-01">
                          Open the Player File ↗
                        </a>
                        <div className="news-key">
                          <h3>Know what you&apos;re reading.</h3>
                          <p>
                            <b>Official confirmation</b> · Demo team statement.
                          </p>
                          <p>
                            <b>Credible reporting</b> · Demo newsroom account.
                          </p>
                          <p>
                            <b>Unconfirmed</b> · Not established.
                          </p>
                          <p>
                            <b>Analysis</b> · Interpretation, not reporting.
                          </p>
                        </div>
                      </aside>
                    </section>
                  </>
                )}
              </>
            )}
          </>
        )}
      </main>
      <footer className="site-footer">
        <a className="footer-wordmark" href="/rankings">
          CHASE UPSIDE<span>↗</span>
        </a>
        <p>FOOTBALL INTELLIGENCE. WITH PERSPECTIVE.</p>
        <span>ISOLATED DESIGN STUDY / NO LIVE DATA / NOV 2026</span>
      </footer>
      {selected.length > 0 && (
        <div className="compare-tray">
          <span>
            <b>{selected.length}/3</b> PLAYERS SELECTED
          </span>
          <span className="selected-names">
            {selected
              .map((id) => players.find((p) => p.id === id)?.name)
              .join(" / ")}
          </span>
          <button
            className="button coral-button"
            onClick={() => setModal({ type: "compare" })}
          >
            Compare players ↗
          </button>
          <button aria-label="Clear comparison" onClick={() => setSelected([])}>
            ✕
          </button>
        </div>
      )}
      <div className="sr-only" role="status" aria-live="polite">
        {notice}
      </div>
      {notice && (
        <div className="toast">
          <span>{notice}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            ✕
          </button>
        </div>
      )}
      {modal && (
        <Modal
          title={
            modal.type === "compare"
              ? "The side-by-side."
              : modal.type === "trade"
                ? "Take it to the Trade Desk."
                : modal.type === "definition"
                  ? "Read the value in context."
                  : modal.story.headline
          }
          onClose={() => setModal(null)}
        >
          {modal.type === "compare" && (
            <>
              {!selected.length ? (
                <p>
                  Select up to three players using the checkboxes on the
                  Rankings board or the Compare player button in a dossier.
                </p>
              ) : (
                <div className="comparison-grid">
                  {selected.map((id) => {
                    const p = boardPlayers.find((p) => p.id === id);
                    return (
                      <section key={id}>
                        <p className="eyebrow">
                          {p.team} / {p.pos}
                          {p.posRank}
                        </p>
                        <h3>
                          <a href={playerHref(p)}>{p.name} ↗</a>
                        </h3>
                        <strong className="compare-value">
                          {number(p.values[board.format])}
                        </strong>
                        <p>{signed(p.movement)} / 7 days</p>
                        <Spark
                          data={p.history}
                          label={`${p.name} 90 day trend`}
                        />
                        <p>
                          Source spread:{" "}
                          {p.disagreement == null
                            ? "Unavailable"
                            : `${p.disagreement} places`}
                        </p>
                        <button
                          className="text-button"
                          onClick={() => toggleCompare(id)}
                        >
                          Remove
                        </button>
                      </section>
                    );
                  })}
                </div>
              )}
              <p className="caption">
                Synthetic {board.format} snapshot. Comparisons do not produce a
                trade verdict.
              </p>
            </>
          )}
          {modal.type === "trade" && (
            <>
              <p className="eyebrow">SIMULATED HANDOFF / NO BACKEND REQUEST</p>
              <h3>
                {tradeScenarios[modal.player.id]?.title ||
                  "Analysis unavailable for this fixture."}
              </h3>
              <p>
                {tradeScenarios[modal.player.id]?.text ||
                  "This player can be selected for a future Trade Desk request. No package analysis, fairness result or roster recommendation exists in this isolated study."}
              </p>
              <p>
                Selected player: <b>{modal.player.name}</b> · {board.format}
              </p>
            </>
          )}
          {modal.type === "definition" && (
            <>
              <p>
                Dynasty value is a relative research measure. Every value here
                is predetermined synthetic fixture data, not a live market price
                or a new valuation formula.
              </p>
              <p>
                Rank is the board&apos;s stated ordinal. Source spread describes
                disagreement in rank places. Neither establishes predictive
                confidence. Missing observations remain unavailable.
              </p>
            </>
          )}
          {modal.type === "story" && (
            <article className="story-reading">
              <p className="eyebrow">
                SYNTHETIC STORY / {modal.story.classification.toUpperCase()}
              </p>
              <p className="story-meta">
                {modal.story.source} · Published{" "}
                {stamp(modal.story.publishedAt)}
                {modal.story.stale ? " · STALE" : ""}
              </p>
              {modal.story.body.split("\n\n").map((p, i) => (
                <p key={i}>{p}</p>
              ))}
              <div className="source-detail">
                <h3>Source & reporting status</h3>
                <p>
                  {modal.story.source} is a fictional demonstration source. This
                  item has no real reporter attribution or external original
                  report. Its confirmation class illustrates presentation only.
                </p>
                <p>
                  <b>Fantasy implication:</b> A role change prompts further
                  research; it is not an instruction to trade.
                </p>
              </div>
              <a
                className="button dark"
                href={playerHref(
                  players.find((p) => p.id === modal.story.playerId),
                )}
              >
                Open Player File ↗
              </a>
            </article>
          )}
        </Modal>
      )}
    </>
  );
}

function RankRow({
  player: p,
  format,
  selected,
  onSelect,
  href,
  expanded,
  onExpand,
}) {
  return (
    <>
      <tr className={selected ? "selected-row" : ""}>
        <td className="choose">
          <label className="compare-check">
            <input
              type="checkbox"
              checked={selected}
              onChange={onSelect}
              aria-label={`Compare ${p.name}`}
            />
          </label>
        </td>
        <td className="rank-number">{String(p.rank).padStart(2, "0")}</td>
        <td>
          <a className="player-cell" href={href}>
            <span className="player-monogram" aria-hidden="true">
              {p.name
                .split(" ")
                .map((n) => n[0])
                .join("")}
            </span>
            <span>
              <b>{p.name}</b>
              <small>
                {p.team} <span>/</span> {p.pos}
                {p.posRank} <span>/</span> AGE {p.age}
              </small>
            </span>
          </a>
        </td>
        <td
          className={`value-cell ${p.values[format] == null ? "unavailable-value" : ""}`}
        >
          {number(p.values[format])}
        </td>
        <td
          className={`movement-cell ${p.movement < 0 ? "negative" : p.movement > 0 ? "positive" : ""}`}
        >
          <span aria-hidden="true">
            {p.movement > 0 ? "↗" : p.movement < 0 ? "↘" : "—"}
          </span>{" "}
          {signed(p.movement)}
        </td>
        <td className="research">
          <Spark
            data={p.history}
            label={`${p.name}: synthetic 90-day value trend`}
            down={p.movement < 0}
          />
        </td>
        <td className="research spread">
          {p.disagreement == null ? (
            <span className="muted">Unavailable</span>
          ) : (
            <>
              <span
                className="spread-line"
                style={{ width: `${p.disagreement * 2 + 12}px` }}
              />
              {p.disagreement} <small>places</small>
            </>
          )}
        </td>
        <td className="research freshness">
          {p.freshness === "stale" ? "◷ Nov 01 · stale" : "✓ Nov 07"}
        </td>
        <td className="mobile-more">
          <button
            onClick={onExpand}
            aria-label={`Details for ${p.name}`}
            aria-expanded={expanded}
          >
            {expanded ? "−" : "＋"}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="mobile-detail">
          <td colSpan="9">
            <b>{p.name}</b> · {p.role}
            <br />
            Source spread:{" "}
            {p.disagreement == null
              ? "Unavailable"
              : `${p.disagreement} rank places`}{" "}
            ·{" "}
            {p.freshness === "stale"
              ? "Stale coverage"
              : "Demo snapshot Nov 07"}
            <br />
            <a href={href}>Open full Player File ↗</a>
          </td>
        </tr>
      )}
    </>
  );
}
function StoryLine({ story: s, onOpen, playerLink }) {
  return (
    <article className="story-line">
      <time dateTime={s.publishedAt}>
        {new Date(s.publishedAt).toLocaleTimeString("en-US", {
          timeZone: "UTC",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        })}
        <span>UTC / NOV {s.publishedAt.slice(8, 10)}</span>
      </time>
      <div>
        <p className="eyebrow">
          {s.category} / {s.classification}
          {s.stale ? " / STALE" : ""}
        </p>
        <button onClick={onOpen}>
          <h3>{s.headline}</h3>
        </button>
        <p>{s.summary}</p>
        <span className="story-meta">{s.source}</span>
        {playerLink && (
          <a className="story-player" href={playerLink}>
            Player File ↗
          </a>
        )}
      </div>
      <button
        className="story-arrow"
        aria-label={`Read ${s.headline}`}
        onClick={onOpen}
      >
        ↗
      </button>
    </article>
  );
}
