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
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, json={"commit_sha": "abc"})

    assert _client(h).get_subject("rid-1", "")["commit_sha"] == "abc"
    assert seen["url"] == "http://api.test/repos/rid-1/subject?subdir="
    assert seen["auth"] == "Bearer tok"


def test_get_files_posts_the_path_list():
    seen = {}

    def h(request):
        import json
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"files": {"a.py": "x"}, "missing": []})

    out = _client(h).get_files("rid-1", "abc", ["a.py"])
    assert out["files"] == {"a.py": "x"}
    assert seen["body"] == {"commit_sha": "abc", "paths": ["a.py"]}


def test_prior_assessment_absent_is_none_not_an_error():
    assert _client(lambda r: httpx.Response(404))\
        .get_prior_assessment("rid-1", "") is None


def test_cache_miss_is_none():
    assert _client(lambda r: httpx.Response(200, json={"hit": False, "response": None}))\
        .cache_get("m", "h") is None


def test_cache_hit_returns_the_payload():
    assert _client(lambda r: httpx.Response(200, json={"hit": True, "response": {"a": 1}}))\
        .cache_get("m", "h") == {"a": 1}


def test_an_upstream_5xx_raises_rather_than_returning_empty():
    with pytest.raises(Exception):
        _client(lambda r: httpx.Response(503)).get_subject("rid-1", "")
