import unittest

from src.agentic_shortener.database import Database
from src.agentic_shortener.models import DomainError
from src.agentic_shortener.shortener import ShortenerService, validate_url


class ShortenerTests(unittest.TestCase):
    def setUp(self):
        self.service = ShortenerService(Database(":memory:"))

    def test_create_resolve_and_analytics(self):
        link = self.service.create("https://example.com/a?b=1")
        self.assertEqual(self.service.resolve(link.code), "https://example.com/a?b=1")
        updated = self.service.get(link.code)
        self.assertEqual(updated.clicks, 1)
        self.assertIsNotNone(updated.last_clicked_at)

    def test_expired_link_is_not_resolved(self):
        link = self.service.create("https://example.com", 1)
        with self.service.database.connect() as connection:
            connection.execute("UPDATE links SET expires_at='2000-01-01T00:00:00+00:00' WHERE code=?",
                               (link.code,))
        with self.assertRaises(DomainError):
            self.service.resolve(link.code)

    def test_rejects_non_http_and_credentials(self):
        for value in ("javascript:alert(1)", "file:///etc/passwd", "https://user:pass@example.com"):
            with self.subTest(value=value), self.assertRaises(DomainError):
                validate_url(value)

    def test_expiry_bounds(self):
        with self.assertRaises(DomainError):
            self.service.create("https://example.com", 0)


if __name__ == "__main__":
    unittest.main()
