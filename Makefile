check:
	uv run ruff check .
	uv run mypy orchestrator
	uv run pytest

run:
	docker build -t codegenerator-deepagents:dev .
	docker run --rm -it --network codewright_default \
		-v codewright_workspaces:/app/workspaces \
		codegenerator-deepagents:dev run --project demo --workspaces-root /app/workspaces "$(REQUEST)"
