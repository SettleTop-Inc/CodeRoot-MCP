# CodeRoot-MCP

Serve CodeRoot's stored repository intelligence — snapshots, metrics, prior
assessments, and the LLM response cache — over MCP.

**This service performs no GitHub access of its own.** It is a thin,
read-through MCP surface over data CodeRoot has already acquired and stored
elsewhere: every tool call is exactly one HTTP request to the CodeRoot API,
authenticated with a bearer token. It does not clone or fetch from GitHub,
does not run acquisition, and does not run any classification or judgment
logic — see `coderoot_mcp/client.py` for the full set of routes it calls.

## Configuration

Two environment variables are required unconditionally. The service refuses
to start without both — see `coderoot_mcp/config.py` — so a misconfigured
deployment fails immediately rather than serving with nothing behind it.
This holds regardless of transport.

| Variable | Required | Meaning |
| --- | --- | --- |
| `CODEROOT_API_URL` | yes | Base URL of the CodeRoot API this server reads through — no trailing slash, no `/v1` prefix. |
| `CODEROOT_API_TOKEN` | yes | Bearer token sent as `Authorization: Bearer <token>` on every request to CodeRoot. |
| `REQUEST_TIMEOUT_S` | no (default `30`) | Per-request timeout, in seconds, for calls to CodeRoot. |
| `MCP_TRANSPORT` | no (default `stdio`) | `stdio` or `streamable-http` — which MCP transport this process serves. See "Running" below. |
| `MCP_HTTP_HOST` | no (default `127.0.0.1`) | Bind address, used only when `MCP_TRANSPORT=streamable-http`. The container image overrides this to `0.0.0.0` — binding all interfaces inside a container is correct; the published port is the operator's choice. |
| `MCP_HTTP_PORT` | no (default `8000`) | Bind port, used only when `MCP_TRANSPORT=streamable-http`. |
| `CODEROOT_MCP_TOKEN` | yes, when `MCP_TRANSPORT=streamable-http` | Bearer token every streamable-http caller must send as `Authorization: Bearer <token>`. See "Inbound auth" below. |
| `CODEROOT_MCP_ALLOW_ANONYMOUS` | no (default `false`) | Explicit opt-out of inbound auth on streamable-http. See "Inbound auth" below. |

### Inbound auth (streamable-http only)

`stdio` has no listening socket — a local client spawns this process and
exchanges JSON-RPC over that process's own stdin/stdout, a trust boundary
already enforced by whoever can spawn the process. `streamable-http` opens a
real network listener, and every one of the six tools is a read (or, for
`llm_cache_put`, a write) against data CodeRoot holds behind its own bearer
auth — without a check here, anyone who can reach the port reaches that data
through this service's own `CODEROOT_API_TOKEN`, regardless of whether they
hold one themselves.

So, when `MCP_TRANSPORT=streamable-http`, the service refuses to start
unless one of the following is set (mirrors the sibling Assessor's
`ASSESSOR_API_TOKEN`/`ASSESSOR_ALLOW_ANONYMOUS`, `assessor/config.py`):

- `CODEROOT_MCP_TOKEN` — every request must carry
  `Authorization: Bearer <CODEROOT_MCP_TOKEN>` or it is rejected with 401.
  This is the same value the sibling Assessor already sends as its own
  `CODEROOT_MCP_TOKEN` (`assessor/config.py`'s `coderoot_mcp_token`,
  consumed by `assessor/mcp_client.py`) — one shared secret, set on both
  services.
- `CODEROOT_MCP_ALLOW_ANONYMOUS=true` — an explicit, deliberate opt-out that
  serves every request unauthenticated. Only appropriate where the network
  path to this port is already controlled some other way (e.g. loopback-only
  publish with nothing else on the host).

The check lives in `coderoot_mcp/auth.py`, applied by
`coderoot_mcp/__main__.py` as ASGI middleware wrapping the Starlette app
`MCPServer.streamable_http_app()` returns — not the `mcp` SDK's own OAuth
resource-server machinery (`TokenVerifier`/`AuthSettings`), which solves a
different, heavier problem than "compare a static bearer token."

## Run with Docker (GHCR)

The image is published to the GitHub Container Registry as
`ghcr.io/settletop-inc/coderoot-mcp`. Tags: `:latest` and `:sha-<short>` for
every push to `main`, and `:vX.Y.Z` for a release tag. (To build it yourself
from this repo instead, see [Running](#running) below.)

**This package is private (org-only), so pulling it requires authenticating to
GHCR first — a one-time step per machine.** Log in with a GitHub Personal
Access Token (classic) that has the `read:packages` scope, supplying the token
as the password:

```bash
docker login ghcr.io -u <github-username>
# Password: a classic PAT with the read:packages scope
```

Or, with the GitHub CLI:

```bash
gh auth refresh -s read:packages
docker login ghcr.io -u <github-username> -p "$(gh auth token)"
```

Without this, `docker pull` / `docker run` of the image returns
`403 Forbidden`.

Then run it. This server speaks MCP over **stdio** by default — the container
reads JSON-RPC on its stdin and writes replies on its stdout — so it must be
run with stdin attached (`-i`). It performs no filesystem or GitHub access of
its own (every tool call is one HTTP request to the CodeRoot API — see
`coderoot_mcp/client.py`), so **no volume mount is needed**; it needs only the
two required environment variables (see [Configuration](#configuration)):

```bash
docker run -i --rm \
  -e CODEROOT_API_URL=http://host.docker.internal:8080 \
  -e CODEROOT_API_TOKEN=<token> \
  ghcr.io/settletop-inc/coderoot-mcp
```

From inside a container, `http://host.docker.internal:8080` reaches a CodeRoot
API running on the host. Run by hand like this the process just waits on stdin
with no output — that is correct; a real MCP client (below) is what drives it.
Omit a required variable and it exits immediately with
`refusing to start without CODEROOT_API_URL` (or `...CODEROOT_API_TOKEN`). To
serve over the network instead of stdio, see the `streamable-http` mode under
[Running](#running).

## Use with Claude Code

Register the published image with Claude Code so it launches the container as
a stdio subprocess. The `-i` is **required** — it is what keeps stdin attached
for the MCP handshake:

```
claude mcp add coderoot -- docker run --rm -i -e CODEROOT_API_URL=http://host.docker.internal:8080 -e CODEROOT_API_TOKEN=<token> ghcr.io/settletop-inc/coderoot-mcp
```

**Local (no Docker), with uv.** After `uv sync --locked --all-extras` in a
clone of this repo, register the `coderoot-mcp` console script (declared in
`pyproject.toml`) directly. Pass the env with Claude Code's own `-e` flags, and
`--directory` so `uv run` launches from the repo no matter where you invoke it:

```
claude mcp add coderoot -e CODEROOT_API_URL=http://localhost:8080 -e CODEROOT_API_TOKEN=<token> -- uv run --directory /path/to/CodeRoot-MCP coderoot-mcp
```

(Locally the CodeRoot API is reached at `http://localhost:8080` — not
`host.docker.internal`, which only applies from inside a container.)

**Confirm it's connected.** `claude mcp list` should show `coderoot` as
connected, and inside Claude Code the six [Tools](#tools) below —
`get_subject`, `get_metrics`, `read_files`, `get_prior_assessment`,
`llm_cache_get`, `llm_cache_put` — become available.

## Running

This section covers building the image from source and the two MCP transports,
selected by `MCP_TRANSPORT`. The default is unchanged from before this option
existed. (To use the already-published image instead, see
[Run with Docker (GHCR)](#run-with-docker-ghcr) above.)

### stdio (default) — a local client spawns this as a subprocess

An MCP client (an IDE plugin, a desktop app) launches this image as a
subprocess and exchanges JSON-RPC over that process's own stdin/stdout. No
port is used in this mode — the container must be run with stdin attached:

```bash
docker build -t coderoot-mcp:dev .

docker run -i --rm \
  -e CODEROOT_API_URL=http://host.docker.internal:8080 \
  -e CODEROOT_API_TOKEN=changeme \
  coderoot-mcp:dev
```

`-i` keeps stdin open so the container waits there for JSON-RPC requests, the
way a real MCP client subprocess would drive it — it will not print anything
on its own and will keep running until the client (or you) closes the
connection.

### streamable-http — another service dials this over the network

Set `MCP_TRANSPORT=streamable-http` and publish the port instead. This is
what makes the container a deployable asset in its own right rather than a
subprocess one client at a time can spawn — any number of services can dial
it concurrently at `http://<host>:<port>/mcp`:

```bash
docker build -t coderoot-mcp:dev .

docker run --rm -p 8000:8000 \
  -e CODEROOT_API_URL=http://host.docker.internal:8080 \
  -e CODEROOT_API_TOKEN=changeme \
  -e MCP_TRANSPORT=streamable-http \
  -e CODEROOT_MCP_TOKEN=changeme-too \
  coderoot-mcp:dev
```

No `-i` is needed here — the container doesn't read stdin in this mode. The
image already sets `MCP_HTTP_HOST=0.0.0.0` so the published port reaches the
process inside the container; override `MCP_HTTP_PORT` (and the `-p` mapping
to match) to use a different port. `CODEROOT_MCP_TOKEN` is required in this
mode (or `CODEROOT_MCP_ALLOW_ANONYMOUS=true` as an explicit opt-out) — see
"Inbound auth" above.

### Both modes

Omit a required environment variable and the process exits immediately,
non-zero, instead of hanging on a stdin read or starting an HTTP listener:
configuration is validated in `main()` before either transport is ever
touched. `CODEROOT_API_URL`/`CODEROOT_API_TOKEN` are required in both modes;
`CODEROOT_MCP_TOKEN` (or the explicit `CODEROOT_MCP_ALLOW_ANONYMOUS` opt-out)
is required only in `streamable-http` mode, since `stdio` opens no listener
for it to guard.

## Tools

| Tool | Returns |
| --- | --- |
| `get_subject(repo_id, subdir="")` | A repository's acquired snapshot metadata: pinned commit SHA, description, homepage, topics, declared licence, the full path inventory and the marker scan — without file bodies or the metrics fields. |
| `get_metrics(repo_id)` | Collected repository metrics: resolved licence and release history. Either may be `null` when never collected — a real answer, not an error. |
| `read_files(repo_id, commit_sha, paths)` | The bodies of the requested file paths at a pinned commit, plus the list of paths that could not be read. A non-empty missing list means those paths need re-acquiring, not that they're empty. |
| `get_prior_assessment(repo_id, subdir="")` | The most recent stored assessment for this repository/subdir, including its content fingerprint and previously derived asset types. `{"found": false, "assessment": null}` when never assessed. |
| `llm_cache_get(model, prompt_sha256)` | A cached LLM response keyed by model name and the SHA-256 hash of the prompt that produced it. `{"hit": false, "response": null}` on a cache miss. |
| `llm_cache_put(model, prompt_sha256, response)` | Stores an LLM response in the cache under that same key, so a later call with it can be served without re-invoking the model. Returns `{"stored": true}`. |

`get_subject`, `get_metrics` and `read_files` return
`{"error": "not_acquired"}` in place of raising when CodeRoot answers with
its plain 404 for "no acquisition for this repo" — a routine, expected
result, not a failure. All six tools return
`{"error": "upstream_error", "status_code": <int>, "detail": <str>}` for any
other HTTP failure (5xx, auth, etc.), meaning CodeRoot itself is down or
erroring and the call should be retried — never read as "this repository has
no content." See `coderoot_mcp/server.py` for the exact payload each tool
returns.

## Development

```bash
uv sync --locked --all-extras
uv run pytest
```

The image installs from `uv.lock` (`uv export --locked | uv pip install
--system -r -`), not from `pyproject.toml` directly, so the dependency graph
CI validates and the graph that ships in the image are the same graph.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
