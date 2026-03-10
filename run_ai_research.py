#!/usr/bin/env python3
"""
Run AI Research Scout for the past 24 hours
"""

import sys
import json
from pathlib import Path
from deep_research import deep_research

def main():
    query = """AI Research Scout: Latest AI developments from the past 24 hours (March 3-4, 2026). 
    
Focus areas:
1) New AI coding agents or automation tools (releases, updates, new frameworks)
2) Model releases or significant updates (GPT, Claude, Gemini, open-source models)
3) MCP (Model Context Protocol) server ecosystem changes and new tools
4) Multi-agent architecture developments relevant to OpenClaw
5) AI agent orchestration and workflow automation tools

Include specific examples, version numbers, GitHub releases, and actionable integration recommendations for OpenClaw's multi-agent system."""

    print("🔍 Starting AI Research Scout...")
    print(f"Query: {query[:100]}...")
    
    try:
        # Run deep research with tech mode
        result = deep_research(
            query=query,
            mode="tech",
            depth="standard"
        )
        
        # Save results
        output_file = Path("./data/research") / f"ai_research_scout_{Path().cwd().name}_{int(__import__('time').time())}.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            f.write(result)
        
        print(f"✅ Research complete! Saved to: {output_file}")
        print(f"📊 Report length: {len(result)} characters")
        
        # Print summary
        lines = result.split('\n')
        summary_lines = [line for line in lines[:20] if line.strip()]
        print("\n📋 Summary preview:")
        for line in summary_lines[:5]:
            print(f"  {line}")
        
        return result
        
    except Exception as e:
        print(f"❌ Research failed: {e}")
        return None

if __name__ == "__main__":
    main()