"""
Sportsbook Odds Scanner — Phase 3: Live odds aggregation + arb/EV detection

Uses The Odds API (api.the-odds-api.com/v4) to pull live odds from 200+ sportsbooks.
Compares soft book odds vs Pinnacle's sharp line to find +EV bets.
Pattern follows polymarket_trading.py (urllib.request, JSON string returns).

Env: ODDS_API_KEY from the-odds-api.com (free: 500 req/mo)
"""

import json
import os
import urllib.request
import urllib.parse
from typing import Optional

# Load .env if not already in environment
if not os.environ.get("ODDS_API_KEY"):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

# Track remaining quota from API response headers
_quota = {"remaining": None, "used": None}


def _odds_api_get(endpoint: str, params: dict = None, timeout: int = 15) -> dict:
    """GET request to The Odds API with apiKey injection."""
    if not ODDS_API_KEY:
        return {"error": "ODDS_API_KEY not set. Sign up at the-odds-api.com (free: 500 req/mo)"}

    url = f"{ODDS_API_BASE}{endpoint}"
    p = {"apiKey": ODDS_API_KEY}
    if params:
        p.update({k: v for k, v in params.items() if v is not None})
    url += "?" + urllib.parse.urlencode(p)

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Track quota from headers
            rem = resp.headers.get("x-requests-remaining")
            used = resp.headers.get("x-requests-used")
            if rem is not None:
                _quota["remaining"] = int(rem)
            if used is not None:
                _quota["used"] = int(used)
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if e.fp else ""
        return {"error": f"Odds API {e.code}: {body}"}
    except Exception as e:
        return {"error": f"Odds API request failed: {str(e)[:500]}"}


# ═══════════════════════════════════════════════════════════════
# Odds math helpers
# ═══════════════════════════════════════════════════════════════

def _american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds > 0:
        return 1 + odds / 100
    else:
        return 1 + 100 / abs(odds)


def _decimal_to_implied(odds: float) -> float:
    """Convert decimal odds to implied probability (0-1)."""
    if odds <= 0:
        return 0.0
    return 1.0 / odds


def _implied_to_american(prob: float) -> int:
    """Convert implied probability (0-1) to American odds."""
    if prob <= 0 or prob >= 1:
        return 0
    if prob > 0.5:
        return int(-100 * prob / (1 - prob))
    else:
        return int(100 * (1 - prob) / prob)


def _calculate_arb(outcome_probs: list[float]) -> dict:
    """Check if implied probabilities sum < 100% (arbitrage opportunity).

    Returns arb info including profit percentage.
    """
    total = sum(outcome_probs)
    is_arb = total < 1.0
    profit_pct = (1.0 / total - 1.0) * 100 if total > 0 and is_arb else 0.0
    return {
        "is_arb": is_arb,
        "total_implied": round(total, 6),
        "overround_pct": round((total - 1.0) * 100, 2),
        "profit_pct": round(profit_pct, 2),
    }


def _calculate_ev(model_prob: float, decimal_odds: float) -> float:
    """Expected value: EV = (prob * payout) - 1."""
    return model_prob * decimal_odds - 1.0


def _kelly_fraction(prob: float, decimal_odds: float, fraction: float = 0.25) -> float:
    """Quarter-Kelly bet sizing: f* = fraction * (bp - q) / b
    where b = decimal_odds - 1, p = prob, q = 1 - prob.
    """
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - prob
    full_kelly = (b * prob - q) / b
    if full_kelly <= 0:
        return 0.0
    return fraction * full_kelly


def _find_best_odds(bookmakers: list, outcome_name: str) -> dict:
    """Find the best price across all bookmakers for a given outcome."""
    best = {"price": -999999, "book": None, "decimal": 0.0}
    for bm in bookmakers:
        for market in bm.get("markets", []):
            for outcome in market.get("outcomes", []):
                if outcome.get("name", "").lower() == outcome_name.lower():
                    price = outcome.get("price", 0)
                    # Validate decimal odds are in sane range (1.01 to 50.0)
                    # Anything above 50 is likely a data error or exchange glitch
                    if isinstance(price, (int, float)) and 1.01 <= price <= 50.0 and price > best["price"]:
                        best = {
                            "price": price,
                            "book": bm.get("key", "unknown"),
                            "book_title": bm.get("title", "Unknown"),
                            "decimal": price,
                            "implied_prob": round(_decimal_to_implied(price), 4),
                        }
    return best if best["book"] else {"error": f"No odds found for '{outcome_name}'"}


def _get_pinnacle_odds(bookmakers: list) -> Optional[dict]:
    """Extract Pinnacle's odds as the sharp reference line."""
    for bm in bookmakers:
        if bm.get("key") == "pinnacle":
            return bm
    return None


def _parse_prop_type(market_key: str) -> Optional[str]:
    """Parse Odds API player prop market key to readable format."""
    prop_map = {
        "player_points": "Points",
        "player_rebounds": "Rebounds",
        "player_assists": "Assists",
        "player_threes": "Three Pointers",
        "player_blocks": "Blocks",
        "player_steals": "Steals",
        "player_points_rebounds_assists": "Points+Rebounds+Assists",
    }
    return prop_map.get(market_key)


# ═══════════════════════════════════════════════════════════════
# TOOL 1: sportsbook_odds — Live odds from 200+ bookmakers
# ═══════════════════════════════════════════════════════════════

def sportsbook_odds(action: str, sport: str = "", market: str = "h2h",
                    bookmakers: str = "", event_id: str = "",
                    limit: int = 10) -> str:
    """Get live sportsbook odds from The Odds API.

    Actions:
        sports     — List available sports (in-season and upcoming)
        odds       — Live odds from all US bookmakers for a sport
        event      — All markets for one specific game
        compare    — Side-by-side bookmaker comparison
        best_odds  — Best line for each outcome across all books
        player_props — Player prop odds (pts, reb, ast, etc.) for today's games

    Note: Player props use 2-3x more API quota than moneyline. Free tier = 500 req/mo.
    """
    try:
        if action == "sports":
            data = _odds_api_get("/sports")
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)
            # Filter to in-season sports
            in_season = [s for s in data if s.get("active", False)] if isinstance(data, list) else data
            return json.dumps({
                "sports": in_season[:limit] if isinstance(in_season, list) else in_season,
                "total_active": len(in_season) if isinstance(in_season, list) else 0,
                "quota": _quota,
            })

        if not sport:
            return json.dumps({"error": "sport required. Use action=sports to list available sports. Common: basketball_nba, americanfootball_nfl, baseball_mlb, icehockey_nhl"})

        if action == "odds":
            params = {
                "regions": "us",
                "markets": market,
                "oddsFormat": "decimal",
            }
            if bookmakers:
                params["bookmakers"] = bookmakers
            data = _odds_api_get(f"/sports/{sport}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)
            games = data[:limit] if isinstance(data, list) else data
            result = []
            for game in (games if isinstance(games, list) else []):
                result.append({
                    "id": game.get("id"),
                    "home": game.get("home_team"),
                    "away": game.get("away_team"),
                    "commence": game.get("commence_time"),
                    "bookmaker_count": len(game.get("bookmakers", [])),
                    "bookmakers": [{
                        "key": bm.get("key"),
                        "title": bm.get("title"),
                        "markets": bm.get("markets", []),
                    } for bm in game.get("bookmakers", [])],
                })
            return json.dumps({"games": result, "count": len(result), "sport": sport, "quota": _quota})

        elif action == "event":
            if not event_id:
                return json.dumps({"error": "event_id required for event action. Get IDs from action=odds"})
            params = {
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "decimal",
            }
            data = _odds_api_get(f"/sports/{sport}/events/{event_id}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)
            return json.dumps({"event": data, "quota": _quota})

        elif action == "compare":
            params = {"regions": "us", "markets": market, "oddsFormat": "decimal"}
            data = _odds_api_get(f"/sports/{sport}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)

            comparisons = []
            for game in (data[:limit] if isinstance(data, list) else []):
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                books = {}
                for bm in game.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") == market:
                            odds_map = {}
                            for o in mkt.get("outcomes", []):
                                odds_map[o["name"]] = o["price"]
                            books[bm["title"]] = odds_map
                comparisons.append({
                    "game": f"{away} @ {home}",
                    "commence": game.get("commence_time"),
                    "odds_by_book": books,
                })
            return json.dumps({"comparisons": comparisons, "quota": _quota})

        elif action == "best_odds":
            params = {"regions": "us,eu", "markets": market, "oddsFormat": "decimal"}
            data = _odds_api_get(f"/sports/{sport}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)

            best_lines = []
            for game in (data[:limit] if isinstance(data, list) else []):
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                bms = game.get("bookmakers", [])
                best_home = _find_best_odds(bms, home)
                best_away = _find_best_odds(bms, away)

                # Check for draw if applicable
                best_draw = _find_best_odds(bms, "Draw")
                outcomes = {home: best_home, away: best_away}
                if "error" not in best_draw:
                    outcomes["Draw"] = best_draw

                best_lines.append({
                    "game": f"{away} @ {home}",
                    "commence": game.get("commence_time"),
                    "best_odds": outcomes,
                })
            return json.dumps({"best_lines": best_lines, "quota": _quota})

        elif action == "player_props":
            if not event_id:
                # Get all games first, then fetch props for each
                params = {"regions": "us", "oddsFormat": "decimal"}
                data = _odds_api_get(f"/sports/{sport}/odds", params)
                if isinstance(data, dict) and "error" in data:
                    return json.dumps(data)

                all_props = []
                prop_limit = min(limit, 8)  # Fetch props for only first N games to conserve quota
                for game in (data[:prop_limit] if isinstance(data, list) else []):
                    game_id = game.get("id")
                    home = game.get("home_team", "")
                    away = game.get("away_team", "")
                    commence = game.get("commence_time", "")

                    # Fetch player props for this game
                    prop_params = {
                        "regions": "us,us2",
                        "markets": "player_points,player_rebounds,player_assists,player_threes,player_blocks,player_steals,player_points_rebounds_assists",
                        "oddsFormat": "decimal",
                    }
                    props_data = _odds_api_get(f"/sports/{sport}/events/{game_id}/odds", prop_params)
                    if isinstance(props_data, dict) and "error" in props_data:
                        continue

                    # Parse player props from bookmakers
                    for bm in props_data.get("bookmakers", []):
                        for market in bm.get("markets", []):
                            market_key = market.get("key", "")
                            prop_type = _parse_prop_type(market_key)
                            if not prop_type:
                                continue

                            for outcome in market.get("outcomes", []):
                                player = outcome.get("name", "").split(" Over")[0].split(" Under")[0].strip()
                                price = outcome.get("price", 0)
                                point = outcome.get("point", None)
                                side = "Over" if "Over" in outcome.get("name", "") else "Under"

                                if price <= 1 or not point:
                                    continue

                                all_props.append({
                                    "game": f"{away} @ {home}",
                                    "commence": commence,
                                    "player": player,
                                    "prop_type": prop_type,
                                    "line": point,
                                    "side": side,
                                    "odds": price,
                                    "implied_prob": round(_decimal_to_implied(price), 4),
                                    "book": bm.get("title", ""),
                                    "book_key": bm.get("key", ""),
                                })

                # Find best odds for each player/prop combination
                best_props = {}
                for prop in all_props:
                    key = (prop["player"], prop["prop_type"], prop["line"])
                    if key not in best_props:
                        best_props[key] = {"over": [], "under": []}
                    if prop["side"] == "Over":
                        best_props[key]["over"].append(prop)
                    else:
                        best_props[key]["under"].append(prop)

                # Format response with best prices
                formatted_props = []
                for (player, prop_type, line), sides in best_props.items():
                    over_best = max(sides["over"], key=lambda x: x["odds"], default=None)
                    under_best = max(sides["under"], key=lambda x: x["odds"], default=None)

                    prop_entry = {
                        "player": player,
                        "prop_type": prop_type,
                        "line": line,
                    }
                    if over_best:
                        prop_entry["over"] = {
                            "odds": over_best["odds"],
                            "implied_prob": over_best["implied_prob"],
                            "best_book": over_best["book"],
                        }
                    if under_best:
                        prop_entry["under"] = {
                            "odds": under_best["odds"],
                            "implied_prob": under_best["implied_prob"],
                            "best_book": under_best["book"],
                        }

                    formatted_props.append(prop_entry)

                return json.dumps({
                    "sport": sport,
                    "player_props": formatted_props[:limit],
                    "total_props": len(formatted_props),
                    "note": "Player props markets are less efficient than moneyline/spreads — higher edge potential. 2-3x quota usage vs regular odds.",
                    "quota": _quota,
                })

            else:
                # Specific event player props
                prop_params = {
                    "regions": "us,us2",
                    "markets": "player_points,player_rebounds,player_assists,player_threes,player_blocks,player_steals,player_points_rebounds_assists",
                    "oddsFormat": "decimal",
                }
                props_data = _odds_api_get(f"/sports/{sport}/events/{event_id}/odds", prop_params)
                if isinstance(props_data, dict) and "error" in props_data:
                    return json.dumps(props_data)

                # Parse and structure
                all_props = []
                for bm in props_data.get("bookmakers", []):
                    for market in bm.get("markets", []):
                        market_key = market.get("key", "")
                        prop_type = _parse_prop_type(market_key)
                        if not prop_type:
                            continue

                        for outcome in market.get("outcomes", []):
                            player = outcome.get("name", "").split(" Over")[0].split(" Under")[0].strip()
                            price = outcome.get("price", 0)
                            point = outcome.get("point", None)
                            side = "Over" if "Over" in outcome.get("name", "") else "Under"

                            if price <= 1 or not point:
                                continue

                            all_props.append({
                                "player": player,
                                "prop_type": prop_type,
                                "line": point,
                                "side": side,
                                "odds": price,
                                "implied_prob": round(_decimal_to_implied(price), 4),
                                "book": bm.get("title", ""),
                            })

                return json.dumps({
                    "event_id": event_id,
                    "player_props": all_props[:limit],
                    "total_available": len(all_props),
                    "quota": _quota,
                })

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: sports, odds, event, compare, best_odds, player_props"})

    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════
# TOOL 2: sportsbook_arb — Arbitrage + EV scanner
# ═══════════════════════════════════════════════════════════════

def sportsbook_arb(action: str, sport: str = "basketball_nba",
                   event_id: str = "", min_profit: float = 0.0,
                   min_ev: float = 0.01, limit: int = 10) -> str:
    """Find arbitrage and +EV opportunities across sportsbooks.

    Actions:
        scan      — Find arbitrage (implied probs sum < 100%)
        calculate — Optimal stake allocation for a specific arb
        ev_scan   — Compare soft book odds vs Pinnacle sharp line, flag +EV
    """
    try:
        if action == "scan":
            # Pull all odds for the sport
            params = {"regions": "us,eu", "markets": "h2h", "oddsFormat": "decimal"}
            data = _odds_api_get(f"/sports/{sport}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)

            arbs = []
            for game in (data if isinstance(data, list) else []):
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                bms = game.get("bookmakers", [])

                best_home = _find_best_odds(bms, home)
                best_away = _find_best_odds(bms, away)

                if "error" in best_home or "error" in best_away:
                    continue

                home_implied = _decimal_to_implied(best_home["decimal"])
                away_implied = _decimal_to_implied(best_away["decimal"])

                arb_info = _calculate_arb([home_implied, away_implied])
                if arb_info["is_arb"] and arb_info["profit_pct"] >= min_profit:
                    arbs.append({
                        "game": f"{away} @ {home}",
                        "commence": game.get("commence_time"),
                        "id": game.get("id"),
                        "home": {
                            "team": home, "best_odds": best_home["decimal"],
                            "book": best_home["book_title"], "implied": round(home_implied, 4),
                        },
                        "away": {
                            "team": away, "best_odds": best_away["decimal"],
                            "book": best_away["book_title"], "implied": round(away_implied, 4),
                        },
                        "arb": arb_info,
                    })

            arbs.sort(key=lambda x: x["arb"]["profit_pct"], reverse=True)
            return json.dumps({
                "arb_opportunities": arbs[:limit],
                "total_found": len(arbs),
                "sport": sport,
                "note": "Profit% = guaranteed profit if you bet the correct stakes on each side" if arbs else "No arb opportunities found. This is normal — true arbs are rare and close fast.",
                "quota": _quota,
            })

        elif action == "calculate":
            if not event_id:
                return json.dumps({"error": "event_id required for calculate. Get from action=scan"})

            params = {"regions": "us,eu", "markets": "h2h", "oddsFormat": "decimal"}
            data = _odds_api_get(f"/sports/{sport}/events/{event_id}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)

            bms = data.get("bookmakers", [])
            home = data.get("home_team", "")
            away = data.get("away_team", "")

            best_home = _find_best_odds(bms, home)
            best_away = _find_best_odds(bms, away)

            if "error" in best_home or "error" in best_away:
                return json.dumps({"error": "Could not find odds for both sides"})

            total_implied = _decimal_to_implied(best_home["decimal"]) + _decimal_to_implied(best_away["decimal"])
            if total_implied >= 1.0:
                return json.dumps({"message": "No arbitrage — implied probabilities sum >= 100%", "total_implied": round(total_implied, 4)})

            # Optimal stakes for $100 total investment
            bankroll = 100.0
            stake_home = bankroll * _decimal_to_implied(best_home["decimal"]) / total_implied
            stake_away = bankroll * _decimal_to_implied(best_away["decimal"]) / total_implied
            profit = bankroll / total_implied - bankroll

            return json.dumps({
                "game": f"{away} @ {home}",
                "bankroll": bankroll,
                "stakes": {
                    home: {"amount": round(stake_home, 2), "odds": best_home["decimal"], "book": best_home["book_title"], "payout": round(stake_home * best_home["decimal"], 2)},
                    away: {"amount": round(stake_away, 2), "odds": best_away["decimal"], "book": best_away["book_title"], "payout": round(stake_away * best_away["decimal"], 2)},
                },
                "guaranteed_profit": round(profit, 2),
                "profit_pct": round(profit / bankroll * 100, 2),
                "quota": _quota,
            })

        elif action == "ev_scan":
            # The key tool — compare soft books vs Pinnacle sharp line
            params = {"regions": "us,eu", "markets": "h2h", "oddsFormat": "decimal",
                      "bookmakers": "pinnacle,draftkings,fanduel,betmgm,caesars,pointsbet,bet365,bovada,betrivers,unibet,williamhill,mybookieag"}
            data = _odds_api_get(f"/sports/{sport}/odds", params)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(data)

            ev_bets = []
            for game in (data if isinstance(data, list) else []):
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                bms = game.get("bookmakers", [])

                # Get Pinnacle as sharp reference
                pinnacle = _get_pinnacle_odds(bms)
                if not pinnacle:
                    continue

                # Extract Pinnacle's implied probs (the "true" odds)
                pin_probs = {}
                for mkt in pinnacle.get("markets", []):
                    if mkt.get("key") == "h2h":
                        total_imp = sum(_decimal_to_implied(o["price"]) for o in mkt.get("outcomes", []))
                        for o in mkt.get("outcomes", []):
                            # Remove vig to get fair prob
                            raw_imp = _decimal_to_implied(o["price"])
                            pin_probs[o["name"]] = raw_imp / total_imp if total_imp > 0 else raw_imp

                if not pin_probs:
                    continue

                # Compare every other bookmaker's odds to Pinnacle's sharp line
                for bm in bms:
                    if bm.get("key") == "pinnacle":
                        continue
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") != "h2h":
                            continue
                        for outcome in mkt.get("outcomes", []):
                            name = outcome.get("name", "")
                            price = outcome.get("price", 0)
                            sharp_prob = pin_probs.get(name)
                            if not sharp_prob or not price:
                                continue

                            ev = _calculate_ev(sharp_prob, price)
                            if ev >= min_ev:
                                kelly = _kelly_fraction(sharp_prob, price)
                                ev_bets.append({
                                    "game": f"{away} @ {home}",
                                    "commence": game.get("commence_time"),
                                    "bet": name,
                                    "book": bm.get("title"),
                                    "book_key": bm.get("key"),
                                    "decimal_odds": price,
                                    "implied_prob": round(_decimal_to_implied(price), 4),
                                    "sharp_prob": round(sharp_prob, 4),
                                    "edge": round(sharp_prob - _decimal_to_implied(price), 4),
                                    "ev_pct": round(ev * 100, 2),
                                    "kelly_fraction": round(kelly, 4),
                                    "kelly_$100": round(kelly * 100, 2),
                                })

            ev_bets.sort(key=lambda x: x["ev_pct"], reverse=True)
            return json.dumps({
                "ev_opportunities": ev_bets[:limit],
                "total_found": len(ev_bets),
                "sport": sport,
                "method": "Pinnacle sharp line as true probability, devigged",
                "note": "+EV means the bookmaker's odds are better than the true probability. Higher EV% = bigger edge." if ev_bets else "No +EV bets found vs Pinnacle. Markets may be efficient right now.",
                "quota": _quota,
            })

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: scan, calculate, ev_scan"})

    except Exception as e:
        return json.dumps({"error": str(e)})
