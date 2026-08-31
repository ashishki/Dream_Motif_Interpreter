from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.dream_memory import router as dream_memory_router
from app.api.dreams import _get_job_enqueuer, _get_redis_client, is_valid_api_key
from app.api.dreams import router as dreams_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.motifs import router as motifs_router
from app.api.patterns import router as patterns_router
from app.api.research import router as research_router
from app.api.search import router as search_router
from app.api.themes import router as themes_router
from app.api.versioning import router as versioning_router
from app.shared.config import get_settings
from app.shared.telegram_auth import is_valid_telegram_web_app_init_data
from app.shared.tracing import configure_logging, get_logger, get_tracer

# The mini-app HTML shell is public by design because it contains no dream data.
# Data APIs still require X-API-Key or verified Telegram WebApp init data.
PUBLIC_PATHS = {"/health", "/ready", "/auth/callback", "/dream-memory/mini-app"}
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
MINI_APP_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://telegram.org; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors https://telegram.org https://*.telegram.org"
)


def create_app() -> FastAPI:
    get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        enqueuer_close = getattr(_get_job_enqueuer(), "shutdown", None)
        if enqueuer_close is not None:
            await enqueuer_close()
        else:
            close = getattr(_get_redis_client(), "aclose", None)
            if close is not None:
                await close()

    application = FastAPI(title="Dream Motif Interpreter", version="0.1.0", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(dreams_router)
    application.include_router(dream_memory_router)
    application.include_router(feedback_router)
    application.include_router(motifs_router)
    application.include_router(research_router)
    application.include_router(patterns_router)
    application.include_router(search_router)
    application.include_router(themes_router)
    application.include_router(versioning_router)

    @application.middleware("http")
    async def require_authentication(request: Request, call_next):
        if request.url.path not in PUBLIC_PATHS:
            if not _has_valid_auth_headers(request.headers):
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

    @application.middleware("http")
    async def protect_private_responses(request: Request, call_next):
        response = await call_next(request)
        for header, value in NO_STORE_HEADERS.items():
            response.headers[header] = value
        for header, value in BASE_SECURITY_HEADERS.items():
            response.headers[header] = value
        if request.url.path == "/dream-memory/mini-app":
            response.headers["Content-Security-Policy"] = MINI_APP_CONTENT_SECURITY_POLICY
        return response

    return application


app = create_app()


def _has_valid_auth_headers(headers) -> bool:
    api_key = headers.get("X-API-Key")
    if is_valid_api_key(api_key):
        return True

    settings = get_settings()
    return is_valid_telegram_web_app_init_data(
        headers.get("X-Telegram-Init-Data"),
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        allowed_user_id=settings.TELEGRAM_ALLOWED_CHAT_ID,
        max_age_seconds=settings.TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS,
    )


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
