import sys
import os

# Add the current directory to sys.path to import agent_tools and agent_tool_profiles
sys.path.append('.')

try:
    from agent_tools import AGENT_TOOLS
    from agent_tool_profiles import AGENT_TOOL_PROFILES

    all_tools = set(t['name'] for t in AGENT_TOOLS)
    gated_tools = set()
    for tools in AGENT_TOOL_PROFILES.values():
        gated_tools.update(tools)

    unrestricted_tools = all_tools - gated_tools
    
    print(f"Total tools: {len(all_tools)}")
    print(f"Gated tools: {len(gated_tools)}")
    print(f"Unrestricted tools: {len(unrestricted_tools)}")
    print("\nUnrestricted tools list:")
    for tool in sorted(unrestricted_tools):
        print(tool)

except Exception as e:
    print(f"Error: {e}")
