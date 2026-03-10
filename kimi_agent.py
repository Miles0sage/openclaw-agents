"""
Kimi Agent Wrapper for OpenClaw
Wraps Deepseek Kimi models to work as agents in the agency
Routes CodeGen to Kimi 2.5, Security to Kimi
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple
from deepseek_client import DeepseekClient, KimiResponse
# cost_tracker removed — inline stub
import json as _json_ka, os as _os_ka, time as _time_ka
def log_cost_event(project="openclaw", agent="unknown", model="unknown",
                   tokens_input=0, tokens_output=0, cost=None, **kwargs):
    _pricing = {"kimi-2.5": {"input": 0.14, "output": 0.28}, "kimi": {"input": 0.27, "output": 0.68}}
    p = _pricing.get(model, {"input": 0.14, "output": 0.28})
    c = cost if cost is not None else round((tokens_input * p["input"] + tokens_output * p["output"]) / 1_000_000, 6)
    try:
        _data_dir = _os_ka.environ.get("OPENCLAW_DATA_DIR", "./data")
        with open(_os_ka.environ.get("OPENCLAW_COSTS_PATH", _os_ka.path.join(_data_dir, "costs", "costs.jsonl")), "a") as _f:
            _f.write(_json_ka.dumps({"timestamp": _time_ka.time(), "agent": agent, "model": model, "cost": c}) + "\n")
    except Exception:
        pass
    return c

logger = logging.getLogger("kimi_agent")


class KimiAgent:
    """Wrapper for Kimi models to work as agents"""

    # Agent-specific configurations
    AGENT_CONFIGS = {
        "coder_agent": {
            "model": "kimi-2.5",
            "description": "CodeGen Pro - Uses Kimi 2.5 for fast, cost-effective code generation",
            "temperature": 0.3,  # Lower temp for consistent code
            "thinking_budget": None,  # Kimi 2.5 doesn't use thinking
            "use_case": "Code implementation, bug fixes, refactoring"
        },
        "hacker_agent": {
            "model": "kimi",
            "description": "Pentest AI - Uses Kimi for advanced security analysis with reasoning",
            "temperature": 0.5,  # Medium temp for balanced security thinking
            "thinking_budget": 5000,  # Use extended thinking for security
            "use_case": "Security audits, threat modeling, vulnerability assessment"
        }
    }

    def __init__(self, agent_id: str, api_key: Optional[str] = None):
        """
        Initialize a Kimi agent

        Args:
            agent_id: "coder_agent" or "hacker_agent"
            api_key: Deepseek API key (uses env var if not provided)
        """
        if agent_id not in self.AGENT_CONFIGS:
            raise ValueError(f"Unknown agent: {agent_id}. Supported: {list(self.AGENT_CONFIGS.keys())}")

        self.agent_id = agent_id
        self.config = self.AGENT_CONFIGS[agent_id]
        self.client = DeepseekClient(api_key)
        self.model = self.config["model"]
        self.temperature = self.config["temperature"]
        self.thinking_budget = self.config["thinking_budget"]

        logger.info(f"✅ {agent_id} initialized with {self.model}")

    def call(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list] = None,
        max_tokens: Optional[int] = None
    ) -> Tuple[str, int]:
        """
        Call Kimi model as agent

        Args:
            prompt: User message or instruction
            system_prompt: Agent persona/system instructions
            conversation_history: Previous messages for context (last 10)
            max_tokens: Max output tokens

        Returns:
            (response_text, output_tokens)
        """
        try:
            # Build full prompt with conversation history if provided
            if conversation_history:
                # Use multi-turn conversation format
                full_messages = []

                # Add system prompt as first message
                if system_prompt:
                    full_messages.append({
                        "role": "system",
                        "content": system_prompt
                    })

                # Add conversation history
                for msg in conversation_history:
                    full_messages.append(msg)

                # For conversation mode, just use the last user message as prompt
                # The DeepseekClient will handle the message building
                prompt_to_send = prompt
            else:
                prompt_to_send = prompt

            # Call Kimi model
            response = self.client.call(
                model=self.model,
                prompt=prompt_to_send,
                system_prompt=system_prompt if not conversation_history else None,
                temperature=self.temperature,
                max_tokens=max_tokens,
                thinking_budget=self.thinking_budget
            )

            # Log cost event
            try:
                cost = log_cost_event(
                    project="openclaw",
                    agent=self.agent_id,
                    model=self.model,
                    tokens_input=response.tokens_input,
                    tokens_output=response.tokens_output
                )
                logger.info(f"💰 {self.agent_id} cost: ${cost:.6f} "
                           f"({response.tokens_input} in / {response.tokens_output} out)")
            except Exception as e:
                logger.warning(f"Failed to log cost: {e}")

            return response.content, response.tokens_output

        except Exception as e:
            logger.error(f"Error calling {self.model}: {e}")
            raise

    def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None
    ):
        """
        Stream response from Kimi model

        Yields: Chunks of streamed content
        """
        try:
            for chunk in self.client.stream(
                model=self.model,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=self.temperature,
                max_tokens=max_tokens
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Stream error: {e}")
            raise

    def get_info(self) -> Dict[str, Any]:
        """Get agent configuration info"""
        model_info = DeepseekClient.get_pricing_info(self.model)
        return {
            "agent_id": self.agent_id,
            "description": self.config["description"],
            "model": self.model,
            "use_case": self.config["use_case"],
            "temperature": self.temperature,
            "thinking_budget": self.thinking_budget,
            "api_model": model_info.get("api_name"),
            "pricing": model_info.get("pricing"),
            "cost_savings": model_info.get("cost_savings"),
            "context_window": model_info.get("context_window"),
            "max_output_tokens": model_info.get("max_output_tokens")
        }


class KimiAgentPool:
    """Pool of Kimi agents for agency"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize pool with Kimi agents"""
        self.agents = {}
        self.api_key = api_key

        # Initialize supported agents
        for agent_id in KimiAgent.AGENT_CONFIGS.keys():
            try:
                self.agents[agent_id] = KimiAgent(agent_id, api_key)
                logger.info(f"✅ {agent_id} added to pool")
            except Exception as e:
                logger.error(f"Failed to initialize {agent_id}: {e}")

    def get_agent(self, agent_id: str) -> Optional[KimiAgent]:
        """Get agent from pool"""
        return self.agents.get(agent_id)

    def call_agent(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Tuple[str, int]:
        """Call agent from pool"""
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")

        return agent.call(prompt, system_prompt, **kwargs)

    def get_agents_info(self) -> Dict[str, Dict]:
        """Get info about all agents in pool"""
        return {
            agent_id: agent.get_info()
            for agent_id, agent in self.agents.items()
        }

    def health_check(self) -> Dict[str, Any]:
        """Check health of all agents"""
        return {
            "agents": list(self.agents.keys()),
            "count": len(self.agents),
            "api_key_set": self.api_key is not None or bool(os.getenv("DEEPSEEK_API_KEY")),
            "models": [agent.model for agent in self.agents.values()]
        }


# Singleton pool instance
_pool: Optional[KimiAgentPool] = None


def get_kimi_pool(api_key: Optional[str] = None) -> KimiAgentPool:
    """Get or create Kimi agent pool"""
    global _pool
    if _pool is None:
        _pool = KimiAgentPool(api_key)
    return _pool


def call_kimi_agent(
    agent_id: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs
) -> Tuple[str, int]:
    """Convenience function to call a Kimi agent"""
    pool = get_kimi_pool()
    return pool.call_agent(agent_id, prompt, system_prompt, **kwargs)
