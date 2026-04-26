"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

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

export default function CustomAlertsConfigurator({ enabled, players }) {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
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
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/custom-alerts", { credentials: "include" });
        if (!res.ok) throw new Error(`load_${res.status}`);
        const json = await res.json();
        if (!cancelled) {
          setRules(Array.isArray(json?.rules) ? json.rules : []);
        }
      } catch (exc) {
        if (!cancelled) setError(`Couldn't load alerts (${exc.message}).`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const persist = useCallback(async (next) => {
    setError("");
    setSavingFor("all");
    try {
      const res = await fetch("/api/custom-alerts", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules: next }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const j = await res.json();
          detail = j?.detail || j?.error || "";
        } catch { /* ignore */ }
        throw new Error(detail || `save_${res.status}`);
      }
      const json = await res.json();
      setRules(Array.isArray(json?.rules) ? json.rules : []);
      setStatus("Saved.");
      setTimeout(() => setStatus(""), 2500);
    } catch (exc) {
      setError(`Couldn't save (${exc.message}).`);
    } finally {
      setSavingFor(null);
    }
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
    (id) => {
      const next = rules.filter((r) => r.id !== id);
      setRules(next);
      persist(next);
    },
    [rules, persist],
  );

  const saveAll = useCallback(() => {
    const cleaned = rules
      .map((r) => ({ ...r, displayName: String(r.displayName || "").trim() }))
      .filter((r) => r.displayName.length > 0);
    persist(cleaned);
  }, [rules, persist]);

  if (!enabled) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem" }}>
        Sign in to set up custom alerts.
      </p>
    );
  }

  if (loading) {
    return <p className="muted" style={{ fontSize: "0.72rem" }}>Loading…</p>;
  }

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
        rules.map((rule) => (
          <div
            key={rule.id}
            className="card"
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
                value={rule.kind}
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
                value={rule.displayName || ""}
                placeholder="Player name"
                list="brisket-custom-alerts-player-list"
                onChange={(e) => updateRule(rule.id, { displayName: e.target.value })}
                style={{ flex: "1 1 200px", minWidth: 160, fontSize: "0.78rem" }}
              />
              <button
                className="button"
                onClick={() => removeRule(rule.id)}
                style={{ fontSize: "0.72rem", padding: "4px 10px" }}
              >
                Remove
              </button>
            </div>

            {rule.kind === "value_crosses" && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <select
                  className="input"
                  value={rule.params?.direction || "above"}
                  onChange={(e) => updateParams(rule.id, { direction: e.target.value })}
                  style={{ flex: "0 0 auto", fontSize: "0.78rem" }}
                >
                  <option value="above">crosses above</option>
                  <option value="below">crosses below</option>
                </select>
                <input
                  type="number"
                  className="input"
                  value={Number(rule.params?.threshold ?? 0)}
                  step={100}
                  min={0}
                  onChange={(e) =>
                    updateParams(rule.id, { threshold: Number(e.target.value) || 0 })
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
                  value={Number(rule.params?.minDelta ?? 10)}
                  min={1}
                  max={200}
                  onChange={(e) =>
                    updateParams(rule.id, { minDelta: Math.max(1, Number(e.target.value) || 1) })
                  }
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
                  onChange={(e) => toggleChannel(rule.id, "email", e.target.checked)}
                />
                Email
              </label>
              <label style={{ display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={(rule.channels || []).includes("push")}
                  onChange={(e) => toggleChannel(rule.id, "push", e.target.checked)}
                />
                Push
              </label>
            </div>
          </div>
        ))
      )}

      <datalist id="brisket-custom-alerts-player-list">
        {playerNames.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button
          className="button"
          onClick={() => addRule("value_crosses")}
          style={{ fontSize: "0.76rem" }}
        >
          + Value alert
        </button>
        <button
          className="button"
          onClick={() => addRule("rank_change")}
          style={{ fontSize: "0.76rem" }}
        >
          + Rank-change alert
        </button>
        <button
          className="button"
          onClick={saveAll}
          disabled={savingFor === "all"}
          style={{ fontSize: "0.76rem", marginLeft: "auto" }}
        >
          {savingFor === "all" ? "Saving…" : "Save all"}
        </button>
      </div>

      {status && (
        <div className="muted" style={{ fontSize: "0.7rem", color: "var(--green)" }}>
          {status}
        </div>
      )}
      {error && (
        <div className="muted" style={{ fontSize: "0.7rem", color: "var(--red)" }}>
          {error}
        </div>
      )}
    </div>
  );
}
