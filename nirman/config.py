"""
NIRMAN AI — Settings
Reads all configuration from environment variables / .env file.
"""
from __future__ import annotations
from enum import Enum
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class VLMProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"


class BlenderMode(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"


class Settings(BaseSettings):
    # VLM
    vlm_provider: VLMProvider = VLMProvider.GEMINI
    gemini_api_key: str = ""
    openai_api_key: str = ""

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "nirman_ai"

    # Blender
    blender_executable: str = "/usr/bin/blender"
    blender_execution_mode: BlenderMode = BlenderMode.DOCKER
    docker_image: str = "nirman-blender:latest"
    docker_timeout: int = 300

    # Generation
    generation_candidates: int = 3
    max_retries: int = 3
    max_correction_attempts: int = 2

    # Paths
    output_dir: str = "./outputs"
    log_level: str = "INFO"

    # Verification thresholds
    min_door_width: float = 0.8
    min_door_height: float = 2.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
