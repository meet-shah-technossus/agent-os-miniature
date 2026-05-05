/* useAgentTerminals — Phase 7
   Maintains a per-agent ring buffer of terminal output lines by
   opening a dedicated second WebSocket connection that filters exclusively
   for channel=terminal_output messages.
*/

import { useEffect, useState } from 'react';
import type { AgentTerminalState, TerminalLine, TerminalLineStyle } from '../types';
import { PIPELINE_POSTS } from '../types';

// ─── Constants ────────────────────────────────────────────────────────────────

export const RING_BUFFER_SIZE = 300;

/** Maps PIPELINE_POST keys → backend sender names */
const POST_TO_SENDER: Record<string, string> = {
  MODULE_MAKER:      'module_maker',
  PROMPT_GENERATOR:  'prompt_generator',
  CODE_GENERATOR:    'code_generator',
  CODE_REVIEWER:     'code_reviewer',
};

/** Pretty display names for each post */
export const POST_DISPLAY_NAME: Record<string, string> = {
  MODULE_MAKER:      'Module Maker',
  PROMPT_GENERATOR:  'Prompt Generator',
  CODE_GENERATOR:    'Code Generator',
  CODE_REVIEWER:     'Code Reviewer',
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

let _lineId = 0;

function nextId(): number {
  return ++_lineId;
}

/**
 * Infers visual style of a terminal line from its text content.
 * - `reasoning` → dim cyan  (lines that look like AI internal monologue)
 * - `file_write` → green    (file creation / writing ops)
 * - `error`      → red      (errors, warnings, failures)
 * - `normal`     → white    (everything else)
 */
function classifyLine(text: string, stream: string): TerminalLineStyle {
  if (stream === 'stderr') return 'error';
  const t = text.trim();
  if (
    t.startsWith('>') ||
    /^(thinking|reasoning|i need to|let me|step \d+[:.)]|first[,:]|next[,:]|to accomplish)/i.test(t)
  ) {
    return 'reasoning';
  }
  if (/\b(writ|creat|updat|generat|sav)(ing|ed|e)\b/i.test(t)) return 'file_write';
  if (/\b(error|fail|exception|traceback|invalid|warning|critical|fatal)\b/i.test(t)) return 'error';
  return 'normal';
}

function makeInitialStates(): Record<string, AgentTerminalState> {
  const states: Record<string, AgentTerminalState> = {};
  for (const post of PIPELINE_POSTS) {
    states[post] = {
      agentPost: post,
      senderName: POST_TO_SENDER[post],
      lines: [],
      status: 'idle',
      model: null,
      currentModuleId: null,
      currentIteration: 0,
      sessionStartedAt: null,
      sessionEndedAt: null,
      lastExitCode: null,
      sessionCount: 0,
    };
  }
  return states;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAgentTerminals() {
  const [states, setStates] = useState<Record<string, AgentTerminalState>>(makeInitialStates);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (ev: MessageEvent<string>) => {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const msg: any = JSON.parse(ev.data);
        if (msg.channel !== 'terminal_output') return;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const payload: Record<string, any> = msg.payload ?? {};
        const eventType: string = payload.event_type ?? '';
        const agentPost: string = payload.agent_post ?? '';
        const sessionId: string = payload.session_id ?? '';
        const timestamp: string = msg.timestamp ?? new Date().toISOString();

        setStates((prev) => {
          const agentState = prev[agentPost];
          if (!agentState) return prev; // unknown post, ignore

          // ── session_start ────────────────────────────────────────────────
          if (eventType === 'session_start') {
            const model: string | null = payload.model ?? null;
            const moduleId: string | null = payload.module_id ?? null;
            const iteration: number = payload.iteration ?? 0;
            const sessionNum = agentState.sessionCount + 1;

            const marker: TerminalLine = {
              id: nextId(),
              timestamp,
              eventType: 'session_start',
              text: [
                `── Session ${sessionNum}`,
                model ? `  model: ${model}` : '',
                moduleId ? `  module: ${moduleId} iter ${iteration}` : '',
                '──',
              ]
                .filter(Boolean)
                .join('  '),
              stream: null,
              style: 'normal',
              sessionId,
            };

            return {
              ...prev,
              [agentPost]: {
                ...agentState,
                lines: [...agentState.lines, marker].slice(-RING_BUFFER_SIZE),
                status: 'running',
                model,
                currentModuleId: moduleId,
                currentIteration: iteration,
                sessionStartedAt: timestamp,
                sessionEndedAt: null,
                lastExitCode: null,
                sessionCount: sessionNum,
              },
            };
          }

          // ── session_end ──────────────────────────────────────────────────
          if (eventType === 'session_end') {
            const exitCode: number = payload.exit_code ?? 0;
            const marker: TerminalLine = {
              id: nextId(),
              timestamp,
              eventType: 'session_end',
              text: `── Session ended  exit ${exitCode} ──`,
              stream: null,
              style: exitCode !== 0 ? 'error' : 'normal',
              sessionId,
            };

            return {
              ...prev,
              [agentPost]: {
                ...agentState,
                lines: [...agentState.lines, marker].slice(-RING_BUFFER_SIZE),
                status: exitCode !== 0 ? 'error' : 'done',
                sessionEndedAt: timestamp,
                lastExitCode: exitCode,
              },
            };
          }

          // ── line ─────────────────────────────────────────────────────────
          if (eventType === 'line') {
            const text: string = payload.line ?? '';
            const stream: 'stdout' | 'stderr' = payload.stream === 'stderr' ? 'stderr' : 'stdout';
            const moduleId: string | null = payload.module_id ?? null;
            const iteration: number = payload.iteration ?? 0;

            const line: TerminalLine = {
              id: nextId(),
              timestamp,
              eventType: 'line',
              text,
              stream,
              style: classifyLine(text, stream),
              sessionId,
            };

            return {
              ...prev,
              [agentPost]: {
                ...agentState,
                lines: [...agentState.lines, line].slice(-RING_BUFFER_SIZE),
                // Promote idle → running if we receive lines before session_start
                status: agentState.status === 'idle' ? 'running' : agentState.status,
                currentModuleId: moduleId ?? agentState.currentModuleId,
                currentIteration: iteration || agentState.currentIteration,
              },
            };
          }

          return prev;
        });
      } catch {
        // ignore malformed JSON
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  const activeAgentPosts = Object.values(states)
    .filter((s) => s.status === 'running')
    .map((s) => s.agentPost);

  return { states, connected, activeAgentPosts };
}
