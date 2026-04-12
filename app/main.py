from fastapi import FastAPI

from app.api.health import router as health_router
from app.shared.config import get_settings


def create_app() -> FastAPI:
    get_settings()

    application = FastAPI(title="Dream Motif Interpreter", version="0.1.0")
    application.include_router(health_router)
    return application


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
