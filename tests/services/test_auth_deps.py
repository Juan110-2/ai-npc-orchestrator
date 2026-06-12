import asyncio
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1 import deps


class TestAuthDeps(unittest.TestCase):
    def test_optional_jwt_returns_none_without_credentials(self):
        result = asyncio.run(deps.optional_jwt(None))
        self.assertIsNone(result)

    @patch("app.api.v1.deps.verify_supabase_token")
    def test_optional_jwt_propagates_invalid_token(self, mock_verify):
        mock_verify.side_effect = HTTPException(status_code=401, detail="Token invalido")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(deps.optional_jwt(credentials))

        self.assertEqual(ctx.exception.status_code, 401)

    @patch.object(deps, "SUPABASE_JWT_SECRET", "configured-secret")
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
            allow_missing_credentials=False,
        )

        self.assertIs(resolved, user)

    @patch.object(deps, "SUPABASE_JWT_SECRET", "configured-secret")
    def test_resolve_authenticated_user_requires_credentials_when_configured(self):
        with self.assertRaises(HTTPException) as ctx:
            deps.resolve_authenticated_user(
                db=MagicMock(),
                credentials=None,
                allow_missing_credentials=False,
            )

        self.assertEqual(ctx.exception.status_code, 401)

    @patch.object(deps, "SUPABASE_JWT_SECRET", "configured-secret")
    @patch("app.api.v1.deps.verify_supabase_token")
    def test_resolve_authenticated_user_rejects_missing_subject(self, mock_verify):
        mock_verify.return_value = {}
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="ok-token")

        with self.assertRaises(HTTPException) as ctx:
            deps.resolve_authenticated_user(
                db=MagicMock(),
                credentials=credentials,
                allow_missing_credentials=False,
            )

        self.assertEqual(ctx.exception.status_code, 401)

    @patch.object(deps, "SUPABASE_JWT_SECRET", None)
    def test_resolve_authenticated_user_returns_none_when_auth_disabled(self):
        resolved = deps.resolve_authenticated_user(
            db=MagicMock(),
            credentials=None,
            allow_missing_credentials=False,
        )

        self.assertIsNone(resolved)
