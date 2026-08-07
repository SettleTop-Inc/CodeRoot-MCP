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
