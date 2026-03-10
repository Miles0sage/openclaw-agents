# Trading Router Module Specification

## Overview

FastAPI APIRouter module extracted from `gateway.py` containing all trading, prediction market, sports betting, and research endpoints.

**File:** `./routers/trading.py`
**Lines:** 424
**Router Prefix:** `/api`
**Tags:** `["trading"]`

## Endpoints by Category

### Research (4 endpoints)

| Method | Path                   | Description                                           |
| ------ | ---------------------- | ----------------------------------------------------- |
| GET    | `/perplexity-research` | Deep research via Perplexity Sonar API (query string) |
| POST   | `/perplexity-research` | Deep research via Perplexity Sonar API (JSON body)    |
| GET    | `/ai-news`             | Fetch latest AI news from RSS feeds                   |
| GET    | `/tweets`              | Read recent tweets from AI accounts                   |

### Polymarket Trading (4 endpoints)

| Method | Path                    | Description                                                                 |
| ------ | ----------------------- | --------------------------------------------------------------------------- |
| POST   | `/polymarket/prices`    | Real-time Polymarket price data (snapshot, spread, midpoint, book, history) |
| POST   | `/polymarket/monitor`   | Monitor markets (mispricing, open interest, volume, holders, leaderboard)   |
| POST   | `/polymarket/portfolio` | View wallet positions, trades, activity (read-only)                         |
| POST   | `/polymarket/trade`     | Place, cancel, manage Polymarket orders (safety-checked, dry-run default)   |

### Kalshi Trading (3 endpoints)

| Method | Path                | Description                                                           |
| ------ | ------------------- | --------------------------------------------------------------------- |
| POST   | `/kalshi/markets`   | Search and view Kalshi market data (read-only)                        |
| POST   | `/kalshi/trade`     | Place, cancel, manage Kalshi orders (safety-checked, dry-run default) |
| POST   | `/kalshi/portfolio` | View Kalshi portfolio (balance, positions, fills, settlements)        |

### Arbitrage & Trading Strategies (3 endpoints)

| Method | Path                  | Description                                                                                  |
| ------ | --------------------- | -------------------------------------------------------------------------------------------- |
| POST   | `/arb/scan`           | Cross-platform arbitrage scanner (Polymarket + Kalshi)                                       |
| POST   | `/trading/strategies` | Automated trading opportunity scanners (bonds, mispricing, whale alerts, trending, expiring) |
| POST   | `/trading/safety`     | Trading safety configuration (dry-run, kill switch, limits, audit log)                       |

### Sportsbook & Sports Betting (5 endpoints)

| Method | Path               | Description                                                    |
| ------ | ------------------ | -------------------------------------------------------------- |
| POST   | `/sportsbook/odds` | Live sportsbook odds from 200+ bookmakers                      |
| POST   | `/sportsbook/arb`  | Sportsbook arbitrage + EV scanner                              |
| POST   | `/sports/predict`  | XGBoost-powered NBA predictions                                |
| POST   | `/sports/betting`  | Full betting pipeline (predictions + odds + EV + Kelly sizing) |
| POST   | `/sports/tracker`  | Prediction tracker (log, grade, track accuracy/ROI)            |

### Utilities (3 endpoints)

| Method | Path                  | Description                                       |
| ------ | --------------------- | ------------------------------------------------- |
| POST   | `/research/deep`      | Deep research with multi-step autonomous research |
| POST   | `/proposals/generate` | Generate branded HTML client proposal             |
| POST   | `/prediction`         | Prediction market queries (PA worker integration) |

## Technical Details

### Imports

```python
import json
import logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
```

### Router Configuration

```python
router = APIRouter(prefix="/api", tags=["trading"])
```

### Error Handling

All endpoints use consistent error handling:

```python
return JSONResponse({"error": str(e)}, status_code=500)
```

### Dynamic Imports

Endpoints use lazy imports from specialized modules:

- `agent_tools` — Research, prediction market tools
- `polymarket_trading` — Polymarket operations
- `kalshi_trading` — Kalshi operations
- `arb_scanner` — Arbitrage detection
- `trading_strategies` — Strategy scanning
- `trading_safety` — Safety configuration
- `sportsbook_odds` — Sportsbook operations
- `sports_model` — Sports predictions and betting
- `prediction_tracker` — Prediction tracking
- `deep_research` — Deep research execution
- `proposal_generator` — Proposal generation

## Integration with Gateway

### In gateway.py:

```python
from routers.trading import router as trading_router

# In app startup:
app.include_router(trading_router)
```

This will register all 22 endpoints under `/api/*` paths.

## Request/Response Pattern

### POST Endpoints (JSON Body)

```python
@router.post("/path")
async def handler(request: Request):
    try:
        body = await request.json()
        # Use body.get("key", default)
        from module import function
        result = function(param=body.get("param"))
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
```

### GET Endpoints (Query Parameters)

```python
@router.get("/path")
async def handler(query: str, model: str = "default"):
    try:
        from module import function
        result = function(param=query)
        return json.loads(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
```

## Functionality Preserved

- All endpoint paths converted from `@app.*` to `@router.*`
- All function signatures unchanged
- All internal logic identical
- Error handling preserved
- Default parameters maintained
- Request body parsing unchanged
- Logging configuration intact

## Testing

Validate syntax:

```bash
python3 -m py_compile ./routers/trading.py
```

Test router registration (minimal):

```python
from routers.trading import router
assert router.prefix == "/api"
assert len(router.routes) == 22
```

## Dependencies

Ensure these modules exist in the OpenClaw environment:

- `agent_tools`
- `polymarket_trading`
- `kalshi_trading`
- `arb_scanner`
- `trading_strategies`
- `trading_safety`
- `sportsbook_odds`
- `sports_model`
- `prediction_tracker`
- `deep_research`
- `proposal_generator`

## Notes

- Router uses prefix `/api`, so all routes will be under `/api/endpoint`
- All endpoints are async
- Error responses return HTTP 500 on exception
- Result parsing expects JSON string from underlying functions
- Some endpoints handle both JSON and plain text responses (e.g., `/prediction`)
- Dynamic imports reduce startup time and dependency coupling
