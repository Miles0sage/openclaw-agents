"""
Chat router for OpenClaw Gateway.

Handles REST and streaming chat endpoints, vision processing, and multi-agent
coordination with session memory, cost gating, and delegation.
"""

import os
import json
import re
import uuid
import time
import logging
import asyncio
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import anthropic

from routers.shared import (
    # Core shared imports
    CONFIG, session_store, save_session_history, broadcast_event, send_cost_alert_if_needed,
    get_agent_config, call_model_with_escalation, call_model_for_agent,
    _build_system_prompt, _check_vision_rate_limit, trim_history_if_needed,
    call_claude_with_tools, anthropic_client, agent_router, metrics,
    Message, VisionRequest, BASE_DIR, DATA_DIR,
    # Cost and quota functions
    _calc_cost, load_quota_config, check_all_quotas, get_quota_status,
    get_response_cache, classify_query, MODEL_ALIASES, get_heartbeat_monitor,
    # Cost gates
    check_cost_budget, BudgetStatus, get_cost_gates,
    # Client imports
    DeepseekClient, MiniMaxClient,
    # Task management
    TASKS_FILE, create_job,
)

from cost_tracker import log_cost_event
import pathlib

logger = logging.getLogger("openclaw_gateway")

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# Vision System Prompts
# ═══════════════════════════════════════════════════════════════════════════════════════════════

_VISION_SYSTEM_PROMPTS = {
    "describe": (
        "You analyze images from smart glasses in real-time. Describe the scene concisely "
        "in under 100 words. Focus on what is most important or actionable for the wearer. "
        "Mention key objects, people count, environment type, and any notable activity."
    ),
    "read_text": (
        "You are an OCR assistant for smart glasses. Extract ALL visible text from the image "
        "accurately. Preserve formatting where possible (signs, labels, screens, documents). "
        "If text is partially obscured, indicate uncertain characters with [?]. "
        "Return only the extracted text, no commentary."
    ),
    "translate": (
        "You are a real-time translation assistant for smart glasses. Extract any visible text "
        "from the image and translate it to {language}. Format as:\n"
        "Original: <extracted text>\nTranslation: <translated text>\n"
        "If multiple text elements are visible, translate each one."
    ),
    "remember": (
        "You are a visual memory assistant for smart glasses. Analyze this image and create "
        "a structured memory tag for later recall. Include:\n"
        "- Scene type (indoor/outdoor, location type)\n"
        "- Key objects and their positions\n"
        "- Any text or signage visible\n"
        "- People (count, general description, no identifying features)\n"
        "- Timestamp context clues (lighting, shadows)\n"
        "Format as a compact JSON-like summary for storage."
    ),
    "identify": (
        "You are an object identification assistant for smart glasses. List every distinct "
        "object visible in the image. Format as a numbered list. Include:\n"
        "- Object name\n"
        "- Approximate position (left/center/right, foreground/background)\n"
        "- Notable attributes (color, size, state)\n"
        "Be thorough but concise. Keep each entry to one line."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# /api/chat Endpoint
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@router.post("/api/chat")
async def chat_endpoint(message: Message):
    """REST chat with optional session memory"""
    session_key = message.sessionKey or "default"
    project_id = message.project_id or "default"

    # ═ TASK CREATION: Detect "create task:", "todo:", etc. in user message
    _TASK_PATTERNS = [
        r'^create task[:\s]+(.+)',
        r'^todo[:\s]+(.+)',
        r'^add task[:\s]+(.+)',
        r'^remind me to[:\s]+(.+)',
        r'^new task[:\s]+(.+)',
    ]
    task_match = None
    for _pattern in _TASK_PATTERNS:
        _m = re.match(_pattern, message.content.strip(), re.IGNORECASE)
        if _m:
            task_match = _m.group(1).strip()
            break

    if task_match:
        try:
            if TASKS_FILE.exists():
                with open(TASKS_FILE, 'r') as f:
                    tasks = json.load(f)
            else:
                tasks = []

            routing = agent_router.select_agent(task_match)
            new_task = {
                "id": str(uuid.uuid4())[:8],
                "title": task_match[:200],
                "description": message.content,
                "status": "todo",
                "agent": routing.get("agentId", "project_manager"),
                "created_at": datetime.now(timezone.utc).isoformat() + "Z",
                "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
                "source": "chat",
                "session_key": session_key
            }
            tasks.append(new_task)
            with open(TASKS_FILE, 'w') as f:
                json.dump(tasks, f, indent=2)

            # Also enqueue in the autonomous runner so chat-created tasks get executed
            jm_job_id = None
            try:
                jm_job = create_job(
                    project=new_task.get("title", "chat-task"),
                    task=message.content,
                    priority="P1"
                )
                jm_job_id = jm_job.id
                logger.info(f"✅ Runner job created for chat task: {jm_job_id}")
            except Exception as _je:
                logger.warning(f"Runner job creation failed (non-fatal): {_je}")

            task_response = (
                f"Task created: **{task_match[:200]}**\n"
                f"ID: `{new_task['id']}`"
                + (f" | Runner job: `{jm_job_id}`" if jm_job_id else "") + "\n"
                f"Assigned to: {routing.get('agentId', 'project_manager')} "
                f"({routing.get('reason', '')})\n\n— Overseer"
            )

            session_store.get(session_key).append({"role": "user", "content": message.content})
            session_store.get(session_key).append({"role": "assistant", "content": task_response})
            save_session_history(session_key, session_store.get(session_key))

            broadcast_event({"type": "task_created", "agent": "project_manager",
                             "message": f"Task created: {task_match[:80]}",
                             "timestamp": datetime.now(timezone.utc).isoformat()})

            return {"response": task_response, "agent": "project_manager", "task_created": new_task,
                    "runner_job_id": jm_job_id,
                    "sessionKey": session_key, "historyLength": len(session_store.get(session_key))}
        except Exception as e:
            logger.error(f"Task creation failed: {e}")
            # Fall through to normal chat if task creation fails

    # ═ AGENT ROUTING: Use intelligent router if no explicit agent_id
    if message.agent_id:
        # Explicit agent_id takes precedence
        agent_id = message.agent_id
        logger.info(f"📌 Explicit agent: {agent_id}")
    else:
        # Use intelligent router for automatic agent selection
        if CONFIG.get("routing", {}).get("agent_routing_enabled", True):
            route_decision = agent_router.select_agent(message.content)
            agent_id = route_decision["agentId"]
            logger.info(f"🎯 Agent Router: {route_decision['reason']} (confidence: {route_decision['confidence']:.2f})")
        else:
            # Fallback to PM if routing disabled
            agent_id = "project_manager"
            logger.info(f"📌 Routing disabled, using default: project_manager")

    # Register agent with heartbeat monitor
    heartbeat = get_heartbeat_monitor()
    if heartbeat:
        heartbeat.register_agent(agent_id, session_key)

    try:
        # ═ QUOTA CHECK: Verify daily/monthly limits and queue size
        quota_config = load_quota_config()
        if quota_config.get("enabled", False):
            # Check all quotas before processing
            quotas_ok, quota_error = check_all_quotas(project_id)
            if not quotas_ok:
                logger.warning(f"Quota exceeded: {quota_error}")
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": "Quota limit exceeded",
                        "detail": quota_error,
                        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    }
                )

            # Get quota status for logging
            quota_status = get_quota_status(project_id)
            logger.info(f"✅ Quota check passed for '{project_id}': {quota_status['daily']['percent']:.1f}% daily, {quota_status['monthly']['percent']:.1f}% monthly")

        # ═ COST GATES: Verify budget limits before processing
        cost_gates = get_cost_gates()
        agent_config = get_agent_config(agent_id)
        model = agent_config.get("model", "claude-sonnet-4-20250514")

        # Estimate tokens (rough estimate before actual call)
        estimated_tokens = len(message.content.split()) * 2

        budget_check = check_cost_budget(
            project=project_id,
            agent=agent_id,
            model=model,
            tokens_input=estimated_tokens // 2,
            tokens_output=estimated_tokens // 2,
            task_id=f"{project_id}:{agent_id}:{session_key}"
        )

        if budget_check.status == BudgetStatus.REJECTED:
            logger.warning(f"💰 Cost gate REJECTED: {budget_check.message}")
            return JSONResponse(
                status_code=402,
                content={
                    "success": False,
                    "error": "Budget limit exceeded",
                    "detail": budget_check.message,
                    "gate": budget_check.gate_name,
                    "remaining_budget": budget_check.remaining_budget,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                }
            )
        elif budget_check.status == BudgetStatus.WARNING:
            logger.warning(f"⚠️  Cost gate WARNING: {budget_check.message}")
            # Still proceed but log warning


        # Load session history if available

        # Check cache first
        response_cache = get_response_cache()
        if response_cache:
            cached = response_cache.get(message.content, agent_id, session_key)
            if cached:
                # Cache hit - return cached response
                session_store.get(session_key).append({"role": "user", "content": message.content})
                session_store.get(session_key).append({"role": "assistant", "content": cached.response})
                save_session_history(session_key, session_store.get(session_key))
                return {
                    "agent": cached.agent_id,
                    "response": cached.response,
                    "provider": agent_config.get("apiProvider"),
                    "model": cached.model,
                    "tokens": 0,
                    "sessionKey": session_key,
                    "historyLength": len(session_store.get(session_key)),
                    "cached": True,
                    "tokens_saved": cached.tokens_saved
                }

        # Add user message to history
        session_store.get(session_key).append({
            "role": "user",
            "content": message.content
        })

        # Broadcast start event for SSE
        broadcast_event({"type": "response_start", "agent": agent_id,
                         "message": f"{agent_id} is thinking...",
                         "timestamp": datetime.now(timezone.utc).isoformat()})

        # ═ TOOL USE: Auto-detect or use explicit flag
        # Agents on Anthropic get tool access for execution tasks
        agent_config_for_tools = get_agent_config(agent_id)
        provider_for_tools = agent_config_for_tools.get("apiProvider", "anthropic") if agent_config_for_tools else "anthropic"

        # Auto-detect: enable tools for Anthropic agents when message looks like an action
        action_keywords = ["deploy", "build", "push", "commit", "install", "create file", "write file",
                          "run ", "execute", "test ", "fix ", "git ", "npm ", "fetch ", "scrape",
                          "research", "search for", "look up", "find out", "check status",
                          "deploy to vercel", "push to github"]
        should_use_tools = message.use_tools
        if should_use_tools is None:
            # Auto-detect based on content
            msg_lower = message.content.lower()
            should_use_tools = provider_for_tools == "anthropic" and any(kw in msg_lower for kw in action_keywords)

        if should_use_tools and provider_for_tools == "anthropic":
            # Use tool-enabled Claude call
            logger.info(f"🔧 Tool-enabled call for {agent_id}")
            system_prompt = _build_system_prompt(agent_id, agent_config_for_tools)
            _trimmed_hist = await trim_history_if_needed(
                session_store.get(session_key), client=anthropic.Anthropic())
            tool_messages = [{"role": m["role"], "content": m["content"]} for m in _trimmed_hist[-10:]]

            model_for_tools = agent_config_for_tools.get("model", "claude-sonnet-4-20250514")
            response_text = await call_claude_with_tools(
                anthropic.Anthropic(),
                model_for_tools,
                system_prompt,
                tool_messages,
                max_rounds=8
            )
            tokens = len(response_text.split()) * 2  # Approximate
            actual_agent = agent_id
        else:
            # Call model with last 10 messages for context (with auto-escalation)
            _trimmed_hist2 = await trim_history_if_needed(
                session_store.get(session_key))
            response_text, tokens, actual_agent = call_model_with_escalation(
                agent_id,
                message.content,
                _trimmed_hist2[-10:]
            )
        if actual_agent != agent_id:
            logger.info(f"⬆️ Chat escalated: {agent_id} → {actual_agent}")
            agent_id = actual_agent  # Use the agent that actually responded

        # Store in cache
        if response_cache:
            response_cache.put(message.content, response_text, agent_id, model,
                      agent_config.get("apiProvider", ""), tokens, session_key=session_key)

        # Record metrics
        metrics.record_agent_call(agent_id)
        metrics.record_session(session_key)

        # Update activity after getting response
        if heartbeat:
            heartbeat.update_activity(agent_id)

        # Add assistant response to history
        session_store.get(session_key).append({
            "role": "assistant",
            "content": response_text
        })

        # Save session to disk
        save_session_history(session_key, session_store.get(session_key))

        # ═ DELEGATION: Check if PM wants to delegate sub-tasks to specialists
        # With memory sharing (session context) and auto-escalation
        delegation_results = []
        if agent_id in ("project_manager", "pm"):
            delegations = agent_router.auto_delegate(response_text, message.content)
            if delegations:
                logger.info(f"🤝 Delegation: {len(delegations)} sub-tasks from PM")

                # Build shared context from session for memory sharing
                session_context = ""
                recent_history = session_store.get(session_key)[-6:]  # Last 3 exchanges
                if recent_history:
                    context_parts = []
                    for msg in recent_history:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")[:500]  # Truncate for cost
                        context_parts.append(f"{role}: {content}")
                    session_context = (
                        "\n--- SESSION CONTEXT (shared by Overseer) ---\n"
                        + "\n".join(context_parts)
                        + "\n--- END CONTEXT ---\n\n"
                    )

                for delegation in delegations:
                    try:
                        broadcast_event({"type": "delegation_start", "agent": delegation["agent_id"],
                                         "message": f"Delegated by PM: {delegation['task'][:80]}..."})

                        # Inject session context into delegation task (memory sharing)
                        enriched_task = session_context + delegation["task"] if session_context else delegation["task"]

                        # Use auto-escalation — if target agent fails, escalate up
                        delegate_response, delegate_tokens, actual_agent = call_model_with_escalation(
                            delegation["agent_id"], enriched_task, conversation=None)
                        delegation_results.append({
                            "agent": actual_agent,
                            "original_agent": delegation["agent_id"],
                            "task": delegation["task"],
                            "response": delegate_response,
                            "tokens": delegate_tokens,
                            "escalated": actual_agent != delegation["agent_id"]
                        })
                        broadcast_event({"type": "delegation_end", "agent": actual_agent,
                                         "message": f"{actual_agent} completed delegation ({delegate_tokens} tokens)"
                                         + (f" [escalated from {delegation['agent_id']}]" if actual_agent != delegation["agent_id"] else "")})
                    except Exception as e:
                        logger.error(f"Delegation to {delegation['agent_id']} failed (all escalations exhausted): {e}")
                        delegation_results.append({
                            "agent": delegation["agent_id"],
                            "original_agent": delegation["agent_id"],
                            "task": delegation["task"],
                            "response": f"[Delegation failed after escalation: {str(e)}]",
                            "tokens": 0,
                            "escalated": False
                        })

                # Synthesize specialist responses via PM
                if delegation_results:
                    synthesis_parts = []
                    for r in delegation_results:
                        synthesis_parts.append(f"### {r['agent']} response:\n{r['response']}")
                    synthesis_prompt = (
                        f"You delegated tasks to specialists. Here are their results:\n\n"
                        f"{''.join(synthesis_parts)}\n\n"
                        f"Original user request: {message.content}\n\n"
                        f"Synthesize these specialist responses into a single, coherent response for the user. "
                        f"Remove any delegation markers. Be concise."
                    )
                    response_text, extra_tokens = call_model_for_agent("project_manager", synthesis_prompt)
                    tokens += extra_tokens + sum(r["tokens"] for r in delegation_results)

                    # Update session with synthesized response
                    session_store.get(session_key)[-1] = {"role": "assistant", "content": response_text}
                    save_session_history(session_key, session_store.get(session_key))

        # Broadcast response event
        broadcast_event({"type": "response_end", "agent": agent_id,
                         "message": f"{agent_id} responded ({tokens} tokens)", "tokens": tokens,
                         "timestamp": datetime.now(timezone.utc).isoformat()})

        # Check cost alerts
        send_cost_alert_if_needed()

        agent_config = get_agent_config(agent_id)

        result = {
            "agent": agent_id,
            "response": response_text,
            "provider": agent_config.get("apiProvider"),
            "model": agent_config.get("model"),
            "tokens": tokens,
            "sessionKey": session_key,
            "historyLength": len(session_store.get(session_key))
        }

        if delegation_results:
            result["delegations"] = [{"agent": r["agent"], "tokens": r["tokens"]} for r in delegation_results]

        return result
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Unregister agent when done
        if heartbeat:
            heartbeat.unregister_agent(agent_id)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# /api/vision Endpoint
# Smart Glasses Image Processing
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@router.post("/api/vision")
async def vision_endpoint(req: VisionRequest):
    """Process images from smart glasses using Claude Haiku 4.5 vision.

    Query types:
    - describe: Concise scene description
    - read_text: OCR text extraction
    - translate: Extract and translate visible text (requires language param)
    - remember: Tag image for memory/recall storage
    - identify: List all objects in scene
    """
    # Validate query type
    valid_queries = {"describe", "read_text", "translate", "remember", "identify"}
    query_type = req.query.lower().strip()
    if query_type not in valid_queries:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid query type '{req.query}'. Must be one of: {', '.join(sorted(valid_queries))}"
        )

    # Validate language for translate query
    if query_type == "translate" and not req.language:
        raise HTTPException(
            status_code=400,
            detail="Language parameter is required for 'translate' query type"
        )

    # Rate limiting per device_id
    device_id = req.device_id or "anonymous"
    if not _check_vision_rate_limit(device_id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: max 10 images per minute per device"
        )

    # Validate base64 image
    try:
        image_bytes = base64.b64decode(req.image, validate=True)
        if len(image_bytes) < 100:
            raise ValueError("Image too small")
        if len(image_bytes) > 20 * 1024 * 1024:  # 20MB max
            raise ValueError("Image exceeds 20MB limit")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base64 image: {e}"
        )

    # Build system prompt
    system_prompt = _VISION_SYSTEM_PROMPTS[query_type]
    if query_type == "translate":
        system_prompt = system_prompt.format(language=req.language)

    # Build user prompt based on query type
    user_prompts = {
        "describe": "Describe this scene concisely.",
        "read_text": "Read and extract all text visible in this image.",
        "translate": f"Extract all visible text and translate it to {req.language}.",
        "remember": "Analyze this image and create a structured memory tag for later recall.",
        "identify": "Identify and list all objects visible in this image.",
    }
    user_prompt = user_prompts[query_type]

    # Call Claude Haiku 4.5 vision API
    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": req.image,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            }],
        )
    except anthropic.BadRequestError as e:
        logger.error(f"Vision API bad request: {e}")
        raise HTTPException(status_code=400, detail=f"Vision API error: {e}")
    except anthropic.RateLimitError as e:
        logger.error(f"Vision API rate limited: {e}")
        raise HTTPException(status_code=429, detail="Anthropic API rate limit reached. Try again shortly.")
    except Exception as e:
        logger.error(f"Vision API call failed: {e}")
        raise HTTPException(status_code=500, detail=f"Vision processing failed: {e}")

    # Extract response text
    result_text = response.content[0].text if response.content else ""

    # Calculate cost
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    cost_usd = _calc_cost("claude-haiku-4-5-20251001", tokens_in, tokens_out)

    # Log cost event
    log_cost_event(
        model="claude-haiku-4-5-20251001",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        agent="vision_agent",
        endpoint="/api/vision",
    )

    # Handle "remember" query: store to session memory if session_key provided
    stored = False
    if query_type == "remember" and req.session_key:
        try:
            session_store.get(req.session_key).append({
                "role": "assistant",
                "content": f"[Visual Memory] {result_text}",
            })
            save_session_history(req.session_key, session_store.get(req.session_key))
            stored = True
        except Exception as e:
            logger.warning(f"Failed to store visual memory: {e}")

    logger.info(
        f"Vision processed: query={query_type} device={device_id} "
        f"tokens_in={tokens_in} tokens_out={tokens_out} cost=${cost_usd:.4f}"
    )

    return {
        "text": result_text,
        "query_type": query_type,
        "agent": "vision_agent",
        "cost_usd": round(cost_usd, 6),
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "stored": stored,
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# /api/chat/stream Endpoint
# REST chat with SSE streaming for real-time token delivery
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@router.post("/api/chat/stream")
async def chat_stream_endpoint(message: Message):
    """REST chat with SSE streaming for real-time token delivery.
    Returns Server-Sent Events with types: start, token, done, error"""
    session_key = message.sessionKey or "default"
    project_id = message.project_id or "default"

    # Agent routing (same as /api/chat)
    if message.agent_id:
        agent_id = message.agent_id
    else:
        if CONFIG.get("routing", {}).get("agent_routing_enabled", True):
            route_decision = agent_router.select_agent(message.content)
            agent_id = route_decision["agentId"]
        else:
            agent_id = "project_manager"

    heartbeat = get_heartbeat_monitor()
    if heartbeat:
        heartbeat.register_agent(agent_id, session_key)

    # Quota check
    quota_config = load_quota_config()
    if quota_config.get("enabled", False):
        quotas_ok, quota_error = check_all_quotas(project_id)
        if not quotas_ok:
            return JSONResponse(status_code=429, content={"success": False, "error": quota_error})

    # Cost gate check
    agent_config = get_agent_config(agent_id)
    model = agent_config.get("model", "claude-sonnet-4-5-20250929")
    provider = agent_config.get("apiProvider", "anthropic")

    estimated_tokens = len(message.content.split()) * 2
    budget_check = check_cost_budget(
        project=project_id, agent=agent_id, model=model,
        tokens_input=estimated_tokens // 2, tokens_output=estimated_tokens // 2,
        task_id=f"{project_id}:{agent_id}:{session_key}"
    )
    if budget_check.status == BudgetStatus.REJECTED:
        return JSONResponse(status_code=402, content={"success": False, "error": budget_check.message})

    # Load session
    session_store.get(session_key).append({"role": "user", "content": message.content})

    # Build system prompt
    persona = agent_config.get("persona", "")
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    signature = agent_config.get("signature", "")

    identity_context = ""
    gateway_dir = os.path.dirname(os.path.abspath(__file__))
    gateway_dir = os.path.dirname(gateway_dir)  # Up one level to openclaw root
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                identity_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass

    system_prompt = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- Follow your character consistently
- Reference real project names (Barber CRM, Delhi Palace, OpenClaw, PrestressCalc, Concrete Canoe)

Remember: You ARE {name}. Stay in character!

--- IDENTITY & CONTEXT ---
{identity_context}"""

    # Intelligent routing for Anthropic models
    router_enabled = CONFIG.get("routing", {}).get("enabled", False)
    if router_enabled and provider == "anthropic":
        try:
            classification = classify_query(message.content)
            routed_model = MODEL_ALIASES.get(classification.model, model)
            model = routed_model
        except Exception:
            pass

    async def generate():
        """SSE generator that streams tokens from the model"""
        full_response = ""
        tokens_used = 0

        try:
            yield f"data: {json.dumps({'type': 'start', 'agent': agent_id, 'model': model, 'provider': provider})}\n\n"

            if provider == "anthropic":
                _trimmed_stream = await trim_history_if_needed(
                    session_store.get(session_key), client=anthropic_client)
                with anthropic_client.messages.stream(
                    model=model, max_tokens=8192,
                    system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                    messages=_trimmed_stream[-10:]
                ) as stream:
                    for text in stream.text_stream:
                        full_response += text
                        yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
                    final = stream.get_final_message()
                    tokens_used = final.usage.output_tokens

            elif provider == "deepseek":
                ds_client = DeepseekClient()
                api_model = model if model in ["kimi-2.5", "kimi"] else "kimi-2.5"
                for chunk in ds_client.stream(model=api_model, prompt=message.content,
                                              system_prompt=system_prompt, max_tokens=8192):
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"

            elif provider == "minimax":
                mm_client = MiniMaxClient()
                api_model = model if model in ["m2.5", "m2.5-lightning"] else "m2.5"
                for chunk in mm_client.stream(model=api_model, prompt=message.content,
                                              system_prompt=system_prompt, max_tokens=16384):
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"

            # Save to session
            session_store.get(session_key).append({"role": "assistant", "content": full_response})
            save_session_history(session_key, session_store.get(session_key))

            # Log cost
            try:
                log_cost_event(project="openclaw", agent=agent_id, model=model,
                              tokens_input=len(message.content.split()) * 2,
                              tokens_output=tokens_used or len(full_response.split()) * 2)
            except Exception:
                pass

            # Record metrics
            metrics.record_agent_call(agent_id)
            metrics.record_session(session_key)

            yield f"data: {json.dumps({'type': 'done', 'agent': agent_id, 'tokens': tokens_used, 'sessionKey': session_key})}\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if heartbeat:
                heartbeat.unregister_agent(agent_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )
