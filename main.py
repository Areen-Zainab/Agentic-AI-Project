#!/usr/bin/env python3
"""
main.py
────────────────────────────────────────────────────────────────────────────
Central backend server for Project Montage.

This FastAPI server orchestrates Phase 1 (Writer's Room) and Phase 2 (Studio Floor),
providing REST APIs for the React frontend to fetch results and trigger execution.

Usage:
    python main.py
    
    The server will start on http://localhost:8000
    API docs available at http://localhost:8000/docs
"""

import json
import os
import sys
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Ensure imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import get_orchestrator, Phase1Request, Phase2Request, EditRequest
from backend.models import ErrorResponse, Phase1Output, Phase2Output, Phase3Output, PipelineStatus
from pydantic import BaseModel
from shared.config.config import IMAGE_ASSETS_DIR, USE_VIDEO_MODEL
from phase5_edit_agent.agents.edit_executor import state_manager as edit_state_manager
from phase5_edit_agent.graph.workflow import build_edit_graph


# ── Lifespan Events ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    print("\n" + "="*80)
    print("PROJECT MONTAGE — Central Backend")
    print("="*80)
    print("\n✓ Backend server starting...")
    print("✓ Phase 1 (Writer's Room) available")
    print("✓ Phase 2 (Studio Floor) available")
    print("✓ Phase 3 (Cutting Room) available")
    print("✓ API docs: http://localhost:8000/docs\n")
    
    yield
    
    print("\n✓ Backend server shutting down...\n")


# ── FastAPI App ────────────────────────────────────────────────────────────

app = FastAPI(
    title="Project Montage Central Backend",
    description="Orchestrates Phase 1 (Writer's Room) and Phase 2 (Studio Floor)",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get global orchestrator
orchestrator = get_orchestrator()
edit_graph = build_edit_graph()


def _load_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _collect_snapshot_assets() -> list[str]:
    base = Path(__file__).resolve().parent
    patterns = [
        base / "outputs" / "image_assets" / "*.png",
        base / "outputs" / "*.json",
        base / "outputs_phase2" / "raw_scenes" / "**" / "*.mp4",
        base / "outputs_phase2" / "stock" / "**" / "*.mp4",
        base / "outputs_phase2" / "audio" / "*.wav",
        base / "outputs_phase2" / "frames" / "**" / "*",
        base / "outputs_phase3" / "*.mp4",
        base / "outputs_phase3" / "*.srt",
        base / "outputs_phase3" / "*.json",
    ]
    assets: list[str] = []
    import glob

    for pattern in patterns:
        for item in glob.glob(str(pattern), recursive=True):
            if os.path.isfile(item):
                assets.append(os.path.abspath(item))
    return sorted(set(assets))


def _build_snapshot_state(extra: dict | None = None) -> dict:
    phase1_output = orchestrator.get_phase1_output()
    phase2_output = orchestrator.get_phase2_output()
    phase3_manifest = _load_json_file(Path("outputs_phase3/phase3_manifest.json"))

    snapshot = {
        "phase1_output": phase1_output.model_dump() if phase1_output else None,
        "phase2_output": phase2_output.model_dump() if phase2_output else None,
        "phase3_output": phase3_manifest or None,
        "pipeline_status": orchestrator.get_status().model_dump(),
    }
    if extra:
        snapshot.update(extra)
    return snapshot


def _snapshot_pipeline(description: str, extra: dict | None = None) -> None:
    edit_state_manager.snapshot(
        state_json=_build_snapshot_state(extra),
        description=description,
        asset_paths=_collect_snapshot_assets(),
    )


def _apply_snapshot_to_orchestrator(snapshot: dict) -> None:
    if snapshot.get("phase1_output"):
        orchestrator.phase1_output = Phase1Output.model_validate(snapshot["phase1_output"])
    if snapshot.get("phase2_output"):
        orchestrator.phase2_output = Phase2Output.model_validate(snapshot["phase2_output"])
    if snapshot.get("pipeline_status"):
        orchestrator.status = PipelineStatus.model_validate(snapshot["pipeline_status"])

    if snapshot.get("selected_scene_id") is not None:
        orchestrator.status.current_phase = f"scene:{snapshot['selected_scene_id']}"


# ── Health Check ────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """Check if the backend is running."""
    return {"status": "ok", "service": "Project Montage Backend"}


# ── Phase 1: Writer's Room Endpoints ────────────────────────────────────────

@app.post("/api/phase1/run", tags=["Phase 1"])
def run_phase1(request: Phase1Request):
    """
    Trigger Phase 1 execution (Writer's Room).
    
    Generates a script and character profiles based on the provided prompt or script file.
    """
    try:
        output = orchestrator.run_phase1(
            prompt=request.prompt,
            script_path=request.script_path
        )
        if output and not output.error:
            _snapshot_pipeline(f"Phase 1 completed: {request.prompt[:80]}")
        return {
            "success": True,
            "data": output.model_dump(),
            "message": "Phase 1 completed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class Phase1HITLRequest(BaseModel):
    approved: bool


@app.post("/api/phase1/hitl/approve", tags=["Phase 1"])
def approve_phase1_hitl(request: Phase1HITLRequest):
    """
    Resume Phase 1 after HITL review.
    Called by the frontend modal after the user reads and approves/rejects the script.
    """
    try:
        output = orchestrator.approve_hitl(approved=request.approved)
        msg = "Script approved — Phase 1 completed." if request.approved else "Script rejected — pipeline stopped."
        return {"success": True, "data": output.model_dump(), "message": msg}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/phase1/script", tags=["Phase 1"])
def get_phase1_script():
    """
    Retrieve the generated script from Phase 1.
    
    Returns the complete script with scenes and dialogue.
    """
    output = orchestrator.get_phase1_output()
    if output is None:
        raise HTTPException(status_code=404, detail="Phase 1 has not been run yet")
    
    if output.script is None:
        raise HTTPException(status_code=404, detail="No script available")
    
    return {
        "success": True,
        "data": output.script.model_dump(),
        "message": "Script retrieved successfully"
    }


@app.get("/api/phase1/character-image/{character_name}", tags=["Phase 1"])
def get_phase1_character_image(character_name: str):
    """
    Serve a Phase 1 character portrait from ``outputs/image_assets`` if present.
    Filenames follow the same sanitization as the Studio Floor pipeline.
    """
    from urllib.parse import unquote

    raw = unquote(character_name).strip()
    stem = "".join(c if c.isalnum() else "_" for c in raw)
    stem = stem.strip("_")
    if not stem:
        raise HTTPException(status_code=400, detail="Invalid character name")
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = Path(IMAGE_ASSETS_DIR) / f"{stem}{ext}"
        if path.is_file():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="Character image not found")


@app.get("/api/phase1/characters", tags=["Phase 1"])
def get_phase1_characters():
    """
    Retrieve character profiles from Phase 1.
    
    Returns all generated characters with descriptions, traits, and reference styles.
    """
    output = orchestrator.get_phase1_output()
    if output is None:
        raise HTTPException(status_code=404, detail="Phase 1 has not been run yet")
    
    return {
        "success": True,
        "data": [c.model_dump() for c in output.characters],
        "message": "Characters retrieved successfully"
    }


@app.get("/api/phase1/outputs", tags=["Phase 1"])
def get_phase1_outputs():
    """
    Retrieve all outputs from Phase 1.
    
    Includes script, characters, images, and metadata.
    """
    output = orchestrator.get_phase1_output()
    if output is None:
        raise HTTPException(status_code=404, detail="Phase 1 has not been run yet")
    
    return {
        "success": True,
        "data": output.model_dump(),
        "message": "Phase 1 outputs retrieved successfully"
    }


# ── Phase 2: Studio Floor Endpoints ─────────────────────────────────────────

@app.post("/api/phase2/run", tags=["Phase 2"])
def run_phase2(request: Phase2Request):
    """
    Trigger Phase 2 execution (Studio Floor).
    
    Generates videos from the script and characters created in Phase 1.
    Requires Phase 1 to have completed successfully.
    """
    try:
        output = orchestrator.run_phase2(scene_id=request.scene_id)
        if output:
            _snapshot_pipeline(
                f"Phase 2 completed{f' for scene {request.scene_id}' if request.scene_id else ''}"
            )
        return {
            "success": True,
            "data": output.model_dump(),
            "message": "Phase 2 completed"
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/phase2/videos", tags=["Phase 2"])
def get_phase2_videos():
    """
    Retrieve video outputs from Phase 2.
    
    Returns paths to generated video files for each scene.
    """
    output = orchestrator.get_phase2_output()
    if output is None:
        raise HTTPException(status_code=404, detail="Phase 2 has not been run yet")
    
    videos = [
        {
            "scene_id": scene.scene_id,
            "path": scene.raw_mp4_path,
            "error": scene.error
        }
        for scene in output.scenes
    ]
    
    return {
        "success": True,
        "data": videos,
        "message": "Videos retrieved successfully"
    }


@app.get("/api/phase2/video/{scene_id}", tags=["Phase 2"])
def stream_scene_video(scene_id: int):
    """
    Stream the MP4 video for a specific scene so the browser can play it.
    Scans disk directly so it works even after a server restart.
    """
    from fastapi.responses import FileResponse
    import os

    base = os.path.dirname(os.path.abspath(__file__))

    # Candidate paths in priority order
    candidates = [
        os.path.join(base, "outputs_phase2", "raw_scenes", f"scene_{scene_id:02d}.mp4"),
        os.path.join(base, "outputs_phase2", "raw_scenes", f"scene_{scene_id}.mp4"),
        os.path.join(base, "outputs_phase2", "raw_scenes", "Pexel-Pipeline", f"scene_{scene_id:02d}.mp4"),
        os.path.join(base, "outputs_phase2", "raw_scenes", "WAN2.2", f"scene_{scene_id:02d}.mp4"),
    ]

    # Also check orchestrator state if available
    try:
        output = orchestrator.get_phase2_output()
        if output:
            match = next((s for s in output.scenes if s.scene_id == scene_id), None)
            if match and match.raw_mp4_path and not match.error:
                p = match.raw_mp4_path if os.path.isabs(match.raw_mp4_path) else os.path.join(base, match.raw_mp4_path)
                candidates.insert(0, p)
    except Exception:
        pass

    for path in candidates:
        if os.path.exists(path):
            return FileResponse(path, media_type="video/mp4", filename=f"scene_{scene_id}.mp4")

    raise HTTPException(
        status_code=404,
        detail=f"Video for scene {scene_id} not found. Checked: {candidates}"
    )


@app.get("/api/phase2/outputs", tags=["Phase 2"])
def get_phase2_outputs():
    """
    Retrieve all outputs from Phase 2.

    Falls back to scanning disk when orchestrator has no in-memory state.
    """
    import os, glob

    output = orchestrator.get_phase2_output()
    if output is not None:
        return {
            "success": True,
            "data": output.model_dump(),
            "message": "Phase 2 outputs retrieved successfully"
        }

    # Fallback: scan disk for generated scene files
    base = os.path.dirname(os.path.abspath(__file__))
    raw_dir = os.path.join(base, "outputs_phase2", "raw_scenes")
    if not os.path.isdir(raw_dir):
        raise HTTPException(status_code=404, detail="Phase 2 has not been run yet")

    scenes = []
    for mp4 in sorted(glob.glob(os.path.join(raw_dir, "scene_*.mp4"))):
        fname = os.path.basename(mp4)          # scene_01.mp4
        try:
            sid = int(fname.replace("scene_", "").replace(".mp4", ""))
        except ValueError:
            continue
        scenes.append({"scene_id": sid, "raw_mp4_path": mp4, "error": None})

    if not scenes:
        raise HTTPException(status_code=404, detail="Phase 2 has not been run yet")

    return {
        "success": True,
        "data": {"scenes": scenes, "video_generation_mode": "pexels_stock"},
        "message": "Phase 2 outputs retrieved from disk"
    }


# ── Phase 3: Cutting Room Endpoints ─────────────────────────────────────────

class Phase3Request(BaseModel):
    transition_style: str = "fade"  # "fade", "cut", "wipe_left", "wipe_right", "dissolve", "fade_black"
    add_subtitles: bool = True


@app.post("/api/phase3/run", tags=["Phase 3"])
def run_phase3(request: Phase3Request):
    """
    Trigger Phase 3 execution (Cutting Room).
    
    Stitches all Phase 2 scene videos into a single final_output.mp4
    with transitions and optional subtitles.
    """
    try:
        from phase3_cutting_room.graph.workflow import build_phase3_graph
        from phase3_cutting_room.graph.state import initial_phase3_state
        
        # Load the Phase 1 scene manifest for subtitle generation
        scene_manifest = {}
        manifest_path = Path("outputs/scene_manifest.json")
        if manifest_path.exists():
            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                scene_manifest = json.load(f)
        
        # Build initial state for Phase 3
        state = initial_phase3_state(
            scene_manifest=scene_manifest,
            transition_style=request.transition_style,
            add_subtitles=request.add_subtitles,
        )
        
        # Execute the Phase 3 graph
        graph = build_phase3_graph()
        result = graph.invoke(state)
        if result and not result.get("error"):
            _snapshot_pipeline(
                f"Phase 3 completed ({request.transition_style}, subtitles={request.add_subtitles})"
            )
        
        return {
            "success": True,
            "data": {
                "final_output_path": result.get("final_output_path"),
                "duration_seconds": result.get("duration_seconds"),
                "scene_count": result.get("scene_count"),
                "phase3_manifest": result.get("phase3_manifest"),
                "events": result.get("events", []),
            },
            "message": "Phase 3 completed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/phase3/video", tags=["Phase 3"])
def get_final_video():
    """
    Stream the final composited MP4 from Phase 3.
    """
    final_path = Path("outputs_phase3/final_output.mp4")
    if not final_path.exists():
        raise HTTPException(status_code=404, detail="Final video not found. Run Phase 3 first.")
    
    return FileResponse(final_path, media_type="video/mp4", filename="final_output.mp4")


@app.get("/api/phase3/outputs", tags=["Phase 3"])
def get_phase3_outputs():
    """
    Retrieve metadata about the Phase 3 final video.
    """
    manifest_path = Path("outputs_phase3/phase3_manifest.json")
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Phase 3 has not been run yet")
    
    import json
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    return {
        "success": True,
        "data": manifest,
        "message": "Phase 3 outputs retrieved successfully"
    }


# ── Phase 5: Edit Agent Endpoints ───────────────────────────────────────────

@app.post("/api/edit/run", tags=["Phase 5"])
def run_edit(request: EditRequest):
    """Classify and execute a natural-language edit request."""
    try:
        current_state = _build_snapshot_state({"query": request.query, "selected_scene_id": request.scene_id, "scene_id": request.scene_id})
        result = edit_graph.invoke(
            {
                "query": request.query,
                "current_state": current_state,
                "scene_id": request.scene_id,
                "status": "pending",
            }
        )
        return {
            "success": True,
            "data": result,
            "message": result.get("response", "Edit executed successfully"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/edit/history", tags=["Phase 5"])
def get_edit_history():
    """Return saved version history for the undo UI."""
    return {
        "success": True,
        "data": edit_state_manager.history(),
        "message": "Edit history retrieved successfully",
    }


@app.post("/api/edit/undo/{version}", tags=["Phase 5"])
def undo_edit_version(version: int):
    """Restore assets and pipeline state from a previous snapshot."""
    try:
        record = edit_state_manager.revert(version)
        _apply_snapshot_to_orchestrator(record.state_json)
        return {
            "success": True,
            "data": {
                "version": record.version,
                "timestamp": record.timestamp,
                "description": record.description,
            },
            "message": f"Reverted to version {version}",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Pipeline Endpoints ──────────────────────────────────────────────────────

@app.get("/api/pipeline/status", tags=["Pipeline"])
def get_pipeline_status():
    """
    Get overall pipeline status.
    
    Returns completion status, timing, and error information for both phases.
    """
    status = orchestrator.get_status()
    return {
        "success": True,
        "data": status.model_dump(),
        "message": "Pipeline status retrieved"
    }


@app.post("/api/pipeline/run", tags=["Pipeline"])
def run_full_pipeline(request: Phase1Request):
    """
    Execute the full pipeline: Phase 1 followed by Phase 2.
    
    This is the complete workflow that generates a script, characters,
    and then produces videos from them.
    """
    try:
        orchestrator.reset()
        phase1_result, phase2_result = orchestrator.run_full_pipeline(
            prompt=request.prompt
        )
        
        return {
            "success": True,
            "data": {
                "phase1": phase1_result.model_dump(),
                "phase2": phase2_result.model_dump() if phase2_result else None
            },
            "message": "Full pipeline executed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/reset", tags=["Pipeline"])
def reset_pipeline():
    """
    Reset the pipeline state.
    
    Clears all results and status, allowing a fresh execution.
    """
    orchestrator.reset()
    return {
        "success": True,
        "message": "Pipeline reset successfully"
    }


# ── Config Endpoints ────────────────────────────────────────────────────────

@app.get("/api/config", tags=["Config"])
def get_config():
    """
    Get backend configuration for the frontend.
    
    Provides information about available phases and their status.
    """
    return {
        "success": True,
        "data": {
            "phases": ["phase1", "phase2"],
            "phase1_name": "Writer's Room",
            "phase2_name": "Studio Floor",
            "phase2_video_generation_mode": (
                "wan_i2v" if USE_VIDEO_MODEL else "pexels_stock"
            ),
            "features": [
                "script_generation",
                "character_design",
                "image_synthesis",
                "video_generation",
                "voice_synthesis",
                "face_swap",
                "lip_sync"
            ]
        }
    }


# ── MCP Endpoints (Integrated) ──────────────────────────────────────────────

from shared.mcp_server.server import list_tools, invoke_tool, InvokeRequest, ToolSchema

@app.get("/tools", response_model=list[ToolSchema], tags=["MCP"])
def get_mcp_tools():
    """List available MCP tools."""
    return list_tools()

@app.post("/invoke", tags=["MCP"])
def post_mcp_invoke(req: InvokeRequest):
    """Invoke an MCP tool."""
    return invoke_tool(req)


# ── Error Handlers ──────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    # Run the server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
