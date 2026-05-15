/* DashboardView — Phase 5
   Left: pipeline status card, iteration counter, Start/Pause/Approve/Reset controls.
   Right: PipelineFlowDiagram (compact embed).
   No module references — all module-based UI removed.
*/

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../hooks/api';
import { usePipelineFlow } from '../hooks/usePipelineFlow';
import PipelineFlowDiagram from './PipelineFlowDiagram';

export default function DashboardView() {
  const { pipelineStatus, isHitlGate, currentIteration, statusText, loading } = usePipelineFlow();
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [resetMsg, setResetMsg] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);

  // ── Helpers ─────────────────────────────────────────────────────────────────
  const withError = <T,>(p: Promise<T>) =>
    p.catch((e: unknown) => setActionError(String(e)));

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleStart   = () => { setActionError(null); withError(api.startPipeline()); };
  const handlePause   = () => { setActionError(null); withError(api.pausePipeline()); };
  const handleApprove = () => { setActionError(null); withError(api.approveGate()); };
  const handleReset = () =>
    api.resetPipeline()
      .then((r) => {
        setResetMsg((r as { message?: string }).message ?? 'Reset queued');
        setShowResetConfirm(false);
      })
      .catch(() => { setResetMsg('Reset failed'); setShowResetConfirm(false); });

  const isFailed = pipelineStatus === 'FAILED';
  const isComplete = pipelineStatus === 'PIPELINE_COMPLETE';

  // Status badge colour
  const statusColour = isFailed  ? 'text-red-400'
    : isComplete                 ? 'text-green-400'
    : isHitlGate                 ? 'text-yellow-400'
    : pipelineStatus === 'IDLE'  ? 'text-slate-500'
    :                              'text-indigo-400';

  return (
    <div className="flex gap-5 h-full min-h-0">

      {/* ── Left: Control panel ─────────────────────────────────────────────── */}
      <aside className="w-[360px] shrink-0 flex flex-col gap-4 overflow-y-auto pr-1" style={{ minWidth: 260 }}>

        {/* Action error banner */}
        <AnimatePresence>
          {actionError && (
            <motion.div
              key="action-error"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-xs"
            >
              <span className="flex-1">{actionError}</span>
              <button onClick={() => setActionError(null)} className="hover:text-white transition-colors">✕</button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Pipeline status card */}
        <div className="glass-card">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Pipeline Status</p>
          {loading ? (
            <p className="text-sm text-[var(--text-muted)] animate-pulse">Loading…</p>
          ) : (
            <>
              <p className={`text-lg font-semibold font-mono ${statusColour}`}>{pipelineStatus}</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">{statusText}</p>
              {currentIteration > 0 && (
                <p className="text-[10px] font-mono text-slate-500 mt-1">Iteration {currentIteration}</p>
              )}
            </>
          )}
        </div>

        {/* Primary controls */}
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

          <AnimatePresence>
            {isHitlGate && (
              <motion.button
                key="approve-gate"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 6 }}
                onClick={handleApprove}
                className="w-full px-3 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-sm font-medium"
                style={{ boxShadow: '0 0 14px rgba(34,197,94,0.35)' }}
              >
                ✓ Approve Gate
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        {/* Danger zone — directly below Controls */}
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

      {/* ── Right: Pipeline flow diagram ─────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="glass-card flex-1 min-h-0 flex flex-col items-center justify-center py-6">
          <PipelineFlowDiagram
            pipelineStatus={pipelineStatus}
            currentIteration={currentIteration}
            compact={false}
          />
        </div>
      </div>
    </div>
  );
}


