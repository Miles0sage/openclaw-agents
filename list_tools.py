import sys
import os

# Add the current directory to sys.path to import agent_tools
sys.path.append('.')

try:
    from agent_tools import AGENT_TOOLS
    tool_names = [t['name'] for t in AGENT_TOOLS]
    print('\n'.join(sorted(tool_names)))
except Exception as e:
    print(f"Error: {e}")
