"""
Supabase Agent - Handles database queries and operations for OpenClaw
Supports both Barber CRM and Delhi Palace databases
"""

import os
import json
from typing import Dict, List, Any, Optional, Tuple
import logging
from datetime import datetime
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supabase_agent")


@dataclass
class QueryResult:
    """Result from a Supabase query"""
    success: bool
    data: Any
    error: Optional[str] = None
    table: Optional[str] = None
    row_count: int = 0
    execution_time_ms: float = 0.0


class SupabaseAgent:
    """Agent for handling Supabase database operations"""

    # Database configurations
    DATABASES = {
        "barber_crm": {
            "name": "Barber CRM",
            "url": "https://djdilkhedpnlercxggby.supabase.co",
            "anonKey": os.getenv("BARBER_CRM_SUPABASE_ANON_KEY", ""),
            "serviceRoleKey": os.getenv("BARBER_CRM_SUPABASE_SERVICE_ROLE_KEY", "")
        },
        "delhi_palace": {
            "name": "Delhi Palace",
            "url": "https://banxtacevgopeczuzycz.supabase.co",
            "anonKey": os.getenv("DELHI_PALACE_SUPABASE_ANON_KEY", ""),
            "serviceRoleKey": os.getenv("DELHI_PALACE_SUPABASE_SERVICE_ROLE_KEY", "")
        }
    }

    # Supported tables and schemas
    TABLES = {
        "barber_crm": {
            "appointments": {
                "description": "Barber appointments",
                "columns": ["id", "client_id", "staff_id", "service_id", "start_time", "end_time", "status", "notes", "created_at", "updated_at"],
                "query_templates": {
                    "upcoming": "SELECT * FROM appointments WHERE status = 'confirmed' AND start_time > now() ORDER BY start_time ASC LIMIT 10",
                    "by_client": "SELECT * FROM appointments WHERE client_id = '{client_id}' ORDER BY start_time DESC LIMIT 10",
                    "by_date": "SELECT * FROM appointments WHERE DATE(start_time) = '{date}' ORDER BY start_time ASC",
                    "availability": "SELECT * FROM appointments WHERE status = 'available' AND start_time > now() ORDER BY start_time ASC"
                }
            },
            "clients": {
                "description": "Barber shop clients",
                "columns": ["id", "name", "email", "phone", "notes", "first_visit", "total_visits", "total_spent", "created_at", "updated_at"],
                "query_templates": {
                    "all": "SELECT id, name, email, phone, total_visits, total_spent FROM clients ORDER BY total_visits DESC LIMIT 50",
                    "by_name": "SELECT * FROM clients WHERE name ILIKE '%{name}%' LIMIT 10",
                    "recent": "SELECT * FROM clients ORDER BY created_at DESC LIMIT 10",
                    "top_customers": "SELECT * FROM clients ORDER BY total_spent DESC LIMIT 10"
                }
            },
            "services": {
                "description": "Barbershop services",
                "columns": ["id", "name", "duration_minutes", "price", "description", "active", "created_at", "updated_at"],
                "query_templates": {
                    "all": "SELECT * FROM services WHERE active = true ORDER BY name ASC",
                    "by_price": "SELECT * FROM services WHERE active = true ORDER BY price DESC"
                }
            },
            "staff": {
                "description": "Barber staff members",
                "columns": ["id", "name", "email", "phone", "specialty", "available_hours", "active", "created_at", "updated_at"],
                "query_templates": {
                    "all": "SELECT id, name, email, specialty, active FROM staff WHERE active = true ORDER BY name ASC"
                }
            },
            "call_logs": {
                "description": "Vapi phone call history",
                "columns": ["id", "call_id", "phone_number", "duration_seconds", "transcript", "status", "created_at", "updated_at"],
                "query_templates": {
                    "recent": "SELECT * FROM call_logs ORDER BY created_at DESC LIMIT 20",
                    "today": "SELECT * FROM call_logs WHERE DATE(created_at) = TODAY() ORDER BY created_at DESC",
                    "by_phone": "SELECT * FROM call_logs WHERE phone_number = '{phone}' ORDER BY created_at DESC LIMIT 10"
                }
            },
            "transactions": {
                "description": "Stripe payment transactions",
                "columns": ["id", "appointment_id", "client_id", "amount", "currency", "status", "stripe_id", "created_at", "updated_at"],
                "query_templates": {
                    "recent": "SELECT * FROM transactions ORDER BY created_at DESC LIMIT 20",
                    "by_client": "SELECT * FROM transactions WHERE client_id = '{client_id}' ORDER BY created_at DESC LIMIT 10",
                    "summary": "SELECT COUNT(*) as total_transactions, SUM(amount) as total_revenue, AVG(amount) as avg_transaction FROM transactions WHERE status = 'completed'"
                }
            }
        },
        "delhi_palace": {
            "orders": {
                "description": "Restaurant orders",
                "columns": ["id", "customer_name", "phone", "items", "total_price", "status", "table_number", "notes", "created_at", "updated_at"],
                "query_templates": {
                    "active": "SELECT * FROM orders WHERE status IN ('pending', 'preparing') ORDER BY created_at ASC",
                    "today": "SELECT * FROM orders WHERE DATE(created_at) = TODAY() ORDER BY created_at DESC",
                    "by_status": "SELECT COUNT(*) as count, status FROM orders WHERE DATE(created_at) = TODAY() GROUP BY status"
                }
            },
            "menu_items": {
                "description": "Menu items and pricing",
                "columns": ["id", "name", "description", "price", "category", "vegetarian", "spicy_level", "active", "created_at", "updated_at"],
                "query_templates": {
                    "all": "SELECT id, name, price, category, vegetarian FROM menu_items WHERE active = true ORDER BY category, name ASC",
                    "by_category": "SELECT * FROM menu_items WHERE category = '{category}' AND active = true ORDER BY name ASC"
                }
            },
            "customers": {
                "description": "Customer information",
                "columns": ["id", "name", "email", "phone", "loyalty_points", "total_spent", "created_at", "updated_at"],
                "query_templates": {
                    "all": "SELECT * FROM customers ORDER BY total_spent DESC LIMIT 50",
                    "top_customers": "SELECT * FROM customers ORDER BY loyalty_points DESC LIMIT 20"
                }
            }
        }
    }

    # Security settings
    SAFE_OPERATIONS = ["SELECT", "read", "get", "fetch", "list", "query"]
    DANGEROUS_OPERATIONS = ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"]

    def __init__(self):
        """Initialize Supabase Agent"""
        logger.info("Initializing SupabaseAgent with {} databases".format(len(self.DATABASES)))
        self.validate_credentials()

    def validate_credentials(self) -> Dict[str, bool]:
        """Validate that Supabase credentials are configured"""
        status = {}
        for db_id, db_config in self.DATABASES.items():
            has_url = bool(db_config.get("url"))
            has_key = bool(db_config.get("anonKey"))
            status[db_id] = has_url and has_key
            if status[db_id]:
                logger.info(f"✅ {db_config['name']}: Credentials available")
            else:
                logger.warning(f"❌ {db_config['name']}: Missing credentials")
        return status

    def list_databases(self) -> List[Dict[str, Any]]:
        """List available databases"""
        return [
            {
                "id": db_id,
                "name": config["name"],
                "url": config["url"],
                "hasCredentials": bool(config.get("anonKey"))
            }
            for db_id, config in self.DATABASES.items()
        ]

    def list_tables(self, database_id: str) -> List[Dict[str, Any]]:
        """List tables available in a database"""
        if database_id not in self.TABLES:
            return {"error": f"Unknown database: {database_id}"}

        return [
            {
                "name": table_name,
                "description": table_config["description"],
                "columnCount": len(table_config["columns"]),
                "columns": table_config["columns"]
            }
            for table_name, table_config in self.TABLES[database_id].items()
        ]

    def get_table_schema(self, database_id: str, table_name: str) -> Dict[str, Any]:
        """Get detailed schema for a table"""
        if database_id not in self.TABLES:
            return {"error": f"Unknown database: {database_id}"}

        if table_name not in self.TABLES[database_id]:
            return {"error": f"Unknown table: {table_name}"}

        table_config = self.TABLES[database_id][table_name]
        return {
            "database": database_id,
            "table": table_name,
            "description": table_config["description"],
            "columns": table_config["columns"],
            "queryTemplates": table_config.get("query_templates", {})
        }

    def execute_safe_query(self, database_id: str, query: str) -> QueryResult:
        """
        Execute a safe query against a Supabase database.
        Only SELECT queries are allowed.
        """
        start_time = datetime.now()

        # Validate query safety
        safe_query = query.strip().upper()

        # Check for dangerous operations
        for dangerous_op in self.DANGEROUS_OPERATIONS:
            if dangerous_op in safe_query:
                return QueryResult(
                    success=False,
                    data=None,
                    error=f"Operation '{dangerous_op}' is not allowed. Only SELECT queries are permitted.",
                    table=None
                )

        # Ensure query starts with SELECT
        if not safe_query.startswith("SELECT"):
            return QueryResult(
                success=False,
                data=None,
                error="Only SELECT queries are allowed.",
                table=None
            )

        # Get database config
        if database_id not in self.DATABASES:
            return QueryResult(
                success=False,
                data=None,
                error=f"Unknown database: {database_id}"
            )

        db_config = self.DATABASES[database_id]

        if not db_config.get("anonKey"):
            return QueryResult(
                success=False,
                data=None,
                error=f"Database '{database_id}' credentials not configured"
            )

        # Log query execution
        logger.info(f"📊 Executing query on {database_id}: {query[:100]}...")

        # TODO: Implement actual Supabase query execution using supabase-py or REST API
        # For now, return a simulation response

        execution_time = (datetime.now() - start_time).total_seconds() * 1000

        return QueryResult(
            success=True,
            data={
                "message": "Query execution simulated (install supabase-py for real queries)",
                "query": query,
                "database": database_id,
                "timestamp": datetime.now().isoformat()
            },
            table=None,
            row_count=0,
            execution_time_ms=execution_time
        )

    def get_query_template(self, database_id: str, table_name: str, template_name: str) -> Optional[str]:
        """Get a pre-defined safe query template"""
        if database_id not in self.TABLES:
            return None

        if table_name not in self.TABLES[database_id]:
            return None

        templates = self.TABLES[database_id][table_name].get("query_templates", {})
        return templates.get(template_name)

    def describe_database(self, database_id: str) -> Dict[str, Any]:
        """Get a complete description of a database"""
        if database_id not in self.DATABASES:
            return {"error": f"Unknown database: {database_id}"}

        db_config = self.DATABASES[database_id]
        tables = self.TABLES.get(database_id, {})

        return {
            "id": database_id,
            "name": db_config["name"],
            "url": db_config["url"],
            "tableCount": len(tables),
            "tables": self.list_tables(database_id),
            "description": f"Database for {db_config['name']}"
        }

    def get_agent_instructions(self) -> str:
        """Get instructions for the SupabaseConnector agent"""
        return """
SUPABASE CONNECTOR AGENT INSTRUCTIONS
=====================================

You are a database specialist. Your role is to:
1. Query Supabase databases safely (appointments, clients, orders, etc.)
2. Analyze and report on data
3. Help coordinate data operations with other agents
4. Audit database security (RLS policies)

ALLOWED OPERATIONS:
✅ SELECT queries to read data
✅ Query templates from predefined safe queries
✅ Analyze data patterns and generate insights
✅ Audit row-level security (RLS) policies
✅ Schema exploration and documentation

FORBIDDEN OPERATIONS:
❌ INSERT, UPDATE, DELETE without PM approval
❌ DROP, TRUNCATE, ALTER tables
❌ Queries with unsafe patterns

AVAILABLE DATABASES:
1. barber_crm - Barber shop management
   Tables: appointments, clients, services, staff, call_logs, transactions

2. delhi_palace - Restaurant management
   Tables: orders, menu_items, customers

QUERY EXAMPLES:
• "Fetch upcoming appointments" → Use appointments table
• "Who are our top customers?" → Use clients or customers table
• "Show today's orders" → Use orders table
• "Audit RLS policies on appointments table" → Security audit

When responding:
- Always specify which database and table you're querying
- Show the query you're executing
- Format results clearly with row counts and summary statistics
- Explain any security implications
- Suggest improvements if data access seems problematic
"""


# Initialize agent when module loads
supabase_agent = SupabaseAgent()


def get_agent() -> SupabaseAgent:
    """Get the global SupabaseAgent instance"""
    return supabase_agent


if __name__ == "__main__":
    # Test the agent
    agent = SupabaseAgent()

    print("📊 Supabase Agent Initialized")
    print("\nDatabases:", agent.list_databases())
    print("\nBarber CRM Tables:", agent.list_tables("barber_crm"))
    print("\nAgent Instructions:\n", agent.get_agent_instructions())
