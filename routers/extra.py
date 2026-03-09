"""
Extra Router — Miscellaneous endpoints that don't fit other routers.

Includes:
- /api/reviews/* (review cycle management)
- /api/verify (output verification)
- /api/leads/find* (lead finder)
- /api/pinch/* (browser automation)
- /api/calls/* (sales calls)
- /api/runner/* (job runner status)
- /api/pa/* (personal assistant bridge)
- /api/leads (lead capture)
- /api/eval/* (eval harness)
- /api/security/* (security scanning)
- /api/onboard* (client onboarding)
- /api/hands/* (scheduled hands management)
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from routers.shared import (
    logger,
    DATA_DIR,
    JSONResponse,
    HTTPException,
    Request,
    get_runner,
    send_slack_message,
    get_event_engine,
)
from job_manager import create_job
from autonomous_runner import _set_kill_flag, _load_kill_flags

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════════════════
# REVIEW CYCLE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

_review_engine = None  # Will be initialized by gateway

@router.post("/api/reviews")
async def start_review(request: Request):
    """Start a new agent-to-agent review cycle"""
    if not _review_engine:
        raise HTTPException(status_code=503, detail="Review engine not initialized")
    data = await request.json()
    work_type = data.get("type", "code_review")
    content = data.get("content", "")
    author = data.get("author_agent", "coder_agent")
    reviewers = data.get("reviewer_agents", [])
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    review_id = _review_engine.start_review(work_type, content, author, reviewers)
    return {"success": True, "review_id": review_id, "type": work_type}


@router.get("/api/reviews")
async def list_reviews():
    """List all reviews"""
    if not _review_engine:
        return {"reviews": [], "stats": {}}
    active = _review_engine.list_active_reviews()
    all_reviews = _review_engine.list_all_reviews()
    stats = _review_engine.get_stats()
    return {"active": active, "all": all_reviews, "stats": stats}


@router.get("/api/reviews/{review_id}")
async def get_review(review_id: str):
    """Get review status and details"""
    if not _review_engine:
        raise HTTPException(status_code=503, detail="Review engine not initialized")
    status = _review_engine.get_review_status(review_id)
    if not status:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"success": True, **status}


@router.delete("/api/reviews/{review_id}")
async def cancel_review(review_id: str):
    """Cancel an active review"""
    if not _review_engine:
        raise HTTPException(status_code=503, detail="Review engine not initialized")
    success = _review_engine.cancel_review(review_id)
    return {"success": success}


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT VERIFICATION ENDPOINTS — Quality gates
# ═══════════════════════════════════════════════════════════════════════════════

_output_verifier = None  # Will be initialized by gateway

@router.post("/api/verify")
async def verify_output(request: Request):
    """Run quality gates on files"""
    if not _output_verifier:
        raise HTTPException(status_code=503, detail="Verifier not initialized")
    data = await request.json()
    files = data.get("files", [])
    work_dir = data.get("work_dir", ".")
    job_id = data.get("job_id")
    result = _output_verifier.verify_all(job_id or "manual", files, work_dir)
    return {
        "success": True,
        "passed": result.passed,
        "score": result.overall_score,
        "recommendation": result.recommendation,
        "summary": result.summary,
        "gates": [{"gate": g.gate, "passed": g.passed, "score": g.score,
                    "issues_count": len(g.issues)} for g in result.gates]
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LEAD FINDER — Google Maps / Search for real businesses
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/leads/find")
async def find_leads_endpoint(
    type: str = "restaurants",
    location: str = "Flagstaff, AZ",
    limit: int = 10,
    save: bool = True,
):
    """Search Google for real businesses and create leads automatically."""
    try:
        from lead_finder import find_leads
        leads = await find_leads(type, location, limit, save)
        return {
            "success": True,
            "business_type": type,
            "location": location,
            "leads": leads,
            "total": len(leads),
        }
    except Exception as e:
        logger.error(f"Lead finder error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/leads/find-all")
async def find_all_leads_endpoint(
    location: str = "Flagstaff, AZ",
    limit: int = 5,
):
    """Search Google for ALL business types at once."""
    try:
        from lead_finder import find_leads_multi
        types = ["restaurants", "barbershops", "dental offices", "auto repair shops", "real estate agencies"]
        results = await find_leads_multi(types, location, limit)
        total = sum(len(v) for v in results.values())
        return {
            "success": True,
            "location": location,
            "results": {k: len(v) for k, v in results.items()},
            "total_leads": total,
            "leads": results,
        }
    except Exception as e:
        logger.error(f"Lead finder multi error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════════════
# PINCHTAB — Browser Automation API routes (for PA worker)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/pinch/navigate")
async def pinch_navigate(request: Request):
    data = await request.json()
    from agent_tools import _pinchtab_navigate
    return JSONResponse({"result": _pinchtab_navigate(data["url"])})

@router.get("/api/pinch/snapshot")
async def pinch_snapshot():
    from agent_tools import _pinchtab_snapshot
    return JSONResponse({"result": _pinchtab_snapshot()})

@router.post("/api/pinch/action")
async def pinch_action(request: Request):
    data = await request.json()
    from agent_tools import _pinchtab_action
    return JSONResponse({"result": _pinchtab_action(data["action"], data["ref"], data.get("value", ""))})

@router.get("/api/pinch/text")
async def pinch_text(mode: str = "readability"):
    from agent_tools import _pinchtab_text
    return JSONResponse({"result": _pinchtab_text(mode)})

@router.get("/api/pinch/screenshot")
async def pinch_screenshot():
    from agent_tools import _pinchtab_screenshot
    return JSONResponse({"result": _pinchtab_screenshot()})

@router.post("/api/pinch/tabs")
async def pinch_tabs(request: Request):
    data = await request.json()
    from agent_tools import _pinchtab_tabs
    return JSONResponse({"result": _pinchtab_tabs(data.get("action", "list"), data.get("url", ""), data.get("tab_id", ""))})

@router.post("/api/pinch/evaluate")
async def pinch_evaluate(request: Request):
    data = await request.json()
    from agent_tools import _pinchtab_evaluate
    return JSONResponse({"result": _pinchtab_evaluate(data.get("expression", data.get("script", "")))})


# ═══════════════════════════════════════════════════════════════════════════════
# SALES CALLER — AI outbound calls via Vapi + ElevenLabs
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/calls/make")
async def make_sales_call(request: Request):
    """Make an outbound AI sales call to a lead."""
    try:
        data = await request.json()
        from sales_caller import call_lead
        result = await call_lead(
            phone=data["phone"],
            business_name=data.get("business_name", "Unknown Business"),
            business_type=data.get("business_type", "restaurant"),
            owner_name=data.get("owner_name", ""),
            lead_id=data.get("lead_id", ""),
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/calls/batch")
async def batch_sales_calls(request: Request):
    """Call multiple leads in sequence."""
    try:
        data = await request.json()
        from sales_caller import call_leads_batch
        results = await call_leads_batch(
            lead_ids=data.get("lead_ids"),
            business_type=data.get("business_type"),
            limit=data.get("limit", 5),
            delay_seconds=data.get("delay_seconds", 60),
        )
        return {"success": True, "calls": results, "total": len(results)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/calls/status/{call_id}")
async def call_status(call_id: str):
    """Check status of an outbound call."""
    try:
        from sales_caller import get_call_status
        return await get_call_status(call_id)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/calls")
async def list_calls():
    """List recent outbound sales calls."""
    try:
        from sales_caller import list_recent_calls
        calls = await list_recent_calls(limit=20)
        return {"calls": calls, "total": len(calls)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/calls/webhook")
async def vapi_call_webhook(request: Request):
    """Receive Vapi call status updates and transcripts."""
    try:
        data = await request.json()
        msg_type = data.get("message", {}).get("type", data.get("type", ""))
        call_data = data.get("message", {}).get("call", data.get("call", {}))
        call_id = call_data.get("id", "unknown")

        logger.info(f"Vapi webhook: {msg_type} for call {call_id}")

        # Save end-of-call report with transcript
        if msg_type in ("end-of-call-report", "call.ended"):
            transcript = data.get("message", {}).get("transcript", data.get("transcript", ""))
            summary = data.get("message", {}).get("summary", data.get("summary", ""))
            duration = call_data.get("duration", 0)
            ended_reason = call_data.get("endedReason", "")
            customer = call_data.get("customer", {})

            # Save transcript
            calls_dir = "./data/calls"
            os.makedirs(calls_dir, exist_ok=True)
            transcript_path = os.path.join(calls_dir, f"{call_id}.json")
            with open(transcript_path, "w") as f:
                json.dump({
                    "call_id": call_id,
                    "customer_number": customer.get("number", ""),
                    "customer_name": customer.get("name", ""),
                    "duration_seconds": duration,
                    "ended_reason": ended_reason,
                    "transcript": transcript,
                    "summary": summary,
                    "raw": data,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2)

            # Send Telegram notification
            outcome = "booked" if any(w in str(transcript).lower() for w in ["schedule", "thursday", "tuesday", "meeting", "appointment", "coffee"]) else "no meeting"
            try:
                from alerts import send_telegram
                import asyncio
                await send_telegram(
                    f"📞 Call ended: {customer.get('name', 'Unknown')}\n"
                    f"Duration: {duration}s | Outcome: {outcome}\n"
                    f"Reason: {ended_reason}"
                )
            except Exception:
                pass

            logger.info(f"Call transcript saved: {call_id} ({duration}s, {ended_reason})")

        return {"ok": True}
    except Exception as e:
        logger.error(f"Vapi webhook error: {e}")
        return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# AUTONOMOUS RUNNER ENDPOINTS — Background job executor
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/runner/status")
async def runner_status():
    """Get autonomous runner status"""
    runner = get_runner()
    if not runner:
        return {"running": False, "message": "Runner not initialized"}
    stats = runner.get_stats()
    active = runner.get_active_jobs()
    return {"running": runner._running, "active_jobs": active, "stats": stats}


@router.get("/api/runner/stats")
async def runner_stats():
    """Get comprehensive job statistics from jobs.jsonl"""
    jobs_file = "data/jobs/jobs.jsonl"

    if not os.path.exists(jobs_file):
        return {
            "total_jobs_processed": 0,
            "success_rate": 0.0,
            "average_job_duration_seconds": 0.0,
            "jobs_by_status": {},
            "jobs_last_24h": 0,
            "top_3_failure_reasons": []
        }

    jobs = []
    try:
        with open(jobs_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    jobs.append(json.loads(line))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading jobs file: {str(e)}")

    if not jobs:
        return {
            "total_jobs_processed": 0,
            "success_rate": 0.0,
            "average_job_duration_seconds": 0.0,
            "jobs_by_status": {},
            "jobs_last_24h": 0,
            "top_3_failure_reasons": []
        }

    # Calculate total jobs processed
    total_jobs = len(jobs)

    # Count jobs by status
    status_counts = Counter(job.get('status', 'unknown') for job in jobs)

    # Calculate success rate (done jobs / total jobs)
    done_jobs = status_counts.get('done', 0)
    success_rate = (done_jobs / total_jobs * 100) if total_jobs > 0 else 0.0

    # Calculate average job duration
    durations = []
    for job in jobs:
        created_at = job.get('created_at')
        completed_at = job.get('completed_at')
        if created_at and completed_at:
            try:
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                completed = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                duration = (completed - created).total_seconds()
                if duration > 0:  # Only include positive durations
                    durations.append(duration)
            except (ValueError, TypeError):
                continue

    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # Count jobs in last 24 hours
    now = datetime.now()
    twenty_four_hours_ago = now - timedelta(hours=24)
    jobs_last_24h = 0

    for job in jobs:
        created_at = job.get('created_at')
        if created_at:
            try:
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                # Convert to naive datetime for comparison
                if created.tzinfo:
                    created = created.replace(tzinfo=None)
                if created >= twenty_four_hours_ago:
                    jobs_last_24h += 1
            except (ValueError, TypeError):
                continue

    # Get top 3 failure reasons
    failure_reasons = []
    for job in jobs:
        if job.get('status') in ['failed', 'killed_manual', 'killed_cost_limit', 'killed_iteration_limit', 'killed_phase_iteration_limit']:
            error = job.get('error', '')
            if error:
                failure_reasons.append(error)

    failure_counter = Counter(failure_reasons)
    top_3_failures = [{"reason": reason, "count": count} for reason, count in failure_counter.most_common(3)]

    return {
        "total_jobs_processed": total_jobs,
        "success_rate": round(success_rate, 2),
        "average_job_duration_seconds": round(avg_duration, 2),
        "jobs_by_status": dict(status_counts),
        "jobs_last_24h": jobs_last_24h,
        "top_3_failure_reasons": top_3_failures
    }

@router.post("/api/runner/execute/{job_id}")
async def runner_execute_job(job_id: str):
    """Manually trigger execution of a specific job"""
    runner = get_runner()
    if not runner:
        raise HTTPException(status_code=503, detail="Runner not initialized")
    asyncio.create_task(runner.execute_job(job_id))
    return {"success": True, "message": f"Job {job_id} queued for execution"}


@router.get("/api/runner/progress/{job_id}")
async def runner_job_progress(job_id: str):
    """Get progress of a running job"""
    runner = get_runner()
    if not runner:
        raise HTTPException(status_code=503, detail="Runner not initialized")
    progress = runner.get_job_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True, **progress}


@router.delete("/api/runner/cancel/{job_id}")
async def runner_cancel_job(job_id: str):
    """Cancel a running job"""
    runner = get_runner()
    if not runner:
        raise HTTPException(status_code=503, detail="Runner not initialized")
    success = runner.cancel_job(job_id)
    return {"success": success}


@router.post("/api/jobs/{job_id}/kill")
async def kill_job(job_id: str, request: Request):
    """
    Kill switch — immediately flags a running job for termination.
    The runner checks this flag at every iteration and will stop the job
    with status 'killed_manual'. Works even if the runner cancel mechanism
    fails, because it uses a file-based flag that the guardrails check.

    Body (optional): {"reason": "why you're killing it"}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = body.get("reason", "manual kill via API")

    _set_kill_flag(job_id, reason)

    # Also try the soft cancel path
    runner = get_runner()
    if runner:
        runner.cancel_job(job_id)

    logger.info(f"Kill switch activated for job {job_id}: {reason}")
    return {
        "success": True,
        "job_id": job_id,
        "reason": reason,
        "message": f"Kill flag set for {job_id}. Job will terminate at next iteration check.",
    }


@router.get("/api/jobs/kill-flags")
async def list_kill_flags():
    """List all active kill flags (for debugging)."""
    return {"kill_flags": _load_kill_flags()}


# ═══════════════════════════════════════════════════════════════════════════════
# PA INTEGRATION — Personal Assistant bidirectional bridge
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/pa/request")
async def pa_request(request: Request):
    """Accept a PA worker request and dispatch to the appropriate handler.

    Auth: X-PA-Token header or standard X-Auth-Token.
    Body: {"action": "create_job", "payload": {...}}
    """
    from pa_integration import handle_pa_request, VALID_ACTIONS

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    action = data.get("action")
    payload = data.get("payload", {})

    if not action:
        return JSONResponse(
            {"error": "Missing 'action' field", "valid_actions": sorted(VALID_ACTIONS)},
            status_code=400,
        )

    result = handle_pa_request(action, payload)

    status_code = 200 if result.get("status") != "failed" else 400
    return JSONResponse(result, status_code=status_code)


@router.get("/api/pa/status/{request_id}")
async def pa_request_status(request_id: str):
    """Query the status of a PA request by ID."""
    from pa_integration import get_pa_request_status

    status = get_pa_request_status(request_id)
    if not status:
        return JSONResponse({"error": "Request not found"}, status_code=404)
    return status


@router.post("/api/pa/callback/status/{request_id}")
async def pa_callback_status(request_id: str, request: Request):
    """Receive status callbacks from PA worker."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    logger.info(f"PA callback received for {request_id}: {data.get('status', 'unknown')}")
    return {"received": True, "request_id": request_id}


@router.get("/api/pa/requests")
async def pa_list_requests(request: Request):
    """List recent PA requests."""
    from pa_integration import get_recent_pa_requests

    limit = int(request.query_params.get("limit", "20"))
    requests_list = get_recent_pa_requests(limit=limit)
    return {"requests": requests_list, "total": len(requests_list)}


# ═══════════════════════════════════════════════════════════════════════════════
# LEAD CAPTURE — Client lead intake
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/leads")
async def capture_lead(request: Request):
    """Capture a new client lead from intake form OR simple sales contact form."""
    import re
    import unicodedata
    import uuid

    try:
        data = await request.json()

        # Support both simple (/sales) and detailed (/intake) form submissions
        # Simple form sends: name, email, business, phone, service, message
        # Intake form sends: business_name, business_type, owner_name, phone, email
        is_simple = "name" in data and "business_name" not in data

        if is_simple:
            # Map simple form fields to standard schema
            required = {
                "business_name": (data.get("business") or data.get("name", "")).strip(),
                "business_type": data.get("service", "other").strip() or "other",
                "owner_name": data.get("name", "").strip(),
                "phone": data.get("phone", "").strip(),
                "email": data.get("email", "").strip(),
            }
            # Simple form only requires name + email
            if not required["owner_name"] or not required["email"]:
                return JSONResponse({"error": "Missing required fields: name, email"}, status_code=400)
        else:
            required = {
                "business_name": data.get("business_name", "").strip(),
                "business_type": data.get("business_type", "").strip(),
                "owner_name": data.get("owner_name", "").strip(),
                "phone": data.get("phone", "").strip(),
                "email": data.get("email", "").strip(),
            }
            missing = [k for k, v in required.items() if not v]
            if missing:
                return JSONResponse(
                    {"error": f"Missing required fields: {', '.join(missing)}"},
                    status_code=400
                )

        # Basic email validation
        email = required["email"]
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return JSONResponse({"error": "Invalid email address"}, status_code=400)

        # --- Build lead record ---
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%d_%H%M%S")

        # Slugify business name for filename
        slug = required["business_name"].lower()
        slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:40]

        lead_id = f"lead-{ts_str}-{slug}"

        lead = {
            "lead_id": lead_id,
            "business_name": required["business_name"],
            "business_type": required["business_type"],
            "owner_name": required["owner_name"],
            "phone": required["phone"],
            "email": email,
            "website_url": (data.get("website_url") or "").strip() or None,
            "services": data.get("services", []),
            "budget": (data.get("budget") or "").strip() or None,
            "notes": (data.get("notes") or data.get("message") or "").strip() or None,
            "source": "intake" if not is_simple else "sales_page",
            "created_at": ts.isoformat(),
            "status": "new",
        }

        # --- Save to disk ---
        leads_dir = "./data/leads"
        os.makedirs(leads_dir, exist_ok=True)

        lead_path = os.path.join(leads_dir, f"{ts_str}_{slug}.json")
        with open(lead_path, "w") as f:
            json.dump(lead, f, indent=2)

        logger.info(f"New lead captured: {lead_id} ({required['business_name']})")

        # --- Create an OpenClaw job for follow-up ---
        try:
            services_str = ", ".join(lead.get("services", [])) or "not specified"
            budget_str = lead.get("budget") or "not specified"
            task_desc = (
                f"New client lead: {required['business_name']} ({required['business_type']}). "
                f"Owner: {required['owner_name']}, Phone: {required['phone']}, Email: {email}. "
                f"Services: {services_str}. Budget: {budget_str}. "
                f"Follow up within 24 hours."
            )
            job = create_job("openclaw", task_desc, "P1")
            lead["job_id"] = job.id
            logger.info(f"Follow-up job created: {job.id}")

            # Emit event
            engine = get_event_engine()
            if engine:
                engine.emit("job.created", {
                    "job_id": job.id,
                    "project": "openclaw",
                    "task": task_desc,
                    "priority": "P1",
                    "source": "intake_form",
                    "lead_id": lead_id,
                })
        except Exception as job_err:
            logger.warning(f"Lead saved but job creation failed: {job_err}")
            lead["job_id"] = None

        # Update saved file with job_id
        with open(lead_path, "w") as f:
            json.dump(lead, f, indent=2)

        return {
            "success": True,
            "lead_id": lead_id,
            "job_id": lead.get("job_id"),
            "message": "Lead captured successfully",
        }

    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    except Exception as e:
        logger.error(f"Lead capture error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/leads")
async def list_leads():
    """List all captured leads (most recent first)."""
    try:
        leads_dir = "./data/leads"
        if not os.path.exists(leads_dir):
            return {"leads": [], "total": 0}

        leads = []
        for fname in sorted(os.listdir(leads_dir), reverse=True):
            if fname.endswith(".json"):
                fpath = os.path.join(leads_dir, fname)
                with open(fpath, "r") as f:
                    leads.append(json.load(f))

        return {"leads": leads, "total": len(leads)}
    except Exception as e:
        logger.error(f"List leads error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════════════
# EVAL HARNESS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

_eval_runs_in_progress: dict = {}  # run_id -> {"status": ..., "task": asyncio.Task}

@router.post("/api/eval/run")
async def run_eval_endpoint(request: Request):
    """Launch an eval run in the background. Returns run_id immediately."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    subset_str = body.get("subset", "all")
    dry_run = body.get("dry_run", False)
    use_llm_judge = body.get("use_llm_judge", True)

    # Parse subset
    if subset_str == "all":
        task_subset = None
    else:
        task_subset = [s.strip() for s in subset_str.split(",")]

    run_id = f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    async def _run_eval_bg():
        try:
            from eval_harness import run_eval
            _eval_runs_in_progress[run_id]["status"] = "running"
            report = await run_eval(
                task_subset=task_subset,
                dry_run=dry_run,
                use_llm_judge=use_llm_judge,
            )
            _eval_runs_in_progress[run_id]["status"] = "completed"
            _eval_runs_in_progress[run_id]["result"] = report.to_dict()
        except Exception as e:
            logger.error(f"Eval run {run_id} failed: {e}")
            _eval_runs_in_progress[run_id]["status"] = "failed"
            _eval_runs_in_progress[run_id]["error"] = str(e)

    task = asyncio.create_task(_run_eval_bg())
    _eval_runs_in_progress[run_id] = {
        "status": "starting",
        "task": task,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "subset": subset_str,
    }

    return {"run_id": run_id, "status": "running", "subset": subset_str}


@router.get("/api/eval/results")
async def list_eval_results():
    """List all past eval runs with summary info."""
    from eval_harness import list_eval_runs
    runs = list_eval_runs()

    # Add any in-progress runs
    for rid, info in _eval_runs_in_progress.items():
        if info["status"] in ("starting", "running"):
            runs.insert(0, {
                "run_id": rid,
                "status": info["status"],
                "started_at": info.get("started_at", ""),
                "subset": info.get("subset", "all"),
            })

    return {"runs": runs, "total": len(runs)}


@router.get("/api/eval/results/{run_id}")
async def get_eval_result(run_id: str):
    """Get detailed results for a specific eval run."""
    # Check in-progress runs first
    if run_id in _eval_runs_in_progress:
        info = _eval_runs_in_progress[run_id]
        if info["status"] == "completed" and "result" in info:
            return info["result"]
        elif info["status"] == "failed":
            return JSONResponse({"error": info.get("error", "Unknown error"), "status": "failed"}, status_code=500)
        else:
            return {"run_id": run_id, "status": info["status"]}

    # Check saved results on disk
    from eval_harness import _load_report
    report = _load_report(run_id)
    if report:
        return report

    raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")


@router.post("/api/eval/compare")
async def compare_eval_runs(request: Request):
    """Compare two eval runs for regression detection."""
    body = await request.json()
    run_a = body.get("run_a")
    run_b = body.get("run_b")
    if not run_a or not run_b:
        raise HTTPException(status_code=400, detail="Both run_a and run_b are required")

    from eval_harness import compare_runs
    return compare_runs(run_a, run_b)


# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY: Prompt Shield Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/security/prompt-scan")
async def security_scan_input(request: Request):
    """Scan text for prompt injection attempts."""
    try:
        from prompt_shield import scan_input, scan_output, scan_skill, is_url_safe
        body = await request.json()
        text = body.get("text", "")
        scan_type = body.get("type", "input")  # input, output, skill, url

        if scan_type == "output":
            result = scan_output(text)
        elif scan_type == "skill":
            result = scan_skill(text)
        elif scan_type == "url":
            safe, reason = is_url_safe(text)
            return {"safe": safe, "reason": reason}
        else:
            result = scan_input(text)

        return result.to_dict()
    except ImportError:
        return {"error": "prompt_shield not available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENT ONBOARDING PIPELINE ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/onboard")
async def onboard_client(request: Request):
    """
    Full client onboarding pipeline:
    Phase 1: Find leads (lead_finder)
    Phase 2: Generate proposals (proposal_generator)
    Phase 3: Make sales calls (sales_caller) — optional, requires explicit enable
    """
    import uuid
    try:
        body = await request.json()
    except Exception:
        body = {}

    business_type = body.get("business_type", "barbershop")
    location = body.get("location", "Flagstaff, AZ")
    count = body.get("count", 10)
    auto_call = body.get("auto_call", False)  # Safety: calls cost real money
    services = body.get("services", ["full_package"])

    pipeline_id = f"onboard-{uuid.uuid4().hex[:8]}"
    results = {
        "pipeline_id": pipeline_id,
        "status": "running",
        "business_type": business_type,
        "location": location,
        "phases": {},
    }

    # Phase 1: Find Leads
    try:
        from lead_finder import search_google_maps
        leads = await search_google_maps(
            query=f"{business_type} in {location}",
            location=location,
            limit=count,
        )
        results["phases"]["find_leads"] = {
            "status": "completed",
            "leads_found": len(leads),
            "leads": leads[:5],  # Preview first 5
        }
    except Exception as e:
        logger.error(f"Onboarding lead find failed: {e}")
        leads = []
        results["phases"]["find_leads"] = {"status": "failed", "error": str(e)}

    # Phase 2: Generate Proposals for top leads
    proposals = []
    for lead in leads[:3]:  # Top 3 leads get proposals
        try:
            from proposal_generator import generate_proposal
            owner_name = lead.get("owner_name", "Owner")
            biz_name = lead.get("business_name", lead.get("title", "Business"))
            proposal_path = generate_proposal(
                business_name=biz_name,
                business_type=business_type,
                owner_name=owner_name,
                selected_services=services,
            )
            proposals.append({"business": biz_name, "proposal_path": proposal_path, "status": "generated"})
        except Exception as e:
            proposals.append({"business": lead.get("business_name", "?"), "status": "failed", "error": str(e)})

    results["phases"]["proposals"] = {
        "status": "completed" if proposals else "skipped",
        "count": len(proposals),
        "proposals": proposals,
    }

    # Phase 3: Sales Calls (only if explicitly enabled — costs real money via Vapi)
    calls = []
    if auto_call and leads:
        for lead in leads[:2]:  # Max 2 calls per pipeline run
            phone = lead.get("phone", "")
            if not phone:
                continue
            try:
                from sales_caller import call_lead
                call_result = await call_lead(
                    phone=phone,
                    business_name=lead.get("business_name", ""),
                    business_type=business_type,
                    owner_name=lead.get("owner_name", ""),
                )
                calls.append({"business": lead.get("business_name", ""), "status": "called", "result": call_result})
            except Exception as e:
                calls.append({"business": lead.get("business_name", ""), "status": "failed", "error": str(e)})

    results["phases"]["sales_calls"] = {
        "status": "completed" if calls else ("skipped" if not auto_call else "no_phones"),
        "auto_call_enabled": auto_call,
        "count": len(calls),
        "calls": calls,
    }

    # Conversion tracking — save pipeline result
    pipeline_dir = os.path.join(DATA_DIR, "onboarding")
    os.makedirs(pipeline_dir, exist_ok=True)
    pipeline_file = os.path.join(pipeline_dir, f"{pipeline_id}.json")
    results["status"] = "completed"
    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    with open(pipeline_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Slack notification
    try:
        await send_slack_message(
            os.environ.get("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7"),
            f"Onboarding pipeline {pipeline_id} completed\n"
            f"Type: {business_type} | Location: {location}\n"
            f"Leads: {len(leads)} | Proposals: {len(proposals)} | Calls: {len(calls)}"
        )
    except Exception:
        pass

    return results


@router.get("/api/onboard/history")
async def list_onboarding_pipelines():
    """List all past onboarding pipeline runs."""
    pipeline_dir = os.path.join(DATA_DIR, "onboarding")
    if not os.path.isdir(pipeline_dir):
        return {"pipelines": [], "total": 0}

    pipelines = []
    for fname in sorted(os.listdir(pipeline_dir), reverse=True):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(pipeline_dir, fname)) as f:
                    pipelines.append(json.load(f))
            except Exception:
                continue

    return {"pipelines": pipelines, "total": len(pipelines)}


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULED HANDS MANAGEMENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/hands/status")
async def hands_status():
    """List all scheduled Hands with their status."""
    try:
        from scheduled_hands import get_scheduler
        scheduler = get_scheduler()
        return scheduler.get_status()
    except ImportError:
        return {"error": "scheduled_hands not available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/hands/run/{hand_name}")
async def run_hand(hand_name: str):
    """Manually trigger a Hand to run immediately."""
    try:
        from scheduled_hands import get_scheduler
        scheduler = get_scheduler()
        ok = scheduler.run_now(hand_name)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Hand '{hand_name}' not found")
        return {"hand": hand_name, "triggered": True, "message": "Running in background"}
    except HTTPException:
        raise
    except ImportError:
        return {"error": "scheduled_hands not available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/hands/enable/{hand_name}")
async def enable_hand(hand_name: str):
    """Enable a disabled Hand (resets circuit breaker)."""
    try:
        from scheduled_hands import get_scheduler
        scheduler = get_scheduler()
        ok = scheduler.enable(hand_name)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Hand '{hand_name}' not found")
        return {"hand": hand_name, "enabled": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/hands/disable/{hand_name}")
async def disable_hand(hand_name: str):
    """Disable a Hand (stops scheduled execution)."""
    try:
        from scheduled_hands import get_scheduler
        scheduler = get_scheduler()
        ok = scheduler.disable(hand_name)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Hand '{hand_name}' not found")
        return {"hand": hand_name, "enabled": False}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/hands/logs/{hand_name}")
async def hand_logs(hand_name: str, limit: int = 20):
    """Get recent execution logs for a Hand."""
    try:
        import os as _os
        log_file = _os.path.join("./data/hands_logs", f"{hand_name}.jsonl")
        if not _os.path.exists(log_file):
            return {"hand": hand_name, "logs": [], "count": 0}
        logs = []
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    logs.append(json.loads(line))
        logs = logs[-limit:]  # last N entries
        return {"hand": hand_name, "logs": logs, "count": len(logs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
