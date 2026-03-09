"""
Polymarket Trading Module — Phase 2: Full Trading Engine

Uses Cloudflare Worker proxy (polymarket-proxy) to access Polymarket APIs
from the US VPS. All requests route through the edge proxy to bypass geoblock.

APIs:
  - Gamma API (gamma-api.polymarket.com) — market search, data, profiles
  - CLOB API (clob.polymarket.com) — order book, midpoints, trading

Proxy URL: https://polymarket-proxy.amit-shah-5201.workers.dev
"""

import json
import os
import urllib.request
import urllib.parse
from typing import Optional

# API base URLs — direct calls work from VPS for reads
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

# Proxy URL for trading (may need proxy for write operations if geoblocked)
PROXY_URL = os.environ.get("POLYMARKET_PROXY_URL", "")

API_BASES = {"gamma": GAMMA_BASE, "clob": CLOB_BASE}


def _api_get(api: str, path: str, params: dict = None, timeout: int = 15) -> dict:
    """Direct GET request to Polymarket API."""
    base = API_BASES.get(api, GAMMA_BASE)
    url = f"{base}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url += f"?{qs}"

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if e.fp else ""
        return {"error": f"Polymarket API {e.code}: {body}"}
    except Exception as e:
        return {"error": f"API request failed: {str(e)[:500]}"}


def _api_post(api: str, path: str, body: dict = None, extra_headers: dict = None,
              timeout: int = 15) -> dict:
    """POST request to Polymarket API. Uses proxy if configured (for geoblock bypass)."""
    # Use proxy for write operations if available
    if PROXY_URL and api == "clob":
        base = f"{PROXY_URL}/clob"
    else:
        base = API_BASES.get(api, GAMMA_BASE)

    url = f"{base}{path}"
    data = json.dumps(body or {}).encode()
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)",
    }
    if extra_headers:
        hdrs.update(extra_headers)

    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:500] if e.fp else ""
        return {"error": f"Polymarket API {e.code}: {body_text}"}
    except Exception as e:
        return {"error": f"API request failed: {str(e)[:500]}"}


def _search_markets(query: str = "", limit: int = 20, active: bool = True,
                    closed: bool = False) -> list:
    """Search Polymarket markets via Gamma API. Returns list of market dicts."""
    params = {"limit": limit, "active": str(active).lower(), "closed": str(closed).lower()}
    if query:
        params["_q"] = query
    result = _api_get("gamma", "/markets", params=params)
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "error" not in result:
        return result.get("markets", result.get("data", []))
    return []


def _get_market(slug_or_id: str) -> dict:
    """Get a single market by slug or condition_id from Gamma API."""
    # Try slug first
    result = _api_get("gamma", f"/markets/{slug_or_id}")
    if isinstance(result, dict) and "error" not in result and result.get("question"):
        return result
    # Try as search
    markets = _search_markets(query=slug_or_id, limit=5)
    for m in markets:
        if m.get("slug") == slug_or_id or m.get("conditionId") == slug_or_id:
            return m
    if markets:
        return markets[0]
    return {"error": f"Market '{slug_or_id}' not found"}


def _resolve_token_ids(market_id: str) -> dict:
    """Resolve a market slug/ID to YES and NO CLOB token IDs."""
    market = _get_market(market_id)
    if "error" in market:
        return market

    raw_tokens = market.get("clobTokenIds", "")
    if isinstance(raw_tokens, str):
        try:
            tokens = json.loads(raw_tokens)
        except json.JSONDecodeError:
            tokens = []
    else:
        tokens = raw_tokens or []

    if len(tokens) < 2:
        return {"error": f"Market '{market_id}' has no CLOB token IDs"}

    return {
        "yes_token": tokens[0],
        "no_token": tokens[1],
        "question": market.get("question", ""),
        "condition_id": market.get("conditionId", ""),
        "slug": market.get("slug", market_id),
        "market_id": market.get("id", ""),
        "outcomes": market.get("outcomes", ""),
        "active": market.get("active", False),
        "closed": market.get("closed", False),
    }


def _extract_price(data) -> Optional[float]:
    """Extract a numeric price from API response."""
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, str):
        try:
            return float(data)
        except ValueError:
            return None
    if isinstance(data, dict):
        if "error" in data:
            return None
        for key in ("mid", "midpoint", "price", "value", "mid_price"):
            if key in data:
                try:
                    return float(data[key])
                except (ValueError, TypeError):
                    pass
    return None


# ═══════════════════════════════════════════════════════════════════
# TOOL 1: polymarket_prices — Real-time price data
# ═══════════════════════════════════════════════════════════════════

def polymarket_prices(action: str, market_id: str = "",
                      token_id: str = "", interval: str = "1d",
                      fidelity: int = 0) -> str:
    """Get real-time price data for Polymarket markets.

    Actions:
        snapshot   — Full price snapshot (midpoint, spread, last trade, mispricing flag)
        spread     — Bid-ask spread for a token
        midpoint   — Midpoint price for a token
        book       — Full order book for a token
        last_trade — Last trade price for a token
        history    — Price history for a token (requires interval)
    """
    try:
        if action == "snapshot":
            return _snapshot(market_id)

        # Resolve token_id if only market_id given
        tid = token_id
        if not tid and market_id:
            resolved = _resolve_token_ids(market_id)
            if "error" in resolved:
                return json.dumps(resolved)
            tid = resolved["yes_token"]

        if not tid:
            return json.dumps({"error": "Provide market_id (slug/ID) or token_id"})

        if action == "spread":
            result = _api_get("clob", f"/spread", params={"token_id": tid})
            return json.dumps(result)
        elif action == "midpoint":
            result = _api_get("clob", f"/midpoint", params={"token_id": tid})
            return json.dumps(result)
        elif action == "book":
            result = _api_get("clob", f"/book", params={"token_id": tid})
            return json.dumps(result)
        elif action == "last_trade":
            result = _api_get("clob", f"/last-trade-price", params={"token_id": tid})
            return json.dumps(result)
        elif action == "history":
            params = {"token_id": tid, "interval": interval}
            if fidelity > 0:
                params["fidelity"] = fidelity
            result = _api_get("clob", "/prices-history", params=params, timeout=20)
            return json.dumps(result)
        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: snapshot, spread, midpoint, book, last_trade, history"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _snapshot(market_id: str) -> str:
    """Full price snapshot — resolves tokens, gets midpoint+spread+last for both YES and NO."""
    if not market_id:
        return json.dumps({"error": "market_id required for snapshot"})

    resolved = _resolve_token_ids(market_id)
    if "error" in resolved:
        return json.dumps(resolved)

    yes_token = resolved["yes_token"]
    no_token = resolved["no_token"]

    # Fetch prices via CLOB API
    yes_mid = _api_get("clob", "/midpoint", params={"token_id": yes_token})
    no_mid = _api_get("clob", "/midpoint", params={"token_id": no_token})
    yes_spread = _api_get("clob", "/spread", params={"token_id": yes_token})
    yes_last = _api_get("clob", "/last-trade-price", params={"token_id": yes_token})

    yes_price = _extract_price(yes_mid)
    no_price = _extract_price(no_mid)

    mispricing = None
    if yes_price is not None and no_price is not None:
        total = yes_price + no_price
        deviation = abs(total - 1.0)
        mispricing = {
            "yes_plus_no": round(total, 6),
            "deviation_from_1": round(deviation, 6),
            "is_mispriced": deviation > 0.02,
            "arb_opportunity": deviation > 0.05,
        }

    return json.dumps({
        "market": {
            "question": resolved["question"],
            "slug": resolved["slug"],
            "market_id": resolved["market_id"],
            "active": resolved["active"],
            "closed": resolved["closed"],
        },
        "yes": {"token_id": yes_token, "midpoint": yes_mid, "spread": yes_spread, "last_trade": yes_last},
        "no": {"token_id": no_token, "midpoint": no_mid},
        "mispricing": mispricing,
    })


# ═══════════════════════════════════════════════════════════════════
# TOOL 2: polymarket_monitor — Market monitoring & arb detection
# ═══════════════════════════════════════════════════════════════════

def polymarket_monitor(action: str, market_id: str = "",
                       condition_id: str = "", event_id: str = "",
                       period: str = "week", order_by: str = "pnl",
                       limit: int = 10) -> str:
    """Monitor markets, detect mispricings, view on-chain data.

    Actions:
        mispricing    — Check if YES+NO prices deviate from $1.00
        open_interest — Open interest for a market
        volume        — Live volume for an event
        holders       — Top token holders for a market
        leaderboard   — Top traders by PnL or volume
        health        — CLOB API health status
    """
    try:
        if action == "mispricing":
            return _check_mispricing(market_id)

        elif action == "open_interest":
            cid = condition_id
            if not cid and market_id:
                resolved = _resolve_token_ids(market_id)
                if "error" in resolved:
                    return json.dumps(resolved)
                cid = resolved["condition_id"]
            if not cid:
                return json.dumps({"error": "Provide condition_id or market_id"})
            result = _api_get("gamma", f"/markets/{cid}")
            oi = result.get("openInterest", result.get("open_interest", "unknown"))
            return json.dumps({"condition_id": cid, "open_interest": oi})

        elif action == "volume":
            if not event_id:
                return json.dumps({"error": "event_id required for volume"})
            result = _api_get("gamma", f"/events/{event_id}")
            return json.dumps({"event_id": event_id, "volume": result.get("volume", "unknown")})

        elif action == "holders":
            cid = condition_id
            if not cid and market_id:
                resolved = _resolve_token_ids(market_id)
                if "error" in resolved:
                    return json.dumps(resolved)
                cid = resolved["condition_id"]
            if not cid:
                return json.dumps({"error": "Provide condition_id or market_id"})
            # Gamma API doesn't have a direct holders endpoint; use CLOB
            result = _api_get("gamma", f"/markets/{cid}")
            return json.dumps({"condition_id": cid, "data": result})

        elif action == "leaderboard":
            # Gamma leaderboard
            result = _api_get("gamma", "/leaderboard", params={
                "period": period, "order_by": order_by, "limit": limit
            })
            return json.dumps(result)

        elif action == "health":
            result = _api_get("clob", "/")
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: mispricing, open_interest, volume, holders, leaderboard, health"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _check_mispricing(market_id: str) -> str:
    """Check a market for YES+NO price deviation from $1.00."""
    if not market_id:
        return json.dumps({"error": "market_id required for mispricing check"})

    resolved = _resolve_token_ids(market_id)
    if "error" in resolved:
        return json.dumps(resolved)

    yes_mid = _api_get("clob", "/midpoint", params={"token_id": resolved["yes_token"]})
    no_mid = _api_get("clob", "/midpoint", params={"token_id": resolved["no_token"]})

    yes_price = _extract_price(yes_mid)
    no_price = _extract_price(no_mid)

    if yes_price is None or no_price is None:
        return json.dumps({
            "market": resolved["question"],
            "slug": resolved["slug"],
            "error": "Could not get midpoint prices",
            "yes_raw": yes_mid, "no_raw": no_mid,
        })

    total = yes_price + no_price
    deviation = abs(total - 1.0)

    return json.dumps({
        "market": resolved["question"],
        "slug": resolved["slug"],
        "yes_midpoint": yes_price,
        "no_midpoint": no_price,
        "sum": round(total, 6),
        "deviation": round(deviation, 6),
        "is_mispriced": deviation > 0.02,
        "arb_opportunity": deviation > 0.05,
        "analysis": (
            f"YES={yes_price:.4f} + NO={no_price:.4f} = {total:.4f}. "
            f"Deviation: {deviation:.4f} from $1.00. "
            + ("ARBITRAGE OPPORTUNITY!" if deviation > 0.05
               else "Notable mispricing." if deviation > 0.02
               else "Prices are fair.")
        ),
    })


# ═══════════════════════════════════════════════════════════════════
# TOOL 3: polymarket_portfolio — Wallet/portfolio viewing
# ═══════════════════════════════════════════════════════════════════

def polymarket_portfolio(action: str, address: str = "",
                         limit: int = 25) -> str:
    """View any wallet's positions, trades, and on-chain activity (read-only).

    Actions:
        positions  — Open positions for a wallet
        closed     — Closed/resolved positions
        trades     — Trade history for a wallet
        value      — Total portfolio value
        activity   — On-chain activity log
        profile    — Public profile info
    """
    try:
        if not address:
            return json.dumps({"error": "address (0x...) required for portfolio queries"})

        if action == "positions":
            result = _api_get("gamma", f"/positions", params={"user": address, "limit": limit})
            return json.dumps(result)
        elif action == "closed":
            result = _api_get("gamma", f"/positions", params={"user": address, "redeemed": "true", "limit": limit})
            return json.dumps(result)
        elif action == "trades":
            result = _api_get("gamma", f"/trades", params={"maker": address, "limit": limit})
            return json.dumps(result)
        elif action == "value":
            result = _api_get("gamma", f"/positions", params={"user": address})
            return json.dumps({"address": address, "positions": result})
        elif action == "activity":
            result = _api_get("gamma", f"/activity", params={"address": address, "limit": limit})
            return json.dumps(result)
        elif action == "profile":
            result = _api_get("gamma", f"/profiles/{address}")
            return json.dumps(result)
        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: positions, closed, trades, value, activity, profile"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════
# TOOL 4: polymarket_trade — Order placement (safety-checked)
# ═══════════════════════════════════════════════════════════════════

def polymarket_trade(action: str, market_id: str = "", side: str = "yes",
                     price: float = 0.0, size: float = 0.0,
                     order_id: str = "", dry_run: Optional[bool] = None) -> str:
    """Place, cancel, and manage Polymarket orders.

    Routes through Cloudflare proxy to bypass US geoblock.
    All orders pass through safety checks. dry_run=True (default) simulates.
    """
    try:
        from trading_safety import check_order_safety, log_trade, _load_config
        cfg = _load_config()
        is_dry = dry_run if dry_run is not None else cfg.dry_run

        if action in ("buy", "sell", "market_buy", "market_sell"):
            if not market_id:
                return json.dumps({"error": "market_id required for trading"})

            price_cents = int(price * 100) if price else 50
            count = max(int(size), 1)

            safety = check_order_safety("polymarket", market_id, side, price_cents, count)
            if not safety["ok"]:
                log_trade("polymarket", action, {
                    "market_id": market_id, "side": side, "price": price, "size": size,
                    "blocked": True, "reason": safety["reason"], "dry_run": is_dry,
                })
                return json.dumps({"blocked": True, "reason": safety["reason"]})

            if is_dry:
                resolved = _resolve_token_ids(market_id)
                token_info = {}
                if "error" not in resolved:
                    token_info = {
                        "token_id": resolved["yes_token"] if side.lower() == "yes" else resolved["no_token"],
                        "question": resolved["question"],
                    }

                result = {
                    "simulated": True, "action": action, "market_id": market_id,
                    "side": side, "price": price, "size": size,
                    "order_value_usd": f"${price * size:.2f}" if price and size else "market price",
                    **token_info,
                    "message": "DRY RUN — no real order placed. Set dry_run=false to go live.",
                }
                log_trade("polymarket", action, {**result, "dry_run": True})
                return json.dumps(result)

            # Real order via CLOB API through proxy
            return _execute_polymarket_order(action, market_id, side, price, size)

        elif action == "cancel":
            if not order_id:
                return json.dumps({"error": "order_id required for cancel"})
            if is_dry:
                result = {"simulated": True, "action": "cancel", "order_id": order_id}
                log_trade("polymarket", "cancel", {**result, "dry_run": True})
                return json.dumps(result)
            result = _api_post("clob", f"/cancel", body={"orderID": order_id})
            return json.dumps(result)

        elif action == "cancel_all":
            if is_dry:
                result = {"simulated": True, "action": "cancel_all"}
                log_trade("polymarket", "cancel_all", {**result, "dry_run": True})
                return json.dumps(result)
            result = _api_post("clob", "/cancel-all")
            return json.dumps(result)

        elif action == "list_orders":
            result = _api_get("clob", "/orders")
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def _execute_polymarket_order(action: str, market_id: str, side: str,
                              price: float, size: float) -> str:
    """Execute a real Polymarket order via CLOB API through proxy."""
    from trading_safety import log_trade

    resolved = _resolve_token_ids(market_id)
    if "error" in resolved:
        return json.dumps(resolved)

    token_id = resolved["yes_token"] if side.lower() == "yes" else resolved["no_token"]

    if action in ("market_buy", "market_sell"):
        body = {
            "tokenID": token_id,
            "amount": size,
            "side": "BUY" if action == "market_buy" else "SELL",
        }
        result = _api_post("clob", "/market-order", body=body, timeout=30)
    else:
        body = {
            "tokenID": token_id,
            "price": price,
            "size": size,
            "side": "BUY" if action == "buy" else "SELL",
        }
        result = _api_post("clob", "/order", body=body, timeout=30)

    log_trade("polymarket", action, {
        "market_id": market_id, "side": side, "price": price, "size": size,
        "via": "proxy", "dry_run": False, "response": str(result)[:500],
    })

    return json.dumps(result)


# ═══════════════════════════════════════════════════════════════════
# TOOL 5: polymarket_balance — Wallet balance and approval status
# ═══════════════════════════════════════════════════════════════════

def polymarket_balance(action: str = "balance") -> str:
    """Check Polymarket wallet balance and approval status."""
    try:
        if action == "balance":
            result = _api_get("clob", "/balance")
            return json.dumps(result)
        elif action == "approval":
            result = _api_get("clob", "/check-approval")
            return json.dumps(result)
        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: balance, approval"})
    except Exception as e:
        return json.dumps({"error": str(e)})
