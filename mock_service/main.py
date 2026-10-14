import asyncio
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Notification Service", version="0.1.0")
scenario: dict[str, int | str] = {"mode": "success", "status_code": 503, "delay_ms": 5000}
deliveries: dict[str, dict] = {}


class Scenario(BaseModel):
    mode: Literal["success", "http_error", "timeout"] = "success"
    status_code: int = Field(default=503, ge=400, le=599)
    delay_ms: int = Field(default=5000, ge=0, le=60000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.put("/admin/scenario")
def set_scenario(data: Scenario) -> dict:
    scenario.update(data.model_dump())
    return scenario


@app.post("/notifications")
async def deliver(payload: dict, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict:
    if scenario["mode"] == "timeout":
        await asyncio.sleep(int(scenario["delay_ms"]) / 1000)
        raise HTTPException(status_code=504, detail="Configured mock timeout")
    if scenario["mode"] == "http_error":
        raise HTTPException(
            status_code=int(scenario["status_code"]), detail="Configured mock failure"
        )
    if idempotency_key in deliveries:
        return {"status": "already_delivered", "duplicate": True}
    deliveries[idempotency_key] = payload
    return {"status": "delivered", "duplicate": False}


@app.get("/admin/deliveries")
def list_deliveries() -> list[dict]:
    return [{"idempotency_key": key, "payload": value} for key, value in deliveries.items()]


@app.delete("/admin/deliveries")
def clear_deliveries() -> dict[str, str]:
    deliveries.clear()
    return {"status": "cleared"}
