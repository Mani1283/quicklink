import json
from http.client import HTTPConnection
import threading
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.agentic_shortener import server
from src.agentic_shortener.audit import JsonlAuditLog
from src.agentic_shortener.ratelimit import SlidingWindowRateLimiter


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_database = server.database
        cls.original_shortener = server.shortener
        cls.original_orchestrator = server.orchestrator
        cls.database = server.Database(":memory:")
        cls.temp = tempfile.TemporaryDirectory()
        server.database = cls.database
        server.shortener = server.ShortenerService(cls.database)
        server.orchestrator = server.Orchestrator(cls.database,
                                                   audit_log=JsonlAuditLog(f"{cls.temp.name}/audit.jsonl"),
                                                   artifacts_dir=f"{cls.temp.name}/artifacts")
        server.post_rate_limiter = SlidingWindowRateLimiter(100, 60)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        server.database = cls.original_database
        server.shortener = cls.original_shortener
        server.orchestrator = cls.original_orchestrator
        server.post_rate_limiter = SlidingWindowRateLimiter(100, 60)
        cls.temp.cleanup()

    def post(self, path, body):
        request = Request(self.base + path, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        return urlopen(request)

    def test_shorten_then_redirect_and_read_analytics(self):
        created = json.load(self.post("/api/shorten", {"url": "https://example.com/path"}))
        connection = HTTPConnection("127.0.0.1", self.httpd.server_port)
        connection.request("GET", "/" + created["code"])
        response = connection.getresponse()
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "https://example.com/path")
        connection.close()
        metadata = json.load(urlopen(self.base + "/api/links/" + created["code"]))
        self.assertEqual(metadata["clicks"], 1)

    def test_scenario_catalog(self):
        data = json.load(urlopen(self.base + "/api/orchestration/scenarios"))
        self.assertEqual({item["id"] for item in data["scenarios"]},
                         {"greenfield", "brownfield", "ambiguous"})

    def test_openapi_schema_is_served(self):
        data = json.load(urlopen(self.base + "/openapi.json"))
        self.assertEqual(data["openapi"], "3.1.0")
        self.assertIn("/api/shorten", data["paths"])

    def test_post_rate_limit_returns_429(self):
        original = server.post_rate_limiter
        server.post_rate_limiter = SlidingWindowRateLimiter(1, 60)
        try:
            self.post("/api/shorten", {"url": "https://example.com/first"})
            with self.assertRaises(HTTPError) as error:
                self.post("/api/shorten", {"url": "https://example.com/second"})
            self.assertEqual(error.exception.code, 429)
            self.assertGreater(int(error.exception.headers["Retry-After"]), 0)
        finally:
            server.post_rate_limiter = original


if __name__ == "__main__":
    unittest.main()
