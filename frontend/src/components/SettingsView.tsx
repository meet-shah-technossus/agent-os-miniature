/* Settings — API keys, GitHub config, project & pipeline settings */

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { api } from '../hooks/api';
import type { Settings as SettingsType, TestGitHubResponse } from '../types';

const card = 'rounded-xl border border-[var(--border-glass)] bg-[var(--glass)] p-5';
const label = 'block text-xs text-[var(--text-secondary)] mb-1';
const input =
  'w-full rounded-lg border border-[var(--border-glass)] bg-black/20 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none';
const toggle =
  'relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer';
const toggleDot = 'inline-block h-4 w-4 rounded-full bg-white transition-transform';

export default function SettingsView() {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState('');
  const [ghTest, setGhTest] = useState<TestGitHubResponse | null>(null);

  // Editable fields
  const [openaiKey, setOpenaiKey] = useState('');
  const [ghToken, setGhToken] = useState('');
  const [ghOwner, setGhOwner] = useState('');
  const [ghRepo, setGhRepo] = useState('');
  const [autoPush, setAutoPush] = useState(false);
  const [autoCreatePr, setAutoCreatePr] = useState(false);
  const [projName, setProjName] = useState('');
  const [projRoot, setProjRoot] = useState('');
  const [projLang, setProjLang] = useState('python');
  const [maxIter, setMaxIter] = useState(5);
  const [convergence, setConvergence] = useState('no_high_severity');
  const [autoApprove, setAutoApprove] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s);
      setOpenaiKey(s.secrets.openai_api_key);
      setGhToken(s.secrets.github_token);
      setGhOwner(s.github.owner);
      setGhRepo(s.github.repo);
      setAutoPush(s.github.auto_push);
      setAutoCreatePr(s.github.auto_create_pr);
      setProjName(s.project.name);
      setProjRoot(s.project.root_path);
      setProjLang(s.project.language);
      setMaxIter(s.pipeline.max_iterations_per_module);
      setConvergence(s.pipeline.convergence_rule);
      setAutoApprove(s.pipeline.auto_approve_hitl);
    }).catch(() => {});
  }, []);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(''), 3000);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await api.updateSettings({
        secrets: { openai_api_key: openaiKey, github_token: ghToken },
        github: { owner: ghOwner, repo: ghRepo, auto_push: autoPush, auto_create_pr: autoCreatePr },
        project: { name: projName, root_path: projRoot, language: projLang },
        pipeline: { max_iterations_per_module: maxIter, convergence_rule: convergence, auto_approve_hitl: autoApprove },
      });
      setSettings(updated);
      setOpenaiKey(updated.secrets.openai_api_key);
      setGhToken(updated.secrets.github_token);
      flash('Settings saved');
    } catch {
      flash('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleTestGH = async () => {
    setGhTest(null);
    try {
      const r = await api.testGitHub();
      setGhTest(r);
    } catch {
      setGhTest({ valid: false, user: '', message: 'Request failed' });
    }
  };

  if (!settings) {
    return <div className="text-[var(--text-secondary)]">Loading settings…</div>;
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-xl font-semibold">Settings</h2>

      {/* Toast */}
      {toast && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white"
        >
          {toast}
        </motion.div>
      )}

      {/* Secrets */}
      <section className={card}>
        <h3 className="text-sm font-medium mb-4">API Keys & Tokens</h3>
        <div className="space-y-3">
          <div>
            <label className={label}>OpenAI API Key</label>
            <input
              type="password"
              className={input}
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
              placeholder="sk-..."
            />
            <p className="text-xs text-[var(--text-secondary)] mt-1">
              Also reads from OPENAI_API_KEY env var or .env file
            </p>
          </div>
          <div>
            <label className={label}>GitHub Token</label>
            <div className="flex gap-2">
              <input
                type="password"
                className={input}
                value={ghToken}
                onChange={(e) => setGhToken(e.target.value)}
                placeholder="ghp_... or github_pat_..."
              />
              <button
                onClick={handleTestGH}
                className="shrink-0 rounded-lg bg-slate-700 px-3 py-2 text-xs hover:bg-slate-600 transition-colors"
              >
                Test
              </button>
            </div>
            {ghTest && (
              <p className={`text-xs mt-1 ${ghTest.valid ? 'text-green-400' : 'text-red-400'}`}>
                {ghTest.message}
              </p>
            )}
            <p className="text-xs text-[var(--text-secondary)] mt-1">
              Also reads from GITHUB_TOKEN env var or .env file
            </p>
          </div>
        </div>
      </section>

      {/* GitHub */}
      <section className={card}>
        <h3 className="text-sm font-medium mb-4">GitHub Integration</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label}>Owner (org or user)</label>
            <input className={input} value={ghOwner} onChange={(e) => setGhOwner(e.target.value)} placeholder="my-org" />
          </div>
          <div>
            <label className={label}>Repository</label>
            <input className={input} value={ghRepo} onChange={(e) => setGhRepo(e.target.value)} placeholder="my-repo" />
          </div>
        </div>
        <div className="flex gap-6 mt-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <button
              type="button"
              onClick={() => setAutoPush(!autoPush)}
              className={`${toggle} ${autoPush ? 'bg-indigo-500' : 'bg-slate-600'}`}
            >
              <span className={`${toggleDot} ${autoPush ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            Auto-push branches
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <button
              type="button"
              onClick={() => setAutoCreatePr(!autoCreatePr)}
              className={`${toggle} ${autoCreatePr ? 'bg-indigo-500' : 'bg-slate-600'}`}
            >
              <span className={`${toggleDot} ${autoCreatePr ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            Auto-create PRs
          </label>
        </div>
      </section>

      {/* Project */}
      <section className={card}>
        <h3 className="text-sm font-medium mb-4">Project</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label}>Project Name</label>
            <input className={input} value={projName} onChange={(e) => setProjName(e.target.value)} />
          </div>
          <div>
            <label className={label}>Language</label>
            <select className={input} value={projLang} onChange={(e) => setProjLang(e.target.value)}>
              <option value="python">Python</option>
              <option value="typescript">TypeScript</option>
              <option value="javascript">JavaScript</option>
              <option value="java">Java</option>
              <option value="go">Go</option>
              <option value="rust">Rust</option>
            </select>
          </div>
        </div>
        <div className="mt-3">
          <label className={label}>Root Path</label>
          <input className={input} value={projRoot} onChange={(e) => setProjRoot(e.target.value)} placeholder="/path/to/project" />
        </div>
      </section>

      {/* Pipeline */}
      <section className={card}>
        <h3 className="text-sm font-medium mb-4">Pipeline</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label}>Max Iterations per Module</label>
            <input
              type="number"
              min={1}
              max={20}
              className={input}
              value={maxIter}
              onChange={(e) => setMaxIter(Number(e.target.value))}
            />
          </div>
          <div>
            <label className={label}>Convergence Rule</label>
            <select className={input} value={convergence} onChange={(e) => setConvergence(e.target.value)}>
              <option value="no_high_severity">No High Severity</option>
              <option value="no_critical">No Critical</option>
              <option value="all_accepted">All Accepted</option>
            </select>
          </div>
        </div>
        <div className="mt-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <button
              type="button"
              onClick={() => setAutoApprove(!autoApprove)}
              className={`${toggle} ${autoApprove ? 'bg-indigo-500' : 'bg-slate-600'}`}
            >
              <span className={`${toggleDot} ${autoApprove ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            Auto-approve HITL gates (debug mode)
          </label>
        </div>
      </section>

      {/* Save */}
      <button
        onClick={handleSave}
        disabled={saving}
        className="rounded-lg bg-indigo-600 px-6 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 transition-colors"
      >
        {saving ? 'Saving…' : 'Save All Settings'}
      </button>
    </div>
  );
}
