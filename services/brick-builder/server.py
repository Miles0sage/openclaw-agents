"""FastAPI server for the Brick Builder AI service."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from models import (
    Brick,
    Build,
    AIRequest,
    AIResponse,
    BrickSuggestion,
    BuildSaveRequest,
    BuildResponse,
    DescriptionResponse,
    CompletionResponse,
)
from prompts import (
    BRICK_SUGGESTION_SYSTEM_PROMPT,
    BRICK_COMPLETION_SYSTEM_PROMPT,
    BRICK_DESCRIPTION_SYSTEM_PROMPT,
    get_suggestion_prompt,
    get_completion_prompt,
    get_description_prompt,
)

# Configuration
OLLAMA_BASE_URL = "http://100.67.6.27:11434"
MODEL_NAME = "qwen2.5-coder:7b"
BUILDS_DIR = Path("./data/brick-builds")
BUILDS_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Brick Builder AI Service",
    description="AI-powered backend for 3D brick building",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OllamaClient:
    """Client for interacting with Ollama API."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = MODEL_NAME):
        self.base_url = base_url
        self.model = model
        self.client = httpx.Client(timeout=120.0)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ) -> str:
        """Generate text using Ollama."""
        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
        except httpx.RequestError as e:
            logger.error(f"Ollama request error: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Ollama service error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generating response: {str(e)}"
            )

    def close(self):
        """Close the HTTP client."""
        self.client.close()


def parse_json_response(response_text: str) -> dict:
    """Parse JSON from Ollama response (handles markdown code blocks)."""
    text = response_text.strip()

    # Remove markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Find the closing ```
        start_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("```json") or line.startswith("```"):
                start_idx = i + 1
                break

        # Find closing ```
        end_idx = len(lines)
        for i in range(start_idx, len(lines)):
            if lines[i].strip() == "```":
                end_idx = i
                break

        text = "\n".join(lines[start_idx:end_idx]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nText: {text}")
        raise ValueError(f"Failed to parse JSON response: {str(e)}")


def load_build(build_id: str) -> Optional[dict]:
    """Load a build from disk."""
    build_file = BUILDS_DIR / f"{build_id}.json"
    if build_file.exists():
        try:
            with open(build_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading build {build_id}: {e}")
    return None


def save_build(build_data: dict) -> str:
    """Save a build to disk and return the build ID."""
    build_id = build_data.get("id", str(uuid.uuid4()))
    build_file = BUILDS_DIR / f"{build_id}.json"

    build_data["id"] = build_id
    build_data["updated_at"] = datetime.utcnow().isoformat()

    try:
        with open(build_file, "w") as f:
            json.dump(build_data, f, indent=2)
        logger.info(f"Saved build {build_id} to {build_file}")
        return build_id
    except Exception as e:
        logger.error(f"Error saving build: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error saving build: {str(e)}"
        )


# Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "brick-builder-ai",
        "model": MODEL_NAME,
        "ollama_url": OLLAMA_BASE_URL
    }


@app.post("/api/ai/suggest", response_model=AIResponse)
async def suggest_bricks(request: AIRequest):
    """Suggest next brick placements given current layout."""
    logger.info(f"Suggestion request: {len(request.bricks)} bricks, count={request.count}")

    client = OllamaClient()
    try:
        brick_dicts = [b.model_dump() for b in request.bricks]
        user_prompt = get_suggestion_prompt(brick_dicts, request.context)

        response_text = client.generate(
            system_prompt=BRICK_SUGGESTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.8,
        )

        # Parse JSON response
        response_data = parse_json_response(response_text)

        # Validate suggestions
        suggestions = []
        for sug in response_data.get("suggestions", [])[:request.count]:
            try:
                suggestions.append(BrickSuggestion(**sug))
            except ValidationError as e:
                logger.warning(f"Invalid suggestion: {e}")
                continue

        if not suggestions:
            raise ValueError("No valid suggestions generated")

        return AIResponse(
            suggestions=suggestions,
            analysis=response_data.get("analysis", ""),
            model=MODEL_NAME
        )

    except Exception as e:
        logger.error(f"Error in suggest_bricks: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating suggestions: {str(e)}"
        )
    finally:
        client.close()


@app.post("/api/ai/complete", response_model=CompletionResponse)
async def complete_build(request: AIRequest):
    """Auto-complete a partial build structure."""
    if not request.context:
        raise HTTPException(
            status_code=400,
            detail="Context is required for completion (e.g., 'finish this wall')"
        )

    logger.info(f"Completion request: {len(request.bricks)} bricks, context='{request.context}'")

    client = OllamaClient()
    try:
        brick_dicts = [b.model_dump() for b in request.bricks]
        user_prompt = get_completion_prompt(brick_dicts, request.context)

        response_text = client.generate(
            system_prompt=BRICK_COMPLETION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.75,
        )

        # Parse JSON response
        response_data = parse_json_response(response_text)

        # Validate added bricks
        added_bricks = []
        for brick in response_data.get("added_bricks", []):
            try:
                added_bricks.append(BrickSuggestion(**brick))
            except ValidationError as e:
                logger.warning(f"Invalid brick in completion: {e}")
                continue

        if not added_bricks:
            raise ValueError("No valid bricks generated for completion")

        return CompletionResponse(
            added_bricks=added_bricks,
            completion_description=response_data.get("completion_description", ""),
            model=MODEL_NAME
        )

    except Exception as e:
        logger.error(f"Error in complete_build: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error completing build: {str(e)}"
        )
    finally:
        client.close()


@app.post("/api/ai/describe", response_model=DescriptionResponse)
async def describe_build(request: AIRequest):
    """Describe what a build looks like in natural language."""
    logger.info(f"Description request: {len(request.bricks)} bricks")

    client = OllamaClient()
    try:
        if not request.bricks:
            return DescriptionResponse(
                description="The build is empty - no bricks have been placed yet.",
                structure_type="empty",
                complexity="simple",
                model=MODEL_NAME
            )

        brick_dicts = [b.model_dump() for b in request.bricks]
        user_prompt = get_description_prompt(brick_dicts)

        response_text = client.generate(
            system_prompt=BRICK_DESCRIPTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.6,
        )

        # Parse JSON response
        response_data = parse_json_response(response_text)

        return DescriptionResponse(
            description=response_data.get("description", ""),
            structure_type=response_data.get("structure_type", "unknown"),
            complexity=response_data.get("complexity", "moderate"),
            model=MODEL_NAME
        )

    except Exception as e:
        logger.error(f"Error in describe_build: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error describing build: {str(e)}"
        )
    finally:
        client.close()


@app.post("/api/builds/save", response_model=BuildResponse)
async def save_build_endpoint(request: BuildSaveRequest):
    """Save a build to disk."""
    build_data = {
        "id": str(uuid.uuid4()),
        "name": request.name,
        "description": request.description,
        "bricks": [b.model_dump() for b in request.bricks],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    build_id = save_build(build_data)
    return BuildResponse(**build_data)


@app.post("/api/builds/load", response_model=BuildResponse)
async def load_build_endpoint(build_id: str):
    """Load a saved build by ID."""
    build_data = load_build(build_id)
    if not build_data:
        raise HTTPException(
            status_code=404,
            detail=f"Build '{build_id}' not found"
        )

    try:
        return BuildResponse(**build_data)
    except ValidationError as e:
        logger.error(f"Error validating loaded build: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading build: {str(e)}"
        )


@app.get("/api/builds/list")
async def list_builds():
    """List all saved builds."""
    builds = []
    try:
        for build_file in sorted(BUILDS_DIR.glob("*.json")):
            try:
                with open(build_file, "r") as f:
                    build_data = json.load(f)
                    builds.append({
                        "id": build_data.get("id"),
                        "name": build_data.get("name"),
                        "description": build_data.get("description"),
                        "brick_count": len(build_data.get("bricks", [])),
                        "created_at": build_data.get("created_at"),
                        "updated_at": build_data.get("updated_at"),
                    })
            except Exception as e:
                logger.warning(f"Error reading build {build_file}: {e}")
                continue

        return {
            "builds": builds,
            "count": len(builds)
        }
    except Exception as e:
        logger.error(f"Error listing builds: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing builds: {str(e)}"
        )


# Mount static files for frontend (after API routes for priority)
FRONTEND_DIR = Path("./services/brick-builder/frontend-dist")
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
else:
    logger.warning(f"Frontend directory not found: {FRONTEND_DIR}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )
