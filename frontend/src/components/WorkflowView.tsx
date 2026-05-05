/* WorkflowView — Phase 8
   A visual, real-time representation of the entire pipeline:
   1. Flow diagram with 4 agent stations + HITL gates + feedback arc
   2. Handoff arrows with traveling-dot animation
   3. HITL gate nodes (amber glow when waiting)
   4. "What's happening" plain-English status bar
   5. Module progress mini-timeline (horizontal scroll, click for detail)
   6. Event feed — plain-English narration of recent bus events
*/

import { useState, useEffect, Fragment } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { Module } from '../types';
import {
  usePipelineFlow,
  stationIndex,
  type StationId,
  type FeedEvent,
} from '../hooks/usePipelineFlow';

// ─── Station config ───────────────────────────────────────────────────────────

interface StationColor {
  border: string;
  activeBorder: string;
  activeBg: string;
  activeShadow: string;
  badgeBg: string;
  badgeText: string;
  ringColor: string;
  pulseColor: string;
}

interface StationConfig {
  id: StationId;
  title: string;
  role: string;
  icon: string;
  type: 'agent' | 'hitl' | 'git';
  color: StationColor;
}

const FLOW_STATIONS: StationConfig[] = [
  {
    id: 'architect',
    title: 'The Architect',
    role: 'Module Maker',
    icon: '🏛',
    type: 'agent',
    color: {
      border: 'border-indigo-500/25',
      activeBorder: 'border-indigo-400',
      activeBg: 'bg-indigo-500/10',
      activeShadow: 'shadow-[0_0_22px_rgba(99,102,241,0.22)]',
      badgeBg: 'bg-indigo-500/20',
      badgeText: 'text-indigo-300',
      ringColor: 'ring-indigo-400',
      pulseColor: '#818CF8',
    },
  },
  {
    id: 'hitl1',
    title: 'Plan Review',
    role: 'Human Checkpoint',
    icon: '⏸',
    type: 'hitl',
    color: {
      border: 'border-amber-500/25',
      activeBorder: 'border-amber-400',
      activeBg: 'bg-amber-500/10',
      activeShadow: 'shadow-[0_0_22px_rgba(234,179,8,0.22)]',
      badgeBg: 'bg-amber-500/20',
      badgeText: 'text-amber-300',
      ringColor: 'ring-amber-400',
      pulseColor: '#FCD34D',
    },
  },
  {
    id: 'writer',
    title: 'The Writer',
    role: 'Prompt Generator',
    icon: '✍',
    type: 'agent',
    color: {
      border: 'border-purple-500/25',
      activeBorder: 'border-purple-400',
      activeBg: 'bg-purple-500/10',
      activeShadow: 'shadow-[0_0_22px_rgba(168,85,247,0.22)]',
      badgeBg: 'bg-purple-500/20',
      badgeText: 'text-purple-300',
      ringColor: 'ring-purple-400',
      pulseColor: '#C084FC',
    },
  },
  {
    id: 'builder',
    title: 'The Builder',
    role: 'Code Generator',
    icon: '⚒',
    type: 'agent',
    color: {
      border: 'border-blue-500/25',
      activeBorder: 'border-blue-400',
      activeBg: 'bg-blue-500/10',
      activeShadow: 'shadow-[0_0_22px_rgba(59,130,246,0.22)]',
      badgeBg: 'bg-blue-500/20',
      badgeText: 'text-blue-300',
      ringColor: 'ring-blue-400',
      pulseColor: '#60A5FA',
    },
  },
  {
    id: 'inspector',
    title: 'The Inspector',
    role: 'Code Reviewer',
    icon: '🔍',
    type: 'agent',
    color: {
      border: 'border-teal-500/25',
      activeBorder: 'border-teal-400',
      activeBg: 'bg-teal-500/10',
      activeShadow: 'shadow-[0_0_22px_rgba(20,184,166,0.22)]',
      badgeBg: 'bg-teal-500/20',
      badgeText: 'text-teal-300',
      ringColor: 'ring-teal-400',
      pulseColor: '#2DD4BF',
    },
  },
  {
    id: 'git',
    title: 'Git Commit',
    role: 'Push to GitHub',
    icon: '⬆',
    type: 'git',
    color: {
      border: 'border-green-500/25',
      activeBorder: 'border-green-400',
      activeBg: 'bg-green-500/10',
      activeShadow: 'shadow-[0_0_22px_rgba(34,197,94,0.22)]',
      badgeBg: 'bg-green-500/20',
      badgeText: 'text-green-300',
      ringColor: 'ring-green-400',
      pulseColor: '#4ADE80',
    },
  },
];

// ─── FlowArrow ────────────────────────────────────────────────────────────────

function FlowArrow({ isAnimating }: { isAnimating: boolean }) {
  return (
    <div className="relative flex items-center w-10 shrink-0 mx-1" aria-hidden>
      {/* Line */}
      <div
        className={`h-px w-full transition-colors duration-400 ${
          isAnimating ? 'bg-white/70' : 'bg-slate-700'
        }`}
      />
      {/* Arrowhead */}
      <div
        className={`absolute right-0 w-0 h-0 border-y-[3px] border-y-transparent border-l-[5px] transition-colors duration-400 ${
          isAnimating ? 'border-l-white/70' : 'border-l-slate-700'
        }`}
      />
      {/* Traveling dot */}
      <AnimatePresence>
        {isAnimating && (
          <motion.span
            key="dot"
            className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-white pointer-events-none"
            initial={{ left: '0%', opacity: 1 }}
            animate={{ left: '90%', opacity: [1, 1, 0] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.65, ease: 'easeInOut' }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── StationNode ──────────────────────────────────────────────────────────────

interface StationNodeProps {
  config: StationConfig;
  isActive: boolean;
  isDone: boolean;
  isHITLWaiting: boolean;
  moduleId: string | null;
  iteration: number;
}

function StationNode({ config, isActive, isDone, isHITLWaiting, moduleId, iteration }: StationNodeProps) {
  const { color, type } = config;
  const isHitl = type === 'hitl';

  const widthClass = isHitl ? 'w-20' : 'w-28';
  const minHeightClass = isHitl ? 'min-h-[110px]' : 'min-h-[140px]';
  const borderClass = isActive ? color.activeBorder : isDone ? 'border-slate-600' : color.border;
  const bgClass = isActive ? color.activeBg : isDone ? 'bg-white/[0.03]' : 'bg-[var(--bg-card)]';
  const shadowClass = isActive ? color.activeShadow : '';
  const ringClass = isActive ? `ring-1 ${color.ringColor}` : '';

  const label = isActive
    ? isHITLWaiting
      ? 'Waiting for you'
      : isHitl
      ? 'Paused'
      : 'Working'
    : isDone
    ? 'Done'
    : '';

  return (
    <div
      className={`
        ${widthClass} ${minHeightClass} rounded-xl border ${borderClass} ${bgClass} ${shadowClass} ${ringClass}
        p-3 flex flex-col items-center text-center gap-1.5 transition-all duration-300 shrink-0
      `}
    >
      {/* Icon with pulse ring */}
      <div className="relative mt-1">
        <span className={`text-2xl leading-none ${isActive ? '' : isDone ? 'opacity-40' : 'opacity-25'}`}>
          {config.icon}
        </span>
        {isActive && (
          <motion.span
            className={`absolute -inset-2.5 rounded-full border ${color.activeBorder}`}
            animate={{ scale: [1, 1.4, 1], opacity: [0.7, 0, 0.7] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
          />
        )}
      </div>

      {/* Title */}
      <span
        className={`text-xs font-semibold leading-tight mt-0.5 ${
          isActive ? 'text-white' : isDone ? 'text-slate-500' : 'text-slate-600'
        }`}
      >
        {config.title}
      </span>

      {/* Role */}
      <span className={`text-[10px] leading-tight ${isActive ? 'text-slate-400' : 'text-slate-700'}`}>
        {config.role}
      </span>

      {/* Status badge */}
      {label && (
        <span
          className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide ${
            isActive ? `${color.badgeBg} ${color.badgeText}` : 'bg-slate-700/50 text-slate-500'
          }`}
        >
          {label}
        </span>
      )}

      {/* Current work */}
      {isActive && moduleId && !isHitl && (
        <div className="w-full mt-0.5 space-y-0.5">
          <p className="text-[10px] text-slate-400 truncate w-full" title={moduleId}>
            {moduleId.replace(/-\d+$/, '')}
          </p>
          {iteration > 0 && (
            <p className="text-[10px] text-slate-600">attempt {iteration}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Feedback arc ─────────────────────────────────────────────────────────────

function FeedbackArc({ isAnimating }: { isAnimating: boolean }) {
  return (
    <div
      className={`mt-3 flex items-center justify-center gap-2 text-xs transition-colors duration-300 ${
        isAnimating ? 'text-orange-400' : 'text-slate-700'
      }`}
    >
      <span>↩</span>
      <span>When code needs revision: The Inspector sends back to The Writer</span>
    </div>
  );
}

// ─── Flow diagram ─────────────────────────────────────────────────────────────

interface FlowDiagramProps {
  activeStation: StationId;
  prevStation: StationId | null;
  isHitlGate: boolean;
  currentModuleId: string | null;
  currentIteration: number;
}

function FlowDiagram({ activeStation, prevStation, isHitlGate, currentModuleId, currentIteration }: FlowDiagramProps) {
  const activeIdx = stationIndex(activeStation);

  const isDone = (id: StationId): boolean => {
    return stationIndex(id) < activeIdx && id !== 'idle';
  };

  const isArrowAnimating = (src: StationId, dst: StationId): boolean => {
    if (!prevStation) return false;
    return prevStation === src && activeStation === dst;
  };

  const isFeedbackAnimating =
    prevStation === 'inspector' && activeStation === 'writer';

  return (
    <div className="px-4 py-6">
      <div className="flex items-center justify-center overflow-x-auto">
        {FLOW_STATIONS.map((station, i) => (
          <Fragment key={station.id}>
            <StationNode
              config={station}
              isActive={activeStation === station.id}
              isDone={isDone(station.id)}
              isHITLWaiting={isHitlGate && activeStation === station.id}
              moduleId={currentModuleId}
              iteration={currentIteration}
            />
            {i < FLOW_STATIONS.length - 1 && (
              <FlowArrow
                isAnimating={isArrowAnimating(station.id, FLOW_STATIONS[i + 1].id)}
              />
            )}
          </Fragment>
        ))}
      </div>
      <FeedbackArc isAnimating={isFeedbackAnimating} />
    </div>
  );
}

// ─── Status bar ───────────────────────────────────────────────────────────────

function StatusBar({ text, pipelineStatus }: { text: string; pipelineStatus: string }) {
  const isHitl = pipelineStatus.startsWith('HITL');
  const isDone = pipelineStatus === 'PIPELINE_COMPLETE';
  const isError = pipelineStatus === 'FAILED';
  const isIdle = pipelineStatus === 'IDLE';

  const colorClass = isError
    ? 'bg-red-500/10 border-red-500/30 text-red-300'
    : isHitl
    ? 'bg-amber-500/10 border-amber-500/30 text-amber-200'
    : isDone
    ? 'bg-green-500/10 border-green-500/30 text-green-200'
    : isIdle
    ? 'bg-slate-700/40 border-slate-600/40 text-slate-400'
    : 'bg-indigo-500/10 border-indigo-500/30 text-slate-200';

  const prefix = isHitl ? '⏸ ' : isDone ? '🎉 ' : isError ? '⚠ ' : '';

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={text}
        className={`rounded-xl border px-4 py-3 text-sm font-medium ${colorClass}`}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.18 }}
      >
        {prefix}{text}
      </motion.div>
    </AnimatePresence>
  );
}

// ─── Module pill ──────────────────────────────────────────────────────────────

const MOD_COLORS: Record<string, { base: string; dot: string }> = {
  pending:     { base: 'border-slate-600/60 bg-slate-800/50 text-slate-500',    dot: 'bg-slate-600' },
  in_progress: { base: 'border-indigo-500/50 bg-indigo-500/10 text-indigo-300', dot: 'bg-indigo-400 animate-pulse' },
  completed:   { base: 'border-green-500/40 bg-green-500/10 text-green-300',    dot: 'bg-green-400' },
  failed:      { base: 'border-red-500/40 bg-red-500/10 text-red-300',          dot: 'bg-red-400' },
};

function ModulePill({
  module,
  isSelected,
  onClick,
}: {
  module: Module;
  isSelected: boolean;
  onClick: () => void;
}) {
  const style = MOD_COLORS[module.status] ?? MOD_COLORS.pending;
  return (
    <button
      onClick={onClick}
      className={`
        shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs
        transition-all duration-150 font-medium
        ${style.base}
        ${isSelected ? 'ring-2 ring-white/30' : 'hover:brightness-110'}
      `}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
      <span className="max-w-[120px] truncate">{module.name}</span>
      {module.status === 'completed' && <span className="opacity-60 text-[10px]">✓</span>}
      {module.status === 'in_progress' && <span className="opacity-60 text-[10px]">…</span>}
    </button>
  );
}

// ─── Module detail panel ──────────────────────────────────────────────────────

function ModuleDetailPanel({ module }: { module: Module }) {
  return (
    <motion.div
      className="mt-3 rounded-lg border border-[var(--border-glass)] bg-black/20 p-4"
      initial={{ opacity: 0, height: 0, overflow: 'hidden' }}
      animate={{ opacity: 1, height: 'auto', overflow: 'visible' }}
      exit={{ opacity: 0, height: 0, overflow: 'hidden' }}
      transition={{ duration: 0.2 }}
    >
      <div className="grid grid-cols-2 gap-x-8 gap-y-2.5 text-xs">
        <div>
          <p className="text-slate-600 mb-0.5">Name</p>
          <p className="text-white font-medium">{module.name}</p>
        </div>
        <div>
          <p className="text-slate-600 mb-0.5">Status</p>
          <p
            className={`font-medium capitalize ${
              module.status === 'completed'
                ? 'text-green-400'
                : module.status === 'in_progress'
                ? 'text-indigo-400'
                : module.status === 'failed'
                ? 'text-red-400'
                : 'text-slate-500'
            }`}
          >
            {module.status.replace('_', ' ')}
          </p>
        </div>
        <div>
          <p className="text-slate-600 mb-0.5">Feature</p>
          <p className="text-slate-300">{module.feature_name || '—'}</p>
        </div>
        <div>
          <p className="text-slate-600 mb-0.5">Order</p>
          <p className="text-slate-300">#{module.execution_order}</p>
        </div>
        {module.dependency_ids.length > 0 && (
          <div className="col-span-2">
            <p className="text-slate-600 mb-0.5">Dependencies</p>
            <p className="text-slate-400 font-mono text-[11px]">{module.dependency_ids.join(', ')}</p>
          </div>
        )}
        {module.pr_url && (
          <div className="col-span-2">
            <p className="text-slate-600 mb-0.5">Pull Request</p>
            <a
              href={module.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-400 hover:text-indigo-300 underline text-[11px]"
            >
              PR #{module.pr_number}
            </a>
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ─── Module timeline ──────────────────────────────────────────────────────────

function ModuleTimeline({ modules, activeModuleId: _activeModuleId }: { modules: Module[]; activeModuleId: string | null }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedModule = modules.find((m) => m.id === selectedId) ?? null;

  const completed = modules.filter((m) => m.status === 'completed').length;
  const pct = modules.length > 0 ? (completed / modules.length) * 100 : 0;

  if (modules.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-4">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
          Module Progress
        </h3>
        <p className="text-xs text-slate-600 italic">
          No modules yet — start the pipeline to generate a plan.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          Module Progress — {completed}/{modules.length} complete
        </h3>
        {selectedId && (
          <button
            onClick={() => setSelectedId(null)}
            className="text-[10px] text-slate-500 hover:text-slate-300 underline"
          >
            close
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-1 bg-slate-800 rounded-full overflow-hidden mb-3">
        <motion.div
          className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5 }}
        />
      </div>

      {/* Pill row */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {modules
          .slice()
          .sort((a, b) => a.execution_order - b.execution_order)
          .map((m) => (
            <ModulePill
              key={m.id}
              module={m}
              isSelected={m.id === selectedId}
              onClick={() => setSelectedId((prev) => (prev === m.id ? null : m.id))}
            />
          ))}
      </div>

      {/* Module detail */}
      <AnimatePresence>
        {selectedModule && <ModuleDetailPanel key={selectedId} module={selectedModule} />}
      </AnimatePresence>
    </div>
  );
}

// ─── Event feed ───────────────────────────────────────────────────────────────

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

function EventFeedItem({ event }: { event: FeedEvent }) {
  const [, tick] = useState(0);
  // Re-render every 30 s to keep relative timestamps fresh
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <motion.div
      className="flex gap-2.5 py-2.5 border-b border-[var(--border-glass)] last:border-0"
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
    >
      <span className="text-sm shrink-0 mt-0.5 select-none">{event.icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-300 leading-snug">{event.text}</p>
        <p className="text-[10px] text-slate-600 mt-0.5">{relativeTime(event.timestamp)}</p>
      </div>
    </motion.div>
  );
}

function EventFeed({ events }: { events: FeedEvent[] }) {
  return (
    <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-4 flex flex-col overflow-hidden min-h-0">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2 shrink-0">
        Live Events
      </h3>
      <div className="flex-1 overflow-y-auto">
        {events.length === 0 ? (
          <p className="text-xs text-slate-600 italic mt-2">
            Events will appear here as the pipeline runs.
          </p>
        ) : (
          <AnimatePresence initial={false}>
            {events.map((ev) => (
              <EventFeedItem key={ev.id} event={ev} />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

// ─── Header stats strip ───────────────────────────────────────────────────────

function HeaderStats({
  pipelineStatus,
  totalModules,
  modules,
}: {
  pipelineStatus: string;
  totalModules: number;
  modules: Module[];
}) {
  const completed = modules.filter((m) => m.status === 'completed').length;
  const inProgress = modules.filter((m) => m.status === 'in_progress').length;
  const total = totalModules || modules.length;

  const statusColorClass =
    pipelineStatus === 'PIPELINE_COMPLETE'
      ? 'bg-green-500/20 text-green-400'
      : pipelineStatus === 'FAILED'
      ? 'bg-red-500/20 text-red-400'
      : pipelineStatus === 'IDLE'
      ? 'bg-slate-700 text-slate-400'
      : pipelineStatus.startsWith('HITL')
      ? 'bg-amber-500/20 text-amber-400'
      : 'bg-indigo-500/20 text-indigo-400';

  return (
    <div className="flex items-center gap-4 text-xs">
      {total > 0 && (
        <span className="text-slate-500">
          <span className="text-white font-semibold">{completed}</span>/{total} modules done
        </span>
      )}
      {inProgress > 0 && (
        <span className="flex items-center gap-1 text-indigo-400">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          {inProgress} in progress
        </span>
      )}
      <span className={`font-mono text-[10px] px-2 py-0.5 rounded ${statusColorClass}`}>
        {pipelineStatus}
      </span>
    </div>
  );
}

// ─── Main export ──────────────────────────────────────────────────────────────

export default function WorkflowView() {
  const flow = usePipelineFlow();

  return (
    <div className="h-full flex flex-col">
      {/* Page header */}
      <div className="mb-5 shrink-0 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white">Workflow</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Real-time visual overview of the pipeline.
          </p>
        </div>
        {!flow.loading && (
          <HeaderStats
            pipelineStatus={flow.pipelineStatus}
            totalModules={flow.totalModules}
            modules={flow.modules}
          />
        )}
      </div>

      {flow.loading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-8 h-8 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
        </div>
      ) : (
        <div className="flex-1 grid grid-cols-[1fr_280px] gap-5 min-h-0 overflow-hidden">
          {/* Left: diagram + status bar + module timeline */}
          <div className="flex flex-col gap-4 overflow-y-auto min-h-0 pr-1">
            {/* Flow diagram card */}
            <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] shrink-0">
              <FlowDiagram
                activeStation={flow.activeStation}
                prevStation={flow.prevStation}
                isHitlGate={flow.isHitlGate}
                currentModuleId={flow.currentModuleId}
                currentIteration={flow.currentIteration}
              />
            </div>

            {/* Status bar */}
            <div className="shrink-0">
              <StatusBar text={flow.statusText} pipelineStatus={flow.pipelineStatus} />
            </div>

            {/* Module timeline */}
            <div className="shrink-0">
              <ModuleTimeline modules={flow.modules} activeModuleId={flow.currentModuleId} />
            </div>
          </div>

          {/* Right: event feed */}
          <EventFeed events={flow.events} />
        </div>
      )}
    </div>
  );
}
