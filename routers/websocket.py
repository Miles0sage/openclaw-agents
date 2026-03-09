"""
WebSocket and real-time job monitoring endpoints for OpenClaw Gateway.

Includes:
- WebSocket endpoints: /, /ws, /ws/glasses (video/audio/gesture processing)
- Job monitoring: /ws/jobs/{job_id} (live state updates)
- Job detail endpoints: /api/jobs/{job_id}/live, /phases, /detail, /costs
- System monitoring: /api/monitoring/active, /costs, /phases
"""

import asyncio
import json
import logging
import os
import uuid
import time
import base64 as b64mod
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import JSONResponse

from routers.shared import (
    active_connections,
    session_store,
    WS_RECEIVE_TIMEOUT,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
    PROTOCOL_VERSION,
    call_model_for_agent,
    trim_history_if_needed,
    agent_router,
    save_session_history,
)

logger = logging.getLogger("openclaw_gateway")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

async def _keepalive_ping(websocket: WebSocket, connection_id: str):
    """Send periodic pings"""
    try:
        while True:
            await asyncio.sleep(WS_PING_INTERVAL)
            try:
                await asyncio.wait_for(
                    websocket.send_json({"type": "pong"}),
                    timeout=WS_PING_TIMEOUT,
                )
            except (asyncio.TimeoutError, Exception):
                logger.warning(f"[WS] {connection_id} - Keepalive failed")
                return
    except asyncio.CancelledError:
        return


async def handle_websocket(websocket: WebSocket):
    """Handle WebSocket with proper model routing"""
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    active_connections[connection_id] = websocket
    ping_task = None

    logger.info(f"[WS] New connection: {connection_id}")

    try:
        data = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=WS_RECEIVE_TIMEOUT,
        )
        msg = json.loads(data)

        logger.info(f"[WS] {connection_id} - First message: {msg.get('method')}")

        ping_task = asyncio.create_task(_keepalive_ping(websocket, connection_id))

        while True:
            if 'msg' not in locals() or msg is None:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WS_RECEIVE_TIMEOUT,
                )
                msg = json.loads(data)

            msg_type = msg.get("type")

            if msg_type == "req":
                request_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", {})

                logger.info(f"[WS] {connection_id} - Request {request_id}: {method}")

                if method == "connect":
                    hello_ok_payload = {
                        "type": "hello-ok",
                        "protocol": PROTOCOL_VERSION,
                        "features": {
                            "methods": ["chat", "agents", "status"],
                            "events": ["message", "status"]
                        },
                        "auth": {
                            "role": "operator",
                            "scopes": ["operator.admin"],
                            "issuedAtMs": int(asyncio.get_event_loop().time() * 1000)
                        },
                        "policy": {
                            "tickIntervalMs": 30000
                        }
                    }

                    await websocket.send_json({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": hello_ok_payload
                    })
                    logger.info(f"[WS] {connection_id} - Connected")

                elif method == "chat.send" or method == "chat":
                    run_id = params.get("idempotencyKey", str(uuid.uuid4()))
                    session_key = params.get("sessionKey", "main")
                    message_text = params.get("message", "")

                    # Acknowledge
                    await websocket.send_json({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": {
                            "runId": run_id,
                            "status": "started"
                        }
                    })

                    try:

                        session_store.get(session_key).append({
                            "role": "user",
                            "content": message_text
                        })

                        # Determine agent using intelligent routing
                        route_decision = agent_router.select_agent(message_text)
                        active_agent = route_decision["agentId"]

                        # Call CORRECT model
                        logger.info(f"🎯 Routing to agent: {active_agent} ({route_decision['reason']})")
                        _trimmed_ws = await trim_history_if_needed(
                            session_store.get(session_key))
                        response_text, tokens = call_model_for_agent(
                            active_agent,
                            message_text,
                            _trimmed_ws[-10:]  # Last 10 messages
                        )

                        timestamp = int(asyncio.get_event_loop().time() * 1000)

                        session_store.get(session_key).append({
                            "role": "assistant",
                            "content": response_text
                        })

                        # Save session to disk
                        save_session_history(session_key, session_store.get(session_key))

                        # Send response
                        await websocket.send_json({
                            "type": "event",
                            "event": "chat",
                            "payload": {
                                "runId": run_id,
                                "message": response_text,
                                "timestamp": timestamp,
                                "stopReason": "end_turn",
                                "usage": {
                                    "totalTokens": tokens
                                }
                            }
                        })

                        logger.info(f"[WS] {connection_id} - Sent response ({tokens} tokens)")

                    except Exception as e:
                        logger.error(f"Error: {e}")
                        await websocket.send_json({
                            "type": "event",
                            "event": "error",
                            "payload": {
                                "runId": run_id,
                                "error": str(e)
                            }
                        })

                else:
                    # Echo other methods
                    await websocket.send_json({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": {}
                    })

            msg = None  # Reset for next iteration

    except asyncio.TimeoutError:
        logger.warning(f"[WS] {connection_id} - Timeout")
    except Exception as e:
        logger.error(f"[WS] {connection_id} - Error: {e}")
    finally:
        if ping_task:
            ping_task.cancel()
        active_connections.pop(connection_id, None)
        logger.info(f"[WS] {connection_id} - Disconnected")


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@router.websocket("/")
async def root_websocket(websocket: WebSocket):
    """Root WebSocket endpoint — main chat connection"""
    await handle_websocket(websocket)


@router.websocket("/ws")
async def ws_websocket(websocket: WebSocket):
    """Standard WebSocket endpoint — main chat connection"""
    await handle_websocket(websocket)


@router.websocket("/ws/glasses")
async def glasses_websocket(websocket: WebSocket):
    """VisionClaw smart glasses WebSocket — receives camera frames + audio, returns AI responses."""
    await websocket.accept()
    device_id = f"glasses-{uuid.uuid4().hex[:8]}"
    logger.info(f"[VISIONCLAW] Device connected: {device_id}")

    # Notify owner
    try:
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if tg_token:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": os.getenv("TELEGRAM_CHAT_ID", ""), "text": f"👓 VisionClaw glasses connected: {device_id}"}
                )
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "handshake":
                logger.info(f"[VISIONCLAW] {device_id} handshake: {data.get('version')} caps={data.get('capabilities')}")
                await websocket.send_json({"type": "ack", "device_id": device_id, "status": "connected"})

            elif msg_type == "frame":
                # Camera frame received — send to vision model
                frame_b64 = data.get("data", "")
                resolution = data.get("resolution", "unknown")
                frame_size = data.get("size", 0)
                logger.info(f"[VISIONCLAW] Frame from {device_id}: {resolution}, {frame_size} bytes")

                # Save latest frame for debug
                os.makedirs("./data/visionclaw", exist_ok=True)
                try:
                    frame_bytes = b64mod.b64decode(frame_b64)
                    with open(f"./data/visionclaw/latest_frame.jpg", "wb") as f:
                        f.write(frame_bytes)
                except Exception:
                    pass

                # TODO: Send to Gemini Vision or Groq for analysis
                # For now, acknowledge
                await websocket.send_json({
                    "type": "ack",
                    "frame_received": True,
                    "resolution": resolution,
                })

            elif msg_type == "audio":
                # Audio chunk — send to STT
                logger.info(f"[VISIONCLAW] Audio from {device_id}: {data.get('duration_ms', 0)}ms")
                # TODO: Buffer audio chunks, send to Groq Whisper when silence detected
                await websocket.send_json({"type": "ack", "audio_received": True})

            elif msg_type == "gesture":
                gesture = data.get("gesture", "unknown")
                logger.info(f"[VISIONCLAW] Gesture from {device_id}: {gesture}")

                if gesture == "double_tap":
                    # Trigger: capture + analyze current scene
                    await websocket.send_json({"type": "hud", "text": "Analyzing...", "duration_ms": 3000})
                elif gesture == "head_nod":
                    await websocket.send_json({"type": "hud", "text": "Confirmed", "duration_ms": 1000})

            elif msg_type == "command":
                cmd = data.get("command", "")
                logger.info(f"[VISIONCLAW] Command from {device_id}: {cmd}")
                # Voice command from STT — process as agent query
                await websocket.send_json({"type": "processing", "command": cmd})

            else:
                logger.warning(f"[VISIONCLAW] Unknown message type from {device_id}: {msg_type}")

    except Exception as e:
        logger.info(f"[VISIONCLAW] Device disconnected: {device_id} ({e})")
    finally:
        try:
            tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if tg_token:
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id": os.getenv("TELEGRAM_CHAT_ID", ""), "text": f"👓 VisionClaw disconnected: {device_id}"}
                    )
        except Exception:
            pass


@router.websocket("/ws/jobs/{job_id}")
async def ws_job_monitor(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job monitoring.

    Connects client to live updates for a specific job. Pushes state
    changes every time an event fires (phase changes, tool calls, etc.).
    """
    from gateway_monitoring import get_job_monitor, get_ws_manager

    ws_mgr = get_ws_manager()
    monitor = get_job_monitor()
    poll_interval_seconds = 1.0
    heartbeat_interval_seconds = 30.0

    await websocket.accept()
    ws_mgr.connect(job_id, websocket)
    logger.info(f"[WS-MONITOR] Client connected for job {job_id}")

    try:
        last_state_signature = ""
        last_heartbeat_at = time.monotonic()

        async def send_state(message_type: str) -> bool:
            nonlocal last_state_signature

            state = monitor.get_live_state(job_id)
            state_signature = json.dumps(state, sort_keys=True, default=str)
            if message_type == "snapshot" or state_signature != last_state_signature:
                await websocket.send_json({"type": message_type, "job_id": job_id, "state": state})
                last_state_signature = state_signature
                return True
            return False

        # Send initial state snapshot
        await send_state("snapshot")

        # Poll the live state so the client sees updates even if no explicit
        # broadcast hook is wired from the event engine yet.
        while True:
            try:
                msg = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=poll_interval_seconds,
                )
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg == "refresh":
                    await send_state("snapshot")
            except asyncio.TimeoutError:
                sent_update = await send_state("update")
                now = time.monotonic()

                if not sent_update and now - last_heartbeat_at >= heartbeat_interval_seconds:
                    await websocket.send_json({"type": "heartbeat", "ts": time.time()})
                    last_heartbeat_at = now
    except Exception as e:
        logger.info(f"[WS-MONITOR] Client disconnected for job {job_id}: {e}")
    finally:
        ws_mgr.disconnect(job_id, websocket)


# ═══════════════════════════════════════════════════════════════════════════
# JOB MONITORING HTTP ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/jobs/{job_id}/live")
async def get_job_live_state(job_id: str):
    """Get real-time state of a running job (phase, progress, active tools, cost)."""
    from gateway_monitoring import get_job_monitor

    monitor = get_job_monitor()
    state = monitor.get_live_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found in live state"}, status_code=404)
    return {"job_id": job_id, "state": state}


@router.get("/api/jobs/{job_id}/phases")
async def get_job_phases(job_id: str):
    """Get phase timeline for a job (start/end timestamps per phase)."""
    from gateway_monitoring import get_job_phases_timeline

    timeline = get_job_phases_timeline(job_id)
    return {"job_id": job_id, "phases": timeline}


@router.get("/api/jobs/{job_id}/detail")
async def get_job_detail(job_id: str):
    """Get full execution details for a completed job from run logs."""
    run_dir = os.path.join(os.path.dirname(__file__), "..", "data", "jobs", "runs", job_id)
    if not os.path.isdir(run_dir):
        return JSONResponse({"error": "Run data not found"}, status_code=404)

    detail = {"job_id": job_id, "phases": {}}

    # Read result.json (overall summary)
    result_path = os.path.join(run_dir, "result.json")
    if os.path.exists(result_path):
        with open(result_path) as f:
            detail["result"] = json.loads(f.read())

    # Read progress.json
    progress_path = os.path.join(run_dir, "progress.json")
    if os.path.exists(progress_path):
        with open(progress_path) as f:
            detail["progress"] = json.loads(f.read())

    # Read plan.json
    plan_path = os.path.join(run_dir, "plan.json")
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            detail["plan"] = json.loads(f.read())

    # Read phase JSONL logs (research, execute, verify, deliver)
    for phase_name in ["research", "plan", "execute", "verify", "deliver"]:
        jsonl_path = os.path.join(run_dir, f"{phase_name}.jsonl")
        if os.path.exists(jsonl_path):
            events = []
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            detail["phases"][phase_name] = {
                "event_count": len(events),
                "events": events[-100:],  # Last 100 events per phase (cap size)
            }

    return detail


@router.get("/api/jobs/{job_id}/costs")
async def get_job_costs(job_id: str):
    """Get detailed cost breakdown for a job (per-phase, per-tool, per-agent, per-model)."""
    from cost_breakdown import get_job_cost_breakdown, get_tool_usage_breakdown

    costs = get_job_cost_breakdown(job_id)
    tools = get_tool_usage_breakdown(job_id)
    return {"job_id": job_id, "costs": costs, "tool_usage": tools}


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM MONITORING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/monitoring/active")
async def get_active_jobs_monitoring():
    """Get live state of all currently active jobs."""
    from gateway_monitoring import get_job_monitor

    monitor = get_job_monitor()
    states = monitor.get_all_live_states()
    return {
        "active_jobs": len(states),
        "jobs": states,
    }


@router.get("/api/monitoring/costs")
async def get_project_costs(request: Request):
    """Get aggregated cost summary for a project or all projects."""
    from cost_breakdown import get_project_cost_summary

    project = request.query_params.get("project")
    days = int(request.query_params.get("days", "7"))
    return get_project_cost_summary(project=project, days=days)


@router.get("/api/monitoring/phases")
async def get_pipeline_phases():
    """Get pipeline phase configuration with allowed tools and descriptions."""
    from autonomous_runner import (
        Phase, RESEARCH_TOOLS, PLAN_TOOLS, EXECUTE_TOOLS,
        CODE_REVIEW_TOOLS, VERIFY_TOOLS, DELIVER_TOOLS
    )

    phases = [
        {
            "name": Phase.RESEARCH.value,
            "tools": RESEARCH_TOOLS,
            "description": "Gather information, analyze requirements, and research the problem domain using web search, file exploration, and documentation review."
        },
        {
            "name": Phase.PLAN.value,
            "tools": PLAN_TOOLS,
            "description": "Create a detailed execution plan by analyzing the codebase structure and breaking down the task into actionable steps."
        },
        {
            "name": Phase.EXECUTE.value,
            "tools": EXECUTE_TOOLS,
            "description": "Implement the planned solution by writing code, running commands, managing files, and deploying changes."
        },
        {
            "name": Phase.CODE_REVIEW.value,
            "tools": CODE_REVIEW_TOOLS,
            "description": "Review the implemented code for quality, correctness, and adherence to best practices through static analysis."
        },
        {
            "name": Phase.VERIFY.value,
            "tools": VERIFY_TOOLS,
            "description": "Test and validate the implementation by running tests, checking functionality, and verifying the solution meets requirements."
        },
        {
            "name": Phase.DELIVER.value,
            "tools": DELIVER_TOOLS,
            "description": "Finalize and deploy the solution by committing changes, deploying to production, and notifying stakeholders."
        }
    ]

    return {"phases": phases}
