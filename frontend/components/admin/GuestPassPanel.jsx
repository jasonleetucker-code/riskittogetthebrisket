/**
 * GuestPassPanel — mint, list and revoke time-boxed guest passes.
 *
 * Moved out of /settings for the same reason as ServerStatusPanel:
 * handing out credentials is an operator action, not a preference, and
 * the endpoints behind it are admin-gated anyway.
 */
"use client";

import { useCallback, useEffect, useState } from "react";

// Imported, not redefined.  The private copy this component used to
// rely on lived in app/settings/page.jsx and did not come with it when
// the component was extracted — see #779 and lib/guest-pass-format.js.
import { fmtPassExpiry } from "@/lib/guest-pass-format";

export default function GuestPassPanel() {
  const [hours, setHours] = useState(12);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [freshToken, setFreshToken] = useState(null);
  const [passes, setPasses] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");

  const fetchList = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/guest-passes", {
        cache: "no-store",
      });
      if (res.status === 403) {
        setError("Admin only.");
        setPasses([]);
        return;
      }
      if (!res.ok) {
        setError(`Server error (${res.status})`);
        return;
      }
      const body = await res.json();
      setPasses(Array.isArray(body?.passes) ? body.passes : []);
      setError("");
    } catch {
      setError("Could not reach the backend.");
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  async function generate() {
    setBusy(true);
    setError("");
    setFreshToken(null);
    setCopyStatus("");
    try {
      const res = await fetch("/api/admin/guest-pass", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          durationHours: Number(hours) || 12,
          note: String(note || "").trim(),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(body?.message || body?.error || `HTTP ${res.status}`);
        return;
      }
      setFreshToken({
        token: body.token,
        expiresAtEpoch: body?.pass?.expiresAtEpoch,
        note: body?.pass?.note || "",
        id: body?.pass?.id,
      });
      setNote("");
      // Refresh the list so the new pass shows up.
      fetchList();
    } catch {
      setError("Could not reach the backend.");
    } finally {
      setBusy(false);
    }
  }

  async function copyToken(token) {
    try {
      await navigator.clipboard.writeText(token);
      setCopyStatus("Copied!");
      setTimeout(() => setCopyStatus(""), 2000);
    } catch {
      setCopyStatus("Copy failed — select the token manually.");
    }
  }

  async function revoke(id) {
    if (
      !window.confirm("Revoke this guest pass? The recipient will lose access.")
    ) {
      return;
    }
    try {
      const res = await fetch(`/api/admin/guest-pass/${id}/revoke`, {
        method: "POST",
      });
      if (!res.ok) {
        setError(`Revoke failed (${res.status})`);
        return;
      }
      fetchList();
    } catch {
      setError("Could not reach the backend.");
    }
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 12px" }}>
        Generate a temporary password to share with someone you want to give
        private-app access. They paste it into the login form's password field;
        their session expires automatically when the pass does. Plaintext tokens
        are shown ONCE — copy and share immediately.
      </p>

      {/* ── Generate form ─────────────────────────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr auto",
          gap: 8,
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <label
          style={{
            fontSize: "0.74rem",
            color: "var(--subtext)",
            whiteSpace: "nowrap",
          }}
          title="How long the guest's session stays valid (1 hour to 720 hours / 30 days)."
        >
          Duration:
          <input
            type="number"
            min={1}
            max={720}
            step={1}
            value={hours}
            onChange={(e) =>
              setHours(Math.max(1, Math.min(720, Number(e.target.value) || 12)))
            }
            style={{
              marginLeft: 6,
              width: 64,
              fontFamily: "var(--mono)",
              fontSize: "0.82rem",
              padding: "4px 6px",
              background: "rgba(8,19,44,0.6)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              color: "var(--text)",
            }}
          />
          <span style={{ marginLeft: 4 }}>hours</span>
        </label>
        <input
          type="text"
          placeholder="Optional note (e.g. 'Brent — preview')"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={100}
          style={{
            fontSize: "0.78rem",
            padding: "5px 8px",
            background: "rgba(8,19,44,0.6)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
          }}
        />
        <button
          className="button"
          onClick={generate}
          disabled={busy}
          style={{ fontSize: "0.78rem", whiteSpace: "nowrap" }}
        >
          {busy ? "Generating…" : `Generate ${hours}h pass`}
        </button>
      </div>

      {error && (
        <div
          style={{
            fontSize: "0.74rem",
            color: "var(--red)",
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}

      {/* ── Fresh-token reveal ────────────────────────────────── */}
      {freshToken && (
        <div
          className="card"
          style={{
            marginBottom: 12,
            padding: 10,
            border: "1px solid var(--green)",
            background: "rgba(52, 211, 153, 0.06)",
          }}
        >
          <div
            style={{
              fontSize: "0.7rem",
              color: "var(--green)",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              marginBottom: 6,
            }}
          >
            New pass — copy NOW (won't be shown again)
          </div>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              marginBottom: 6,
            }}
          >
            <code
              style={{
                fontFamily: "var(--mono)",
                fontSize: "0.82rem",
                padding: "6px 10px",
                background: "rgba(8,19,44,0.85)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                flex: 1,
                wordBreak: "break-all",
              }}
            >
              {freshToken.token}
            </code>
            <button
              className="button"
              onClick={() => copyToken(freshToken.token)}
              style={{ fontSize: "0.74rem" }}
            >
              Copy
            </button>
          </div>
          {copyStatus && (
            <div
              style={{
                fontSize: "0.7rem",
                color: copyStatus === "Copied!" ? "var(--green)" : "var(--red)",
              }}
            >
              {copyStatus}
            </div>
          )}
          <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
            Expires {fmtPassExpiry(freshToken.expiresAtEpoch)} · #
            {freshToken.id}
            {freshToken.note ? ` · ${freshToken.note}` : ""}
          </div>
        </div>
      )}

      {/* ── Active + recent passes ────────────────────────────── */}
      <div style={{ fontWeight: 600, fontSize: "0.78rem", marginBottom: 6 }}>
        Recent passes
      </div>
      {listLoading ? (
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          Loading…
        </div>
      ) : passes.length === 0 ? (
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          No passes yet.
        </div>
      ) : (
        <div className="table-wrap" style={{ marginTop: 4 }}>
          <table style={{ width: "100%", fontSize: "0.74rem" }}>
            <thead>
              <tr style={{ color: "var(--subtext)", textAlign: "left" }}>
                <th style={{ padding: "4px 6px", width: 50 }}>#</th>
                <th style={{ padding: "4px 6px" }}>Note</th>
                <th style={{ padding: "4px 6px", width: 130 }}>Expires</th>
                <th style={{ padding: "4px 6px", width: 100 }}>Status</th>
                <th style={{ padding: "4px 6px", width: 80 }}></th>
              </tr>
            </thead>
            <tbody>
              {passes.map((p) => {
                const status = p.isRevoked
                  ? { label: "Revoked", color: "var(--red)" }
                  : p.isExpired
                    ? { label: "Expired", color: "var(--subtext)" }
                    : { label: "Active", color: "var(--green)" };
                return (
                  <tr
                    key={p.id}
                    style={{ borderTop: "1px solid var(--border-dim)" }}
                  >
                    <td
                      style={{
                        padding: "4px 6px",
                        fontFamily: "var(--mono)",
                        color: "var(--subtext)",
                      }}
                    >
                      {p.id}
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      {p.note || <span className="muted">— no note —</span>}
                    </td>
                    <td
                      style={{ padding: "4px 6px", fontFamily: "var(--mono)" }}
                    >
                      {fmtPassExpiry(p.expiresAtEpoch)}
                    </td>
                    <td
                      style={{
                        padding: "4px 6px",
                        color: status.color,
                        fontWeight: 600,
                      }}
                    >
                      {status.label}
                    </td>
                    <td style={{ padding: "4px 6px", textAlign: "right" }}>
                      {p.isActive && (
                        <button
                          className="button"
                          onClick={() => revoke(p.id)}
                          style={{
                            fontSize: "0.68rem",
                            padding: "2px 8px",
                            borderColor: "var(--red)",
                            color: "var(--red)",
                          }}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
