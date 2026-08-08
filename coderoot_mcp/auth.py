"""Inbound bearer-token guard for the streamable-http transport.

stdio has no listening socket: a local client spawns this process and
exchanges JSON-RPC over that process's own stdin/stdout, so there is no
network boundary for a bearer token to protect there (see config.py's
docstring). This guard exists only for "streamable-http" -- wired in by
`coderoot_mcp/__main__.py`, which wraps the Starlette app
`MCPServer.streamable_http_app()` returns before handing it to uvicorn.

Deliberately NOT the `mcp` SDK's own OAuth machinery
(`TokenVerifier`/`AuthSettings`/`RequireAuthMiddleware`, passed to
`MCPServer(...)`/`streamable_http_app(...)`): that is a full OAuth 2.1
resource-server framework -- WWW-Authenticate resource metadata, protected-
resource routes, an authorization server provider. This service needs
exactly what the sibling Assessor already built for the identical problem
(`assessor/app.py`'s `auth()` dependency): compare one static bearer token,
fail closed, explicit opt-out. Mirroring that scheme instead of adopting a
second, heavier one keeps the two services' operator-facing behaviour
identical -- same header, same failure mode, same escape hatch.
"""
from __future__ import annotations

import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerAuthMiddleware:
    """Rejects any HTTP request whose `Authorization` header is not exactly
    `Bearer {token}`, unless `allow_anonymous` is set -- in which case every
    request passes through unchecked, matching the Assessor's
    `assessor_allow_anonymous` semantics exactly (not a lower bar, not a
    different check for a subset of routes).

    Only `scope["type"] == "http"` requests are checked. Streamable-HTTP's
    session negotiation happens over ordinary HTTP requests to `/mcp` (GET
    for the SSE stream, POST for JSON-RPC), not a separate scope type, so
    this is the only scope that ever carries a client-supplied header here;
    `lifespan` (startup/shutdown events from uvicorn) is passed straight
    through since it has no `Authorization` header to check.

    Compares bytes, not str, and constant-time. Two traps this specifically
    guards against, both already hit once in this project's sibling
    (`assessor/app.py`'s own comment on this exact line):
      1. `secrets.compare_digest` requires both arguments to be the same
         type (str/str or bytes/bytes) and raises `TypeError` if either
         *str* argument contains a non-ASCII character -- so an
         unauthenticated caller sending a header with any byte >= 0x80 (a
         pasted token with a smart quote, any multi-byte UTF-8 character)
         would 500 inside the auth check itself, before any bearer value was
         even compared, turning "reject" into an unhandled crash. Encoding
         both sides to bytes first removes the restriction entirely rather
         than special-casing non-ASCII input.
      2. `compare_digest(None, expected)` raises `TypeError` too -- the
         missing-header case is guarded explicitly before the comparison
         ever runs, rather than relying on the comparison to reject `None`
         for us.

    A third guard, not present in the sibling Assessor's version of this
    check: `self._token is None` is rejected outright, before building the
    expected string. Without it, `f"Bearer {self._token}"` with
    `self._token = None` stringifies to the literal `"Bearer None"`, which a
    caller could then send verbatim and pass. `config.py`'s fail-closed
    validator already makes `token=None, allow_anonymous=False` unreachable
    in this service's own startup path, but this class does not rely on that
    invariant holding at every future call site -- found by this module's
    own test suite (`test_the_expected_bearer_string_itself_is_never_
    accepted_as_a_literal_header`), not carried over from the Assessor.
    """

    def __init__(self, app: ASGIApp, *, token: str | None, allow_anonymous: bool) -> None:
        self._app = app
        self._token = token
        self._allow_anonymous = allow_anonymous

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._allow_anonymous:
            await self._app(scope, receive, send)
            return

        authorization = Request(scope).headers.get("authorization")
        if self._token is None or authorization is None or not secrets.compare_digest(
                authorization.encode(), f"Bearer {self._token}".encode()):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)
