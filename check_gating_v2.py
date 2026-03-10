import sys
import os
sys.path.append('.')
from agent_tools import AGENT_TOOLS
from agent_tool_profiles import AGENT_TOOL_PROFILES

all_tool_names = set(t['name'] for t in AGENT_TOOLS)
gated_tools = set()
for profile in AGENT_TOOL_PROFILES.values():
    gated_tools.update(profile)

unrestricted = all_tool_names - gated_tools
print(f"Total tools in AGENT_TOOLS: {len(all_tool_names)}")
print(f"Total gated tools: {len(gated_tools)}")
print(f"Unrestricted tools ({len(unrestricted)}):")
for t in sorted(unrestricted):
    print(f"  - {t}")

# Check if any tool in AGENT_TOOL_PROFILES is NOT in AGENT_TOOLS
extra_tools = gated_tools - all_tool_names
if extra_tools:
    print(f"\nTools in profiles but NOT in AGENT_TOOLS ({len(extra_tools)}):")
    for t in sorted(extra_tools):
        print(f"  - {t}")

