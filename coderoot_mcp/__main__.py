"""Entrypoint (the `coderoot-mcp` console script) for both transports.

`create_mcp()`'s absence at module scope is deliberate: `Settings()` raises
`ConfigError` when unconfigured, so building the server eagerly at import
time would make merely importing this module crash. Everything that touches
`Settings` lives inside `main()` (or is passed into `create_mcp()` by it),
which only runs when the console script is actually invoked.

`uvicorn` is imported at module level (not lazily inside a function, unlike
the pattern above) purely so tests can monkeypatch `uvicorn.Server` via this
module's own attribute -- the import itself has no side effect and does not
touch `Settings`, so it does not threaten the no-import-time-crash invariant
`tests/test_main.py::test_importing_main_has_no_side_effects_when_unconfigured`
guards."""
from __future__ import annotations

import uvicorn

from .auth import BearerAuthMiddleware


def create_mcp(settings=None):
    from .config import Settings
    from .client import CodeRootClient
    from .server import build_server

    s = settings if settings is not None else Settings()
    return build_server(CodeRootClient(s))


def main() -> None:
    """`Settings.mcp_transport` (default `"stdio"`, unchanged) picks how this
    process is served:

    - "stdio": `MCPServer.run(transport="stdio")` -- the SDK's
      `stdio_server()` reads/writes JSON-RPC over this process's stdin/
      stdout, how a local MCP client (Claude Desktop, an IDE plugin, etc.)
      talks to a server it launches as a subprocess. Unchanged.
    - "streamable-http": served by `_run_streamable_http` below, NOT by
      `MCPServer.run(transport="streamable-http", ...)` -- see that
      function's docstring for why the two are no longer the same call.

    `Settings()` is constructed once, here, before touching either
    transport, so the fail-closed check (missing CODEROOT_API_URL/
    CODEROOT_API_TOKEN, or -- for streamable-http -- missing
    CODEROOT_MCP_TOKEN/CODEROOT_MCP_ALLOW_ANONYMOUS) still runs first
    regardless of which transport is selected."""
    from .config import Settings

    s = Settings()
    mcp = create_mcp(s)
    if s.mcp_transport == "streamable-http":
        _run_streamable_http(mcp, s)
    else:
        mcp.run(transport="stdio")


def _run_streamable_http(mcp, s) -> None:
    """Serves `mcp.streamable_http_app()` over uvicorn directly, wrapped in
    `BearerAuthMiddleware`, instead of delegating to
    `MCPServer.run(transport="streamable-http", ...)`.

    That delegation is what this function replaced, and it cannot carry
    inbound auth: `run_streamable_http_async` (what `.run()` calls for this
    transport) builds the Starlette app AND the `uvicorn.Server` itself,
    internally, with no hook to wrap the app in middleware first and no
    handle exposed back afterward. Building both here instead -- app, then
    middleware, then uvicorn -- mirrors
    `tests/test_http_transport.py`'s own `_serve()` helper, which already
    does the same thing for the same underlying reason (there: to keep a
    handle for clean shutdown; here: to insert the auth guard)."""
    app = mcp.streamable_http_app(host=s.mcp_http_host)
    guarded = BearerAuthMiddleware(app, token=s.coderoot_mcp_token,
                                    allow_anonymous=s.coderoot_mcp_allow_anonymous)
    config = uvicorn.Config(guarded, host=s.mcp_http_host, port=s.mcp_http_port,
                             log_level=mcp.settings.log_level.lower())
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
