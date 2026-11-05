# codegenerator-deepagents

A plan / act / observe / replan orchestrator with a web UI. A Project Manager agent writes a to-do list; ten
specialist agents do the tasks (side by side where the list allows); every result is checked in code, never by
trusting the agent's own claim; failures replan; the run ends with a report and a zip of the code.

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

## The loop

`plan` (Project Manager: tasks with `depends_on` and `writes`) -> `approve` (optional) -> `act` (start every ready
task, up to `concurrency`, never two with overlapping `writes`) -> observe each result in code -> `plan` again on a
failure, else `act` -> `report` (secret scan, per-task commits, `report.md`, `delivery.zip`) or `escalate`.

Limits (`orchestrator/config.py`): 2 attempts per task (counted across roles), 20 dispatches, 3 replans, 60 min per
run, 10 min per task, 2 invalid plans in a row. Concurrency defaults to 1 because the model server has one slot.

Guardrails enforced in code: tool allowlist per role; per-task write scope (never `.git`, never a real `.env`, size
and file-count budgets); QA/DevOps status comes from the real exit code of `run_tests` / `run_build`; secret scan
blocks the zip; a plan can be held for approval.

## Final review

When all tasks have passed, the run pauses before building the zip and asks the person whether anything should change
("Ready to deliver" card: summary, the files that will be in the zip, a box for changes). "Deliver the zip" builds the
zip. "Request changes" sends the note to the Project Manager, which delegates the extra work and the person is asked
again (up to 5 rounds). A run that did not pass is never sent for review. It is on by default in the web UI
(`final_review`), off in the CLI unless `--review` is given.

## Projects

Every run gets its own new project folder by default (named from the request, for example
`calculator-in-python-c5c38465`), so the zip holds only what that request built. Pick an existing project in the
composer to keep building on its files on purpose; the zip then holds the whole project. A project has one active run
at a time.

## What the model is sent

`docs/PROMPTS-AS-SENT.md` shows the exact system prompts, first messages, tool descriptions and injected messages.
Regenerate it with `make prompts` after editing any `prompt.md`, `config.yaml`, `TEAM_RULES` or tool docstring.

## Layout

- `orchestrator/` graph, loop rules, guardrails, events, runner, server, demo model, roles (`agents/<role>/`)
- `web/` Vite + React + TypeScript UI; all state is rebuilt from the event log by one reducer (`src/model.ts`)
- `runs/<run_id>/` (inside the workspace): `events.jsonl`, `task_log.json`, `meta.json`, artifacts, `report.md`, zip
