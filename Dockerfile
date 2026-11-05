# codegenerator-deepagents image. Build context: the parent directory of this
# repo (../), i.e. the directory that holds both `codegenerator-deepagents/`
# and a sibling `codewright/` checkout, since this project depends on
# `codewright` via an editable path dependency (`../codewright`).
#
# Example build:
#   docker build -f codegenerator-deepagents/Dockerfile -t codegenerator-deepagents /home/ubuntu
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv

# git: codewright's own agent runtime shells out to git for project imports / change delivery.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sibling checkout of codewright, resolved by the editable path dependency
# `codewright = { path = "../codewright", editable = true }` in pyproject.toml.
COPY codewright /codewright

# Dependencies first (cached layer), then the source.
COPY codegenerator-deepagents/pyproject.toml codegenerator-deepagents/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY codegenerator-deepagents/orchestrator orchestrator

RUN useradd --system --uid 10001 --home-dir /app orchestrator \
    && chown -R orchestrator /app
USER orchestrator

ENV PATH=/app/.venv/bin:$PATH

ENTRYPOINT ["python", "-m", "orchestrator.cli"]
