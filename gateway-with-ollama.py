"""
OpenClaw Gateway - ACTUALLY USES LOCAL MODELS
Fixed to properly route to Ollama based on config.json
"""

import os
import json
import asyncio
import uuid
import sys
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import anthropic
import requests
from dotenv import load_dotenv
import logging

# Import orchestrator
from orchestrator import Orchestrator, AgentRole, Message as OrchMessage, MessageAudience

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("openclaw_gateway")

# Initialize Orchestrator
orchestrator = Orchestrator()

app = FastAPI(title="OpenClaw Gateway", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load config
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

# Initialize Anthropic client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Protocol version
PROTOCOL_VERSION = 3

# Timeout settings
WS_RECEIVE_TIMEOUT = 120
WS_PING_INTERVAL = 30
WS_PING_TIMEOUT = 10

# Active connections
active_connections: Dict[str, WebSocket] = {}
chat_history: Dict[str, list] = {}


class Message(BaseModel):
    content: str
    agent_id: Optional[str] = "pm"


def call_ollama(model: str, prompt: str, endpoint: str = "http://localhost:11434") -> tuple[str, int]:
    """Call Ollama API"""
    logger.info(f"🔥 Calling Ollama: {model}")

    response = requests.post(
        f"{endpoint}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    data = response.json()
    text = data.get("response", "")
    tokens = len(text.split())  # Rough estimate

    logger.info(f"✅ Ollama responded: {len(text)} chars")
    return text, tokens


def call_anthropic(model: str, prompt: str) -> tuple[str, int]:
    """Call Anthropic API"""
    logger.info(f"☁️  Calling Anthropic: {model}")

    response = anthropic_client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text
    tokens = response.usage.output_tokens

    logger.info(f"✅ Anthropic responded: {tokens} tokens")
    return text, tokens


def get_agent_config(agent_key: str) -> Dict:
    """Get agent configuration from config.json"""
    return CONFIG.get("agents", {}).get(agent_key, {})


def call_model_for_agent(agent_key: str, prompt: str, conversation: list = None) -> tuple[str, int]:
    """
    Route to correct model based on agent config

    Returns: (response_text, tokens_used)
    """
    agent_config = get_agent_config(agent_key)

    if not agent_config:
        logger.warning(f"⚠️  No config for agent: {agent_key}, using default")
        agent_config = get_agent_config("project_manager")

    provider = agent_config.get("apiProvider", "anthropic")
    model = agent_config.get("model", "claude-sonnet-4-5-20250929")
    endpoint = agent_config.get("endpoint", "http://localhost:11434")

    logger.info(f"📍 Agent: {agent_key} → Provider: {provider} → Model: {model}")

    # Build full prompt with conversation history if provided
    if conversation:
        full_prompt = "\n\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in conversation
        ])
        full_prompt += f"\n\nassistant: "
    else:
        full_prompt = prompt

    # Route to correct provider
    if provider == "ollama":
        return call_ollama(model, full_prompt, endpoint)
    elif provider == "anthropic":
        # For Anthropic, use conversation format if available
        if conversation:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=4096,
                messages=conversation
            )
            return response.content[0].text, response.usage.output_tokens
        else:
            return call_anthropic(model, prompt)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def build_agent_system_prompt(agent_role: AgentRole) -> str:
    """Build system prompt with agent identity"""
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
- Celebrate wins! 🎉

Now respond as {orchestrator.agents[agent_role].name} {orchestrator.agents[agent_role].emoji}!
"""
    return base_prompt


@app.get("/")
async def root():
    """Health check showing ACTUAL model configuration"""
    return {
        "name": "OpenClaw Gateway",
        "version": "2.0.0",
        "status": "online",
        "agents": len(CONFIG.get("agents", {})),
        "protocol": "OpenClaw v1",
        "model_config": {
            agent: {
                "provider": cfg.get("apiProvider"),
                "model": cfg.get("model")
            }
            for agent, cfg in CONFIG.get("agents", {}).items()
        }
    }


@app.get("/api/agents")
async def list_agents():
    """List agents with ACTUAL model configuration"""
    agents = []
    for agent_id, config in CONFIG.get("agents", {}).items():
        agents.append({
            "id": agent_id,
            "name": config.get("name"),
            "provider": config.get("apiProvider"),
            "model": config.get("model"),
            "role": config.get("type"),
            "status": "idle"
        })
    return {"agents": agents}


@app.post("/api/chat")
async def chat_endpoint(message: Message):
    """Simple REST chat - routes to correct model"""
    agent_id = message.agent_id or "project_manager"

    try:
        response_text, tokens = call_model_for_agent(
            agent_id,
            message.content
        )

        agent_config = get_agent_config(agent_id)

        return {
            "agent": agent_id,
            "response": response_text,
            "provider": agent_config.get("apiProvider"),
            "model": agent_config.get("model"),
            "tokens": tokens
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/")
async def root_websocket(websocket: WebSocket):
    await handle_websocket(websocket)


@app.websocket("/ws")
async def ws_websocket(websocket: WebSocket):
    await handle_websocket(websocket)


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
                        if session_key not in chat_history:
                            chat_history[session_key] = []

                        chat_history[session_key].append({
                            "role": "user",
                            "content": message_text
                        })

                        # Determine agent (default PM)
                        active_agent = "project_manager"

                        # Call CORRECT model
                        logger.info(f"🎯 Routing to agent: {active_agent}")
                        response_text, tokens = call_model_for_agent(
                            active_agent,
                            message_text,
                            chat_history[session_key][-10:]  # Last 10 messages
                        )

                        timestamp = int(asyncio.get_event_loop().time() * 1000)

                        chat_history[session_key].append({
                            "role": "assistant",
                            "content": response_text
                        })

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


if __name__ == "__main__":
    import uvicorn
    print("🦞 OpenClaw Gateway FIXED - Now using ACTUAL models from config!")
    print(f"   Protocol: OpenClaw v{PROTOCOL_VERSION}")
    print("   WebSocket: ws://0.0.0.0:18789/ws")
    print("")
    print("📊 Agent Configuration:")
    for agent_id, config in CONFIG.get("agents", {}).items():
        provider = config.get("apiProvider", "unknown")
        model = config.get("model", "unknown")
        emoji = config.get("emoji", "")
        print(f"   {emoji} {agent_id:20} → {provider:10} → {model}")
    print("")
    uvicorn.run(app, host="0.0.0.0", port=18789, log_level="info")
