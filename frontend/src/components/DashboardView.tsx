/* DashboardView — Phase 11
   Merges PipelineView (controls / status) with WorkflowView (flow diagram).
   Layout: left control panel (fixed 380px) + right workflow visualization.
*/

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../hooks/api';
import type { PipelineStatus, Module } from '../types';
import WorkflowView from './WorkflowView';
import ModuleDetailModal from './ModuleDetailModal';

const statusColor: Record<string, string> = {
  completed:   'text-green-400',
  in_progress: 'text-yellow-400',
  failed:      'text-red-400',
  pending:     'text-slate-500',
};

export default function DashboardView() {
  const [status, setStatus]   = useState<PipelineStatus | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [resetMsg, setResetMsg] = useState('');

  useEffect(() => {
    const load = () => {
      api.getPipelineStatus().then(setStatus).catch(() => {});
      api.getModules().then(setModules).catch(() => {});
    };
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleStart  = () => api.startPipeline().then(setStatus).catch(() => {});
  const handlePause  = () => api.pausePipeline().catch(() => {});
  const handleApprove = () =>
    api.approveGate().then((r) => { if (r.approved) api.getPipelineStatus().then(setStatus); });
  const handleRetryModuleMaker = () =>
    api.retryModuleMaker().then((r) => { if (r.approved) api.getPipelineStatus().then(setStatus); });
  const handleRetryPromptGenerator = () =>
    api.retryPromptGenerator().then((r) => { if (r.approved) api.getPipelineStatus().then(setStatus); });
  const handleRetryCodeGenerator = () =>
    api.retryCodeGenerator().then((r) => { if (r.approved) api.getPipelineStatus().then(setStatus); });
  const handleRetryCodeReviewer = () =>
    api.retryCodeReviewer().then((r) => { if (r.approved) api.getPipelineStatus().then(setStatus); });
  const handleSkipToNextModule = () =>
    api.skipToNextModule().then((r) => {
      if (r.approved) {
        api.getPipelineStatus().then(setStatus);
        api.getModules().then(setModules);
      }
    });
  const handleReset = () =>
    api.resetPipeline()
      .then((r) => {
        setResetMsg(r.message);
        setShowResetConfirm(false);
        if (r.success) {
          api.getPipelineStatus().then(setStatus);
          api.getModules().then(setModules);
        }
      })
      .catch(() => { setResetMsg('Reset failed'); setShowResetConfirm(false); });

  // ── Derived flags ────────────────────────────────────────────────────────────
  const isFailed    = status?.pipeline_status === 'FAILED';
  const preFailure  = isFailed ? (status?.metadata?.pre_failure_status as string | undefined) : undefined;

  const isModuleReview =
    status?.pipeline_status === 'HITL_1_MODULE_REVIEW' ||
    (isFailed && ['MODULE_PLANNING', 'HITL_1_MODULE_REVIEW', 'PROMPT_GENERATION', 'HITL_2_PROMPT_REVIEW'].includes(preFailure ?? ''));

  const isPromptReview =
    status?.pipeline_status === 'HITL_2_PROMPT_REVIEW' ||
    (isFailed && ['PROMPT_GENERATION', 'HITL_2_PROMPT_REVIEW'].includes(preFailure ?? ''));

  const isCodeGenRetryable =
    ['HITL_3_REVIEW_DECISION', 'VALIDATION', 'CODE_REVIEW'].includes(status?.pipeline_status ?? '') ||
    (isFailed && ['CODE_GENERATION', 'VALIDATION', 'CODE_REVIEW', 'HITL_3_REVIEW_DECISION'].includes(preFailure ?? ''));

  const isCodeReviewRetryable =
    status?.pipeline_status === 'HITL_3_REVIEW_DECISION' ||
    (isFailed && ['CODE_REVIEW', 'HITL_3_REVIEW_DECISION'].includes(preFailure ?? ''));

  const canSkip =
    status?.pipeline_status === 'HITL_3_REVIEW_DECISION' ||
    status?.pipeline_status === 'HITL_4_MAX_ITERATIONS';

  const total     = modules.length;
  const done      = modules.filter((m) => m.status === 'completed').length;
  const progress  = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="flex gap-5 h-full min-h-0">
      {/* ── Left: Control panel ─────────────────────────────────────────────── */}
      <aside className="w-[380px] shrink-0 flex flex-col gap-4 overflow-y-auto pr-1" style={{ minWidth: 280 }}>

        {/* Status card */}
        <div className="glass-card">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Pipeline Status</p>
          {status ? (
            <>
              <p className={`text-xl font-semibold font-mono ${isFailed ? 'text-red-400' : 'text-white'}`}>
                {status.pipeline_status}
              </p>
              {isFailed && preFailure && (
                <p className="text-xs text-red-400 mt-0.5">Failed during: {preFailure}</p>
              )}
              {status.current_module_id && (
                <p className="text-xs text-[var(--text-secondary)] mt-1 font-mono">
                  {status.current_module_id} — iter {status.current_iteration}
                </p>
              )}
              {!!status.metadata?.repo_url && (
                <a
                  href={status.metadata.repo_url as string}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 mt-1 text-xs text-purple-400 hover:text-purple-300 transition-colors"
                >
                  ↗ {(status.metadata.repo_url as string).replace('https://github.com/', '')}
                </a>
              )}
            </>
          ) : (
            <p className="text-sm text-[var(--text-muted)] animate-pulse">Loading…</p>
          )}
        </div>

        {/* Progress bar */}
        {total > 0 && (
          <div className="glass-card">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-[var(--text-secondary)]">Module Progress</p>
              <p className="text-xs font-semibold text-white">{done}/{total}</p>
            </div>
            <div className="w-full h-1.5 rounded-full bg-white/5">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-purple-500"
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
            <p className="text-[10px] text-[var(--text-muted)] mt-1 text-right">{progress}%</p>
          </div>
        )}

        {/* Primary actions */}
        <div className="glass-card space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">Controls</p>

          <div className="flex gap-2">
            <button
              onClick={handleStart}
              className="flex-1 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium transition-colors"
            >
              ▶ Start / Resume
            </button>
            <button
              onClick={handlePause}
              className="px-3 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm font-medium transition-colors"
            >
              ⏸
            </button>
          </div>

          {status?.is_hitl_gate && (
            <motion.button
              onClick={handleApprove}
              className="w-full px-3 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-sm font-medium"
              animate={{ boxShadow: ['0 0 0 rgba(34,197,94,0)', '0 0 18px rgba(34,197,94,0.45)', '0 0 0 rgba(34,197,94,0)'] }}
              transition={{ repeat: Infinity, duration: 2 }}
            >
              ✓ Approve Gate
            </motion.button>
          )}

          {isModuleReview && (
            <button onClick={handleRetryModuleMaker} className="w-full px-3 py-2 rounded-lg bg-amber-700 hover:bg-amber-600 text-sm font-medium transition-colors">
              ↺ Retry Module Maker
            </button>
          )}
          {isPromptReview && (
            <button onClick={handleRetryPromptGenerator} className="w-full px-3 py-2 rounded-lg bg-amber-700 hover:bg-amber-600 text-sm font-medium transition-colors">
              ↺ Retry Prompt Generator
            </button>
          )}
          {isCodeGenRetryable && (
            <button onClick={handleRetryCodeGenerator} className="w-full px-3 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-sm font-medium transition-colors">
              ↺ Retry Code Generator
            </button>
          )}
          {isCodeReviewRetryable && (
            <button onClick={handleRetryCodeReviewer} className="w-full px-3 py-2 rounded-lg bg-teal-700 hover:bg-teal-600 text-sm font-medium transition-colors">
              ↺ Retry Code Reviewer
            </button>
          )}
          {canSkip && (
            <button onClick={handleSkipToNextModule} className="w-full px-3 py-2 rounded-lg bg-orange-700 hover:bg-orange-600 text-sm font-medium transition-colors">
              ⏭ Skip to Next Module
            </button>
          )}
        </div>

        {/* Module list */}
        {modules.length > 0 && (
          <div className="glass-card">
            <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">Modules</p>
            <div className="space-y-1 max-h-52 overflow-y-auto">
              {modules.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setSelectedModuleId(m.id)}
                  className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/5 transition-colors group"
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    m.status === 'completed' ? 'bg-green-400' :
                    m.status === 'in_progress' ? 'bg-yellow-400 animate-pulse' :
                    m.status === 'failed' ? 'bg-red-400' : 'bg-slate-600'
                  }`} />
                  <span className={`text-xs font-mono truncate flex-1 ${statusColor[m.status] ?? 'text-slate-400'}`}>
                    {m.id}
                  </span>
                  <span className="text-[10px] text-slate-700 group-hover:text-slate-500 transition-colors">↗</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Danger zone */}
        <div className="glass-card border-red-500/15">
          <p className="text-[10px] uppercase tracking-widest text-red-400/60 mb-2">Danger Zone</p>
          {!showResetConfirm ? (
            <button
              onClick={() => setShowResetConfirm(true)}
              className="w-full px-3 py-2 rounded-lg border border-red-500/25 text-red-400 hover:bg-red-500/10 text-sm font-medium transition-colors"
            >
              ↺ Reset Pipeline
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-red-300">This will clear all progress. Are you sure?</p>
              <div className="flex gap-2">
                <button onClick={handleReset} className="flex-1 px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-xs font-medium transition-colors">
                  Confirm Reset
                </button>
                <button onClick={() => setShowResetConfirm(false)} className="flex-1 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-xs font-medium transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          )}
          {resetMsg && <p className="text-xs text-slate-400 mt-2">{resetMsg}</p>}
        </div>
      </aside>

      {/* ── Right: Workflow visualization ───────────────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-hidden">
        <WorkflowView />
      </div>

      {/* Module detail modal */}
      <AnimatePresence>
        {selectedModuleId && (
          <ModuleDetailModal
            moduleId={selectedModuleId}
            onClose={() => setSelectedModuleId(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
