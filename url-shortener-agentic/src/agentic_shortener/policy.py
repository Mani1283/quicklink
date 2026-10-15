"""Pre-execution policy checks for security, compliance, and change control."""

import re
from pathlib import PurePosixPath


class PolicyViolation(ValueError):
    pass


class PolicyEngine:
    BLOCKED_PATTERNS = (
        (re.compile(r"\b(disable|remove|bypass)\b.{0,30}\b(auth|authentication|authorization)\b", re.I),
         "security controls cannot be disabled"),
        (re.compile(r"\b(log|store|retain)\b.{0,35}\b(password|secret|access token)\b", re.I),
         "credentials and secrets must not be logged or retained"),
        (re.compile(r"\b(delete|drop)\b.{0,35}\b(production database|all customer data)\b", re.I),
         "destructive production data changes are prohibited without a separately governed migration"),
    )

    def check_request(self, request: str) -> None:
        for pattern, reason in self.BLOCKED_PATTERNS:
            if pattern.search(request):
                raise PolicyViolation(reason)

    def check_artifact(self, kind: str, artifact: dict) -> None:
        if kind == "release" and artifact.get("status") not in {"ready_for_human_review", "blocked"}:
            raise PolicyViolation("release output must remain pending human review")
        if kind == "policy" and str(artifact.get("result", "")).lower() not in {"pass", "approved"}:
            raise PolicyViolation("policy analysis did not pass; implementation is stopped")
        if artifact.get("provider") == "openai-responses":
            if kind == "implementation" and (not artifact.get("files") or not artifact.get("tests")):
                raise PolicyViolation("model implementation must include source and test proposals")
            if kind == "documentation" and not artifact.get("files"):
                raise PolicyViolation("model documentation stage must include reviewable files")
        files = artifact.get("files", [])
        tests = artifact.get("tests", []) if kind == "implementation" else []
        if not isinstance(files, list) or not isinstance(tests, list):
            raise PolicyViolation("generated files and tests must be arrays")
        seen = set()
        total_bytes = 0
        for item in [*files, *tests]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) \
                    or not isinstance(item.get("content"), str):
                raise PolicyViolation("generated files need string path and content fields")
            path = item["path"]
            parsed = PurePosixPath(path)
            if (not path or "\\" in path or ":" in path or parsed.is_absolute()
                    or any(part in {"", ".", ".."} for part in parsed.parts)):
                raise PolicyViolation("generated file path must be a safe relative POSIX path")
            if path in seen:
                raise PolicyViolation("generated file paths must be unique")
            seen.add(path)
            total_bytes += len(item["content"].encode("utf-8"))
            if total_bytes > 1_000_000:
                raise PolicyViolation("generated files exceed the 1 MB per-stage limit")
