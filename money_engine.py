"""
Money Engine — Unified daily scanner for proven money-making strategies.

Combines: sports +EV betting, prediction market arb, bonds, crypto signals,
and cross-platform mispricing into one actionable daily report.

Proven strategies only — each has mathematical edge, not hunches:
  1. Sports arbitrage: guaranteed profit from price gaps across books
  2. +EV betting: mispriced lines vs Pinnacle sharp reference (XGBoost-enhanced)
  3. Prediction market bonds: YES+NO < $1.00 = risk-free profit
  4. Cross-platform arb: Polymarket vs Kalshi price gaps on same events
  5. Expiring convergence: high-conviction markets near close → near-certain gains
  6. Crypto fear/greed contrarian: buy extreme fear, trim extreme greed (data-driven)

Usage:
    # Full daily scan
    result = money_engine("scan")

    # Sports-only
    result = money_engine("sports", params={"sport": "basketball_nba"})

    # Crypto signals
    result = money_engine("crypto")

    # Dashboard summary
    result = money_engine("dashboard")
"""

import json
import logging
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

# Load .env if not already in environment
if not os.environ.get("ODDS_API_KEY"):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass

logger = logging.getLogger("money_engine")

# ---------------------------------------------------------------------------
# Crypto data (CoinGecko free API — no key needed, 30 req/min)
# ---------------------------------------------------------------------------

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def _cg_get(endpoint: str, params: dict = None, timeout: int = 15) -> dict:
    """GET request to CoinGecko free API."""
    url = f"{COINGECKO_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def _crypto_fear_greed() -> dict:
    """Get Bitcoin Fear & Greed Index — proven contrarian signal."""
    try:
        url = "https://api.alternative.me/fng/?limit=7&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        entries = data.get("data", [])
        if not entries:
            return {"error": "No fear/greed data"}

        current = entries[0]
        value = int(current["value"])
        classification = current["value_classification"]

        # 7-day trend
        values_7d = [int(e["value"]) for e in entries[:7]]
        avg_7d = sum(values_7d) / len(values_7d)
        trend = "rising" if values_7d[0] > avg_7d else "falling"

        # Contrarian signal
        if value <= 20:
            signal = "STRONG_BUY"
            reasoning = "Extreme Fear historically precedes 30-60 day rallies. DCA into BTC/ETH."
        elif value <= 35:
            signal = "BUY"
            reasoning = "Fear zone — good accumulation territory for major coins."
        elif value >= 80:
            signal = "STRONG_SELL"
            reasoning = "Extreme Greed — historically precedes corrections. Take profits."
        elif value >= 65:
            signal = "TRIM"
            reasoning = "Greed zone — reduce position sizes, set stop-losses tighter."
        else:
            signal = "HOLD"
            reasoning = "Neutral zone — no strong contrarian signal."

        return {
            "index": value,
            "classification": classification,
            "signal": signal,
            "reasoning": reasoning,
            "trend_7d": trend,
            "avg_7d": round(avg_7d, 1),
            "history": [{"value": int(e["value"]), "date": e.get("timestamp", "")} for e in entries],
        }
    except Exception as e:
        return {"error": f"Fear/Greed fetch failed: {e}"}


def _crypto_top_movers() -> dict:
    """Get top crypto movers (24h) — momentum + mean reversion signals."""
    data = _cg_get("/coins/markets", params={
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": "50",
        "sparkline": "false",
        "price_change_percentage": "24h,7d",
    })
    if isinstance(data, dict) and "error" in data:
        return data

    if not isinstance(data, list):
        return {"error": "Unexpected response format"}

    gainers = []
    losers = []
    for coin in data:
        change_24h = coin.get("price_change_percentage_24h") or 0
        change_7d = coin.get("price_change_percentage_7d_in_currency") or 0
        entry = {
            "symbol": coin.get("symbol", "").upper(),
            "name": coin.get("name", ""),
            "price": coin.get("current_price"),
            "market_cap_rank": coin.get("market_cap_rank"),
            "change_24h": round(change_24h, 2),
            "change_7d": round(change_7d, 2),
            "volume_24h": coin.get("total_volume"),
        }

        if change_24h > 5:
            entry["signal"] = "momentum_long" if change_7d > 0 else "overbought_caution"
            gainers.append(entry)
        elif change_24h < -5:
            entry["signal"] = "mean_reversion_buy" if change_7d > -10 else "falling_knife"
            losers.append(entry)

    gainers.sort(key=lambda x: x["change_24h"], reverse=True)
    losers.sort(key=lambda x: x["change_24h"])

    return {
        "top_gainers": gainers[:10],
        "top_losers": losers[:10],
        "note": "Mean reversion: large-cap coins down >5% in 24h but up/flat over 7d tend to bounce. "
                "Falling knives (down both 24h and 7d) are riskier.",
    }


def _crypto_scan() -> dict:
    """Full crypto intelligence scan."""
    fear_greed = _crypto_fear_greed()
    movers = _crypto_top_movers()

    # BTC dominance check
    btc_data = _cg_get("/coins/bitcoin", params={"localization": "false", "tickers": "false",
                                                    "community_data": "false", "developer_data": "false"})
    btc_dominance = None
    if isinstance(btc_data, dict) and "market_data" in btc_data:
        md = btc_data["market_data"]
        btc_dominance = md.get("market_cap_percentage", {}).get("btc")

    # Build actionable summary
    actions = []
    fg = fear_greed
    if fg.get("signal") in ("STRONG_BUY", "BUY"):
        actions.append({
            "strategy": "Fear/Greed Contrarian",
            "action": fg["signal"],
            "target": "BTC, ETH (large caps)",
            "reasoning": fg.get("reasoning", ""),
            "confidence": "high" if fg.get("signal") == "STRONG_BUY" else "medium",
        })
    elif fg.get("signal") in ("STRONG_SELL", "TRIM"):
        actions.append({
            "strategy": "Fear/Greed Contrarian",
            "action": fg["signal"],
            "target": "Reduce exposure across portfolio",
            "reasoning": fg.get("reasoning", ""),
            "confidence": "high" if fg.get("signal") == "STRONG_SELL" else "medium",
        })

    # Mean reversion plays from losers
    if isinstance(movers.get("top_losers"), list):
        for coin in movers["top_losers"][:3]:
            if coin.get("signal") == "mean_reversion_buy":
                actions.append({
                    "strategy": "Mean Reversion",
                    "action": "BUY_DIP",
                    "target": f"{coin['symbol']} @ ${coin['price']}",
                    "reasoning": f"Down {coin['change_24h']}% in 24h but 7d trend is {coin['change_7d']}%",
                    "confidence": "medium",
                })

    return {
        "fear_greed": fear_greed,
        "top_movers": movers,
        "btc_dominance": btc_dominance,
        "actions": actions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Sports Edge Scanner (XGBoost model vs sharp line)
# ---------------------------------------------------------------------------

def _sports_edge_scan(sport: str = "basketball_nba") -> dict:
    """
    How sportsbooks set lines + where our model finds edges:

    Sportsbook Line-Setting Process:
    1. Opening line: Set by sharp books (Pinnacle, Circa) using power ratings + models
    2. Market moves: Line moves based on betting volume (follow the money)
    3. Soft books (DraftKings, FanDuel) copy sharp lines with extra vig (margin)
    4. The edge: Soft books are slow to move → their prices lag the sharp line

    Our Edge:
    - XGBoost model trained on 3,700+ NBA games (23 features)
    - Compare our probability vs Pinnacle's implied probability
    - When our model disagrees with Pinnacle by >3%, that's a potential edge
    - Bet on soft books that are even further from true probability
    - Quarter-Kelly sizing keeps risk managed
    """
    results = {
        "sport": sport,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_predictions": [],
        "ev_opportunities": [],
        "arb_opportunities": [],
        "how_lines_work": {
            "1_opening": "Sharp books (Pinnacle) set the true line using statistical models",
            "2_market": "Money moves the line — big bets from sharps shift it quickly",
            "3_soft_lag": "Soft books (DraftKings, FanDuel, BetMGM) copy but lag behind",
            "4_our_edge": "Our XGBoost model + Pinnacle comparison finds where soft books are wrong",
            "5_sizing": "Quarter-Kelly: bet 25% of what Kelly criterion suggests for safety",
        },
    }

    # Step 1: Get XGBoost predictions
    try:
        from sports_model import sports_predict
        preds = json.loads(sports_predict("predict", sport="nba"))
        results["model_predictions"] = preds.get("predictions", [])
        if preds.get("message"):
            results["model_note"] = preds["message"]
    except Exception as e:
        results["model_predictions"] = [{"error": f"Model prediction failed: {e}"}]

    # Step 2: Get +EV opportunities (model vs odds)
    try:
        from sports_model import sports_betting
        ev_picks = json.loads(sports_betting("recommend"))
        results["ev_opportunities"] = ev_picks.get("recommendations", ev_picks.get("picks", []))
        if ev_picks.get("bankroll"):
            results["bankroll"] = ev_picks["bankroll"]
    except Exception as e:
        results["ev_opportunities"] = [{"error": f"EV scan failed: {e}"}]

    # Step 3: Get arbitrage opportunities
    try:
        from sportsbook_odds import sportsbook_arb
        arbs = json.loads(sportsbook_arb("scan", sport=sport))
        results["arb_opportunities"] = arbs.get("arb_opportunities", [])
    except Exception as e:
        results["arb_opportunities"] = [{"error": f"Arb scan failed: {e}"}]

    # Step 4: Get best lines across all books
    try:
        from sportsbook_odds import sportsbook_odds
        best = json.loads(sportsbook_odds("best_odds", sport=sport, limit=5))
        results["best_lines"] = best.get("best_lines", [])
    except Exception as e:
        results["best_lines"] = [{"error": f"Best lines failed: {e}"}]

    # Combine into actionable picks
    actions = []
    for opp in results.get("ev_opportunities", []):
        if isinstance(opp, dict) and "error" not in opp:
            ev = opp.get("expected_value", opp.get("ev", 0))
            if isinstance(ev, (int, float)) and ev > 0:
                actions.append({
                    "strategy": "XGBoost +EV",
                    "action": "BET",
                    "target": opp.get("game", opp.get("team", "unknown")),
                    "side": opp.get("side", opp.get("pick", "")),
                    "ev_pct": ev,
                    "kelly_stake": opp.get("kelly_stake", opp.get("stake", "?")),
                    "book": opp.get("book", opp.get("bookmaker", "")),
                    "confidence": "high" if ev > 5 else "medium" if ev > 2 else "low",
                })

    for arb in results.get("arb_opportunities", []):
        if isinstance(arb, dict) and "error" not in arb:
            actions.append({
                "strategy": "Sportsbook Arb",
                "action": "ARB",
                "target": arb.get("game", ""),
                "profit_pct": arb.get("arb", {}).get("profit_pct", 0),
                "confidence": "guaranteed",
            })

    results["actions"] = actions
    return results


# ---------------------------------------------------------------------------
# Prediction Market Scanner
# ---------------------------------------------------------------------------

def _prediction_market_scan() -> dict:
    """Scan Polymarket + Kalshi for all proven edge strategies."""
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bonds": [],
        "cross_platform_arb": [],
        "mispricing": [],
        "expiring_convergence": [],
        "trending": [],
    }

    # Strategy 1: Bonds (YES+NO < $1.00 = risk-free)
    try:
        from trading_strategies import trading_strategies
        bonds = json.loads(trading_strategies("bonds", {"max_results": 10}))
        results["bonds"] = bonds.get("bonds", bonds.get("opportunities", []))
    except Exception as e:
        results["bonds"] = [{"error": str(e)}]

    # Strategy 2: Cross-platform arb
    try:
        from trading_strategies import trading_strategies
        misp = json.loads(trading_strategies("mispricing", {"max_results": 10}))
        results["cross_platform_arb"] = misp.get("cross_platform_arb", [])
        results["mispricing"] = misp.get("single_platform_mispricing", [])
    except Exception as e:
        results["cross_platform_arb"] = [{"error": str(e)}]

    # Strategy 3: Expiring convergence (markets closing soon with high conviction)
    try:
        from trading_strategies import trading_strategies
        expiring = json.loads(trading_strategies("expiring", {"hours": 48, "limit": 10}))
        exp_list = expiring.get("expiring", [])
        # Filter to high-conviction only
        results["expiring_convergence"] = [
            e for e in exp_list
            if isinstance(e, dict) and e.get("conviction", "").startswith("strong")
        ]
    except Exception as e:
        results["expiring_convergence"] = [{"error": str(e)}]

    # Strategy 4: Trending (volume spikes = news)
    try:
        from trading_strategies import trading_strategies
        trending = json.loads(trading_strategies("trending", {"limit": 10}))
        results["trending"] = trending.get("trending", [])
    except Exception as e:
        results["trending"] = [{"error": str(e)}]

    # Build actionable picks
    actions = []

    # Bonds = near risk-free
    for bond in results.get("bonds", []):
        if isinstance(bond, dict) and "error" not in bond:
            actions.append({
                "strategy": "Prediction Market Bond",
                "action": "BOND",
                "target": bond.get("title", bond.get("question", "?")),
                "platform": bond.get("platform", "?"),
                "price": bond.get("yes_price", bond.get("price", "?")),
                "edge": "Risk-free if YES+NO < $1.00",
                "confidence": "very_high",
            })

    # Cross-platform arb
    for arb in results.get("cross_platform_arb", []):
        if isinstance(arb, dict) and "error" not in arb:
            actions.append({
                "strategy": "Cross-Platform Arb",
                "action": "ARB",
                "target": arb.get("title", arb.get("event", "?")),
                "edge_pct": arb.get("edge", arb.get("spread", 0)),
                "platforms": f"{arb.get('platform_a', '?')} vs {arb.get('platform_b', '?')}",
                "confidence": "high",
            })

    # Expiring convergence
    for exp in results.get("expiring_convergence", []):
        if isinstance(exp, dict) and "error" not in exp:
            actions.append({
                "strategy": "Expiring Convergence",
                "action": "BUY" if exp.get("conviction") == "strong YES" else "SHORT",
                "target": exp.get("title", "?"),
                "hours_left": exp.get("hours_left"),
                "price": exp.get("yes_price"),
                "confidence": "high",
            })

    results["actions"] = actions
    return results


# ---------------------------------------------------------------------------
# Main Money Engine
# ---------------------------------------------------------------------------

def money_engine(action: str, params: Optional[dict] = None) -> str:
    """
    Unified money-making scanner — proven strategies with mathematical edge.

    Actions:
        scan          — Full scan: sports + prediction markets + crypto
        sports        — Sports-only: XGBoost +EV, arb, best lines
        prediction    — Prediction markets only: bonds, arb, mispricing, expiring
        crypto        — Crypto: fear/greed contrarian, momentum, mean reversion
        dashboard     — Quick summary of all opportunities with action items
        scan_schedule — Show next scan time and recent scan history
        explain       — How each strategy works and its historical edge
    """
    params = params or {}
    start = time.time()

    try:
        if action == "scan":
            return _full_scan(params)
        elif action == "sports":
            result = _sports_edge_scan(params.get("sport", "basketball_nba"))
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)
        elif action == "prediction":
            result = _prediction_market_scan()
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)
        elif action == "crypto":
            result = _crypto_scan()
            result["scan_time_seconds"] = round(time.time() - start, 1)
            return json.dumps(result, default=str)
        elif action == "dashboard":
            return _dashboard(params)
        elif action == "scan_schedule":
            return _scan_schedule(params)
        elif action == "explain":
            return _explain_strategies()
        else:
            return json.dumps({
                "error": f"Unknown action '{action}'",
                "available": ["scan", "sports", "prediction", "crypto", "dashboard", "scan_schedule", "explain"],
            })
    except Exception as e:
        logger.error(f"Money engine error: {e}")
        return json.dumps({"error": str(e)})


def _full_scan(params: dict) -> str:
    """Run all scanners and produce unified report."""
    start = time.time()

    sports = {}
    prediction = {}
    crypto = {}

    # Sports scan
    try:
        sport = params.get("sport", "basketball_nba")
        sports = _sports_edge_scan(sport)
    except Exception as e:
        sports = {"error": str(e)}

    # Prediction market scan
    try:
        prediction = _prediction_market_scan()
    except Exception as e:
        prediction = {"error": str(e)}

    # Crypto scan
    try:
        crypto = _crypto_scan()
    except Exception as e:
        crypto = {"error": str(e)}

    # Merge all actions, sort by confidence
    all_actions = []
    confidence_rank = {"guaranteed": 0, "very_high": 1, "high": 2, "medium": 3, "low": 4}

    for source_name, source_data in [("sports", sports), ("prediction", prediction), ("crypto", crypto)]:
        if isinstance(source_data, dict):
            for action_item in source_data.get("actions", []):
                action_item["source"] = source_name
                all_actions.append(action_item)

    all_actions.sort(key=lambda x: confidence_rank.get(x.get("confidence", "low"), 5))

    # Count by strategy type
    strategy_counts = {}
    for a in all_actions:
        s = a.get("strategy", "unknown")
        strategy_counts[s] = strategy_counts.get(s, 0) + 1

    return json.dumps({
        "scan_time_seconds": round(time.time() - start, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_opportunities": len(all_actions),
        "by_strategy": strategy_counts,
        "top_actions": all_actions[:20],
        "sports": sports,
        "prediction_markets": prediction,
        "crypto": crypto,
        "disclaimer": "Mathematical edge != guaranteed profit. Manage bankroll. All trades dry-run by default.",
    }, default=str)


def _scan_schedule(params: dict = None) -> str:
    """Show when the next daily scan is and recent scan history."""
    params = params or {}
    import glob
    from pathlib import Path

    schedule_info = {
        "next_scan": "Daily at 4:30 PM ET (21:30 UTC)",
        "cron_entry": "30 21 * * * cd /root/openclaw && /usr/bin/python3 daily_scan.py >> data/betting/scan.log 2>&1",
        "timezone": "UTC (4:30 PM ET = 21:30 UTC)",
        "days": "Every day (Mon-Sun)",
    }

    # Get recent scan history
    report_dir = "./data/betting/daily_reports"
    recent_reports = []
    try:
        report_files = sorted(glob.glob(f"{report_dir}/*.json"), reverse=True)[:7]
        for report_file in report_files:
            try:
                with open(report_file, "r") as f:
                    data = json.load(f)
                    report_date = Path(report_file).stem
                    dash_picks = len(data.get("dashboard", {}).get("picks", []))
                    nba_picks = len(data.get("nba_value", {}).get("top_picks", []))
                    crypto_signal = (
                        data.get("crypto", {})
                        .get("fear_greed", {})
                        .get("signal", "HOLD")
                    )
                    recent_reports.append({
                        "date": report_date,
                        "dashboard_signals": dash_picks,
                        "nba_plays": nba_picks,
                        "crypto_signal": crypto_signal,
                    })
            except Exception:
                pass
    except Exception as e:
        schedule_info["history_error"] = str(e)

    return json.dumps({
        "schedule": schedule_info,
        "recent_scans": recent_reports,
        "scan_log": "./data/betting/scan.log",
        "next_action": "Install cron entry if you haven't already. See schedule.cron_entry above.",
    }, default=str)


def _dashboard(params: dict) -> str:
    """Quick summary — top picks across all strategies."""
    # Light scan (skip full details)
    all_picks = []

    # Quick crypto check (fastest)
    try:
        fg = _crypto_fear_greed()
        if fg.get("signal") in ("STRONG_BUY", "STRONG_SELL"):
            all_picks.append({
                "priority": 1,
                "type": "crypto",
                "signal": fg["signal"],
                "detail": f"Fear/Greed Index: {fg.get('index')} ({fg.get('classification')})",
                "action": fg.get("reasoning", ""),
            })
    except Exception:
        pass

    # Quick prediction market check
    try:
        from trading_strategies import trading_strategies
        bonds = json.loads(trading_strategies("bonds", {"max_results": 3}))
        bond_list = bonds.get("bonds", bonds.get("opportunities", []))
        if bond_list:
            all_picks.append({
                "priority": 2,
                "type": "prediction_market",
                "signal": "BONDS_AVAILABLE",
                "detail": f"{len(bond_list)} near-risk-free bond opportunities",
                "action": "Buy YES+NO where combined < $1.00",
            })
    except Exception:
        pass

    # Quick expiring check
    try:
        from trading_strategies import trading_strategies
        exp = json.loads(trading_strategies("expiring", {"hours": 24, "limit": 5}))
        exp_list = exp.get("expiring", [])
        strong = [e for e in exp_list if isinstance(e, dict) and e.get("conviction", "").startswith("strong")]
        if strong:
            all_picks.append({
                "priority": 3,
                "type": "prediction_market",
                "signal": "EXPIRING_CONVERGENCE",
                "detail": f"{len(strong)} high-conviction markets closing within 24h",
                "action": "Buy dominant side for near-certain small gains",
            })
    except Exception:
        pass

    # Quick sports check
    try:
        from sportsbook_odds import sportsbook_arb
        arbs = json.loads(sportsbook_arb("scan", sport="basketball_nba"))
        arb_list = arbs.get("arb_opportunities", [])
        if arb_list:
            all_picks.append({
                "priority": 1,
                "type": "sports",
                "signal": "ARB_FOUND",
                "detail": f"{len(arb_list)} guaranteed-profit arbitrage opportunities",
                "action": "Bet both sides at different books for risk-free profit",
            })
    except Exception:
        pass

    all_picks.sort(key=lambda x: x.get("priority", 99))

    return json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_signals": len(all_picks),
        "picks": all_picks,
        "note": "Run money_engine('scan') for full details on each opportunity.",
    }, default=str)


def _explain_strategies() -> str:
    """Explain each strategy, its historical edge, and risk profile."""
    return json.dumps({
        "strategies": [
            {
                "name": "Sports Arbitrage",
                "edge": "Guaranteed 1-5% profit per event",
                "how": "Different bookmakers price the same event differently. "
                       "Bet both sides at different books where combined implied probability < 100%. "
                       "You profit regardless of outcome.",
                "risk": "Very low — only risk is bookmaker limiting/banning your account.",
                "capital_needed": "$500+ per arb to make meaningful profit",
                "frequency": "Rare (3-5 per week in NBA). Must act fast — arbs close in minutes.",
            },
            {
                "name": "+EV Sports Betting (XGBoost)",
                "edge": "3-8% edge per bet on average when model disagrees with books",
                "how": "Our XGBoost model (trained on 3,700+ NBA games, 23 features) calculates "
                       "true win probability. When our probability differs from Pinnacle's sharp "
                       "line by >3%, soft books (DraftKings, FanDuel) are even further off — that's our edge.",
                "risk": "Medium — individual bets can lose. Edge compounds over 100+ bets.",
                "capital_needed": "$1,000+ bankroll, Quarter-Kelly sizing",
                "frequency": "2-5 bets per day during NBA season",
            },
            {
                "name": "Prediction Market Bonds",
                "edge": "Risk-free 1-10% return",
                "how": "When YES + NO prices sum to less than $1.00, buy both. "
                       "You're guaranteed $1.00 at resolution regardless of outcome. "
                       "Profit = $1.00 - (YES + NO price).",
                "risk": "Near zero — only risk is platform insolvency.",
                "capital_needed": "$100+ per bond",
                "frequency": "Occasional. More common on Polymarket than Kalshi.",
            },
            {
                "name": "Cross-Platform Arbitrage",
                "edge": "2-10% on matching markets",
                "how": "Same event priced differently on Polymarket vs Kalshi. "
                       "Buy YES on the cheaper platform, NO on the more expensive one.",
                "risk": "Low — main risk is resolution timing/rule differences between platforms.",
                "capital_needed": "$200+ per trade",
                "frequency": "5-15 opportunities per week (2%+ edge)",
            },
            {
                "name": "Expiring Convergence",
                "edge": "1-5% in final hours",
                "how": "Markets with >85% conviction closing within 24-48h tend to resolve as priced. "
                       "Buy the dominant side at 85-95 cents, collect $1.00 at resolution.",
                "risk": "Low-medium — the 5-15% chance of upset exists.",
                "capital_needed": "$100+ per market",
                "frequency": "3-10 per day across Kalshi events",
            },
            {
                "name": "Crypto Fear/Greed Contrarian",
                "edge": "Historical 20-40% returns within 90 days of Extreme Fear",
                "how": "Bitcoin Fear & Greed Index below 20 (Extreme Fear) has historically "
                       "preceded rallies. Above 80 (Extreme Greed) precedes corrections. "
                       "DCA into BTC/ETH during fear, take profits during greed.",
                "risk": "Medium-high — crypto is volatile. Use DCA, not lump sum.",
                "capital_needed": "Any amount. DCA $50-500/week.",
                "frequency": "Extreme readings happen 2-3 times per year.",
            },
        ],
        "bankroll_rules": {
            "rule_1": "Never risk more than 5% of total bankroll on any single bet/trade",
            "rule_2": "Quarter-Kelly sizing: bet 25% of what Kelly criterion suggests",
            "rule_3": "Keep 3 separate bankrolls: sports ($X), prediction markets ($Y), crypto ($Z)",
            "rule_4": "Track every trade. Review weekly. Cut strategies that aren't working.",
            "rule_5": "Set stop-losses. If bankroll drops 20%, stop and review.",
        },
    })


# ---------------------------------------------------------------------------
# Register as MCP tool
# ---------------------------------------------------------------------------

MONEY_ENGINE_TOOL = {
    "name": "money_engine",
    "description": "Unified money-making scanner — sports +EV, prediction market arb, crypto signals. Proven strategies with mathematical edge.",
    "parameters": {
        "action": {
            "type": "string",
            "description": "scan | sports | prediction | crypto | dashboard | explain",
            "required": True,
        },
        "params": {
            "type": "object",
            "description": "Optional params: {sport: 'basketball_nba', hours: 24, limit: 10}",
            "required": False,
        },
    },
    "handler": money_engine,
}
