from __future__ import annotations

from fastapi import FastAPI, Request

from app.api.health import router as health_router
from app.shared.config import get_settings
from app.shared.tracing import configure_logging, get_logger, get_tracer


def create_app() -> FastAPI:
    get_settings()
    configure_logging()

    application = FastAPI(title="Dream Motif Interpreter", version="0.1.0")
    application.include_router(health_router)

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


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
