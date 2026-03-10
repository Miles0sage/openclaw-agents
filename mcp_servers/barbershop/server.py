"""
OpenClaw Barbershop MCP Server — 7 tools for barbershop/salon operations.

Wired to Barber CRM Supabase (djdilkhedpnlercxggby).
Tables: barbers, services, clients, appointments, availability,
        reviews, payments, locations, barber_services, notification_history.
View: appointments_with_details (denormalized for reads).

Tools:
  1. manage_appointments — Book/reschedule/cancel/check-in appointments
  2. manage_clients     — Client profiles, preferences, visit history
  3. manage_services    — Service catalog, pricing, duration
  4. check_availability — Find open time slots by date/barber/service
  5. manage_walkins     — Walk-in queue (in-memory, no DB table)
  6. send_reminders     — Appointment reminders & follow-ups via SMS
  7. shop_analytics     — Revenue, retention, staff performance, trends

Usage:
  python -m mcp_servers.barbershop.server          # stdio mode
  python -m mcp_servers.barbershop.server --http    # HTTP mode (port 8801)
"""

from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone, timedelta, date, time as dtime
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "OpenClaw Barbershop Tools",
    version="1.0.0",
    instructions=(
        "Barbershop & salon management MCP server by OpenClaw. "
        "Provides tools for appointment scheduling, client management, "
        "services, walk-in queues, SMS reminders, and analytics."
    ),
)

# ---------------------------------------------------------------------------
# Supabase client (lazy init — Barber CRM database)
# ---------------------------------------------------------------------------

_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is None:
        url = os.getenv("BARBERSHOP_SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
        key = os.getenv("BARBERSHOP_SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", "")))
        if not url or not key:
            return None
        try:
            from supabase import create_client
            _supabase = create_client(url, key)
        except ImportError:
            return None
    return _supabase


def _demo_response(tool: str, params: dict) -> dict:
    return {
        "status": "demo_mode",
        "tool": tool,
        "message": "Running in demo mode. Connect Supabase for live data.",
        "params_received": params,
        "demo_data": True,
    }


# ---------------------------------------------------------------------------
# Helpers: resolve names to UUIDs
# ---------------------------------------------------------------------------

def _resolve_barber(sb, barber_name: str) -> str | None:
    """Look up barber UUID by name."""
    result = sb.table("barbers").select("id").ilike("name", f"%{barber_name}%").eq("is_active", True).limit(1).execute()
    return result.data[0]["id"] if result.data else None


def _resolve_client(sb, client_name: str | None = None, client_phone: str | None = None) -> str | None:
    """Look up client UUID by name or phone."""
    if client_phone:
        result = sb.table("clients").select("id").eq("phone", client_phone).limit(1).execute()
        if result.data:
            return result.data[0]["id"]
    if client_name:
        result = sb.table("clients").select("id").ilike("name", f"%{client_name}%").limit(1).execute()
        if result.data:
            return result.data[0]["id"]
    return None


def _resolve_service(sb, service_name: str) -> dict | None:
    """Look up service by name, return {id, duration_minutes, price}."""
    result = sb.table("services").select("id,duration_minutes,price,name").ilike("name", f"%{service_name}%").eq("is_active", True).limit(1).execute()
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Helper: enrich appointments with barber/client/service names
# (appointments_with_details view not accessible via anon key)
# ---------------------------------------------------------------------------

_name_cache: dict[str, dict] = {"barbers": {}, "clients": {}, "services": {}}


def _enrich_appointments(sb, appointments: list[dict]) -> list[dict]:
    """Add barber_name, client_name, service_name to raw appointment rows."""
    # Collect unique IDs
    barber_ids = {a["barber_id"] for a in appointments if a.get("barber_id")}
    client_ids = {a["client_id"] for a in appointments if a.get("client_id")}
    service_ids = {a["service_id"] for a in appointments if a.get("service_id")}

    # Batch-fetch names (only uncached ones)
    for bid in barber_ids - set(_name_cache["barbers"]):
        r = sb.table("barbers").select("id,name").eq("id", bid).execute()
        if r.data:
            _name_cache["barbers"][bid] = r.data[0]["name"]
    for cid in client_ids - set(_name_cache["clients"]):
        r = sb.table("clients").select("id,name,phone").eq("id", cid).execute()
        if r.data:
            _name_cache["clients"][cid] = r.data[0]["name"]
    for sid in service_ids - set(_name_cache["services"]):
        r = sb.table("services").select("id,name,price").eq("id", sid).execute()
        if r.data:
            _name_cache["services"][sid] = r.data[0]

    enriched = []
    for a in appointments:
        a["barber_name"] = _name_cache["barbers"].get(a.get("barber_id"), "Unknown")
        a["client_name"] = _name_cache["clients"].get(a.get("client_id"), "Unknown")
        svc = _name_cache["services"].get(a.get("service_id"), {})
        a["service_name"] = svc.get("name", "Unknown")
        a["service_price"] = svc.get("price", 0)
        enriched.append(a)
    return enriched


# ---------------------------------------------------------------------------
# In-memory walk-in queue (no walkin_queue table in Barber CRM)
# ---------------------------------------------------------------------------

_walkin_queue: list[dict] = []
_walkin_counter = 0


# ---------------------------------------------------------------------------
# Tool 1: Appointment Management
# Uses appointments_with_details view for reads, appointments table for writes.
# appointments: id, barber_id, client_id, service_id, location_id,
#   start_time, end_time, status, payment_status, notes, created_at, updated_at
# Status enum: pending | confirmed | in_progress | completed | cancelled | no_show
# ---------------------------------------------------------------------------

@mcp.tool
def manage_appointments(
    action: str,
    client_name: str | None = None,
    client_phone: str | None = None,
    barber_name: str | None = None,
    service_name: str | None = None,
    date: str | None = None,
    time: str | None = None,
    appointment_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Manage barbershop appointments.

    Actions:
      - book: Create a new appointment (resolves names to IDs automatically)
      - list: List appointments (filter by date/barber/status)
      - cancel: Cancel an appointment
      - reschedule: Move appointment to new date/time
      - checkin: Mark a client as checked in (in_progress)
      - complete: Mark an appointment as completed
      - today: Get today's full schedule

    Args:
        action: One of: book, list, cancel, reschedule, checkin, complete, today
        client_name: Client's name
        client_phone: Client's phone number
        barber_name: Barber's name (for filtering or assignment)
        service_name: Service requested
        date: Date in YYYY-MM-DD format
        time: Time in HH:MM format (24h)
        appointment_id: Appointment ID (for cancel/reschedule/checkin/complete)
        notes: Additional notes
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_appointments", {
            "action": action,
            "sample_schedule": [
                {"time": "09:00", "client": "Jake", "barber": "Carlos", "service": "Fade", "status": "confirmed"},
                {"time": "09:30", "client": "Mike", "barber": "Carlos", "service": "Beard Trim", "status": "in_progress"},
                {"time": "10:00", "client": "Tom", "barber": "Alex", "service": "Full Cut + Style", "status": "pending"},
            ]
        })

    if action == "book":
        if not all([client_name, service_name, date, time]):
            return {"error": "client_name, service_name, date, and time required"}

        # Resolve names to UUIDs
        client_id = _resolve_client(sb, client_name, client_phone)
        if not client_id:
            # Auto-create client
            new_client = sb.table("clients").insert({
                "name": client_name,
                "phone": client_phone or "",
            }).execute()
            client_id = new_client.data[0]["id"] if new_client.data else None
            if not client_id:
                return {"error": f"Could not create client '{client_name}'"}

        svc = _resolve_service(sb, service_name)
        if not svc:
            return {"error": f"Service '{service_name}' not found. Use manage_services(action='list') to see available services."}

        barber_id = None
        if barber_name:
            barber_id = _resolve_barber(sb, barber_name)
            if not barber_id:
                return {"error": f"Barber '{barber_name}' not found"}
        else:
            # Pick first active barber
            any_barber = sb.table("barbers").select("id,name").eq("is_active", True).limit(1).execute()
            if any_barber.data:
                barber_id = any_barber.data[0]["id"]

        # Build start_time and end_time as timestamps
        start_dt = f"{date}T{time}:00"
        duration = svc.get("duration_minutes", 30)
        start = datetime.fromisoformat(start_dt)
        end = start + timedelta(minutes=duration)

        data = {
            "barber_id": barber_id,
            "client_id": client_id,
            "service_id": svc["id"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "status": "confirmed",
            "notes": notes or "",
        }
        result = sb.table("appointments").insert(data).execute()
        apt = result.data[0] if result.data else data
        apt["_resolved"] = {"client": client_name, "service": svc["name"], "barber": barber_name or "auto-assigned"}
        return {"appointment": apt, "status": "booked"}

    elif action == "list":
        q = sb.table("appointments").select("*")
        if date:
            q = q.gte("start_time", f"{date}T00:00:00").lt("start_time", f"{date}T23:59:59")
        if barber_name:
            bid = _resolve_barber(sb, barber_name)
            if bid:
                q = q.eq("barber_id", bid)
        result = q.order("start_time").limit(50).execute()
        # Enrich with names
        appointments = _enrich_appointments(sb, result.data)
        return {"appointments": appointments, "count": len(appointments)}

    elif action == "cancel":
        if not appointment_id:
            return {"error": "appointment_id required"}
        result = sb.table("appointments").update({"status": "cancelled"}).eq("id", appointment_id).execute()
        return {"cancelled": result.data}

    elif action == "reschedule":
        if not appointment_id:
            return {"error": "appointment_id required"}
        if not date and not time:
            return {"error": "date and/or time required for reschedule"}
        # Get current appointment to preserve duration
        current = sb.table("appointments").select("start_time,end_time,service_id").eq("id", appointment_id).execute()
        if not current.data:
            return {"error": "Appointment not found"}
        cur = current.data[0]
        old_start = datetime.fromisoformat(cur["start_time"].replace("Z", "+00:00"))
        old_end = datetime.fromisoformat(cur["end_time"].replace("Z", "+00:00"))
        duration = (old_end - old_start).total_seconds() / 60

        new_date = date or old_start.strftime("%Y-%m-%d")
        new_time = time or old_start.strftime("%H:%M")
        new_start = datetime.fromisoformat(f"{new_date}T{new_time}:00")
        new_end = new_start + timedelta(minutes=duration)

        updates = {
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
            "status": "confirmed",
        }
        if barber_name:
            bid = _resolve_barber(sb, barber_name)
            if bid:
                updates["barber_id"] = bid
        result = sb.table("appointments").update(updates).eq("id", appointment_id).execute()
        return {"rescheduled": result.data}

    elif action == "checkin":
        if not appointment_id:
            return {"error": "appointment_id required"}
        result = sb.table("appointments").update({"status": "in_progress"}).eq("id", appointment_id).execute()
        return {"checked_in": result.data}

    elif action == "complete":
        if not appointment_id:
            return {"error": "appointment_id required"}
        result = sb.table("appointments").update({"status": "completed"}).eq("id", appointment_id).execute()
        return {"completed": result.data}

    elif action == "today":
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        q = sb.table("appointments").select("*").gte("start_time", f"{today_str}T00:00:00").lt("start_time", f"{today_str}T23:59:59")
        if barber_name:
            bid = _resolve_barber(sb, barber_name)
            if bid:
                q = q.eq("barber_id", bid)
        result = q.order("start_time").execute()
        appointments = _enrich_appointments(sb, result.data)
        return {"date": today_str, "appointments": appointments, "count": len(appointments)}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 2: Client Management (table: clients)
# Columns: id, name, email, phone, notes, loyalty_points, created_at, updated_at
# ---------------------------------------------------------------------------

@mcp.tool
def manage_clients(
    action: str,
    client_name: str | None = None,
    client_phone: str | None = None,
    client_email: str | None = None,
    client_id: str | None = None,
    notes: str | None = None,
    search_query: str | None = None,
) -> dict:
    """
    Manage client profiles and preferences.

    Actions:
      - add: Register a new client
      - get: Get client details by ID or phone
      - update: Update client info
      - search: Search clients by name/phone
      - history: Get client's appointment history (with barber/service names)
      - list: List all clients (paginated)
      - loyalty: Check/update loyalty points

    Args:
        action: One of: add, get, update, search, history, list, loyalty
        client_name: Client's full name
        client_phone: Phone number
        client_email: Email address
        client_id: Client ID (for get/update/history)
        notes: Notes about the client (preferences, allergies, etc.)
        search_query: Search string for search action
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_clients", {
            "action": action,
            "sample_clients": [
                {"name": "Jake Martinez", "phone": "928-555-0101", "loyalty_points": 120},
                {"name": "Mike Johnson", "phone": "928-555-0102", "loyalty_points": 80},
            ]
        })

    table = "clients"

    if action == "add":
        if not client_name:
            return {"error": "client_name required"}
        data = {
            "name": client_name,
            "phone": client_phone or "",
            "email": client_email or "",
            "notes": notes or "",
            "loyalty_points": 0,
        }
        result = sb.table(table).insert(data).execute()
        return {"client": result.data[0] if result.data else data}

    elif action == "get":
        if client_id:
            result = sb.table(table).select("*").eq("id", client_id).execute()
        elif client_phone:
            result = sb.table(table).select("*").eq("phone", client_phone).execute()
        elif client_name:
            result = sb.table(table).select("*").ilike("name", f"%{client_name}%").limit(1).execute()
        else:
            return {"error": "client_id, client_phone, or client_name required"}
        return {"client": result.data[0] if result.data else None}

    elif action == "update":
        if not client_id:
            return {"error": "client_id required"}
        updates = {}
        if client_name:
            updates["name"] = client_name
        if client_phone:
            updates["phone"] = client_phone
        if client_email:
            updates["email"] = client_email
        if notes:
            updates["notes"] = notes
        if not updates:
            return {"error": "Nothing to update"}
        result = sb.table(table).update(updates).eq("id", client_id).execute()
        return {"updated": result.data}

    elif action == "search":
        if not search_query:
            return {"error": "search_query required"}
        result = sb.table(table).select("*").or_(
            f"name.ilike.%{search_query}%,phone.ilike.%{search_query}%"
        ).limit(20).execute()
        return {"clients": result.data, "count": len(result.data)}

    elif action == "history":
        if not client_id and not client_phone and not client_name:
            return {"error": "client_id, client_phone, or client_name required"}
        cid = client_id
        if not cid:
            cid = _resolve_client(sb, client_name, client_phone)
        if not cid:
            return {"error": "Client not found"}
        result = sb.table("appointments").select("*").eq("client_id", cid).order("start_time", desc=True).limit(20).execute()
        history = _enrich_appointments(sb, result.data)
        return {"history": history, "count": len(history)}

    elif action == "list":
        result = sb.table(table).select("*").order("name").limit(50).execute()
        return {"clients": result.data, "count": len(result.data)}

    elif action == "loyalty":
        if not client_id and not client_phone:
            return {"error": "client_id or client_phone required"}
        if not client_id:
            client_id = _resolve_client(sb, None, client_phone)
        if not client_id:
            return {"error": "Client not found"}
        result = sb.table(table).select("name,loyalty_points").eq("id", client_id).execute()
        if result.data:
            return {"client": result.data[0]["name"], "loyalty_points": result.data[0]["loyalty_points"]}
        return {"error": "Client not found"}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 3: Service Catalog (table: services)
# Columns: id, name, duration_minutes, price, description, is_active, location_id
# ---------------------------------------------------------------------------

@mcp.tool
def manage_services(
    action: str,
    service_name: str | None = None,
    price: float | None = None,
    duration_minutes: int | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    service_id: str | None = None,
) -> dict:
    """
    Manage barbershop service catalog.

    Actions:
      - list: List all active services
      - add: Add a new service
      - update: Update service details (price, duration, etc.)
      - toggle: Activate/deactivate a service

    Args:
        action: One of: list, add, update, toggle
        service_name: Service name
        price: Price in dollars
        duration_minutes: Service duration in minutes
        description: Service description
        is_active: Whether service is available
        service_id: Service ID (for update/toggle)
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_services", {
            "action": action,
            "sample_services": [
                {"name": "Classic Cut", "price": 25, "duration_minutes": 30},
                {"name": "Fade", "price": 30, "duration_minutes": 35},
                {"name": "Beard Trim", "price": 15, "duration_minutes": 15},
                {"name": "Hot Towel Shave", "price": 35, "duration_minutes": 30},
                {"name": "Cut + Beard Combo", "price": 40, "duration_minutes": 45},
            ]
        })

    table = "services"

    if action == "list":
        q = sb.table(table).select("*").eq("is_active", True)
        result = q.order("name").execute()
        return {"services": result.data, "count": len(result.data)}

    elif action == "add":
        if not all([service_name, price, duration_minutes]):
            return {"error": "service_name, price, and duration_minutes required"}
        data = {
            "name": service_name,
            "price": price,
            "duration_minutes": duration_minutes,
            "description": description or "",
            "is_active": True,
        }
        result = sb.table(table).insert(data).execute()
        return {"service": result.data[0] if result.data else data}

    elif action == "update":
        if not service_id and not service_name:
            return {"error": "service_id or service_name required"}
        updates = {}
        if price is not None:
            updates["price"] = price
        if duration_minutes is not None:
            updates["duration_minutes"] = duration_minutes
        if description is not None:
            updates["description"] = description
        if is_active is not None:
            updates["is_active"] = is_active
        if not updates:
            return {"error": "Nothing to update"}
        if service_id:
            result = sb.table(table).update(updates).eq("id", service_id).execute()
        else:
            result = sb.table(table).update(updates).ilike("name", f"%{service_name}%").execute()
        return {"updated": result.data}

    elif action == "toggle":
        if not service_id and not service_name:
            return {"error": "service_id or service_name required"}
        if service_id:
            svc = sb.table(table).select("is_active").eq("id", service_id).execute()
        else:
            svc = sb.table(table).select("is_active,id").ilike("name", f"%{service_name}%").limit(1).execute()
        if not svc.data:
            return {"error": "Service not found"}
        new_status = not svc.data[0]["is_active"]
        sid = service_id or svc.data[0]["id"]
        sb.table(table).update({"is_active": new_status}).eq("id", sid).execute()
        return {"service": service_name or service_id, "is_active": new_status}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 4: Availability Check
# Uses: barbers, availability, appointments tables
# availability: barber_id, day_of_week (enum), start_time (TIME), end_time (TIME)
# ---------------------------------------------------------------------------

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@mcp.tool
def check_availability(
    date: str,
    barber_name: str | None = None,
    service_name: str | None = None,
    duration_minutes: int = 30,
) -> dict:
    """
    Check available appointment slots.

    Returns open time slots for a given date, optionally filtered by barber
    and service type. Uses real barber schedules and existing bookings.

    Args:
        date: Date to check in YYYY-MM-DD format
        barber_name: Specific barber (or None for any available)
        service_name: Service name (to determine duration)
        duration_minutes: Default slot duration if service not specified
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("check_availability", {
            "date": date,
            "sample_slots": [
                {"time": "09:00", "barbers": ["Carlos", "Alex"]},
                {"time": "09:30", "barbers": ["Alex"]},
                {"time": "10:00", "barbers": ["Carlos", "Alex"]},
                {"time": "10:30", "barbers": ["Carlos"]},
                {"time": "11:00", "barbers": ["Carlos", "Alex"]},
            ]
        })

    # Determine service duration
    if service_name:
        svc = _resolve_service(sb, service_name)
        if svc:
            duration_minutes = svc["duration_minutes"]

    # Figure out day of week for availability lookup
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    day_name = DAY_NAMES[target_date.weekday()]

    # Get barbers
    if barber_name:
        bid = _resolve_barber(sb, barber_name)
        if not bid:
            return {"error": f"Barber '{barber_name}' not found"}
        barbers_data = sb.table("barbers").select("id,name").eq("id", bid).execute()
    else:
        barbers_data = sb.table("barbers").select("id,name").eq("is_active", True).execute()

    if not barbers_data.data:
        return {"date": date, "available_slots": [], "note": "No active barbers found"}

    # Get working hours for this day
    barber_ids = [b["id"] for b in barbers_data.data]
    barber_names = {b["id"]: b["name"] for b in barbers_data.data}

    # Try availability table; fall back to default hours (09:00-18:00)
    barber_hours = {}
    try:
        avail = sb.table("availability").select("barber_id,start_time,end_time").eq("day_of_week", day_name).in_("barber_id", barber_ids).execute()
        for a in avail.data:
            barber_hours[a["barber_id"]] = (a["start_time"], a["end_time"])
    except Exception:
        pass
    # Default hours for barbers without explicit availability
    for bid in barber_ids:
        if bid not in barber_hours:
            barber_hours[bid] = ("09:00:00", "18:00:00")

    # Get existing appointments for this date (non-cancelled)
    existing = sb.table("appointments").select("barber_id,start_time,end_time,status").gte("start_time", f"{date}T00:00:00").lt("start_time", f"{date}T23:59:59").execute()
    # Filter out cancelled/no_show in Python (Supabase not_.in_ syntax varies)
    existing.data = [a for a in existing.data if a.get("status") not in ("cancelled", "no_show")]

    booked_slots: dict[str, list[tuple[str, str]]] = {}
    for apt in existing.data:
        bid = apt["barber_id"]
        if bid not in booked_slots:
            booked_slots[bid] = []
        s = apt["start_time"][11:16] if "T" in apt["start_time"] else apt["start_time"][:5]
        e = apt["end_time"][11:16] if "T" in apt["end_time"] else apt["end_time"][:5]
        booked_slots[bid].append((s, e))

    # Generate slots
    available_slots = []
    for h in range(7, 21):  # 7 AM to 8 PM
        for m in [0, 30]:
            slot_time = f"{h:02d}:{m:02d}"
            slot_end_dt = datetime(2000, 1, 1, h, m) + timedelta(minutes=duration_minutes)
            slot_end = slot_end_dt.strftime("%H:%M")

            free_barbers = []
            for bid in barber_ids:
                # Check if barber works this day
                if bid not in barber_hours:
                    continue
                work_start, work_end = barber_hours[bid]
                if slot_time < work_start[:5] or slot_end > work_end[:5]:
                    continue

                # Check if slot conflicts with existing booking
                conflict = False
                for bs, be in booked_slots.get(bid, []):
                    if slot_time < be and slot_end > bs:
                        conflict = True
                        break
                if not conflict:
                    free_barbers.append(barber_names[bid])

            if free_barbers:
                available_slots.append({
                    "time": slot_time,
                    "available_barbers": free_barbers,
                    "duration_minutes": duration_minutes,
                })

    return {
        "date": date,
        "day": day_name,
        "service": service_name,
        "requested_barber": barber_name,
        "available_slots": available_slots,
        "total_open": len(available_slots),
    }


# ---------------------------------------------------------------------------
# Tool 5: Walk-in Queue (in-memory — Barber CRM has no walkin table)
# ---------------------------------------------------------------------------

@mcp.tool
def manage_walkins(
    action: str,
    client_name: str | None = None,
    service_name: str | None = None,
    phone: str | None = None,
    walkin_id: str | None = None,
) -> dict:
    """
    Manage the walk-in queue.

    Note: Queue is in-memory per server session. For persistent queue,
    connect a walkin_queue table.

    Actions:
      - add: Add a walk-in to the queue
      - queue: View current queue with wait times
      - next: Call the next person in line
      - remove: Remove someone from the queue
      - estimate: Get estimated wait time

    Args:
        action: One of: add, queue, next, remove, estimate
        client_name: Walk-in client's name
        service_name: Requested service
        phone: Phone number (for text-when-ready)
        walkin_id: Walk-in entry ID (for remove)
    """
    global _walkin_counter

    # Get avg service time from DB if available
    avg_time = 30
    sb = _get_supabase()
    if sb and service_name:
        svc = _resolve_service(sb, service_name)
        if svc:
            avg_time = svc["duration_minutes"]

    if action == "add":
        if not client_name:
            return {"error": "client_name required"}
        _walkin_counter += 1
        position = len([w for w in _walkin_queue if w["status"] == "waiting"]) + 1
        entry = {
            "id": str(_walkin_counter),
            "client_name": client_name,
            "service_name": service_name or "General",
            "phone": phone or "",
            "status": "waiting",
            "position": position,
            "estimated_wait_minutes": position * avg_time,
            "joined_at": datetime.now(timezone.utc).isoformat(),
        }
        _walkin_queue.append(entry)
        return {
            "walkin": entry,
            "position": position,
            "estimated_wait": f"~{position * avg_time} minutes",
        }

    elif action == "queue":
        waiting = [w for w in _walkin_queue if w["status"] == "waiting"]
        queue = []
        for i, entry in enumerate(waiting, 1):
            queue.append({
                "position": i,
                "id": entry["id"],
                "client_name": entry["client_name"],
                "service": entry["service_name"],
                "estimated_wait": f"~{i * avg_time} minutes",
                "joined_at": entry["joined_at"],
            })
        return {"queue": queue, "total_waiting": len(queue)}

    elif action == "next":
        waiting = [w for w in _walkin_queue if w["status"] == "waiting"]
        if not waiting:
            return {"message": "Queue is empty."}
        entry = waiting[0]
        entry["status"] = "called"
        entry["called_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "called": entry["client_name"],
            "service": entry["service_name"],
            "phone": entry["phone"],
            "waited_since": entry["joined_at"],
        }

    elif action == "remove":
        if not walkin_id:
            return {"error": "walkin_id required"}
        for w in _walkin_queue:
            if w["id"] == walkin_id:
                w["status"] = "removed"
                return {"removed": walkin_id}
        return {"error": "Walk-in not found"}

    elif action == "estimate":
        waiting = [w for w in _walkin_queue if w["status"] == "waiting"]
        wait = len(waiting) * avg_time
        return {
            "people_ahead": len(waiting),
            "estimated_wait": f"~{wait} minutes",
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 6: SMS Reminders
# Uses notification_history table for logging sent messages.
# ---------------------------------------------------------------------------

@mcp.tool
def send_reminders(
    action: str,
    appointment_id: str | None = None,
    phone: str | None = None,
    message: str | None = None,
    reminder_type: str = "appointment",
) -> dict:
    """
    Send appointment reminders and follow-up messages.

    Actions:
      - appointment: Send appointment reminder (24h or 1h before)
      - follow_up: Send post-appointment follow-up (review request)
      - custom: Send a custom message
      - pending: List tomorrow's appointments needing reminders
      - templates: List available reminder templates

    Args:
        action: One of: appointment, follow_up, custom, pending, templates
        appointment_id: Appointment to remind about
        phone: Phone number (overrides appointment's phone)
        message: Custom message text
        reminder_type: Type of reminder (24h, 1h, follow_up)
    """
    if action == "appointment":
        if not appointment_id:
            return {"error": "appointment_id required"}
        sb = _get_supabase()
        if sb:
            apt = sb.table("appointments").select("*").eq("id", appointment_id).execute()
            if apt.data:
                enriched = _enrich_appointments(sb, apt.data)
                a = enriched[0]
                start = a.get("start_time", "")
                time_str = start[11:16] if "T" in start else "your scheduled time"
                date_str = start[:10] if "T" in start else "your appointment date"
                msg = (
                    f"Hi {a.get('client_name', 'there')}! Reminder: you have a "
                    f"{a.get('service_name', 'appointment')} with {a.get('barber_name', 'us')} "
                    f"at {time_str} on {date_str}. See you soon!"
                )
                # Get client phone
                cid = a.get("client_id")
                if cid and not phone:
                    cr = sb.table("clients").select("phone").eq("id", cid).execute()
                    to = cr.data[0]["phone"] if cr.data else ""
                else:
                    to = phone or ""
            else:
                msg = "Appointment reminder"
                to = phone or ""
        else:
            msg = "You have an upcoming appointment. See you soon!"
            to = phone or ""

        return {
            "status": "queued",
            "to": to,
            "message": msg,
            "reminder_type": reminder_type,
            "note": "Connect Twilio for live SMS delivery.",
        }

    elif action == "follow_up":
        msg = (
            "Thanks for visiting! We hope you love your new look. "
            "We'd really appreciate a quick review. See you next time!"
        )
        return {
            "status": "queued",
            "to": phone or "",
            "message": message or msg,
            "type": "follow_up",
        }

    elif action == "custom":
        if not phone or not message:
            return {"error": "phone and message required"}
        return {
            "status": "queued",
            "to": phone,
            "message": message,
            "type": "custom",
        }

    elif action == "pending":
        sb = _get_supabase()
        if not sb:
            return _demo_response("send_reminders", {"action": "pending"})
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        result = sb.table("appointments").select("*").gte("start_time", f"{tomorrow}T00:00:00").lt("start_time", f"{tomorrow}T23:59:59").in_("status", ["pending", "confirmed"]).execute()
        appointments = _enrich_appointments(sb, result.data)
        return {
            "date": tomorrow,
            "appointments_needing_reminder": appointments,
            "count": len(appointments),
        }

    elif action == "templates":
        return {
            "templates": {
                "24h_reminder": "Hi {name}! Reminder: {service} with {barber} at {time} tomorrow. Reply CANCEL to cancel.",
                "1h_reminder": "Hi {name}! Your {service} appointment is in 1 hour at {time}. See you soon!",
                "follow_up": "Thanks for visiting! Love your look? Leave us a review!",
                "birthday": "Happy Birthday {name}! Enjoy 20% off your next visit. Book now!",
                "loyalty": "You've earned {points} loyalty points! Redeem for discounts on your next visit.",
                "no_show": "We missed you today, {name}. Want to reschedule? Reply YES.",
                "promo": "This week only: All services 10% off. Book your spot!",
            }
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 7: Shop Analytics
# Uses appointments_with_details view + services + reviews tables
# ---------------------------------------------------------------------------

@mcp.tool
def shop_analytics(
    report: str,
    period: str = "today",
    barber_name: str | None = None,
) -> dict:
    """
    Get barbershop analytics and performance reports.

    Reports:
      - revenue: Revenue breakdown by period
      - staff_performance: Per-barber stats (appointments, revenue, rating)
      - client_retention: Client retention and repeat visit rates
      - summary: Full business summary with KPIs

    Args:
        report: One of: revenue, staff_performance, client_retention, summary
        period: Time period (today, week, month)
        barber_name: Filter by specific barber
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("shop_analytics", {
            "report": report,
            "sample_data": {
                "revenue_today": 580,
                "appointments_today": 18,
                "avg_ticket": 32.22,
                "top_barber": "Carlos",
                "retention_rate": "72%",
                "popular_service": "Fade",
            }
        })

    now = datetime.now(timezone.utc)
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0).isoformat()
    elif period == "week":
        since = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        since = (now - timedelta(days=30)).isoformat()
    else:
        since = (now - timedelta(days=1)).isoformat()

    q = sb.table("appointments").select("*").gte("start_time", since)
    if barber_name:
        bid = _resolve_barber(sb, barber_name)
        if bid:
            q = q.eq("barber_id", bid)
    apts = q.execute()
    apts.data = _enrich_appointments(sb, apts.data)

    if report == "revenue":
        total = sum(float(a.get("service_price", 0) or 0) for a in apts.data if a.get("status") == "completed")
        completed = [a for a in apts.data if a.get("status") == "completed"]
        return {
            "period": period,
            "total_revenue": round(total, 2),
            "completed": len(completed),
            "total_appointments": len(apts.data),
            "average_ticket": round(total / max(len(completed), 1), 2),
        }

    elif report == "staff_performance":
        barbers: dict[str, dict] = {}
        for a in apts.data:
            b = a.get("barber_name", "Unknown")
            if b not in barbers:
                barbers[b] = {"appointments": 0, "completed": 0, "revenue": 0.0, "no_shows": 0}
            barbers[b]["appointments"] += 1
            if a.get("status") == "completed":
                barbers[b]["completed"] += 1
                barbers[b]["revenue"] += float(a.get("service_price", 0) or 0)
            elif a.get("status") == "no_show":
                barbers[b]["no_shows"] += 1
        # Round revenue
        for b in barbers:
            barbers[b]["revenue"] = round(barbers[b]["revenue"], 2)

        # Get avg ratings from reviews table
        for bname in barbers:
            bid = _resolve_barber(sb, bname)
            if bid:
                reviews = sb.table("reviews").select("rating").eq("barber_id", bid).execute()
                if reviews.data:
                    avg = sum(r["rating"] for r in reviews.data) / len(reviews.data)
                    barbers[bname]["avg_rating"] = round(avg, 1)
                    barbers[bname]["review_count"] = len(reviews.data)

        return {"period": period, "staff": barbers}

    elif report == "client_retention":
        client_visits: dict[str, int] = {}
        for a in apts.data:
            c = a.get("client_name", "Unknown")
            client_visits[c] = client_visits.get(c, 0) + 1
        total_clients = len(client_visits)
        repeat = sum(1 for v in client_visits.values() if v > 1)
        return {
            "period": period,
            "total_unique_clients": total_clients,
            "repeat_clients": repeat,
            "retention_rate": f"{round(repeat / max(total_clients, 1) * 100)}%" if total_clients else "N/A",
            "avg_visits": round(sum(client_visits.values()) / max(total_clients, 1), 1),
        }

    elif report == "summary":
        completed = [a for a in apts.data if a.get("status") == "completed"]
        total = sum(float(a.get("service_price", 0) or 0) for a in completed)
        by_status = {}
        for a in apts.data:
            s = a.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1

        svc_counts: dict[str, int] = {}
        for a in apts.data:
            s = a.get("service_name", "Unknown")
            svc_counts[s] = svc_counts.get(s, 0) + 1
        top_services = sorted(svc_counts.items(), key=lambda x: -x[1])[:5]

        return {
            "period": period,
            "total_appointments": len(apts.data),
            "total_revenue": round(total, 2),
            "avg_ticket": round(total / max(len(completed), 1), 2),
            "by_status": by_status,
            "top_services": [{"name": n, "count": c} for n, c in top_services],
        }

    return {"error": f"Unknown report: {report}"}


# ---------------------------------------------------------------------------
# Run server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(os.getenv("MCP_BARBERSHOP_PORT", "8801"))
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run()  # stdio mode (default)
