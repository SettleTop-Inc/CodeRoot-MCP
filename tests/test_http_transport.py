"""Real, end-to-end proof that "streamable-http" actually serves callable
tools over the network -- not just that `Settings` parses the option.
"Test that only asserts the config parsed proves nothing about whether the
transport works" is the exact trap this file exists to avoid.

Two tiers, both driving a REAL `mcp.client.Client` over a REAL streamable-http
socket -- never an in-memory double standing in for the transport:

  1. `test_*_over_streamable_http` -- `build_server()`'s own tool contract,
     served via the SDK's real `MCPServer.streamable_http_app()` (the exact
     ASGI app `run_streamable_http_async` -- what `MCPServer.run(transport=
     "streamable-http", ...)` calls -- serves) over a real uvicorn socket.
     Client side is `mcp.client.streamable_http.streamable_http_client` +
     `mcp.client.client.Client`, the same pair the sibling Assessor repo's
     `assessor/mcp_client.py` uses for the other end of this exact
     connection. `_serve()` below mirrors that repo's
     `tests/test_mcp_client.py::_serve()` pattern (verified against that
     file directly): `.serve()`, not `.run()` -- `.run()` installs OS signal
     handlers, which only the main thread may do, and this runs in a
     background thread.

  2. `test_the_real_console_entrypoint_...` -- spawns the actual
     `coderoot-mcp` console script as a subprocess with
     MCP_TRANSPORT=streamable-http, against a real (stub) CodeRoot API, and
     drives one real tool call through the whole stack: env-var config
     parsing, `main()`'s transport dispatch (`coderoot_mcp/__main__.py`),
     and the SDK's HTTP transport itself -- exactly as a deployed operator
     would exercise them, not just the pieces in isolation.
"""
from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time

import uvicorn
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client

from coderoot_mcp.server import build_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Client:
    """Same shape as tests/test_server.py::_Client -- CodeRootClient's
    interface (not CodeRoot-MCP's own tool interface), so this file doubles
    the same boundary the rest of the suite already doubles."""

    def get_subject(self, repo_id, subdir):
        return {"commit_sha": "abc123", "topics": ["mcp"], "tree_paths": ["a.py"],
                "license": "MIT", "releases": [{"tag": "v1"}]}

    def get_files(self, repo_id, commit_sha, paths):
        return {"files": {p: "x" for p in paths}, "missing": []}

    def get_prior_assessment(self, repo_id, subdir):
        return {"content_fingerprint": "fp", "asset_types": ["mcp_server"]}

    def cache_get(self, model, h):
        return None

    def cache_put(self, model, h, response):
        pass


@contextlib.contextmanager
def _serve(mcp_server):
    """Serve a real MCPServer over a real HTTP port with uvicorn in a
    background thread, yielding the /mcp endpoint URL. `asyncio.run(server.
    serve())` (not `server.run()`, and not `MCPServer.run()`) is deliberate:
    `.run()` installs OS signal handlers, which only the main thread may do;
    `.serve()` alone does not, and it also hands back a `server` object this
    fixture can flip `should_exit` on for a clean shutdown -- `MCPServer.run()`
    builds its own `uvicorn.Server` internally with no handle exposed back."""
    port = _free_port()
    app = mcp_server.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn server did not start within 5s"
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def _call_tool(url: str, tool: str, args: dict):
    # `streamable_http_client(url)` returns an (unentered) async context
    # manager; `Client.__aenter__` enters it itself
    # (`exit_stack.enter_async_context(transport)` in mcp/client/client.py) --
    # entering it here first would hand `Client(...)` the already-yielded
    # stream tuple instead, which is not itself a context manager. Same
    # construction as the sibling Assessor repo's `assessor/mcp_client.py`
    # (`transport = streamable_http_client(...); async with Client(transport,
    # ...)`, never `async with streamable_http_client(...) as transport`).
    transport = streamable_http_client(url)
    async with Client(transport, mode="auto") as client:
        return await client.call_tool(tool, args)


# --- tier 1: build_server()'s real tool contract over a real socket --------

def test_a_real_mcp_client_calls_get_subject_over_streamable_http():
    with _serve(build_server(_Client())) as url:
        result = asyncio.run(_call_tool(url, "get_subject", {"repo_id": "r", "subdir": ""}))
    assert result.is_error is not True
    body = json.loads(result.content[0].text)
    assert body["commit_sha"] == "abc123"
    assert "license" not in body  # get_subject excludes the metrics fields


def test_read_files_round_trips_arguments_and_result_over_streamable_http():
    with _serve(build_server(_Client())) as url:
        result = asyncio.run(_call_tool(
            url, "read_files", {"repo_id": "r", "commit_sha": "abc", "paths": ["a.py"]}))
    body = json.loads(result.content[0].text)
    assert body == {"files": {"a.py": "x"}, "missing": []}


def test_tool_listing_is_visible_over_streamable_http():
    async def _list(url):
        transport = streamable_http_client(url)
        async with Client(transport, mode="auto") as client:
            return await client.list_tools()

    with _serve(build_server(_Client())) as url:
        tools = asyncio.run(_list(url))
    names = {t.name for t in tools.tools}
    assert names == {"get_subject", "read_files", "get_metrics",
                     "get_prior_assessment", "llm_cache_get", "llm_cache_put"}


# --- tier 2: the real console entrypoint, as a subprocess ------------------

class _StubCodeRootHandler(http.server.BaseHTTPRequestHandler):
    """A real (if minimal) upstream CodeRoot API for the SUBPROCESS's own
    CodeRootClient to call -- httpx.MockTransport only works inside the
    process that constructed it, so an out-of-process test needs a real
    listener instead."""

    def do_GET(self):
        if self.path.startswith("/repos/") and self.path.endswith("/subject?subdir="):
            body = json.dumps({"commit_sha": "abc123", "topics": [],
                               "license": "MIT", "releases": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:  # pragma: no cover - not exercised by this test
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # keep pytest output quiet


@contextlib.contextmanager
def _stub_coderoot_api():
    port = _free_port()
    httpd = http.server.HTTPServer(("127.0.0.1", port), _StubCodeRootHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.05)
    return False


def test_the_real_console_entrypoint_serves_a_real_tool_call_over_streamable_http():
    """Spawns the ACTUAL `coderoot-mcp` entrypoint -- env-var config parsing,
    `main()`'s transport dispatch, and the SDK's streamable-http transport,
    exactly as a deployed operator would run it -- against a real (stub)
    CodeRoot API, and drives one real tool call through the whole stack."""
    port = _free_port()
    with _stub_coderoot_api() as api_url:
        env = dict(os.environ)
        env.update({
            "CODEROOT_API_URL": api_url,
            "CODEROOT_API_TOKEN": "test-token",
            "MCP_TRANSPORT": "streamable-http",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": str(port),
        })
        proc = subprocess.Popen(
            [sys.executable, "-m", "coderoot_mcp"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            started = _wait_for_port("127.0.0.1", port, timeout=15)
            if not started:
                proc.terminate()
                out = proc.stdout.read() if proc.stdout else ""
                assert started, f"server did not start listening within 15s; output:\n{out}"

            result = asyncio.run(_call_tool(
                f"http://127.0.0.1:{port}/mcp", "get_subject", {"repo_id": "r", "subdir": ""}))
            assert result.is_error is not True
            body = json.loads(result.content[0].text)
            assert body["commit_sha"] == "abc123"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - platform-dependent
                proc.kill()
                proc.wait(timeout=5)
