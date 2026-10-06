import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from jose import jwt

from app.core import auth

_SECRET = "secreto-de-prueba-solo-para-tests"


class TestTokenClaims(unittest.TestCase):
    def _verify(self, claims, key=_SECRET):
        token = jwt.encode(claims, key, algorithm="HS256")
        with patch.object(auth, "SUPABASE_JWT_SECRET", _SECRET):
            return auth.verify_supabase_token(token)

    def test_valid_token_is_accepted(self):
        payload = self._verify({"sub": "abc", "exp": int(time.time()) + 60})
        self.assertEqual(payload["sub"], "abc")

    def test_token_without_exp_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._verify({"sub": "abc"})
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._verify({"sub": "abc", "exp": int(time.time()) - 60})
        self.assertEqual(ctx.exception.status_code, 401)

    def test_token_signed_with_other_secret_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._verify({"sub": "abc", "exp": int(time.time()) + 60}, key="otro-secreto-distinto")
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
