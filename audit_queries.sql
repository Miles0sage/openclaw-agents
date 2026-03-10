/*
OpenClaw Audit Trail - Sample SQL Queries

This file contains useful queries for analyzing request logs and audit data.
Run these against the D1 database to generate insights.
*/

-- ============================================================================
-- DAILY TRENDS
-- ============================================================================

-- Daily cost trends (last 30 days)
SELECT
    DATE(timestamp) as date,
    COUNT(*) as total_requests,
    SUM(cost) as total_cost,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    AVG(latency_ms) as avg_latency_ms,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful_requests,
    COUNT(CASE WHEN status = 'error' THEN 1 END) as failed_requests,
    ROUND(100.0 * COUNT(CASE WHEN status = 'success' THEN 1 END) / COUNT(*), 2) as success_rate
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY DATE(timestamp)
ORDER BY date DESC;


-- Hourly cost trends (last 24 hours)
SELECT
    datetime(timestamp, 'start of hour') as hour,
    COUNT(*) as requests,
    SUM(cost) as cost,
    AVG(routing_confidence) as avg_confidence,
    AVG(latency_ms) as avg_latency
FROM request_logs
WHERE timestamp >= datetime('now', '-24 hours')
GROUP BY datetime(timestamp, 'start of hour')
ORDER BY hour DESC;


-- ============================================================================
-- AGENT USAGE STATISTICS
-- ============================================================================

-- Agent usage breakdown (last 30 days)
SELECT
    agent_selected,
    COUNT(*) as requests,
    SUM(cost) as total_cost,
    AVG(cost) as avg_cost,
    MIN(cost) as min_cost,
    MAX(cost) as max_cost,
    AVG(latency_ms) as avg_latency_ms,
    MAX(latency_ms) as max_latency_ms,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
    COUNT(CASE WHEN status = 'error' THEN 1 END) as errors,
    COUNT(CASE WHEN status = 'timeout' THEN 1 END) as timeouts,
    ROUND(100.0 * COUNT(CASE WHEN status = 'success' THEN 1 END) / COUNT(*), 2) as success_rate,
    AVG(routing_confidence) as avg_confidence
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY agent_selected
ORDER BY requests DESC;


-- Agent routing confidence trends
SELECT
    agent_selected,
    DATE(timestamp) as date,
    COUNT(*) as requests,
    AVG(routing_confidence) as avg_confidence,
    MIN(routing_confidence) as min_confidence,
    MAX(routing_confidence) as max_confidence
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY agent_selected, DATE(timestamp)
ORDER BY agent_selected, date DESC;


-- ============================================================================
-- MODEL USAGE
-- ============================================================================

-- Model usage breakdown
SELECT
    model,
    COUNT(*) as requests,
    SUM(cost) as total_cost,
    AVG(cost) as avg_cost,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    AVG(output_tokens) as avg_output_tokens,
    AVG(latency_ms) as avg_latency_ms,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY model
ORDER BY total_cost DESC;


-- Model efficiency (cost per token)
SELECT
    model,
    SUM(cost) as total_cost,
    SUM(input_tokens + output_tokens) as total_tokens,
    ROUND(SUM(cost) / NULLIF(SUM(input_tokens + output_tokens), 0) * 1000000, 6) as cost_per_million_tokens,
    COUNT(*) as requests,
    AVG(latency_ms) as avg_latency_ms
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days') AND status = 'success'
GROUP BY model
ORDER BY cost_per_million_tokens DESC;


-- ============================================================================
-- CHANNEL ANALYSIS
-- ============================================================================

-- Channel usage and costs
SELECT
    channel,
    COUNT(*) as requests,
    COUNT(DISTINCT user_id) as unique_users,
    SUM(cost) as total_cost,
    AVG(cost) as avg_cost,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
    COUNT(CASE WHEN status = 'error' THEN 1 END) as errors,
    ROUND(100.0 * COUNT(CASE WHEN status = 'success' THEN 1 END) / COUNT(*), 2) as success_rate
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY channel
ORDER BY total_cost DESC;


-- ============================================================================
-- ERROR ANALYSIS
-- ============================================================================

-- Error rates by type (last 30 days)
SELECT
    error_type,
    COUNT(*) as occurrences,
    error_message as sample_error,
    MIN(timestamp) as first_occurrence,
    MAX(timestamp) as last_occurrence
FROM error_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY error_type
ORDER BY occurrences DESC;


-- Errors by agent and error type
SELECT
    rl.agent_selected,
    el.error_type,
    COUNT(*) as count,
    el.error_message as sample
FROM error_logs el
JOIN request_logs rl ON el.trace_id = rl.trace_id
WHERE el.timestamp >= datetime('now', '-30 days')
GROUP BY rl.agent_selected, el.error_type
ORDER BY count DESC;


-- HTTP error code distribution
SELECT
    http_code,
    COUNT(*) as occurrences,
    COUNT(DISTINCT user_id) as affected_users,
    AVG(latency_ms) as avg_latency
FROM request_logs
WHERE http_code >= 400 AND timestamp >= datetime('now', '-30 days')
GROUP BY http_code
ORDER BY occurrences DESC;


-- Failed requests with details
SELECT
    trace_id,
    timestamp,
    channel,
    agent_selected,
    model,
    http_code,
    error_message,
    latency_ms
FROM request_logs
WHERE status != 'success' AND timestamp >= datetime('now', '-7 days')
ORDER BY timestamp DESC
LIMIT 50;


-- ============================================================================
-- PERFORMANCE ANALYSIS
-- ============================================================================

-- Slowest requests (all time)
SELECT
    trace_id,
    timestamp,
    channel,
    agent_selected,
    model,
    message_length,
    latency_ms,
    cost,
    status
FROM request_logs
WHERE status = 'success'
ORDER BY latency_ms DESC
LIMIT 20;


-- Latency percentiles (last 7 days)
SELECT
    agent_selected,
    COUNT(*) as requests,
    ROUND(AVG(latency_ms), 2) as p50_latency,
    MAX(CASE
        WHEN COUNT(*) OVER (PARTITION BY agent_selected ORDER BY latency_ms) 
             >= CEIL(0.5 * COUNT(*) OVER (PARTITION BY agent_selected))
        THEN latency_ms
    END) as p50,
    MAX(CASE
        WHEN COUNT(*) OVER (PARTITION BY agent_selected ORDER BY latency_ms) 
             >= CEIL(0.95 * COUNT(*) OVER (PARTITION BY agent_selected))
        THEN latency_ms
    END) as p95,
    MAX(latency_ms) as p99
FROM request_logs
WHERE timestamp >= datetime('now', '-7 days') AND status = 'success'
GROUP BY agent_selected;


-- Long-running requests by agent
SELECT
    agent_selected,
    COUNT(CASE WHEN latency_ms > 5000 THEN 1 END) as slow_requests,
    ROUND(100.0 * COUNT(CASE WHEN latency_ms > 5000 THEN 1 END) / COUNT(*), 2) as slow_percentage,
    MAX(latency_ms) as max_latency,
    AVG(latency_ms) as avg_latency
FROM request_logs
WHERE timestamp >= datetime('now', '-7 days')
GROUP BY agent_selected
ORDER BY slow_requests DESC;


-- ============================================================================
-- COST OPTIMIZATION
-- ============================================================================

-- Cost breakdown: input vs output
SELECT
    model,
    COUNT(*) as requests,
    SUM(cost_breakdown_input) as input_costs,
    SUM(cost_breakdown_output) as output_costs,
    SUM(cost) as total_cost,
    ROUND(100.0 * SUM(cost_breakdown_input) / SUM(cost), 2) as input_percentage,
    ROUND(100.0 * SUM(cost_breakdown_output) / SUM(cost), 2) as output_percentage
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days') AND status = 'success'
GROUP BY model
ORDER BY total_cost DESC;


-- Cost per token by model (optimization metric)
SELECT
    model,
    SUM(input_tokens) as input_tokens,
    SUM(output_tokens) as output_tokens,
    SUM(cost_breakdown_input) as input_cost,
    SUM(cost_breakdown_output) as output_cost,
    ROUND(SUM(cost_breakdown_input) / NULLIF(SUM(input_tokens), 0) * 1000000, 6) as cost_per_input_million,
    ROUND(SUM(cost_breakdown_output) / NULLIF(SUM(output_tokens), 0) * 1000000, 6) as cost_per_output_million
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days') AND status = 'success'
GROUP BY model;


-- Identify expensive agents (potential optimization targets)
SELECT
    agent_selected,
    COUNT(*) as requests,
    SUM(cost) as total_cost,
    AVG(cost) as avg_cost,
    AVG(output_tokens) as avg_output_tokens,
    CASE
        WHEN AVG(cost) > (SELECT AVG(cost) * 1.5 FROM request_logs WHERE timestamp >= datetime('now', '-30 days'))
        THEN 'REVIEW'
        ELSE 'NORMAL'
    END as status
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days') AND status = 'success'
GROUP BY agent_selected
HAVING COUNT(*) >= 10
ORDER BY avg_cost DESC;


-- ============================================================================
-- USER BEHAVIOR
-- ============================================================================

-- Top users by request volume
SELECT
    user_id,
    COUNT(*) as requests,
    COUNT(DISTINCT DATE(timestamp)) as active_days,
    SUM(cost) as total_cost,
    AVG(cost) as avg_cost,
    COUNT(DISTINCT channel) as channels_used
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY user_id
ORDER BY requests DESC
LIMIT 20;


-- User usage by channel
SELECT
    user_id,
    channel,
    COUNT(*) as requests,
    SUM(cost) as total_cost,
    AVG(latency_ms) as avg_latency
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY user_id, channel
ORDER BY user_id, requests DESC;


-- ============================================================================
-- TREND ANALYSIS
-- ============================================================================

-- Cost trend week-over-week
SELECT
    strftime('%Y-W%W', timestamp) as week,
    COUNT(*) as requests,
    SUM(cost) as weekly_cost,
    AVG(cost) as avg_cost,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful
FROM request_logs
WHERE timestamp >= datetime('now', '-90 days')
GROUP BY strftime('%Y-W%W', timestamp)
ORDER BY week DESC;


-- Confidence trending
SELECT
    DATE(timestamp) as date,
    agent_selected,
    AVG(routing_confidence) as avg_confidence,
    MIN(routing_confidence) as min_confidence,
    MAX(routing_confidence) as max_confidence,
    COUNT(*) as requests
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY DATE(timestamp), agent_selected
ORDER BY date DESC, agent_selected;


-- ============================================================================
-- AUDIT TRAIL
-- ============================================================================

-- View all requests for a specific user
SELECT
    timestamp,
    channel,
    agent_selected,
    model,
    message,
    response_text,
    cost,
    status,
    latency_ms
FROM request_logs
WHERE user_id = ? AND timestamp >= datetime('now', '-30 days')
ORDER BY timestamp DESC;


-- View all requests with a specific trace ID
SELECT * FROM request_logs WHERE trace_id = ?;


-- Get all errors for a specific trace
SELECT * FROM error_logs WHERE trace_id = ?;


-- ============================================================================
-- COMPLIANCE & MONITORING
-- ============================================================================

-- Daily spend report
SELECT
    DATE(timestamp) as date,
    COUNT(*) as total_requests,
    SUM(cost) as daily_cost,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
    COUNT(CASE WHEN status = 'error' THEN 1 END) as failed,
    ROUND(100.0 * COUNT(CASE WHEN status = 'success' THEN 1 END) / COUNT(*), 2) as success_rate
FROM request_logs
GROUP BY DATE(timestamp)
ORDER BY date DESC;


-- Quota compliance check (rough estimate)
SELECT
    DATE(timestamp) as date,
    COUNT(*) as requests,
    SUM(cost) as cost,
    'OK' as status
FROM request_logs
WHERE timestamp >= datetime('now', '-1 days')
GROUP BY DATE(timestamp)
HAVING SUM(cost) < 100;


-- Response quality metrics
SELECT
    agent_selected,
    COUNT(*) as requests,
    AVG(message_length) as avg_input_length,
    AVG(LENGTH(response_text)) as avg_output_length,
    AVG(output_tokens) as avg_output_tokens,
    AVG(CAST(output_tokens AS FLOAT) / NULLIF(message_length, 0)) as token_per_char_ratio
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days') AND status = 'success'
GROUP BY agent_selected;
