"""
FastAPI APIRouter module for Slack integration endpoints.

Routes:
- POST /slack/events          - Receive Slack messages via webhook with signature verification
- POST /api/quotas/check      - Check if a request would be allowed under current quotas
- GET  /slack/report/costs    - Send cost summary to Slack
- GET  /slack/report/health   - Send gateway health to Slack
- GET  /slack/report/sessions - Send session count to Slack
- POST /slack/report/send     - Send arbitrary message to Slack
- POST /slack/create-job      - Create a job from Slack JSON payload
- POST /slack/slash/job       - Slack slash command: /job <project> <priority> <task>
- POST /slack/slash/jobs      - Slack slash command: /jobs [status]
- POST /slack/slash/approve   - Slack slash command: /approve <job-id>
"""

import json
import uuid
import asyncio
import hmac
import hashlib
import time
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from routers.shared import (
    SLACK_SIGNING_SECRET,
    SLACK_BOT_TOKEN,
    SLACK_REPORT_CHANNEL,
    CONFIG,
    TASKS_FILE,
    send_slack_message,
    load_session_history,
    save_session_history,
    broadcast_event,
    build_channel_system_prompt,
    get_memory_manager,
    get_cost_metrics,
    get_heartbeat_monitor,
    SESSIONS_DIR,
    call_claude_with_tools,
    agent_router,
)
from job_manager import create_job, list_jobs, get_job, update_job_status
from complexity_classifier import classify as classify_query

import anthropic

logger = logging.getLogger("openclaw_gateway")
router = APIRouter()

# Dedup cache: event_id -> timestamp (prevents Slack retries from being processed twice)
_seen_events: dict[str, float] = {}
_SEEN_EVENTS_TTL = 300  # 5 minutes


def _dedup_cleanup() -> None:
    """Remove expired entries from the dedup cache."""
    now = time.time()
    expired = [k for k, v in _seen_events.items() if now - v > _SEEN_EVENTS_TTL]
    for k in expired:
        del _seen_events[k]


# ═══════════════════════════════════════════════════════════════════════
# SLACK WEBHOOK HANDLER
# ═══════════════════════════════════════════════════════════════════════


@router.post("/slack/events")
async def slack_events(request: Request):
    """Receive Slack messages via webhook with signature verification"""
    try:
        # Get request body and headers for signature verification
        body_bytes = await request.body()
        payload = json.loads(body_bytes)

        # Handle URL verification challenge FIRST (before signature check)
        # Slack sends this during app setup and it must be answered immediately
        if payload.get("type") == "url_verification":
            logger.info("Slack verification challenge received")
            return {"challenge": payload.get("challenge")}

        # --- Retry header: Slack sends X-Slack-Retry-Num on retries ---
        retry_num = request.headers.get("X-Slack-Retry-Num")
        if retry_num is not None:
            logger.info(f"Slack retry #{retry_num} — acknowledging without reprocessing")
            return {"ok": True}

        # --- Dedup by event_id (belt-and-suspenders with retry header) ---
        event_id = payload.get("event_id", "")
        if event_id:
            if event_id in _seen_events:
                logger.info(f"Duplicate Slack event {event_id} — skipping")
                return {"ok": True}
            _seen_events[event_id] = time.time()
            _dedup_cleanup()

        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")

        # Verify Slack signature (security best practice)
        if SLACK_SIGNING_SECRET:
            # Check timestamp is within 5 minutes (prevent replay attacks)
            try:
                request_time = int(timestamp)
                current_time = int(time.time())
                if abs(current_time - request_time) > 300:
                    logger.warning("Slack request timestamp too old (replay attack?)")
                    return JSONResponse({"error": "Invalid timestamp"}, status_code=403)
            except ValueError:
                logger.warning("Invalid timestamp from Slack")
                return JSONResponse({"error": "Invalid timestamp"}, status_code=403)

            # Verify signature
            sig_basestring = f"v0:{timestamp}:{body_bytes.decode()}"
            expected_signature = "v0=" + hmac.new(
                SLACK_SIGNING_SECRET.encode(),
                sig_basestring.encode(),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_signature, signature):
                logger.warning("Invalid Slack signature")
                return JSONResponse({"error": "Invalid signature"}, status_code=403)

        # Handle message events
        event = payload.get("event", {})
        if event.get("type") == "message" and not event.get("bot_id"):
            user_id = event.get("user")
            channel_id = event.get("channel")
            thread_ts = event.get("thread_ts") or event.get("ts")
            text = event.get("text", "")

            if not text or not user_id or not channel_id:
                return {"ok": True}

            # Fire-and-forget: process in background so we return 200 to Slack < 3s
            asyncio.create_task(_process_slack_message(user_id, channel_id, thread_ts, text))

        return {"ok": True}

    except Exception as e:
        logger.error(f"Slack webhook error: {e}")
        return {"ok": False, "error": str(e)}


async def _process_slack_message(user_id: str, channel_id: str, thread_ts: str, text: str) -> None:
    """Background handler for Slack messages — runs after 200 is returned to Slack."""
    session_key = f"slack:{user_id}:{channel_id}"
    logger.info(f"💬 Slack message from {user_id} in {channel_id}: {text[:50]}")

    # ═ TASK CREATION: Detect "create task:", "todo:", etc. from Slack
    import re as _re_sl
    _SL_TASK_PATTERNS = [
        r'^create task[:\s]+(.+)', r'^todo[:\s]+(.+)', r'^add task[:\s]+(.+)',
        r'^remind me to[:\s]+(.+)', r'^new task[:\s]+(.+)',
    ]
    sl_task_match = None
    for _p in _SL_TASK_PATTERNS:
        _m = _re_sl.match(_p, text.strip(), _re_sl.IGNORECASE)
        if _m:
            sl_task_match = _m.group(1).strip()
            break

    if sl_task_match:
        try:
            if TASKS_FILE.exists():
                with open(TASKS_FILE, 'r') as f:
                    tasks = json.load(f)
            else:
                tasks = []
            routing = agent_router.select_agent(sl_task_match)
            new_task = {
                "id": str(uuid.uuid4())[:8],
                "title": sl_task_match[:200],
                "description": text,
                "status": "todo",
                "agent": routing.get("agentId", "project_manager"),
                "created_at": datetime.now(timezone.utc).isoformat() + "Z",
                "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
                "source": "slack",
                "session_key": session_key
            }
            tasks.append(new_task)
            with open(TASKS_FILE, 'w') as f:
                json.dump(tasks, f, indent=2)

            sl_jm_job_id = None
            try:
                sl_jm_job = create_job(
                    project=new_task.get("title", "slack-task"),
                    task=text,
                    priority="P1"
                )
                sl_jm_job_id = sl_jm_job.id
                logger.info(f"✅ Runner job created for Slack task: {sl_jm_job_id}")
            except Exception as _sje:
                logger.warning(f"Runner job creation failed for Slack task (non-fatal): {_sje}")

            task_response = (
                f"Task created: *{sl_task_match[:200]}*\n"
                f"ID: `{new_task['id']}`"
                + (f" | Runner job: `{sl_jm_job_id}`" if sl_jm_job_id else "") + "\n"
                f"Assigned to: {routing.get('agentId', 'project_manager')}"
            )
            broadcast_event({"type": "task_created", "agent": "project_manager",
                             "message": f"Task from Slack: {sl_task_match[:80]}"})
            await send_slack_message(channel_id, task_response, thread_ts)
            return
        except Exception as e:
            logger.error(f"Slack task creation failed: {e}")

    try:
        route_decision = agent_router.select_agent(text)
        logger.info(f"🎯 Routed to {route_decision['agentId']}: {route_decision['reason']}")

        session_history = load_session_history(session_key)
        messages_for_api = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in session_history
        ]
        messages_for_api.append({"role": "user", "content": text})

        agent_config = CONFIG.get("agents", {}).get(route_decision["agentId"], {})
        system_prompt = build_channel_system_prompt(agent_config)
        model = agent_config.get("model", "claude-opus-4-6")

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        assistant_message = await call_claude_with_tools(
            client, model, system_prompt, messages_for_api
        )

        session_history.append({"role": "user", "content": text})
        session_history.append({"role": "assistant", "content": assistant_message})
        save_session_history(session_key, session_history)

        try:
            mm = get_memory_manager()
            if mm:
                mm.auto_extract_memories([
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": assistant_message}
                ])
        except Exception:
            pass

        logger.info(f"✅ Response generated: {assistant_message[:50]}...")
        await send_slack_message(channel_id, assistant_message, thread_ts)

    except Exception as e:
        logger.error(f"Error processing Slack message: {e}")
        await send_slack_message(channel_id, f"❌ Error processing message: {str(e)}", thread_ts)


# ═══════════════════════════════════════════════════════════════════════
# QUOTA CHECK ENDPOINT
# ═══════════════════════════════════════════════════════════════════════


class QuotaCheckRequest(BaseModel):
    project_id: Optional[str] = "default"
    queue_size: Optional[int] = 0


@router.post("/api/quotas/check")
async def quota_check_endpoint(req: QuotaCheckRequest):
    """Check if a request would be allowed under current quotas"""
    try:
        from routers.shared import check_all_quotas, get_quota_status
        quotas_ok, error_msg = check_all_quotas(req.project_id, req.queue_size)
        status = get_quota_status(req.project_id)

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "allowed": quotas_ok,
            "error": error_msg,
            "status": status
        }
    except Exception as e:
        logger.error(f"Error checking quotas: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }


# ═══════════════════════════════════════════════════════════════════════
# SLACK REPORTING ENDPOINTS
# GET  /slack/report/costs    - Send cost summary to Slack
# GET  /slack/report/health   - Send gateway health to Slack
# GET  /slack/report/sessions - Send session count to Slack
# POST /slack/report/send     - Send arbitrary message to Slack
# ═══════════════════════════════════════════════════════════════════════


@router.get("/slack/report/costs")
async def slack_report_costs():
    """Send cost summary to Slack"""
    try:
        metrics_data = get_cost_metrics()
        total = metrics_data.get('total_cost', 0)
        message = f"""*Cost Summary*

Total: ${total:.4f}
Entries: {metrics_data.get('entries_count', 0)}

*Top Agents:*"""

        for agent, cost in list(metrics_data.get('by_agent', {}).items())[:5]:
            message += f"\n  - {agent}: ${cost:.4f}"

        if not metrics_data.get('by_agent'):
            message += "\n  (no cost data yet)"

        await send_slack_message(SLACK_REPORT_CHANNEL, message)
        return {"ok": True, "message": "Cost summary sent"}
    except Exception as e:
        logger.error(f"Error sending cost report: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/slack/report/health")
async def slack_report_health():
    """Send gateway health to Slack"""
    try:
        monitor = get_heartbeat_monitor()
        if not monitor:
            message = "Heartbeat monitor not initialized"
        else:
            status = monitor.get_status()
            agents_monitoring = status.get("agents_monitoring", 0)
            is_running = status.get("running", False)

            session_count = len(list(SESSIONS_DIR.glob('*.json')))
            message = f"""*Gateway Health*

Heartbeat: {"running" if is_running else "stopped"}
Agents Monitored: {agents_monitoring}
Active Sessions: {session_count}
API Status: OK"""

        await send_slack_message(SLACK_REPORT_CHANNEL, message)
        return {"ok": True, "message": "Health report sent"}
    except Exception as e:
        logger.error(f"Error sending health report: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/slack/report/sessions")
async def slack_report_sessions():
    """Send active sessions count to Slack"""
    try:
        session_files = list(SESSIONS_DIR.glob("*.json"))
        total_messages = 0
        for f in session_files:
            try:
                data = json.load(open(f))
                total_messages += len(data.get("messages", []))
            except:
                pass

        message = f"""📊 *Active Sessions*

Sessions: {len(session_files)}
Total Messages: {total_messages}"""

        await send_slack_message(SLACK_REPORT_CHANNEL, message)
        return {"ok": True, "message": "Session report sent"}
    except Exception as e:
        logger.error(f"Error sending session report: {e}")
        return {"ok": False, "error": str(e)}


class SlackMessageRequest(BaseModel):
    channel: str
    text: str
    thread_ts: Optional[str] = None


@router.post("/slack/report/send")
async def slack_report_send(req: SlackMessageRequest):
    """Send arbitrary message to Slack channel"""
    try:
        if not req.channel or not req.text:
            return {"ok": False, "error": "channel and text required"}

        success = await send_slack_message(req.channel, req.text, req.thread_ts)
        return {"ok": success, "message": "Message sent" if success else "Failed to send"}
    except Exception as e:
        logger.error(f"Error sending Slack message: {e}")
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# SLACK JOB MANAGEMENT — Slash commands + JSON API for job creation
# ═══════════════════════════════════════════════════════════════════════


@router.post("/slack/create-job")
async def slack_create_job(request: Request):
    """Create a job from Slack JSON payload and notify the report channel."""
    try:
        data = await request.json()
        project = data.get("project", "openclaw")
        task = data.get("task", "General task")
        priority = data.get("priority", "P1")
        slack_user = data.get("slack_user_id", "unknown")

        job = create_job(project, task, priority)
        logger.info(f"✅ Job created from Slack: {job.id} by {slack_user}")

        await send_slack_message(
            SLACK_REPORT_CHANNEL,
            f"📋 *New Job Created*\n• *ID:* `{job.id}`\n• *Project:* {project}\n• *Task:* {task}\n• *Priority:* {priority}\n• *Created by:* <@{slack_user}>"
        )

        return {"success": True, "job_id": job.id, "status": "pending", "message": f"Job created: {job.id}"}
    except Exception as e:
        logger.error(f"Slack job creation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/slack/slash/job")
async def slack_slash_job(request: Request):
    """Slack slash command: /job <project> <priority> <task>"""
    try:
        form = await request.form()
        text = form.get("text", "").strip()
        user_id = form.get("user_id", "unknown")

        if not text:
            return PlainTextResponse(
                "Usage: `/job <project> <priority> <task>`\n"
                "Example: `/job barber-crm P1 Fix booking page`\n"
                "Projects: barber-crm, openclaw, delhi-palace, prestress-calc"
            )

        parts = text.split(None, 2)
        project = parts[0] if len(parts) >= 1 else "openclaw"
        priority = parts[1].upper() if len(parts) >= 2 and parts[1].upper() in ("P0", "P1", "P2", "P3") else "P1"
        task = parts[2] if len(parts) >= 3 else text
        if len(parts) >= 2 and parts[1].upper() not in ("P0", "P1", "P2", "P3"):
            task = " ".join(parts[1:])

        job = create_job(project, task, priority)
        logger.info(f"✅ Slash command job: {job.id} by {user_id}")

        await send_slack_message(
            SLACK_REPORT_CHANNEL,
            f"📋 *New Job via /job*\n• *ID:* `{job.id}`\n• *Project:* {project}\n• *Task:* {task}\n• *Priority:* {priority}\n• *By:* <@{user_id}>"
        )

        return PlainTextResponse(f"✅ Job created!\nID: `{job.id}`\nProject: {project} | Priority: {priority}\nTask: {task}")
    except Exception as e:
        logger.error(f"Slash command error: {e}")
        return PlainTextResponse(f"❌ Error: {str(e)}")


@router.post("/slack/slash/jobs")
async def slack_slash_jobs(request: Request):
    """Slack slash command: /jobs [status] — list recent jobs"""
    try:
        form = await request.form()
        filter_status = form.get("text", "").strip().lower()
        jobs = list_jobs()
        if filter_status:
            jobs = [j for j in jobs if j.get("status") == filter_status]
        if not jobs:
            return PlainTextResponse("No jobs found.")

        recent = jobs[-10:]
        lines = ["*Recent Jobs:*"]
        for j in reversed(recent):
            emoji = {"pending": "⏳", "analyzing": "🔍", "code_generated": "💻", "pr_ready": "📝", "approved": "✅", "merged": "🚀", "done": "✅", "failed": "❌"}.get(j.get("status", ""), "❓")
            lines.append(f"{emoji} `{j['id']}` | {j['project']} | {j.get('status','?')} | {j['task'][:60]}")
        return PlainTextResponse("\n".join(lines))
    except Exception as e:
        return PlainTextResponse(f"❌ Error: {str(e)}")


@router.post("/slack/slash/approve")
async def slack_slash_approve(request: Request):
    """Slack slash command: /approve <job-id>"""
    try:
        form = await request.form()
        job_id = form.get("text", "").strip()
        user_id = form.get("user_id", "unknown")

        if not job_id:
            return PlainTextResponse("Usage: `/approve <job-id>`")
        job = get_job(job_id)
        if not job:
            return PlainTextResponse(f"❌ Job `{job_id}` not found")
        if job.get("status") != "pr_ready":
            return PlainTextResponse(f"⚠️ Job `{job_id}` is `{job.get('status')}`, not ready for approval")

        update_job_status(job_id, "approved", approved_by=user_id)

        await send_slack_message(
            SLACK_REPORT_CHANNEL,
            f"✅ *Job Approved*\n• *ID:* `{job_id}`\n• *Task:* {job['task']}\n• *Approved by:* <@{user_id}>"
        )
        return PlainTextResponse(f"✅ Job `{job_id}` approved! Processor will execute it shortly.")
    except Exception as e:
        return PlainTextResponse(f"❌ Error: {str(e)}")
