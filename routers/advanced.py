"""
Advanced endpoints router for OpenClaw v4.x.

Includes:
- Oz integration (callback, reports, status)
- Reflections (list, stats, search)
- Proposals (create, list, get)
- Policy & Events
- Misc endpoints (ping, avatar, webhooks, streams)
- Mission Control & Job Viewer pages
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse

from routers.shared import (
    logger, DATA_DIR, AUTH_TOKEN, broadcast_event,
    get_event_engine, create_job,
    create_proposal, list_proposals, get_proposal, auto_approve_and_execute, get_policy,
    _event_log
)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# OZ INTEGRATION — Scheduled task callback, reports, status
# ═══════════════════════════════════════════════════════════════════════

@router.post("/api/oz/callback")
async def oz_callback(request: Request):
    """Handle Oz scheduled task results (nightly scans, weekly reviews, health checks).

    Oz agents call this endpoint to report results back to OpenClaw.
    Results are logged as events and stored in reports/.
    """
    try:
        data = await request.json()
        task_name = data.get("task_name", "unknown")
        task_id = data.get("task_id", "")
        status = data.get("status", "completed")
        output = data.get("output", "")
        findings = data.get("findings", [])

        # Store report
        import datetime as dt
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"{task_name.lower().replace(' ', '_')}_{timestamp}.json")
        with open(report_path, "w") as f:
            json.dump({"task_name": task_name, "task_id": task_id, "status": status,
                       "output": output, "findings": findings, "timestamp": timestamp}, f, indent=2)

        # Emit event
        engine = get_event_engine()
        if engine:
            engine.emit("oz.callback", {
                "task_name": task_name, "task_id": task_id, "status": status,
                "findings_count": len(findings), "report": report_path
            })

        # Auto-create jobs for critical findings
        jobs_created = []
        for finding in findings:
            if finding.get("severity") in ("critical", "high"):
                try:
                    job = create_job(
                        project=finding.get("project", "openclaw"),
                        task=f"[Oz {task_name}] {finding.get('description', 'Fix finding')}",
                        priority="P0" if finding["severity"] == "critical" else "P1"
                    )
                    jobs_created.append(job.id)
                    logger.info(f"Auto-created job {job.id} for {finding['severity']} finding")
                except Exception as je:
                    logger.warning(f"Failed to create job for finding: {je}")

        logger.info(f"Oz callback: {task_name} ({status}), {len(findings)} findings, {len(jobs_created)} jobs created")
        return {
            "received": True, "task_name": task_name, "report": report_path,
            "jobs_created": jobs_created
        }
    except Exception as e:
        logger.error(f"Oz callback error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/oz/reports")
async def oz_reports():
    """List all Oz scheduled task reports."""
    try:
        report_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        if not os.path.exists(report_dir):
            return {"reports": [], "total": 0}
        reports = []
        for f in sorted(os.listdir(report_dir), reverse=True)[:50]:
            if f.endswith(".json"):
                path = os.path.join(report_dir, f)
                try:
                    with open(path) as fh:
                        reports.append(json.load(fh))
                except Exception:
                    reports.append({"file": f, "error": "parse_failed"})
        return {"reports": reports, "total": len(reports)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/oz/status")
async def oz_agent_status():
    """Get Oz integration status — schedules, MCP bridge, environment."""
    try:
        # Check MCP bridge
        import aiohttp
        mcp_ok = False
        mcp_tools = 0
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8787/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        mcp_ok = True
                        mcp_tools = d.get("tools_available", 0)
        except Exception:
            pass

        # Check schedules
        schedules = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "oz", "schedule", "list", "--output-format", "json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if stdout:
                schedules = json.loads(stdout.decode())
        except Exception:
            pass

        return {
            "oz_available": os.path.exists("/usr/bin/oz"),
            "environment_id": os.environ.get("OZ_ENVIRONMENT_ID", "wguVnlBs2L6GmchuiGLKAL"),
            "mcp_bridge": {"running": mcp_ok, "tools": mcp_tools, "port": 8787},
            "schedules": schedules if isinstance(schedules, list) else [],
            "callback_endpoint": "/api/oz/callback",
            "reports_endpoint": "/api/oz/reports",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# REFLEXION LOOP — Self-improving agent memory
# ═══════════════════════════════════════════════════════════════════════

@router.get("/api/reflections")
async def api_list_reflections(request: Request):
    """List all reflections, optionally filtered by project."""
    try:
        from reflexion import list_reflections as reflexion_list
        project = request.query_params.get("project")
        limit = int(request.query_params.get("limit", "50"))
        refs = reflexion_list(project=project, limit=limit)
        return {"reflections": refs, "total": len(refs)}
    except Exception as e:
        logger.error(f"Reflections list error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/reflections/stats")
async def api_reflections_stats():
    """Get reflection statistics."""
    try:
        from reflexion import get_stats as reflexion_stats
        return reflexion_stats()
    except Exception as e:
        logger.error(f"Reflections stats error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/reflections/search")
async def api_search_reflections(request: Request):
    """Search reflections for a task description."""
    try:
        from reflexion import search_reflections as reflexion_search, format_reflections_for_prompt as fmt_reflections
        data = await request.json()
        task = data.get("task", "")
        project = data.get("project")
        limit = data.get("limit", 3)
        if not task:
            return JSONResponse({"error": "task required"}, status_code=400)
        refs = reflexion_search(task, project=project, limit=limit)
        return {
            "reflections": refs,
            "total": len(refs),
            "formatted": fmt_reflections(refs),
        }
    except Exception as e:
        logger.error(f"Reflections search error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# CLOSED LOOP — Proposals, Auto-Approval, Events, Policy
# ═══════════════════════════════════════════════════════════════════════

@router.post("/api/proposal/create")
async def api_create_proposal(request: Request):
    """Create a proposal and run it through auto-approval"""
    try:
        data = await request.json()
        proposal = create_proposal(
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            agent_pref=data.get("agent_pref", "project_manager"),
            tokens_est=data.get("tokens_est", 5000),
            tags=data.get("tags", []),
            auto_approve_threshold=data.get("auto_approve_threshold", 50),
        )
        logger.info(f"Proposal created: {proposal.id} cost=${proposal.cost_est_usd:.4f}")

        # Emit event
        engine = get_event_engine()
        if engine:
            engine.emit("proposal.created", {"proposal_id": proposal.id, "title": proposal.title, "cost": proposal.cost_est_usd})

        # Run through auto-approval
        result = auto_approve_and_execute(proposal.to_dict())

        return {
            "proposal_id": proposal.id,
            "cost_est_usd": proposal.cost_est_usd,
            "approval": result,
        }
    except Exception as e:
        logger.error(f"Proposal creation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/proposals")
async def api_list_proposals(status: Optional[str] = None):
    """List proposals, optionally filtered by status"""
    try:
        proposals = list_proposals(status=status)
        return {"proposals": [p.to_dict() for p in proposals], "total": len(proposals)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/proposal/{proposal_id}")
async def api_get_proposal(proposal_id: str):
    """Get a single proposal"""
    try:
        p = get_proposal(proposal_id)
        if not p:
            return JSONResponse({"error": "not found"}, status_code=404)
        return p.to_dict()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/policy")
async def api_get_policy():
    """Get current ops policy"""
    try:
        return get_policy()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# HEALTH & MISC ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/api/ping")
async def api_ping():
    """Simple health check endpoint"""
    import time
    return {"status": "pong", "timestamp": time.time()}


@router.get("/control/avatar/{name}")
async def api_control_avatar(name: str, meta: Optional[str] = None):
    """Return a placeholder for dashboard avatar requests."""
    return {"name": name, "avatar": None}


# ═══════════════════════════════════════════════════════════════════════
# EVENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/api/events")
async def api_get_events(limit: int = 50, event_type: Optional[str] = None, since: Optional[str] = None):
    """Get recent events. Optional ?since= ISO timestamp filter."""
    try:
        engine = get_event_engine()
        # Also read from persistent file if engine is empty
        events = []
        if engine:
            events = engine.get_recent_events(limit=200, event_type=event_type)

        # Supplement from events.jsonl if we have few in-memory events
        if len(events) < limit:
            events_file = os.path.join(DATA_DIR, "events", "events.jsonl")
            if os.path.exists(events_file):
                with open(events_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                            if event_type and evt.get("event_type") != event_type:
                                continue
                            events.append(evt)
                        except:
                            continue

        # Deduplicate by event_id
        seen = set()
        unique = []
        for e in events:
            eid = e.get("event_id") or e.get("id") or id(e)
            if eid not in seen:
                seen.add(eid)
                unique.append(e)
        events = unique

        # Filter by since timestamp
        if since:
            events = [e for e in events if (e.get("timestamp", "") or "") > since]

        # Sort by timestamp descending, limit
        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        events = events[:limit]
        return {"events": events, "total": len(events)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/events")
async def api_post_event(request: Request):
    """Create a new event."""
    try:
        body = await request.json()
        event_type = body.get("event_type", "custom")
        data = body.get("data", body)
        engine = get_event_engine()
        if not engine:
            return JSONResponse({"error": "Event engine not available"}, status_code=503)
        event_id = engine.emit(event_type, data)
        return {"ok": True, "event_id": event_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/events/stream")
async def event_stream():
    """SSE endpoint for real-time dashboard updates"""
    async def generate():
        last_index = len(_event_log)
        while True:
            await asyncio.sleep(1)
            current_len = len(_event_log)
            if current_len > last_index:
                for event in _event_log[last_index:current_len]:
                    yield f"data: {json.dumps(event)}\n\n"
                last_index = current_len

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/api/events/recent")
async def recent_events():
    """Get recent events (non-streaming fallback)"""
    return {"success": True, "events": _event_log[-50:], "total": len(_event_log)}


# ═══════════════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/webhook/openclaw-jobs")
async def n8n_openclaw_jobs_webhook(request: Request):
    """Receive OpenClaw job events from n8n workflows.

    This endpoint is called by the event_engine when job events occur:
    - job.created: new job submitted
    - job.completed: job finished successfully
    - job.failed: job encountered an error
    - job.approved: job was approved
    - job.phase_change: job moved to a new phase
    """
    try:
        body = await request.json()
        event_type = body.get("event_type", "unknown")
        event_id = body.get("event_id", "")
        data = body.get("data", {})

        logger.info(
            f"n8n webhook received: event_type={event_type}, event_id={event_id}, "
            f"job_id={data.get('job_id', 'N/A')}"
        )

        # Log to a dedicated webhook event log for pipeline monitoring
        # Use runtime env lookup so tests can monkeypatch OPENCLAW_DATA_DIR
        _data_dir = os.environ.get("OPENCLAW_DATA_DIR", DATA_DIR)
        webhook_log_path = os.path.join(_data_dir, "webhooks", "n8n_events.jsonl")
        os.makedirs(os.path.dirname(webhook_log_path), exist_ok=True)

        record = {
            "webhook_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "event_id": event_id,
            "data": data,
        }

        with open(webhook_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")

        return {
            "ok": True,
            "message": f"Event {event_type} received and logged",
            "event_id": event_id
        }
    except Exception as e:
        logger.error(f"n8n webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/webhook/slack-test")
async def slack_webhook_test(request: Request):
    """Test endpoint for Slack webhook events from n8n workflows.

    This endpoint accepts Slack message payloads and logs them for testing.
    In production, replace with actual Slack incoming webhook integration.
    """
    try:
        body = await request.json()

        # Log the incoming message
        logger.info(f"Slack webhook test received: {body.get('text', 'no text')[:100]}")

        # Log to a dedicated webhook log for monitoring
        _data_dir = os.environ.get("OPENCLAW_DATA_DIR", DATA_DIR)
        slack_log_path = os.path.join(_data_dir, "webhooks", "slack_test.jsonl")
        os.makedirs(os.path.dirname(slack_log_path), exist_ok=True)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text": body.get("text", ""),
            "attachments": len(body.get("attachments", [])),
        }

        with open(slack_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")

        return {
            "ok": True,
            "message": "Slack webhook test received",
        }
    except Exception as e:
        logger.error(f"Slack test webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD & UI PAGES
# ═══════════════════════════════════════════════════════════════════════

@router.get("/oz")
@router.get("/oz-status")
async def oz_status_page():
    """Serve Oz Cloud Agent status & capabilities page"""
    oz_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "oz_status.html")
    try:
        with open(oz_path, "r") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Oz status page not found</h1>", status_code=404)


@router.get("/mission-control")
@router.get("/mission-control.html")
async def mission_control_page():
    """Serve Mission Control v4.0 dashboard"""
    mc_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mission_control.html")
    try:
        with open(mc_path, "r") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard.html", status_code=302)


@router.get("/job-viewer")
@router.get("/job-viewer.html")
@router.get("/job_viewer.html")
async def job_viewer_page():
    """Serve Job Execution Viewer"""
    jv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "job_viewer.html")
    try:
        with open(jv_path, "r") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Job Viewer not found</h1>", status_code=404)
