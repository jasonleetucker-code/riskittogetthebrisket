/**
 * The contract failure classifier — the distinctions it must not collapse.
 *
 * Every case here corresponds to a route that used to render the wrong
 * thing because the failure arrived as a string. The names say which.
 */
import { describe, it, expect } from "vitest";
import {
  classifyContractFailure,
  classifyContractPayload,
  shouldRedirectToLogin,
} from "@/lib/contract-failure";

describe("classifyContractFailure", () => {
  it("tells a 503 that explains itself from one that does not", () => {
    // This app 503s deliberately when scoring identity cannot be proven
    // across leagues — the server is UP and declining for a stated
    // reason. Rendering that as "the backend is unreachable" describes a
    // working fail-closed guard as an outage.
    const degraded = classifyContractFailure(503, {
      error: "scoring_identity_unproven",
      message: "Leagues do not share proven scoring.",
    });
    expect(degraded.kind).toBe("degraded");
    expect(degraded.code).toBe("scoring_identity_unproven");
    expect(degraded.message).toMatch(/proven scoring/);

    expect(classifyContractFailure(503, null).kind).toBe("unavailable");
  });

  it("separates 401 from 403 — one is a sign-in, the other is an answer", () => {
    expect(classifyContractFailure(401, null).kind).toBe("auth");
    const forbidden = classifyContractFailure(403, null);
    expect(forbidden.kind).toBe("forbidden");
    // No retry: retrying cannot change a permissions answer, and offering
    // one implies it might.
    expect(forbidden.retryable).toBe(false);
  });

  it("does not call a rate limit a server error", () => {
    const limited = classifyContractFailure(429, null);
    expect(limited.kind).toBe("rate_limited");
    expect(limited.retryable).toBe(true);
  });

  it("distinguishes 'never reached a server' from every HTTP status", () => {
    // The old code could not express this at all: a network error and a
    // 500 were both `err.message`.
    expect(classifyContractFailure(null, null).kind).toBe("offline");
    expect(classifyContractFailure(500, null).kind).toBe("server");
    expect(classifyContractFailure(502, null).kind).toBe("unavailable");
    expect(classifyContractFailure(504, null).kind).toBe("unavailable");
  });

  it("prefers the server's own words to ours", () => {
    const f = classifyContractFailure(500, { detail: "pipeline not stamped" });
    expect(f.message).toBe("pipeline not stamped");
  });

  it("survives a non-JSON body without inventing a code", () => {
    const f = classifyContractFailure(500, "<html>502 Bad Gateway</html>");
    expect(f.kind).toBe("server");
    expect(f.code).toBe("");
  });
});

describe("classifyContractPayload", () => {
  it("returns null for a usable board, on either encoding", () => {
    expect(classifyContractPayload({ playersArray: [{ displayName: "x" }] })).toBeNull();
    expect(classifyContractPayload({ players: { x: {} } })).toBeNull();
  });

  it("calls an empty board EMPTY, not an error", () => {
    // A contract that arrives, parses, and has no players is a backend
    // that has not finished its first scrape. Telling the user something
    // went wrong invites them to retry something already working.
    const f = classifyContractPayload({ playersArray: [], players: {} });
    expect(f.kind).toBe("empty");
    expect(f.message).not.toMatch(/error|failed|wrong/i);
  });

  it("separates 'nothing arrived' from 'arrived empty'", () => {
    expect(classifyContractPayload(null).kind).toBe("no_data");
    expect(classifyContractPayload("nonsense").kind).toBe("no_data");
  });
});

describe("shouldRedirectToLogin", () => {
  const auth = { kind: "auth" };

  it("redirects only the stuck-session case it was written for", () => {
    expect(shouldRedirectToLogin(auth, { hadAuthCache: true, pathname: "/rankings" })).toBe(true);
  });

  it("does not bounce an anonymous visitor off a public route", () => {
    // `useDynastyData` is hydrated on public routes. Redirecting every
    // 401 would make them unreachable while signed out.
    expect(shouldRedirectToLogin(auth, { hadAuthCache: false, pathname: "/" })).toBe(false);
  });

  it("never redirects from /login to /login", () => {
    expect(shouldRedirectToLogin(auth, { hadAuthCache: true, pathname: "/login" })).toBe(false);
    expect(
      shouldRedirectToLogin(auth, { hadAuthCache: true, pathname: "/login/callback" }),
    ).toBe(false);
  });

  it("never redirects on a failure that is not an auth failure", () => {
    // A 503 used to be able to reach the 401 branch, because the branch
    // tested `/\b401\b/` against a message that could contain anything
    // the server echoed back.
    for (const kind of ["degraded", "unavailable", "server", "offline", "forbidden"]) {
      expect(shouldRedirectToLogin({ kind }, { hadAuthCache: true, pathname: "/rankings" })).toBe(
        false,
      );
    }
  });
});
