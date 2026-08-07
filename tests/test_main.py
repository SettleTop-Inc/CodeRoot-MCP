"""Guards the one invariant coderoot_mcp.__main__ exists to protect: that
importing the module never constructs Settings() (which raises ConfigError
when unconfigured). A module-level `create_mcp()`/server construction would
make merely importing this module crash on an unconfigured machine -- the
exact defect that cost the sibling Assessor repo a fix round."""
import importlib
import sys


def test_importing_main_has_no_side_effects_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CODEROOT_API_URL", raising=False)
    monkeypatch.delenv("CODEROOT_API_TOKEN", raising=False)
    # Force a fresh import even if some earlier test already cached the
    # module, so the module body actually executes under this environment.
    sys.modules.pop("coderoot_mcp.__main__", None)
    importlib.import_module("coderoot_mcp.__main__")


# --- main()'s transport dispatch --------------------------------------------
# Fast, no sockets: these guard the wiring in coderoot_mcp/__main__.py itself
# (which transport gets selected, and with what kwargs) by substituting a
# fake object in place of the real MCPServer's .run(). Whether the SDK's
# streamable-http transport actually works over a real socket when selected
# is a different question, answered by tests/test_http_transport.py -- a
# test that only asserts these dispatch args proves nothing about whether a
# real client could connect.

class _RecordingMcp:
    def __init__(self):
        self.calls = []

    def run(self, transport, **kwargs):
        self.calls.append((transport, kwargs))


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


def test_main_dispatches_to_streamable_http_with_the_configured_host_and_port(monkeypatch):
    monkeypatch.setenv("CODEROOT_API_URL", "http://x")
    monkeypatch.setenv("CODEROOT_API_TOKEN", "t")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_HTTP_PORT", "9001")
    mod = _reload_main()

    fake = _RecordingMcp()
    monkeypatch.setattr(mod, "create_mcp", lambda settings: fake)
    mod.main()

    assert fake.calls == [("streamable-http", {"host": "0.0.0.0", "port": 9001})]


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
