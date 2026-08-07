# CodeRoot-MCP — MCP surface over CodeRoot's stored repository intelligence.
# This service performs no GitHub access and no git operations of its own; it
# is a thin HTTP client against the CodeRoot API, so (unlike the sibling
# Assessor's image) no `git` package is needed here.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY coderoot_mcp ./coderoot_mcp
# --locked (not --frozen) fails the build if uv.lock has drifted from
# pyproject.toml, matching CI's `uv sync --locked` gate (ci.yml) so the graph
# CI validates and the graph that ships are the same. Exported to a
# requirements file and installed with `uv pip install --system` rather than
# `uv sync` so the image keeps a no-venv layout (global site-packages, CMD
# invokes the `coderoot-mcp` console script directly). `--no-emit-project` +
# a separate `--no-deps .` install: the exported file pins every dependency
# at its exact locked version, and installing the local package with
# --no-deps afterward can't reintroduce unpinned resolution for its own
# dependencies.
RUN uv export --locked --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --system --no-cache -r requirements.txt \
    && uv pip install --system --no-cache --no-deps .

# Non-root so a container runtime can enforce non-root execution.
RUN useradd --uid 1000 --create-home --shell /bin/bash app && chown -R app:app /app
USER 1000

# This service speaks MCP over stdio, not HTTP: there is no port to EXPOSE
# and no health endpoint to add — an MCP client launches this image as a
# subprocess and exchanges JSON-RPC over the process's own stdin/stdout, so
# it must be run with stdin attached (`docker run -i --rm ...`; see README).
# Configuration is env-only (CODEROOT_API_URL, CODEROOT_API_TOKEN — see
# coderoot_mcp/config.py) and `main()` fails closed before ever touching
# stdio when either is missing, so an unconfigured container exits
# immediately instead of hanging on a stdin read.
CMD ["coderoot-mcp"]
