/* usePipelineFlow — Phase 8
   Synthesizes pipeline state for the Workflow visualization page.
   - Polls GET /api/pipeline/status + GET /api/modules every 3 s
   - Opens a dedicated WS connection to capture pipeline_events,
     module_updates, review_feedback, and hitl_requests for the event feed
   - Derives which station is active + which arrow is transitioning
*/

import { useState, useEffect, useRef } from 'react';
import type { Module, BusMessage } from '../types';
import { api } from './api';

// ─── Station ID type ──────────────────────────────────────────────────────────

export type StationId =
  | 'idle'
  | 'architect'
  | 'hitl1'
  | 'writer'
  | 'builder'
  | 'inspector'
  | 'git'
  | 'done';

export const STATION_ORDER: StationId[] = [
  'idle', 'architect', 'hitl1', 'writer', 'builder', 'inspector', 'git', 'done',
];

export function stationIndex(s: StationId): number {
  return STATION_ORDER.indexOf(s);
}

// ─── Feed event type ──────────────────────────────────────────────────────────

export interface FeedEvent {
  id: number;
  timestamp: string; // ISO string
  text: string;
  icon: string;
}

// ─── Flow state shape ─────────────────────────────────────────────────────────

export interface FlowState {
  pipelineStatus: string;
  currentModuleId: string | null;
  currentIteration: number;
  isHitlGate: boolean;
  totalModules: number;
  modules: Module[];
  activeStation: StationId;
  /** Previously active station — set briefly during a transition so arrows can animate. */
  prevStation: StationId | null;
  events: FeedEvent[];
  statusText: string;
  loading: boolean;
}

// ─── Pipeline status → station map ───────────────────────────────────────────

function psToStation(status: string): StationId {
  switch (status) {
    case 'IDLE':                    return 'idle';
    case 'LOADING_REQUIREMENTS':
    case 'MODULE_PLANNING':         return 'architect';
    case 'HITL_1_MODULE_REVIEW':    return 'hitl1';
    case 'PROMPT_GENERATION':
    case 'HITL_2_PROMPT_REVIEW':    return 'writer';
    case 'CODE_GENERATION':
    case 'VALIDATION':              return 'builder';
    case 'CODE_REVIEW':
    case 'HITL_3_REVIEW_DECISION':
    case 'DECISION':
    case 'HITL_4_MAX_ITERATIONS':   return 'inspector';
    case 'GIT_COMMIT':
    case 'MODULE_COMPLETE':
    case 'NEXT_MODULE':
    case 'INTEGRATION_TEST':
    case 'HITL_5_PR_REVIEW':       return 'git';
    case 'PIPELINE_COMPLETE':      return 'done';
    case 'FAILED':                 return 'idle';
    default:                       return 'idle';
  }
}

// ─── "What's happening" text ──────────────────────────────────────────────────

export function buildStatusText(
  status: string,
  moduleId: string | null,
  iteration: number,
  modules: Module[],
): string {
  const mod = modules.find((m) => m.id === moduleId);
  const name = mod?.name ?? (moduleId ? moduleId.replace(/-\d+$/, '') : 'module');
  const iter = iteration || 1;

  switch (status) {
    case 'IDLE':
      return 'Pipeline is idle — press Start to begin.';
    case 'LOADING_REQUIREMENTS':
      return 'Loading and parsing your requirements file...';
    case 'MODULE_PLANNING':
      return 'The Architect is decomposing your requirements into a feature module plan.';
    case 'HITL_1_MODULE_REVIEW':
      return 'The pipeline is waiting for your review of the module plan. Press Approve to continue.';
    case 'PROMPT_GENERATION':
      return `The Writer is crafting the engineering prompt for the ${name} module (attempt ${iter}).`;
    case 'HITL_2_PROMPT_REVIEW':
      return `Waiting for your review of the prompt for the ${name} module.`;
    case 'CODE_GENERATION':
      return `The Builder is writing code for the ${name} module (attempt ${iter}).`;
    case 'VALIDATION':
      return `Validating the generated code for the ${name} module...`;
    case 'CODE_REVIEW':
      return `The Inspector is reviewing code quality for the ${name} module.`;
    case 'HITL_3_REVIEW_DECISION':
      return `Waiting for your decision on the ${name} module code review.`;
    case 'DECISION':
      return `Evaluating the review results for the ${name} module...`;
    case 'GIT_COMMIT':
      return `Committing and pushing the ${name} module to GitHub.`;
    case 'MODULE_COMPLETE':
      return `The ${name} module is complete!`;
    case 'NEXT_MODULE':
      return 'Moving to the next module in the plan...';
    case 'HITL_4_MAX_ITERATIONS':
      return `Maximum iterations reached for the ${name} module. Your review is needed.`;
    case 'PIPELINE_COMPLETE':
      return 'All modules are complete. Your application is ready on GitHub!';
    case 'FAILED':
      return 'The pipeline encountered an error. Check the Terminal Hub for details.';
    default:
      return 'Pipeline is running...';
  }
}

// ─── Bus message → plain-English feed event ───────────────────────────────────

let _evtId = 0;

function toFeedEvent(msg: BusMessage, modules: Module[]): FeedEvent | null {
  const p = msg.payload as Record<string, unknown>;
  const ev = p.event as string | undefined;
  const mod = modules.find((m) => m.id === msg.module_id);
  const name = mod?.name ?? (msg.module_id ? msg.module_id.replace(/-\d+$/, '') : '');
  const ts = msg.timestamp;

  switch (msg.channel) {
    case 'pipeline_events': {
      const decision = p.decision as string | undefined;
      if (ev === 'decision' && decision === 'MODULE_COMPLETE')
        return { id: ++_evtId, timestamp: ts, text: `The Inspector accepted the ${name} module. Moving to commit.`, icon: '✓' };
      if (ev === 'decision' && decision === 'ITERATE')
        return { id: ++_evtId, timestamp: ts, text: `The Inspector sent the ${name} module back to The Writer for revision.`, icon: '↩' };
      if (ev === 'decision' && decision === 'HITL_4_MAX_ITERATIONS')
        return { id: ++_evtId, timestamp: ts, text: `Max iterations reached for ${name}. Your review is needed.`, icon: '⚠' };
      if (ev === 'git_push')
        return { id: ++_evtId, timestamp: ts, text: `Code committed and pushed to GitHub — iteration ${p.iteration ?? '?'}.`, icon: '↑' };
      if (ev === 'repo_cloned')
        return { id: ++_evtId, timestamp: ts, text: `Source repository cloned — ${p.file_count ?? 0} files included for context.`, icon: '⬇' };
      return null;
    }
    case 'module_updates': {
      const s = p.status as string | undefined;
      if (s === 'in_progress')
        return { id: ++_evtId, timestamp: ts, text: `Started working on the ${name} module.`, icon: '▸' };
      if (s === 'completed')
        return { id: ++_evtId, timestamp: ts, text: `The ${name} module is complete!`, icon: '✓' };
      if (s === 'failed')
        return { id: ++_evtId, timestamp: ts, text: `The ${name} module failed.`, icon: '✕' };
      return null;
    }
    case 'review_feedback': {
      const issues = p.issues as number | undefined;
      if (typeof issues === 'number')
        return {
          id: ++_evtId,
          timestamp: ts,
          text:
            issues === 0
              ? `The Inspector reviewed ${name} — all checks passed.`
              : `The Inspector found ${issues} issue${issues !== 1 ? 's' : ''} in ${name}. Sending feedback to The Writer.`,
          icon: issues === 0 ? '✓' : '⚠',
        };
      return { id: ++_evtId, timestamp: ts, text: `The Inspector reviewed the ${name} module.`, icon: '◈' };
    }
    case 'hitl_requests':
      return { id: ++_evtId, timestamp: ts, text: 'Pipeline is paused and waiting for your approval.', icon: '⏸' };
    default:
      return null;
  }
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function usePipelineFlow(): FlowState {
  const [pipelineStatus, setPipelineStatus] = useState<string>('IDLE');
  const [currentModuleId, setCurrentModuleId] = useState<string | null>(null);
  const [currentIteration, setCurrentIteration] = useState<number>(0);
  const [isHitlGate, setIsHitlGate] = useState(false);
  const [totalModules, setTotalModules] = useState(0);
  const [modules, setModules] = useState<Module[]>([]);
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [prevStation, setPrevStation] = useState<StationId | null>(null);
  const [loading, setLoading] = useState(true);

  const prevStationRef = useRef<StationId>('idle');
  const modulesRef = useRef<Module[]>([]);
  const cancelledRef = useRef(false);

  useEffect(() => {
    modulesRef.current = modules;
  }, [modules]);

  // Poll pipeline status + modules
  useEffect(() => {
    cancelledRef.current = false;

    const poll = async () => {
      try {
        const [statusRes, modsRes] = await Promise.all([
          api.getPipelineStatus(),
          api.getModules(),
        ]);
        if (cancelledRef.current) return;

        const newStation = psToStation(statusRes.pipeline_status);
        const oldStation = prevStationRef.current;
        if (newStation !== oldStation) {
          prevStationRef.current = newStation;
          setPrevStation(oldStation);
          setTimeout(() => {
            if (!cancelledRef.current) setPrevStation(null);
          }, 1200);
        }

        setPipelineStatus(statusRes.pipeline_status);
        setCurrentModuleId(statusRes.current_module_id);
        setCurrentIteration(statusRes.current_iteration);
        setIsHitlGate(statusRes.is_hitl_gate);
        setTotalModules(statusRes.total_modules);
        setModules(modsRes);
        setLoading(false);
      } catch {
        if (!cancelledRef.current) setLoading(false);
      }
    };

    poll();
    const id = setInterval(poll, 3000);
    return () => {
      cancelledRef.current = true;
      clearInterval(id);
    };
  }, []);

  // WebSocket for the event feed
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    const TRACKED = new Set(['pipeline_events', 'module_updates', 'review_feedback', 'hitl_requests']);

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as BusMessage;
        if (!TRACKED.has(msg.channel)) return;
        const feedEvt = toFeedEvent(msg, modulesRef.current);
        if (feedEvt) {
          setEvents((prev) => [feedEvt, ...prev].slice(0, 30));
        }
      } catch {
        // ignore malformed JSON
      }
    };

    return () => ws.close();
  }, []);

  const activeStation = psToStation(pipelineStatus);
  const statusText = buildStatusText(pipelineStatus, currentModuleId, currentIteration, modules);

  return {
    pipelineStatus,
    currentModuleId,
    currentIteration,
    isHitlGate,
    totalModules,
    modules,
    activeStation,
    prevStation,
    events,
    statusText,
    loading,
  };
}
