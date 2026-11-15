"use client";

/**
 * /auction/join?token=… — claim a commissioner-issued seat invitation.
 *
 * The token is single-use and expiring; it, not the username, is what binds
 * a person to a seat.  We ask for a handle (normally the Sleeper username)
 * and a NEW Chase Upside password — never a Sleeper password.
 */
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Banner, Button, Field, Input, PageHeader, Panel } from "@/components/ds";
import { auctionFetch } from "@/lib/auction-client";
import styles from "../auction.module.css";

function JoinInner() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [invite, setInvite] = useState(null);
  const [me, setMe] = useState(null);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({ handle: "", password: "", confirm: "", displayName: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [inv, who] = await Promise.all([
          auctionFetch(`/invites/peek?token=${encodeURIComponent(token)}`),
          auctionFetch("/auth/me"),
        ]);
        setInvite(inv);
        setMe(who);
        if (inv.intendedHandle) setForm((f) => ({ ...f, handle: inv.intendedHandle }));
      } catch (x) {
        setErr(x.message);
      }
    })();
  }, [token]);

  const claim = async (e) => {
    e.preventDefault();
    if (!me?.user && form.password !== form.confirm) {
      setErr("Passwords do not match.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await auctionFetch("/invites/claim", {
        method: "POST",
        body: me?.user ? { token } : { token, handle: form.handle, password: form.password, displayName: form.displayName || form.handle },
      });
      window.location.href = `/auction/${encodeURIComponent(invite.roomId)}`;
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader className={styles.hero} eyebrow="Rookie auction" title="Join the auction room" />
      {err ? <Banner tone="negative">{err}</Banner> : null}
      {invite ? (
        <Panel
          className={styles.narrow}
          title={invite.seat ? `Claim ${invite.seat.name}` : "Join as an observer"}
          subtitle={`${invite.roomName} · ${invite.roomType === "mock" ? "Mock room" : "Official room"}`}
        >
          <form onSubmit={claim} className={styles.col}>
            {me?.user ? (
              <p>
                You are signed in as <strong>{me.user.handle}</strong>. Claiming adds this seat to that account.
              </p>
            ) : (
              <>
                <Field label="Handle" hint="Your Sleeper username is a good choice. It is only a login name.">
                  <Input autoComplete="username" value={form.handle} onChange={set("handle")} required readOnly={Boolean(invite.intendedHandle)} />
                </Field>
                <Field label="Display name">
                  <Input value={form.displayName} onChange={set("displayName")} maxLength={60} />
                </Field>
                <Field label="New Chase Upside password" hint="At least 10 characters. Do NOT reuse your Sleeper password.">
                  <Input type="password" autoComplete="new-password" value={form.password} onChange={set("password")} minLength={10} required />
                </Field>
                <Field label="Confirm password">
                  <Input type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} minLength={10} required />
                </Field>
              </>
            )}
            <div>
              <Button type="submit" variant="primary" loading={busy}>
                {invite.seat ? "Claim seat" : "Join"}
              </Button>
            </div>
          </form>
        </Panel>
      ) : null}
    </section>
  );
}

export default function AuctionJoinPage() {
  return (
    <Suspense fallback={null}>
      <JoinInner />
    </Suspense>
  );
}
