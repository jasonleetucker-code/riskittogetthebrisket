"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FailureState } from "@/components/ds";
import { classifyContractFailure } from "@/lib/contract-failure";

const KIND_LABELS = {
  value_crosses: "Value crosses threshold",
  rank_change: "Rank moves by",
};

function genId() {
  return `alert_${Math.random().toString(16).slice(2, 14)}`;
}

function newRule(kind = "value_crosses") {
  if (kind === "rank_change") {
    return {
      id: genId(),
      kind,
      displayName: "",
      params: { minDelta: 10 },
      channels: ["email"],
    };
  }
  return {
    id: genId(),
    kind: "value_crosses",
    displayName: "",
    params: { threshold: 6000, direction: "above" },
    channels: ["email"],
  };
}

/**
 * A number input's value as a rule parameter: the number, or null when the
 * field is empty.  An emptied field is MISSING, never 0 (or any other
 * stand-in) — Save refuses a rule with a missing number instead.
 */
function numberOrNull(raw) {
  if (raw === "" || raw === null || raw === undefined) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/** The input's displayed value: the number, or "" when it is missing. */
function shownNumber(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : "";
}

/**
 * The number a rule still needs before it can be saved, or null when it has
 * every number its kind uses.
 */
function missingNumberFor(rule) {
  if (rule.kind === "rank_change") {
    return shownNumber(rule.params?.minDelta) === "" ? "how many positions" : null;
  }
  return shownNumber(rule.params?.threshold) === "" ? "a threshold" : null;
}

async function readBody(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * The server's saved list from a response body, or null when the body is
 * not a list.  A malformed answer is NOT an empty list: treating it as one
 * is what let a failed load show "No alerts configured yet" and a later
 * Save overwrite the alerts the server still held.
 */
function rulesFrom(json) {
  return Array.isArray(json?.rules) ? json.rules : null;
}

/**
 * PUT the complete rule list.  Resolves `{ok: true, rules}` with the list
 * the SERVER confirmed, or `{ok: false, message}`.  Never throws.
 */
async function putRules(next) {
  let res;
  try {
    res = await fetch("/api/custom-alerts", {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules: next }),
    });
  } catch {
    return { ok: false, message: classifyContractFailure(null, null).message };
  }
  const json = await readBody(res);
  if (!res.ok) {
    return { ok: false, message: classifyContractFailure(res.status, json).message };
  }
  const rules = rulesFrom(json);
  if (!rules) {
    return { ok: false, message: "The server did not confirm the saved alerts." };
  }
  return { ok: true, rules };
}

/**
 * Custom alerts on /settings.
 *
 * Three states the previous version collapsed (verified 2026-11-16):
 *   * a FAILED load rendered "No alerts configured yet" — and Save then
 *     PUT that empty list over the alerts the server still held;
 *   * Remove dropped the rule from the screen BEFORE the server answered,
 *     so a failed delete still looked like a delete.
 * Now: a failed load is its own state with a retry, and nothing can be
 * added, saved or removed until a load has succeeded; Remove and Save
 * change the list only to what the server confirmed.  Rule inputs are locked
 * while a save or remove is in flight (a save replaces the screen with the
 * server's list when it answers, so an edit typed meanwhile would be lost),
 * and an
 * emptied number stays empty — never 0 — and blocks Save with a message.
 */
export default function CustomAlertsConfigurator({ enabled, players }) {
  // `rules` are the editable drafts; `savedRules` is the last list the
  // server confirmed.  Remove deletes from the SAVED list, so it never
  // smuggles another rule's unsaved edits onto the server.
  const [rules, setRules] = useState([]);
  const [savedRules, setSavedRules] = useState([]);
  // "loading" | "loaded" | "failed"
  const [loadState, setLoadState] = useState("loading");
  const [loadFailure, setLoadFailure] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  // null | "all" | <rule id being removed>
  const [savingFor, setSavingFor] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const playerNames = useMemo(() => {
    if (!Array.isArray(players)) return [];
    return players
      .map((p) => p?.name || p?.displayName)
      .filter((n) => typeof n === "string" && n.length > 0)
      .slice(0, 800);
  }, [players]);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    setLoadState("loading");
    setLoadFailure(null);
    (async () => {
      let failure = null;
      let loaded = null;
      try {
        const res = await fetch("/api/custom-alerts", { credentials: "include" });
        const json = await readBody(res);
        if (!res.ok) {
          failure = classifyContractFailure(res.status, json);
        } else {
          loaded = rulesFrom(json);
          if (!loaded) {
            failure = {
              kind: "no_data",
              code: "",
              message: "The server answered without a list of alerts.",
              retryable: true,
            };
          }
        }
      } catch {
        failure = classifyContractFailure(null, null);
      }
      if (cancelled) return;
      if (failure) {
        setLoadFailure(failure);
        setLoadState("failed");
        return;
      }
      setRules(loaded);
      setSavedRules(loaded);
      setLoadState("loaded");
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, reloadToken]);

  const retryLoad = useCallback(() => setReloadToken((n) => n + 1), []);

  const flashStatus = useCallback((text) => {
    setStatus(text);
    setTimeout(() => setStatus(""), 2500);
  }, []);

  const addRule = useCallback((kind) => {
    setRules((prev) => [...prev, newRule(kind)]);
  }, []);

  const updateRule = useCallback((id, patch) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const updateParams = useCallback((id, patch) => {
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, params: { ...r.params, ...patch } } : r)),
    );
  }, []);

  const toggleChannel = useCallback((id, channel, on) => {
    setRules((prev) =>
      prev.map((r) => {
        if (r.id !== id) return r;
        const set = new Set(r.channels || ["email"]);
        if (on) set.add(channel);
        else set.delete(channel);
        if (set.size === 0) set.add("email");
        return { ...r, channels: Array.from(set) };
      }),
    );
  }, []);

  const removeRule = useCallback(
    async (id) => {
      if (loadState !== "loaded" || savingFor) return;
      setError("");
      // Never saved: it exists only on this screen, so dropping it is local.
      if (!savedRules.some((r) => r.id === id)) {
        setRules((prev) => prev.filter((r) => r.id !== id));
        return;
      }
      setSavingFor(id);
      const result = await putRules(savedRules.filter((r) => r.id !== id));
      setSavingFor(null);
      if (!result.ok) {
        setError(`Couldn't remove the alert (${result.message}). It is still saved.`);
        return;
      }
      setSavedRules(result.rules);
      setRules((prev) => prev.filter((r) => r.id !== id));
      flashStatus("Alert removed.");
    },
    [loadState, savingFor, savedRules, flashStatus],
  );

  const saveAll = useCallback(async () => {
    if (loadState !== "loaded" || savingFor) return;
    setError("");
    const cleaned = rules
      .map((r) => ({ ...r, displayName: String(r.displayName || "").trim() }))
      .filter((r) => r.displayName.length > 0);
    // A rule whose number was cleared is not saved as 0: Save stops and
    // says which alert needs it.
    const incomplete = cleaned.find((r) => missingNumberFor(r));
    if (incomplete) {
      setError(
        `Enter ${missingNumberFor(incomplete)} for the ${incomplete.displayName} alert before saving. Nothing was saved.`,
      );
      return;
    }
    setSavingFor("all");
    const result = await putRules(cleaned);
    setSavingFor(null);
    if (!result.ok) {
      setError(`Couldn't save (${result.message}).`);
      return;
    }
    setSavedRules(result.rules);
    setRules(result.rules);
    flashStatus("Saved.");
  }, [loadState, savingFor, rules, flashStatus]);

  if (!enabled) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem" }}>
        Sign in to set up custom alerts.
      </p>
    );
  }

  if (loadState === "loading") {
    return (
      <p className="muted" role="status" style={{ fontSize: "0.72rem" }}>
        Loading your alerts…
      </p>
    );
  }

  if (loadState === "failed") {
    // No list, no "No alerts configured yet", and no Save: the saved alerts
    // are unknown, and saving would replace them with whatever is on screen.
    return (
      <div data-testid="custom-alerts-load-failed">
        <FailureState failure={loadFailure} onRetry={retryLoad} context="your custom alerts" />
        <p className="muted" style={{ fontSize: "0.7rem", margin: "6px 0 0" }}>
          Your saved alerts could not be read, so they cannot be edited until
          they load. Nothing has been changed.
        </p>
      </div>
    );
  }

  const busy = savingFor !== null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <p className="muted" style={{ fontSize: "0.72rem", margin: 0 }}>
        Watch a specific player for value crossings or rank moves. Alerts fire at most
        once per 24 hours per (player, rule) pair, delivered via your enabled channels.
      </p>

      {rules.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.72rem", fontStyle: "italic" }}>
          No alerts configured yet.
        </p>
      ) : (
        rules.map((rule, index) => {
          const name = String(rule.displayName || "").trim();
          const ruleLabel = name ? `the ${name} alert` : `alert ${index + 1}`;
          const removing = savingFor === rule.id;
          return (
            <div
              key={rule.id}
              className="card"
              data-testid={`custom-alert-${rule.id}`}
              style={{
                padding: 10,
                display: "flex",
                flexDirection: "column",
                gap: 6,
                border: "1px solid var(--border)",
              }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <select
                  className="input"
                  aria-label={`Alert type for ${ruleLabel}`}
                  value={rule.kind}
                  disabled={busy}
                  onChange={(e) => {
                    const next = newRule(e.target.value);
                    updateRule(rule.id, {
                      kind: next.kind,
                      params: next.params,
                    });
                  }}
                  style={{ flex: "0 0 auto", fontSize: "0.78rem" }}
                >
                  {Object.entries(KIND_LABELS).map(([k, label]) => (
                    <option key={k} value={k}>{label}</option>
                  ))}
                </select>
                <input
                  className="input"
                  aria-label={`Player name for alert ${index + 1}`}
                  value={rule.displayName || ""}
                  disabled={busy}
                  placeholder="Player name"
                  list="brisket-custom-alerts-player-list"
                  onChange={(e) => updateRule(rule.id, { displayName: e.target.value })}
                  style={{ flex: "1 1 200px", minWidth: 160, fontSize: "0.78rem" }}
                />
                <button
                  type="button"
                  className="button"
                  aria-label={removing ? `Removing ${ruleLabel}` : `Remove ${ruleLabel}`}
                  aria-busy={removing || undefined}
                  onClick={() => removeRule(rule.id)}
                  disabled={busy}
                  style={{ fontSize: "0.72rem", padding: "4px 10px" }}
                >
                  {removing ? "Removing…" : "Remove"}
                </button>
              </div>

              {rule.kind === "value_crosses" && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <select
                    className="input"
                    aria-label={`Direction for ${ruleLabel}`}
                    value={rule.params?.direction || "above"}
                    disabled={busy}
                    onChange={(e) => updateParams(rule.id, { direction: e.target.value })}
                    style={{ flex: "0 0 auto", fontSize: "0.78rem" }}
                  >
                    <option value="above">crosses above</option>
                    <option value="below">crosses below</option>
                  </select>
                  <input
                    type="number"
                    className="input"
                    aria-label={`Threshold (canonical value) for ${ruleLabel}`}
                    value={shownNumber(rule.params?.threshold)}
                    aria-invalid={shownNumber(rule.params?.threshold) === "" || undefined}
                    disabled={busy}
                    step={100}
                    min={0}
                    onChange={(e) =>
                      updateParams(rule.id, { threshold: numberOrNull(e.target.value) })
                    }
                    style={{ flex: "0 0 110px", fontSize: "0.78rem" }}
                  />
                  <span className="muted" style={{ fontSize: "0.7rem" }}>(canonical value)</span>
                </div>
              )}

              {rule.kind === "rank_change" && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <span style={{ fontSize: "0.78rem" }}>at least</span>
                  <input
                    type="number"
                    className="input"
                    aria-label={`At least how many positions for ${ruleLabel}`}
                    value={shownNumber(rule.params?.minDelta)}
                    aria-invalid={shownNumber(rule.params?.minDelta) === "" || undefined}
                    disabled={busy}
                    min={1}
                    max={200}
                    onChange={(e) => {
                      const n = numberOrNull(e.target.value);
                      updateParams(rule.id, { minDelta: n === null ? null : Math.max(1, n) });
                    }}
                    style={{ flex: "0 0 80px", fontSize: "0.78rem" }}
                  />
                  <span style={{ fontSize: "0.78rem" }}>positions in either direction</span>
                </div>
              )}

              <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", fontSize: "0.78rem" }}>
                <span className="muted" style={{ fontSize: "0.72rem" }}>Send via:</span>
                <label style={{ display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={(rule.channels || ["email"]).includes("email")}
                    disabled={busy}
                    onChange={(e) => toggleChannel(rule.id, "email", e.target.checked)}
                  />
                  Email
                </label>
                <label style={{ display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={(rule.channels || []).includes("push")}
                    disabled={busy}
                    onChange={(e) => toggleChannel(rule.id, "push", e.target.checked)}
                  />
                  Push
                </label>
              </div>
            </div>
          );
        })
      )}

      <datalist id="brisket-custom-alerts-player-list">
        {playerNames.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button
          type="button"
          className="button"
          onClick={() => addRule("value_crosses")}
          disabled={busy}
          style={{ fontSize: "0.76rem" }}
        >
          + Value alert
        </button>
        <button
          type="button"
          className="button"
          onClick={() => addRule("rank_change")}
          disabled={busy}
          style={{ fontSize: "0.76rem" }}
        >
          + Rank-change alert
        </button>
        <button
          type="button"
          className="button"
          onClick={saveAll}
          disabled={busy}
          style={{ fontSize: "0.76rem", marginLeft: "auto" }}
        >
          {savingFor === "all" ? "Saving…" : "Save all"}
        </button>
      </div>

      {status && (
        <div role="status" className="muted" style={{ fontSize: "0.7rem", color: "var(--green)" }}>
          {status}
        </div>
      )}
      {error && (
        <div role="alert" className="muted" style={{ fontSize: "0.7rem", color: "var(--red)" }}>
          {error}
        </div>
      )}
    </div>
  );
}
