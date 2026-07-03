"""Health check endpoints (Req 6.1-6.4).

* ``GET /health/live`` always returns 200 if the process is up (no dependency
  checks) so it answers well within 500 ms (Req 6.1).
* ``GET /health/ready`` verifies Postgres and Redis connectivity (Req 6.2),
  returning 200 when all dependencies are up (Req 6.4) or 503 listing each
  unavailable dependency (Req 6.3).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from agentforge.api.schemas import LivenessResponse, ReadinessResponse
from agentforge.db.engine import check_database

router = APIRouter(prefix="/health", tags=["health"])


async def _check_redis(redis_client) -> bool:
    """Return True if Redis answers PING, else False. Never raises."""
    if redis_client is None:
        return False
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Liveness: always 200 if the process is running."""
    return LivenessResponse(status="alive")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(request: Request) -> Response:
    """Readiness: verify Postgres + Redis; 200 all-up, else 503 listing down deps."""
    engine = getattr(request.app.state, "db_engine", None)
    redis_client = getattr(request.app.state, "redis", None)

    db_up = await check_database(engine) if engine is not None else False
    redis_up = await _check_redis(redis_client)

    dependencies = {
        "database": "up" if db_up else "down",
        "redis": "up" if redis_up else "down",
    }
    all_up = db_up and redis_up
    body = ReadinessResponse(
        status="ready" if all_up else "not_ready",
        dependencies=dependencies,
    )
    status_code = status.HTTP_200_OK if all_up else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=body.model_dump())
