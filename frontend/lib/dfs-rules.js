/**
 * dfs-rules.js — rule-builder vocabulary and validation for the lazily loaded
 * RuleBuilder (kept out of the /dfs page chunk). The payload shaping that the
 * build call needs, rulesToConstraints, stays in lib/dfs.js.
 */

export const RULE_TYPES = [
  { value: "at_least", label: "At least N of these" },
  { value: "at_most", label: "At most N of these" },
  { value: "exactly", label: "Exactly N of these" },
  { value: "if_then", label: "If A, then B" },
  { value: "if_not", label: "If A, then not B" },
  { value: "if_then_n", label: "If A, then at least N of group B" },
];

const needsN = new Set(["at_least", "at_most", "exactly", "if_then_n"]);
const isConditional = new Set(["if_then", "if_not", "if_then_n"]);

export function ruleNeedsCount(type) {
  return needsN.has(type);
}

export function ruleIsConditional(type) {
  return isConditional.has(type);
}

/** Validate one owner rule; returns an error string or null. */
export function ruleError(rule) {
  const n = Number(rule.n);
  if (needsN.has(rule.type) && (!Number.isInteger(n) || n < 0)) return "Enter a whole number for N.";
  if (isConditional.has(rule.type)) {
    if (!rule.when?.length || !rule.then?.length) return "Choose players for both A and B.";
    if (rule.when.some((p) => rule.then.includes(p))) return "A player cannot be in both A and B.";
  } else if (!rule.players?.length) {
    return "Choose at least one player.";
  }
  return null;
}

/**
 * Team / game stack draft → validated backend entry, or { error }.
 * "At least `count` teams (or games) each supplying `size`+ players", with an
 * optional position filter. Blank counts are errors, never defaults.
 */
export function teamStackEntry(draft, slotCount) {
  const size = Number(draft.size);
  const count = Number(draft.count);
  if (!Number.isInteger(size) || size < 2 || size > slotCount) return { error: `Players per stack must be a whole number from 2 to ${slotCount}.` };
  if (!Number.isInteger(count) || count < 1) return { error: "Number of stacks must be a whole number of at least 1." };
  if (size * count > slotCount) return { error: `${count} × ${size} players is more than a ${slotCount}-player lineup.` };
  const scope = draft.scope === "game" ? "game" : "team";
  const positions = draft.positions || [];
  const who = positions.length ? ` (${positions.join("/")})` : "";
  return {
    entry: {
      label: `${count > 1 ? `${count} × ` : ""}${size}-player ${scope} stack${who}`,
      scope,
      size,
      count,
      positions,
    },
  };
}
