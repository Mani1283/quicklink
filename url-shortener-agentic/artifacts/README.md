# Generated run artifacts

The orchestrator creates one directory per run at `artifacts/runs/<run_id>/`. It contains:

- `run.json`: current run state, plan version, approval decisions, and event lineage.
- `<stage_id>.json`: each current stage artifact. Replanning and rollback remove invalidated stage files.

Files are written atomically. These files may contain user requirements and agent outputs; protect and expire them according to the deployment's data policy.
