# UI Theme And Frontend Stack Audit

Status: research note.
Date: 2026-06-18.
Worker: sprint-8a-ui-stack-audit.

## Scope

This note supports Sprint 8A UI/theme research only. It audits the current frontend stack and extracts reusable finance/product UI patterns for later mockup and implementation approval.

No frontend runtime files, package files, API files, shared contracts, worker files, infra files, or scripts were edited.

## Current Frontend Stack

| Area | Current state | Notes for revamp |
| --- | --- | --- |
| Framework | Next.js App Router, React 19, TypeScript | Routes live under `frontend/app/`; most product surfaces are client components. |
| Styling | Tailwind utilities plus large `frontend/app/globals.css` component layer and many inline styles | Existing visual language is bespoke, dark, dense, and operational. The implementation style is fragmented. |
| Theme | `next-themes`, dark default, Geist Sans and Geist Mono | Theme provider is wired, but the CSS token set is effectively dark-first. Light mode is not a real design target yet. |
| Charts | Recharts | Used for the portfolio area chart and allocation donut. Current chart history is reconstructed in the frontend and should be replaced by Sprint 3 dashboard contracts before polish. |
| Icons | `lucide-react` is installed, but current navigation mostly uses glyph/text symbols and one custom SVG theme toggle | Later UI work should standardize icon usage instead of mixing glyphs, manual SVG, and text-only controls. |
| UI helpers | `class-variance-authority`, `clsx`, `tailwind-merge` are installed; `components/ui/button.tsx` exists | The Button helper is not the dominant pattern. Most pages use global `.btn-*` classes and inline styles. |
| Data fetching | Direct `fetch` wrapper in `frontend/lib/api.ts`; `@tanstack/react-query` and `axios` are installed but not evident in scoped UI reads | Do not add another data pattern during visual work without approval. |
| Forms | Direct controlled inputs in scoped pages; `react-hook-form`, resolvers, and `zod` are installed but not evident in scoped UI reads | Watchlist and note flows are currently hand-rolled. A form standardization decision is separate from theme work. |
| Testing | Jest, Testing Library, jsdom, snapshots, Recharts mocks | Good component behavior coverage exists for dashboard, mobile ordering, allocation keyboard interaction, auth, transactions, and snapshots. |
| E2E | Playwright smoke specs for auth, freshness, ingestion, and intelligence/watchlist API round trips | Scoped e2e files do not collect screenshots or visual regression baselines. Playwright config was outside this dispatch read set. |

Context7 was used on 2026-06-18 to check current shadcn/ui docs:

- Library ID resolved: `/websites/ui_shadcn`.
- Source docs referenced: `https://ui.shadcn.com/docs/new`,
  `https://ui.shadcn.com/docs/changelog/2023-06-new-cli`, and
  `https://ui.shadcn.com/docs/dark-mode/next`.

## Existing Design Language

The current app already points in the right product direction:

- Dark, near-black surfaces with warm gray text.
- Hairline borders, low-radius panels, compact tables/cards, and tabular numbers.
- Muted P&L colors instead of neon.
- Geist Mono for labels, timestamps, and compact financial values.
- Dense dashboard structure with current value, P&L, chart, holdings, allocation, pending orders, sync health, activity, and watchlist/intelligence surfaces.
- Mobile route ordering markers such as `data-mobile-section`, with tests asserting mobile information architecture.

The main issue is not taste direction. The issue is that the design system is implicit and scattered across global CSS, Tailwind classes, inline styles, one CVA Button helper, and component-specific layout code.

## Approved Reference Direction

User-provided visual references:

- `docs/frontend_reference/G2S3b3jbMAAsVDO.jpeg`
- `docs/frontend_reference/G2S3cgsbUAEIV7D.jpeg`
- `docs/frontend_reference/G2S3d0WacAEIvTB.jpeg`
- `docs/frontend_reference/G2S3e23akAAbp_4.jpeg`

These references define the stronger taste direction for future mockups. They are not a request to copy the content, military theme, or fictional labels. They are references for layout density, information hierarchy, control surfaces, status language, and motion vocabulary.

Reusable visual vocabulary:

- Dark command-center canvas with fine grid lines and thin panel borders.
- Muted gray base palette, with contrast created by weight, size, opacity, and border emphasis rather than bright gradients.
- Monospaced or tabular-number treatment for codes, values, timestamps, and compact status labels.
- Clear bold/normal hierarchy: strong headings and primary numbers, quieter subtitles and supporting copy.
- Dense tables and rails for repeated operational items, but chart-first hierarchy for the main portfolio screen.
- Numeric indicators with small up/down arrows for movement, especially the compact KPI pattern in `G2S3cgsbUAEIV7D.jpeg`.
- Muted green for good/active/positive, muted red for bad/blocked/negative, and yellow/amber/orange for warning or attention, matching the control-panel palette in `G2S3e23akAAbp_4.jpeg`.
- Left vertical icon rail for primary app areas, plus a secondary left panel for tools or workflow controls where appropriate, as in `G2S3d0WacAEIvTB.jpeg`.
- Bottom icon command bar for mode controls, zoom, inspect, run/pause-like actions, or chart tooling when a flow benefits from command-center interaction.
- Status chips and small segmented controls should feel mechanical and precise, not soft SaaS pills.

Product translation:

- Portfolio dashboard: chart-first cockpit with total value, net capital, investment P&L, confidence, time controls, and top gain/loss drivers.
- Review/reconciliation: command-and-control decision desk showing evidence, candidate choices, impact, and remaining blockers.
- Ops: runtime/control panel style for imports, scheduler state, XTB refresh, verification, and protected DB gates.
- Watchlist/checkpoints: trading decision desk style with checkpoints, thesis, trigger state, and action history.

Interaction principles:

- The chart should be interactive, not a static illustration.
- Active chart selections must look intentional on touch devices. Avoid default browser/SVG focus outlines around pie/donut sectors; replace them with a designed selected state, accessible focus ring on the control wrapper, or a separate selected-row/control state.
- Animated callouts are desirable, but they must be phased. A thin line extending from a selected chart segment followed by a value count-up is a target interaction pattern, not Sprint 4 MVP scope unless the chart library and tests support it cleanly.
- Motion should feel like a precise instrument panel: short, purposeful, and reversible. It must respect `prefers-reduced-motion`.
- For data graphics, animation must never hide confidence, exact values, or keyboard/touch usability.

## Component Boundaries

Current boundaries are understandable but uneven:

- Layout: `Header` and `Sidebar` own global navigation, auth controls, mobile drawer, timestamp, and active route state.
- Dashboard: `frontend/components/dashboard/` owns chart, allocation, holdings, performance summary, pending orders, sync status, activity, and stat cards.
- Intelligence: `NotePanel` and `WatchlistTeaser` are reusable workflow widgets.
- API contracts: `frontend/lib/api.ts` owns handwritten frontend DTOs and API methods.
- Pages: route files still contain substantial product-specific layout and state orchestration, especially dashboard, portfolio detail, holding detail, and watchlist.

Recommended later direction:

- Keep dashboard product sections under `frontend/components/dashboard/`, but split chart cockpit primitives from secondary workflow widgets.
- Move repeated financial formatting and tone helpers out of page files only when a UI implementation ticket touches those files.
- Promote a small set of design primitives only after the chart-first dashboard contract is stable: panel, metric, status chip, segmented control, command/action item, data row, and chart shell.

## Charting Audit

Recharts is sufficient for the next dashboard MVP only if the first interactive requirements remain modest:

- Existing Recharts usage already covers area/line composition, a net-capital reference line, tooltips, range buttons, a donut, slice selection, and keyboard-accessible allocation category controls.
- Jest tests already mock Recharts, keeping component tests deterministic.
- Recharts can likely carry Sprint 4 while the team validates data contracts and visual hierarchy.

Risks and constraints:

- Current `PortfolioChart` reconstructs portfolio history from holdings and recent transactions in the frontend. That is product-risky and should be superseded by the Sprint 3 dashboard contract for inception series, net capital, confidence states, and data gaps.
- Current chart color treatment uses brighter green/cyan values than the rest of the palette. Later theme work should bring chart lines back into the muted operational palette.
- The allocation donut has custom callout animation but no visible reduced-motion guard in scoped CSS.
- Touch selection has previously produced ugly selected-sector bounding boxes. Any pie/donut/driver interaction must explicitly design focus, active, pressed, and selected states before implementation.
- Chart accessibility should not depend only on SVG hover. Provide summary stats, accessible controls, and a compact data table or drilldown for key series points.

Recommendation needing approval:

- Keep Recharts for the first chart-first dashboard contract/UI pass if it can satisfy touch selection, tooltip, selected-state, and basic callout requirements.
- Revisit the charting layer if the approved mockup requires advanced interactions such as crosshair sync, dense annotations, zoom/pan, OHLC/candlestick behavior, radial command graphics, or polished animated callouts.
- Treat Three.js as a later specialized visualization option, not the default charting choice. It may fit a command-center background, 3D globe, radar-like overview, or high-polish animated scene, but it increases accessibility, performance, testing, and mobile complexity. Use it only after a mockup proves a 3D scene is product-critical.

Phased interaction target:

1. Sprint 4 MVP: interactive line chart with period controls, hover/tap tooltip, selected point/series state, visible confidence gaps, and no default ugly focus artifacts.
2. Post-MVP chart polish: selected segment/driver callout with a thin connector line and value count-up, implemented in SVG/canvas with reduced-motion fallback.
3. Later command-center polish: optional Three.js or canvas layer only for a proven high-value visualization, verified with desktop/mobile screenshots and nonblank render checks.

## Component System And shadcn/ui

Context7 check on 2026-06-18: shadcn/ui is not a traditional black-box component library. Its CLI copies component source into the project, usually under `components/ui/`, and the application owns and customizes that code. It uses project configuration such as `components.json`, Tailwind CSS variables, aliases, and framework settings.

Why this matters for agents:

- Owned source components are easier for coding agents to inspect, modify, and review than opaque component libraries.
- Components can be added selectively instead of adopting a full design system at once.
- Radix-based primitives can improve accessibility for dialogs, dropdowns, menus, tooltips, tabs, sheets, command palettes, and form controls.
- The copied-code model still creates maintenance responsibility: once components are in the repo, local conventions, tests, and visual QA own them.

Recommended package posture:

- Do not add all shadcn/ui components.
- Consider a small, approved pilot set after dashboard contract shape is stable: `button`, `tabs`, `tooltip`, `dropdown-menu`, `sheet`, `dialog`, `command`, `popover`, and form primitives only if they replace real repeated local UI.
- Keep bespoke financial visualization components local. Do not force charts, KPI tiles, command rails, or portfolio-specific widgets into generic shadcn wrappers.
- If adopted, document component ownership in `AGENTS.md` or a frontend runbook so future agents know copied components are editable local source, not vendor code.
- Evaluate other modern UI packages using the same criteria: accessible primitives, Tailwind/token compatibility, source ownership, low visual lock-in, agent-editable code, small adoption surface, and testability.

## Styling And Theme Audit

The current CSS token vocabulary is useful:

- Surfaces: `--bg-0` through `--bg-3`, `--bg-inset`.
- Borders: `--line-1` through `--line-3`.
- Text: `--fg-0` through `--fg-4`.
- P&L: `--pl-up`, `--pl-dn`, with subtle backgrounds.
- Warning: `--warn`, `--warn-bg`.
- Radius: `4px`.

Keep these principles:

- Dollars before percentages.
- Compact panels, thin borders, low radius.
- Tabular numbers everywhere money or quantity appears.
- Neutral palette with restrained positive/negative colors.
- Confidence state as a first-class visual layer, not hidden helper text.

Clean up later:

- Remove or replace negative letter spacing in new UI work; current CSS uses several negative tracking values.
- Avoid using viewport-scaled font sizes for fixed UI controls; current `clamp()` appears on metric values.
- Standardize focus rings for buttons, segmented controls, links, chart controls, and row buttons.
- Add `@media (prefers-reduced-motion: reduce)` handling for allocation callouts, bars, hover transforms, and cursor animations before expandable navigation or richer chart motion ships.

## Responsive Patterns

Current responsive behavior is pragmatic:

- Fixed desktop sidebar at `md` and top header on all viewports.
- Mobile drawer in the header with `aria-expanded` and `aria-controls`.
- Dashboard, portfolio, and holding detail use `data-mobile-section` markers tested by `mobile-routes.test.tsx`.
- Holdings and transactions switch from dense desktop table/grid rows to mobile cards.
- Some filter controls are intentionally disabled placeholders on mobile, with `aria-disabled`.

Gaps to address before visual polish:

- No screenshot evidence is collected in scoped tests for 390px mobile, tablet, or wide desktop.
- Some mobile controls are text-heavy and may need icon+tooltip treatment once the action model is approved.
- The compact single-button navigation concept from the roadmap should wait for a dedicated accessibility pass: keyboard support, focus trap or non-trapping menu behavior, `aria-expanded`, escape/click-outside behavior, route-change close, and reduced-motion fallback.

## Testing And Screenshot Tooling

Current coverage strengths:

- Dashboard unit tests cover loading, error, loaded state, optional panel failures, sync action, mobile nav, allocation keyboard interaction, snapshots, and history reconstruction.
- Mobile route tests assert section order for dashboard, portfolio detail, and holding detail.
- Transactions tests assert mobile card and desktop table coexistence.
- Playwright e2e specs exercise auth, freshness API access through browser session, XTB ingestion flow with local-only fixture skipping, and intelligence/watchlist API round trips.

Current gaps:

- No scoped evidence of Playwright screenshots, `toHaveScreenshot`, or visual regression baselines.
- No scoped evidence of automated axe/accessibility checks.
- No scoped e2e for chart-first dashboard first viewport or no-overlap layout.
- Playwright config was not read because it was outside this dispatch record.

Recommended later gates for Sprint 4 dashboard UI:

- Component tests for trusted, provisional, warning, and blocked dashboard states.
- Component tests that assert no ambiguous all-time/total P&L labels.
- Playwright desktop and mobile smoke with screenshots as evidence, even if not committed as baselines.
- At least one mobile viewport near 390x844 and one desktop wide viewport.
- Canvas/SVG nonblank check for chart rendering if the chart becomes central to acceptance.

## Reference Scouting: Reusable Patterns

These are pattern targets, not screenshot collection requirements.

### Chart-First Cockpit Hierarchy

Use the first viewport as a portfolio performance cockpit:

- Primary: current total value and confidence state.
- Primary chart: total portfolio value from inception.
- Companion line: net capital at work.
- Context stats: investment P&L/gain-loss, rolling 30D investment gain, net capital, cash reserve, current/history/P&L confidence.
- Deposits and withdrawals: markers or tooltip/drilldown, not default visual noise.
- Reconciliation: top material action visible when it blocks trust.

Pattern to avoid:

- Log-first dashboards, transaction feeds above chart, or benchmark-heavy first screens.

### Calm Dense Operations Style

Adopt a professional finance cockpit posture:

- Quiet surfaces and strong information density.
- Small uppercase labels and clear numeric hierarchy.
- No decorative hero composition, marketing cards, gradient backgrounds, or oversized empty space.
- Use panels for bounded tools and repeated items, not as nested page-section decoration.
- Keep rows scannable with stable columns on desktop and concise cards on mobile.

### Top Gain/Loss Driver Treatment

Use a symmetric driver section:

- Top 5 gains and top 5 losses.
- Dollars first, percentage second only when denominator confidence is reliable.
- Driver row includes symbol, asset type, venue/account if useful, dollar contribution, percent contribution, and confidence state.
- Low-confidence drivers are flagged or omitted according to the contract.
- Clicking a driver should open asset detail with the same selected period context.

Avoid a single "top driver" because it hides loss concentration and weakens decision context.

### CTA Patterns

Candidate CTA layouts for later mockups:

- Action rail under the chart: compact horizontal actions such as Add checkpoint, Review watchlist, Inspect movement, Refresh XTB.
- Command bar: keyboard-friendly dense action group near filters and period controls.
- Contextual action row: only show actions relevant to confidence state, selected period, or selected driver.
- Box cards: acceptable only if they remain compact and do not turn the cockpit into a marketing grid.

MVP rule:

- The chart-first dashboard can ship with simple placeholders for CTA placement, but final CTA treatment needs user approval before implementation.

### Command And Control Flow Pattern

Use the `G2S3d0WacAEIvTB.jpeg` and `G2S3e23akAAbp_4.jpeg` references for workflow-heavy areas:

- A left icon rail can switch between Portfolio, Assets, Watchlist, Ops, and possibly Review.
- A secondary panel can show tools, filters, task categories, or decision blocks.
- A central canvas can show portfolio chart, reconciliation graph, or checkpoint workflow depending on route.
- A bottom command strip can host mode controls, zoom/inspect, refresh, run/pause, or apply/confirm actions.
- Keep destructive or irreversible actions visually distinct and confirmation-gated.

This pattern should not replace the portfolio cockpit by default. Use it when the user is actively operating a workflow: reconciliation, XTB refresh, runtime ops, automation, watchlist/checkpoints, or trading-decision review.

### Filter Patterns

Candidate filters:

- Period: 7D, 30D, 90D, inception. This is primary.
- Scope: portfolio, asset type, venue, selected tags/sector/conviction when metadata exists.
- Driver mode: dollars, percent, confidence-filtered.
- Chart overlays: net capital, deposits/withdrawals markers, confidence gaps.

Open decision:

- Filters must declare scope. A filter should not silently apply to chart, drivers, holdings, and asset table all at once unless the UI makes that explicit.

### Navigation Ideas

The roadmap's compact single-button nav is promising but should be treated as a later design-system item:

- Top-level areas: Portfolio, Assets, Watchlist, Ops.
- Keep the current desktop sidebar until the compact nav has a tested keyboard and reduced-motion design.
- On mobile, menu open/close should preserve route context and close on navigation.
- Icons should come from one source, preferably the installed `lucide-react`, with text labels where the meaning is not obvious.

## Accessibility And Reduced Motion

Minimum later requirements:

- Every icon-only control has an accessible name and visible tooltip or adjacent label where needed.
- Do not encode gain/loss, confidence, or warnings by color alone.
- Chart controls are keyboard reachable and have pressed/selected states.
- Chart summaries are available as text, not only hover tooltips.
- Allocation and driver controls keep `aria-pressed` or equivalent selected state.
- Respect `prefers-reduced-motion` for callout animations, hover transforms, blinking cursor effects, and future nav expansion.
- Do not use manual glyph icons when an accessible lucide icon and label would be clearer.

## Recommendations Needing Approval

1. Approve the reference-image design direction as the visual north star for dashboard mockups.
2. Decide whether to run a selective shadcn/ui pilot after data contracts stabilize.
3. Keep Recharts for Sprint 4 only if approved mockups do not require advanced chart animation or radial command visuals.
4. Defer Three.js until a specific visualization proves it needs a 3D/canvas scene.
5. Standardize on muted gray, green, red, and amber command-center tokens before UI implementation.
6. Use installed `lucide-react` for future icon buttons and navigation icons; replace glyph/manual SVG usage only inside approved UI tickets.
7. Add reduced-motion CSS before shipping animated allocation callouts, expandable nav, or richer chart transitions.
8. Add Playwright desktop/mobile screenshot evidence for dashboard UI acceptance, but decide separately whether to commit visual snapshot baselines.

## Skipped By Scope

- Context7 was used only for shadcn/ui package documentation; no packages were installed.
- The local reference images were inspected, but no external screenshot collection was performed.
- No Playwright/Jest config files were read because they were outside this dispatch record.
- No frontend lint, typecheck, unit tests, e2e, or screenshot gates were run because this was docs-only and the dispatch verification command is narrower.
