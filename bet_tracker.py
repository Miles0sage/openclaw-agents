"""
Bet Tracking + P&L System
Tracks every bet recommendation, whether it was placed, and the result.
Stores in data/betting/bet_ledger.json with thread-safe file access.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
import fcntl

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("bet_tracker")

# Directories
DATA_DIR = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/betting")
LEDGER_FILE = DATA_DIR / "bet_ledger.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Starting bankroll
STARTING_BANKROLL = 500.0


def _load_ledger() -> List[Dict[str, Any]]:
    """Load bet ledger with file locking."""
    if not LEDGER_FILE.exists():
        return []

    try:
        with open(LEDGER_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"Error loading ledger: {e}")
        return []


def _save_ledger(ledger: List[Dict[str, Any]]) -> None:
    """Save bet ledger with file locking and atomic write."""
    try:
        # Write to temp file first
        temp_file = LEDGER_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(ledger, f, indent=2)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Atomic move
        temp_file.replace(LEDGER_FILE)
    except Exception as e:
        logger.error(f"Error saving ledger: {e}")
        raise


def _log_bet(game: str, side: str, odds: float, model_prob: float, edge_pct: float,
             book: str, stake_usd: float, market: str = "h2h") -> Dict[str, Any]:
    """Log a new bet recommendation."""
    ledger = _load_ledger()

    # Calculate implied probability from odds (decimal)
    implied_prob = 1.0 / odds

    # Calculate quarter-kelly percentage
    kelly_pct = (model_prob * odds - (1.0 - model_prob)) / odds if model_prob > 0 else 0
    quarter_kelly_pct = (kelly_pct / 4.0) * 100.0 if kelly_pct > 0 else 0.0

    bet = {
        "bet_id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sport": "nba",
        "game": game,
        "side": side,
        "market": market,
        "entry_odds": odds,
        "entry_implied_prob": round(implied_prob, 4),
        "model_prob": round(model_prob, 4),
        "edge_pct": round(edge_pct, 2),
        "book": book,
        "stake_usd": stake_usd,
        "quarter_kelly_pct": round(quarter_kelly_pct, 2),
        "status": "pending",
        "result_payout": None,
        "pnl": None,
        "clv": None,
        "notes": ""
    }

    ledger.append(bet)
    _save_ledger(ledger)

    return bet


def _settle_bet(bet_id: str, result: str) -> Dict[str, Any]:
    """Settle a bet (won/lost/void/push)."""
    ledger = _load_ledger()
    bet = None
    idx = -1

    for i, b in enumerate(ledger):
        if b["bet_id"] == bet_id:
            bet = b
            idx = i
            break

    if not bet:
        return {"error": f"Bet {bet_id} not found"}

    if bet["status"] != "pending":
        return {"error": f"Bet {bet_id} already settled as {bet['status']}"}

    # Calculate payout and P&L
    stake = bet["stake_usd"]
    odds = bet["entry_odds"]

    if result == "won":
        payout = stake * odds
        pnl = payout - stake
    elif result == "lost":
        payout = 0.0
        pnl = -stake
    elif result == "void":
        payout = stake
        pnl = 0.0
    elif result == "push":
        payout = stake
        pnl = 0.0
    else:
        return {"error": f"Invalid result: {result}"}

    bet["status"] = result
    bet["result_payout"] = round(payout, 2)
    bet["pnl"] = round(pnl, 2)

    ledger[idx] = bet
    _save_ledger(ledger)

    return bet


def _get_pending() -> List[Dict[str, Any]]:
    """Get all unsettled bets."""
    ledger = _load_ledger()
    return [b for b in ledger if b["status"] == "pending"]


def _get_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Get last N settled bets."""
    ledger = _load_ledger()
    settled = [b for b in ledger if b["status"] != "pending"]
    return settled[-limit:]


def _calculate_pnl() -> Dict[str, Any]:
    """Calculate P&L summary."""
    ledger = _load_ledger()
    settled = [b for b in ledger if b["status"] != "pending"]

    if not settled:
        return {
            "total_bets": 0,
            "wins": 0,
            "losses": 0,
            "voids": 0,
            "pushes": 0,
            "win_rate_pct": 0.0,
            "total_staked": 0.0,
            "total_profit": 0.0,
            "roi_pct": 0.0,
            "current_bankroll": STARTING_BANKROLL,
            "best_bet": None,
            "worst_bet": None
        }

    wins = [b for b in settled if b["status"] == "won"]
    losses = [b for b in settled if b["status"] == "lost"]
    voids = [b for b in settled if b["status"] == "void"]
    pushes = [b for b in settled if b["status"] == "push"]

    total_staked = sum(b["stake_usd"] for b in settled)
    total_profit = sum(b["pnl"] for b in settled if b["pnl"] is not None)

    win_count = len(wins)
    total_decisive = win_count + len(losses)
    win_rate = (win_count / total_decisive * 100) if total_decisive > 0 else 0.0

    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0

    # Best and worst bets
    best_bet = max(settled, key=lambda b: b.get("pnl", -999)) if settled else None
    worst_bet = min(settled, key=lambda b: b.get("pnl", 999)) if settled else None

    return {
        "total_bets": len(settled),
        "wins": len(wins),
        "losses": len(losses),
        "voids": len(voids),
        "pushes": len(pushes),
        "win_rate_pct": round(win_rate, 2),
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round(roi, 2),
        "current_bankroll": round(STARTING_BANKROLL + total_profit, 2),
        "best_bet": best_bet.get("bet_id") if best_bet else None,
        "worst_bet": worst_bet.get("bet_id") if worst_bet else None
    }


def _get_daily_pnl() -> Dict[str, Any]:
    """Get today's P&L."""
    ledger = _load_ledger()
    today = datetime.now(timezone.utc).date()

    today_bets = []
    for b in ledger:
        bet_date = datetime.fromisoformat(b["timestamp"]).date()
        if bet_date == today and b["status"] != "pending":
            today_bets.append(b)

    if not today_bets:
        return {
            "date": today.isoformat(),
            "total_bets": 0,
            "wins": 0,
            "losses": 0,
            "total_staked": 0.0,
            "total_profit": 0.0,
            "roi_pct": 0.0
        }

    wins = len([b for b in today_bets if b["status"] == "won"])
    losses = len([b for b in today_bets if b["status"] == "lost"])
    total_staked = sum(b["stake_usd"] for b in today_bets)
    total_profit = sum(b["pnl"] for b in today_bets if b["pnl"] is not None)
    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0

    return {
        "date": today.isoformat(),
        "total_bets": len(today_bets),
        "wins": wins,
        "losses": losses,
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round(roi, 2)
    }


def _get_streak() -> Dict[str, Any]:
    """Get current win/loss streak."""
    ledger = _load_ledger()
    settled = [b for b in ledger if b["status"] in ["won", "lost"]]

    if not settled:
        return {
            "current_streak_type": None,
            "current_streak_count": 0,
            "best_win_streak": 0,
            "best_loss_streak": 0
        }

    current_streak_type = settled[-1]["status"]
    current_streak_count = 1

    for i in range(len(settled) - 2, -1, -1):
        if settled[i]["status"] == current_streak_type:
            current_streak_count += 1
        else:
            break

    # Track best streaks
    best_win_streak = 0
    best_loss_streak = 0
    current_type = None
    current_count = 0

    for b in settled:
        if b["status"] in ["won", "lost"]:
            if b["status"] == current_type:
                current_count += 1
            else:
                if current_type == "won":
                    best_win_streak = max(best_win_streak, current_count)
                else:
                    best_loss_streak = max(best_loss_streak, current_count)
                current_type = b["status"]
                current_count = 1

    if current_type == "won":
        best_win_streak = max(best_win_streak, current_count)
    else:
        best_loss_streak = max(best_loss_streak, current_count)

    return {
        "current_streak_type": current_streak_type,
        "current_streak_count": current_streak_count,
        "best_win_streak": best_win_streak,
        "best_loss_streak": best_loss_streak
    }


def bet_tracker(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Main entry point for bet tracking."""
    params = params or {}

    try:
        if action == "log":
            # params: game, side, odds, model_prob, edge_pct, book, stake_usd, market
            bet = _log_bet(
                game=params.get("game", ""),
                side=params.get("side", ""),
                odds=float(params.get("odds", 1.0)),
                model_prob=float(params.get("model_prob", 0.5)),
                edge_pct=float(params.get("edge_pct", 0.0)),
                book=params.get("book", ""),
                stake_usd=float(params.get("stake_usd", 0.0)),
                market=params.get("market", "h2h")
            )
            return json.dumps({
                "action": "log",
                "success": True,
                "bet": bet
            })

        elif action == "settle":
            # params: bet_id, result
            bet = _settle_bet(
                bet_id=params.get("bet_id", ""),
                result=params.get("result", "")
            )
            if "error" in bet:
                return json.dumps({"action": "settle", "success": False, "error": bet["error"]})
            return json.dumps({
                "action": "settle",
                "success": True,
                "bet": bet
            })

        elif action == "pending":
            pending = _get_pending()
            return json.dumps({
                "action": "pending",
                "count": len(pending),
                "bets": pending
            })

        elif action == "history":
            limit = int(params.get("limit", 20))
            history = _get_history(limit)
            return json.dumps({
                "action": "history",
                "count": len(history),
                "bets": history
            })

        elif action == "pnl":
            summary = _calculate_pnl()
            return json.dumps({
                "action": "pnl",
                "summary": summary
            })

        elif action == "daily":
            daily = _get_daily_pnl()
            return json.dumps({
                "action": "daily",
                "daily": daily
            })

        elif action == "streak":
            streak = _get_streak()
            return json.dumps({
                "action": "streak",
                "streak": streak
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "available_actions": ["log", "settle", "pending", "history", "pnl", "daily", "streak"]
            })

    except Exception as e:
        logger.error(f"Error in bet_tracker({action}): {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "action": action
        })


if __name__ == "__main__":
    # Test basic functionality
    print(bet_tracker("pnl"))
