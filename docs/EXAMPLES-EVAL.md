# Few-shot examples: on versus off, measured on the real model

Model: Qwen3.5-9B (4096-token context), live sandbox. Harness: `scripts/eval_examples.py` (a scripted Project
Manager delegates the SAME instruction to one real specialist; only `RunConfig.examples` differs; conditions
are interleaved in random order). Raw rows: `docs/eval/`. Team size: `scripts/eval_team_size.py`.

## What was measured
- accepted: the code's independent check passed (for Security and Code Analyst the correct outcome is `fail`).
- quality: an automatic check of the files the specialist wrote (task specific, same for both conditions).

## Run 1 (before fixes): examples did NOT help
24 runs per condition, 8 tasks: accepted ON 17 / OFF 20, quality ON 16 / OFF 16.
Two causes found by reading the failures: the rewritten prompts had lost the "save with write_file" rule (the most
common failure in both conditions was "wrote no file"), and the document-role examples described the content but
never showed it being saved with `write_file`, so the model imitated a prose answer. Two of my checks were also
wrong (`out-of-scope` with hyphens; Security's correct outcome is `fail`).

## Run 2 (after fixes: `write_file` rule in TEAM_RULES, examples show the save, checks corrected)
11 tasks (DevOps excluded: in the runs I inspected the sandbox rejected the build (`SandboxRequestError: Docker 400 ... OCI runtime`) and 0 of 6 were accepted in both conditions, so it measures nothing),
3 repeats per task and condition (5 for the database task):

| | examples ON | examples OFF |
|---|---|---|
| accepted | 31 / 35 (89%) | 25 / 35 (71%) |
| quality | 30 / 35 (86%) | 23 / 35 (66%) |
| tool calls per task | 2.3 | 1.9 |
| seconds per task | 4.8 | 4.6 |
| largest prompt seen (tokens) | 1685 avg | 1516 avg |

Fisher exact, two-sided: p = 0.13 (accepted), p = 0.09 (quality). That is a trend, not a proven effect.
Per task (quality ON/OFF): Product Manager 2/3 vs 0/3, Solution Architect 3/3 vs 1/3, Business Analyst 3/3 vs 2/3,
UI/UX 2/3 vs 1/3, Security 1/3 vs 0/3 (and with examples it correctly reported `fail` 3/3 versus 1/3 without);
equal for Backend, Frontend, QA, Writer; worse for Code Analyst (2/3 vs 3/3). One QA run with examples was stopped by the
repeated-call guard. Only first tries were measured; the `for: retry` examples are untested on the real model.

## Context cost (real token counts from the model server)
The first call of a specialist (system prompt + TEAM_RULES + tools + task) is 1,076 to 1,577 tokens without
examples and 1,112 to 1,577 with them (+0 to +150: nothing is added when nothing matches, as for the Business
Analyst's notes task in some repeats). The largest prompt seen in any run was 2,563 tokens (QA, after reading files and
running tests), leaving about 1,500 of the 4,096 for the answer and further reads. The example budget leaves
`work_reserve_tokens` (1,500) free by construction.

## Project Manager team size (real Project Manager, 3 simple requests x 2)
"Make a calculator", "Write a Python function that reverses a string, with a test", "Create a small command-line todo
list in Python": 6 of 6 runs passed with exactly backend-developer + qa-engineer (2 to 4 tasks, 20 to 65 s), no analyst,
product manager, architect, designer or UI, and only the requested files. (`.pytest_cache` also ended up in the project folder; the zip does not
exclude it yet.)

## Limits
Small samples (3 per cell), one model, one run each of the two experiments, my own tasks and checks, examples written by
the same person who wrote the prompts. Treat the result as encouraging, repeat before relying on it.
