"""
OpenClaw MCP Server — Exposes OpenClaw agent tools to Claude Code
Run: python3 ./mcp_server.py
Add to Claude Code: claude mcp add --transport stdio openclaw -- python3 ./mcp_server.py
"""

import sys
import os
import json
import asyncio

# Load environment variables
from dotenv import load_dotenv
load_dotenv("./.env")

# Add openclaw to path so we can import agent_tools
sys.path.insert(0, ".")
from agent_tools import execute_tool, AGENT_TOOLS

# Try MCP SDK first, fall back to raw stdio protocol
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False


if HAS_MCP_SDK:
    # ═══════════════════════════════════════════════════════════════
    # MCP SDK Implementation
    # ═══════════════════════════════════════════════════════════════
    app = Server("openclaw")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        """Convert AGENT_TOOLS schemas to MCP Tool format."""
        tools = []
        for tool_def in AGENT_TOOLS:
            tools.append(types.Tool(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                inputSchema=tool_def.get("input_schema", {"type": "object", "properties": {}})
            ))
        return tools

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        """Route MCP tool calls to OpenClaw's execute_tool."""
        result = execute_tool(name, arguments)
        return [types.TextContent(type="text", text=result)]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

else:
    # ═══════════════════════════════════════════════════════════════
    # Raw JSON-RPC Stdio Fallback (no mcp package needed)
    # ═══════════════════════════════════════════════════════════════

    async def handle_request(request: dict) -> dict:
        method = request.get("method", "")
        req_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "openclaw", "version": "2.1.0"}
                }
            }

        elif method == "notifications/initialized":
            return None  # No response for notifications

        elif method == "tools/list":
            tools = []
            for tool_def in AGENT_TOOLS:
                tools.append({
                    "name": tool_def["name"],
                    "description": tool_def.get("description", ""),
                    "inputSchema": tool_def.get("input_schema", {"type": "object", "properties": {}})
                })
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools}
            }

        elif method == "tools/call":
            params = request.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = execute_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                    "isError": result.startswith("Error:") or result.startswith("Unknown tool:")
                }
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }

    async def main():
        """Read JSON-RPC messages from stdin, write responses to stdout."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_event_loop())

        buffer = b""
        while True:
            try:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buffer += chunk

                # Process complete lines
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        request = json.loads(line)
                        response = await handle_request(request)
                        if response is not None:
                            response_bytes = json.dumps(response).encode() + b"\n"
                            writer.write(response_bytes)
                            await writer.drain()
                    except json.JSONDecodeError:
                        continue
            except Exception:
                break


if __name__ == "__main__":
    asyncio.run(main())
