from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.dreams import _get_redis_client, is_valid_api_key, router as dreams_router
from app.api.health import router as health_router
from app.api.motifs import router as motifs_router
from app.api.patterns import router as patterns_router
from app.api.research import router as research_router
from app.api.search import router as search_router
from app.api.themes import router as themes_router
from app.api.versioning import router as versioning_router
from app.shared.config import get_settings
from app.shared.tracing import configure_logging, get_logger, get_tracer

PUBLIC_PATHS = {"/health", "/auth/callback"}


def create_app() -> FastAPI:
    get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        close = getattr(_get_redis_client(), "aclose", None)
        if close is not None:
            await close()

    application = FastAPI(title="Dream Motif Interpreter", version="0.1.0", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(dreams_router)
    application.include_router(motifs_router)
    application.include_router(research_router)
    application.include_router(patterns_router)
    application.include_router(search_router)
    application.include_router(themes_router)
    application.include_router(versioning_router)

    @application.middleware("http")
    async def require_authentication(request: Request, call_next):
        if request.url.path not in PUBLIC_PATHS:
            api_key = request.headers.get("X-API-Key")
            if not is_valid_api_key(api_key):
                return JSONResponse(
                    status_code=_unauthorized_status_code(request.url.path),
                    content={"detail": "Unauthorized"},
                )
        return await call_next(request)

    @application.middleware("http")
    async def log_requests(request: Request, call_next):
        tracer = get_tracer("app.http")
        logger = get_logger("app.http")

        with tracer.start_as_current_span(f"http.{request.method.lower()}") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.route", request.url.path)

            response = await call_next(request)

            span.set_attribute("http.status_code", response.status_code)
            logger.info(
                "request.completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response

    return application


app = create_app()


def _unauthorized_status_code(path: str) -> int:
    if path.startswith("/themes/categories/") and path.endswith("/approve"):
        return 403
    return 401


def main() -> None:
    import uvicorn

    host = "0.0.0.0" if get_settings().ENV == "production" else "127.0.0.1"
    uvicorn.run(app, host=host, port=8000, reload=False)


if __name__ == "__main__":
    main()
