# codegenerator-deepagents image. Build context: the parent directory of this
# repo (../), i.e. the directory that holds both `codegenerator-deepagents/`
# and a sibling `codewright/` checkout, since this project depends on
# `codewright` via an editable path dependency (`../codewright`).
#
# Example build:
#   docker build -f codegenerator-deepagents/Dockerfile -t codegenerator-deepagents /home/ubuntu
# Stage 1: build the web UI.
FROM node:22-slim AS web
WORKDIR /web
COPY codegenerator-deepagents/web/package.json codegenerator-deepagents/web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY codegenerator-deepagents/web/ ./
RUN npm run build

# Stage 2: the orchestrator (CLI and web service).
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
COPY --from=web /web/dist /app/web/dist

RUN useradd --system --uid 10001 --home-dir /app orchestrator \
    && chown -R orchestrator /app
USER orchestrator

ENV PATH=/app/.venv/bin:$PATH \
    WEB_DIST=/app/web/dist \
    WORKSPACES_ROOT=/app/workspaces

EXPOSE 8090
# `docker run <image>` serves the web UI; `docker run <image> run ...` / `resume ...` use the CLI.
ENTRYPOINT ["python", "-m", "orchestrator.cli"]
CMD ["serve", "--port", "8090"]
