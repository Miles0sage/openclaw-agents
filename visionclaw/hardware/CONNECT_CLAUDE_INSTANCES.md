# Connecting Claude Code Instances — VPS ↔ GPU Computer

## Architecture

```
┌──────────────────────┐         ┌──────────────────────────┐
│  VPS (<your-vps-ip>) │         │  YOUR GPU PC (home)      │
│                      │         │                          │
│  OpenClaw Gateway    │◄═══════►│  GPU Worker (port 7890)  │
│  Claude Code (tmux)  │  Cloud  │  Claude Code             │
│  75+ AI tools        │  flare  │  Blender                 │
│  Gateway WS/API      │  Tunnel │  NVIDIA GPU              │
│                      │         │  Whisper / Moondream      │
└──────────────────────┘         └──────────────────────────┘
```

The VPS Claude sends tasks to your GPU PC. Your GPU PC does the heavy work
(rendering, local AI, Blender) and sends results back. Connected via
Cloudflare Tunnel — no port forwarding, no static IP needed.

## Setup — GPU Computer (Your PC)

### Step 1: Install prerequisites

```bash
# Python
pip install fastapi uvicorn httpx

# Claude Code (if not installed)
npm install -g @anthropic-ai/claude-code

# Blender (for 3D model work)
# Windows: Download from blender.org
# Linux: sudo apt install blender
# Mac: brew install blender

# Cloudflare Tunnel
# Windows: Download cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
# Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared
# Mac: brew install cloudflare/cloudflare/cloudflared
```

### Step 2: Set a secret key

```bash
# Pick a secret (same on both VPS and GPU PC)
export WORKER_SECRET="your-secret-key-here"
```

### Step 3: Start the GPU worker

```bash
cd /path/to/openclaw/visionclaw/hardware
python gpu_worker.py
```

You'll see:

```
╔══════════════════════════════════════╗
║  VisionClaw GPU Worker v0.1.0        ║
║  Listening on http://0.0.0.0:7890    ║
╚══════════════════════════════════════╝
```

### Step 4: Create Cloudflare Tunnel

```bash
# Quick tunnel (temporary URL, good for testing)
cloudflared tunnel --url http://localhost:7890

# You'll get a URL like: https://some-random-words.trycloudflare.com
# Copy this URL — you'll need it on the VPS
```

For a permanent tunnel (survives reboots):

```bash
cloudflared tunnel login
cloudflared tunnel create gpu-worker
cloudflared tunnel route dns gpu-worker gpu<your-domain>
cloudflared tunnel run gpu-worker
```

## Setup — VPS (OpenClaw Gateway)

### Step 5: Save the tunnel URL

```bash
# On the VPS, set the GPU worker URL
export GPU_WORKER_URL="https://some-random-words.trycloudflare.com"
export WORKER_SECRET="your-secret-key-here"  # same as GPU PC
```

### Step 6: Test the connection

```bash
# From VPS, ping the GPU worker
curl -s $GPU_WORKER_URL/health | python3 -m json.tool
```

Should return:

```json
{
  "status": "ok",
  "gpu_available": true,
  "gpu_info": "NVIDIA GeForce RTX 3080, 10240 MiB, 8192 MiB",
  "timestamp": 1709420000
}
```

### Step 7: Send tasks from VPS to GPU PC

```bash
# Run a shell command on your GPU PC
curl -X POST $GPU_WORKER_URL/shell \
  -H "Authorization: Bearer $WORKER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"command": "nvidia-smi"}'

# Run Blender on your GPU PC
curl -X POST $GPU_WORKER_URL/blender \
  -H "Authorization: Bearer $WORKER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"script": "import bpy; bpy.ops.mesh.primitive_cube_add(); bpy.ops.export_mesh.stl(filepath=OUTPUT_PATH)"}'

# Run Claude Code on your GPU PC
curl -X POST $GPU_WORKER_URL/claude \
  -H "Authorization: Bearer $WORKER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "what GPU is available on this machine?"}'

# Run local Whisper on your GPU PC
curl -X POST $GPU_WORKER_URL/inference \
  -H "Authorization: Bearer $WORKER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"model": "whisper", "input_data": "<base64 wav audio>"}'
```

## What You Can Do With This

| Task                   | Where it runs | Why                              |
| ---------------------- | ------------- | -------------------------------- |
| Blender 3D rendering   | GPU PC        | Needs GPU for fast renders       |
| Generate STL files     | GPU PC        | Blender Python scripts           |
| Local Whisper STT      | GPU PC        | Free, no API costs, fast on GPU  |
| Local Moondream vision | GPU PC        | Free local vision AI             |
| Claude Code tasks      | GPU PC        | Separate instance, parallel work |
| Web scraping           | VPS           | Better uptime, static IP         |
| Gateway/API            | VPS           | Always-on server                 |
| AI API calls           | VPS           | API keys stored on VPS           |

## How VPS Claude Calls GPU Claude

The VPS Claude Code instance can call your GPU PC's Claude Code:

```python
import httpx

# From gateway.py or any VPS script
async def ask_gpu_claude(prompt: str):
    """Send a task to the Claude Code instance on the GPU PC."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GPU_WORKER_URL}/claude",
            headers={"Authorization": f"Bearer {WORKER_SECRET}"},
            json={
                "prompt": prompt,
                "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                "max_turns": 10
            },
            timeout=600  # 10 min
        )
        return resp.json()

# Example: Have GPU Claude generate and export a Blender model
result = await ask_gpu_claude(
    "Open Blender via Python, run the VisionClaw frame generator script, "
    "export each piece as STL, and tell me the file paths."
)
```

## Security Notes

- The `WORKER_SECRET` authenticates requests — change it from the default
- Cloudflare Tunnel encrypts all traffic (HTTPS)
- The GPU worker only accepts commands from authenticated requests
- No ports need to be opened on your home router
- If you're paranoid: add IP allowlisting in gpu_worker.py
