"""
Trading Safety Layer — Pre-flight checks, limits, kill switch, audit log.

Every trade (real or simulated) flows through this module before execution.
All amounts are in CENTS to avoid float precision bugs (Kalshi convention).
"""

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

DATA_DIR = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/trading")
CONFIG_PATH = DATA_DIR / "config.json"
TRADE_LOG_PATH = DATA_DIR / "trade_log.jsonl"


@dataclass
class TradingConfig:
    dry_run: bool = True
    kill_switch: bool = False
    confirm_threshold_cents: int = 5000       # $50 — flag for confirmation
    max_per_market_cents: int = 50000         # $500 per market
    max_total_exposure_cents: int = 200000    # $2000 total
    allowed_platforms: list = field(default_factory=lambda: ["polymarket", "kalshi"])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TradingConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _load_config() -> TradingConfig:
    """Load config from disk, or return defaults."""
    if CONFIG_PATH.exists():
        try:
            return TradingConfig.from_dict(json.loads(CONFIG_PATH.read_text()))
        except Exception:
            pass
    return TradingConfig()


def _save_config(cfg: TradingConfig):
    """Persist config to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg.to_dict(), indent=2))


def check_order_safety(platform: str, ticker: str, side: str,
                       price_cents: int, count: int) -> dict:
    """Pre-flight check before every order.

    Returns {"ok": True} or {"ok": False, "reason": "..."}.
    """
    cfg = _load_config()

    # Kill switch
    if cfg.kill_switch:
        return {"ok": False, "reason": "Kill switch is ON — all trading halted"}

    # Platform check
    if platform.lower() not in cfg.allowed_platforms:
        return {"ok": False, "reason": f"Platform '{platform}' not in allowed list: {cfg.allowed_platforms}"}

    # Side check
    if side.lower() not in ("yes", "no", "buy", "sell"):
        return {"ok": False, "reason": f"Invalid side '{side}'. Use: yes, no, buy, sell"}

    # Order value
    order_value = price_cents * count
    if order_value <= 0:
        return {"ok": False, "reason": f"Invalid order value: {order_value} cents (price={price_cents}, count={count})"}

    # Per-market limit
    if order_value > cfg.max_per_market_cents:
        return {
            "ok": False,
            "reason": f"Order ${order_value/100:.2f} exceeds per-market limit ${cfg.max_per_market_cents/100:.2f}"
        }

    # Confirmation threshold
    needs_confirm = order_value > cfg.confirm_threshold_cents

    # Total exposure check (sum from trade log)
    total_exposure = _calculate_exposure(platform)
    if total_exposure + order_value > cfg.max_total_exposure_cents:
        return {
            "ok": False,
            "reason": f"Would exceed total exposure limit. Current: ${total_exposure/100:.2f}, "
                      f"order: ${order_value/100:.2f}, limit: ${cfg.max_total_exposure_cents/100:.2f}"
        }

    return {
        "ok": True,
        "dry_run": cfg.dry_run,
        "needs_confirmation": needs_confirm,
        "order_value_cents": order_value,
        "order_value_usd": f"${order_value/100:.2f}",
        "total_exposure_after": total_exposure + order_value,
    }


def _calculate_exposure(platform: str) -> int:
    """Sum net exposure from trade log for a platform (cents)."""
    if not TRADE_LOG_PATH.exists():
        return 0
    total = 0
    try:
        for line in TRADE_LOG_PATH.read_text().strip().split("\n"):
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("platform", "").lower() != platform.lower():
                continue
            if entry.get("simulated"):
                continue
            action = entry.get("action", "")
            value = entry.get("order_value_cents", 0)
            if action in ("buy", "yes", "market_buy"):
                total += value
            elif action in ("sell", "no", "market_sell"):
                total -= value
    except Exception:
        pass
    return max(total, 0)


def log_trade(platform: str, action: str, details: dict):
    """Append-only audit log — every order (real or simulated)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform,
        "action": action,
        "simulated": details.get("dry_run", True),
        **details,
    }
    with open(TRADE_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def manage_safety(action: str, config: Optional[dict] = None) -> str:
    """Manage trading safety configuration.

    Actions:
        status      — Current config + exposure summary
        get_config  — Raw config JSON
        set_config  — Update config fields (partial update)
        trade_log   — Recent trade log entries
        kill_switch — Toggle kill switch (on/off)
        reset       — Reset to safe defaults
    """
    try:
        cfg = _load_config()

        if action == "status":
            poly_exposure = _calculate_exposure("polymarket")
            kalshi_exposure = _calculate_exposure("kalshi")
            log_count = 0
            if TRADE_LOG_PATH.exists():
                log_count = sum(1 for line in TRADE_LOG_PATH.read_text().strip().split("\n") if line)
            return json.dumps({
                "config": cfg.to_dict(),
                "exposure": {
                    "polymarket_cents": poly_exposure,
                    "kalshi_cents": kalshi_exposure,
                    "total_cents": poly_exposure + kalshi_exposure,
                    "total_usd": f"${(poly_exposure + kalshi_exposure)/100:.2f}",
                    "limit_usd": f"${cfg.max_total_exposure_cents/100:.2f}",
                },
                "trade_log_entries": log_count,
                "safety_status": "KILL SWITCH ON" if cfg.kill_switch else ("DRY RUN" if cfg.dry_run else "LIVE TRADING"),
            })

        elif action == "get_config":
            return json.dumps(cfg.to_dict())

        elif action == "set_config":
            if not config:
                return json.dumps({"error": "Provide config dict with fields to update"})
            d = cfg.to_dict()
            d.update({k: v for k, v in config.items() if k in TradingConfig.__dataclass_fields__})
            cfg = TradingConfig.from_dict(d)
            _save_config(cfg)
            return json.dumps({"updated": True, "config": cfg.to_dict()})

        elif action == "trade_log":
            if not TRADE_LOG_PATH.exists():
                return json.dumps({"entries": [], "count": 0})
            lines = TRADE_LOG_PATH.read_text().strip().split("\n")
            entries = [json.loads(l) for l in lines[-50:] if l]  # Last 50
            return json.dumps({"entries": entries, "count": len(entries)})

        elif action == "kill_switch":
            # Toggle
            cfg.kill_switch = not cfg.kill_switch
            _save_config(cfg)
            state = "ON — all trading halted" if cfg.kill_switch else "OFF — trading allowed"
            log_trade("system", "kill_switch", {"state": state, "dry_run": False})
            return json.dumps({"kill_switch": cfg.kill_switch, "state": state})

        elif action == "reset":
            cfg = TradingConfig()
            _save_config(cfg)
            return json.dumps({"reset": True, "config": cfg.to_dict()})

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: status, get_config, set_config, trade_log, kill_switch, reset"})

    except Exception as e:
        return json.dumps({"error": str(e)})
