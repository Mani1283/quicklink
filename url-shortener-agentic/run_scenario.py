"""Run one governed scenario in an interactive terminal."""

import argparse
import json
from pathlib import Path

from src.agentic_shortener.config import DB_PATH
from src.agentic_shortener.database import Database
from src.agentic_shortener.orchestrator import Orchestrator
from src.agentic_shortener.scenarios import SCENARIOS


def scenario_request(scenario: str) -> str:
    path = Path("scenarios") / f"{scenario}.json"
    return json.loads(path.read_text(encoding="utf-8"))["request"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a human-governed software engineering scenario")
    parser.add_argument("scenario", choices=sorted(SCENARIOS), help="scenario DAG to execute")
    parser.add_argument("--request", help="override the example request")
    parser.add_argument("--repository", help="brownfield repository path (must be under ALLOWED_REPOSITORY_ROOTS)")
    parser.add_argument("--actor", default="terminal-reviewer", help="human reviewer/operator label")
    args = parser.parse_args()

    workflow = Orchestrator(Database(DB_PATH))
    request = args.request or scenario_request(args.scenario)
    run = workflow.create_run(args.scenario, request, args.repository)
    print(f"Run {run['run_id']} started ({args.scenario}); status={run['status']}")
    while run["status"] == "awaiting_approval":
        gate = run["pending_gate"]
        print(f"\nApproval required: stage={gate['stage_id']} risk={gate['risk']} "
              f"plan_version={gate['plan_version']}")
        try:
            decision = input("Approve? [y/N] ").strip().lower()
        except EOFError:
            print("No approval supplied; run remains paused at its approval gate.")
            break
        rationale = input("Review rationale: ").strip()
        run = workflow.decide(run["run_id"], gate["gate_id"],
                              "approve" if decision in {"y", "yes"} else "reject",
                              args.actor, rationale)
        print(f"status={run['status']}")

    artifact_directory = workflow.artifacts_dir / run["run_id"]
    print(f"\nRun ID: {run['run_id']}")
    print(f"Status: {run['status']}")
    print(f"Artifacts: {artifact_directory.resolve()}")
    print(f"Audit verification: {json.dumps(workflow.verify_audit())}")
    return 0 if run["status"] in {"completed", "awaiting_approval", "stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
