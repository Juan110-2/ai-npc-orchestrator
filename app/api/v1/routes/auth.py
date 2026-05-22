"""
Endpoints de autenticación — proxy hacia Supabase Auth.

Permite obtener un JWT de Supabase directamente desde la API,
sin pasar por el frontend. Útil para pruebas en Swagger y clientes externos.

Métodos soportados por Supabase (este endpoint cubre email+password):
  - Email + contraseña  → POST /auth/login
  - Código OTP / magic link  → se inicia desde el cliente Supabase / frontend
  - OAuth Google  → se inicia desde el cliente Supabase / frontend
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
    token_type: str = Field("bearer", description="Tipo de token — siempre `bearer`.")
    expires_in: int = Field(..., description="Segundos hasta que expira el token (normalmente 3600).")
    refresh_token: str = Field(..., description="Token para renovar la sesión sin volver a autenticarse.")


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesión con email y contraseña",
    description=(
        "Autentica al usuario contra Supabase usando email y contraseña, "
        "y devuelve un JWT listo para usar en los endpoints protegidos.\n\n"
        "**Cómo usarlo en Swagger:**\n"
        "1. Ejecuta este endpoint con tus credenciales.\n"
        "2. Copia el valor de `access_token` de la respuesta.\n"
        "3. Haz clic en **Authorize** (arriba a la derecha) y pega el token.\n"
        "4. Todos los endpoints protegidos quedan autorizados para esta sesión.\n\n"
        "**Otros métodos de autenticación soportados por la plataforma:**\n"
        "- **Google OAuth**: se inicia desde el frontend — redirige a Google y Supabase emite el JWT.\n"
        "- **Magic link / OTP**: se solicita desde el frontend — Supabase envía un código al correo.\n\n"
        "**Nota**: requiere que `SUPABASE_URL` y `SUPABASE_ANON_KEY` estén configurados. "
        "En modo desarrollo local sin Supabase, este endpoint retorna `503`."
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
        "(por seguridad, no se revela si el email está registrado).\n\n"
        "El usuario recibirá un enlace para establecer una nueva contraseña. "
        "El enlace redirige al frontend configurado en Supabase."
    ),
    response_description="Sin contenido — el correo fue enviado (o el email no existe).",
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
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva cuenta con email y contraseña",
    description=(
        "Crea una nueva cuenta de usuario en la plataforma usando email y contraseña.\n\n"
        "**Flujo completo de registro:**\n"
        "1. Llamar este endpoint con email, contraseña y nombre completo.\n"
        "2. Supabase crea la cuenta y envía un correo de confirmación.\n"
        "3. El usuario confirma su correo haciendo clic en el enlace recibido.\n"
        "4. Usar `POST /auth/login` con las mismas credenciales para obtener el JWT.\n\n"
        "**Rol asignado:** todo usuario nuevo recibe el rol `student` por defecto. "
        "Un `admin` puede cambiarlo después mediante `PATCH /admin/users/{id}`.\n\n"
        "**Nota:** si la confirmación de email está desactivada en Supabase, "
        "el JWT se devuelve directamente en la respuesta de este endpoint."
    ),
    response_description=(
        "Cuenta creada. Si la confirmación de email está desactivada, incluye el JWT. "
        "Si está activada, `access_token` es `null` y el usuario debe confirmar su correo."
    ),
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
        "message": "Cuenta creada. Revisá tu correo para confirmar la cuenta antes de iniciar sesión.",
        "user_id": data.get("id"),
        "email": data.get("email"),
        "access_token": data.get("access_token"),
        "confirmation_required": data.get("access_token") is None,
    }
