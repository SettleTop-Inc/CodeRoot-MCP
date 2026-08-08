"""Guards the one invariant coderoot_mcp.__main__ exists to protect: that
importing the module never constructs Settings() (which raises ConfigError
when unconfigured). A module-level `create_mcp()`/server construction would
make merely importing this module crash on an unconfigured machine -- the
exact defect that cost the sibling Assessor repo a fix round."""
import importlib
import sys
from types import SimpleNamespace


def test_importing_main_has_no_side_effects_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CODEROOT_API_URL", raising=False)
    monkeypatch.delenv("CODEROOT_API_TOKEN", raising=False)
    # Force a fresh import even if some earlier test already cached the
    # module, so the module body actually executes under this environment.
    sys.modules.pop("coderoot_mcp.__main__", None)
    importlib.import_module("coderoot_mcp.__main__")


# --- main()'s transport dispatch --------------------------------------------
# Fast, no sockets: these guard the wiring in coderoot_mcp/__main__.py itself
# (which transport gets selected, and with what kwargs/middleware) by
# substituting fakes for the real MCPServer and the real uvicorn.Server.
# Whether the SDK's streamable-http transport -- and the auth guard wrapped
# around it -- actually works over a real socket is a different question,
# answered by tests/test_http_transport.py -- a test that only asserts these
# dispatch args proves nothing about whether a real client could connect.

class _RecordingMcp:
    """Stands in for the real MCPServer. `.run()` records stdio dispatch
    (unchanged path); `.streamable_http_app()` records the streamable-http
    path's app-building call (coderoot_mcp/__main__.py's `_run_streamable_http`
    no longer calls `.run(transport="streamable-http", ...)` at all -- see
    that function's docstring for why)."""

    def __init__(self):
        self.calls = []
        self.streamable_http_app_calls = []
        self.settings = SimpleNamespace(log_level="INFO")

    def run(self, transport, **kwargs):
        self.calls.append((transport, kwargs))

    def streamable_http_app(self, *, host):
        self.streamable_http_app_calls.append(host)
        return "FAKE_STARLETTE_APP"


class _RecordingUvicornServer:
    """Stands in for uvicorn.Server so the streamable-http dispatch test
    never binds a real socket. `.run()` deliberately does nothing -- the
    real one blocks forever serving requests."""
    instances: list["_RecordingUvicornServer"] = []

    def __init__(self, config):
        self.config = config
        _RecordingUvicornServer.instances.append(self)

    def run(self):
        pass


def _reload_main():
    sys.modules.pop("coderoot_mcp.__main__", None)
    return importlib.import_module("coderoot_mcp.__main__")


def test_main_defaults_to_stdio_with_no_transport_kwargs(monkeypatch):
    monkeypatch.setenv("CODEROOT_API_URL", "http://x")
    monkeypatch.setenv("CODEROOT_API_TOKEN", "t")
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    mod = _reload_main()

    fake = _RecordingMcp()
    monkeypatch.setattr(mod, "create_mcp", lambda settings: fake)
    mod.main()

    assert fake.calls == [("stdio", {})]
    # stdio never touches the streamable-http app-building path at all.
    assert fake.streamable_http_app_calls == []


def test_main_dispatches_to_streamable_http_with_the_configured_host_and_port(monkeypatch):
    monkeypatch.setenv("CODEROOT_API_URL", "http://x")
    monkeypatch.setenv("CODEROOT_API_TOKEN", "t")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_HTTP_PORT", "9001")
    monkeypatch.setenv("CODEROOT_MCP_TOKEN", "secret")
    mod = _reload_main()

    fake = _RecordingMcp()
    monkeypatch.setattr(mod, "create_mcp", lambda settings: fake)
    _RecordingUvicornServer.instances.clear()
    monkeypatch.setattr(mod.uvicorn, "Server", _RecordingUvicornServer)
    mod.main()

    # No more mcp.run(transport="streamable-http", ...) call -- see
    # _run_streamable_http's docstring for why (no hook to insert the auth
    # middleware through it).
    assert fake.calls == []
    assert fake.streamable_http_app_calls == ["0.0.0.0"]
    assert len(_RecordingUvicornServer.instances) == 1
    config = _RecordingUvicornServer.instances[0].config
    assert (config.host, config.port) == ("0.0.0.0", 9001)
    # The app handed to uvicorn is the auth-guarded wrapper, not the bare
    # Starlette app -- this is the actual security-relevant assertion: an
    # unguarded fake app reaching uvicorn.Config would mean the middleware
    # silently stopped being wired in.
    from coderoot_mcp.auth import BearerAuthMiddleware
    assert isinstance(config.app, BearerAuthMiddleware)
    assert config.app._token == "secret"
    assert config.app._allow_anonymous is False


def test_main_still_fails_closed_before_touching_either_transport(monkeypatch):
    from coderoot_mcp.config import ConfigError

    monkeypatch.delenv("CODEROOT_API_URL", raising=False)
    monkeypatch.setenv("CODEROOT_API_TOKEN", "t")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    mod = _reload_main()

    fake = _RecordingMcp()
    monkeypatch.setattr(mod, "create_mcp", lambda settings: fake)
    try:
        mod.main()
        assert False, "expected ConfigError"
    except ConfigError:
        pass
    assert fake.calls == []
    assert fake.streamable_http_app_calls == []


def test_main_still_fails_closed_when_streamable_http_has_no_inbound_auth(monkeypatch):
    # The NEW fail-closed branch (config.py's CODEROOT_MCP_TOKEN /
    # CODEROOT_MCP_ALLOW_ANONYMOUS check) must run before either transport is
    # touched too, same as the pre-existing CODEROOT_API_URL/TOKEN check
    # above -- this is the one this whole change exists to add.
    from coderoot_mcp.config import ConfigError

    monkeypatch.setenv("CODEROOT_API_URL", "http://x")
    monkeypatch.setenv("CODEROOT_API_TOKEN", "t")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.delenv("CODEROOT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("CODEROOT_MCP_ALLOW_ANONYMOUS", raising=False)
    mod = _reload_main()

    fake = _RecordingMcp()
    monkeypatch.setattr(mod, "create_mcp", lambda settings: fake)
    try:
        mod.main()
        assert False, "expected ConfigError"
    except ConfigError:
        pass
    assert fake.calls == []
    assert fake.streamable_http_app_calls == []
