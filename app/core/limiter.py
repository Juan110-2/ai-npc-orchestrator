import base64
import json

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _subject_from_bearer(request: Request) -> str | None:
    """
    `sub` del JWT de la cabecera Authorization, sin verificar la firma.

    Solo se usa como clave del límite de mensajes: la autenticación real la hacen
    las dependencias de la ruta, que FastAPI resuelve antes de aplicar el límite,
    así que un token falso recibe 401 y nunca llega a contar.
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    parts = auth[7:].strip().split(".")
    if len(parts) != 3:
        return None
    try:
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    sub = payload.get("sub") if isinstance(payload, dict) else None
    return sub if isinstance(sub, str) and sub else None


def rate_limit_key(request: Request) -> str:
    """
    Clave del límite de mensajes: el usuario autenticado y, si no hay token, la IP.

    Contar por usuario evita que todos los estudiantes de una misma red (una sala o
    el wifi de la universidad), o todos los que llegan por el proxy de la plataforma,
    compartan un solo cupo.
    """
    sub = _subject_from_bearer(request)
    return f"user:{sub}" if sub else f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=rate_limit_key)
