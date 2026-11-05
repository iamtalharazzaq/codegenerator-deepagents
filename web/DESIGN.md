# Orchestrator console: design rationale

The screen answers three questions in this order: **what state is the run in, what failed, what do I do next.**

## Hierarchy

1. **Run status** (header): one large status chip, then two meters (tasks done, dispatch budget), at-once count, elapsed
   time and a copyable run ID. When the run is stuck, "Resume run" is the only primary button in the header.
2. **Blocking issue** (Attention card, top of the right panel): the blocker in one sentence (who, how many tries, why),
   the guardrail hits that led to it, and the next steps: Resume with guidance, Retry task, View logs, Agent details.
   It also carries "Approve the plan" while the run waits for you, and the zip when the run passed.
3. **Progress** (stages or agent hub, then the plan checklist).
4. **Details** (conversation, revision history, event log, per-agent panel), folded away until asked for.

## Progressive disclosure

- Project Manager messages are clamped to three lines with "Show more".
- Results are one compact timeline row (icon, agent, outcome, try, one-line reason). Guardrail hits are a badge on the
  task they belong to, not a banner.
- The plan is a checklist; every change to it is a diff (+ added, − removed, ✓ completed) inside a collapsed
  "Revision history", with the reason as one line above the checklist.
- The event log is a bottom drawer: one line when closed; filters (kind, task) and a live tail when open.

## Status system

One vocabulary everywhere (chips, graph nodes, run list, plan items): **passed, running, queued, blocked, failed,
escalated, idle.** Each status is a colour, an icon shape and a word; none relies on colour alone. Chips carry
`aria-label="Status: …"`. "Failed" is one try that did not pass; "escalated" is the failure that stopped the run.

## Colour tokens (dark theme, defined in `src/styles.css`)

| Role | Tokens |
|---|---|
| Surfaces (low to high) | `page #0a0f14`, `surface #111922`, `raised #18232e` |
| Text | `fg #eaf0f4` (15:1), `fg-2 #b9c6d1` (10:1), `fg-3 #98a9b8` (7:1) |
| Interactive | `accent #7cc8f2`, `accent-bg #1c6a96` with `on-accent #fff` (5.9:1) |
| Borders | `line #354655` for dividers, `control #5b7084` for inputs and buttons (3.1 to 3.8:1) |
| Status | each has a text colour and a chip background, all 7.4:1 or better on their chip |

`src/a11y.test.ts` reads these tokens from the CSS and fails the build if any text pair drops below 4.5:1 or a control
border below 3:1 (WCAG 2.1 AA, 1.4.3 and 1.4.11).

## Typography and spacing

- One sans (Schibsted Grotesk) for all UI text; monospace (IBM Plex Mono) only for IDs, paths, tool calls, reasons and
  the log. Body 14px, nothing below 13px.
- Spacing is Tailwind's 4px scale; the layout uses 1, 2, 3, 4 and 6 (4, 8, 12, 16, 24px). Cards use a 16px inner gap.

## Graph views

- **Stages** (default): delegations as columns in the order they ran. Tasks in one column ran at the same time; every
  stage waited for the one before. Not-started work sits in a last column with what blocks it. Cards show tries,
  duration and guardrail hits.
- **Agent hub**: the ten specialists around the Project Manager. A line means "has been given work", a moving line
  means "working now". Click any card or node for the side panel (every try, its reason, what it touched, its tool
  calls, the result file). Esc closes it.

## Responsive and accessible

- Wide: runs | conversation | status, graph, plan. Narrow (< 1024px): Chat / Plan / Graph tabs; the Attention card stays
  on top; the page scrolls and the chat has its own scroll area.
- Every control is a real button or input with a visible focus ring; the graph nodes are focusable and open with
  Enter or Space; the log is a labelled `role="log"`; meters are `role="progressbar"` with text values.
- Animation stops under `prefers-reduced-motion`.

## Mock data

`?mock=escalated` (the screen in the design brief: 3/7 tasks, 6/20 dispatches, Backend Developer failed twice),
`?mock=running` and `?mock=passed` replay event logs from `src/mock.ts` through the same reducer as a live run, so
the mock cannot drift from what the app really draws.
