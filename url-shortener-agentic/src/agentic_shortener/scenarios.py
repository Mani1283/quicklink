"""Scenario catalog. Edges form the explicit dependency graph for each run."""

SCENARIOS = {
    "greenfield": {
        "title": "New URL shortener",
        "description": "Build a secure URL shortener with analytics from a new-system request.",
        "stages": [
            {"id": "requirements", "kind": "requirements", "depends_on": [], "risk": "low"},
            {"id": "architecture", "kind": "architecture", "depends_on": ["requirements"], "risk": "medium"},
            {"id": "policy", "kind": "policy", "depends_on": ["requirements"], "risk": "low"},
            {"id": "implementation", "kind": "implementation", "depends_on": ["architecture", "policy"], "risk": "high", "approval": True},
            {"id": "validation", "kind": "validation", "depends_on": ["implementation"], "risk": "medium"},
            {"id": "documentation", "kind": "documentation", "depends_on": ["implementation"], "risk": "low"},
            {"id": "release", "kind": "release", "depends_on": ["validation", "documentation"], "risk": "high", "approval": True},
        ],
    },
    "brownfield": {
        "title": "Analytics enhancement",
        "description": "Add click analytics to an existing URL shortener without breaking its API.",
        "stages": [
            {"id": "requirements", "kind": "requirements", "depends_on": [], "risk": "low"},
            {"id": "codebase_analysis", "kind": "brownfield_analysis", "depends_on": ["requirements"], "risk": "medium"},
            {"id": "architecture", "kind": "architecture", "depends_on": ["codebase_analysis"], "risk": "medium"},
            {"id": "policy", "kind": "policy", "depends_on": ["requirements"], "risk": "low"},
            {"id": "implementation", "kind": "implementation", "depends_on": ["architecture", "policy"], "risk": "high", "approval": True},
            {"id": "validation", "kind": "validation", "depends_on": ["implementation"], "risk": "medium"},
            {"id": "documentation", "kind": "documentation", "depends_on": ["implementation"], "risk": "low"},
            {"id": "release", "kind": "release", "depends_on": ["validation", "documentation"], "risk": "high", "approval": True},
        ],
    },
    "ambiguous": {
        "title": "Ambiguous retention requirement",
        "description": "Handle an underspecified analytics retention request through clarification and safe defaults.",
        "stages": [
            {"id": "requirements", "kind": "requirements", "depends_on": [], "risk": "low"},
            {"id": "clarification", "kind": "clarification", "depends_on": ["requirements"], "risk": "medium", "approval": True},
            {"id": "architecture", "kind": "architecture", "depends_on": ["clarification"], "risk": "medium"},
            {"id": "policy", "kind": "policy", "depends_on": ["requirements"], "risk": "low"},
            {"id": "implementation", "kind": "implementation", "depends_on": ["architecture", "policy"], "risk": "high", "approval": True},
            {"id": "validation", "kind": "validation", "depends_on": ["implementation"], "risk": "medium"},
            {"id": "documentation", "kind": "documentation", "depends_on": ["implementation"], "risk": "low"},
            {"id": "release", "kind": "release", "depends_on": ["validation", "documentation"], "risk": "high", "approval": True},
        ],
    },
}


def validate_graph(stages: list[dict]) -> None:
    ids = [stage["id"] for stage in stages]
    if len(ids) != len(set(ids)):
        raise ValueError("stage IDs must be unique")
    known = set(ids)
    for stage in stages:
        if set(stage.get("depends_on", [])) - known:
            raise ValueError(f"unknown dependency in stage {stage['id']}")
    pending = {stage["id"]: set(stage.get("depends_on", [])) for stage in stages}
    visited = set()
    while pending:
        ready = {name for name, deps in pending.items() if deps <= visited}
        if not ready:
            raise ValueError("stage dependency graph contains a cycle")
        visited |= ready
        pending = {name: deps for name, deps in pending.items() if name not in ready}


for _scenario in SCENARIOS.values():
    validate_graph(_scenario["stages"])
