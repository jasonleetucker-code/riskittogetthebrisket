"use client";

import { useCallback, useEffect, useState } from "react";
import {
  isPushSupported,
  getCurrentSubscription,
  subscribe,
  unsubscribe,
} from "@/lib/push-subscription";

const SUPPORT_HINT_BY_PERMISSION = {
  granted: "",
  denied: "Browser denied push permission. Re-enable it in site settings to receive notifications on this device.",
  default: "",
};

export default function PushNotificationToggle({ enabled }) {
  const [supported, setSupported] = useState(false);
  const [hasSub, setHasSub] = useState(false);
  const [permission, setPermission] = useState("default");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!isPushSupported()) {
      setSupported(false);
      return () => {};
    }
    setSupported(true);
    setPermission(typeof Notification !== "undefined" ? Notification.permission : "default");
    (async () => {
      try {
        const sub = await getCurrentSubscription();
        if (!cancelled) setHasSub(!!sub);
      } catch {
        if (!cancelled) setHasSub(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleEnable = useCallback(async () => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await subscribe();
      setHasSub(true);
      setPermission(Notification.permission);
      setStatus("This device will receive push alerts.");
      setTimeout(() => setStatus(""), 3000);
    } catch (exc) {
      const code = exc?.message || "unknown";
      if (code.startsWith("permission_")) {
        setPermission(code.replace("permission_", ""));
        setError("Push permission was not granted.");
      } else if (code === "public_key_unavailable_503") {
        setError("Push isn't configured on the server yet.");
      } else {
        setError(`Couldn't subscribe (${code}).`);
      }
    } finally {
      setBusy(false);
    }
  }, []);

  const handleDisable = useCallback(async () => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await unsubscribe();
      setHasSub(false);
      setStatus("Push disabled on this device.");
      setTimeout(() => setStatus(""), 3000);
    } catch (exc) {
      setError(`Couldn't unsubscribe (${exc?.message || "unknown"}).`);
    } finally {
      setBusy(false);
    }
  }, []);

  if (!supported) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem" }}>
        This browser doesn&apos;t support web push notifications.
      </p>
    );
  }

  if (!enabled) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem" }}>
        Sign in to enable push notifications.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "0.82rem" }}>Push to this device</strong>
        {hasSub ? (
          <button className="button" onClick={handleDisable} disabled={busy} style={{ fontSize: "0.76rem" }}>
            {busy ? "Working…" : "Disable"}
          </button>
        ) : (
          <button className="button" onClick={handleEnable} disabled={busy} style={{ fontSize: "0.76rem" }}>
            {busy ? "Working…" : "Enable"}
          </button>
        )}
      </div>
      {status && (
        <div className="muted" style={{ fontSize: "0.7rem", color: "var(--green)" }}>
          {status}
        </div>
      )}
      {error && (
        <div className="muted" style={{ fontSize: "0.7rem", color: "var(--red)" }}>
          {error}
        </div>
      )}
      {SUPPORT_HINT_BY_PERMISSION[permission] && (
        <div className="muted" style={{ fontSize: "0.68rem" }}>
          {SUPPORT_HINT_BY_PERMISSION[permission]}
        </div>
      )}
      <p className="muted" style={{ fontSize: "0.68rem", margin: 0 }}>
        Daily digests + custom alerts arrive as system notifications. iOS requires the
        app to be installed to your home screen; Android/desktop work in any browser tab.
      </p>
    </div>
  );
}
