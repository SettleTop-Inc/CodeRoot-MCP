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

# Transport is selected at runtime by MCP_TRANSPORT (coderoot_mcp/config.py),
# defaulting to "stdio" so this image's behaviour is unchanged unless an
# operator opts in to "streamable-http":
#
#   stdio (default): an MCP client launches this image as a subprocess and
#   exchanges JSON-RPC over the process's own stdin/stdout — no port is used
#   in this mode, and it must be run with stdin attached
#   (`docker run -i --rm ...`; see README).
#
#   streamable-http: this image instead serves MCP over HTTP, so another
#   service can dial it over the network rather than spawning it — run with
#   MCP_TRANSPORT=streamable-http and a published port (see README).
#
# MCP_HTTP_HOST defaults to 127.0.0.1 in coderoot_mcp/config.py (a safe
# default for a bare process); overridden to 0.0.0.0 here so the container
# listens on all interfaces when HTTP mode is selected — binding all
# interfaces inside a container is correct, the published port is the
# operator's choice (mirrors the sibling Assessor's ASSESSOR_BIND_ADDR,
# Dockerfile). EXPOSE is documentation only, and a no-op in stdio mode.
ENV MCP_HTTP_HOST=0.0.0.0
EXPOSE 8000

# Configuration is env-only (CODEROOT_API_URL, CODEROOT_API_TOKEN — see
# coderoot_mcp/config.py) and `main()` fails closed before ever touching
# either transport when one is missing, so an unconfigured container exits
# immediately instead of hanging on a stdin read or an HTTP listener.
CMD ["coderoot-mcp"]
