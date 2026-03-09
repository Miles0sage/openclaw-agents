"""
FastAPI APIRouter for workflow, job, CEO, and MCP endpoints.

This module contains all workflow orchestration, autonomous job management,
CEO engine, and MCP tool server endpoints extracted from gateway.py.
"""

import os
import json
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse

from routers.shared import (
    workflow_engine,
    get_ceo_engine,
    get_event_engine,
    broadcast_event,
    call_model_for_agent,
    get_agent_config,
    get_memory_manager,
    get_cron_scheduler,
    create_job,
    get_job,
    list_jobs,
    update_job_status,
    validate_job,
    JobValidationError,
    log_cost_event,
    logger,
)

router = APIRouter(prefix="/api", tags=["workflows"])

# ═══════════════════════════════════════════════════════════════════════
# WORKFLOW ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

WORKFLOW_TEMPLATES = {
    "code_review": {
        "name": "Code Review",
        "description": "Review code changes for quality and correctness",
        "steps": [
            {"agent": "code_reviewer", "task": "Review the provided code changes"},
            {"agent": "project_manager", "task": "Summarize findings and recommendations"}
        ]
    },
    "feature_build": {
        "name": "Feature Build",
        "description": "Build a new feature from requirements to deployment",
        "steps": [
            {"agent": "project_manager", "task": "Break down the feature into implementation tasks"},
            {"agent": "coder_agent", "task": "Implement the feature based on the plan"},
            {"agent": "code_reviewer", "task": "Review the implementation"},
            {"agent": "project_manager", "task": "Plan deployment strategy"}
        ]
    },
    "bug_investigation": {
        "name": "Bug Investigation",
        "description": "Investigate and resolve a reported bug",
        "steps": [
            {"agent": "project_manager", "task": "Understand the bug and reproduction steps"},
            {"agent": "elite_coder", "task": "Debug and find root cause"},
            {"agent": "coder_agent", "task": "Implement the fix"},
            {"agent": "code_reviewer", "task": "Review the fix"}
        ]
    }
}

def _load_workflows() -> list:
    """Load workflows from disk."""
    workflows_path = os.path.join(os.path.dirname(__file__), "..", "data", "workflows.json")
    if os.path.exists(workflows_path):
        try:
            with open(workflows_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load workflows: {e}")
    return []

def _save_workflows(workflows: list):
    """Save workflows to disk."""
    workflows_path = os.path.join(os.path.dirname(__file__), "..", "data", "workflows.json")
    os.makedirs(os.path.dirname(workflows_path), exist_ok=True)
    try:
        with open(workflows_path, "w") as f:
            json.dump(workflows, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save workflows: {e}")

async def _execute_workflow(workflow_id: str):
    """Execute workflow steps sequentially, passing output forward."""
    workflows = _load_workflows()
    workflow = None
    for wf in workflows:
        if wf["id"] == workflow_id:
            workflow = wf
            break

    if not workflow:
        return

    workflow["status"] = "running"
    workflow["started_at"] = datetime.now(timezone.utc).isoformat() + "Z"
    _save_workflows(workflows)

    broadcast_event({"type": "workflow_started", "agent": "system",
                     "message": f"Workflow '{workflow.get('name', workflow_id)}' started"})

    previous_output = ""

    for i, step in enumerate(workflow["steps"]):
        workflows = _load_workflows()
        for wf in workflows:
            if wf["id"] == workflow_id:
                workflow = wf
                break

        if workflow["status"] == "cancelled":
            break

        workflow["current_step"] = i
        _save_workflows(workflows)

        agent_id = step.get("agent", "project_manager")
        task = step.get("task", "")

        if previous_output:
            task = f"Previous step output:\n{previous_output}\n\nYour task: {task}"

        broadcast_event({"type": "workflow_step_start", "agent": agent_id,
                         "message": f"Workflow step {i+1}/{len(workflow['steps'])}: {step.get('task', '')[:60]}"})

        try:
            response_text, tokens = call_model_for_agent(agent_id, task)

            step_result = {
                "step": i,
                "agent": agent_id,
                "task": step.get("task", ""),
                "status": "completed",
                "response": response_text,
                "tokens": tokens,
                "completed_at": datetime.now(timezone.utc).isoformat() + "Z"
            }
            previous_output = response_text

            agent_cfg = get_agent_config(agent_id)
            try:
                log_cost_event(
                    project="openclaw",
                    agent=agent_id,
                    model=agent_cfg.get("model", "unknown"),
                    tokens_input=len(task.split()),
                    tokens_output=tokens
                )
            except Exception as e:
                logger.warning(f"Cost logging failed: {e}")

            workflow["results"].append(step_result)

            broadcast_event({"type": "workflow_step_completed", "agent": agent_id,
                             "message": f"Step {i+1} completed"})

        except Exception as e:
            logger.error(f"Workflow step failed: {e}")
            step_result = {
                "step": i,
                "agent": agent_id,
                "task": step.get("task", ""),
                "status": "failed",
                "error": str(e),
                "failed_at": datetime.now(timezone.utc).isoformat() + "Z"
            }
            workflow["results"].append(step_result)
            workflow["status"] = "failed"
            break

    workflow["status"] = workflow.get("status", "completed")
    if workflow["status"] == "running":
        workflow["status"] = "completed"
    workflow["completed_at"] = datetime.now(timezone.utc).isoformat() + "Z"
    _save_workflows(workflows)

    broadcast_event({"type": "workflow_completed", "agent": "system",
                     "message": f"Workflow '{workflow.get('name', workflow_id)}' {workflow['status']}"})

@router.post("/workflow/start")
async def start_workflow(request: Request):
    """Start a new workflow"""
    try:
        data = await request.json()
        workflow_name = data.get("workflow", "")
        params = data.get("params", {})

        if not workflow_name:
            return JSONResponse({"error": "workflow name required"}, status_code=400)

        workflow_id = workflow_engine.start_workflow(workflow_name, params)
        logger.info(f"Workflow started: {workflow_id} ({workflow_name})")

        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": "started",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Workflow start error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/workflow/status/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """Get workflow status"""
    try:
        status = workflow_engine.get_workflow_status(workflow_id)
        if not status:
            return JSONResponse({"error": "workflow not found"}, status_code=404)

        return {
            "workflow_id": workflow_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Workflow status error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/workflows")
async def create_workflow_endpoint(request: Request):
    """Create and optionally start a new workflow"""
    body = await request.json()
    steps = body.get("steps", [])
    name = body.get("name", "Unnamed Workflow")
    auto_start = body.get("auto_start", False)

    if not steps:
        raise HTTPException(status_code=400, detail="Workflow must have at least one step")

    workflow_id = str(uuid.uuid4())[:8]
    workflow = {
        "id": workflow_id,
        "name": name,
        "steps": steps,
        "status": "created",
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "results": [],
        "current_step": 0
    }

    workflows = _load_workflows()
    workflows.append(workflow)
    _save_workflows(workflows)

    if auto_start:
        asyncio.create_task(_execute_workflow(workflow_id))
        workflow["status"] = "running"

    broadcast_event({"type": "workflow_created", "agent": "system",
                     "message": f"Workflow '{name}' created ({len(steps)} steps)"})

    return {"success": True, "workflow": workflow}


@router.get("/workflows")
async def list_workflows_endpoint():
    """List all workflows"""
    workflows = _load_workflows()
    return {"success": True, "workflows": workflows, "total": len(workflows)}


@router.get("/workflows/templates")
async def list_workflow_templates():
    """List available workflow templates"""
    templates = {
        name: {"name": t["name"], "description": t["description"], "steps_count": len(t["steps"])}
        for name, t in WORKFLOW_TEMPLATES.items()
    }
    return {"success": True, "templates": templates, "total": len(templates)}


@router.post("/workflows/templates/{template_name}")
async def create_workflow_from_template(template_name: str, request: Request):
    """Create and start a workflow from a template. Optionally pass context in request body."""
    if template_name not in WORKFLOW_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found. Available: {', '.join(WORKFLOW_TEMPLATES.keys())}")

    template = WORKFLOW_TEMPLATES[template_name]
    try:
        body = await request.json()
    except Exception:
        body = {}
    context = body.get("context", "")
    auto_start = body.get("auto_start", True)

    steps = []
    for i, step in enumerate(template["steps"]):
        new_step = dict(step)
        if i == 0 and context:
            new_step["task"] = f"Context: {context}\n\n{new_step['task']}"
        steps.append(new_step)

    workflow_id = str(uuid.uuid4())[:8]
    workflow = {
        "id": workflow_id,
        "name": f"{template['name']} ({workflow_id})",
        "template": template_name,
        "steps": steps,
        "status": "created",
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "results": [],
        "current_step": 0,
        "context": context[:500] if context else ""
    }

    workflows = _load_workflows()
    workflows.append(workflow)
    _save_workflows(workflows)

    if auto_start:
        asyncio.create_task(_execute_workflow(workflow_id))
        workflow["status"] = "running"

    broadcast_event({"type": "workflow_created", "agent": "system",
                     "message": f"Template '{template_name}' started ({len(steps)} steps)"})

    return {"success": True, "workflow": workflow}


@router.get("/workflows/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str):
    """Get workflow status and results"""
    workflows = _load_workflows()
    for wf in workflows:
        if wf["id"] == workflow_id:
            return {"success": True, "workflow": wf}
    raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")


@router.delete("/workflows/{workflow_id}")
async def cancel_workflow_endpoint(workflow_id: str):
    """Cancel a running workflow"""
    workflows = _load_workflows()
    for wf in workflows:
        if wf["id"] == workflow_id:
            wf["status"] = "cancelled"
            wf["cancelled_at"] = datetime.now(timezone.utc).isoformat() + "Z"
            break
    _save_workflows(workflows)
    broadcast_event({"type": "workflow_cancelled", "agent": "system",
                     "message": f"Workflow {workflow_id} cancelled"})
    return {"success": True, "message": f"Workflow {workflow_id} cancelled"}


@router.post("/workflows/{workflow_id}/start")
async def start_workflow_endpoint(workflow_id: str):
    """Start a created workflow"""
    asyncio.create_task(_execute_workflow(workflow_id))
    return {"success": True, "message": f"Workflow {workflow_id} started"}


# ═══════════════════════════════════════════════════════════════════════
# AUTONOMOUS JOB QUEUE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/job/create")
async def create_new_job(request: Request):
    """Create a new autonomous job. Supports optional X-Client-Key for billing."""
    try:
        data = await request.json()
        project = data.get("project", "unknown")
        task = data.get("task", "")
        priority = data.get("priority", "P1")

        client_key = request.headers.get("X-Client-Key")
        client_record = None
        if client_key:
            from client_auth import authenticate_client, check_job_limit, deduct_credit
            client_record = authenticate_client(client_key)
            if not client_record:
                return JSONResponse({"error": "Invalid or inactive API key"}, status_code=401)
            can_submit, reason = check_job_limit(client_record)
            if not can_submit:
                return JSONResponse({"error": f"Plan limit reached: {reason}"}, status_code=429)

        try:
            validate_job(project, task, priority)
        except JobValidationError as ve:
            return JSONResponse({"error": str(ve)}, status_code=400)

        try:
            import asyncio
            from prompt_shield import scan_input
            scan_result = await asyncio.to_thread(scan_input, task)
            if scan_result.blocked:
                logger.warning(f"Job blocked by prompt shield: {scan_result.reason}")
                return JSONResponse({"error": f"Input blocked: {scan_result.reason}"}, status_code=422)
        except ImportError:
            pass

        import asyncio as _asyncio
        job = await _asyncio.to_thread(create_job, project, task, priority)

        if client_record:
            try:
                deduct_credit(client_record["client_id"], reason=f"job:{job.id}")
            except Exception as e:
                logger.warning(f"Credit deduction failed for {client_record['client_id']}: {e}")
        logger.info(f"Job created: {job.id}")

        engine = get_event_engine()
        if engine:
            engine.emit("job.created", {"job_id": job.id, "project": project, "task": task, "priority": priority})

        return {
            "job_id": job.id,
            "project": project,
            "task": task,
            "status": "pending",
            "created_at": job.created_at
        }
    except JobValidationError:
        raise
    except Exception as e:
        logger.error(f"Job creation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status"""
    try:
        job = get_job(job_id)
        if not job:
            return JSONResponse({"error": "job not found"}, status_code=404)

        return job
    except Exception as e:
        logger.error(f"Job status error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/jobs")
async def list_all_jobs(
    status: str = "all",
    project: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List jobs, optionally filtered by status/project."""
    try:
        jobs = list_jobs(status=status, project=project, limit=limit, offset=offset)
        normalized = []
        for j in jobs:
            if isinstance(j, dict) and "job_id" not in j and "id" in j:
                j = {**j, "job_id": j.get("id")}
            normalized.append(j)
        return {"jobs": normalized, "total": len(normalized)}
    except Exception as e:
        logger.error(f"List jobs error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/jobs/stats")
async def get_jobs_stats():
    """Aggregate counts by status for observability."""
    try:
        from supabase_client import table_count

        pending = table_count("jobs", "status=eq.pending", select="id")
        running = table_count("jobs", "status=eq.running", select="id")
        failed = table_count("jobs", "status=in.(failed,error)", select="id")
        # DLQ table may not have an `id` column; use job_id.
        dlq = table_count("dead_letter_queue", "resolved=is.false", select="job_id")
        return {"pending": pending, "running": running, "failed": failed, "dlq": dlq}
    except Exception as e:
        logger.error(f"Jobs stats error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/job/{job_id}/approve")
async def approve_job(job_id: str, request: Request):
    """Approve a job for merging"""
    try:
        data = await request.json()
        approved_by = data.get("approved_by", "user")

        update_job_status(job_id, "approved", approved_by=approved_by)
        logger.info(f"Job approved: {job_id}")

        engine = get_event_engine()
        if engine:
            engine.emit("job.approved", {"job_id": job_id, "approved_by": approved_by})

        return {"job_id": job_id, "status": "approved", "approved_by": approved_by}
    except Exception as e:
        logger.error(f"Job approval error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# CEO ENGINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/ceo/status")
async def ceo_status():
    """Get AI CEO engine status, goals, and schedule."""
    ceo = get_ceo_engine()
    if not ceo:
        return JSONResponse({"error": "CEO engine not initialized"}, status_code=503)
    return ceo.get_status()


@router.get("/ceo/decisions")
async def ceo_decisions(limit: int = 50):
    """Get recent CEO decisions."""
    ceo = get_ceo_engine()
    if not ceo:
        return JSONResponse({"error": "CEO engine not initialized"}, status_code=503)
    return {"decisions": ceo.get_decisions(limit), "total": len(ceo.get_decisions(limit))}


@router.get("/ceo/goals")
async def ceo_goals():
    """Get all strategic goals."""
    ceo = get_ceo_engine()
    if not ceo:
        return JSONResponse({"error": "CEO engine not initialized"}, status_code=503)
    return {"goals": ceo.goals}


@router.post("/ceo/goals")
async def ceo_add_goal(request: Request):
    """Add a new strategic goal."""
    ceo = get_ceo_engine()
    if not ceo:
        return JSONResponse({"error": "CEO engine not initialized"}, status_code=503)
    body = await request.json()
    title = body.get("title")
    if not title:
        return JSONResponse({"error": "title is required"}, status_code=400)
    goal = ceo.add_goal(
        title=title,
        priority=body.get("priority", "P1"),
        metrics=body.get("metrics", []),
    )
    return {"goal": goal}


@router.put("/ceo/goals/{goal_id}")
async def ceo_update_goal(goal_id: str, request: Request):
    """Update a strategic goal."""
    ceo = get_ceo_engine()
    if not ceo:
        return JSONResponse({"error": "CEO engine not initialized"}, status_code=503)
    body = await request.json()
    goal = ceo.update_goal(goal_id, **body)
    if not goal:
        return JSONResponse({"error": f"Goal {goal_id} not found"}, status_code=404)
    return {"goal": goal}


@router.post("/ceo/trigger/{task_name}")
async def ceo_trigger_task(task_name: str):
    """Manually trigger a CEO autonomous task."""
    ceo = get_ceo_engine()
    if not ceo:
        return JSONResponse({"error": "CEO engine not initialized"}, status_code=503)
    result = await ceo.trigger_task(task_name)
    return result


# ═══════════════════════════════════════════════════════════════════════
# MCP TOOL SERVERS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/mcp/servers")
async def mcp_list_servers():
    """List available MCP tool servers and their tools."""
    import json as _json
    servers = []
    mcp_dir = os.path.join(os.path.dirname(__file__), "..", "mcp_servers")
    for name in ["restaurant", "barbershop"]:
        manifest = os.path.join(mcp_dir, name, "server.json")
        if os.path.exists(manifest):
            with open(manifest) as f:
                servers.append(_json.load(f))
    return {"servers": servers, "count": len(servers)}


@router.post("/mcp/{server_name}/call")
async def mcp_call_tool(server_name: str, request: Request):
    """Call a tool on an MCP server. Body: {tool, arguments, api_key?}"""
    import json as _json
    body = await request.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})
    api_key = body.get("api_key", "")

    if not tool_name:
        return JSONResponse({"error": "tool name required"}, status_code=400)

    from mcp_servers.shared.billing import UsageTracker, APIKeyManager, billing_check
    tracker = UsageTracker(server_name)
    key_mgr = APIKeyManager(server_name)
    block = billing_check(tracker, key_mgr, api_key, tool_name)
    if block:
        return JSONResponse(block, status_code=429)

    try:
        if server_name == "restaurant":
            from mcp_servers.restaurant.server import mcp as srv
        elif server_name == "barbershop":
            from mcp_servers.barbershop.server import mcp as srv
        else:
            return JSONResponse({"error": f"Unknown server: {server_name}"}, status_code=404)

        result = await srv.call_tool(tool_name, arguments)
        text = result.content[0].text if result.content else "{}"
        try:
            data = _json.loads(text)
        except Exception:
            data = {"result": text}
        return {"tool": tool_name, "server": server_name, "result": data}
    except Exception as e:
        logger.error(f"MCP call error: {server_name}/{tool_name}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/mcp/{server_name}/tools")
async def mcp_list_tools(server_name: str):
    """List tools available on an MCP server."""
    try:
        if server_name == "restaurant":
            from mcp_servers.restaurant.server import mcp as srv
        elif server_name == "barbershop":
            from mcp_servers.barbershop.server import mcp as srv
        else:
            return JSONResponse({"error": f"Unknown server: {server_name}"}, status_code=404)

        tools = await srv.list_tools()
        return {
            "server": server_name,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema if hasattr(t, "inputSchema") else {},
                }
                for t in tools
            ],
            "count": len(tools),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/mcp/keys")
async def mcp_create_api_key(request: Request):
    """Create an API key for an MCP server. Body: {server, owner, tier?}"""
    body = await request.json()
    server = body.get("server")
    owner = body.get("owner")
    tier = body.get("tier", "free")
    if not server or not owner:
        return JSONResponse({"error": "server and owner required"}, status_code=400)
    from mcp_servers.shared.billing import APIKeyManager
    mgr = APIKeyManager(server)
    key = mgr.create_key(owner, tier)
    return {"api_key": key, "server": server, "owner": owner, "tier": tier}


@router.get("/mcp/{server_name}/usage")
async def mcp_usage(server_name: str, api_key: str = "anonymous"):
    """Get usage stats for an API key on a server."""
    from mcp_servers.shared.billing import UsageTracker
    tracker = UsageTracker(server_name)
    usage = tracker.get_usage(api_key)
    return {"server": server_name, "usage": usage}
