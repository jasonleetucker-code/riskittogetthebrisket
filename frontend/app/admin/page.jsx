/**
 * /admin — operator dashboard for flipping feature flags, running
 * one-off admin actions (flush cache, force-logout, migrate signal
 * state), and viewing observability signals (flag state, ID mapping
 * coverage, NFL data provider status).
 *
 * Access is gated server-side by ``PRIVATE_APP_ALLOWED_USERNAMES``
 * — non-admin sessions get 403 from the admin endpoints.  This
 * page renders a friendly "Not authorized" message if any endpoint
 * returns 403.
 *
 * Deliberately minimal UI — raw data, action buttons, confirmation
 * modals.  Polish comes later; the infrastructure of "one place
 * for all admin levers" is the point.
 */
"use client";

import { useEffect, useState } from "react";


export default function AdminPage() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionLog, setActionLog] = useState([]);

  const loadStatus = async () => {
    try {
      setBusy(true);
      const res = await fetch("/api/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setStatus(body);
      setErr("");
    } catch (e) {
      setErr(`Failed to load status: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { loadStatus(); }, []);

  const runAction = async (label, url, method = "POST") => {
    if (!confirm(`Run: ${label}?`)) return;
    try {
      setBusy(true);
      const res = await fetch(url, { method });
      const body = await res.json().catch(() => ({}));
      const ok = res.ok;
      setActionLog((prev) => [
        {
          ts: new Date().toISOString(),
          label, url, status: res.status, ok,
          body: JSON.stringify(body).slice(0, 400),
        },
        ...prev.slice(0, 19),
      ]);
      await loadStatus();
    } catch (e) {
      setActionLog((prev) => [
        { ts: new Date().toISOString(), label, url, status: "ERR", ok: false, body: e.message },
        ...prev.slice(0, 19),
      ]);
    } finally {
      setBusy(false);
    }
  };

  if (err) {
    return (
      <main style={{ padding: "var(--space-lg)" }}>
        <h1>Admin</h1>
        <div className="card" style={{ background: "rgba(220, 50, 50, 0.1)" }}>
          <p>{err}</p>
          <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
            This page requires an admin session.  If you're signed in
            and still seeing this, your username may not be in the
            allowlist.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main style={{ padding: "var(--space-lg)", maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ marginBottom: "var(--space-md)" }}>Admin</h1>
      <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginBottom: "var(--space-lg)" }}>
        Operator controls.  Every action logs to the backend with the
        username + timestamp.  Don't flip flags you don't understand.
      </p>

      {/* ── Feature flags ─────────────────────────── */}
      <section className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h2 style={{ margin: 0, fontSize: "1rem", fontWeight: 700 }}>Feature flags</h2>
        <p style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
          Flags are env-driven; flip via <code>RISKIT_FEATURE_&lt;NAME&gt;=1</code> + deploy.
          This table is read-only — it reflects what the server currently sees.
        </p>
        {status?.featureFlags ? (
          <table style={{ width: "100%", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Flag</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(status.featureFlags).map(([name, on]) => (
                <tr key={name}>
                  <td className="font-mono">{name}</td>
                  <td style={{ textAlign: "center" }}>
                    <span style={{ color: on ? "var(--green)" : "var(--muted)" }}>
                      {on ? "● ON" : "○ off"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: "var(--muted)" }}>Loading…</p>
        )}
      </section>

      {/* ── ID mapping + NFL data ─────────────────── */}
      <section className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h2 style={{ margin: 0, fontSize: "1rem", fontWeight: 700 }}>ID mapper + NFL data</h2>
        {status?.idMappingCoverage ? (
          <pre style={{ fontSize: "0.75rem", overflow: "auto" }}>
            {JSON.stringify(status.idMappingCoverage, null, 2)}
          </pre>
        ) : null}
        {status?.nflDataProvider ? (
          <pre style={{ fontSize: "0.75rem", overflow: "auto" }}>
            {JSON.stringify(status.nflDataProvider, null, 2)}
          </pre>
        ) : null}
      </section>

      {/* ── Actions ────────────────────────────────── */}
      <section className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h2 style={{ margin: 0, fontSize: "1rem", fontWeight: 700 }}>Actions</h2>
        <div style={{ display: "flex", gap: "var(--space-sm)", flexWrap: "wrap", marginTop: "var(--space-sm)" }}>
          <button
            className="btn"
            disabled={busy}
            onClick={() => runAction("Flush NFL data cache", "/api/admin/nfl-data/flush")}
          >
            Flush NFL data cache
          </button>
          <button
            className="btn"
            disabled={busy}
            onClick={() => runAction("Migrate signal state", "/api/admin/signal-state/migrate")}
          >
            Migrate signal state
          </button>
          <button
            className="btn btn-danger"
            disabled={busy}
            onClick={() => runAction(
              "⚠️ Force-logout ALL sessions",
              "/api/admin/sessions/force-logout-all",
            )}
          >
            Force-logout all sessions
          </button>
        </div>
      </section>

      {/* ── Action log ─────────────────────────────── */}
      {actionLog.length > 0 && (
        <section className="card">
          <h2 style={{ margin: 0, fontSize: "1rem", fontWeight: 700 }}>Recent actions</h2>
          <table style={{ width: "100%", fontSize: "0.75rem", fontFamily: "monospace" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Time</th>
                <th style={{ textAlign: "left" }}>Action</th>
                <th>Status</th>
                <th style={{ textAlign: "left" }}>Response</th>
              </tr>
            </thead>
            <tbody>
              {actionLog.map((a, i) => (
                <tr key={i} style={{ color: a.ok ? "var(--green)" : "var(--amber)" }}>
                  <td>{a.ts.slice(11, 19)}</td>
                  <td>{a.label}</td>
                  <td style={{ textAlign: "center" }}>{a.status}</td>
                  <td style={{ maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {a.body}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
