"""
Gemini API Client for Google's Generative AI Models
Raw requests.post() wrapper — consistent with minimax_client.py / deepseek_client.py patterns.

Supports two backends:
1. OpenRouter (primary) — pay-as-you-go, no rate limits, OpenAI-compatible API
2. Google Direct (fallback) — free tier, rate-limited (15 RPM)

Supported models:
- gemini-2.5-flash-lite  ($0.10/$0.40 per 1M tokens)
- gemini-2.5-flash       ($0.30/$2.50 per 1M tokens)
- gemini-3-flash-preview (FREE during preview — Google direct only)
"""

import os
import json
import requests
import httpx
import asyncio
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import logging

logger = logging.getLogger("gemini_client")

# OpenRouter model name mapping
OPENROUTER_MODEL_MAP = {
    "gemini-2.5-flash": "google/gemini-2.5-flash",
    "gemini-2.5-flash-lite": "google/gemini-2.5-flash-lite",
    "gemini-3-flash-preview": "google/gemini-2.5-flash",  # no preview on OR, use stable
}


@dataclass
class GeminiResponse:
    """Response from Gemini model"""
    content: str
    model: str
    tokens_input: int
    tokens_output: int
    stop_reason: str
    tool_calls: Optional[List[Dict]] = None


class GeminiClient:
    """
    Google Gemini API client via REST (no SDK dependency).

    Supported models:
    - gemini-2.5-flash-lite  ($0.10/$0.40 per 1M tokens)
    - gemini-2.5-flash       ($0.30/$2.50 per 1M tokens)
    - gemini-3-flash-preview (FREE during preview)
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MODELS = {
        "gemini-2.5-flash-lite": {
            "api_name": "gemini-2.5-flash-lite",
            "pricing": {"input": 0.10, "output": 0.40},
            "context_window": 1048576,
            "max_output_tokens": 65536,
            "description": "Gemini 2.5 Flash-Lite — cheapest, fast",
            "use_case": "Simple text tasks, classification, extraction",
        },
        "gemini-2.5-flash": {
            "api_name": "gemini-2.5-flash",
            "pricing": {"input": 0.30, "output": 2.50},
            "context_window": 1048576,
            "max_output_tokens": 65536,
            "description": "Gemini 2.5 Flash — balanced, native tool calling",
            "use_case": "Tool execution, coding, multi-step reasoning",
        },
        "gemini-3-flash-preview": {
            "api_name": "gemini-3-flash-preview",
            "pricing": {"input": 0.0, "output": 0.0},
            "context_window": 1048576,
            "max_output_tokens": 65536,
            "description": "Gemini 3 Flash Preview — FREE during preview",
            "use_case": "Research, planning, text generation (free!)",
        },
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.use_openrouter = bool(self.openrouter_key)
        if not self.api_key and not self.openrouter_key:
            raise ValueError("Neither GEMINI_API_KEY nor OPENROUTER_API_KEY is set")

    def _validate_model(self, model: str) -> str:
        if model not in self.MODELS:
            raise ValueError(f"Unsupported model: {model}. Supported: {list(self.MODELS.keys())}")
        return self.MODELS[model]["api_name"]

    @staticmethod
    def _convert_tools_to_gemini(tools: List[Dict]) -> List[Dict]:
        """Convert Anthropic-format tool schemas to Gemini functionDeclarations.

        Anthropic format:
            {"name": "foo", "description": "...", "input_schema": {...}}

        Gemini format:
            {"functionDeclarations": [{"name": "foo", "description": "...", "parameters": {...}}]}
        """
        declarations = []
        for tool in tools:
            decl: Dict[str, Any] = {
                "name": tool["name"],
                "description": tool.get("description", ""),
            }
            schema = tool.get("input_schema", {})
            if schema:
                # Gemini doesn't allow additionalProperties in function params
                params = dict(schema)
                params.pop("additionalProperties", None)
                decl["parameters"] = params
            declarations.append(decl)
        return [{"functionDeclarations": declarations}]

    @staticmethod
    def _normalize_tool_calls(gemini_parts: list) -> Optional[List[Dict]]:
        """Convert Gemini functionCall parts to Anthropic-style tool_use dicts.

        Gemini returns:
            {"functionCall": {"name": "foo", "args": {"key": "val"}}}

        We normalize to:
            {"type": "tool_use", "id": "...", "name": "foo", "input": {"key": "val"}}
        """
        tool_calls = []
        for i, part in enumerate(gemini_parts):
            fc = part.get("functionCall")
            if fc:
                tool_calls.append({
                    "type": "tool_use",
                    "id": f"gemini_tc_{i}",
                    "name": fc["name"],
                    "input": fc.get("args", {}),
                })
        return tool_calls if tool_calls else None

    def _call_openrouter(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        timeout: int = 120,
    ) -> GeminiResponse:
        """Call Gemini via OpenRouter (OpenAI-compatible API). No rate limits."""
        or_model = OPENROUTER_MODEL_MAP.get(model, "google/gemini-2.5-flash")

        if max_tokens is None:
            max_tokens = min(self.MODELS.get(model, {}).get("max_output_tokens", 16384), 16384)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": or_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Convert tools to OpenAI format
        if tools:
            openai_tools = []
            for t in tools:
                schema = t.get("input_schema", {})
                schema_copy = dict(schema)
                schema_copy.pop("additionalProperties", None)
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", "")[:200],
                        "parameters": schema_copy,
                    }
                })
            payload["tools"] = openai_tools

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "HTTP-Referer": "https://example.com",
                    "X-Title": "OpenClaw",
                },
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            stop_reason = choice.get("finish_reason", "stop")

            # Parse tool calls from OpenAI format to our normalized format
            tool_calls = None
            or_tool_calls = message.get("tool_calls", [])
            if or_tool_calls:
                tool_calls = []
                for i, tc in enumerate(or_tool_calls):
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"or_tc_{i}"),
                        "name": fn.get("name", ""),
                        "input": args,
                    })

            usage = data.get("usage", {})
            tokens_input = usage.get("prompt_tokens", 0)
            tokens_output = usage.get("completion_tokens", 0)

            logger.info(f"OpenRouter OK: {or_model} — {tokens_input}+{tokens_output} tokens")
            return GeminiResponse(
                content=content,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                stop_reason=stop_reason,
                tool_calls=tool_calls,
            )

        except requests.exceptions.RequestException as e:
            logger.warning(f"OpenRouter request failed: {e}")
            raise

    async def _call_openrouter_async(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        timeout: int = 120,
    ) -> GeminiResponse:
        """Async version of OpenRouter call."""
        or_model = OPENROUTER_MODEL_MAP.get(model, "google/gemini-2.5-flash")

        if max_tokens is None:
            max_tokens = min(self.MODELS.get(model, {}).get("max_output_tokens", 16384), 16384)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": or_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            openai_tools = []
            for t in tools:
                schema = t.get("input_schema", {})
                schema_copy = dict(schema)
                schema_copy.pop("additionalProperties", None)
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", "")[:200],
                        "parameters": schema_copy,
                    }
                })
            payload["tools"] = openai_tools

        try:
            async with httpx.AsyncClient(timeout=timeout) as http_client:
                response = await http_client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "HTTP-Referer": "https://example.com",
                        "X-Title": "OpenClaw",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            stop_reason = choice.get("finish_reason", "stop")

            tool_calls = None
            or_tool_calls = message.get("tool_calls", [])
            if or_tool_calls:
                tool_calls = []
                for i, tc in enumerate(or_tool_calls):
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"or_tc_{i}"),
                        "name": fn.get("name", ""),
                        "input": args,
                    })

            usage = data.get("usage", {})
            tokens_input = usage.get("prompt_tokens", 0)
            tokens_output = usage.get("completion_tokens", 0)

            logger.info(f"OpenRouter OK: {or_model} — {tokens_input}+{tokens_output} tokens")
            return GeminiResponse(
                content=content,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                stop_reason=stop_reason,
                tool_calls=tool_calls,
            )

        except httpx.HTTPError as e:
            logger.warning(f"OpenRouter async request failed: {e}")
            raise

    def call(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        timeout: int = 120,
    ) -> GeminiResponse:
        """Call Gemini API synchronously. Tries OpenRouter first, falls back to Google direct."""
        self._validate_model(model)

        # Try OpenRouter first (no rate limits)
        if self.use_openrouter:
            try:
                return self._call_openrouter(model, prompt, system_prompt, temperature, max_tokens, tools, timeout)
            except Exception as e:
                logger.warning(f"OpenRouter failed, falling back to Google direct: {e}")

        # Fallback: Google direct API
        if not self.api_key:
            raise ValueError("No GEMINI_API_KEY and OpenRouter failed")

        api_model = self.MODELS[model]["api_name"]

        if max_tokens is None:
            max_tokens = min(self.MODELS[model]["max_output_tokens"], 16384)

        # Build contents array
        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        # Build request payload
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        if tools:
            payload["tools"] = self._convert_tools_to_gemini(tools)

        url = f"{self.BASE_URL}/models/{api_model}:generateContent"

        try:
            response = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

            # Parse response
            candidates = data.get("candidates", [])
            if not candidates:
                return GeminiResponse(
                    content="",
                    model=model,
                    tokens_input=0,
                    tokens_output=0,
                    stop_reason="error",
                )

            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])
            stop_reason = candidate.get("finishReason", "STOP").lower()

            # Extract text content
            text_parts = [p["text"] for p in parts if "text" in p]
            content = "\n".join(text_parts)

            # Extract tool calls
            tool_calls = self._normalize_tool_calls(parts)

            # Token usage
            usage = data.get("usageMetadata", {})
            tokens_input = usage.get("promptTokenCount", 0)
            tokens_output = usage.get("candidatesTokenCount", 0)

            return GeminiResponse(
                content=content,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                stop_reason=stop_reason,
                tool_calls=tool_calls,
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"Gemini API request failed: {e}")
            raise

    async def call_async(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        timeout: int = 120,
    ) -> GeminiResponse:
        """Call Gemini API asynchronously. Tries OpenRouter first, falls back to Google direct."""
        self._validate_model(model)

        # Try OpenRouter first (no rate limits)
        if self.use_openrouter:
            try:
                return await self._call_openrouter_async(model, prompt, system_prompt, temperature, max_tokens, tools, timeout)
            except Exception as e:
                logger.warning(f"OpenRouter async failed, falling back to Google direct: {e}")

        # Fallback: Google direct API
        if not self.api_key:
            raise ValueError("No GEMINI_API_KEY and OpenRouter failed")

        api_model = self.MODELS[model]["api_name"]

        if max_tokens is None:
            max_tokens = min(self.MODELS[model]["max_output_tokens"], 16384)

        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        if tools:
            payload["tools"] = self._convert_tools_to_gemini(tools)

        url = f"{self.BASE_URL}/models/{api_model}:generateContent"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.api_key,
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                candidates = data.get("candidates", [])
                if not candidates:
                    return GeminiResponse(
                        content="", model=model,
                        tokens_input=0, tokens_output=0,
                        stop_reason="error",
                    )

                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                stop_reason = candidate.get("finishReason", "STOP").lower()

                text_parts = [p["text"] for p in parts if "text" in p]
                content = "\n".join(text_parts)
                tool_calls = self._normalize_tool_calls(parts)

                usage = data.get("usageMetadata", {})
                tokens_input = usage.get("promptTokenCount", 0)
                tokens_output = usage.get("candidatesTokenCount", 0)

                return GeminiResponse(
                    content=content,
                    model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    stop_reason=stop_reason,
                    tool_calls=tool_calls,
                )

        except httpx.HTTPError as e:
            logger.error(f"Gemini async API request failed: {e}")
            raise

    @staticmethod
    def calculate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
        if model not in GeminiClient.MODELS:
            return 0.0
        pricing = GeminiClient.MODELS[model]["pricing"]
        cost = (tokens_input * pricing["input"] + tokens_output * pricing["output"]) / 1_000_000
        return round(cost, 6)


# Convenience functions
def create_gemini_client(api_key: Optional[str] = None) -> GeminiClient:
    return GeminiClient(api_key)


def call_gemini(
    model: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs,
) -> GeminiResponse:
    client = GeminiClient()
    return client.call(model, prompt, system_prompt, **kwargs)
