"""The MCP surface over CodeRoot's stored repository intelligence.

Every tool is a thin delegation to CodeRootClient. This module knows nothing about
HTTP; the client knows nothing about MCP."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

_METRIC_KEYS = ("license", "releases")


def build_server(client) -> MCPServer:
    mcp = MCPServer(name="coderoot-mcp")

    @mcp.tool()
    def get_subject(repo_id: str, subdir: str = "") -> dict:
        """Return a repository's acquired snapshot metadata: the pinned commit SHA,
        description, homepage, topics, declared licence, the full path inventory and
        the marker scan, without the file bodies."""
        s = client.get_subject(repo_id, subdir)
        return {k: v for k, v in s.items() if k not in _METRIC_KEYS}

    @mcp.tool()
    def get_metrics(repo_id: str) -> dict:
        """Return collected repository metrics — resolved licence and release history.
        Both may be null when they were never collected, which is a real answer and
        not an error."""
        s = client.get_subject(repo_id, "")
        return {k: s.get(k) for k in _METRIC_KEYS}

    @mcp.tool()
    def read_files(repo_id: str, commit_sha: str, paths: list[str]) -> dict:
        """Return the bodies of the requested file paths at a pinned commit. The
        response carries both the found file bodies and the list of paths that
        could not be read; a non-empty missing list means those paths need
        re-acquiring and must not be discarded or treated as absence of content."""
        return client.get_files(repo_id, commit_sha, paths)

    @mcp.tool()
    def get_prior_assessment(repo_id: str, subdir: str = "") -> dict | None:
        """Return the most recent stored assessment for this repository and subdir,
        including its content fingerprint and previously derived asset types.
        Returns null when this repository has never been assessed."""
        return client.get_prior_assessment(repo_id, subdir)

    @mcp.tool()
    def llm_cache_get(model: str, prompt_sha256: str) -> dict | None:
        """Look up a cached LLM response by model name and the SHA-256 hash of the
        prompt that produced it. Returns null on a cache miss, which is a normal
        outcome and not an error."""
        return client.cache_get(model, prompt_sha256)

    @mcp.tool()
    def llm_cache_put(model: str, prompt_sha256: str, response: dict) -> None:
        """Store an LLM response in the cache keyed by model name and the SHA-256
        hash of the prompt, so a later call with the same key can be served without
        re-invoking the model."""
        client.cache_put(model, prompt_sha256, response)

    return mcp
