IMAGE = codegenerator-deepagents:dev
NET = codewright_default
VOLUME = codewright_workspaces
# Model settings are passed through from your shell when set (same names codewright uses).
LLM_ENV = -e LLM_REMOTE_GPU_URL -e LLM_LOCAL_CPU_URL -e LLM_PROFILE -e REMOTE_GPU_API_KEY -e LOCAL_CPU_API_KEY

check:
	uv run ruff check .
	uv run mypy orchestrator
	uv run pytest
	cd web && npm run typecheck && npm test

build:
	docker build -f Dockerfile -t $(IMAGE) ..

# The web UI and API on http://127.0.0.1:8090, using the real model and the live sandbox.
serve: build
	docker run --rm -it --network $(NET) -p 127.0.0.1:8090:8090 -v $(VOLUME):/app/workspaces $(LLM_ENV) $(IMAGE)

# The same, with a scripted model (no LLM needed). QA really runs tests in the live sandbox.
demo: build
	docker run --rm -it --network $(NET) -p 127.0.0.1:8090:8090 -v $(VOLUME):/app/workspaces \
		-e ORCH_DEMO=1 -e ORCH_DEMO_SANDBOX=1 $(IMAGE)

run: build
	docker run --rm -it --network $(NET) -v $(VOLUME):/app/workspaces $(LLM_ENV) \
		$(IMAGE) run --project demo --workspaces-root /app/workspaces "$(REQUEST)"

prompts:
	uv run python scripts/capture_prompts.py
