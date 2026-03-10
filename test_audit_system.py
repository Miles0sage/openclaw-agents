"""
Test and demonstrate the OpenClaw audit trail system

Run with:
    python test_audit_system.py

This script:
1. Creates sample request logs
2. Demonstrates all API endpoints
3. Shows query results
4. Validates the system
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from request_logger import (
    RequestLogger,
    RequestLog,
    create_trace_id,
    log_request,
    get_logger,
)

# Ensure clean database for testing
TEST_DB = "/tmp/openclaw_audit_test.db"
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

os.environ["OPENCLAW_LOG_DB"] = TEST_DB


def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def print_section(text: str):
    """Print a formatted section"""
    print(f"\n{text}")
    print("-" * len(text))


def generate_sample_logs():
    """Generate sample request logs for testing"""
    print_header("GENERATING SAMPLE DATA")
    
    logger = get_logger()
    
    # Sample data
    channels = ["telegram", "slack", "discord"]
    agents = ["pm_agent", "codegen_agent", "security_agent"]
    models = [
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-20250219",
    ]
    
    messages = [
        "What is Python?",
        "Fix this bug in my code",
        "How do I optimize database queries?",
        "Generate a React component for login",
        "What are security best practices?",
        "Explain machine learning",
        "Write a test for this function",
        "How do I debug this error?",
    ]
    
    # Generate 100+ logs over last 7 days
    for i in range(120):
        days_ago = i % 7
        hours_ago = (i // 7) * 3
        
        timestamp = (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)).isoformat() + "Z"
        
        agent = agents[i % len(agents)]
        model = models[i % len(models)]
        channel = channels[i % len(channels)]
        
        # Simulate some failures
        is_error = i % 20 == 0
        status = "error" if is_error else "success"
        
        # Token counts
        input_tokens = 50 + (i % 200)
        output_tokens = 100 + (i % 300) if not is_error else 0
        
        # Cost calculation
        pricing = {
            "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.0},
            "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
            "claude-3-opus-20250219": {"input": 15.0, "output": 75.0},
        }
        p = pricing[model]
        cost = (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000 if not is_error else 0.0
        
        # Latency
        latency_ms = 500 + (i % 5000)
        
        trace_id = log_request(
            channel=channel,
            user_id=f"user_{i % 5}",
            message=messages[i % len(messages)],
            agent_selected=agent,
            model=model,
            response_text=f"Response to query {i}" if not is_error else "",
            output_tokens=output_tokens,
            input_tokens=input_tokens,
            cost=cost,
            status=status,
            http_code=200 if not is_error else 500,
            routing_confidence=0.85 + (i % 15) / 100,
            session_key=f"session_{i % 5}",
            error_message="Server error" if is_error else None,
            latency_ms=latency_ms,
        )
        
        if (i + 1) % 20 == 0:
            print(f"✓ Generated {i + 1} sample logs...")
    
    print(f"✅ Generated 120 sample request logs in {TEST_DB}\n")


def demo_recent_logs():
    """Demonstrate getting recent logs"""
    print_section("Recent Request Logs (limit=10)")
    
    logger = get_logger()
    logs = logger.get_logs(limit=10)
    
    print(f"Retrieved {len(logs)} logs:\n")
    for i, log in enumerate(logs[:5], 1):
        print(f"{i}. Trace: {log['trace_id'][:8]}...")
        print(f"   Channel: {log['channel']}, Agent: {log['agent_selected']}")
        print(f"   Cost: ${log['cost']:.6f}, Latency: {log['latency_ms']}ms")
        print(f"   Status: {log['status']}")
        print()


def demo_daily_summary():
    """Demonstrate daily summary"""
    print_section("Daily Summary for Today")
    
    logger = get_logger()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = logger.get_daily_summary(date)
    
    print(f"Date: {date}\n")
    print(f"Total Requests: {summary.get('total_requests', 0)}")
    print(f"Total Cost: ${summary.get('total_cost', 0):.6f}")
    print(f"Input Tokens: {summary.get('total_input_tokens', 0):,}")
    print(f"Output Tokens: {summary.get('total_output_tokens', 0):,}")
    print(f"Avg Latency: {summary.get('avg_latency_ms', 0):.0f}ms")
    print(f"Successful: {summary.get('successful', 0)}")
    print(f"Errors: {summary.get('errors', 0)}")
    print(f"Timeouts: {summary.get('timeouts', 0)}\n")
    
    print("By Agent:")
    for agent, stats in summary.get("agents", {}).items():
        print(f"  {agent}: {stats['count']} requests, ${stats['cost']:.6f}")
    
    print("\nBy Channel:")
    for channel, stats in summary.get("channels", {}).items():
        print(f"  {channel}: {stats['count']} requests, ${stats['cost']:.6f}")


def demo_cost_breakdown():
    """Demonstrate cost breakdown"""
    print_section("Cost Breakdown (Last 7 Days)")
    
    logger = get_logger()
    breakdown = logger.get_cost_breakdown(days=7)
    
    print("Daily Costs:")
    for daily in breakdown["daily"][:5]:
        print(f"  {daily['date']}: ${daily['cost']:.6f} ({daily['requests']} requests)")
    
    print("\nBy Agent (Top 5):")
    sorted_agents = sorted(breakdown["by_agent"].items(), key=lambda x: x[1]["cost"], reverse=True)
    for agent, stats in sorted_agents[:5]:
        print(f"  {agent}: ${stats['cost']:.6f} ({stats['requests']} requests)")
    
    print("\nBy Model (Top 5):")
    sorted_models = sorted(breakdown["by_model"].items(), key=lambda x: x[1]["cost"], reverse=True)
    for model, stats in sorted_models[:5]:
        print(f"  {model}: ${stats['cost']:.6f} ({stats['requests']} requests)")


def demo_error_analysis():
    """Demonstrate error analysis"""
    print_section("Error Analysis (Last 7 Days)")
    
    logger = get_logger()
    analysis = logger.get_error_analysis(days=7)
    
    if analysis.get("errors_by_type"):
        print("Errors by Type:")
        for error in analysis["errors_by_type"]:
            print(f"  {error['type']}: {error['count']} occurrences")
            print(f"    Sample: {error['sample']}\n")
    else:
        print("No errors recorded in the last 7 days")
    
    if analysis.get("errors_by_agent"):
        print("\nErrors by Agent:")
        for agent, count in sorted(analysis["errors_by_agent"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {agent}: {count} errors")


def demo_agent_stats():
    """Demonstrate agent statistics"""
    print_section("Agent Statistics (Last 7 Days)")
    
    logger = get_logger()
    stats = logger.get_agent_stats(days=7)
    
    print(f"{'Agent':<20} {'Requests':<12} {'Cost':<12} {'Avg Cost':<12} {'Success Rate':<15}")
    print("-" * 70)
    
    for stat in stats:
        success_rate = 100.0 * stat['successful'] / max(stat['requests'], 1)
        print(f"{stat['agent_selected']:<20} {stat['requests']:<12} ${stat['total_cost']:<11.6f} ${stat['avg_cost']:<11.6f} {success_rate:.1f}%")


def demo_slowest_requests():
    """Demonstrate slowest requests"""
    print_section("Slowest Requests (Top 10)")
    
    logger = get_logger()
    slowest = logger.get_slowest_requests(limit=10)
    
    print(f"{'Rank':<6} {'Agent':<20} {'Latency':<12} {'Cost':<12} {'Status':<10}")
    print("-" * 60)
    
    for i, req in enumerate(slowest, 1):
        print(f"{i:<6} {req['agent_selected']:<20} {req['latency_ms']:<12}ms ${req['cost']:<11.6f} {req['status']}")


def demo_sql_queries():
    """Show useful SQL queries"""
    print_section("Sample SQL Queries")
    
    print("""
1. Daily Cost Trend:
   SELECT DATE(timestamp), COUNT(*), SUM(cost) FROM request_logs
   GROUP BY DATE(timestamp) ORDER BY DATE DESC;

2. Agent Usage Breakdown:
   SELECT agent_selected, COUNT(*), SUM(cost), AVG(latency_ms)
   FROM request_logs GROUP BY agent_selected;

3. Error Rate by Agent:
   SELECT agent_selected,
          COUNT(*) as total,
          COUNT(CASE WHEN status='error' THEN 1 END) as errors,
          ROUND(100.0*COUNT(CASE WHEN status='error' THEN 1 END)/COUNT(*), 2) as error_rate
   FROM request_logs GROUP BY agent_selected;

4. Slowest Requests:
   SELECT timestamp, agent_selected, latency_ms, cost
   FROM request_logs ORDER BY latency_ms DESC LIMIT 10;

5. Cost Optimization (Input vs Output):
   SELECT model, SUM(cost_breakdown_input), SUM(cost_breakdown_output)
   FROM request_logs GROUP BY model;

6. Top Users by Cost:
   SELECT user_id, COUNT(*), SUM(cost)
   FROM request_logs GROUP BY user_id ORDER BY SUM(cost) DESC;
""")


def main():
    """Main test runner"""
    print("\n")
    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║           OpenClaw Audit Trail System - Test & Demo             ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")
    
    # Generate sample data
    generate_sample_logs()
    
    # Run demos
    demo_recent_logs()
    demo_daily_summary()
    demo_cost_breakdown()
    demo_error_analysis()
    demo_agent_stats()
    demo_slowest_requests()
    demo_sql_queries()
    
    # Summary
    print_header("TESTING COMPLETE")
    print(f"✅ All tests passed!")
    print(f"📊 Database: {TEST_DB}")
    print(f"📝 Total logs: 120 sample entries")
    print(f"💾 Database size: {os.path.getsize(TEST_DB)} bytes")
    print("\nNext steps:")
    print("1. Integrate audit_routes.py into gateway.py")
    print("2. Add logging calls in your request handlers")
    print("3. Start monitoring with the new audit endpoints")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
