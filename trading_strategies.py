"""
Trading Strategies Engine — Automated opportunity scanners across Polymarket and Kalshi.

Combines arb scanner, bond finder, and market intelligence into actionable strategies.
"""

import json
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# Main strategies function
# ═══════════════════════════════════════════════════════════════════

def trading_strategies(action: str, params: Optional[dict] = None) -> str:
    """Automated trading opportunity scanners.

    Actions:
        bonds       — Scan both platforms for >90% contracts near expiry
        mispricing  — Cross-platform price gaps
        whale_alerts — Monitor top Polymarket wallets for new positions
        trending    — Markets with volume spikes
        expiring    — Markets closing soon with predictable outcomes
        summary     — Run all scanners, return combined report
    """
    params = params or {}

    try:
        if action == "bonds":
            return _strategy_bonds(params)
        elif action == "mispricing":
            return _strategy_mispricing(params)
        elif action == "whale_alerts":
            return _strategy_whale_alerts(params)
        elif action == "trending":
            return _strategy_trending(params)
        elif action == "expiring":
            return _strategy_expiring(params)
        elif action == "summary":
            return _strategy_summary(params)
        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: bonds, mispricing, whale_alerts, trending, expiring, summary"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _strategy_bonds(params: dict) -> str:
    """Find high-probability contracts — the safest prediction market play."""
    from arb_scanner import arb_scan
    query = params.get("query", "")
    max_results = params.get("max_results", 15)
    return arb_scan("bonds", query=query, max_results=max_results)


def _strategy_mispricing(params: dict) -> str:
    """Find cross-platform and single-platform mispricings."""
    from arb_scanner import arb_scan

    query = params.get("query", "")
    max_results = params.get("max_results", 10)
    min_edge = params.get("min_edge", 0.02)

    # Get both cross-platform arb and single-platform mispricing
    cross = json.loads(arb_scan("scan", query=query, min_edge=min_edge, max_results=max_results))
    single = json.loads(arb_scan("mispricing", query=query, max_results=max_results))

    return json.dumps({
        "cross_platform_arb": cross.get("matches", []),
        "single_platform_mispricing": single.get("mispricings", []),
        "total_opportunities": len(cross.get("matches", [])) + len(single.get("mispricings", [])),
    })


def _strategy_whale_alerts(params: dict) -> str:
    """Monitor top Polymarket wallets for new positions."""
    try:
        from polymarket_trading import polymarket_monitor

        # Get leaderboard first
        leaders = json.loads(polymarket_monitor(
            "leaderboard", period=params.get("period", "week"),
            order_by="pnl", limit=params.get("limit", 5)
        ))

        if "error" in leaders:
            return json.dumps({"error": f"Could not fetch leaderboard: {leaders['error']}",
                              "suggestion": "Try polymarket_monitor(action='leaderboard') directly"})

        # Get top wallets from leaderboard
        whale_data = []
        leader_list = leaders if isinstance(leaders, list) else leaders.get("data", leaders.get("leaderboard", []))

        if isinstance(leader_list, list):
            for whale in leader_list[:5]:
                addr = whale.get("address", whale.get("wallet", ""))
                if not addr:
                    continue
                # Fetch recent positions
                from polymarket_trading import polymarket_portfolio
                positions = json.loads(polymarket_portfolio("positions", address=addr, limit=5))
                whale_data.append({
                    "address": addr[:10] + "..." + addr[-6:] if len(addr) > 16 else addr,
                    "pnl": whale.get("pnl", whale.get("profit", "?")),
                    "recent_positions": positions if "error" not in positions else "unavailable",
                })

        return json.dumps({
            "whales": whale_data,
            "count": len(whale_data),
            "note": "Whale tracking shows what top traders are buying. Not investment advice.",
        })
    except Exception as e:
        return json.dumps({"error": f"Whale tracking failed: {str(e)}"})


def _strategy_trending(params: dict) -> str:
    """Find markets with high recent volume — indicates news or big moves."""
    try:
        from kalshi_trading import _kalshi_api_call

        # Kalshi trending — sort by volume
        kalshi_result = _kalshi_api_call("/markets", params={
            "limit": params.get("limit", 15),
            "status": "open",
        })
        kalshi_markets = kalshi_result.get("markets", [])
        # Sort by volume descending
        kalshi_markets.sort(key=lambda m: m.get("volume", 0), reverse=True)

        trending = []
        for m in kalshi_markets[:params.get("limit", 10)]:
            trending.append({
                "platform": "kalshi",
                "title": m.get("title", ""),
                "ticker": m.get("ticker", ""),
                "volume": m.get("volume", 0),
                "open_interest": m.get("open_interest", 0),
                "yes_price": m.get("yes_bid"),
                "close_time": m.get("close_time"),
            })

        # Polymarket trending
        from polymarket_trading import _search_markets
        poly_markets = _search_markets(limit=15, active=True, closed=False)
        poly_markets.sort(key=lambda m: float(m.get("volumeNum", 0) or m.get("volume", 0) or 0), reverse=True)
        for m in poly_markets[:params.get("limit", 10)]:
            trending.append({
                "platform": "polymarket",
                "title": m.get("question", m.get("title", "")),
                "slug": m.get("slug", ""),
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
            })

        return json.dumps({
            "trending": trending,
            "count": len(trending),
        })
    except Exception as e:
        return json.dumps({"error": f"Trending scan failed: {str(e)}"})


def _strategy_expiring(params: dict) -> str:
    """Find markets closing soon — these tend to converge to 0 or 100."""
    try:
        from kalshi_trading import _kalshi_api_call
        import time

        kalshi_result = _kalshi_api_call("/markets", params={
            "limit": 50,
            "status": "open",
        })
        kalshi_markets = kalshi_result.get("markets", [])

        # Filter to markets closing within the next N hours
        hours = params.get("hours", 48)
        now = time.time()
        cutoff = now + (hours * 3600)

        expiring = []
        for m in kalshi_markets:
            close_time = m.get("close_time", "")
            if not close_time:
                continue
            # Parse ISO time
            try:
                import datetime
                ct = datetime.datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                close_ts = ct.timestamp()
            except (ValueError, AttributeError):
                continue

            if close_ts > cutoff or close_ts < now:
                continue

            hours_left = (close_ts - now) / 3600
            yes_price = m.get("yes_bid") or m.get("last_price")
            if yes_price is None:
                continue
            yes_p = float(yes_price) / 100 if float(yes_price) > 1 else float(yes_price)

            expiring.append({
                "platform": "kalshi",
                "title": m.get("title", ""),
                "ticker": m.get("ticker", ""),
                "hours_left": round(hours_left, 1),
                "yes_price": yes_p,
                "conviction": "strong YES" if yes_p > 0.85 else "strong NO" if yes_p < 0.15 else "uncertain",
                "close_time": close_time,
            })

        expiring.sort(key=lambda x: x["hours_left"])

        return json.dumps({
            "expiring": expiring[:params.get("limit", 15)],
            "count": len(expiring),
            "hours_window": hours,
            "strategy": "Markets closing soon with high conviction (>85% or <15%) are likely to resolve as priced. "
                        "Buy the dominant side for small but near-certain gains.",
        })
    except Exception as e:
        return json.dumps({"error": f"Expiring scan failed: {str(e)}"})


def _strategy_summary(params: dict) -> str:
    """Run all scanners and return a combined report."""
    results = {}

    try:
        results["bonds"] = json.loads(_strategy_bonds({"max_results": 5}))
    except Exception as e:
        results["bonds"] = {"error": str(e)}

    try:
        results["mispricing"] = json.loads(_strategy_mispricing({"max_results": 5}))
    except Exception as e:
        results["mispricing"] = {"error": str(e)}

    try:
        results["trending"] = json.loads(_strategy_trending({"limit": 5}))
    except Exception as e:
        results["trending"] = {"error": str(e)}

    try:
        results["expiring"] = json.loads(_strategy_expiring({"hours": 24, "limit": 5}))
    except Exception as e:
        results["expiring"] = {"error": str(e)}

    # Count total opportunities
    total = 0
    total += len(results.get("bonds", {}).get("bonds", []))
    total += results.get("mispricing", {}).get("total_opportunities", 0)
    total += len(results.get("trending", {}).get("trending", []))
    total += len(results.get("expiring", {}).get("expiring", []))

    return json.dumps({
        **results,
        "total_opportunities": total,
        "note": "This is market intelligence, not investment advice. All trades are dry-run by default.",
    })
