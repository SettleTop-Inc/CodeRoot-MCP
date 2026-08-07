"""The MCP surface over CodeRoot's stored repository intelligence.

Every tool is a thin delegation to CodeRootClient. This module knows nothing about
HTTP; the client knows nothing about MCP."""
from __future__ import annotations

import httpx

from mcp.server.mcpserver import MCPServer

_METRIC_KEYS = ("license", "releases")


def _http_error_payload(exc: httpx.HTTPStatusError) -> dict:
    """Turn a raised HTTPStatusError into the discriminated payload the
    subject/file tools return instead of letting it escape. Returned as a
    structured dict rather than re-raised: the SDK's tool runner catches any
    exception escaping a tool and rewrites it into an opaque `ToolError`
    string (mcp/server/mcpserver/tools/base.py:181), which would destroy the
    very discriminator this exists to preserve.

    {"error": "not_acquired"} is CodeRoot's plain 404 for this repo/subdir
    (subjects.py: "no acquisition for this repo") -- a routine, expected
    answer, not a failure. The right response is to acquire it.

    {"error": "upstream_error", "status_code": <int>, "detail": <str>} is
    anything else -- CodeRoot itself is down or erroring. The right response
    is to retry later, never to read it as "this repository has no content"."""
    status = exc.response.status_code
    if status == 404:
        return {"error": "not_acquired"}
    return {"error": "upstream_error", "status_code": status, "detail": str(exc)}


def build_server(client) -> MCPServer:
    mcp = MCPServer(name="coderoot-mcp")

    @mcp.tool()
    def get_subject(repo_id: str, subdir: str = "") -> dict:
        """Return a repository's acquired snapshot metadata: the pinned commit SHA,
        description, homepage, topics, declared licence, the full path inventory and
        the marker scan, without the file bodies.

        On an HTTP failure this returns a discriminated error payload instead
        of raising: {"error": "not_acquired"} when this repository has never
        been acquired (CodeRoot's plain 404) -- acquire it and retry -- or
        {"error": "upstream_error", "status_code": <int>, "detail": <str>} for
        any other failure (5xx, auth, etc.), meaning CodeRoot itself is broken
        or unreachable and the call should be retried, not read as "this
        repository has no content"."""
        try:
            s = client.get_subject(repo_id, subdir)
        except httpx.HTTPStatusError as exc:
            return _http_error_payload(exc)
        return {k: v for k, v in s.items() if k not in _METRIC_KEYS}

    @mcp.tool()
    def get_metrics(repo_id: str) -> dict:
        """Return collected repository metrics — resolved licence and release history.
        Both may be null when they were never collected, which is a real answer and
        not an error.

        On an HTTP failure this returns a discriminated error payload instead
        of raising: {"error": "not_acquired"} for CodeRoot's plain 404 (this
        repository has never been acquired) or {"error": "upstream_error",
        "status_code": <int>, "detail": <str>} for any other failure -- see
        get_subject's docstring for what each means."""
        try:
            s = client.get_subject(repo_id, "")
        except httpx.HTTPStatusError as exc:
            return _http_error_payload(exc)
        return {k: s.get(k) for k in _METRIC_KEYS}

    @mcp.tool()
    def read_files(repo_id: str, commit_sha: str, paths: list[str]) -> dict:
        """Return the bodies of the requested file paths at a pinned commit. The
        response carries both the found file bodies and the list of paths that
        could not be read; a non-empty missing list means those paths need
        re-acquiring and must not be discarded or treated as absence of content.

        On an HTTP failure this returns a discriminated error payload instead
        of raising: {"error": "not_acquired"} for CodeRoot's plain 404 or
        {"error": "upstream_error", "status_code": <int>, "detail": <str>} for
        any other failure -- see get_subject's docstring for what each means."""
        try:
            return client.get_files(repo_id, commit_sha, paths)
        except httpx.HTTPStatusError as exc:
            return _http_error_payload(exc)

    @mcp.tool()
    def get_prior_assessment(repo_id: str, subdir: str = "") -> dict:
        """Return the most recent stored assessment for this repository and subdir,
        including its content fingerprint and previously derived asset types. When
        this repository has never been assessed, returns
        {"found": false, "assessment": null} — a real, non-error result, not an
        absent payload."""
        a = client.get_prior_assessment(repo_id, subdir)
        return {"found": a is not None, "assessment": a}

    @mcp.tool()
    def llm_cache_get(model: str, prompt_sha256: str) -> dict:
        """Look up a cached LLM response by model name and the SHA-256 hash of the
        prompt that produced it. On a cache miss — the common case against a cold
        cache — returns {"hit": false, "response": null} rather than an absent
        payload, which is a normal outcome and not an error."""
        r = client.cache_get(model, prompt_sha256)
        return {"hit": r is not None, "response": r}

    @mcp.tool()
    def llm_cache_put(model: str, prompt_sha256: str, response: dict) -> dict:
        """Store an LLM response in the cache keyed by model name and the SHA-256
        hash of the prompt, so a later call with the same key can be served without
        re-invoking the model. Returns {"stored": true} on success; a failed write
        raises rather than returning an empty payload."""
        client.cache_put(model, prompt_sha256, response)
        return {"stored": True}

    return mcp
