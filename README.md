# codegenerator-deepagents

A plan / dispatch / observe / replan orchestrator for Codewright's role roster, built on
[`deepagents`](https://pypi.org/project/deepagents/). It depends on `codewright`'s own `agent`
package (LLM client, workspace tools, sandbox tools) via an editable path dependency on a sibling
`../codewright` checkout — this repo is meant to live next to `codewright/` on disk, e.g.:

```
/home/ubuntu/codewright/
/home/ubuntu/codegenerator-deepagents/
```

## Running

This project must run attached to `codewright`'s `codewright_default` Docker network so it can
reach `sandbox-runner` (and any other Codewright services it talks to). Run it with:

```
make run REQUEST="..."
```

## Development

```
uv sync
uv run python -c "import deepagents, agent.llm.client, agent.tools.workspace, agent.tools.sandbox; print('ok')"
```

The second command is a smoke test for the dependency wiring: it confirms that the editable path
dependency on `../codewright` resolves and that `codewright`'s `agent` package imports cleanly from
inside this project's environment.
