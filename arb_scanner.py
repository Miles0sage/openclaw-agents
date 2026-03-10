"""
Cross-Platform Arbitrage Scanner — Polymarket + Kalshi

Finds price discrepancies, mispriced markets, high-probability bonds,
and cross-platform arbitrage opportunities.
"""

import json
import re
from difflib import SequenceMatcher
from typing import Optional


def _get_polymarket_markets(query: str = "", limit: int = 20) -> list:
    """Fetch Polymarket markets via proxy API."""
    try:
        from polymarket_trading import _search_markets
        return _search_markets(query=query, limit=limit, active=True, closed=False)
    except Exception:
        return []


def _get_kalshi_markets(query: str = "", limit: int = 20) -> list:
    """Fetch Kalshi markets via API."""
    try:
        from kalshi_trading import _kalshi_api_call
        params = {"limit": limit}
        if query:
            params["title"] = query
        params["status"] = "open"
        result = _kalshi_api_call("/markets", params=params)
        return result.get("markets", [])
    except Exception:
        return []


def _fuzzy_match(title_a: str, title_b: str) -> float:
    """Fuzzy match score between two event titles (0-1)."""
    # Normalize
    a = re.sub(r'[^\w\s]', '', title_a.lower()).strip()
    b = re.sub(r'[^\w\s]', '', title_b.lower()).strip()
    return SequenceMatcher(None, a, b).ratio()


def _extract_price(market: dict, platform: str) -> Optional[float]:
    """Extract YES price from a market dict."""
    if platform == "polymarket":
        for key in ("outcomePrices", "outcomes_prices"):
            val = market.get(key)
            if val:
                if isinstance(val, str):
                    try:
                        prices = json.loads(val)
                        return float(prices[0]) if prices else None
                    except (json.JSONDecodeError, IndexError, TypeError):
                        pass
                elif isinstance(val, list) and val:
                    return float(val[0])
        # Try bestBid
        best = market.get("bestBid") or market.get("best_bid")
        if best:
            return float(best)
    elif platform == "kalshi":
        for key in ("yes_bid", "last_price", "yes_price"):
            val = market.get(key)
            if val is not None:
                return float(val) / 100 if float(val) > 1 else float(val)
    return None


def _extract_title(market: dict, platform: str) -> str:
    """Extract title/question from a market dict."""
    if platform == "polymarket":
        return market.get("question", market.get("title", ""))
    elif platform == "kalshi":
        return market.get("title", "")
    return ""


# ═══════════════════════════════════════════════════════════════════
# Main arb_scan function
# ═══════════════════════════════════════════════════════════════════

def arb_scan(action: str, query: str = "", min_edge: float = 0.02,
             max_results: int = 10) -> str:
    """Cross-platform arbitrage scanner.

    Actions:
        scan       — Auto-find matching events across platforms, compare prices
        compare    — Compare specific event keyword across platforms
        bonds      — High-probability contracts (>90% YES or NO, near expiry = safe bets)
        mispricing — Single-platform YES+NO != $1.00 markets
    """
    try:
        if action == "scan" or action == "compare":
            return _cross_platform_scan(query, min_edge, max_results)

        elif action == "bonds":
            return _find_bonds(query, max_results)

        elif action == "mispricing":
            return _find_mispricing(query, max_results)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: scan, compare, bonds, mispricing"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def _cross_platform_scan(query: str, min_edge: float, max_results: int) -> str:
    """Find matching markets across Polymarket and Kalshi, compare prices."""
    # Fetch from both platforms
    poly_markets = _get_polymarket_markets(query, limit=30)
    kalshi_markets = _get_kalshi_markets(query, limit=30)

    if not poly_markets and not kalshi_markets:
        return json.dumps({"error": "Could not fetch markets from either platform", "query": query})

    matches = []
    for pm in poly_markets:
        pm_title = _extract_title(pm, "polymarket")
        pm_price = _extract_price(pm, "polymarket")
        if not pm_title or pm_price is None:
            continue

        for km in kalshi_markets:
            km_title = _extract_title(km, "kalshi")
            km_price = _extract_price(km, "kalshi")
            if not km_title or km_price is None:
                continue

            similarity = _fuzzy_match(pm_title, km_title)
            if similarity < 0.5:
                continue

            edge = abs(pm_price - km_price)
            if edge < min_edge:
                continue

            # Determine direction
            if pm_price > km_price:
                direction = f"Buy on Kalshi ({km_price:.2f}), sell on Polymarket ({pm_price:.2f})"
            else:
                direction = f"Buy on Polymarket ({pm_price:.2f}), sell on Kalshi ({km_price:.2f})"

            # Estimate profit after fees (~2% Polymarket, ~1% Kalshi spread)
            net_edge = edge - 0.03  # Rough fee estimate

            matches.append({
                "polymarket": {
                    "title": pm_title,
                    "slug": pm.get("slug", pm.get("id", "")),
                    "yes_price": pm_price,
                },
                "kalshi": {
                    "title": km_title,
                    "ticker": km.get("ticker", ""),
                    "yes_price": km_price,
                },
                "similarity": round(similarity, 2),
                "edge": round(edge, 4),
                "net_edge_after_fees": round(net_edge, 4),
                "profitable": net_edge > 0,
                "direction": direction,
            })

    # Sort by edge descending
    matches.sort(key=lambda x: x["edge"], reverse=True)

    return json.dumps({
        "matches": matches[:max_results],
        "count": len(matches),
        "polymarket_markets_scanned": len(poly_markets),
        "kalshi_markets_scanned": len(kalshi_markets),
        "min_edge_filter": min_edge,
        "query": query or "(all active markets)",
    })


def _find_bonds(query: str, max_results: int) -> str:
    """Find high-probability contracts (>90% YES or NO) — the 'bond' strategy."""
    bonds = []

    # Polymarket bonds
    poly_markets = _get_polymarket_markets(query, limit=50)
    for m in poly_markets:
        price = _extract_price(m, "polymarket")
        title = _extract_title(m, "polymarket")
        if price is None or not title:
            continue
        # High conviction: YES > 0.90 or NO > 0.90 (YES < 0.10)
        if price > 0.90:
            bonds.append({
                "platform": "polymarket",
                "title": title,
                "slug": m.get("slug", ""),
                "side": "YES",
                "price": price,
                "potential_return": round((1.0 - price) / price * 100, 1),
                "confidence": "high" if price > 0.95 else "moderate",
            })
        elif price < 0.10:
            bonds.append({
                "platform": "polymarket",
                "title": title,
                "slug": m.get("slug", ""),
                "side": "NO",
                "price": round(1.0 - price, 4),
                "potential_return": round(price / (1.0 - price) * 100, 1),
                "confidence": "high" if price < 0.05 else "moderate",
            })

    # Kalshi bonds
    kalshi_mkts = _get_kalshi_markets(query, limit=50)
    for m in kalshi_mkts:
        price = _extract_price(m, "kalshi")
        title = _extract_title(m, "kalshi")
        if price is None or not title:
            continue
        if price > 0.90:
            bonds.append({
                "platform": "kalshi",
                "title": title,
                "ticker": m.get("ticker", ""),
                "side": "YES",
                "price": price,
                "potential_return": round((1.0 - price) / price * 100, 1),
                "confidence": "high" if price > 0.95 else "moderate",
            })
        elif price < 0.10:
            bonds.append({
                "platform": "kalshi",
                "title": title,
                "ticker": m.get("ticker", ""),
                "side": "NO",
                "price": round(1.0 - price, 4),
                "potential_return": round(price / (1.0 - price) * 100, 1),
                "confidence": "high" if price < 0.05 else "moderate",
            })

    # Sort by confidence (price closest to 1.0)
    bonds.sort(key=lambda x: x["price"], reverse=True)

    return json.dumps({
        "bonds": bonds[:max_results],
        "count": len(bonds),
        "strategy": "Buy high-probability contracts near expiry. If resolved YES, collect $1.00 per contract. "
                     "Risk: event doesn't resolve as expected. Lower price = higher risk but higher return.",
    })


def _find_mispricing(query: str, max_results: int) -> str:
    """Find markets where YES + NO != $1.00 on a single platform."""
    mispricings = []

    # Check Polymarket
    poly_markets = _get_polymarket_markets(query, limit=30)
    for m in poly_markets:
        title = _extract_title(m, "polymarket")
        prices_raw = m.get("outcomePrices") or m.get("outcomes_prices")
        if not prices_raw or not title:
            continue

        try:
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw
            if len(prices) >= 2:
                yes_p = float(prices[0])
                no_p = float(prices[1])
                total = yes_p + no_p
                deviation = abs(total - 1.0)
                if deviation > 0.02:
                    mispricings.append({
                        "platform": "polymarket",
                        "title": title,
                        "slug": m.get("slug", ""),
                        "yes_price": yes_p,
                        "no_price": no_p,
                        "sum": round(total, 4),
                        "deviation": round(deviation, 4),
                        "opportunity": "BUY both" if total < 0.98 else "SELL both" if total > 1.02 else "small",
                    })
        except (json.JSONDecodeError, IndexError, TypeError, ValueError):
            continue

    # Check Kalshi
    kalshi_mkts = _get_kalshi_markets(query, limit=30)
    for m in kalshi_mkts:
        title = _extract_title(m, "kalshi")
        yes_bid = m.get("yes_bid")
        no_bid = m.get("no_bid")
        if yes_bid is None or no_bid is None or not title:
            continue
        # Kalshi prices in cents
        yes_p = float(yes_bid) / 100 if float(yes_bid) > 1 else float(yes_bid)
        no_p = float(no_bid) / 100 if float(no_bid) > 1 else float(no_bid)
        total = yes_p + no_p
        deviation = abs(total - 1.0)
        if deviation > 0.02:
            mispricings.append({
                "platform": "kalshi",
                "title": title,
                "ticker": m.get("ticker", ""),
                "yes_price": yes_p,
                "no_price": no_p,
                "sum": round(total, 4),
                "deviation": round(deviation, 4),
                "opportunity": "BUY both" if total < 0.98 else "SELL both" if total > 1.02 else "small",
            })

    mispricings.sort(key=lambda x: x["deviation"], reverse=True)

    return json.dumps({
        "mispricings": mispricings[:max_results],
        "count": len(mispricings),
        "strategy": "When YES + NO < $1.00, buy both sides for guaranteed profit at resolution. "
                     "When YES + NO > $1.00, sell both sides. Deviation must exceed fees (~3%) to profit.",
    })
