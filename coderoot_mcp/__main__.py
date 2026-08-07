"""Stdio entrypoint (the `coderoot-mcp` console script).

`create_mcp()`'s absence at module scope is deliberate: `Settings()` raises
`ConfigError` when unconfigured, so building the server eagerly at import
time would make merely importing this module crash. Everything that touches
`Settings` lives inside `main()`, which only runs when the console script is
actually invoked."""
from __future__ import annotations


def create_mcp():
    from .config import Settings
    from .client import CodeRootClient
    from .server import build_server

    s = Settings()
    return build_server(CodeRootClient(s))


def main() -> None:
    """`MCPServer.run()` defaults to the "stdio" transport — the SDK's
    `stdio_server()` reads/writes JSON-RPC over this process's stdin/stdout,
    which is how a local MCP client (Claude Desktop, an IDE plugin, etc.)
    talks to a server it launches as a subprocess."""
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
