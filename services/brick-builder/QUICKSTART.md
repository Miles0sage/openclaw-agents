# Brick Builder AI Service - Quick Start

## Prerequisites

1. **Ollama Running**: Make sure Ollama is running on your local PC with the `qwen2.5-coder:7b` model
   - Ensure it's accessible at `http://100.67.6.27:11434`
   - Pull the model if you haven't: `ollama pull qwen2.5-coder:7b`

2. **Python 3.9+** on the VPS

## Setup (2 minutes)

```bash
cd ./services/brick-builder
pip install -r requirements.txt --break-system-packages
```

## Start the Server

```bash
python3 -m uvicorn server:app --host 0.0.0.0 --port 8001
```

You should see:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

## Test It

In another terminal:

```bash
# Health check
curl http://localhost:8001/health

# Save a simple 3-brick tower
curl -X POST http://localhost:8001/api/builds/save \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Tower",
    "description": "A test tower",
    "bricks": [
      {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
      {"x": 0, "y": 0, "z": 1, "color": "blue", "size": "standard"},
      {"x": 0, "y": 0, "z": 2, "color": "yellow", "size": "standard"}
    ]
  }'

# List builds
curl http://localhost:8001/api/builds/list
```

## API Overview

All endpoints accept/return JSON. Here are the main ones:

### 1. Save a Build
```
POST /api/builds/save
Body: { name, description, bricks }
```

### 2. Suggest Next Bricks
```
POST /api/ai/suggest
Body: { bricks, context?, count? }
Returns: suggestions + analysis
```

### 3. Describe a Build
```
POST /api/ai/describe
Body: { bricks }
Returns: description + structure_type + complexity
```

### 4. Complete a Build
```
POST /api/ai/complete
Body: { bricks, context }
Returns: added_bricks + completion_description
```

### 5. List Saved Builds
```
GET /api/builds/list
Returns: list of builds with metadata
```

## Example: Full Workflow

```bash
# 1. Start with a few bricks
BRICKS='[
  {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
  {"x": 1, "y": 0, "z": 0, "color": "red", "size": "standard"}
]'

# 2. Get AI suggestions for next 5 bricks
curl -X POST http://localhost:8001/api/ai/suggest \
  -H "Content-Type: application/json" \
  -d "{\"bricks\": $BRICKS, \"context\": \"build upward\", \"count\": 5}"

# 3. Describe what you have so far
curl -X POST http://localhost:8001/api/ai/describe \
  -H "Content-Type: application/json" \
  -d "{\"bricks\": $BRICKS}"

# 4. Auto-complete with "finish a wall 2 bricks high"
curl -X POST http://localhost:8001/api/ai/complete \
  -H "Content-Type: application/json" \
  -d "{\"bricks\": $BRICKS, \"context\": \"finish this wall 2 bricks high\"}"

# 5. Save your final build
curl -X POST http://localhost:8001/api/builds/save \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Wall",
    "description": "A 2x2 red wall",
    "bricks": [
      {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
      {"x": 1, "y": 0, "z": 0, "color": "red", "size": "standard"},
      {"x": 0, "y": 0, "z": 1, "color": "red", "size": "standard"},
      {"x": 1, "y": 0, "z": 1, "color": "red", "size": "standard"}
    ]
  }'
```

## Troubleshooting

### Server won't start
- Check Python version: `python3 --version` (need 3.9+)
- Check port 8001 isn't in use: `lsof -i :8001`
- Install dependencies: `pip install -r requirements.txt --break-system-packages`

### AI endpoints fail
- Check Ollama is running: `curl http://100.67.6.27:11434/api/tags`
- Check model is pulled: `ollama list` on your PC
- Check firewall isn't blocking VPS → PC connection

### Builds not saving
- Check `./data/brick-builds/` exists and is writable
- Check disk space: `df -h ./`

### All tests pass but endpoints slow
- First inference is slower as model loads
- Check network latency to your PC
- Monitor Ollama CPU/GPU usage

## Next Steps

1. **Integrate with frontend**: Use the API from your React/Vue app
2. **Add authentication**: Wrap endpoints with API key validation
3. **Deploy systemd service**: See README.md for service file
4. **Monitor**: Add logging/metrics to track inference times

## Files Reference

- `server.py` - Main FastAPI app (7 endpoints)
- `models.py` - Pydantic request/response models
- `prompts.py` - System prompts for AI tasks
- `requirements.txt` - Dependencies
- `test_endpoints.py` - Integration tests
- `README.md` - Full documentation

## Support

Stuck? Check the logs:
```bash
# If running with systemd
journalctl -u brick-builder-ai -f

# If running in terminal, you'll see output directly
```

All errors include helpful `detail` messages explaining what went wrong.
