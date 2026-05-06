"""Dispatch edit intents to the appropriate phase rerun."""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any

from backend.orchestrator import get_orchestrator
from phase5_edit_agent.agents.intent_classifier import EditIntent
from phase5_edit_agent.state_manager import StateManager
from shared.config.config import BASE_DIR

state_manager = StateManager()


def _parse_scope_scene(scope: str) -> int | None:
    if scope.startswith("scene:"):
        try:
            return int(scope.split(":", 1)[1])
        except Exception:
            return None
    return None


def _collect_current_assets() -> list[str]:
    patterns = [
        "outputs_phase2/raw_scenes/**/*.mp4",
        "outputs_phase2/stock/**/*.mp4",
        "outputs_phase3/*.mp4",
        "outputs_phase3/*.srt",
        "outputs/image_assets/*.png",
        "outputs/*.json",
    ]
    assets: list[str] = []
    for pattern in patterns:
        for item in glob.glob(str(BASE_DIR / pattern), recursive=True):
            if os.path.isfile(item):
                assets.append(os.path.abspath(item))
    return sorted(set(assets))


def _load_scene_manifest() -> dict[str, Any]:
    manifest_path = BASE_DIR / "outputs" / "scene_manifest.json"
    if not manifest_path.is_file():
        return {}
    with open(manifest_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _rerun_phase1(intent: EditIntent, current_state: dict[str, Any], scene_id: int | None) -> dict[str, Any]:
    orchestrator = get_orchestrator()
    base_prompt = current_state.get("query") or intent.parameters.get("query") or "Revise the existing story"
    if scene_id is not None:
        base_prompt = f"Scene {scene_id}: {base_prompt}"
    output = orchestrator.run_phase1(
        prompt=f"{base_prompt}. Edit request: {intent.intent}. Details: {intent.parameters}"
    )
    updated: dict[str, Any] = {"phase1_output": output.model_dump()}
    if scene_id is not None:
        phase2_output = orchestrator.run_phase2(scene_id=scene_id)
        updated["phase2_output"] = phase2_output.model_dump()
    return updated


def _rerun_phase2(intent: EditIntent, current_state: dict[str, Any], scene_id: int | None) -> dict[str, Any]:
    orchestrator = get_orchestrator()
    selected_scene_id = scene_id if scene_id is not None else _parse_scope_scene(intent.scope)
    output = orchestrator.run_phase2(scene_id=selected_scene_id)
    return {"phase2_output": output.model_dump()}


def _rerun_phase3(intent: EditIntent, current_state: dict[str, Any]) -> dict[str, Any]:
    from phase3_cutting_room.graph.state import initial_phase3_state
    from phase3_cutting_room.graph.workflow import build_phase3_graph

    scene_manifest = _load_scene_manifest()
    transition_style = str(intent.parameters.get("transition_style", "fade"))
    add_subtitles = bool(intent.parameters.get("add_subtitles", True))
    state = initial_phase3_state(
        scene_manifest=scene_manifest,
        transition_style=transition_style,
        add_subtitles=add_subtitles,
    )
    graph = build_phase3_graph()
    result = graph.invoke(state)
    return {"phase3_output": result}


def execute_edit(intent: EditIntent, current_state: dict[str, Any], state_mgr: StateManager | None = None) -> dict[str, Any]:
    """Execute an edit and store before/after snapshots."""
    manager = state_mgr or state_manager
    scene_id = current_state.get("scene_id") or current_state.get("selected_scene_id")
    before_assets = _collect_current_assets()
    before_version = manager.snapshot(
        state_json={"query": current_state.get("query"), "current_state": current_state, "intent": intent.model_dump()},
        description=f"Before edit: {intent.intent}",
        asset_paths=before_assets,
    )

    if intent.target == "script":
        updated = _rerun_phase1(intent, current_state, scene_id)
    elif intent.target in {"audio", "video_frame"}:
        updated = _rerun_phase2(intent, current_state, scene_id)
    elif intent.target == "video":
        updated = _rerun_phase3(intent, current_state)
    else:
        raise ValueError(f"Unknown target: {intent.target}")

    selected_scene_id = scene_id if scene_id is not None else _parse_scope_scene(intent.scope)
    preview_video_url = "/api/phase3/video" if intent.target == "video" else None
    if intent.target != "video" and selected_scene_id is not None:
        preview_video_url = f"/api/phase2/video/{selected_scene_id}"

    after_state = {
        **current_state,
        **updated,
        "classified_intent": intent.model_dump(),
        "selected_scene_id": selected_scene_id,
        "preview_video_url": preview_video_url,
    }
    after_assets = _collect_current_assets()
    after_version = manager.snapshot(
        state_json=after_state,
        description=f"After edit: {intent.intent}",
        asset_paths=after_assets,
    )

    return {
        "classified_intent": intent.model_dump(),
        "updated_state": after_state,
        "selected_scene_id": selected_scene_id,
        "preview_video_url": preview_video_url,
        "before_version": before_version,
        "after_version": after_version,
        "history": manager.history(),
    }
