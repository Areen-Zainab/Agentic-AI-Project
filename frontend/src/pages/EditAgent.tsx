import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

interface EditIntent {
  intent: string;
  target: 'audio' | 'video_frame' | 'video' | 'script';
  scope: string;
  parameters: Record<string, unknown>;
  confidence: number;
}

interface VersionRecord {
  version: number;
  timestamp: string;
  description: string;
}

interface SceneOption {
  scene_id: number;
  location?: string;
  characters?: string[];
}

interface EditRunResult {
  classified_intent?: EditIntent;
  execution_result?: Record<string, unknown>;
  response?: string;
  history?: VersionRecord[];
  preview_video_url?: string;
  before_version?: number;
  after_version?: number;
  selected_scene_id?: number | null;
}

const API = 'http://localhost:8000/api';

const EditAgent = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [undoingVersion, setUndoingVersion] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [intent, setIntent] = useState<EditIntent | null>(null);
  const [result, setResult] = useState<EditRunResult | null>(null);
  const [history, setHistory] = useState<VersionRecord[]>([]);
  const [scenes, setScenes] = useState<SceneOption[]>([]);
  const [selectedSceneId, setSelectedSceneId] = useState<number | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [beforeVersion, setBeforeVersion] = useState<number | null>(null);
  const [afterVersion, setAfterVersion] = useState<number | null>(null);
  const [reviewMode, setReviewMode] = useState(false);

  const loadHistory = async () => {
    try {
      const res = await fetch(`${API}/edit/history`);
      if (res.ok) {
        const data = await res.json();
        setHistory(Array.isArray(data.data) ? data.data : []);
      }
    } catch {
      setHistory([]);
    }
  };

  const loadScenes = async () => {
    try {
      const res = await fetch(`${API}/phase1/script`);
      if (!res.ok) {
        return;
      }
      const data = await res.json();
      const loadedScenes = Array.isArray(data.data?.scenes) ? data.data.scenes : [];
      const options = loadedScenes.map((scene: any) => ({
        scene_id: scene.scene_id,
        location: scene.location,
        characters: scene.characters,
      }));
      setScenes(options);
      if (options.length > 0 && selectedSceneId === null) {
        setSelectedSceneId(options[0].scene_id);
      }
    } catch {
      setScenes([]);
    }
  };

  useEffect(() => {
    void loadHistory();
    void loadScenes();
  }, []);

  useEffect(() => {
    if (!loading) {
      setLoadingStep(0);
      return;
    }
    const timer = setInterval(() => {
      setLoadingStep((step) => (step < 4 ? step + 1 : step));
    }, 2500);
    return () => clearInterval(timer);
  }, [loading]);

  const handleRunEdit = async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      setError('Enter an edit request first.');
      return;
    }

    setLoading(true);
    setError(null);
    setNotice(null);
    setIntent(null);
    setResult(null);
    setPreviewUrl(null);
    setBeforeVersion(null);
    setAfterVersion(null);
    setReviewMode(false);

    try {
      const res = await fetch(`${API}/edit/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: trimmed, scene_id: selectedSceneId }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Edit execution failed');
      }

      const runResult = (data.data || {}) as EditRunResult;
      setResult(runResult);
      setIntent(runResult.classified_intent || null);
      setPreviewUrl(runResult.preview_video_url ? `${API.replace('/api', '')}${runResult.preview_video_url}` : null);
      setBeforeVersion(runResult.before_version ?? null);
      setAfterVersion(runResult.after_version ?? null);
      setReviewMode(true);
      setNotice(data.message || runResult.response || 'Review the preview and accept or reject the changes.');
      await loadHistory();
    } catch (err: any) {
      setError(err.message || 'An error occurred while running the edit.');
    } finally {
      setLoading(false);
    }
  };

  const handleAccept = async () => {
    if (afterVersion === null) {
      setNotice('Nothing to accept yet.');
      return;
    }
    setReviewMode(false);
    setNotice(`Changes accepted at version ${afterVersion}.`);
    await loadHistory();
  };

  const handleUndo = async (version: number) => {
    setUndoingVersion(version);
    setError(null);
    setNotice(null);
    setReviewMode(false);
    setPreviewUrl(null);
    try {
      const res = await fetch(`${API}/edit/undo/${version}`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Undo failed');
      }
      setNotice(data.message || `Reverted to version ${version}`);
      await loadHistory();
    } catch (err: any) {
      setError(err.message || 'Undo failed.');
    } finally {
      setUndoingVersion(null);
    }
  };

  const steps = [
    { icon: '🧠', label: 'Classify' },
    { icon: '🧪', label: 'Validate' },
    { icon: '⚙️', label: 'Execute' },
    { icon: '🗂️', label: 'Snapshot' },
    { icon: '💬', label: 'Respond' },
  ];

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=DM+Sans:wght@300;400;500;700&family=DM+Mono:wght@400&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes pulse { 0%,100%{ opacity:1; } 50%{ opacity:0.5; } }
        @keyframes spin { to { transform: rotate(360deg); } }

        .e-root { display: flex; min-height: 100vh; background: #0a0a0b; color: #e8e0d0; font-family: 'DM Sans', sans-serif; }
        .e-sidebar { width: 240px; min-width: 240px; position: fixed; top: 0; left: 0; bottom: 0; background: #111113; border-right: 1px solid #1e1e22; display: flex; flex-direction: column; padding: 28px 0 24px; }
        .e-logo { padding: 0 24px 28px; border-bottom: 1px solid #1e1e22; }
        .e-logo-eyebrow { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #9c8eb5; margin-bottom: 4px; }
        .e-logo-title { font-family: 'Playfair Display', serif; font-size: 20px; font-weight: 700; color: #f0e8d8; }
        .e-nav { padding: 20px 24px 16px; border-bottom: 1px solid #1e1e22; }
        .e-nav-lbl { font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase; color: #4a4a55; margin-bottom: 12px; }
        .e-link-row { display: flex; align-items: center; gap: 10px; padding: 7px 0; }
        .e-link-name { flex: 1; font-size: 13px; color: #b0a898; }
        .e-link-dot { width: 6px; height: 6px; border-radius: 50%; background: #4a4a55; }
        .e-sidebar-footer { margin-top: auto; padding: 16px 24px 0; border-top: 1px solid #1e1e22; font-size: 10px; color: #3a3a44; font-family: 'DM Mono', monospace; }

        .e-main { margin-left: 240px; flex: 1; display: flex; flex-direction: column; }
        .e-topbar { position: sticky; top: 0; z-index: 50; background: rgba(10,10,11,0.92); backdrop-filter: blur(8px); border-bottom: 1px solid #1e1e22; padding: 0 40px; height: 52px; display: flex; align-items: center; justify-content: space-between; }
        .e-breadcrumb { font-family: 'DM Mono', monospace; font-size: 11px; color: #4a4a55; display: flex; align-items: center; gap: 8px; }
        .e-breadcrumb span { color: #9c8eb5; }
        .e-phase-badge { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.12em; background: rgba(156,142,181,0.12); color: #9c8eb5; border: 1px solid rgba(156,142,181,0.25); border-radius: 4px; padding: 4px 10px; text-transform: uppercase; }
        .e-content { padding: 48px 40px 80px; max-width: 1080px; }

        .e-hero { margin-bottom: 36px; }
        .e-hero-eyebrow { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: #9c8eb5; margin-bottom: 12px; }
        .e-hero-title { font-family: 'Playfair Display', serif; font-size: 46px; font-weight: 700; color: #f0e8d8; line-height: 1.1; margin-bottom: 12px; }
        .e-hero-sub { font-size: 15px; color: #6a6268; font-weight: 300; max-width: 720px; line-height: 1.6; }

        .e-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr); gap: 24px; align-items: start; }
        .e-panel { background: #111113; border: 1px solid #1e1e22; border-radius: 12px; overflow: hidden; }
        .e-panel-hd { padding: 20px 22px; border-bottom: 1px solid #1e1e22; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
        .e-panel-title { font-family: 'Playfair Display', serif; font-size: 19px; color: #f0e8d8; }
        .e-panel-sub { font-size: 12px; color: #6a6268; font-family: 'DM Mono', monospace; }
        .e-panel-body { padding: 22px; }

        .e-textarea { width: 100%; min-height: 168px; resize: vertical; background: #0d0d0f; color: #e8e0d0; border: 1px solid #1e1e22; border-radius: 10px; padding: 16px; font-size: 14px; line-height: 1.6; font-family: 'DM Sans', sans-serif; outline: none; }
        .e-textarea:focus { border-color: rgba(156,142,181,0.45); box-shadow: 0 0 0 3px rgba(156,142,181,0.08); }

        .e-run-btn { width: 100%; margin-top: 16px; background: linear-gradient(135deg, #9c8eb5 0%, #7d6d99 100%); color: #fff; border: none; border-radius: 10px; padding: 15px 24px; font-size: 15px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 10px; transition: transform 0.2s ease, box-shadow 0.2s ease; box-shadow: 0 8px 22px rgba(156,142,181,0.2); }
        .e-run-btn:hover:not(:disabled) { transform: translateY(-1px); }
        .e-run-btn:disabled { opacity: 0.65; cursor: not-allowed; }
        .e-spinner { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.25); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }

        .e-status { display: grid; gap: 16px; }
        .e-message { padding: 16px 18px; background: rgba(156,142,181,0.08); border: 1px solid rgba(156,142,181,0.15); border-radius: 10px; color: #cfc4de; font-size: 14px; line-height: 1.6; }
        .e-error { padding: 16px 18px; background: rgba(208,128,128,0.1); border-left: 4px solid #D08080; border-radius: 8px; color: #f0c9c9; font-size: 14px; }

        .e-card { background: #0d0d0f; border: 1px solid #1e1e22; border-radius: 10px; overflow: hidden; }
        .e-card-hd { padding: 14px 16px; border-bottom: 1px solid #1e1e22; font-family: 'DM Mono', monospace; text-transform: uppercase; letter-spacing: 0.12em; font-size: 10px; color: #9c8eb5; }
        .e-card-body { padding: 16px; display: grid; gap: 10px; }
        .e-field { display: grid; gap: 4px; }
        .e-field-lbl { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #4a4a55; font-family: 'DM Mono', monospace; }
        .e-field-val { font-size: 14px; color: #e8e0d0; word-break: break-word; }
        .e-json { white-space: pre-wrap; font-size: 12px; line-height: 1.6; color: #c9c0b2; background: #0a0a0b; border: 1px solid #1e1e22; border-radius: 8px; padding: 12px; max-height: 220px; overflow: auto; }

        .e-steps { display: flex; flex-direction: column; gap: 8px; }
        .e-step { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: #0d0d0f; border: 1px solid #1e1e22; border-radius: 8px; color: #4a4a55; }
        .e-step.active { color: #9c8eb5; background: rgba(156,142,181,0.08); }
        .e-step.done { color: #4a9e6f; background: rgba(74,158,111,0.08); }
        .e-step-status { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.12em; }

        .e-history { display: grid; gap: 12px; }
        .e-history-item { padding: 14px 16px; background: #0d0d0f; border: 1px solid #1e1e22; border-radius: 10px; display: grid; gap: 10px; }
        .e-history-top { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
        .e-history-title { font-size: 14px; color: #f0e8d8; font-weight: 600; }
        .e-history-meta { font-size: 11px; color: #5c5c67; font-family: 'DM Mono', monospace; }
        .e-history-desc { font-size: 13px; color: #c2b8aa; line-height: 1.5; }
        .e-revert-btn { border: 1px solid #2a2a30; background: transparent; color: #d5cde0; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.15s ease; }
        .e-revert-btn:hover:not(:disabled) { border-color: rgba(156,142,181,0.45); color: #fff; }
        .e-revert-btn:disabled { opacity: 0.6; cursor: not-allowed; }

        .e-cta-bar { margin-top: 28px; padding-top: 28px; border-top: 1px solid #1a1a20; display: flex; align-items: center; justify-content: space-between; }
        .e-cta-hint { font-size: 12px; color: #3a3a44; font-family: 'DM Mono', monospace; }
        .e-btn-back { background: transparent; color: #9a9288; border: 1px solid #2a2a30; border-radius: 7px; padding: 11px 24px; font-family: 'DM Sans', sans-serif; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
        .e-btn-back:hover { border-color: #3a3a40; color: #c8c0b0; }
      `}</style>

      <div className="e-root">
        <aside className="e-sidebar">
          <div className="e-logo">
            <div className="e-logo-eyebrow">Phase 5</div>
            <div className="e-logo-title">Edit Agent</div>
          </div>
          <div className="e-nav">
            <div className="e-nav-lbl">Workflow</div>
            {steps.map((step) => (
              <div key={step.label} className="e-link-row">
                <span>{step.icon}</span>
                <span className="e-link-name">{step.label}</span>
                <span className="e-link-dot" />
              </div>
            ))}
          </div>
          <div className="e-sidebar-footer">CS-4015 Agentic AI · FAST NUCES</div>
        </aside>

        <main className="e-main">
          <div className="e-topbar">
            <div className="e-breadcrumb">Montage <span>/</span> Phase 5 — Edit Agent</div>
            <div className="e-phase-badge">Edit + Undo</div>
          </div>

          <div className="e-content">
            <div className="e-hero">
              <div className="e-hero-eyebrow">Phase 5 · Edit Agent</div>
              <h1 className="e-hero-title">Describe an edit and re-run the right part of the pipeline.</h1>
              <p className="e-hero-sub">
                The agent classifies your request, executes the appropriate rerun,
                stores snapshots before and after, and exposes the version history
                so you can revert any step.
              </p>
            </div>

            {error && (
              <div className="e-error">
                <strong>Error</strong>
                <div>{error}</div>
              </div>
            )}

            {notice && (
              <div className="e-message">
                {notice}
              </div>
            )}

            <div className="e-grid">
              <section className="e-panel">
                <div className="e-panel-hd">
                  <div>
                    <div className="e-panel-title">Edit Request</div>
                    <div className="e-panel-sub">Free-text command → classified intent</div>
                  </div>
                  <div className="e-panel-sub">/api/edit/run</div>
                </div>
                <div className="e-panel-body">
                          <div className="e-field" style={{ marginBottom: '14px' }}>
                            <div className="e-field-lbl">Scene</div>
                            <select
                              className="e-textarea"
                              style={{ minHeight: 'unset', padding: '12px 14px' }}
                              value={selectedSceneId ?? ''}
                              onChange={(event) => setSelectedSceneId(event.target.value ? Number(event.target.value) : null)}
                            >
                              <option value="">All scenes</option>
                              {scenes.map((scene) => (
                                <option key={scene.scene_id} value={scene.scene_id}>
                                  Scene {scene.scene_id}{scene.location ? ` — ${scene.location}` : ''}
                                </option>
                              ))}
                            </select>
                          </div>
                  <textarea
                    className="e-textarea"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Example: Make the narrator sound sad in scene 2 and add fade transitions between scenes."
                  />
                  <button className="e-run-btn" onClick={handleRunEdit} disabled={loading}>
                    {loading ? (
                      <>
                        <span className="e-spinner" />
                        Running Edit Agent...
                      </>
                    ) : (
                      'Run Edit Agent'
                    )}
                  </button>
                </div>
              </section>

              <aside className="e-status">
                <div className="e-panel">
                  <div className="e-panel-hd">
                    <div>
                      <div className="e-panel-title">Agent Progress</div>
                      <div className="e-panel-sub">classify → validate → execute → snapshot → respond</div>
                    </div>
                    {loading && <div className="e-panel-sub">running</div>}
                  </div>
                  <div className="e-panel-body">
                    <div className="e-steps">
                      {steps.map((step, index) => {
                        const cls = loading
                          ? index < loadingStep
                            ? 'done'
                            : index === loadingStep
                              ? 'active'
                              : ''
                          : '';
                        return (
                          <div key={step.label} className={`e-step ${cls}`}>
                            <span>{step.label}</span>
                            <span className="e-step-status">
                              {loading
                                ? index < loadingStep
                                  ? 'DONE'
                                  : index === loadingStep
                                    ? 'RUNNING'
                                    : 'WAIT'
                                : 'READY'}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                <div className="e-card">
                  <div className="e-card-hd">Classified Intent</div>
                  <div className="e-card-body">
                    {intent ? (
                      <>
                        <div className="e-field">
                          <div className="e-field-lbl">Intent</div>
                          <div className="e-field-val">{intent.intent}</div>
                        </div>
                        <div className="e-field">
                          <div className="e-field-lbl">Target</div>
                          <div className="e-field-val">{intent.target}</div>
                        </div>
                        <div className="e-field">
                          <div className="e-field-lbl">Scope</div>
                          <div className="e-field-val">{intent.scope}</div>
                        </div>
                        <div className="e-field">
                          <div className="e-field-lbl">Confidence</div>
                          <div className="e-field-val">{Math.round(intent.confidence * 100)}%</div>
                        </div>
                        <div className="e-field">
                          <div className="e-field-lbl">Parameters</div>
                          <pre className="e-json">{JSON.stringify(intent.parameters, null, 2)}</pre>
                        </div>
                      </>
                    ) : (
                      <div className="e-field-val" style={{ color: '#6a6268' }}>
                        Run an edit to see the classified intent here.
                      </div>
                    )}
                  </div>
                </div>

                <div className="e-card">
                  <div className="e-card-hd">Execution Preview</div>
                  <div className="e-card-body">
                    {previewUrl ? (
                      <video
                        controls
                        preload="metadata"
                        src={previewUrl}
                        style={{ width: '100%', borderRadius: '8px', border: '1px solid #1e1e22' }}
                      />
                    ) : result?.response ? (
                      <div className="e-field-val">{result.response}</div>
                    ) : (
                      <div className="e-field-val" style={{ color: '#6a6268' }}>
                        The latest edit result will appear here.
                      </div>
                    )}
                    {result?.execution_result && (
                      <pre className="e-json">{JSON.stringify(result.execution_result, null, 2)}</pre>
                    )}
                    {reviewMode && (
                      <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
                        <button className="e-run-btn" style={{ marginTop: 0, flex: 1 }} onClick={handleAccept}>
                          Accept Changes
                        </button>
                        <button
                          className="e-revert-btn"
                          style={{ flex: 1 }}
                          onClick={() => beforeVersion !== null && handleUndo(beforeVersion)}
                          disabled={beforeVersion === null}
                        >
                          Reject Changes
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </aside>
            </div>

            <section className="e-panel" style={{ marginTop: '24px' }}>
              <div className="e-panel-hd">
                <div>
                  <div className="e-panel-title">Version History</div>
                  <div className="e-panel-sub">Snapshots created before and after edits</div>
                </div>
                <div className="e-panel-sub">/api/edit/history</div>
              </div>
              <div className="e-panel-body">
                <div className="e-history">
                  {history.length > 0 ? (
                    history.map((record) => (
                      <div key={record.version} className="e-history-item">
                        <div className="e-history-top">
                          <div>
                            <div className="e-history-title">Version {record.version}</div>
                            <div className="e-history-meta">{record.timestamp}</div>
                          </div>
                          <button
                            className="e-revert-btn"
                            onClick={() => handleUndo(record.version)}
                            disabled={undoingVersion === record.version}
                          >
                            {undoingVersion === record.version ? 'Reverting...' : 'Revert'}
                          </button>
                        </div>
                        <div className="e-history-desc">{record.description}</div>
                      </div>
                    ))
                  ) : (
                    <div className="e-history-item">
                      <div className="e-history-desc">
                        No versions saved yet. Run Phase 1, Phase 2, Phase 3, or an edit to create snapshots.
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>

            <div className="e-cta-bar">
              <div className="e-cta-hint">← Phase 3</div>
              <div style={{ display: 'flex', gap: '12px' }}>
                <button className="e-btn-back" onClick={() => navigate('/phase3')}>
                  ← Back to Phase 3
                </button>
                <button className="e-btn-back" onClick={() => navigate('/')}>
                  Back to Phase 1
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
};

export default EditAgent;
