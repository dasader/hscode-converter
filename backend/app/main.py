import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router, ensure_data_dirs
from app.core.config import Settings


def create_app() -> FastAPI:
    app = FastAPI(title="HSCode Connector", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        try:
            settings = Settings()
            ensure_data_dirs(settings)
        except Exception:
            pass

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
