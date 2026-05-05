/* Agents Management Page
   Layout:
   ├── Left  : agent roster cards + "Create Custom Agent"
   └── Right : selected agent
       ├── File pills (Soul / Skills / Tools / Ceiling / Brain) — click to open edit modal
       ├── Read-only rendered preview of the active file
       └── Post Assignments + Model Routing panels
*/

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Editor from '@monaco-editor/react';
import { api } from '../hooks/api';
import type { AgentMeta, AgentDetail, PipelinePost } from '../types';
import { AGENT_FILES, PIPELINE_POSTS } from '../types';
import CreateAgentWizard from './CreateAgentWizard';

// ─── Markdown renderer ────────────────────────────────────────────────────────

function renderMarkdown(md: string): string {
  return md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^#{3} (.+)$/gm, '<h3 class="text-sm font-semibold mt-3 mb-1 text-indigo-300">$1</h3>')
    .replace(/^#{2} (.+)$/gm, '<h2 class="text-base font-bold mt-4 mb-2 text-indigo-200">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold mt-5 mb-2 text-white">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em class="italic text-slate-300">$1</em>')
    .replace(/`(.+?)`/g, '<code class="bg-black/30 rounded px-1 text-emerald-300 text-xs font-mono">$1</code>')
    .replace(/^[-*] (.+)$/gm, '<li class="ml-4 list-disc text-slate-300 text-sm">$1</li>')
    .replace(/^---$/gm, '<hr class="border-slate-700 my-3" />')
    .replace(/\n{2,}/g, '</p><p class="mb-2 text-slate-300 text-sm">');
}

// ─── Ceiling structured renderer ─────────────────────────────────────────────

const CEILING_STYLES: Record<string, { color: string; bg: string; dot: string; border: string }> = {
  'Can Do':        { color: 'text-green-400',  bg: 'bg-green-500/10',  dot: 'bg-green-400',  border: 'border-green-500/30' },
  'Must Escalate': { color: 'text-yellow-400', bg: 'bg-yellow-500/10', dot: 'bg-yellow-400', border: 'border-yellow-500/30' },
  'Must Not Do':   { color: 'text-red-400',    bg: 'bg-red-500/10',    dot: 'bg-red-400',    border: 'border-red-500/30' },
};
const DEFAULT_CEILING_STYLE = { color: 'text-slate-300', bg: 'bg-white/5', dot: 'bg-slate-400', border: 'border-[var(--border-glass)]' };

function CeilingPreview({ content }: { content: string }) {
  const lines = content.split('\n');
  const sections: { heading: string; items: string[] }[] = [];
  let cur: { heading: string; items: string[] } | null = null;
  for (const line of lines) {
    if (line.startsWith('## ')) {
      if (cur) sections.push(cur);
      cur = { heading: line.slice(3).trim(), items: [] };
    } else if (cur && line.trim().startsWith('- ')) {
      cur.items.push(line.trim().slice(2));
    }
  }
  if (cur) sections.push(cur);
  if (!sections.length)
    return <pre className="text-xs text-slate-400 whitespace-pre-wrap leading-relaxed">{content}</pre>;
  return (
    <div className="space-y-3">
      {sections.map((sec) => {
        const s = CEILING_STYLES[sec.heading] ?? DEFAULT_CEILING_STYLE;
        return (
          <div key={sec.heading} className={`rounded-lg border p-3 ${s.bg} ${s.border}`}>
            <h3 className={`text-xs font-semibold mb-2 flex items-center gap-2 ${s.color}`}>
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dot}`} />
              {sec.heading}
            </h3>
            <ul className="space-y-1">
              {sec.items.length === 0
                ? <li className="text-xs text-slate-500 italic">No entries</li>
                : sec.items.map((item, i) => (
                    <li key={i} className="text-xs text-slate-300 flex gap-2">
                      <span className="text-slate-500 shrink-0">•</span>{item}
                    </li>
                  ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

// ─── Brain preview (read-only, used in main panel) ────────────────────────────

function BrainPreview({ content }: { content: string }) {
  const entries = content.split(/(?=^## )/m).filter((e) => e.trim());
  if (entries.length === 0)
    return <p className="text-sm text-slate-500 italic">Brain is empty — memories accumulate as the pipeline runs.</p>;
  return (
    <div className="space-y-2">
      {entries.map((entry, i) => (
        <div key={i} className="rounded-lg bg-white/5 border border-[var(--border-glass)] p-3">
          <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono leading-relaxed">{entry.trim()}</pre>
        </div>
      ))}
    </div>
  );
}

// ─── File Edit Modal ──────────────────────────────────────────────────────────

interface FileEditModalProps {
  agentName: string;
  fileName: string;
  initialContent: string;
  onSaved: (content: string) => void;
  onClearBrain: () => Promise<void>;
  onClose: () => void;
}

function FileEditModal({
  agentName, fileName, initialContent, onSaved, onClearBrain, onClose,
}: FileEditModalProps) {
  const isBrain = fileName === 'brain';
  const isCeiling = fileName === 'ceiling';
  const [content, setContent] = useState(initialContent);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [toast, setToast] = useState('');
  const dirty = content !== initialContent;

  // Esc closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 2500); };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateAgentFile(agentName, fileName, content);
      onSaved(content);
      showToast('Saved ✓');
    } catch {
      showToast('Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleClearBrain = async () => {
    if (!confirm(`Clear the brain of "${agentName}"? This cannot be undone.`)) return;
    setClearing(true);
    try {
      await onClearBrain();
      onClose();
    } catch {
      showToast('Clear failed');
    } finally {
      setClearing(false);
    }
  };

  // Brain entries for read-only display
  const brainEntries = initialContent.split(/(?=^## )/m).filter((e) => e.trim());

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 10 }}
        transition={{ duration: 0.15 }}
        className="w-full max-w-4xl flex flex-col rounded-2xl border border-[var(--border-glass)] bg-[var(--bg-card)] shadow-2xl overflow-hidden"
        style={{ height: '82vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border-glass)] shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white capitalize">{fileName}</span>
            <span className="text-xs text-slate-500 font-mono">— {agentName}</span>
            {!isBrain && dirty && <span className="text-xs text-amber-400">• unsaved changes</span>}
          </div>
          <div className="flex items-center gap-2">
            {toast && <span className="text-xs text-green-400">{toast}</span>}
            {isBrain ? (
              <button
                onClick={handleClearBrain}
                disabled={clearing}
                className="px-3 py-1.5 text-xs rounded-lg bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 disabled:opacity-50 transition-colors"
              >
                {clearing ? 'Clearing…' : 'Clear Brain'}
              </button>
            ) : (
              <>
                <button
                  onClick={() => setContent(initialContent)}
                  disabled={!dirty}
                  className="px-3 py-1.5 text-xs rounded-lg border border-[var(--border-glass)] text-slate-400 hover:text-white disabled:opacity-30 transition-colors"
                >
                  Revert
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving || !dirty}
                  className="px-3 py-1.5 text-xs rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 transition-colors"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </>
            )}
            <button
              onClick={onClose}
              className="ml-1 w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors text-sm"
            >
              ✕
            </button>
          </div>
        </div>

        {/* ── Content ────────────────────────────────────────────────────── */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {isBrain ? (
            <div className="h-full overflow-y-auto p-5 space-y-2">
              <p className="text-xs text-slate-500 mb-3">
                {brainEntries.length} memory entr{brainEntries.length === 1 ? 'y' : 'ies'} — read-only
              </p>
              {brainEntries.length === 0
                ? <p className="text-sm text-slate-500 italic">Brain is empty.</p>
                : brainEntries.map((entry, i) => (
                    <div key={i} className="rounded-lg bg-white/5 border border-[var(--border-glass)] p-3">
                      <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono leading-relaxed">
                        {entry.trim()}
                      </pre>
                    </div>
                  ))}
            </div>
          ) : (
            <Editor
              height="100%"
              defaultLanguage="markdown"
              value={content}
              onChange={(v) => setContent(v ?? '')}
              theme="vs-dark"
              options={{
                fontSize: 13,
                minimap: { enabled: false },
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                padding: { top: 14, bottom: 14 },
                renderLineHighlight: 'line',
                scrollbar: { useShadows: false, verticalScrollbarSize: 8, horizontalScrollbarSize: 6 },
              }}
            />
          )}
        </div>

        {/* ── Footer hint ────────────────────────────────────────────────── */}
        {!isBrain && (
          <div className="px-5 py-2 border-t border-[var(--border-glass)] shrink-0 flex items-center gap-4">
            <span className="text-[11px] text-slate-600">Press Esc to close</span>
            {isCeiling && (
              <span className="text-[11px] text-slate-600">
                Use <code className="text-emerald-400 font-mono">## Can Do</code>,{' '}
                <code className="text-emerald-400 font-mono">## Must Escalate</code>,{' '}
                <code className="text-emerald-400 font-mono">## Must Not Do</code> sections
              </span>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}

// ─── Agent detail panel ───────────────────────────────────────────────────────

interface AgentDetailPanelProps {
  meta: AgentMeta;
  detail: AgentDetail | null;
  loadingDetail: boolean;
  onFileSaved: (file: string, content: string) => void;
  onClearBrain: () => Promise<void>;
}

function AgentDetailPanel({
  meta, detail, loadingDetail, onFileSaved, onClearBrain,
}: AgentDetailPanelProps) {
  // files_present uses 'soul.md' keys; AGENT_FILES uses 'soul' — normalise with fp()
  const fp = (f: string) => f.endsWith('.md') ? f : f + '.md';
  const defaultFile = AGENT_FILES.find((f) => meta.files_present.includes(fp(f))) ?? '';
  const [previewFile, setPreviewFile] = useState<string>(defaultFile);
  const [modalFile, setModalFile] = useState<string | null>(null);

  // Reset when agent changes
  useEffect(() => {
    setPreviewFile(AGENT_FILES.find((f) => meta.files_present.includes(fp(f))) ?? '');
    setModalFile(null);
  }, [meta.name]);

  const handlePillClick = (f: string) => {
    setPreviewFile(f);
    setModalFile(f);
  };

  const previewContent = detail?.files[fp(previewFile)] ?? '';

  return (
    <div className="flex flex-col h-full" style={{ minHeight: '22rem' }}>
      {/* ── File pills ──────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2 mb-4 shrink-0">
        {AGENT_FILES.map((f) => {
          if (!meta.files_present.includes(fp(f))) return null;
          const active = previewFile === f;
          return (
            <button
              key={f}
              onClick={() => handlePillClick(f)}
              className={`px-3.5 py-1.5 text-xs capitalize rounded-full border font-medium transition-all ${
                active
                  ? 'bg-indigo-500/20 border-indigo-500/60 text-indigo-200 shadow-[0_0_0_1px_rgba(99,102,241,0.3)]'
                  : 'border-[var(--border-glass)] text-slate-400 hover:text-white hover:border-indigo-500/40 hover:bg-white/5'
              }`}
            >
              {f}
            </button>
          );
        })}
        <span className="text-[10px] text-slate-600 self-center ml-1">click to view &amp; edit</span>
      </div>

      {/* ── Read-only preview ───────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-[var(--border-glass)] bg-[var(--bg-primary)] p-4">
        {loadingDetail ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-5 h-5 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
          </div>
        ) : !detail ? (
          <p className="text-sm text-slate-500 italic">Loading…</p>
        ) : !previewFile ? (
          <p className="text-sm text-slate-500 italic">No files found.</p>
        ) : previewFile === 'ceiling' ? (
          <CeilingPreview content={previewContent} />
        ) : previewFile === 'brain' ? (
          <BrainPreview content={previewContent} />
        ) : (
          <div
            className="prose-sm leading-relaxed"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(previewContent) }}
          />
        )}
      </div>

      {/* ── Edit modal ──────────────────────────────────────────────────── */}
      <AnimatePresence>
        {modalFile && detail && (
          <FileEditModal
            key={`${meta.name}-${modalFile}`}
            agentName={meta.name}
            fileName={modalFile}
            initialContent={detail.files[modalFile + '.md'] ?? ''}
            onSaved={(newContent) => {
              onFileSaved(modalFile, newContent);
              setModalFile(null);
            }}
            onClearBrain={async () => {
              await onClearBrain();
              setModalFile(null);
            }}
            onClose={() => setModalFile(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── FileBadge (on agent roster card) ────────────────────────────────────────

function FileBadge({ name, present }: { name: string; present: boolean }) {
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-mono uppercase ${
        present
          ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
          : 'bg-white/5 text-slate-600 border border-white/5'
      }`}
    >
      {name}
    </span>
  );
}

// ─── Post assignment + model routing panel ────────────────────────────────────

interface AssignmentPanelProps {
  agents: AgentMeta[];
  registry: Record<string, string>;
  modelRouting: Record<string, string>;
  onRegistryChange: (post: PipelinePost, agentName: string) => void;
  onModelChange: (post: PipelinePost, model: string) => void;
  onSaveRegistry: () => void;
  onSaveModels: () => void;
  savingRegistry: boolean;
  savingModels: boolean;
}

function AssignmentPanel({
  agents, registry, modelRouting,
  onRegistryChange, onModelChange,
  onSaveRegistry, onSaveModels,
  savingRegistry, savingModels,
}: AssignmentPanelProps) {
  return (
    <div className="mt-5 space-y-4">
      {/* Post assignments */}
      <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-white">Post Assignments</h3>
          <button
            onClick={onSaveRegistry}
            disabled={savingRegistry}
            className="px-3 py-1 text-xs rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 transition-colors"
          >
            {savingRegistry ? 'Saving…' : 'Save'}
          </button>
        </div>
        <p className="text-[11px] text-slate-500 mb-3">
          Each post is a slot in the pipeline. Assign any agent to handle it. On pipeline reset, model routing reverts to defaults but assignments are preserved.
        </p>
        <div className="space-y-2">
          {PIPELINE_POSTS.map((post) => (
            <div key={post} className="flex items-center gap-3">
              <span className="text-xs text-slate-400 font-mono w-44 shrink-0">{post}</span>
              <select
                value={registry[post] ?? ''}
                onChange={(e) => onRegistryChange(post, e.target.value)}
                className="flex-1 bg-[var(--bg-primary)] border border-[var(--border-glass)] rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:border-indigo-500 transition-colors"
              >
                <option value="">(none)</option>
                {agents.map((a) => (
                  <option key={a.name} value={a.name}>{a.display_name}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      {/* Model routing */}
      <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-white">Model Routing</h3>
          <button
            onClick={onSaveModels}
            disabled={savingModels}
            className="px-3 py-1 text-xs rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 transition-colors"
          >
            {savingModels ? 'Saving…' : 'Save'}
          </button>
        </div>
        <p className="text-[11px] text-slate-500 mb-3">
          Set which OpenAI model each pipeline post uses. Saved to config.yaml and database.{' '}
          <span className="text-amber-400">Pipeline reset reverts all models to defaults.</span>
        </p>
        <div className="space-y-2">
          {PIPELINE_POSTS.map((post) => (
            <div key={post} className="flex items-center gap-3">
              <span className="text-xs text-slate-400 font-mono w-44 shrink-0">{post}</span>
              <input
                type="text"
                value={modelRouting[post] ?? ''}
                onChange={(e) => onModelChange(post, e.target.value)}
                placeholder="e.g. gpt-4.1-mini"
                className="flex-1 bg-[var(--bg-primary)] border border-[var(--border-glass)] rounded-lg px-2 py-1.5 text-sm text-white placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors font-mono"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Main page component ──────────────────────────────────────────────────────

export default function AgentsView() {
  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [registry, setRegistry] = useState<Record<string, string>>({});
  const [savingRegistry, setSavingRegistry] = useState(false);
  const [modelRouting, setModelRouting] = useState<Record<string, string>>({});
  const [savingModels, setSavingModels] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  // ── initial load ────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoadingAgents(true);

    Promise.all([api.listAgents(), api.getRegistry(), api.getModelRouting()])
      .then(([listRes, regRes, routingRes]) => {
        if (cancelled) return;
        setAgents(listRes.agents);
        setRegistry(regRes.mapping);
        setModelRouting(routingRes.model_routing);
        if (listRes.agents.length > 0) setSelectedName(listRes.agents[0].name);
      })
      .catch(() => { if (!cancelled) setErrorMsg('Failed to load agents'); })
      .finally(() => { if (!cancelled) setLoadingAgents(false); });

    return () => { cancelled = true; };
  }, []);

  // ── load agent detail when selection changes ────────────────────────────────
  useEffect(() => {
    if (!selectedName) return;
    let cancelled = false;
    setLoadingDetail(true);
    setDetail(null);

    api.getAgent(selectedName)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch(() => { if (!cancelled) setErrorMsg('Failed to load agent details'); })
      .finally(() => { if (!cancelled) setLoadingDetail(false); });

    return () => { cancelled = true; };
  }, [selectedName]);

  // ── file saved: patch local detail ─────────────────────────────────────────
  const handleFileSaved = useCallback((file: string, content: string) => {
    setDetail((prev) => prev ? { ...prev, files: { ...prev.files, [file]: content } } : prev);
  }, []);

  // ── clear brain ─────────────────────────────────────────────────────────────
  const handleClearBrain = useCallback(async () => {
    if (!selectedName) return;
    await api.clearAgentBrain(selectedName);
    const updated = await api.getAgent(selectedName);
    setDetail(updated);
  }, [selectedName]);

  // ── registry ────────────────────────────────────────────────────────────────
  const handleRegistryChange = (post: PipelinePost, agentName: string) =>
    setRegistry((prev) => ({ ...prev, [post]: agentName }));

  const handleSaveRegistry = async () => {
    setSavingRegistry(true);
    try { await api.updateRegistry(registry); }
    catch { setErrorMsg('Failed to save post assignments'); }
    finally { setSavingRegistry(false); }
  };

  // ── model routing ───────────────────────────────────────────────────────────
  const handleModelChange = (post: PipelinePost, model: string) =>
    setModelRouting((prev) => ({ ...prev, [post]: model }));

  const handleSaveModels = async () => {
    setSavingModels(true);
    try {
      const res = await api.updateModelRouting(modelRouting);
      setModelRouting(res.model_routing);
    } catch {
      setErrorMsg('Failed to save model routing');
    } finally {
      setSavingModels(false);
    }
  };

  const selectedMeta = agents.find((a) => a.name === selectedName) ?? null;

  return (
    <div className="h-full flex flex-col">
      {/* Page header */}
      <div className="mb-5 shrink-0">
        <h2 className="text-2xl font-bold text-white">Agents</h2>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          Select an agent, then click any configuration pill to view and edit it.
        </p>
      </div>

      {/* Error banner */}
      {errorMsg && (
        <div className="mb-4 shrink-0 px-4 py-2 rounded-lg bg-red-500/10 text-red-400 border border-red-500/30 text-sm flex items-center justify-between">
          {errorMsg}
          <button onClick={() => setErrorMsg('')} className="text-xs underline ml-3">dismiss</button>
        </div>
      )}

      {/* Two-panel layout */}
      <div className="flex gap-5 flex-1 min-h-0 overflow-hidden">
        {/* ── Left: roster ─────────────────────────────────────────── */}
        <div className="w-64 shrink-0 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {loadingAgents ? (
              <div className="flex justify-center pt-10">
                <div className="w-6 h-6 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
              </div>
            ) : agents.length === 0 ? (
              <p className="text-sm text-slate-500 italic text-center pt-8">No agents found.</p>
            ) : (
              agents.map((agent) => (
                <motion.button
                  key={agent.name}
                  onClick={() => setSelectedName(agent.name)}
                  whileHover={{ x: 2 }}
                  className={`w-full text-left p-3 rounded-xl border transition-colors ${
                    selectedName === agent.name
                      ? 'border-indigo-500/50 bg-indigo-500/10'
                      : 'border-[var(--border-glass)] bg-[var(--bg-card)] hover:border-indigo-500/30 hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-start justify-between mb-1">
                    <span className="font-semibold text-sm text-white truncate mr-1">{agent.display_name}</span>
                    {agent.is_custom && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 shrink-0">
                        custom
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 font-mono mb-2 truncate">{agent.name}</div>
                  {agent.post_assignment && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                      {agent.post_assignment}
                    </span>
                  )}
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {AGENT_FILES.map((f) => (
                      <FileBadge key={f} name={f} present={agent.files_present.includes(f)} />
                    ))}
                  </div>
                </motion.button>
              ))
            )}
          </div>

          <button
            onClick={() => setShowWizard(true)}
            className="mt-3 shrink-0 w-full py-2 rounded-xl border border-dashed border-[var(--border-glass)] text-xs text-slate-500 hover:text-indigo-300 hover:border-indigo-500/50 transition-colors"
          >
            + Create Custom Agent
          </button>
        </div>

        {/* ── Right: detail ────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col overflow-y-auto min-w-0">
          {!selectedMeta ? (
            <div className="flex items-center justify-center flex-1 text-slate-500 text-sm">
              Select an agent
            </div>
          ) : (
            <>
              {/* Agent name header */}
              <div className="mb-4 shrink-0 px-1">
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-bold text-white">{selectedMeta.display_name}</h3>
                  {selectedMeta.is_builtin && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">built-in</span>
                  )}
                  {selectedMeta.is_custom && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">custom</span>
                  )}
                </div>
                <div className="text-xs text-slate-500 font-mono mt-0.5">{selectedMeta.name}</div>
              </div>

              {/* Detail panel (pills + preview + modal) */}
              <div className="rounded-xl border border-[var(--border-glass)] bg-[var(--bg-card)] p-4 shrink-0" style={{ minHeight: '22rem' }}>
                {selectedMeta.files_present.length === 0
                  ? <p className="text-sm text-slate-500 italic">No files found for this agent.</p>
                  : (
                    <AgentDetailPanel
                      meta={selectedMeta}
                      detail={detail}
                      loadingDetail={loadingDetail}
                      onFileSaved={handleFileSaved}
                      onClearBrain={handleClearBrain}
                    />
                  )}
              </div>

              {/* Assignment + model routing */}
              <AssignmentPanel
                agents={agents}
                registry={registry}
                modelRouting={modelRouting}
                onRegistryChange={handleRegistryChange}
                onModelChange={handleModelChange}
                onSaveRegistry={handleSaveRegistry}
                onSaveModels={handleSaveModels}
                savingRegistry={savingRegistry}
                savingModels={savingModels}
              />
            </>
          )}
        </div>
      </div>

      {/* Create Agent Wizard overlay */}
      <AnimatePresence>
        {showWizard && (
          <CreateAgentWizard
            key="create-agent-wizard"
            onDone={(agentName) => {
              setShowWizard(false);
              api.listAgents().then((res) => {
                setAgents(res.agents);
                setSelectedName(agentName);
              }).catch(() => {});
            }}
            onCancel={() => setShowWizard(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
