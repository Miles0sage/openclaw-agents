"""
Kalshi Trading Module — Full SDK wrapper for Kalshi prediction markets.

Read-only market data works without auth. Trading requires RSA key pair.
All monetary values in CENTS (Kalshi native convention).
"""

import json
import os
import logging
from typing import Optional

logger = logging.getLogger("kalshi_trading")

# Kalshi SDK imports — graceful degradation if not installed
try:
    import kalshi_python
    from kalshi_python import KalshiClient
    KALSHI_SDK_AVAILABLE = True
except ImportError:
    KALSHI_SDK_AVAILABLE = False

from trading_safety import check_order_safety, log_trade


def _get_portfolio_api():
    """Get authenticated PortfolioApi. Returns (api, error_str)."""
    client, err = _get_client(authenticated=True)
    if err:
        return None, err
    try:
        from kalshi_python import PortfolioApi
        return PortfolioApi(client), None
    except Exception as e:
        return None, str(e)


def _kalshi_sdk_call(endpoint: str, method: str = "GET", params: dict = None, body: dict = None) -> dict:
    """Route authenticated Kalshi API calls through the SDK's typed API classes."""
    try:
        portfolio, err = _get_portfolio_api()
        if err:
            return {"error": err}

        # Portfolio endpoints
        if endpoint == "/portfolio/balance":
            resp = portfolio.get_balance()
            return {"balance_cents": resp.balance, "balance_usd": f"${resp.balance / 100:.2f}"}

        elif endpoint == "/portfolio/positions":
            limit = (params or {}).get("limit", 50)
            resp = portfolio.get_positions(limit=limit)
            positions = resp.market_positions if hasattr(resp, 'market_positions') else (resp.positions if hasattr(resp, 'positions') else [])
            return {"positions": [p.to_dict() if hasattr(p, 'to_dict') else str(p) for p in (positions or [])]}

        elif endpoint == "/portfolio/fills":
            limit = (params or {}).get("limit", 50)
            resp = portfolio.get_fills(limit=limit)
            fills = resp.fills if hasattr(resp, 'fills') else []
            return {"fills": [f.to_dict() if hasattr(f, 'to_dict') else str(f) for f in (fills or [])]}

        elif endpoint == "/portfolio/settlements":
            limit = (params or {}).get("limit", 50)
            resp = portfolio.get_settlements(limit=limit)
            settlements = resp.settlements if hasattr(resp, 'settlements') else []
            return {"settlements": [s.to_dict() if hasattr(s, 'to_dict') else str(s) for s in (settlements or [])]}

        elif endpoint == "/portfolio/orders" and method == "GET":
            resp = portfolio.get_orders()
            orders = resp.orders if hasattr(resp, 'orders') else []
            return {"orders": [o.to_dict() if hasattr(o, 'to_dict') else str(o) for o in (orders or [])]}

        elif endpoint == "/portfolio/orders" and method == "POST":
            from kalshi_python import CreateOrderRequest
            req = CreateOrderRequest(**body)
            resp = portfolio.create_order(req)
            return resp.to_dict() if hasattr(resp, 'to_dict') else {"result": str(resp)}

        elif endpoint.startswith("/portfolio/orders/") and method == "DELETE":
            order_id = endpoint.split("/")[-1]
            resp = portfolio.cancel_order(order_id)
            return resp.to_dict() if hasattr(resp, 'to_dict') else {"result": str(resp)}

        elif endpoint == "/portfolio/orders" and method == "DELETE":
            from kalshi_python import BatchCancelOrdersRequest
            resp = portfolio.batch_cancel_orders(BatchCancelOrdersRequest())
            return resp.to_dict() if hasattr(resp, 'to_dict') else {"result": str(resp)}

        else:
            return {"error": f"Unhandled authenticated endpoint: {method} {endpoint}"}

    except Exception as e:
        return {"error": f"Kalshi SDK error: {str(e)[:500]}"}


def _get_client(authenticated: bool = False):
    """Get Kalshi API client. Returns (client, error_str)."""
    if not KALSHI_SDK_AVAILABLE:
        return None, "kalshi-python SDK not installed. Run: pip3 install kalshi-python"

    try:
        config = kalshi_python.Configuration()
        config.host = "https://api.elections.kalshi.com/trade-api/v2"
        client = KalshiClient(configuration=config)

        if authenticated:
            key_id = os.environ.get("KALSHI_API_KEY_ID", "")
            key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "./data/trading/kalshi_private.pem")

            if not key_id:
                return None, "KALSHI_API_KEY_ID not set. Generate API key at kalshi.com/account/api"

            if not os.path.exists(key_path):
                return None, f"Kalshi private key not found at {key_path}. Set KALSHI_PRIVATE_KEY_PATH"

            client.set_kalshi_auth(key_id, key_path)

        return client, None
    except Exception as e:
        return None, f"Kalshi client error: {str(e)}"


def _kalshi_api_call(endpoint: str, method: str = "GET", params: dict = None,
                     body: dict = None, authenticated: bool = False) -> dict:
    """Direct REST call to Kalshi API. Uses SDK client for authenticated calls."""
    import urllib.request
    import urllib.parse

    base = "https://api.elections.kalshi.com/trade-api/v2"

    if authenticated:
        # Use SDK for authenticated calls — it handles RSA signing
        return _kalshi_sdk_call(endpoint, method, params, body)

    url = f"{base}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:500] if e.fp else ""
        return {"error": f"Kalshi API {e.code}: {body_text}"}
    except Exception as e:
        return {"error": f"Kalshi API error: {str(e)[:500]}"}


# ═══════════════════════════════════════════════════════════════════
# TOOL 1: kalshi_markets — Market data (read-only, no auth needed)
# ═══════════════════════════════════════════════════════════════════

def kalshi_markets(action: str, ticker: str = "", query: str = "",
                   event_ticker: str = "", status: str = "",
                   limit: int = 20) -> str:
    """Search and view Kalshi market data.

    Actions:
        search       — Search markets by keyword
        get          — Get specific market by ticker
        orderbook    — Order book for a market
        trades       — Recent trades for a market
        candlesticks — Price history candles
        events       — List events (categories)
    """
    try:
        if action == "search":
            params = {"limit": limit}
            if query:
                params["title"] = query
            if status:
                params["status"] = status
            if event_ticker:
                params["event_ticker"] = event_ticker
            result = _kalshi_api_call("/markets", params=params)
            markets = result.get("markets", [])
            return json.dumps({
                "markets": [{
                    "ticker": m.get("ticker"),
                    "title": m.get("title"),
                    "status": m.get("status"),
                    "yes_price": m.get("yes_bid"),
                    "no_price": m.get("no_bid"),
                    "volume": m.get("volume"),
                    "open_interest": m.get("open_interest"),
                    "close_time": m.get("close_time"),
                    "event_ticker": m.get("event_ticker"),
                } for m in markets[:limit]],
                "count": len(markets),
            })

        elif action == "get":
            if not ticker:
                return json.dumps({"error": "ticker required for get action"})
            result = _kalshi_api_call(f"/markets/{ticker}")
            market = result.get("market", result)
            return json.dumps({
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "subtitle": market.get("subtitle"),
                "status": market.get("status"),
                "yes_bid": market.get("yes_bid"),
                "yes_ask": market.get("yes_ask"),
                "no_bid": market.get("no_bid"),
                "no_ask": market.get("no_ask"),
                "last_price": market.get("last_price"),
                "volume": market.get("volume"),
                "open_interest": market.get("open_interest"),
                "close_time": market.get("close_time"),
                "result": market.get("result"),
                "event_ticker": market.get("event_ticker"),
                "rules_primary": market.get("rules_primary", "")[:500],
            })

        elif action == "orderbook":
            if not ticker:
                return json.dumps({"error": "ticker required for orderbook"})
            result = _kalshi_api_call(f"/markets/{ticker}/orderbook")
            return json.dumps(result)

        elif action == "trades":
            if not ticker:
                return json.dumps({"error": "ticker required for trades"})
            result = _kalshi_api_call(f"/markets/{ticker}/trades", params={"limit": limit})
            return json.dumps(result)

        elif action == "candlesticks":
            if not ticker:
                return json.dumps({"error": "ticker required for candlesticks"})
            result = _kalshi_api_call(f"/markets/{ticker}/candlesticks", params={"limit": limit})
            return json.dumps(result)

        elif action == "events":
            params = {"limit": limit}
            if status:
                params["status"] = status
            result = _kalshi_api_call("/events", params=params)
            events = result.get("events", [])
            return json.dumps({
                "events": [{
                    "event_ticker": e.get("event_ticker"),
                    "title": e.get("title"),
                    "category": e.get("category"),
                    "market_count": len(e.get("markets", [])),
                } for e in events[:limit]],
                "count": len(events),
            })

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: search, get, orderbook, trades, candlesticks, events"})

    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════
# TOOL 2: kalshi_trade — Order placement (safety-checked)
# ═══════════════════════════════════════════════════════════════════

def kalshi_trade(action: str, ticker: str = "", side: str = "yes",
                 price: int = 0, count: int = 1, order_id: str = "",
                 dry_run: Optional[bool] = None) -> str:
    """Place, cancel, and manage Kalshi orders.

    Actions:
        buy         — Limit order to buy YES or NO
        sell        — Limit order to sell a position
        market_buy  — Market order (takes best available price)
        market_sell — Market sell
        cancel      — Cancel a specific order by ID
        cancel_all  — Cancel all open orders
        list_orders — List current open orders

    All orders pass through safety checks. dry_run=True (default) simulates.
    """
    try:
        from trading_safety import _load_config
        cfg = _load_config()

        # Determine dry_run
        is_dry = dry_run if dry_run is not None else cfg.dry_run

        if action in ("buy", "sell", "market_buy", "market_sell"):
            if not ticker:
                return json.dumps({"error": "ticker required for trading"})

            # Safety check
            safety = check_order_safety("kalshi", ticker, side, price or 50, count)
            if not safety["ok"]:
                log_trade("kalshi", action, {
                    "ticker": ticker, "side": side, "price": price, "count": count,
                    "blocked": True, "reason": safety["reason"], "dry_run": is_dry,
                })
                return json.dumps({"blocked": True, "reason": safety["reason"]})

            if is_dry:
                result = {
                    "simulated": True,
                    "action": action,
                    "ticker": ticker,
                    "side": side,
                    "price_cents": price,
                    "count": count,
                    "order_value_usd": f"${(price * count)/100:.2f}",
                    "message": "DRY RUN — no real order placed. Set dry_run=false or trading_safety set_config {dry_run: false} to go live.",
                }
                log_trade("kalshi", action, {**result, "dry_run": True})
                return json.dumps(result)

            # Real order — needs authenticated client
            return _execute_kalshi_order(action, ticker, side, price, count)

        elif action == "cancel":
            if not order_id:
                return json.dumps({"error": "order_id required for cancel"})
            if is_dry:
                result = {"simulated": True, "action": "cancel", "order_id": order_id}
                log_trade("kalshi", "cancel", {**result, "dry_run": True})
                return json.dumps(result)
            return _cancel_kalshi_order(order_id)

        elif action == "cancel_all":
            if is_dry:
                result = {"simulated": True, "action": "cancel_all"}
                log_trade("kalshi", "cancel_all", {**result, "dry_run": True})
                return json.dumps(result)
            return _cancel_all_kalshi_orders()

        elif action == "list_orders":
            return _list_kalshi_orders()

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def _execute_kalshi_order(action: str, ticker: str, side: str,
                          price: int, count: int) -> str:
    """Execute a real Kalshi order via API."""
    try:
        # Determine order type
        if action.startswith("market"):
            order_type = "market"
        else:
            order_type = "limit"

        body = {
            "ticker": ticker,
            "action": "buy" if action in ("buy", "market_buy") else "sell",
            "side": side.lower(),
            "type": order_type,
            "count": count,
        }
        if order_type == "limit" and price > 0:
            body["yes_price"] = price if side.lower() == "yes" else None
            body["no_price"] = price if side.lower() == "no" else None

        result = _kalshi_api_call("/portfolio/orders", method="POST", body=body, authenticated=True)

        log_trade("kalshi", action, {
            "ticker": ticker, "side": side, "price": price, "count": count,
            "order_value_cents": price * count, "dry_run": False,
            "response": str(result)[:500],
        })

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Order execution failed: {str(e)}"})


def _cancel_kalshi_order(order_id: str) -> str:
    result = _kalshi_api_call(f"/portfolio/orders/{order_id}", method="DELETE", authenticated=True)
    log_trade("kalshi", "cancel", {"order_id": order_id, "dry_run": False, "response": str(result)[:500]})
    return json.dumps(result)


def _cancel_all_kalshi_orders() -> str:
    result = _kalshi_api_call("/portfolio/orders", method="DELETE", authenticated=True)
    log_trade("kalshi", "cancel_all", {"dry_run": False, "response": str(result)[:500]})
    return json.dumps(result)


def _list_kalshi_orders() -> str:
    result = _kalshi_api_call("/portfolio/orders", authenticated=True)
    return json.dumps(result)


# ═══════════════════════════════════════════════════════════════════
# TOOL 3: kalshi_portfolio — Portfolio management
# ═══════════════════════════════════════════════════════════════════

def kalshi_portfolio(action: str, limit: int = 50) -> str:
    """View Kalshi portfolio, positions, fills, and settlements.

    Actions:
        balance      — Account balance
        positions    — Current open positions
        fills        — Recent trade fills
        settlements  — Settled positions (resolved markets)
        summary      — Combined overview
    """
    try:
        if action == "balance":
            result = _kalshi_api_call("/portfolio/balance", authenticated=True)
            return json.dumps(result)

        elif action == "positions":
            result = _kalshi_api_call("/portfolio/positions", params={"limit": limit}, authenticated=True)
            return json.dumps(result)

        elif action == "fills":
            result = _kalshi_api_call("/portfolio/fills", params={"limit": limit}, authenticated=True)
            return json.dumps(result)

        elif action == "settlements":
            result = _kalshi_api_call("/portfolio/settlements", params={"limit": limit}, authenticated=True)
            return json.dumps(result)

        elif action == "summary":
            # Aggregate multiple calls
            balance = _kalshi_api_call("/portfolio/balance", authenticated=True)
            positions = _kalshi_api_call("/portfolio/positions", params={"limit": 10}, authenticated=True)
            fills = _kalshi_api_call("/portfolio/fills", params={"limit": 5}, authenticated=True)

            return json.dumps({
                "balance": balance,
                "positions": positions,
                "recent_fills": fills,
            })

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: balance, positions, fills, settlements, summary"})

    except Exception as e:
        return json.dumps({"error": str(e)})
