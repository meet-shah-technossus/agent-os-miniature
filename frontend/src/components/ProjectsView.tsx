/* ProjectsView — Phase 10
   Project & Module Progress Page.

   Layout:
     ┌─ Project Header ──────────────────────────────────────────┐
     │  name · language · path | pipeline status | progress bar  │
     │  start time | elapsed | ETA            | GitHub repo link  │
     └───────────────────────────────────────────────────────────┘
     ┌─ Tabs [Modules] [Dependencies] ───────────────────────────┐
     │  ModuleGrid  ─or─  DependencyGraph                        │
     └───────────────────────────────────────────────────────────┘
     ModuleDetailDrawer  (slide-in from right, 42 vw wide)
*/

import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../hooks/api';
import type {
  Module, Iteration, ModuleDetail, PipelineStatus,
  Settings, Metrics, BusMessage, ReviewEntry,
} from '../types';

// ─── Constants ────────────────────────────────────────────────────────────────

const POLL_MS = 3000;

const ITERATION_STAGES = ['Prompt', 'Generate', 'Validate', 'Review', 'Commit'];

const STAGE_IDX: Record<string, number> = {
  PROMPT_GENERATION: 0,        HITL_2_PROMPT_REVIEW: 0,
  CODE_GENERATION: 1,
  VALIDATION: 2,
  CODE_REVIEW: 3,              HITL_3_REVIEW_DECISION: 3,  DECISION: 3,
  GIT_COMMIT: 4,               MODULE_COMPLETE: 4,
};

const STATUS_STYLE: Record<string, { dot: string; badge: string; card: string }> = {
  pending:     { dot: 'bg-slate-500',              badge: 'text-slate-400 bg-slate-500/10 border-slate-500/25',  card: 'border-[var(--border-glass)]' },
  in_progress: { dot: 'bg-blue-400 animate-pulse', badge: 'text-blue-300 bg-blue-500/10 border-blue-500/35',     card: 'border-blue-500/40 ring-1 ring-blue-500/15' },
  completed:   { dot: 'bg-green-400',              badge: 'text-green-300 bg-green-500/10 border-green-500/35',  card: 'border-green-500/25' },
  failed:      { dot: 'bg-red-400',                badge: 'text-red-300 bg-red-500/10 border-red-500/35',        card: 'border-red-500/40' },
};
const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending', in_progress: 'In Progress', completed: 'Completed', failed: 'Failed',
};

const PIPELINE_STATUS_COLORS: Record<string, string> = {
  IDLE:              'text-slate-400 bg-slate-500/10 border-slate-500/25',
  PIPELINE_COMPLETE: 'text-green-300 bg-green-500/10 border-green-500/35',
  FAILED:            'text-red-300 bg-red-500/10 border-red-500/35',
};
function pipelineBadgeClass(s: string): string {
  return PIPELINE_STATUS_COLORS[s] ?? 'text-blue-300 bg-blue-500/10 border-blue-500/35';
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDuration(ms: number): string {
  if (ms <= 0) return '—';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function fmtTs(iso: string): string {
  return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractScore(review: ReviewEntry | undefined): number | null {
  if (!review) return null;
  const c = review.content;
  for (const v of [c?.convergence_score, c?.score, c?.overall_score, c?.summary?.convergence_score]) {
    if (typeof v === 'number') return Math.round(v * 100) / 100;
  }
  return null;
}

function extractDecision(review: ReviewEntry | undefined): string | null {
  if (!review) return null;
  const c = review.content;
  return c?.decision ?? c?.verdict ?? c?.approved_decision ?? c?.outcome ?? null;
}

function extractSummary(review: ReviewEntry | undefined): string {
  if (!review) return '';
  const c = review.content;
  return String(c?.summary ?? c?.executive_summary ?? c?.overall_summary ?? c?.feedback ?? '').slice(0, 280);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractValidation(review: ReviewEntry | undefined): { tool: string; passed: boolean }[] {
  if (!review) return [];
  const c = review.content;
  const raw = c?.validation ?? c?.validations ?? c?.tool_results ?? c?.checks ?? null;
  if (!raw || typeof raw !== 'object') return [];
  if (Array.isArray(raw)) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return raw.map((item: any) => ({
      tool: String(item?.tool ?? item?.name ?? item?.check ?? '?'),
      passed: !!(item?.passed ?? item?.success ?? item?.ok ?? false),
    }));
  }
  return Object.entries(raw).map(([k, v]) => ({
    tool: k,
    passed: !!(typeof v === 'object' ? (v as Record<string, unknown>)?.passed ?? (v as Record<string, unknown>)?.success : v),
  }));
}

// ─── Dependency-graph layout ──────────────────────────────────────────────────

function buildLayers(modules: Module[]): Module[][] {
  const assigned = new Map<string, number>();
  const layers: Module[][] = [];
  const sorted = [...modules].sort((a, b) => a.execution_order - b.execution_order);
  const remaining = [...sorted];

  let safety = 0;
  while (remaining.length > 0 && safety < 200) {
    safety++;
    const batch: Module[] = [];
    for (const m of remaining) {
      const allResolved = m.dependency_ids.every((d) => assigned.has(d));
      if (allResolved) batch.push(m);
    }
    if (batch.length === 0) {
      // Unresolvable cycle — dump into one more layer
      const layerIdx = layers.length;
      layers.push([...remaining]);
      remaining.forEach((m) => assigned.set(m.id, layerIdx));
      remaining.length = 0;
      break;
    }
    for (const m of batch) {
      const depMax = m.dependency_ids.length > 0
        ? Math.max(...m.dependency_ids.map((d) => assigned.get(d) ?? 0))
        : -1;
      const layerIdx = depMax + 1;
      if (!layers[layerIdx]) layers[layerIdx] = [];
      layers[layerIdx].push(m);
      assigned.set(m.id, layerIdx);
    }
    batch.forEach((m) => {
      const idx = remaining.findIndex((r) => r.id === m.id);
      if (idx !== -1) remaining.splice(idx, 1);
    });
  }
  return layers;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

/** Small dots showing which iteration stage the active module is on. */
function StageSteps({ pipelineStatus, maxIter }: { pipelineStatus: string; maxIter: number }) {
  const active = STAGE_IDX[pipelineStatus] ?? -1;
  return (
    <div className="mt-2">
      <div className="flex items-center gap-1 mb-1">
        {ITERATION_STAGES.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            <div
              className={`w-2 h-2 rounded-full transition-colors ${
                i < active
                  ? 'bg-blue-500/50'
                  : i === active
                  ? 'bg-blue-400 ring-2 ring-blue-400/30'
                  : 'bg-slate-700'
              }`}
              title={s}
            />
            {i < ITERATION_STAGES.length - 1 && (
              <div className={`w-3 h-px ${i < active ? 'bg-blue-500/40' : 'bg-slate-700'}`} />
            )}
          </div>
        ))}
      </div>
      <p className="text-[10px] text-blue-400">
        {STAGE_IDX[pipelineStatus] !== undefined
          ? ITERATION_STAGES[STAGE_IDX[pipelineStatus]]
          : pipelineStatus.replace(/_/g, ' ')}
        {maxIter > 0 ? ` (max ${maxIter} iter)` : ''}
      </p>
    </div>
  );
}

interface ModuleCardProps {
  module: Module;
  pipelineStatus: PipelineStatus | null;
  maxIter: number;
  onClick: () => void;
}

function ModuleCard({ module: m, pipelineStatus, maxIter, onClick }: ModuleCardProps) {
  const st = m.status;
  const style = STATUS_STYLE[st] ?? STATUS_STYLE.pending;
  const isActive = pipelineStatus?.current_module_id === m.id && st === 'in_progress';
  const iterNum = isActive ? (pipelineStatus?.current_iteration ?? 0) : 0;
  const iterPct = maxIter > 0 ? Math.min(1, iterNum / maxIter) * 100 : 0;
  const pipelineSt = pipelineStatus?.pipeline_status ?? '';

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-xl border p-4 bg-[var(--bg-card)] hover:bg-white/5 transition-all duration-200 ${style.card}`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] text-slate-500 font-mono">{m.id}</p>
          <p className="text-sm font-semibold text-white truncate leading-snug">{m.name}</p>
        </div>
        <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium ${style.badge}`}>
          {STATUS_LABEL[st] ?? st}
        </span>
      </div>

      {/* Feature badge */}
      {m.feature_name && (
        <p className="text-[10px] text-slate-500 truncate mb-2">
          <span className="text-slate-600">Feature:</span> {m.feature_name}
        </p>
      )}

      {/* In-progress: stage indicator + iteration bar */}
      {st === 'in_progress' && (
        <div className="mt-1">
          {isActive && <StageSteps pipelineStatus={pipelineSt} maxIter={maxIter} />}
          {maxIter > 0 && (
            <div className="mt-2">
              <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
                <span>Iteration {iterNum}</span>
                <span>of {maxIter}</span>
              </div>
              <div className="h-1 rounded-full bg-slate-700 overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all"
                  style={{ width: `${iterPct}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Completed: score + iterations + PR link */}
      {st === 'completed' && (
        <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-500">
          {m.pr_url ? (
            <a
              href={m.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-green-400 hover:text-green-300 flex items-center gap-1"
            >
              <span>↗</span> PR #{m.pr_number}
            </a>
          ) : (
            <span className="text-green-500">✓ Complete</span>
          )}
          <span>v{m.version}</span>
        </div>
      )}

      {/* Failed */}
      {st === 'failed' && (
        <p className="text-[10px] text-red-400 mt-1">Failed — click for details</p>
      )}

      {/* Deps */}
      {m.dependency_ids.length > 0 && (
        <p className="text-[10px] text-slate-600 mt-2 truncate">
          Deps: {m.dependency_ids.join(', ')}
        </p>
      )}
    </button>
  );
}

// ─── Module grid ──────────────────────────────────────────────────────────────

interface ModuleGridProps {
  modules: Module[];
  pipelineStatus: PipelineStatus | null;
  maxIter: number;
  onSelect: (id: string) => void;
}

function ModuleGrid({ modules, pipelineStatus, maxIter, onSelect }: ModuleGridProps) {
  const features = [...new Set(modules.map((m) => m.feature_name).filter(Boolean))];
  const grouped = features.length > 1;

  if (modules.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-slate-600">
        <p className="text-4xl mb-3">◫</p>
        <p className="text-sm">No modules yet. Start the pipeline to generate modules.</p>
      </div>
    );
  }

  const renderCards = (mods: Module[]) => (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
      {mods.map((m) => (
        <ModuleCard
          key={m.id}
          module={m}
          pipelineStatus={pipelineStatus}
          maxIter={maxIter}
          onClick={() => onSelect(m.id)}
        />
      ))}
    </div>
  );

  if (!grouped) return renderCards(modules);

  return (
    <div className="space-y-6">
      {features.map((feat) => (
        <div key={feat}>
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3 flex items-center gap-2">
            <span className="w-3 h-px bg-slate-600" />
            {feat}
            <span className="w-3 h-px bg-slate-600" />
          </h3>
          {renderCards(modules.filter((m) => m.feature_name === feat))}
        </div>
      ))}
      {modules.filter((m) => !m.feature_name).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-3">Ungrouped</h3>
          {renderCards(modules.filter((m) => !m.feature_name))}
        </div>
      )}
    </div>
  );
}

// ─── Dependency graph ─────────────────────────────────────────────────────────

const NODE_W = 160;
const NODE_H = 52;
const COL_GAP = 88;
const ROW_GAP = 16;
const PAD = 24;

function DependencyGraph({ modules, onSelect }: { modules: Module[]; onSelect: (id: string) => void }) {
  const layers = buildLayers(modules);

  // Map module_id → {x, y} in the layout
  const positions = new Map<string, { x: number; y: number }>();
  for (let li = 0; li < layers.length; li++) {
    for (let ri = 0; ri < layers[li].length; ri++) {
      positions.set(layers[li][ri].id, {
        x: PAD + li * (NODE_W + COL_GAP),
        y: PAD + ri * (NODE_H + ROW_GAP),
      });
    }
  }

  const maxLayerSize = Math.max(...layers.map((l) => l.length), 1);
  const svgW = PAD * 2 + layers.length * (NODE_W + COL_GAP) - COL_GAP;
  const svgH = PAD * 2 + maxLayerSize * (NODE_H + ROW_GAP) - ROW_GAP;

  if (modules.length === 0) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-600 text-sm">
        No modules to display.
      </div>
    );
  }

  return (
    <div className="overflow-auto">
      <svg
        width={svgW}
        height={svgH}
        className="block"
        style={{ minWidth: svgW, minHeight: svgH }}
      >
        {/* Edges */}
        {modules.map((m) =>
          m.dependency_ids.map((depId) => {
            const srcPos = positions.get(depId);
            const tgtPos = positions.get(m.id);
            if (!srcPos || !tgtPos) return null;
            const sx = srcPos.x + NODE_W;
            const sy = srcPos.y + NODE_H / 2;
            const tx = tgtPos.x;
            const ty = tgtPos.y + NODE_H / 2;
            const cp = (tx - sx) * 0.45;
            return (
              <path
                key={`${depId}->${m.id}`}
                d={`M ${sx} ${sy} C ${sx + cp} ${sy}, ${tx - cp} ${ty}, ${tx} ${ty}`}
                fill="none"
                stroke="rgba(99,102,241,0.3)"
                strokeWidth={1.5}
                markerEnd="url(#arrow)"
              />
            );
          })
        )}

        {/* Arrow marker */}
        <defs>
          <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M 0 0 L 6 3 L 0 6 Z" fill="rgba(99,102,241,0.5)" />
          </marker>
        </defs>

        {/* Nodes */}
        {modules.map((m) => {
          const pos = positions.get(m.id);
          if (!pos) return null;
          const st = m.status;
          const colors = {
            pending:     { fill: 'rgba(30,41,59,0.9)',  stroke: 'rgba(100,116,139,0.4)', text: '#94a3b8', dot: '#64748b' },
            in_progress: { fill: 'rgba(30,58,138,0.35)', stroke: 'rgba(96,165,250,0.5)',  text: '#93c5fd',  dot: '#60a5fa' },
            completed:   { fill: 'rgba(5,46,22,0.4)',   stroke: 'rgba(74,222,128,0.4)',  text: '#86efac',  dot: '#4ade80' },
            failed:      { fill: 'rgba(69,10,10,0.4)',  stroke: 'rgba(248,113,113,0.5)', text: '#fca5a5',  dot: '#f87171' },
          }[st] ?? { fill: 'rgba(30,41,59,0.9)', stroke: 'rgba(100,116,139,0.4)', text: '#94a3b8', dot: '#64748b' };

          return (
            <g
              key={m.id}
              transform={`translate(${pos.x},${pos.y})`}
              className="cursor-pointer"
              onClick={() => onSelect(m.id)}
            >
              <rect
                width={NODE_W}
                height={NODE_H}
                rx={8}
                fill={colors.fill}
                stroke={colors.stroke}
                strokeWidth={1.5}
              />
              {/* Status dot */}
              <circle cx={12} cy={10} r={3.5} fill={colors.dot} />
              {/* Module ID */}
              <text x={22} y={13.5} fontSize={9} fill={colors.dot} fontFamily="monospace">{m.id}</text>
              {/* Name */}
              <foreignObject x={8} y={20} width={NODE_W - 16} height={28}>
                <div
                  // @ts-ignore
                  xmlns="http://www.w3.org/1999/xhtml"
                  style={{
                    fontSize: 11, fontFamily: 'Inter,sans-serif', color: colors.text,
                    lineHeight: '14px', overflow: 'hidden', display: '-webkit-box',
                    WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                  }}
                >
                  {m.name}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
      <p className="text-[10px] text-slate-600 mt-3 text-center">Click a node to open module details. Arrows show dependencies.</p>
    </div>
  );
}

// ─── Module detail drawer ─────────────────────────────────────────────────────

function DrawerIterationRow({
  iter, prompt, review,
}: {
  iter: Iteration;
  prompt: { content: string } | undefined;
  review: ReviewEntry | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const score      = extractScore(review);
  const decision   = extractDecision(review);
  const summary    = extractSummary(review);
  const validation = extractValidation(review);
  const durationMs = iter.completed_at
    ? new Date(iter.completed_at).getTime() - new Date(iter.started_at).getTime()
    : -1;
  const statusColor = iter.status === 'completed' ? 'text-green-400' : iter.status === 'failed' ? 'text-red-400' : 'text-blue-400';

  return (
    <div className="border border-[var(--border-glass)] rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors"
      >
        <span className="text-slate-500 text-xs font-mono w-14 shrink-0">iter {iter.iteration_number}</span>
        <span className={`text-xs ${statusColor}`}>{iter.status}</span>
        {score !== null && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/25">
            score {score}
          </span>
        )}
        {decision && (
          <span className={`text-xs px-1.5 py-0.5 rounded border ${
            String(decision).toLowerCase().includes('pass') || String(decision).toLowerCase().includes('approv')
              ? 'bg-green-500/10 text-green-300 border-green-500/25'
              : 'bg-amber-500/10 text-amber-300 border-amber-500/25'
          }`}>
            {String(decision).slice(0, 20)}
          </span>
        )}
        <span className="text-[10px] text-slate-600 ml-auto">{fmtDuration(durationMs)}</span>
        <span className={`text-slate-500 text-xs transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-[var(--border-glass)] space-y-4">
          {/* Prompt excerpt */}
          {prompt && (
            <div>
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Prompt Excerpt</p>
              <pre className="text-xs text-slate-400 bg-black/30 rounded-lg p-3 whitespace-pre-wrap line-clamp-6 font-mono leading-relaxed overflow-hidden max-h-36">
                {prompt.content.slice(0, 600)}{prompt.content.length > 600 ? '…' : ''}
              </pre>
            </div>
          )}

          {/* Review summary */}
          {summary && (
            <div>
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Review Summary</p>
              <p className="text-xs text-slate-300 bg-black/20 rounded-lg p-3 leading-relaxed">{summary}</p>
            </div>
          )}

          {/* Validation results */}
          {validation.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Validation Results</p>
              <div className="flex flex-wrap gap-2">
                {validation.map((v, vi) => (
                  <span
                    key={vi}
                    className={`text-xs px-2 py-1 rounded border flex items-center gap-1.5 ${
                      v.passed
                        ? 'text-green-300 bg-green-500/10 border-green-500/25'
                        : 'text-red-300 bg-red-500/10 border-red-500/25'
                    }`}
                  >
                    {v.passed ? '✓' : '✕'} {v.tool}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Timestamps */}
          <div className="flex gap-4 text-[10px] text-slate-600">
            <span>Started: {fmtTs(iter.started_at)}</span>
            {iter.completed_at && <span>Completed: {fmtTs(iter.completed_at)}</span>}
            <span>Tokens: {iter.token_usage.toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function ModuleDetailDrawer({
  moduleId,
  allModules,
  onClose,
}: {
  moduleId: string;
  allModules: Module[];
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<ModuleDetail | null>(null);
  const [busHistory, setBusHistory] = useState<BusMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [drawerTab, setDrawerTab] = useState<'overview' | 'iterations' | 'timeline'>('overview');

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    Promise.all([
      api.getModuleDetail(moduleId),
      api.getBusHistory(),
    ]).then(([d, bus]) => {
      setDetail(d);
      setBusHistory(bus.filter((b) => b.module_id === moduleId));
    }).finally(() => setLoading(false));
  }, [moduleId]);

  const m = allModules.find((x) => x.id === moduleId);
  const st = m?.status ?? 'pending';
  const style = STATUS_STYLE[st] ?? STATUS_STYLE.pending;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const defJson = detail?.definition as Record<string, any> | null;

  return (
    <motion.div
      className="fixed inset-0 z-40 flex justify-end"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <motion.div
        className="relative z-50 w-[42vw] min-w-[420px] max-w-[700px] h-full flex flex-col bg-[var(--bg-primary)] border-l border-[var(--border-glass)] shadow-2xl"
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: 'spring', stiffness: 320, damping: 32 }}
      >
        {/* Header */}
        <div className="shrink-0 px-5 py-4 border-b border-[var(--border-glass)]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-2 h-2 rounded-full shrink-0 ${st === 'in_progress' ? 'bg-blue-400 animate-pulse' : st === 'completed' ? 'bg-green-400' : st === 'failed' ? 'bg-red-400' : 'bg-slate-500'}`} />
                <span className="text-xs font-mono text-slate-500">{moduleId}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded border ${style.badge}`}>
                  {STATUS_LABEL[st] ?? st}
                </span>
              </div>
              <h2 className="text-base font-bold text-white truncate">{m?.name ?? moduleId}</h2>
              {m?.feature_name && (
                <p className="text-xs text-slate-500 mt-0.5">{m.feature_name}</p>
              )}
            </div>
            <button onClick={onClose} className="shrink-0 text-slate-500 hover:text-white text-lg transition-colors">✕</button>
          </div>

          {/* Drawer tabs */}
          <div className="flex gap-1 mt-3">
            {(['overview', 'iterations', 'timeline'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setDrawerTab(t)}
                className={`px-3 py-1.5 text-xs rounded-md transition-colors capitalize ${
                  drawerTab === t
                    ? 'text-white bg-indigo-500/20 border border-indigo-500/30'
                    : 'text-slate-500 hover:text-white hover:bg-white/5'
                }`}
              >
                {t}
                {t === 'iterations' && detail && (
                  <span className="ml-1 text-[10px] text-slate-600">({detail.iterations.length})</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-600 text-sm gap-2">
              <span className="w-4 h-4 rounded-full border-2 border-slate-500 border-t-transparent animate-spin" />
              Loading...
            </div>
          )}

          {!loading && drawerTab === 'overview' && detail && (
            <div className="space-y-5">
              {/* Stats row */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-[var(--border-glass)] bg-[var(--bg-card)] p-3 text-center">
                  <p className="text-lg font-bold text-white">{detail.iterations.length}</p>
                  <p className="text-[10px] text-slate-500">Iterations</p>
                </div>
                <div className="rounded-lg border border-[var(--border-glass)] bg-[var(--bg-card)] p-3 text-center">
                  <p className="text-lg font-bold text-white">
                    {detail.iterations.reduce((s, it) => s + it.token_usage, 0).toLocaleString()}
                  </p>
                  <p className="text-[10px] text-slate-500">Tokens</p>
                </div>
                <div className="rounded-lg border border-[var(--border-glass)] bg-[var(--bg-card)] p-3 text-center">
                  <p className="text-lg font-bold text-white">v{m?.version ?? 1}</p>
                  <p className="text-[10px] text-slate-500">Version</p>
                </div>
              </div>

              {/* PR link */}
              {m?.pr_url && (
                <a
                  href={m.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 px-3 py-2 rounded-lg border border-green-500/30 bg-green-500/10 text-green-300 text-sm hover:bg-green-500/15 transition-colors"
                >
                  <span>↗</span>
                  <span>Pull Request #{m.pr_number}</span>
                  <span className="text-xs text-green-500/70 ml-auto truncate">{m.pr_url.replace('https://', '')}</span>
                </a>
              )}

              {/* Module definition */}
              {defJson && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Module Definition</p>
                  <div className="space-y-3">
                    {defJson.description && (
                      <div>
                        <p className="text-[10px] text-slate-600 mb-1">Description</p>
                        <p className="text-xs text-slate-300 bg-black/20 rounded-lg p-3 leading-relaxed">{defJson.description}</p>
                      </div>
                    )}
                    {defJson.files_to_create && (
                      <div>
                        <p className="text-[10px] text-slate-600 mb-1">Files to Create</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(defJson.files_to_create as string[]).map((f: string) => (
                            <span key={f} className="text-[10px] font-mono text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 px-1.5 py-0.5 rounded">{f}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {defJson.acceptance_criteria && (
                      <div>
                        <p className="text-[10px] text-slate-600 mb-1">Acceptance Criteria</p>
                        <ul className="space-y-1">
                          {(defJson.acceptance_criteria as string[]).map((ac: string, i: number) => (
                            <li key={i} className="text-xs text-slate-400 flex gap-2">
                              <span className="text-indigo-500 shrink-0">◆</span>
                              {ac}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {defJson.dependencies && (
                      <div>
                        <p className="text-[10px] text-slate-600 mb-1">Dependencies</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(defJson.dependencies as string[]).map((d: string) => (
                            <span key={d} className="text-[10px] font-mono text-slate-400 bg-slate-700/50 border border-slate-600/50 px-1.5 py-0.5 rounded">{d}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {/* Raw JSON fallback for untyped fields */}
                    <details className="mt-2">
                      <summary className="text-[10px] text-slate-600 cursor-pointer hover:text-slate-400">View raw definition JSON</summary>
                      <pre className="mt-2 text-[10px] font-mono text-slate-500 bg-black/30 rounded-lg p-3 overflow-x-auto leading-relaxed whitespace-pre-wrap">
                        {JSON.stringify(defJson, null, 2)}
                      </pre>
                    </details>
                  </div>
                </div>
              )}

              {/* Dependency module links */}
              {(m?.dependency_ids ?? []).length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Dependencies</p>
                  <div className="flex flex-wrap gap-2">
                    {(m!.dependency_ids).map((dep) => (
                      <span key={dep} className="text-xs font-mono px-2 py-1 rounded border border-[var(--border-glass)] text-slate-400 bg-[var(--bg-card)]">
                        {dep}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {!loading && drawerTab === 'iterations' && detail && (
            <div className="space-y-3">
              {detail.iterations.length === 0 && (
                <p className="text-sm text-slate-600 py-8 text-center">No iterations recorded yet.</p>
              )}
              {[...detail.iterations]
                .sort((a, b) => a.iteration_number - b.iteration_number)
                .map((iter) => (
                  <DrawerIterationRow
                    key={iter.id ?? iter.iteration_number}
                    iter={iter}
                    prompt={detail.prompts.find((p) => p.iteration === iter.iteration_number)}
                    review={detail.reviews.find((r) => r.iteration === iter.iteration_number)}
                  />
                ))}
            </div>
          )}

          {!loading && drawerTab === 'timeline' && (
            <div className="space-y-2">
              {busHistory.length === 0 && (
                <p className="text-sm text-slate-600 py-8 text-center">No bus events recorded for this module.</p>
              )}
              {busHistory.map((msg, i) => {
                const evtName = String(msg.payload?.event ?? msg.payload?.type ?? msg.channel).replace(/_/g, ' ');
                return (
                  <div key={i} className="flex gap-3 text-xs">
                    <span className="text-slate-600 shrink-0 w-20 text-right font-mono">
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                    <div className="w-px bg-slate-700 shrink-0 self-stretch" />
                    <div className="pb-2">
                      <p className="text-slate-300">{evtName}</p>
                      <p className="text-slate-600 text-[10px]">
                        {msg.sender} · iter {msg.iteration} · {msg.channel}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Project header ───────────────────────────────────────────────────────────

function ProjectHeader({
  settings,
  pipelineStatus,
  metrics,
  modules,
}: {
  settings: Settings;
  pipelineStatus: PipelineStatus | null;
  metrics: Metrics | null;
  modules: Module[];
}) {
  const nowMs = Date.now();
  const ps = pipelineStatus?.pipeline_status ?? 'IDLE';
  const completed = metrics?.completed_modules ?? 0;
  const total = metrics?.total_modules ?? modules.length;
  const failed = metrics?.failed_modules ?? 0;
  const pct = total > 0 ? (completed / total) * 100 : 0;

  // Elapsed time — try metadata.started_at, then earliest module created_at
  const startIso: string | null =
    (pipelineStatus?.metadata?.started_at as string | undefined) ??
    (modules.length > 0
      ? [...modules].sort((a, b) => a.created_at.localeCompare(b.created_at))[0].created_at
      : null);
  const elapsedMs = startIso ? nowMs - new Date(startIso).getTime() : -1;

  // ETA — avg ms per completed module × remaining
  const completedModules = modules.filter((m) => m.status === 'completed');
  let etaStr = '—';
  if (completedModules.length > 0 && startIso && total > completed) {
    const avgMs = elapsedMs / completedModules.length;
    const remaining = total - completed;
    etaStr = fmtDuration(avgMs * remaining);
  } else if (ps === 'PIPELINE_COMPLETE') {
    etaStr = 'Done';
  }

  const githubBase = settings.github.owner && settings.github.repo
    ? `https://github.com/${settings.github.owner}/${settings.github.repo}`
    : null;

  return (
    <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-5 mb-6">
      {/* Top row */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-bold text-white">
              {settings.project.name || 'Unnamed Project'}
            </h1>
            <span className="text-xs px-2 py-0.5 rounded border border-[var(--border-glass)] text-slate-400 font-mono uppercase">
              {settings.project.language}
            </span>
          </div>
          {settings.project.root_path && (
            <p className="text-xs text-slate-500 font-mono truncate max-w-md">
              {settings.project.root_path}
            </p>
          )}
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Pipeline status */}
          <span className={`text-xs px-2.5 py-1 rounded-full border font-medium ${pipelineBadgeClass(ps)}`}>
            {ps.replace(/_/g, ' ')}
          </span>
          {/* GitHub link */}
          {githubBase && (
            <a
              href={githubBase}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-slate-400 hover:text-white flex items-center gap-1.5 border border-[var(--border-glass)] rounded-lg px-2.5 py-1 transition-colors hover:border-white/30"
            >
              <span>⎇</span> {settings.github.owner}/{settings.github.repo}
            </a>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5">
          <span>
            <span className="text-white font-semibold">{completed}</span>
            <span> / {total} modules complete</span>
            {failed > 0 && <span className="text-red-400 ml-2">({failed} failed)</span>}
          </span>
          <span className={`font-mono ${pct === 100 ? 'text-green-400' : 'text-slate-400'}`}>
            {pct.toFixed(0)}%
          </span>
        </div>
        <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              pct === 100 ? 'bg-green-500' : failed > 0 ? 'bg-gradient-to-r from-indigo-500 to-red-500' : 'bg-gradient-to-r from-indigo-500 to-purple-500'
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap gap-5 mt-3 text-xs text-slate-500">
        {startIso && (
          <span>Started: <span className="text-slate-300">{fmtTs(startIso)}</span></span>
        )}
        {elapsedMs > 0 && (
          <span>Elapsed: <span className="text-slate-300">{fmtDuration(elapsedMs)}</span></span>
        )}
        <span>ETA: <span className="text-slate-300">{etaStr}</span></span>
        <span>Iterations: <span className="text-slate-300">{(metrics?.total_iterations ?? 0).toLocaleString()}</span></span>
        <span>Tokens: <span className="text-slate-300">{(metrics?.total_token_usage ?? 0).toLocaleString()}</span></span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

type PageTab = 'modules' | 'dependencies';

export default function ProjectsView() {
  const [modules, setModules] = useState<Module[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');
  const [pageTab, setPageTab] = useState<PageTab>('modules');
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async (initial = false) => {
    try {
      const [mods, ps, met] = await Promise.all([
        api.getModules(),
        api.getPipelineStatus(),
        api.getMetrics(),
      ]);
      setModules(mods);
      setPipelineStatus(ps);
      setMetrics(met);
      if (initial) setLoading(false);
    } catch {
      setErrorMsg('Failed to load project data');
      if (initial) setLoading(false);
    }
  }, []);

  // Load settings once
  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {});
  }, []);

  // Polling loop
  useEffect(() => {
    refresh(true);
    const schedule = () => {
      pollRef.current = setTimeout(() => { refresh(); schedule(); }, POLL_MS);
    };
    schedule();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, [refresh]);

  const maxIter = settings?.pipeline.max_iterations_per_module ?? 5;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 gap-3">
        <span className="w-5 h-5 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
        Loading project data...
      </div>
    );
  }

  return (
    <div className="space-y-0 relative">
      {errorMsg && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-300">
          {errorMsg}
        </div>
      )}

      {/* Project header */}
      {settings && (
        <ProjectHeader
          settings={settings}
          pipelineStatus={pipelineStatus}
          metrics={metrics}
          modules={modules}
        />
      )}

      {/* Page tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-[var(--border-glass)] pb-2">
        {(['modules', 'dependencies'] as PageTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setPageTab(t)}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors capitalize ${
              pageTab === t
                ? 'text-white bg-indigo-500/15 border border-indigo-500/30'
                : 'text-slate-500 hover:text-white hover:bg-white/5'
            }`}
          >
            {t === 'modules' ? `Modules (${modules.length})` : 'Dependencies'}
          </button>
        ))}

        {/* Status summary pills */}
        <div className="ml-auto flex items-center gap-2">
          {(['pending', 'in_progress', 'completed', 'failed'] as const).map((s) => {
            const count = modules.filter((m) => m.status === s).length;
            if (count === 0) return null;
            const c = STATUS_STYLE[s];
            return (
              <span key={s} className={`text-[10px] px-2 py-0.5 rounded-full border ${c.badge}`}>
                {count} {STATUS_LABEL[s]}
              </span>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={pageTab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.15 }}
        >
          {pageTab === 'modules' && (
            <ModuleGrid
              modules={modules}
              pipelineStatus={pipelineStatus}
              maxIter={maxIter}
              onSelect={setSelectedModuleId}
            />
          )}
          {pageTab === 'dependencies' && (
            <DependencyGraph
              modules={modules}
              onSelect={(id) => { setSelectedModuleId(id); setPageTab('modules'); }}
            />
          )}
        </motion.div>
      </AnimatePresence>

      {/* Module detail drawer */}
      <AnimatePresence>
        {selectedModuleId && (
          <ModuleDetailDrawer
            key={selectedModuleId}
            moduleId={selectedModuleId}
            allModules={modules}
            onClose={() => setSelectedModuleId(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
