import base64
import json
import unittest

from starlette.requests import Request

from app.core.limiter import rate_limit_key


def _token(payload: dict) -> str:
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'ES256'})}.{b64(payload)}.firma"


def _request(authorization: str | None = None, ip: str = "10.0.0.7") -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request({"type": "http", "headers": headers, "client": (ip, 5000)})


class TestRateLimitKey(unittest.TestCase):
    def test_con_token_cuenta_por_usuario(self):
        req = _request(f"Bearer {_token({'sub': 'abc-123'})}")
        self.assertEqual(rate_limit_key(req), "user:abc-123")

    def test_dos_usuarios_en_la_misma_ip_no_comparten_cupo(self):
        a = rate_limit_key(_request(f"Bearer {_token({'sub': 'estudiante-a'})}", ip="10.0.0.7"))
        b = rate_limit_key(_request(f"Bearer {_token({'sub': 'estudiante-b'})}", ip="10.0.0.7"))
        self.assertNotEqual(a, b)

    def test_sin_token_cuenta_por_ip(self):
        self.assertEqual(rate_limit_key(_request(None, ip="10.0.0.9")), "ip:10.0.0.9")

    def test_token_mal_formado_cuenta_por_ip(self):
        for auth in ("Bearer basura", "Bearer a.b.c", "Basic usuario:clave", "Bearer " + _token({"sin": "sub"})):
            with self.subTest(auth=auth):
                self.assertEqual(rate_limit_key(_request(auth, ip="10.0.0.9")), "ip:10.0.0.9")


if __name__ == "__main__":
    unittest.main()
