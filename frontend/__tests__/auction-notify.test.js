import fs from "node:fs";
import path from "node:path";
import * as url from "node:url";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

import { describeDelivery, detectPlatform } from "../lib/auction-notify.js";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");
const SW = fs.readFileSync(path.join(ROOT, "public", "sw.js"), "utf8");

function win(standalone) {
  return { matchMedia: () => ({ matches: standalone }), PushManager: function () {}, Notification: function () {} };
}

describe("detectPlatform", () => {
  const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile/15E148 Safari/604.1";
  it("iPhone Safari needs Add to Home Screen", () => {
    const p = detectPlatform({ userAgent: iphone, serviceWorker: {} }, win(false));
    expect(p.kind).toBe("ios-browser");
    expect(p.iosTooOld).toBe(false);
  });
  it("iPhone Home Screen app", () => {
    expect(detectPlatform({ userAgent: iphone, serviceWorker: {} }, win(true)).kind).toBe("ios-homescreen");
  });
  it("old iOS is flagged", () => {
    const old = iphone.replace("17_4", "16_2");
    expect(detectPlatform({ userAgent: old, serviceWorker: {} }, win(false)).iosTooOld).toBe(true);
  });
  it("Android Chrome does not require installation", () => {
    const p = detectPlatform({ userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/128 Mobile", serviceWorker: {} }, win(false));
    expect(p.kind).toBe("android");
    expect(p.pushCapable).toBe(true);
  });
});

describe("delivery wording never claims the phone displayed it", () => {
  it("'sent' is described as accepted by the push service", () => {
    expect(describeDelivery("sent")).toMatch(/Accepted by the push service/);
    expect(describeDelivery("sent")).toMatch(/not proof/);
  });
});

function loadSW() {
  const listeners = {};
  const self = {
    addEventListener: (n, h) => {
      listeners[n] = h;
    },
    clients: { claim: vi.fn(), matchAll: vi.fn(async () => []), openWindow: vi.fn(async () => {}) },
    location: { origin: "https://chaseupside.com" },
    registration: { showNotification: vi.fn(async () => {}) },
    skipWaiting: vi.fn(),
  };
  vm.runInNewContext(SW, { URL, caches: { open: vi.fn(), keys: vi.fn(async () => []), match: vi.fn() }, fetch: vi.fn(), self, setTimeout, clearTimeout });
  return { listeners, self };
}

describe("service worker notification taps open only same-origin paths", () => {
  it.each([
    ["/auction/r_1", "/auction/r_1"],
    ["https://evil.example.com/x", "/"],
    ["//evil.example.com/x", "/"],
    ["javascript:alert(1)", "/"],
    ["/\t/evil.example.com", "/"],
    ["/\\evil.example.com", "/"],
    ["/auction/r_1?x=1#lot", "/auction/r_1?x=1#lot"],
    [undefined, "/"],
  ])("%s → %s", async (given, expected) => {
    const { listeners, self } = loadSW();
    let waited;
    listeners.notificationclick({ notification: { close() {}, data: { url: given } }, waitUntil: (p) => (waited = p) });
    await waited;
    expect(self.clients.openWindow).toHaveBeenCalledWith(expected);
  });

  it("push shows a visible notification with the event timestamp", async () => {
    const { listeners, self } = loadSW();
    let waited;
    listeners.push({
      data: { json: () => ({ title: "Outbid: X", body: "b", url: "https://evil.example.com", tag: "t", ts: 1790000000000 }) },
      waitUntil: (p) => (waited = p),
    });
    await waited;
    const [, opts] = self.registration.showNotification.mock.calls[0];
    expect(opts.data.url).toBe("/");
    expect(opts.timestamp).toBe(1790000000000);
  });
});
