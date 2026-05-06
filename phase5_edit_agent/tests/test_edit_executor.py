import pytest

pytest.importorskip("langgraph")

from phase5_edit_agent.agents.edit_executor import execute_edit
from phase5_edit_agent.agents.intent_classifier import EditIntent


class _StubStateMgr:
    def __init__(self):
        self._v = 0

    def snapshot(self, state_json, description, asset_paths):
        self._v += 1
        return self._v

    def history(self):
        return [{"version": self._v, "description": "stub"}]


def test_execute_edit_audio_scene_scoped(monkeypatch):
    from phase5_edit_agent.agents import edit_executor as mod

    class _StubOutput:
        def model_dump(self):
            return {"scenes": [{"scene_id": 2, "raw_mp4_path": "scene_02.mp4"}]}

    class _StubOrchestrator:
        def run_phase2(self, scene_id=None):
            assert scene_id == 2
            return _StubOutput()

    monkeypatch.setattr(mod, "get_orchestrator", lambda: _StubOrchestrator())
    monkeypatch.setattr(mod, "_collect_current_assets", lambda: [])
    monkeypatch.setattr(mod, "_phase2_scene_path", lambda scene_id: None)

    intent = EditIntent(
        intent="update_audio",
        target="audio",
        scope="scene:2",
        parameters={"tone": "sad"},
        confidence=0.9,
    )
    result = execute_edit(intent, {"query": "make scene 2 sad"}, state_mgr=_StubStateMgr())
    assert result["selected_scene_id"] == 2
    assert result["before_version"] == 1
    assert result["after_version"] == 2


def test_execute_edit_video_composition_params(monkeypatch):
    from phase5_edit_agent.agents import edit_executor as mod

    monkeypatch.setattr(mod, "_collect_current_assets", lambda: [])
    monkeypatch.setattr(mod, "_phase2_scene_path", lambda scene_id: None)
    monkeypatch.setattr(
        mod,
        "_rerun_phase3",
        lambda intent, current_state: {
            "phase3_output": {"ok": True},
            "composition_changes": {
                "transition_style": intent.parameters.get("transition_style"),
                "add_subtitles": intent.parameters.get("add_subtitles"),
            },
        },
    )
    intent = EditIntent(
        intent="update_video_composition",
        target="video",
        scope="all",
        parameters={"transition_style": "cut", "add_subtitles": False},
        confidence=0.95,
    )
    result = execute_edit(intent, {"query": "cut + no subtitles"}, state_mgr=_StubStateMgr())
    assert result["preview_video_url"] == "/api/phase3/video"


def test_execute_edit_adjust_speed_without_numeric_parameter(monkeypatch):
    from phase5_edit_agent.agents import edit_executor as mod

    monkeypatch.setattr(mod, "_collect_current_assets", lambda: [])
    monkeypatch.setattr(mod, "_phase2_scene_path", lambda scene_id: None)
    monkeypatch.setattr(mod, "_speed_adjust_scene", lambda scene_id, speed: True)

    class _StubOrchestrator:
        def get_phase2_output(self):
            return None

    monkeypatch.setattr(mod, "get_orchestrator", lambda: _StubOrchestrator())

    intent = EditIntent(
        intent="adjust_speed",
        target="video",
        scope="all",
        parameters={"query": "speed up this scene"},
        confidence=0.91,
    )
    result = execute_edit(
        intent,
        {"query": "speed up this scene", "selected_scene_id": 2},
        state_mgr=_StubStateMgr(),
    )
    assert result["preview_video_url"] == "/api/phase2/video/2"


def test_execute_edit_video_speed_falls_back_to_phase2_scene(monkeypatch):
    from phase5_edit_agent.agents import edit_executor as mod

    seen_scene_ids = []

    monkeypatch.setattr(mod, "_collect_current_assets", lambda: [])
    monkeypatch.setattr(mod, "_phase2_scene_path", lambda scene_id: None)
    monkeypatch.setattr(mod, "_speed_adjust_scene", lambda scene_id, speed: seen_scene_ids.append((scene_id, speed)) or True)

    class _StubOutput:
        def model_dump(self):
            return {"scenes": [{"scene_id": 3, "raw_mp4_path": "scene_03.mp4", "error": None}]}

    class _StubOrchestrator:
        def get_phase2_output(self):
            return _StubOutput()

    monkeypatch.setattr(mod, "get_orchestrator", lambda: _StubOrchestrator())

    intent = EditIntent(
        intent="adjust_speed",
        target="video",
        scope="all",
        parameters={"speed": 1.25},
        confidence=0.99,
    )
    result = execute_edit(
        intent,
        {"query": "adjust speed", "phase2_output": {"scenes": [{"scene_id": 3, "error": None}]}} ,
        state_mgr=_StubStateMgr(),
    )

    assert seen_scene_ids == [(3, 1.25)]
    assert result["selected_scene_id"] == 3
