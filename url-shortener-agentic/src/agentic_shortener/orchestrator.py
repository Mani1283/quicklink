"""Stateful DAG orchestrator with approval gates, bounded retries, and audit lineage."""

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath

from .agents import DeterministicAgent, StageAgent, configured_stage_agent
from .audit import JsonlAuditLog
from .config import ARTIFACTS_DIR, AUDIT_PATH
from .database import Database
from .policy import PolicyEngine, PolicyViolation
from .repository import RepositoryScanner
from .scenarios import SCENARIOS, validate_graph


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def synchronized_run(method):
    """Serialize mutations for one run while allowing different runs to progress independently."""
    @wraps(method)
    def wrapper(self, run_id, *args, **kwargs):
        with self._get_run_lock(run_id):
            return method(self, run_id, *args, **kwargs)
    return wrapper


class Orchestrator:
    def __init__(self, database: Database, agent: StageAgent | None = None,
                 policy: PolicyEngine | None = None, max_retries: int = 2, parallelism: int = 4,
                 fallback_agent: StageAgent | None = None, audit_log: JsonlAuditLog | None = None,
                 artifacts_dir: str | Path | None = None,
                 repository_scanner: RepositoryScanner | None = None):
        self.db = database
        self.agent = agent or configured_stage_agent()
        self.fallback_agent = fallback_agent or DeterministicAgent()
        self.policy = policy or PolicyEngine()
        self.max_retries = max_retries
        self.parallelism = parallelism
        self.audit_log = audit_log or JsonlAuditLog(AUDIT_PATH)
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.repository_scanner = repository_scanner or RepositoryScanner()
        self._export_lock = threading.RLock()
        self._event_lock = threading.Lock()
        self._run_locks: dict[str, threading.RLock] = {}
        self._run_locks_lock = threading.Lock()

    def create_run(self, scenario: str, request: str, repository_path: str | Path | None = None) -> dict:
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario")
        if not isinstance(request, str) or not request.strip() or len(request) > 10000:
            raise ValueError("request must contain 1 to 10000 characters")
        if repository_path is None and scenario == "brownfield":
            repository_path = self.repository_scanner.allowed_roots[0]
        repository_snapshot = (self.repository_scanner.snapshot(repository_path)
                               if repository_path else None)
        run_id = str(uuid.uuid4())
        context = {"stages": {stage["id"]: {"status": "pending", "attempts": 0}
                              for stage in SCENARIOS[scenario]["stages"]},
                   "artifacts": {}, "decisions": [], "repository": repository_snapshot,
                   "pending_gate": None,
                   "started_at": now(), "completed_at": None}
        self._insert_run(run_id, scenario, request.strip(), "running", 1, context)
        self._event(run_id, "run_created", details={"scenario": scenario, "plan_version": 1})
        try:
            self.policy.check_request(request)
        except PolicyViolation as exc:
            self._set_status(run_id, "blocked")
            self._event(run_id, "policy_block", details={"reason": str(exc)})
            return self.get_run(run_id)
        return self.advance(run_id)

    @synchronized_run
    def advance(self, run_id: str) -> dict:
        run = self._row(run_id)
        if run["status"] not in {"running", "awaiting_approval"}:
            return self.get_run(run_id)
        scenario = SCENARIOS[run["scenario"]]
        validate_graph(scenario["stages"])
        context = json.loads(run["context_json"])
        if context.get("pending_gate"):
            return self.get_run(run_id)
        stage_by_id = {stage["id"]: stage for stage in scenario["stages"]}
        while True:
            ready = [stage for stage in scenario["stages"]
                     if context["stages"][stage["id"]]["status"] == "pending"
                     and all(context["stages"][dep]["status"] == "succeeded"
                             for dep in stage.get("depends_on", []))]
            if not ready:
                statuses = [value["status"] for value in context["stages"].values()]
                if all(state == "succeeded" for state in statuses):
                    context["completed_at"] = now()
                    self._save_context(run_id, context, "completed")
                    self._event(run_id, "run_completed", details={"plan_version": run["plan_version"]})
                elif not any(state in {"running", "pending"} for state in statuses):
                    self._save_context(run_id, context, "failed")
                else:
                    self._save_context(run_id, context, "running")
                return self.get_run(run_id)
            # A high-impact stage is never executed until a human approves this exact plan version.
            gated = next((stage for stage in ready if stage.get("approval")), None)
            if gated:
                gate = {"gate_id": str(uuid.uuid4()), "stage_id": gated["id"],
                        "plan_version": run["plan_version"], "risk": gated["risk"],
                        "requested_at": now(), "status": "pending"}
                context["pending_gate"] = gate
                self._save_context(run_id, context, "awaiting_approval")
                self._event(run_id, "approval_requested", stage_id=gated["id"],
                            details={"gate_id": gate["gate_id"], "risk": gate["risk"],
                                     "plan_version": run["plan_version"]})
                return self.get_run(run_id)
            # Sibling stages execute concurrently; outputs are committed in declared graph order.
            with ThreadPoolExecutor(max_workers=min(self.parallelism, len(ready))) as pool:
                results = list(pool.map(lambda stage: self._execute_stage(run_id, run["request"], stage,
                                                                          self._stage_context(context,
                                                                                              run["plan_version"])), ready))
            for stage, outcome in zip(ready, results):
                state = context["stages"][stage["id"]]
                state["attempts"] = outcome["attempts"]
                if outcome["error"]:
                    state.update(status="failed", error=outcome["error"])
                    self._event(run_id, "stage_failed", stage_id=stage["id"],
                                details={"error": outcome["error"], "attempts": outcome["attempts"]})
                    self._save_context(run_id, context, "failed")
                    return self.get_run(run_id)
                try:
                    self.policy.check_artifact(stage["kind"], outcome["artifact"])
                except PolicyViolation as exc:
                    state.update(status="blocked", error=str(exc))
                    self._event(run_id, "policy_block", stage_id=stage["id"], details={"reason": str(exc)})
                    self._save_context(run_id, context, "blocked")
                    return self.get_run(run_id)
                state.update(status="succeeded", completed_at=now())
                context["artifacts"][stage["id"]] = outcome["artifact"]
                self._event(run_id, "stage_succeeded", stage_id=stage["id"],
                            details={"attempts": outcome["attempts"], "fallback": outcome["fallback"],
                                     "artifact": outcome["artifact"]})
            self._save_context(run_id, context, "running")
            run = self._row(run_id)

    @synchronized_run
    def decide(self, run_id: str, gate_id: str, decision: str, actor: str, rationale: str = "") -> dict:
        run = self._row(run_id)
        context = json.loads(run["context_json"])
        gate = context.get("pending_gate")
        if not gate or gate["gate_id"] != gate_id or gate["status"] != "pending":
            raise ValueError("approval gate is missing, stale, or already decided")
        if gate["plan_version"] != run["plan_version"]:
            raise ValueError("approval gate is stale because the plan changed")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError("actor must contain 1 to 120 characters")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not isinstance(rationale, str):
            raise ValueError("rationale must be a string")
        gate.update(status=decision + "d", decided_at=now(), actor=actor.strip(), rationale=rationale[:2000])
        context["pending_gate"] = None
        decision_record = {"gate_id": gate_id, "stage_id": gate["stage_id"], "decision": decision,
                           "actor": actor.strip(), "rationale": rationale[:2000],
                           "plan_version": run["plan_version"], "decided_at": gate["decided_at"]}
        context.setdefault("decisions", []).append(decision_record)
        if decision == "reject":
            context["stages"][gate["stage_id"]].update(status="rejected", error=rationale or "human rejected")
            self._save_context(run_id, context, "stopped")
            self._event(run_id, "approval_rejected", stage_id=gate["stage_id"], actor=actor.strip(),
                        details={"gate_id": gate_id, "rationale": rationale[:2000]})
            return self.get_run(run_id)
        self._save_context(run_id, context, "running")
        self._event(run_id, "approval_granted", stage_id=gate["stage_id"], actor=actor.strip(),
                    details={"gate_id": gate_id, "plan_version": run["plan_version"],
                             "rationale": rationale[:2000]})
        result = self._execute_stage(run_id, run["request"],
                                     next(s for s in SCENARIOS[run["scenario"]]["stages"]
                                          if s["id"] == gate["stage_id"]),
                                     self._stage_context(context, run["plan_version"]))
        stage_state = context["stages"][gate["stage_id"]]
        stage_state["attempts"] = result["attempts"]
        if result["error"]:
            stage_state.update(status="failed", error=result["error"])
            self._save_context(run_id, context, "failed")
            self._event(run_id, "stage_failed", stage_id=gate["stage_id"],
                        details={"error": result["error"], "attempts": result["attempts"]})
            return self.get_run(run_id)
        stage_state.update(status="succeeded", completed_at=now())
        context["artifacts"][gate["stage_id"]] = result["artifact"]
        self._event(run_id, "stage_succeeded", stage_id=gate["stage_id"],
                    details={"attempts": result["attempts"], "fallback": result["fallback"],
                             "artifact": result["artifact"]})
        self._save_context(run_id, context, "running")
        return self.advance(run_id)

    @synchronized_run
    def replan(self, run_id: str, request: str, actor: str, rationale: str) -> dict:
        run = self._row(run_id)
        if run["status"] not in {"running", "awaiting_approval"}:
            raise ValueError("only active runs may be replanned")
        if not isinstance(request, str) or not request.strip() or len(request) > 10000:
            raise ValueError("request must contain 1 to 10000 characters")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor is required")
        if not isinstance(rationale, str):
            raise ValueError("rationale must be a string")
        self.policy.check_request(request)
        context = json.loads(run["context_json"])
        if context.get("pending_gate"):
            old = context["pending_gate"]
            self._event(run_id, "approval_invalidated", stage_id=old["stage_id"], actor=actor,
                        details={"gate_id": old["gate_id"], "reason": "upstream request changed"})
            context["pending_gate"] = None
        # Requirement changes invalidate all downstream output; preserving the request lineage in events.
        for stage in context["stages"].values():
            stage.update(status="pending", attempts=0)
            stage.pop("error", None)
            stage.pop("completed_at", None)
        context["artifacts"] = {}
        context["decisions"] = []
        context["started_at"] = now()
        context["completed_at"] = None
        with self.db.connect() as connection:
            connection.execute("UPDATE orchestration_runs SET request=?,status='running',plan_version=plan_version+1,"
                               "context_json=?,updated_at=? WHERE run_id=?",
                               (request.strip(), json.dumps(context), now(), run_id))
        self._event(run_id, "plan_revised", actor=actor,
                    details={"rationale": rationale[:2000], "invalidated_stages": list(context["stages"]),
                             "previous_request_sha256": hashlib.sha256(run["request"].encode()).hexdigest(),
                             "revised_request_sha256": hashlib.sha256(request.strip().encode()).hexdigest(),
                             "plan_version": run["plan_version"] + 1})
        return self.advance(run_id)

    @synchronized_run
    def retry(self, run_id: str, stage_id: str, actor: str, rationale: str) -> dict:
        run = self._row(run_id)
        context = json.loads(run["context_json"])
        stage = context["stages"].get(stage_id)
        if not stage or stage["status"] not in {"failed", "blocked"}:
            raise ValueError("only failed or blocked stages can be retried")
        if stage["attempts"] >= self.max_retries + 1:
            raise ValueError("bounded retry limit has been reached")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor is required")
        if not isinstance(rationale, str):
            raise ValueError("rationale must be a string")
        stage.update(status="pending")
        stage.pop("error", None)
        self._save_context(run_id, context, "running")
        self._event(run_id, "retry_requested", stage_id=stage_id, actor=actor,
                    details={"rationale": rationale[:2000], "retry_count": stage["attempts"]})
        return self.advance(run_id)

    @synchronized_run
    def rollback(self, run_id: str, stage_id: str, actor: str, rationale: str) -> dict:
        run = self._row(run_id)
        if run["status"] not in {"running", "awaiting_approval", "failed", "blocked"}:
            raise ValueError("only non-terminal runs can be rolled back")
        if not actor or not actor.strip():
            raise ValueError("actor is required")
        if not isinstance(rationale, str):
            raise ValueError("rationale must be a string")
        stages = SCENARIOS[run["scenario"]]["stages"]
        if stage_id not in {stage["id"] for stage in stages}:
            raise ValueError("unknown stage_id")
        context = json.loads(run["context_json"])
        if context.get("pending_gate"):
            self._event(run_id, "approval_invalidated", stage_id=context["pending_gate"]["stage_id"],
                        actor=actor.strip(), details={"gate_id": context["pending_gate"]["gate_id"],
                                                       "reason": "stage rollback"})
            context["pending_gate"] = None
        invalidated = {stage_id}
        changed = True
        while changed:
            changed = False
            for stage in stages:
                if stage["id"] not in invalidated and invalidated.intersection(stage.get("depends_on", [])):
                    invalidated.add(stage["id"])
                    changed = True
        for name in invalidated:
            context["stages"][name] = {"status": "pending", "attempts": 0}
            context["artifacts"].pop(name, None)
        context["decisions"] = [decision for decision in context.get("decisions", [])
                                if decision["stage_id"] not in invalidated]
        self._save_context(run_id, context, "running")
        self._event(run_id, "rollback_executed", stage_id=stage_id, actor=actor.strip(),
                    details={"rationale": rationale[:2000], "invalidated_stages": sorted(invalidated),
                             "scope": "workflow artifacts only; no external side effects"})
        return self.advance(run_id)

    @synchronized_run
    def stop(self, run_id: str, actor: str, rationale: str) -> dict:
        run = self._row(run_id)
        if run["status"] not in {"running", "awaiting_approval", "failed", "blocked"}:
            raise ValueError("run is already terminal")
        if not actor or not actor.strip():
            raise ValueError("actor is required")
        if not isinstance(rationale, str):
            raise ValueError("rationale must be a string")
        context = json.loads(run["context_json"])
        context["pending_gate"] = None
        self._save_context(run_id, context, "stopped")
        self._event(run_id, "safe_stop", actor=actor.strip(),
                    details={"rationale": rationale[:2000], "remaining_stages_blocked": True})
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict:
        row = self._row(run_id)
        context = json.loads(row["context_json"])
        with self.db.connect() as connection:
            events = connection.execute("SELECT * FROM orchestration_events WHERE run_id=? ORDER BY event_id",
                                        (run_id,)).fetchall()
        return {"run_id": row["run_id"], "scenario": row["scenario"], "request": row["request"],
                "status": row["status"], "plan_version": row["plan_version"], "stages": context["stages"],
                "artifacts": context["artifacts"], "pending_gate": context["pending_gate"],
                "decisions": context.get("decisions", []),
                "repository": ({key: context["repository"].get(key)
                                for key in ("root", "file_count", "total_chars", "truncated")}
                               if context.get("repository") else None),
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "events": [{"event_id": event["event_id"], "at": event["at"],
                            "type": event["event_type"], "stage_id": event["stage_id"],
                            "actor": event["actor"], "details": json.loads(event["details_json"])}
                           for event in events]}

    def metrics(self) -> dict:
        with self.db.connect() as connection:
            runs = connection.execute("SELECT status,created_at,updated_at FROM orchestration_runs").fetchall()
            counts = {row["status"]: 0 for row in runs}
            for row in runs:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            events = connection.execute("SELECT run_id,stage_id,event_id,event_type,at FROM orchestration_events "
                                         "ORDER BY event_id").fetchall()
        total = len(runs)
        completed = counts.get("completed", 0)
        terminal_total = sum(counts.get(state, 0) for state in ("completed", "failed", "blocked", "stopped"))
        latencies = [(datetime.fromisoformat(row["updated_at"]) - datetime.fromisoformat(row["created_at"])).total_seconds()
                     for row in runs if row["status"] == "completed"]
        retry_count = sum(event["event_type"] in {"retry_requested", "stage_retry"} for event in events)
        rollback_count = sum(event["event_type"] == "rollback_executed" for event in events)
        fallback_count = sum(event["event_type"] == "stage_fallback" for event in events)
        failure_events = sum(event["event_type"] in {"stage_failed", "policy_block"} for event in events)
        failures = {}
        recoveries = []
        for event in events:
            if event["event_type"] == "stage_failed":
                failures[(event["run_id"], event["stage_id"])] = (event["at"], None)
            elif event["event_type"] == "stage_succeeded":
                key = (event["run_id"], event["stage_id"])
                if key in failures:
                    failed_at, recovered_at = failures[key]
                    if recovered_at is None:
                        recoveries.append((datetime.fromisoformat(event["at"]) -
                                           datetime.fromisoformat(failed_at)).total_seconds())
                        failures[key] = (failed_at, event["at"])
        return {"run_count": total, "success_rate": completed / terminal_total if terminal_total else 0.0,
                "success_rate_sample_runs": terminal_total,
                "retry_count": retry_count, "rollback_count": rollback_count,
                "fallback_count": fallback_count,
                "retry_frequency_per_run": retry_count / total if total else 0.0,
                "rollback_frequency_per_run": rollback_count / total if total else 0.0,
                "failure_event_count": failure_events,
                "end_to_end_latency_seconds_avg": sum(latencies) / len(latencies) if latencies else None,
                "mttr_seconds_avg": sum(recoveries) / len(recoveries) if recoveries else None,
                "mttr_note": "Mean time from a stage failure event to a later successful stage recovery; null when no recovery is observed.",
                "status_counts": counts}

    def verify_audit(self) -> dict:
        valid, records, error = self.audit_log.verify()
        return {"valid": valid, "records_checked": records, "error": error,
                "algorithm": "SHA-256 hash chain", "scope": "tamper-evident local JSONL; not immutable storage"}

    @staticmethod
    def _stage_context(context: dict, plan_version: int) -> dict:
        return {"artifacts": context["artifacts"], "decisions": context.get("decisions", []),
                "repository": context.get("repository"), "plan_version": plan_version}

    def _execute_stage(self, run_id: str, request: str, stage: dict, stage_context: dict) -> dict:
        start = time.monotonic()
        for attempt in range(1, self.max_retries + 2):
            try:
                agent_context = json.loads(json.dumps(stage_context))
                artifact = self.agent.execute(stage["kind"], request, agent_context)
                if not isinstance(artifact, dict):
                    raise TypeError("stage agent must return a JSON-compatible object")
                json.dumps(artifact)
                return {"artifact": artifact, "attempts": attempt, "error": None, "fallback": False,
                        "duration_seconds": time.monotonic() - start}
            except Exception as exc:  # Bounded retry; error is recorded without exposing a traceback to callers.
                self._event(run_id, "stage_retry" if attempt <= self.max_retries else "stage_attempt_failed",
                            stage_id=stage["id"],
                            details={"attempt": attempt, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
                if attempt == self.max_retries + 1:
                    primary_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                    try:
                        agent_context = json.loads(json.dumps(stage_context))
                        artifact = self.fallback_agent.execute(stage["kind"], request, agent_context)
                        if not isinstance(artifact, dict):
                            raise TypeError("fallback agent must return a JSON-compatible object")
                        json.dumps(artifact)
                        self._event(run_id, "stage_fallback", stage_id=stage["id"],
                                    details={"primary_error": primary_error, "strategy": "fallback_agent"})
                        return {"artifact": artifact, "attempts": attempt, "error": None, "fallback": True,
                                "duration_seconds": time.monotonic() - start}
                    except Exception as fallback_error:
                        return {"artifact": None, "attempts": attempt,
                                "error": f"primary={primary_error}; fallback={type(fallback_error).__name__}: "
                                         f"{str(fallback_error)[:300]}", "fallback": True,
                                "duration_seconds": time.monotonic() - start}
        raise AssertionError("unreachable")

    def _insert_run(self, run_id, scenario, request, status, version, context):
        with self.db.connect() as connection:
            connection.execute("INSERT INTO orchestration_runs VALUES(?,?,?,?,?,?,?,?)",
                               (run_id, scenario, request, status, version, json.dumps(context), now(), now()))
        self._export_run(run_id)

    def _get_run_lock(self, run_id: str) -> threading.RLock:
        with self._run_locks_lock:
            lock = self._run_locks.get(run_id)
            if lock is None:
                lock = threading.RLock()
                self._run_locks[run_id] = lock
            return lock

    def _row(self, run_id):
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM orchestration_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("run not found")
        return row

    def _event(self, run_id, event_type, stage_id=None, actor=None, details=None):
        at = now()
        details = details or {}
        with self._event_lock:
            with self.db.connect() as connection:
                cursor = connection.execute("INSERT INTO orchestration_events(run_id,at,event_type,stage_id,actor,details_json) "
                                            "VALUES(?,?,?,?,?,?)", (run_id, at, event_type, stage_id, actor,
                                                                    json.dumps(details, sort_keys=True)))
                event_id = cursor.lastrowid
            self.audit_log.append({"event_id": event_id, "run_id": run_id, "at": at,
                                   "type": event_type, "stage_id": stage_id, "actor": actor,
                                   "details": details})
            self._export_run(run_id)

    def _save_context(self, run_id, context, status):
        with self.db.connect() as connection:
            connection.execute("UPDATE orchestration_runs SET context_json=?,status=?,updated_at=? WHERE run_id=?",
                               (json.dumps(context), status, now(), run_id))
        self._export_run(run_id)

    def _set_status(self, run_id, status):
        with self.db.connect() as connection:
            connection.execute("UPDATE orchestration_runs SET status=?,updated_at=? WHERE run_id=?",
                               (status, now(), run_id))
        self._export_run(run_id)

    def _export_run(self, run_id: str) -> None:
        """Atomically materialize the current run snapshot and each stage artifact."""
        with self._export_lock:
            with self.db.connect() as connection:
                row = connection.execute("SELECT * FROM orchestration_runs WHERE run_id=?", (run_id,)).fetchone()
                if row is None:
                    return
                context = json.loads(row["context_json"])
                events = connection.execute("SELECT event_id,at,event_type,stage_id,actor,details_json "
                                            "FROM orchestration_events WHERE run_id=? ORDER BY event_id",
                                            (run_id,)).fetchall()
            directory = self.artifacts_dir / run_id
            directory.mkdir(parents=True, exist_ok=True)
            event_data = [{"event_id": event["event_id"], "at": event["at"],
                           "type": event["event_type"], "stage_id": event["stage_id"],
                           "actor": event["actor"], "details": json.loads(event["details_json"])}
                          for event in events]
            snapshot = {"run_id": row["run_id"], "scenario": row["scenario"], "request": row["request"],
                        "status": row["status"], "plan_version": row["plan_version"],
                        "stages": context["stages"], "decisions": context.get("decisions", []),
                        "pending_gate": context.get("pending_gate"),
                        "repository": ({key: context["repository"].get(key)
                                        for key in ("root", "file_count", "total_chars", "truncated")}
                                       if context.get("repository") else None),
                        "created_at": row["created_at"], "updated_at": row["updated_at"],
                        "events": event_data}
            self._atomic_json(directory / "run.json", snapshot)
            artifact_names = set(context["artifacts"])
            active_changes = {}
            for stage_id, artifact in context["artifacts"].items():
                self._atomic_json(directory / f"{stage_id}.json", artifact)
                generated = [*artifact.get("files", [])]
                if stage_id == "implementation":
                    generated.extend(artifact.get("tests", []))
                for item in generated:
                    relative = PurePosixPath(item["path"])
                    if relative.is_absolute() or "\\" in item["path"] or ":" in item["path"] \
                            or any(part in {"", ".", ".."} for part in relative.parts):
                        raise ValueError("unsafe generated artifact path")
                    target = directory / "changes" / Path(*relative.parts)
                    if not target.resolve().is_relative_to((directory / "changes").resolve()):
                        raise ValueError("generated artifact escaped the run directory")
                    self._atomic_text(target, item["content"])
                    active_changes[relative.as_posix()] = {
                        "stage_id": stage_id,
                        "sha256": hashlib.sha256(item["content"].encode("utf-8")).hexdigest(),
                    }
            changes_dir = directory / "changes"
            manifest_path = changes_dir / "manifest.json"
            previous_manifest = {}
            if manifest_path.exists():
                try:
                    previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    previous_manifest = {}
            historical = set(previous_manifest.get("superseded_files", []))
            historical.update(set(previous_manifest.get("active_files", {})) - set(active_changes))
            self._atomic_json(manifest_path, {"plan_version": row["plan_version"],
                                               "active_files": active_changes,
                                               "superseded_files": sorted(historical)})
            for stage in context["stages"]:
                artifact_path = directory / f"{stage}.json"
                if stage not in artifact_names and artifact_path.exists():
                    artifact_path.unlink()

    @staticmethod
    def _atomic_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
                if not value.endswith("\n"):
                    stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
