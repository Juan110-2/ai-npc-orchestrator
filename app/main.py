from typing import Union
from fastapi import FastAPI
from app.api.v1.routes import profiles, conversation, scenarios, sessions
from app.api.v1.routes import conversation

app = FastAPI()

app.include_router(profiles.router)
app.include_router(conversation.router)
app.include_router(scenarios.router)
app.include_router(sessions.router)


@app.get("/")
def read_root():
    return {"Hello": "World"}