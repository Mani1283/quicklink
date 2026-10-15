# Risk, policy, and change controls

| Risk | Control in prototype | Remaining production work |
|---|---|---|
| Malformed or unsafe destination URL | Scheme/host/credential/length validation; service never fetches URL | Abuse detection, domain reputation, takedown process |
| Click analytics privacy | Aggregate count and timestamp only | Document retention, deletion, and applicable privacy obligations |
| Code collision | Random opaque code, unique constraint, bounded allocation attempts | Collision monitoring and capacity planning |
| Request flooding | Bounded process-local sliding-window POST rate limit per peer IP | Shared distributed limiter, trusted proxy handling, abuse monitoring |
| High-impact autonomous change | Approval gate bound to gate ID and plan version | Authenticated reviewer, role authorization, separation of duties |
| Prompt/request injection into workflow | Policy checks, typed stage contract, deterministic baseline agent | Provider-specific prompt isolation and output schema validation |
| Agent or dependency failure | Bounded retries and fail-closed stage status | Circuit breaker, queue, alerting, per-provider budgets |
| Partial workflow result | SQLite run snapshot, per-run artifact export, and hash-chained JSONL mirror | Backup, retention, remote WORM audit storage, and ledger reconciliation |
| Unexpected upstream changes | Replan invalidates approvals and downstream artifacts | Explicit artifact hashes and diff-aware selective invalidation |
| Unsafe release | Release artifact cannot perform deployment; approval required | CI/CD policy, signed artifact, canary, rollback runbook |

## Guardrail behavior

- Block requests asking to disable authentication, retain credentials/secrets, or destructively delete production data.
- Reject stale or repeated approval gate IDs and approvals for a previous plan version.
- Require a non-empty actor string for human decisions and operator actions.
- Keep release generation advisory. The server has no deploy command or credentials.
- Keep a safe stop available for active runs. Stops are durable and block subsequent stage execution.
- Retries are bounded. A failed stage cannot be retried beyond its configured attempt budget.

This prototype does not claim regulatory compliance. A deployment must map the data flow and retention behavior to its actual legal, security, and organizational policies.
