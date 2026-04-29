/* Module Editor (HITL) — Monaco JSON editor for module plan review */

import { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import { api } from '../hooks/api';
import type { ModuleDefinitionsPayload } from '../types';

export default function ModuleEditor() {
  const [content, setContent] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const payloadRef = useRef<ModuleDefinitionsPayload | null>(null);

  const loadDefinitions = () => {
    setLoading(true);
    api.getModuleDefinitions()
      .then((payload) => {
        payloadRef.current = payload;
        setContent(JSON.stringify(payload.modules, null, 2));
        setLoading(false);
      })
      .catch(() => {
        // Fall back to DB summary if definitions not yet available
        api.getModules()
          .then((mods) => setContent(JSON.stringify(mods, null, 2)))
          .catch(() => {});
        setLoading(false);
      });
  };

  useEffect(() => { loadDefinitions(); }, []);

  const handleApprove = async () => {
    // Persist edits before advancing the pipeline
    try {
      const editedModules = JSON.parse(content);
      const body: ModuleDefinitionsPayload = {
        modules: Array.isArray(editedModules) ? editedModules : [],
        project_folder_structure: payloadRef.current?.project_folder_structure ?? [],
      };
      await api.saveModuleDefinitions(body);
      payloadRef.current = body;
    } catch {
      setStatus('JSON parse error — fix the JSON before approving');
      return;
    }
    api.approveGate('hitl_1_module_review')
      .then((r) => setStatus(r.message))
      .catch(() => setStatus('Error approving gate'));
  };

  const handleRetry = () => {
    setStatus('Retrying Module Maker generation...');
    api.retryModuleMaker()
      .then((r) => {
        setStatus(r.message);
        if (r.approved) {
          const poll = setInterval(() => {
            api.getPipelineStatus().then((s) => {
              if (s.pipeline_status === 'HITL_1_MODULE_REVIEW') {
                clearInterval(poll);
                loadDefinitions();
                setStatus('Module Maker completed — review the new plan');
              }
            }).catch(() => {});
          }, 3000);
        }
      })
      .catch(() => setStatus('Error retrying Module Maker'));
  };

  const handleSaveDraft = () => {
    try {
      const editedModules = JSON.parse(content);
      const body: ModuleDefinitionsPayload = {
        modules: Array.isArray(editedModules) ? editedModules : [],
        project_folder_structure: payloadRef.current?.project_folder_structure ?? [],
      };
      api.saveModuleDefinitions(body)
        .then(() => {
          payloadRef.current = body;
          setStatus('Draft saved');
        })
        .catch(() => setStatus('Save failed'));
    } catch {
      setStatus('JSON parse error — cannot save');
    }
  };

  return (
    <div className="space-y-4">
      <div className="glass-card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Module Editor (HITL Gate 1)</h2>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              Full blueprint JSON — edit freely, then Approve to save &amp; continue
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleSaveDraft}
              className="px-3 py-1.5 rounded-lg bg-[var(--glass-hover)] hover:bg-[var(--border-glass)] text-xs font-medium transition-colors"
            >
              Save Draft
            </button>
            <button
              onClick={handleApprove}
              className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-xs font-medium transition-colors"
            >
              Approve
            </button>
            <button
              onClick={handleRetry}
              className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-xs font-medium transition-colors"
            >
              Retry Generation
            </button>
            <button
              onClick={() => setStatus('Rejected — edit and re-approve')}
              className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-xs font-medium transition-colors"
            >
              Reject
            </button>
          </div>
        </div>
        {status && (
          <p className="text-xs text-[var(--text-secondary)] mb-2">{status}</p>
        )}
        <div className="rounded-lg overflow-hidden border border-[var(--border-glass)]">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-xs text-[var(--text-secondary)]">
              Loading module definitions…
            </div>
          ) : (
            <Editor
              height="calc(100vh - 16rem)"
              defaultLanguage="json"
              theme="vs-dark"
              value={content}
              onChange={(v) => setContent(v || '')}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                wordWrap: 'off',
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
