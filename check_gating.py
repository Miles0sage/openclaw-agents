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
print(f"Total tools: {len(all_tool_names)}")
print(f"Unrestricted tools ({len(unrestricted)}):")
for t in sorted(unrestricted):
    print(f"  - {t}")

# Check specific tools
overseer_tools = AGENT_TOOL_PROFILES.get('overseer', set())
print("\nOverseer tools:")
for t in sorted(overseer_tools):
    print(f"  - {t}")

# Check if tmux_agents and manage_reactions are ONLY in overseer
for role, tools in AGENT_TOOL_PROFILES.items():
    if role == 'overseer': continue
    if 'tmux_agents' in tools:
        print(f"WARNING: tmux_agents found in {role}")
    if 'manage_reactions' in tools:
        print(f"WARNING: manage_reactions found in {role}")

