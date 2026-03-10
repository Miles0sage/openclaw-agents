import sys

path = './agent_tool_profiles.py'
with open(path, 'r') as f:
    lines = f.readlines()

new_lines = []
skip_betting = False

for line in lines:
    if '"betting_agent": {' in line:
        skip_betting = True
        continue
    if skip_betting:
        if '},' in line:
            skip_betting = False
        continue
    
    if '"trading_agent": {' in line:
        new_lines.append(line)
        new_lines.append('        "kalshi_markets", "kalshi_portfolio", "kalshi_trade",\n')
        new_lines.append('        "polymarket_monitor", "polymarket_portfolio", "polymarket_prices", "polymarket_trade",\n')
        new_lines.append('        "trading_safety", "trading_strategies",\n')
        new_lines.append('        "money_engine", "prediction_market", "prediction_tracker",\n')
        new_lines.append('        "arb_scanner", "betting_brain", "sportsbook_odds", "sportsbook_arb",\n')
        new_lines.append('        "sports_predict", "sports_betting", "bet_tracker",\n')
        new_lines.append('        "file_read", "file_write", "recall_memory",\n')
        new_lines.append('        "web_search", "web_fetch",\n')
        new_lines.append('        "save_memory", "search_memory",\n')
        new_lines.append('        "compute_math", "compute_stats", "compute_sort", "compute_search",\n')
        new_lines.append('        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",\n')
        # We will skip the next lines until the closing brace of the original trading_agent
        continue
    
    # If we are inside the original trading_agent, skip its lines
    if len(new_lines) > 0 and new_lines[-1] == '    "trading_agent": {\n' and '},' not in line:
        if 'compute_prime' in line: # This is the last line of the original trading_agent
            pass 
        continue
    if len(new_lines) > 0 and new_lines[-1] == '    "trading_agent": {\n' and '},' in line:
        new_lines.append(line)
        continue

    # Add recall_memory to other agents
    if '"project_manager": {' in line:
        new_lines.append(line)
        new_lines.append('        "recall_memory",\n')
        continue
    if '"researcher": {' in line:
        new_lines.append(line)
        new_lines.append('        "recall_memory",\n')
        continue
    if '"overseer": {' in line:
        new_lines.append(line)
        new_lines.append('        "recall_memory",\n')
        continue
    if '"sales_agent": {' in line:
        new_lines.append(line)
        new_lines.append('        "recall_memory",\n')
        continue
    if '"browser_agent": {' in line:
        new_lines.append(line)
        new_lines.append('        "recall_memory",\n')
        continue

    new_lines.append(line)

with open(path, 'w') as f:
    f.writelines(new_lines)
