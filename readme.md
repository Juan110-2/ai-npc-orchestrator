# AI NPC Orchestrator

Middleware backend for orchestrating AI-driven NPC conversations using configurable profiles.

This project is part of an academic prototyping phase and focuses on validating architecture, logic, and real-time interaction flow between psychological profiles and large language models.

---

## Project Goals

- Define structured psychological/personality profiles
- Inject those profiles into AI model prompts dynamically
- Orchestrate real-time conversations for NPCs
- Remain model-agnostic (OpenAI, local models, or other providers)
- Support future scalability and extensibility

---

## Tech Stack

- Python 3.10+
- FastAPI
- Uvicorn
- python-dotenv
- Pydantic

---

## Project Structure (initial)

```text
app/
	main.py
	api/v1/routes/
		profiles.py
		scenarios.py
		sessions.py
		conversation.py
	services/
		orchestrator.py
		intervention_evaluator.py
		severity_manager.py
		ai/
			base.py
			factory.py
			openai_client.py
			local_mock.py
```

---

## Run Locally

1. Create a virtual environment:

```bash
python -m venv .venv
```

2. Activate it (Windows PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

Alternative without activation (Windows):

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

4. Configure environment variables (at least):

```env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/ai_npc
AI_PROVIDER=mock
# If using OpenAI:
# AI_PROVIDER=openai
# OPENAI_API_KEY=your_api_key
```

5. Start the API:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Alternative without activation (Windows):

```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

6. Open docs:

```text
http://127.0.0.1:8000/docs
```

---

## Real-Time Operation and External Service Integration

This API can work in near real-time when called from another service.
The current conversation endpoint is synchronous request-response:

- Endpoint: `POST /conversation/{session_id}`
- Input body:

```json
{
	"content": "Therapist/trainee message"
}
```

- Output: one `ConversationMessageResponse` (patient reply + metadata)

### Current processing flow per message

1. Validate session exists and is open.
2. Store trainee message.
3. Evaluate intervention impact.
4. Adjust emotional severity.
5. Generate patient response with orchestrator.
6. Store patient message.
7. Return response to caller.

### Integration patterns from another service

- Synchronous HTTP (simplest):
	Caller waits for immediate response from `/conversation/{session_id}`.

- Asynchronous queue/event (more scalable):
	Caller publishes event, orchestrator processes, response is returned by callback/event.

- Streaming (best real-time UX):
	Use SSE/WebSocket when partial tokens or progressive delivery are needed.

### Practical recommendation

Start with synchronous HTTP for simplicity, then move to async or streaming if latency/load grows.
Track p95/p99 latency end-to-end before changing architecture.

---

## Benchmark Scripts

### Requisito previo: activar el entorno virtual

Los scripts **deben correr con el Python del `.venv`**, no con el del sistema.
Si corres `python` directamente sin activar el venv, los módulos de IA no están disponibles.

**Opción A — activar el venv (recomendado para sesiones de trabajo):**

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/bench_providers_tagged.py --benchmark-tag bench_v2 --turns 5
```

**Opción B — llamar al ejecutable del venv directamente (sin activar):**

```powershell
.\.venv\Scripts\python.exe scripts/bench_providers_tagged.py --benchmark-tag bench_v2 --turns 5
```

> Si ves `No module named 'openai'` o `No module named 'google'`, es porque
> estás usando el Python del sistema. Usa una de las opciones anteriores.

---

### `scripts/bench_providers.py` — Benchmark base

Corrida estándar: N llamadas de orchestrator, classifier y evaluator por proveedor.
Registra en `ai_call_logs` con `purpose=bench`.

```powershell
# Corrida completa (10 turnos por proveedor)
python scripts/bench_providers.py

# Personalizar proveedores y turnos
python scripts/bench_providers.py --providers openai gemini --turns 5
```

---

### `scripts/bench_providers_tagged.py` — Benchmark con tag configurable

Misma lógica que `bench_providers.py`, pero permite etiquetar cada corrida
con un nombre diferente para comparar contra el benchmark anterior sin mezclar datos.

```powershell
# Corrida equivalente al bench base
python scripts/bench_providers_tagged.py --benchmark-tag bench

# Corrida nueva para comparar (nuevo modelo, nueva config, etc.)
python scripts/bench_providers_tagged.py --benchmark-tag bench_v2
python scripts/bench_providers_tagged.py --benchmark-tag bench_refactor --turns 15

# Solo un proveedor
python scripts/bench_providers_tagged.py --benchmark-tag bench_openai --providers openai
```

El resumen final filtra `v_provider_metrics` por el tag indicado.
Para comparar dos corridas, corre ambas con tags distintos y consulta directamente:

```sql
select purpose, provider, model, n_calls, success_rate_pct, p50_latency_ms, total_cost_usd
from public.v_provider_metrics
where purpose in ('bench', 'bench_v2')
order by purpose, provider;
```

---

### `scripts/generate_clinical_sessions_2x1.py` — Sesiones clínicas multi-turno

Genera conversaciones clínicas completas cruzando arquetipos de trainee
con proveedores NPC. El trainee es siempre Gemini. Útil para evaluación
cualitativa de respuestas NPC y análisis de latencia en contexto real.

**Combinaciones por defecto:** 2 arquetipos × 3 proveedores = 6 sesiones paralelas.
Las llamadas NPC se registran con `purpose=bench_v2` por defecto.

```powershell
# Corrida completa (5 turnos por sesión)
python scripts/generate_clinical_sessions_2x1.py

# Personalizar
python scripts/generate_clinical_sessions_2x1.py --turns 8
python scripts/generate_clinical_sessions_2x1.py --turns 10 --benchmark-tag bench_v2
python scripts/generate_clinical_sessions_2x1.py --archetypes empatico --npc-providers openai
python scripts/generate_clinical_sessions_2x1.py --workers 2
```

**Salida generada** en `scripts/transcripts/`:

| Archivo | Descripción |
|---|---|
| `session_empatico_openai_<ts>.json` | Transcript completo de una sesión |
| `all_sessions_<ts>.jsonl` | Todas las sesiones en un solo archivo |
| `metrics_<ts>.csv` | Métricas agregadas por sesión |

Cada transcript JSON contiene:
```json
{
  "meta": { "archetype": "empatico", "npc_provider": "openai", "npc_ok": 5, ... },
  "transcript": [
    { "speaker": "npc",     "content": "Hola, no sé por dónde empezar..." },
    { "speaker": "trainee", "content": "Entiendo, tómate tu tiempo..." },
    ...
  ]
}
```


