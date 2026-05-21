"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuthContext } from "@/app/AppShellWrapper";
import CallSheet from "@/components/betting/CallSheet";
import BetList from "@/components/betting/BetList";
import RootingDashboard from "@/components/betting/RootingDashboard";
import BettingSettings from "@/components/betting/BettingSettings";

async function getJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail ? ` — ${typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)}` : "";
    throw new Error(`${data?.error || `HTTP ${res.status}`}${detail}`);
  }
  return data;
}

async function sendJson(url, body, method = "POST") {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail ? ` — ${typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)}` : "";
    throw new Error(`${data?.error || `HTTP ${res.status}`}${detail}`);
  }
  return data;
}

export default function BettingPage() {
  const { authenticated } = useAuthContext();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [recs, setRecs] = useState({ recommendations: [], env: "demo", generatedAt: null });
  const [bets, setBets] = useState([]);
  const [settings, setSettings] = useState(null);
  const [rooting, setRooting] = useState([]);

  const refreshBets = useCallback(async () => {
    const [b, r] = await Promise.all([getJson("/api/betting/bets"), getJson("/api/betting/rooting")]);
    setBets(b.bets || []);
    setRooting(r.rooting || []);
  }, []);

  useEffect(() => {
    if (authenticated !== true) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [recData, betData, setData, rootData] = await Promise.all([
          getJson("/api/betting/recommendations"),
          getJson("/api/betting/bets"),
          getJson("/api/betting/settings"),
          getJson("/api/betting/rooting"),
        ]);
        if (cancelled) return;
        setRecs(recData);
        setBets(betData.bets || []);
        setSettings(setData.settings);
        setRooting(rootData.rooting || []);
      } catch (e) {
        if (!cancelled) setError(e?.message || "Failed to load betting data");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authenticated]);

  const onApprove = useCallback(
    async (payload) => {
      await sendJson("/api/betting/bets", payload);
      await refreshBets();
    },
    [refreshBets]
  );

  const onCancel = useCallback(
    async (betId) => {
      await sendJson(`/api/betting/bets/${betId}/cancel`, {});
      await refreshBets();
    },
    [refreshBets]
  );

  const onKill = useCallback(async () => {
    await sendJson("/api/betting/kill", {});
    await refreshBets();
  }, [refreshBets]);

  const onSaveSettings = useCallback(async (patch) => {
    const data = await sendJson("/api/betting/settings", patch, "PUT");
    setSettings(data.settings);
  }, []);

  if (authenticated === false) {
    return (
      <section className="card">
        <h1 className="page-title">Betting</h1>
        <p className="muted text-sm" style={{ marginTop: 4 }}>Sign in to access the betting call sheet.</p>
      </section>
    );
  }

  if (authenticated === null || loading) {
    return (
      <section className="card">
        <h1 className="page-title">Betting</h1>
        <p className="muted text-sm" style={{ marginTop: 4 }}>Loading…</p>
      </section>
    );
  }

  const env = settings?.env || recs?.env || "demo";
  const unitUsd = settings?.unit_usd ?? 5;

  return (
    <section>
      <div className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h1 className="page-title">Betting</h1>
        <p className="muted text-sm" style={{ marginTop: 4 }}>
          Aggregated betting consensus → approve a bet → it rests on Kalshi until your price hits.
        </p>
      </div>

      {error ? (
        <div className="card text-red text-sm" style={{ marginBottom: "var(--space-md)" }}>{error}</div>
      ) : null}

      <RootingDashboard rooting={rooting} />
      <CallSheet
        recommendations={recs.recommendations}
        env={env}
        unitUsd={unitUsd}
        generatedAt={recs.generatedAt}
        onApprove={onApprove}
      />
      <BetList bets={bets} onCancel={onCancel} onKill={onKill} />
      {settings ? <BettingSettings settings={settings} env={env} onSave={onSaveSettings} /> : null}
    </section>
  );
}
