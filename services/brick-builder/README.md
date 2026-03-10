# Brick Builder AI Service

FastAPI backend for AI-powered 3D LEGO-style brick building. This service provides intelligent brick placement suggestions, auto-completion, and natural language descriptions using Ollama with the Qwen 2.5 Coder model.

## Features

- **AI Brick Suggestions**: Suggest next brick placements given current layout
- **Auto-Completion**: Intelligently complete partial structures (walls, towers, roofs, etc.)
- **Natural Language Descriptions**: Describe builds in human-readable text
- **Persistent Storage**: Save and load builds to/from disk
- **Structured JSON Responses**: All AI outputs are validated JSON with detailed reasoning
- **Health Checks**: Built-in service health monitoring

## Architecture

### Components

- `server.py` - Main FastAPI application with all endpoints
- `models.py` - Pydantic models for request/response validation
- `prompts.py` - System prompts and prompt generation for AI tasks
- `requirements.txt` - Python dependencies

### Ollama Integration

The service connects to Ollama running on your local PC:
- **Base URL**: `http://100.67.6.27:11434`
- **Model**: `qwen2.5-coder:7b`
- **Timeout**: 120 seconds

Ensure Ollama is running on your PC with the model pulled before starting this service.

## Installation

```bash
cd ./services/brick-builder
pip install -r requirements.txt --break-system-packages
```

## Running the Server

```bash
python3 -m uvicorn server:app --host 0.0.0.0 --port 8001
```

Or for development with auto-reload:

```bash
python3 -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

## API Endpoints

### Health Check

```
GET /health
```

Returns service status and configuration.

**Response:**
```json
{
  "status": "ok",
  "service": "brick-builder-ai",
  "model": "qwen2.5-coder:7b",
  "ollama_url": "http://100.67.6.27:11434"
}
```

### Suggest Bricks

```
POST /api/ai/suggest
```

Suggest next brick placements given current layout.

**Request:**
```json
{
  "bricks": [
    {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"}
  ],
  "context": "Make it taller",
  "count": 5
}
```

**Response:**
```json
{
  "suggestions": [
    {
      "x": 0,
      "y": 0,
      "z": 1,
      "color": "red",
      "size": "standard",
      "reason": "Continues the red tower vertically"
    }
  ],
  "analysis": "Your structure is a simple red tower. Adding bricks vertically creates height.",
  "model": "qwen2.5-coder:7b"
}
```

### Complete Build

```
POST /api/ai/complete
```

Auto-complete a partial structure with intelligent brick placement.

**Request:**
```json
{
  "bricks": [
    {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
    {"x": 1, "y": 0, "z": 0, "color": "red", "size": "standard"}
  ],
  "context": "Finish this wall 3 bricks high",
  "count": 10
}
```

**Response:**
```json
{
  "added_bricks": [
    {
      "x": 0,
      "y": 0,
      "z": 1,
      "color": "red",
      "size": "standard",
      "reason": "Builds wall vertically"
    }
  ],
  "completion_description": "Added bricks to create a 2x3 red wall",
  "model": "qwen2.5-coder:7b"
}
```

### Describe Build

```
POST /api/ai/describe
```

Get a natural language description of a build.

**Request:**
```json
{
  "bricks": [
    {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
    {"x": 0, "y": 0, "z": 1, "color": "red", "size": "standard"},
    {"x": 0, "y": 0, "z": 2, "color": "red", "size": "standard"}
  ]
}
```

**Response:**
```json
{
  "description": "A simple red tower made of three standard bricks stacked vertically.",
  "structure_type": "tower",
  "complexity": "simple",
  "model": "qwen2.5-coder:7b"
}
```

### Save Build

```
POST /api/builds/save
```

Save a build to persistent storage.

**Request:**
```json
{
  "name": "My Tower",
  "description": "A tall red tower",
  "bricks": [
    {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"}
  ]
}
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Tower",
  "description": "A tall red tower",
  "bricks": [...],
  "created_at": "2026-03-08T10:30:00",
  "updated_at": "2026-03-08T10:30:00"
}
```

### Load Build

```
POST /api/builds/load?build_id=<id>
```

Load a saved build by ID.

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Tower",
  "description": "A tall red tower",
  "bricks": [...],
  "created_at": "2026-03-08T10:30:00",
  "updated_at": "2026-03-08T10:30:00"
}
```

### List Builds

```
GET /api/builds/list
```

List all saved builds.

**Response:**
```json
{
  "builds": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "My Tower",
      "description": "A tall red tower",
      "brick_count": 10,
      "created_at": "2026-03-08T10:30:00",
      "updated_at": "2026-03-08T10:30:00"
    }
  ],
  "count": 1
}
```

## Data Models

### Brick

Represents a single brick in 3D space.

```python
{
  "x": float,              # X coordinate
  "y": float,              # Y coordinate
  "z": float,              # Z coordinate
  "color": str,            # Brick color
  "size": str              # standard, small, or large
}
```

### Available Colors

- red, blue, yellow, green, white, black, orange, purple, pink, brown, gray, cyan, lime, tan

### Brick Sizes

- `small` - 0.5 units
- `standard` - 1 unit (default)
- `large` - 2 units

## Storage

Builds are saved as JSON files in `./data/brick-builds/`. Each build file is named with its UUID and contains complete build information including creation/update timestamps.

## Testing

Run the test suite:

```bash
python3 test_endpoints.py
```

This will:
1. Start the server
2. Test health endpoint
3. Test save/load functionality
4. Test list endpoint
5. Clean up

## Error Handling

The service returns standard HTTP status codes:

- `200` - Success
- `400` - Invalid request (missing required fields, validation errors)
- `404` - Build not found
- `500` - Server error (Ollama connection failure, JSON parsing error, etc.)
- `503` - Ollama service unavailable

Error responses include a `detail` field with explanation:

```json
{
  "detail": "Ollama service error: connection refused"
}
```

## Configuration

Key settings in `server.py`:

```python
OLLAMA_BASE_URL = "http://100.67.6.27:11434"  # Ollama endpoint
MODEL_NAME = "qwen2.5-coder:7b"               # LLM model
BUILDS_DIR = Path("./data/brick-builds")  # Storage location
```

## Performance

- Suggestion generation: ~5-10 seconds (temperature 0.8)
- Completion generation: ~5-10 seconds (temperature 0.75)
- Description generation: ~3-5 seconds (temperature 0.6)
- HTTP timeout: 120 seconds

Response times depend on Ollama performance and network latency.

## Logging

Server logs to stdout with `INFO` level by default. Enable debug logging by modifying:

```python
logging.basicConfig(level=logging.DEBUG)
```

## Production Deployment

For production use:

1. Use a process manager (systemd, supervisord, etc.)
2. Configure Uvicorn with multiple workers
3. Add reverse proxy (nginx, Caddy)
4. Enable HTTPS
5. Set up monitoring and alerting
6. Backup build files regularly

Example systemd service file:

```ini
[Unit]
Description=Brick Builder AI Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=./services/brick-builder
ExecStart=/usr/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Notes

- The AI features require Ollama to be running on your local PC
- First inference may take longer as the model loads into memory
- Responses are deterministic within temperature settings
- Brick coordinates are floats for future sub-unit precision
- All timestamps are in UTC ISO format
