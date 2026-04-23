import { describe, it, expect } from "vitest";
import {
  encodeTrade,
  decodeTrade,
  buildShareUrl,
  parseShareParam,
  SHARE_PARAM,
  SHARE_SCHEMA_VERSION,
} from "@/lib/trade-share";

describe("trade-share", () => {
  const sample = {
    sides: [
      { name: "Team Alpha", players: ["Ja'Marr Chase", "2026 1.03"] },
      { name: "Team Bravo", players: ["Josh Allen"] },
    ],
  };

  it("round-trips a basic trade", () => {
    const encoded = encodeTrade(sample);
    const decoded = decodeTrade(encoded);
    expect(decoded.sides).toHaveLength(2);
    expect(decoded.sides[0].name).toBe("Team Alpha");
    expect(decoded.sides[0].players).toContain("Ja'Marr Chase");
    expect(decoded.sides[1].players).toEqual(["Josh Allen"]);
  });

  it("preserves apostrophes and punctuation in player names", () => {
    const trade = { sides: [{ name: "x", players: ["Ja'Marr Chase"] }] };
    const decoded = decodeTrade(encodeTrade(trade));
    expect(decoded.sides[0].players[0]).toBe("Ja'Marr Chase");
  });

  it("preserves an optional note", () => {
    const trade = { ...sample, note: "Testing a buy-low play" };
    const decoded = decodeTrade(encodeTrade(trade));
    expect(decoded.note).toBe("Testing a buy-low play");
  });

  it("caps note length at 200 chars", () => {
    const long = "a".repeat(500);
    const decoded = decodeTrade(encodeTrade({ ...sample, note: long }));
    expect(decoded.note.length).toBeLessThanOrEqual(200);
  });

  it("caps player list length per side", () => {
    const many = Array.from({ length: 50 }, (_, i) => `Player ${i}`);
    const decoded = decodeTrade(encodeTrade({ sides: [{ name: "x", players: many }] }));
    expect(decoded.sides[0].players.length).toBeLessThanOrEqual(32);
  });

  it("filters non-string players during encode", () => {
    const trade = {
      sides: [{ name: "x", players: ["real", null, 42, "", undefined, "also real"] }],
    };
    const decoded = decodeTrade(encodeTrade(trade));
    expect(decoded.sides[0].players).toEqual(["real", "also real"]);
  });

  it("rejects unrecognized schema versions", () => {
    const futureShape = btoa(JSON.stringify({ v: 999, s: [] }))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeTrade(futureShape)).toBeNull();
  });

  it("returns null on garbage input", () => {
    expect(decodeTrade("completely-not-base64")).toBeNull();
    expect(decodeTrade(null)).toBeNull();
    expect(decodeTrade(undefined)).toBeNull();
    expect(decodeTrade("")).toBeNull();
  });

  it("builds a URL with ?share= param", () => {
    const url = buildShareUrl(sample, { baseUrl: "https://example.com" });
    expect(url).toMatch(/^https:\/\/example\.com\/trade\?share=/);
    // Inspect just the encoded portion; the URL itself obviously
    // has slashes in ``https://`` and ``/trade``.
    const encoded = url.split("?share=")[1];
    expect(encoded).not.toContain("+"); // base64url, not plain base64
    expect(encoded).not.toContain("/");
    expect(encoded).not.toContain("=");
  });

  it("parseShareParam extracts and decodes", () => {
    const url = buildShareUrl(sample, { baseUrl: "https://example.com" });
    const decoded = parseShareParam(url);
    expect(decoded.sides).toHaveLength(2);
    expect(decoded.sides[0].name).toBe("Team Alpha");
  });

  it("parseShareParam handles bare search string", () => {
    const encoded = encodeTrade(sample);
    const decoded = parseShareParam(`?${SHARE_PARAM}=${encoded}`);
    expect(decoded.sides).toHaveLength(2);
  });

  it("parseShareParam returns null when no share param", () => {
    expect(parseShareParam("?other=true")).toBeNull();
    expect(parseShareParam("")).toBeNull();
    expect(parseShareParam(null)).toBeNull();
  });

  it("survives messaging-app URL encoding (no + or /)", () => {
    // Build a long payload that's likely to hit base64 padding / specials.
    const trade = {
      sides: [
        { name: "Team Alpha", players: Array.from({ length: 20 }, (_, i) => `Player ${i}`) },
        { name: "Team Bravo", players: Array.from({ length: 20 }, (_, i) => `Other ${i}`) },
      ],
    };
    const encoded = encodeTrade(trade);
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    expect(encoded).not.toContain("=");
    expect(decodeTrade(encoded).sides).toHaveLength(2);
  });

  it("emits the schema version inline", () => {
    // Sanity check: if we ever bump SHARE_SCHEMA_VERSION, this
    // test reminds us to also adjust decodeTrade's accept list.
    expect(SHARE_SCHEMA_VERSION).toBe(1);
  });
});
