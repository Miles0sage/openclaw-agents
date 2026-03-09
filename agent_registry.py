"""
Agent Registry - Manages agent auto-registration and health tracking
Enables agent discovery, health monitoring, and status reporting
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")

@dataclass
class AgentStatus:
    """Agent health and status information"""
    agent_id: str
    name: str
    model: str
    provider: str
    role: str
    status: str  # "active", "inactive", "error"
    last_heartbeat: float  # Unix timestamp
    call_count: int = 0
    error_count: int = 0
    avg_response_time_ms: float = 0.0
    last_error: Optional[str] = None
    registered_at: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['last_heartbeat_iso'] = datetime.fromtimestamp(self.last_heartbeat).isoformat()
        data['registered_at_iso'] = datetime.fromtimestamp(self.registered_at).isoformat()
        return data


class AgentRegistry:
    """Central registry for all agents in the system"""
    
    def __init__(self, persistence_path: str = None):
        """
        Initialize agent registry

        Args:
            persistence_path: Path to save agent registry to disk
        """
        self.agents: Dict[str, AgentStatus] = {}
        self.persistence_path = persistence_path or os.path.join(DATA_DIR, "agents", "agents.json")
        self.metrics: Dict[str, Dict[str, Any]] = {}
        self._load_from_disk()
        
    def register_agent(
        self,
        agent_id: str,
        name: str,
        model: str,
        provider: str,
        role: str,
        status: str = "active"
    ) -> AgentStatus:
        """
        Register an agent on startup
        
        Args:
            agent_id: Unique agent identifier
            name: Human-readable agent name
            model: Model name/ID
            provider: API provider (anthropic, deepseek, ollama, etc.)
            role: Agent role/type (coordinator, developer, security, data_specialist, etc.)
            status: Initial status (active, inactive, error)
            
        Returns:
            AgentStatus object
        """
        now = time.time()
        
        agent = AgentStatus(
            agent_id=agent_id,
            name=name,
            model=model,
            provider=provider,
            role=role,
            status=status,
            last_heartbeat=now,
            registered_at=now
        )
        
        self.agents[agent_id] = agent
        self._save_to_disk()
        
        logger.info(
            f"✅ Registered agent: {name} "
            f"(id={agent_id}, model={model}, provider={provider}, role={role})"
        )
        
        return agent
    
    def update_heartbeat(self, agent_id: str, status: str = "active") -> bool:
        """Update agent heartbeat timestamp"""
        if agent_id not in self.agents:
            logger.warning(f"⚠️  Cannot update heartbeat for unknown agent: {agent_id}")
            return False
        
        self.agents[agent_id].last_heartbeat = time.time()
        self.agents[agent_id].status = status
        self._save_to_disk()
        return True
    
    def record_call(self, agent_id: str, response_time_ms: float = 0.0, error: Optional[str] = None) -> bool:
        """Record agent call/invocation"""
        if agent_id not in self.agents:
            return False
        
        agent = self.agents[agent_id]
        agent.call_count += 1
        
        if error:
            agent.error_count += 1
            agent.last_error = error
            agent.status = "error"
        else:
            agent.status = "active"
            # Update average response time
            if agent.avg_response_time_ms == 0:
                agent.avg_response_time_ms = response_time_ms
            else:
                agent.avg_response_time_ms = (
                    (agent.avg_response_time_ms * (agent.call_count - 1) + response_time_ms) 
                    / agent.call_count
                )
        
        self._save_to_disk()
        return True
    
    def get_agent(self, agent_id: str) -> Optional[AgentStatus]:
        """Get agent by ID"""
        return self.agents.get(agent_id)
    
    def get_all_agents(self) -> List[AgentStatus]:
        """Get all registered agents"""
        return list(self.agents.values())
    
    def get_agents_by_role(self, role: str) -> List[AgentStatus]:
        """Get agents by role"""
        return [a for a in self.agents.values() if a.role == role]
    
    def get_agents_by_provider(self, provider: str) -> List[AgentStatus]:
        """Get agents by provider"""
        return [a for a in self.agents.values() if a.provider == provider]
    
    def get_active_agents(self) -> List[AgentStatus]:
        """Get only active agents"""
        return [a for a in self.agents.values() if a.status == "active"]
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of all agent statuses"""
        all_agents = self.get_all_agents()
        active_agents = self.get_active_agents()
        
        total_calls = sum(a.call_count for a in all_agents)
        total_errors = sum(a.error_count for a in all_agents)
        
        return {
            "total_agents": len(all_agents),
            "active_agents": len(active_agents),
            "inactive_agents": len(all_agents) - len(active_agents),
            "total_calls": total_calls,
            "total_errors": total_errors,
            "agents": [a.to_dict() for a in all_agents]
        }
    
    def _save_to_disk(self):
        """Save registry to disk for persistence"""
        try:
            data = {
                "timestamp": time.time(),
                "agents": {
                    agent_id: agent.to_dict() 
                    for agent_id, agent in self.agents.items()
                }
            }
            
            path = Path(self.persistence_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"❌ Failed to save agent registry to disk: {e}")
    
    def _load_from_disk(self):
        """Load registry from disk if it exists"""
        try:
            path = Path(self.persistence_path)
            if not path.exists():
                return
            
            with open(path, "r") as f:
                data = json.load(f)
            
            for agent_id, agent_data in data.get("agents", {}).items():
                agent = AgentStatus(
                    agent_id=agent_data["agent_id"],
                    name=agent_data["name"],
                    model=agent_data["model"],
                    provider=agent_data["provider"],
                    role=agent_data["role"],
                    status=agent_data["status"],
                    last_heartbeat=agent_data["last_heartbeat"],
                    call_count=agent_data.get("call_count", 0),
                    error_count=agent_data.get("error_count", 0),
                    avg_response_time_ms=agent_data.get("avg_response_time_ms", 0.0),
                    last_error=agent_data.get("last_error"),
                    registered_at=agent_data.get("registered_at", time.time())
                )
                self.agents[agent_id] = agent
            
            logger.info(f"✅ Loaded {len(self.agents)} agents from disk")
        except Exception as e:
            logger.warning(f"⚠️  Could not load agent registry from disk: {e}")


# Global registry instance
_registry: Optional[AgentRegistry] = None


def init_agent_registry(persistence_path: str = None) -> AgentRegistry:
    """Initialize the global agent registry"""
    global _registry
    _registry = AgentRegistry(persistence_path)
    return _registry


def get_agent_registry() -> Optional[AgentRegistry]:
    """Get the global agent registry instance"""
    global _registry
    return _registry


def register_agents_from_config(config: Dict[str, Any]) -> int:
    """
    Auto-register all agents from config.json
    
    Args:
        config: Gateway configuration dictionary
        
    Returns:
        Number of agents registered
    """
    registry = get_agent_registry()
    if not registry:
        logger.error("❌ Agent registry not initialized")
        return 0
    
    agents_config = config.get("agents", {})
    count = 0
    
    for agent_id, agent_config in agents_config.items():
        try:
            registry.register_agent(
                agent_id=agent_id,
                name=agent_config.get("name", agent_id),
                model=agent_config.get("model", "unknown"),
                provider=agent_config.get("apiProvider", "anthropic"),
                role=agent_config.get("type", "general"),
                status="active"
            )
            count += 1
        except Exception as e:
            logger.error(f"❌ Failed to register agent {agent_id}: {e}")
    
    logger.info(f"✅ Auto-registered {count} agents from config")
    return count
