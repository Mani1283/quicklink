# Agentic Software Engineering System: URL Shortener

A runnable, dependency-free Python prototype that converts engineering requests into governed, reviewable work. It includes a URL shortener API, SQLite persistence and analytics, plus an orchestration engine with dependency gates, parallel stages, approval checkpoints, retries, rollback hooks, policy checks, audit events, replanning, and reliability metrics.

## Requirements

- Python 3.11 or later
- No third-party packages are required

## Run

From this directory:

```sh
python -m src.agentic_shortener.server
```

The service listens on `http://127.0.0.1:8000`. Set `HOST`, `PORT`, or `SHORTENER_DB` to override defaults. The database is created at `./data/shortener.db`.

### Shorten and use a URL

```sh
curl -X POST http://127.0.0.1:8000/api/shorten \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/products?id=42","expires_in_days":30}'
```

Follow the returned `short_url` to redirect. The service does not fetch or preview submitted URLs.

### Run a scenario from the CLI

```sh
python run_scenario.py greenfield
python run_scenario.py brownfield --request "Add click analytics without breaking existing clients"
```

The CLI pauses at every human approval gate. It writes run snapshots and stage artifacts to `artifacts/runs/<run_id>/`, and appends workflow events to `data/orchestration-audit.jsonl`.

The CLI pauses for each human approval gate. Generated run snapshots and stage artifacts are written to `artifacts/runs/<run_id>/`; the hash-chained audit log is written to `data/orchestration-audit.jsonl`.

### Windows PowerShell examples

Start the API in one PowerShell window:

```powershell
python -m src.agentic_shortener.server
```

In a second window, create a short link (PowerShell uses a backtick for line continuation):

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/shorten" `
  -H "Content-Type: application/json" `
  -d '{"url":"https://example.com"}'
```

Or use PowerShell's native HTTP command:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/shorten `
  -ContentType 'application/json' -Body '{"url":"https://example.com"}'
```

### Orchestrate an engineering request

```sh
curl http://127.0.0.1:8000/api/orchestration/scenarios
curl -X POST http://127.0.0.1:8000/api/orchestration/runs \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"greenfield","request":"Build an audited URL shortener"}'
```

Fetch a run using its returned `run_id`. Runs pause at human approval gates. Approve or reject a pending gate with `POST /api/orchestration/runs/{run_id}/approvals`, using `{"decision":"approve","gate_id":"...","actor":"reviewer"}`. Rejection stops the run. `GET /api/orchestration/metrics` reports reliability measures.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness and DB availability |
| POST | `/api/shorten` | Create a short link |
| GET | `/{code}` | Record a click and redirect |
| GET | `/api/links/{code}` | Link metadata and click analytics |
| GET | `/api/orchestration/scenarios` | Scenario catalog and DAGs |
| POST | `/api/orchestration/runs` | Start an orchestration run |
| GET | `/api/orchestration/runs/{run_id}` | Run state, lineage, and audit events |
| POST | `/api/orchestration/runs/{run_id}/approvals` | Approve or reject a gate |
| POST | `/api/orchestration/runs/{run_id}/replan` | Revise an active request and invalidate stale outputs/approvals |
| POST | `/api/orchestration/runs/{run_id}/retry` | Request a bounded retry for a failed stage |
| POST | `/api/orchestration/runs/{run_id}/rollback` | Reset a stage and its dependents; state-only rollback |
| POST | `/api/orchestration/runs/{run_id}/stop` | Safe-stop an active run |
| GET | `/api/orchestration/metrics` | Aggregate reliability metrics |
| GET | `/api/orchestration/audit/verify` | Verify the local JSONL audit hash chain |
| GET | `/openapi.json` | OpenAPI 3.1 contract |

The API is intentionally small and uses Python's standard-library HTTP server. In production, put it behind a hardened ASGI/WSGI server and TLS-terminating reverse proxy.

## Project structure

```text
src/agentic_shortener/   API, persistence, URL service, rate limiter, named agents, controls
scenarios/               Greenfield, brownfield, and ambiguous request examples
tests/                   Unit and HTTP integration tests (unittest)
docs/                    Architecture, controls, testing, and scenario notes
artifacts/runs/          Generated run snapshots and per-stage output JSON
run_scenario.py          Interactive CLI with approval checkpoints
```

## Scenarios

- **Greenfield:** create a URL shortener from a new-system request.
- **Brownfield:** change analytics for an existing service while preserving API compatibility.
- **Ambiguous:** clarify retention and privacy requirements before implementation.

Each scenario describes actionable stages and dependencies, runs design and policy analysis in parallel after requirements, gates implementation and release on human approval, and keeps a decision trail. See [`docs/SCENARIOS.md`](docs/SCENARIOS.md).

## Validation

Run the standard-library test suite:

```sh
python -m unittest discover -s tests -v
```

Tests cover URL validation, creation, redirection, expiry, analytics, DAG ordering, approval gates, policy blocks, bounded retries, fallback, replanning, rate limiting, audit-chain verification, artifact export, and HTTP behavior.

## Agent providers and brownfield repository input

The default is deterministic and works offline. To enable the optional OpenAI Responses API stage agent, set `AGENT_PROVIDER=openai`, `OPENAI_API_KEY`, and (optionally) `OPENAI_MODEL` before starting the service or CLI. This sends the request plus bounded repository context to the configured provider. Do not enable it for sensitive source unless that data flow is approved. The adapter has no tools and cannot write to the repository, execute commands, or deploy. Proposed files are exported under the run's `changes/` folder for review; they are never applied automatically. If the provider fails, the workflow uses its deterministic fallback and records that fact.

For brownfield runs, the project root is scanned by default. To scan another local repo, pass `--repository PATH` to the CLI or `repository_path` in the run API request. `ALLOWED_REPOSITORY_ROOTS` limits eligible paths. The scanner skips common dependency/build/data directories, bounds file and character counts, and applies heuristic secret redaction. Redaction is not guaranteed; review the data flow before enabling an external provider.

## Known limits

- The deterministic provider is a reference agent, not a general-purpose coding model. The optional OpenAI adapter produces proposals and still requires human review; no model API credentials are included.
- The built-in HTTP server is for local demonstration, not high-throughput production deployment.
- Analytics are aggregate click counts and timestamps. No IP addresses, user agents, or referrers are retained.
- POST endpoints use a process-local per-IP sliding window limit (60 requests per 60 seconds by default). Configure `POST_RATE_LIMIT` and `POST_RATE_WINDOW_SECONDS` for local tuning.
- Authentication, tenancy, custom domains, distributed queues, and multi-instance coordination are not implemented.
- The limiter is process-local and trusts the direct peer IP. Production needs a shared limiter and a trusted-proxy policy.
- JSONL audit chaining detects edits but does not make local storage immutable. Production needs access-controlled remote/WORM audit storage and reconciliation with the SQLite event ledger.
- SQLite is suitable for a prototype; production should use a managed database and explicit migrations.
- Human approvals are stored with the run and actor string; production identity, authorization, signatures, and reviewer separation must be integrated.
- The API has no authentication/authorization layer. Keep it bound to localhost for this prototype; do not expose it to an untrusted network.
- MTTR is a stage recovery interval from a recorded stage failure to a later success for that same stage; production incident MTTR needs incident detection and restoration events from the operations platform.
- The local JSONL audit chain is coordinated across processes on the same host, but remains mutable by a privileged operator and is not a substitute for remote immutable audit storage.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CONTROLS.md`](docs/CONTROLS.md), and [`docs/TESTING.md`](docs/TESTING.md).
