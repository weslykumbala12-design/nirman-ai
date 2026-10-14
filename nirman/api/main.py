"""
NIRMAN AI — FastAPI Application Entry Point
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from ..memory.store import FailureMemoryStore
from ..pipeline import GenerationPipeline
from .routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to MongoDB on startup; close on shutdown."""
    settings = get_settings()
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

    memory   = FailureMemoryStore(settings.mongodb_uri, settings.mongodb_db)
    pipeline = GenerationPipeline(settings, memory)

    app.state.memory   = memory
    app.state.pipeline = pipeline
    logger.info("NIRMAN AI started. VLM=%s Blender=%s",
                settings.vlm_provider.value, settings.blender_execution_mode.value)
    yield
    await memory.close()
    logger.info("NIRMAN AI shut down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="NIRMAN AI",
        description=(
            "Graph-guided, feedback-driven 3D building generation "
            "from real-world photographs."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow all origins in development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(router, prefix="/api/v1")

    # Serve GLTF / static outputs
    outputs_dir = Path(get_settings().output_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")

    # Serve frontend (if built)
    frontend_dir = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
