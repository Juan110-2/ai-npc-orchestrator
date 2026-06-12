"""
Endpoints de autenticación: proxy hacia Supabase Auth.

Permite obtener un JWT de Supabase directamente desde la API,
sin pasar por el frontend. Útil para pruebas en Swagger y clientes externos.

Métodos soportados por Supabase (este endpoint cubre email y contraseña):
  - Email + contraseña -> POST /auth/login
  - Código OTP / magic link -> se inicia desde el cliente Supabase o el frontend
  - OAuth Google -> se inicia desde el cliente Supabase o el frontend
"""
import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import SUPABASE_ANON_KEY, SUPABASE_URL

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginInput(BaseModel):
    email: str = Field(..., description="Correo electrónico registrado en la plataforma.")
    password: str = Field(..., min_length=6, description="Contraseña de la cuenta.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "estudiante@correounivalle.edu.co",
                "password": "mi_contraseña_segura",
            }
        }
    }


class SignupInput(BaseModel):
    email: str = Field(..., description="Correo electrónico para la nueva cuenta.")
    password: str = Field(..., min_length=6, description="Contraseña (mínimo 6 caracteres).")
    full_name: str = Field(..., description="Nombre completo del usuario.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "estudiante@correounivalle.edu.co",
                "password": "mi_contraseña_segura",
                "full_name": "Juan Pérez",
            }
        }
    }


class ForgotPasswordInput(BaseModel):
    email: str = Field(..., description="Correo electrónico de la cuenta a recuperar.")

    model_config = {
        "json_schema_extra": {
            "example": {"email": "estudiante@correounivalle.edu.co"}
        }
    }


class LoginResponse(BaseModel):
    access_token: str = Field(..., description="JWT de Supabase. Úsalo en `Authorization: Bearer <token>`.")
    token_type: str = Field("bearer", description="Tipo de token: siempre `bearer`.")
    expires_in: int = Field(..., description="Segundos hasta que expira el token (normalmente 3600).")
    refresh_token: str = Field(..., description="Token para renovar la sesión sin volver a autenticarse.")


class SignupResponse(BaseModel):
    message: str = Field(..., description="Mensaje resumido del resultado del registro.")
    user_id: str | None = Field(None, description="UUID del usuario creado, si Supabase lo devuelve.")
    email: str | None = Field(None, description="Correo asociado a la cuenta creada.")
    access_token: str | None = Field(
        None,
        description="JWT inicial si la confirmación por correo está desactivada; `null` en caso contrario.",
    )
    confirmation_required: bool = Field(
        ...,
        description="Indica si el usuario debe confirmar su correo antes de iniciar sesión.",
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesión con email y contraseña",
    description=(
        "Autentica al usuario contra Supabase usando email y contraseña, "
        "y devuelve un JWT listo para usar en los endpoints protegidos.\n\n"
        "Cómo usarlo en Swagger:\n"
        "1. Ejecuta este endpoint con tus credenciales.\n"
        "2. Copia el valor de `access_token` de la respuesta.\n"
        "3. Haz clic en **Authorize** y pega el token.\n"
        "4. Los endpoints protegidos quedarán autorizados para esa sesión.\n\n"
        "Requiere que `SUPABASE_URL` y `SUPABASE_ANON_KEY` estén configurados. "
        "En modo desarrollo local sin Supabase, este endpoint responde `503`."
    ),
    response_description="JWT de Supabase con tipo, expiración y refresh token.",
    responses={
        401: {"description": "Credenciales incorrectas"},
        503: {"description": "Supabase no configurado en este entorno"},
    },
)
def login(body: LoginInput):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Autenticación no disponible en este entorno. "
                "SUPABASE_URL y SUPABASE_ANON_KEY no están configurados."
            ),
        )

    url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    payload = {"email": body.email, "password": body.password}

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo conectar con Supabase: {exc}",
        )

    if resp.status_code != 200:
        data = resp.json() if resp.content else {}
        detail = data.get("error_description") or data.get("msg") or "Credenciales inválidas"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    data = resp.json()
    return LoginResponse(
        access_token=data["access_token"],
        token_type=data.get("token_type", "bearer"),
        expires_in=data["expires_in"],
        refresh_token=data["refresh_token"],
    )


@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Solicitar recuperación de contraseña",
    description=(
        "Envía un correo de recuperación de contraseña al email indicado. "
        "Si el correo no existe en el sistema, la respuesta es igualmente `204` "
        "para no revelar si la cuenta está registrada.\n\n"
        "El enlace de recuperación redirige al frontend configurado en Supabase."
    ),
    response_description="Sin contenido: el correo fue enviado o el email no existe.",
    responses={
        503: {"description": "Supabase no configurado en este entorno"},
    },
)
def forgot_password(body: ForgotPasswordInput):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Autenticación no disponible en este entorno. "
                "SUPABASE_URL y SUPABASE_ANON_KEY no están configurados."
            ),
        )

    url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/recover"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }

    try:
        httpx.post(url, json={"email": body.email}, headers=headers, timeout=10)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo conectar con Supabase: {exc}",
        )


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva cuenta con email y contraseña",
    description=(
        "Crea una nueva cuenta de usuario en la plataforma usando email y contraseña.\n\n"
        "Flujo completo:\n"
        "1. Llamar este endpoint con email, contraseña y nombre completo.\n"
        "2. Supabase crea la cuenta y envía un correo de confirmación.\n"
        "3. El usuario confirma su correo haciendo clic en el enlace recibido.\n"
        "4. Luego puede usar `POST /auth/login` para obtener el JWT.\n\n"
        "Todo usuario nuevo recibe el rol `student` por defecto. "
        "Si la confirmación por correo está desactivada en Supabase, el JWT puede devolverse "
        "directamente en la respuesta."
    ),
    response_description="Resultado del registro, con indicación de si la confirmación por correo es requerida.",
    responses={
        400: {"description": "Email ya registrado u otros errores de validación de Supabase"},
        503: {"description": "Supabase no configurado en este entorno"},
    },
)
def signup(body: SignupInput):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Autenticación no disponible en este entorno. "
                "SUPABASE_URL y SUPABASE_ANON_KEY no están configurados."
            ),
        )

    url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/signup"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "email": body.email,
        "password": body.password,
        "data": {"full_name": body.full_name},
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo conectar con Supabase: {exc}",
        )

    if resp.status_code not in (200, 201):
        data = resp.json() if resp.content else {}
        detail = data.get("msg") or data.get("error_description") or "Error al crear la cuenta"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    data = resp.json()
    return {
        "message": "Cuenta creada. Revisa tu correo para confirmar la cuenta antes de iniciar sesión.",
        "user_id": data.get("id"),
        "email": data.get("email"),
        "access_token": data.get("access_token"),
        "confirmation_required": data.get("access_token") is None,
    }
