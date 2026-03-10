"""
Gateway VPS Integration Module
===============================

FastAPI routes for VPS agent integration with fallback support.

Add to your FastAPI gateway:
    from gateway_vps_integration import setup_vps_routes, get_vps_bridge
    
    app = FastAPI()
    bridge = setup_vps_routes(app)
"""

import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import json

from vps_integration_bridge import (
    VPSIntegrationBridge,
    VPSAgentConfig,
    VPSProtocol,
    get_default_bridge
)

logger = logging.getLogger("gateway_vps_integration")

# Global bridge instance
_vps_bridge: Optional[VPSIntegrationBridge] = None


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

class VPSAgentRequest(BaseModel):
    """Request to call VPS agent"""
    agent_name: str
    prompt: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class VPSAgentResponse(BaseModel):
    """Response from VPS agent call"""
    success: bool
    agent_name: str
    response: Optional[str] = None
    error: Optional[str] = None
    fallback_chain: List[str]
    latency_ms: float
    retried: bool
    retry_count: int


class AgentHealthResponse(BaseModel):
    """Agent health status"""
    agent_name: str
    status: str
    success_rate: float
    total_requests: int
    total_failures: int
    consecutive_failures: int


class VPSHealthSummary(BaseModel):
    """Summary of all VPS agents"""
    total_agents: int
    healthy_agents: int
    unhealthy_agents: int
    degraded_agents: int
    error_rate: float


class RegisterAgentRequest(BaseModel):
    """Request to register VPS agent"""
    name: str
    host: str
    port: int
    protocol: str = "http"
    auth_token: Optional[str] = None
    timeout_seconds: int = 30
    max_retries: int = 3
    fallback_agents: List[str] = []


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def setup_vps_routes(app, bridge: Optional[VPSIntegrationBridge] = None) -> VPSIntegrationBridge:
    """Setup VPS integration routes on FastAPI app
    
    Args:
        app: FastAPI application instance
        bridge: Optional VPSIntegrationBridge instance (creates new if None)
    
    Returns:
        Configured VPSIntegrationBridge instance
    """
    global _vps_bridge
    
    if bridge is None:
        _vps_bridge = VPSIntegrationBridge()
    else:
        _vps_bridge = bridge
    
    router = APIRouter(prefix="/api/vps", tags=["vps"])
    
    @router.post("/call", response_model=VPSAgentResponse)
    async def call_vps_agent(request: VPSAgentRequest) -> Dict[str, Any]:
        """Call a VPS agent with fallback chain support
        
        Example:
            POST /api/vps/call
            {
                "agent_name": "pm-agent",
                "prompt": "Plan a 3-phase project",
                "session_id": "user-123",
                "user_id": "user-123"
            }
        """
        try:
            logger.info(f"Calling VPS agent: {request.agent_name}")
            
            result = await _vps_bridge.call_agent_async(
                agent_name=request.agent_name,
                prompt=request.prompt,
                session_id=request.session_id,
                user_id=request.user_id,
                metadata=request.metadata
            )
            
            return result.to_dict()
        
        except Exception as e:
            logger.error(f"Error calling VPS agent: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to call VPS agent: {str(e)}"
            )
    
    @router.post("/register", status_code=201)
    async def register_agent(request: RegisterAgentRequest) -> Dict[str, Any]:
        """Register a new VPS agent
        
        Example:
            POST /api/vps/register
            {
                "name": "pm-agent",
                "host": "192.168.1.100",
                "port": 5000,
                "protocol": "http",
                "timeout_seconds": 30,
                "max_retries": 3,
                "fallback_agents": ["sonnet-agent"]
            }
        """
        try:
            protocol = VPSProtocol(request.protocol)
            config = VPSAgentConfig(
                name=request.name,
                host=request.host,
                port=request.port,
                protocol=protocol,
                auth_token=request.auth_token,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
                fallback_agents=request.fallback_agents
            )
            
            _vps_bridge.register_agent(config)
            logger.info(f"Registered VPS agent: {request.name}")
            
            return {
                "status": "registered",
                "agent_name": request.name,
                "url": config.get_url()
            }
        
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid protocol: {e}")
        except Exception as e:
            logger.error(f"Error registering agent: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/agents")
    async def list_agents() -> Dict[str, Any]:
        """List all registered VPS agents"""
        agents = []
        for name, config in _vps_bridge.agents.items():
            agents.append({
                "name": name,
                "host": config.host,
                "port": config.port,
                "protocol": config.protocol.value,
                "url": config.get_url()
            })
        
        return {
            "total": len(agents),
            "agents": agents
        }
    
    @router.get("/health/{agent_name}", response_model=AgentHealthResponse)
    async def get_agent_health(agent_name: str) -> Dict[str, Any]:
        """Get health status of a specific VPS agent"""
        if agent_name not in _vps_bridge.agents:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        
        return _vps_bridge.get_agent_health(agent_name)
    
    @router.get("/health", response_model=VPSHealthSummary)
    async def get_vps_health() -> Dict[str, Any]:
        """Get overall VPS health summary"""
        return _vps_bridge.get_health_summary()
    
    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> Dict[str, Any]:
        """Get session details and message history"""
        session = _vps_bridge.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        
        return session.to_dict()
    
    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> None:
        """Delete a session"""
        if session_id in _vps_bridge.sessions:
            del _vps_bridge.sessions[session_id]
            logger.info(f"Deleted session: {session_id}")
        else:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    @router.post("/sessions/cleanup")
    async def cleanup_sessions(max_age_hours: int = 24) -> Dict[str, Any]:
        """Clean up old sessions"""
        count = _vps_bridge.cleanup_sessions(max_age_hours=max_age_hours)
        return {
            "cleaned_up": count,
            "remaining_sessions": len(_vps_bridge.sessions)
        }
    
    @router.get("/status")
    async def gateway_status() -> Dict[str, Any]:
        """Get gateway status"""
        health = _vps_bridge.get_health_summary()
        return {
            "status": "operational" if health["healthy_agents"] > 0 else "degraded",
            "agents": health["total_agents"],
            "healthy_agents": health["healthy_agents"],
            "unhealthy_agents": health["unhealthy_agents"],
            "sessions": len(_vps_bridge.sessions)
        }
    
    app.include_router(router)
    
    logger.info(f"VPS integration routes registered at /api/vps/*")
    
    return _vps_bridge


def get_vps_bridge() -> VPSIntegrationBridge:
    """Get the VPS bridge instance"""
    global _vps_bridge
    if _vps_bridge is None:
        _vps_bridge = VPSIntegrationBridge()
    return _vps_bridge


if __name__ == "__main__":
    # Example setup
    from fastapi import FastAPI
    
    app = FastAPI()
    bridge = setup_vps_routes(app)
    
    print(f"Gateway VPS integration ready on /api/vps/*")
