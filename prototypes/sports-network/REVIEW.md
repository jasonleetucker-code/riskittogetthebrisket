# Visual review and design specification

## Point of view

**Visual thesis:** a football broadcast identity that opens into a precise research workspace: ink navy, coral newsroom emphasis, warm editorial surfaces, condensed headlines and disciplined numerical alignment.

**Content plan:** Rankings moves from compact context directly into the board; Player File moves from identity and current value into historical research and peers; News moves from a newsroom masthead into lead reporting, a coral priority rail, and a chronological desk. The same company, three task-specific compositions.

**Interaction thesis:** feedback through selection, disclosure and focus, rather than perpetual animation. The wire advances manually. Charts respond to pointer inspection and a keyboard slider. Mobile research controls expand on request. Reduced-motion preferences remove smooth scrolling.

The incumbent components already contain useful behavior; a recolor would not establish the owner's chosen composition. The prototype therefore explores composition independently while documenting production owners for later reuse. It does not replace rich production functionality with a smaller demo.

## Tokens and composition rules

| Layer | Prototype decision |
|---|---|
| Brand | Compact coral CU tile, stacked wordmark, horizontal media navigation, a small manual wire |
| Color | Navy `#0b2130`, coral `#fd633f`, cream `#f0eddf`, selective gold `#f7c77f`; dark navy text on coral controls |
| Type | Barlow Condensed Bold for identity and headings; IBM Plex Sans for reading, controls and tabular figures; locally loaded, licensed subsets |
| Density | Full-width working regions with dividers; no card wall or permanent sidebar; 3.6% desktop gutters, 24px tablet, 16px mobile |
| Tables | Aligned numeric columns, sticky desktop headings, explicit sorted state, restrained direction colors plus signs/glyphs, missing values last |
| Charts | Labeled value units, actual elapsed-time spacing, date-based ranges, discontinuous paths over missing observations, accessible inspection values |
| Selection | Checkbox, row treatment and selection count; three-player limit with visible and announced feedback |
| State | Distinct loading, empty, unavailable, stale source and missing-data presentations; restore/retry controls remain local demonstrations |
| Mobile | Research columns disclosed per row; secondary filters collapse; dossier value moves beneath identity; lead news text precedes its image |
| Focus | Visible focus styles, skip link, tab/tabpanel semantics with arrow-key navigation, native dialog plus explicit focus cycling and return |

Sunday Paper's influence is reading rhythm, warm surfaces, long-form spacing and editorial dividers. It does not dilute Sports Network into a neutral newspaper or introduce a third font family. These remain prototype tokens, not a production design-system decision.

## Render → critique → revision

The initial nine renders were inspected as a contact sheet, with individual viewport/full-page screenshots available locally. The revised nine were rendered again. Automated scan results supplement visual inspection; they are not a claim of assistive-technology or production certification.

### Rankings: five specific shortcomings

1. **Mobile controls delayed the actual board.** The first 390px render showed the control area instead of useful player rows. Secondary movement/column controls now expand behind More filters; search and format remain visible. Header and row spacing were tightened.
2. **The last position filter wrapped awkwardly.** In the first revised mobile view, DB occupied a separate line beside Export. Position filters now get a full row; Export sits with the table's metadata.
3. **Hidden demo-label text removed the select name.** Mobile axe scans failed select-name on all screens. The reusable select now always has an explicit accessible name.
4. **Source-spread sorting had a misleading one-way control.** Independent review found the header did not reverse direction. It now toggles and reports ascending/descending state; browser coverage verifies both.
5. **Miniature trends treated irregular observations as equally spaced.** Sparklines now use actual elapsed dates and preserve missing gaps. Seven-day movement has a fixed Oct31→Nov7 fixture oracle. Local-font preload/fallback adjustments also address the measured mobile layout shift.

Remaining design opportunity: mobile intentionally shows fewer research dimensions; users must open row details or a dossier. The board is not virtualized; 64 fixture players are intentionally bounded. A real hundreds/thousands-row production board must preserve its existing performance strategies.

### Player File: five specific shortcomings

1. **Title-case names weakened the broadcast identity.** The first hero looked less assertive than the newsroom. Player names now use uppercase condensed display type.
2. **The hero image could be mistaken for the selected athlete.** The caption now explicitly says generated illustration, not a player portrait. This single reusable image remains a prototype limitation.
3. **Chart ranges and point spacing misrepresented time.** Date-based filtering and coordinates replace slice counts; the 30D view no longer includes October 4. Small-screen axis labels were enlarged.
4. **Unavailable current value contradicted the same-day history.** The missing-value fixture now has null current-day observations in every format, with earlier observations preserved. Unavailable text gets a smaller typographic treatment so it fits the value area.
5. **Research navigation could lose the user's starting context.** A second-hop peer link discarded the original board filters, and missing news opened another player's report. Peer links now carry the validated return URL; missing reports navigate to the newsroom. Browser journeys cover both.

Remaining design opportunity: the artwork is atmospheric rather than player-specific, and the scouting prose is representative fixture content. Owner review should judge the composition and workflow, not assume that real player research is implemented. Actual roster fit and trade analysis remain unavailable.

### News Desk: five specific shortcomings

1. **Mobile filtering displaced the lead story.** Search, team and category remain immediate; position, source and relevance expand behind Refine the desk.
2. **Image-first mobile ordering delayed the actual headline.** The lead copy now precedes the image at 390px, while desktop preserves the image/editorial/priority composition.
3. **The same hidden demo label failed mobile accessibility.** The shared explicit-name fix applies here; scans are rerun rather than assuming the fix passed.
4. **The lead's reporting class could feel factual without nearby context.** Story surfaces carry demo source names and confirmation classes; source details explicitly identify fictional attribution and distinguish implication from reporting. The global synthetic notice remains present.
5. **A perpetual ticker would compete with reading.** The wire remains stationary and uses explicit previous/next actions. Its deterministic ordering excludes stale and unconfirmed stories, then sorts confirmation class, importance and publication time.

Remaining design opportunity: lengthy chronological browsing repeats some stories featured in the priority rail. This is deliberate in the demonstration, but owner review should judge whether real usage needs a compact already-featured treatment. No simulated source link pretends to be a real publisher article.

## Verification scope and limitations

The machine-readable receipt records actual final checks and runtime source hashes. Test code, screenshot evidence, axe results and local performance samples live together under `output/playwright/`.

- Correctness tests use fixed known answers, including format-specific rank/value order, missing-last sorting, filtered export, news facet conjunction, historical gaps and seven-day movement consistency.
- Browser journeys exercise comparison limits, persisted selection, dialog focus return/containment, row expansion, time ranges, keyboard research tabs, source reading, missing-data and recovery flows, and cross-screen board state.
- Nine rendered populated-state scans cover WCAG 2 A/AA and 2.1 AA rules supported by axe. Manual code/keyboard checks supplement those scans. No actual screen reader certification is claimed.
- Reflow is checked at 390/768/1440 CSS pixels and a 720px CSS-viewport proxy for a 1440px viewport at 200% zoom. Native browser-UI zoom and iOS Safari are not independently certified.
- Performance values come from a local, unthrottled Chromium production preview. They are not production LCP, INP, field performance or a network/device laboratory benchmark.

## Owner review and future migration

Review the three working experiences and all nine sizes before deciding the baseline. Typography, density, coral emphasis and the balance of editorial versus research should be judged in actual use.

After explicit visual approval **and separate production execution authorization**, reconcile current claims and contracts, re-baseline the full route inventory, then migrate shared foundations → shell → flagship experiences → other authorized private tools → public league → remaining active routes → verified consolidation. Keep specialized/parked workflows, auth, flags, share links, exports, league transforms and canonical numerical owners intact. This paragraph is a migration recommendation, not implementation authorization.

**UNRESOLVED:** owner design approval; production integration/verification deliberately not attempted; #2112 charter remains open/unmerged and should receive this review pointer through Integration. No acceptance claim is made for production or model quality.
