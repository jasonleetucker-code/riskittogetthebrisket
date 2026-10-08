"use client";

/**
 * TradeProtectionsEditor — persistent personal trade protections (C3-CON-02).
 *
 * Edits ``tradeConstraintsByLeague[leagueKey]`` through
 * ``GET/PUT /api/user/trade-protections``.  The backend constraint owner
 * (``src/trade/constraints.py``) decides what is valid and what it means;
 * this component only collects names/teams and renders the server's answer.
 * It does not decide who is protected — no local matching, no local team
 * vocabulary (the NFL-team options come from the server, read off the same
 * board the rule is later matched against).
 *
 * Semantics shown to the user, per the spec (§2.2): protection applies to the
 * OUTGOING side of generated trade ideas only, in THIS league only.  Players
 * keep their value, stay valid incoming targets, and the manual calculator is
 * unaffected.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Banner, Button, Field, Input, Select } from "@/components/ds";
import styles from "./trade-protections.module.css";

const ENDPOINT = "/api/user/trade-protections";

const REASON_TEXT = {
  unknown_player: "is not a player on the current board",
  not_a_player: "is a draft pick, not a player",
  unknown_nfl_team: "is not an NFL team code on the current board",
  not_a_string: "is not a valid entry",
  too_many: "too many entries",
};

function key(value) {
  return String(value || "").trim().toLowerCase();
}

export function describeSaveError(body, status) {
  if (status === 503) return "No board is loaded right now, so protections can't be checked. Try again shortly.";
  if (status === 401) return "Sign in again to save protections.";
  if (status === 403) return body?.message || "This session cannot save trade protections.";
  const errors = Array.isArray(body?.errors) ? body.errors : [];
  if (errors.length) {
    const text = errors
      .map((e) => {
        const what = REASON_TEXT[e?.reason] || "was rejected";
        if (e?.reason === "too_many") {
          return e?.field === "nflTeams" ? "too many NFL teams (limit 40)" : "too many protected players (limit 100)";
        }
        return `"${e?.value}" ${what}`;
      })
      .join("; ");
    const more = Number(body?.errorsTruncated) || 0;
    return more > 0 ? `${text}; and ${more} more` : text;
  }
  return body?.message || body?.error || `Save failed (${status}).`;
}

export default function TradeProtectionsEditor({ enabled, leagueKey, leagueName, players }) {
  const [saved, setSaved] = useState(null); // last server answer
  const [untouchables, setUntouchables] = useState([]);
  const [nflTeams, setNflTeams] = useState([]);
  const [playerDraft, setPlayerDraft] = useState("");
  const [teamDraft, setTeamDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [status, setStatus] = useState("");
  // The league the editor is showing NOW.  A save started for league A must
  // not paint its answer over league B if the user switched mid-request.
  const currentLeague = useRef(leagueKey);
  currentLeague.current = leagueKey;

  const applyServer = useCallback((body) => {
    setSaved(body);
    setUntouchables(Array.isArray(body?.untouchables) ? body.untouchables : []);
    setNflTeams(Array.isArray(body?.nflTeams) ? body.nflTeams : []);
  }, []);

  useEffect(() => {
    if (!enabled || !leagueKey) return undefined;
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    setSaveError("");
    setStatus("");
    (async () => {
      try {
        const res = await fetch(`${ENDPOINT}?leagueKey=${encodeURIComponent(leagueKey)}`, {
          credentials: "include",
          cache: "no-store",
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body?.message || body?.error || `load_${res.status}`);
        if (!cancelled) applyServer(body);
      } catch (exc) {
        if (!cancelled) {
          setSaved(null);
          setLoadError(`Couldn't load trade protections (${exc.message}).`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, leagueKey, applyServer]);

  const playerNames = useMemo(() => {
    if (!Array.isArray(players)) return [];
    const out = [];
    for (const p of players) {
      if (!p || p.assetClass === "pick" || String(p.pos || p.position || "").toUpperCase() === "PICK") continue;
      const n = p.name || p.displayName;
      if (typeof n === "string" && n) out.push(n);
      if (out.length >= 1500) break;
    }
    return out;
  }, [players]);

  const teamOptions = Array.isArray(saved?.nflTeamOptions) ? saved.nflTeamOptions : [];
  const unresolved = new Set((saved?.unresolvedUntouchables || []).map(key));

  const dirty = useMemo(() => {
    if (!saved) return false;
    const a = JSON.stringify([...untouchables].map(key).sort());
    const b = JSON.stringify([...(saved.untouchables || [])].map(key).sort());
    const c = JSON.stringify([...nflTeams].sort());
    const d = JSON.stringify([...(saved.nflTeams || [])].sort());
    return a !== b || c !== d;
  }, [saved, untouchables, nflTeams]);

  const addPlayer = useCallback(() => {
    const name = playerDraft.trim();
    if (!name) return;
    setUntouchables((prev) => (prev.some((n) => key(n) === key(name)) ? prev : [...prev, name]));
    setPlayerDraft("");
    setStatus("");
  }, [playerDraft]);

  const addTeam = useCallback(() => {
    const code = teamDraft.trim().toUpperCase();
    if (!code) return;
    setNflTeams((prev) => (prev.includes(code) ? prev : [...prev, code].sort()));
    setTeamDraft("");
    setStatus("");
  }, [teamDraft]);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError("");
    setStatus("");
    try {
      const res = await fetch(ENDPOINT, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ leagueKey, untouchables, nflTeams }),
      });
      const body = await res.json().catch(() => ({}));
      if (currentLeague.current !== leagueKey) return; // league changed mid-save
      if (!res.ok) {
        setSaveError(describeSaveError(body, res.status));
        return;
      }
      if (body?.leagueKey !== leagueKey) {
        setSaveError("The server answered for a different league; reload to see what was saved.");
        return;
      }
      applyServer(body);
      setStatus("Saved.");
    } catch (exc) {
      setSaveError(`Couldn't save (${exc.message}).`);
    } finally {
      setSaving(false);
    }
  }, [leagueKey, untouchables, nflTeams, applyServer]);

  if (!enabled) {
    return <p className={styles.empty}>Sign in to set trade protections.</p>;
  }
  if (!leagueKey) {
    return <p className={styles.empty}>Choose a league to set its trade protections.</p>;
  }
  if (loading) {
    return (
      <p className={styles.empty} role="status">
        Loading trade protections…
      </p>
    );
  }
  if (loadError) {
    return <Banner tone="negative">{loadError}</Banner>;
  }

  const league = leagueName || leagueKey;
  return (
    <div className={styles.root}>
      <p className={styles.note}>
        Protected players and NFL teams are never put on the <strong>outgoing</strong> side of
        generated trade ideas in <strong>{league}</strong>. They keep their value, can still be
        suggested as players to acquire, and the manual trade calculator is unaffected. Other
        leagues are not affected.
      </p>

      <section className={styles.group} aria-label="Protected players">
        <h3 className={styles.groupTitle}>Players</h3>
        <div className={styles.addRow}>
          <Field label="Protect a player">
            <Input
              value={playerDraft}
              list="trade-protections-player-list"
              placeholder="Player name"
              onChange={(e) => setPlayerDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addPlayer();
                }
              }}
            />
          </Field>
          <Button size="sm" onClick={addPlayer} disabled={!playerDraft.trim()}>
            Add player
          </Button>
        </div>
        <datalist id="trade-protections-player-list">
          {playerNames.map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
        {untouchables.length === 0 ? (
          <p className={styles.empty}>No individually protected players.</p>
        ) : (
          <ul className={styles.list}>
            {untouchables.map((name) => (
              <li key={key(name)} className={styles.item}>
                <span className={styles.itemName}>
                  {name}
                  {unresolved.has(key(name)) ? (
                    <Badge tone="warning">Not on current board — still protected</Badge>
                  ) : null}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove ${name}`}
                  onClick={() => setUntouchables((prev) => prev.filter((n) => key(n) !== key(name)))}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.group} aria-label="Protected NFL teams">
        <h3 className={styles.groupTitle}>NFL teams</h3>
        {teamOptions.length === 0 ? (
          <p className={styles.empty}>
            NFL teams are unavailable until the board loads; existing team rules are kept.
          </p>
        ) : (
          <div className={styles.addRow}>
            <Field label="Protect every player on an NFL team">
              <Select value={teamDraft} onChange={(e) => setTeamDraft(e.target.value)}>
                <option value="">Choose a team</option>
                {teamOptions
                  .filter((code) => !nflTeams.includes(code))
                  .map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
              </Select>
            </Field>
            <Button size="sm" onClick={addTeam} disabled={!teamDraft}>
              Add team
            </Button>
          </div>
        )}
        {nflTeams.length === 0 ? (
          <p className={styles.empty}>No protected NFL teams.</p>
        ) : (
          <ul className={styles.list}>
            {nflTeams.map((code) => (
              <li key={code} className={styles.item}>
                <span className={`${styles.itemName} ${styles.code}`}>{code}</span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove ${code}`}
                  onClick={() => setNflTeams((prev) => prev.filter((c) => c !== code))}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className={styles.actions}>
        <Button variant="primary" size="sm" onClick={save} loading={saving} disabled={!dirty}>
          Save protections
        </Button>
        {status ? (
          <span className={styles.note} role="status">
            {status}
          </span>
        ) : null}
      </div>
      {saveError ? <Banner tone="negative">{saveError}</Banner> : null}
    </div>
  );
}
