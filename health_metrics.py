import psutil
import time
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from heartbeat_monitor import get_heartbeat_monitor
    _HAS_HEARTBEAT_MONITOR = True
except ImportError:
    _HAS_HEARTBEAT_MONITOR = False

try:
    from scheduled_hands import get_scheduler
    _HAS_SCHEDULED_HANDS = True
except ImportError:
    _HAS_SCHEDULED_HANDS = False

def get_system_uptime() -> Dict[str, Any]:
    """Get system uptime in a human-readable format and seconds."""
    boot_time_timestamp = psutil.boot_time()
    boot_time_datetime = datetime.fromtimestamp(boot_time_timestamp)
    now = datetime.now()
    uptime_delta = now - boot_time_datetime
    uptime_seconds = int(uptime_delta.total_seconds())

    days = uptime_delta.days
    hours = uptime_delta.seconds // 3600
    minutes = (uptime_delta.seconds % 3600) // 60
    seconds = uptime_delta.seconds % 60

    if days > 0:
        uptime_human = f"{days}d {hours}h {minutes}m {seconds}s"
    else:
        uptime_human = f"{hours}h {minutes}m {seconds}s"

    return {
        "uptime_seconds": uptime_seconds,
        "uptime_human": uptime_human
    }

def get_memory_usage() -> Dict[str, Any]:
    """Get memory usage in MB and percentage."""
    mem = psutil.virtual_memory()
    total_mb = mem.total / (1024 * 1024)
    used_mb = mem.used / (1024 * 1024)
    percentage = mem.percent
    return {
        "total_mb": round(total_mb, 2),
        "used_mb": round(used_mb, 2),
        "percentage": percentage
    }

def get_disk_usage(path: str = '/') -> Dict[str, Any]:
    """Get disk usage for a given path in GB and percentage."""
    disk = psutil.disk_usage(path)
    total_gb = disk.total / (1024 * 1024 * 1024)
    used_gb = disk.used / (1024 * 1024 * 1024)
    percentage = disk.percent
    return {
        "total_gb": round(total_gb, 2),
        "used_gb": round(used_gb, 2),
        "percentage": percentage
    }

def get_active_jobs_count() -> int:
    """Get the count of active jobs from the heartbeat monitor."""
    if _HAS_HEARTBEAT_MONITOR:
        monitor = get_heartbeat_monitor()
        if monitor:
            return len(monitor.get_in_flight_agents())
    return 0

def get_scheduled_hands_status() -> Optional[Dict[str, Any]]:
    """Get the status of scheduled hands."""
    if _HAS_SCHEDULED_HANDS:
        scheduler = get_scheduler()
        if scheduler:
            # Assuming get_scheduler().get_status() returns a dict
            return scheduler.get_status()
    return None

async def get_health_metrics() -> Dict[str, Any]:
    """Collects all health metrics for the /api/health endpoint."""
    uptime = get_system_uptime()
    memory = get_memory_usage()
    disk = get_disk_usage()
    active_jobs = get_active_jobs_count()
    scheduled_hands_status = get_scheduled_hands_status()

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "uptime": uptime,
        "memory_usage": memory,
        "disk_usage": disk,
        "active_jobs_count": active_jobs,
        "last_eval_score": "N/A",  # Placeholder as no source was found
        "scheduled_hands_status": scheduled_hands_status
    }
