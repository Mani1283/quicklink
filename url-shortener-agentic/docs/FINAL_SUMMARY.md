# Final engineering summary

## Plan and rationale

The prototype separates a small URL shortener product from a stateful engineering workflow. The service uses Python's standard library and SQLite so it can run locally without external packages. The orchestration uses a validated dependency graph, parallel ready stages, persisted state, specialist stage-agent adapters, and human gates for implementation and release. Deterministic agents keep the example repeatable; a provider implementation can replace the router without changing the graph engine.

## Delivered artifacts

- Runnable shortener API with URL validation, opaque codes, expiry, redirects, click counts, and SQLite persistence.
- Greenfield, brownfield, and ambiguous scenario definitions and documented walkthroughs.
- Workflow engine with DAG validation, parallel execution, shared artifacts and decisions, approval gates, replanning, bounded retries, fallback, state rollback, and safe stop.
- Process-local POST rate limiting.
- SQLite event ledger, hash-chained JSONL audit mirror, audit verification endpoint, and atomic per-run artifact export.
- Named deterministic requirement, architecture, implementation, validation, documentation, release, policy, clarification, and brownfield analysis agents, plus an opt-in OpenAI Responses adapter.
- Bounded and heuristic-redacted brownfield repository scanning under configured allowlisted roots; generated source, test, and documentation files remain review proposals in run artifacts.
- OpenAPI 3.1 endpoint, interactive `run_scenario.py`, unit/integration tests, setup guide, architecture overview, controls, scenarios, and testing approach.

## Validation and safety

The repository includes `unittest` coverage for the shortener, workflow, API, rate limiter, audit chain, artifact export, repository scanning, and mocked model-adapter behavior. The suite result is recorded in the delivery response. The workflow fails closed on policy blocks and stage failures, approvals are bound to gate IDs and plan versions, re-planning invalidates prior decisions, and the release agent never deploys.

## Assumptions

- The ambiguous analytics scenario uses aggregate counts only, with no IP address, user-agent, or referrer retention until a human specifies otherwise.
- Deterministic agents are the default. The optional OpenAI adapter requires the user to configure an API key and sends request/repository context to that provider only when explicitly enabled.
- Human actor values are labels for this prototype and are not authenticated identities.

## Risks, trade-offs, and limits

- The built-in HTTP server and SQLite database are local-prototype choices, not a production deployment topology.
- Rate limiting is per-process and keyed by the direct peer IP. Production needs trusted proxy handling and a shared limiter.
- The local audit hash chain is tamper-evident, but privileged users can still alter local files. Production needs remote immutable storage and reconciliation with the SQLite ledger.
- Rollback restores orchestration state and removes dependent artifacts; it cannot undo external side effects because agents have no external tools.
- Reported MTTR is the stage failure-to-recovery interval, not operational incident MTTR. Production needs incident detection and restoration telemetry.
- Authentication, authorization, tenancy, custom domains, abuse/takedown operations, migrations, backups, and distributed workers remain deployment work.
- Repository redaction is heuristic and cannot guarantee removal of all sensitive data. Brownfield scanning and any external-provider use must be reviewed against source-code handling policy.
