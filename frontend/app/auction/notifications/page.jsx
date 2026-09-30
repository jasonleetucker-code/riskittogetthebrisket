"use client";

/**
 * /auction/notifications — phone alerts for the auction room (AUC-002).
 *
 * Native Web Push from Chase Upside itself: no extra app, no SMS, no
 * subscription.  "Accepted by the push service" is never presented as
 * "your phone showed it" — the test asks the person to confirm.
 */
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Badge, Banner, Button, Field, Input, PageHeader, Panel } from "@/components/ds";
import { formatRoomTime } from "@/lib/auction-client";
import {
  currentSubscription,
  describeDelivery,
  detectPlatform,
  disablePushHere,
  enablePush,
  notifyApi,
  permissionState,
  refreshBinding,
} from "@/lib/auction-notify";
import styles from "../auction.module.css";

function SetupSteps({ platform }) {
  if (platform.kind === "ios-browser") {
    return (
      <ol className={styles.rules}>
        {platform.iosTooOld ? <li>This iPhone needs iOS 16.4 or newer for web notifications. Update iOS first.</li> : null}
        <li>
          In Safari, tap the <strong>Share</strong> button, then <strong>Add to Home Screen</strong>, then <strong>Add</strong>.
        </li>
        <li>
          Close Safari and open <strong>Chase Upside</strong> from the new Home Screen icon.
        </li>
        <li>
          In that app, open the auction room and <strong>sign in again</strong> (the Home Screen app keeps its own sign-in).
        </li>
        <li>
          Come back to this page inside the app and tap <strong>Turn on notifications</strong>, then <strong>Allow</strong>.
        </li>
      </ol>
    );
  }
  if (platform.kind === "ios-homescreen") {
    return <p>You are in the Home Screen app. Tap <strong>Turn on notifications</strong> below, then <strong>Allow</strong>.</p>;
  }
  if (platform.kind === "android") {
    return (
      <ol className={styles.rules}>
        <li>
          Tap <strong>Turn on notifications</strong> below, then <strong>Allow</strong>.
        </li>
        <li>Optional: Chrome menu → <strong>Add to Home screen</strong> for a one-tap icon. It is not required for notifications.</li>
      </ol>
    );
  }
  return <p>Tap <strong>Turn on notifications</strong> and allow them. For your phone, open this page on the phone itself.</p>;
}

function Recovery({ platform }) {
  return (
    <ul className={styles.rules}>
      {platform.kind.startsWith("ios") ? (
        <li>
          Blocked or stopped on iPhone: <strong>Settings → Notifications → Chase Upside</strong> → Allow Notifications. If Chase Upside is not
          listed, delete the Home Screen icon and repeat the setup steps.
        </li>
      ) : (
        <li>
          Blocked in Chrome: tap the icon left of the address → <strong>Permissions → Notifications → Allow</strong>, then reload and turn on
          again.
        </li>
      )}
      <li>Signing out of the auction room turns alerts off on this device. Sign back in here and tap Turn on notifications again.</li>
      <li>Nothing arrives? Send a test. If the status says accepted but nothing appears, check Focus / Do Not Disturb and battery saver.</li>
      <li>Every alert is also kept in your in-app inbox, so nothing depends on a notification arriving.</li>
    </ul>
  );
}

function NotificationsInner() {
  const params = useSearchParams();
  const [platform, setPlatform] = useState({ kind: "unknown", pushCapable: false });
  const [perm, setPerm] = useState("default");
  const [hereSub, setHereSub] = useState(null);
  const [state, setState] = useState(null);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lastTest, setLastTest] = useState(null);
  const [email, setEmail] = useState("");

  const load = useCallback(async () => {
    try {
      setState(await notifyApi.state());
      setErr(null);
    } catch (x) {
      setErr(x.status === 401 ? "Sign in to the auction room first." : x.message);
    }
    setPerm(permissionState());
    setHereSub(await currentSubscription().catch(() => null));
  }, []);

  useEffect(() => {
    setPlatform(detectPlatform());
    refreshBinding().finally(load);
  }, [load]);

  useEffect(() => {
    const token = params.get("verify");
    if (!token) return;
    notifyApi
      .verifyEmail(token)
      .then(() => {
        setMsg({ tone: "positive", text: "Email verified. You can now turn on email backup." });
        load();
      })
      .catch((x) => setMsg({ tone: "negative", text: x.message }));
  }, [params, load]);

  const run = async (fn, ok) => {
    setBusy(true);
    setMsg(null);
    try {
      const out = await fn();
      if (ok) setMsg({ tone: "positive", text: typeof ok === "function" ? ok(out) : ok });
      await load();
      return out;
    } catch (x) {
      setMsg({ tone: "negative", text: x.message });
      return null;
    } finally {
      setBusy(false);
    }
  };

  const hereDevice = state?.devices?.find((d) => d.live && hereSub);
  const prefsOrder = state ? Object.keys(state.labels) : [];

  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow="Rookie auction"
        title="Phone alerts"
        description="Chase Upside sends alerts straight to your phone's normal notifications. No extra app, no text-message plan, nothing to pay for."
        actions={
          <Button variant="ghost" as={Link} href="/auction">
            Auction rooms
          </Button>
        }
      />
      {err ? <Banner tone="negative">{err}</Banner> : null}
      {msg ? <Banner tone={msg.tone}>{msg.text}</Banner> : null}
      {state && !state.pushConfigured ? (
        <Banner tone="warning" title="Push is not configured on this server">
          Your inbox still records every alert. Phone delivery starts once the server has its notification keys.
        </Banner>
      ) : null}

      <div className={styles.grid}>
        <div className={styles.col}>
          <Panel title="This device">
            <dl className={styles.ledger}>
              <dt>Detected</dt>
              <dd>{{ "ios-homescreen": "iPhone Home Screen app", "ios-browser": "iPhone Safari", android: "Android", desktop: "Computer" }[platform.kind] || "Unknown"}</dd>
              <dt>Permission</dt>
              <dd>{{ granted: "Allowed", denied: "Blocked", default: "Not asked yet", unsupported: "Not supported here" }[perm]}</dd>
              <dt>Subscribed</dt>
              <dd>{hereSub ? (hereDevice ? "Yes — linked to your account" : "Browser subscribed, not linked") : "No"}</dd>
            </dl>
            <SetupSteps platform={platform} />
            <div className={styles.row}>
              <Button
                variant="primary"
                disabled={busy || !platform.pushCapable || platform.kind === "ios-browser"}
                onClick={() => run(() => enablePush(state?.publicKey), "Notifications are on for this device. Send a test to check it.")}
              >
                Turn on notifications
              </Button>
              <Button
                disabled={busy || !state?.devices?.some((d) => d.live)}
                onClick={() =>
                  run(
                    async () => {
                      const out = await notifyApi.test(hereDevice?.id);
                      setLastTest(out.outboxIds?.[0] ?? null);
                      return out;
                    },
                    "Test sent. Check the phone, then answer below.",
                  )
                }
              >
                Send a test
              </Button>
              {hereSub ? (
                <Button variant="ghost" disabled={busy} onClick={() => run(disablePushHere, "Alerts are off on this device.")}>
                  Turn off here
                </Button>
              ) : null}
            </div>
            {lastTest != null ? (
              <div className={styles.row}>
                <span>Did the test notification appear on your device?</span>
                <Button size="sm" onClick={() => run(() => notifyApi.confirm(lastTest, true), "Thanks — recorded as seen on the device.").then(() => setLastTest(null))}>
                  Yes, I saw it
                </Button>
                <Button size="sm" variant="ghost" onClick={() => run(() => notifyApi.confirm(lastTest, false), "Recorded as not seen. See the recovery steps.").then(() => setLastTest(null))}>
                  No
                </Button>
              </div>
            ) : null}
          </Panel>

          <Panel title="What to alert me about" subtitle="Low-noise defaults. Messages never include anyone's maximum bid.">
            <div className={styles.col}>
              {prefsOrder.map((k) => (
                <label key={k} className={styles.row}>
                  <input
                    type="checkbox"
                    checked={Boolean(state.prefs[k])}
                    disabled={busy || (k === "email_backup" && !state.email?.verified)}
                    onChange={(e) => run(() => notifyApi.prefs({ [k]: e.target.checked }))}
                  />
                  {state.labels[k]}
                </label>
              ))}
            </div>
          </Panel>

          <Panel title="Email backup (optional)" subtitle="Only if you turn it on. Never text messages.">
            <p className={styles.muted}>
              {state?.email ? `${state.email.address} — ${state.email.verified ? "verified" : "not verified yet"}` : "No email on file."}
            </p>
            <div className={styles.row}>
              <Field label="Email address">
                <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <Button disabled={busy || !email} onClick={() => run(() => notifyApi.email(email), "Verification email sent. Open the link while signed in.")}>
                Send verification link
              </Button>
            </div>
          </Panel>
        </div>

        <div className={styles.col}>
          <Panel title="Your devices" dense flush>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Device</th>
                    <th scope="col">State</th>
                    <th scope="col">Last accepted</th>
                  </tr>
                </thead>
                <tbody>
                  {(state?.devices || []).map((d) => (
                    <tr key={d.id}>
                      <td>{d.label || d.platform || `Device ${d.id}`}</td>
                      <td>{d.live ? <Badge tone="positive">Active</Badge> : <Badge>{d.disabled_reason || "signed out"}</Badge>}</td>
                      <td>{d.last_ok_at ? formatRoomTime(d.last_ok_at) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel title="Recent deliveries" dense flush>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Alert</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(state?.recent || []).map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.title}
                        <span className={styles.sub}>{r.channel}</span>
                      </td>
                      <td>{describeDelivery(r.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel title="If alerts stop" dense>
            <Recovery platform={platform} />
          </Panel>
        </div>
      </div>
    </section>
  );
}

export default function AuctionNotificationsPage() {
  return (
    <Suspense fallback={null}>
      <NotificationsInner />
    </Suspense>
  );
}
