/* Prompt Editor (HITL) — Monaco markdown editor with approve/reject */

import { useCallback, useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import { api } from '../hooks/api';
import type { PipelineStatus } from '../types';

const PLACEHOLDER =
  '# Waiting for prompt…\n\nThe prompt will load automatically when the pipeline reaches the HITL_2 prompt review gate.';

export default function PromptEditor() {
  const [content, setContent] = useState(PLACEHOLDER);
  const [status, setStatus] = useState('');
  const [moduleId, setModuleId] = useState<string | null>(null);
  const [iteration, setIteration] = useState(0);
  const [loading, setLoading] = useState(false);
  const [dirty, setDirty] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadPrompt = useCallback(() => {
    api.getCurrentPrompt()
      .then((p) => {
        setContent(p.content);
        setModuleId(p.module_id);
        setIteration(p.iteration);
        setDirty(false);
        setStatus('');
      })
      .catch(() => {
        // Prompt not available yet — check pipeline status to show context
        api.getPipelineStatus().then((ps: PipelineStatus) => {
          if (ps.pipeline_status === 'HITL_2_PROMPT_REVIEW') {
            setStatus('Prompt file not found — try Retry Prompt Generator.');
          }
        }).catch(() => {});
      });
  }, []);

  // Initial load + polling every 3s
  useEffect(() => {
    loadPrompt();
    pollRef.current = setInterval(loadPrompt, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadPrompt]);

  // Stop polling once we have content (avoid overwriting edits)
  useEffect(() => {
    if (moduleId && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [moduleId]);

  const handleSave = async () => {
    setLoading(true);
    try {
      await api.updateCurrentPrompt(content);
      setDirty(false);
      setStatus('Saved');
    } catch {
      setStatus('Error saving prompt');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    setLoading(true);
    try {
      // Persist edits before approving
      if (dirty) {
        await api.updateCurrentPrompt(content);
        setDirty(false);
      }
      const r = await api.approveGate('hitl_2_prompt_review');
      setStatus(r.message);
      if (r.approved) {
        // Reset after approval — will re-poll for next prompt
        setModuleId(null);
        setContent(PLACEHOLDER);
        pollRef.current = setInterval(loadPrompt, 3000);
      }
    } catch {
      setStatus('Error approving gate');
    } finally {
      setLoading(false);
    }
  };

  const handleReload = () => {
    loadPrompt();
  };

  return (
    <div className="space-y-4">
      <div className="glass-card">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold">Prompt Editor (HITL Gate 2)</h2>
            {moduleId && (
              <span className="text-xs text-[var(--text-secondary)]">
                {moduleId} · Iteration {iteration}
                {dirty && <span className="text-amber-400 ml-1">· Unsaved</span>}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleReload}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg bg-slate-600 hover:bg-slate-500 text-xs font-medium transition-colors disabled:opacity-50"
            >
              Reload
            </button>
            <button
              onClick={handleSave}
              disabled={loading || !dirty}
              className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs font-medium transition-colors disabled:opacity-50"
            >
              Save
            </button>
            <button
              onClick={handleApprove}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-xs font-medium transition-colors disabled:opacity-50"
            >
              Approve
            </button>
          </div>
        </div>
        {status && (
          <p className="text-xs text-[var(--text-secondary)] mb-2">{status}</p>
        )}
        <div className="rounded-lg overflow-hidden border border-[var(--border-glass)]">
          <Editor
            height="calc(100vh - 14rem)"
            defaultLanguage="markdown"
            theme="vs-dark"
            value={content}
            onChange={(v) => {
              setContent(v || '');
              if (moduleId) setDirty(true);
            }}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              wordWrap: 'on',
              lineNumbers: 'on',
              readOnly: !moduleId,
            }}
          />
        </div>
      </div>
    </div>
  );
}
