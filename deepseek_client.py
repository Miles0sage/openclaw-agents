"""
Deepseek API Client for Kimi LLM Models
Provides wrapper for Deepseek Kimi 2.5 and Kimi models
Supports streaming and non-streaming responses with function calling
"""

import os
import json
import requests
import httpx
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger("deepseek_client")


@dataclass
class KimiResponse:
    """Response from Kimi model"""
    content: str
    model: str
    tokens_input: int
    tokens_output: int
    stop_reason: str
    tool_calls: Optional[List[Dict]] = None


class DeepseekClient:
    """
    Deepseek API client for Kimi models

    Supported models:
    - deepseek-reasoner (full Kimi with extended thinking)
    - deepseek-chat (Kimi 2.5, optimized for speed)

    Pricing (as of Feb 2026):
    - Kimi 2.5: ~$0.14 input / $0.28 output per 1M tokens (60% cheaper than Sonnet)
    - Kimi: ~$0.27 input / $0.68 output per 1M tokens (75% cheaper than Opus)
    """

    BASE_URL = "https://api.deepseek.com/v1"
    MODELS = {
        "kimi-2.5": {
            "api_name": "deepseek-chat",
            "pricing": {
                "input": 0.14,      # $0.14 per 1M input tokens
                "output": 0.28,     # $0.28 per 1M output tokens
            },
            "context_window": 64000,
            "max_output_tokens": 8192,
            "description": "Kimi 2.5 - Fast, cost-effective for code generation",
            "cost_vs_sonnet": "95% cheaper",  # Sonnet: $3/$15, Kimi 2.5: $0.14/$0.28
            "use_case": "CodeGen agent - good for routine coding tasks"
        },
        "kimi": {
            "api_name": "deepseek-reasoner",
            "pricing": {
                "input": 0.27,      # $0.27 per 1M input tokens (cache: $0.135)
                "output": 0.68,     # $0.68 per 1M output tokens
            },
            "context_window": 128000,
            "max_output_tokens": 8192,
            "cache_size": 24000,    # 24K cache tokens (half-price)
            "description": "Kimi - Full model with extended thinking for complex reasoning",
            "cost_vs_opus": "82% cheaper",  # Opus: $15/$75, Kimi: $0.27/$0.68
            "use_case": "Security agent - better reasoning for threat modeling"
        }
    }

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Deepseek client with API key"""
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable not set")

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _validate_model(self, model: str) -> str:
        """Validate and get API model name"""
        if model not in self.MODELS:
            raise ValueError(f"Unsupported model: {model}. Supported: {list(self.MODELS.keys())}")
        return self.MODELS[model]["api_name"]

    def call(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        thinking_budget: Optional[int] = None,
        timeout: int = 60
    ) -> KimiResponse:
        """
        Call Deepseek API synchronously

        Args:
            model: "kimi-2.5" or "kimi"
            prompt: User message
            system_prompt: System prompt/persona
            temperature: 0.0-1.0 (default 0.7)
            max_tokens: Max output tokens
            tools: List of function definitions for tool calling
            thinking_budget: For kimi only, budget for extended thinking (8-10000)
            timeout: Request timeout in seconds

        Returns:
            KimiResponse with content, tokens, and tool calls
        """
        api_model = self._validate_model(model)
        model_config = self.MODELS[model]

        if max_tokens is None:
            max_tokens = model_config["max_output_tokens"]

        messages = []

        # Add system prompt if provided
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        # Add user message
        messages.append({
            "role": "user",
            "content": prompt
        })

        payload = {
            "model": api_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        # Add thinking budget for deepseek-reasoner
        if model == "kimi" and thinking_budget:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(thinking_budget, 10000)  # Max 10k tokens
            }

        # Add tools if provided
        if tools:
            payload["tools"] = tools

        try:
            response = requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=timeout
            )
            response.raise_for_status()

            data = response.json()

            # Extract response
            choice = data["choices"][0]
            message = choice["message"]

            content = message.get("content", "")
            stop_reason = choice.get("finish_reason", "stop")

            # Extract tool calls if present
            tool_calls = None
            if "tool_calls" in message and message["tool_calls"]:
                tool_calls = message["tool_calls"]

            # Extract tokens
            usage = data.get("usage", {})
            tokens_input = usage.get("prompt_tokens", 0)
            tokens_output = usage.get("completion_tokens", 0)

            return KimiResponse(
                content=content,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                stop_reason=stop_reason,
                tool_calls=tool_calls
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise

    async def call_async(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        thinking_budget: Optional[int] = None,
        timeout: int = 60
    ) -> KimiResponse:
        """
        Call Deepseek API asynchronously

        Args:
            model: "kimi-2.5" or "kimi"
            prompt: User message
            system_prompt: System prompt/persona
            temperature: 0.0-1.0
            max_tokens: Max output tokens
            tools: List of function definitions
            thinking_budget: Extended thinking budget
            timeout: Request timeout

        Returns:
            KimiResponse with content, tokens, and tool calls
        """
        api_model = self._validate_model(model)
        model_config = self.MODELS[model]

        if max_tokens is None:
            max_tokens = model_config["max_output_tokens"]

        messages = []

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        messages.append({
            "role": "user",
            "content": prompt
        })

        payload = {
            "model": api_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        if model == "kimi" and thinking_budget:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(thinking_budget, 10000)
            }

        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()

                data = response.json()
                choice = data["choices"][0]
                message = choice["message"]

                content = message.get("content", "")
                stop_reason = choice.get("finish_reason", "stop")

                tool_calls = None
                if "tool_calls" in message and message["tool_calls"]:
                    tool_calls = message["tool_calls"]

                usage = data.get("usage", {})
                tokens_input = usage.get("prompt_tokens", 0)
                tokens_output = usage.get("completion_tokens", 0)

                return KimiResponse(
                    content=content,
                    model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    stop_reason=stop_reason,
                    tool_calls=tool_calls
                )

        except httpx.HTTPError as e:
            logger.error(f"Async API request failed: {e}")
            raise

    def stream(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        timeout: int = 60
    ):
        """
        Stream response from Deepseek API

        Yields: Chunks of streamed content
        """
        api_model = self._validate_model(model)
        model_config = self.MODELS[model]

        if max_tokens is None:
            max_tokens = model_config["max_output_tokens"]

        messages = []

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        messages.append({
            "role": "user",
            "content": prompt
        })

        payload = {
            "model": api_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }

        try:
            with requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=timeout
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                choice = data["choices"][0]
                                delta = choice.get("delta", {})
                                if "content" in delta and delta["content"]:
                                    yield delta["content"]
                            except json.JSONDecodeError:
                                pass

        except requests.exceptions.RequestException as e:
            logger.error(f"Stream request failed: {e}")
            raise

    @staticmethod
    def get_pricing_info(model: str) -> Dict[str, Any]:
        """Get pricing information for a model"""
        if model not in DeepseekClient.MODELS:
            return {}

        config = DeepseekClient.MODELS[model]
        return {
            "model": model,
            "api_name": config["api_name"],
            "pricing": config["pricing"],
            "context_window": config["context_window"],
            "max_output_tokens": config["max_output_tokens"],
            "description": config["description"],
            "cost_savings": config.get("cost_vs_sonnet") or config.get("cost_vs_opus"),
            "use_case": config["use_case"]
        }

    @staticmethod
    def calculate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
        """Calculate cost for API call"""
        if model not in DeepseekClient.MODELS:
            return 0.0

        pricing = DeepseekClient.MODELS[model]["pricing"]
        cost = (tokens_input * pricing["input"] + tokens_output * pricing["output"]) / 1_000_000
        return round(cost, 6)


# Convenience functions for integration
def create_deepseek_client(api_key: Optional[str] = None) -> DeepseekClient:
    """Factory function to create Deepseek client"""
    return DeepseekClient(api_key)


def call_deepseek(
    model: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs
) -> KimiResponse:
    """Convenience function for single API call"""
    client = DeepseekClient()
    return client.call(model, prompt, system_prompt, **kwargs)
