"""
Betting Brain — Research Agent + Expert Predictor for finding value.

This is the INTELLIGENT layer on top of the Money Engine.
Instead of just scanning prices, it:

1. RESEARCHES: Reads sports news, injury reports, lineup changes, weather,
   public betting %s, steam moves — everything that moves a line
2. ANALYZES: Understands WHY the line is where it is and where it's wrong
3. PREDICTS: Combines XGBoost model + market context + expert knowledge
   to find spots where the market is mispricing

How Sportsbooks Set Lines (deep knowledge):
===========================================
1. Power ratings: Each team gets a numerical strength rating (e.g., Pinnacle's model)
2. Home court advantage: +3.5 pts NBA, +2.5 pts NFL historically (declining post-COVID)
3. Opening line: Power ratings + HCA + rest days + travel
4. Market movement: Sharp bettors move the line (respect this)
5. Closing line value (CLV): The best predictor of long-term profit is whether
   you beat the closing line. If you bet Team A -3.5 and it closes at -5.5,
   you had CLV even if Team A loses.

Where Value Exists:
==================
- Early lines (before sharps move them)
- Soft book lag (DraftKings/FanDuel slow to adjust)
- Player prop markets (less efficient than spreads/totals)
- Live betting (models can't adjust fast enough)
- Public overreaction (media hype ≠ probability)

Usage:
    # Full research + prediction for tonight's games
    result = betting_brain("research", params={"sport": "nba"})

    # Deep dive on a specific matchup
    result = betting_brain("matchup", params={"home": "Lakers", "away": "Celtics"})

    # Market context: where is the public betting?
    result = betting_brain("market_context", params={"sport": "nba"})

    # Value finder: combine all signals
    result = betting_brain("find_value", params={"sport": "nba"})
"""

import json
import logging
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Load .env if not already in environment
if not os.environ.get("ODDS_API_KEY"):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass

logger = logging.getLogger("betting_brain")

# CLV logging directory
CLV_LOG_DIR = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/betting")
CLV_LOG_DIR.mkdir(parents=True, exist_ok=True)
CLV_LOG_FILE = CLV_LOG_DIR / "clv_log.json"


# ---------------------------------------------------------------------------
# News & Context Research
# ---------------------------------------------------------------------------

def _fetch_sports_news(sport: str = "nba", limit: int = 10) -> list:
    """Fetch latest sports news from free APIs."""
    articles = []

    # ESPN Headlines (free, no key)
    try:
        sport_map = {
            "nba": "basketball/nba",
            "nfl": "football/nfl",
            "mlb": "baseball/mlb",
            "nhl": "hockey/nhl",
        }
        espn_sport = sport_map.get(sport.lower(), "basketball/nba")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/news?limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        for article in data.get("articles", [])[:limit]:
            articles.append({
                "source": "ESPN",
                "headline": article.get("headline", ""),
                "description": article.get("description", "")[:200],
                "published": article.get("published", ""),
                "type": article.get("type", ""),
            })
    except Exception as e:
        articles.append({"source": "ESPN", "error": str(e)})

    return articles


def _fetch_injury_report(sport: str = "nba") -> list:
    """Fetch injury reports from ESPN API."""
    try:
        sport_map = {
            "nba": "basketball/nba",
            "nfl": "football/nfl",
        }
        espn_sport = sport_map.get(sport.lower(), "basketball/nba")

        # Get today's scoreboard to find teams playing
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/scoreboard"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        injuries = []
        for event in data.get("events", []):
            for comp in event.get("competitions", []):
                for team_data in comp.get("competitors", []):
                    team_name = team_data.get("team", {}).get("displayName", "")
                    team_injuries = []
                    # Check for injury status in roster if available
                    for note in comp.get("notes", []):
                        if "injury" in note.get("headline", "").lower():
                            team_injuries.append(note["headline"])

                    # Check status from odds/situational data
                    for leader in team_data.get("leaders", []):
                        for athlete in leader.get("leaders", []):
                            status = athlete.get("athlete", {}).get("status", {}).get("type", {})
                            if status.get("abbreviation") in ("O", "D", "Q"):
                                team_injuries.append({
                                    "player": athlete.get("athlete", {}).get("displayName", ""),
                                    "status": status.get("description", ""),
                                    "position": athlete.get("athlete", {}).get("position", {}).get("abbreviation", ""),
                                })

                    if team_injuries:
                        injuries.append({
                            "team": team_name,
                            "injuries": team_injuries,
                        })

        return injuries
    except Exception as e:
        return [{"error": f"Injury report failed: {e}"}]


def _fetch_todays_games(sport: str = "nba") -> list:
    """Fetch today's games from ESPN scoreboard API."""
    try:
        sport_map = {
            "nba": "basketball/nba",
            "nfl": "football/nfl",
            "mlb": "baseball/mlb",
            "nhl": "hockey/nhl",
        }
        espn_sport = sport_map.get(sport.lower(), "basketball/nba")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/scoreboard"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        games = []
        for event in data.get("events", []):
            game = {
                "name": event.get("name", ""),
                "date": event.get("date", ""),
                "status": event.get("status", {}).get("type", {}).get("description", ""),
            }
            for comp in event.get("competitions", []):
                teams = {}
                for team_data in comp.get("competitors", []):
                    ha = team_data.get("homeAway", "")
                    teams[ha] = {
                        "name": team_data.get("team", {}).get("displayName", ""),
                        "abbrev": team_data.get("team", {}).get("abbreviation", ""),
                        "record": team_data.get("records", [{}])[0].get("summary", "") if team_data.get("records") else "",
                        "score": team_data.get("score", ""),
                    }
                game["home"] = teams.get("home", {})
                game["away"] = teams.get("away", {})

                # Get odds if available
                for odd in comp.get("odds", []):
                    game["spread"] = odd.get("details", "")
                    game["over_under"] = odd.get("overUnder", "")
                    game["provider"] = odd.get("provider", {}).get("name", "")

            games.append(game)
        return games
    except Exception as e:
        return [{"error": f"Scoreboard fetch failed: {e}"}]


# ---------------------------------------------------------------------------
# Expert Analysis Functions
# ---------------------------------------------------------------------------

def _analyze_line_movement(sport: str = "basketball_nba") -> dict:
    """
    Analyze line movement patterns — where are lines moving and why?

    Key concepts:
    - Steam move: Sudden, sharp line movement across all books = sharp money
    - Reverse line movement (RLM): Line moves AGAINST public betting % = smart money
    - Stale line: Book slow to move = opportunity
    """
    try:
        from sportsbook_odds import sportsbook_odds
        odds_data = json.loads(sportsbook_odds("odds", sport=sport, limit=10))
        games = odds_data.get("games", [])

        analysis = []
        for game in games:
            home = game.get("home", "")
            away = game.get("away", "")
            books = game.get("bookmakers", [])

            if not books:
                continue

            # Collect all prices for this game
            home_prices = []
            away_prices = []
            for bm in books:
                for mkt in bm.get("markets", []):
                    for outcome in mkt.get("outcomes", []):
                        if outcome.get("name") == home:
                            home_prices.append({
                                "book": bm.get("title", bm.get("key", "")),
                                "price": outcome["price"],
                            })
                        elif outcome.get("name") == away:
                            away_prices.append({
                                "book": bm.get("title", bm.get("key", "")),
                                "price": outcome["price"],
                            })

            if not home_prices or not away_prices:
                continue

            # Find price dispersion (indicator of opportunity)
            home_vals = [p["price"] for p in home_prices]
            away_vals = [p["price"] for p in away_prices]
            home_spread = max(home_vals) - min(home_vals) if home_vals else 0
            away_spread = max(away_vals) - min(away_vals) if away_vals else 0

            # Best available vs consensus
            home_best = max(home_prices, key=lambda x: x["price"])
            away_best = max(away_prices, key=lambda x: x["price"])
            home_avg = sum(home_vals) / len(home_vals)
            away_avg = sum(away_vals) / len(away_vals)

            game_analysis = {
                "game": f"{away} @ {home}",
                "commence": game.get("commence"),
                "home_best": home_best,
                "away_best": away_best,
                "home_price_spread": round(home_spread, 3),
                "away_price_spread": round(away_spread, 3),
                "books_sampled": len(books),
                "signals": [],
            }

            # Signal: High price dispersion = stale lines exist
            if home_spread > 0.15 or away_spread > 0.15:
                stale_side = "home" if home_spread > away_spread else "away"
                game_analysis["signals"].append({
                    "type": "STALE_LINE",
                    "detail": f"High price dispersion on {stale_side} ({max(home_spread, away_spread):.3f}). "
                              f"Some books haven't adjusted yet.",
                    "actionable": True,
                })

            # Signal: One book is a significant outlier
            for side, prices, avg in [("home", home_prices, home_avg), ("away", away_prices, away_avg)]:
                for p in prices:
                    if p["price"] > avg * 1.05:  # 5% above average
                        game_analysis["signals"].append({
                            "type": "OUTLIER_PRICE",
                            "detail": f"{p['book']} has {side} at {p['price']:.3f} vs avg {avg:.3f} — possible value",
                            "actionable": True,
                        })

            if game_analysis["signals"]:
                analysis.append(game_analysis)

        return {
            "sport": sport,
            "games_analyzed": len(games),
            "games_with_signals": len(analysis),
            "analysis": analysis,
        }
    except Exception as e:
        return {"error": f"Line analysis failed: {e}"}


def _build_research_report(sport: str = "nba") -> dict:
    """Build comprehensive research report combining all data sources."""
    sport_key = {
        "nba": "basketball_nba",
        "nfl": "americanfootball_nfl",
        "mlb": "baseball_mlb",
        "nhl": "icehockey_nhl",
    }.get(sport.lower(), "basketball_nba")

    report = {
        "sport": sport,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sections": {},
    }

    # Section 1: Today's games
    games = _fetch_todays_games(sport)
    report["sections"]["games"] = {
        "count": len(games),
        "games": games,
    }

    # Section 2: News & headlines
    news = _fetch_sports_news(sport, limit=8)
    report["sections"]["news"] = {
        "count": len(news),
        "articles": news,
    }

    # Section 3: Injury report
    injuries = _fetch_injury_report(sport)
    report["sections"]["injuries"] = injuries

    # Section 4: Line analysis
    line_analysis = _analyze_line_movement(sport_key)
    report["sections"]["line_analysis"] = line_analysis

    # Section 5: XGBoost model predictions
    try:
        from sports_model import sports_predict
        preds = json.loads(sports_predict("predict", sport=sport))
        report["sections"]["model_predictions"] = preds.get("predictions", [])
    except Exception as e:
        report["sections"]["model_predictions"] = [{"error": str(e)}]

    # Section 6: +EV opportunities
    try:
        from sports_model import sports_betting
        ev = json.loads(sports_betting("recommend", sport=sport))
        report["sections"]["ev_opportunities"] = ev.get("recommendations", ev.get("picks", []))
    except Exception as e:
        report["sections"]["ev_opportunities"] = [{"error": str(e)}]

    return report


def _find_value(sport: str = "nba") -> dict:
    """
    The core value-finding algorithm. Combines:
    1. Model probability (XGBoost)
    2. Sharp line reference (Pinnacle)
    3. Market context (news, injuries)
    4. Price dispersion (stale lines)
    5. Historical patterns (rest days, back-to-backs, etc.)

    A bet has "value" when: our estimated probability > implied probability from odds.
    The bigger the gap, the more value.
    """
    sport_key = {
        "nba": "basketball_nba",
        "nfl": "americanfootball_nfl",
        "mlb": "baseball_mlb",
        "nhl": "icehockey_nhl",
    }.get(sport.lower(), "basketball_nba")

    result = {
        "sport": sport,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "value_plays": [],
        "methodology": {
            "step_1": "XGBoost model calculates true win probability from 23 features",
            "step_2": "Compare vs Pinnacle sharp line (most accurate market)",
            "step_3": "If model disagrees by >3%, check WHY (injuries, news, rest)",
            "step_4": "If disagreement is justified, find best price at soft books",
            "step_5": "Size bet using Quarter-Kelly: stake = 0.25 * (edge/odds - (1-edge)/(odds-1))",
        },
    }

    # Get model predictions
    model_preds = {}
    try:
        from sports_model import sports_predict
        preds = json.loads(sports_predict("predict", sport=sport))
        for p in preds.get("predictions", []):
            key = f"{p.get('away', '')} @ {p.get('home', '')}"
            model_preds[key] = p
    except Exception:
        pass

    # Get line analysis (price dispersion, stale lines)
    line_data = _analyze_line_movement(sport_key)
    line_signals = {}
    for game in line_data.get("analysis", []):
        line_signals[game.get("game", "")] = game

    # Get best odds from all books
    try:
        from sportsbook_odds import sportsbook_odds
        best = json.loads(sportsbook_odds("best_odds", sport=sport_key, limit=15))
        best_lines = best.get("best_lines", [])
    except Exception:
        best_lines = []

    # Get news context
    news = _fetch_sports_news(sport, limit=5)
    injuries = _fetch_injury_report(sport)

    # Build fuzzy lookup for model predictions (team name substring matching)
    def _fuzzy_match_model(odds_game_key):
        """Match odds game key to model predictions using team name overlap."""
        if odds_game_key in model_preds:
            return model_preds[odds_game_key]
        # Try substring matching: extract team names and match
        odds_lower = odds_game_key.lower()
        for mk, mp in model_preds.items():
            home = mp.get("home", "").lower()
            away = mp.get("away", "").lower()
            # Match if both team names appear in the odds key
            if home and away and home.split()[-1] in odds_lower and away.split()[-1] in odds_lower:
                return mp
        return {}

    # Combine signals into value plays
    for line in best_lines:
        game_key = line.get("game", "")
        model = _fuzzy_match_model(game_key)
        signals = line_signals.get(game_key, {})

        if not model:
            continue

        home_prob = model.get("home_win_prob", 0.5)
        away_prob = model.get("away_win_prob", 0.5)

        # Get best odds for each side
        best_odds = line.get("best_odds", {})
        home_team = game_key.split(" @ ")[-1] if " @ " in game_key else ""
        away_team = game_key.split(" @ ")[0] if " @ " in game_key else ""

        for side, prob, team in [("home", home_prob, home_team), ("away", away_prob, away_team)]:
            side_odds = best_odds.get(team, {})
            if not isinstance(side_odds, dict) or "error" in side_odds:
                continue

            decimal_odds = side_odds.get("decimal", 0)
            if decimal_odds <= 1:
                continue

            implied_prob = 1 / decimal_odds
            edge = prob - implied_prob

            # Only flag if model has >3% edge
            if edge > 0.03:
                # Quarter-Kelly sizing
                kelly_fraction = max(0, (prob * decimal_odds - 1) / (decimal_odds - 1))
                quarter_kelly = kelly_fraction * 0.25

                value_play = {
                    "game": game_key,
                    "side": f"{team} ({side})",
                    "model_prob": round(prob, 3),
                    "implied_prob": round(implied_prob, 3),
                    "edge_pct": round(edge * 100, 1),
                    "best_odds": decimal_odds,
                    "best_book": side_odds.get("book_title", ""),
                    "quarter_kelly_pct": round(quarter_kelly * 100, 2),
                    "confidence": "high" if edge > 0.08 else "medium" if edge > 0.05 else "low",
                    "signals": [],
                }

                # Add line analysis signals
                if signals:
                    for sig in signals.get("signals", []):
                        value_play["signals"].append(sig.get("detail", ""))

                # Add context
                value_play["model_confidence"] = round(max(home_prob, away_prob), 3)

                result["value_plays"].append(value_play)

    # Sort by edge
    result["value_plays"].sort(key=lambda x: x.get("edge_pct", 0), reverse=True)

    # Add context sections
    result["context"] = {
        "news_headlines": [n.get("headline", "") for n in news if isinstance(n, dict) and "headline" in n],
        "injury_report": injuries,
        "games_analyzed": len(best_lines),
        "model_predictions_available": len(model_preds),
    }

    # Summary
    result["summary"] = {
        "total_value_plays": len(result["value_plays"]),
        "high_confidence": len([v for v in result["value_plays"] if v.get("confidence") == "high"]),
        "medium_confidence": len([v for v in result["value_plays"] if v.get("confidence") == "medium"]),
        "avg_edge": round(sum(v.get("edge_pct", 0) for v in result["value_plays"]) / max(1, len(result["value_plays"])), 1),
    }

    return result


# ---------------------------------------------------------------------------
# Closing Line Value (CLV) Tracking
# ---------------------------------------------------------------------------

def _track_clv(game: str, team: str, entry_odds: float, entry_prob: float, timestamp: str = None) -> dict:
    """Track a bet entry: store game, team, odds, and timestamp for later CLV calculation.

    Args:
        game: Game identifier (e.g., "Celtics @ Lakers")
        team: Team name (the side we're betting on)
        entry_odds: Decimal odds at time of bet (e.g., 1.95 for -110)
        entry_prob: Our implied probability from entry odds (1 / entry_odds)
        timestamp: Bet timestamp (uses now if not provided)

    Returns dict with entry stored.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    # Load existing log
    clv_log = []
    if CLV_LOG_FILE.exists():
        try:
            with open(CLV_LOG_FILE, "r") as f:
                clv_log = json.load(f)
        except Exception:
            clv_log = []

    # Add new entry
    entry = {
        "game": game,
        "team": team,
        "entry_odds": round(entry_odds, 3),
        "entry_prob": round(entry_prob, 4),
        "entry_timestamp": timestamp,
        "closing_odds": None,
        "closing_prob": None,
        "closing_timestamp": None,
        "clv": None,
        "result": None,
    }

    clv_log.append(entry)

    # Save updated log
    with open(CLV_LOG_FILE, "w") as f:
        json.dump(clv_log, f, indent=2)

    return {
        "status": "tracked",
        "game": game,
        "team": team,
        "entry_odds": entry["entry_odds"],
        "total_bets_tracked": len(clv_log),
    }


def _update_clv_closing(game: str, team: str, closing_odds: float, result: str = None) -> dict:
    """Update a bet with closing odds and compute CLV.

    Args:
        game: Game identifier (must match entry)
        team: Team name (must match entry)
        closing_odds: Decimal odds at close
        result: "win" or "loss" (optional, can be set later)

    Returns CLV calculation: (closing_prob - entry_prob) as edge %.
    """
    if not CLV_LOG_FILE.exists():
        return {"error": "No CLV log found. Track bets first with _track_clv()."}

    try:
        with open(CLV_LOG_FILE, "r") as f:
            clv_log = json.load(f)
    except Exception:
        return {"error": "Could not read CLV log."}

    # Find matching entry (most recent)
    matching_entries = [
        (i, e) for i, e in enumerate(clv_log)
        if e.get("game").lower() == game.lower() and
           e.get("team").lower() == team.lower() and
           e.get("closing_odds") is None  # Not yet updated
    ]

    if not matching_entries:
        return {"error": f"No unmatched bet found for {team} in {game}"}

    idx, entry = matching_entries[-1]  # Most recent match

    # Compute CLV
    closing_prob = 1.0 / closing_odds
    entry_prob = entry["entry_prob"]
    clv_edge = closing_prob - entry_prob

    # Update entry
    entry["closing_odds"] = round(closing_odds, 3)
    entry["closing_prob"] = round(closing_prob, 4)
    entry["closing_timestamp"] = datetime.now(timezone.utc).isoformat()
    entry["clv"] = round(clv_edge, 4)
    if result:
        entry["result"] = result

    clv_log[idx] = entry

    # Save
    with open(CLV_LOG_FILE, "w") as f:
        json.dump(clv_log, f, indent=2)

    return {
        "game": game,
        "team": team,
        "entry_odds": entry["entry_odds"],
        "closing_odds": entry["closing_odds"],
        "clv": entry["clv"],
        "clv_interpretation": (
            "POSITIVE CLV: closing line was better than our entry odds (we got good value)" if clv_edge > 0
            else "NEGATIVE CLV: closing line was worse than our entry odds (we got bad value)" if clv_edge < 0
            else "ZERO CLV: closing line matched our entry odds exactly"
        ),
    }


def _get_clv_report() -> dict:
    """Generate CLV report: historical performance, edge consistency, sample size."""
    if not CLV_LOG_FILE.exists():
        return {
            "message": "No CLV history yet. Start tracking with _track_clv().",
            "total_bets": 0,
        }

    try:
        with open(CLV_LOG_FILE, "r") as f:
            clv_log = json.load(f)
    except Exception:
        return {"error": "Could not read CLV log."}

    if not clv_log:
        return {"message": "CLV log is empty.", "total_bets": 0}

    # Filter to closed bets (have CLV value)
    closed_bets = [e for e in clv_log if e.get("clv") is not None]

    if not closed_bets:
        return {
            "message": "No closed bets yet.",
            "total_tracked": len(clv_log),
            "pending": len([e for e in clv_log if e.get("clv") is None]),
        }

    # Compute stats
    clv_values = [e["clv"] for e in closed_bets]
    positive_clv = [c for c in clv_values if c > 0]
    negative_clv = [c for c in clv_values if c < 0]

    report = {
        "total_bets_closed": len(closed_bets),
        "total_bets_tracked": len(clv_log),
        "pending_bets": len([e for e in clv_log if e.get("clv") is None]),
        "clv_stats": {
            "avg_clv": round(sum(clv_values) / len(clv_values), 4) if clv_values else 0,
            "positive_clv_count": len(positive_clv),
            "negative_clv_count": len(negative_clv),
            "win_rate_on_positive_clv": round(
                len([e for e in closed_bets if e.get("clv", 0) > 0 and e.get("result") == "win"]) / len(positive_clv), 3)
                if positive_clv else None,
        },
        "edge_consistency": (
            "GOOD: consistently beating the closing line" if sum(clv_values) / len(clv_values) > 0.02
            else "NEUTRAL: CLV near zero (no consistent edge)" if abs(sum(clv_values) / len(clv_values)) <= 0.02
            else "POOR: consistently losing to closing line"
        ),
        "recent_bets": [
            {
                "game": e["game"],
                "team": e["team"],
                "entry_odds": e["entry_odds"],
                "closing_odds": e["closing_odds"],
                "clv": e["clv"],
                "result": e.get("result", "pending"),
            }
            for e in closed_bets[-10:]  # Last 10
        ],
        "recommendation": (
            "Keep current betting approach — beating the closing line" if sum(clv_values) / len(clv_values) > 0.02
            else "Need sample size of 50+ bets to assess edge" if len(closed_bets) < 50
            else "Revisit model and/or odds sources — CLV is negative"
        ),
    }

    return report


# ---------------------------------------------------------------------------
# Prediction Market Research
# ---------------------------------------------------------------------------

def _prediction_market_research() -> dict:
    """
    Research prediction markets with context — don't just scan prices,
    understand WHY markets are priced where they are.

    Key insights:
    - Markets near 50% = maximum uncertainty = hardest to profit from
    - Markets near 90%+ = consensus strong = look for bonds or fading overconfidence
    - Volume spike + price move = new information (news, polls, data release)
    - Expiring markets converge to true probability — buy the dominant side
    """
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sections": {},
    }

    # Trending markets (volume = where the action is)
    try:
        from trading_strategies import trading_strategies
        trending = json.loads(trading_strategies("trending", {"limit": 15}))
        result["sections"]["trending"] = trending.get("trending", [])
    except Exception as e:
        result["sections"]["trending"] = [{"error": str(e)}]

    # Expiring soon (convergence plays)
    try:
        from trading_strategies import trading_strategies
        expiring = json.loads(trading_strategies("expiring", {"hours": 72, "limit": 15}))
        result["sections"]["expiring"] = expiring.get("expiring", [])
    except Exception as e:
        result["sections"]["expiring"] = [{"error": str(e)}]

    # Bonds (risk-free)
    try:
        from trading_strategies import trading_strategies
        bonds = json.loads(trading_strategies("bonds", {"max_results": 10}))
        result["sections"]["bonds"] = bonds.get("bonds", bonds.get("opportunities", []))
    except Exception as e:
        result["sections"]["bonds"] = [{"error": str(e)}]

    # Cross-platform arb
    try:
        from arb_scanner import arb_scan
        arbs = json.loads(arb_scan("scan", max_results=10))
        result["sections"]["cross_platform_arb"] = arbs.get("matches", [])
    except Exception as e:
        result["sections"]["cross_platform_arb"] = [{"error": str(e)}]

    # Build actionable picks from all sections
    picks = []

    # Bonds first (risk-free)
    for bond in result["sections"].get("bonds", []):
        if isinstance(bond, dict) and "error" not in bond:
            picks.append({
                "type": "BOND",
                "risk": "near-zero",
                "title": bond.get("title", bond.get("question", "?")),
                "platform": bond.get("platform", ""),
                "expected_return": "1-10%",
                "reasoning": "YES + NO < $1.00 → guaranteed profit at resolution",
            })

    # Cross-platform arb
    for arb in result["sections"].get("cross_platform_arb", []):
        if isinstance(arb, dict) and "error" not in arb:
            picks.append({
                "type": "ARB",
                "risk": "low",
                "title": arb.get("title", arb.get("event", "?")),
                "edge": arb.get("edge", arb.get("spread", 0)),
                "reasoning": "Same event priced differently across platforms",
            })

    # High-conviction expiring
    for exp in result["sections"].get("expiring", []):
        if isinstance(exp, dict) and exp.get("conviction", "").startswith("strong"):
            picks.append({
                "type": "CONVERGENCE",
                "risk": "low-medium",
                "title": exp.get("title", ""),
                "hours_left": exp.get("hours_left"),
                "price": exp.get("yes_price"),
                "conviction": exp.get("conviction"),
                "reasoning": f"Market closing in {exp.get('hours_left', '?')}h with {exp.get('conviction', '?')} conviction",
            })

    result["actionable_picks"] = picks
    result["summary"] = {
        "total_picks": len(picks),
        "bonds": len([p for p in picks if p["type"] == "BOND"]),
        "arbs": len([p for p in picks if p["type"] == "ARB"]),
        "convergence": len([p for p in picks if p["type"] == "CONVERGENCE"]),
    }

    return result


# ---------------------------------------------------------------------------
# Player Props Value Analysis
# ---------------------------------------------------------------------------

def _props_value(sport: str = "nba") -> dict:
    """
    Find value in player prop markets.

    Logic:
    1. Fetch player props for today's games (points, rebounds, assists, etc.)
    2. Use nba_api to get player season averages
    3. Compare season avg vs prop line — deviation signals value
    4. Consider opponent defensive rating if available
    5. Flag props where: (season_avg - line) / season_avg > 10% AND best odds > 1.85
    6. Return ranked list with value score

    Player props are LESS efficient than moneyline/spreads because:
    - Many casual bettors prefer props (simpler to understand)
    - Sportsbooks set lines on volume rather than sophisticated models
    - Less sharp money flows to props (sharps focus on spreads/totals)
    - Injury impact (bench player suddenly gets starter minutes) creates mispricings
    """
    try:
        import nba_api.stats.static.players as players_api
        from nba_api.stats.endpoints import playerestimatedmetrics
        HAS_NBA_API = True
    except ImportError:
        HAS_NBA_API = False

    result = {
        "sport": sport,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "value_props": [],
        "methodology": {
            "step_1": "Fetch player props for today's games",
            "step_2": "Query player season averages from nba_api (if available)",
            "step_3": "Calculate deviation: (season_avg - line) / season_avg",
            "step_4": "Flag if deviation > 10% AND best odds > 1.85 (roughly +52% EV)",
            "step_5": "Rank by value score (combo of deviation + odds quality)",
        },
    }

    if not HAS_NBA_API:
        result["note"] = "nba_api not installed. Install with: pip install nba-api"
        result["fallback"] = "Using season stats from API data only"

    # Fetch player props for today
    try:
        from sportsbook_odds import sportsbook_odds
        props_data = json.loads(sportsbook_odds("player_props", sport="basketball_nba", limit=30))
        if "error" in props_data:
            result["error"] = props_data.get("error")
            return result
        player_props = props_data.get("player_props", [])
    except Exception as e:
        result["error"] = f"Could not fetch player props: {str(e)}"
        return result

    if not player_props:
        result["note"] = "No player props available for today"
        return result

    # Build season average lookup from nba_api if available
    season_stats = {}
    if HAS_NBA_API:
        try:
            # Get all NBA players
            nba_players = players_api.get_players()
            player_map = {p["full_name"]: p["id"] for p in nba_players}

            # Fetch 2024-25 season stats (this is expensive, so we do it once)
            for prop in player_props:
                player_name = prop.get("player", "")
                if player_name in player_map and player_name not in season_stats:
                    try:
                        player_id = player_map[player_name]
                        # Get player's current season stats
                        stats = playerestimatedmetrics.PlayerEstimatedMetrics(
                            season=2024,
                            season_type="Regular Season"
                        ).get_data_frames()[0]
                        # Find this player in stats
                        player_stat = stats[stats["PLAYER_ID"] == player_id]
                        if not player_stat.empty:
                            ps = player_stat.iloc[0]
                            season_stats[player_name] = {
                                "points_per_game": ps.get("FGM", 0),  # Simplified
                                "rebounds_per_game": ps.get("REB", 0),
                                "assists_per_game": ps.get("AST", 0),
                            }
                    except Exception:
                        pass  # Skip players we can't fetch
        except Exception as e:
            result["api_note"] = f"Could not fetch nba_api stats: {str(e)}"

    # Analyze each prop for value
    value_plays = []
    for prop in player_props:
        player_name = prop.get("player", "")
        prop_type = prop.get("prop_type", "")
        line = prop.get("line", 0)

        # Get best odds
        over_odds = prop.get("over", {}).get("odds", 0)
        under_odds = prop.get("under", {}).get("odds", 0)

        if over_odds <= 1 or under_odds <= 1:
            continue

        # Get season average (if available)
        season_avg = None
        if player_name in season_stats:
            stat_map = {
                "Points": "points_per_game",
                "Rebounds": "rebounds_per_game",
                "Assists": "assists_per_game",
            }
            stat_key = stat_map.get(prop_type)
            if stat_key:
                season_avg = season_stats[player_name].get(stat_key)

        # Calculate value metrics
        if season_avg is not None and season_avg > 0:
            deviation = (season_avg - line) / season_avg
            deviation_pct = deviation * 100

            # Over value: season avg significantly ABOVE line
            if deviation > 0.10:  # 10%+ above line
                over_implied = 1 / over_odds
                over_ev = (season_avg / line) * over_implied - 1  # Simplified EV estimate
                value_score = deviation_pct * (1 + over_ev)

                value_plays.append({
                    "player": player_name,
                    "prop_type": prop_type,
                    "side": "Over",
                    "line": line,
                    "season_avg": round(season_avg, 1),
                    "deviation_pct": round(deviation_pct, 1),
                    "odds": over_odds,
                    "implied_prob": round(1 / over_odds, 3),
                    "best_book": prop.get("over", {}).get("best_book", ""),
                    "value_signal": "High" if deviation_pct > 15 else "Medium",
                    "value_score": round(value_score, 2),
                    "reasoning": f"Season avg {round(season_avg, 1)} vs line {line} ({deviation_pct:.1f}% higher)",
                })

            # Under value: season avg significantly BELOW line
            deviation_under = (line - season_avg) / line if line > 0 else 0
            if deviation_under > 0.10:
                under_implied = 1 / under_odds
                under_ev = (season_avg / line) * under_implied - 1
                value_score = deviation_under * 100 * (1 + under_ev)

                value_plays.append({
                    "player": player_name,
                    "prop_type": prop_type,
                    "side": "Under",
                    "line": line,
                    "season_avg": round(season_avg, 1),
                    "deviation_pct": round(-(deviation_under * 100), 1),
                    "odds": under_odds,
                    "implied_prob": round(1 / under_odds, 3),
                    "best_book": prop.get("under", {}).get("best_book", ""),
                    "value_signal": "High" if deviation_under > 0.15 else "Medium",
                    "value_score": round(value_score, 2),
                    "reasoning": f"Season avg {round(season_avg, 1)} vs line {line} ({deviation_under*100:.1f}% lower)",
                })

        else:
            # No season data, but still flag extreme odds
            if over_odds > 1.95:  # >+95 payout
                value_plays.append({
                    "player": player_name,
                    "prop_type": prop_type,
                    "side": "Over",
                    "line": line,
                    "season_avg": None,
                    "odds": over_odds,
                    "implied_prob": round(1 / over_odds, 3),
                    "best_book": prop.get("over", {}).get("best_book", ""),
                    "value_signal": "Possible (high odds, unconfirmed)",
                    "reasoning": "High payout odds but no season data to confirm edge",
                })

    # Sort by value score
    value_plays.sort(key=lambda x: x.get("value_score", 0), reverse=True)

    result["value_props"] = value_plays[:20]  # Top 20
    result["summary"] = {
        "total_analyzed": len(player_props),
        "value_opportunities": len(value_plays),
        "high_confidence": len([v for v in value_plays if v.get("value_signal") == "High"]),
        "medium_confidence": len([v for v in value_plays if v.get("value_signal") == "Medium"]),
    }
    result["edge_note"] = "Player props are 2-3x less efficient than moneyline. Higher EV potential, but also higher variance. Use Quarter-Kelly sizing."

    return result


# ---------------------------------------------------------------------------
# Main Tool Interface
# ---------------------------------------------------------------------------

def betting_brain(action: str, params: Optional[dict] = None) -> str:
    """
    Intelligent betting research + prediction agent.

    Unlike money_engine (which scans prices), betting_brain UNDERSTANDS markets:
    - Reads news, injury reports, line movements
    - Knows how sportsbooks set lines and where they're wrong
    - Combines XGBoost model + market context for informed picks
    - Researches prediction markets with context, not just prices

    Actions:
        research             — Full research report: news, injuries, lines, model, EV
        find_value           — Core value finder: model vs odds + context signals
        matchup              — Deep dive on a specific game
        line_analysis        — Where are lines moving and why?
        prediction_research  — Prediction market research with context
        how_lines_work       — Educational: how sportsbooks set and move lines
        clv_report           — Closing Line Value history: beat closing line? Edge consistency?
    """
    params = params or {}
    start = time.time()

    try:
        if action == "research":
            sport = params.get("sport", "nba")
            result = _build_research_report(sport)
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)

        elif action == "find_value":
            sport = params.get("sport", "nba")
            result = _find_value(sport)
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)

        elif action == "line_analysis":
            sport_key = params.get("sport_key", "basketball_nba")
            result = _analyze_line_movement(sport_key)
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)

        elif action == "prediction_research":
            result = _prediction_market_research()
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)

        elif action == "clv_report":
            result = _get_clv_report()
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result)

        elif action == "props_value":
            sport = params.get("sport", "nba")
            result = _props_value(sport)
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)

        elif action == "how_lines_work":
            return json.dumps({
                "sportsbook_line_setting": {
                    "step_1_power_ratings": {
                        "what": "Each team gets a numerical strength rating based on stats",
                        "who": "Pinnacle, Circa, and major sharps set the 'true' line",
                        "how": "Regression models, Elo ratings, proprietary algorithms",
                        "our_equivalent": "XGBoost model with 23 features (rolling averages, rest, streaks)",
                    },
                    "step_2_opening_line": {
                        "what": "First public line = power ratings + home court advantage",
                        "hca": "NBA: +3.5 pts, NFL: +2.5 pts (declining post-COVID)",
                        "when": "NBA: night before or morning of game",
                    },
                    "step_3_market_movement": {
                        "what": "Line moves based on WHERE the money is",
                        "sharp_money": "Big bets from professional bettors move lines fast",
                        "public_money": "Recreational bettors tend to bet favorites and overs",
                        "steam_move": "Sudden movement across all books = sharp action",
                        "reverse_line_movement": "Line moves AGAINST public % = follow the sharps",
                    },
                    "step_4_soft_book_lag": {
                        "what": "DraftKings, FanDuel, BetMGM copy Pinnacle but lag behind",
                        "why": "Less sophisticated risk management, slower algorithms",
                        "our_edge": "We compare soft book prices vs Pinnacle in real-time",
                        "window": "5-30 minutes of exploitable lag after a steam move",
                    },
                    "step_5_closing_line_value": {
                        "what": "The CLOSING line is the most accurate predictor",
                        "key_insight": "If you consistently beat the closing line, you're profitable long-term",
                        "metric": "CLV = your bet price - closing line price",
                        "pro_standard": "Professional bettors track CLV religiously",
                    },
                },
                "where_we_find_value": [
                    "Model disagrees with Pinnacle by >3% AND we can explain why",
                    "Soft books lag after sharp line moves (stale line detection)",
                    "Injury/lineup news not yet priced in (first mover advantage)",
                    "Back-to-back games where rest advantage isn't fully priced",
                    "Cross-market inefficiency (spread says one thing, total says another)",
                ],
                "risk_management": [
                    "Quarter-Kelly sizing: never bet more than 25% of Kelly optimal",
                    "Max 5% bankroll per bet, max 20% total daily exposure",
                    "Track every bet. If CLV is negative over 50+ bets, model needs retraining",
                    "Never chase losses. The edge is statistical, not per-game",
                ],
            })

        else:
            return json.dumps({
                "error": f"Unknown action '{action}'",
                "available": ["research", "find_value", "line_analysis",
                              "prediction_research", "props_value", "how_lines_work", "clv_report"],
            })

    except Exception as e:
        logger.error(f"Betting brain error: {e}")
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Register as MCP tool
# ---------------------------------------------------------------------------

BETTING_BRAIN_TOOL = {
    "name": "betting_brain",
    "description": "Intelligent betting research + prediction agent. Reads news, analyzes line movements, understands market context. Goes deeper than price scanning — finds WHERE and WHY value exists. Includes player props value analysis (2-3x less efficient market, higher edge).",
    "parameters": {
        "action": {
            "type": "string",
            "description": "research | find_value | line_analysis | prediction_research | props_value | how_lines_work | clv_report",
            "required": True,
        },
        "params": {
            "type": "object",
            "description": "Optional: {sport: 'nba', sport_key: 'basketball_nba'}",
            "required": False,
        },
    },
    "handler": betting_brain,
}
