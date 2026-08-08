"""Startup-time configuration for CodeRoot-MCP.

This service reads CodeRoot's stored repository intelligence over HTTP using a
bearer token. Both the base URL and the token are mandatory: without them there
is nothing safe to serve, so the service refuses to start rather than come up
half-configured. Mirrors the fail-closed pattern used by the sibling Assessor
service (`assessor/config.py`): a `model_validator(mode="after")` raises
`ConfigError`, a plain `Exception` subclass — pydantic only rewraps
`ValueError`/`TypeError`/`AssertionError` raised from validators, so a plain
`Exception` propagates uncaught and `pytest.raises(ConfigError)` sees it directly.

`mcp_transport` selects how `coderoot_mcp/__main__.py` serves this process --
"stdio" (the default, unchanged) for a local client that spawns this as a
subprocess, or "streamable-http" for another service to dial over the
network -- see that module for how the choice is used. `mcp_http_host`/
`mcp_http_port` matter only in "streamable-http" mode; `mcp_http_host`
defaults to loopback, the same convention as the sibling Assessor's
`assessor_bind_addr` (`assessor/config.py`) -- the container image overrides
it to 0.0.0.0 via a Dockerfile `ENV`, matching that service's own pattern
(binding all interfaces is correct inside a container; the published port is
the operator's choice).

`coderoot_mcp_token`/`coderoot_mcp_allow_anonymous` guard the "streamable-http"
transport's network listener the same way `assessor_api_token`/
`assessor_allow_anonymous` guard the sibling Assessor's -- a required inbound
bearer token, with an explicit boolean that must be set to run without one.
Named `CODEROOT_MCP_TOKEN` (not, say, `MCP_API_TOKEN`) to match this
codebase's own naming convention already visible in the sibling repos: a
shared secret is named after the SERVICE the token grants access to, the same
name on the sending side (the Assessor's `assessor/config.py` already reads
`CODEROOT_MCP_TOKEN` as the token it sends here) and the receiving side (here).
`coderoot_api_token` above is the same pattern in the other direction -- the
token this service sends TO CodeRoot.

Deliberately scoped to "streamable-http": stdio has no listening socket at
all -- a local client spawns this process and exchanges JSON-RPC over that
process's own stdin/stdout, a trust boundary already enforced by whoever can
spawn the process, not by anything a bearer header could add. Requiring
CODEROOT_MCP_TOKEN unconditionally would force every local stdio deployment
(an IDE plugin, Claude Desktop) to set a credential that protects nothing
there, and would break every existing stdio caller (including this repo's own
test suite) for no security benefit. See coderoot_mcp/auth.py for where the
token is actually checked."""
from __future__ import annotations

from typing import Literal

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

    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8000

    # --- inbound auth (streamable-http transport only; see module docstring) ---
    coderoot_mcp_token: str | None = None
    coderoot_mcp_allow_anonymous: bool = False

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
        # Only the "streamable-http" transport opens a network listener -- see
        # the module docstring for why stdio is exempt.
        if (self.mcp_transport == "streamable-http"
                and not self.coderoot_mcp_token
                and not self.coderoot_mcp_allow_anonymous):
            raise ConfigError(
                "refusing to serve streamable-http unauthenticated: set "
                "CODEROOT_MCP_TOKEN, or set CODEROOT_MCP_ALLOW_ANONYMOUS=true "
                "to opt out deliberately")
        return self
