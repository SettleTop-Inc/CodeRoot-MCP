"""Typed HTTP client for CodeRoot's data-plane routes.

One `httpx.Client` per instance, base URL and bearer header set once at
construction so no call site can forget auth or leak the token into a request
body. `transport=` exists purely so tests can inject `httpx.MockTransport` and
exercise the real `httpx.Client` request path (header handling, URL building)
rather than mocking around it.

Every route raises on a non-2xx response, with exactly one documented
exception: `get_prior_assessment` treats 404 as "not yet assessed" and returns
`None`. Nowhere else does a failure get swallowed into an empty result — a
5xx from CodeRoot must surface as an error, not as data that looks like "this
repo has nothing," or a downstream assessor would read an outage as grounds
for a false `not_derivable` verdict.
"""
from __future__ import annotations

import httpx

from .config import Settings


class CodeRootClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=settings.coderoot_api_url,
            timeout=settings.request_timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {settings.coderoot_api_token}"},
        )

    def get_subject(self, repo_id: str, subdir: str) -> dict:
        r = self._client.get(f"/repos/{repo_id}/subject", params={"subdir": subdir})
        r.raise_for_status()
        return r.json()

    def get_files(self, repo_id: str, commit_sha: str, paths: list[str]) -> dict:
        r = self._client.post(
            f"/repos/{repo_id}/files",
            json={"commit_sha": commit_sha, "paths": paths},
        )
        r.raise_for_status()
        return r.json()

    def get_prior_assessment(self, repo_id: str, subdir: str) -> dict | None:
        r = self._client.get(f"/repos/{repo_id}/assessment", params={"subdir": subdir})
        if r.status_code == 404:
            # No acquisition/assessment row yet — the normal state for most
            # repos, not a failure.
            return None
        r.raise_for_status()
        return r.json()

    def cache_get(self, model: str, prompt_sha256: str) -> dict | None:
        r = self._client.get(
            "/llm-cache", params={"model": model, "prompt_sha256": prompt_sha256}
        )
        r.raise_for_status()
        data = r.json()
        return data["response"] if data["hit"] else None

    def cache_put(self, model: str, prompt_sha256: str, response: dict) -> None:
        r = self._client.post(
            "/llm-cache",
            json={"model": model, "prompt_sha256": prompt_sha256, "response": response},
        )
        r.raise_for_status()

    def close(self) -> None:
        self._client.close()
