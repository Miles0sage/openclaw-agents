"""
Pipeline Orchestrator for CEO g5
=================================
Manages the lead discovery → qualification → outreach → proposal pipeline.

State persisted in data/ceo/pipeline_state.json.
Metrics appended to data/ceo/pipeline_metrics.jsonl.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from glob import glob

logger = logging.getLogger("pipeline_orchestrator")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
LEADS_DIR = os.path.join(DATA_DIR, "leads")
CEO_DIR = os.path.join(DATA_DIR, "ceo")
STATE_PATH = os.path.join(CEO_DIR, "pipeline_state.json")
METRICS_PATH = os.path.join(CEO_DIR, "pipeline_metrics.jsonl")

DEFAULT_STATE = {
    "search_intervals": {
        "restaurants": 3,
        "barbershops": 5,
        "dental": 5,
        "auto": 7,
    },
    "default_location": "Flagstaff AZ",
    "last_searches": {},
    "g5_targets": {"leads": 10, "demos": 3, "customers": 1},
}


class PipelineOrchestrator:
    def __init__(self):
        self.state = self._load_state()

    # -- State persistence --

    def _load_state(self) -> dict:
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        # Initialize with defaults
        os.makedirs(CEO_DIR, exist_ok=True)
        self._save_state(DEFAULT_STATE)
        return dict(DEFAULT_STATE)

    def _save_state(self, state: dict = None):
        if state is None:
            state = self.state
        os.makedirs(CEO_DIR, exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)

    # -- Lead loading --

    def _load_all_leads(self) -> list:
        """Load all lead JSON files from the leads directory."""
        leads = []
        pattern = os.path.join(LEADS_DIR, "*.json")
        for path in glob(pattern):
            try:
                with open(path) as f:
                    lead = json.load(f)
                    lead["_file"] = path
                    leads.append(lead)
            except (json.JSONDecodeError, OSError):
                continue
        return leads

    # -- Lead scoring & qualification --

    def _score_lead(self, lead: dict) -> int:
        """Score a lead 0-100 based on available data quality."""
        score = 0
        if lead.get("phone"):
            score += 30
        if lead.get("website_url"):
            score += 25
        rating = lead.get("rating")
        if rating is not None:
            try:
                if float(rating) >= 3.5:
                    score += 25
            except (ValueError, TypeError):
                pass
        if lead.get("reviews"):
            score += 15
        address = lead.get("address", "")
        if "flagstaff" in address.lower() or "flag" in lead.get("source", "").lower():
            score += 5
        return score

    def qualify_leads(self) -> list:
        """Return leads with score >= 30 and not already called/declined."""
        leads = self._load_all_leads()
        qualified = []
        skip_statuses = {"called", "declined", "customer", "interested"}
        for lead in leads:
            score = self._score_lead(lead)
            if score >= 30 and lead.get("status", "new") not in skip_statuses:
                lead["_score"] = score
                qualified.append(lead)
        # Sort by score descending
        qualified.sort(key=lambda l: l["_score"], reverse=True)
        return qualified

    def get_interested_leads(self) -> list:
        """Return leads with status 'interested'."""
        leads = self._load_all_leads()
        return [l for l in leads if l.get("status") == "interested"]

    # -- Discovery scheduling --

    def _days_since_search(self, business_type: str) -> float:
        """Days since last search for this business type."""
        last = self.state.get("last_searches", {}).get(business_type)
        if not last:
            return 999  # Never searched
        try:
            ts = datetime.fromisoformat(last).timestamp()
            return (time.time() - ts) / 86400
        except (ValueError, TypeError):
            return 999

    def should_run_discovery(self) -> bool:
        """True if any business type is past its search interval."""
        intervals = self.state.get("search_intervals", {})
        for btype, interval_days in intervals.items():
            if self._days_since_search(btype) >= interval_days:
                return True
        return False

    def _get_due_business_type(self) -> tuple:
        """Return (business_type, location) for the most overdue search."""
        intervals = self.state.get("search_intervals", {})
        location = self.state.get("default_location", "Flagstaff AZ")
        most_overdue = None
        max_overdue = -1
        for btype, interval_days in intervals.items():
            days = self._days_since_search(btype)
            overdue = days - interval_days
            if overdue > max_overdue:
                max_overdue = overdue
                most_overdue = btype
        return most_overdue, location

    # -- Job builders --

    def build_discovery_job(self) -> str:
        """Build a specific discovery job task string."""
        btype, location = self._get_due_business_type()
        # Mark search as done now
        if "last_searches" not in self.state:
            self.state["last_searches"] = {}
        self.state["last_searches"][btype] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        return (
            f"Lead Discovery: Search for [{btype}] in [{location}] using the find_leads tool. "
            f"Parameters: business_type='{btype}', location='{location}', limit=10. "
            f"Save results. Expected: 5-10 new leads."
        )

    def build_outreach_job(self, leads: list) -> str:
        """Build an outreach job with specific lead names and phones."""
        lead_lines = []
        for lead in leads[:5]:  # Cap at 5 per batch
            name = lead.get("business_name", "Unknown")
            phone = lead.get("phone", "no phone")
            btype = lead.get("business_type", "business")
            lead_lines.append(f"  - {name} ({phone}, {btype})")

        leads_str = "\n".join(lead_lines)
        return (
            f"Lead Outreach: Call the following {len(lead_lines)} qualified leads using the "
            f"sales_call tool. For each call, pass business_name and phone. Log results.\n"
            f"Leads to call:\n{leads_str}\n"
            f"After each call, update the lead status: 'interested' if positive, 'declined' if not."
        )

    def build_proposal_job(self, leads: list) -> str:
        """Build a proposal generation job for interested leads."""
        lead_lines = []
        for lead in leads[:3]:  # Cap at 3 proposals per batch
            name = lead.get("business_name", "Unknown")
            btype = lead.get("business_type", "other")
            owner = lead.get("owner_name", "Business Owner")
            lead_lines.append(f"  - {name} (type: {btype}, owner: {owner})")

        leads_str = "\n".join(lead_lines)
        return (
            f"Proposal Generation: Create proposals for the following interested leads using "
            f"generate_proposal tool.\n"
            f"Leads:\n{leads_str}\n"
            f"For each, generate a proposal with selected_services=['receptionist', 'website']. "
            f"Customize based on business type."
        )

    # -- Metrics & progress --

    def record_run(self, results: dict):
        """Append run metrics to pipeline_metrics.jsonl."""
        os.makedirs(CEO_DIR, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_leads": len(self._load_all_leads()),
            "qualified": len(self.qualify_leads()),
            "interested": len(self.get_interested_leads()),
            **results,
        }
        with open(METRICS_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")

    def get_g5_progress(self) -> int:
        """Calculate g5 progress % based on pipeline counts vs targets."""
        targets = self.state.get("g5_targets", {"leads": 10, "demos": 3, "customers": 1})
        all_leads = self._load_all_leads()
        total_leads = len(all_leads)
        interested = len([l for l in all_leads if l.get("status") == "interested"])
        customers = len([l for l in all_leads if l.get("status") == "customer"])

        # Weighted progress: leads 40%, demos 30%, customers 30%
        lead_pct = min(total_leads / max(targets["leads"], 1), 1.0) * 40
        demo_pct = min(interested / max(targets["demos"], 1), 1.0) * 30
        cust_pct = min(customers / max(targets["customers"], 1), 1.0) * 30

        return int(lead_pct + demo_pct + cust_pct)
