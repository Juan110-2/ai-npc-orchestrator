import os
from typing import get_args, get_origin

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.routes import admin, auth, conversation, evaluations, metrics, profiles, scenarios, sessions

_DESCRIPTION = """
API del orquestador de simulaciones con personajes NPC impulsados por IA.

## Flujo típico de uso

**Configuración previa** (`teacher` o `admin`):

1. `POST /auth/login` para obtener JWT
2. `POST /scenarios/create` para crear el escenario
3. `POST /profiles/create` para crear el perfil del NPC

**Inicio de sesión de práctica**:

1. `POST /sessions/start` para vincular perfil, escenario y estudiante

**Práctica del estudiante**:

1. `GET /sessions/` para consultar sesiones disponibles
2. `POST /conversation/{session_id}` para conversar por turnos
3. `POST /conversation/{session_id}/stream` para streaming SSE
4. `PATCH /sessions/{session_id}/time` para reportar tiempo de práctica
5. `PATCH /sessions/{session_id}/end` para cerrar la sesión

**Evaluación**:

1. `GET /evaluation/{session_id}` para revisar la evaluación
2. `PUT /evaluation/{session_id}` para completar scores y feedback docente

## Recursos principales

- **Auth**: autenticación y recuperación de acceso
- **Profiles**: perfiles de personajes simulados
- **Scenarios**: escenarios clínicos o narrativos
- **Sessions**: sesiones de práctica y trazabilidad de tiempo/estado
- **Conversation**: motor conversacional síncrono y streaming SSE
- **Admin**: usuarios y roles
- **Admin Metrics**: métricas técnicas de llamadas de IA
- **Evaluation**: evaluación automática y docente

## Autenticación

Los endpoints protegidos requieren un JWT de Supabase:

`Authorization: Bearer <token>`

En modo desarrollo, si `SUPABASE_JWT_SECRET` no está configurado, varias rutas omiten autenticación.

## Severidad emocional

La severidad (`current_severity`) es un valor flotante entre `behavior_min` y `behavior_max`
del perfil. Refleja el estado emocional del personaje simulado:

- **0 a 1**: calmado, receptivo
- **2 a 3**: moderadamente angustiado
- **4**: severamente angustiado
- **5**: muy alto, con posibilidad de cierre automático
"""

app = FastAPI(
    title="AI NPC Orchestrator",
    version="0.1.0",
    description=_DESCRIPTION,
    openapi_tags=[
        {
            "name": "auth",
            "description": (
                "Autenticación de usuarios. Incluye login por email y contraseña, "
                "registro y recuperación de acceso."
            ),
        },
        {
            "name": "profiles",
            "description": (
                "Perfiles de personajes simulados (NPC), con identidad, comportamiento "
                "y rango de severidad emocional."
            ),
        },
        {
            "name": "scenarios",
            "description": (
                "Escenarios de simulación que contextualizan cada sesión, incluyendo "
                "severidad inicial, riesgos y restricciones."
            ),
        },
        {
            "name": "sessions",
            "description": (
                "Sesiones de práctica que vinculan perfil y escenario, y registran "
                "estado, tiempo acumulado y severidad."
            ),
        },
        {
            "name": "conversation",
            "description": (
                "Motor conversacional con el NPC. Soporta flujo síncrono y streaming SSE."
            ),
        },
        {
            "name": "admin",
            "description": "Gestión de usuarios y roles.",
        },
        {
            "name": "admin-metrics",
            "description": (
                "Métricas técnicas de proveedores de IA: latencia, tokens, costo y tasas de éxito."
            ),
        },
        {
            "name": "evaluation",
            "description": (
                "Evaluación pedagógica de sesiones: métricas automáticas y rúbrica docente."
            ),
        },
    ],
)


def _resolve_schema_example(schema: dict, components: dict) -> dict | list | str | int | float | bool | None:
    if not schema:
        return None

    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        target = components.get("schemas", {}).get(name, {})
        if "example" in target:
            return target["example"]
        return _resolve_schema_example(target, components)

    if "example" in schema:
        return schema["example"]

    schema_type = schema.get("type")
    if schema_type == "array":
        item_example = _resolve_schema_example(schema.get("items", {}), components)
        return [item_example] if item_example is not None else []

    if schema_type == "object":
        properties = schema.get("properties", {})
        built = {}
        for key, value in properties.items():
            prop_example = _resolve_schema_example(value, components)
            if prop_example is not None:
                built[key] = prop_example
        return built or None

    return schema.get("default")


def _resolve_response_model_example(response_model):
    if response_model is None:
        return None

    origin = get_origin(response_model)
    if origin is list:
        args = get_args(response_model)
        if args:
            item_example = _resolve_response_model_example(args[0])
            return [item_example] if item_example is not None else []
        return []

    model_config = getattr(response_model, "model_config", None)
    if isinstance(model_config, dict):
        extra = model_config.get("json_schema_extra") or {}
        if "example" in extra:
            return extra["example"]
    return None


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )

    components = openapi_schema.get("components", {})
    route_examples = {}
    for route in app.routes:
        if not hasattr(route, "path") or not hasattr(route, "methods"):
            continue
        response_model = getattr(route, "response_model", None)
        example = _resolve_response_model_example(response_model)
        if example is None:
            continue
        for method in getattr(route, "methods", []):
            route_examples[(route.path, method.lower())] = example

    for path, path_item in openapi_schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                content = response.get("content", {}).get("application/json")
                if not content or content.get("example") or content.get("examples"):
                    continue
                example = route_examples.get((path, method))
                if example is None:
                    example = _resolve_schema_example(content.get("schema", {}), components)
                if example is not None:
                    content["example"] = example

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

default_origins = ",".join(
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://frontend-ai-npc-orchestrator.vercel.app",
    ]
)
allowed_origins = os.getenv("CORS_ALLOW_ORIGINS", default_origins).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(conversation.router)
app.include_router(scenarios.router)
app.include_router(sessions.router)
app.include_router(admin.router)
app.include_router(metrics.router)
app.include_router(evaluations.router)


@app.get("/", include_in_schema=False)
def read_root():
    return {"service": "ai-npc-orchestrator", "status": "ok"}
