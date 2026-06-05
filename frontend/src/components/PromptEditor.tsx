/* PromptEditor — extracted from CommandCenter (Phase 13.3)
   Renders the prompt editing panel with tool/model selection and approve button.
*/

import { useRef, useEffect } from 'react';
import type { CliToolStatus } from '../types';

/* ── Exported constants ──────────────────────────────────────────────────── */

export type CliToolKey = 'codex' | 'aider' | 'claude' | 'gemini' | 'qwen' | 'deepseek' | 'copilot';

export const CLI_TOOL_KEYS: CliToolKey[] = ['codex', 'aider', 'claude', 'gemini', 'qwen', 'deepseek', 'copilot'];

export const CLI_DISPLAY: Record<CliToolKey, string> = {
  codex:    'OpenAI Codex',
  aider:    'Aider',
  claude:   'Claude Code',
  gemini:   'Gemini CLI',
  qwen:     'Qwen Coder',
  deepseek: 'DeepSeek',
  copilot:  'GitHub Copilot',
};

export const CLI_ICON: Record<CliToolKey, string> = {
  codex:    '✦',
  aider:    '⌬',
  claude:   '◈',
  gemini:   '◆',
  qwen:     '◇',
  deepseek: '◎',
  copilot:  '⬡',
};

/* ── Props ───────────────────────────────────────────────────────────────── */

export interface PromptEditorProps {
  content: string;
  isLoading: boolean;
  pipelineStatus: string;
  iteration: number;
  selectedTool: CliToolKey;
  selectedModel: string;
  availableModels: string[];
  toolStatuses: CliToolStatus[];
  onContentChange: (v: string) => void;
  onApprove: () => void;
  onToolSelect: (key: CliToolKey) => void;
  onModelSelect: (model: string) => void;
  promptGenFailed: boolean;
  promptGenError: string;
  onRetryPromptGenerator: () => void;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export default function PromptEditor({
  content,
  isLoading,
  pipelineStatus,
  iteration,
  selectedTool,
  selectedModel,
  availableModels,
  toolStatuses,
  onContentChange,
  onApprove,
  onToolSelect,
  onModelSelect,
  promptGenFailed,
  promptGenError,
  onRetryPromptGenerator,
}: PromptEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [content]);

  const isHitlGate = pipelineStatus === 'HITL_PROMPT_REVIEW';
  const isGenerating = pipelineStatus === 'PROMPT_GENERATION' || pipelineStatus === 'STORY_PROMPT_GENERATION';
  const hasContent = !!content.trim();

  return (
    <div className="flex flex-col rounded-xl border border-[var(--border-glass)] bg-[var(--bg-secondary)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border-glass)]">
        <span className="text-sm font-semibold text-white">Prompt</span>
        {iteration > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono">
            iter {iteration}
          </span>
        )}
        <div className="flex-1" />

        {/* Tool selector */}
        <select
          value={selectedTool}
          onChange={(e) => onToolSelect(e.target.value as CliToolKey)}
          className="rounded px-2 py-1 bg-slate-800 border border-white/10 text-white/80 text-xs"
        >
          {CLI_TOOL_KEYS.filter((k) => {
            const ts = toolStatuses.find((t) => t.key === k);
            return !ts || ts.available;
          }).map((k) => (
            <option key={k} value={k}>{CLI_DISPLAY[k]}</option>
          ))}
        </select>

        {/* Model selector */}
        <select
          value={selectedModel}
          onChange={(e) => onModelSelect(e.target.value)}
          className="rounded px-2 py-1 bg-slate-800 border border-white/10 text-white/80 text-xs max-w-[160px]"
        >
          {availableModels.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      {/* Editor area */}
      <div className="flex-1 min-h-0 p-4">
        {isGenerating && !hasContent && (
          <div className="flex items-center gap-2 text-sm text-slate-400 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce" />
            Generating prompt…
          </div>
        )}
        {promptGenFailed && (
          <div className="mb-3 px-3 py-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
            <span className="flex-1">Prompt generation failed{promptGenError ? `: ${promptGenError}` : ''}</span>
            <button
              onClick={onRetryPromptGenerator}
              disabled={isLoading}
              className="px-3 py-1 rounded-lg text-xs font-semibold bg-rose-500 text-white hover:bg-rose-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              Retry
            </button>
          </div>
        )}
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          placeholder="Prompt will appear here when generated…"
          className="w-full min-h-[120px] max-h-[400px] bg-transparent text-sm text-white/90 placeholder:text-white/20 resize-none focus:outline-none font-mono leading-relaxed"
          readOnly={!isHitlGate}
        />
      </div>

      {/* Footer with approve */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-t border-[var(--border-glass)]">
        <div className="flex-1" />
        <button
          onClick={onApprove}
          disabled={isLoading || !isHitlGate || !hasContent}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Approve & Generate
        </button>
      </div>
    </div>
  );
}
