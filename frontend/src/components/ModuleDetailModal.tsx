/* Module Detail Modal — shows definition, prompts, reviews, iterations for a module */

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Editor from '@monaco-editor/react';
import { api } from '../hooks/api';
import type { ModuleDetail } from '../types';

type Tab = 'info' | 'definition' | 'prompts' | 'reviews' | 'iterations';

interface Props {
  moduleId: string | null;
  onClose: () => void;
}

const tabLabels: { key: Tab; label: string }[] = [
  { key: 'info', label: 'Info' },
  { key: 'definition', label: 'Definition' },
  { key: 'prompts', label: 'Prompts' },
  { key: 'reviews', label: 'Reviews' },
  { key: 'iterations', label: 'Iterations' },
];

const statusColor: Record<string, string> = {
  completed: 'text-green-400',
  in_progress: 'text-yellow-400',
  failed: 'text-red-400',
  pending: 'text-slate-400',
  passed: 'text-green-400',
};

export default function ModuleDetailModal({ moduleId, onClose }: Props) {
  const [detail, setDetail] = useState<ModuleDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('info');
  const [selectedPrompt, setSelectedPrompt] = useState(0);
  const [selectedReview, setSelectedReview] = useState(0);

  useEffect(() => {
    if (!moduleId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setError('');
    setTab('info');
    api
      .getModuleDetail(moduleId)
      .then((d) => {
        setDetail(d);
        setSelectedPrompt(0);
        setSelectedReview(0);
      })
      .catch(() => setError('Failed to load module details'))
      .finally(() => setLoading(false));
  }, [moduleId]);

  if (!moduleId) return null;

  return (
    <AnimatePresence>
      <motion.div
        key="overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          key="modal"
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          className="relative w-[90vw] max-w-4xl max-h-[85vh] overflow-hidden rounded-2xl border border-white/10 bg-[var(--bg-card)] shadow-2xl flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
            <h2 className="text-lg font-semibold truncate">
              {detail?.module.name || moduleId}
            </h2>
            <button
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-white/10 text-[var(--text-secondary)] transition-colors"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 6l8 8M14 6l-8 8" />
              </svg>
            </button>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 px-6 pt-3 pb-1 border-b border-white/10">
            {tabLabels.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  tab === t.key
                    ? 'bg-indigo-600 text-white'
                    : 'text-[var(--text-secondary)] hover:bg-white/10'
                }`}
              >
                {t.label}
                {t.key === 'prompts' && detail ? ` (${detail.prompts.length})` : ''}
                {t.key === 'reviews' && detail ? ` (${detail.reviews.length})` : ''}
                {t.key === 'iterations' && detail ? ` (${detail.iterations.length})` : ''}
              </button>
            ))}
          </div>

          {/* Body */}
          <div className="flex-1 overflow-auto p-6">
            {loading && (
              <div className="flex items-center justify-center h-40 text-[var(--text-secondary)]">
                Loading…
              </div>
            )}
            {error && (
              <div className="flex items-center justify-center h-40 text-red-400">
                {error}
              </div>
            )}
            {!loading && !error && detail && (
              <>
                {/* Info Tab */}
                {tab === 'info' && (
                  <div className="space-y-3">
                    <Row label="Module ID" value={detail.module.id} />
                    <Row label="Name" value={detail.module.name} />
                    <Row label="Feature" value={detail.module.feature_name} />
                    <Row label="Status">
                      <span className={statusColor[detail.module.status] || ''}>
                        {detail.module.status}
                      </span>
                    </Row>
                    <Row label="Version" value={String(detail.module.version)} />
                    <Row label="Execution Order" value={String(detail.module.execution_order)} />
                    <Row
                      label="Dependencies"
                      value={
                        detail.module.dependency_ids.length
                          ? detail.module.dependency_ids.join(', ')
                          : 'None'
                      }
                    />
                    {detail.module.pr_number && (
                      <Row label="Pull Request">
                        <a
                          href={detail.module.pr_url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-purple-400 hover:underline"
                        >
                          PR #{detail.module.pr_number}
                        </a>
                      </Row>
                    )}
                    <Row label="Created" value={fmtDate(detail.module.created_at)} />
                    <Row label="Updated" value={fmtDate(detail.module.updated_at)} />
                  </div>
                )}

                {/* Definition Tab */}
                {tab === 'definition' && (
                  detail.definition ? (
                    <Editor
                      height="55vh"
                      defaultLanguage="json"
                      value={JSON.stringify(detail.definition, null, 2)}
                      theme="vs-dark"
                      options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }}
                    />
                  ) : (
                    <p className="text-[var(--text-secondary)] text-center mt-10">
                      No definition file found. Run Module Maker to generate.
                    </p>
                  )
                )}

                {/* Prompts Tab */}
                {tab === 'prompts' && (
                  detail.prompts.length ? (
                    <div className="space-y-3">
                      <div className="flex gap-2 flex-wrap">
                        {detail.prompts.map((p, i) => (
                          <button
                            key={p.iteration}
                            onClick={() => setSelectedPrompt(i)}
                            className={`px-3 py-1 rounded-md text-sm ${
                              selectedPrompt === i
                                ? 'bg-indigo-600 text-white'
                                : 'bg-white/5 text-[var(--text-secondary)] hover:bg-white/10'
                            }`}
                          >
                            Iteration {p.iteration}
                          </button>
                        ))}
                      </div>
                      <pre className="whitespace-pre-wrap text-sm bg-black/30 rounded-lg p-4 overflow-auto max-h-[50vh] leading-relaxed">
                        {detail.prompts[selectedPrompt]?.content}
                      </pre>
                    </div>
                  ) : (
                    <p className="text-[var(--text-secondary)] text-center mt-10">
                      No prompts generated yet.
                    </p>
                  )
                )}

                {/* Reviews Tab */}
                {tab === 'reviews' && (
                  detail.reviews.length ? (
                    <div className="space-y-3">
                      <div className="flex gap-2 flex-wrap">
                        {detail.reviews.map((r, i) => (
                          <button
                            key={r.iteration}
                            onClick={() => setSelectedReview(i)}
                            className={`px-3 py-1 rounded-md text-sm ${
                              selectedReview === i
                                ? 'bg-indigo-600 text-white'
                                : 'bg-white/5 text-[var(--text-secondary)] hover:bg-white/10'
                            }`}
                          >
                            Iteration {r.iteration}
                          </button>
                        ))}
                      </div>
                      <Editor
                        height="50vh"
                        defaultLanguage="json"
                        value={JSON.stringify(detail.reviews[selectedReview]?.content, null, 2)}
                        theme="vs-dark"
                        options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }}
                      />
                    </div>
                  ) : (
                    <p className="text-[var(--text-secondary)] text-center mt-10">
                      No reviews yet.
                    </p>
                  )
                )}

                {/* Iterations Tab */}
                {tab === 'iterations' && (
                  detail.iterations.length ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-white/10 text-left text-[var(--text-secondary)]">
                            <th className="py-2 pr-4">#</th>
                            <th className="py-2 pr-4">Status</th>
                            <th className="py-2 pr-4">Tokens</th>
                            <th className="py-2 pr-4">Started</th>
                            <th className="py-2">Completed</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.iterations.map((it) => (
                            <tr key={it.iteration_number} className="border-b border-white/5">
                              <td className="py-2 pr-4 font-mono">{it.iteration_number}</td>
                              <td className={`py-2 pr-4 ${statusColor[it.status] || ''}`}>
                                {it.status}
                              </td>
                              <td className="py-2 pr-4 font-mono">
                                {it.token_usage.toLocaleString()}
                              </td>
                              <td className="py-2 pr-4">{fmtDate(it.started_at)}</td>
                              <td className="py-2">
                                {it.completed_at ? fmtDate(it.completed_at) : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-[var(--text-secondary)] text-center mt-10">
                      No iterations yet.
                    </p>
                  )
                )}
              </>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

/* ---- helpers ---- */

function Row({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex gap-4">
      <span className="w-36 shrink-0 text-sm text-[var(--text-secondary)]">{label}</span>
      <span className="text-sm">{children ?? value}</span>
    </div>
  );
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
