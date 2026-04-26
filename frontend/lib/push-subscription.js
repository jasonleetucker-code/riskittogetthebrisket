"use client";

/**
 * push-subscription — small client-side helper for opting into Web Push
 *
 * Flow when a user opts in:
 *   1. Fetch the VAPID public key from /api/push/public-key (cached
 *      by the SW for an hour, so this is usually a no-network call
 *      after the first request).
 *   2. Register the service worker if not already controlling the page.
 *   3. Call `Notification.requestPermission()` — the browser blocks
 *      if the user has previously denied; we surface that as an error.
 *   4. Call `pushManager.subscribe({applicationServerKey})`.
 *   5. POST the resulting subscription JSON to /api/push/subscribe so
 *      the backend can target this device on the next signal alert.
 *
 * Opt-out is the inverse: unsubscribe locally, then POST the endpoint
 * to /api/push/unsubscribe so we don't keep a dead record around.
 */

function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i);
  return arr;
}

export function isPushSupported() {
  if (typeof window === "undefined") return false;
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

async function fetchPublicKey() {
  const res = await fetch("/api/push/public-key", { cache: "default" });
  if (!res.ok) throw new Error(`public_key_unavailable_${res.status}`);
  const json = await res.json();
  if (!json?.publicKey) throw new Error("public_key_missing");
  return json.publicKey;
}

async function ensureRegistration() {
  if (!("serviceWorker" in navigator)) {
    throw new Error("service_worker_unsupported");
  }
  const reg =
    (await navigator.serviceWorker.getRegistration("/")) ||
    (await navigator.serviceWorker.register("/sw.js", { scope: "/" }));
  await navigator.serviceWorker.ready;
  return reg;
}

export async function getCurrentSubscription() {
  if (!isPushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

export async function subscribe() {
  if (!isPushSupported()) {
    throw new Error("push_unsupported");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(`permission_${permission}`);
  }

  const publicKey = await fetchPublicKey();
  const reg = await ensureRegistration();

  let sub = await reg.pushManager.getSubscription();
  if (sub) {
    const sk = sub.options?.applicationServerKey;
    let bytes = null;
    try {
      bytes = sk ? new Uint8Array(sk) : null;
    } catch {
      bytes = null;
    }
    const expected = urlBase64ToUint8Array(publicKey);
    const matches =
      bytes &&
      bytes.length === expected.length &&
      bytes.every((v, i) => v === expected[i]);
    if (!matches) {
      try {
        await sub.unsubscribe();
      } catch {
        /* ignore */
      }
      sub = null;
    }
  }

  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
  }

  const payload = sub.toJSON();
  const ua =
    (typeof navigator !== "undefined" && navigator.userAgent) || "";
  const res = await fetch("/api/push/subscribe", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, ua }),
  });
  if (!res.ok) {
    throw new Error(`subscribe_${res.status}`);
  }
  return sub;
}

export async function unsubscribe() {
  const sub = await getCurrentSubscription();
  if (!sub) return false;
  const endpoint = sub.endpoint;
  try {
    await sub.unsubscribe();
  } catch {
    /* ignore */
  }
  try {
    await fetch("/api/push/unsubscribe", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint }),
    });
  } catch {
    /* best-effort; if the network is down the server will prune on
       its own next time the endpoint returns 404/410 */
  }
  return true;
}
