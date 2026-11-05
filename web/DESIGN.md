# Orchestrator console: design rationale

The screen answers three questions in this order: **what state is the run in, what failed, what do I do next.**

## One home per fact

Nothing is said twice. Each fact has exactly one place:

| Fact | Where it lives |
|---|---|
| Run status | the header chip (the run list has its own row per run) |
| What is happening right now | one live line under the header |
| The plan, and the Project Manager's reasoning | the Plan card (checklist, approval buttons, History) |
| What each specialist did, and why it failed | one task card in the Activity feed, updated in place |
| What stopped the run, and the next step | the Blocker card (shown only when stuck; it names the task, the reason stays on the task card) |
| The last check before delivery | the Review card ("Ready to deliver": summary, files, "Anything to change?"); the zip does not exist until the person accepts |
| What you get | the Result card (summary, zip, full report on demand) |
| Debugging detail | the Event log drawer |

A retry that fails the same way says "Same error as try 1" instead of repeating the text.

## Layout

1. **Header**: status chip, tasks done, dispatches used, elapsed time, project name, copyable run ID, and "Resume run" when stuck.
2. **Now line**: "Project Manager is planning", "Waiting for your approval", "Backend Developer working: write_file …".
3. **Left**: runs. **Centre**: the Activity feed (what you said, then each delegation; tasks that ran together share an
   "N at once" row) and the composer. **Right**: Blocker, Result, Plan, Team.
4. **Planning is shown where it happens.** While the Project Manager works out the plan, the Plan card says so, shows its
   reasoning as it arrives, and holds skeleton lines until the checklist appears.

## Progressive disclosure

- Task cards show the objective, status, try and time; writes, tool calls, guardrail hits and the result file are behind
  "Details". A guardrail hit is a badge on the task.
- The Project Manager's note is clamped to three lines with "Show more"; older notes and every plan change (+ added, −
  removed) are inside "History".
- The Team (hub) diagram is a collapsible card; clicking a specialist scrolls to its latest task card.

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

## Responsive and accessible

- Wide: runs | activity | blocker, result, plan, team. Narrow (< 1024px): Activity / Plan / Team tabs; the Blocker card
  stays on top; the page scrolls and the activity feed has its own scroll area.
- Every control is a real button or input with a visible focus ring; the team diagram's nodes are focusable and jump to
  their task with Enter or Space; the log is a labelled `role="log"`; meters are `role="progressbar"` with text values.
- Animation stops under `prefers-reduced-motion`.

## Mock data

`?mock=escalated` (3/7 tasks, 6/20 dispatches, Backend Developer failed twice), `?mock=running`, `?mock=passed`,
`?mock=planning` (the Project Manager is thinking) and `?mock=approval` (the plan waits for a decision) replay event logs from `src/mock.ts` through the same reducer as a live run, so
the mock cannot drift from what the app really draws.
