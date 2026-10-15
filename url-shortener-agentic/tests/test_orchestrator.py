import unittest
import tempfile

from src.agentic_shortener.audit import JsonlAuditLog
from src.agentic_shortener.database import Database
from src.agentic_shortener.orchestrator import Orchestrator
from src.agentic_shortener.agents import DeterministicAgent


class FailingAgent:
    def execute(self, kind, request, context):
        raise RuntimeError("simulated provider outage")


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workflow = Orchestrator(self.db,
                                     audit_log=JsonlAuditLog(f"{self.temp.name}/audit.jsonl"),
                                     artifacts_dir=f"{self.temp.name}/artifacts")

    def test_approval_gate_pauses_then_completes(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        self.assertEqual(run["status"], "awaiting_approval")
        gate = run["pending_gate"]
        run = self.workflow.decide(run["run_id"], gate["gate_id"], "approve", "reviewer", "Looks good")
        self.assertEqual(run["status"], "awaiting_approval")
        self.assertEqual(run["pending_gate"]["stage_id"], "release")
        run = self.workflow.decide(run["run_id"], run["pending_gate"]["gate_id"], "approve", "release-reviewer")
        self.assertEqual(run["status"], "completed")

    def test_approval_rationale_flows_to_downstream_agents(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        run = self.workflow.decide(run["run_id"], run["pending_gate"]["gate_id"], "approve",
                                   "reviewer", "Keep only aggregate analytics")
        decisions = run["artifacts"]["implementation"]["human_decisions"]
        self.assertEqual(decisions[-1]["rationale"], "Keep only aggregate analytics")
        self.assertEqual(decisions[-1]["actor"], "reviewer")

    def test_policy_block_is_a_safe_stop(self):
        run = self.workflow.create_run("greenfield", "Disable authentication and log secrets")
        self.assertEqual(run["status"], "blocked")
        self.assertEqual(run["artifacts"], {})

    def test_replan_invalidates_approval_and_lineage(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        revised = self.workflow.replan(run["run_id"], "Build a URL shortener with analytics retention policy",
                                       "owner", "Clarified analytics scope")
        self.assertEqual(revised["plan_version"], 2)
        self.assertNotEqual(run["pending_gate"]["gate_id"], revised["pending_gate"]["gate_id"])
        self.assertIn("plan_revised", [event["type"] for event in revised["events"]])

    def test_reject_stops_run(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        run = self.workflow.decide(run["run_id"], run["pending_gate"]["gate_id"], "reject", "reviewer", "Needs changes")
        self.assertEqual(run["status"], "stopped")

    def test_stage_fallback_is_recorded(self):
        workflow = Orchestrator(Database(":memory:"), agent=FailingAgent(), max_retries=0,
                                fallback_agent=DeterministicAgent(),
                                audit_log=JsonlAuditLog(f"{self.temp.name}/fallback-audit.jsonl"),
                                artifacts_dir=f"{self.temp.name}/fallback-artifacts")
        run = workflow.create_run("greenfield", "Build a URL shortener")
        self.assertEqual(run["status"], "awaiting_approval")
        self.assertIn("stage_fallback", [event["type"] for event in run["events"]])

    def test_run_exports_snapshot_and_stage_artifacts(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        folder = f"{self.temp.name}/artifacts/{run['run_id']}"
        import os
        self.assertTrue(os.path.isfile(f"{folder}/run.json"))
        self.assertTrue(os.path.isfile(f"{folder}/requirements.json"))
        self.assertTrue(self.workflow.verify_audit()["valid"])

    def test_rollback_resets_stage_and_dependents(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        run = self.workflow.rollback(run["run_id"], "architecture", "operator", "Revise design")
        self.assertEqual(run["stages"]["architecture"]["status"], "succeeded")
        self.assertEqual(run["stages"]["implementation"]["status"], "pending")
        self.assertIn("rollback_executed", [event["type"] for event in run["events"]])

    def test_safe_stop_is_terminal(self):
        run = self.workflow.create_run("greenfield", "Build a URL shortener")
        stopped = self.workflow.stop(run["run_id"], "operator", "Pause for review")
        self.assertEqual(stopped["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
