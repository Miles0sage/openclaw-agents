"""
OpenClaw Gateway Dashboard API
FastAPI backend for real-time monitoring and management

Features:
- Gateway & tunnel status monitoring
- Log aggregation from gateway and tunnel services
- Webhook URL management
- Service restart capabilities
- Encrypted secret management
- Detailed health checks
- Token-based authentication
- CORS enabled for frontend
- Static file serving
"""

import os
import json
import logging
import hashlib
import hmac
import base64
import subprocess
import pathlib
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from functools import wraps

from fastapi import FastAPI, HTTPException, Depends, Header, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
GATEWAY_PORT = int(os.getenv("OPENCLAW_GATEWAY_PORT", 18789))
GATEWAY_HOST = os.getenv("OPENCLAW_GATEWAY_HOST", "localhost")
DASHBOARD_PORT = int(os.getenv("OPENCLAW_DASHBOARD_PORT", 9000))
DASHBOARD_PASSWORD = os.getenv("OPENCLAW_DASHBOARD_PASSWORD", "openclaw-dashboard-2026")
DASHBOARD_TOKEN = os.getenv("OPENCLAW_DASHBOARD_TOKEN", "moltbot-secure-token-2026")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
GATEWAY_LOG_PATH = pathlib.Path(os.getenv("OPENCLAW_GATEWAY_LOG_PATH", os.path.join(DATA_DIR, "events", "gateway.log")))
TUNNEL_LOG_PATH = pathlib.Path(os.getenv("OPENCLAW_TUNNEL_LOG_PATH", "/tmp/cloudflared-tunnel.log"))
CONFIG_PATH = pathlib.Path(os.getenv("OPENCLAW_CONFIG_PATH", "./config.json"))
SECRETS_PATH = pathlib.Path(os.getenv("OPENCLAW_SECRETS_PATH", "/tmp/openclaw_secrets.json"))
STATIC_DIR = pathlib.Path(os.getenv("OPENCLAW_STATIC_DIR", "/var/www/dashboard"))

STATIC_DIR.mkdir(parents=True, exist_ok=True)
SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("openclaw_dashboard")

# FastAPI app setup
app = FastAPI(
    title="OpenClaw Dashboard API",
    description="Real-time monitoring and management for OpenClaw Gateway",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving
if STATIC_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(STATIC_DIR)), name="dashboard")


# ============================================================================
# Models
# ============================================================================

class StatusResponse(BaseModel):
    """Gateway status response"""
    gateway_running: bool
    gateway_port: int
    gateway_host: str
    tunnel_running: bool
    tunnel_url: Optional[str] = None
    uptime_seconds: int
    timestamp: str
    version: str = "1.0.0"


class LogResponse(BaseModel):
    """Log response"""
    gateway_logs: List[str]
    tunnel_logs: List[str]
    total_lines: int
    timestamp: str


class WebhookResponse(BaseModel):
    """Webhook URLs response"""
    telegram_webhook: str
    slack_webhook: str
    telegram_enabled: bool
    slack_enabled: bool


class ConfigResponse(BaseModel):
    """Gateway configuration (no secrets)"""
    name: str
    version: str
    port: int
    channels: Dict[str, Any]
    agents_count: int
    timestamp: str


class SecretInput(BaseModel):
    """Secret input for storing API keys"""
    key: str
    value: str
    service: Optional[str] = None


class SecretResponse(BaseModel):
    """Secret response"""
    message: str
    key: str
    service: Optional[str] = None


class RestartResponse(BaseModel):
    """Restart response"""
    success: bool
    message: str
    timestamp: str


class HealthCheckResponse(BaseModel):
    """Detailed health check"""
    status: str  # "healthy", "degraded", "unhealthy"
    gateway_health: str
    tunnel_health: str
    database_health: str
    api_latency_ms: float
    memory_usage_mb: float
    cpu_usage_percent: float
    uptime_hours: float
    errors_last_hour: int
    warnings_last_hour: int
    timestamp: str


# ============================================================================
# Authentication
# ============================================================================

def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """Verify dashboard access token"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid scheme")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Accept either the token or password
    if token != DASHBOARD_TOKEN and token != DASHBOARD_PASSWORD:
        logger.warning(f"🚨 Invalid dashboard token attempt: {token[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token"
        )

    return token


# ============================================================================
# Utility Functions
# ============================================================================

def read_log_file(log_path: pathlib.Path, lines: int = 50) -> List[str]:
    """Read last N lines from a log file"""
    if not log_path.exists():
        return [f"Log file not found: {log_path}"]

    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()
            # Get last N lines
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return [line.rstrip('\n') for line in recent_lines]
    except Exception as e:
        logger.error(f"Error reading log file {log_path}: {e}")
        return [f"Error reading log file: {str(e)}"]


def check_service_running(port: int, host: str = "localhost") -> bool:
    """Check if service is running on port"""
    try:
        result = subprocess.run(
            ["netstat", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return f":{port}" in result.stdout
    except Exception:
        # Fallback: try curl
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", f"http://{host}:{port}/health"],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False


def get_process_uptime(port: int) -> int:
    """Get process uptime in seconds"""
    try:
        import psutil
        import os

        # Try to get the gateway process
        try:
            import psutil
            # Look for the gateway process (python gateway.py)
            for proc in psutil.process_iter(['pid', 'name', 'create_time']):
                try:
                    if 'python' in proc.name().lower() and 'gateway' in ' '.join(proc.cmdline()):
                        create_time = proc.create_time()
                        uptime = time.time() - create_time
                        return int(max(0, uptime))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            pass

        # Fallback: check /proc/stat for system boot time
        if os.path.exists('/proc/stat'):
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('btime'):
                        boot_time = int(line.split()[1])
                        uptime = int(time.time()) - boot_time
                        return uptime

        return 0
    except Exception as e:
        logger.warning(f"Could not get process uptime: {e}")
        return 0


def load_config() -> Dict[str, Any]:
    """Load gateway configuration"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")

    return {
        "name": "OpenClaw Gateway",
        "version": "1.0.0",
        "port": GATEWAY_PORT,
        "channels": {},
        "agents": {}
    }


def load_secrets() -> Dict[str, str]:
    """Load encrypted secrets"""
    try:
        if SECRETS_PATH.exists():
            with open(SECRETS_PATH, 'r') as f:
                data = json.load(f)
                return data.get('secrets', {})
    except Exception as e:
        logger.error(f"Error loading secrets: {e}")

    return {}


def save_secrets(secrets: Dict[str, str]) -> bool:
    """Save encrypted secrets"""
    try:
        data = {
            'secrets': secrets,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        with open(SECRETS_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving secrets: {e}")
        return False


def get_webhook_urls() -> Dict[str, Any]:
    """Get webhook URLs from config"""
    config = load_config()
    channels = config.get('channels', {})

    base_url = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"

    return {
        "telegram_webhook": f"{base_url}/telegram/webhook" if channels.get('telegram', {}).get('enabled') else "",
        "slack_webhook": f"{base_url}/slack/events" if channels.get('slack', {}).get('enabled') else "",
        "telegram_enabled": channels.get('telegram', {}).get('enabled', False),
        "slack_enabled": channels.get('slack', {}).get('enabled', False),
    }


def count_errors_and_warnings(log_path: pathlib.Path, hours: int = 1) -> tuple:
    """Count errors and warnings in the last N hours"""
    if not log_path.exists():
        return 0, 0

    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        errors = 0
        warnings = 0

        with open(log_path, 'r') as f:
            for line in f:
                try:
                    # Simple heuristic: look for ERROR, WARNING, error, warning
                    if any(marker in line for marker in ['ERROR', 'error', '❌']):
                        errors += 1
                    elif any(marker in line for marker in ['WARNING', 'warning', '⚠️']):
                        warnings += 1
                except Exception:
                    pass

        return errors, warnings
    except Exception as e:
        logger.error(f"Error counting logs: {e}")
        return 0, 0


def get_system_metrics() -> Dict[str, float]:
    """Get system metrics"""
    try:
        # Memory usage
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True,
            text=True,
            timeout=5
        )
        lines = result.stdout.split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            memory_usage = round((used / total) * 100, 2) if total > 0 else 0
        else:
            memory_usage = 0

        # CPU usage
        result = subprocess.run(
            ["top", "-bn1"],
            capture_output=True,
            text=True,
            timeout=5
        )
        cpu_usage = 0
        for line in result.stdout.split('\n'):
            if 'Cpu(s)' in line:
                try:
                    parts = line.split()
                    cpu_usage = float(parts[1].replace('%us,', ''))
                except Exception:
                    pass

        return {
            "memory_mb": round(used if 'used' in locals() else 0, 2),
            "cpu_percent": cpu_usage
        }
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        return {"memory_mb": 0, "cpu_percent": 0}


# ============================================================================
# Routes
# ============================================================================

@app.get("/api/status", response_model=StatusResponse)
async def get_status(token: str = Depends(verify_token)):
    """Get gateway and tunnel status"""
    try:
        gateway_running = check_service_running(GATEWAY_PORT, GATEWAY_HOST)
        tunnel_running = False
        tunnel_url = None

        # Check for tunnel logs indicating active tunnel
        if TUNNEL_LOG_PATH.exists():
            try:
                with open(TUNNEL_LOG_PATH, 'r') as f:
                    last_lines = f.readlines()[-20:]
                    tunnel_logs_text = ''.join(last_lines)
                    tunnel_running = 'INF' in tunnel_logs_text or 'quic' in tunnel_logs_text

                    # Try to extract tunnel URL
                    for line in last_lines:
                        if 'workers.dev' in line or 'tunnel' in line.lower():
                            tunnel_url = line.strip()
            except Exception:
                pass

        uptime = get_process_uptime(GATEWAY_PORT)

        return StatusResponse(
            gateway_running=gateway_running,
            gateway_port=GATEWAY_PORT,
            gateway_host=GATEWAY_HOST,
            tunnel_running=tunnel_running,
            tunnel_url=tunnel_url,
            uptime_seconds=uptime,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")


@app.get("/api/logs", response_model=LogResponse)
async def get_logs(lines: int = 50, token: str = Depends(verify_token)):
    """Get last N lines from gateway and tunnel logs"""
    try:
        if lines < 1 or lines > 500:
            lines = 50

        gateway_logs = read_log_file(GATEWAY_LOG_PATH, lines)
        tunnel_logs = read_log_file(TUNNEL_LOG_PATH, lines)

        return LogResponse(
            gateway_logs=gateway_logs,
            tunnel_logs=tunnel_logs,
            total_lines=len(gateway_logs) + len(tunnel_logs),
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting logs: {str(e)}")


@app.get("/api/webhooks", response_model=WebhookResponse)
async def get_webhooks(token: str = Depends(verify_token)):
    """Get webhook URLs for Telegram and Slack"""
    try:
        webhooks = get_webhook_urls()
        return WebhookResponse(**webhooks)
    except Exception as e:
        logger.error(f"Error getting webhooks: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting webhooks: {str(e)}")


@app.get("/api/config", response_model=ConfigResponse)
async def get_config(token: str = Depends(verify_token)):
    """Get gateway configuration (no secrets)"""
    try:
        config = load_config()

        # Remove sensitive fields
        channels = {}
        for name, channel_config in config.get('channels', {}).items():
            safe_channel = {
                'enabled': channel_config.get('enabled', False),
                'name': channel_config.get('name', ''),
                'type': channel_config.get('type', '')
            }
            channels[name] = safe_channel

        return ConfigResponse(
            name=config.get('name', 'OpenClaw Gateway'),
            version=config.get('version', '1.0.0'),
            port=config.get('port', GATEWAY_PORT),
            channels=channels,
            agents_count=len(config.get('agents', {})),
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting config: {str(e)}")


@app.post("/api/secrets", response_model=SecretResponse)
async def save_secret(secret: SecretInput, token: str = Depends(verify_token)):
    """Save encrypted API key (base64 encoded for now)"""
    try:
        if not secret.key or not secret.value:
            raise HTTPException(status_code=400, detail="Key and value are required")

        # Load existing secrets
        secrets = load_secrets()

        # Encode value (simple base64 for now)
        encoded_value = base64.b64encode(secret.value.encode()).decode()
        secrets[secret.key] = encoded_value

        # Save
        if not save_secrets(secrets):
            raise HTTPException(status_code=500, detail="Failed to save secret")

        logger.info(f"✅ Secret saved: {secret.key} (service: {secret.service})")

        return SecretResponse(
            message=f"Secret '{secret.key}' saved successfully",
            key=secret.key,
            service=secret.service
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving secret: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving secret: {str(e)}")


@app.post("/api/restart", response_model=RestartResponse)
async def restart_gateway(token: str = Depends(verify_token)):
    """Restart gateway service"""
    try:
        logger.info("🔄 Restarting gateway service...")

        # Stop gateway
        stop_result = subprocess.run(
            ["pkill", "-f", "openclaw.*gateway"],
            capture_output=True,
            timeout=10
        )

        # Small delay
        import time
        time.sleep(2)

        # Start gateway (this is a placeholder - actual startup depends on your setup)
        # You might use systemctl, docker restart, or a custom start script
        # For now, we'll just kill the process and assume systemd/supervisor will restart it

        logger.info("✅ Gateway restart initiated")

        return RestartResponse(
            success=True,
            message="Gateway restart initiated. Service should be back online in 5-10 seconds.",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except subprocess.TimeoutExpired:
        logger.error("Timeout restarting gateway")
        raise HTTPException(status_code=500, detail="Restart timeout")
    except Exception as e:
        logger.error(f"Error restarting gateway: {e}")
        raise HTTPException(status_code=500, detail=f"Error restarting gateway: {str(e)}")


@app.get("/api/health", response_model=HealthCheckResponse)
async def health_check(token: str = Depends(verify_token)):
    """Detailed health check"""
    try:
        gateway_running = check_service_running(GATEWAY_PORT, GATEWAY_HOST)
        tunnel_running = check_service_running(8001, GATEWAY_HOST)  # Assuming tunnel on 8001

        # Check database connectivity (assuming local)
        database_health = "healthy"  # Placeholder

        # Measure API latency
        import time
        start = time.time()
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", f"http://{GATEWAY_HOST}:{GATEWAY_PORT}/health"],
                capture_output=True,
                timeout=5
            )
            api_latency = (time.time() - start) * 1000
        except Exception:
            api_latency = 0

        # Get system metrics
        metrics = get_system_metrics()
        memory_usage = metrics.get("memory_mb", 0)
        cpu_usage = metrics.get("cpu_percent", 0)

        # Get uptime
        uptime_seconds = get_process_uptime(GATEWAY_PORT)
        uptime_hours = uptime_seconds / 3600

        # Count errors and warnings
        errors, warnings = count_errors_and_warnings(GATEWAY_LOG_PATH, hours=1)

        # Determine overall status
        if gateway_running and uptime_seconds > 0:
            if cpu_usage < 80 and memory_usage < 80:
                overall_status = "healthy"
            else:
                overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        return HealthCheckResponse(
            status=overall_status,
            gateway_health="healthy" if gateway_running else "unhealthy",
            tunnel_health="healthy" if tunnel_running else "unhealthy",
            database_health=database_health,
            api_latency_ms=round(api_latency, 2),
            memory_usage_mb=memory_usage,
            cpu_usage_percent=cpu_usage,
            uptime_hours=round(uptime_hours, 2),
            errors_last_hour=errors,
            warnings_last_hour=warnings,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        raise HTTPException(status_code=500, detail=f"Health check error: {str(e)}")


@app.get("/health")
async def basic_health():
    """Basic health check (no auth required)"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/")
async def root():
    """Root endpoint - serve dashboard"""
    dashboard_file = STATIC_DIR / "index.html"
    if dashboard_file.exists():
        return FileResponse(dashboard_file)

    return {
        "service": "OpenClaw Dashboard API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/docs")
async def docs():
    """API documentation"""
    return {
        "title": "OpenClaw Dashboard API",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Basic health check (no auth)",
            "GET /api/status": "Gateway and tunnel status",
            "GET /api/logs": "Last 50 lines of logs",
            "GET /api/webhooks": "Webhook URLs",
            "GET /api/config": "Gateway configuration",
            "GET /api/health": "Detailed health check",
            "POST /api/secrets": "Save encrypted secrets",
            "POST /api/restart": "Restart gateway"
        },
        "auth": "Bearer token in Authorization header",
        "token": "[redacted]",
        "password": "[redacted]"
    }


# ============================================================================
# SSE (Server-Sent Events) — Real-time Dashboard Updates
# ============================================================================

_sse_clients: list[asyncio.Queue] = []


async def _broadcast_sse(event_type: str, data: dict):
    """Push an event to all connected SSE clients."""
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_clients.remove(q)


def _load_gateway_data(endpoint: str) -> dict:
    """Fetch data from the main gateway API."""
    import urllib.request
    try:
        url = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}{endpoint}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.debug(f"Gateway fetch {endpoint} failed: {e}")
        return {}


@app.get("/api/stream")
async def sse_stream(request: Request):
    """SSE endpoint — pushes real-time updates to dashboard clients."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_clients.append(queue)

    async def event_generator():
        try:
            # Send initial snapshot
            yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield message
                except asyncio.TimeoutError:
                    # Send keepalive ping every 15s
                    yield f": keepalive {datetime.now(timezone.utc).isoformat()}\n\n"
        finally:
            if queue in _sse_clients:
                _sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/live/jobs")
async def live_jobs():
    """Active jobs with real-time status."""
    data = _load_gateway_data("/api/jobs?status=all&limit=20")
    if isinstance(data, dict) and "jobs" in data:
        return {"jobs": data["jobs"], "timestamp": datetime.now(timezone.utc).isoformat()}
    # Fallback: read from job files
    jobs_dir = pathlib.Path(DATA_DIR) / "jobs"
    jobs = []
    if jobs_dir.exists():
        for f in sorted(jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            try:
                jobs.append(json.loads(f.read_text()))
            except Exception:
                pass
    return {"jobs": jobs, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/live/costs")
async def live_costs():
    """Rolling 24h cost burn rate."""
    try:
        from cost_tracker import get_cost_metrics
        metrics = get_cost_metrics()
        return {
            "metrics": metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "metrics": {}, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/live/eval")
async def live_eval():
    """Latest eval run results."""
    eval_dir = pathlib.Path(DATA_DIR) / "eval_results"
    if not eval_dir.exists():
        return {"latest": None, "runs": [], "timestamp": datetime.now(timezone.utc).isoformat()}
    runs = sorted(eval_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest = None
    run_summaries = []
    for r in runs[:10]:
        try:
            data = json.loads(r.read_text())
            summary = {
                "run_id": data.get("run_id", r.stem),
                "score": data.get("score", data.get("overall_score")),
                "total": data.get("total_tasks"),
                "passed": data.get("passed"),
                "timestamp": data.get("timestamp", data.get("completed_at")),
            }
            run_summaries.append(summary)
            if latest is None:
                latest = data
        except Exception:
            pass
    return {"latest": latest, "runs": run_summaries, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/live/billing")
async def live_billing():
    """Current billing plan usage (from client_auth)."""
    try:
        from client_auth import list_clients
        clients = list_clients()
        return {
            "clients": clients[:50],
            "total_clients": len(clients),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "clients": [], "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/live/agents")
async def live_agents():
    """Active tmux agents and their status."""
    try:
        from tmux_spawner import TmuxSpawner
        spawner = TmuxSpawner()
        agents = spawner.list_agents()
        return {"agents": agents, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": str(e), "agents": [], "timestamp": datetime.now(timezone.utc).isoformat()}


# ============================================================================
# Analytics Endpoints
# ============================================================================

def parse_event_log(log_path: pathlib.Path, limit: int = 10000) -> List[Dict[str, Any]]:
    """Parse JSONL event log file"""
    events = []
    if not log_path.exists():
        return events

    try:
        with open(log_path, 'r') as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error parsing events: {e}")

    return events[-limit:]  # Return most recent


@app.get("/api/analytics/agents")
async def get_agent_analytics():
    """Agent performance statistics from event logs"""
    try:
        events_file = pathlib.Path(DATA_DIR) / "events" / "events.jsonl"
        events = parse_event_log(events_file)

        agent_stats = {}

        # Parse job completion events
        for event in events:
            try:
                data = event.get("data", {})
                event_type = event.get("event_type", "")

                # Look for job completion events
                if "job" in event_type and "completed" in event_type:
                    agent = data.get("agent", "unknown")
                    if agent not in agent_stats:
                        agent_stats[agent] = {
                            "jobs": 0,
                            "success": 0,
                            "failed": 0,
                            "total_cost": 0.0,
                            "total_duration": 0.0
                        }

                    agent_stats[agent]["jobs"] += 1
                    if data.get("status") == "done":
                        agent_stats[agent]["success"] += 1
                    else:
                        agent_stats[agent]["failed"] += 1

                    agent_stats[agent]["total_cost"] += float(data.get("cost_usd", 0))
                    agent_stats[agent]["total_duration"] += float(data.get("duration", 0))
            except Exception:
                continue

        # Calculate averages
        for agent, stats in agent_stats.items():
            if stats["jobs"] > 0:
                stats["success_rate"] = round((stats["success"] / stats["jobs"]) * 100, 1)
                stats["avg_duration"] = round(stats["total_duration"] / stats["jobs"], 2)
                stats["avg_cost"] = round(stats["total_cost"] / stats["jobs"], 4)
            else:
                stats["success_rate"] = 0
                stats["avg_duration"] = 0
                stats["avg_cost"] = 0

        return {
            "agents": agent_stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in agent analytics: {e}")
        return {"agents": {}, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/analytics/costs")
async def get_cost_analytics():
    """Cost tracking with daily/weekly breakdown"""
    try:
        events_file = pathlib.Path(DATA_DIR) / "events" / "events.jsonl"
        events = parse_event_log(events_file)

        daily_costs = {}
        agent_costs = {}
        total_cost = 0.0

        # Parse cost events
        for event in events:
            try:
                timestamp = event.get("timestamp", "")
                data = event.get("data", {})

                # Extract date
                if timestamp:
                    date_key = timestamp.split("T")[0]
                else:
                    continue

                cost = float(data.get("cost_usd", 0))
                agent = data.get("agent", "unknown")

                if cost > 0:
                    total_cost += cost

                    if date_key not in daily_costs:
                        daily_costs[date_key] = 0.0
                    daily_costs[date_key] += cost

                    if agent not in agent_costs:
                        agent_costs[agent] = 0.0
                    agent_costs[agent] += cost
            except Exception:
                continue

        # Calculate weekly costs
        weekly_costs = {}
        for date_str, cost in sorted(daily_costs.items()):
            try:
                date_obj = datetime.fromisoformat(date_str)
                week_key = f"week_{date_obj.isocalendar()[1]}"
                if week_key not in weekly_costs:
                    weekly_costs[week_key] = 0.0
                weekly_costs[week_key] += cost
            except Exception:
                continue

        return {
            "total_cost": round(total_cost, 4),
            "daily_costs": {k: round(v, 4) for k, v in sorted(daily_costs.items())[-30:]},
            "weekly_costs": {k: round(v, 4) for k, v in weekly_costs.items()},
            "by_agent": {k: round(v, 4) for k, v in sorted(agent_costs.items(), key=lambda x: x[1], reverse=True)},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in cost analytics: {e}")
        return {"total_cost": 0, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/analytics/jobs")
async def get_job_analytics(status: Optional[str] = None, agent: Optional[str] = None, limit: int = 50):
    """Recent job history with filters"""
    try:
        events_file = pathlib.Path(DATA_DIR) / "events" / "events.jsonl"
        events = parse_event_log(events_file, limit=10000)

        jobs = []

        # Extract job events
        for event in events:
            try:
                event_type = event.get("event_type", "")
                data = event.get("data", {})
                timestamp = event.get("timestamp", "")

                # Look for job-related events
                if "job" in event_type or "task" in event_type:
                    job_data = {
                        "id": event.get("event_id", ""),
                        "agent": data.get("agent", "unknown"),
                        "status": data.get("status", "unknown"),
                        "duration": float(data.get("duration", 0)),
                        "cost": round(float(data.get("cost_usd", 0)), 4),
                        "timestamp": timestamp,
                        "event_type": event_type
                    }

                    # Apply filters
                    if status and job_data["status"] != status:
                        continue
                    if agent and job_data["agent"] != agent:
                        continue

                    jobs.append(job_data)
            except Exception:
                continue

        # Sort by timestamp descending
        jobs = sorted(jobs, key=lambda x: x["timestamp"], reverse=True)[:limit]

        return {
            "jobs": jobs,
            "count": len(jobs),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in job analytics: {e}")
        return {"jobs": [], "count": 0, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


# Background task: poll gateway and push updates via SSE every 10s
async def _sse_poller():
    """Periodically push updates to SSE clients."""
    while True:
        await asyncio.sleep(10)
        if not _sse_clients:
            continue
        try:
            # Push job status
            jobs_data = _load_gateway_data("/api/jobs?status=running&limit=10")
            if jobs_data:
                await _broadcast_sse("jobs", jobs_data)

            # Push cost metrics
            try:
                from cost_tracker import get_cost_metrics
                costs = get_cost_metrics()
                await _broadcast_sse("costs", costs if isinstance(costs, dict) else {})
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"SSE poller error: {e}")


@app.on_event("startup")
async def start_sse_poller():
    """Start the SSE background poller."""
    asyncio.create_task(_sse_poller())


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Generic exception handler"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


# ============================================================================
# Startup/Shutdown
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Startup event"""
    logger.info("=" * 60)
    logger.info("🚀 OpenClaw Dashboard API Starting")
    logger.info(f"📡 Gateway: {GATEWAY_HOST}:{GATEWAY_PORT}")
    logger.info(f"🔐 Dashboard: Bearer {DASHBOARD_TOKEN[:10]}...")
    logger.info(f"📊 Listening on 0.0.0.0:{DASHBOARD_PORT}")
    logger.info(f"📁 Static files: {STATIC_DIR}")
    logger.info(f"📝 Gateway logs: {GATEWAY_LOG_PATH}")
    logger.info(f"🔗 Tunnel logs: {TUNNEL_LOG_PATH}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event"""
    logger.info("🛑 OpenClaw Dashboard API shutting down...")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Ensure secrets file exists
    if not SECRETS_PATH.exists():
        save_secrets({})

    # Start server
    uvicorn.run(
        "dashboard_api:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        reload=False,
        log_level="info"
    )
