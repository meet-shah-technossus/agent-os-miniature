/* DashboardView — Phase 5 / Phase 7 (GitHub Review mode story queue)
   Left: pipeline status card, GHR context, iteration counter, Start/Pause/Approve/Reset controls.
   Right: Story Queue — hierarchical tree (Epic → Feature → Story) in GHR mode + PipelineFlowDiagram.
*/

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../hooks/api';
import type {
  StoryQueueItem,
  StoryQueueResponse,
  StoryQueueHierarchyResponse,
  HierarchyEpic,
  HierarchyFeature,
} from '../hooks/api';
import { usePipelineFlow } from '../hooks/usePipelineFlow';
import PipelineFlowDiagram from './PipelineFlowDiagram';

// ── Story status badge ────────────────────────────────────────────────────────
function storyStatusBadge(status: StoryQueueItem['status']) {
  const base = 'px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide';
  switch (status) {
    case 'completed': return <span className={`${base} bg-green-500/20 text-green-400`}>done</span>;
    case 'in_progress': return <span className={`${base} bg-indigo-500/20 text-indigo-300 animate-pulse`}>active</span>;
    case 'failed': return <span className={`${base} bg-red-500/20 text-red-400`}>failed</span>;
    default: return <span className={`${base} bg-white/[0.06] text-white/40`}>queued</span>;
  }
}

// ── QueueStoryRow ─────────────────────────────────────────────────────────────
interface QueueStoryRowProps {
  story: StoryQueueItem;
  isActive: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  indent?: boolean;
}
function QueueStoryRow({ story, isActive, isExpanded, onToggle, indent = false }: QueueStoryRowProps) {
  return (
    <div
      className={`rounded-lg border transition-colors cursor-pointer select-none ${indent ? 'ml-6' : ''} ${isActive
          ? 'border-indigo-500/40 bg-indigo-500/[0.08]'
          : story.status === 'completed'
            ? 'border-green-500/20 bg-green-500/[0.04]'
            : story.status === 'failed'
              ? 'border-red-500/20 bg-red-500/[0.04]'
              : 'border-white/[0.05] bg-white/[0.02] hover:bg-white/[0.04]'
        }`}
      onClick={onToggle}
    >
      {/* Summary row */}
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="text-[10px] font-mono text-white/25 w-5 shrink-0">{story.position}</span>
        <span className="text-[10px] font-mono text-white/40 shrink-0 w-20 truncate" title={story.story_id}>
          {story.story_id}
        </span>
        <span className="flex-1 text-xs text-white/70 truncate" title={story.title}>
          {story.title}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {story.story_iteration > 1 && (
            <span className="text-[10px] text-white/30">iter {story.story_iteration}</span>
          )}
          {storyStatusBadge(story.status)}
          <span className="text-white/20 text-[10px]">{isExpanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Expanded detail */}
      {isExpanded && (
        <div className="px-3 pb-3 border-t border-white/[0.04] space-y-2 pt-2">
          {story.acceptance_criteria.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-white/25 mb-1">Acceptance Criteria</p>
              <ul className="space-y-0.5">
                {story.acceptance_criteria.map((ac, i) => (
                  <li key={i} className="flex gap-1.5 text-[11px] text-white/50">
                    <span className="text-white/20 shrink-0">—</span>
                    <span>{ac}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-white/40">
            {story.branch_name && (
              <span>🌿 <span className="font-mono">{story.branch_name}</span></span>
            )}
            {story.pr_url ? (
              <a
                href={story.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-400 hover:text-indigo-300 transition-colors"
                onClick={(e) => e.stopPropagation()}
              >
                🔗 PR #{story.pr_number}
              </a>
            ) : story.pr_number ? (
              <span>🔗 PR #{story.pr_number}</span>
            ) : null}
          </div>
          {story.depends_on.length > 0 && (
            <p className="text-[11px] text-white/35">
              ⛓ Depends on: <span className="font-mono">{story.depends_on.join(', ')}</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── QueueFeatureGroup ─────────────────────────────────────────────────────────
interface QueueFeatureGroupProps {
  feature: HierarchyFeature;
  currentStoryId: string | null;
  expandedStory: string | null;
  onToggleStory: (id: string | null) => void;
  indent?: boolean;
}
function QueueFeatureGroup({
  feature,
  currentStoryId,
  expandedStory,
  onToggleStory,
  indent = false,
}: QueueFeatureGroupProps) {
  const [open, setOpen] = useState(true);
  const activeCount = feature.stories.filter(
    (s) => s.status === 'in_progress' || s.story_id === currentStoryId
  ).length;
  const doneCount = feature.stories.filter((s) => s.status === 'completed').length;

  return (
    <div className={`${indent ? 'ml-3' : ''}`}>
      {/* Feature heading */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left hover:bg-white/[0.03] transition-colors group"
      >
        <span className={`w-2 h-2 rounded-full border-l-2 shrink-0 transition-transform ${open ? 'rotate-90' : ''} text-violet-400/60`}>
          <svg className="w-2.5 h-2.5 text-violet-400/60 transition-transform" style={{ transform: open ? 'rotate(90deg)' : 'none' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <span className="text-[10px] font-mono text-white/25 shrink-0 w-14 truncate">{feature.feature_id}</span>
        <span className="flex-1 text-xs font-semibold text-violet-300/80 group-hover:text-violet-300 truncate">
          {feature.feature_title}
        </span>
        <span className="text-[10px] text-white/30 shrink-0">
          {doneCount}/{feature.stories.length}
          {activeCount > 0 && <span className="ml-1 text-indigo-400 animate-pulse">●</span>}
        </span>
      </button>

      {/* Stories under feature */}
      {open && (
        <div className="mt-1 space-y-1 border-l-2 border-violet-500/20 ml-3 pl-2">
          {feature.stories.map((story) => (
            <QueueStoryRow
              key={story.story_id}
              story={story}
              isActive={story.story_id === currentStoryId || story.status === 'in_progress'}
              isExpanded={expandedStory === story.story_id}
              onToggle={() => onToggleStory(expandedStory === story.story_id ? null : story.story_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── QueueEpicGroup ────────────────────────────────────────────────────────────
interface QueueEpicGroupProps {
  epic: HierarchyEpic;
  currentStoryId: string | null;
  expandedStory: string | null;
  onToggleStory: (id: string | null) => void;
}
function QueueEpicGroup({ epic, currentStoryId, expandedStory, onToggleStory }: QueueEpicGroupProps) {
  const [open, setOpen] = useState(true);
  const allStories = [
    ...epic.features.flatMap((f) => f.stories),
    ...epic.stories,
  ];
  const doneCount = allStories.filter((s) => s.status === 'completed').length;
  const activeCount = allStories.filter(
    (s) => s.status === 'in_progress' || s.story_id === currentStoryId
  ).length;

  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.015] overflow-hidden">
      {/* Epic heading */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-white/[0.03] transition-colors"
      >
        <svg
          className={`w-3.5 h-3.5 text-indigo-400/60 transition-transform shrink-0 ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400/70 font-mono shrink-0">
          {epic.epic_id}
        </span>
        <span className="flex-1 text-xs font-semibold text-white/90 truncate">{epic.epic_title}</span>
        <span className="text-[10px] text-white/30 shrink-0 font-mono">
          {doneCount}/{allStories.length}
          {activeCount > 0 && <span className="ml-1 text-indigo-400 animate-pulse">●</span>}
        </span>
      </button>

      {/* Features + direct stories */}
      {open && (
        <div className="border-t border-white/[0.05] px-3 py-2 space-y-2">
          {epic.features.map((feat) => (
            <QueueFeatureGroup
              key={feat.feature_id}
              feature={feat}
              currentStoryId={currentStoryId}
              expandedStory={expandedStory}
              onToggleStory={onToggleStory}
            />
          ))}
          {/* Stories directly under epic (no feature) */}
          {epic.stories.map((story) => (
            <QueueStoryRow
              key={story.story_id}
              story={story}
              isActive={story.story_id === currentStoryId || story.status === 'in_progress'}
              isExpanded={expandedStory === story.story_id}
              onToggle={() => onToggleStory(expandedStory === story.story_id ? null : story.story_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── DashboardView ─────────────────────────────────────────────────────────────

export default function DashboardView() {
  const { pipelineStatus, isHitlGate, currentIteration, statusText, loading } = usePipelineFlow();
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [resetMsg, setResetMsg] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);

  // ── Story Queue (GitHub Review mode) ────────────────────────────────────────
  const [storyQueue, setStoryQueue] = useState<StoryQueueResponse | null>(null);
  const [storyHierarchy, setStoryHierarchy] = useState<StoryQueueHierarchyResponse | null>(null);
  const [expandedStory, setExpandedStory] = useState<string | null>(null);
  const queuePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const [q, h] = await Promise.all([
          api.getStoryQueue(),
          api.getStoryQueueHierarchy(),
        ]);
        setStoryQueue(q);
        setStoryHierarchy(h);
      } catch {
        // Silently ignore — not in GHR mode or endpoint unavailable
      }
    };
    poll();
    queuePollRef.current = setInterval(poll, 3000);
    return () => { if (queuePollRef.current) clearInterval(queuePollRef.current); };
  }, []);

  const isGhrMode = storyQueue?.mode === 'github_review';
  // Both standard and github_review now use story-wise queue execution
  const isQueueMode = storyQueue?.mode === 'github_review' || storyQueue?.mode === 'standard';

  // ── Helpers ──────────────────────────────────────────────────────────────────
  const [pauseRequested, setPauseRequested] = useState(false);

  // Clear the "pause pending" indicator whenever the pipeline status changes
  useEffect(() => { setPauseRequested(false); }, [pipelineStatus]);

  const withError = <T,>(p: Promise<T>) =>
    p.catch((e: unknown) => setActionError(String(e)));

  const handleStart = () => { setActionError(null); withError(api.startPipeline()); };
  const handlePause = () => {
    setActionError(null);
    setPauseRequested(true);
    withError(api.pausePipeline());
  };
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
  const statusColour = isFailed ? 'text-red-400'
    : isComplete ? 'text-green-400'
      : isHitlGate ? 'text-yellow-400'
        : pipelineStatus === 'IDLE' ? 'text-slate-500'
          : 'text-indigo-400';

  // Active story for GHR left-panel context
  const activeStory = storyQueue?.stories.find(s => s.story_id === storyQueue.current_story_id)
    ?? storyQueue?.stories.find(s => s.status === 'in_progress');

  // Helper to check if hierarchy has any content
  const hasHierarchyContent = storyHierarchy && (
    storyHierarchy.epics.length > 0 ||
    storyHierarchy.ungrouped_features.length > 0 ||
    storyHierarchy.flat_stories.length > 0
  );

  return (
    <div className="flex gap-5 h-full min-h-0">

      {/* ── Left: Control panel ───────────────────────────────────────────────── */}
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
              {currentIteration > 0 && !isGhrMode && (
                <p className="text-[10px] font-mono text-slate-500 mt-1">Iteration {currentIteration}</p>
              )}
            </>
          )}
        </div>

        {/* GitHub Review mode context card */}
        {isQueueMode && storyQueue && (
          <motion.div
            key="ghr-context"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass-card border-indigo-500/20"
          >
            <p className="text-[10px] uppercase tracking-widest text-indigo-400/60 mb-3">
              {isGhrMode ? 'GitHub Review Mode' : 'Standard Pipeline'}
            </p>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-white/40">Progress</span>
                <span className="font-mono text-white/70">
                  {storyQueue.stories_completed} / {storyQueue.stories_total || storyQueue.stories.length} stories
                </span>
              </div>
              {storyQueue.current_story_id && (
                <div className="flex justify-between">
                  <span className="text-white/40">Current Story</span>
                  <span className="font-mono text-indigo-300 truncate max-w-[160px]" title={storyQueue.current_story_id}>
                    {storyQueue.current_story_id}
                  </span>
                </div>
              )}
              {activeStory && (
                <>
                  {/* Show Epic / Feature breadcrumb if available */}
                  {activeStory.epic_title && (
                    <div className="flex justify-between">
                      <span className="text-white/40">Epic</span>
                      <span className="text-indigo-400/70 truncate max-w-[160px]" title={activeStory.epic_title}>
                        {activeStory.epic_title}
                      </span>
                    </div>
                  )}
                  {activeStory.feature_title && (
                    <div className="flex justify-between">
                      <span className="text-white/40">Feature</span>
                      <span className="text-violet-400/70 truncate max-w-[160px]" title={activeStory.feature_title}>
                        {activeStory.feature_title}
                      </span>
                    </div>
                  )}
                  {activeStory.story_iteration > 0 && (
                    <div className="flex justify-between">
                      <span className="text-white/40">Story Iteration</span>
                      <span className="font-mono text-white/70">{activeStory.story_iteration}</span>
                    </div>
                  )}
                  {activeStory.branch_name && (
                    <div className="flex justify-between">
                      <span className="text-white/40">Branch</span>
                      <span className="font-mono text-white/50 truncate max-w-[160px]" title={activeStory.branch_name}>
                        {activeStory.branch_name}
                      </span>
                    </div>
                  )}
                  {activeStory.pr_number && (
                    <div className="flex justify-between items-center">
                      <span className="text-white/40">PR</span>
                      {activeStory.pr_url ? (
                        <a
                          href={activeStory.pr_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono text-indigo-400 hover:text-indigo-300 transition-colors"
                        >
                          #{activeStory.pr_number}
                        </a>
                      ) : (
                        <span className="font-mono text-white/50">#{activeStory.pr_number}</span>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}

        {/* Primary controls */}
        <div className="glass-card space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">Controls</p>

          <div className="flex gap-2">
            <button
              onClick={handleStart}
              className="flex-1 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium transition-colors"
            >
              Start / Resume
            </button>
            <button
              onClick={handlePause}
              disabled={pauseRequested}
              className="px-3 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm font-medium transition-colors disabled:opacity-60"
              title={pauseRequested ? 'Pause pending — current step will finish first' : 'Pause after the current step completes'}
            >
              {pauseRequested ? (
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                  Pausing…
                </span>
              ) : 'Pause'}
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
                Approve Gate
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
              Reset Pipeline
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

      {/* ── Right: Story Queue (GHR) + Pipeline flow diagram ──────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col gap-4 min-h-0">

        {/* Story Queue panel — Standard and GitHub Review modes */}
        {isQueueMode && storyHierarchy && (
          <div className="glass-card flex flex-col overflow-hidden" style={{ maxHeight: 480 }}>
            <div className="flex items-center justify-between mb-3 shrink-0">
              <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Story Queue</p>
              <span className="text-[10px] text-white/30">
                {storyHierarchy.stories_completed} / {storyHierarchy.stories_total} complete
              </span>
            </div>

            <div className="flex-1 overflow-y-auto space-y-2 pr-1">

              {/* ── Scenario A: Full hierarchy — Epic → Feature → Story ───────── */}
              {storyHierarchy.epics.map((epic) => (
                <QueueEpicGroup
                  key={epic.epic_id}
                  epic={epic}
                  currentStoryId={storyHierarchy.current_story_id}
                  expandedStory={expandedStory}
                  onToggleStory={setExpandedStory}
                />
              ))}

              {/* ── Scenario B: Features without Epics ───────────────────────── */}
              {storyHierarchy.ungrouped_features.map((feat) => (
                <QueueFeatureGroup
                  key={feat.feature_id}
                  feature={feat}
                  currentStoryId={storyHierarchy.current_story_id}
                  expandedStory={expandedStory}
                  onToggleStory={setExpandedStory}
                />
              ))}

              {/* ── Scenario C: Flat stories (no Epic or Feature) ────────────── */}
              {storyHierarchy.flat_stories.map((story) => (
                <QueueStoryRow
                  key={story.story_id}
                  story={story}
                  isActive={
                    story.story_id === storyHierarchy.current_story_id ||
                    story.status === 'in_progress'
                  }
                  isExpanded={expandedStory === story.story_id}
                  onToggle={() =>
                    setExpandedStory(expandedStory === story.story_id ? null : story.story_id)
                  }
                />
              ))}

              {/* Empty state */}
              {!hasHierarchyContent && (
                <p className="text-xs text-white/30 text-center py-4">No stories in queue yet</p>
              )}
            </div>
          </div>
        )}

        {/* Flow diagram */}
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
