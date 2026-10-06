import asyncio
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1 import deps


class TestAuthDeps(unittest.TestCase):
    @patch("app.api.v1.deps.UsersRepository.get_by_id")
    @patch("app.api.v1.deps.verify_supabase_token")
    def test_resolve_authenticated_user_returns_profile(self, mock_verify, mock_get_by_id):
        user_id = uuid4()
        user = MagicMock(id=user_id)
        mock_verify.return_value = {"sub": str(user_id)}
        mock_get_by_id.return_value = user
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="ok-token")

        resolved = deps.resolve_authenticated_user(
            db=MagicMock(),
            credentials=credentials,
        )

        self.assertIs(resolved, user)

    def test_resolve_authenticated_user_requires_credentials_when_configured(self):
        with self.assertRaises(HTTPException) as ctx:
            deps.resolve_authenticated_user(
                db=MagicMock(),
                credentials=None,
                )

        self.assertEqual(ctx.exception.status_code, 401)

    @patch("app.api.v1.deps.verify_supabase_token")
    def test_resolve_authenticated_user_rejects_missing_subject(self, mock_verify):
        mock_verify.return_value = {}
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="ok-token")

        with self.assertRaises(HTTPException) as ctx:
            deps.resolve_authenticated_user(
                db=MagicMock(),
                credentials=credentials,
                )

        self.assertEqual(ctx.exception.status_code, 401)

    @patch.object(deps, "verify_supabase_token")
    def test_resolve_authenticated_user_rejects_invalid_subject(self, mock_verify):
        mock_verify.return_value = {"sub": "no-es-uuid"}
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="ok-token")

        with self.assertRaises(HTTPException) as ctx:
            deps.resolve_authenticated_user(db=MagicMock(), credentials=credentials)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_resolve_authenticated_user_without_secret_never_returns_none(self):
        # Sin SUPABASE_JWT_SECRET ya no hay bypass: sin token siempre 401.
        with patch("app.core.auth.SUPABASE_JWT_SECRET", None):
            with self.assertRaises(HTTPException) as ctx:
                deps.resolve_authenticated_user(db=MagicMock(), credentials=None)
            self.assertEqual(ctx.exception.status_code, 401)

            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
            with self.assertRaises(HTTPException) as ctx:
                deps.resolve_authenticated_user(db=MagicMock(), credentials=credentials)
            self.assertEqual(ctx.exception.status_code, 401)

    @patch("app.api.v1.deps.UsersRepository.get_by_id")
    def test_require_staff_rules(self, mock_get_by_id):
        uid = uuid4()
        for role, allowed in (("student", False), ("teacher", True), ("admin", True)):
            mock_get_by_id.return_value = MagicMock(role=role)
            if allowed:
                self.assertEqual(deps.require_staff(db=MagicMock(), payload={"sub": str(uid)}).role, role)
            else:
                with self.assertRaises(HTTPException) as ctx:
                    deps.require_staff(db=MagicMock(), payload={"sub": str(uid)})
                self.assertEqual(ctx.exception.status_code, 403)

        mock_get_by_id.return_value = None
        with self.assertRaises(HTTPException) as ctx:
            deps.require_staff(db=MagicMock(), payload={"sub": str(uid)})
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException) as ctx:
            deps.require_staff(db=MagicMock(), payload={})
        self.assertEqual(ctx.exception.status_code, 401)
