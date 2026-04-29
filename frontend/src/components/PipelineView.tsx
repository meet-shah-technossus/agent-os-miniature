/* Pipeline View — module cards, iteration progress, status overview */

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../hooks/api';
import type { PipelineStatus, Module } from '../types';
import ModuleDetailModal from './ModuleDetailModal';

const statusColor: Record<string, string> = {
  completed: 'bg-green-500',
  in_progress: 'bg-yellow-500',
  failed: 'bg-red-500',
  pending: 'bg-slate-600',
};

export default function PipelineView() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [resetStatus, setResetStatus] = useState('');

  useEffect(() => {
    const load = () => {
      api.getPipelineStatus().then(setStatus).catch(() => {});
      api.getModules().then(setModules).catch(() => {});
    };
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  const handleStart = () => {
    api.startPipeline().then(setStatus).catch(() => {});
  };

  const handlePause = () => {
    api.pausePipeline().catch(() => {});
  };

  const handleApprove = () => {
    api.approveGate().then((r) => {
      if (r.approved) api.getPipelineStatus().then(setStatus);
    });
  };

  const handleRetryModuleMaker = () => {
    api.retryModuleMaker().then((r) => {
      if (r.approved) api.getPipelineStatus().then(setStatus);
    });
  };

  const handleRetryPromptGenerator = () => {
    api.retryPromptGenerator().then((r) => {
      if (r.approved) api.getPipelineStatus().then(setStatus);
    });
  };

  const handleRetryCodeGenerator = () => {
    api.retryCodeGenerator().then((r) => {
      if (r.approved) api.getPipelineStatus().then(setStatus);
    });
  };

  const handleRetryCodeReviewer = () => {
    api.retryCodeReviewer().then((r) => {
      if (r.approved) api.getPipelineStatus().then(setStatus);
    });
  };

  const handleSkipToNextModule = () => {
    api.skipToNextModule().then((r) => {
      if (r.approved) {
        api.getPipelineStatus().then(setStatus);
        api.getModules().then(setModules);
      }
    });
  };

  const handleReset = () => {
    api.resetPipeline().then((r) => {
      setResetStatus(r.message);
      setShowResetConfirm(false);
      if (r.success) {
        // Refresh data after reset
        api.getPipelineStatus().then(setStatus);
        api.getModules().then(setModules);
      }
    }).catch(() => {
      setResetStatus('Reset request failed');
      setShowResetConfirm(false);
    });
  };

  const isFailed = status?.pipeline_status === 'FAILED';
  const preFailure = isFailed ? (status?.metadata?.pre_failure_status as string | undefined) : undefined;

  const isModuleReview =
    status?.pipeline_status === 'HITL_1_MODULE_REVIEW' ||
    (isFailed && (
      preFailure === 'MODULE_PLANNING' ||
      preFailure === 'HITL_1_MODULE_REVIEW' ||
      preFailure === 'PROMPT_GENERATION' ||
      preFailure === 'HITL_2_PROMPT_REVIEW'
    ));

  const isPromptReview =
    status?.pipeline_status === 'HITL_2_PROMPT_REVIEW' ||
    (isFailed && (preFailure === 'PROMPT_GENERATION' || preFailure === 'HITL_2_PROMPT_REVIEW'));

  const isCodeGenRetryable =
    status?.pipeline_status === 'HITL_3_REVIEW_DECISION' ||
    status?.pipeline_status === 'VALIDATION' ||
    status?.pipeline_status === 'CODE_REVIEW' ||
    (isFailed && (
      preFailure === 'CODE_GENERATION' ||
      preFailure === 'VALIDATION' ||
      preFailure === 'CODE_REVIEW' ||
      preFailure === 'HITL_3_REVIEW_DECISION'
    ));

  const isCodeReviewRetryable =
    status?.pipeline_status === 'HITL_3_REVIEW_DECISION' ||
    (isFailed && (
      preFailure === 'CODE_REVIEW' ||
      preFailure === 'HITL_3_REVIEW_DECISION'
    ));

  const canSkipToNextModule =
    status?.pipeline_status === 'HITL_3_REVIEW_DECISION' ||
    status?.pipeline_status === 'HITL_4_MAX_ITERATIONS';

  return (
    <div className="space-y-6">
      {/* Status banner */}
      {status && (
        <div className="glass-card flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              Pipeline Status
            </p>
            <p className={`text-xl font-semibold mt-1 ${isFailed ? 'text-red-400' : ''}`}>
              {status.pipeline_status}
            </p>
            {isFailed && preFailure && (
              <p className="text-sm text-red-400 mt-1">
                Failed during: {preFailure}
              </p>
            )}
            {status.current_module_id && (
              <p className="text-sm text-[var(--text-secondary)] mt-1">
                Module: {status.current_module_id} — Iteration {status.current_iteration}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleStart}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium transition-colors"
            >
              Start / Resume
            </button>
            <button
              onClick={handlePause}
              className="px-4 py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-sm font-medium transition-colors"
            >
              Pause
            </button>
            {status.is_hitl_gate && (
              <motion.button
                onClick={handleApprove}
                animate={{ boxShadow: ['0 0 0 rgba(34,197,94,0)', '0 0 20px rgba(34,197,94,0.4)', '0 0 0 rgba(34,197,94,0)'] }}
                transition={{ repeat: Infinity, duration: 2 }}
                className="px-4 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-sm font-medium"
              >
                Approve Gate
              </motion.button>
            )}
            {isModuleReview && (
              <button
                onClick={handleRetryModuleMaker}
                className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-sm font-medium transition-colors"
              >
                Retry Module Maker
              </button>
            )}
            {isPromptReview && (
              <button
                onClick={handleRetryPromptGenerator}
                className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-sm font-medium transition-colors"
              >
                Retry Prompt Generator
              </button>
            )}
            {isCodeGenRetryable && (
              <button
                onClick={handleRetryCodeGenerator}
                className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-sm font-medium transition-colors"
              >
                Retry Code Generator
              </button>
            )}
            {isCodeReviewRetryable && (
              <button
                onClick={handleRetryCodeReviewer}
                className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-sm font-medium transition-colors"
              >
                Retry Code Reviewer
              </button>
            )}
            {canSkipToNextModule && (
              <button
                onClick={handleSkipToNextModule}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-medium transition-colors"
              >
                Accept &amp; Next Module
              </button>
            )}
            <button
              onClick={() => setShowResetConfirm(true)}
              className="px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 text-sm font-medium transition-colors"
            >
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Reset status message */}
      {resetStatus && (
        <div className="glass-card text-sm text-[var(--text-secondary)]">
          {resetStatus}
          <button
            onClick={() => setResetStatus('')}
            className="ml-3 text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* Reset confirmation modal */}
      <AnimatePresence>
        {showResetConfirm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
            onClick={() => setShowResetConfirm(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="glass-card max-w-md w-full mx-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold text-red-400 mb-3">
                Reset Entire Pipeline?
              </h3>
              <p className="text-sm text-[var(--text-secondary)] mb-4">
                This will permanently delete <strong>all modules, iterations, prompts,
                reviews, validations, and requirements</strong> from the database.
                <br /><br />
                Generated code on your local disk will <strong>not</strong> be deleted.
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowResetConfirm(false)}
                  className="px-4 py-2 rounded-lg bg-slate-600 hover:bg-slate-500 text-sm font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleReset}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-sm font-medium transition-colors"
                >
                  Yes, Reset Everything
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Module cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <AnimatePresence>
          {modules.map((m) => {
            // Derive display status: if the pipeline is actively working on this
            // module (not IDLE/PIPELINE_COMPLETE), override DB status to in_progress.
            const pipelineActive = status && ![
              'IDLE', 'PIPELINE_COMPLETE',
            ].includes(status.pipeline_status);
            const isCurrentModule = pipelineActive && status?.current_module_id === m.id;
            const displayStatus = isCurrentModule ? 'in_progress' : m.status;

            return (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="glass-card cursor-pointer hover:ring-1 hover:ring-indigo-500/50 transition-all"
              onClick={() => setSelectedModuleId(m.id)}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-2 h-2 rounded-full ${statusColor[displayStatus] || 'bg-slate-500'}`} />
                <span className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
                  {displayStatus.replace('_', ' ')}
                </span>
              </div>
              <h3 className="font-semibold">{m.name}</h3>
              <p className="text-sm text-[var(--text-secondary)]">{m.feature_name}</p>
              <div className="flex items-center gap-2 mt-2">
                <p className="text-xs text-[var(--text-secondary)]">
                  v{m.version} · order {m.execution_order}
                </p>
                {m.pr_number && (
                  <a
                    href={m.pr_url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 text-xs hover:bg-purple-500/30 transition-colors"
                    onClick={(e) => !m.pr_url && e.preventDefault()}
                  >
                    PR #{m.pr_number}
                  </a>
                )}
              </div>
            </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      <ModuleDetailModal
        moduleId={selectedModuleId}
        onClose={() => setSelectedModuleId(null)}
      />
    </div>
  );
}
