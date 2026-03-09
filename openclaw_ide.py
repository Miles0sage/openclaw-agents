"""
OpenClaw IDE — Native tool-calling executor using Gemini + our 81 MCP tools.

Replaces OpenCode CLI with direct Gemini API calls + real tool execution.
This is our own IDE: the LLM sees tools, requests them, we execute them,
feed results back, loop until done. No subprocess, no CLI wrapper.

Fallback chain: Gemini 2.5 Flash → Gemini 3 Flash Preview (free) → Grok → MiniMax

Cost: ~$0.001-0.005/job (Gemini 2.5 Flash with tool calling)
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

from gemini_client import GeminiClient, GeminiResponse, OPENROUTER_MODEL_MAP
from agent_tools import execute_tool as _raw_execute_tool, AGENT_TOOLS
from cost_tracker import log_cost_event

logger = logging.getLogger("openclaw_ide")

# Load env
if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass

# Max tool-call iterations before we force-stop (prevents infinite loops)
MAX_ITERATIONS = 25

# Models in priority order (cheapest viable first)
MODEL_CHAIN = [
    "gemini-2.5-flash",          # $0.30/$2.50 per 1M — native tool calling, reliable
    "gemini-3-flash-preview",    # FREE — preview, less reliable but costs nothing
]


def _fix_schema_for_gemini(schema: dict) -> dict:
    """Fix JSON Schema issues that Gemini rejects (e.g. array without items)."""
    if not isinstance(schema, dict):
        return schema
    fixed = {}
    for k, v in schema.items():
        if isinstance(v, dict):
            v = _fix_schema_for_gemini(v)
            # Gemini requires 'items' on array-typed properties
            if v.get("type") == "array" and "items" not in v:
                v = {**v, "items": {"type": "string"}}
        fixed[k] = v
    return fixed


def _compact_tools(tools: list, max_tools: int = 81) -> list:
    """Shorten tool descriptions to save tokens. Keep name + params."""
    compact = []
    for t in tools[:max_tools]:
        schema = _fix_schema_for_gemini(t.get("input_schema", {}))
        compact.append({
            "name": t["name"],
            "description": t.get("description", "")[:120],
            "input_schema": schema,
        })
    return compact


def _execute_tool_safe(tool_name: str, tool_input: dict, job_id: str = "") -> str:
    """Execute a tool with error handling. Returns result string."""
    try:
        # Route through tool_router if available for phase gating
        try:
            from tool_router import get_registry
            registry = get_registry()
            result = registry.execute_tool(tool_name, tool_input, job_id=job_id)
            return result if isinstance(result, str) else json.dumps(result)
        except (ImportError, Exception):
            pass

        result = _raw_execute_tool(tool_name, tool_input)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})


async def execute_with_ide(
    prompt: str,
    tools: Optional[list] = None,
    system_prompt: str = "",
    workspace: str = "/root/openclaw",
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    max_iterations: int = MAX_ITERATIONS,
    timeout: int = 300,
    model: Optional[str] = None,
) -> dict:
    """
    Execute a prompt with native tool calling via Gemini API.

    This is the core IDE loop:
    1. Send prompt + tools to Gemini
    2. If Gemini returns tool_calls, execute them
    3. Feed tool results back to Gemini
    4. Repeat until Gemini stops calling tools or max iterations

    Returns: {"text": str, "tokens": int, "tool_calls": list, "cost_usd": float}
    """
    start_time = time.time()

    # Select tools
    if tools is None:
        tools = _compact_tools(AGENT_TOOLS)

    # Default system prompt
    if not system_prompt:
        system_prompt = (
            "You are an autonomous AI agent with access to tools. "
            "Execute the task by calling the appropriate tools. "
            "Read files before editing them. Test code after writing it. "
            f"Working directory: {workspace}\n"
            "When done, respond with your final summary (no tool calls)."
        )

    # Build conversation for multi-turn tool calling
    conversation = [{"role": "user", "parts": [{"text": prompt}]}]

    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    all_tool_calls = []
    final_text = ""
    iterations = 0

    # Try models in order
    selected_model = model or MODEL_CHAIN[0]

    try:
        client = GeminiClient()
    except ValueError as e:
        return {"text": f"IDE init failed: {e}", "tokens": 0, "tool_calls": [], "cost_usd": 0.0}

    gemini_tools = client._convert_tools_to_gemini(tools)

    for iteration in range(max_iterations):
        if time.time() - start_time > timeout:
            logger.warning(f"IDE timeout after {iteration} iterations for {job_id}/{phase}")
            break

        iterations = iteration + 1

        try:
            import httpx

            # Decide backend: OpenRouter (primary) or Google direct (fallback)
            use_or = client.use_openrouter
            provider_used = "openrouter" if use_or else "gemini"

            if use_or:
                # --- OpenRouter path (OpenAI-compatible) ---
                or_model = OPENROUTER_MODEL_MAP.get(selected_model, "google/gemini-2.5-flash")

                # Convert Gemini conversation format to OpenAI messages
                or_messages = []
                if system_prompt:
                    or_messages.append({"role": "system", "content": system_prompt})
                for turn in conversation:
                    role = turn["role"]
                    parts_list = turn.get("parts", [])
                    if role == "user":
                        # Check if it's tool results
                        if parts_list and "functionResponse" in parts_list[0]:
                            for p in parts_list:
                                fr = p["functionResponse"]
                                or_messages.append({
                                    "role": "tool",
                                    "tool_call_id": fr.get("_tool_call_id", f"tc_{fr['name']}"),
                                    "content": json.dumps(fr["response"]) if isinstance(fr["response"], dict) else str(fr["response"]),
                                })
                        else:
                            text = " ".join(p.get("text", "") for p in parts_list if "text" in p)
                            if text:
                                or_messages.append({"role": "user", "content": text})
                    elif role == "model":
                        # Reconstruct assistant message with tool_calls
                        content_text = " ".join(p.get("text", "") for p in parts_list if "text" in p)
                        tc_list = []
                        for i, p in enumerate(parts_list):
                            if "functionCall" in p:
                                fc = p["functionCall"]
                                tc_id = f"tc_{fc['name']}_{iteration}_{i}"
                                tc_list.append({
                                    "id": tc_id,
                                    "type": "function",
                                    "function": {
                                        "name": fc["name"],
                                        "arguments": json.dumps(fc.get("args", {})),
                                    }
                                })
                        msg: dict = {"role": "assistant"}
                        if content_text:
                            msg["content"] = content_text
                        if tc_list:
                            msg["tool_calls"] = tc_list
                            if not content_text:
                                msg["content"] = ""
                        elif not content_text:
                            msg["content"] = ""
                        or_messages.append(msg)

                # Build OpenAI-format tools
                or_tools = []
                for t_raw in (tools or []):
                    schema = t_raw.get("input_schema", {})
                    schema_copy = dict(schema)
                    schema_copy.pop("additionalProperties", None)
                    or_tools.append({
                        "type": "function",
                        "function": {
                            "name": t_raw["name"],
                            "description": t_raw.get("description", "")[:120],
                            "parameters": schema_copy,
                        }
                    })

                or_payload = {
                    "model": or_model,
                    "messages": or_messages,
                    "temperature": 0.2,
                    "max_tokens": 16384,
                }
                if or_tools:
                    or_payload["tools"] = or_tools

                async with httpx.AsyncClient(timeout=timeout) as http_client:
                    response = await http_client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {client.openrouter_key}",
                            "HTTP-Referer": "https://example.com",
                            "X-Title": "OpenClaw",
                        },
                        json=or_payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                or_content = message.get("content", "") or ""

                usage = data.get("usage", {})
                tokens_in = usage.get("prompt_tokens", 0)
                tokens_out = usage.get("completion_tokens", 0)
                total_tokens_in += tokens_in
                total_tokens_out += tokens_out
                step_cost = client.calculate_cost(selected_model, tokens_in, tokens_out)
                total_cost += step_cost

                # Convert OpenAI tool_calls back to Gemini parts format (for conversation continuity)
                parts = []
                if or_content:
                    parts.append({"text": or_content})
                or_tool_calls = message.get("tool_calls", [])
                for tc in or_tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parts.append({"functionCall": {"name": fn.get("name", ""), "args": args}})
                    # Store tc ID for tool result mapping
                    parts[-1]["functionCall"]["_or_tc_id"] = tc.get("id", "")

                text_parts = [p["text"] for p in parts if "text" in p]
                tool_call_parts = [p for p in parts if "functionCall" in p]

            else:
                # --- Google direct path (original) ---
                payload = {
                    "contents": conversation,
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 16384,
                    },
                    "tools": gemini_tools,
                }
                if system_prompt:
                    payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

                api_model = client.MODELS[selected_model]["api_name"]
                url = f"{client.BASE_URL}/models/{api_model}:generateContent"

                async with httpx.AsyncClient(timeout=timeout) as http_client:
                    response = await http_client.post(
                        url,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": client.api_key,
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                # Parse response
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.warning(f"IDE: No candidates from {selected_model} for {job_id}/{phase}")
                    break

                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])

                # Token tracking
                usage = data.get("usageMetadata", {})
                tokens_in = usage.get("promptTokenCount", 0)
                tokens_out = usage.get("candidatesTokenCount", 0)
                total_tokens_in += tokens_in
                total_tokens_out += tokens_out
                step_cost = client.calculate_cost(selected_model, tokens_in, tokens_out)
                total_cost += step_cost

                # Extract text and tool calls
                text_parts = [p["text"] for p in parts if "text" in p]
                tool_call_parts = [p for p in parts if "functionCall" in p]

            stop_reason = "STOP"

            if text_parts:
                final_text = "\n".join(text_parts)

            # If no tool calls, we're done — synthesize text from tool results if empty
            if not tool_call_parts and not final_text and all_tool_calls:
                # Model finished but didn't produce summary text — build one from tool results
                result_summaries = []
                for tc in all_tool_calls[-5:]:
                    result_summaries.append(f"Tool {tc['tool']}: {tc['result'][:500]}")
                final_text = "Task completed. Tool results:\n" + "\n".join(result_summaries)
            if not tool_call_parts:
                logger.info(
                    f"IDE: {job_id}/{phase} complete after {iterations} iterations, "
                    f"{len(all_tool_calls)} tool calls, ${total_cost:.6f}"
                )
                break

            # Add model response to conversation
            conversation.append({"role": "model", "parts": parts})

            # Execute each tool call and collect results
            tool_results = []
            for tc_part in tool_call_parts:
                fc = tc_part["functionCall"]
                tool_name = fc["name"]
                tool_input = fc.get("args", {})

                logger.info(f"IDE: {job_id}/{phase} calling {tool_name}({json.dumps(tool_input)[:100]})")

                # Execute tool in thread pool to not block event loop
                result_str = await asyncio.get_running_loop().run_in_executor(
                    None, _execute_tool_safe, tool_name, tool_input, job_id
                )

                # Truncate large results to save tokens
                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"

                all_tool_calls.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result_str[:2000],
                })

                fr_entry: Dict[str, Any] = {
                    "name": tool_name,
                    "response": {"result": result_str},
                }
                # Store OpenRouter tool_call_id for conversation continuity
                or_tc_id = fc.get("_or_tc_id")
                if or_tc_id:
                    fr_entry["_tool_call_id"] = or_tc_id
                tool_results.append({"functionResponse": fr_entry})

            # Add tool results to conversation for next iteration
            conversation.append({"role": "user", "parts": tool_results})

        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:300] if hasattr(e.response, 'text') else str(e)
            logger.warning(f"IDE: {selected_model} HTTP error: {error_body}")

            # Try next model in chain
            current_idx = MODEL_CHAIN.index(selected_model) if selected_model in MODEL_CHAIN else 0
            if current_idx + 1 < len(MODEL_CHAIN):
                selected_model = MODEL_CHAIN[current_idx + 1]
                logger.info(f"IDE: Falling back to {selected_model}")
                continue
            else:
                break

        except Exception as e:
            logger.error(f"IDE: Unexpected error in iteration {iteration}: {e}")
            break

    elapsed = time.time() - start_time

    # Log cost
    if total_cost > 0 and job_id:
        try:
            log_cost_event(
                agent="openclaw_ide",
                model=selected_model,
                input_tokens=total_tokens_in,
                output_tokens=total_tokens_out,
                cost_usd=total_cost,
                job_id=job_id,
                phase=phase,
                provider="openrouter" if client.use_openrouter else "gemini",
            )
        except Exception:
            pass

    result = {
        "text": final_text,
        "tokens": total_tokens_in + total_tokens_out,
        "tool_calls": all_tool_calls,
        "cost_usd": round(total_cost, 6),
        "model": selected_model,
        "iterations": iterations,
        "elapsed_seconds": round(elapsed, 1),
    }

    logger.info(
        f"IDE result: {job_id}/{phase} — {len(all_tool_calls)} tool calls, "
        f"{iterations} iterations, ${total_cost:.6f}, {elapsed:.1f}s"
    )

    return result


async def execute_ide_with_fallback(
    prompt: str,
    tools: Optional[list] = None,
    system_prompt: str = "",
    workspace: str = "/root/openclaw",
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    guardrails=None,
    **kwargs,
) -> dict:
    """
    Execute with IDE (Gemini native tool calling) as primary,
    then fall back to Grok/MiniMax text-only if Gemini fails.

    This replaces execute_with_fallback() from opencode_executor.py
    """
    # Primary: OpenClaw IDE (Gemini + native tool calling)
    try:
        result = await execute_with_ide(
            prompt=prompt,
            tools=tools,
            system_prompt=system_prompt,
            workspace=workspace,
            job_id=job_id,
            phase=phase,
            priority=priority,
        )
        if result and result.get("text"):
            return result
        logger.warning(f"IDE returned empty response for {job_id}/{phase}")
    except Exception as e:
        logger.warning(f"IDE failed for {job_id}/{phase}: {e}")

    # Fallback: Grok (text-only but cheap)
    try:
        from grok_executor import execute_with_grok
        logger.info(f"Falling back to Grok for {job_id}/{phase}")
        grok_result = await execute_with_grok(
            prompt=prompt, job_id=job_id, phase=phase,
            priority=priority, system_prompt=system_prompt,
        )
        if grok_result and grok_result.get("text"):
            return grok_result
    except Exception as e:
        logger.warning(f"Grok fallback failed: {e}")

    # Fallback: MiniMax (text-only)
    try:
        from minimax_executor import execute_with_minimax
        logger.info(f"Falling back to MiniMax for {job_id}/{phase}")
        mm_result = await execute_with_minimax(
            prompt=prompt, job_id=job_id, phase=phase,
            priority=priority, system_prompt=system_prompt,
        )
        if mm_result and mm_result.get("text"):
            return mm_result
    except Exception as e:
        logger.warning(f"MiniMax fallback failed: {e}")

    return {"text": "", "tokens": 0, "tool_calls": [], "cost_usd": 0.0}


# Quick self-test
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    async def test():
        print("=" * 60)
        print("OpenClaw IDE — Self-Test")
        print("=" * 60)

        # Test 1: Simple tool call (file_read)
        print("\nTest 1: Read a file via tool calling...")
        result = await execute_with_ide(
            prompt="Read the file ./bet_tracker.py and tell me how many actions it supports. List them.",
            job_id="ide-test-001",
            phase="test",
        )
        print(f"  Tool calls: {len(result['tool_calls'])}")
        print(f"  Cost: ${result['cost_usd']:.6f}")
        print(f"  Iterations: {result['iterations']}")
        print(f"  Model: {result['model']}")
        print(f"  Response: {result['text'][:300]}")

        if result["tool_calls"]:
            print(f"  Tools used: {[tc['tool'] for tc in result['tool_calls']]}")
            print("  PASS: Tool calling works!")
        else:
            print("  WARN: No tool calls made (model may have answered from memory)")

        # Test 2: Multi-tool (read + write)
        print("\nTest 2: Multi-tool task (sports_predict + write report)...")
        result2 = await execute_with_ide(
            prompt=(
                "Use the sports_predict tool with action='predict' to get today's NBA predictions. "
                "Then write a brief summary to os.environ.get("OPENCLAW_DATA_DIR", "./data")/betting/ide_test_report.md "
                "listing each game and the predicted winner."
            ),
            job_id="ide-test-002",
            phase="test",
            timeout=120,
        )
        print(f"  Tool calls: {len(result2['tool_calls'])}")
        print(f"  Cost: ${result2['cost_usd']:.6f}")
        print(f"  Iterations: {result2['iterations']}")
        print(f"  Tools used: {[tc['tool'] for tc in result2['tool_calls']]}")

        if any(tc["tool"] == "sports_predict" for tc in result2["tool_calls"]):
            print("  PASS: MCP tool (sports_predict) called successfully!")
        else:
            print("  FAIL: sports_predict not called")

        # Test 3: Quick sportsbook_odds test
        print("\nTest 3: Sportsbook odds lookup...")
        result3 = await execute_with_ide(
            prompt="Use sportsbook_odds with action='sports' to list available sports. Return just the sport keys.",
            job_id="ide-test-003",
            phase="test",
            timeout=60,
        )
        print(f"  Tool calls: {len(result3['tool_calls'])}")
        print(f"  Cost: ${result3['cost_usd']:.6f}")
        if any(tc["tool"] == "sportsbook_odds" for tc in result3["tool_calls"]):
            print("  PASS: sportsbook_odds called!")
        else:
            print("  WARN: sportsbook_odds not called")

        total_cost = result["cost_usd"] + result2["cost_usd"] + result3["cost_usd"]
        total_tools = len(result["tool_calls"]) + len(result2["tool_calls"]) + len(result3["tool_calls"])
        print(f"\n{'=' * 60}")
        print(f"Total: {total_tools} tool calls, ${total_cost:.6f}")
        print(f"{'=' * 60}")

    asyncio.run(test())
