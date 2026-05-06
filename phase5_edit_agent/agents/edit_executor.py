"""Dispatch edit intents to the appropriate phase rerun."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend.orchestrator import get_orchestrator
from phase5_edit_agent.agents.intent_classifier import EditIntent
from phase5_edit_agent.state_manager import StateManager
from shared.config.config import BASE_DIR

state_manager = StateManager()
EDITS_DIR = BASE_DIR / "outputs_phase5" / "edits"
EDITS_DIR.mkdir(parents=True, exist_ok=True)


def _parse_scope_scene(scope: str) -> int | None:
    if scope.startswith("scene:"):
        try:
            return int(scope.split(":", 1)[1])
        except Exception:
            return None
    return None


def _normalize_transition_style(raw: str | None) -> str:
    if not raw:
        return "fade"
    style = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "wipeleft": "wipe_left",
        "wiperight": "wipe_right",
        "fadeblack": "fade_black",
    }
    style = aliases.get(style, style)
    allowed = {"fade", "cut", "wipe_left", "wipe_right", "dissolve", "fade_black"}
    return style if style in allowed else "fade"


def _parse_scope_character(scope: str) -> str | None:
    if scope.startswith("character:"):
        value = scope.split(":", 1)[1].strip()
        return value or None
    return None


def _resolve_selected_scene_id(
    intent: EditIntent,
    current_state: dict[str, Any],
    scene_id: int | None,
) -> int | None:
    if scene_id is not None:
        return int(scene_id)

    scoped_scene_id = _parse_scope_scene(intent.scope)
    if scoped_scene_id is not None:
        return scoped_scene_id

    selected_scene_id = current_state.get("selected_scene_id")
    if selected_scene_id is not None:
        return int(selected_scene_id)

    current_scene_id = current_state.get("scene_id")
    if current_scene_id is not None:
        return int(current_scene_id)

    phase2_output = current_state.get("phase2_output")
    if isinstance(phase2_output, dict):
        for scene in phase2_output.get("scenes", []) or []:
            if isinstance(scene, dict) and not scene.get("error") and scene.get("scene_id") is not None:
                return int(scene["scene_id"])

    phase1_output = current_state.get("phase1_output")
    if isinstance(phase1_output, dict):
        script = phase1_output.get("script", {})
        if isinstance(script, dict):
            scenes = script.get("scenes", []) or []
            if scenes:
                first_scene = scenes[0]
                if isinstance(first_scene, dict) and first_scene.get("scene_id") is not None:
                    return int(first_scene["scene_id"])

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


def _phase2_scene_path(scene_id: int) -> Path | None:
    candidates = [
        BASE_DIR / "outputs_phase2" / "raw_scenes" / f"scene_{scene_id:02d}.mp4",
        BASE_DIR / "outputs_phase2" / "raw_scenes" / f"scene_{scene_id}.mp4",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _manifest_path() -> Path:
    return BASE_DIR / "outputs" / "scene_manifest.json"


def _load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_manifest(data: dict[str, Any]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def _scene_duration(path: Path) -> float:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return float((probe.stdout or "0").strip() or "0")
    except Exception:
        return 0.0


def _update_manifest_for_voice_tone(scene_id: int | None, tone: str) -> None:
    manifest = _load_manifest()
    scenes = manifest.get("scenes", [])
    for scene in scenes:
        if scene_id is not None and int(scene.get("scene_id", -1)) != scene_id:
            continue
        for line in scene.get("dialogue", []) or []:
            line["emotion"] = tone
    if scenes:
        _save_manifest(manifest)


def _update_manifest_for_visual_edit(scene_id: int | None, look: str | None, design_update: bool) -> None:
    manifest = _load_manifest()
    scenes = manifest.get("scenes", [])
    look_suffix = ""
    if look == "darker":
        look_suffix = " darker cinematic lighting"
    elif look == "brighter":
        look_suffix = " brighter cinematic lighting"
    design_suffix = " redesigned character appearance and outfit details" if design_update else ""
    for scene in scenes:
        if scene_id is not None and int(scene.get("scene_id", -1)) != scene_id:
            continue
        for line in scene.get("dialogue", []) or []:
            cue = str(line.get("visual_cue", "")).strip()
            merged = f"{cue}{look_suffix}{design_suffix}".strip()
            if merged:
                line["visual_cue"] = merged
    if scenes:
        _save_manifest(manifest)


def _overlay_background_music(scene_id: int) -> bool:
    scene_path = _phase2_scene_path(scene_id)
    if scene_path is None:
        return False
    duration = _scene_duration(scene_path)
    if duration <= 0:
        duration = 8.0
    temp_output = scene_path.with_name(f"{scene_path.stem}_bgm_tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(scene_path),
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:sample_rate=44100:duration={duration}",
        "-filter_complex",
        "[1:a]volume=0.08[music];[0:a][music]amix=inputs=2:duration=first[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(temp_output),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
    if result.returncode != 0 or not temp_output.is_file():
        return False
    shutil.move(str(temp_output), str(scene_path))
    return True


def _speed_adjust_scene(scene_id: int, speed: float) -> bool:
    scene_path = _phase2_scene_path(scene_id)
    if scene_path is None:
        return False
    speed = max(0.5, min(float(speed), 2.0))
    temp_output = scene_path.with_name(f"{scene_path.stem}_speed_tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(scene_path),
        "-filter_complex",
        f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        str(temp_output),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
    if result.returncode != 0 or not temp_output.is_file():
        return False
    shutil.move(str(temp_output), str(scene_path))
    return True


def _parse_speed_factor(raw_speed: Any) -> float:
    """Convert free-form speed hints into a safe ffmpeg factor."""
    if raw_speed is None:
        return 1.25
    if isinstance(raw_speed, (int, float)):
        return max(0.5, min(float(raw_speed), 2.0))

    text = str(raw_speed).strip().lower()
    if not text:
        return 1.25
    if "slow" in text:
        return 0.8
    if "fast" in text or "speed up" in text:
        return 1.25

    # Accept forms like "1.5x"
    cleaned = text.replace("x", "").strip()
    try:
        return max(0.5, min(float(cleaned), 2.0))
    except ValueError:
        return 1.25


def _is_speed_intent(intent: EditIntent) -> bool:
    name = (intent.intent or "").lower()
    if "speed" in name or "adjust_speed" in name:
        return True
    query_hint = str(intent.parameters.get("query", "")).lower()
    return "speed up" in query_hint or "slow down" in query_hint


def _default_speed_for_intent(intent: EditIntent) -> float:
    name = (intent.intent or "").lower()
    query_hint = str(intent.parameters.get("query", "")).lower()
    if "slow" in name or "slow down" in query_hint:
        return 0.8
    return 1.25


def _save_edit_clip(scene_id: int | None, source_path: Path | None, edit_version: int) -> str | None:
    if scene_id is None or source_path is None or not source_path.is_file():
        return None
    target = EDITS_DIR / f"v{edit_version}_scene_{scene_id:02d}.mp4"
    shutil.copy2(source_path, target)
    return target.name


def _save_before_clip(scene_id: int | None, source_path: Path | None, before_version: int) -> str | None:
    if scene_id is None or source_path is None or not source_path.is_file():
        return None
    target = EDITS_DIR / f"v{before_version}_scene_{scene_id:02d}_before.mp4"
    shutil.copy2(source_path, target)
    return target.name


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
    if selected_scene_id is None:
        # granular default: keep edits scoped where possible
        selected_scene_id = current_state.get("selected_scene_id")
    tone = intent.parameters.get("tone")
    music_action = intent.parameters.get("music_action")
    if tone and selected_scene_id is not None:
        _update_manifest_for_voice_tone(int(selected_scene_id), str(tone))
    if intent.target == "video_frame":
        _update_manifest_for_visual_edit(
            int(selected_scene_id) if selected_scene_id is not None else None,
            str(intent.parameters.get("look")) if intent.parameters.get("look") else None,
            bool(intent.parameters.get("design_update")),
        )
    output = orchestrator.run_phase2(scene_id=selected_scene_id)
    music_overlayed = False
    if (
        intent.intent == "add_background_music"
        or str(music_action).lower() in {"add", "change"}
    ) and selected_scene_id is not None:
        music_overlayed = _overlay_background_music(int(selected_scene_id))
    return {
        "phase2_output": output.model_dump(),
        "edited_scope": {
            "scene_id": selected_scene_id,
            "character": _parse_scope_character(intent.scope),
            "target": intent.target,
        },
        "music_overlayed": music_overlayed,
    }


def _rerun_phase3(intent: EditIntent, current_state: dict[str, Any]) -> dict[str, Any]:
    from phase3_cutting_room.graph.state import initial_phase3_state
    from phase3_cutting_room.graph.workflow import build_phase3_graph

    scene_manifest = _load_scene_manifest()
    transition_style = _normalize_transition_style(intent.parameters.get("transition_style"))
    add_subtitles = bool(intent.parameters.get("add_subtitles", True))
    state = initial_phase3_state(
        scene_manifest=scene_manifest,
        transition_style=transition_style,
        add_subtitles=add_subtitles,
    )
    graph = build_phase3_graph()
    result = graph.invoke(state)
    return {
        "phase3_output": result,
        "composition_changes": {
            "transition_style": transition_style,
            "add_subtitles": add_subtitles,
            "speed": intent.parameters.get("speed"),
        },
    }


def execute_edit(intent: EditIntent, current_state: dict[str, Any], state_mgr: StateManager | None = None) -> dict[str, Any]:
    """Execute an edit and store before/after snapshots."""
    manager = state_mgr or state_manager
    scene_id = _resolve_selected_scene_id(intent, current_state, current_state.get("scene_id") or current_state.get("selected_scene_id"))
    before_assets = _collect_current_assets()
    original_scene_path = _phase2_scene_path(scene_id) if scene_id is not None else None
    before_version = manager.snapshot(
        state_json={"query": current_state.get("query"), "current_state": current_state, "intent": intent.model_dump()},
        description=f"Before edit: {intent.intent}",
        asset_paths=before_assets,
    )
    before_clip_name = _save_before_clip(scene_id, original_scene_path, before_version)

    if intent.target == "script":
        updated = _rerun_phase1(intent, current_state, scene_id)
    elif intent.target in {"audio", "video_frame"}:
        updated = _rerun_phase2(intent, current_state, scene_id)
    elif intent.target == "video":
        selected_scene_id = _resolve_selected_scene_id(intent, current_state, scene_id)
        if _is_speed_intent(intent) and selected_scene_id is not None:
            raw_speed = intent.parameters.get("speed", _default_speed_for_intent(intent))
            speed_factor = _parse_speed_factor(raw_speed)
            speed_applied = _speed_adjust_scene(int(selected_scene_id), speed_factor)
            updated = {
                "speed_adjusted": speed_applied,
                "speed_factor": speed_factor,
                "phase2_output": get_orchestrator().get_phase2_output().model_dump() if get_orchestrator().get_phase2_output() else None,
            }
        else:
            updated = _rerun_phase3(intent, current_state)
    else:
        raise ValueError(f"Unknown target: {intent.target}")

    selected_scene_id = _resolve_selected_scene_id(intent, current_state, scene_id)
    preview_video_url = "/api/phase3/video" if intent.target == "video" else None
    if intent.target == "video" and _is_speed_intent(intent) and selected_scene_id is not None:
        preview_video_url = f"/api/phase2/video/{selected_scene_id}"
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
    edited_scene_path = _phase2_scene_path(selected_scene_id) if selected_scene_id is not None else None
    edited_clip_name = _save_edit_clip(selected_scene_id, edited_scene_path, after_version)

    return {
        "classified_intent": intent.model_dump(),
        "updated_state": after_state,
        "selected_scene_id": selected_scene_id,
        "preview_video_url": preview_video_url,
        "original_video_url": (
            f"/api/edit/clip/{before_clip_name}" if before_clip_name else None
        ),
        "edited_clip_url": (
            f"/api/edit/clip/{edited_clip_name}" if edited_clip_name else None
        ),
        "edit_saved": bool(edited_clip_name),
        "before_version": before_version,
        "after_version": after_version,
        "history": manager.history(),
    }
