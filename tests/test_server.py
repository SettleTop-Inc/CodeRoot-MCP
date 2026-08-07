import json
import httpx
import pytest
from mcp.client.client import Client

from coderoot_mcp.server import build_server


class _Client:
    def __init__(self):
        self.calls = []

    def get_subject(self, repo_id, subdir):
        self.calls.append(("subject", repo_id, subdir))
        return {"commit_sha": "abc", "topics": ["mcp"], "tree_paths": ["a.py"],
                "license": "MIT", "releases": [{"tag": "v1"}]}

    def get_files(self, repo_id, commit_sha, paths):
        self.calls.append(("files", repo_id, commit_sha, tuple(paths)))
        return {"files": {"a.py": "x"}, "missing": []}

    def get_prior_assessment(self, repo_id, subdir):
        return {"content_fingerprint": "fp", "asset_types": ["mcp_server"]}

    def cache_get(self, model, h): return None
    def cache_put(self, model, h, response): self.calls.append(("put", model, h))


class _ClientNoPriorAssessment(_Client):
    def get_prior_assessment(self, repo_id, subdir):
        return None


class _ClientCacheHit(_Client):
    def cache_get(self, model, h):
        return {"asset_types": ["agent"]}


class _ClientMissingFile(_Client):
    def get_files(self, repo_id, commit_sha, paths):
        self.calls.append(("files", repo_id, commit_sha, tuple(paths)))
        return {"files": {"a.py": "x"}, "missing": ["b.py"]}


class _RaisingClient(_Client):
    """A client double whose get_subject/get_files raise httpx.HTTPStatusError
    the way the real CodeRootClient does when raise_for_status() fires (a 4xx
    or 5xx response). No client double that could fail this way existed
    before this test file -- the entire error path was unexercised."""

    def __init__(self, status_code):
        super().__init__()
        self.status_code = status_code

    def _raise(self):
        request = httpx.Request("GET", "http://api.test/x")
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError(
            f"{self.status_code} error", request=request, response=response)

    def get_subject(self, repo_id, subdir):
        self._raise()

    def get_files(self, repo_id, commit_sha, paths):
        self._raise()


@pytest.mark.anyio
async def test_all_six_tools_are_registered():
    names = {t.name for t in await build_server(_Client()).list_tools()}
    assert names == {"get_subject", "read_files", "get_metrics",
                     "get_prior_assessment", "llm_cache_get", "llm_cache_put"}


@pytest.mark.anyio
async def test_every_tool_has_a_description():
    for t in await build_server(_Client()).list_tools():
        assert t.description and len(t.description) > 20


@pytest.mark.anyio
async def test_get_subject_excludes_the_metrics_fields():
    r = await build_server(_Client()).call_tool("get_subject", {"repo_id": "r", "subdir": ""})
    body = json.loads(r.content[0].text)
    assert body["commit_sha"] == "abc"
    assert "license" not in body and "releases" not in body


@pytest.mark.anyio
async def test_get_metrics_returns_only_the_metrics_fields():
    r = await build_server(_Client()).call_tool("get_metrics", {"repo_id": "r"})
    assert json.loads(r.content[0].text) == {"license": "MIT", "releases": [{"tag": "v1"}]}


@pytest.mark.anyio
async def test_read_files_passes_the_path_list_through():
    c = _Client()
    r = await build_server(c).call_tool(
        "read_files", {"repo_id": "r", "commit_sha": "abc", "paths": ["a.py"]})
    assert json.loads(r.content[0].text)["files"] == {"a.py": "x"}
    assert ("files", "r", "abc", ("a.py",)) in c.calls


@pytest.mark.anyio
async def test_read_files_carries_missing_through_untouched():
    # The one field read_files exists to carry: a non-empty `missing` means
    # "re-acquire this repository" downstream. A tool that filtered or
    # flattened it would silently turn that into "we looked and found
    # nothing" -- so this must be asserted on directly, not just implied by
    # a fixture that happens to hard-code an empty list.
    c = _ClientMissingFile()
    r = await build_server(c).call_tool(
        "read_files", {"repo_id": "r", "commit_sha": "abc", "paths": ["a.py", "b.py"]})
    body = json.loads(r.content[0].text)
    assert body["missing"] == ["b.py"]
    assert body["files"] == {"a.py": "x"}


@pytest.mark.anyio
async def test_get_prior_assessment_found_returns_the_wrapped_assessment():
    r = await build_server(_Client()).call_tool(
        "get_prior_assessment", {"repo_id": "r", "subdir": ""})
    assert json.loads(r.content[0].text) == {
        "found": True,
        "assessment": {"content_fingerprint": "fp", "asset_types": ["mcp_server"]},
    }


@pytest.mark.anyio
async def test_get_prior_assessment_absent_still_lands_in_content():
    # Regression: a tool that returns bare `None` puts its payload in
    # structured_content instead of content[0].text, with content == [].
    # Wrapping in a dict keeps every tool on one parsing path.
    r = await build_server(_ClientNoPriorAssessment()).call_tool(
        "get_prior_assessment", {"repo_id": "r", "subdir": ""})
    assert r.content and len(r.content) > 0
    assert json.loads(r.content[0].text) == {"found": False, "assessment": None}


@pytest.mark.anyio
async def test_llm_cache_get_hit_returns_the_wrapped_response():
    r = await build_server(_ClientCacheHit()).call_tool(
        "llm_cache_get", {"model": "m", "prompt_sha256": "h"})
    assert json.loads(r.content[0].text) == {
        "hit": True, "response": {"asset_types": ["agent"]}}


@pytest.mark.anyio
async def test_llm_cache_get_miss_still_lands_in_content():
    # Same regression as above: cache miss is the common case for a cold
    # cache, so `content` must never be empty on this path.
    r = await build_server(_Client()).call_tool(
        "llm_cache_get", {"model": "m", "prompt_sha256": "h"})
    assert r.content and len(r.content) > 0
    assert json.loads(r.content[0].text) == {"hit": False, "response": None}


@pytest.mark.anyio
async def test_llm_cache_put_returns_a_confirmation_payload():
    c = _Client()
    r = await build_server(c).call_tool(
        "llm_cache_put", {"model": "m", "prompt_sha256": "h", "response": {"a": 1}})
    assert r.content and len(r.content) > 0
    assert json.loads(r.content[0].text) == {"stored": True}
    assert ("put", "m", "h") in c.calls


# --- Error handling: a routine 404 ("never acquired") must stay distinguishable
# from an upstream failure ("CodeRoot is down"). Confusing them would let an
# outage look like "nothing to assess".

@pytest.mark.anyio
async def test_get_subject_404_reports_not_acquired():
    r = await build_server(_RaisingClient(404)).call_tool(
        "get_subject", {"repo_id": "r", "subdir": ""})
    assert r.content and len(r.content) > 0
    assert json.loads(r.content[0].text) == {"error": "not_acquired"}


@pytest.mark.anyio
async def test_get_subject_5xx_reports_upstream_error_with_the_status_code():
    r = await build_server(_RaisingClient(503)).call_tool(
        "get_subject", {"repo_id": "r", "subdir": ""})
    body = json.loads(r.content[0].text)
    assert body["error"] == "upstream_error"
    assert body["status_code"] == 503


@pytest.mark.anyio
async def test_get_metrics_404_reports_not_acquired():
    r = await build_server(_RaisingClient(404)).call_tool("get_metrics", {"repo_id": "r"})
    assert json.loads(r.content[0].text) == {"error": "not_acquired"}


@pytest.mark.anyio
async def test_get_metrics_5xx_reports_upstream_error():
    r = await build_server(_RaisingClient(500)).call_tool("get_metrics", {"repo_id": "r"})
    body = json.loads(r.content[0].text)
    assert body["error"] == "upstream_error"
    assert body["status_code"] == 500


@pytest.mark.anyio
async def test_read_files_404_reports_not_acquired():
    r = await build_server(_RaisingClient(404)).call_tool(
        "read_files", {"repo_id": "r", "commit_sha": "abc", "paths": ["a.py"]})
    assert json.loads(r.content[0].text) == {"error": "not_acquired"}


@pytest.mark.anyio
async def test_read_files_5xx_reports_upstream_error():
    r = await build_server(_RaisingClient(502)).call_tool(
        "read_files", {"repo_id": "r", "commit_sha": "abc", "paths": ["a.py"]})
    body = json.loads(r.content[0].text)
    assert body["error"] == "upstream_error"
    assert body["status_code"] == 502


@pytest.mark.anyio
async def test_a_real_mcp_client_sees_the_discriminator_not_an_opaque_error_string():
    # build_server(...).call_tool() (used by every test above) calls
    # MCPServer.call_tool() directly, which never touches
    # MCPServer._handle_call_tool -- the callback actually wired to the
    # lowlevel Server as on_call_tool, and so the one a real client's
    # tools/call request is dispatched through. That handler is what rewrites
    # any exception escaping a tool into an opaque
    # `CallToolResult(content=[TextContent(text=str(e))], is_error=True)`
    # (mcp/server/mcpserver/server.py:415-424) -- the exact collapse this
    # fix exists to prevent. Driving through `mcp.client.client.Client`
    # (mode="legacy") exercises that real dispatch path end to end: a
    # JSON-RPC call over in-memory streams into `Server.run()`, the same
    # method `MCPServer.run_stdio_async` uses in production. Without the
    # fix in server.py, this test fails (see remediation report for the
    # captured pre-fix transcript): is_error is True and the body is the
    # string "Error executing tool get_subject: 404 error" instead of JSON.
    server = build_server(_RaisingClient(404))
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("get_subject", {"repo_id": "r", "subdir": ""})
    assert result.is_error is not True
    assert result.content and len(result.content) > 0
    assert json.loads(result.content[0].text) == {"error": "not_acquired"}
