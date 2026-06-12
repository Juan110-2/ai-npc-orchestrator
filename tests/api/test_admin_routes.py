import unittest
from unittest.mock import MagicMock, patch

from app.api.v1.routes import admin as admin_routes
from tests.api.test_utils import build_client, clear_overrides, make_user


class TestAdminRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)

    def tearDown(self):
        clear_overrides()

    @patch("app.api.v1.routes.admin.UsersRepository.get_by_id")
    def test_get_my_profile_returns_authenticated_user(self, mock_get_by_id):
        user = make_user(role="teacher")
        mock_get_by_id.return_value = user
        self.client.app.dependency_overrides[admin_routes.verify_supabase_jwt] = (
            lambda: {"sub": str(user.id)}
        )

        response = self.client.get("/admin/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(user.id))
        self.assertEqual(response.json()["role"], "teacher")

    @patch("app.api.v1.routes.admin.UsersRepository.list_all")
    def test_list_users_returns_all_for_admin(self, mock_list_all):
        mock_list_all.return_value = [make_user(role="student"), make_user(role="teacher")]
        self.client.app.dependency_overrides[admin_routes._require_admin] = (
            lambda: make_user(role="admin")
        )

        response = self.client.get("/admin/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    @patch("app.api.v1.routes.admin.UsersRepository.update")
    def test_update_user_blocks_self_demotion(self, mock_update):
        admin = make_user(role="admin")
        self.client.app.dependency_overrides[admin_routes._require_admin] = lambda: admin

        response = self.client.patch(
            f"/admin/users/{admin.id}",
            json={"role": "teacher"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "No puedes cambiar tu propio rol de admin")
        mock_update.assert_not_called()

    @patch("app.api.v1.routes.admin.UsersRepository.list_by_role")
    def test_list_students_allows_teacher(self, mock_list_by_role):
        mock_list_by_role.return_value = [make_user(role="student")]
        self.client.app.dependency_overrides[admin_routes._require_teacher_or_admin] = (
            lambda: make_user(role="teacher")
        )

        response = self.client.get("/admin/students")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["role"], "student")
        _, kwargs = mock_list_by_role.call_args
        self.assertEqual(kwargs["role"], "student")

    def test_list_users_rejects_non_admin(self):
        def deny():
            raise admin_routes.HTTPException(status_code=403, detail="Acceso denegado")

        self.client.app.dependency_overrides[admin_routes._require_admin] = deny

        response = self.client.get("/admin/users")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Acceso denegado")
