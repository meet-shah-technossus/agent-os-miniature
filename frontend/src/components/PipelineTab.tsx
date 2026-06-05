/* PipelineTab — extracted from SettingsView (Phase 13.3)
   Renders the Pipeline configuration tab: Execution, Mode, LLM providers.
*/

import { api } from '../hooks/api';
import type { RequirementsUploadResponse, RequirementsPreviewDoc } from '../hooks/api';
import { card, labelClass, inputClass, btnPrimary, btnSecondary, toggleBase, toggleDot } from './AIToolsTab';

/* ── Props ─────────────────────────────────────────────────────────────────── */
export interface PipelineTabProps {
  // Execution
  maxIter: number; setMaxIter: (v: number) => void;
  convergence: string; setConvergence: (v: string) => void;
  autoApprove: boolean; setAutoApprove: (v: boolean) => void;
  // Mode
  pipelineMode: 'standard' | 'github_review'; setPipelineMode: (v: 'standard' | 'github_review') => void;
  ghReviewUrl: string; setGhReviewUrl: (v: string) => void;
  ghReviewForkName: string; setGhReviewForkName: (v: string) => void;
  ghReviewBranch: string; setGhReviewBranch: (v: string) => void;
  // Requirements (shared with Pipeline Mode)
  reqSource: 'device' | 'jira' | 'asana' | 'ado'; setReqSource: (v: 'device' | 'jira' | 'asana' | 'ado') => void;
  reqPath: string; setReqPath: (v: string) => void;
  reqStats: { epics: number; features: number; stories: number } | null; setReqStats: (v: { epics: number; features: number; stories: number } | null) => void;
  reqError: string; setReqError: (v: string) => void;
  reqUploading: boolean; setReqUploading: (v: boolean) => void;
  reqIngesting: boolean; setReqIngesting: (v: boolean) => void;
  reqValidationResult: { valid: boolean; errors: string[]; warnings: string[] } | null; setReqValidationResult: (v: { valid: boolean; errors: string[]; warnings: string[] } | null) => void;
  reqViewOpen: boolean; setReqViewOpen: (v: boolean) => void;
  reqViewDoc: RequirementsPreviewDoc | null; setReqViewDoc: (v: RequirementsPreviewDoc | null) => void;
  reqViewLoading: boolean; setReqViewLoading: (v: boolean) => void;
  reqViewError: string; setReqViewError: (v: string) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  // JIRA
  jiraUrl: string; setJiraUrl: (v: string) => void;
  jiraEmail: string; setJiraEmail: (v: string) => void;
  jiraToken: string; setJiraToken: (v: string) => void;
  jiraProject: string; setJiraProject: (v: string) => void;
  // Asana
  asanaToken: string; setAsanaToken: (v: string) => void;
  asanaProjectId: string; setAsanaProjectId: (v: string) => void;
  // ADO
  adoOrg: string; setAdoOrg: (v: string) => void;
  adoToken: string; setAdoToken: (v: string) => void;
  adoProject: string; setAdoProject: (v: string) => void;
  adoProjects: string[]; setAdoProjects: (v: string[]) => void;
  adoProjectsLoading: boolean;
  adoProjectsFetchError: string; setAdoProjectsFetchError: (v: string) => void;
  fetchAdoProjects: (org: string, token: string) => void;
  // Prompt Generator LLM
  pgProvider: 'ollama' | 'openai'; setPgProvider: (v: 'ollama' | 'openai') => void;
  pgOllamaModel: string; setPgOllamaModel: (v: string) => void;
  pgOpenAIModel: string; setPgOpenAIModel: (v: string) => void;
  ollamaBaseUrl: string; setOllamaBaseUrl: (v: string) => void;
  ollamaTimeout: number; setOllamaTimeout: (v: number) => void;
  // Code Reviewer LLM
  crProvider: 'openai' | 'copilot' | 'ollama'; setCrProvider: (v: 'openai' | 'copilot' | 'ollama') => void;
  crModel: string; setCrModel: (v: string) => void;
  crOllamaModel: string; setCrOllamaModel: (v: string) => void;
}

/* ── Component ─────────────────────────────────────────────────────────────── */
export default function PipelineTab(p: PipelineTabProps) {
  return (
    <div className="space-y-6">
      {/* Execution settings */}
      <section className={card}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">Execution</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Max Iterations</label>
            <input type="number" min={1} max={20} className={inputClass} value={p.maxIter} onChange={(e) => p.setMaxIter(Number(e.target.value))} />
          </div>
          <div>
            <label className={labelClass}>Convergence Rule</label>
            <select className={inputClass} value={p.convergence} onChange={(e) => p.setConvergence(e.target.value)}>
              <option value="no_high_severity">No High Severity</option>
              <option value="no_critical">No Critical</option>
              <option value="all_accepted">All Accepted</option>
            </select>
          </div>
        </div>
        <div className="mt-4">
          <label className="flex items-center gap-2.5 text-xs text-white/60 cursor-pointer">
            <button type="button" onClick={() => p.setAutoApprove(!p.autoApprove)} className={`${toggleBase} ${p.autoApprove ? 'bg-indigo-600' : 'bg-white/10'}`}>
              <span className={`${toggleDot} ${p.autoApprove ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
            </button>
            Auto-approve HITL gates (debug mode)
          </label>
        </div>
      </section>

      {/* Pipeline mode */}
      <section className={card}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">Mode</h3>
        <div className="space-y-3">
          <label className="flex items-start gap-3 cursor-pointer p-3 rounded-lg border border-white/[0.06] hover:border-white/[0.1] transition-colors">
            <input type="radio" name="pipeline_mode" value="standard" checked={p.pipelineMode === 'standard'} onChange={() => p.setPipelineMode('standard')} className="mt-0.5 accent-indigo-500" />
            <div>
              <p className="text-sm font-medium text-white/80">Standard — Generate code from requirements</p>
              <p className="text-xs text-white/30 mt-0.5">Module Maker builds modules from requirements, then iterates through Code Gen → Review.</p>
            </div>
          </label>
          <label className="flex items-start gap-3 cursor-pointer p-3 rounded-lg border border-white/[0.06] hover:border-white/[0.1] transition-colors">
            <input type="radio" name="pipeline_mode" value="github_review" checked={p.pipelineMode === 'github_review'} onChange={() => p.setPipelineMode('github_review')} className="mt-0.5 accent-indigo-500" />
            <div>
              <p className="text-sm font-medium text-white/80">GitHub Review — Improve an existing repo</p>
              <p className="text-xs text-white/30 mt-0.5">Forks a GitHub repo, runs a full requirements-aware code review, then iterates fixes.</p>
            </div>
          </label>
        </div>

        {p.pipelineMode === 'github_review' && (
          <div className="mt-4 pt-4 border-t border-white/[0.04] space-y-4">
            <div>
              <label className={labelClass}>Source Repository URL</label>
              <input className={inputClass} value={p.ghReviewUrl} onChange={(e) => p.setGhReviewUrl(e.target.value)} placeholder="https://github.com/owner/repo" />
            </div>

            {/* Requirements Source */}
            <div>
              <p className={labelClass}>Requirements Source</p>
              <div className="grid grid-cols-4 gap-2 mb-3">
                {([['device', '📁', 'From Device'], ['jira', '🟦', 'JIRA'], ['asana', '🟧', 'Asana'], ['ado', '🟦', 'Azure DevOps']] as [typeof p.reqSource, string, string][]).map(([val, icon, name]) => (
                  <button key={val} onClick={() => { p.setReqSource(val); p.setReqError(''); p.setReqStats(null); }} className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition-colors ${p.reqSource === val ? 'border-indigo-500/40 bg-indigo-500/10 text-white' : 'border-white/[0.06] text-white/50 hover:border-white/[0.12]'}`}>
                    <span>{icon}</span> {name}
                  </button>
                ))}
              </div>

              {/* Device */}
              {p.reqSource === 'device' && (
                <div className="space-y-2">
                  <input ref={p.fileInputRef} type="file" accept=".xlsx,.csv,.txt,.yaml,.yml" className="hidden" onChange={async (e) => {
                    const file = e.target.files?.[0]; if (!file) return;
                    p.setReqError(''); p.setReqStats(null); p.setReqUploading(true);
                    try {
                      const res: RequirementsUploadResponse = await api.uploadRequirements(file);
                      p.setReqPath(res.path);
                      const s = res.stats;
                      p.setReqStats({ epics: s?.epics ?? (res as any).epics ?? 0, features: s?.features ?? (res as any).features ?? 0, stories: s?.stories ?? (res as any).tasks ?? 0 });
                    } catch (err) { p.setReqError(err instanceof Error ? err.message : 'Upload failed'); }
                    finally { p.setReqUploading(false); if (p.fileInputRef.current) p.fileInputRef.current.value = ''; }
                  }} />
                  <div className="flex items-center gap-3">
                    <button onClick={() => p.fileInputRef.current?.click()} disabled={p.reqUploading} className={btnSecondary}>{p.reqUploading ? 'Uploading…' : 'Browse & Upload…'}</button>
                    {p.reqPath ? <span className="text-xs font-mono text-indigo-300/80 truncate max-w-xs">{p.reqPath.split('/').pop()}</span> : <span className="text-xs text-white/25">No file chosen</span>}
                  </div>
                </div>
              )}

              {/* JIRA */}
              {p.reqSource === 'jira' && (
                <div className="space-y-3">
                  <div><label className={labelClass}>JIRA Base URL</label><input className={inputClass} value={p.jiraUrl} onChange={(e) => p.setJiraUrl(e.target.value)} placeholder="https://yourorg.atlassian.net" /></div>
                  <div className="grid grid-cols-2 gap-4">
                    <div><label className={labelClass}>Email</label><input className={inputClass} type="email" value={p.jiraEmail} onChange={(e) => p.setJiraEmail(e.target.value)} placeholder="you@example.com" /></div>
                    <div><label className={labelClass}>Project Key</label><input className={inputClass} value={p.jiraProject} onChange={(e) => p.setJiraProject(e.target.value.toUpperCase())} placeholder="PROJ" /></div>
                  </div>
                  <div><label className={labelClass}>API Token</label><input className={inputClass} type="password" value={p.jiraToken} onChange={(e) => p.setJiraToken(e.target.value)} placeholder="Atlassian API token" /></div>
                  <button disabled={p.reqIngesting || !p.jiraUrl || !p.jiraEmail || !p.jiraToken || !p.jiraProject} onClick={async () => {
                    p.setReqError(''); p.setReqStats(null); p.setReqIngesting(true); p.setReqValidationResult(null);
                    try { const res = await api.ingestRemoteRequirements({ source: 'jira', jira_url: p.jiraUrl, jira_email: p.jiraEmail, jira_api_token: p.jiraToken.startsWith('***') ? '' : p.jiraToken, jira_project_key: p.jiraProject }); p.setReqPath(res.path); const s = res.stats; p.setReqStats({ epics: s?.epics ?? 0, features: s?.features ?? 0, stories: s?.stories ?? 0 }); }
                    catch (err) { p.setReqError(err instanceof Error ? err.message : 'Ingestion failed'); }
                    finally { p.setReqIngesting(false); }
                  }} className={btnPrimary}>{p.reqIngesting ? 'Importing…' : 'Import from JIRA'}</button>
                </div>
              )}

              {/* Asana */}
              {p.reqSource === 'asana' && (
                <div className="space-y-3">
                  <div><label className={labelClass}>Personal Access Token</label><input className={inputClass} type="password" value={p.asanaToken} onChange={(e) => p.setAsanaToken(e.target.value)} placeholder="Asana PAT" /></div>
                  <div><label className={labelClass}>Project GID</label><input className={inputClass} value={p.asanaProjectId} onChange={(e) => p.setAsanaProjectId(e.target.value)} placeholder="1234567890123456" /></div>
                  <button disabled={p.reqIngesting || !p.asanaToken || !p.asanaProjectId} onClick={async () => {
                    p.setReqError(''); p.setReqStats(null); p.setReqIngesting(true); p.setReqValidationResult(null);
                    try { const res = await api.ingestRemoteRequirements({ source: 'asana', asana_token: p.asanaToken.startsWith('***') ? '' : p.asanaToken, asana_project_id: p.asanaProjectId }); p.setReqPath(res.path); const s = res.stats; p.setReqStats({ epics: s?.epics ?? 0, features: s?.features ?? 0, stories: s?.stories ?? 0 }); }
                    catch (err) { p.setReqError(err instanceof Error ? err.message : 'Ingestion failed'); }
                    finally { p.setReqIngesting(false); }
                  }} className={btnPrimary}>{p.reqIngesting ? 'Importing…' : 'Import from Asana'}</button>
                </div>
              )}

              {/* ADO */}
              {p.reqSource === 'ado' && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-4">
                    <div><label className={labelClass}>Organisation</label><input className={inputClass} value={p.adoOrg} onChange={(e) => { p.setAdoOrg(e.target.value); p.setAdoProjects([]); p.setAdoProjectsFetchError(''); }} placeholder="my-org" /></div>
                    <div>
                      <label className={labelClass}>Project</label>
                      <div className="flex gap-2">
                        <select className={`${inputClass} flex-1`} value={p.adoProject} onChange={(e) => p.setAdoProject(e.target.value)} disabled={p.adoProjectsLoading}>
                          {p.adoProjects.length === 0 ? <option value="">{p.adoProjectsLoading ? 'Loading…' : '— fetch projects —'}</option> : <><option value="">— select a project —</option>{p.adoProjects.map((proj) => <option key={proj} value={proj}>{proj}</option>)}</>}
                        </select>
                        <button type="button" disabled={p.adoProjectsLoading || !p.adoOrg} onClick={() => p.fetchAdoProjects(p.adoOrg, p.adoToken)} className="px-3 py-1.5 text-xs rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-white whitespace-nowrap">{p.adoProjectsLoading ? '…' : 'Fetch'}</button>
                      </div>
                      {p.adoProjectsFetchError && <p className="text-[10px] text-red-400/80 mt-1">{p.adoProjectsFetchError}</p>}
                    </div>
                  </div>
                  <div><label className={labelClass}>Personal Access Token</label><input className={inputClass} type="password" value={p.adoToken} onChange={(e) => { p.setAdoToken(e.target.value); p.setAdoProjects([]); p.setAdoProjectsFetchError(''); }} placeholder="ADO PAT" /></div>
                  <button disabled={p.reqIngesting || !p.adoOrg || !p.adoToken || !p.adoProject} onClick={async () => {
                    p.setReqError(''); p.setReqStats(null); p.setReqIngesting(true); p.setReqValidationResult(null);
                    try { const res = await api.ingestRemoteRequirements({ source: 'ado', ado_org: p.adoOrg, ado_token: p.adoToken.startsWith('***') ? '' : p.adoToken, ado_project: p.adoProject }); p.setReqPath(res.path); const s = res.stats; p.setReqStats({ epics: s?.epics ?? 0, features: s?.features ?? 0, stories: s?.stories ?? 0 }); }
                    catch (err) { p.setReqError(err instanceof Error ? err.message : 'Ingestion failed'); }
                    finally { p.setReqIngesting(false); }
                  }} className={btnPrimary}>{p.reqIngesting ? 'Importing…' : 'Import from ADO'}</button>
                </div>
              )}

              {/* Ingestion feedback */}
              {p.reqStats && <p className="text-xs text-green-400/80 mt-2">Loaded: {p.reqStats.epics} epics · {p.reqStats.features} features · {p.reqStats.stories} stories</p>}
              {p.reqError && <p className="text-xs text-red-400/80 mt-2">{p.reqError}</p>}
            </div>

            {/* Fork Name Override + Branch Name Prefix */}
            <div className="grid grid-cols-2 gap-4">
              <div><label className={labelClass}>Fork Name Override</label><input className={inputClass} value={p.ghReviewForkName} onChange={(e) => p.setGhReviewForkName(e.target.value)} placeholder="my-repo" /></div>
              <div>
                <label className={labelClass}>Branch Name Prefix</label>
                <input className={inputClass} value={p.ghReviewBranch} onChange={(e) => p.setGhReviewBranch(e.target.value)} placeholder="story-" />
                <p className="text-[10px] text-white/25 mt-1">Branches are auto-named: prefix + story-id (e.g. story-42-auth)</p>
              </div>
            </div>

            {/* View Requirements */}
            <div className="pt-2 border-t border-white/[0.04] flex items-center gap-3">
              <p className="text-xs text-white/30 flex-1">Preview the requirements that will be used for this GitHub Review run.</p>
              <button onClick={async () => {
                p.setReqViewError(''); p.setReqViewDoc(null); p.setReqViewOpen(true); p.setReqViewLoading(true);
                try { const doc = await api.previewRequirements(); p.setReqViewDoc(doc); }
                catch (err) { p.setReqViewError(err instanceof Error ? err.message : 'Failed to load preview'); }
                finally { p.setReqViewLoading(false); }
              }} className="flex items-center gap-1.5 px-3 py-1 rounded-lg border border-indigo-500/30 bg-indigo-500/10 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 transition-colors shrink-0">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                View Requirements
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── Prompt Generator LLM Provider ──────────────────────────────── */}
      <section className={card}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-1">Prompt Generator</h3>
        <p className="text-[11px] text-white/30 mb-4">Choose the LLM backend used when generating implementation and fix prompts.</p>
        <div className="flex gap-3 mb-5">
          {([['ollama', '🦙', 'Ollama (GPU)'] as const, ['openai', '✦', 'OpenAI API'] as const]).map(([val, icon, name]) => (
            <button key={val} onClick={() => p.setPgProvider(val)} className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-all ${p.pgProvider === val ? 'border-indigo-500/50 bg-indigo-500/10 text-white' : 'border-white/[0.08] bg-white/[0.03] text-white/50 hover:border-white/20 hover:text-white/70'}`}>
              <span>{icon}</span>{name}
            </button>
          ))}
        </div>
        {p.pgProvider === 'ollama' && (
          <div className="space-y-4">
            <div>
              <label className={labelClass}>Ollama Base URL</label>
              <input className={inputClass} value={p.ollamaBaseUrl} onChange={(e) => p.setOllamaBaseUrl(e.target.value)} placeholder="http://192.168.x.x:11434" />
              <p className="text-[10px] text-white/25 mt-1.5">Remote GPU over VPN — set the full URL including port.</p>
            </div>
            <div>
              <label className={labelClass}>Model</label>
              <select className={inputClass} value={p.pgOllamaModel} onChange={(e) => p.setPgOllamaModel(e.target.value)}>
                {['llama3.1:8b', 'llama3.2:3b', 'llama3:latest', 'qwen2.5:7b', 'qwen2.5-coder:32b', 'gemma3:4b', 'mistral-nemo:latest', 'ibm/granite-docling:latest', 'nomic-embed-text:latest'].map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Request Timeout (seconds)</label>
              <input type="number" min={30} max={1200} className={inputClass} value={p.ollamaTimeout} onChange={(e) => p.setOllamaTimeout(Number(e.target.value))} />
            </div>
          </div>
        )}
        {p.pgProvider === 'openai' && (
          <div className="space-y-4">
            <div>
              <label className={labelClass}>OpenAI Model</label>
              <input className={inputClass} value={p.pgOpenAIModel} onChange={(e) => p.setPgOpenAIModel(e.target.value)} placeholder="gpt-4.1-mini" />
              <p className="text-[10px] text-white/25 mt-1.5">Any OpenAI chat model. API key configured under VCS / Git or OPENAI_API_KEY env var.</p>
            </div>
          </div>
        )}
      </section>

      {/* ── Code Reviewer LLM Provider ─────────────────────────────────── */}
      <section className={card}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-1">Code Reviewer</h3>
        <p className="text-[11px] text-white/30 mb-4">Choose the LLM backend for automated PR code review.</p>
        <div className="flex gap-3 mb-5">
          {([['openai', '✦', 'OpenAI API'] as const, ['copilot', '🤖', 'GitHub Copilot'] as const, ['ollama', '🦙', 'Ollama (GPU)'] as const]).map(([val, icon, name]) => (
            <button key={val} onClick={() => p.setCrProvider(val)} className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-all ${p.crProvider === val ? 'border-indigo-500/50 bg-indigo-500/10 text-white' : 'border-white/[0.08] bg-white/[0.03] text-white/50 hover:border-white/20 hover:text-white/70'}`}>
              <span>{icon}</span>{name}
            </button>
          ))}
        </div>
        {p.crProvider === 'openai' && (
          <div className="space-y-4"><div>
            <label className={labelClass}>OpenAI Model</label>
            <select className={inputClass} value={p.crModel} onChange={(e) => p.setCrModel(e.target.value)}>
              {['gpt-5.2', 'gpt-5-mini', 'gpt-4.1', 'gpt-4.1-2025-04-14', 'gpt-4o', 'gpt-4o-mini', 'gpt-4', 'gpt-3.5-turbo'].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <p className="text-[10px] text-white/25 mt-1.5">Requires OPENAI_API_KEY env var.</p>
          </div></div>
        )}
        {p.crProvider === 'copilot' && (
          <div className="space-y-4"><div>
            <label className={labelClass}>Copilot Model</label>
            <select className={inputClass} value={p.crModel} onChange={(e) => p.setCrModel(e.target.value)}>
              {['gpt-5.2', 'gpt-5-mini', 'gpt-4.1', 'gpt-4.1-2025-04-14', 'gpt-4o', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06', 'gpt-4o-mini', 'gpt-4', 'gpt-3.5-turbo', 'claude-haiku-4.5', 'gemini-3.1-pro-preview', 'gemini-2.5-pro'].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <p className="text-[10px] text-white/25 mt-1.5">Uses your GITHUB_TOKEN — no OpenAI key required.</p>
          </div></div>
        )}
        {p.crProvider === 'ollama' && (
          <div className="space-y-4"><div>
            <label className={labelClass}>Ollama Model</label>
            <select className={inputClass} value={p.crOllamaModel} onChange={(e) => p.setCrOllamaModel(e.target.value)}>
              {['llama3.1:8b', 'llama3.2:3b', 'llama3:latest', 'qwen2.5:7b', 'qwen2.5-coder:32b', 'gemma3:4b', 'mistral-nemo:latest'].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <p className="text-[10px] text-white/25 mt-1.5">Ollama base URL is shared with Prompt Generator settings above.</p>
          </div></div>
        )}
      </section>
    </div>
  );
}
