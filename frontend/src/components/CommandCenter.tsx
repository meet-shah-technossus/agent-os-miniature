/* CommandCenter — Phase 4
   Main workspace: left pane (prompt editor + review viewer) + right pane
   (CLI terminal grid with framer-motion dynamic expansion).

   Layout:
     ┌──────────────────────┬─────────────────────────────┐
     │  LEFT PANE           │  RIGHT PANE                 │
     │  ┌──────────────┐    │  ┌────┐ ┌────┐ ┌────┐      │
     │  │ Prompt Editor│    │  │CLI │ │CLI │ │CLI │      │
     │  │              │    │  │    │ │    │ │    │      │
     │  └──────────────┘    │  └────┘ └────┘ └────┘      │
     │  ┌──────────────┐    │  ┌────────────────────┐     │
     │  │ Review JSON  │    │  │  Active (expanded) │     │
     │  └──────────────┘    │  └────────────────────┘     │
     └──────────────────────┴─────────────────────────────┘
*/

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { AgentTerminalState, BusMessage, CliToolStatus } from '../types';
import { api } from '../hooks/api';
import TerminalPanel from './TerminalPanel';
import PromptEditor, { CLI_TOOL_KEYS, CLI_DISPLAY, CLI_ICON, type CliToolKey } from './PromptEditor';
import ReviewViewer from './ReviewViewer';
import { TOOL_MODELS } from '../constants';

// ─── Constants ────────────────────────────────────────────────────────────────

// Map CLI tool keys to PIPELINE_POST keys used by terminal states
const CLI_TO_POST: Record<CliToolKey, string> = {
  codex:    'CODE_GENERATOR',
  aider:    'CODE_GENERATOR',
  claude:   'CODE_GENERATOR',
  gemini:   'CODE_GENERATOR',
  qwen:     'CODE_GENERATOR',
  deepseek: 'CODE_GENERATOR',
  copilot:  'CODE_GENERATOR',
};

const SYSTEM_TERMINALS = [
  { key: 'PROMPT_GENERATOR' as const, label: 'Prompt Generator', icon: '⊕' },
  { key: 'CODE_REVIEWER'    as const, label: 'Code Reviewer',    icon: '⊗' },
];
type SystemTerminalKey = 'PROMPT_GENERATOR' | 'CODE_REVIEWER';

// ─── Pill badge ───────────────────────────────────────────────────────────────

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    idle:          'bg-slate-500/20 text-slate-400 border-slate-500/30',
    running:       'bg-green-500/20  text-green-400  border-green-500/30',
    authenticated: 'bg-blue-500/20   text-blue-400   border-blue-500/30',
    error:         'bg-red-500/20    text-red-400    border-red-500/30',
    done:          'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${map[status] ?? map.idle}`}>
      {status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
      {status}
    </span>
  );
}

// ─── Compact CLI Card (collapsed state) ──────────────────────────────────────

interface CliCardProps {
  toolKey: CliToolKey;
  toolStatus: CliToolStatus | undefined;
  isSelected: boolean;
  terminalState: AgentTerminalState | undefined;
  onClick: () => void;
}

function CliCard({ toolKey, toolStatus, isSelected, terminalState, onClick }: CliCardProps) {
  // Only show 'running' if this specific tool is confirmed as the active one.
  // When activeTool is null (no tool info from backend) only the currently
  // selected (isSelected) card shows running, to avoid all cards lighting up.
  const isActiveForTool = terminalState?.status === 'running' &&
    (terminalState.activeTool === toolKey || (terminalState.activeTool === null && isSelected));
  const runStatus = isActiveForTool ? 'running' : (terminalState?.status === 'running' ? 'idle' : (terminalState?.status ?? 'idle'));
  const isRunning = runStatus === 'running';

  return (
    <motion.div
      layout
      layoutId={`cli-card-${toolKey}`}
      onClick={onClick}
      className={`cursor-pointer rounded-xl border transition-colors shrink-0 ${
        isSelected
          ? 'border-indigo-500/50 bg-indigo-500/10'
          : 'border-[var(--border-glass)] bg-[var(--bg-secondary)] hover:border-indigo-500/30'
      }`}
      style={{ flex: '0 0 80px' }}
      transition={{ type: 'spring', stiffness: 350, damping: 30 }}
    >
      <div className="flex items-center gap-3 px-4 h-full">
        <span className={`text-xl ${isSelected ? 'text-indigo-400' : 'text-slate-500'}`}>
          {CLI_ICON[toolKey]}
        </span>
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-semibold truncate ${isSelected ? 'text-white' : 'text-slate-300'}`}>
            {CLI_DISPLAY[toolKey]}
          </p>
          <p className="text-[11px] text-slate-500 truncate">
            {toolStatus?.installed ? (toolStatus.authenticated ? 'authenticated' : 'not authenticated') : 'not installed'}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <StatusPill status={isRunning ? 'running' : toolStatus?.authenticated ? 'authenticated' : 'idle'} />
          {toolStatus?.installed === false && (
            <span className="text-[10px] text-red-400/70">not installed</span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Expanded Terminal Panel ──────────────────────────────────────────────────

interface ExpandedTerminalProps {
  toolKey: CliToolKey;
  terminalState: AgentTerminalState | undefined;
  onCollapse: () => void;
}

function ExpandedTerminal({ toolKey, terminalState, onCollapse }: ExpandedTerminalProps) {
  const [minTermHeight, setMinTermHeight] = useState(350);
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);

  const handleResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startH: minTermHeight };
    const onMouseMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setMinTermHeight(Math.max(200, dragRef.current.startH + ev.clientY - dragRef.current.startY));
    };
    const onMouseUp = () => {
      dragRef.current = null;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  const fallbackState: AgentTerminalState = terminalState ?? {
    agentPost: CLI_TO_POST[toolKey],
    senderName: toolKey,
    lines: [],
    status: 'idle',
    model: null,
    currentModuleId: null,
    currentIteration: 0,
    sessionStartedAt: null,
    sessionEndedAt: null,
    lastExitCode: null,
    sessionCount: 0,
    activeTool: null,
  };

  return (
    <motion.div
      layout
      layoutId={`cli-card-${toolKey}`}
      className="rounded-xl border border-indigo-500/40 bg-[var(--bg-secondary)] overflow-hidden flex flex-col"
      style={{ height: `${minTermHeight}px`, flexShrink: 0 }}
      transition={{ type: 'spring', stiffness: 280, damping: 28 }}
    >
      {/* Expanded header */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--border-glass)] shrink-0">
        <span className="text-indigo-400">{CLI_ICON[toolKey]}</span>
        <span className="font-semibold text-white text-sm">{CLI_DISPLAY[toolKey]}</span>
        <StatusPill status={fallbackState.status} />
        <div className="flex-1" />
        <button
          onClick={onCollapse}
          className="text-slate-500 hover:text-white transition-colors text-xs px-2 py-1 rounded hover:bg-white/5"
        >
          Collapse ↑
        </button>
      </div>
      {/* Terminal output */}
      <div className="flex-1 min-h-0">
        <TerminalPanel state={fallbackState} compact={false} />
      </div>
      {/* Vertical resize handle */}
      <div
        onMouseDown={handleResizeMouseDown}
        className="shrink-0 flex items-center justify-center hover:bg-indigo-500/20 transition-colors"
        style={{ height: '8px', cursor: 'ns-resize', borderTop: '1px solid rgba(99,102,241,0.2)' }}
        title="Drag to resize"
      >
        <div style={{ width: '32px', height: '2px', borderRadius: '1px', background: 'rgba(99,102,241,0.4)' }} />
      </div>
    </motion.div>
  );
}

// ─── System Terminal Card (collapsed) ───────────────────────────────────────────

interface SystemTerminalCardProps {
  termKey: SystemTerminalKey;
  label: string;
  icon: string;
  terminalState: AgentTerminalState | undefined;
  onClick: () => void;
}

function SystemTerminalCard({ termKey, label, icon, terminalState, onClick }: SystemTerminalCardProps) {
  const runStatus = terminalState?.status ?? 'idle';
  const isRunning = runStatus === 'running';

  return (
    <motion.div
      layout
      layoutId={`system-card-${termKey}`}
      onClick={onClick}
      className="cursor-pointer rounded-xl border border-[var(--border-glass)] bg-[var(--bg-secondary)] hover:border-indigo-500/30 transition-colors shrink-0"
      style={{ flex: '0 0 80px' }}
      transition={{ type: 'spring', stiffness: 350, damping: 30 }}
    >
      <div className="flex items-center gap-3 px-4 h-full">
        <span className="text-xl text-slate-500">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate text-slate-300">{label}</p>
          <p className="text-[11px] text-slate-500 truncate">system process</p>
        </div>
        <StatusPill status={isRunning ? 'running' : runStatus} />
      </div>
    </motion.div>
  );
}

// ─── Expanded System Terminal ──────────────────────────────────────────────────

interface ExpandedSystemTerminalProps {
  termKey: SystemTerminalKey;
  label: string;
  icon: string;
  terminalState: AgentTerminalState | undefined;
  onCollapse: () => void;
}

function ExpandedSystemTerminal({ termKey, label, icon, terminalState, onCollapse }: ExpandedSystemTerminalProps) {
  const [minTermHeight, setMinTermHeight] = useState(350);
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);

  const handleResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startH: minTermHeight };
    const onMouseMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setMinTermHeight(Math.max(200, dragRef.current.startH + ev.clientY - dragRef.current.startY));
    };
    const onMouseUp = () => {
      dragRef.current = null;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  const fallbackState: AgentTerminalState = terminalState ?? {
    agentPost: termKey,
    senderName: label.toLowerCase().replace(/ /g, '_'),
    lines: [],
    status: 'idle',
    model: null,
    currentModuleId: null,
    currentIteration: 0,
    sessionStartedAt: null,
    sessionEndedAt: null,
    lastExitCode: null,
    sessionCount: 0,
    activeTool: null,
  };

  return (
    <motion.div
      layout
      layoutId={`system-card-${termKey}`}
      className="rounded-xl border border-indigo-500/40 bg-[var(--bg-secondary)] overflow-hidden flex flex-col"
      style={{ height: `${minTermHeight}px`, flexShrink: 0 }}
      transition={{ type: 'spring', stiffness: 280, damping: 28 }}
    >
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--border-glass)] shrink-0">
        <span className="text-indigo-400">{icon}</span>
        <span className="font-semibold text-white text-sm">{label}</span>
        <StatusPill status={fallbackState.status} />
        <div className="flex-1" />
        <button
          onClick={onCollapse}
          className="text-slate-500 hover:text-white transition-colors text-xs px-2 py-1 rounded hover:bg-white/5"
        >
          Collapse ↑
        </button>
      </div>
      <div className="flex-1 min-h-0">
        <TerminalPanel state={fallbackState} compact={false} />
      </div>
      {/* Vertical resize handle */}
      <div
        onMouseDown={handleResizeMouseDown}
        className="shrink-0 flex items-center justify-center hover:bg-indigo-500/20 transition-colors"
        style={{ height: '8px', cursor: 'ns-resize', borderTop: '1px solid rgba(99,102,241,0.2)' }}
        title="Drag to resize"
      >
        <div style={{ width: '32px', height: '2px', borderRadius: '1px', background: 'rgba(99,102,241,0.4)' }} />
      </div>
    </motion.div>
  );
}
// ─── Right pane: CLI terminal grid ────────────────────────────────────────────

interface CliGridProps {
  terminalStates: Record<string, AgentTerminalState>;
  toolStatuses: CliToolStatus[];
  activeTool: CliToolKey | null;
  expandedSystemKeys: Set<SystemTerminalKey>;
  onSelectTool: (k: CliToolKey) => void;
  onToggleSystem: (k: SystemTerminalKey) => void;
}

function CliGrid({ terminalStates, toolStatuses, activeTool, expandedSystemKeys, onSelectTool, onToggleSystem }: CliGridProps) {
  // Filter CODE_GENERATOR tool cards to installed + authenticated tools only
  const availableToolKeys = CLI_TOOL_KEYS.filter((k) => {
    const ts = toolStatuses.find((t) => t.key === k);
    return k === activeTool || (ts?.installed && ts?.authenticated);
  });

  // Re-order so active tool is always first
  const orderedToolKeys = activeTool && availableToolKeys.includes(activeTool)
    ? [activeTool, ...availableToolKeys.filter((k) => k !== activeTool)]
    : availableToolKeys;

  return (
    <div className="flex flex-col gap-3 pr-1">
      <AnimatePresence>
        {/* System terminals: Prompt Generator + Code Reviewer */}
        {SYSTEM_TERMINALS.map(({ key, label, icon }) => {
          const isExpanded = expandedSystemKeys.has(key);
          const term = terminalStates[key];
          if (isExpanded) {
            return (
              <ExpandedSystemTerminal
                key={key}
                termKey={key}
                label={label}
                icon={icon}
                terminalState={term}
                onCollapse={() => onToggleSystem(key)}
              />
            );
          }
          return (
            <SystemTerminalCard
              key={key}
              termKey={key}
              label={label}
              icon={icon}
              terminalState={term}
              onClick={() => onToggleSystem(key)}
            />
          );
        })}

        {/* CODE_GENERATOR tool terminals (only available tools) */}
        {orderedToolKeys.map((key) => {
          const ts = toolStatuses.find((t) => t.key === key);
          const post = CLI_TO_POST[key];
          const termState = terminalStates[post];
          const isActive = activeTool === key;

          if (isActive) {
            return (
              <ExpandedTerminal
                key={key}
                toolKey={key}
                terminalState={termState}
                onCollapse={() => onSelectTool(key)}
              />
            );
          }
          return (
            <CliCard
              key={key}
              toolKey={key}
              toolStatus={ts}
              isSelected={false}
              terminalState={termState}
              onClick={() => onSelectTool(key)}
            />
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// ─── Main CommandCenter ────────────────────────────────────────────────────────

interface Props {
  terminalStates: Record<string, AgentTerminalState>;
  wsConnected: boolean;
  messages: BusMessage[];
}

export default function CommandCenter({ terminalStates, wsConnected, messages }: Props) {
  // ── State ────────────────────────────────────────────────────────────────────
  const [promptContent, setPromptContent] = useState('');
  const [, setReviewContent] = useState('');
  const [reviewOriginalContent, setReviewOriginalContent] = useState('');
  const [reviewEditedContent, setReviewEditedContent] = useState('');
  const [promptIteration, setPromptIteration] = useState(0);
  const [reviewIteration, setReviewIteration] = useState(0);
  const [pipelineStatus, setPipelineStatus] = useState('IDLE');
  const [toolStatuses, setToolStatuses] = useState<CliToolStatus[]>([]);
  const [selectedTool, setSelectedTool] = useState<CliToolKey>('codex');
  const [selectedModel, setSelectedModel] = useState<string>(TOOL_MODELS.codex[0]);
  const [activeTool, setActiveTool] = useState<CliToolKey | null>(null);
  const [expandedSystemKeys, setExpandedSystemKeys] = useState<Set<SystemTerminalKey>>(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prFailed, setPrFailed] = useState(false);
  const [prError, setPrError] = useState('');
  const [promptGenFailed, setPromptGenFailed] = useState(false);
  const [promptGenError, setPromptGenError] = useState('');
  const [, setCodeGenFailed] = useState(false);
  const [codeGenError, setCodeGenError] = useState('');
  const [codeReviewFailed, setCodeReviewFailed] = useState(false);
  const [codeReviewError, setCodeReviewError] = useState('');

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reviewUserModifiedRef = useRef(false);
  const promptUserModifiedRef = useRef(false);
  const promptIterationRef = useRef(0);
  const reviewIterationRef = useRef(0);

  // ── Polling ───────────────────────────────────────────────────────────────────

  const refresh = useCallback(async () => {
    try {
      const [statusRes, promptRes, reviewRes] = await Promise.all([
        api.getPipelineStatus(),
        api.getCurrentPrompt().catch(() => null),
        api.getCurrentReview().catch(() => null),
      ]);
      setPipelineStatus(statusRes.pipeline_status);
      setPrFailed(!!statusRes.metadata?.pr_failed);
      setPrError((statusRes.metadata?.pr_error as string) || '');
      setPromptGenFailed(!!statusRes.metadata?.prompt_gen_failed);
      setPromptGenError((statusRes.metadata?.prompt_gen_error as string) || '');
      setCodeGenFailed(statusRes.pipeline_status === 'CODE_GEN_FAILED');
      setCodeGenError((statusRes.metadata?.code_gen_error as string) || '');
      setCodeReviewFailed(!!statusRes.metadata?.code_review_failed);
      setCodeReviewError((statusRes.metadata?.code_review_error as string) || '');
      if (promptRes && promptRes.content) {
        // Always update when iteration advances (new prompt from code review loop).
        // Only suppress if user manually edited the *current* iteration.
        const isNewIteration = promptRes.iteration > promptIterationRef.current;
        if (isNewIteration || !promptUserModifiedRef.current) {
          setPromptContent(promptRes.content);
          setPromptIteration(promptRes.iteration);
          promptIterationRef.current = promptRes.iteration;
          if (isNewIteration) {
            promptUserModifiedRef.current = false;
          }
        }
      }
      if (reviewRes && reviewRes.content) {
        const pretty = (() => {
          const c = reviewRes.content;
          if (c.trim().startsWith('{')) {
            try { return JSON.stringify(JSON.parse(c), null, 2); } catch { /* */ }
          }
          return c;
        })();
        setReviewContent(pretty);
        setReviewOriginalContent(pretty);
        // Always update the editor when a new iteration arrives (new review
        // from backend after a retry loop). Only suppress if user is editing the
        // *current* iteration.
        const isNewReviewIteration = reviewRes.iteration > reviewIterationRef.current;
        if (isNewReviewIteration || !reviewUserModifiedRef.current) {
          setReviewEditedContent(pretty);
          setReviewIteration(reviewRes.iteration);
          reviewIterationRef.current = reviewRes.iteration;
          if (isNewReviewIteration) {
            reviewUserModifiedRef.current = false;
          }
        }
      }
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  // Load CLI tool statuses once
  useEffect(() => {
    api.getCliTools()
      .then((res) => setToolStatuses(res.tools))
      .catch(() => {});
  }, []);

  // When CODE_GEN_FAILED banner is shown, ensure selectedTool is an available tool
  useEffect(() => {
    if (pipelineStatus !== 'CODE_GEN_FAILED' || toolStatuses.length === 0) return;
    const currentTs = toolStatuses.find((t) => t.key === selectedTool);
    if (!currentTs?.available) {
      const firstReady = CLI_TOOL_KEYS.find((k) => toolStatuses.find((t) => t.key === k)?.available);
      if (firstReady) {
        setSelectedTool(firstReady);
        setSelectedModel(TOOL_MODELS[firstReady]?.[0] ?? '');
      }
    }
  }, [pipelineStatus, toolStatuses]);

  // Auto-expand the active tool terminal when code generation starts
  useEffect(() => {
    const codeGenState = terminalStates['CODE_GENERATOR'];
    if (!codeGenState) return;
    const runningTool = codeGenState.activeTool as CliToolKey | null;
    if (runningTool && CLI_TOOL_KEYS.includes(runningTool) && runningTool !== activeTool) {
      setActiveTool(runningTool);
      setSelectedTool(runningTool);
      setSelectedModel(TOOL_MODELS[runningTool]?.[0] ?? '');
    }
  }, [terminalStates]);

  // Immediately update state from WebSocket pipeline events — no poll needed
  const prevMsgLen = useRef(0);
  useEffect(() => {
    const newMsgs = messages.slice(prevMsgLen.current);
    prevMsgLen.current = messages.length;
    if (newMsgs.length === 0) return;

    // Every pipeline message carries pipeline_status — apply it immediately
    // so the Approve button enables without waiting for the 3-second poll.
    for (const m of newMsgs) {
      if (m.channel === 'pipeline' && m.pipeline_status) {
        setPipelineStatus(m.pipeline_status as string);
      }
    }

    // For prompt/review content changes, still fetch the latest text
    const hasPromptDone = newMsgs.some(
      (m) => m.channel === 'pipeline' && (m.event === 'prompt_generation_complete' || m.event === 'hitl_gate'),
    );
    const hasReviewDone = newMsgs.some(
      (m) => m.channel === 'pipeline' && (m.event === 'code_review_complete' || m.event === 'state_changed'),
    );
    const hasComponentFailed = newMsgs.some(
      (m) => m.channel === 'pipeline' &&
        ['prompt_gen_failed', 'code_gen_failed', 'code_review_failed'].includes(m.event as string),
    );
    if (hasPromptDone || hasReviewDone || hasComponentFailed) {
      refresh();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  // ── Handlers ──────────────────────────────────────────────────────────────────


  const handleApprovePrompt = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.approvePrompt(promptContent, selectedTool, selectedModel);
      promptUserModifiedRef.current = false;
      setActiveTool(selectedTool);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const isReviewModified = useMemo(
    () => !!reviewOriginalContent && reviewEditedContent !== reviewOriginalContent,
    [reviewOriginalContent, reviewEditedContent],
  );

  const isReviewValidJson = useMemo(() => {
    const trimmed = reviewEditedContent.trim();
    if (!trimmed || !trimmed.startsWith('{')) return true;
    try { JSON.parse(trimmed); return true; } catch { return false; }
  }, [reviewEditedContent]);

  const handlePromptEdit = (v: string) => {
    promptUserModifiedRef.current = true;
    setPromptContent(v);
  };

  const handleReviewEdit = (v: string) => {
    reviewUserModifiedRef.current = true;
    setReviewEditedContent(v);
  };

  const handleReviewReset = () => {
    reviewUserModifiedRef.current = false;
    setReviewEditedContent(reviewOriginalContent);
  };

  const handleApproveReview = async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (isReviewModified && isReviewValidJson) {
        await api.submitReview(reviewEditedContent);
      }
      await api.approveReview();
      reviewUserModifiedRef.current = false;
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleMoveToNextStory = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.moveToNextStory();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleStopCodeGen = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.stopCodeGeneration();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleStopRollback = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.stopRollback();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleStopContinue = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.stopContinue();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetryPR = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.retryPR();
      // Don't optimistically clear prFailed here — let refresh() pull the
      // actual backend state. If the retry succeeded, pr_failed will be false;
      // if an operational step failed (git push, PR creation, etc.) the updated
      // pr_error will still be shown and the button remains usable.
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetryPromptGenerator = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.retryPromptGenerator();
      setPromptGenFailed(false);
      setPromptGenError('');
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetryCodeGenerator = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.retryCodeGenerator(selectedTool, selectedModel);
      await refresh();
    } catch (e) {
      setError(String(e));
      // Re-sync state so the button visibility stays accurate
      await refresh().catch(() => null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetryCodeReviewer = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.retryCodeReviewer();
      setCodeReviewFailed(false);
      setCodeReviewError('');
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleToolSelect = (key: CliToolKey) => {
    const isExpanding = activeTool !== key;
    if (isExpanding) {
      setSelectedTool(key);
      setSelectedModel(TOOL_MODELS[key]?.[0] ?? '');
      api.setCliTool('CODE_GENERATOR', key).catch(() => {});
    }
    setActiveTool((prev) => (prev === key ? null : key));
  };

  const handleModelSelect = (model: string) => {
    setSelectedModel(model);
    api.updateModelRouting({ CODE_GENERATOR: model }).catch(() => {});
  };

  const handleSystemToggle = (key: SystemTerminalKey) => {
    setExpandedSystemKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="h-full flex flex-col">
      {/* Page header */}
      <div className="mb-4 shrink-0 flex items-center gap-3">
        <div>
          <h2 className="text-2xl font-bold text-white">Command Center</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-0.5">
            Prompt editor · Review JSON · CLI terminal grid
          </p>
        </div>
        <div className="flex-1" />
        <span
          className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${
            wsConnected
              ? 'bg-green-500/10 text-green-400 border-green-500/30'
              : 'bg-red-500/10 text-red-400 border-red-500/30'
          }`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
          {wsConnected ? 'Live' : 'Disconnected'}
        </span>
        {/* Pipeline status pill */}
        <span className="text-xs px-2.5 py-1 rounded-full border border-[var(--border-glass)] text-slate-400 font-mono">
          {pipelineStatus.toLowerCase().replace(/_/g, ' ')}
        </span>
      </div>

      {/* Error banner */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-3 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2 shrink-0"
          >
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="hover:text-white transition-colors">✕</button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main split layout */}
      <div className="flex-1 min-h-0 flex gap-4">
        {/* ── Left pane ─────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-4 min-h-0 overflow-y-auto" style={{ width: '45%', minWidth: 320 }}>
          {/* Prompt editor */}
          <PromptEditor
            content={promptContent}
            isLoading={isLoading}
            pipelineStatus={pipelineStatus}
            iteration={promptIteration}
            selectedTool={selectedTool}
            selectedModel={selectedModel}
            availableModels={TOOL_MODELS[selectedTool] ?? []}
            toolStatuses={toolStatuses}
            onContentChange={handlePromptEdit}
            onApprove={handleApprovePrompt}
            onToolSelect={handleToolSelect}
            onModelSelect={handleModelSelect}
            promptGenFailed={promptGenFailed}
            promptGenError={promptGenError}
            onRetryPromptGenerator={handleRetryPromptGenerator}
          />

          {/* Review JSON viewer */}
          <ReviewViewer
            content={reviewEditedContent}
            iteration={reviewIteration}
            pipelineStatus={pipelineStatus}
            isModified={isReviewModified}
            isValidJson={isReviewValidJson}
            onApprove={handleApproveReview}
            onMoveToNextStory={handleMoveToNextStory}
            onReset={handleReviewReset}
            onContentChange={handleReviewEdit}
            onRetryPR={handleRetryPR}
            onRetryCodeGenerator={handleRetryCodeGenerator}
            isLoading={isLoading}
            prFailed={prFailed}
            prError={prError}
            codeReviewFailed={codeReviewFailed}
            codeReviewError={codeReviewError}
            onRetryCodeReviewer={handleRetryCodeReviewer}
            reviewJsonExists={!!reviewOriginalContent.trim()}
          />
        </div>

        {/* ── Divider ────────────────────────────────────────────────────── */}
        <div className="w-px shrink-0 bg-[var(--border-glass)]" />

        {/* ── Right pane ────────────────────────────────────────────────── */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="mb-2 shrink-0 flex items-center gap-2">
            <h3 className="text-sm font-semibold text-white">CLI Terminals</h3>
            <span className="text-[11px] text-slate-500">click to expand</span>
            <div className="flex-1" />
            {(pipelineStatus === 'CODE_GENERATION' || pipelineStatus === 'STORY_CODE_GENERATION') && (
              <button
                onClick={handleStopCodeGen}
                disabled={isLoading}
                title="Kill the running CLI session and preserve partial file changes"
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-red-600 text-white hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <span className="w-2 h-2 rounded-sm bg-white inline-block" />
                Stop
              </button>
            )}
          </div>
          {pipelineStatus === 'CODE_GEN_FAILED' && (
            <div className="mb-2 shrink-0 px-3 py-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex flex-col gap-2">
              <div className="flex items-start gap-2">
                <span className="mt-0.5">⚠</span>
                <span className="flex-1">Code generation failed{codeGenError ? `: ${codeGenError}` : ''}</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-rose-300/70 shrink-0">Change tool/model before retrying:</span>
                <select
                  value={selectedTool}
                  onChange={(e) => {
                    const t = e.target.value as CliToolKey;
                    setSelectedTool(t);
                    setSelectedModel(TOOL_MODELS[t]?.[0] ?? '');
                  }}
                  className="flex-1 min-w-[110px] rounded px-2 py-1 bg-slate-800 border border-white/10 text-white/80 text-xs"
                >
                  {CLI_TOOL_KEYS.filter((k) => {
                    const ts = toolStatuses.find((t) => t.key === k);
                    return ts?.available === true;
                  }).map((k) => (
                    <option key={k} value={k}>{CLI_DISPLAY[k]}</option>
                  ))}
                </select>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="flex-1 min-w-[140px] rounded px-2 py-1 bg-slate-800 border border-white/10 text-white/80 text-xs"
                >
                  {(TOOL_MODELS[selectedTool] ?? []).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <button
                  onClick={handleRetryCodeGenerator}
                  disabled={isLoading}
                  className="px-3 py-1 rounded-lg text-xs font-semibold bg-rose-500 text-white hover:bg-rose-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                >
                  Retry
                </button>
              </div>
            </div>
          )}
          {pipelineStatus === 'CODE_GEN_STOPPED' && (
            <div className="mb-2 shrink-0 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-amber-400 text-xs font-semibold">
                <span className="w-2 h-2 rounded-sm bg-amber-400 inline-block" />
                Code generation stopped — partial changes preserved on disk
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                The CLI session was killed. Any files written up to this point are still on disk.
                Choose what to do with the partial changes:
              </p>
              <div className="flex items-center gap-2 mt-1">
                <button
                  onClick={handleStopRollback}
                  disabled={isLoading}
                  title="Discard partial changes (git reset --hard HEAD + git clean -fd) and return to prompt review"
                  className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-600 text-white hover:bg-slate-500 border border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Roll Back
                </button>
                <button
                  onClick={handleStopContinue}
                  disabled={isLoading}
                  title="Commit partial changes, push to GitHub and proceed to code review"
                  className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Save &amp; Continue
                </button>
              </div>
              <p className="text-[10px] text-slate-500 italic">
                Roll Back discards all partial changes. Save &amp; Continue commits what was written and opens a PR.
              </p>
            </div>
          )}
          <div className="flex-1 min-h-0 overflow-y-auto">
            <CliGrid
              terminalStates={terminalStates}
              toolStatuses={toolStatuses}
              activeTool={activeTool}
              expandedSystemKeys={expandedSystemKeys}
              onSelectTool={handleToolSelect}
              onToggleSystem={handleSystemToggle}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
