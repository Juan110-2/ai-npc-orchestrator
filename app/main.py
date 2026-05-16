import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import (
    profiles, conversation, scenarios, sessions, admin, metrics, evaluations,
)

app = FastAPI(title="AI NPC Orchestrator", version="0.1.0")

default_origins = ",".join(
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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

app.include_router(profiles.router)
app.include_router(conversation.router)
app.include_router(scenarios.router)
app.include_router(sessions.router)
app.include_router(admin.router)
app.include_router(metrics.router)
app.include_router(evaluations.router)


@app.get("/")
def read_root():
    return {"service": "ai-npc-orchestrator", "status": "ok"}
