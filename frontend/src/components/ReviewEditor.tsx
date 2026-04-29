/* Review Editor (HITL) — interactive review panel with override controls */

import { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import { api } from '../hooks/api';

const DEFAULT_REVIEW = JSON.stringify(
  { overall_status: 'needs_changes', convergence_score: 0, files: [], ac_verification: {} },
  null,
  2
);

export default function ReviewEditor() {
  const [content, setContent] = useState(DEFAULT_REVIEW);
  const [moduleId, setModuleId] = useState<string | null>(null);
  const [iteration, setIteration] = useState<number | null>(null);
  const [loadError, setLoadError] = useState('');
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch the current review on mount (and whenever it changes)
  useEffect(() => {
    api
      .getCurrentReview()
      .then((r) => {
        setContent(r.content);
        setModuleId(r.module_id);
        setIteration(r.iteration);
        setLoadError('');
      })
      .catch(() => {
        setLoadError('No review available yet — pipeline has not reached the review stage.');
      });
  }, []);

  // Auto-save 1 s after the last keystroke
  const handleChange = (v: string | undefined) => {
    const val = v ?? '';
    setContent(val);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      setSaving(true);
      api
        .updateCurrentReview(val)
        .then(() => {
          setStatus('Saved');
          setSaving(false);
        })
        .catch(() => {
          setStatus('Save failed');
          setSaving(false);
        });
    }, 1000);
  };

  const handleApprove = () => {
    // Flush any pending save first
    if (saveTimer.current) clearTimeout(saveTimer.current);
    api
      .updateCurrentReview(content)
      .then(() => api.approveGate('hitl_3_review_decision'))
      .then((r) => setStatus(r.message))
      .catch(() => setStatus('Error approving gate'));
  };

  const handleReject = () => {
    setStatus('Rejected — edit review and re-approve');
  };

  return (
    <div className="space-y-4">
      <div className="glass-card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Review Editor (HITL Gate 3)</h2>
            {moduleId && (
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                Module: {moduleId} · Iteration {iteration}
                {saving && <span className="ml-2 opacity-60">saving…</span>}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-xs font-medium transition-colors"
            >
              Approve
            </button>
            <button
              onClick={handleReject}
              className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-xs font-medium transition-colors"
            >
              Reject
            </button>
          </div>
        </div>
        {loadError && (
          <p className="text-xs text-yellow-400 mb-2">{loadError}</p>
        )}
        {status && (
          <p className="text-xs text-[var(--text-secondary)] mb-2">{status}</p>
        )}
        <div className="rounded-lg overflow-hidden border border-[var(--border-glass)]">
          <Editor
            height="calc(100vh - 16rem)"
            defaultLanguage="json"
            theme="vs-dark"
            value={content}
            onChange={handleChange}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'on',
            }}
          />
        </div>
      </div>
    </div>
  );
}

