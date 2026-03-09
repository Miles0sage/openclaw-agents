"""
Shared dependencies for all OpenClaw gateway routers.

This module centralises globals, utilities, and model-calling functions
that are used by multiple router modules.
"""

import os
import json
import asyncio
import uuid
import sys
import pathlib
import hmac
import hashlib
import time
import logging
import requests
import httpx
import anthropic
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel

# ── External module imports ─────────────────────────────────────────────
from orchestrator import Orchestrator, AgentRole
from cost_tracker import calculate_cost, log_cost_event, get_cost_log_path, get_cost_metrics, get_cost_summary
from deepseek_client import DeepseekClient
from minimax_client import MiniMaxClient
from gemini_client import GeminiClient
from response_cache import get_response_cache
from agent_tools import AGENT_TOOLS, execute_tool
from complexity_classifier import classify as classify_query, ClassificationResult, MODEL_PRICING, MODEL_ALIASES, MODEL_RATE_LIMITS
from heartbeat_monitor import HeartbeatMonitor, get_heartbeat_monitor
from agent_router import AgentRouter
from workflow_engine import WorkflowEngine
from job_manager import create_job, get_job, list_jobs, update_job_status, validate_job, JobValidationError
from autonomous_runner import get_runner
from review_cycle import ReviewCycleEngine
from output_verifier import OutputVerifier
from event_engine import get_event_engine
from proposal_engine import create_proposal, get_proposal, list_proposals
from approval_engine import auto_approve_and_execute, get_policy
from cost_gates import get_cost_gates, check_cost_budget, BudgetStatus

logger = logging.getLogger("openclaw_gateway")

# ── Config & constants ──────────────────────────────────────────────────
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
SESSIONS_DIR = pathlib.Path(os.getenv("OPENCLAW_SESSIONS_DIR", os.path.join(DATA_DIR, "sessions")))

def _apply_env_overrides(cfg: dict) -> dict:
    """Apply OPENCLAW_* environment variable overrides to config."""
    overrides = {
        "OPENCLAW_BUDGET": lambda v: cfg.setdefault("cost_gates", {}).update({"per_task_limit": float(v)}),
        "OPENCLAW_POLL_INTERVAL": lambda v: cfg.setdefault("runner", {}).update({"poll_interval": int(v)}),
        "OPENCLAW_MAX_CONCURRENT": lambda v: cfg.setdefault("runner", {}).update({"max_concurrent": int(v)}),
        "OPENCLAW_LOG_LEVEL": lambda v: cfg.setdefault("logging", {}).update({"level": v.upper()}),
    }
    for env_key, apply_fn in overrides.items():
        val = os.getenv(env_key)
        if val:
            apply_fn(val)
            logger.info(f"Config override: {env_key}={val}")
    return cfg

# Base directory (project root — one level up from routers/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load config (done once at import time)
_config_path = os.path.join(BASE_DIR, "config.json")
if not os.path.exists(_config_path):
    _config_path = "config.json"
with open(_config_path, "r") as f:
    CONFIG = json.load(f)
CONFIG = _apply_env_overrides(CONFIG)

# Slack configuration
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_REPORT_CHANNEL = os.getenv("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")

# Auth token
AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN")

# Protocol version
PROTOCOL_VERSION = 3

# Timeout settings
WS_RECEIVE_TIMEOUT = 120
WS_PING_INTERVAL = 30
WS_PING_TIMEOUT = 10

# Anthropic client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Agent Router
agent_router = AgentRouter(config_path=_config_path if os.path.exists(_config_path) else "config.json")

# Workflow Engine
workflow_engine = WorkflowEngine()

# Orchestrator (shared instance)
orchestrator = Orchestrator()

# Tasks storage for Mission Control
TASKS_FILE = pathlib.Path(os.path.join(DATA_DIR, "jobs", "tasks.json"))

# History trimming
MAX_HISTORY_MESSAGES = 40
SUMMARIZE_THRESHOLD = 30


# ── Pydantic models ────────────────────────────────────────────────────

class Message(BaseModel):
    content: str
    agent_id: Optional[str] = "pm"
    sessionKey: Optional[str] = None
    project_id: Optional[str] = None
    use_tools: Optional[bool] = None

class VisionRequest(BaseModel):
    image: str
    query: str = "describe"
    session_key: Optional[str] = None
    language: Optional[str] = None
    device_id: Optional[str] = None


# ── Inline stubs ────────────────────────────────────────────────────────

def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    return calculate_cost(model, tokens_in, tokens_out)

def load_quota_config() -> dict:
    return {"enabled": False}

def check_daily_quota(project_id: str = "default") -> tuple:
    return True, None

def check_monthly_quota(project_id: str = "default") -> tuple:
    return True, None

def check_queue_size(project_id: str = "default", queue_size: int = 0) -> tuple:
    return True, None

def check_all_quotas(project_id: str = "default", queue_size: int = 0) -> tuple:
    return True, None

def get_quota_status(project_id: str = "default") -> dict:
    return {
        "daily": {"limit": 50, "used": 0, "remaining": 50, "percent": 0},
        "monthly": {"limit": 1000, "used": 0, "remaining": 1000, "percent": 0},
    }

class _MetricsStub:
    def check_rate_limit(self, ip: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
        return True
    def record_request(self, ip: str, path: str):
        pass
    def record_agent_call(self, agent_id: str):
        pass
    def record_session(self, session_key: str):
        pass
    def get_prometheus_metrics(self) -> str:
        return "# No metrics collector\n"
    def load_from_disk(self):
        pass

metrics = _MetricsStub()

def init_metrics_collector(): pass
def get_metrics_collector(): return None
def record_metric(**kwargs): pass


# ── Memory Manager ──────────────────────────────────────────────────────

class _MemoryManagerStub:
    def __init__(self):
        self._file = os.path.join(DATA_DIR, "memories.jsonl")
        os.makedirs(os.path.dirname(self._file), exist_ok=True)
        self._sb = None

    def _get_sb(self):
        if self._sb is None:
            try:
                from supabase_client import table_insert, table_select, table_update, is_connected
                self._sb = {"insert": table_insert, "select": table_select, "update": table_update, "connected": is_connected}
            except Exception:
                self._sb = False
        return self._sb if self._sb else None

    def _use_sb(self) -> bool:
        try:
            sb = self._get_sb()
            return sb is not None and sb["connected"]()
        except Exception:
            return False

    def count(self) -> int:
        if self._use_sb():
            rows = self._get_sb()["select"]("memories", "select=id", limit=5000)
            if rows is not None:
                return len(rows)
        if not os.path.exists(self._file): return 0
        with open(self._file) as f:
            return sum(1 for line in f if line.strip())

    def get_context_for_prompt(self, persona: str, max_tokens: int = 500) -> str:
        memories = self.get_recent(limit=10)
        return "\n".join(m.get("content", "") for m in memories)[:max_tokens]

    def auto_extract_memories(self, messages: list):
        pass

    def get_recent(self, limit: int = 20) -> list:
        if self._use_sb():
            rows = self._get_sb()["select"]("memories", "order=created_at.desc", limit=limit)
            if rows is not None:
                return rows
        if not os.path.exists(self._file): return []
        memories = []
        with open(self._file) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: memories.append(json.loads(line))
                except: continue
        return sorted(memories, key=lambda m: m.get("timestamp", ""), reverse=True)[:limit]

    def get_by_tag(self, tag: str) -> list:
        if self._use_sb():
            rows = self._get_sb()["select"]("memories", f"tags=cs.{{{tag}}}&order=created_at.desc", limit=100)
            if rows is not None:
                return rows
        return [m for m in self.get_recent(limit=100) if tag in m.get("tags", [])]

    def add_memory(self, content: str, tags: list = None, source: str = "manual", importance: int = 5, remind_at: str = None) -> str:
        mem_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        if self._use_sb():
            row = {"content": content, "importance": importance, "tags": tags or [], "created_at": now}
            if remind_at:
                row["remind_at"] = remind_at
            result = self._get_sb()["insert"]("memories", row)
            if result:
                db_id = result[0].get("id", mem_id) if isinstance(result, list) else mem_id
                return str(db_id)
        record = {"id": mem_id, "content": content, "tags": tags or [], "source": source, "importance": importance, "timestamp": now}
        if remind_at:
            record["remind_at"] = remind_at
            record["reminded"] = False
        with open(self._file, "a") as f:
            f.write(json.dumps(record) + "\n")
        return mem_id

    def get_due_reminders(self) -> list:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if self._use_sb():
            rows = self._get_sb()["select"]("memories", f"remind_at=not.is.null&reminded=eq.false&remind_at=lte.{now}&order=remind_at.asc", limit=50)
            if rows is not None:
                return rows
        due = []
        for m in self.get_recent(limit=200):
            if m.get("remind_at") and not m.get("reminded", True):
                if m["remind_at"] <= now:
                    due.append(m)
        return due

    def mark_reminded(self, mem_id: str):
        if self._use_sb():
            result = self._get_sb()["update"]("memories", f"id=eq.{mem_id}", {"reminded": True})
            if result:
                return
        if not os.path.exists(self._file):
            return
        lines = []
        with open(self._file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("id") == mem_id:
                        record["reminded"] = True
                    lines.append(json.dumps(record))
                except:
                    lines.append(line)
        with open(self._file, "w") as f:
            f.write("\n".join(lines) + "\n")


_memory_manager_instance = None

def init_memory_manager():
    global _memory_manager_instance
    _memory_manager_instance = _MemoryManagerStub()
    return _memory_manager_instance

def get_memory_manager():
    return _memory_manager_instance


# ── CEO Scheduler Adapter ──────────────────────────────────────────────

from ceo_engine import CEOEngine, init_ceo_engine, get_ceo_engine
import ceo_engine as _ceo_module

class _CEOSchedulerAdapter:
    def __init__(self, ceo: CEOEngine):
        self._ceo = ceo
        self._started = False
    def start(self):
        self._started = True
    def stop(self):
        self._started = False
    def list_jobs(self) -> list:
        return list(_ceo_module.SCHEDULES.keys()) if self._started else []

_cron_scheduler_instance = None

def init_cron_scheduler():
    global _cron_scheduler_instance
    ceo = init_ceo_engine()
    _cron_scheduler_instance = _CEOSchedulerAdapter(ceo)
    return _cron_scheduler_instance

def get_cron_scheduler():
    return _cron_scheduler_instance


# ── Session Store ───────────────────────────────────────────────────────

class SessionStore:
    """Lazy-loading session store with atomic writes."""
    def __init__(self, sessions_dir):
        self._dir = pathlib.Path(sessions_dir)
        self._cache = {}

    def get(self, key: str) -> list:
        if key not in self._cache:
            safe_key = key.replace("/", "_").replace("\\", "_")
            path = self._dir / f"{safe_key}.json"
            if path.exists():
                try:
                    with open(path) as f:
                        data = json.load(f)
                        self._cache[key] = data.get("messages", [])
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to load session {key}: {e}")
                    self._cache[key] = []
            else:
                self._cache[key] = []
        return self._cache[key]

    def set(self, key: str, messages: list):
        self._cache[key] = messages
        safe_key = key.replace("/", "_").replace("\\", "_")
        path = self._dir / f"{safe_key}.json"
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump({"session_key": key, "messages": messages}, f)
            tmp.replace(path)
        except IOError as e:
            logger.error(f"Failed to save session {key}: {e}")

    def keys(self):
        disk_keys = set()
        for p in self._dir.glob("*.json"):
            disk_keys.add(p.stem)
        return list(set(self._cache.keys()) | disk_keys)

    def __len__(self):
        return len(self.keys())

    def __contains__(self, key):
        if key in self._cache:
            return True
        safe_key = key.replace("/", "_").replace("\\", "_")
        return (self._dir / f"{safe_key}.json").exists()

# Global instances (initialized in gateway.py lifespan)
session_store = SessionStore(SESSIONS_DIR)
active_connections: Dict[str, WebSocket] = {}


# ── SSE Event Stream ───────────────────────────────────────────────────

_event_log = []

def broadcast_event(event_data: dict):
    """Broadcast an event to SSE subscribers via ring buffer and emit to event engine"""
    event_data.setdefault("timestamp", datetime.now(timezone.utc).isoformat() + "Z")
    _event_log.append(event_data)
    while len(_event_log) > 200:
        _event_log.pop(0)
    event_type_raw = event_data.get("type", "")
    event_type = event_type_raw.replace("_", ".") if event_type_raw else ""
    if event_type:
        try:
            engine = get_event_engine()
            event_payload = {k: v for k, v in event_data.items() if k not in ["type", "timestamp"]}
            engine.emit(event_type, event_payload)
        except Exception as e:
            logger.warning(f"Failed to emit event {event_type} to event engine: {e}")


# ── Cost Alerts ────────────────────────────────────────────────────────

_cost_alerts_sent = {}

def send_cost_alert_if_needed():
    try:
        slack_config = CONFIG.get("slack_alerts", {})
    except NameError:
        slack_config = {}
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return
    try:
        cost_data = get_cost_metrics()
        quota_status = get_quota_status("default")
        daily_spend = cost_data.get("today_usd", 0)
        monthly_spend = cost_data.get("month_usd", 0)
        daily_limit = quota_status.get("daily", {}).get("limit", 50)
        monthly_limit = quota_status.get("monthly", {}).get("limit", 1000)
        thresholds = [80, 90, 100]
        alerts = []
        if daily_limit > 0:
            daily_pct = (daily_spend / daily_limit) * 100
            for threshold in thresholds:
                if daily_pct >= threshold:
                    key = f"daily_{threshold}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
                    if key not in _cost_alerts_sent:
                        alerts.append(f"Daily spend at ${daily_spend:.2f}/${daily_limit:.2f} ({daily_pct:.0f}%)")
                        _cost_alerts_sent[key] = time.time()
        if monthly_limit > 0:
            monthly_pct = (monthly_spend / monthly_limit) * 100
            for threshold in thresholds:
                if monthly_pct >= threshold:
                    key = f"monthly_{threshold}_{datetime.now(timezone.utc).strftime('%Y-%m')}"
                    if key not in _cost_alerts_sent:
                        alerts.append(f"Monthly spend at ${monthly_spend:.2f}/${monthly_limit:.2f} ({monthly_pct:.0f}%)")
                        _cost_alerts_sent[key] = time.time()
        for alert_msg in alerts:
            try:
                requests.post(webhook_url, json={"text": f"[COST ALERT] {alert_msg}", "username": "OpenClaw Cost Monitor", "icon_emoji": ":money_with_wings:"}, timeout=5)
                logger.info(f"Cost alert sent: {alert_msg}")
                broadcast_event({"type": "cost_alert", "agent": "system", "message": alert_msg})
            except Exception as e:
                logger.error(f"Failed to send Slack alert: {e}")
    except Exception as e:
        logger.warning(f"Cost alert check failed: {e}")


# ── Session helpers ────────────────────────────────────────────────────

def sanitize_session_key(session_key: str) -> str:
    import re
    sanitized = re.sub(r'[^a-zA-Z0-9:_\-]', '', session_key)
    if not sanitized or '..' in sanitized or '/' in session_key:
        raise ValueError(f"Invalid session key: {session_key}")
    return sanitized

def load_session_history(session_key: str) -> list:
    session_key = sanitize_session_key(session_key)
    session_file = SESSIONS_DIR / f"{session_key}.json"
    if session_file.exists():
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
                logger.info(f"Loaded session {session_key}: {len(data.get('messages', []))} messages")
                return data.get('messages', [])
        except Exception as e:
            logger.error(f"Error loading session {session_key}: {e}")
    return []

def save_session_history(session_key: str, history: list) -> bool:
    session_key = sanitize_session_key(session_key)
    session_file = SESSIONS_DIR / f"{session_key}.json"
    try:
        data = {"session_key": session_key, "messages": history, "updated_at": asyncio.get_event_loop().time()}
        with open(session_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved session {session_key}: {len(history)} messages")
        return True
    except Exception as e:
        logger.error(f"Error saving session {session_key}: {e}")
        return False


# ── Slack helper ───────────────────────────────────────────────────────

async def send_slack_message(channel: str, text: str, thread_ts: str = None) -> bool:
    if not SLACK_BOT_TOKEN:
        logger.warning("Slack Bot Token not configured, skipping send")
        return False
    try:
        payload = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
                json=payload,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"Slack send failed: {data.get('error', 'unknown')}")
                return False
            return True
    except Exception as e:
        logger.error(f"Slack send error: {e}")
        return False


# ── Claude tool calling ────────────────────────────────────────────────

async def call_claude_with_tools(client, model: str, system_prompt: str, messages: list, max_rounds: int = 5) -> str:
    """Call Claude with tool use, automatically executing tools and feeding results back."""
    from agent_tools import AGENT_TOOLS, execute_tool

    tools = AGENT_TOOLS
    current_messages = list(messages)

    for round_num in range(max_rounds):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=current_messages,
                tools=tools,
            )
        except Exception as e:
            logger.error(f"Claude tool call round {round_num} failed: {e}")
            raise

        if response.stop_reason == "end_turn" or response.stop_reason != "tool_use":
            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            return "\n".join(text_parts) if text_parts else "(No text response)"

        text_parts = []
        tool_results = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                logger.info(f"Tool call [{round_num}]: {tool_name}({json.dumps(tool_input)[:100]})")
                try:
                    result = await execute_tool(tool_name, tool_input)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)[:2000]})
                except Exception as e:
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True})

        current_messages.append({"role": "assistant", "content": response.content})
        current_messages.append({"role": "user", "content": tool_results})

    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(text_parts) if text_parts else "(Tool loop reached max rounds)"


# ── Vision rate limiting ───────────────────────────────────────────────

_vision_rate_limits: Dict[str, list] = {}

def _check_vision_rate_limit(device_id: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    now = time.time()
    if device_id not in _vision_rate_limits:
        _vision_rate_limits[device_id] = []
    _vision_rate_limits[device_id] = [ts for ts in _vision_rate_limits[device_id] if now - ts < window_seconds]
    if len(_vision_rate_limits[device_id]) >= max_requests:
        return False
    _vision_rate_limits[device_id].append(now)
    return True


# ── System prompt builders ─────────────────────────────────────────────

def _build_system_prompt(agent_key: str, agent_config: dict = None) -> str:
    if not agent_config:
        agent_config = get_agent_config(agent_key) or {}
    persona = agent_config.get("persona", "")
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    signature = agent_config.get("signature", "")
    identity_context = ""
    gateway_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                identity_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass
    delegation_instructions = ""
    if agent_key == "project_manager":
        delegation_instructions = """
DELEGATION: When a task requires specialist work, include markers:
[DELEGATE:elite_coder]task[/DELEGATE]
[DELEGATE:coder_agent]task[/DELEGATE]
[DELEGATE:hacker_agent]task[/DELEGATE]
[DELEGATE:database_agent]task[/DELEGATE]
"""
    return f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- You have access to execution tools: shell commands, git, file I/O, Vercel deploy, package install, web scraping, and research.
- Use tools proactively to accomplish tasks. Don't just describe what to do — DO it.
- When asked to build, deploy, or fix something, use the tools to actually execute the work.
- Research before executing complex tasks (use research_task tool).
- Auto-install missing tools/packages as needed (use install_package tool).
{delegation_instructions}
--- IDENTITY & CONTEXT ---
{identity_context}"""


def build_agent_system_prompt(agent_role: AgentRole) -> str:
    soul_context = ""
    gateway_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                soul_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass
    identity_context = orchestrator.get_agent_context(agent_role)
    agent_config = orchestrator.config["agents"].get(agent_role.value, {})
    persona = agent_config.get("persona", "")
    skills = agent_config.get("skills", [])
    workflow_status = orchestrator.get_workflow_status()
    base_prompt = f"""You are part of the Cybershield AI Agency - a multi-agent system powered by OpenClaw.

{identity_context}

YOUR PERSONA:
{persona}

YOUR SKILLS:
{', '.join(skills)}

CURRENT WORKFLOW STATE: {workflow_status['current_state']}
NEXT HANDLER: {workflow_status['next_handler']}

CORE GUIDELINES:
1. ALWAYS identify yourself in messages
2. ALWAYS use your signature: {orchestrator.agents[agent_role].signature}
3. Tag recipients with @ symbols
4. Follow the communication rules in your identity section above
5. Be playful but professional
6. Never break character - you ARE this agent

REMEMBER:
- If you need to talk to the client and you're NOT the PM, route through @Cybershield-PM
- If you're collaborating with another agent, tag them clearly
- Keep the team workflow moving forward
- Celebrate wins!

Now respond as {orchestrator.agents[agent_role].name} {orchestrator.agents[agent_role].emoji}!
"""
    if soul_context:
        base_prompt += f"\n\n--- IDENTITY & CONTEXT ---\n{soul_context[:3000]}"
    return base_prompt


def build_channel_system_prompt(agent_config: dict) -> str:
    soul_context = ""
    gateway_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                soul_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    persona = agent_config.get("persona", "You are a helpful assistant.")
    signature = agent_config.get("signature", "")
    skills = agent_config.get("skills", [])
    style = agent_config.get("style_guidelines", [])
    skills_str = ", ".join(skills) if skills else "general assistance"
    style_str = "\n".join(f"- {s}" for s in style) if style else "- Professional and direct"
    prompt = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

YOUR SKILLS: {skills_str}

COMMUNICATION STYLE:
{style_str}

AVAILABLE TOOLS — USE THEM PROACTIVELY:
- github_repo_info: Check repo status, issues, PRs, commits for any GitHub repo
- github_create_issue: File bugs and feature requests on GitHub
- web_search: Search the web for current information, docs, tutorials
- create_job: Create tasks in the autonomous job queue
- list_jobs: View current job queue and status
- create_proposal: Submit a proposal for auto-approval
- approve_job: Approve a job for execution
- get_cost_summary: Check budget and cost status

ACTIVE PROJECTS (user: Miles Sage):
- Barber CRM (Miles0sage/Barber-CRM)
- Delhi Palace (Miles0sage/Delhi-Palce-)
- OpenClaw (this platform)
- PrestressCalc (Miles0sage/Mathcad-Scripts)
- Concrete Canoe 2026

BEHAVIOR:
- When someone asks about a repo -> use github_repo_info tool
- When someone asks to create a task -> use create_job tool
- When someone needs current info -> use web_search tool
- When asked about costs/budget -> use get_cost_summary tool
- Think step by step for complex requests
- Be proactive: suggest next steps, offer to check things
- Reference specific projects when relevant

Always sign off with: {signature}"""
    if soul_context:
        prompt += f"\n\n--- IDENTITY & CONTEXT ---\n{soul_context[:3000]}"
    try:
        mm = get_memory_manager()
        if mm:
            memory_context = mm.get_context_for_prompt(persona, max_tokens=500)
            if memory_context:
                prompt += f"\n\nRELEVANT MEMORIES:\n{memory_context}"
    except Exception:
        pass
    return prompt


# ── Agent config & model calling ───────────────────────────────────────

def get_agent_config(agent_key: str) -> Dict:
    return CONFIG.get("agents", {}).get(agent_key, {})

ESCALATION_CHAIN = {
    "coder_agent": "elite_coder",
    "elite_coder": "project_manager",
    "hacker_agent": "project_manager",
    "database_agent": None,
    "project_manager": None,
}

def call_ollama(model: str, prompt: str, endpoint: str = "http://localhost:11434") -> tuple[str, int]:
    logger.info(f"Calling Ollama: {model}")
    response = requests.post(f"{endpoint}/api/generate", json={"model": model, "prompt": prompt, "stream": False}, timeout=120)
    data = response.json()
    text = data.get("response", "")
    tokens = len(text.split())
    logger.info(f"Ollama responded: {len(text)} chars")
    return text, tokens

def call_anthropic_api(model: str, prompt: str) -> tuple[str, int]:
    logger.info(f"Calling Anthropic: {model}")
    response = anthropic_client.messages.create(model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt}])
    text = response.content[0].text
    tokens = response.usage.output_tokens
    logger.info(f"Anthropic responded: {tokens} tokens")
    return text, tokens

def call_model_with_escalation(agent_key: str, prompt: str, conversation: list = None, max_escalations: int = 2) -> tuple[str, int, str]:
    current_agent = agent_key
    attempts = 0
    while current_agent and attempts <= max_escalations:
        try:
            response_text, tokens = call_model_for_agent(current_agent, prompt, conversation)
            if attempts > 0:
                logger.info(f"Escalation success: {agent_key} -> {current_agent} (attempt {attempts + 1})")
                broadcast_event({"type": "escalation_success", "agent": current_agent, "message": f"Escalated from {agent_key} -> {current_agent} (succeeded)"})
            return response_text, tokens, current_agent
        except Exception as e:
            logger.warning(f"Agent {current_agent} failed: {e}")
            broadcast_event({"type": "escalation_attempt", "agent": current_agent, "message": f"{current_agent} failed: {str(e)[:60]}. Escalating..."})
            next_agent = ESCALATION_CHAIN.get(current_agent)
            if next_agent:
                logger.info(f"Escalating: {current_agent} -> {next_agent}")
                current_agent = next_agent
                attempts += 1
            else:
                raise
    raise RuntimeError(f"Escalation chain exhausted for {agent_key} after {attempts} attempts")


def call_model_for_agent(agent_key: str, prompt: str, conversation: list = None) -> tuple[str, int]:
    agent_config = get_agent_config(agent_key)
    if not agent_config:
        logger.warning(f"No config for agent: {agent_key}, using default")
        agent_config = get_agent_config("project_manager")
    provider = agent_config.get("apiProvider", "anthropic")
    model = agent_config.get("model", "claude-sonnet-4-5-20250929")
    endpoint = agent_config.get("endpoint", "http://localhost:11434")
    persona = agent_config.get("persona", "")
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    signature = agent_config.get("signature", "")

    identity_context = ""
    gateway_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                identity_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            logger.warning(f"Identity file not found: {filepath}")

    skills_index = ""
    skills_index_path = os.path.join(gateway_dir, "skills", "index.md")
    try:
        with open(skills_index_path, "r") as f:
            skills_index = f.read()
    except FileNotFoundError:
        logger.warning(f"Skill graph index not found: {skills_index_path}")

    delegation_instructions = ""
    if agent_key == "project_manager":
        delegation_instructions = """

DELEGATION: When a task requires specialist work, you can delegate by including markers in your response:
[DELEGATE:elite_coder]detailed task description here[/DELEGATE]
[DELEGATE:coder_agent]simple coding task here[/DELEGATE]
[DELEGATE:hacker_agent]security review task here[/DELEGATE]
[DELEGATE:database_agent]database query task here[/DELEGATE]

Only delegate when the task clearly needs a specialist. For planning, coordination, and general questions, handle directly.
After delegation results come back, synthesize them into a final response for the user.
"""

    anthropic_system = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- Follow your character consistently
- Follow the communication and behavior rules in the identity documents below
- Reference real project names (Barber CRM, Delhi Palace, OpenClaw, PrestressCalc, Concrete Canoe)
- NEVER invent fake project names like "DataGuard Enterprise" or "SecureShield"
{delegation_instructions}
Remember: You ARE {name}. Stay in character!

--- IDENTITY & CONTEXT ---
{identity_context}

--- SKILL GRAPH ---
{skills_index}"""

    ollama_suffix = f"\n\nSign your response with: {signature}"

    router_enabled = CONFIG.get("routing", {}).get("enabled", False)
    if router_enabled and provider == "anthropic":
        try:
            classification = classify_query(prompt)
            routed_model = MODEL_ALIASES.get(classification.model, model)
            logger.info(f"Router: complexity={classification.complexity}, model={classification.model} ({routed_model}), confidence={classification.confidence}")
            model = routed_model
        except Exception as e:
            logger.warning(f"Router failed, using default model: {e}")

    logger.info(f"Agent: {agent_key} -> Provider: {provider} -> Model: {model}")

    if conversation:
        full_prompt = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation])
        full_prompt += f"\n\nassistant: "
    else:
        full_prompt = prompt

    if provider == "ollama":
        ollama_prompt = f"{full_prompt}{ollama_suffix}"
        return call_ollama(model, ollama_prompt, endpoint)
    elif provider == "anthropic":
        cached_system = [{"type": "text", "text": anthropic_system, "cache_control": {"type": "ephemeral"}}]
        if conversation:
            response = anthropic_client.messages.create(model=model, max_tokens=8192, system=cached_system, messages=conversation)
        else:
            response = anthropic_client.messages.create(model=model, max_tokens=8192, system=cached_system, messages=[{"role": "user", "content": prompt}])
        response_text = response.content[0].text
        tokens_input = response.usage.input_tokens
        tokens_output = response.usage.output_tokens
        try:
            cost = log_cost_event(project="openclaw", agent=agent_key, model=model, tokens_input=tokens_input, tokens_output=tokens_output)
            logger.info(f"Cost logged: ${cost:.4f} ({agent_key} / {model})")
        except Exception as e:
            logger.warning(f"Cost logging failed: {e}")
        return response_text, tokens_output
    elif provider == "deepseek":
        try:
            deepseek_client = DeepseekClient()
            api_model = model if model in ["kimi-2.5", "kimi"] else "kimi-2.5"
            response = deepseek_client.call(model=api_model, prompt=prompt if not conversation else full_prompt, system_prompt=anthropic_system, max_tokens=8192, temperature=0.7)
            response_text = response.content
            tokens_input = response.tokens_input
            tokens_output = response.tokens_output
            try:
                cost = log_cost_event(project="openclaw", agent=agent_key, model=api_model, tokens_input=tokens_input, tokens_output=tokens_output)
                logger.info(f"Cost logged: ${cost:.4f} ({agent_key} / {api_model})")
            except Exception as e:
                logger.warning(f"Cost logging failed: {e}")
            return response_text, tokens_output
        except Exception as e:
            logger.error(f"Deepseek API error: {e}")
            raise
    elif provider == "minimax":
        try:
            minimax_client = MiniMaxClient()
            api_model = model if model in ["m2.5", "m2.5-lightning"] else "m2.5"
            response = minimax_client.call(model=api_model, prompt=prompt if not conversation else full_prompt, system_prompt=anthropic_system, max_tokens=16384, temperature=0.3)
            response_text = response.content
            tokens_input = response.tokens_input
            tokens_output = response.tokens_output
            try:
                cost = log_cost_event(project="openclaw", agent=agent_key, model=api_model, tokens_input=tokens_input, tokens_output=tokens_output)
                logger.info(f"Cost logged: ${cost:.4f} ({agent_key} / {api_model})")
            except Exception as e:
                logger.warning(f"Cost logging failed: {e}")
            return response_text, tokens_output
        except Exception as e:
            logger.error(f"MiniMax API error: {e}")
            raise
    elif provider == "gemini":
        try:
            gemini_client = GeminiClient()
            valid_models = list(GeminiClient.MODELS.keys())
            api_model = model if model in valid_models else "gemini-2.5-flash"
            response = gemini_client.call(model=api_model, prompt=prompt if not conversation else full_prompt, system_prompt=anthropic_system, max_tokens=8192, temperature=0.3)
            response_text = response.content
            tokens_input = response.tokens_input
            tokens_output = response.tokens_output
            try:
                cost = log_cost_event(project="openclaw", agent=agent_key, model=api_model, tokens_input=tokens_input, tokens_output=tokens_output)
                logger.info(f"Cost logged: ${cost:.4f} ({agent_key} / {api_model})")
            except Exception as e:
                logger.warning(f"Cost logging failed: {e}")
            return response_text, tokens_output
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ── History trimming ───────────────────────────────────────────────────

async def trim_history_if_needed(history: list, client=None) -> list:
    if len(history) <= SUMMARIZE_THRESHOLD:
        return history
    old = history[:-20]
    recent = history[-20:]
    summary_parts = []
    for m in old:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        summary_parts.append(f"{m.get('role', 'unknown')}: {str(content)[:200]}")
    summary_text = "\n".join(summary_parts)
    if client:
        try:
            resp = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=500,
                    messages=[{"role": "user", "content": "Summarize this conversation history concisely. Preserve key decisions, completed tasks, and important context:\n\n" + summary_text}],
                ),
            )
            summary = resp.content[0].text
        except Exception as e:
            logger.warning(f"History summarisation failed, using truncation: {e}")
            summary = f"[Previous conversation with {len(old)} messages -- auto-truncated]"
    else:
        summary = f"[Previous conversation with {len(old)} messages -- auto-truncated]"
    return [{"role": "assistant", "content": f"[Conversation summary]: {summary}"}] + recent
