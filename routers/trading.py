"""
FastAPI router for trading, prediction markets, and sports betting endpoints.

Includes:
- Polymarket: prices, monitor, portfolio, trade
- Kalshi: markets, trade, portfolio
- Arbitrage scanning (cross-platform)
- Trading strategies and safety
- Sportsbook odds and arbitrage
- Sports predictions and betting
- Deep research
- Proposal generation
- Prediction tracking
- Perplexity research
- AI news and tweets
"""

import json
import logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("openclaw_gateway")

router = APIRouter(prefix="/api", tags=["trading"])


# ═══════════════════════════════════════════════════════════════════════
# RESEARCH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/perplexity-research")
async def api_perplexity_research_get(query: str, model: str = "sonar", focus: str = "web"):
    """Deep research via Perplexity Sonar API (GET)."""
    try:
        from agent_tools import _perplexity_research
        result = _perplexity_research(query=query, model=model, focus=focus)
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/perplexity-research")
async def api_perplexity_research_post(request: Request):
    """Deep research via Perplexity Sonar API (POST)."""
    try:
        body = await request.json()
        from agent_tools import _perplexity_research
        result = _perplexity_research(
            query=body.get("query", ""),
            model=body.get("model", "sonar"),
            focus=body.get("focus", "web")
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# AI NEWS & TWEETS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/ai-news")
async def api_ai_news(limit: int = 10, source: Optional[str] = None, hours: int = 24):
    """Fetch latest AI news from RSS feeds."""
    try:
        from agent_tools import _read_ai_news
        result = _read_ai_news(limit=limit, source=source, hours=hours)
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/tweets")
async def api_tweets(account: Optional[str] = None, limit: int = 5):
    """Read recent tweets from AI accounts via Nitter."""
    try:
        from agent_tools import _read_tweets
        result = _read_tweets(account=account, limit=limit)
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# POLYMARKET TRADING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/polymarket/prices")
async def api_polymarket_prices(request: Request):
    """Real-time Polymarket price data — snapshot, spread, midpoint, book, last trade, history."""
    try:
        body = await request.json()
        from polymarket_trading import polymarket_prices
        result = polymarket_prices(
            action=body.get("action", "snapshot"),
            market_id=body.get("market_id", ""),
            token_id=body.get("token_id", ""),
            interval=body.get("interval", "1d"),
            fidelity=body.get("fidelity", 0),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/polymarket/monitor")
async def api_polymarket_monitor(request: Request):
    """Monitor markets — mispricing detector, open interest, volume, holders, leaderboard, health."""
    try:
        body = await request.json()
        from polymarket_trading import polymarket_monitor
        result = polymarket_monitor(
            action=body.get("action", "health"),
            market_id=body.get("market_id", ""),
            condition_id=body.get("condition_id", ""),
            event_id=body.get("event_id", ""),
            period=body.get("period", "week"),
            order_by=body.get("order_by", "pnl"),
            limit=body.get("limit", 10),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/polymarket/portfolio")
async def api_polymarket_portfolio(request: Request):
    """View any wallet's Polymarket positions, trades, activity (read-only)."""
    try:
        body = await request.json()
        from polymarket_trading import polymarket_portfolio
        result = polymarket_portfolio(
            action=body.get("action", "positions"),
            address=body.get("address", ""),
            limit=body.get("limit", 25),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/polymarket/trade")
async def api_polymarket_trade(request: Request):
    """Place, cancel, manage Polymarket orders — safety-checked, dry-run default."""
    try:
        body = await request.json()
        from polymarket_trading import polymarket_trade
        result = polymarket_trade(
            action=body.get("action", "buy"),
            market_id=body.get("market_id", ""),
            side=body.get("side", "yes"),
            price=body.get("price", 0.0),
            size=body.get("size", 0.0),
            order_id=body.get("order_id", ""),
            dry_run=body.get("dry_run"),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# KALSHI TRADING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/kalshi/markets")
async def api_kalshi_markets(request: Request):
    """Search and view Kalshi market data — read-only, no auth needed."""
    try:
        body = await request.json()
        from kalshi_trading import kalshi_markets
        result = kalshi_markets(
            action=body.get("action", "search"),
            ticker=body.get("ticker", ""),
            query=body.get("query", ""),
            event_ticker=body.get("event_ticker", ""),
            status=body.get("status", ""),
            limit=body.get("limit", 20),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/kalshi/trade")
async def api_kalshi_trade(request: Request):
    """Place, cancel, manage Kalshi orders — safety-checked, dry-run default."""
    try:
        body = await request.json()
        from kalshi_trading import kalshi_trade
        result = kalshi_trade(
            action=body.get("action", "buy"),
            ticker=body.get("ticker", ""),
            side=body.get("side", "yes"),
            price=body.get("price", 0),
            count=body.get("count", 1),
            order_id=body.get("order_id", ""),
            dry_run=body.get("dry_run"),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/kalshi/portfolio")
async def api_kalshi_portfolio(request: Request):
    """View Kalshi portfolio — balance, positions, fills, settlements."""
    try:
        body = await request.json()
        from kalshi_trading import kalshi_portfolio
        result = kalshi_portfolio(
            action=body.get("action", "balance"),
            limit=body.get("limit", 50),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# ARBITRAGE & TRADING STRATEGIES
# ═══════════════════════════════════════════════════════════════════════

@router.post("/arb/scan")
async def api_arb_scan(request: Request):
    """Cross-platform arbitrage scanner — Polymarket + Kalshi."""
    try:
        body = await request.json()
        from arb_scanner import arb_scan
        result = arb_scan(
            action=body.get("action", "scan"),
            query=body.get("query", ""),
            min_edge=body.get("min_edge", 0.02),
            max_results=body.get("max_results", 10),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/trading/strategies")
async def api_trading_strategies(request: Request):
    """Automated trading opportunity scanners — bonds, mispricing, whale alerts, trending, expiring."""
    try:
        body = await request.json()
        from trading_strategies import trading_strategies
        result = trading_strategies(
            action=body.get("action", "summary"),
            params=body.get("params"),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/trading/safety")
async def api_trading_safety(request: Request):
    """Trading safety configuration — dry-run, kill switch, limits, audit log."""
    try:
        body = await request.json()
        from trading_safety import manage_safety
        result = manage_safety(
            action=body.get("action", "status"),
            config=body.get("config"),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# SPORTSBOOK ODDS + BETTING ENGINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/sportsbook/odds")
async def api_sportsbook_odds(request: Request):
    """Live sportsbook odds from 200+ bookmakers — moneylines, spreads, totals, comparisons."""
    try:
        body = await request.json()
        from sportsbook_odds import sportsbook_odds
        result = sportsbook_odds(
            action=body.get("action", "sports"),
            sport=body.get("sport", ""),
            market=body.get("market", "h2h"),
            bookmakers=body.get("bookmakers", ""),
            event_id=body.get("event_id", ""),
            limit=body.get("limit", 10),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/sportsbook/arb")
async def api_sportsbook_arb(request: Request):
    """Sportsbook arbitrage + EV scanner — find arbs and +EV bets vs Pinnacle sharp line."""
    try:
        body = await request.json()
        from sportsbook_odds import sportsbook_arb
        result = sportsbook_arb(
            action=body.get("action", "scan"),
            sport=body.get("sport", "basketball_nba"),
            event_id=body.get("event_id", ""),
            min_profit=body.get("min_profit", 0.0),
            min_ev=body.get("min_ev", 0.01),
            limit=body.get("limit", 10),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/sports/predict")
async def api_sports_predict(request: Request):
    """XGBoost-powered NBA predictions — win probabilities, model evaluation, training."""
    try:
        body = await request.json()
        from sports_model import sports_predict
        result = sports_predict(
            action=body.get("action", "predict"),
            sport=body.get("sport", "nba"),
            team=body.get("team", ""),
            date=body.get("date", ""),
            limit=body.get("limit", 10),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/sports/betting")
async def api_sports_betting(request: Request):
    """Full betting pipeline — predictions + odds + EV + Kelly sizing."""
    try:
        body = await request.json()
        from sports_model import sports_betting
        result = sports_betting(
            action=body.get("action", "recommend"),
            sport=body.get("sport", "nba"),
            bankroll=body.get("bankroll", 100.0),
            min_ev=body.get("min_ev", 0.01),
            limit=body.get("limit", 10),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/sports/tracker")
async def api_sports_tracker(request: Request):
    """Prediction tracker — log predictions, grade results, track accuracy/ROI."""
    try:
        body = await request.json()
        from prediction_tracker import prediction_tracker
        result = prediction_tracker(
            action=body.get("action", "record"),
            date=body.get("date", ""),
            bankroll=body.get("bankroll", 100.0),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# RESEARCH & UTILITIES
# ═══════════════════════════════════════════════════════════════════════

@router.post("/research/deep")
async def api_deep_research(request: Request):
    """Deep research — multi-step autonomous research with structured reports."""
    try:
        body = await request.json()
        from deep_research import deep_research
        result = deep_research(
            query=body.get("query", ""),
            depth=body.get("depth", "medium"),
            mode=body.get("mode", "general"),
            max_sources=body.get("max_sources", 0),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/proposals/generate")
async def api_generate_proposal(request: Request):
    """Generate a branded HTML client proposal."""
    try:
        body = await request.json()
        from proposal_generator import generate_proposal
        result = generate_proposal(
            business_name=body.get("business_name", ""),
            business_type=body.get("business_type", "other"),
            owner_name=body.get("owner_name", ""),
            selected_services=body.get("selected_services", []),
            custom_notes=body.get("custom_notes", ""),
        )
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/prediction")
async def api_prediction(request: Request):
    """Prediction market queries — PA worker calls this endpoint."""
    try:
        body = await request.json()
        from agent_tools import _prediction_market
        result = _prediction_market(
            action=body.get("action", "list_markets"),
            query=body.get("query", ""),
            market_id=body.get("market_id", ""),
            tag=body.get("tag", ""),
            limit=body.get("limit", 10),
        )
        # Result may be raw JSON string or plain text from CLI
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return {"result": result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
