"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";

export default function SharpPersonPage({ params }) {
  const [personId, setPersonId] = useState(null);
  const [person, setPerson] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.resolve(params).then((resolved) => setPersonId(resolved.personId));
  }, [params]);

  useEffect(() => {
    if (!personId) return;
    fetch(`/api/sharp/people/${encodeURIComponent(personId)}`, { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
        setPerson(body);
      })
      .catch((err) => setError(apiErrorMessage(err)));
  }, [personId]);

  if (error) return <section><PageHeader title="Sharp profile" /><div className="card"><EmptyState title="Profile unavailable" message={error} /></div></section>;
  if (!person) return <LoadingState message="Loading Sharp profile…" />;

  return (
    <section>
      <PageHeader
        title={person.public_display_name || person.canonical_name}
        subtitle={[person.primary_public_handle, person.current_affiliation].filter(Boolean).join(" · ")}
      />
      <div style={{ marginBottom: 10 }}><Link href="/market/sharp-people">← All Sharp people</Link></div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 14 }}>
          <div><span className="muted">Membership</span><br /><strong>{person.membership_state}</strong></div>
          <div><span className="muted">Curated expertise</span><br /><strong>{person.curated_expertise_score ?? "—"}</strong></div>
          <div><span className="muted">Trackability</span><br /><strong>{person.trackability_score ?? "—"}</strong></div>
          <div><span className="muted">Data completeness</span><br /><strong>{person.performanceMetrics?.[0]?.data_completeness == null ? "Unknown" : `${Math.round(person.performanceMetrics[0].data_completeness * 100)}%`}</strong></div>
        </div>
        <p className="muted" style={{ lineHeight: 1.55 }}>{person.why_included || person.evidence_of_skill || person.candidate_status}</p>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <h3>Verified public identities</h3>
        {(person.verifiedPlatformIdentities || []).length ? (
          <div style={{ display: "grid", gap: 8 }}>
            {person.verifiedPlatformIdentities.map((account) => (
              <div key={account.account_id}>
                <strong>{String(account.platform).toUpperCase()}</strong> · {account.username || account.display_name || account.platform_user_id}
                <div className="muted" style={{ fontSize: "0.68rem" }}>
                  {account.verification_method} · confidence {Math.round((account.verification_confidence || 0) * 100)}%
                </div>
              </div>
            ))}
          </div>
        ) : <div className="muted">No verified fantasy-platform identity. Curated membership is still retained.</div>}
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <h3>Empirical dynasty performance</h3>
        {(person.performanceMetrics || []).length ? person.performanceMetrics.map((metric) => (
          <div key={metric.metric_id} style={{ marginBottom: 8 }}>
            {metric.league_type} · {metric.seasons_observed ?? "?"} seasons · win rate {metric.winning_percentage == null ? "unknown" : `${(metric.winning_percentage * 100).toFixed(1)}%`} · championships {metric.championships ?? "unknown"}
          </div>
        )) : <div className="muted">No measurable platform history is linked. No neutral win rate or synthetic championship record is assigned.</div>}
      </div>

      <div className="card">
        <h3>Public evidence</h3>
        <div style={{ display: "grid", gap: 8 }}>
          {(person.evidence || []).map((evidence, index) => (
            <div key={`${evidence.source_url || "evidence"}-${index}`}>
              {evidence.source_url ? <a href={evidence.source_url} target="_blank" rel="noreferrer">{evidence.description || evidence.source_url}</a> : evidence.description}
              <div className="muted" style={{ fontSize: "0.68rem" }}>{evidence.evidence_type}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
