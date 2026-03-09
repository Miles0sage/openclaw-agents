"""
Cost Gates Module for OpenClaw Gateway
Enforces budget limits at 3 tiers: per-task, daily, monthly
Stores budget state in D1 database or local JSON
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlite3

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")

# Pricing constants (updated Feb 2026)
PRICING = {
    # Kimi Models (Deepseek)
    "kimi-2.5": {
        "input": 0.27,      # $0.27 per million input tokens
        "output": 1.10,     # $1.10 per million output tokens
    },
    "kimi-reasoner": {
        "input": 0.55,      # $0.55 per million input tokens
        "output": 2.19,     # $2.19 per million output tokens
    },
    # Claude Models
    "claude-haiku-4-5-20251001": {
        "input": 0.8,       # $0.80 per million input tokens
        "output": 4.0,      # $4.00 per million output tokens
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0,       # $3.00 per million input tokens
        "output": 15.0,     # $15.00 per million output tokens
    },
    "claude-opus-4-6": {
        "input": 15.0,      # $15.00 per million input tokens
        "output": 60.0,     # $60.00 per million output tokens
    },
    # Gemini Models (Google)
    "gemini-2.5-flash-lite": {
        "input": 0.10,      # $0.10 per million input tokens
        "output": 0.40,     # $0.40 per million output tokens
    },
    "gemini-2.5-flash": {
        "input": 0.30,      # $0.30 per million input tokens
        "output": 2.50,     # $2.50 per million output tokens
    },
    "gemini-3-flash-preview": {
        "input": 0.0,       # FREE during preview
        "output": 0.0,      # FREE during preview
    },
    # Old aliases for backward compat
    "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
}

class BudgetStatus(Enum):
    """Budget enforcement status"""
    APPROVED = "approved"
    WARNING = "warning"
    REJECTED = "rejected"


@dataclass
class BudgetGate:
    """Single budget gate configuration"""
    name: str              # "per-task", "daily", "monthly"
    limit: float           # Maximum allowed spend in USD
    threshold_warning: float  # Warning threshold (e.g., 80% of limit)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CostCheckResult:
    """Result of a cost check"""
    status: BudgetStatus
    remaining_budget: float
    projected_total: float  # What spending would be after this task
    message: str
    gate_name: str


class CostGatesDB:
    """D1 database backend for cost tracking (SQLite compatible)"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(DATA_DIR, "costs", "budget.db")
        self._init_db()
    
    def _init_db(self):
        """Initialize D1 database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_spending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE UNIQUE,
                    project TEXT,
                    agent TEXT,
                    total_cost REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_spending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year_month TEXT UNIQUE,
                    project TEXT,
                    agent TEXT,
                    total_cost REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_spending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE,
                    project TEXT,
                    agent TEXT,
                    model TEXT,
                    tokens_input INTEGER,
                    tokens_output INTEGER,
                    cost REAL,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS budget_approval (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    project TEXT,
                    agent TEXT,
                    estimated_cost REAL,
                    approval_status TEXT,
                    approval_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_by TEXT,
                    approved_at TIMESTAMP
                )
            """)
            
            conn.commit()
    
    def get_daily_spending(self, date: str = None, project: str = None) -> float:
        """Get spending for a specific day"""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(total_cost), 0) FROM daily_spending WHERE date = ? AND (project = ? OR ? IS NULL)",
                (date, project, project)
            )
            return cursor.fetchone()[0]
    
    def get_monthly_spending(self, year_month: str = None, project: str = None) -> float:
        """Get spending for a specific month"""
        if year_month is None:
            year_month = datetime.now(timezone.utc).strftime("%Y-%m")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(total_cost), 0) FROM monthly_spending WHERE year_month = ? AND (project = ? OR ? IS NULL)",
                (year_month, project, project)
            )
            return cursor.fetchone()[0]
    
    def record_daily_spending(self, project: str, agent: str, cost: float, date: str = None):
        """Record daily spending"""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO daily_spending (date, project, agent, total_cost)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET total_cost = total_cost + ?
            """, (date, project, agent, cost, cost))
            conn.commit()
    
    def record_monthly_spending(self, project: str, agent: str, cost: float, year_month: str = None):
        """Record monthly spending"""
        if year_month is None:
            year_month = datetime.now(timezone.utc).strftime("%Y-%m")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO monthly_spending (year_month, project, agent, total_cost)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(year_month) DO UPDATE SET total_cost = total_cost + ?
            """, (year_month, project, agent, cost, cost))
            conn.commit()
    
    def record_task_spending(self, task_id: str, project: str, agent: str, model: str,
                            tokens_input: int, tokens_output: int, cost: float, status: str = "approved"):
        """Record task spending"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO task_spending (task_id, project, agent, model, tokens_input, tokens_output, cost, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, project, agent, model, tokens_input, tokens_output, cost, status))
            conn.commit()
    
    def get_task_spending(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get spending record for a task"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM task_spending WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0], 'task_id': row[1], 'project': row[2], 'agent': row[3],
                    'model': row[4], 'tokens_input': row[5], 'tokens_output': row[6],
                    'cost': row[7], 'status': row[8], 'created_at': row[9]
                }
            return None
    
    def request_approval(self, task_id: str, project: str, agent: str, estimated_cost: float) -> bool:
        """Request approval for high-cost task"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO budget_approval (task_id, project, agent, estimated_cost, approval_status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (task_id, project, agent, estimated_cost))
            conn.commit()
        return True
    
    def approve_task(self, task_id: str, approved_by: str = "system", reason: str = ""):
        """Approve a pending task"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE budget_approval
                SET approval_status = 'approved', approved_by = ?, approved_at = CURRENT_TIMESTAMP, approval_reason = ?
                WHERE task_id = ?
            """, (approved_by, reason, task_id))
            conn.commit()
    
    def is_approved(self, task_id: str) -> bool:
        """Check if task is approved"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT approval_status FROM budget_approval WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            return row and row[0] == "approved" if row else False


class CostGates:
    """Main cost gates enforcement system"""
    
    # Default budget gates (3-tier)
    DEFAULT_GATES = {
        "per_task": BudgetGate(
            name="per-task",
            limit=10.0,
            threshold_warning=8.0
        ),
        "daily": BudgetGate(
            name="daily",
            limit=50.0,
            threshold_warning=40.0
        ),
        "monthly": BudgetGate(
            name="monthly",
            limit=1000.0,
            threshold_warning=800.0
        ),
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, db_path: str = None):
        """Initialize cost gates with optional custom config"""
        self.db = CostGatesDB(db_path or os.path.join(DATA_DIR, "costs", "budget.db"))
        self.config = config or {}
        self.gates = self._load_gates()
    
    def _load_gates(self) -> Dict[str, BudgetGate]:
        """Load budget gates from config or use defaults"""
        gates = {}
        for key, default_gate in self.DEFAULT_GATES.items():
            if key in self.config:
                gate_config = self.config[key]
                gates[key] = BudgetGate(
                    name=gate_config.get("name", default_gate.name),
                    limit=gate_config.get("limit", default_gate.limit),
                    threshold_warning=gate_config.get("threshold_warning", default_gate.threshold_warning),
                )
            else:
                gates[key] = default_gate
        return gates
    
    def calculate_cost(self, model: str, tokens_input: int, tokens_output: int) -> float:
        """Calculate cost for token usage"""
        pricing = self._get_pricing(model)
        if not pricing:
            pricing = PRICING.get("claude-3-5-sonnet-20241022", {"input": 3.0, "output": 15.0})
        
        cost = (tokens_input * pricing["input"] + tokens_output * pricing["output"]) / 1_000_000
        return round(cost, 6)
    
    def _get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        """Get pricing for a model"""
        # Exact match
        if model in PRICING:
            return PRICING[model]
        
        # Fuzzy match
        model_normalized = model.replace("-", "").lower()
        for key, pricing in PRICING.items():
            if key.replace("-", "").lower() in model_normalized:
                return pricing
        
        return None
    
    def check_budget(self, project: str, agent: str, model: str, tokens_input: int, 
                     tokens_output: int, task_id: str = None) -> CostCheckResult:
        """
        Check if a task is within budget
        Returns: CostCheckResult with status and details
        """
        cost = self.calculate_cost(model, tokens_input, tokens_output)
        
        if task_id is None:
            task_id = f"{project}:{agent}:{datetime.now(timezone.utc).timestamp()}"
        
        # Check per-task gate
        per_task_gate = self.gates["per_task"]
        if cost > per_task_gate.limit:
            return CostCheckResult(
                status=BudgetStatus.REJECTED,
                remaining_budget=0,
                projected_total=cost,
                message=f"Task cost ${cost:.4f} exceeds per-task limit ${per_task_gate.limit}",
                gate_name="per-task"
            )
        
        # Check daily spending
        daily_spending = self.db.get_daily_spending(project=project)
        daily_gate = self.gates["daily"]
        projected_daily = daily_spending + cost
        
        if projected_daily > daily_gate.limit:
            return CostCheckResult(
                status=BudgetStatus.REJECTED,
                remaining_budget=max(0, daily_gate.limit - daily_spending),
                projected_total=projected_daily,
                message=f"Daily spending would reach ${projected_daily:.4f}, exceeds limit ${daily_gate.limit}",
                gate_name="daily"
            )
        
        # Check monthly spending
        monthly_spending = self.db.get_monthly_spending(project=project)
        monthly_gate = self.gates["monthly"]
        projected_monthly = monthly_spending + cost
        
        if projected_monthly > monthly_gate.limit:
            return CostCheckResult(
                status=BudgetStatus.REJECTED,
                remaining_budget=max(0, monthly_gate.limit - monthly_spending),
                projected_total=projected_monthly,
                message=f"Monthly spending would reach ${projected_monthly:.4f}, exceeds limit ${monthly_gate.limit}",
                gate_name="monthly"
            )
        
        # Check warning thresholds
        if cost > per_task_gate.threshold_warning or \
           projected_daily > daily_gate.threshold_warning or \
           projected_monthly > monthly_gate.threshold_warning:
            return CostCheckResult(
                status=BudgetStatus.WARNING,
                remaining_budget=min(
                    daily_gate.limit - projected_daily,
                    monthly_gate.limit - projected_monthly
                ),
                projected_total=cost,
                message=f"Task cost ${cost:.4f} approaching limits (daily: ${projected_daily:.4f}/${daily_gate.limit}, monthly: ${projected_monthly:.4f}/${monthly_gate.limit})",
                gate_name="warning"
            )
        
        # All checks passed
        return CostCheckResult(
            status=BudgetStatus.APPROVED,
            remaining_budget=min(
                daily_gate.limit - projected_daily,
                monthly_gate.limit - projected_monthly
            ),
            projected_total=cost,
            message=f"Task cost ${cost:.4f} approved",
            gate_name="all"
        )
    
    def record_spending(self, project: str, agent: str, cost: float, task_id: str = None):
        """Record spending after task execution"""
        self.db.record_daily_spending(project, agent, cost)
        self.db.record_monthly_spending(project, agent, cost)
    
    def get_budget_status(self, project: str = None) -> Dict[str, Any]:
        """Get current budget status"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        this_month = datetime.now(timezone.utc).strftime("%Y-%m")
        
        daily_spending = self.db.get_daily_spending(date=today, project=project)
        monthly_spending = self.db.get_monthly_spending(year_month=this_month, project=project)
        
        daily_gate = self.gates["daily"]
        monthly_gate = self.gates["monthly"]
        
        return {
            "date": today,
            "daily": {
                "spent": round(daily_spending, 4),
                "limit": daily_gate.limit,
                "remaining": round(daily_gate.limit - daily_spending, 4),
                "percent_used": round((daily_spending / daily_gate.limit) * 100, 1),
            },
            "month": {
                "spent": round(monthly_spending, 4),
                "limit": monthly_gate.limit,
                "remaining": round(monthly_gate.limit - monthly_spending, 4),
                "percent_used": round((monthly_spending / monthly_gate.limit) * 100, 1),
            },
        }


# Global instance
_cost_gates = None


def init_cost_gates(config: Optional[Dict[str, Any]] = None) -> CostGates:
    """Initialize global cost gates"""
    global _cost_gates
    _cost_gates = CostGates(config)
    return _cost_gates


def get_cost_gates() -> CostGates:
    """Get global cost gates instance"""
    global _cost_gates
    if _cost_gates is None:
        _cost_gates = CostGates()
    return _cost_gates


def check_cost_budget(project: str, agent: str, model: str, tokens_input: int,
                      tokens_output: int, task_id: str = None) -> CostCheckResult:
    """Convenience function to check budget"""
    gates = get_cost_gates()
    return gates.check_budget(project, agent, model, tokens_input, tokens_output, task_id)


def record_cost(project: str, agent: str, cost: float, task_id: str = None):
    """Convenience function to record spending"""
    gates = get_cost_gates()
    gates.record_spending(project, agent, cost, task_id)
