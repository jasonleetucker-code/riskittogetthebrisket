"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";

export default function SharpIdentityReviewPage() {
  const [platform, setPlatform] = useState("all");
  const [status, setStatus] = useState("open");
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ platform, status, limit: "500" });
      const response = await fetch(`/api/sharp/review?${params}`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
      setPayload(body);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }, [platform, status]);

  useEffect(() => { load(); }, [load]);

  async function decide(candidateId, decision) {
    const reason = window.prompt(`Reason for ${decision} (optional):`) || "";
    setBusy(candidateId);
    try {
      const response = await fetch(`/api/sharp/review/${encodeURIComponent(candidateId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, reason }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const candidates = payload?.candidates || [];
  return (
    <section>
      <PageHeader
        title="Sharp Identity Review"
        subtitle="Approve only corroborated public platform identities. Username resemblance alone remains unresolved."
      />
      <div style={{ marginBottom: 10 }}><Link href="/market/sharp-people">← Sharp people</Link></div>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end" }}>
          <label>Platform<br /><select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="all">All</option><option value="sleeper">Sleeper</option><option value="ffpc">FFPC</option></select></label>
          <label>Status<br /><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="open">Open review</option><option value="all">All</option><option value="high_confidence_probable">High-confidence probable</option><option value="possible">Possible</option><option value="unresolved">Unresolved</option><option value="conflict">Conflict</option><option value="rejected_match">Rejected</option></select></label>
          <button type="button" onClick={load}>Refresh</button>
          <div className="muted">{payload?.total ?? "—"} candidates</div>
        </div>
      </div>
      {error ? <div className="card" style={{ marginBottom: 12 }}><EmptyState title="Identity review error" message={error} /></div> : null}
      {!payload && !error ? <LoadingState message="Loading identity candidates…" /> : null}
      {payload && !candidates.length ? <div className="card"><EmptyState title="No candidates in this queue" /></div> : null}
      <div style={{ display: "grid", gap: 10 }}>
        {candidates.map((candidate) => (
          <article key={candidate.candidate_id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 230 }}>
                <strong>{candidate.public_display_name || candidate.canonical_name}</strong>
                <div className="muted" style={{ fontSize: "0.68rem" }}>
                  {candidate.primary_public_handle || "No handle"} · {candidate.current_affiliation || "No affiliation"}
                </div>
                <p>
                  <strong>{String(candidate.platform).toUpperCase()}</strong> · {candidate.candidate_username || candidate.candidate_team_or_entry_name || candidate.candidate_display_name || "Unnamed candidate"}
                </p>
                <div className="muted" style={{ fontSize: "0.68rem", lineHeight: 1.5 }}>
                  Status: {candidate.verification_status} · confidence {Math.round((candidate.confidence || 0) * 100)}% · method {candidate.candidate_generation_method}
                  {candidate.evidence_url ? <> · <a href={candidate.evidence_url} target="_blank" rel="noreferrer">evidence</a></> : null}
                </div>
                {(candidate.supports || []).length ? <div>Supports: {(candidate.supports || []).join("; ")}</div> : null}
                {(candidate.contradicts || []).length ? <div>Contradicts: {(candidate.contradicts || []).join("; ")}</div> : null}
              </div>
              <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
                <button type="button" disabled={busy === candidate.candidate_id || !candidate.candidate_platform_user_id && !candidate.observed_manager_key} onClick={() => decide(candidate.candidate_id, "approve")}>Approve</button>
                <button type="button" disabled={busy === candidate.candidate_id} onClick={() => decide(candidate.candidate_id, "reject")}>Reject</button>
                <button type="button" disabled={busy === candidate.candidate_id} onClick={() => decide(candidate.candidate_id, "unresolved")}>Leave unresolved</button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
