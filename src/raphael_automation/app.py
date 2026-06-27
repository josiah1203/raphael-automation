"""Raphael automation service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from raphael_contracts.errors import ErrorResponse
from raphael_automation.event_bus import handle_bus_event
from raphael_automation.routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        from raphael_contracts.kafka import start_consumer

        start_consumer(handle_bus_event, group_id="raphael-automation")
    except Exception:
        pass
    yield


app = FastAPI(title="raphael-automation", version="0.1.0", lifespan=lifespan)
app.include_router(router, prefix="/v1/automations")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "raphael-automation"}


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=ErrorResponse(code="internal_error", message=str(exc)).model_dump())
