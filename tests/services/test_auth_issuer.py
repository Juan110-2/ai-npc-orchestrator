import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jose import jwk, jwt

from app.core import auth

_ISSUER = "https://proyecto.supabase.co/auth/v1"


def _make_key():
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_jwk = jwk.construct(
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
        algorithm="ES256",
    ).to_dict()
    public_jwk["kid"] = "k1"
    return pem, public_jwk


class TestAsymmetricIssuer(unittest.TestCase):
    def setUp(self):
        self.pem, self.public_jwk = _make_key()
        self.jwks_calls = []

        def fake_get_jwk(url, kid):
            self.jwks_calls.append(url)
            return self.public_jwk

        self._p = patch.object(auth, "_get_jwk_for_kid", side_effect=fake_get_jwk)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _token(self, iss):
        return jwt.encode(
            {"sub": "u1", "iss": iss, "exp": int(time.time()) + 60},
            self.pem,
            algorithm="ES256",
            headers={"kid": "k1"},
        )

    def test_matching_issuer_is_accepted(self):
        with patch.object(auth, "SUPABASE_JWT_ISSUER", _ISSUER), patch.object(auth, "SUPABASE_JWKS_URL", None):
            claims = auth.verify_supabase_token(self._token(_ISSUER))
        self.assertEqual(claims["sub"], "u1")
        self.assertEqual(self.jwks_calls, [f"{_ISSUER}/.well-known/jwks.json"])

    def test_mismatched_issuer_is_rejected_without_fetching_jwks(self):
        with patch.object(auth, "SUPABASE_JWT_ISSUER", _ISSUER), patch.object(auth, "SUPABASE_JWKS_URL", None):
            with self.assertRaises(HTTPException) as ctx:
                auth.verify_supabase_token(self._token("https://atacante.example/auth/v1"))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(self.jwks_calls, [])

    def test_no_configured_issuer_is_rejected(self):
        with patch.object(auth, "SUPABASE_JWT_ISSUER", None), patch.object(auth, "SUPABASE_JWKS_URL", None):
            with self.assertRaises(HTTPException) as ctx:
                auth.verify_supabase_token(self._token("https://atacante.example/auth/v1"))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(self.jwks_calls, [])
