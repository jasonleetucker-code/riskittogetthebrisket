/**
 * ROS index join — pins the fix for a join that matched 12 of 1075
 * board rows while telling the user, for the other 1063, "No ROS source
 * ranked this player today."
 *
 * The assertions below are written against the SHAPES that broke, not
 * against a snapshot: the aggregate lowercases and strips apostrophes,
 * board rows carry display names, and six aggregate rows exist twice
 * under two casings. A snapshot-count assertion would go stale nightly;
 * these do not.
 */
import { describe, it, expect } from "vitest";
import { buildRosIndex, rosEntryForRow } from "@/lib/ros-index";

/** A payload row shaped like `/api/ros/player-values` serves. */
function rosRow(canonicalName, over = {}) {
  return {
    canonicalName,
    rosValue: 50,
    rosRankOverall: 10,
    rosRankPosition: 3,
    confidence: 0.8,
    volatilityFlag: false,
    staleFlag: false,
    tier: "B",
    sourceCount: 3,
    ...over,
  };
}

describe("buildRosIndex / rosEntryForRow", () => {
  it("joins an apostrophe name — the class a bare lowercase misses", () => {
    // The aggregate stores "jamarr chase"; the board says "Ja'Marr
    // Chase". trim+lowercase gives "ja'marr chase" and misses. This
    // single case is the 47-player difference between name-key family 3
    // and family 1, which is why the fix is not `.toLowerCase()`.
    const index = buildRosIndex([rosRow("jamarr chase", { rosValue: 91 })]);
    const hit = rosEntryForRow(index, { canonicalName: "Ja'Marr Chase" });
    expect(hit).not.toBeNull();
    expect(hit.rosValue).toBe(91);
  });

  it("joins an initials name", () => {
    const index = buildRosIndex([rosRow("aj brown", { rosValue: 77 })]);
    expect(rosEntryForRow(index, { canonicalName: "A.J. Brown" })?.rosValue).toBe(77);
  });

  it("joins plain lowercase rows, which is the common case", () => {
    const index = buildRosIndex([rosRow("jahmyr gibbs", { rosValue: 88 })]);
    expect(rosEntryForRow(index, { canonicalName: "Jahmyr Gibbs" })?.rosValue).toBe(88);
  });

  it("still joins the wrongly-cased aggregate rows", () => {
    // These 16 rows are the data defect in backlog §9 #18 — and before
    // this fix they were the ONLY rows that joined. They must keep
    // working, or the fix trades one broken set for another.
    const index = buildRosIndex([rosRow("Nate Landman", { rosValue: 42 })]);
    expect(rosEntryForRow(index, { canonicalName: "Nate Landman" })?.rosValue).toBe(42);
  });

  describe("duplicate aggregate rows resolve deterministically", () => {
    // Six players exist twice in the aggregate, once per casing, with
    // different values from different source sets. Last-write-wins made
    // the winner an artifact of payload order — and it picked wrong:
    // Cam Skattebo rendered 37.72 from a DraftSharks-only row while his
    // 2-source row (28.74) never displayed.
    const draftSharksOnly = rosRow("Cam Skattebo", {
      rosValue: 37.72,
      sourceCount: 1,
      confidence: 0.4,
    });
    const twoSource = rosRow("cam skattebo", {
      rosValue: 28.74,
      sourceCount: 2,
      confidence: 0.6,
    });

    it("prefers the broader source set regardless of payload order", () => {
      for (const players of [
        [draftSharksOnly, twoSource],
        [twoSource, draftSharksOnly],
      ]) {
        const hit = rosEntryForRow(buildRosIndex(players), {
          canonicalName: "Cam Skattebo",
        });
        expect(hit.rosValue).toBe(28.74);
        expect(hit.sourceCount).toBe(2);
      }
    });

    it("falls to confidence, then value, when source counts tie", () => {
      const lowConf = rosRow("Tank Dell", { rosValue: 60, sourceCount: 2, confidence: 0.3 });
      const highConf = rosRow("tank dell", { rosValue: 10, sourceCount: 2, confidence: 0.9 });
      expect(
        rosEntryForRow(buildRosIndex([lowConf, highConf]), { canonicalName: "Tank Dell" })
          .rosValue,
      ).toBe(10);

      const lo = rosRow("Cam Ward", { rosValue: 10, sourceCount: 2, confidence: 0.5 });
      const hi = rosRow("cam ward", { rosValue: 70, sourceCount: 2, confidence: 0.5 });
      expect(
        rosEntryForRow(buildRosIndex([lo, hi]), { canonicalName: "Cam Ward" }).rosValue,
      ).toBe(70);
    });
  });

  it("tries every name field a row might carry", () => {
    // The two call sites disagreed on precedence (canonicalName ||
    // displayName || name vs canonicalName || name || displayName).
    const index = buildRosIndex([rosRow("puka nacua", { rosValue: 80 })]);
    expect(rosEntryForRow(index, { name: "Puka Nacua" })?.rosValue).toBe(80);
    expect(rosEntryForRow(index, { displayName: "Puka Nacua" })?.rosValue).toBe(80);
    expect(
      rosEntryForRow(index, { canonicalName: "Nobody At All", name: "Puka Nacua" })
        ?.rosValue,
    ).toBe(80);
  });

  it("returns null rather than a false reading when there is genuinely no row", () => {
    // 226 of 1075 board rows have no aggregate entry even after the
    // fix. For those the UI's "No ROS source ranked this player today"
    // is finally TRUE, so null here is the correct answer, not a miss.
    const index = buildRosIndex([rosRow("jahmyr gibbs")]);
    expect(rosEntryForRow(index, { canonicalName: "Some Undrafted Guy" })).toBeNull();
  });

  it("never indexes an unnamed row under an empty key", () => {
    // An "" bucket would answer every other unnamed row's lookup with
    // whichever one landed last.
    const index = buildRosIndex([
      { canonicalName: "", rosValue: 1 },
      { canonicalName: null, rosValue: 2 },
      rosRow("josh allen", { rosValue: 99 }),
    ]);
    expect(index.size).toBe(1);
    expect(rosEntryForRow(index, { canonicalName: "" })).toBeNull();
    expect(rosEntryForRow(index, { canonicalName: "Josh Allen" })?.rosValue).toBe(99);
  });

  it("survives a missing or malformed index instead of throwing", () => {
    // The fetch path falls back to an empty cache on error; a throw
    // here would take down the whole popup.
    expect(rosEntryForRow(null, { canonicalName: "Josh Allen" })).toBeNull();
    expect(rosEntryForRow({}, { canonicalName: "Josh Allen" })).toBeNull();
    expect(rosEntryForRow(buildRosIndex([]), null)).toBeNull();
    expect(buildRosIndex(null).size).toBe(0);
  });
});
