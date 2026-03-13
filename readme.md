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


