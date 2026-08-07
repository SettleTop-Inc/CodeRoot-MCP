import json
import httpx
import pytest
from coderoot_mcp.config import Settings
from coderoot_mcp.client import CodeRootClient

_S = Settings(coderoot_api_url="http://api.test", coderoot_api_token="tok")


def _client(handler):
    return CodeRootClient(_S, transport=httpx.MockTransport(handler))


def test_get_subject_calls_the_right_route_and_carries_the_bearer():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, json={"commit_sha": "abc"})

    assert _client(h).get_subject("rid-1", "")["commit_sha"] == "abc"
    assert seen["method"] == "GET"
    assert seen["url"] == "http://api.test/repos/rid-1/subject?subdir="
    assert seen["auth"] == "Bearer tok"


def test_get_files_posts_the_path_list():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"files": {"a.py": "x"}, "missing": []})

    out = _client(h).get_files("rid-1", "abc", ["a.py"])
    assert out["files"] == {"a.py": "x"}
    assert seen["method"] == "POST"
    assert seen["url"] == "http://api.test/repos/rid-1/files"
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"commit_sha": "abc", "paths": ["a.py"]}


def test_prior_assessment_absent_is_none_not_an_error():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(404)

    assert _client(h).get_prior_assessment("rid-1", "") is None
    assert seen["method"] == "GET"
    assert seen["url"] == "http://api.test/repos/rid-1/assessment?subdir="
    assert seen["auth"] == "Bearer tok"


def test_cache_miss_is_none():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"hit": False, "response": None})

    assert _client(h).cache_get("m", "h") is None
    assert seen["method"] == "GET"
    assert seen["url"] == "http://api.test/llm-cache?model=m&prompt_sha256=h"
    assert seen["auth"] == "Bearer tok"


def test_cache_hit_returns_the_payload():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"hit": True, "response": {"a": 1}})

    assert _client(h).cache_get("m", "h") == {"a": 1}
    assert seen["method"] == "GET"
    assert seen["url"] == "http://api.test/llm-cache?model=m&prompt_sha256=h"
    assert seen["auth"] == "Bearer tok"


def test_cache_put_posts_the_full_payload():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"stored": True})

    _client(h).cache_put("m", "h", {"a": 1})
    assert seen["method"] == "POST"
    assert seen["url"] == "http://api.test/llm-cache"
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"model": "m", "prompt_sha256": "h", "response": {"a": 1}}
    assert set(seen["body"]) == {"model", "prompt_sha256", "response"}


def test_an_upstream_5xx_raises_rather_than_returning_empty():
    seen = {}

    def h(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(503)

    with pytest.raises(Exception):
        _client(h).get_subject("rid-1", "")
    assert seen["method"] == "GET"
    assert seen["url"] == "http://api.test/repos/rid-1/subject?subdir="
