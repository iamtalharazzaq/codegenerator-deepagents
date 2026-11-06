# Orchestrator console: design rationale

The screen answers three questions in this order: **what state is the run in, what failed, what do I do next.**
Passed runs feel calm and lead with the deliverable; stuck runs feel urgent and lead with the next action.

## Hierarchy: what leads the eye

| Level | What | How it is made to lead |
|---|---|---|
| 1 | The one thing to do next | the only gradient (indigo to cyan) button on screen: **Download zip** (passed), **Resume run** (stuck), **Stop** (running, red) |
| 2 | State | a large status pill with icon and word in the top bar; on a stuck run the **Attention needed** card tops the right pane |
| 3 | The deliverable or the plan (while it waits for you: **Approve and start**, **Request changes** with a note, **Reject**) | the **Result** hero (rendered markdown, Download zip, file count, Full report), or the Plan stepper |
| 4 | What each agent did | compact step cards in the Activity timeline |
| 5 | Detail | Details toggles, drawers, the Event log |

Three surface layers (`surface` < `raised` < `overlay`) with a 1px hairline and a soft inner highlight replace heavy outlines. Only
things that matter get a tinted border or glow: the running step, the Attention card, the passed Result hero.

### One home per fact

| Fact | Where it lives |
|---|---|
| Run status, tasks done, dispatch budget, time, run ID | the top bar (segments: one per task, coloured by state) |
| What is happening right now | the live strip at the top of the Activity pane |
| The Project Manager's reasoning | the timeline (collapsed to one line, "Show reasoning"); the latest note, clamped, in the Plan tab |
| What each specialist did and why it failed | one step card in the timeline, updated in place |
| Who failed, the cause, every guardrail warning, the next actions | the **Attention needed** card (guardrails are merged into it, never separate banners) |
| Every change to the plan and why | Revision history (a diff: added green, removed red) |
| Order, blockers and tries | the Team tab (stages swimlane, or the hub) |
| The last check before delivery | the Review card ("Ready to deliver") on Overview |
| Debugging detail | the Event log drawer |

A retry that fails the same way says "Same error as try 1" instead of repeating the text.

## Layout

- **Top bar** (sticky glass): breadcrumb, status pill, segmented task progress, dispatch meter, elapsed time, copyable run ID, and the one primary CTA.
- **Sidebar**: search, New run, runs grouped Today / Yesterday / Earlier; one truncated line per run, relative time, status icon, task count;
  the full prompt is in a tooltip; the active run has an accent bar. Collapses to icons (remembered); under 1024px it is a drawer.
- **Two panes, each scrolls on its own, no nested scrollbars** (the page never scrolls; checked in a browser at 1440, 900 and 390px).
  - *Activity*: the prompt, the Project Manager's plan, one card per delegation (tasks that ran together share an "N at once" row), and the
    composer docked below.
  - *Right pane*: **Overview** (Result hero + stats), **Plan** (stage stepper + revision history), **Team** (stages swimlane or hub; a node
    opens the agent drawer), **Files** (tree, preview, zip).
- **Composer** has four honest states: start a run; "Guidance for the next attempt" (with what happens on submit, Resume, Retry task);
  locked while running or waiting for you (with the reason and Stop); and a "Run complete" banner (Start a follow-up run, New run).
  A disabled button always has the reason printed next to it.
- **Under 768px** the panes become tabs: Activity / Overview / Plan / Team / Files.

## Status system

One vocabulary everywhere (pill, chips, plan stages, swimlane, hub, sidebar, segments): **passed, running, queued, blocked, failed,
escalated, idle.** Each is a colour, a distinct icon shape and a word (`theme/tokens.ts`), and each chip has an `aria-label` such as
"Status: Escalated. Escalated, needs your attention". "Failed" is one try that did not pass; "escalated" is the failure that stopped the run.

## Colour tokens (`src/styles.css`, dark default on `:root`, light on `[data-theme="light"]`)

| Token | Dark | Light | Use |
|---|---|---|---|
| `page` / `surface` / `raised` / `overlay` | `#0a0c11` `#10131a` `#161a23` `#1d222d` | `#f4f5fa` `#ffffff` `#f0f2f8` `#ffffff` | the layers |
| `fg` / `fg-2` / `fg-3` | `#eef1f7` `#b6bfd0` `#8f9ab0` | `#11141c` `#394156` `#566075` | text, all 4.5:1 or better on every layer |
| `accent` | `#a3b2ff` | `#4338ca` | links, focus ring, active tab |
| `accent-from` to `accent-to` | `#4f46e5` to `#0e7490` | `#4338ca` to `#0e7490` | the signature gradient: primary buttons, active-run bar, tab underline |
| `control` | `#6b7790` | `#6f7a91` | input borders, 3:1 or better (WCAG 1.4.11) |
| status text and chip background | `passed #4ade9b / #0f2c20` ... | `passed #0a7a45 / #dcf5e7` ... | semantic colours are used for status only |
| `hairline`, `highlight` | white at 8% and 5% | slate at 10%, white at 90% | the 1px edge and the inner top highlight |

Each agent has one icon and one hue (`AGENTS` in `theme/tokens.ts`), shown as a tinted rounded square in the timeline, plan, swimlane, hub, files and
drawer, so an agent is recognised without reading its name. `src/a11y.test.ts` reads the tokens for **both themes** and fails the build if any text pair
drops below 4.5:1, the gradient's ends below 4.5:1 with white text, or a control border below 3:1. An axe-core run over the escalated, passed, team,
files and phone views in both themes found no violations.

## Type, spacing, radius

- One sans (Inter) for all UI text; monospace (JetBrains Mono) only for IDs, paths, tool calls and the log.
  Scale: meta 13/20, body 14/22, content 15/25 (summaries, markdown), title 17/24, display 22/28. Nothing below 13px (a test checks the components).
- Spacing is the 4px Tailwind scale, used in 8px steps: 8, 12, 16, 24, 32. Cards are padded 16 to 24px.
- Radius: controls 12px, cards 16px, pills and chips fully round.

## Motion rules

Motion explains state; it never decorates. Durations are 150 to 240ms ease-out (`MOTION` in `theme/tokens.ts`); springs only for sliding indicators (tab underline, active-run bar, view toggle) and the check pop.

- **Loops only mean "working now"**: the spinning icon, the pulsing dot on the live agent, the flowing dashed edge on an active dispatch or stage rail, the shimmer on the running progress segment, the glow line under the top bar.
- **Changes animate once**: progress segments grow in, the timeline cards and plan stages reorder with `layout`, details expand by height, drawers slide 48px.
- **Reward**: when a run passes, a check pops and 20 confetti pieces burst once (live passes, not on a reload).
- **Reduced motion** (`prefers-reduced-motion`): every loop stops, transitions become instant, framer-motion transforms are skipped, the confetti is a still check.

## Accessibility

Tabs are an ARIA tablist (arrow keys, Home, End) with tabpanels; drawers are modal dialogs that trap focus, close on Escape and return focus to the control that
opened them; the timeline and log are labelled regions (`role="log"` for the log); progress is `role="progressbar"` with text values; the live strip is `role="status"`;
there is a skip link; every control has a visible focus ring.

## Data

The UI is driven by the run's event log through one reducer (`model.ts`), so a live run, a reloaded page and the mock data go through the same code.
The Files tab previews through `GET /api/runs/{id}/files/{path}`, which serves text files from the project with the same exclusions as the zip.

Mock runs for design review: `?mock=passed` (make a calculator: 3/3 tasks, 3/20 dispatches, 43s, 7 files, markdown result), `?mock=escalated` (3/7 tasks,
Backend Developer recursion error twice, three guardrail blocks on write paths, 3 replans), `?mock=running`, `?mock=planning`, `?mock=approval`, `?mock=review`.
`&tab=overview|plan|team|files` opens a tab. Light theme: the toggle in the top bar.
