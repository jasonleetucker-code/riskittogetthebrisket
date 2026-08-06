"use client";

/**
 * CommandPalette — universal search (R1). Succeeds GlobalSearch.
 *
 * One keyboard-first surface for everything findable:
 *   • Players & picks — the EXACT legacy semantics preserved:
 *     lib/player-filters matchesQuery grammar (free text, "wr chi",
 *     owner:/team:/pos: tokens via the teamByPlayer index) with the
 *     same prefix→substring→other name-rank tiering.
 *   • Navigation — every destination from lib/nav-model paletteTargets()
 *     (pages, tools, tabs), matched on label/group/keywords. Skipped
 *     when the query uses filter tokens (":") — that is always a
 *     player search.
 *
 * Opened by "/" or Cmd/Ctrl+K (wired in AppShell). Players list first
 * (dominant use — type a name, Enter opens the popup), then "Go to".
 * With an empty query the palette shows top destinations, so it also
 * works as pure navigation.
 *
 * A11y (fixes the audit's plain-button results): the input is a
 * combobox with aria-activedescendant; results are a real listbox of
 * options; built on ds Modal so focus trap/restore and the overlay
 * stack come for free.
 *
 * Props (superset of GlobalSearch's contract):
 *   rows, sleeperTeams, isOpen, onClose, onSelect(row)
 *
 * ⚠ `sleeperTeams` — the RAW team array — not the prebuilt
 * `{byId, byName}` index it used to take. The index is built HERE.
 *
 * That is a bundle boundary, not a style preference. `buildTeamByPlayer`
 * lives in `lib/waiver-logic.js` (33.9 KB of source), and AppShell — the
 * ROOT LAYOUT — imported it solely to build this prop. So the whole
 * waiver module landed in the chunk every route downloads (measured:
 * chunk 2910, 12.0 KB raw / 4.5 KB gz, in the always-loaded intersection
 * of all 35 routes) to serve a palette that is itself lazily loaded and
 * only reachable after "/" or Cmd+K.
 *
 * Building the index inside the lazy component moves that import behind
 * the same gate as the component. Precedent: `PlayerPopup.jsx:7,680`
 * already imports `buildTeamByPlayer` itself for the same reason.
 *
 * Keep it this way. Hoisting the memo back into a caller re-attaches
 * waiver-logic to whatever chunk that caller sits in.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon, Modal } from "@/components/ds";
import { resolvedRank } from "@/lib/dynasty-data";
import { matchesQuery } from "@/lib/player-filters";
import { paletteTargets } from "@/lib/nav-model";
import { buildTeamByPlayer } from "@/lib/waiver-logic";

const MAX_PLAYERS = 12;
const MAX_NAV = 6;
const EMPTY_QUERY_NAV = 8;

function matchNavTargets(query) {
  const q = query.trim().toLowerCase();
  const targets = paletteTargets();
  if (!q) return targets.slice(0, EMPTY_QUERY_NAV);
  // token grammar (pos:/owner:/team:) is always a player search
  if (q.includes(":")) return [];
  return targets
    .filter((t) => {
      const hay = [t.label, t.group, t.hint, ...(t.keywords || [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    })
    .slice(0, MAX_NAV);
}

export default function CommandPalette({
  rows = [],
  sleeperTeams = null,
  isOpen,
  onClose,
  onSelect,
}) {
  const router = useRouter();

  // League-scoped ownership index for the `owner:` / `team:` tokens.
  // Rows are scoring-profile-scoped and never carry the owner, so the
  // join happens at render time (CLAUDE.md's scoringProfile/leagueKey
  // split). Built here rather than passed in — see the header.
  const teamByPlayer = useMemo(
    () => (sleeperTeams ? buildTeamByPlayer(sleeperTeams) : null),
    [sleeperTeams],
  );
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIdx(0);
    }
  }, [isOpen]);

  const q = query.trim();

  // Players — legacy semantics preserved verbatim (grammar + tiering).
  const playerResults = useMemo(() => {
    if (q.length === 0) return [];
    const extras = { teamByPlayer };
    const ql = q.toLowerCase();
    const matched = [];
    for (const r of rows) {
      if (!matchesQuery(r, q, extras)) continue;
      const name = String(r.name || "").toLowerCase();
      const tier = name.startsWith(ql) ? 0 : name.includes(ql) ? 1 : 2;
      matched.push([tier, matched.length, r]);
    }
    matched.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    return matched.slice(0, MAX_PLAYERS).map((m) => m[2]);
  }, [rows, q, teamByPlayer]);

  const navResults = useMemo(() => matchNavTargets(q), [q]);

  // Flat option list: players first (dominant use), then navigation.
  const options = useMemo(
    () => [
      ...playerResults.map((row) => ({ kind: "player", row })),
      ...navResults.map((item) => ({ kind: "nav", item })),
    ],
    [playerResults, navResults]
  );

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  const activate = useCallback(
    (option) => {
      if (!option) return;
      if (option.kind === "player") {
        onSelect?.(option.row);
      } else {
        router.push(option.item.href);
      }
      onClose?.();
    },
    [onSelect, onClose, router]
  );

  const onKeyDown = useCallback(
    (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.min(prev + 1, options.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        activate(options[selectedIdx]);
      }
      // Escape is handled by the ds Modal (topmost-overlay semantics).
    },
    [options, selectedIdx, activate]
  );

  useEffect(() => {
    const el = listRef.current?.querySelector('[aria-selected="true"]');
    el?.scrollIntoView?.({ block: "nearest" });
  }, [selectedIdx]);

  const listboxId = "shell-palette-listbox";
  const activeId =
    options.length > 0 ? `shell-palette-opt-${selectedIdx}` : undefined;
  const playerCount = playerResults.length;

  return (
    <Modal
      open={Boolean(isOpen)}
      onClose={onClose}
      title="Search"
      srOnlyTitle
      initialFocus={inputRef}
    >
      <div className="shell-palette-input-row">
        <Icon name="search" size={16} />
        <input
          ref={inputRef}
          className="ds-input"
          type="text"
          role="combobox"
          aria-expanded={options.length > 0}
          aria-controls={listboxId}
          aria-activedescendant={activeId}
          aria-label="Search players, picks, and pages"
          placeholder="Search players, picks, pages… (owner: team: pos:)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
      </div>

      <div
        ref={listRef}
        id={listboxId}
        role="listbox"
        aria-label="Search results"
        className="shell-palette-list"
      >
        {playerCount > 0 && (
          <div className="shell-palette-section" role="presentation">
            Players &amp; picks
          </div>
        )}
        {playerResults.map((r, i) => {
          const rank = resolvedRank(r);
          const selected = i === selectedIdx;
          return (
            <button
              key={`p-${r.name}`}
              id={`shell-palette-opt-${i}`}
              type="button"
              role="option"
              aria-selected={selected}
              className="shell-palette-option"
              onClick={() => activate({ kind: "player", row: r })}
              onMouseEnter={() => setSelectedIdx(i)}
              tabIndex={-1}
            >
              <span className="shell-palette-option-body">
                <span className="shell-palette-option-name">{r.name}</span>
                <span className="shell-palette-option-meta">
                  {r.pos}
                  {r.raw?.team ? ` · ${r.raw.team}` : ""}
                  {rank < Infinity ? ` · #${rank}` : ""}
                </span>
              </span>
              <span className="shell-palette-option-value">
                {Math.round(r.values?.full || 0).toLocaleString()}
              </span>
            </button>
          );
        })}

        {navResults.length > 0 && (
          <div className="shell-palette-section" role="presentation">
            Go to
          </div>
        )}
        {navResults.map((item, j) => {
          const i = playerCount + j;
          const selected = i === selectedIdx;
          return (
            <button
              key={`n-${item.href}`}
              id={`shell-palette-opt-${i}`}
              type="button"
              role="option"
              aria-selected={selected}
              className="shell-palette-option"
              onClick={() => activate({ kind: "nav", item })}
              onMouseEnter={() => setSelectedIdx(i)}
              tabIndex={-1}
            >
              <Icon name="arrow-right" size={12} />
              <span className="shell-palette-option-body">
                <span className="shell-palette-option-name">{item.label}</span>
                <span className="shell-palette-option-meta">
                  {item.group ? `${item.group} · ` : ""}
                  {item.hint || item.href}
                </span>
              </span>
            </button>
          );
        })}

        {q.length > 0 && options.length === 0 && (
          <div className="shell-palette-empty">
            No results for &ldquo;{query}&rdquo;
          </div>
        )}
      </div>

      {q.length === 0 && (
        <div className="shell-palette-hints">
          Players: <code>wr chi</code> · <code>owner:jason rb</code> ·{" "}
          <code>pos:te team:kc</code>
          <br />
          <span className="shell-kbd">↑</span>{" "}
          <span className="shell-kbd">↓</span> navigate ·{" "}
          <span className="shell-kbd">Enter</span> select ·{" "}
          <span className="shell-kbd">Esc</span> close
        </div>
      )}
    </Modal>
  );
}
