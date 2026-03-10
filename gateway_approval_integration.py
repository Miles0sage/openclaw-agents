"""
Gateway Integration Module for Personal Assistant Approval System

This module provides the integration layer between the OpenClaw Gateway
and the Personal Assistant approval system.

Installation Instructions:
1. Add imports to gateway.py (see IMPORTS section below)
2. Add initialization in main section (see INITIALIZATION section)
3. Add endpoints to FastAPI app (see ENDPOINTS section)
4. Modify chat_endpoint() to use approval flow (see MIDDLEWARE section)
"""

# ═══════════════════════════════════════════════════════════════════════
# IMPORTS - Add these to gateway.py imports section
# ═══════════════════════════════════════════════════════════════════════

from datetime import datetime, timezone

# from approval_client import ApprovalClient, ExecutionSummary, ApprovalStatus
# from task_queue import TaskQueue, TaskStatus
# import time

# ═══════════════════════════════════════════════════════════════════════
# INITIALIZATION - Add to app startup section in gateway.py
# ═══════════════════════════════════════════════════════════════════════

"""
# Initialize approval client
APPROVAL_CLIENT = None
TASK_QUEUE = None

@app.on_event("startup")
async def startup_approval_system():
    global APPROVAL_CLIENT, TASK_QUEUE

    approval_url = os.getenv("APPROVAL_SYSTEM_URL", "http://localhost:8001")
    approval_key = os.getenv("APPROVAL_API_KEY", "")

    APPROVAL_CLIENT = ApprovalClient(
        assistant_url=approval_url,
        api_key=approval_key,
        timeout=10.0,
        fallback_strict=True
    )

    TASK_QUEUE = TaskQueue(
        persistence_dir=os.getenv("OPENCLAW_TASKS_DIR", os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "./data"), "tasks")),
        auto_save=True
    )

    logger.info("✅ Approval system initialized")
    logger.info(f"   - Assistant URL: {approval_url}")
    logger.info(f"   - Fallback Mode: {'Strict' if APPROVAL_CLIENT.fallback_strict else 'Permissive'}")

    # Start health check task
    asyncio.create_task(APPROVAL_CLIENT.periodic_health_check())

@app.on_event("shutdown")
async def shutdown_approval_system():
    global APPROVAL_CLIENT, TASK_QUEUE
    if TASK_QUEUE:
        logger.info("💾 Saving task queue state...")
        TASK_QUEUE._save_to_disk()
    logger.info("✅ Approval system shut down")
"""

# ═══════════════════════════════════════════════════════════════════════
# MIDDLEWARE - Modify chat_endpoint() with approval flow
# ═══════════════════════════════════════════════════════════════════════

"""
# Replace the existing @app.post("/api/chat") endpoint with this:

@app.post("/api/chat")
async def chat_endpoint(message: Message):
    '''REST chat with optional session memory and approval workflow'''

    session_key = message.sessionKey or "default"
    project_id = message.project_id or "default"
    task_id = str(uuid.uuid4())

    # ═ APPROVAL WORKFLOW
    if APPROVAL_CLIENT and TASK_QUEUE:
        # Enqueue task
        TASK_QUEUE.enqueue(
            task_id=task_id,
            task_type="chat",
            description=message.content[:100],
            estimated_cost=0.01,  # Rough estimate
            context={"session_key": session_key, "project_id": project_id}
        )

        # Request approval
        TASK_QUEUE.set_pending_approval(task_id)
        approval_response, in_fallback = await APPROVAL_CLIENT.request_approval(
            task_id=task_id,
            task_type="chat",
            description=message.content[:100],
            estimated_cost=0.01,
            context={"session_key": session_key}
        )

        if not approval_response.approved:
            TASK_QUEUE.reject_task(task_id, approval_response.reason)
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": "Task rejected by personal assistant",
                    "reason": approval_response.reason,
                    "task_id": task_id,
                    "fallback_mode": in_fallback
                }
            )

        # Apply constraints if any
        task_config = {}
        if approval_response.constraints:
            task_config = APPROVAL_CLIENT.apply_constraints(task_config, approval_response.constraints)

        TASK_QUEUE.approve_task(task_id, approval_response.reason,
                               [c.to_dict() if hasattr(c, 'to_dict') else c
                                for c in (approval_response.constraints or [])])

    # ... rest of existing chat_endpoint code ...
    # At the end, add:

    if TASK_QUEUE:
        actual_cost = tokens * 0.00002  # Rough calculation
        TASK_QUEUE.complete_task(
            task_id=task_id,
            result=response_text[:500],
            actual_cost=actual_cost,
            logs=json.dumps({"tokens": tokens, "agent": agent_id})
        )

        # Report to personal assistant
        await APPROVAL_CLIENT.report_execution(
            ExecutionSummary(
                task_id=task_id,
                status="completed",
                result=response_text[:500],
                actual_cost=actual_cost,
                start_time=datetime.now(timezone.utc).isoformat() + "Z",
                end_time=datetime.now(timezone.utc).isoformat() + "Z"
            )
        )
"""

# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - Add these new endpoints to gateway.py
# ═══════════════════════════════════════════════════════════════════════

endpoints_code = '''
# ═══════════════════════════════════════════════════════════════════════
# APPROVAL SYSTEM ENDPOINTS
# GET  /api/queue/status        - Get queue status
# GET  /api/queue/tasks         - List all tasks
# GET  /api/queue/task/{id}     - Get task details
# POST /api/queue/approve/{id}  - Manually approve task
# POST /api/queue/reject/{id}   - Manually reject task
# POST /api/queue/abort/{id}    - Abort running task
# GET  /api/approval/health     - Check approval system health
# ═══════════════════════════════════════════════════════════════════════

class ApprovalManualRequest(BaseModel):
    """Request to manually approve/reject a task"""
    reason: str
    constraints: Optional[list] = None

@app.get("/api/queue/status")
async def queue_status_endpoint():
    """Get current task queue status"""
    if not TASK_QUEUE:
        return {"error": "Task queue not initialized", "status": "disabled"}

    status = TASK_QUEUE.get_queue_status()
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "data": status
    }

@app.get("/api/queue/tasks")
async def queue_list_endpoint(
    status: Optional[str] = None,
    limit: Optional[int] = 100,
    offset: Optional[int] = 0
):
    """List tasks in queue"""
    if not TASK_QUEUE:
        return {"error": "Task queue not initialized"}

    tasks = list(TASK_QUEUE.tasks.values())

    if status:
        tasks = [t for t in tasks if t.status == status]

    # Sort by created_at descending
    tasks.sort(key=lambda t: t.created_at, reverse=True)

    total = len(tasks)
    tasks = tasks[offset:offset+limit]

    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "total": total,
        "offset": offset,
        "limit": limit,
        "tasks": [t.to_dict() for t in tasks]
    }

@app.get("/api/queue/task/{task_id}")
async def queue_task_endpoint(task_id: str):
    """Get details for a specific task"""
    if not TASK_QUEUE:
        return {"error": "Task queue not initialized"}

    task = TASK_QUEUE.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": f"Task not found: {task_id}"
        })

    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "task": task.to_dict()
    }

@app.post("/api/queue/approve/{task_id}")
async def queue_approve_endpoint(task_id: str, req: ApprovalManualRequest):
    """Manually approve a task"""
    if not TASK_QUEUE:
        return JSONResponse(status_code=503, content={"error": "Task queue not initialized"})

    task = TASK_QUEUE.approve_task(task_id, req.reason, req.constraints)
    if not task:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": f"Task not found: {task_id}"
        })

    logger.info(f"✅ Task manually approved: {task_id}")
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "task": task.to_dict()
    }

@app.post("/api/queue/reject/{task_id}")
async def queue_reject_endpoint(task_id: str, req: ApprovalManualRequest):
    """Manually reject a task"""
    if not TASK_QUEUE:
        return JSONResponse(status_code=503, content={"error": "Task queue not initialized"})

    task = TASK_QUEUE.reject_task(task_id, req.reason)
    if not task:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": f"Task not found: {task_id}"
        })

    logger.warning(f"❌ Task manually rejected: {task_id}")
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "task": task.to_dict()
    }

@app.post("/api/queue/abort/{task_id}")
async def queue_abort_endpoint(task_id: str):
    """Abort a running task"""
    if not TASK_QUEUE:
        return JSONResponse(status_code=503, content={"error": "Task queue not initialized"})

    task = TASK_QUEUE.abort_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": f"Task not found: {task_id}"
        })

    logger.warning(f"🛑 Task aborted: {task_id}")
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "task": task.to_dict()
    }

@app.get("/api/approval/health")
async def approval_health_endpoint():
    """Check health of approval system"""
    if not APPROVAL_CLIENT:
        return JSONResponse(status_code=503, content={
            "success": False,
            "status": "disabled"
        })

    is_healthy = await APPROVAL_CLIENT.get_health()

    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "approval_system": {
            "healthy": is_healthy,
            "fallback_mode": APPROVAL_CLIENT.fallback_mode,
            "assistant_url": APPROVAL_CLIENT.assistant_url
        }
    }
'''

print(endpoints_code)
