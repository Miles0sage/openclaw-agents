"""
OpenClaw Request Logger & Audit Trail

Logs every request to D1 database with:
- Request details (message, model, agent, channel)
- Response metrics (tokens, cost, latency)
- Status tracking (success/error, HTTP code)
- Debugging info (trace ID, confidence, error messages)
"""

import os
import json
import uuid
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger("openclaw_logger")

# D1 Database path (SQLite-compatible)
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
DB_PATH = os.getenv("OPENCLAW_LOG_DB", os.path.join(DATA_DIR, "events", "audit.db"))


@dataclass
class RequestLog:
    """Request log entry"""
    trace_id: str
    timestamp: str
    channel: str
    user_id: str
    session_key: str
    message: str
    message_length: int
    agent_selected: str
    routing_confidence: float
    model: str
    
    # Response fields
    response_text: str
    output_tokens: int
    input_tokens: int
    cost: float
    cost_breakdown_input: float
    cost_breakdown_output: float
    
    # Status fields
    status: str  # "success", "error", "timeout"
    http_code: int
    error_message: Optional[str] = None
    
    # Latency (milliseconds)
    latency_ms: int = 0
    
    # Metadata
    metadata: Optional[str] = None  # JSON string


class RequestLogger:
    """Thread-safe request logger for D1 database"""
    
    def __init__(self, db_path: str = DB_PATH):
        """Initialize logger with D1 database"""
        self.db_path = db_path
        self.lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        """Initialize D1 database schema"""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create requests table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_key TEXT,
                    message TEXT NOT NULL,
                    message_length INTEGER,
                    agent_selected TEXT NOT NULL,
                    routing_confidence REAL,
                    model TEXT NOT NULL,
                    
                    response_text TEXT,
                    output_tokens INTEGER DEFAULT 0,
                    input_tokens INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    cost_breakdown_input REAL DEFAULT 0.0,
                    cost_breakdown_output REAL DEFAULT 0.0,
                    
                    status TEXT NOT NULL,
                    http_code INTEGER,
                    error_message TEXT,
                    latency_ms INTEGER DEFAULT 0,
                    metadata TEXT,
                    
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for fast queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trace_id ON request_logs(trace_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON request_logs(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_selected ON request_logs(agent_selected)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_channel ON request_logs(channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_id ON request_logs(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON request_logs(status)
            """)
            
            # Create error logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    stack_trace TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (trace_id) REFERENCES request_logs(trace_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_timestamp ON error_logs(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_type ON error_logs(error_type)
            """)
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Initialized D1 database at {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize D1 database: {e}")
            raise
    
    def log_request(self, log_entry: RequestLog) -> str:
        """
        Log a request to D1 database
        Returns: trace_id
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Convert to dict for easy insertion
                data = asdict(log_entry)
                
                # Build INSERT query
                columns = ", ".join(data.keys())
                placeholders = ", ".join(["?" for _ in data.keys()])
                query = f"INSERT INTO request_logs ({columns}) VALUES ({placeholders})"
                
                cursor.execute(query, tuple(data.values()))
                conn.commit()
                conn.close()
                
                logger.debug(f"📝 Logged request {log_entry.trace_id}")
                return log_entry.trace_id
            except Exception as e:
                logger.error(f"❌ Failed to log request: {e}")
                raise
    
    def log_error(self, trace_id: str, error_type: str, error_msg: str, stack_trace: str = ""):
        """Log an error to error_logs table"""
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                timestamp = datetime.now(timezone.utc).isoformat() + "Z"
                
                cursor.execute("""
                    INSERT INTO error_logs (trace_id, error_type, error_message, stack_trace, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (trace_id, error_type, error_msg, stack_trace, timestamp))
                
                conn.commit()
                conn.close()
                
                logger.debug(f"📝 Logged error for trace {trace_id}: {error_type}")
            except Exception as e:
                logger.error(f"❌ Failed to log error: {e}")
    
    def get_logs(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get recent request logs"""
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM request_logs
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                
                rows = cursor.fetchall()
                conn.close()
                
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"❌ Failed to get logs: {e}")
                return []
    
    def get_daily_summary(self, date: str) -> Dict[str, Any]:
        """
        Get daily summary for a specific date (YYYY-MM-DD)
        Returns: total requests, cost, errors, agents used, etc.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Parse date range
                start = f"{date}T00:00:00Z"
                end = f"{date}T23:59:59Z"
                
                # Get daily stats
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_requests,
                        SUM(cost) as total_cost,
                        SUM(input_tokens) as total_input_tokens,
                        SUM(output_tokens) as total_output_tokens,
                        AVG(latency_ms) as avg_latency_ms,
                        COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
                        COUNT(CASE WHEN status = 'error' THEN 1 END) as errors,
                        COUNT(CASE WHEN status = 'timeout' THEN 1 END) as timeouts
                    FROM request_logs
                    WHERE timestamp >= ? AND timestamp <= ?
                """, (start, end))
                
                stats = dict(cursor.fetchone())
                
                # Get agent breakdown
                cursor.execute("""
                    SELECT agent_selected, COUNT(*) as count, SUM(cost) as cost
                    FROM request_logs
                    WHERE timestamp >= ? AND timestamp <= ?
                    GROUP BY agent_selected
                """, (start, end))
                
                stats["agents"] = {row[0]: {"count": row[1], "cost": row[2]} 
                                   for row in cursor.fetchall()}
                
                # Get channel breakdown
                cursor.execute("""
                    SELECT channel, COUNT(*) as count, SUM(cost) as cost
                    FROM request_logs
                    WHERE timestamp >= ? AND timestamp <= ?
                    GROUP BY channel
                """, (start, end))
                
                stats["channels"] = {row[0]: {"count": row[1], "cost": row[2]} 
                                     for row in cursor.fetchall()}
                
                # Get model breakdown
                cursor.execute("""
                    SELECT model, COUNT(*) as count, SUM(cost) as cost
                    FROM request_logs
                    WHERE timestamp >= ? AND timestamp <= ?
                    GROUP BY model
                """, (start, end))
                
                stats["models"] = {row[0]: {"count": row[1], "cost": row[2]} 
                                   for row in cursor.fetchall()}
                
                conn.close()
                return stats
            except Exception as e:
                logger.error(f"❌ Failed to get daily summary: {e}")
                return {}
    
    def get_cost_breakdown(self, days: int = 30) -> Dict[str, Any]:
        """
        Get cost breakdown for last N days
        Returns: daily totals, agent costs, model costs
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() + "Z"
                
                # Daily totals
                cursor.execute("""
                    SELECT
                        DATE(timestamp) as date,
                        SUM(cost) as cost,
                        COUNT(*) as requests,
                        AVG(routing_confidence) as avg_confidence
                    FROM request_logs
                    WHERE timestamp >= ? AND status = 'success'
                    GROUP BY DATE(timestamp)
                    ORDER BY date DESC
                """, (start_date,))
                
                daily = [dict(row) for row in cursor.fetchall()]
                
                # Agent costs
                cursor.execute("""
                    SELECT agent_selected, SUM(cost) as cost, COUNT(*) as requests
                    FROM request_logs
                    WHERE timestamp >= ? AND status = 'success'
                    GROUP BY agent_selected
                    ORDER BY cost DESC
                """, (start_date,))
                
                agents = {row[0]: {"cost": row[1], "requests": row[2]} 
                          for row in cursor.fetchall()}
                
                # Model costs
                cursor.execute("""
                    SELECT model, SUM(cost) as cost, COUNT(*) as requests
                    FROM request_logs
                    WHERE timestamp >= ? AND status = 'success'
                    GROUP BY model
                    ORDER BY cost DESC
                """, (start_date,))
                
                models = {row[0]: {"cost": row[1], "requests": row[2]} 
                          for row in cursor.fetchall()}
                
                conn.close()
                
                return {
                    "period_days": days,
                    "daily": daily,
                    "by_agent": agents,
                    "by_model": models
                }
            except Exception as e:
                logger.error(f"❌ Failed to get cost breakdown: {e}")
                return {}
    
    def get_error_analysis(self, days: int = 30) -> Dict[str, Any]:
        """
        Analyze errors for last N days
        Returns: error types, frequency, affected agents
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() + "Z"
                
                # Error breakdown
                cursor.execute("""
                    SELECT error_type, COUNT(*) as count, error_message
                    FROM error_logs
                    WHERE timestamp >= ?
                    GROUP BY error_type
                    ORDER BY count DESC
                """, (start_date,))
                
                errors_by_type = [{"type": row[0], "count": row[1], "sample": row[2]} 
                                  for row in cursor.fetchall()]
                
                # Errors by agent
                cursor.execute("""
                    SELECT rl.agent_selected, COUNT(*) as count
                    FROM error_logs el
                    JOIN request_logs rl ON el.trace_id = rl.trace_id
                    WHERE el.timestamp >= ?
                    GROUP BY rl.agent_selected
                    ORDER BY count DESC
                """, (start_date,))
                
                errors_by_agent = {row[0]: row[1] for row in cursor.fetchall()}
                
                # HTTP error codes
                cursor.execute("""
                    SELECT http_code, COUNT(*) as count
                    FROM request_logs
                    WHERE timestamp >= ? AND http_code >= 400
                    GROUP BY http_code
                    ORDER BY count DESC
                """, (start_date,))
                
                http_errors = {str(row[0]): row[1] for row in cursor.fetchall()}
                
                conn.close()
                
                return {
                    "period_days": days,
                    "errors_by_type": errors_by_type,
                    "errors_by_agent": errors_by_agent,
                    "http_errors": http_errors
                }
            except Exception as e:
                logger.error(f"❌ Failed to analyze errors: {e}")
                return {}
    
    def get_slowest_requests(self, limit: int = 10) -> List[Dict]:
        """Get slowest requests"""
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT
                        trace_id, timestamp, agent_selected, model,
                        latency_ms, cost, status
                    FROM request_logs
                    ORDER BY latency_ms DESC
                    LIMIT ?
                """, (limit,))
                
                rows = cursor.fetchall()
                conn.close()
                
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"❌ Failed to get slowest requests: {e}")
                return []
    
    def get_agent_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get agent usage statistics"""
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() + "Z"
                
                cursor.execute("""
                    SELECT
                        agent_selected,
                        COUNT(*) as requests,
                        SUM(cost) as total_cost,
                        AVG(cost) as avg_cost,
                        AVG(latency_ms) as avg_latency_ms,
                        COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
                        COUNT(CASE WHEN status = 'error' THEN 1 END) as errors,
                        AVG(routing_confidence) as avg_confidence
                    FROM request_logs
                    WHERE timestamp >= ?
                    GROUP BY agent_selected
                    ORDER BY requests DESC
                """, (start_date,))
                
                stats = [dict(row) for row in cursor.fetchall()]
                conn.close()
                
                return stats
            except Exception as e:
                logger.error(f"❌ Failed to get agent stats: {e}")
                return []


# Global logger instance
_logger_instance: Optional[RequestLogger] = None


def get_logger() -> RequestLogger:
    """Get global logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = RequestLogger()
    return _logger_instance


def create_trace_id() -> str:
    """Generate a unique trace ID"""
    return str(uuid.uuid4())


def log_request(
    channel: str,
    user_id: str,
    message: str,
    agent_selected: str,
    model: str,
    response_text: str,
    output_tokens: int,
    input_tokens: int,
    cost: float,
    status: str,
    http_code: int,
    routing_confidence: float = 1.0,
    session_key: Optional[str] = None,
    error_message: Optional[str] = None,
    latency_ms: int = 0,
    metadata: Optional[Dict] = None,
) -> str:
    """
    Convenience function to log a request
    Returns: trace_id
    """
    trace_id = create_trace_id()
    
    # Calculate cost breakdown
    total_pricing = {
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.0},
        "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
        "claude-3-opus-20250219": {"input": 15.0, "output": 75.0},
    }
    
    pricing = total_pricing.get(model, {"input": 3.0, "output": 15.0})
    cost_input = (input_tokens * pricing["input"]) / 1_000_000
    cost_output = (output_tokens * pricing["output"]) / 1_000_000
    
    log_entry = RequestLog(
        trace_id=trace_id,
        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
        channel=channel,
        user_id=user_id,
        session_key=session_key or user_id,
        message=message,
        message_length=len(message),
        agent_selected=agent_selected,
        routing_confidence=routing_confidence,
        model=model,
        response_text=response_text,
        output_tokens=output_tokens,
        input_tokens=input_tokens,
        cost=cost,
        cost_breakdown_input=cost_input,
        cost_breakdown_output=cost_output,
        status=status,
        http_code=http_code,
        error_message=error_message,
        latency_ms=latency_ms,
        metadata=json.dumps(metadata) if metadata else None,
    )
    
    logger = get_logger()
    return logger.log_request(log_entry)
