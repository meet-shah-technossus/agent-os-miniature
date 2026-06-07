/* ReviewViewer — extracted from CommandCenter (Phase 13.3)
   Renders the code-review JSON viewer with approve/edit/reset controls.
*/

import { useEffect, useRef } from 'react';
import Editor, { type Monaco } from '@monaco-editor/react';
import type { editor as MonacoEditor } from 'monaco-editor';

/* ── Props ───────────────────────────────────────────────────────────────── */

export interface ReviewViewerProps {
  content: string;
  iteration: number;
  pipelineStatus: string;
  isModified: boolean;
  isValidJson: boolean;
  onApprove: () => void;
  onMoveToNextStory: () => void;
  onReset: () => void;
  onContentChange: (v: string) => void;
  onRetryPR: () => void;
  onRetryCodeGenerator: () => void;
  isLoading: boolean;
  prFailed: boolean;
  prError: string;
  codeReviewFailed: boolean;
  codeReviewError: string;
  onRetryCodeReviewer: () => void;
  reviewJsonExists: boolean;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export default function ReviewViewer({
  content,
  iteration,
  pipelineStatus,
  isModified,
  isValidJson,
  onApprove,
  onMoveToNextStory,
  onReset,
  onContentChange,
  onRetryPR,
  onRetryCodeGenerator,
  isLoading,
  prFailed,
  prError,
  codeReviewFailed,
  codeReviewError,
  onRetryCodeReviewer,
  reviewJsonExists,
}: ReviewViewerProps) {
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  // Track the last externally-set content so we only push updates when it actually changes
  const lastExternalContent = useRef<string>('');

  const isReviewGate = pipelineStatus === 'HITL_REVIEW_DECISION';
  const isReviewing = pipelineStatus === 'CODE_REVIEW' || pipelineStatus === 'STORY_CODE_REVIEW';
  const isPRCreation = pipelineStatus === 'PR_CREATION' || pipelineStatus === 'STORY_PR_CREATION';
  const isStoryComplete = pipelineStatus === 'STORY_COMPLETE';

  // Push external content changes into the editor without resetting cursor position
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    if (content === lastExternalContent.current) return;
    lastExternalContent.current = content;
    const model = editor.getModel();
    if (!model) return;
    // Use pushEditOperations to replace content while preserving cursor / selection
    const fullRange = model.getFullModelRange();
    model.pushEditOperations(
      editor.getSelections() ?? [],
      [{ range: fullRange, text: content }],
      () => null,
    );
  }, [content]);

  // Sync readOnly state without re-mounting the editor
  useEffect(() => {
    editorRef.current?.updateOptions({
      readOnly: !isReviewGate,
      renderLineHighlight: isReviewGate ? 'line' : 'none',
    });
  }, [isReviewGate]);

  function handleEditorMount(editorInstance: MonacoEditor.IStandaloneCodeEditor, _monaco: Monaco) {
    editorRef.current = editorInstance;
    lastExternalContent.current = content;
  }

  return (
    <div className="flex flex-col rounded-xl border border-[var(--border-glass)] bg-[var(--bg-secondary)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border-glass)]">
        <span className="text-sm font-semibold text-white">Review</span>
        {iteration > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono">
            iter {iteration}
          </span>
        )}
        {isModified && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
            modified
          </span>
        )}
        {!isValidJson && content.trim() && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30">
            invalid JSON
          </span>
        )}
        <div className="flex-1" />
        {isModified && (
          <button
            onClick={onReset}
            className="text-[10px] text-slate-400 hover:text-white transition-colors"
          >
            Reset
          </button>
        )}
      </div>

      {/* Review content area */}
      <div className="flex-1 min-h-0">
        {isReviewing && !reviewJsonExists && (
          <div className="flex items-center gap-2 px-4 py-4 text-sm text-slate-400 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-bounce" />
            Running code review…
          </div>
        )}
        {isPRCreation && (
          <div className="flex items-center gap-2 px-4 py-4 text-sm text-slate-400 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" />
            Creating pull request…
          </div>
        )}
        {codeReviewFailed && (
          <div className="mx-4 mt-3 mb-1 px-3 py-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
            <span className="flex-1">Code review failed{codeReviewError ? `: ${codeReviewError}` : ''}</span>
            <button
              onClick={onRetryCodeReviewer}
              disabled={isLoading}
              className="px-3 py-1 rounded-lg text-xs font-semibold bg-rose-500 text-white hover:bg-rose-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              Retry
            </button>
          </div>
        )}
        {prFailed && (
          <div className="mx-4 mt-3 mb-1 px-3 py-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs flex items-center gap-2">
            <span className="flex-1">PR creation failed{prError ? `: ${prError}` : ''}</span>
            <button
              onClick={onRetryPR}
              disabled={isLoading}
              className="px-3 py-1 rounded-lg text-xs font-semibold bg-amber-500 text-white hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              Retry PR
            </button>
          </div>
        )}
        <Editor
          height="280px"
          language="json"
          defaultValue={content}
          theme="vs-dark"
          onMount={handleEditorMount}
          onChange={(v) => {
            const val = v ?? '';
            lastExternalContent.current = val;
            onContentChange(val);
          }}
          options={{
            readOnly: !isReviewGate,
            minimap: { enabled: false },
            wordWrap: 'on',
            scrollBeyondLastLine: false,
            fontSize: 12,
            lineNumbers: 'on',
            glyphMargin: false,
            folding: true,
            lineDecorationsWidth: 8,
            renderLineHighlight: isReviewGate ? 'line' : 'none',
            overviewRulerLanes: 0,
            scrollbar: { verticalScrollbarSize: 6 },
          }}
        />
      </div>

      {/* Footer with approve / next story */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-t border-[var(--border-glass)] flex-wrap">
        {isReviewGate && (
          <>
            <button
              onClick={onRetryCodeGenerator}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-600/80 text-white hover:bg-amber-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Retry Code Gen
            </button>
            <button
              onClick={onRetryCodeReviewer}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-600/80 text-white hover:bg-amber-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Retry Reviewer
            </button>
            <button
              onClick={onMoveToNextStory}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-600 text-white hover:bg-slate-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Skip Story →
            </button>
          </>
        )}
        {isStoryComplete && (
          <button
            onClick={onMoveToNextStory}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next Story →
          </button>
        )}
        <div className="flex-1" />
        {isModified && (
          <button
            onClick={onReset}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-700 text-white/70 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Reset
          </button>
        )}
        <button
          onClick={onApprove}
          disabled={isLoading || !isReviewGate || (!isValidJson && !!content.trim())}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Approve Review
        </button>
      </div>
    </div>
  );
}
