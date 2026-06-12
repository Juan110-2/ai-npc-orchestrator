# AI NPC Orchestrator

Backend del trabajo de grado para orquestar conversaciones con NPC impulsados por IA, administrar sesiones de práctica clínica simulada y registrar trazabilidad técnica y pedagógica.

## Qué hace este backend

- expone una API REST con FastAPI
- administra perfiles de NPC y escenarios clínicos
- inicia, sigue y cierra sesiones de práctica
- procesa conversación síncrona y streaming SSE
- soporta múltiples proveedores de IA
- registra métricas técnicas por llamada
- genera evaluación automática y soporta evaluación docente

## Alcance actual

- este backend vive en un repositorio separado del frontend
- el flujo principal del orquestador ya está implementado
- el foco actual es robustecer pruebas, documentación y mantenibilidad sin cambiar la lógica de negocio

## Stack principal

- Python 3
- FastAPI
- SQLAlchemy
- PostgreSQL
- Supabase Auth
- Pydantic
- `openai`
- `google-genai`

## Estructura actual

```text
app/
|-- api/v1/routes/        # Endpoints HTTP
|-- core/                 # Configuración, auth y base de datos
|-- models/               # Modelos ORM
|-- repositories/         # Acceso a datos
|-- schemas/              # Contratos de entrada y salida
`-- services/
    |-- ai/               # Clientes y métricas de IA
    |-- conversation/     # Núcleo conversacional, heurísticas y streaming
    |-- evaluation/       # Evaluación automática
    `-- sessions/         # Tiempo de sesión y utilidades
scripts/                  # Benchmarks y generación de sesiones
tests/
|-- api/                  # Contratos HTTP y rutas
|-- integration/          # Integración real con base de datos
`-- services/             # Servicios y lógica puntual
supabase/                 # Migraciones SQL
```

## Levantar el proyecto

### 1. Crear entorno virtual

```powershell
python -m venv .venv
```

### 2. Instalar dependencias

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configurar variables de entorno

Mínimas:

```env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/ai_npc
AI_PROVIDER=mock
```

Según proveedor:

```env
OPENAI_API_KEY=...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...
```

Para auth real:

```env
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_JWT_SECRET=...
SUPABASE_JWT_ISSUER=...
SUPABASE_JWKS_URL=...
```

### 4. Ejecutar la API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 5. Abrir Swagger

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

## Pruebas

Importante: usa el Python del entorno virtual del proyecto.

### Suite principal actual

```powershell
.\.venv\Scripts\python.exe -m unittest tests.services.test_conversation_heuristics tests.services.test_streaming tests.services.test_auth_deps tests.api.test_sessions_routes tests.api.test_evaluations_routes tests.api.test_metrics_routes tests.api.test_admin_routes tests.api.test_conversation_routes tests.api.test_conversation_stream_routes tests.integration.test_repositories_integration
```

### Suites por bloque

Heurísticas:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.services.test_conversation_heuristics
```

Streaming y auth/deps:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.services.test_streaming tests.services.test_auth_deps
```

Rutas HTTP:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.api.test_sessions_routes tests.api.test_evaluations_routes tests.api.test_metrics_routes tests.api.test_admin_routes tests.api.test_conversation_routes tests.api.test_conversation_stream_routes
```

Integración real con base de datos:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.integration.test_repositories_integration
```

Nota: la prueba de evaluaciones reutiliza registros reales existentes en `public.user_profiles`, porque en este proyecto esa tabla depende del flujo real de auth de Supabase y sus llaves foráneas.

### Validación rápida de compilación

```powershell
.\.venv\Scripts\python.exe -m py_compile app\main.py
```

Si haces cambios grandes:

```powershell
.\.venv\Scripts\python.exe -m py_compile app\api\v1\routes\auth.py app\api\v1\routes\sessions.py app\api\v1\routes\evaluations.py app\services\conversation\streaming.py
```

## Benchmarks y scripts útiles

Benchmark base:

```powershell
.\.venv\Scripts\python.exe scripts/bench_providers.py
```

Benchmark con tag:

```powershell
.\.venv\Scripts\python.exe scripts/bench_providers_tagged.py --benchmark-tag bench_v2 --turns 5
```

Sesiones clínicas multi-turno:

```powershell
.\.venv\Scripts\python.exe scripts/generate_clinical_sessions_2x1.py --turns 8
```

## Estado actual resumido

- la lógica conversacional fue desacoplada en `app/services/conversation/`
- Swagger quedó más alineado con los contratos reales de respuesta
- ya existe una base de pruebas de servicios, rutas y SSE
- ya existe una primera capa de integración real con PostgreSQL para repositorios clave
- todavía conviene seguir ampliando cobertura sobre flujos completos y revisar archivos heredados con codificación inconsistente
- la verificación agregada más reciente dejó `50` pruebas exitosas

## Archivos de contexto del proyecto

- estado vivo del backend: [README-backend.md](D:/Universidad/Trabajo%20de%20Grado/project-information/README-backend.md)
- estado vivo del frontend: [README-frontend.md](D:/Universidad/Trabajo%20de%20Grado/project-information/README-frontend.md)
