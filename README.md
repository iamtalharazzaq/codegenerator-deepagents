# codegenerator-deepagents

An AI engineering team with a web UI. One Project Manager deep agent plans, delegates to specialist deep agents
(side by side where the work allows), reads their results, and decides what to do next. No specialist's claim of
success is trusted: code checks the files really written and the real exit code of the tests or build. A failure is
retried with the full history of the earlier tries, or reassigned. The run ends with a report and a zip of the code.

It reuses codewright's LLM client, sandbox client and `Workspace` (editable path dependency) and does not touch
codewright's playbooks, API or web app.

## Run it

```
make demo      # web UI on http://127.0.0.1:8090 with a scripted model (no LLM needed); QA uses the live sandbox
make serve     # the same with the real model (set LLM_REMOTE_GPU_URL / LLM_LOCAL_CPU_URL / LLM_PROFILE first)
make run REQUEST="add a wishlist"   # CLI, one run, events printed to the terminal
make check     # ruff, mypy, pytest, web typecheck + tests
```

The container joins codewright's Docker network (`codewright_default`) because the sandbox runner is only reachable
there. Build context is the parent directory; `Dockerfile.dockerignore` keeps it to this repo and `../codewright`.

## How a run works

The Project Manager is one `create_deep_agent`. It plans with `write_todos`, finds who can do what with
`get_agent_capabilities`, and delegates with deepagents' `task` tool. A delegation is the objective plus optional lines:

| Line | Meaning | Enforced by code |
|---|---|---|
| `WRITES:` | paths the specialist may write | write scope; anything else is blocked |
| `DONE:` | acceptance criteria | handed to the specialist, kept on the task and in the report |
| `AFTER:` | ids of tasks that must have passed first | refused if a task does not exist or has not passed (the dependency graph) |
| `RETRY:` | id of the failed task this follows | the earlier tries, their reasons, checks and last output go to the specialist; an unchanged instruction is refused; 3 tries per piece of work; a different specialist may take it over |

Every reply the Project Manager reads ends with `[task <id> | try n | PASSED/FAILED | checked: ...]`.
**Independent evaluation** (`orchestrator/evaluate.py`) overrules a claimed pass when the files it says it wrote are
missing or empty, it wrote nothing in its scope, or it has a check tool (QA `run_tests`, DevOps `run_build`) and never
ran it or the last run exited non-zero. Without a sandbox the pass is accepted but marked `UNVERIFIED`. A run cannot
pass while failed work is unresolved. Semantic review (does it meet the requirement?) is a task for another
specialist (QA, Security Engineer), ordered with `AFTER:`.

**The agency** is a folder per agent in `orchestrator/agents/` (`prompt.md` + `config.yaml`: name, description, tools,
capabilities, `enabled`). Adding a specialist is adding a folder. Today: business analyst, product manager, solution
architect, code analyst, database engineer, backend and frontend developers, UI/UX designer, QA, DevOps, security
engineer, technical writer.

**Human in the loop.** The first delegation is held by deepagents' own human-in-the-loop interrupt until the person
approves the plan, sends it back with changes (the Project Manager revises and the plan is shown again), or rejects it
(the run stops). In the web UI these are the **Approve and start**, **Request changes** (with a note) and **Reject**
buttons on the Plan tab; the API is `POST /api/runs/{id}/approve` with `{approved, feedback}`.
Changes asked for at the final review go through the same gate: the Project Manager writes a new plan (naming the files
it will create, change or delete), the person approves it, and only then does anything run. Specialists can delete
files inside their `WRITES` scope (`delete_file`), and the independent check confirms the file is really gone. The Project Manager's conversation is checkpointed in SQLite (`runs/<id>/checkpoints.sqlite`), so a
pending approval, or a run cut off mid-way, is picked up by the next process exactly where it stopped, and finished
delegations are not run again. Destructive or outward commands (`rm -rf`, `git push`, `terraform apply`, publishing...)
need the person's explicit yes; with nobody to ask they are refused. A timeout is never an approval.

**Context cost.** The model has a 4,096-token window, so what it is sent is held to a budget
(`tests/test_context_budget.py`): the Project Manager about 1,300 tokens before any work, a specialist about 750.
`orchestrator/lean.py` shows the model short tool descriptions and argument schemas without prose (execution still uses
deepagents' own tools), and a specialist reply is cut to `max_reply_chars` when passed to the Project Manager (the full
reply is saved as the task's artifact, the status block is always kept).

Limits (`orchestrator/config.py`): 20 delegations, 3 tries per piece of work (infrastructure failures wait and retry),
60 min per run, 10 min per task. Concurrency defaults to 1 because the model server has one slot.

Guardrails enforced in code: tool allowlist per role; per-task write scope (never `.git`, never a real `.env`, size
and file-count budgets); loop detection; secret scan blocks the zip.

## Final review

When all tasks have passed, the run pauses before building the zip and asks the person whether anything should change
("Ready to deliver" card: summary, the files that will be in the zip, a box for changes). "Deliver the zip" builds the
zip. "Request changes" sends the note to the Project Manager, which delegates the extra work and the person is asked
again (up to 5 rounds). A run that did not pass is never sent for review. It is on by default in the web UI
(`final_review`), off in the CLI unless `--review` is given.

## Projects

Every run gets its own new project folder by default (named from the request, for example
`calculator-in-python-c5c38465`; the id keeps similar requests apart), so the zip holds only what that request built. The
download is named without the id (`calculator-in-python.zip`), and the thread heading in the UI is a short title made
from the prompt (the full prompt is in the tooltip and at the top of the Activity pane). Pick an existing project in the
composer to keep building on its files on purpose; the zip then holds the whole project. A project has one active run
at a time.

## What the model is sent

`docs/PROMPTS-AS-SENT.md` shows the exact system prompts, first messages, tool descriptions and injected messages.
Regenerate it with `make prompts` after editing any `prompt.md`, `config.yaml`, `TEAM_RULES` or tool docstring.

## Layout

- `orchestrator/` team (Project Manager + control), evaluation, guardrails, events, runner, server, demo model, agents (`agents/<role>/`)
- `web/` Vite + React + TypeScript UI; all state is rebuilt from the event log by one reducer (`src/model.ts`)
- `runs/<run_id>/` (inside the workspace): `events.jsonl`, `task_log.json`, `meta.json`, `checkpoints.sqlite`, artifacts, `report.md`, zip
