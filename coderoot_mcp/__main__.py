"""Entrypoint (the `coderoot-mcp` console script) for both transports.

`create_mcp()`'s absence at module scope is deliberate: `Settings()` raises
`ConfigError` when unconfigured, so building the server eagerly at import
time would make merely importing this module crash. Everything that touches
`Settings` lives inside `main()` (or is passed into `create_mcp()` by it),
which only runs when the console script is actually invoked."""
from __future__ import annotations


def create_mcp(settings=None):
    from .config import Settings
    from .client import CodeRootClient
    from .server import build_server

    s = settings if settings is not None else Settings()
    return build_server(CodeRootClient(s))


def main() -> None:
    """`Settings.mcp_transport` (default `"stdio"`, unchanged) picks which of
    `MCPServer.run()`'s transports serves this process
    (mcp/server/mcpserver/server.py's `run()` overloads):

    - "stdio": the SDK's `stdio_server()` reads/writes JSON-RPC over this
      process's stdin/stdout -- how a local MCP client (Claude Desktop, an
      IDE plugin, etc.) talks to a server it launches as a subprocess.
    - "streamable-http": the SDK serves MCP over HTTP instead (uvicorn
      serving `MCPServer.streamable_http_app()`), bound to
      `mcp_http_host`/`mcp_http_port` -- how another service dials this
      process over the network rather than spawning it.

    `Settings()` is constructed once, here, before touching either
    transport, so the fail-closed check (missing CODEROOT_API_URL/
    CODEROOT_API_TOKEN) still runs first regardless of which transport is
    selected."""
    from .config import Settings

    s = Settings()
    mcp = create_mcp(s)
    if s.mcp_transport == "streamable-http":
        mcp.run(transport="streamable-http", host=s.mcp_http_host, port=s.mcp_http_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
