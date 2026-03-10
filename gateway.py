"""
OpenClaw Gateway — Thin shell that wires routers + middleware.

All route handlers live in routers/*.py.
All shared code lives in routers/shared.py.
"""

import asyncio
import os
import sys
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from api_auth import (
    authenticate_request,
    increment_usage,
    RateLimitError,
    QuotaError,
)

# ── Shared infrastructure (config, stubs, helpers, model callers) ────────
from routers.shared import (
    CONFIG, metrics, logger,
    init_memory_manager, get_memory_manager,
    init_cron_scheduler, get_cron_scheduler,
    call_model_for_agent,
    # Re-exports for backward compatibility (other modules import from gateway)
    anthropic_client, get_agent_config, send_slack_message, broadcast_event,
    SLACK_REPORT_CHANNEL,
)

# ── Lifespan-only imports (startup/shutdown) ─────────────────────────────
from response_cache import init_response_cache
from cost_gates import init_cost_gates
from heartbeat_monitor import HeartbeatMonitorConfig, init_heartbeat_monitor, stop_heartbeat_monitor
from event_engine import init_event_engine
from autonomous_runner import init_runner, get_runner
from error_recovery import init_error_recovery
from review_cycle import ReviewCycleEngine
from output_verifier import OutputVerifier

# ── External router modules (pre-existing, not in routers/) ─────────────
from audit_routes import router as audit_router
from intake_routes import router as intake_router
from client_auth import router as client_auth_router
from github_integration import router as github_router
from email_notifications import router as email_router

# ── New router modules ──────────────────────────────────────────────────
from routers.health import router as health_router
from routers.chat import router as chat_router
from routers.telegram import router as telegram_router
from routers.slack import router as slack_router
from routers.cost_quota import router as cost_quota_router
from routers.agent_manage import router as agent_manage_router
from routers.intelligent_routing import router as ir_router
from routers.websocket import router as ws_router
from routers.twilio import router as twilio_router
from routers.workflows import router as workflows_router
from routers.trading import router as trading_router
from routers.google_auth import router as google_auth_router
from routers.advanced import router as advanced_router
from routers.admin import router as admin_router
from routers.extra import router as extra_router
from routers.memory import router as memory_router
from routers.dispatch import router as dispatch_router
from routers.cursor_tasks import router as cursor_router
from routers.brick_builder import router as brick_builder_router
from routers.analytics import router as analytics_router
from routers.portal import router as portal_router

# Optional: research router
try:
    from routers.research import router as research_router
except ImportError:
    research_router = None


# ═════════════════════════════════════════════════════════════════════════
# LIFESPAN — startup & shutdown
# ═════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(application):
    # ── STARTUP ──────────────────────────────────────────────────────
    # Metrics
    try:
        metrics.load_from_disk()
        logger.info("Metrics system initialized (loaded costs from disk)")
    except Exception as e:
        logger.warning(f"Could not load metrics from disk: {e}")

    # Cost gates
    cost_gates_config = CONFIG.get("cost_gates", {})
    if cost_gates_config.get("enabled", True):
        cg = init_cost_gates(cost_gates_config)
        logger.info(f"Cost gates initialized: per-task=${cg.gates['per_task'].limit}, daily=${cg.gates['daily'].limit}, monthly=${cg.gates['monthly'].limit}")
    else:
        logger.info("Cost gates disabled in config")

    # Heartbeat monitor
    try:
        hb_config = HeartbeatMonitorConfig(
            check_interval_ms=30000,
            stale_threshold_ms=5 * 60 * 1000,
            timeout_threshold_ms=60 * 60 * 1000,
        )
        await init_heartbeat_monitor(alert_manager=None, config=hb_config)
        logger.info("Heartbeat monitor initialized and started")
    except Exception as err:
        logger.error(f"Failed to initialize heartbeat monitor: {err}")

    # Event engine
    try:
        event_engine = init_event_engine()
        logger.info("Event engine initialized (closed-loop system active)")
    except Exception as err:
        logger.error(f"Failed to initialize event engine: {err}")
        event_engine = None

    # Cron scheduler
    try:
        cron = init_cron_scheduler()
        cron.start()
        logger.info(f"Cron scheduler initialized ({len(cron.list_jobs())} jobs)")
    except Exception as err:
        logger.error(f"Failed to initialize cron scheduler: {err}")

    # Coding factory crons (dual-engine: Claude Code + Codex)
    try:
        from coding_factory_cron import register_coding_factory_crons
        from scheduled_hands import get_scheduler
        hands_scheduler = get_scheduler()
        await register_coding_factory_crons(hands_scheduler)
        logger.info("Coding factory crons registered (Claude + Codex hands active)")
    except Exception as err:
        logger.error(f"Failed to initialize coding factory crons: {err}")

    # PA Tools crons now registered as Hands in scheduled_hands.py (4 PA + 1 AI news)
    # No separate registration needed — HandScheduler picks them up from BUILTIN_HANDS

    # Memory manager
    try:
        memory = init_memory_manager()
        logger.info(f"Memory manager initialized ({memory.count()} memories)")
    except Exception as err:
        logger.error(f"Failed to initialize memory manager: {err}")

    # Reactions engine
    try:
        from reactions import get_reactions_engine, register_with_event_engine
        reactions_eng = get_reactions_engine()
        if event_engine:
            register_with_event_engine(event_engine)
        logger.info(f"Reactions engine initialized ({len(reactions_eng.get_rules())} rules)")
    except Exception as err:
        logger.error(f"Failed to initialize reactions engine: {err}")

    # Self-improvement engine
    try:
        from self_improve import get_self_improve_engine
        get_self_improve_engine()
        logger.info("Self-improvement engine initialized")
    except Exception as err:
        logger.error(f"Failed to initialize self-improve engine: {err}")

    # AGI Systems: Prompt Versioning, Tool Factory, Guardrail Auto-Apply
    try:
        from prompt_versioning import get_store as get_prompt_store
        prompt_store = get_prompt_store()
        logger.info("Prompt versioning system initialized")
    except Exception as err:
        logger.error(f"Failed to initialize prompt versioning: {err}")

    try:
        from tool_factory import get_factory as get_tool_factory
        tool_factory = get_tool_factory()
        logger.info("Tool factory initialized")
    except Exception as err:
        logger.error(f"Failed to initialize tool factory: {err}")

    try:
        from guardrail_auto_apply import get_auto_apply_engine
        guardrail_applier = get_auto_apply_engine(auto_apply=True)
        logger.info("Guardrail auto-apply engine initialized")
    except Exception as err:
        logger.error(f"Failed to initialize guardrail auto-apply: {err}")

    # Response cache
    try:
        init_response_cache(default_ttl=30, max_entries=1000)
        logger.info("Response cache initialized (TTL=30s, max=1000)")
    except Exception as err:
        logger.error(f"Failed to initialize response cache: {err}")

    # Data directories for traces and KG
    os.makedirs("data/traces", exist_ok=True)
    os.makedirs("data/kg", exist_ok=True)

    # Knowledge Graph Engine
    try:
        from kg_engine import init_kg_engine
        kg = init_kg_engine(db_path="data/kg/knowledge.db", event_engine=event_engine)
        logger.info("Knowledge graph engine initialized")
    except Exception as err:
        logger.error(f"Failed to initialize KG engine: {err}")

    # Streaming Manager
    try:
        from streaming import init_stream_manager
        stream_mgr = init_stream_manager(event_engine=event_engine)
        logger.info("Streaming manager initialized")
    except Exception as err:
        logger.error(f"Failed to initialize streaming manager: {err}")

    # Tracing Engine
    try:
        from otel_tracer import init_tracer
        tracer = init_tracer(export_path="data/traces/spans.jsonl")
        logger.info("Tracing engine initialized")
    except Exception as err:
        logger.error(f"Failed to initialize tracer: {err}")

    # Step journal (append-only JSONL per job for crash recovery replay)
    try:
        from journal import init_journal
        init_journal(trace_dir="data/traces")
        logger.info("Step journal initialized (data/traces)")
    except Exception as err:
        logger.error(f"Failed to initialize step journal: {err}")

    # LLM Judge
    try:
        from llm_judge import init_judge
        import asyncio

        async def _judge_call_fn(system_prompt: str, user_message: str, model: str) -> str:
            """Adapter: judge expects async fn(system, user, model)->str; call_model_for_agent is sync."""
            loop = asyncio.get_event_loop()
            text, _ = await loop.run_in_executor(
                None,
                lambda: call_model_for_agent("coder_agent", user_message, None),
            )
            return text

        judge = init_judge(call_model_fn=_judge_call_fn)
        logger.info("LLM Judge initialized")
    except Exception as err:
        logger.error(f"Failed to initialize LLM Judge: {err}")

    # Autonomous runner — disabled by default to prevent dual-runner credit burn.
    # Only the openclaw-worker-p0/p1/p2 systemd services should consume the job queue.
    # Set OPENCLAW_RUNNER_ENABLED=1 in .env ONLY if you want the gateway to also run jobs.
    if os.getenv("OPENCLAW_RUNNER_ENABLED", "0") == "1":
        try:
            runner = init_runner(max_concurrent=3, budget_limit_usd=15.0)
            await runner.start()
            logger.info("Autonomous job runner started (max_concurrent=3, budget=$15/job)")
        except Exception as err:
            logger.error(f"Failed to start autonomous runner: {err}")
    else:
        logger.info("Autonomous job runner DISABLED (OPENCLAW_RUNNER_ENABLED != 1) — worker pools handle job queue")

    # AI CEO Engine
    try:
        from ceo_engine import get_ceo_engine
        ceo = get_ceo_engine()
        if ceo:
            await ceo.start()
            logger.info(f"AI CEO Engine started ({len(ceo.get_active_goals())} goals, 4 autonomous loops)")
    except Exception as err:
        logger.error(f"Failed to start CEO engine: {err}")

    # Scheduled Hands (autonomous workers)
    try:
        from scheduled_hands import get_scheduler
        hands_scheduler = get_scheduler()
        hands_scheduler.start()
        status = hands_scheduler.get_status()
        logger.info(f"Scheduled Hands started ({len(status['hands'])} hands registered)")
    except Exception as err:
        logger.error(f"Failed to start Scheduled Hands: {err}")

    # Review cycle + output verifier — inject into extra router
    try:
        import routers.extra as _extra_mod
        _extra_mod._review_engine = ReviewCycleEngine(call_agent_fn=call_model_for_agent)
        _extra_mod._output_verifier = OutputVerifier()
        logger.info("Review cycle engine + output verifier initialized")
    except Exception as err:
        logger.error(f"Failed to init review/verifier: {err}")

    # Error recovery
    try:
        recovery = await init_error_recovery()
        application.include_router(recovery.create_routes())
        logger.info("Error recovery system initialized (circuit breakers + crash recovery)")
    except Exception as err:
        logger.error(f"Failed to init error recovery: {err}")

    yield  # ── APP RUNNING ──

    # ── SHUTDOWN ─────────────────────────────────────────────────────
    try:
        from scheduled_hands import get_scheduler
        hs = get_scheduler()
        hs.stop()
        logger.info("Scheduled Hands stopped")
    except Exception as err:
        logger.error(f"Failed to stop Scheduled Hands: {err}")

    try:
        stop_heartbeat_monitor()
        logger.info("Heartbeat monitor stopped")
    except Exception as err:
        logger.error(f"Failed to stop heartbeat monitor: {err}")

    if os.getenv("OPENCLAW_RUNNER_ENABLED", "0") == "1":
        try:
            r = get_runner()
            if r:
                await r.stop()
            logger.info("Autonomous runner stopped")
        except Exception as err:
            logger.error(f"Failed to stop autonomous runner: {err}")

    try:
        from ceo_engine import get_ceo_engine
        ceo = get_ceo_engine()
        if ceo:
            await ceo.stop()
        logger.info("AI CEO Engine stopped")
    except Exception as err:
        logger.error(f"Failed to stop CEO engine: {err}")

    try:
        c = get_cron_scheduler()
        if c:
            c.stop()
        logger.info("Cron scheduler stopped")
    except Exception as err:
        logger.error(f"Failed to stop cron scheduler: {err}")


# ═════════════════════════════════════════════════════════════════════════
# APP CREATION + MIDDLEWARE
# ═════════════════════════════════════════════════════════════════════════

app = FastAPI(title="OpenClaw Gateway", version="4.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REQUEST_TIMEOUT_SECONDS = int(os.getenv("OPENCLAW_REQUEST_TIMEOUT_SECONDS", "300"))
REQUIRE_API_KEY = os.getenv("OPENCLAW_REQUIRE_API_KEY", "").lower() in {"1", "true", "yes"}


def get_supabase():
    """Best-effort Supabase client getter for legacy module compatibility."""
    try:
        from supabase_client import get_client
        return get_client()
    except Exception:
        return None


@app.get("/api/alerts")
async def get_alerts(
    limit: int = Query(50, ge=1, le=500),
    severity: str | None = None,
    job_id: str | None = None,
    agent_key: str | None = None,
):
    """Get recent alerts for dashboard/API clients.

    Primary source: Supabase (durable/queryable).
    Fallback source: local JSONL runbook store.
    """
    from runbook import get_runbook
    try:
        sb = get_supabase()
        if sb:
            query = sb.table("alerts").select("*").order("created_at", desc=True).limit(limit)
            if severity:
                query = query.eq("severity", severity)
            if job_id:
                query = query.eq("job_id", job_id)
            if agent_key:
                query = query.eq("agent_key", agent_key)
            result = query.execute()
            return {"alerts": result.data or []}
    except Exception as exc:
        logger.warning("Supabase alerts query failed, falling back to JSONL: %s", exc)

    return {
        "alerts": get_runbook().get_alerts(
            limit=limit,
            severity=severity,
            job_id=job_id,
            agent_key=agent_key,
        )
    }


@app.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge one alert."""
    from runbook import get_runbook

    ok = get_runbook().acknowledge(alert_id)
    return {"acknowledged": ok}


@app.get("/api/runbook")
async def get_runbook_entries():
    """Get all runbook entries."""
    from runbook import get_runbook

    return get_runbook().get_all_runbook_entries()


@app.get("/api/dlq")
async def get_dlq(limit: int = Query(50, ge=1, le=500), unresolved_only: bool = True):
    from dead_letter_queue import get_dlq_jobs
    return {"jobs": get_dlq_jobs(limit=limit, unresolved_only=unresolved_only)}


@app.post("/api/dlq/{job_id}/retry")
async def retry_dlq_job(job_id: str):
    from dead_letter_queue import retry_from_dlq
    success = retry_from_dlq(job_id)
    return {"success": success, "job_id": job_id}


@app.post("/api/dlq/{job_id}/resolve")
async def resolve_dlq_job(job_id: str):
    from dead_letter_queue import resolve_dlq
    success = resolve_dlq(job_id)
    return {"success": success, "job_id": job_id}

# ── Include routers ─────────────────────────────────────────────────────
# Pre-existing external routers
app.include_router(audit_router)
app.include_router(intake_router)
app.include_router(client_auth_router)
app.include_router(github_router)
app.include_router(email_router)

# New modular routers
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(telegram_router)
app.include_router(slack_router)
app.include_router(cost_quota_router)
app.include_router(agent_manage_router)
app.include_router(ir_router)
app.include_router(ws_router)
app.include_router(twilio_router)
app.include_router(workflows_router)
app.include_router(trading_router)
app.include_router(google_auth_router)
app.include_router(advanced_router)
app.include_router(admin_router)
app.include_router(memory_router)
app.include_router(dispatch_router)
app.include_router(cursor_router)
app.include_router(brick_builder_router)
app.include_router(analytics_router)
app.include_router(portal_router)
app.include_router(extra_router)
if research_router:
    app.include_router(research_router)

# Static files
app.mount("/static", StaticFiles(directory="./static"), name="static")
app.mount("/dashboard/v2", StaticFiles(directory="./public/dashboard"), name="dashboard_v2")
if os.path.isdir("./dashboard_app"):
    app.mount("/dashboard_app", StaticFiles(directory="./dashboard_app"), name="dashboard_app")

# Analytics dashboard (React app built by Cursor)
_analytics_dir = "./public/analytics-dashboard"
if os.path.isdir(_analytics_dir):
    app.mount("/analytics", StaticFiles(directory=_analytics_dir, html=True), name="analytics_dashboard")

# Docs site (MkDocs built by OpenCode)
_docs_dir = "./site"
if os.path.isdir(_docs_dir):
    app.mount("/docs", StaticFiles(directory=_docs_dir, html=True), name="docs_site")


# ── Auth middleware ──────────────────────────────────────────────────────
AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN")
if not AUTH_TOKEN:
    raise RuntimeError("GATEWAY_AUTH_TOKEN environment variable is required. Set it in .env or systemd unit.")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    exempt_paths = [
        "/", "/health", "/metrics", "/test-exempt", "/test-version",
        "/dashboard", "/dashboard.html", "/dashboard/v2", "/dashboard/v2/index.html", "/monitoring", "/terms", "/privacy", "/intake",
        "/telegram/webhook", "/coderclaw/webhook", "/slack/events",
        "/api/audit", "/client-portal", "/client_portal.html",
        "/api/billing/plans", "/api/billing/webhook", "/api/github/webhook",
        "/api/notifications/config", "/secrets", "/metrics-dashboard", "/mobile",
        "/sales", "/nightowl", "/visionclaw", "/oz", "/oz-status",
        "/analytics", "/docs",
        "/webhook/twilio", "/webhook/openclaw-jobs", "/webhook/slack-test",
        "/api/digest", "/api/ping", "/api/version",
    ]
    path = request.url.path

    dashboard_exempt_prefixes = [
        "/api/costs", "/api/heartbeat", "/api/quotas", "/api/agents",
        "/api/route/health", "/api/proposal", "/api/proposals", "/api/policy",
        "/api/events", "/api/memories", "/api/memory", "/api/cron", "/api/tasks",
        "/api/workflows", "/api/dashboard", "/mission-control", "/job-viewer",
        "/api/intake", "/api/jobs", "/api/reviews", "/api/verify", "/api/runner",
        "/api/cache", "/api/health", "/api/reactions", "/api/metrics", "/api/live",
        "/api/dispatch",  # PC dispatcher (needs auth but via token)
        "/api/analytics",  # Dashboard analytics endpoints
        "/oauth", "/api/gmail", "/api/calendar", "/api/polymarket",
        "/api/prediction", "/api/kalshi", "/api/arb", "/api/trading",
        "/api/sportsbook", "/api/sports", "/api/research", "/api/leads",
        "/api/calls", "/api/security", "/api/reflections", "/api/reminders",
        "/api/ai-news", "/api/tweets", "/api/perplexity-research",
        "/api/monitoring", "/api/pa", "/api/oz", "/api/ceo", "/api/pinch",
        "/api/mcp", "/api/eval", "/api/onboard", "/api/billing", "/api/hands",
        "/api/cursor", "/api/chat", "/api/vision",
    ]

    is_exempt = (
        path in exempt_paths
        or path.startswith(("/telegram/", "/slack/", "/api/audit", "/static/", "/dashboard/", "/dashboard_app/", "/control/", "/prestress/", "/ws/", "/brick-builder/", "/analytics/", "/docs/"))
        or any(path.startswith(prefix) for prefix in dashboard_exempt_prefixes)
    )

    if is_exempt:
        return await call_next(request)

    # Allow requests already authenticated via API key middleware.
    if isinstance(getattr(request.state, "api_key", None), dict):
        return await call_next(request)

    token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if not token:
        # Check standard Authorization: Bearer header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if token != AUTH_TOKEN:
        logger.warning(f"AUTH FAILED: {path} (no valid token)")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in ["/health", "/metrics", "/test-exempt"]:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    # Skip rate limit for authenticated admin requests
    admin_token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if admin_token and admin_token == AUTH_TOKEN:
        metrics.record_request(client_ip, path)
        return await call_next(request)

    if not metrics.check_rate_limit(client_ip, max_requests=30, window_seconds=60):
        logger.warning(f"RATE LIMITED: {client_ip} ({path})")
        return JSONResponse(
            {"error": "Rate limit exceeded (max 30 req/min per IP)"},
            status_code=429,
        )

    metrics.record_request(client_ip, path)
    return await call_next(request)


def _extract_api_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        return api_key.strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return ""


def _is_api_protection_exempt(path: str) -> bool:
    if path in {"/", "/health", "/metrics", "/test-exempt", "/test-version"}:
        return True
    exempt_prefixes = (
        "/static/",
        "/dashboard/",
        "/dashboard_app/",
        "/analytics/",
        "/docs/",
        "/telegram/",
        "/slack/",
        "/webhook/",
        "/ws/",
    )
    return any(path.startswith(prefix) for prefix in exempt_prefixes)


@app.middleware("http")
async def api_protection_middleware(request: Request, call_next):
    """Per-key auth/rate protections + hard request timeout wrapper."""
    path = request.url.path
    api_key = ""

    if not _is_api_protection_exempt(path):
        # Skip API key lookup if request is already authenticated via admin X-Auth-Token
        admin_token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
        if admin_token and admin_token == AUTH_TOKEN:
            return await call_next(request)
        api_key = _extract_api_key(request)
        if api_key:
            try:
                key_record = await authenticate_request(api_key)
                if key_record is None:
                    return JSONResponse({"error": "Invalid or inactive API key"}, status_code=401)
                request.state.api_key = key_record
            except RateLimitError as exc:
                return JSONResponse({"error": str(exc), "retry_after": 60}, status_code=429)
            except QuotaError as exc:
                return JSONResponse({"error": str(exc)}, status_code=429)
        elif REQUIRE_API_KEY and path.startswith("/api/"):
            return JSONResponse({"error": "Missing API key"}, status_code=401)

    try:
        response = await asyncio.wait_for(call_next(request), timeout=REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Request timeout"}, status_code=504)

    # Increment request usage only for successful authenticated key checks.
    key_record = getattr(request.state, "api_key", None)
    if isinstance(key_record, dict) and key_record.get("id"):
        increment_usage(key_record["id"], is_job=False)
    return response


# ═════════════════════════════════════════════════════════════════════════
# MAIN — uvicorn entry point
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "18789"))
    print(f"🦞 OpenClaw Gateway v4.2 starting on port {port}")
    print(f"   REST: http://0.0.0.0:{port}/api/chat")
    print(f"   WebSocket: ws://0.0.0.0:{port}/ws")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
