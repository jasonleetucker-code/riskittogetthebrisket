# Competitor Reuse Policy

**Status:** OWNER-APPROVED CANONICAL PRODUCT / IMPLEMENTATION POLICY  
**Owner direction captured:** 2026-08-12  
**Scope:** competitor research, product inspiration, architecture, workflows, UX patterns, feature concepts, and implementation planning.

## Owner direction

For **Risk It To Get The Brisket**, there is **no artificial originality requirement** when learning from public/free fantasy-football websites or other publicly observable products.

Architecture, workflows, interaction patterns, data-flow concepts, feature structures, and publicly observable product ideas are explicitly fair game to **reproduce, adapt, combine, or improve** when they are useful for this personal site.

Do **not** reject a technically good design merely because a competitor already uses the same or a very similar architecture. Do **not** spend engineering time making a workflow different only for the sake of being original.

The correct question is:

> **Is this the best architecture or product pattern for Brisket, given our canonical systems, data, performance requirements, and owner goals?**

If the answer is yes, use it — even if a public competitor uses substantially the same pattern.

## Practical interpretation

Competitor research may legitimately produce recommendations such as:

- use the same overall page/workflow architecture;
- use the same sequence of user decisions;
- use similar navigation, filtering, drill-down, onboarding, or dashboard patterns;
- use the same general caching/materialization/indexing pattern if it is technically sound;
- reproduce a useful feature concept closely and then integrate it with Brisket's canonical data/model layer;
- combine the best parts of several public products into one Brisket workflow.

There is no requirement to rename, rearrange, or re-architect something simply to create superficial differentiation.

## What still matters

This policy does **not** change the platform's normal engineering requirements:

- Brisket must still use canonical owners rather than create duplicate valuation, identity, trade, roster, market, or probability engines;
- methodology still needs evidence, provenance, missing-data discipline, and anti-double-counting;
- architecture must still satisfy performance, security, privacy, maintainability, and correctness requirements;
- unavailable/private implementation details should not be invented and represented as known facts;
- use Brisket's own repository/codebase as the implementation target rather than assuming another site's hidden internals are known.

## Precedence correction

This owner direction **supersedes any older or subordinate planning language that says competitor architecture must not be copied or that Brisket must intentionally avoid reproducing a competitor's publicly observable architecture/workflow**.

In particular, any wording in detailed Sharp/Insider or competitive-research documents such as "do not copy architecture" should be read as obsolete. The intended rule is instead:

> **Use or closely adapt competitor architecture and public product patterns whenever they are the best fit; originality is not a product requirement.**
