import sys
import os

path = './agent_tool_profiles.py'
with open(path, 'r') as f:
    content = f.read()

# Define the new trading_agent tools (12 trading + 7 betting)
trading_tools = {
    "kalshi_markets", "kalshi_portfolio", "kalshi_trade",
    "polymarket_monitor", "polymarket_portfolio", "polymarket_prices", "polymarket_trade",
    "trading_safety", "trading_strategies",
    "money_engine", "prediction_market", "arb_scanner",
    "betting_brain", "sportsbook_odds", "sportsbook_arb",
    "sports_predict", "sports_betting", "prediction_tracker", "bet_tracker"
}

# We also want to keep the utility tools that were already there
utility_tools = {
    "file_read", "file_write",
    "web_search", "web_fetch",
    "save_memory", "search_memory",
    "compute_math", "compute_stats", "compute_sort", "compute_search",
    "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
}

all_trading_agent_tools = trading_tools | utility_tools

# Now we need to update the AGENT_TOOL_PROFILES dictionary in the file.
# Since it's a python file, we can import it, modify the dict, and write it back, 
# but that might lose comments.
# Better to do a string replacement or use AST.

# Actually, I'll just rewrite the AGENT_TOOL_PROFILES part.

import ast

class ProfileUpdater(ast.NodeTransformer):
    def visit_Dict(self, node):
        if isinstance(node.parent, ast.Assign) and isinstance(node.parent.targets[0], ast.Name) and node.parent.targets[0].id == 'AGENT_TOOL_PROFILES':
            new_keys = []
            new_values = []
            
            # Keep track of which ones we've added
            added_trading = False
            
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'betting_agent':
                    continue # Remove betting_agent
                
                if isinstance(key, ast.Constant) and key.value == 'trading_agent':
                    # Update trading_agent
                    new_keys.append(key)
                    new_values.append(ast.Set(elts=[ast.Constant(value=t) for t in sorted(all_trading_agent_tools)]))
                    added_trading = True
                elif isinstance(key, ast.Constant) and key.value == 'overseer':
                    # Add recall_memory to overseer
                    existing_tools = set(elt.value for elt in value.elts if isinstance(elt, ast.Constant))
                    existing_tools.add('recall_memory')
                    new_keys.append(key)
                    new_values.append(ast.Set(elts=[ast.Constant(value=t) for t in sorted(existing_tools)]))
                elif isinstance(key, ast.Constant) and key.value == 'project_manager':
                    # Add recall_memory to project_manager
                    existing_tools = set(elt.value for elt in value.elts if isinstance(elt, ast.Constant))
                    existing_tools.add('recall_memory')
                    new_keys.append(key)
                    new_values.append(ast.Set(elts=[ast.Constant(value=t) for t in sorted(existing_tools)]))
                else:
                    new_keys.append(key)
                    new_values.append(value)
            
            node.keys = new_keys
            node.values = new_values
        return node

# Using AST might be overkill and lose formatting.
# Let's just use a simpler approach: read the file, find the sections, and replace them.

