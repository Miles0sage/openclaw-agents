# Brick Builder AI Service - Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Client                           │
│              (React/Vue/Web Application)                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ HTTP/JSON
                     │
┌────────────────────▼────────────────────────────────────────┐
│                                                               │
│          Brick Builder FastAPI Server (8001)                 │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ server.py - Main FastAPI Application                │   │
│  │                                                       │   │
│  │ • Health check endpoint                              │   │
│  │ • POST /api/ai/suggest                               │   │
│  │ • POST /api/ai/complete                              │   │
│  │ • POST /api/ai/describe                              │   │
│  │ • POST /api/builds/save                              │   │
│  │ • POST /api/builds/load                              │   │
│  │ • GET /api/builds/list                               │   │
│  │                                                       │   │
│  │ OllamaClient - HTTP wrapper for Ollama               │   │
│  │ • generate() - calls Ollama API                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ models.py - Pydantic Data Models                     │   │
│  │                                                       │   │
│  │ • Brick - single brick in 3D space                   │   │
│  │ • Build - collection of bricks                       │   │
│  │ • AIRequest - request payload for AI                 │   │
│  │ • AIResponse - suggestion response                   │   │
│  │ • BrickSuggestion - single suggested brick           │   │
│  │ • CompletionResponse - auto-completion result        │   │
│  │ • DescriptionResponse - natural language desc        │   │
│  │ • BuildSaveRequest / BuildResponse                   │   │
│  │                                                       │   │
│  │ All models:                                           │   │
│  │ • Inherit from pydantic.BaseModel                    │   │
│  │ • Include validation rules (min/max)                 │   │
│  │ • Have json_schema_extra examples                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ prompts.py - AI Prompt Management                    │   │
│  │                                                       │   │
│  │ System Prompts (define AI behavior):                 │   │
│  │ • BRICK_SUGGESTION_SYSTEM_PROMPT                     │   │
│  │ • BRICK_COMPLETION_SYSTEM_PROMPT                     │   │
│  │ • BRICK_DESCRIPTION_SYSTEM_PROMPT                    │   │
│  │                                                       │   │
│  │ Prompt Generators (create user prompts):             │   │
│  │ • get_suggestion_prompt()                            │   │
│  │ • get_completion_prompt()                            │   │
│  │ • get_description_prompt()                           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ HTTP to Ollama API
                     │
┌────────────────────▼────────────────────────────────────────┐
│     Ollama (http://100.67.6.27:11434)                       │
│     Model: qwen2.5-coder:7b                                 │
│     Running on local PC                                     │
└─────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────┐
│   Persistent Storage                                         │
│   ./data/brick-builds/                         │
│                                                              │
│   └─ {uuid}.json files (one per build)                      │
│      • Contains full build data                             │
│      • JSON format                                          │
│      • Indexed by UUID                                      │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow Examples

### 1. Suggest Next Bricks

```
Client Request
    │
    └─> POST /api/ai/suggest
        │
        ├─> Validate AIRequest (Pydantic)
        │
        ├─> get_suggestion_prompt()
        │   └─> Formats user's bricks into prompt text
        │
        ├─> OllamaClient.generate()
        │   ├─> system: BRICK_SUGGESTION_SYSTEM_PROMPT
        │   ├─> prompt: user_prompt + bricks
        │   └─> HTTP POST to Ollama /api/generate
        │
        ├─> parse_json_response()
        │   └─> Extracts JSON from Ollama output
        │
        ├─> Validate suggestions (BrickSuggestion models)
        │
        └─> AIResponse
            └─> Client receives suggestions + analysis
```

### 2. Save Build

```
Client Request
    │
    └─> POST /api/builds/save
        │
        ├─> Validate BuildSaveRequest (Pydantic)
        │
        ├─> Generate UUID for build
        │
        ├─> Add timestamps (created_at, updated_at)
        │
        ├─> save_build()
        │   ├─> Create JSON structure
        │   └─> Write to ./data/brick-builds/{uuid}.json
        │
        └─> BuildResponse with build data + ID
            └─> Client receives build ID for future reference
```

### 3. Load Build

```
Client Request
    │
    └─> POST /api/builds/load?build_id={uuid}
        │
        ├─> load_build(build_id)
        │   └─> Read from ./data/brick-builds/{uuid}.json
        │
        ├─> Validate with BuildResponse (Pydantic)
        │
        └─> Return full build data
            └─> Client can continue editing
```

## Key Design Decisions

### 1. Pydantic for Validation

**Why**: Automatic type checking, serialization, and error messages
- Request validation before processing
- Response validation before sending
- Swagger/OpenAPI documentation auto-generated
- Clear error messages to clients

Example:
```python
class AIRequest(BaseModel):
    bricks: List[Brick] = Field(...)
    context: Optional[str] = None
    count: int = Field(default=5, ge=1, le=50)  # Min=1, Max=50
```

### 2. Separate Prompt Management

**Why**: Easy to tune AI behavior without touching main logic
- System prompts define tone/constraints
- User prompt generators format data
- Easy A/B testing of different prompts
- Maintainability (all AI logic in one place)

### 3. OllamaClient Wrapper

**Why**: Centralized error handling and configuration
- All Ollama communication in one place
- Timeout configuration (120s)
- Error logging and HTTP exceptions
- Easy to switch to different LLM later

### 4. JSON File Storage

**Why**: Simple, reliable, no database needed
- Human-readable format
- Easy to backup/transfer
- Direct filesystem access
- UUID-based indexing
- Good for small-to-medium scale

### 5. Temperature Settings by Task

```python
suggest_bricks:    temperature=0.8  # More creative
complete_build:    temperature=0.75 # Balanced
describe_build:    temperature=0.6  # More deterministic
```

## Error Handling Strategy

```
Invalid Request
    ├─> Pydantic validation failure → 400 Bad Request
    │
Invalid Data
    ├─> JSON parsing failure → 500 Server Error
    ├─> Model validation failure → 500 Server Error
    │
External Service
    ├─> Ollama connection error → 503 Service Unavailable
    ├─> Ollama timeout → 500 Server Error
    │
File System
    ├─> Build not found → 404 Not Found
    ├─> Write failure → 500 Server Error
```

## Scaling Considerations

### Current Design (Single Instance)

- One server process
- Single OllamaClient connection
- File-based storage
- Good for: MVP, testing, single developer

### Future Scaling

**For Multiple Users:**
1. Add database (PostgreSQL for durability, Redis for cache)
2. Add authentication/authorization
3. Add per-user build namespacing
4. Add queue system (Redis/RabbitMQ) for AI jobs

**For High Load:**
1. Load balancer (nginx)
2. Multiple server instances
3. Async job queue for AI tasks
4. Caching layer (Redis) for frequent queries

**For Better AI:**
1. Support multiple Ollama servers
2. Model fallback chain
3. Streaming responses for long generations
4. Batch processing for multiple suggestions

## Testing Strategy

### Current Tests (test_endpoints.py)

✓ Health check
✓ Save build
✓ Load build
✓ List builds
✓ Server startup

### Recommended Additional Tests

- [ ] Unit tests for model validation
- [ ] Mock Ollama for AI endpoint tests
- [ ] Integration tests for full workflows
- [ ] Error cases (invalid JSON, missing fields, etc.)
- [ ] Performance tests (response times)
- [ ] Concurrent request tests

Example test pattern:
```python
def test_suggest_bricks_with_invalid_count():
    """Count must be between 1-50"""
    resp = requests.post(
        f"{BASE_URL}/api/ai/suggest",
        json={
            "bricks": [...],
            "count": 100  # Should fail
        }
    )
    assert resp.status_code == 422  # Validation error
```

## Dependencies

```
fastapi              # Web framework
uvicorn              # ASGI server
httpx                # HTTP client (async-ready)
pydantic             # Data validation
python-multipart     # Form parsing
```

All are production-ready with good community support.

## Configuration

Centralized in `server.py`:

```python
OLLAMA_BASE_URL = "http://100.67.6.27:11434"
MODEL_NAME = "qwen2.5-coder:7b"
BUILDS_DIR = Path("./data/brick-builds")
```

To modify:
1. Edit constants in `server.py`
2. Consider moving to `.env` file for production
3. Use environment variables: `os.getenv("OLLAMA_URL")`

## Monitoring & Logging

Current:
- Basic logging to stdout
- Error logging with context

Recommended improvements:
- Structured logging (JSON format)
- Request/response logging
- Performance metrics (response times)
- AI quality metrics (suggestion acceptance rate)
- Uptime monitoring
- Alerting on errors

## Security Considerations

Current (MVP):
- ✓ Input validation (Pydantic)
- ✗ No authentication
- ✗ No rate limiting
- ✗ No HTTPS
- ✗ No CORS origin restrictions

For production:
1. Add API key authentication
2. Add rate limiting (per IP, per key)
3. Deploy behind reverse proxy with HTTPS
4. Restrict CORS to known origins
5. Add request size limits
6. Sanitize file paths (already safe with UUID)

## Performance Characteristics

### Response Times
- Health check: ~1ms
- Save build: ~10ms (file I/O)
- List builds: ~20-50ms (depends on count)
- AI suggestions: 5-10 seconds (Ollama inference)
- AI description: 3-5 seconds (Ollama inference)
- AI completion: 5-10 seconds (Ollama inference)

### Bottleneck
**Ollama inference time** dominates (5-10 sec per request)

Optimization ideas:
- Cache common prompts
- Batch multiple requests
- Stream responses
- Use faster models (if acceptable)

### Memory Usage
- Server idle: ~100MB
- With Ollama 7B model loaded: ~14GB
- Per request: minimal overhead

## Future Enhancements

1. **Streaming Responses**: Stream brick suggestions as they're generated
2. **Batch Requests**: Process multiple builds in one request
3. **Model Selection**: Let users choose between fast/accurate models
4. **Fine-tuning**: Improve model with user feedback
5. **Brick Validation**: Check builds for structural stability
6. **3D Rendering**: Return 3D model data (OBJ, GLTF)
7. **Building Templates**: Pre-made structures to start from
8. **Multiplayer**: Collaborative building in real-time
