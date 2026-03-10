import sys
import os
import json
from pathlib import Path

# Add the root directory to the Python path to allow importing bet_tracker
sys.path.insert(0, '.')

from bet_tracker import bet_tracker, LEDGER_FILE, STARTING_BANKROLL

def run_test_betting_pipeline():
    print("Running Full Betting Pipeline Test...")
    
    # Ensure a clean slate for testing
    if LEDGER_FILE.exists():
        os.remove(LEDGER_FILE)

    # 1. Log 3 test bets
    print("Test 1: Logging bets...")
    try:
        bet1 = json.loads(bet_tracker("log", {
            "game": "LAL vs GSW", "side": "LAL", "odds": 2.10, 
            "model_prob": 0.55, "edge_pct": 5.0, "book": "DraftKings", "stake_usd": 100.0
        }))["bet"]
        bet2 = json.loads(bet_tracker("log", {
            "game": "BOS vs MIA", "side": "BOS", "odds": 1.80, 
            "model_prob": 0.60, "edge_pct": 10.0, "book": "FanDuel", "stake_usd": 50.0
        }))["bet"]
        bet3 = json.loads(bet_tracker("log", {
            "game": "DEN vs PHX", "side": "PHX", "odds": 2.50, 
            "model_prob": 0.45, "edge_pct": 2.5, "book": "BetMGM", "stake_usd": 75.0
        }))["bet"]
        assert bet1 and bet2 and bet3, "Failed to log all bets"
        print("PASS: Bets logged successfully.")
    except Exception as e:
        print(f"FAIL: Logging bets failed - {e}")
        return

    # 2. Settle 2 bets (1 win, 1 loss)
    print("Test 2: Settling bets...")
    try:
        settle1 = json.loads(bet_tracker("settle", {"bet_id": bet1["bet_id"], "result": "won"}))["bet"]
        settle2 = json.loads(bet_tracker("settle", {"bet_id": bet2["bet_id"], "result": "lost"}))["bet"]
        assert settle1["status"] == "won" and settle2["status"] == "lost", "Failed to settle bets correctly"
        print("PASS: Bets settled successfully.")
    except Exception as e:
        print(f"FAIL: Settling bets failed - {e}")
        return

    # 3. Call pnl and verify the math is correct
    print("Test 3: Verifying P&L...")
    try:
        pnl_summary = json.loads(bet_tracker("pnl"))["summary"]
        
        # Expected values based on the logged and settled bets
        expected_total_bets = 2
        expected_wins = 1
        expected_losses = 1
        expected_total_staked = 100.0 + 50.0
        expected_profit_bet1 = 100.0 * 2.10 - 100.0 # 110.0
        expected_profit_bet2 = -50.0 # -50.0
        expected_total_profit = expected_profit_bet1 + expected_profit_bet2 # 60.0
        expected_roi_pct = (expected_total_profit / expected_total_staked) * 100
        expected_win_rate_pct = (expected_wins / (expected_wins + expected_losses)) * 100
        expected_current_bankroll = STARTING_BANKROLL + expected_total_profit

        assert pnl_summary["total_bets"] == expected_total_bets, f"Total bets mismatch: {pnl_summary['total_bets']} vs {expected_total_bets}"
        assert pnl_summary["wins"] == expected_wins, f"Wins mismatch: {pnl_summary['wins']} vs {expected_wins}"
        assert pnl_summary["losses"] == expected_losses, f"Losses mismatch: {pnl_summary['losses']} vs {expected_losses}"
        assert abs(pnl_summary["total_staked"] - expected_total_staked) < 0.01, f"Total staked mismatch: {pnl_summary['total_staked']} vs {expected_total_staked}"
        assert abs(pnl_summary["total_profit"] - expected_total_profit) < 0.01, f"Total profit mismatch: {pnl_summary['total_profit']} vs {expected_total_profit}"
        assert abs(pnl_summary["roi_pct"] - expected_roi_pct) < 0.01, f"ROI % mismatch: {pnl_summary['roi_pct']} vs {expected_roi_pct}"
        assert abs(pnl_summary["win_rate_pct"] - expected_win_rate_pct) < 0.01, f"Win rate % mismatch: {pnl_summary['win_rate_pct']} vs {expected_win_rate_pct}"
        assert abs(pnl_summary["current_bankroll"] - expected_current_bankroll) < 0.01, f"Current bankroll mismatch: {pnl_summary['current_bankroll']} vs {expected_current_bankroll}"
        
        print("PASS: P&L calculations are correct.")
    except Exception as e:
        print(f"FAIL: P&L verification failed - {e}")
        return

    # 4. Call streak and verify streak tracking
    print("Test 4: Verifying streak tracking...")
    try:
        streak_info = json.loads(bet_tracker("streak"))["streak"]
        # The last settled bet was a loss, so current streak should be 1 loss
        assert streak_info["current_streak_type"] == "lost", f"Streak type mismatch: {streak_info['current_streak_type']}"
        assert streak_info["current_streak_count"] == 1, f"Streak count mismatch: {streak_info['current_streak_count']}"
        assert streak_info["best_win_streak"] == 1, f"Best win streak mismatch: {streak_info['best_win_streak']}"
        assert streak_info["best_loss_streak"] == 1, f"Best loss streak mismatch: {streak_info['best_loss_streak']}"
        print("PASS: Streak tracking is correct.")
    except Exception as e:
        print(f"FAIL: Streak tracking failed - {e}")
        return

    # 5. Clean up test data
    print("Test 5: Cleaning up test data...")
    try:
        if LEDGER_FILE.exists():
            os.remove(LEDGER_FILE)
        assert not LEDGER_FILE.exists(), "Failed to remove ledger file"
        print("PASS: Test data cleaned up.")
    except Exception as e:
        print(f"FAIL: Cleanup failed - {e}")
        return

    print("Full Betting Pipeline Test Complete.")

if __name__ == "__main__":
    run_test_betting_pipeline()
