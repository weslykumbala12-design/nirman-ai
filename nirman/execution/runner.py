"""
NIRMAN AI — Blender Execution Runner
Executes generated Blender Python scripts in a sandboxed environment.
Supports both local subprocess and Docker-containerised execution.
"""
from __future__ import annotations
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success:        bool
    stdout:         str
    stderr:         str
    exit_code:      int
    execution_time_s: float
    gltf_path:      Optional[str] = None
    blend_path:     Optional[str] = None
    error_message:  Optional[str] = None
    error_detail:   Optional[dict] = None


def _parse_output(stdout: str) -> tuple[bool, Optional[dict]]:
    """Detect NIRMAN_SUCCESS / NIRMAN_ERROR markers in stdout."""
    if "NIRMAN_SUCCESS" in stdout:
        return True, None
    for line in stdout.splitlines():
        if line.startswith("NIRMAN_ERROR:"):
            try:
                return False, json.loads(line[len("NIRMAN_ERROR:"):])
            except json.JSONDecodeError:
                return False, {"raw": line}
    return False, None


# ── Local runner ──────────────────────────────────────────────────────────────

class LocalBlenderRunner:
    """Execute Blender via subprocess on the local machine."""

    def __init__(self, blender_executable: str = "blender", timeout: int = 300) -> None:
        self.blender_executable = blender_executable
        self.timeout = timeout

    def run_script(self, script_content: str, output_dir: str) -> ExecutionResult:
        out_path   = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        script_p   = out_path / "build_script.py"
        gltf_p     = str(out_path / "building.gltf")
        blend_p    = str(out_path / "building.blend")
        script_p.write_text(script_content, encoding="utf-8")

        cmd = [self.blender_executable, "--background", "--python", str(script_p)]
        start = time.time()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            elapsed = round(time.time() - start, 2)
            ok, detail = _parse_output(res.stdout)
            return ExecutionResult(
                success=ok and res.returncode == 0,
                stdout=res.stdout, stderr=res.stderr,
                exit_code=res.returncode, execution_time_s=elapsed,
                gltf_path=gltf_p  if Path(gltf_p).exists()  else None,
                blend_path=blend_p if Path(blend_p).exists() else None,
                error_message=None if ok else "Script execution failed",
                error_detail=detail,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False, stdout="", stderr="", exit_code=-1,
                execution_time_s=round(time.time() - start, 2),
                error_message=f"Blender timed out after {self.timeout}s",
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False, stdout="", stderr="", exit_code=-1,
                execution_time_s=0.0,
                error_message=f"Blender not found: {self.blender_executable}",
            )


# ── Docker runner ─────────────────────────────────────────────────────────────

class DockerBlenderRunner:
    """Execute Blender inside a sandboxed Docker container (network disabled)."""

    def __init__(
        self,
        docker_image: str = "nirman-blender:latest",
        timeout: int = 300,
        project_root: Optional[str] = None,
    ) -> None:
        self.docker_image = docker_image
        self.timeout      = timeout
        self.project_root = project_root or str(Path(__file__).parent.parent.parent)

    def run_script(self, script_content: str, output_dir: str) -> ExecutionResult:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        script_p = out_path / "build_script.py"
        gltf_p   = str(out_path / "building.gltf")
        blend_p  = str(out_path / "building.blend")
        script_p.write_text(script_content, encoding="utf-8")

        cmd = [
            "docker", "run", "--rm",
            "--network", "none",   # sandbox: no internet
            "-v", f"{out_path.resolve()}:/workspace/output",
            "-v", f"{self.project_root}:/workspace/nirman_ai:ro",
            "-e", "PYTHONPATH=/workspace/nirman_ai",
            self.docker_image,
            "blender", "--background",
            "--python", "/workspace/output/build_script.py",
        ]
        start = time.time()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            elapsed = round(time.time() - start, 2)
            ok, detail = _parse_output(res.stdout)
            return ExecutionResult(
                success=ok and res.returncode == 0,
                stdout=res.stdout, stderr=res.stderr,
                exit_code=res.returncode, execution_time_s=elapsed,
                gltf_path=gltf_p  if Path(gltf_p).exists()  else None,
                blend_path=blend_p if Path(blend_p).exists() else None,
                error_message=None if ok else "Docker execution failed",
                error_detail=detail,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False, stdout="", stderr="", exit_code=-1,
                execution_time_s=round(time.time() - start, 2),
                error_message=f"Docker Blender timed out after {self.timeout}s",
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False, stdout="", stderr="", exit_code=-1,
                execution_time_s=0.0,
                error_message="docker not found — is Docker installed and running?",
            )


# ── Factory ───────────────────────────────────────────────────────────────────

class BlenderRunnerFactory:
    @staticmethod
    def create(mode: str, **kw) -> LocalBlenderRunner | DockerBlenderRunner:
        if mode == "local":
            return LocalBlenderRunner(
                blender_executable=kw.get("blender_executable", "blender"),
                timeout=kw.get("timeout", 300),
            )
        if mode == "docker":
            return DockerBlenderRunner(
                docker_image=kw.get("docker_image", "nirman-blender:latest"),
                timeout=kw.get("timeout", 300),
                project_root=kw.get("project_root"),
            )
        raise ValueError(f"Unknown Blender mode '{mode}'. Use 'local' or 'docker'.")
