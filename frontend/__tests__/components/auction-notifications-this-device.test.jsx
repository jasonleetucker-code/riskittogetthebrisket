// 2026-11-16 verified sweep: phone alerts must identify THIS device by its id.
//
// The page called "this device" the first live device on the account whenever
// this browser held any subscription.  With two phones, "Send a test" went to
// the other phone and "linked" described a device that was not this one.  The
// device list carries no endpoint, so this browser is the device whose id the
// server returned when this browser's own subscription was registered.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

const notify = vi.hoisted(() => ({
  registration: { deviceId: 7 },
  subscription: { endpoint: "https://push.example/this-browser" },
  devices: [],
  test: null,
}));

vi.mock("@/lib/auction-notify", () => ({
  currentSubscription: () => Promise.resolve(notify.subscription),
  describeDelivery: (s) => s,
  detectPlatform: () => ({ kind: "android", pushCapable: true }),
  disablePushHere: () => Promise.resolve(),
  enablePush: () => Promise.resolve(notify.registration),
  permissionState: () => "granted",
  refreshBinding: () => Promise.resolve(notify.registration),
  notifyApi: {
    state: () =>
      Promise.resolve({
        devices: notify.devices,
        labels: {},
        prefs: {},
        pushConfigured: true,
        publicKey: "k",
        recent: [],
        email: null,
      }),
    test: (...args) => notify.test(...args),
    confirm: () => Promise.resolve({}),
  },
}));

import AuctionNotificationsPage from "@/app/auction/notifications/page.jsx";
import { findThisDevice, thisDeviceId } from "@/app/auction/notifications/this-device";

const OTHER_PHONE = { id: 9, label: "Other phone", live: true };
const THIS_PHONE = { id: 7, label: "This phone", live: true };

function subscribedRow() {
  const dt = screen.getByText("Subscribed");
  return dt.nextElementSibling;
}

afterEach(() => {
  notify.registration = { deviceId: 7 };
  notify.subscription = { endpoint: "https://push.example/this-browser" };
  notify.devices = [];
});

describe("phone alerts: this device is identified by its own id", () => {
  it("sends the test to THIS device even when another live device is listed first", async () => {
    notify.devices = [OTHER_PHONE, THIS_PHONE];
    notify.test = vi.fn().mockResolvedValue({ outboxIds: [101] });
    render(<AuctionNotificationsPage />);

    await waitFor(() => expect(subscribedRow().textContent).toBe("Yes — linked to your account"));
    const send = screen.getByRole("button", { name: "Send a test" });
    expect(send).not.toBeDisabled();
    fireEvent.click(send);
    await waitFor(() => expect(notify.test).toHaveBeenCalledTimes(1));
    expect(notify.test).toHaveBeenCalledWith(7);

    const thisRow = screen.getByText("This phone").closest("tr");
    expect(within(thisRow).getByText("This device")).toBeInTheDocument();
    const otherRow = screen.getByText("Other phone").closest("tr");
    expect(within(otherRow).queryByText("This device")).not.toBeInTheDocument();
  });

  it("does not call this browser linked, or send a test elsewhere, when only ANOTHER device is live", async () => {
    notify.registration = null; // this browser's binding was not confirmed by the server
    notify.devices = [OTHER_PHONE];
    notify.test = vi.fn().mockResolvedValue({ outboxIds: [102] });
    render(<AuctionNotificationsPage />);

    await waitFor(() => expect(subscribedRow().textContent).toBe("Browser subscribed, not linked"));
    const send = screen.getByRole("button", { name: "Send a test" });
    expect(send).toBeDisabled();
    fireEvent.click(send);
    expect(notify.test).not.toHaveBeenCalled();
  });

  it("is not linked when this device's own row is signed out, even if another device is live", async () => {
    notify.devices = [OTHER_PHONE, { ...THIS_PHONE, live: false, disabled_reason: "signed_out" }];
    notify.test = vi.fn();
    render(<AuctionNotificationsPage />);
    await waitFor(() => expect(subscribedRow().textContent).toBe("Browser subscribed, not linked"));
    expect(screen.getByRole("button", { name: "Send a test" })).toBeDisabled();
  });

  it("says No when this browser holds no subscription at all", async () => {
    notify.subscription = null;
    notify.devices = [OTHER_PHONE];
    notify.test = vi.fn();
    render(<AuctionNotificationsPage />);
    await waitFor(() => expect(subscribedRow().textContent).toBe("No"));
    expect(screen.getByRole("button", { name: "Send a test" })).toBeDisabled();
  });
});

describe("this-device helpers", () => {
  it("reads only an integer deviceId from the registration answer", () => {
    expect(thisDeviceId({ deviceId: 7 })).toBe(7);
    expect(thisDeviceId({ deviceId: "7" })).toBeNull();
    expect(thisDeviceId(null)).toBeNull();
  });

  it("never falls back to the first live device", () => {
    const devices = [OTHER_PHONE, THIS_PHONE];
    expect(findThisDevice(devices, 7, { endpoint: "x" })).toBe(THIS_PHONE);
    expect(findThisDevice(devices, null, { endpoint: "x" })).toBeNull();
    expect(findThisDevice(devices, 7, null)).toBeNull();
    expect(findThisDevice(devices, 42, { endpoint: "x" })).toBeNull();
  });
});
