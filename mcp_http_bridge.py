"""
OpenClaw MCP HTTP Bridge — Exposes MCP server over HTTP for Oz agents

This bridge converts the stdio-based MCP protocol to HTTP, allowing:
- Oz cloud agents to call OpenClaw tools
- Remote agents to access OpenClaw resources
- Integration with HTTP-based MCP clients

Run: python3 ./mcp_http_bridge.py
Then set --mcp flag in Oz agents to:
  --mcp '{"openclaw":{"type":"http","url":"http://localhost:8787/mcp"}}'
"""

import sys
import os
import json
import asyncio
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# Load environment variables
from dotenv import load_dotenv
load_dotenv("./.env")

# Add openclaw to path
sys.path.insert(0, ".")
from agent_tools import execute_tool, AGENT_TOOLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_http_bridge")

app = FastAPI(
    title="OpenClaw MCP HTTP Bridge",
    description="HTTP bridge for OpenClaw MCP server",
    version="1.0.0"
)


@app.get("/mcp/tools")
async def list_tools():
    """List all available OpenClaw tools via MCP."""
    tools = []
    for tool_def in AGENT_TOOLS:
        tools.append({
            "name": tool_def["name"],
            "description": tool_def.get("description", ""),
            "inputSchema": tool_def.get("input_schema", {"type": "object", "properties": {}})
        })
    return {"tools": tools}


@app.post("/mcp/call")
async def call_tool(request: dict):
    """Call an OpenClaw tool via MCP.

    Expected request format:
    {
        "name": "tool_name",
        "arguments": {"arg1": "value1", ...}
    }
    """
    try:
        name = request.get("name", "")
        arguments = request.get("arguments", {})

        if not name:
            raise HTTPException(status_code=400, detail="Missing tool name")

        result = execute_tool(name, arguments)

        return {
            "content": [{"type": "text", "text": result}],
            "isError": result.startswith("Error:") or result.startswith("Unknown tool:")
        }
    except Exception as e:
        logger.error(f"Tool call error: {e}")
        return JSONResponse(
            status_code=500,
            content={"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}
        )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "openclaw_mcp_http_bridge",
        "tools_available": len(AGENT_TOOLS)
    }


@app.get("/")
async def root():
    """Root endpoint with API documentation."""
    return {
        "service": "OpenClaw MCP HTTP Bridge",
        "version": "1.0.0",
        "endpoints": {
            "/mcp/tools": "GET - List all available MCP tools",
            "/mcp/call": "POST - Call a tool with arguments",
            "/health": "GET - Health check",
            "/docs": "GET - Interactive API documentation (Swagger)"
        },
        "usage": {
            "description": "Configure Oz agents to use this MCP server",
            "oz_mcp_flag": "--mcp '{\"openclaw\":{\"type\":\"http\",\"url\":\"http://localhost:8787/mcp\"}}'",
            "environment_url": "https://<your-domain>/mcp (for cloud agents)"
        }
    }


if __name__ == "__main__":
    port = int(os.getenv("MCP_HTTP_PORT", "8787"))
    host = os.getenv("MCP_HTTP_HOST", "0.0.0.0")

    logger.info(f"Starting OpenClaw MCP HTTP Bridge on {host}:{port}")
    logger.info(f"Available tools: {len(AGENT_TOOLS)}")
    logger.info(f"API docs at http://{host}:{port}/docs")

    uvicorn.run(app, host=host, port=port, log_level="info")
