"""
VisionClaw GPU Worker — Runs on Miles' GPU Computer
=====================================================

This lightweight FastAPI server runs on your GPU PC at home.
The VPS OpenClaw gateway sends heavy tasks here (Blender rendering,
local AI inference, etc.) and gets results back.

Connection: VPS → Cloudflare Tunnel → Your GPU PC

Setup:
  1. Install: pip install fastapi uvicorn httpx
  2. Install Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
  3. Run: python gpu_worker.py
  4. Create tunnel: cloudflared tunnel --url http://localhost:7890
  5. Copy the tunnel URL and set it on the VPS

The VPS Claude Code instance can then call your GPU PC for:
  - Blender renders (generate STL, render previews)
  - Local AI inference (Whisper, Moondream, LLaMA)
  - Heavy computation (video processing, etc.)
  - Running Claude Code commands on your local machine
"""

import os
import json
import subprocess
import asyncio
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="VisionClaw GPU Worker", version="0.1.0")

# Simple shared secret for auth
WORKER_SECRET = os.getenv("WORKER_SECRET", "change-this-secret-key")

# ═══════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════

def verify_token(authorization: str = Header(None)):
    if not authorization or authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Invalid token")

# ═══════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════

class ShellRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout: int = 120

class BlenderRequest(BaseModel):
    script: str  # Python script to run in Blender
    output_format: str = "stl"  # stl, png, obj
    output_name: str = "output"

class ClaudeRequest(BaseModel):
    prompt: str
    allowed_tools: list[str] = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    max_turns: int = 10

class InferenceRequest(BaseModel):
    model: str  # whisper, moondream, llama, etc.
    input_data: str  # base64 audio/image or text
    params: dict = {}

# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    """Health check — VPS pings this to verify GPU worker is alive."""
    import shutil
    gpu_available = shutil.which("nvidia-smi") is not None
    gpu_info = None
    if gpu_available:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            gpu_info = result.stdout.strip()
        except Exception:
            pass

    return {
        "status": "ok",
        "gpu_available": gpu_available,
        "gpu_info": gpu_info,
        "timestamp": time.time()
    }


@app.post("/shell")
async def run_shell(req: ShellRequest, authorization: str = Header(None)):
    """Run a shell command on the GPU PC."""
    verify_token(authorization)

    try:
        result = subprocess.run(
            req.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=req.timeout,
            cwd=req.cwd
        )
        return {
            "stdout": result.stdout[-5000:],  # last 5KB
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "stdout": "", "stderr": "Command timed out"}


@app.post("/blender")
async def run_blender(req: BlenderRequest, authorization: str = Header(None)):
    """Run a Blender Python script and return the output file."""
    verify_token(authorization)

    import tempfile
    import base64

    # Write script to temp file
    script_path = Path(tempfile.mktemp(suffix=".py"))
    output_path = Path(tempfile.mktemp(suffix=f".{req.output_format}"))

    # Inject output path into script
    full_script = f'OUTPUT_PATH = "{output_path}"\n' + req.script
    script_path.write_text(full_script)

    try:
        result = subprocess.run(
            ["blender", "--background", "--python", str(script_path)],
            capture_output=True,
            text=True,
            timeout=300  # 5 min max
        )

        if output_path.exists():
            file_data = base64.b64encode(output_path.read_bytes()).decode()
            return {
                "status": "ok",
                "output_file": file_data,
                "output_format": req.output_format,
                "size_bytes": output_path.stat().st_size,
                "blender_log": result.stdout[-2000:]
            }
        else:
            return {
                "status": "error",
                "error": "No output file generated",
                "blender_log": result.stdout[-2000:],
                "blender_err": result.stderr[-2000:]
            }
    finally:
        script_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


@app.post("/claude")
async def run_claude(req: ClaudeRequest, authorization: str = Header(None)):
    """Run a Claude Code command on the GPU PC and return output."""
    verify_token(authorization)

    tools = ",".join(req.allowed_tools)
    cmd = [
        "claude",
        "--print",
        "--allowedTools", tools,
        "--max-turns", str(req.max_turns),
        "-p", req.prompt
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
            env={**os.environ, "DISABLE_INTERACTIVITY": "1"}
        )
        return {
            "status": "ok",
            "output": result.stdout[-10000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Claude Code timed out after 10 minutes"}


@app.post("/inference")
async def run_inference(req: InferenceRequest, authorization: str = Header(None)):
    """Run local AI inference on GPU (Whisper, Moondream, etc.)."""
    verify_token(authorization)

    import base64
    import tempfile

    if req.model == "whisper":
        # Local Whisper STT
        audio_bytes = base64.b64decode(req.input_data)
        audio_path = Path(tempfile.mktemp(suffix=".wav"))
        audio_path.write_bytes(audio_bytes)

        try:
            result = subprocess.run(
                ["whisper", str(audio_path), "--model", "base", "--output_format", "json"],
                capture_output=True, text=True, timeout=60
            )
            return {"status": "ok", "text": result.stdout, "model": "whisper-base"}
        finally:
            audio_path.unlink(missing_ok=True)

    elif req.model == "moondream":
        # Local Moondream vision via Ollama
        result = subprocess.run(
            ["ollama", "run", "moondream",
             json.dumps({"prompt": req.params.get("prompt", "Describe this image"),
                         "images": [req.input_data]})],
            capture_output=True, text=True, timeout=60
        )
        return {"status": "ok", "text": result.stdout, "model": "moondream"}

    else:
        # Generic Ollama model
        result = subprocess.run(
            ["ollama", "run", req.model, req.input_data],
            capture_output=True, text=True, timeout=120
        )
        return {"status": "ok", "text": result.stdout, "model": req.model}


# ═══════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("\n╔══════════════════════════════════════╗")
    print("║  VisionClaw GPU Worker v0.1.0        ║")
    print("║  Listening on http://0.0.0.0:7890    ║")
    print("╚══════════════════════════════════════╝\n")
    print("Next: Run cloudflared tunnel to expose this to your VPS")
    print("  cloudflared tunnel --url http://localhost:7890\n")
    uvicorn.run(app, host="0.0.0.0", port=7890)
