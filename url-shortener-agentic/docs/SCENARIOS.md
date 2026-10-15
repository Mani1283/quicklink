# Required scenario walkthroughs

## Greenfield

**Request:** Build a URL shortener with secure redirects, expiry, aggregate click analytics, tests, and setup documentation.

**Decomposition:** requirements -> architecture and policy (parallel) -> implementation -> validation and docs (parallel) -> release. Implementation and release each wait for a reviewer decision. Outputs include acceptance criteria, component decisions, policy checks, changes/files, validation plan, docs list, and release checklist.

**Validation:** URL shape/scheme/credentials, expiry, unique codes, redirect behavior, click analytics, and error paths are represented in unit and integration tests. Release remains a proposed state until human review.

## Brownfield

**Request:** Add click analytics to an existing URL shortener without changing create/redirect contracts or retaining personal request metadata.

**Decomposition:** requirements -> codebase analysis -> architecture, with policy analysis parallel to codebase analysis -> implementation approval -> validation and docs -> release approval.

**Reasoning:** The redirect path, link persistence, analytics API, and compatibility tests are impacted. The data flow is lookup -> atomic click increment -> redirect. The existing create and redirect contracts are explicit constraints.

**Validation:** Compatibility tests, atomic increment behavior, privacy checks, and expiry behavior should pass before release approval.

## Ambiguous

**Request:** Add analytics and retain data for an “appropriate period.”

**Ambiguities:** Retention duration, deletion semantics, and required level of detail. The system records these as questions and pauses at a clarification gate. Until a human resolves them, the safe proposed assumption is aggregate counts only and no IP/user-agent/referrer collection.

**Decomposition:** requirements -> clarification approval -> architecture; policy runs in parallel with initial requirements -> implementation approval -> validation and docs -> release approval.

**Validation:** Confirm retention and deletion requirements are reflected in schema and tests. If unresolved, reject or stop; do not silently invent a retention period.

## Running each scenario

Use `python run_scenario.py greenfield`, `python run_scenario.py brownfield`, or `python run_scenario.py ambiguous`. The CLI stops for a reviewer response at each approval gate. A brownfield run scans the project root unless `--repository PATH` is supplied; paths outside `ALLOWED_REPOSITORY_ROOTS` are rejected. To inspect the stage graph first, start the API and request `GET /api/orchestration/scenarios`.

The deterministic provider returns repeatable planning and validation artifacts. Set `AGENT_PROVIDER=openai` with an API key to have the optional model agent create source/test/documentation proposals. Proposals go to that run's `artifacts/runs/<run_id>/changes/` directory and are not applied to the working tree. The model-backed validation output is a plan; it does not execute tests. Execute the documented local test command independently before release review.
