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

Two environment variables are required. The service refuses to start
without both — see `coderoot_mcp/config.py` — so a misconfigured deployment
fails immediately rather than serving with nothing behind it. This holds
regardless of transport.

| Variable | Required | Meaning |
| --- | --- | --- |
| `CODEROOT_API_URL` | yes | Base URL of the CodeRoot API this server reads through — no trailing slash, no `/v1` prefix. |
| `CODEROOT_API_TOKEN` | yes | Bearer token sent as `Authorization: Bearer <token>` on every request to CodeRoot. |
| `REQUEST_TIMEOUT_S` | no (default `30`) | Per-request timeout, in seconds, for calls to CodeRoot. |
| `MCP_TRANSPORT` | no (default `stdio`) | `stdio` or `streamable-http` — which MCP transport this process serves. See "Running" below. |
| `MCP_HTTP_HOST` | no (default `127.0.0.1`) | Bind address, used only when `MCP_TRANSPORT=streamable-http`. The container image overrides this to `0.0.0.0` — binding all interfaces inside a container is correct; the published port is the operator's choice. |
| `MCP_HTTP_PORT` | no (default `8000`) | Bind port, used only when `MCP_TRANSPORT=streamable-http`. |

## Running

This service supports two MCP transports, selected by `MCP_TRANSPORT`. The
default is unchanged from before this option existed.

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
  coderoot-mcp:dev
```

No `-i` is needed here — the container doesn't read stdin in this mode. The
image already sets `MCP_HTTP_HOST=0.0.0.0` so the published port reaches the
process inside the container; override `MCP_HTTP_PORT` (and the `-p` mapping
to match) to use a different port.

### Both modes

Omit either required environment variable and the process exits immediately,
non-zero, instead of hanging on a stdin read or starting an HTTP listener:
configuration is validated in `main()` before either transport is ever
touched.

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
