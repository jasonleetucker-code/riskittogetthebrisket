"use client";

/**
 * /auction — Rookie auction room lobby.
 *
 * Self-authenticating page (lib/public-routes.js SELF_AUTHED_PAGE_PREFIXES):
 * league-mates sign in with an AUCTION account (their Sleeper username as a
 * handle + a separate Chase Upside password), never a Sleeper password.
 * The site owner can continue from their existing site session.
 *
 * Only MOCK rooms can be created.  Official rooms are gated off until the
 * owner separately approves launch.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Banner, Button, EmptyState, Field, Input, PageHeader, Panel, Select } from "@/components/ds";
import { AuctionRequestError, auctionFetch } from "@/lib/auction-client";
import styles from "./auction.module.css";

function SignIn({ siteOwnerAvailable, onDone }) {
  const [handle, setHandle] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await auctionFetch("/auth/login", { method: "POST", body: { handle, password } });
      setPassword("");
      onDone();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  const owner = async () => {
    setBusy(true);
    setErr(null);
    try {
      await auctionFetch("/auth/site-owner", { method: "POST", body: {} });
      onDone();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Sign in to the auction room" className={styles.narrow}>
      <form onSubmit={submit} className={styles.col}>
        <Field label="Handle" hint="Usually your Sleeper username. It is only a login name — never enter your Sleeper password here.">
          <Input autoComplete="username" value={handle} onChange={(e) => setHandle(e.target.value)} required />
        </Field>
        <Field label="Chase Upside auction password">
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        {err ? <Banner tone="negative">{err}</Banner> : null}
        <div className={styles.row}>
          <Button type="submit" variant="primary" loading={busy}>
            Sign in
          </Button>
          {siteOwnerAvailable ? (
            <Button type="button" onClick={owner} disabled={busy}>
              Continue as site owner
            </Button>
          ) : null}
        </div>
        <p className={styles.muted}>
          New here? Open the invitation link your commissioner sent you to set up your account and claim your seat.
        </p>
      </form>
    </Panel>
  );
}

function CreateMockRoom({ onCreated }) {
  const [form, setForm] = useState({
    name: "Mock rookie auction",
    preset: "fast",
    seatSource: "league",
    budgetSource: "draft_capital",
    equalAmount: 100,
    poolSource: "contract",
    bots: true,
    commissionerSeat: 0,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const out = await auctionFetch("/rooms", {
        method: "POST",
        body: {
          ...form,
          roomType: "mock",
          equalAmount: Number(form.equalAmount),
          commissionerSeat: Number(form.commissionerSeat),
        },
      });
      onCreated(out.roomId);
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Create a mock room" subtitle="Practice only. Nothing in a mock touches real rosters, budgets or Sleeper.">
      <form onSubmit={submit} className={styles.col}>
        <div className={styles.formGrid}>
          <Field label="Room name">
            <Input value={form.name} onChange={set("name")} maxLength={120} />
          </Field>
          <Field label="Timing" hint="Fast: 10-minute auctions, no nightly pause. Rehearsal: 13 active hours with the real 9 PM–8 AM pause. Proposed official: 65 active hours.">
            <Select
              value={form.preset}
              onChange={set("preset")}
              options={[
                { value: "fast", label: "Fast (minutes, always active)" },
                { value: "rehearsal", label: "Rehearsal (13h, real quiet hours)" },
                { value: "official", label: "Proposed official (65h, real quiet hours)" },
              ]}
            />
          </Field>
          <Field label="Seats">
            <Select
              value={form.seatSource}
              onChange={set("seatSource")}
              options={[
                { value: "league", label: "The 12 league teams" },
                { value: "generic", label: "Generic Team 1–12" },
              ]}
            />
          </Field>
          <Field label="Budgets" hint="Draft capital = current raw auction dollars per team (2027 pick ownership), never effective auction power.">
            <Select
              value={form.budgetSource}
              onChange={set("budgetSource")}
              options={[
                { value: "draft_capital", label: "Current draft capital (raw dollars)" },
                { value: "equal", label: "Equal budgets" },
                { value: "zero", label: "All $0 (tests $0 rules)" },
              ]}
            />
          </Field>
          {form.budgetSource === "equal" ? (
            <Field label="Equal budget ($)">
              <Input type="number" min={0} step={1} data-numeric value={form.equalAmount} onChange={set("equalAmount")} />
            </Field>
          ) : null}
          <Field label="Rookie pool" hint="No official 2027 class exists yet. Mocks use a clearly labelled fixture.">
            <Select
              value={form.poolSource}
              onChange={set("poolSource")}
              options={[
                { value: "contract", label: "Prior-class fixture (current board rookies)" },
                { value: "synthetic", label: "Synthetic players" },
              ]}
            />
          </Field>
          <Field label="Your seat (1–12)">
            <Input type="number" min={1} max={12} step={1} data-numeric value={Number(form.commissionerSeat) + 1} onChange={(e) => setForm((f) => ({ ...f, commissionerSeat: Math.max(0, Math.min(11, Number(e.target.value) - 1)) }))} />
          </Field>
        </div>
        <label className={styles.row}>
          <input type="checkbox" checked={form.bots} onChange={set("bots")} /> Fill every other seat with a bot (you can turn bots off per seat before starting, and invite people instead)
        </label>
        {err ? <Banner tone="negative">{err}</Banner> : null}
        <div>
          <Button type="submit" variant="primary" loading={busy}>
            Create mock room
          </Button>
        </div>
      </form>
    </Panel>
  );
}

export default function AuctionLobbyPage() {
  const [me, setMe] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      setMe(await auctionFetch("/auth/me"));
      setErr(null);
    } catch (x) {
      setErr(x instanceof AuctionRequestError ? x : new Error("The auction service is unreachable."));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const logout = async () => {
    await auctionFetch("/auth/logout", { method: "POST", body: {} }).catch(() => {});
    load();
  };

  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow="Rookie auction"
        title="Auction room"
        description="The league's shared slow rookie auction: private maximum bids, twelve open lots at a time, clocks that pause 9 PM–8 AM Eastern."
        actions={
          me?.user ? (
            <Button variant="ghost" onClick={logout}>
              Sign out {me.user.handle}
            </Button>
          ) : null
        }
      />
      <Banner tone="warning" title="Mock rooms only">
        Official draft rooms are switched off until the commissioner approves launch. Everything here is rehearsal.
      </Banner>
      {err ? <Banner tone="negative">{err.message}</Banner> : null}
      {me && !me.user ? <SignIn siteOwnerAvailable={me.siteOwnerAvailable} onDone={load} /> : null}
      {me?.user ? (
        <>
          <Panel title="Your rooms" flush>
            {me.rooms.length === 0 ? (
              <EmptyState title="No rooms yet" description={me.user.isSiteAdmin ? "Create a mock room below." : "Ask your commissioner for an invitation link."} />
            ) : (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th scope="col">Room</th>
                      <th scope="col">Type</th>
                      <th scope="col">Status</th>
                      <th scope="col">Your role</th>
                    </tr>
                  </thead>
                  <tbody>
                    {me.rooms.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link href={`/auction/${r.id}`} className={styles.player}>
                            {r.name}
                          </Link>
                        </td>
                        <td>{r.room_type === "mock" ? "Mock" : "Official"}</td>
                        <td>{r.status}</td>
                        <td>{r.role ? `${r.role}${r.seat_id ? ` · ${r.seat_id}` : ""}` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          {me.user.isSiteAdmin ? <CreateMockRoom onCreated={(id) => (window.location.href = `/auction/${id}`)} /> : null}
        </>
      ) : null}
    </section>
  );
}
