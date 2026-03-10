"""Pydantic models for the Brick Builder AI service."""

from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class Brick(BaseModel):
    """Represents a single brick in the 3D space."""
    x: float = Field(..., description="X coordinate")
    y: float = Field(..., description="Y coordinate")
    z: float = Field(..., description="Z coordinate")
    color: str = Field(..., description="Brick color (e.g., 'red', 'blue', 'yellow')")
    size: str = Field(
        default="standard",
        description="Brick size (e.g., 'small', 'standard', 'large')"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "x": 0,
                "y": 0,
                "z": 0,
                "color": "red",
                "size": "standard"
            }
        }
    }


class Build(BaseModel):
    """Represents a complete brick build."""
    id: str = Field(default_factory=lambda: None, description="Build ID")
    name: str = Field(..., description="Build name")
    description: Optional[str] = Field(default=None, description="Build description")
    bricks: List[Brick] = Field(default_factory=list, description="List of bricks")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "build_001",
                "name": "Simple Tower",
                "description": "A 5-brick tower",
                "bricks": [
                    {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
                    {"x": 0, "y": 0, "z": 1, "color": "blue", "size": "standard"}
                ],
                "created_at": "2026-03-08T00:00:00",
                "updated_at": "2026-03-08T00:00:00"
            }
        }
    }


class AIRequest(BaseModel):
    """Request for AI suggestions."""
    bricks: List[Brick] = Field(..., description="Current brick layout")
    context: Optional[str] = Field(
        default=None,
        description="Additional context or instructions (e.g., 'build a wall', 'add a roof')"
    )
    count: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of suggestions to generate"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "bricks": [
                    {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"}
                ],
                "context": "Add more bricks to make it taller",
                "count": 5
            }
        }
    }


class BrickSuggestion(BaseModel):
    """A single suggested brick placement."""
    x: float = Field(..., description="X coordinate")
    y: float = Field(..., description="Y coordinate")
    z: float = Field(..., description="Z coordinate")
    color: str = Field(..., description="Brick color")
    size: str = Field(default="standard", description="Brick size")
    reason: Optional[str] = Field(default=None, description="Why this brick is suggested")

    model_config = {
        "json_schema_extra": {
            "example": {
                "x": 0,
                "y": 0,
                "z": 1,
                "color": "red",
                "size": "standard",
                "reason": "Continues the red tower vertically"
            }
        }
    }


class AIResponse(BaseModel):
    """Response from AI suggestions."""
    suggestions: List[BrickSuggestion] = Field(..., description="List of suggested bricks")
    analysis: str = Field(..., description="AI analysis of the current build")
    model: str = Field(default="qwen2.5-coder:7b", description="Model used")

    model_config = {
        "json_schema_extra": {
            "example": {
                "suggestions": [
                    {
                        "x": 0,
                        "y": 0,
                        "z": 1,
                        "color": "red",
                        "size": "standard",
                        "reason": "Continues the structure vertically"
                    }
                ],
                "analysis": "Your build has a stable base with one red brick. Adding more bricks vertically creates a tower pattern.",
                "model": "qwen2.5-coder:7b"
            }
        }
    }


class BuildSaveRequest(BaseModel):
    """Request to save a build."""
    name: str = Field(..., description="Build name")
    description: Optional[str] = Field(default=None, description="Build description")
    bricks: List[Brick] = Field(..., description="List of bricks")


class BuildResponse(BaseModel):
    """Response when saving/loading a build."""
    id: str = Field(..., description="Build ID")
    name: str = Field(..., description="Build name")
    description: Optional[str] = Field(default=None)
    bricks: List[Brick] = Field(...)
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)


class DescriptionResponse(BaseModel):
    """Response from AI description endpoint."""
    description: str = Field(..., description="Natural language description of the build")
    structure_type: str = Field(..., description="Type of structure (e.g., 'tower', 'house', 'wall')")
    complexity: str = Field(..., description="Complexity level (simple, moderate, complex)")
    model: str = Field(default="qwen2.5-coder:7b")


class CompletionResponse(BaseModel):
    """Response from AI completion endpoint."""
    added_bricks: List[BrickSuggestion] = Field(..., description="Bricks added to complete the structure")
    completion_description: str = Field(..., description="Description of how the structure was completed")
    model: str = Field(default="qwen2.5-coder:7b")
