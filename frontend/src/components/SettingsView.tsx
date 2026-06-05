/* Settings â€” professional tabbed layout with real CLI-tool management */

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../hooks/api';
import type { RequirementsUploadResponse, RequirementsPreviewDoc } from '../hooks/api';
import type {
  AIToolCredential,
  CliToolStatus,
  Settings as SettingsType,
  TestGitHubResponse,
} from '../types';
import AIToolsTab, { type ToolKey, card, labelClass, inputClass, btnPrimary, btnSecondary, toggleBase, toggleDot } from './AIToolsTab';
import PipelineTab from './PipelineTab';

// Local aliases for remaining render functions that use short names
const label = labelClass;
const input = inputClass;

/* â”€â”€ Tab types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
type Tab = 'ai-tools' | 'github' | 'project' | 'pipeline' | 'requirements';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'ai-tools',     label: 'AI Tools',        icon: 'âš¡' },
  { key: 'github',       label: 'VCS / Git',        icon: 'ðŸ”—' },
  { key: 'project',      label: 'Project',          icon: 'ðŸ“' },
  { key: 'pipeline',     label: 'Pipeline',         icon: 'ðŸ”„' },
  { key: 'requirements', label: 'Requirements',     icon: 'ðŸ“‹' },
];

const emptyCredential = (): AIToolCredential => ({
  enabled: false, auth_method: '', api_key: '', email: '', account_id: '', endpoint: '',
});

/* â”€â”€ Requirements preview sub-components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */

import type { ReqEpic, ReqFeature, ReqStory } from '../hooks/api';

function ReqStoryBlock({ story }: { story: ReqStory }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.03] transition-colors"
      >
        <span className="text-[10px] text-white/30 font-mono w-16 shrink-0">{story.id}</span>
        <span className="flex-1 text-xs text-white/80 font-medium">{story.title}</span>
        <span className="text-[10px] text-white/30 shrink-0">{story.acceptance_criteria.length} AC</span>
        <svg className={`w-3 h-3 text-white/30 transition-transform shrink-0 ${open ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="border-t border-white/[0.04] px-3 py-2 space-y-1.5">
          {story.description && (
            <p className="text-[11px] text-white/40 leading-relaxed mb-2">{story.description}</p>
          )}
          {story.acceptance_criteria.length === 0 ? (
            <p className="text-[11px] text-white/25 italic">No acceptance criteria</p>
          ) : (
            story.acceptance_criteria.map((ac, i) => (
              <div key={ac.id} className="flex items-start gap-2">
                <span className="mt-0.5 w-4 h-4 rounded-full border border-emerald-500/40 bg-emerald-500/10 flex items-center justify-center shrink-0">
                  <svg className="w-2.5 h-2.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                  </svg>
                </span>
                <span className="text-[11px] text-white/60 leading-relaxed">
                  <span className="text-white/25 font-mono mr-1">{i + 1}.</span>{ac.title}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function ReqFeatureBlock({ feature }: { feature: ReqFeature }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="ml-3 space-y-1.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-left group"
      >
        <svg className={`w-3 h-3 text-violet-400/60 transition-transform ${open ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-[10px] font-mono text-white/25 w-14 shrink-0">{feature.id}</span>
        <span className="text-xs font-semibold text-violet-300/80 group-hover:text-violet-300">{feature.title}</span>
        <span className="text-[10px] text-white/25">{feature.stories.length} stor{feature.stories.length !== 1 ? 'ies' : 'y'}</span>
      </button>
      {open && (
        <div className="ml-5 space-y-1.5">
          {feature.stories.map((s) => <ReqStoryBlock key={s.id} story={s} />)}
        </div>
      )}
    </div>
  );
}

function ReqEpicBlock({ epic }: { epic: ReqEpic }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-white/[0.03] transition-colors"
      >
        <svg className={`w-3.5 h-3.5 text-indigo-400/60 transition-transform ${open ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400/70 font-mono">{epic.id}</span>
        <span className="flex-1 text-sm font-semibold text-white/90">{epic.title}</span>
        <span className="text-[10px] text-white/25">{epic.features.length} feature{epic.features.length !== 1 ? 's' : ''}</span>
      </button>
      {open && (
        <div className="border-t border-white/[0.05] px-4 py-3 space-y-3">
          {epic.description && (
            <p className="text-[11px] text-white/35 leading-relaxed">{epic.description}</p>
          )}
          {epic.features.map((f) => <ReqFeatureBlock key={f.id} feature={f} />)}
        </div>
      )}
    </div>
  );
}

/* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

export default function SettingsView() {
  /* â”€â”€ Top-level state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [settings, setSettings]     = useState<SettingsType | null>(null);
  const [saving, setSaving]         = useState(false);
  const [toast, setToast]           = useState('');
  const [activeTab, setActiveTab]   = useState<Tab>('ai-tools');
  const [ghTest, setGhTest]         = useState<TestGitHubResponse | null>(null);

  /* â”€â”€ Editable fields â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [ghToken, setGhToken]             = useState('');
  const [ghOwner, setGhOwner]             = useState('');
  const [ghRepo, setGhRepo]               = useState('');
  const [autoPush, setAutoPush]           = useState(false);
  const [autoCreatePr, setAutoCreatePr]   = useState(false);
  const [vcsProvider, setVcsProvider]     = useState<'github' | 'ado'>('github');
  const [projName, setProjName]           = useState('');
  const [projRoot, setProjRoot]           = useState('');
  const [projLang, setProjLang]           = useState('python');
  const [repoName, setRepoName]           = useState('');
  const [featureBranch, setFeatureBranch] = useState('dev');
  const [promptFilePath, setPromptFilePath] = useState('');
  const [maxIter, setMaxIter]             = useState(5);
  const [convergence, setConvergence]     = useState('no_high_severity');
  const [autoApprove, setAutoApprove]     = useState(false);

  /* â”€â”€ AI Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [aiTools, setAiTools] = useState<Record<ToolKey, AIToolCredential>>({
    codex: emptyCredential(), claude: emptyCredential(), gemini: emptyCredential(),
    qwen: emptyCredential(), deepseek: emptyCredential(), cursor: emptyCredential(),
    copilot: emptyCredential(),
  });
  const [expandedTool, setExpandedTool]   = useState<ToolKey | null>(null);
  const [toolStatuses, setToolStatuses]   = useState<Record<string, CliToolStatus>>({});
  const [toolLoading, setToolLoading]     = useState<Record<string, boolean>>({});
  const [toolMessage, setToolMessage]     = useState<Record<string, { ok: boolean; text: string }>>({});
  const [apiKeyInputs, setApiKeyInputs]   = useState<Record<string, string>>({});
  const [copiedCmd, setCopiedCmd]         = useState<Record<string, boolean>>({});

  /* â”€â”€ Requirements â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [reqSource, setReqSource] = useState<'device' | 'jira' | 'asana' | 'ado'>('device');
  const [reqPath, setReqPath]     = useState('');
  const [reqStats, setReqStats]   = useState<{ epics: number; features: number; stories: number } | null>(null);
  const [reqError, setReqError]   = useState('');
  const [reqUploading, setReqUploading]   = useState(false);
  const [reqIngesting, setReqIngesting]   = useState(false);
  const [reqViewOpen, setReqViewOpen]     = useState(false);
  const [reqViewDoc, setReqViewDoc]       = useState<RequirementsPreviewDoc | null>(null);
  const [reqViewLoading, setReqViewLoading] = useState(false);
  const [reqValidating, setReqValidating] = useState(false);
  const [reqValidationResult, setReqValidationResult] = useState<{ valid: boolean; errors: string[]; warnings: string[] } | null>(null);
  const [reqViewError, setReqViewError]   = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [jiraUrl, setJiraUrl]             = useState('');
  const [jiraEmail, setJiraEmail]         = useState('');
  const [jiraToken, setJiraToken]         = useState('');
  const [jiraProject, setJiraProject]     = useState('');
  const [asanaToken, setAsanaToken]       = useState('');
  const [asanaProjectId, setAsanaProjectId] = useState('');
  const [adoOrg, setAdoOrg]               = useState('');
  const [adoToken, setAdoToken]           = useState('');
  const [adoProject, setAdoProject]       = useState('');
  const [adoProjects, setAdoProjects]     = useState<string[]>([]);
  const [adoProjectsLoading, setAdoProjectsLoading] = useState(false);
  const [adoProjectsFetchError, setAdoProjectsFetchError] = useState('');
  const [adoMcpOpen, setAdoMcpOpen]       = useState<Record<string, boolean>>({});

  /* â”€â”€ Pipeline mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [pipelineMode, setPipelineMode]   = useState<'standard' | 'github_review'>('standard');
  const [ghReviewUrl, setGhReviewUrl]     = useState('');
  const [ghReviewForkName, setGhReviewForkName] = useState('');
  const [ghReviewBranch, setGhReviewBranch]     = useState('story-');

  /* â”€â”€ Prompt Generator / Ollama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [pgProvider, setPgProvider]         = useState<'ollama' | 'openai'>('ollama');
  const [pgOllamaModel, setPgOllamaModel]   = useState('llama3.1:8b');
  const [pgOpenAIModel, setPgOpenAIModel]   = useState('gpt-4.1-mini');
  const [ollamaBaseUrl, setOllamaBaseUrl]   = useState('http://localhost:11434');
  const [ollamaTimeout, setOllamaTimeout]   = useState(300);

  /* â”€â”€ Code Reviewer LLM Provider â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [crProvider, setCrProvider]         = useState<'openai' | 'copilot' | 'ollama'>('openai');
  const [crModel, setCrModel]               = useState('gpt-4.1-mini');
  const [crOllamaModel, setCrOllamaModel]   = useState('llama3.1:8b');


  /* â”€â”€ Load settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s);
      setGhToken(s.secrets.github_token);
      setGhOwner(s.github.owner);
      setGhRepo(s.github.repo);
      // Auto-derive repo name from project root folder when not configured
      if (!s.github.repo && s.project.root_path) {
        const derivedRepo = s.project.root_path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || '';
        if (derivedRepo) setGhRepo(derivedRepo);
      }
      setAutoPush(s.github.auto_push);
      setAutoCreatePr(s.github.auto_create_pr);
      setVcsProvider(s.vcs?.provider === 'ado' ? 'ado' : 'github');
      setProjName(s.project.name);
      setProjRoot(s.project.root_path);
      setProjLang(s.project.language);
      setRepoName(s.project.repo_name ?? '');
      setFeatureBranch(s.project.feature_branch ?? 'dev');
      setPromptFilePath(s.project.prompt_file_path ?? '');
      setMaxIter(s.pipeline.max_iterations);
      setConvergence(s.pipeline.convergence_rule);
      setAutoApprove(s.pipeline.auto_approve_hitl);
      if (s.ai_tools) {
        setAiTools({
          codex:    { ...emptyCredential(), ...s.ai_tools.codex },
          claude:   { ...emptyCredential(), ...s.ai_tools.claude },
          gemini:   { ...emptyCredential(), ...s.ai_tools.gemini },
          qwen:     { ...emptyCredential(), ...s.ai_tools.qwen },
          deepseek: { ...emptyCredential(), ...s.ai_tools.deepseek },
          cursor:   { ...emptyCredential(), ...s.ai_tools.cursor },
          copilot:  { ...emptyCredential(), ...s.ai_tools.copilot },
        });
      }
      if (s.requirements) {
        setReqPath(s.requirements.path ?? '');
        setReqSource((s.requirements.source as typeof reqSource) ?? 'device');
        setJiraUrl(s.requirements.jira_url ?? '');
        setJiraEmail(s.requirements.jira_email ?? '');
        setJiraToken(s.requirements.jira_api_token ? '***' : '');
        setJiraProject(s.requirements.jira_project_key ?? '');
        setAsanaToken(s.requirements.asana_token ? '***' : '');
        setAsanaProjectId(s.requirements.asana_project_id ?? '');
        setAdoOrg(s.requirements.ado_org ?? '');
        setAdoToken(s.requirements.ado_token ? '***' : '');
        setAdoProject(s.requirements.ado_project ?? '');
      }
      if (s.pipeline_mode) {
        setPipelineMode(s.pipeline_mode === 'github_review' ? 'github_review' : 'standard');
      }
      if (s.github_review) {
        setGhReviewUrl(s.github_review.source_repo_url ?? '');
        setReqPath(s.github_review.requirements_path ?? '');
        setGhReviewForkName(s.github_review.fork_repo_name ?? '');
        setGhReviewBranch(s.github_review.branch_name || 'story-');
      }
      if (s.ollama) {
        setOllamaBaseUrl(s.ollama.base_url || 'http://localhost:11434');
        setOllamaTimeout(s.ollama.timeout_seconds ?? 300);
      }
      if (s.prompt_generator) {
        setPgProvider(s.prompt_generator.provider === 'openai' ? 'openai' : 'ollama');
        setPgOllamaModel(s.prompt_generator.ollama_model || 'llama3.1:8b');
        setPgOpenAIModel(s.prompt_generator.openai_model || 'gpt-4.1-mini');
      }
      if (s.code_reviewer) {
        const p = (s.code_reviewer.provider as 'openai' | 'copilot' | 'ollama') || 'openai';
        setCrProvider(p);
        setCrModel(s.code_reviewer.model || 'gpt-4.1-mini');
        setCrOllamaModel(s.code_reviewer.ollama_model || 'llama3.1:8b');
      }
    }).catch(() => {});
  }, []);

  /* â”€â”€ Load CLI tool statuses â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const loadToolStatuses = useCallback(() => {
    api.getCliTools().then(({ tools }) => {
      const map: Record<string, CliToolStatus> = {};
      for (const t of tools) map[t.key] = t;
      setToolStatuses(map);
    }).catch(() => {});
  }, []);

  useEffect(() => { loadToolStatuses(); }, [loadToolStatuses]);

  /* â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(''), 3000);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const aiToolsPayload = Object.fromEntries(
        (Object.keys(aiTools) as ToolKey[]).map((k) => {
          const cred = aiTools[k];
          return [k, {
            ...cred,
            api_key: cred.api_key && cred.api_key.startsWith('***') ? '' : (cred.api_key ?? ''),
          }];
        })
      ) as Record<ToolKey, AIToolCredential>;

      const updated = await api.updateSettings({
        secrets: { github_token: ghToken },
        github: { owner: ghOwner, repo: ghRepo, auto_push: autoPush, auto_create_pr: autoCreatePr },
        project: { name: projName, root_path: projRoot, language: projLang, repo_name: repoName, feature_branch: featureBranch, prompt_file_path: promptFilePath },
        pipeline: { max_iterations: maxIter, convergence_rule: convergence, auto_approve_hitl: autoApprove },
        ai_tools: aiToolsPayload,
        pipeline_mode: pipelineMode,
        vcs: { provider: vcsProvider },
        github_review: {
          source_repo_url: ghReviewUrl,
          requirements_path: reqPath,
          fork_repo_name: ghReviewForkName,
          branch_name: ghReviewBranch || 'story-',
        },
        requirements: {
          path: reqPath, source: reqSource,
          jira_url: jiraUrl, jira_email: jiraEmail,
          jira_api_token: jiraToken.startsWith('***') ? '' : jiraToken,
          jira_project_key: jiraProject,
          asana_token: asanaToken.startsWith('***') ? '' : asanaToken,
          asana_project_id: asanaProjectId,
          ado_org: adoOrg,
          ado_token: adoToken.startsWith('***') ? '' : adoToken,
          ado_project: adoProject,
        },
        ollama: {
          base_url: ollamaBaseUrl,
          model: pgOllamaModel,
          timeout_seconds: ollamaTimeout,
        },
        prompt_generator: {
          provider: pgProvider,
          ollama_model: pgOllamaModel,
          openai_model: pgOpenAIModel,
        },
        code_reviewer: {
          provider: crProvider,
          model: crModel,
          ollama_model: crOllamaModel,
        },
      });
      setSettings(updated);
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
      // Pass the live token from the input (unless it's a masked placeholder)
      const tokenToTest = ghToken && !ghToken.startsWith('***') && !ghToken.includes('...') ? ghToken : undefined;
      const r = await api.testGitHub(tokenToTest);
      setGhTest(r);
      // Auto-populate Owner from the authenticated GitHub user
      if (r.valid && r.user) setGhOwner(r.user);
      // Auto-populate Repo from project root folder name if still empty
      if (!ghRepo && projRoot) {
        const derivedRepo = projRoot.replace(/\\/g, '/').split('/').filter(Boolean).pop() || '';
        if (derivedRepo) setGhRepo(derivedRepo);
      }
    } catch {
      setGhTest({ valid: false, user: '', message: 'Request failed' });
    }
  };

  const fetchAdoProjects = async (org: string, token: string) => {
    if (!org) return;  // token may be '***' â€” backend resolves the saved PAT automatically
    setAdoProjectsLoading(true);
    setAdoProjectsFetchError('');
    try {
      const res = await api.getAdoProjects(org, token);
      setAdoProjects(res.projects);
      // If the currently stored project isn't in the fetched list, auto-select the first
      // available project so the controlled <select> value always matches an option.
      if (res.projects.length > 0 && !res.projects.includes(adoProject)) {
        setAdoProject(res.projects[0]);
      }
    } catch (err) {
      setAdoProjectsFetchError(err instanceof Error ? err.message : 'Failed to fetch projects');
      setAdoProjects([]);
    } finally {
      setAdoProjectsLoading(false);
    }
  };

  /* â”€â”€ Loading state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  if (!settings) {
    return (
      <div className="flex items-center justify-center h-64 text-white/40 text-sm">
        Loading settingsâ€¦
      </div>
    );
  }

  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */
  /* RENDER                                                                     */
  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

  return (
    <div className="max-w-5xl mx-auto">
      {/* â”€â”€ Header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <p className="text-xs text-white/40 mt-0.5">Configure AI tools, integrations, and pipeline behavior</p>
        </div>
        <button onClick={handleSave} disabled={saving} className={btnPrimary}>
          {saving ? 'Savingâ€¦' : 'Save Changes'}
        </button>
      </div>

      {/* â”€â”€ Toast â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mb-4 rounded-lg bg-indigo-600/90 backdrop-blur px-4 py-2 text-sm text-white"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>

      {/* â”€â”€ Tab navigation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex gap-1 mb-6 border-b border-white/[0.06] pb-px">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2.5 text-xs font-medium rounded-t-lg transition-colors relative ${
              activeTab === t.key
                ? 'text-white bg-white/[0.06]'
                : 'text-white/40 hover:text-white/70'
            }`}
          >
            <span className="mr-1.5">{t.icon}</span>
            {t.label}
            {activeTab === t.key && (
              <motion.div
                layoutId="tab-indicator"
                className="absolute bottom-0 left-0 right-0 h-px bg-indigo-500"
              />
            )}
          </button>
        ))}
      </div>

      {/* â”€â”€ Tab content â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15 }}
        >
          {activeTab === 'ai-tools' && <AIToolsTab aiTools={aiTools} setAiTools={setAiTools} expandedTool={expandedTool} setExpandedTool={setExpandedTool} toolStatuses={toolStatuses} setToolStatuses={setToolStatuses} toolLoading={toolLoading} setToolLoading={setToolLoading} toolMessage={toolMessage} setToolMessage={setToolMessage} apiKeyInputs={apiKeyInputs} setApiKeyInputs={setApiKeyInputs} copiedCmd={copiedCmd} setCopiedCmd={setCopiedCmd} adoOrg={adoOrg} adoMcpOpen={adoMcpOpen} setAdoMcpOpen={setAdoMcpOpen} />}
          {activeTab === 'github' && renderGitHub()}
          {activeTab === 'project' && renderProject()}
          {activeTab === 'pipeline' && <PipelineTab maxIter={maxIter} setMaxIter={setMaxIter} convergence={convergence} setConvergence={setConvergence} autoApprove={autoApprove} setAutoApprove={setAutoApprove} pipelineMode={pipelineMode} setPipelineMode={setPipelineMode} ghReviewUrl={ghReviewUrl} setGhReviewUrl={setGhReviewUrl} ghReviewForkName={ghReviewForkName} setGhReviewForkName={setGhReviewForkName} ghReviewBranch={ghReviewBranch} setGhReviewBranch={setGhReviewBranch} reqSource={reqSource} setReqSource={setReqSource} reqPath={reqPath} setReqPath={setReqPath} reqStats={reqStats} setReqStats={setReqStats} reqError={reqError} setReqError={setReqError} reqUploading={reqUploading} setReqUploading={setReqUploading} reqIngesting={reqIngesting} setReqIngesting={setReqIngesting} reqValidationResult={reqValidationResult} setReqValidationResult={setReqValidationResult} reqViewOpen={reqViewOpen} setReqViewOpen={setReqViewOpen} reqViewDoc={reqViewDoc} setReqViewDoc={setReqViewDoc} reqViewLoading={reqViewLoading} setReqViewLoading={setReqViewLoading} reqViewError={reqViewError} setReqViewError={setReqViewError} fileInputRef={fileInputRef} jiraUrl={jiraUrl} setJiraUrl={setJiraUrl} jiraEmail={jiraEmail} setJiraEmail={setJiraEmail} jiraToken={jiraToken} setJiraToken={setJiraToken} jiraProject={jiraProject} setJiraProject={setJiraProject} asanaToken={asanaToken} setAsanaToken={setAsanaToken} asanaProjectId={asanaProjectId} setAsanaProjectId={setAsanaProjectId} adoOrg={adoOrg} setAdoOrg={setAdoOrg} adoToken={adoToken} setAdoToken={setAdoToken} adoProject={adoProject} setAdoProject={setAdoProject} adoProjects={adoProjects} setAdoProjects={setAdoProjects} adoProjectsLoading={adoProjectsLoading} adoProjectsFetchError={adoProjectsFetchError} setAdoProjectsFetchError={setAdoProjectsFetchError} fetchAdoProjects={fetchAdoProjects} pgProvider={pgProvider} setPgProvider={setPgProvider} pgOllamaModel={pgOllamaModel} setPgOllamaModel={setPgOllamaModel} pgOpenAIModel={pgOpenAIModel} setPgOpenAIModel={setPgOpenAIModel} ollamaBaseUrl={ollamaBaseUrl} setOllamaBaseUrl={setOllamaBaseUrl} ollamaTimeout={ollamaTimeout} setOllamaTimeout={setOllamaTimeout} crProvider={crProvider} setCrProvider={setCrProvider} crModel={crModel} setCrModel={setCrModel} crOllamaModel={crOllamaModel} setCrOllamaModel={setCrOllamaModel} />}
          {activeTab === 'requirements' && renderRequirements()}
        </motion.div>
      </AnimatePresence>

      {/* â”€â”€ Global Requirements Preview Modal (shared across tabs) â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {renderReqPreviewModal()}
    </div>
  );
  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */
  /* TAB: GitHub                                                                */
  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

  function renderGitHub() {
    return (
      <div className="space-y-6">
        {/* VCS Provider selector */}
        <section className={card}>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">
            VCS Target Provider
          </h3>
          <p className="text-[11px] text-white/40 mb-3">
            Choose where code is pushed and PRs are created. This is independent of where requirements are sourced.
          </p>
          <div className="flex gap-3">
            {[
              ['github', 'ðŸ™', 'GitHub'] as const,
              ['ado', 'ðŸ”·', 'Azure DevOps'] as const,
            ].map(([val, icon, name]) => (
              <button
                key={val}
                onClick={() => setVcsProvider(val)}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-all ${
                  vcsProvider === val
                    ? 'border-indigo-500/50 bg-indigo-500/10 text-white'
                    : 'border-white/[0.08] bg-white/[0.03] text-white/50 hover:border-white/20 hover:text-white/70'
                }`}
              >
                <span className="text-base">{icon}</span>
                {name}
              </button>
            ))}
          </div>
        </section>

        {/* GitHub-specific fields */}
        {vcsProvider === 'github' && (
          <>
            {/* Token */}
            <section className={card}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">
                GitHub Authentication
              </h3>
              <div>
                <label className={label}>GitHub Personal Access Token</label>
                <div className="flex gap-2">
                  <input
                    type="password"
                    className={input}
                    value={ghToken}
                    onChange={(e) => setGhToken(e.target.value)}
                    placeholder="ghp_â€¦ or github_pat_â€¦"
                  />
                  <button onClick={handleTestGH} className={btnSecondary}>
                    Test
                  </button>
                </div>
                {ghTest && (
                  <p className={`text-xs mt-2 ${ghTest.valid ? 'text-green-400/80' : 'text-red-400/80'}`}>
                    {ghTest.message}
                  </p>
                )}
                <p className="text-[10px] text-white/25 mt-1.5">
                  Also reads from GITHUB_TOKEN env var or .env file
                </p>
              </div>
            </section>

            {/* Repo */}
            <section className={card}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">
                Repository
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={label}>Owner (org or user)</label>
                  <input className={input} value={ghOwner} onChange={(e) => setGhOwner(e.target.value)} placeholder="my-org" />
                </div>
                <div>
                  <label className={label}>Repository</label>
                  <input className={input} value={ghRepo} onChange={(e) => setGhRepo(e.target.value)} placeholder="my-repo" />
                </div>
              </div>
              <div className="flex gap-6 mt-5">
                <label className="flex items-center gap-2.5 text-xs text-white/60 cursor-pointer">
                  <button
                    type="button"
                    onClick={() => setAutoPush(!autoPush)}
                    className={`${toggleBase} ${autoPush ? 'bg-indigo-600' : 'bg-white/10'}`}
                  >
                    <span className={`${toggleDot} ${autoPush ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
                  </button>
                  Auto-push branches
                </label>
                <label className="flex items-center gap-2.5 text-xs text-white/60 cursor-pointer">
                  <button
                    type="button"
                    onClick={() => setAutoCreatePr(!autoCreatePr)}
                    className={`${toggleBase} ${autoCreatePr ? 'bg-indigo-600' : 'bg-white/10'}`}
                  >
                    <span className={`${toggleDot} ${autoCreatePr ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
                  </button>
                  Auto-create PRs
                </label>
              </div>
            </section>
          </>
        )}

        {/* ADO-specific fields */}
        {vcsProvider === 'ado' && (
          <section className={card}>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">
              Azure DevOps Configuration
            </h3>
            <p className="text-[11px] text-white/40 mb-4">
              Provide your ADO credentials for git &amp; PR operations. Ensure your Personal Access Token has{' '}
              <strong className="text-white/60">Code (Read &amp; Write)</strong> and{' '}
              <strong className="text-white/60">Pull Request Contribute</strong> scopes.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={label}>Organization</label>
                <input
                  className={input}
                  value={adoOrg}
                  onChange={(e) => { setAdoOrg(e.target.value); setAdoProjects([]); setAdoProjectsFetchError(''); }}
                  placeholder="my-ado-org"
                />
              </div>
              <div>
                <label className={label}>Project</label>
                <div className="flex gap-2">
                  <select
                    className={`${input} flex-1`}
                    value={adoProject}
                    onChange={(e) => setAdoProject(e.target.value)}
                    disabled={adoProjectsLoading}
                  >
                    {adoProjects.length === 0 ? (
                      <option value="">{adoProjectsLoading ? 'Loadingâ€¦' : 'â€” fetch projects â€”'}</option>
                    ) : (
                      <>
                        <option value="">â€” select a project â€”</option>
                        {adoProjects.map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </>
                    )}
                  </select>
                  <button
                    type="button"
                    disabled={adoProjectsLoading || !adoOrg || !adoToken || adoToken.startsWith('***')}
                    onClick={() => fetchAdoProjects(adoOrg, adoToken)}
                    className="px-3 py-1.5 text-xs rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-white whitespace-nowrap"
                  >
                    {adoProjectsLoading ? 'â€¦' : 'Fetch'}
                  </button>
                </div>
                {adoProjectsFetchError && <p className="text-[10px] text-red-400/80 mt-1">{adoProjectsFetchError}</p>}
              </div>
            </div>
            <div className="mt-4">
              <label className={label}>ADO Personal Access Token</label>
              <input
                type="password"
                className={input}
                value={adoToken}
                onChange={(e) => setAdoToken(e.target.value)}
                placeholder="Enter your ADO PAT"
              />
            </div>
          </section>
        )}
      </div>
    );
  }

  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */
  /* TAB: Project                                                               */
  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

  function renderProject() {
    return (
      <section className={card}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-4">
          Project Information
        </h3>
        <div className="grid grid-cols-2 gap-4">
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
        <div className="mt-4">
          <label className={label}>Root Path</label>
          <input className={input} value={projRoot} onChange={(e) => setProjRoot(e.target.value)} placeholder="/path/to/project" />
        </div>
        <div className="grid grid-cols-2 gap-4 mt-4">
          <div>
            <label className={label}>Repository Name</label>
            <input
              className={input}
              value={repoName}
              onChange={(e) => setRepoName(e.target.value)}
              placeholder="my-project"
            />
            <p className="text-[10px] text-white/25 mt-1">
              Used for GitHub/ADO repo creation and local folder name
            </p>
          </div>
          <div>
            <label className={label}>Feature Branch Name</label>
            <input
              className={input}
              value={featureBranch}
              onChange={(e) => setFeatureBranch(e.target.value)}
              placeholder="dev"
            />
            <p className="text-[10px] text-white/25 mt-1">
              Branch used for all fix iterations (default: dev)
            </p>
          </div>
        </div>
        <div className="mt-4">
          <label className={label}>Prompt File Path</label>
          <input
            className={input}
            value={promptFilePath}
            onChange={(e) => setPromptFilePath(e.target.value)}
            placeholder="data/prompts/latest.md"
          />
          <p className="text-[10px] text-white/25 mt-1">
            Fixed location where the Prompt Generator writes the generated prompt
          </p>
        </div>
      </section>
    );
  }

  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */
  /* TAB: Requirements                                                          */
  /* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

  function renderRequirements() {
    return (
      <section className={card}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50 mb-1">
          Requirements Ingestion
        </h3>
        <p className="text-xs text-white/30 mb-5">
          Choose where the pipeline pulls requirements from.
        </p>

        {/* Source selector */}
        <div className="mb-5">
          <label className={label}>Source</label>
          <div className="grid grid-cols-4 gap-2">
            {([
              ['device', 'ðŸ“', 'From Device'],
              ['jira',   'ðŸŸ¦', 'JIRA'],
              ['asana',  'ðŸŸ§', 'Asana'],
              ['ado',    'ðŸŸ¦', 'Azure DevOps'],
            ] as [typeof reqSource, string, string][]).map(([val, icon, name]) => (
              <button
                key={val}
                onClick={() => { setReqSource(val); setReqError(''); setReqStats(null); }}
                className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition-colors ${
                  reqSource === val
                    ? 'border-indigo-500/40 bg-indigo-500/10 text-white'
                    : 'border-white/[0.06] text-white/50 hover:border-white/[0.12]'
                }`}
              >
                <span>{icon}</span> {name}
              </button>
            ))}
          </div>
        </div>

        {/* Device */}
        {reqSource === 'device' && (
          <div className="space-y-3">
            <div>
              <label className={label}>Active Requirements File</label>
              <p className="text-sm font-mono text-indigo-300/80 break-all">
                {reqPath || '(default requirements.yaml)'}
              </p>
            </div>
            <input
              ref={fileInputRef} type="file"
              accept=".xlsx,.csv,.txt,.yaml,.yml"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setReqError(''); setReqStats(null); setReqUploading(true);
                try {
                  const res: RequirementsUploadResponse = await api.uploadRequirements(file);
                  setReqPath(res.path);
                  const s = res.stats;
                  setReqStats({
                    epics:    s?.epics    ?? (res as any).epics    ?? 0,
                    features: s?.features ?? (res as any).features ?? 0,
                    stories:  s?.stories  ?? (res as any).tasks    ?? 0,
                  });
                } catch (err) {
                  setReqError(err instanceof Error ? err.message : 'Upload failed');
                } finally {
                  setReqUploading(false);
                  if (fileInputRef.current) fileInputRef.current.value = '';
                }
              }}
            />
            <button onClick={() => fileInputRef.current?.click()} disabled={reqUploading} className={btnSecondary}>
              {reqUploading ? 'Uploadingâ€¦' : 'Browse & Uploadâ€¦'}
            </button>
            <p className="text-[10px] text-white/25">Accepted: .xlsx Â· .csv Â· .txt Â· .yaml / .yml (up to 5 MB)</p>
          </div>
        )}

        {/* JIRA */}
        {reqSource === 'jira' && (
          <div className="space-y-4">
            <div>
              <label className={label}>JIRA Base URL</label>
              <input className={input} value={jiraUrl} onChange={(e) => setJiraUrl(e.target.value)} placeholder="https://yourorg.atlassian.net" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={label}>Email</label>
                <input className={input} type="email" value={jiraEmail} onChange={(e) => setJiraEmail(e.target.value)} placeholder="you@example.com" />
              </div>
              <div>
                <label className={label}>Project Key</label>
                <input className={input} value={jiraProject} onChange={(e) => setJiraProject(e.target.value.toUpperCase())} placeholder="PROJ" />
              </div>
            </div>
            <div>
              <label className={label}>API Token</label>
              <input className={input} type="password" value={jiraToken} onChange={(e) => setJiraToken(e.target.value)} placeholder="Atlassian API token" />
              <p className="text-[10px] text-white/25 mt-1">Generate at: atlassian.com/manage-profile/security/api-tokens</p>
            </div>
            <div className="flex gap-2">
              <button
                disabled={reqValidating || !jiraUrl || !jiraEmail || !jiraToken || !jiraProject}
                onClick={async () => {
                  setReqValidationResult(null); setReqError(''); setReqValidating(true);
                  try {
                    const res = await api.validateRemoteConnection({
                      source: 'jira', jira_url: jiraUrl, jira_email: jiraEmail,
                      jira_api_token: jiraToken.startsWith('***') ? '' : jiraToken,
                      jira_project_key: jiraProject,
                    });
                    setReqValidationResult(res);
                    if (!res.valid) setReqError(res.errors.join(' '));
                  } catch (err) {
                    setReqError(err instanceof Error ? err.message : 'Validation failed');
                  } finally { setReqValidating(false); }
                }}
                className={`${btnPrimary} !bg-slate-700 hover:!bg-slate-600`}
              >
                {reqValidating ? 'Validatingâ€¦' : 'Validate Connection'}
              </button>
              <button
                disabled={reqIngesting || !jiraUrl || !jiraEmail || !jiraToken || !jiraProject}
                onClick={async () => {
                  setReqError(''); setReqStats(null); setReqIngesting(true); setReqValidationResult(null);
                  try {
                    const res = await api.ingestRemoteRequirements({
                      source: 'jira', jira_url: jiraUrl, jira_email: jiraEmail,
                      jira_api_token: jiraToken.startsWith('***') ? '' : jiraToken,
                      jira_project_key: jiraProject,
                    });
                    setReqPath(res.path);
                    const s = res.stats;
                    setReqStats({ epics: s?.epics ?? 0, features: s?.features ?? 0, stories: s?.stories ?? 0 });
                  } catch (err) {
                    setReqError(err instanceof Error ? err.message : 'Ingestion failed');
                  } finally { setReqIngesting(false); }
                }}
                className={btnPrimary}
              >
                {reqIngesting ? 'Importingâ€¦' : 'Import from JIRA'}
              </button>
            </div>
          </div>
        )}

        {/* Asana */}
        {reqSource === 'asana' && (
          <div className="space-y-4">
            <div>
              <label className={label}>Personal Access Token</label>
              <input className={input} type="password" value={asanaToken} onChange={(e) => setAsanaToken(e.target.value)} placeholder="Asana PAT" />
              <p className="text-[10px] text-white/25 mt-1">Generate at: app.asana.com/0/my-apps</p>
            </div>
            <div>
              <label className={label}>Project GID</label>
              <input className={input} value={asanaProjectId} onChange={(e) => setAsanaProjectId(e.target.value)} placeholder="1234567890123456" />
            </div>
            <div className="flex gap-2">
              <button
                disabled={reqValidating || !asanaToken || !asanaProjectId}
                onClick={async () => {
                  setReqValidationResult(null); setReqError(''); setReqValidating(true);
                  try {
                    const res = await api.validateRemoteConnection({
                      source: 'asana',
                      asana_token: asanaToken.startsWith('***') ? '' : asanaToken,
                      asana_project_id: asanaProjectId,
                    });
                    setReqValidationResult(res);
                    if (!res.valid) setReqError(res.errors.join(' '));
                  } catch (err) {
                    setReqError(err instanceof Error ? err.message : 'Validation failed');
                  } finally { setReqValidating(false); }
                }}
                className={`${btnPrimary} !bg-slate-700 hover:!bg-slate-600`}
              >
                {reqValidating ? 'Validatingâ€¦' : 'Validate Connection'}
              </button>
              <button
                disabled={reqIngesting || !asanaToken || !asanaProjectId}
                onClick={async () => {
                  setReqError(''); setReqStats(null); setReqIngesting(true); setReqValidationResult(null);
                  try {
                    const res = await api.ingestRemoteRequirements({
                      source: 'asana',
                      asana_token: asanaToken.startsWith('***') ? '' : asanaToken,
                      asana_project_id: asanaProjectId,
                    });
                    setReqPath(res.path);
                    const s = res.stats;
                    setReqStats({ epics: s?.epics ?? 0, features: s?.features ?? 0, stories: s?.stories ?? 0 });
                  } catch (err) {
                    setReqError(err instanceof Error ? err.message : 'Ingestion failed');
                  } finally { setReqIngesting(false); }
                }}
                className={btnPrimary}
              >
                {reqIngesting ? 'Importingâ€¦' : 'Import from Asana'}
              </button>
            </div>
          </div>
        )}

        {/* ADO */}
        {reqSource === 'ado' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={label}>Organisation</label>
                <input
                  className={input}
                  value={adoOrg}
                  onChange={(e) => { setAdoOrg(e.target.value); setAdoProjects([]); setAdoProjectsFetchError(''); }}
                  placeholder="my-org"
                />
              </div>
              <div>
                <label className={label}>Project</label>
                <div className="flex gap-2">
                  <select
                    className={`${input} flex-1`}
                    value={adoProject}
                    onChange={(e) => setAdoProject(e.target.value)}
                    disabled={adoProjectsLoading}
                  >
                    {adoProjects.length === 0 ? (
                      <option value="">{adoProjectsLoading ? 'Loadingâ€¦' : 'â€” fetch projects â€”'}</option>
                    ) : (
                      <>
                        <option value="">â€” select a project â€”</option>
                        {adoProjects.map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </>
                    )}
                  </select>
                  <button
                    type="button"
                    disabled={adoProjectsLoading || !adoOrg}
                    onClick={() => fetchAdoProjects(adoOrg, adoToken)}
                    className="px-3 py-1.5 text-xs rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-white whitespace-nowrap"
                  >
                    {adoProjectsLoading ? 'â€¦' : 'Fetch'}
                  </button>
                </div>
                {adoProjectsFetchError && <p className="text-[10px] text-red-400/80 mt-1">{adoProjectsFetchError}</p>}
              </div>
            </div>
            <div>
              <label className={label}>Personal Access Token</label>
              <input
                className={input}
                type="password"
                value={adoToken}
                onChange={(e) => { setAdoToken(e.target.value); setAdoProjects([]); setAdoProjectsFetchError(''); }}
                placeholder="ADO PAT"
              />
              <p className="text-[10px] text-white/25 mt-1">Generate at: dev.azure.com â†’ User settings â†’ Personal access tokens</p>
            </div>
            <div className="flex gap-2">
              <button
                disabled={reqValidating || !adoOrg || !adoProject}
                onClick={async () => {
                  setReqValidationResult(null); setReqError(''); setReqValidating(true);
                  try {
                    const res = await api.validateRemoteConnection({
                      source: 'ado', ado_org: adoOrg,
                      ado_token: adoToken.startsWith('***') ? '' : adoToken,
                      ado_project: adoProject,
                    });
                    setReqValidationResult(res);
                    if (!res.valid) setReqError(res.errors.join(' '));
                  } catch (err) {
                    setReqError(err instanceof Error ? err.message : 'Validation failed');
                  } finally { setReqValidating(false); }
                }}
                className={`${btnPrimary} !bg-slate-700 hover:!bg-slate-600`}
              >
                {reqValidating ? 'Validatingâ€¦' : 'Validate Connection'}
              </button>
              <button
                disabled={reqIngesting || !adoOrg || !adoToken || !adoProject}
                onClick={async () => {
                  setReqError(''); setReqStats(null); setReqIngesting(true); setReqValidationResult(null);
                  try {
                    const res = await api.ingestRemoteRequirements({
                      source: 'ado', ado_org: adoOrg,
                      ado_token: adoToken.startsWith('***') ? '' : adoToken,
                      ado_project: adoProject,
                    });
                    setReqPath(res.path);
                    const s = res.stats;
                    setReqStats({ epics: s?.epics ?? 0, features: s?.features ?? 0, stories: s?.stories ?? 0 });
                  } catch (err) {
                    setReqError(err instanceof Error ? err.message : 'Ingestion failed');
                  } finally { setReqIngesting(false); }
                }}
                className={btnPrimary}
              >
                {reqIngesting ? 'Importingâ€¦' : 'Import from ADO'}
              </button>
            </div>
          </div>
        )}

        {/* Feedback */}
        {reqValidationResult && reqValidationResult.valid && (
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-xs text-green-400/80 mt-4">
            âœ“ Connection validated successfully.
            {reqValidationResult.warnings.length > 0 && (
              <span className="text-yellow-400/80 ml-2">
                Warnings: {reqValidationResult.warnings.join('; ')}
              </span>
            )}
          </motion.p>
        )}
        {reqStats && (
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-xs text-green-400/80 mt-4">
            Loaded: {reqStats.epics} epics Â· {reqStats.features} features Â· {reqStats.stories} stories
          </motion.p>
        )}
        {reqError && <p className="text-xs text-red-400/80 mt-4">{reqError}</p>}

        {/* Saved source badge + View Requirements */}
        {settings?.requirements?.source && (
          <div className="mt-5 pt-4 border-t border-white/[0.04] flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-widest text-white/25">Active:</span>
            <span className="text-xs font-medium text-white/60 px-2 py-0.5 rounded bg-white/[0.06]">
              {settings.requirements.source === 'device' ? 'ðŸ“ From Device' :
               settings.requirements.source === 'jira'   ? 'ðŸŸ¦ JIRA' :
               settings.requirements.source === 'asana'  ? 'ðŸŸ§ Asana' : 'ðŸŸ¦ Azure DevOps'}
            </span>
            {settings.requirements.source === 'device' && settings.requirements.path && (
              <span className="text-xs font-mono text-white/30 truncate max-w-xs">{settings.requirements.path.split('/').pop()}</span>
            )}
            <button
              disabled={!settings.requirements.path}
              onClick={async () => {
                setReqViewError('');
                setReqViewDoc(null);
                setReqViewOpen(true);
                setReqViewLoading(true);
                try {
                  const doc = await api.previewRequirements();
                  setReqViewDoc(doc);
                } catch (err) {
                  setReqViewError(err instanceof Error ? err.message : 'Failed to load preview');
                } finally {
                  setReqViewLoading(false);
                }
              }}
              className="ml-auto flex items-center gap-1.5 px-3 py-1 rounded-lg border border-indigo-500/30 bg-indigo-500/10 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              View Requirements
            </button>
          </div>
        )}

        {/* Requirements Preview Modal is rendered globally â€” see renderReqPreviewModal() */}
      </section>
    );
  }

  /* â”€â”€ Requirements preview modal (shared â€” rendered at root level) â”€â”€â”€â”€â”€â”€â”€ */
  function renderReqPreviewModal() {
    return (
      <AnimatePresence>
        {reqViewOpen && (
          <motion.div
            key="req-preview-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-50 flex items-center justify-center p-4"
              style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)' }}
              onClick={(e) => { if (e.target === e.currentTarget) setReqViewOpen(false); }}
            >
              <motion.div
                initial={{ opacity: 0, scale: 0.96, y: 12 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96, y: 12 }}
                transition={{ duration: 0.18 }}
                className="w-full max-w-2xl max-h-[80vh] flex flex-col rounded-2xl border border-white/[0.08] bg-[#0f1117] shadow-2xl overflow-hidden"
              >
                {/* Modal header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06] shrink-0">
                  <div>
                    <h2 className="text-sm font-semibold text-white">Requirements Preview</h2>
                    {reqViewDoc && (() => {
                      const nEpics = reqViewDoc.epics.length;
                      const nFeat  = reqViewDoc.epics.reduce((a, e) => a + e.features.length, 0);
                      const nStory = reqViewDoc.epics.reduce((a, e) => a + e.features.reduce((b, f) => b + f.stories.length, 0), 0);
                      const nAC    = reqViewDoc.epics.reduce((a, e) => a + e.features.reduce((b, f) => b + f.stories.reduce((c, s) => c + s.acceptance_criteria.length, 0), 0), 0);
                      return (
                        <p className="text-[11px] text-white/40 mt-0.5">
                          {nEpics} epic{nEpics !== 1 ? 's' : ''} Â· {nFeat} feature{nFeat !== 1 ? 's' : ''} Â· {nStory} stor{nStory !== 1 ? 'ies' : 'y'} Â· {nAC} acceptance criteria
                        </p>
                      );
                    })()}
                  </div>
                  <button
                    onClick={() => setReqViewOpen(false)}
                    className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/[0.06] transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {/* Modal body */}
                <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
                  {reqViewLoading && (
                    <div className="flex items-center justify-center py-12 text-white/40 text-sm">
                      <svg className="w-5 h-5 mr-2 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                      Loadingâ€¦
                    </div>
                  )}
                  {reqViewError && (
                    <p className="text-sm text-red-400/80 py-4">{reqViewError}</p>
                  )}
                  {reqViewDoc && reqViewDoc.epics.map((epic) => (
                    <ReqEpicBlock key={epic.id} epic={epic} />
                  ))}
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
    );
  }
}
