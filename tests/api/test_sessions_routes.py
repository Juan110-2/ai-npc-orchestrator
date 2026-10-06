import unittest
from unittest.mock import MagicMock, patch

from tests.api.test_utils import (
    build_client,
    clear_overrides,
    make_session,
    override_auth,
    override_session_access,
)


class TestSessionRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)

    def tearDown(self):
        clear_overrides()

    @patch("app.api.v1.routes.sessions._last_model_map", return_value={})
    @patch("app.api.v1.routes.sessions._paginated_sessions")
    def test_list_sessions_returns_paginated_payload(self, mock_paginated, _mock_models):
        session = make_session()
        mock_paginated.return_value = (1, [session])
        override_auth()

        response = self.client.get("/sessions/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["page"], 1)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["id"], str(session.id))

    @patch("app.api.v1.routes.sessions.ProfileRepository.get_by_id")
    @patch("app.api.v1.routes.sessions.ScenarioRepository.get_by_id")
    @patch("app.api.v1.routes.sessions.SessionRepository.start")
    def test_start_session_uses_payload_fallbacks(self, mock_start, mock_scenario, mock_profile):
        session = make_session()
        profile = MagicMock(id=session.profile_id)
        scenario = MagicMock()
        mock_profile.return_value = profile
        mock_scenario.return_value = scenario
        mock_start.return_value = session

        override_auth(session.user_id)

        response = self.client.post(
            "/sessions/start",
            json={
                "profile_id": str(session.profile_id),
                "scenario_id": str(session.scenario_id),
            },
        )

        self.assertEqual(response.status_code, 201)
        _, kwargs = mock_start.call_args
        self.assertEqual(kwargs["user_id"], session.user_id)
        self.assertEqual(kwargs["assigned_by"], session.user_id)

    @patch("app.api.v1.routes.sessions._run_post_close_hooks")
    def test_end_session_marks_completed_and_runs_hooks(self, mock_hooks):
        session = make_session()
        override_session_access(session)

        response = self.client.patch(f"/sessions/{session.id}/end", json={})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertIsNotNone(session.ended_at)
        self.db.commit.assert_called()
        mock_hooks.assert_called_once_with(self.db, session)

    def test_end_session_returns_400_when_already_closed(self):
        session = make_session(ended_at="already")
        override_session_access(session)

        response = self.client.patch(f"/sessions/{session.id}/end", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Session already ended")
