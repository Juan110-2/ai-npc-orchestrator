"""
Autenticación y autorización de `/evaluation/*`, `/profiles/*`, `/scenarios/*` y `/admin/metrics/*`.

Sin BD real ni IA: se simula el JWT con `override_auth` y los perfiles con un dict de usuarios.
"""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.core.auth import verify_supabase_jwt
from app.main import app
from tests.api.test_utils import (
    build_client,
    clear_overrides,
    make_evaluation,
    make_session,
    make_user,
    override_auth,
)

_DEPS = "app.api.v1.deps"
_EV = "app.api.v1.routes.evaluations"


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)
        self.users: dict = {}
        self._patch = patch(f"{_DEPS}.UsersRepository.get_by_id", side_effect=lambda _db, uid: self.users.get(uid))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        clear_overrides()

    def login_as(self, role, user_id=None):
        user_id = user_id or uuid4()
        if role is not None:
            self.users[user_id] = make_user(id=user_id, role=role)
        override_auth(user_id)
        return user_id

    def logout(self):
        app.dependency_overrides.pop(verify_supabase_jwt, None)

    def call(self, method, url, body=None):
        return getattr(self.client, method)(url, json=body) if body is not None else getattr(self.client, method)(url)


class TestEvaluationsAuth(_Base):
    def _routes(self):
        sid = uuid4()
        return [
            ("get", "/evaluation/rubric/active", None),
            ("get", "/evaluation/", None),
            ("get", f"/evaluation/{sid}", None),
            ("get", f"/evaluation/student/{uuid4()}", None),
            ("post", f"/evaluation/{sid}/auto", None),
            ("put", f"/evaluation/{sid}", {"scores": {}, "status": "draft"}),
        ]

    def test_all_routes_require_token(self):
        for method, url, body in self._routes():
            with self.subTest(route=f"{method} {url}"):
                self.assertEqual(self.call(method, url, body).status_code, 401)

    def test_token_without_valid_sub_is_401(self):
        for payload in ({}, {"sub": "anon"}):
            app.dependency_overrides[verify_supabase_jwt] = lambda p=payload: p
            for method, url, body in self._routes()[1:]:
                with self.subTest(payload=payload, route=f"{method} {url}"):
                    self.assertEqual(self.call(method, url, body).status_code, 401)

    def test_write_routes_forbidden_for_student_and_profileless(self):
        for role in ("student", None):
            self.login_as(role)
            sid = uuid4()
            self.assertEqual(self.client.post(f"/evaluation/{sid}/auto").status_code, 403)
            self.assertEqual(
                self.client.put(f"/evaluation/{sid}", json={"scores": {}, "status": "draft"}).status_code,
                403,
            )

    @patch(f"{_EV}.EvaluationsRepository.submit_teacher_evaluation")
    @patch(f"{_EV}.run_auto_evaluation")
    def test_write_routes_allowed_for_staff(self, mock_auto, mock_submit):
        ev = make_evaluation()
        mock_auto.return_value = ev
        mock_submit.return_value = ev
        for role in ("teacher", "admin"):
            with self.subTest(role=role):
                uid = self.login_as(role)
                self.assertEqual(self.client.post(f"/evaluation/{ev.session_id}/auto").status_code, 200)
                r = self.client.put(f"/evaluation/{ev.session_id}", json={"scores": {}, "status": "draft"})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(mock_submit.call_args.kwargs["evaluator_id"], uid)

    @patch(f"{_EV}.RubricsRepository.get_active", return_value=None)
    def test_rubric_open_to_any_authenticated_user(self, _):
        self.login_as("student")
        # 404 (no hay rúbrica) prueba que pasó la autenticación
        self.assertEqual(self.client.get("/evaluation/rubric/active").status_code, 404)

    def _list_query(self):
        q = MagicMock()
        q.limit.return_value.all.return_value = []
        chain = self.db.query.return_value
        for _ in range(4):
            chain = chain.outerjoin.return_value
        chain.order_by.return_value = q
        return q

    def test_list_filters_own_evaluations_for_student(self):
        q = self._list_query()
        self.login_as("student")
        self.assertEqual(self.client.get("/evaluation/").status_code, 200)
        q.filter.assert_called_once()

    def test_list_filters_own_evaluations_without_profile(self):
        q = self._list_query()
        self.login_as(None)
        self.assertEqual(self.client.get("/evaluation/").status_code, 200)
        q.filter.assert_called_once()

    def test_list_returns_all_for_staff(self):
        for role in ("teacher", "admin"):
            with self.subTest(role=role):
                q = self._list_query()
                self.login_as(role)
                self.assertEqual(self.client.get("/evaluation/").status_code, 200)
                q.filter.assert_not_called()

    @patch(f"{_EV}.SessionRepository.get_by_id")
    @patch(f"{_EV}.EvaluationsRepository.get_by_session")
    def test_get_evaluation_owner_ok_other_student_403_staff_ok(self, mock_get, mock_session):
        owner = uuid4()
        ev = make_evaluation(student_id=owner)
        mock_get.return_value = ev
        mock_session.return_value = make_session(id=ev.session_id, user_id=owner)
        url = f"/evaluation/{ev.session_id}"

        self.login_as("student", owner)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.login_as("student")
        self.assertEqual(self.client.get(url).status_code, 403)

        self.login_as(None)
        self.assertEqual(self.client.get(url).status_code, 403)

        for role in ("teacher", "admin"):
            self.login_as(role)
            self.assertEqual(self.client.get(url).status_code, 200)

    @patch(f"{_EV}.EvaluationsRepository.list_by_student", return_value=[])
    def test_student_history_self_or_staff(self, _):
        me = self.login_as("student")
        self.assertEqual(self.client.get(f"/evaluation/student/{me}").status_code, 200)
        self.assertEqual(self.client.get(f"/evaluation/student/{uuid4()}").status_code, 403)
        self.login_as("teacher")
        self.assertEqual(self.client.get(f"/evaluation/student/{uuid4()}").status_code, 200)
        self.login_as("admin")
        self.assertEqual(self.client.get(f"/evaluation/student/{uuid4()}").status_code, 200)


class _CatalogMixin:
    prefix = ""
    repo = ""
    create_body: dict = {}
    update_body: dict = {}
    # método -> código esperado para staff
    list_method = ""

    def make_row(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        row = self.make_row()
        self._repo_patches = [
            patch(f"{self.repo}.{name}", return_value=value)
            for name, value in (
                (self.list_method, [row]), ("get_by_id", row),
                ("create", row), ("update", row), ("delete", True),
            )
        ]
        for p in self._repo_patches:
            p.start()

    def tearDown(self):
        for p in self._repo_patches:
            p.stop()
        super().tearDown()

    def _routes(self):
        rid = uuid4()
        return [
            ("get", f"{self.prefix}/", None, 200),
            ("get", f"{self.prefix}/{rid}", None, 200),
            ("post", f"{self.prefix}/create", self.create_body, 201),
            ("patch", f"{self.prefix}/{rid}/update", self.update_body, 200),
            ("delete", f"{self.prefix}/{rid}/delete", None, 204),
        ]

    def test_all_routes_require_token(self):
        for method, url, body, _ in self._routes():
            with self.subTest(route=f"{method} {url}"):
                self.assertEqual(self.call(method, url, body).status_code, 401)

    def test_student_reads_but_cannot_write(self):
        self.login_as("student")
        for method, url, body, ok in self._routes():
            with self.subTest(route=f"{method} {url}"):
                expected = ok if method == "get" else 403
                self.assertEqual(self.call(method, url, body).status_code, expected)

    def test_staff_has_full_access(self):
        for role in ("teacher", "admin"):
            self.login_as(role)
            for method, url, body, ok in self._routes():
                with self.subTest(role=role, route=f"{method} {url}"):
                    self.assertEqual(self.call(method, url, body).status_code, ok)


class TestProfilesAuth(_CatalogMixin, _Base):
    prefix = "/profiles"
    list_method = "get_all"
    repo = "app.api.v1.routes.profiles.ProfileRepository"
    create_body = {"name": "Ana", "description": "d", "traits": {}, "behavior": {}}
    update_body = {"name": "Ana"}

    def make_row(self):
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=uuid4(), name="Ana", description="d", traits={}, behavior={},
            created_at=now, updated_at=now,
        )


class TestScenariosAuth(_CatalogMixin, _Base):
    prefix = "/scenarios"
    list_method = "list"
    repo = "app.api.v1.routes.scenarios.ScenarioRepository"
    create_body = {"name": "Esc", "context": "ctx", "severity": 3}
    update_body = {"name": "Esc"}

    def make_row(self):
        return SimpleNamespace(
            id=uuid4(), name="Esc", context="ctx", severity=3, risk_flags=[],
            constraints={}, created_at=datetime.now(timezone.utc),
        )


class TestMetricsAuth(_Base):
    def test_requires_token(self):
        self.assertEqual(self.client.get("/admin/metrics/providers").status_code, 401)

    def test_bearer_without_secret_is_401(self):
        with patch("app.core.auth.SUPABASE_JWT_SECRET", None):
            r = self.client.get("/admin/metrics/providers", headers={"Authorization": "Bearer x"})
        self.assertEqual(r.status_code, 401)
