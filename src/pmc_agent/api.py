from __future__ import annotations

from dataclasses import asdict

from pmc_agent.orchestrator import PmcAgent

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - optional integration surface
    FastAPI = None
    BaseModel = object


if FastAPI:
    app = FastAPI(title="PMC Supply Chain Control Agent")
    agent = PmcAgent.create_default()

    class RunRequest(BaseModel):
        text: str

    @app.post("/agent/run")
    def run_agent(request: RunRequest) -> dict:
        return asdict(agent.run(request.text))
else:
    app = None
