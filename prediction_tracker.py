"""
Prediction Tracker — Log predictions, grade results, track accuracy/ROI

Stores daily prediction files in data/predictions/{date}.json.
Integrates with sports_model.py (predict + betting) and nba_api (actual scores).
"""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PREDICTIONS_DIR = Path("./data/predictions")
PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)


def _send_telegram_sync(text: str) -> None:
    """Synchronous wrapper for async send_telegram function."""
    try:
        from alerts import send_telegram
        asyncio.run(send_telegram(text))
    except Exception:
        pass  # Silently handle any telegram errors


def prediction_tracker(action: str, date: str = "", bankroll: float = 100.0) -> str:
    """Track sports predictions and results.

    Actions:
        log       — Save today's predictions + recommendations to disk
        check     — Grade a past day's predictions against actual results
        record    — Show overall track record across all graded days
        yesterday — Grade yesterday + show results
    """
    try:
        if action == "log":
            return _log_predictions(date, bankroll)
        elif action == "check":
            return _check_results(date)
        elif action == "record":
            return _get_record()
        elif action == "yesterday":
            return _check_yesterday()
        else:
            return json.dumps({"error": f"Unknown action: {action}. Use: log, check, record, yesterday"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════
# LOG — Save today's predictions before games start
# ═══════════════════════════════════════════════════════════════

def _log_predictions(date: str, bankroll: float) -> str:
    """Call sports_predict + sports_betting, save results to disk."""
    from sports_model import sports_predict, sports_betting

    target_date = date or datetime.now().strftime("%Y-%m-%d")

    # Get predictions
    pred_raw = sports_predict(action="predict", date=date)
    pred_data = json.loads(pred_raw)

    if "error" in pred_data:
        return json.dumps({"error": f"Failed to get predictions: {pred_data['error']}"})

    predictions = pred_data.get("predictions", [])
    if not predictions:
        return json.dumps({"message": "No games scheduled", "date": target_date})

    # Get betting recommendations
    bet_raw = sports_betting(action="recommend", bankroll=bankroll)
    bet_data = json.loads(bet_raw)
    recommendations = bet_data.get("recommendations", [])

    # Deduplicate predictions by (home, away) matchup
    seen_preds = set()
    deduped_predictions = []
    for p in predictions:
        if "error" in p:
            continue
        key = (p.get("home", ""), p.get("away", ""))
        if key in seen_preds:
            continue
        seen_preds.add(key)
        deduped_predictions.append({
            "home": p.get("home", ""),
            "away": p.get("away", ""),
            "predicted_winner": p.get("predicted_winner", ""),
            "home_win_prob": p.get("home_win_prob", 0),
            "away_win_prob": p.get("away_win_prob", 0),
            "confidence": p.get("confidence", 0),
        })

    # Deduplicate recommendations by (game, bet_on)
    seen_recs = set()
    deduped_recommendations = []
    for r in recommendations:
        key = (r.get("game", ""), r.get("bet_on", ""))
        if key in seen_recs:
            continue
        seen_recs.add(key)
        deduped_recommendations.append({
            "game": r.get("game", ""),
            "bet_on": r.get("bet_on", ""),
            "odds": r.get("best_odds", r.get("odds", 0)),
            "model_prob": r.get("model_prob", 0),
            "ev_pct": r.get("ev_pct", 0),
            "bet_size": r.get("bet_size", r.get("kelly_bet", 0)),
            "expected_profit": r.get("expected_profit", 0),
        })

    # Build log entry
    entry = {
        "date": target_date,
        "logged_at": datetime.now(timezone.utc).isoformat() + "Z",
        "predictions": deduped_predictions,
        "recommendations": deduped_recommendations,
    }

    # Save — idempotent, overwrites same day
    filepath = PREDICTIONS_DIR / f"{target_date}.json"
    with open(filepath, "w") as f:
        json.dump(entry, f, indent=2)

    # Send Telegram notification with prediction summary
    num_games = len(entry["predictions"])
    num_bets = len(entry["recommendations"])

    if num_games > 0:
        # Find the top pick by confidence
        top_pick = max(entry["predictions"], key=lambda p: p.get("confidence", 0))
        top_confidence = top_pick.get("confidence", 0)
        top_team = top_pick.get("predicted_winner", "N/A")

        # Find the biggest edge (highest EV)
        biggest_edge = None
        biggest_edge_ev = 0
        for rec in entry["recommendations"]:
            ev_pct = rec.get("ev_pct", 0)
            if ev_pct > biggest_edge_ev:
                biggest_edge_ev = ev_pct
                biggest_edge = rec.get("bet_on", "N/A")

        edge_str = f"\nBiggest edge: {biggest_edge} (+{biggest_edge_ev:.1f}% EV)" if biggest_edge else ""

        tg_message = (
            f"🏀 *NBA Predictions Logged* ({target_date})\n"
            f"{num_games} games, {num_bets} bets\n"
            f"Top pick: {top_team} ({top_confidence:.1f}% confidence){edge_str}"
        )
        _send_telegram_sync(tg_message)

    return json.dumps({
        "status": "logged",
        "date": target_date,
        "games": len(entry["predictions"]),
        "bets": len(entry["recommendations"]),
        "file": str(filepath),
    })


# ═══════════════════════════════════════════════════════════════
# CHECK — Grade predictions against actual NBA scores
# ═══════════════════════════════════════════════════════════════

def _get_game_results(date_str: str) -> list:
    """Fetch actual NBA game results for a given date using nba_api."""
    from nba_api.stats.endpoints import scoreboardv2

    # Parse date and format for NBA API (MM/DD/YYYY)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    nba_date = dt.strftime("%m/%d/%Y")

    time.sleep(0.6)  # Rate limit: NBA.com allows ~2 req/sec
    sb = scoreboardv2.ScoreboardV2(game_date=nba_date, timeout=15)

    game_header = sb.game_header.get_data_frame()
    line_score = sb.line_score.get_data_frame()

    if game_header.empty:
        return []

    results = []
    for _, game in game_header.iterrows():
        game_id = game["GAME_ID"]
        game_status = game.get("GAME_STATUS_ID", 0)

        # Only process completed games (status 3 = Final)
        if game_status != 3:
            continue

        game_lines = line_score[line_score["GAME_ID"] == game_id]
        if len(game_lines) < 2:
            continue

        home_line = game_lines[game_lines["TEAM_ID"] == game["HOME_TEAM_ID"]].iloc[0]
        away_line = game_lines[game_lines["TEAM_ID"] == game["VISITOR_TEAM_ID"]].iloc[0]

        home_pts = int(home_line.get("PTS", 0) or 0)
        away_pts = int(away_line.get("PTS", 0) or 0)

        home_name = f"{home_line.get('TEAM_CITY_NAME', '')} {home_line.get('TEAM_NAME', '')}".strip()
        away_name = f"{away_line.get('TEAM_CITY_NAME', '')} {away_line.get('TEAM_NAME', '')}".strip()

        results.append({
            "home_team": home_name,
            "away_team": away_name,
            "home_score": home_pts,
            "away_score": away_pts,
            "winner": home_name if home_pts > away_pts else away_name,
        })

    return results


def _match_team(pred_name: str, result_name: str) -> bool:
    """Fuzzy match team names — matches if at least 2 words overlap."""
    pred_words = set(pred_name.lower().split())
    result_words = set(result_name.lower().split())
    return len(pred_words & result_words) >= 2


def _check_results(date: str) -> str:
    """Grade predictions against actual game results."""
    target_date = date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    filepath = PREDICTIONS_DIR / f"{target_date}.json"

    if not filepath.exists():
        return json.dumps({"error": f"No predictions logged for {target_date}. Run action=log first."})

    with open(filepath) as f:
        entry = json.load(f)

    # Fetch actual results from NBA API
    actual_results = _get_game_results(target_date)

    if not actual_results:
        return json.dumps({
            "error": f"No completed games found for {target_date}. Games may not have finished yet.",
            "date": target_date,
        })

    # Dedup predictions on load (safety net for pre-fix files)
    seen_pred_keys = set()
    deduped_preds = []
    for p in entry.get("predictions", []):
        key = (p.get("home", ""), p.get("away", ""))
        if key not in seen_pred_keys:
            seen_pred_keys.add(key)
            deduped_preds.append(p)

    # Grade predictions
    graded_predictions = []
    picks_correct = 0
    picks_total = 0

    for pred in deduped_preds:
        home = pred.get("home", "")
        away = pred.get("away", "")
        predicted_winner = pred.get("predicted_winner", "")

        # Find matching result
        matched = None
        for result in actual_results:
            if _match_team(home, result["home_team"]) and _match_team(away, result["away_team"]):
                matched = result
                break
            # Try reverse match
            if _match_team(home, result["away_team"]) and _match_team(away, result["home_team"]):
                matched = result
                break

        if matched:
            correct = _match_team(predicted_winner, matched["winner"])
            picks_total += 1
            if correct:
                picks_correct += 1

            graded_predictions.append({
                "home": home,
                "away": away,
                "predicted_winner": predicted_winner,
                "actual_winner": matched["winner"],
                "home_score": matched["home_score"],
                "away_score": matched["away_score"],
                "correct": correct,
            })
        else:
            graded_predictions.append({
                "home": home,
                "away": away,
                "predicted_winner": predicted_winner,
                "actual_winner": "UNMATCHED",
                "home_score": 0,
                "away_score": 0,
                "correct": None,
            })

    # Grade bets
    graded_bets = []
    bets_won = 0
    bets_total = 0
    total_wagered = 0.0
    total_profit = 0.0

    seen_bet_keys = set()  # Dedup graded bets by (game, bet_on)
    for rec in entry.get("recommendations", []):
        bet_on = rec.get("bet_on", "")
        game_name = rec.get("game", "")
        odds = rec.get("odds", 0)
        bet_size = rec.get("bet_size", 0)

        # Skip duplicate bet entries
        bet_key = (game_name, bet_on)
        if bet_key in seen_bet_keys:
            continue
        seen_bet_keys.add(bet_key)

        # Find the specific game this bet belongs to, then check winner
        won = None
        for result in actual_results:
            # Match by BOTH teams in the game, not just the bet team
            game_teams_match = (
                (_match_team(bet_on, result["home_team"]) or _match_team(bet_on, result["away_team"])) and
                (game_name == "" or any(
                    _match_team(t, result["home_team"]) or _match_team(t, result["away_team"])
                    for t in game_name.replace(" @ ", " vs ").replace(" vs ", "|").split("|")
                ))
            )
            if game_teams_match:
                won = _match_team(bet_on, result["winner"])
                break

        if won is not None:
            bets_total += 1
            total_wagered += bet_size

            if won:
                bets_won += 1
                profit = bet_size * (odds - 1)
            else:
                profit = -bet_size

            total_profit += profit

            graded_bets.append({
                "game": rec.get("game", ""),
                "bet_on": bet_on,
                "odds": odds,
                "bet_size": round(bet_size, 2),
                "won": won,
                "profit": round(profit, 2),
            })

    # Build summary
    summary = {
        "picks_correct": picks_correct,
        "picks_total": picks_total,
        "picks_pct": round(picks_correct / picks_total * 100, 1) if picks_total > 0 else 0,
        "bets_won": bets_won,
        "bets_total": bets_total,
        "total_wagered": round(total_wagered, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round(total_profit / total_wagered * 100, 1) if total_wagered > 0 else 0,
    }

    # Save results back to file
    entry["results"] = {
        "graded_at": datetime.now(timezone.utc).isoformat() + "Z",
        "predictions": graded_predictions,
        "bets": graded_bets,
        "summary": summary,
    }

    with open(filepath, "w") as f:
        json.dump(entry, f, indent=2)

    # Send Telegram notification with results
    picks_correct = summary.get("picks_correct", 0)
    picks_total = summary.get("picks_total", 0)
    bets_won = summary.get("bets_won", 0)
    bets_total = summary.get("bets_total", 0)
    total_profit = summary.get("total_profit", 0)
    roi_pct = summary.get("roi_pct", 0)

    picks_pct = round(picks_correct / picks_total * 100, 1) if picks_total > 0 else 0

    tg_message = (
        f"📊 *NBA Results* ({target_date})\n"
        f"Picks: {picks_correct}/{picks_total} ({picks_pct}%)\n"
        f"Bets: {bets_won}/{bets_total} won\n"
        f"Profit: ${total_profit:+.2f} (ROI: {roi_pct:+.1f}%)"
    )
    _send_telegram_sync(tg_message)

    return json.dumps({
        "date": target_date,
        "summary": summary,
        "predictions": graded_predictions,
        "bets": graded_bets,
    })


# ═══════════════════════════════════════════════════════════════
# YESTERDAY — Shortcut: grade yesterday + return results
# ═══════════════════════════════════════════════════════════════

def _check_yesterday() -> str:
    """Grade yesterday's predictions and return results."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return _check_results(yesterday)


# ═══════════════════════════════════════════════════════════════
# RECORD — Aggregate track record across all graded days
# ═══════════════════════════════════════════════════════════════

def _get_record() -> str:
    """Aggregate track record across all graded prediction files."""
    files = sorted(PREDICTIONS_DIR.glob("*.json"))

    if not files:
        return json.dumps({"message": "No prediction files found. Run action=log first."})

    total_picks = 0
    total_correct = 0
    total_bets = 0
    total_bets_won = 0
    total_wagered = 0.0
    total_profit = 0.0
    days = []
    ungraded = []

    for fp in files:
        with open(fp) as fh:
            entry = json.load(fh)

        date = entry.get("date", fp.stem)
        results = entry.get("results")

        if not results:
            ungraded.append(date)
            continue

        summary = results.get("summary", {})
        day_info = {
            "date": date,
            "picks": f"{summary.get('picks_correct', 0)}/{summary.get('picks_total', 0)}",
            "picks_pct": summary.get("picks_pct", 0),
            "bets": f"{summary.get('bets_won', 0)}/{summary.get('bets_total', 0)}",
            "wagered": summary.get("total_wagered", 0),
            "profit": summary.get("total_profit", 0),
            "roi_pct": summary.get("roi_pct", 0),
        }
        days.append(day_info)

        total_picks += summary.get("picks_total", 0)
        total_correct += summary.get("picks_correct", 0)
        total_bets += summary.get("bets_total", 0)
        total_bets_won += summary.get("bets_won", 0)
        total_wagered += summary.get("total_wagered", 0)
        total_profit += summary.get("total_profit", 0)

    best_day = max(days, key=lambda d: d["profit"]) if days else None
    worst_day = min(days, key=lambda d: d["profit"]) if days else None

    record = {
        "total_days_graded": len(days),
        "total_days_logged": len(files),
        "ungraded_dates": ungraded,
        "overall": {
            "picks_correct": total_correct,
            "picks_total": total_picks,
            "picks_pct": round(total_correct / total_picks * 100, 1) if total_picks > 0 else 0,
            "bets_won": total_bets_won,
            "bets_total": total_bets,
            "bets_pct": round(total_bets_won / total_bets * 100, 1) if total_bets > 0 else 0,
            "total_wagered": round(total_wagered, 2),
            "total_profit": round(total_profit, 2),
            "roi_pct": round(total_profit / total_wagered * 100, 1) if total_wagered > 0 else 0,
        },
        "best_day": best_day,
        "worst_day": worst_day,
        "daily_breakdown": days,
    }

    return json.dumps(record)
