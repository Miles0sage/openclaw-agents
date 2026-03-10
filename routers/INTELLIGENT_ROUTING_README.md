# Intelligent Routing Router Module

## Quick Start

This module provides FastAPI router endpoints for intelligent query classification and model routing across Claude models (Haiku, Sonnet, Opus).

### Import

```python
from routers.intelligent_routing import router
app.include_router(router)
```

### Endpoints

- `POST /api/route` - Classify single query
- `POST /api/route/test` - Batch classify queries
- `GET /api/route/models` - List available models
- `GET /api/route/health` - Health check

---

## Detailed Endpoint Documentation

### 1. POST /api/route - Single Query Classification

**Request**:

```bash
curl -X POST http://localhost:8000/api/route \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Write a hello world in Python",
    "context": "For learning purposes",
    "sessionKey": "default:user123",
    "force_model": null
  }'
```

**Request Fields**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| query | str | Yes | Query text to classify |
| context | str | No | Additional context for better classification |
| sessionKey | str | No | Session ID for cost logging |
| force_model | str | No | Force specific model: "haiku", "sonnet", or "opus" |

**Response (Success - 200)**:

```json
{
  "success": true,
  "timestamp": "2026-03-05T00:37:08Z",
  "model": "haiku",
  "complexity": 2,
  "confidence": 0.94,
  "reasoning": "Simple coding task, well-defined scope",
  "cost_estimate": 0.000012,
  "estimated_tokens": 150,
  "metadata": {
    "pricing": {
      "input": 0.8,
      "output": 4.0
    },
    "cost_savings_vs_sonnet": 0.000024,
    "cost_savings_percentage": 66.67,
    "rate_limit": {
      "requests_per_minute": 10000,
      "tokens_per_minute": 1000000
    }
  }
}
```

**Response (Budget Exceeded - 402)**:

```json
{
  "success": false,
  "error": "Budget limit exceeded",
  "detail": "Monthly budget of $50.00 exceeded by $2.34",
  "gate": "monthly_limit",
  "remaining_budget": -2.34,
  "timestamp": "2026-03-05T00:37:08Z"
}
```

**Response (Invalid Request - 400)**:

```json
{
  "success": false,
  "error": "query is required and must be a string"
}
```

---

### 2. POST /api/route/test - Batch Query Classification

**Request**:

```bash
curl -X POST http://localhost:8000/api/route/test \
  -H "Content-Type: application/json" \
  -d '{
    "queries": [
      "Fix typo in button.tsx",
      "Refactor entire auth system to use JWT",
      "Analyze S&P 500 price trends from 2020-2026"
    ]
  }'
```

**Response (Success - 200)**:

```json
{
  "success": true,
  "timestamp": "2026-03-05T00:37:08Z",
  "results": [
    {
      "query": "Fix typo in button.tsx",
      "model": "haiku",
      "complexity": 1,
      "confidence": 0.98,
      "cost_estimate": 0.000008,
      "savings_percentage": 75.3
    },
    {
      "query": "Refactor entire auth system to use JWT",
      "model": "sonnet",
      "complexity": 6,
      "confidence": 0.91,
      "cost_estimate": 0.000156,
      "savings_percentage": 0.0
    },
    {
      "query": "Analyze S&P 500 price trends from 2020-2026",
      "model": "opus",
      "complexity": 8,
      "confidence": 0.87,
      "cost_estimate": 0.000234,
      "savings_percentage": -280.5
    }
  ],
  "stats": {
    "total_queries": 3,
    "by_model": {
      "haiku": 1,
      "sonnet": 1,
      "opus": 1
    },
    "avg_complexity": 5.0,
    "avg_confidence": 0.92,
    "total_estimated_cost": 0.000398,
    "avg_savings_percentage": -68.4
  }
}
```

---

### 3. GET /api/route/models - Model Catalog

**Request**:

```bash
curl http://localhost:8000/api/route/models
```

**Response**:

```json
{
  "success": true,
  "timestamp": "2026-03-05T00:37:08Z",
  "models": [
    {
      "name": "Claude 3.5 Haiku",
      "model": "haiku",
      "alias": "claude-3-5-haiku-20241022",
      "pricing": {
        "input": 0.8,
        "output": 4.0
      },
      "contextWindow": 200000,
      "maxOutputTokens": 4096,
      "costSavingsPercentage": -75,
      "available": true,
      "rateLimit": {
        "requests_per_minute": 10000,
        "tokens_per_minute": 1000000
      }
    },
    {
      "name": "Claude 3.5 Sonnet",
      "model": "sonnet",
      "alias": "claude-3-5-sonnet-20241022",
      "pricing": {
        "input": 3.0,
        "output": 15.0
      },
      "contextWindow": 200000,
      "maxOutputTokens": 4096,
      "costSavingsPercentage": 0,
      "available": true,
      "rateLimit": {
        "requests_per_minute": 10000,
        "tokens_per_minute": 1000000
      }
    },
    {
      "name": "Claude Opus 4.6",
      "model": "opus",
      "alias": "claude-opus-4-1-20250805",
      "pricing": {
        "input": 15.0,
        "output": 75.0
      },
      "contextWindow": 200000,
      "maxOutputTokens": 4096,
      "costSavingsPercentage": 400,
      "available": true,
      "rateLimit": {
        "requests_per_minute": 2000,
        "tokens_per_minute": 400000
      }
    }
  ],
  "optimalDistribution": {
    "haiku": "70%",
    "sonnet": "20%",
    "opus": "10%"
  },
  "expectedCostSavings": "60-70% reduction vs always using Sonnet"
}
```

---

### 4. GET /api/route/health - Health Check

**Request**:

```bash
curl http://localhost:8000/api/route/health
```

**Response**:

```json
{
  "success": true,
  "timestamp": "2026-03-05T00:37:08Z",
  "status": "healthy",
  "models_available": 3,
  "models": ["haiku", "sonnet", "opus"],
  "router_version": "1.0.0"
}
```

---

## Classification Logic

The router uses a complexity classifier that:

1. **Analyzes query text** for:
   - Keywords indicating complexity level
   - Multi-file/multi-step patterns
   - Language/domain indicators

2. **Routes based on complexity**:
   - **Haiku (0-3)**: Simple tasks (typos, small fixes, basic questions)
   - **Sonnet (4-6)**: Medium tasks (feature implementation, refactoring)
   - **Opus (7-10)**: Complex tasks (architecture, deep reasoning, novel problems)

3. **Calculates cost savings**:
   - Baseline: Sonnet pricing
   - Haiku: 60-75% cheaper than Sonnet
   - Opus: 300-400% more expensive but handles complex tasks

---

## Cost Gate Integration

The router integrates with the cost_gates system:

```python
# Budget checking happens before routing decision
budget_check = check_cost_budget(
    project=project,
    agent="router",
    model=result.model,
    tokens_input=estimated_tokens // 2,
    tokens_output=estimated_tokens // 2,
    task_id=f"{project}:router:{sessionKey}"
)

if budget_check.status == BudgetStatus.REJECTED:
    return 402 Payment Required
elif budget_check.status == BudgetStatus.WARNING:
    log warning but allow request
```

---

## Usage Patterns

### Pattern 1: Auto-Classify & Route

```python
response = requests.post("http://localhost:8000/api/route", json={
    "query": user_input,
    "sessionKey": "myproject:user123"
})
model = response.json()["model"]  # "haiku", "sonnet", or "opus"
# Use model for subsequent API call
```

### Pattern 2: Force Model for Testing

```python
response = requests.post("http://localhost:8000/api/route", json={
    "query": user_input,
    "force_model": "sonnet"  # Always use Sonnet for testing
})
```

### Pattern 3: Batch Classification

```python
response = requests.post("http://localhost:8000/api/route/test", json={
    "queries": [query1, query2, query3]
})
stats = response.json()["stats"]
# Analyze distribution across models
```

### Pattern 4: Check Available Models

```python
response = requests.get("http://localhost:8000/api/route/models")
models = response.json()["models"]
# Display model options to user
```

---

## Error Codes

| Code | Meaning         | Example                  |
| ---- | --------------- | ------------------------ |
| 200  | Success         | Classification completed |
| 400  | Bad Request     | Missing required field   |
| 402  | Budget Exceeded | Cost gate rejection      |
| 500  | Server Error    | Internal exception       |

---

## Configuration

The router uses shared configuration from:

- **complexity_classifier**: Defines classification logic
- **cost_tracker**: Records cost events
- **cost_gates**: Enforces budget limits
- **config.json**: General OpenClaw configuration

---

## Integration Checklist

- [x] Extract endpoints from gateway.py
- [x] Convert @app decorators to @router
- [x] Import shared dependencies
- [x] Validate Pydantic models
- [x] Test imports and syntax
- [x] Verify cost gate integration
- [ ] Add to gateway.py router includes (NEXT STEP)
- [ ] Test endpoints on live gateway
- [ ] Update API documentation
- [ ] Monitor cost tracking

---

## Next Steps

1. **Add to gateway.py**:

   ```python
   from routers.intelligent_routing import router as intelligent_routing_router
   app.include_router(intelligent_routing_router)
   ```

2. **Test endpoints**:

   ```bash
   curl http://localhost:8000/api/route/health
   ```

3. **Monitor logs**:

   ```bash
   journalctl -u openclaw-gateway -f | grep "router"
   ```

4. **Track costs**:
   ```bash
   curl http://localhost:8000/api/cost-summary
   ```

---

## Files

- **Module**: `./routers/intelligent_routing.py` (274 lines)
- **Shared**: `./routers/shared.py`
- **Gateway**: `./gateway.py` (includes router)
- **Config**: `./config.json`

---

## Support

For issues or questions:

1. Check logs: `journalctl -u openclaw-gateway -f`
2. Test endpoint: `curl http://localhost:8000/api/route/health`
3. Verify imports: `python3 -c "from routers.intelligent_routing import router"`
4. Check shared deps: Ensure `routers/shared.py` is available
