"""
VPS Integration Bridge for OpenClaw Gateway
=============================================

Bridges Cloudflare Workers to VPS agents with:
1. HTTP calls to local/remote VPS agents
2. Session sharing between Cloudflare and VPS systems
3. Automatic fallback chains when VPS is unreachable
4. Health tracking and smart routing

Usage:
    from vps_integration_bridge import VPSIntegrationBridge, VPSAgentConfig

    # Initialize bridge
    bridge = VPSIntegrationBridge()
    
    # Register VPS agents
    bridge.register_agent(
        VPSAgentConfig(
            name="pm-agent",
            host="192.168.1.100",
            port=5000,
            protocol="http"
        )
    )
    
    # Call VPS agent with fallback
    result = bridge.call_agent(
        agent_name="pm-agent",
        prompt="Plan a 3-phase project",
        session_id="user-123"
    )
"""

import json
import logging
import time
import asyncio
import httpx
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta
from enum import Enum
from functools import lru_cache
import sys
import os

# Add error handler to path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from error_handler import (
        AgentHealthTracker,
        ErrorType,
        classify_error,
        execute_with_retry,
        execute_with_timeout,
        TimeoutException,
    )
except ImportError as e:
    logging.warning(f"Error handler not available: {e}")

logger = logging.getLogger("vps_integration_bridge")


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION & DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════

class VPSProtocol(str, Enum):
    """VPS communication protocol"""
    HTTP = "http"
    HTTPS = "https"
    GRPC = "grpc"  # Future support


@dataclass
class VPSAgentConfig:
    """Configuration for a VPS agent endpoint"""
    name: str
    host: str
    port: int
    protocol: VPSProtocol = VPSProtocol.HTTP
    auth_token: Optional[str] = None
    timeout_seconds: int = 30
    max_retries: int = 3
    fallback_agents: List[str] = field(default_factory=list)
    
    def get_url(self, endpoint: str = "") -> str:
        """Get full URL for agent"""
        return f"{self.protocol.value}://{self.host}:{self.port}{endpoint}"
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers with auth token if configured"""
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers


@dataclass
class SessionContext:
    """Shared session context between Cloudflare and VPS"""
    session_id: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_message(self, role: str, content: str, agent: str = ""):
        """Add message to session history"""
        self.last_activity = datetime.now()
        self.messages.append({
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "agent": agent
        })
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for transmission"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "messages": self.messages,
            "metadata": self.metadata
        }


@dataclass
class VPSCallResult:
    """Result from calling VPS agent"""
    success: bool
    agent_name: str
    response: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[ErrorType] = None
    fallback_chain: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    retried: bool = False
    retry_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert result to dictionary"""
        return {
            "success": self.success,
            "agent_name": self.agent_name,
            "response": self.response,
            "error": self.error,
            "error_type": self.error_type.value if self.error_type else None,
            "fallback_chain": self.fallback_chain,
            "latency_ms": round(self.latency_ms, 2),
            "retried": self.retried,
            "retry_count": self.retry_count
        }


# ═══════════════════════════════════════════════════════════════════════════
# VPS INTEGRATION BRIDGE
# ═══════════════════════════════════════════════════════════════════════════

class VPSIntegrationBridge:
    """Bridge between Cloudflare Workers and VPS agents"""
    
    def __init__(self, default_timeout: int = 30):
        """Initialize bridge"""
        self.agents: Dict[str, VPSAgentConfig] = {}
        self.sessions: Dict[str, SessionContext] = {}
        self.default_timeout = default_timeout
        self.health_tracker = AgentHealthTracker()
        self.http_client: Optional[httpx.Client] = None
        self._fallback_chains: Dict[str, List[str]] = {}
        
        logger.info("VPSIntegrationBridge initialized")
    
    def register_agent(self, config: VPSAgentConfig) -> None:
        """Register a VPS agent"""
        self.agents[config.name] = config
        self.health_tracker.register_agent(config.name)
        logger.info(f"Registered VPS agent: {config.name} at {config.get_url()}")
        
        # Build fallback chain
        if config.fallback_agents:
            self._fallback_chains[config.name] = config.fallback_agents
    
    def get_agent_config(self, agent_name: str) -> Optional[VPSAgentConfig]:
        """Get agent configuration"""
        return self.agents.get(agent_name)
    
    def register_session(self, session_id: str, user_id: str) -> SessionContext:
        """Register or get session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionContext(
                session_id=session_id,
                user_id=user_id
            )
            logger.debug(f"Created session: {session_id}")
        return self.sessions[session_id]
    
    def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Get existing session"""
        return self.sessions.get(session_id)
    
    def cleanup_sessions(self, max_age_hours: int = 24) -> int:
        """Remove sessions older than max_age_hours"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        expired = [
            sid for sid, ctx in self.sessions.items()
            if ctx.last_activity < cutoff
        ]
        for sid in expired:
            del self.sessions[sid]
        logger.info(f"Cleaned up {len(expired)} expired sessions")
        return len(expired)
    
    async def call_agent_async(
        self,
        agent_name: str,
        prompt: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> VPSCallResult:
        """Call VPS agent asynchronously with fallback chain"""
        
        start_time = time.time()
        result = VPSCallResult(success=False, agent_name=agent_name)
        
        # Validate agent exists
        if agent_name not in self.agents:
            result.error = f"Agent '{agent_name}' not registered"
            logger.error(result.error)
            return result
        
        # Setup session if provided
        if session_id and user_id:
            session = self.register_session(session_id, user_id)
            session.metadata.update(metadata or {})
            session.add_message("user", prompt)
        
        # Build fallback chain
        agent_chain = [agent_name]
        if agent_name in self._fallback_chains:
            agent_chain.extend(self._fallback_chains[agent_name])
        
        result.fallback_chain = agent_chain
        
        # Try each agent in chain
        for idx, current_agent in enumerate(agent_chain):
            try:
                config = self.agents.get(current_agent)
                if not config:
                    logger.warning(f"Fallback agent '{current_agent}' not found")
                    continue
                
                logger.info(f"Calling agent: {current_agent} (attempt {idx + 1}/{len(agent_chain)})")
                
                # Make request with timeout
                response = await self._call_with_timeout(
                    config,
                    prompt,
                    session_id
                )
                
                # Success - record and return
                self.health_tracker.record_agent_success(current_agent)
                result.success = True
                result.agent_name = current_agent
                result.response = response
                result.latency_ms = (time.time() - start_time) * 1000
                result.retry_count = idx
                
                # Add to session
                if session_id:
                    session = self.get_session(session_id)
                    if session:
                        session.add_message("assistant", response, current_agent)
                
                logger.info(f"✓ Success from {current_agent} ({result.latency_ms:.1f}ms)")
                return result
            
            except Exception as e:
                error_type = classify_error(e)
                self.health_tracker.record_agent_failure(current_agent, e)
                
                logger.warning(
                    f"✗ Failed on {current_agent}: {error_type.value} - {str(e)}"
                )
                
                # Only return failure if this is the last agent
                if idx == len(agent_chain) - 1:
                    result.success = False
                    result.error = f"All agents failed. Last error: {str(e)}"
                    result.error_type = error_type
                    result.latency_ms = (time.time() - start_time) * 1000
                    result.retry_count = idx
                    return result
                else:
                    # Try next agent in chain
                    result.retried = True
                    continue
        
        # Should not reach here
        result.error = "No valid agents in fallback chain"
        return result
    
    def call_agent(
        self,
        agent_name: str,
        prompt: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> VPSCallResult:
        """Call VPS agent synchronously (wrapper around async)"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't use run() if loop is running
                raise RuntimeError("Event loop is running; use call_agent_async()")
        except RuntimeError:
            pass
        
        return asyncio.run(
            self.call_agent_async(agent_name, prompt, session_id, user_id, metadata)
        )
    
    async def _call_with_timeout(
        self,
        config: VPSAgentConfig,
        prompt: str,
        session_id: Optional[str] = None
    ) -> str:
        """Call agent with timeout and retry logic"""
        
        async def make_request() -> str:
            url = config.get_url("/v1/messages")
            headers = config.get_headers()
            
            payload = {
                "model": config.name,
                "messages": [{"role": "user", "content": prompt}]
            }
            if session_id:
                payload["session_id"] = session_id
            
            logger.debug(f"POST {url} with payload: {json.dumps(payload)[:100]}...")
            
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                
                data = response.json()
                if "content" in data:
                    return data["content"]
                elif "message" in data:
                    return data["message"]
                else:
                    return str(data)
        
        # Retry logic with exponential backoff
        retry_delays = [1, 2, 4]
        last_error = None
        
        for attempt in range(config.max_retries):
            try:
                return await asyncio.wait_for(
                    make_request(),
                    timeout=config.timeout_seconds
                )
            except asyncio.TimeoutError:
                last_error = TimeoutException(f"Request timeout after {config.timeout_seconds}s")
                if attempt < config.max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.debug(f"Timeout, retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                raise last_error
            except httpx.HTTPError as e:
                last_error = e
                if attempt < config.max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.debug(f"HTTP error, retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                raise TimeoutException(str(e)) from e
        
        if last_error:
            raise last_error
    
    def get_agent_health(self, agent_name: str) -> Dict:
        """Get agent health status"""
        status = self.health_tracker.get_agent_status(agent_name)
        return status
    
    def get_health_summary(self) -> Dict:
        """Get overall health summary"""
        return self.health_tracker.get_summary()
    
    def export_sessions(self, filepath: str) -> int:
        """Export all sessions to JSON file"""
        data = {
            "exported_at": datetime.now().isoformat(),
            "total_sessions": len(self.sessions),
            "sessions": {
                sid: ctx.to_dict()
                for sid, ctx in self.sessions.items()
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Exported {len(self.sessions)} sessions to {filepath}")
        return len(self.sessions)
    
    def import_sessions(self, filepath: str) -> int:
        """Import sessions from JSON file"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        imported = 0
        for sid, session_data in data.get("sessions", {}).items():
            ctx = SessionContext(
                session_id=session_data["session_id"],
                user_id=session_data["user_id"],
                created_at=datetime.fromisoformat(session_data["created_at"]),
                last_activity=datetime.fromisoformat(session_data["last_activity"]),
                messages=session_data["messages"],
                metadata=session_data["metadata"]
            )
            self.sessions[sid] = ctx
            imported += 1
        
        logger.info(f"Imported {imported} sessions from {filepath}")
        return imported


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

# Global bridge instance (for module-level usage)
_default_bridge: Optional[VPSIntegrationBridge] = None


def get_default_bridge() -> VPSIntegrationBridge:
    """Get or create default bridge instance"""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = VPSIntegrationBridge()
    return _default_bridge


def setup_default_bridge(agents: List[VPSAgentConfig]) -> VPSIntegrationBridge:
    """Setup default bridge with agents"""
    bridge = get_default_bridge()
    for agent in agents:
        bridge.register_agent(agent)
    return bridge


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Setup
    bridge = VPSIntegrationBridge()
    
    # Register agents
    bridge.register_agent(VPSAgentConfig(
        name="pm-agent",
        host="localhost",
        port=5000,
        timeout_seconds=30,
        max_retries=2,
        fallback_agents=["sonnet-agent"]
    ))
    
    bridge.register_agent(VPSAgentConfig(
        name="sonnet-agent",
        host="localhost",
        port=5001,
        timeout_seconds=30
    ))
    
    # Example call (would fail since no actual server running)
    print("VPS Integration Bridge initialized and ready")
