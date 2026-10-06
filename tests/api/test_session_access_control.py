import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from tests.api.test_utils import (
    build_client,
    clear_overrides,
    make_message,
    make_session,
    make_user,
    override_auth,
)

_DEPS = "app.api.v1.deps"


class TestSessionAccessControl(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)
        self.owner_id = uuid4()
        self.session = make_session(user_id=self.owner_id)
        self.other_id = uuid4()
        self.users: dict = {}

        self._patches = [
            patch(f"{_DEPS}.SessionRepository.get_by_id", side_effect=self._get_session),
            patch(f"{_DEPS}.UsersRepository.get_by_id", side_effect=self._get_user),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        clear_overrides()

    def _get_session(self, _db, session_id):
        return self.session if session_id == self.session.id else None

    def _get_user(self, _db, user_id):
        return self.users.get(user_id)

    def _login_as(self, role, user_id=None):
        user_id = user_id or uuid4()
        self.users[user_id] = make_user(id=user_id, role=role)
        override_auth(user_id)
        return user_id

    def _routes(self):
        sid = self.session.id
        return [
            ("get", f"/sessions/{sid}", None),
            ("patch", f"/sessions/{sid}/time", {"delta_seconds": 5}),
            ("post", f"/sessions/{sid}/time", {"delta_seconds": 5}),
            ("patch", f"/sessions/{sid}/end", {}),
            ("post", f"/conversation/{sid}", {"content": "hola"}),
            ("post", f"/conversation/{sid}/stream", {"content": "hola"}),
            ("get", f"/conversation/{sid}/history", None),
        ]

    def _call(self, method, url, body):
        kwargs = {} if body is None else {"json": body}
        return getattr(self.client, method)(url, **kwargs)

    # --- 401 sin token -------------------------------------------------

    def test_all_session_routes_require_token(self):
        for method, url, body in self._routes():
            with self.subTest(route=f"{method} {url}"):
                self.assertEqual(self._call(method, url, body).status_code, 401)

    def test_list_and_start_require_token(self):
        self.assertEqual(self.client.get("/sessions/").status_code, 401)
        response = self.client.post(
            "/sessions/start",
            json={"profile_id": str(uuid4()), "scenario_id": str(uuid4())},
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_returns_401(self):
        response = self.client.get(
            f"/sessions/{self.session.id}",
            headers={"Authorization": "Bearer no-es-un-jwt"},
        )
        self.assertEqual(response.status_code, 401)

    # --- 403 / 404 -----------------------------------------------------

    def test_student_gets_403_on_other_users_session(self):
        self._login_as("student", self.other_id)
        for method, url, body in self._routes():
            with self.subTest(route=f"{method} {url}"):
                self.assertEqual(self._call(method, url, body).status_code, 403)

    def test_user_without_profile_is_treated_as_student(self):
        override_auth(self.other_id)
        self.assertEqual(self.client.get(f"/sessions/{self.session.id}").status_code, 403)

    def test_student_gets_403_on_session_without_owner(self):
        self.session.user_id = None
        self._login_as("student")
        for method, url, body in self._routes():
            with self.subTest(route=f"{method} {url}"):
                self.assertEqual(self._call(method, url, body).status_code, 403)

    def test_teacher_can_read_session_without_owner(self):
        self.session.user_id = None
        self._login_as("teacher")
        self.assertEqual(self.client.get(f"/sessions/{self.session.id}").status_code, 200)

    def test_missing_session_returns_404(self):
        self._login_as("student")
        response = self.client.get(f"/sessions/{uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Session not found")

    # --- exito: dueno, teacher, admin ----------------------------------

    def test_owner_teacher_and_admin_can_get_session(self):
        for role, user_id in (
            ("student", self.owner_id),
            ("teacher", None),
            ("admin", None),
            ("superadmin", None),
        ):
            with self.subTest(role=role):
                self._login_as(role, user_id)
                response = self.client.get(f"/sessions/{self.session.id}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["id"], str(self.session.id))

    @patch("app.api.v1.routes.sessions.SessionRepository.add_time_delta")
    def test_flush_time_allowed_for_owner_and_staff(self, mock_add):
        mock_add.return_value = self.session
        for role, user_id in (("student", self.owner_id), ("teacher", None), ("admin", None)):
            with self.subTest(role=role):
                self._login_as(role, user_id)
                for method in ("patch", "post"):
                    response = self._call(method, f"/sessions/{self.session.id}/time", {"delta_seconds": 5})
                    self.assertEqual(response.status_code, 200)

    @patch("app.api.v1.routes.sessions._run_post_close_hooks")
    def test_end_session_allowed_for_owner_and_staff(self, _mock_hooks):
        for role, user_id in (("student", self.owner_id), ("teacher", None), ("admin", None)):
            with self.subTest(role=role):
                self.session.ended_at = None
                self._login_as(role, user_id)
                response = self.client.patch(f"/sessions/{self.session.id}/end", json={})
                self.assertEqual(response.status_code, 200)

    @patch("app.api.v1.routes.conversation.ConversationRepository.list_by_session")
    def test_history_allowed_for_owner_and_staff(self, mock_list):
        mock_list.return_value = [make_message(session_id=self.session.id)]
        for role, user_id in (("student", self.owner_id), ("teacher", None), ("admin", None)):
            with self.subTest(role=role):
                self._login_as(role, user_id)
                response = self.client.get(f"/conversation/{self.session.id}/history")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), 1)

    @patch("app.api.v1.routes.conversation.finalize_and_evaluate_sync")
    @patch("app.api.v1.routes.conversation.commit_patient_message")
    @patch("app.api.v1.routes.conversation.persist_patient_message")
    @patch("app.api.v1.routes.conversation.generate_sync_ai_response")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_allowed_for_owner_and_staff(
        self, mock_resolve, mock_process, mock_generate, mock_persist, _commit, _finalize
    ):
        mock_resolve.return_value = (self.session, SimpleNamespace(), SimpleNamespace())
        mock_generate.return_value = SimpleNamespace(
            content="Hola",
            provider="mock",
            model="m",
            tokens_input=1,
            tokens_output=1,
            tokens_total=2,
            latency_ms=1.0,
        )
        mock_persist.return_value = make_message(session_id=self.session.id)
        for role, user_id in (("student", self.owner_id), ("teacher", None), ("admin", None)):
            with self.subTest(role=role):
                self._login_as(role, user_id)
                response = self.client.post(f"/conversation/{self.session.id}", json={"content": "hola"})
                self.assertEqual(response.status_code, 200)

    @patch("app.services.conversation.streaming.finalize_and_evaluate_stream")
    @patch("app.services.conversation.streaming.commit_stream_message", return_value=True)
    @patch("app.services.conversation.streaming.SessionLocal")
    @patch("app.api.v1.routes.conversation.build_stream_inputs")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_stream_allowed_for_owner_and_teacher(
        self, mock_resolve, mock_process, mock_build, mock_session_local, _commit, _finalize
    ):
        from app.services.conversation.models import StreamInputs
        from tests.api.test_conversation_stream_routes import _make_ctx

        mock_resolve.return_value = (self.session, SimpleNamespace(), SimpleNamespace())
        mock_process.return_value = _make_ctx()
        mock_build.return_value = StreamInputs(system_prompt=None, effective_user_input="hola", forced_text="hola")
        mock_session_local.return_value = MagicMock()
        for role, user_id in (("student", self.owner_id), ("teacher", None)):
            with self.subTest(role=role):
                self._login_as(role, user_id)
                with self.client.stream(
                    "POST", f"/conversation/{self.session.id}/stream", json={"content": "hola"}
                ) as response:
                    body = "".join(response.iter_text())
                self.assertEqual(response.status_code, 200)
                self.assertIn("event: done", body)

    # --- 403 no persiste ni llama a la IA ------------------------------

    @patch("app.api.v1.routes.conversation.generate_sync_ai_response")
    @patch("app.api.v1.routes.conversation.build_stream_inputs")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_forbidden_converse_does_not_persist_nor_call_ai(
        self, mock_resolve, mock_process, mock_build, mock_generate
    ):
        self._login_as("student", self.other_id)
        for suffix in ("", "/stream"):
            with self.subTest(route=suffix or "sync"):
                response = self.client.post(
                    f"/conversation/{self.session.id}{suffix}", json={"content": "hola"}
                )
                self.assertEqual(response.status_code, 403)
        mock_resolve.assert_not_called()
        mock_process.assert_not_called()
        mock_build.assert_not_called()
        mock_generate.assert_not_called()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()

    def test_token_without_valid_sub_returns_401(self):
        from app.core.auth import verify_supabase_jwt
        from app.main import app

        for payload in ({"role": "anon"}, {"sub": "no-es-uuid"}):
            app.dependency_overrides[verify_supabase_jwt] = lambda payload=payload: payload
            for method, path, body in self._routes() + [("get", "/sessions/", None)]:
                with self.subTest(payload=payload, method=method, path=path):
                    response = self.client.request(method, path, json=body)
                    self.assertEqual(response.status_code, 401)

    # --- listado y start -----------------------------------------------

    @patch("app.api.v1.routes.sessions._last_model_map", return_value={})
    @patch("app.api.v1.routes.sessions._paginated_sessions", return_value=(0, []))
    def test_list_sessions_with_token_uses_payload(self, mock_paginated, _models):
        user_id = self._login_as("student")
        response = self.client.get("/sessions/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_paginated.call_args.args[1], {"sub": str(user_id)})

    @patch("app.api.v1.routes.sessions.auto_close_stale_sessions")
    @patch("app.api.v1.routes.sessions._last_model_map", return_value={})
    @patch("app.api.v1.routes.sessions._list_all_sessions", return_value=(0, []))
    @patch("app.api.v1.routes.sessions._list_user_sessions", return_value=(0, []))
    def test_list_sessions_scope_depends_on_role(self, mock_own, mock_all, _models, _stale):
        cases = [("student", False), ("teacher", False), ("admin", True), (None, False)]
        for role, sees_all in cases:
            with self.subTest(role=role):
                mock_own.reset_mock()
                mock_all.reset_mock()
                if role is None:
                    # Usuario autenticado sin perfil: solo sus sesiones.
                    override_auth(uuid4())
                else:
                    self._login_as(role)
                response = self.client.get("/sessions/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(mock_all.called, sees_all)
                self.assertEqual(mock_own.called, not sees_all)

    @patch("app.api.v1.routes.sessions.SessionRepository.start")
    @patch("app.api.v1.routes.sessions.ScenarioRepository.get_by_id")
    @patch("app.api.v1.routes.sessions.ProfileRepository.get_by_id")
    def test_start_session_student_cannot_create_sessions(self, mock_profile, mock_scenario, mock_start):
        student_id = self._login_as("student")
        # Ni para sí mismo ni para otro: el estudiante solo realiza las sesiones asignadas.
        for extra in ({}, {"user_id": str(student_id)}, {"user_id": str(self.other_id)}, {"assigned_by": str(self.other_id)}):
            with self.subTest(extra=extra):
                response = self.client.post(
                    "/sessions/start",
                    json={"profile_id": str(uuid4()), "scenario_id": str(uuid4()), **extra},
                )
                self.assertEqual(response.status_code, 403)
        mock_start.assert_not_called()
        mock_profile.assert_not_called()

    @patch("app.api.v1.routes.sessions.SessionRepository.start")
    @patch("app.api.v1.routes.sessions.ScenarioRepository.get_by_id")
    @patch("app.api.v1.routes.sessions.ProfileRepository.get_by_id")
    def test_start_session_user_without_profile_cannot_create_sessions(self, mock_profile, mock_scenario, mock_start):
        override_auth(uuid4())
        response = self.client.post(
            "/sessions/start",
            json={"profile_id": str(uuid4()), "scenario_id": str(uuid4())},
        )
        self.assertEqual(response.status_code, 403)
        mock_start.assert_not_called()

    @patch("app.api.v1.routes.sessions.SessionRepository.start")
    @patch("app.api.v1.routes.sessions.ScenarioRepository.get_by_id")
    @patch("app.api.v1.routes.sessions.ProfileRepository.get_by_id")
    def test_start_session_teacher_defaults_to_self(self, mock_profile, mock_scenario, mock_start):
        teacher_id = self._login_as("teacher")
        mock_profile.return_value = MagicMock(id=uuid4())
        mock_start.return_value = make_session(user_id=teacher_id)
        response = self.client.post(
            "/sessions/start",
            json={"profile_id": str(uuid4()), "scenario_id": str(uuid4())},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], teacher_id)
        self.assertEqual(mock_start.call_args.kwargs["assigned_by"], teacher_id)

    @patch("app.api.v1.routes.sessions.SessionRepository.start")
    @patch("app.api.v1.routes.sessions.ScenarioRepository.get_by_id")
    @patch("app.api.v1.routes.sessions.ProfileRepository.get_by_id")
    def test_start_session_teacher_and_admin_can_assign_to_other_user(self, mock_profile, mock_scenario, mock_start):
        mock_profile.return_value = MagicMock(id=uuid4())
        mock_start.return_value = make_session(user_id=self.other_id)
        for role in ("teacher", "admin"):
            with self.subTest(role=role):
                self._login_as(role)
                response = self.client.post(
                    "/sessions/start",
                    json={"profile_id": str(uuid4()), "scenario_id": str(uuid4()), "user_id": str(self.other_id)},
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(mock_start.call_args.kwargs["user_id"], self.other_id)
