"""Named, replaceable stage agents and deterministic reference implementations."""

from typing import Protocol

from .config import AGENT_PROVIDER


class StageAgent(Protocol):
    def execute(self, kind: str, request: str, context: dict) -> dict: ...


class RequirementAgent:
    def execute(self, request: str, context: dict) -> dict:
        lower = request.lower()
        questions = []
        if "retention" in lower or "analytics" in lower:
            questions.append("Confirm analytics retention and deletion policy")
        if "scale" in lower or "high traffic" in lower:
            questions.append("Confirm expected throughput and availability target")
        return {"summary": request, "acceptance_criteria": [
            "API contract is documented", "Inputs are validated", "Failure behavior is explicit",
            "Tests cover success and failure paths"], "open_questions": questions}


class DesignAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"components": ["HTTP API", "shortener domain service", "SQLite repository", "orchestration engine"],
                "decisions": ["Use random opaque codes", "Store UTC timestamps", "Keep analytics privacy-minimal"],
                "upstream_artifacts": sorted(context.get("artifacts", context)),
                "human_decisions": context.get("decisions", []),
                "plan_version": context.get("plan_version")}


class CodeAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"changes": ["short link CRUD", "redirect and click count", "expiry handling", "API metadata"],
                "planned_files": ["shortener.py", "server.py", "database.py"],
                "human_decisions": context.get("decisions", []),
                "status": "awaiting_human_review"}


class TestAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"checks": ["unit", "integration", "security input cases", "dependency graph"],
                "result": "review_required",
                "evidence": "Test suite is provided; execute it in the review environment",
                "decisions_under_test": context.get("decisions", [])}


class DocumentationAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"artifacts": ["setup guide", "architecture overview", "API reference", "risk register"],
                "decisions_to_document": context.get("decisions", [])}


class ReleaseAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"status": "ready_for_human_review", "checklist": ["validation reviewed", "docs reviewed",
                "migration plan reviewed", "rollback plan identified"], "deployment_performed": False,
                "approval_decisions": context.get("decisions", [])}


class BrownfieldAnalysisAgent:
    def execute(self, request: str, context: dict) -> dict:
        repository = context.get("repository") or {}
        files = repository.get("files", [])
        relevant = []
        for item in files:
            path = item["path"].lower()
            if any(term in path for term in ("route", "api", "short", "redirect", "storage", "database", "test")):
                relevant.append(item["path"])
        return {"repository_root": repository.get("root"),
                "repository_file_count": repository.get("file_count", 0),
                "repository_truncated": repository.get("truncated", False),
                "impacted_files": relevant,
                "impacted_areas": ["API/route handler", "domain service", "persistence", "analytics", "tests"],
                "compatibility_constraint": "Preserve existing create and redirect contracts",
                "data_flow": "redirect request -> link lookup -> atomic click increment -> 302 response",
                "repository_manifest": [{"path": item["path"], "sha256": item["sha256"]} for item in files]}


class ClarificationAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"questions": ["What is the retention period for click analytics?",
                              "Should analytics be deleted with a link?"],
                "safe_assumption": "Aggregate counts only; do not retain IP, user-agent, or referrer",
                "status": "awaiting_human_decision"}


class PolicyAnalysisAgent:
    def execute(self, request: str, context: dict) -> dict:
        return {"checks": ["input validation", "no credential-bearing URLs", "least data collection",
                           "human gate before implementation and release"], "result": "pass"}


class AgentRouter:
    """Dispatch stage kinds to separately replaceable agent implementations."""

    def __init__(self):
        self.agents = {
            "requirements": RequirementAgent(),
            "architecture": DesignAgent(),
            "implementation": CodeAgent(),
            "validation": TestAgent(),
            "documentation": DocumentationAgent(),
            "release": ReleaseAgent(),
            "brownfield_analysis": BrownfieldAnalysisAgent(),
            "clarification": ClarificationAgent(),
            "policy": PolicyAnalysisAgent(),
        }

    def execute(self, kind: str, request: str, context: dict) -> dict:
        try:
            agent = self.agents[kind]
        except KeyError as exc:
            raise ValueError(f"unsupported stage kind: {kind}") from exc
        return agent.execute(request, context)


# Compatibility name retained for callers and tests from the first prototype.
DeterministicAgent = AgentRouter


def configured_stage_agent() -> StageAgent:
    """Select the real model adapter only when explicitly enabled by configuration."""
    if AGENT_PROVIDER == "deterministic":
        return AgentRouter()
    if AGENT_PROVIDER == "openai":
        from .llm_agent import OpenAIResponsesStageAgent
        return OpenAIResponsesStageAgent()
    raise ValueError("AGENT_PROVIDER must be 'deterministic' or 'openai'")
