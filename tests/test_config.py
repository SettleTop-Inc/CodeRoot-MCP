import pytest
from coderoot_mcp.config import Settings, ConfigError


def test_refuses_to_start_without_an_api_url():
    with pytest.raises(ConfigError, match="CODEROOT_API_URL"):
        Settings(coderoot_api_url=None, coderoot_api_token="t")


def test_refuses_to_start_without_a_token():
    with pytest.raises(ConfigError, match="CODEROOT_API_TOKEN"):
        Settings(coderoot_api_url="http://x", coderoot_api_token=None)


def test_accepts_a_complete_configuration():
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t")
    assert s.request_timeout_s == 30


def test_defaults_to_stdio_transport_with_no_behaviour_change():
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t")
    assert s.mcp_transport == "stdio"


def test_http_bind_settings_default_to_loopback_and_8000():
    # mcp_http_host/mcp_http_port matter only in streamable-http mode, but
    # they still need sane defaults so constructing Settings() never fails
    # regardless of which transport ends up selected.
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t")
    assert s.mcp_http_host == "127.0.0.1"
    assert s.mcp_http_port == 8000


def test_streamable_http_transport_is_selectable():
    # coderoot_mcp_allow_anonymous=True here is incidental to what this test
    # checks (transport/host/port selection) -- it's present only to satisfy
    # the inbound-auth fail-closed validator below, exercised on its own in
    # the "inbound auth" tests further down this file.
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t",
                 mcp_transport="streamable-http", mcp_http_host="0.0.0.0",
                 mcp_http_port=9000, coderoot_mcp_allow_anonymous=True)
    assert s.mcp_transport == "streamable-http"
    assert s.mcp_http_host == "0.0.0.0"
    assert s.mcp_http_port == 9000


def test_an_unknown_transport_value_is_rejected():
    with pytest.raises(Exception):
        Settings(coderoot_api_url="http://x", coderoot_api_token="t", mcp_transport="http")


def test_fails_closed_regardless_of_which_transport_is_selected():
    # The fail-closed check (missing CODEROOT_API_URL/TOKEN) must not become
    # transport-conditional -- an HTTP-mode deployment with no credentials is
    # exactly as unsafe to serve from as a stdio one.
    with pytest.raises(ConfigError, match="CODEROOT_API_URL"):
        Settings(coderoot_api_url=None, coderoot_api_token="t",
                 mcp_transport="streamable-http")
    with pytest.raises(ConfigError, match="CODEROOT_API_TOKEN"):
        Settings(coderoot_api_url="http://x", coderoot_api_token=None,
                 mcp_transport="streamable-http")


# --- inbound auth (streamable-http only) ------------------------------------

def test_stdio_never_requires_inbound_auth_settings():
    # stdio has no listening socket, so neither CODEROOT_MCP_TOKEN nor the
    # anonymous opt-out should be demanded -- the default transport, and the
    # default configuration, must keep working unchanged.
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t")
    assert s.mcp_transport == "stdio"
    assert s.coderoot_mcp_token is None
    assert s.coderoot_mcp_allow_anonymous is False


def test_streamable_http_refuses_to_start_with_neither_token_nor_opt_out():
    with pytest.raises(ConfigError, match="CODEROOT_MCP_TOKEN"):
        Settings(coderoot_api_url="http://x", coderoot_api_token="t",
                 mcp_transport="streamable-http")


def test_streamable_http_accepts_a_configured_inbound_token():
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t",
                 mcp_transport="streamable-http", coderoot_mcp_token="secret")
    assert s.coderoot_mcp_token == "secret"


def test_streamable_http_accepts_the_explicit_anonymous_opt_out():
    s = Settings(coderoot_api_url="http://x", coderoot_api_token="t",
                 mcp_transport="streamable-http", coderoot_mcp_allow_anonymous=True)
    assert s.coderoot_mcp_allow_anonymous is True
