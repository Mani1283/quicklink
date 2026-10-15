import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agentic_shortener.llm_agent import OpenAIResponsesStageAgent
from src.agentic_shortener.repository import RepositoryScanner


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class AgentAndRepositoryTests(unittest.TestCase):
    def test_responses_agent_parses_and_validates_json_proposals(self):
        content = {"design_summary": "Add checked URL parsing",
                   "files": [{"path": "shortener/validation.py", "content": "def validate(value):\n    return value\n"}],
                   "tests": [{"path": "tests/test_validation.py", "content": "def test_valid():\n    assert True\n"}],
                   "risks": ["Review generated code before use"]}
        body = json.dumps({"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(content)}]}]}).encode()
        agent = OpenAIResponsesStageAgent(api_key="unit-test-key", model="test-model")
        with patch("src.agentic_shortener.llm_agent.urllib.request.urlopen",
                   return_value=FakeResponse(body)) as call:
            artifact = agent.execute("implementation", "Add validation", {"artifacts": {}})
        self.assertEqual(artifact["provider"], "openai-responses")
        self.assertEqual(artifact["files"][0]["path"], "shortener/validation.py")
        self.assertTrue(call.called)
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")

    def test_repository_snapshot_is_bounded_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("API_KEY = 'do-not-send'\nprint('hello')\n", encoding="utf-8")
            (root / ".env").write_text("API_KEY=private\n", encoding="utf-8")
            scanner = RepositoryScanner(allowed_roots=[root], max_total_chars=1000)
            snapshot = scanner.snapshot(root)
        self.assertEqual(snapshot["file_count"], 1)
        self.assertNotIn("do-not-send", snapshot["files"][0]["content"])
        self.assertNotIn(".env", [file["path"] for file in snapshot["files"]])

    def test_repository_path_outside_allowlist_is_rejected(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as denied:
            scanner = RepositoryScanner(allowed_roots=[allowed])
            with self.assertRaises(ValueError):
                scanner.snapshot(denied)


if __name__ == "__main__":
    unittest.main()
