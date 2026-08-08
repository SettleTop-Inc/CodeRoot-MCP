"""Drives `BearerAuthMiddleware` through Starlette's `TestClient` -- a real
ASGI call, not a hand-called `__call__` with fabricated scope/receive/send
dicts -- against a trivial downstream app, so these tests exercise exactly
the object `coderoot_mcp/__main__.py` wraps around the real MCP Starlette
app, not a paraphrase of it.

`tests/test_http_transport.py` separately proves the guard is actually wired
onto the real `/mcp` streamable-http surface end-to-end, over a real socket,
against a real MCP client -- the two files are complementary, not
redundant: this one is the fast, exhaustive check of the auth decision
itself; that one is the "is it actually plugged in" check."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from coderoot_mcp.auth import BearerAuthMiddleware


def _downstream() -> Starlette:
    async def ok(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/mcp", ok)])


def _client(*, token: str | None, allow_anonymous: bool) -> TestClient:
    guarded = BearerAuthMiddleware(_downstream(), token=token, allow_anonymous=allow_anonymous)
    return TestClient(guarded)


def test_a_request_with_no_bearer_is_rejected():
    client = _client(token="secret", allow_anonymous=False)
    resp = client.get("/mcp")
    assert resp.status_code == 401


def test_a_request_with_the_wrong_bearer_is_rejected():
    client = _client(token="secret", allow_anonymous=False)
    resp = client.get("/mcp", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_a_request_with_the_right_bearer_succeeds():
    client = _client(token="secret", allow_anonymous=False)
    resp = client.get("/mcp", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_the_anonymous_opt_out_genuinely_allows_unauthenticated_access():
    # No token configured at all, matching the deployment shape the opt-out
    # exists for -- CODEROOT_MCP_TOKEN unset, CODEROOT_MCP_ALLOW_ANONYMOUS=true.
    client = _client(token=None, allow_anonymous=True)
    resp = client.get("/mcp")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_a_non_ascii_bearer_is_cleanly_rejected_not_a_500():
    # The exact trap this project already hit once (see auth.py's docstring
    # and this project's Assessor sibling): secrets.compare_digest raises
    # TypeError on a non-ASCII *str* argument, which -- if the comparison
    # were done on str instead of bytes -- would turn this into an unhandled
    # 500 instead of the intended 401, an authentication check that crashes
    # rather than rejects.
    #
    # httpx's client-side header encoding rejects a non-ASCII header value
    # before it ever reaches the app -- TestClient(...).get(..., headers=...)
    # with a non-ASCII value raises UnicodeEncodeError in the TEST itself,
    # never touching BearerAuthMiddleware. Drive the ASGI app directly
    # instead, with the header injected as raw latin-1-encoded bytes, the
    # same regression-test shape the sibling Assessor already uses for this
    # exact trap (assessor/tests/test_app_http.py::
    # test_non_ascii_bearer_header_is_401_not_500) -- ASGI headers are always
    # raw bytes on the wire; latin-1 is what an ASGI server decodes them as
    # per the spec, so this is how a real non-ASCII header actually arrives.
    import asyncio

    app = BearerAuthMiddleware(_downstream(), token="secret", allow_anonymous=False)
    headers = [(b"authorization", "Bearer café".encode("latin-1"))]
    scope = {"type": "http", "method": "GET", "path": "/mcp", "raw_path": b"/mcp",
              "query_string": b"", "headers": headers, "client": ("test", 123),
              "server": ("test", 80), "scheme": "http", "http_version": "1.1"}
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    assert status == 401


def test_a_malformed_header_with_no_bearer_prefix_is_rejected_not_a_500():
    client = _client(token="secret", allow_anonymous=False)
    resp = client.get("/mcp", headers={"Authorization": "secret"})
    assert resp.status_code == 401


def test_the_expected_bearer_string_itself_is_never_accepted_as_a_literal_header():
    # Guards against a degenerate bypass: if `token` were None/empty and the
    # comparison were done carelessly, a caller sending the literal string
    # "Bearer None" might match "Bearer {None}". It must not.
    client = _client(token=None, allow_anonymous=False)
    resp = client.get("/mcp", headers={"Authorization": "Bearer None"})
    assert resp.status_code == 401


def test_non_http_scopes_pass_through_unchecked():
    # Lifespan events (startup/shutdown) carry no Authorization header and
    # must not be blocked by this middleware, or the app could never start.
    # A bare recording ASGI app stands in for the downstream here, rather
    # than a real Starlette app, so this test proves what THIS middleware
    # does with a non-http scope without depending on Starlette's own
    # lifespan handling too.
    import anyio

    calls = []

    async def _recording_downstream(scope, receive, send):
        calls.append(scope["type"])

    app = BearerAuthMiddleware(_recording_downstream, token="secret", allow_anonymous=False)

    async def _noop_receive():
        return {"type": "lifespan.startup"}

    async def _noop_send(message):
        pass

    anyio.run(app, {"type": "lifespan"}, _noop_receive, _noop_send)
    assert calls == ["lifespan"]
