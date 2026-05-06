"""
backend/models.py
────────────────────────────────────────────────────────────────────────────
Data models for Phase 1 and Phase 2 outputs, used for API serialization.
"""

from typing import Any, Optional
from pydantic import BaseModel


# ── Phase 1 Models ──────────────────────────────────────────────────────────

class DialogueLine(BaseModel):
    """A single line of dialogue in a scene."""
    speaker: str
    line: str
    visual_cue: Optional[str] = None


class Scene(BaseModel):
    """A scene in the script."""
    scene_id: int
    location: str
    characters: list[str]
    dialogue: list[DialogueLine]


class Script(BaseModel):
    """The complete generated script."""
    scenes: list[Scene]


class Character(BaseModel):
    """A character profile."""
    name: str
    personality_traits: list[str]
    appearance_description: str
    reference_style: str
    image_path: Optional[str] = None


class Phase1Output(BaseModel):
    """Combined output from Phase 1."""
    status: str
    input_mode: str
    hitl_approved: Optional[bool] = None   # None = pending, True = approved, False = rejected
    script: Optional[Script] = None
    characters: list[Character]
    images: list[str]
    error: Optional[str] = None


# ── Phase 2 Models ──────────────────────────────────────────────────────────

class Phase2SceneResult(BaseModel):
    """Result for a single scene processed in Phase 2."""
    scene_id: int
    raw_mp4_path: Optional[str] = None
    error: Optional[str] = None


class Phase2Output(BaseModel):
    """Combined output from Phase 2."""
    scenes: list[Phase2SceneResult]
    error: Optional[str] = None
    # Mirrors USE_VIDEO_MODEL at run time: Wan I2V vs Pexels stock pipeline
    video_generation_mode: str = "pexels_stock"


# ── Phase 3 Models ──────────────────────────────────────────────────────────

class Phase3Output(BaseModel):
    """Combined output from Phase 3 (Cutting Room)."""
    final_output_path: Optional[str] = None
    duration_seconds: float = 0.0
    scene_count: int = 0
    transition_style: str = "fade"
    subtitles_burned: bool = False
    srt_path: Optional[str] = None
    error: Optional[str] = None
    status: str = "pending"


# ── Pipeline Status Models ──────────────────────────────────────────────────

class PipelineStatus(BaseModel):
    """Overall pipeline execution status."""
    phase1_completed: bool = False
    phase1_error: Optional[str] = None
    phase1_start_time: Optional[str] = None
    phase1_end_time: Optional[str] = None

    phase2_completed: bool = False
    phase2_error: Optional[str] = None
    phase2_start_time: Optional[str] = None
    phase2_end_time: Optional[str] = None

    phase3_completed: bool = False
    phase3_error: Optional[str] = None
    phase3_start_time: Optional[str] = None
    phase3_end_time: Optional[str] = None

    pipeline_running: bool = False
    current_phase: Optional[str] = None


# ── Request Models ──────────────────────────────────────────────────────────

class Phase1Request(BaseModel):
    """Request body for triggering Phase 1."""
    prompt: str
    script_path: Optional[str] = None


class Phase2Request(BaseModel):
    """Request body for triggering Phase 2."""
    scene_id: Optional[int] = None
    """If specified, process only this scene. If None, process all scenes."""


class Phase3Request(BaseModel):
    """Request body for triggering Phase 3."""
    transition_style: str = "fade"
    """Transition between scenes: fade | cut | wipe_left | wipe_right | dissolve | fade_black"""
    add_subtitles: bool = True
    """Whether to burn SRT subtitles into the final video."""


class EditRequest(BaseModel):
    """Request body for triggering the Phase 5 edit workflow."""
    query: str
    scene_id: Optional[int] = None


# ── API Response Models ──────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None


class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
