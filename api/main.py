from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .backend.config import ApiConfig
from .backend.db import init_app_db
from .backend.routers import admin, chat, robot, runtime, system
from .backend.state import build_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    init_app_db()
    app.state.container = build_state()
    if app.state.container.config.autostart_robot:
        app.state.container.robot.start()
    logging.getLogger("grumpyadmin").info("API startup complete")
    try:
        yield
    finally:
        app.state.container.runtime.shutdown()
        app.state.container.robot.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="grumpyadmin-api", version="0.1.0", lifespan=lifespan)

    config = ApiConfig.from_env()
    cors_origins = [o.strip() for o in config.cors_origin.split(",") if o.strip()]
    if not cors_origins:
        cors_origins = ["http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router, prefix="/api/v1")
    app.include_router(runtime.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(robot.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")

    return app


app = create_app()


def main() -> int:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
