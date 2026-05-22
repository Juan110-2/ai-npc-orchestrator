import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import (
    profiles, conversation, scenarios, sessions, admin, metrics, evaluations, auth,
)

_DESCRIPTION = """
API del orquestador de simulaciones con personajes NPC impulsados por IA.

## Flujo típico de uso

**Configuración previa** (una sola vez — rol `teacher` o `admin`):

```
1. POST /auth/login      → obtener JWT
2. POST /scenarios/      → crear escenario (situación, severidad inicial, riesgos)
3. POST /profiles/       → crear perfil del NPC (identidad, comportamiento, severidad)
```

**Inicio de sesión** (rol `teacher` o `admin`, asigna la sesión al estudiante):

```
1. POST /auth/login                          → obtener JWT
2. POST /sessions/start                      → crear sesión (scenario_id + profile_id + user_id del estudiante)
```

> `teacher` y `admin` pueden colocar su propio `user_id` en `user_id` para asignarse la sesión a sí mismos y probar el flujo completo.

**Práctica** (rol `student` — todo ocurre a través de la sesión asignada):

```
1. POST /auth/login                          → obtener JWT
2. GET  /sessions/                           → consultar sesiones propias
3. POST /conversation/{session_id}/turn      → enviar mensajes al NPC (turno a turno)
   └── streaming: GET /conversation/{session_id}/stream  (SSE, text/event-stream)
4. PATCH /sessions/{session_id}/time         → reportar tiempo de práctica acumulado
5. PATCH /sessions/{session_id}/end          → cerrar sesión (success | crisis | inappropriate)
```

**Evaluación** (rol `teacher` o `admin`):

```
1. GET /evaluations/{session_id}             → revisar métricas automáticas generadas al cerrar
2. PUT /evaluations/{session_id}             → completar rúbrica con scores y feedback
```

## Recursos principales

| Recurso | Descripción |
|---|---|
| **Profiles** | Perfiles de personajes simulados (identidad, comportamiento, rango de severidad) |
| **Scenarios** | Escenarios de simulación que contextualizan cada sesión (situación, severidad inicial, riesgos) |
| **Sessions** | Sesiones: vinculan perfil + escenario, rastrean severidad y tiempo acumulado |
| **Conversation** | Motor de conversación: turno síncrono o streaming SSE en tiempo real |
| **Admin** | Gestión de usuarios y roles (`student` / `teacher` / `admin`) |
| **Admin Metrics** | Métricas técnicas de proveedores de IA: latencia, tokens, costos (solo `admin`) |
| **Evaluation** | Evaluación: métricas automáticas + rúbrica completada por el docente |

## Autenticación

Los endpoints protegidos requieren un JWT de Supabase en el header:

```
Authorization: Bearer <token>
```

En modo desarrollo (sin `SUPABASE_JWT_SECRET`), la autenticación se omite automáticamente.

## Severidad emocional

La severidad (`current_severity`) es un valor flotante entre `behavior_min` y `behavior_max`
del perfil (por defecto `0.0–5.0`). Refleja el estado emocional del personaje simulado (NPC):

- **0–1**: Calmado, receptivo
- **2–3**: Moderadamente angustiado
- **4**: Severamente angustiado
- **5**: Muy alto — cierre automático de sesión
"""

app = FastAPI(
    title="AI NPC Orchestrator",
    version="0.1.0",
    description=_DESCRIPTION,
    # contact={
    #     "name": "Trabajo de Grado — AI NPC Orchestrator",
    #     "email": "juan.moreno.jaramillo@correounivalle.edu.co",
    # },
    openapi_tags=[
        {
            "name": "auth",
            "description": (
                "Autenticación de usuarios. "
                "`POST /auth/login` permite obtener un JWT de Supabase con email y contraseña, "
                "listo para usar en los endpoints protegidos directamente desde Swagger. "
                "Otros métodos (Google OAuth, magic link) se inician desde el frontend."
            ),
        },
        {
            "name": "profiles",
            "description": (
                "Perfiles de personajes simulados (NPC). "
                "Definen nombre, identidad (`traits`) y comportamiento conversacional (`behavior`), "
                "incluido el rango de severidad emocional permitido."
            ),
        },
        {
            "name": "scenarios",
            "description": (
                "Escenarios de simulación que contextualizan cada sesión. "
                "Incluyen la situación narrativa, severidad emocional inicial (1–5), "
                "indicadores de riesgo y restricciones específicas."
            ),
        },
        {
            "name": "sessions",
            "description": (
                "Sesiones de práctica que vinculan un perfil con un escenario. "
                "Rastrean severidad emocional en tiempo real, tiempo acumulado y estado "
                "(`active` / `completed` / `terminated`)."
            ),
        },
        {
            "name": "conversation",
            "description": (
                "Motor de conversación con el NPC. Cada turno persiste mensajes, "
                "recalcula severidad y detecta condiciones de cierre automático. "
                "Soporta respuesta síncrona y streaming SSE (`text/event-stream`)."
            ),
        },
        {
            "name": "admin",
            "description": (
                "Gestión de usuarios y roles. "
                "`GET /admin/me` requiere cualquier JWT válido; "
                "el resto de operaciones exige rol `admin`."
            ),
        },
        {
            "name": "admin-metrics",
            "description": (
                "Métricas técnicas de los proveedores de IA utilizados en el orquestador "
                "(latencia p50/p95/p99, TTFT, tokens, tasa de éxito, costo). "
                "Acceso exclusivo para `admin`."
            ),
        },
        {
            "name": "evaluation",
            "description": (
                "Evaluación pedagógica de sesiones. "
                "Incluye métricas automáticas (calculadas al cerrar la sesión) "
                "y la rúbrica completada por el docente con puntuaciones y retroalimentación."
            ),
        },
    ],
)

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
