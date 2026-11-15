"use client";

/** /auction/reset?token=… — set a new auction password from a one-time link. */
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Banner, Button, Field, Input, PageHeader, Panel } from "@/components/ds";
import { auctionFetch } from "@/lib/auction-client";
import styles from "../auction.module.css";

function ResetInner() {
  const token = useSearchParams().get("token") || "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (pw !== pw2) return setErr("Passwords do not match.");
    setBusy(true);
    setErr(null);
    try {
      await auctionFetch("/auth/reset", { method: "POST", body: { token, password: pw } });
      window.location.href = "/auction";
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader className={styles.hero} eyebrow="Rookie auction" title="Set a new password" />
      <Panel className={styles.narrow} title="New Chase Upside auction password" subtitle="Signing in elsewhere stops working once you save.">
        <form onSubmit={submit} className={styles.col}>
          <Field label="New password" hint="At least 10 characters. Not your Sleeper password.">
            <Input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={10} required />
          </Field>
          <Field label="Confirm">
            <Input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} minLength={10} required />
          </Field>
          {err ? <Banner tone="negative">{err}</Banner> : null}
          <div>
            <Button type="submit" variant="primary" loading={busy}>
              Save password
            </Button>
          </div>
        </form>
      </Panel>
    </section>
  );
}

export default function AuctionResetPage() {
  return (
    <Suspense fallback={null}>
      <ResetInner />
    </Suspense>
  );
}
