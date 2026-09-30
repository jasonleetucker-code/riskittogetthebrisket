/**
 * Rookie auction room — phone notifications client (AUC-002).
 *
 * Native, standards-based Web Push through the site's existing service
 * worker and VAPID key.  No extra app on the phone, no SMS.  Reuses the
 * shared helpers in lib/push-subscription.js; the server binds each browser
 * subscription to the signed-in AUCTION account + session.
 */
"use client";

import { ensureRegistration, urlBase64ToUint8Array } from "@/lib/push-subscription";
import { auctionFetch } from "@/lib/auction-client";

/** What kind of device/browser is this, for setup instructions. */
export function detectPlatform(nav = typeof navigator !== "undefined" ? navigator : null, win = typeof window !== "undefined" ? window : null) {
  if (!nav || !win) return { kind: "unknown", standalone: false, pushCapable: false };
  const ua = nav.userAgent || "";
  const isIOS = /iPhone|iPad|iPod/i.test(ua) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const standalone =
    Boolean(win.matchMedia && win.matchMedia("(display-mode: standalone)").matches) || nav.standalone === true;
  const pushCapable = "serviceWorker" in nav && "PushManager" in win && "Notification" in win;
  let iosVersion = null;
  const m = ua.match(/OS (\d+)_(\d+)/);
  if (isIOS && m) iosVersion = Number(m[1]) + Number(m[2]) / 100;
  let kind = "desktop";
  if (isIOS) kind = standalone ? "ios-homescreen" : "ios-browser";
  else if (isAndroid) kind = "android";
  return { kind, standalone, pushCapable, iosVersion, iosTooOld: isIOS && iosVersion != null && iosVersion < 16.4 };
}

export function permissionState() {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  return Notification.permission; // "default" | "granted" | "denied"
}

export async function currentSubscription() {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  if (!reg || !reg.pushManager) return null;
  return reg.pushManager.getSubscription();
}

function deviceLabel(p) {
  return { "ios-homescreen": "iPhone (Home Screen app)", "ios-browser": "iPhone Safari", android: "Android", desktop: "Computer" }[p.kind] || "Device";
}

/**
 * Must be called from a tap/click (iOS requires a user gesture for the
 * permission prompt).  Returns {deviceId}.
 */
export async function enablePush(publicKey) {
  const platform = detectPlatform();
  if (!platform.pushCapable) throw new Error("This browser cannot receive web notifications here. See the setup steps.");
  if (!publicKey) throw new Error("Push is not configured on the server yet.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") {
    throw new Error(perm === "denied" ? "Notifications are blocked for this site. See recovery steps below." : "Permission was not granted.");
  }
  const reg = await ensureRegistration();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) });
  }
  return auctionFetch("/notify/devices", {
    method: "POST",
    body: { subscription: sub.toJSON(), label: deviceLabel(platform), platform: platform.kind },
  });
}

/** Re-bind an existing subscription to the current session (after sign-in). */
export async function refreshBinding() {
  if (permissionState() !== "granted") return null;
  const sub = await currentSubscription();
  if (!sub) return null;
  const platform = detectPlatform();
  return auctionFetch("/notify/devices", {
    method: "POST",
    body: { subscription: sub.toJSON(), label: deviceLabel(platform), platform: platform.kind },
  }).catch(() => null);
}

export async function disablePushHere() {
  const sub = await currentSubscription();
  if (sub) {
    await auctionFetch("/notify/devices/disable", { method: "POST", body: { endpoint: sub.endpoint } }).catch(() => {});
    await sub.unsubscribe().catch(() => {});
  }
}

export const notifyApi = {
  state: () => auctionFetch("/notify/state"),
  prefs: (patch) => auctionFetch("/notify/prefs", { method: "POST", body: { prefs: patch } }),
  test: (deviceId) => auctionFetch("/notify/test", { method: "POST", body: deviceId ? { deviceId } : {} }),
  confirm: (outboxId, seen, note) => auctionFetch("/notify/test/confirm", { method: "POST", body: { outboxId, seen, note } }),
  inbox: (roomId) => auctionFetch(`/notify/inbox${roomId ? `?roomId=${encodeURIComponent(roomId)}` : ""}`),
  markRead: (body) => auctionFetch("/notify/inbox/read", { method: "POST", body }),
  email: (email) => auctionFetch("/notify/email", { method: "POST", body: { email } }),
  verifyEmail: (token) => auctionFetch("/notify/email/verify", { method: "POST", body: { token } }),
  watch: (roomId, auction, on) => auctionFetch(`/rooms/${encodeURIComponent(roomId)}/watch`, { method: "POST", body: { auction, on } }),
};

/** Human wording for delivery states — "accepted" is not "seen". */
export function describeDelivery(status) {
  return (
    {
      pending: "Waiting to send",
      sending: "Sending",
      sent: "Accepted by the push service (not proof it appeared)",
      stale: "Skipped — no longer true when it was due",
      gone: "This device's subscription expired",
      failed: "Failed after retries",
      expired_ttl: "Expired before it could be delivered",
      suppressed_mock: "Mock room — not sent (turn on [MOCK] pushes to receive)",
      suppressed_email: "Email backup off",
      quota_exhausted: "Daily email allowance used",
      device_inactive: "Device signed out or disabled",
    }[status] || status
  );
}
