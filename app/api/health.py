from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    index_last_updated: Optional[str] = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # Public endpoint by design: GET /health is intentionally unauthenticated per
    # IMPLEMENTATION_CONTRACT OBS-3.
    return HealthResponse(status="ok", index_last_updated=None)
