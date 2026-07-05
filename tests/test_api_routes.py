import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src import api_v1_endpoints as api


class FakeCursor:
    def __init__(self):
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.query = query

    def fetchone(self):
        if "current_database" in self.query:
            return {
                "checked_at": datetime(2026, 7, 4, tzinfo=timezone.utc),
                "database_name": "pursuitdesk_test",
            }
        return None


class FakeConnection:
    def cursor(self, *args, **kwargs):
        return FakeCursor()


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        api.app.dependency_overrides[api.get_db_connection] = lambda: FakeConnection()
        self.client = TestClient(api.app)

    def tearDown(self):
        api.app.dependency_overrides.clear()

    def test_health_route_returns_runtime_contract(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "pursuitdesk_test")
        self.assertEqual(body["vector_store"], "pgvector")
        self.assertIn("checked_at", body)
        self.assertIn("auth_required", body)

    def test_active_opportunity_filter_validation_rejects_invalid_range(self):
        response = self.client.get("/api/v1/opportunities/active?min_value=10&max_value=1")

        self.assertEqual(response.status_code, 422)
        self.assertIn("min_value cannot exceed max_value", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
