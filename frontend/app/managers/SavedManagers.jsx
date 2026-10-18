"use client";

/**
 * Manager Intelligence — saved managers (C6-MGR-02 Batch F).
 *
 * `useSavedManagers` owns the signed-in user's saved list (GET / POST /
 * DELETE /api/manager-intel/saved); `SaveManagerButton` saves or removes the
 * looked-up manager; `SavedManagersPanel` lists them with their activity-check
 * state, an in-app "Check for new activity" (POST …/saved/refresh) and the
 * link to the scoped leaderboards.
 *
 * Display layer only: entries are keyed by the permanent Sleeper user id
 * and names are re-read by the backend (`src/intel/manager_saved.py`), so a
 * renamed manager stays saved and shows the new name.  `lib/manager-saved.js`
 * labels.  Unavailable and empty states are explicit, never a blank panel.
 */

import { useCallback, useEffect, useState } from "react";
import { Banner, Button, EmptyState, Panel, Skeleton } from "@/components/ds";
import {
  SAVED_ENDPOINT,
  SAVED_REFRESH_ENDPOINT,
  alertStateText,
  atCap,
  formerNamesText,
  isSaved,
  leaderboardHref,
  lookupHref,
  nameStateText,
  refreshRows,
  saveBody,
  savedCapText,
  savedErrorMessage,
  eventLine,
} from "@/lib/manager-saved";
import styles from "./managers.module.css";
import saved from "./saved.module.css";

async function readJson(response) {
  return response.json().catch(() => ({}));
}

export function useSavedManagers() {
  const [state, setState] = useState({ phase: "loading", data: null, error: null });
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState(null);
  const [check, setCheck] = useState({ phase: "idle", result: null, error: null });

  const load = useCallback(async () => {
    try {
      const response = await fetch(SAVED_ENDPOINT, {
        cache: "no-store",
        credentials: "same-origin",
      });
      const body = await readJson(response);
      if (!response.ok) {
        setState({
          phase: "unavailable",
          data: null,
          error: savedErrorMessage(response.status, body),
        });
        return;
      }
      setState({ phase: "ready", data: body, error: null });
    } catch {
      setState({ phase: "unavailable", data: null, error: savedErrorMessage(0, null) });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const write = useCallback(async (userId, init) => {
    setBusy(userId);
    setNotice(null);
    try {
      const response = await fetch(init.url, {
        method: init.method,
        cache: "no-store",
        credentials: "same-origin",
        headers: init.body ? { "Content-Type": "application/json" } : undefined,
        body: init.body ? JSON.stringify(init.body) : undefined,
      });
      const body = await readJson(response);
      if (!response.ok) {
        setNotice({ tone: "negative", text: savedErrorMessage(response.status, body) });
        return false;
      }
      setState({ phase: "ready", data: body, error: null });
      return true;
    } catch {
      setNotice({ tone: "negative", text: savedErrorMessage(0, null) });
      return false;
    } finally {
      setBusy("");
    }
  }, []);

  const save = useCallback(
    (userId, options) => {
      const body = saveBody(userId, options);
      if (!body) return Promise.resolve(false);
      return write(userId, { url: SAVED_ENDPOINT, method: "POST", body });
    },
    [write],
  );

  const remove = useCallback(
    (userId) =>
      write(userId, {
        url: `${SAVED_ENDPOINT}?userId=${encodeURIComponent(String(userId))}`,
        method: "DELETE",
      }),
    [write],
  );

  const refresh = useCallback(async () => {
    setCheck({ phase: "loading", result: null, error: null });
    try {
      const response = await fetch(SAVED_REFRESH_ENDPOINT, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
      });
      const body = await readJson(response);
      if (!response.ok) {
        setCheck({
          phase: "error",
          result: null,
          error: savedErrorMessage(response.status, body),
        });
        return;
      }
      setCheck({ phase: "ready", result: body, error: null });
      load();
    } catch {
      setCheck({ phase: "error", result: null, error: savedErrorMessage(0, null) });
    }
  }, [load]);

  return { ...state, busy, notice, check, save, remove, refresh };
}

/** Save / remove the looked-up manager (by permanent Sleeper user id). */
export function SaveManagerButton({ savedState, userId, name }) {
  if (!savedState || savedState.phase === "unavailable" || !userId) return null;
  const on = isSaved(savedState.data, userId);
  const full = !on && atCap(savedState.data);
  const label = name || "this manager";
  return (
    <span className={saved.saveControl}>
      <Button
        size="sm"
        variant={on ? "secondary" : "primary"}
        aria-pressed={on}
        loading={savedState.busy === String(userId)}
        disabled={savedState.phase !== "ready" || full}
        onClick={() => (on ? savedState.remove(userId) : savedState.save(userId))}
      >
        {on ? "Saved" : "Save manager"}
        <span className={styles.srOnly}>
          {on ? `: remove ${label} from saved managers` : `: ${label}`}
        </span>
      </Button>
      {full ? (
        <span className={styles.muted}>Saved list full ({savedCapText(savedState.data)})</span>
      ) : null}
    </span>
  );
}

function CheckResults({ check }) {
  if (check.phase === "error") {
    return (
      <Banner tone="negative" title="Check failed">
        {check.error}
      </Banner>
    );
  }
  if (check.phase !== "ready") return null;
  const rows = refreshRows(check.result);
  if (!rows.length) {
    return <p className={styles.note}>No saved managers to check.</p>;
  }
  return (
    <section className={saved.checkResults} aria-label="New activity">
      <ul className={saved.checkList}>
        {rows.map((r) => (
          <li key={r.userId}>
            <strong>{r.name}</strong>
            {r.events.length ? (
              <ul className={saved.eventList}>
                {r.events.map((ev) => (
                  <li key={ev.id}>{eventLine(ev)}</li>
                ))}
              </ul>
            ) : (
              <span className={styles.muted}> — {r.note || "no new activity"}</span>
            )}
          </li>
        ))}
      </ul>
      {check.result?.remaining ? (
        <p className={styles.note}>
          {check.result.remaining} more saved manager
          {check.result.remaining === 1 ? "" : "s"} not checked this time — check again
          later, or wait for the daily sweep.
        </p>
      ) : null}
      {check.result?.note ? <p className={styles.note}>{check.result.note}</p> : null}
    </section>
  );
}

export function SavedManagersPanel({ savedState, onOpen }) {
  if (!savedState) return null;
  const { phase, data, error, busy, notice, check } = savedState;
  const managers = data?.managers || [];
  return (
    <Panel
      title="Saved managers"
      subtitle={phase === "ready" ? savedCapText(data) : undefined}
      actions={
        phase === "ready" && managers.length ? (
          <span className={saved.panelActions}>
            <Button
              size="sm"
              variant="ghost"
              loading={check.phase === "loading"}
              onClick={savedState.refresh}
            >
              Check for new activity
            </Button>
            <a href={leaderboardHref({ population: "saved" })} className={styles.link}>
              Leaderboards
            </a>
          </span>
        ) : null
      }
    >
      {phase === "loading" ? <Skeleton height={48} /> : null}
      {phase === "unavailable" ? (
        <Banner tone="warning" title="Saved managers unavailable">
          {error}
        </Banner>
      ) : null}
      {notice ? (
        <Banner tone={notice.tone} title="Not saved">
          {notice.text}
        </Banner>
      ) : null}
      {phase === "ready" && !managers.length ? (
        <EmptyState
          title="No saved managers yet"
          description="Look up a manager and choose Save manager. Saved managers are followed by their Sleeper account, so a rename keeps them here, and new moves reach you in the daily alert email when notifications are on."
        />
      ) : null}
      {phase === "ready" && managers.length ? (
        <ul className={saved.savedList}>
          {managers.map((m) => {
            const href = lookupHref(m);
            const nameNote = nameStateText(m);
            const former = formerNamesText(m);
            return (
              <li key={m.userId} className={saved.savedRow}>
                <div className={saved.savedName}>
                  {href ? (
                    <a
                      href={href}
                      className={styles.link}
                      onClick={(event) => {
                        if (!onOpen || !m.username) return;
                        event.preventDefault();
                        onOpen(m.username);
                      }}
                    >
                      {m.displayName || m.username || m.userId}
                    </a>
                  ) : (
                    <span>{m.displayName || m.username || m.userId}</span>
                  )}
                  <span className={styles.muted}>
                    {m.username ? `@${m.username}` : ""}
                    {former ? ` · ${former}` : ""}
                  </span>
                  {nameNote ? <span className={styles.muted}>{nameNote}</span> : null}
                </div>
                <span className={`${styles.muted} ${saved.savedState}`}>
                  {alertStateText(m)}
                </span>
                <span className={saved.savedButtons}>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-pressed={m.alerts !== false}
                    loading={busy === m.userId}
                    onClick={() => savedState.save(m.userId, { alerts: m.alerts === false })}
                  >
                    {m.alerts === false ? "Alerts off" : "Alerts on"}
                    <span className={styles.srOnly}>
                      {` for ${m.displayName || m.username || m.userId}`}
                    </span>
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => savedState.remove(m.userId)}
                    disabled={busy === m.userId}
                  >
                    Remove
                    <span className={styles.srOnly}>
                      {` ${m.displayName || m.username || m.userId}`}
                    </span>
                  </Button>
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <CheckResults check={check} />
    </Panel>
  );
}

export default SavedManagersPanel;
