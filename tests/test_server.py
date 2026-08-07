import json
import pytest
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
