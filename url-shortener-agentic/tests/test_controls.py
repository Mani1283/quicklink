import json
import tempfile
import unittest
from pathlib import Path

from src.agentic_shortener.audit import JsonlAuditLog
from src.agentic_shortener.ratelimit import SlidingWindowRateLimiter


class ControlsTests(unittest.TestCase):
    def test_sliding_window_rate_limit_and_reset(self):
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)
        self.assertEqual(limiter.allow("client", now=100), (True, 0))
        self.assertEqual(limiter.allow("client", now=101), (True, 0))
        allowed, retry_after = limiter.allow("client", now=102)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)
        self.assertEqual(limiter.allow("client", now=111), (True, 0))

    def test_audit_chain_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            audit = JsonlAuditLog(path)
            audit.append({"event_id": 1, "type": "run_created"})
            audit.append({"event_id": 2, "type": "approval_requested"})
            self.assertEqual(audit.verify(), (True, 2, None))
            records = path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(records[0])
            tampered["event"]["type"] = "rewritten"
            records[0] = json.dumps(tampered)
            path.write_text("\n".join(records) + "\n", encoding="utf-8")
            self.assertFalse(audit.verify()[0])


if __name__ == "__main__":
    unittest.main()
