# Testing approach

The `unittest` suite has no external test dependency. Unit tests exercise domain validation and the orchestration state machine with an isolated in-memory database. HTTP integration tests start an ephemeral local server and cover JSON endpoints, redirects, metadata, errors, approval flow, rate limiting, audit-chain verification, and artifact export.

Recommended CI sequence:

1. `python -m unittest discover -s tests -v`
2. Static type/lint checks if adopted by the implementation team.
3. API contract checks against the documented routes.
4. Security cases for URL schemes, credentials, hostile input, body limits, and secret-like request strings.
5. A migration and restore exercise against a disposable database.
6. Manual approval/rejection, replan, stop, retry, and rollback drills before release.
7. Verify the JSONL hash chain and reconcile its events against the SQLite ledger.
8. Run the API server and CLI concurrently to exercise cross-process audit locking and SQLite contention.

## Trade-offs and limits

- In-memory SQLite is used for isolated tests; production should use a managed database and schema migration tool.
- The deterministic agent exercises orchestration semantics but does not demonstrate model quality. A model adapter should validate structured output and retain provider/model/prompt version lineage.
- This prototype's rollback only reverses workflow artifacts. It cannot undo external systems because agents have no external tools.
- The reported recovery interval is stage-level. Production incident MTTR requires incident detection and restoration events from the operations platform.
- No load, concurrency, penetration, or compliance certification is claimed.
