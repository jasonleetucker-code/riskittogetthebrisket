// INDEPENDENT audit (area E): useAuctionRoom's long-poll revision handling.
// Companion to tests/auction/test_independent_recovery_audit.py.
//
// `it.fails` is vitest's strict-xfail: each one pins an AUDIT DEFECT and
// flips to a hard failure the moment the defect is fixed.
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuctionRoom } from "../../lib/auction-client.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const ok = (body) => ({ status: 200, ok: true, json: async () => body });
const snap = (revision, extra = {}) => ok({ revision, public: { tag: `rev${revision}` }, ...extra });

/** A scripted server.  Each fetch takes the next scripted answer; once the
 * script is exhausted (or an entry is null) a call hangs — a long-poll with
 * nothing new. */
function scripted(script) {
  const urls = [];
  const f = vi.fn(async (url) => {
    urls.push(String(url));
    const next = script.shift();
    if (next === undefined || next === null) return new Promise(() => {});
    if (next instanceof Error) throw next;
    return next;
  });
  f.urls = urls;
  vi.stubGlobal("fetch", f);
  return f;
}

describe("useAuctionRoom never rolls back to an older revision", () => {
  it("drops stale, out-of-order and duplicate snapshots and keeps polling after the newest", async () => {
    const f = scripted([snap(5), snap(7), snap(6), snap(7), snap(7)]);
    const { result } = renderHook(() => useAuctionRoom("r_a"));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(6));
    expect(result.current.view.revision).toBe(7);
    expect(result.current.view.public.tag).toBe("rev7");
    // Every poll after rev 7 arrived asks for "after=7", never an older base.
    const polls = f.urls.slice(2);
    expect(polls.every((u) => u.includes("after=7"))).toBe(true);
  });

  it("survives a server restart mid-wait: reconnects and resumes from the revision it holds", async () => {
    const f = scripted([snap(5), new TypeError("connection reset by restart"), snap(6)]);
    const { result } = renderHook(() => useAuctionRoom("r_a"));
    await waitFor(() => expect(result.current.sync).toBe("reconnecting"));
    expect(result.current.view.revision).toBe(5); // nothing lost while offline
    await waitFor(() => expect(result.current.view.revision).toBe(6), { timeout: 4000 });
    expect(result.current.sync).toBe("live");
    expect(f.urls[2]).toContain("after=5");
  });
});

describe("AUDIT DEFECTS", () => {
  // MEDIUM: after a restore from the hourly backup (RPO up to ~1 h) the room's
  // revision goes BACKWARDS (server half: test_E_restore_rewinds_the_revision_
  // clients_already_hold).  /view carries no store epoch, so an open tab drops
  // every post-restore snapshot as "stale" — even after refresh() — and keeps
  // showing bids the restore lost, until the room passes the old revision.
  // Fix: stamp a store/restore epoch in /view (e.g. meta.store_id + a restore
  // generation) and reset revRef when it changes.
  it.fails("adopts the authoritative snapshot after a restore rewinds the revision", async () => {
    const before = { storeEpoch: "original" };
    const after = { storeEpoch: "restored" };
    const f = scripted([snap(50, before), snap(12, after), null, snap(12, after)]);
    const { result } = renderHook(() => useAuctionRoom("r_a"));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(3));
    expect(result.current.view.revision).toBe(50); // the restored rev 12 was dropped
    await act(async () => result.current.refresh()); // even a manual refresh
    await waitFor(() => expect(f).toHaveBeenCalledTimes(5));
    expect(result.current.view.revision).toBe(12);
  });

  // LOW / latent: revRef is not reset when roomId changes, so a reused hook
  // instance drops the next room's snapshots whenever its revision is lower.
  // Not reachable from today's UI (room switches use full page loads), but the
  // hook's own contract is wrong.  Fix: reset revRef in the effect on roomId.
  it.fails("shows the new room after roomId changes", async () => {
    const f = scripted([snap(40), null, snap(3)]);
    const { result, rerender } = renderHook(({ id }) => useAuctionRoom(id), {
      initialProps: { id: "r_a" },
    });
    await waitFor(() => expect(result.current.view?.revision).toBe(40));
    rerender({ id: "r_b" });
    await waitFor(() => expect(f.urls.some((u) => u.includes("r_b"))).toBe(true));
    await waitFor(() => expect(result.current.view.revision).toBe(3));
  });
});
