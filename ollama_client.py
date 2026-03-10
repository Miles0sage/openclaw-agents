"""Ollama Client — Route cheap tasks to local GPU via SSH tunnel.

This client connects to a local Ollama instance running on Miles' PC
(RTX 4060, 8GB VRAM) via SSH reverse tunnel at localhost:11434.

Cost: FREE (vs. $0.14/M tokens for Kimi)

Usage
-----
    from ollama_client import OllamaClient

    client = OllamaClient()

    # Check if tunnel is active
    if await client.is_available():
        result = await client.generate(
            prompt="Summarize this code...",
            model="qwen2.5:7b"
        )
        print(result["content"])
    else:
        print("Tunnel not active, falling back to cloud provider")
"""

import asyncio
import httpx
import logging
import json
import time
from typing import Optional, Dict, List

logger = logging.getLogger("openclaw.ollama_client")

OLLAMA_URL = "http://localhost:11434"
OLLAMA_TIMEOUT = 120.0  # 2 minutes — local inference can be slow
OLLAMA_AVAILABILITY_CHECK_TIMEOUT = 5.0  # Quick check

# Default models that fit 8GB VRAM
DEFAULT_MODELS = {
    "qwen2.5:7b": "qwen",      # Recommended — fast, good quality
    "deepseek-coder-v2:6.7b": "deepseek",  # Code-focused
    "mistral:7b": "mistral",    # Balanced
    "neural-chat:7b": "chat",   # Conversational
}


class OllamaClient:
    """Client for local Ollama inference via SSH reverse tunnel.

    Provides async/await interface to Ollama REST API.
    Handles timeouts, availability checks, and fallback signaling.
    """

    def __init__(self, base_url: str = OLLAMA_URL, timeout: float = OLLAMA_TIMEOUT):
        """Initialize Ollama client.

        Args:
            base_url: Ollama API endpoint (default: localhost:11434)
            timeout: Request timeout in seconds (default: 120)
        """
        self.base_url = base_url
        self.timeout = timeout
        self.availability_check_timeout = OLLAMA_AVAILABILITY_CHECK_TIMEOUT

    async def is_available(self) -> bool:
        """Check if Ollama is reachable (tunnel active and server running).

        This is a quick check with a short timeout. Used to decide whether
        to try Ollama before falling back to cloud providers.

        Returns:
            True if Ollama is reachable, False otherwise (tunnel down, server crashed, etc.)
        """
        try:
            async with httpx.AsyncClient(timeout=self.availability_check_timeout) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception as e:
            logger.debug(f"Ollama availability check failed: {e}")
            return False

    async def list_models(self) -> List[str]:
        """List all available local models.

        Returns:
            List of model names (e.g., ["qwen2.5:7b", "mistral:7b"])
            Empty list if Ollama is unreachable.
        """
        try:
            async with httpx.AsyncClient(timeout=self.availability_check_timeout) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.debug(f"Failed to list models: {e}")
        return []

    async def generate(
        self,
        prompt: str,
        model: str = "qwen2.5:7b",
        system: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[List[str]] = None,
    ) -> Dict:
        """Generate a completion from a local model.

        POST /api/generate — Ollama text generation endpoint.

        Args:
            prompt: Input prompt
            model: Model name (default: qwen2.5:7b)
            system: Optional system prompt
            temperature: Sampling temperature (0.0-2.0, default 0.7)
            top_p: Nucleus sampling parameter (default 0.9)
            max_tokens: Max output tokens (optional)
            stop_sequences: List of stop strings

        Returns:
            {
                "model": str,
                "content": str,
                "tokens_input": int,
                "tokens_output": int,
                "generation_time_ms": int,
            }

        Raises:
            RuntimeError: If Ollama is unreachable or request fails
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,  # We want the full response at once
            "temperature": temperature,
            "top_p": top_p,
        }

        if system:
            payload["system"] = system

        if max_tokens:
            # Ollama uses 'num_predict' instead of 'max_tokens'
            payload["options"] = {"num_predict": max_tokens}

        if stop_sequences:
            payload["stop"] = stop_sequences

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                start_time = time.time()
                r = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                r.raise_for_status()

                data = r.json()
                generation_time_ms = int((time.time() - start_time) * 1000)

                # Extract token counts — Ollama provides these
                tokens_input = data.get("prompt_eval_count", 0)
                tokens_output = data.get("eval_count", 0)

                logger.info(
                    f"Ollama generate success: model={model}, "
                    f"tokens={tokens_input}→{tokens_output}, "
                    f"time={generation_time_ms}ms"
                )

                return {
                    "model": model,
                    "content": data.get("response", ""),
                    "tokens_input": tokens_input,
                    "tokens_output": tokens_output,
                    "generation_time_ms": generation_time_ms,
                    "stop_reason": data.get("stop_reason", "stop"),
                }

        except httpx.TimeoutException as e:
            logger.warning(f"Ollama request timeout: {e}")
            raise RuntimeError(f"Ollama timeout after {self.timeout}s: {e}")
        except Exception as e:
            logger.warning(f"Ollama generate failed: {e}")
            raise RuntimeError(f"Ollama generate failed: {e}")

    async def chat(
        self,
        messages: List[Dict],
        model: str = "qwen2.5:7b",
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """Chat completion using a local model.

        Converts multi-turn messages to a single prompt for the /api/generate endpoint.
        (Some Ollama versions don't have /api/chat, so we use /api/generate instead.)

        Args:
            messages: List of conversation messages
                [
                    {"role": "system", "content": "You are helpful..."},
                    {"role": "user", "content": "What is 2+2?"},
                    {"role": "assistant", "content": "4"},
                    {"role": "user", "content": "And 3+3?"},
                ]
            model: Model name (default: qwen2.5:7b)
            temperature: Sampling temperature (default 0.7)
            top_p: Nucleus sampling (default 0.9)
            max_tokens: Max output tokens (optional)

        Returns:
            {
                "model": str,
                "content": str,
                "tokens_input": int,
                "tokens_output": int,
                "generation_time_ms": int,
            }

        Raises:
            RuntimeError: If Ollama is unreachable or request fails
        """
        # Convert messages to a flat prompt (since /api/chat may not be available)
        system_prompt = None
        prompt_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")

        full_prompt = "\n".join(prompt_parts)

        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "temperature": temperature,
            "top_p": top_p,
        }

        if system_prompt:
            payload["system"] = system_prompt

        if max_tokens:
            payload["options"] = {"num_predict": max_tokens}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                start_time = time.time()
                r = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                r.raise_for_status()

                data = r.json()
                generation_time_ms = int((time.time() - start_time) * 1000)

                tokens_input = data.get("prompt_eval_count", 0)
                tokens_output = data.get("eval_count", 0)

                logger.info(
                    f"Ollama chat success: model={model}, "
                    f"tokens={tokens_input}→{tokens_output}, "
                    f"time={generation_time_ms}ms"
                )

                return {
                    "model": model,
                    "content": data.get("response", ""),
                    "tokens_input": tokens_input,
                    "tokens_output": tokens_output,
                    "generation_time_ms": generation_time_ms,
                    "stop_reason": data.get("stop_reason", "stop"),
                }

        except httpx.TimeoutException as e:
            logger.warning(f"Ollama chat timeout: {e}")
            raise RuntimeError(f"Ollama timeout after {self.timeout}s: {e}")
        except Exception as e:
            logger.warning(f"Ollama chat failed: {e}")
            raise RuntimeError(f"Ollama chat failed: {e}")

    async def health(self) -> Dict:
        """Get Ollama server health status.

        Returns:
            {
                "status": "ok" | "unavailable",
                "version": str,
                "models_count": int,
                "models": [str, ...]
            }
        """
        try:
            async with httpx.AsyncClient(timeout=self.availability_check_timeout) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {
                        "status": "ok",
                        "models_count": len(models),
                        "models": models,
                    }
        except Exception as e:
            logger.debug(f"Health check failed: {e}")

        return {
            "status": "unavailable",
            "models_count": 0,
            "models": [],
        }


# Module-level singleton
_ollama_client = None


def get_ollama_client() -> OllamaClient:
    """Get or create the module-level Ollama client singleton."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client
