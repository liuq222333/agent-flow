from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.v1.router import router as v1_router
from app.core.auth import authenticate_api_request
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agent Workflow Platform API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def api_auth_middleware(request: Request, call_next):
        decision = authenticate_api_request(
            request.url.path,
            request.headers.get("authorization"),
            settings,
        )
        if not decision.allowed:
            return JSONResponse(
                {"detail": decision.detail},
                status_code=decision.status_code,
                headers=decision.headers,
            )
        return await call_next(request)

    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
