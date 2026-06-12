import unittest
from unittest.mock import MagicMock

from app.api.v1.routes import metrics as metrics_routes
from tests.api.test_utils import build_client, clear_overrides, make_user


class _MappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]


class TestMetricsRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)

    def tearDown(self):
        clear_overrides()

    def test_get_provider_metrics_returns_rows(self):
        self.client.app.dependency_overrides[metrics_routes._require_admin] = (
            lambda: make_user(role="admin")
        )
        self.db.execute.return_value = _MappingsResult(
            [{"provider": "openai", "model": "gpt", "purpose": "orchestrator"}]
        )

        response = self.client.get("/admin/metrics/providers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["provider"], "openai")

    def test_get_metrics_summary_returns_totals(self):
        self.client.app.dependency_overrides[metrics_routes._require_admin] = (
            lambda: make_user(role="admin")
        )
        self.db.execute.side_effect = [
            _MappingsResult(
                [{
                    "total_calls": 10,
                    "total_ok": 9,
                    "total_errors": 1,
                    "total_tokens_in": 100,
                    "total_tokens_out": 50,
                    "total_cost_usd": 1.23,
                    "n_providers": 2,
                    "n_sessions": 3,
                }]
            ),
            _MappingsResult([{"provider": "openai", "model": "gpt", "n_calls": 10}]),
            _MappingsResult([{"purpose": "orchestrator", "n_calls": 10}]),
        ]

        response = self.client.get("/admin/metrics/summary")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["totals"]["total_calls"], 10)
        self.assertEqual(body["by_provider"][0]["provider"], "openai")

    def test_metrics_requires_admin_when_dependency_fails(self):
        def deny():
            raise metrics_routes.HTTPException(status_code=403, detail="Solo administradores")

        self.client.app.dependency_overrides[metrics_routes._require_admin] = deny

        response = self.client.get("/admin/metrics/providers")

        self.assertEqual(response.status_code, 403)
