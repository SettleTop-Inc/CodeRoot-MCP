"""Startup-time configuration for CodeRoot-MCP.

This service reads CodeRoot's stored repository intelligence over HTTP using a
bearer token. Both the base URL and the token are mandatory: without them there
is nothing safe to serve, so the service refuses to start rather than come up
half-configured. Mirrors the fail-closed pattern used by the sibling Assessor
service (`assessor/config.py`): a `model_validator(mode="after")` raises
`ConfigError`, a plain `Exception` subclass — pydantic only rewraps
`ValueError`/`TypeError`/`AssertionError` raised from validators, so a plain
`Exception` propagates uncaught and `pytest.raises(ConfigError)` sees it directly.
"""
from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised at construction when the configuration is unsafe to serve with."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False,
                                      extra="ignore")

    coderoot_api_url: str | None = None
    coderoot_api_token: str | None = None
    request_timeout_s: int = 30

    @model_validator(mode="after")
    def _fails_closed(self) -> "Settings":
        if not self.coderoot_api_url:
            raise ConfigError(
                "refusing to start without CODEROOT_API_URL: CodeRoot-MCP has "
                "nothing to serve from without it")
        if not self.coderoot_api_token:
            raise ConfigError(
                "refusing to start without CODEROOT_API_TOKEN: every CodeRoot "
                "route sits behind bearer auth")
        return self
