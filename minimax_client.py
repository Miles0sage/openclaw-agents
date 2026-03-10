"""
MiniMax API Client for M2.5 Models
OpenAI-compatible API wrapper for MiniMax M2.5 and M2.5-Lightning
Supports sync, async, and streaming responses with function calling

MiniMax M2.5 Stats:
- 80.2% SWE-Bench Verified (SOTA for coding)
- 205K context window, 131K max output
- $0.30/1M input, $1.20/1M output (98% cheaper than Opus)
- 50 TPS standard, 100 TPS Lightning
"""

import os
import json
import requests
import httpx
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger("minimax_client")


@dataclass
class MiniMaxResponse:
    """Response from MiniMax model"""
    content: str
    model: str
    tokens_input: int
    tokens_output: int
    stop_reason: str
    tool_calls: Optional[List[Dict]] = None


class MiniMaxClient:
    """
    MiniMax API client for M2.5 models (OpenAI-compatible)

    Supported models:
    - m2.5 (MiniMax-M2.5, 50 TPS, $0.30/$1.20 per 1M tokens)
    - m2.5-lightning (MiniMax-M2.5-Lightning, 100 TPS, $0.30/$2.40 per 1M tokens)

    Pricing (as of Feb 2026):
    - M2.5: $0.30 input / $1.20 output per 1M tokens (98% cheaper than Opus)
    - M2.5-Lightning: $0.30 input / $2.40 output per 1M tokens (2x faster)
    """

    BASE_URL = "https://api.minimax.io/v1"
    MODELS = {
        "m2.5": {
            "api_name": "MiniMax-M2.5",
            "pricing": {
                "input": 0.30,
                "output": 1.20,
            },
            "context_window": 205000,
            "max_output_tokens": 131072,
            "speed_tps": 50,
            "description": "MiniMax M2.5 - SOTA coding (80.2% SWE-Bench), extended thinking",
            "cost_vs_opus": "98% cheaper",
            "use_case": "Complex coding, multi-file refactors, architecture implementation"
        },
        "m2.5-lightning": {
            "api_name": "MiniMax-M2.5-Lightning",
            "pricing": {
                "input": 0.30,
                "output": 2.40,
            },
            "context_window": 205000,
            "max_output_tokens": 131072,
            "speed_tps": 100,
            "description": "MiniMax M2.5 Lightning - 2x faster, same capability",
            "cost_vs_opus": "97% cheaper",
            "use_case": "Time-critical complex coding, real-time streaming"
        }
    }

    def __init__(self, api_key: Optional[str] = None):
        """Initialize MiniMax client with API key"""
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY environment variable not set")

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
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        timeout: int = 120
    ) -> MiniMaxResponse:
        """
        Call MiniMax API synchronously

        Args:
            model: "m2.5" or "m2.5-lightning"
            prompt: User message
            system_prompt: System prompt/persona
            temperature: 0.0-1.0 (default 0.3 for coding precision)
            max_tokens: Max output tokens (default from model config)
            tools: List of function definitions for tool calling
            timeout: Request timeout in seconds (default 120 for long reasoning)
        """
        api_model = self._validate_model(model)
        model_config = self.MODELS[model]

        if max_tokens is None:
            max_tokens = min(model_config["max_output_tokens"], 16384)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": api_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

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

            return MiniMaxResponse(
                content=content,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                stop_reason=stop_reason,
                tool_calls=tool_calls
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"MiniMax API request failed: {e}")
            raise

    async def call_async(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        timeout: int = 120
    ) -> MiniMaxResponse:
        """Call MiniMax API asynchronously"""
        api_model = self._validate_model(model)
        model_config = self.MODELS[model]

        if max_tokens is None:
            max_tokens = min(model_config["max_output_tokens"], 16384)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": api_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
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

                return MiniMaxResponse(
                    content=content,
                    model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    stop_reason=stop_reason,
                    tool_calls=tool_calls
                )

        except httpx.HTTPError as e:
            logger.error(f"MiniMax async API request failed: {e}")
            raise

    def stream(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        timeout: int = 120
    ):
        """
        Stream response from MiniMax API

        Yields: Chunks of streamed content
        """
        api_model = self._validate_model(model)
        model_config = self.MODELS[model]

        if max_tokens is None:
            max_tokens = min(model_config["max_output_tokens"], 16384)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

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
            logger.error(f"MiniMax stream request failed: {e}")
            raise

    @staticmethod
    def get_pricing_info(model: str) -> Dict[str, Any]:
        """Get pricing information for a model"""
        if model not in MiniMaxClient.MODELS:
            return {}

        config = MiniMaxClient.MODELS[model]
        return {
            "model": model,
            "api_name": config["api_name"],
            "pricing": config["pricing"],
            "context_window": config["context_window"],
            "max_output_tokens": config["max_output_tokens"],
            "speed_tps": config["speed_tps"],
            "description": config["description"],
            "cost_savings": config.get("cost_vs_opus"),
            "use_case": config["use_case"]
        }

    @staticmethod
    def calculate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
        """Calculate cost for API call"""
        if model not in MiniMaxClient.MODELS:
            return 0.0

        pricing = MiniMaxClient.MODELS[model]["pricing"]
        cost = (tokens_input * pricing["input"] + tokens_output * pricing["output"]) / 1_000_000
        return round(cost, 6)


# Convenience functions
def create_minimax_client(api_key: Optional[str] = None) -> MiniMaxClient:
    """Factory function to create MiniMax client"""
    return MiniMaxClient(api_key)


def call_minimax(
    model: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs
) -> MiniMaxResponse:
    """Convenience function for single API call"""
    client = MiniMaxClient()
    return client.call(model, prompt, system_prompt, **kwargs)
