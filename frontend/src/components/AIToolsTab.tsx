/* AIToolsTab — extracted from SettingsView (Phase 13.3)
   Renders the AI Tools configuration tab.
*/

import { motion, AnimatePresence } from 'framer-motion';
import type { AIToolCredential, CliToolStatus } from '../types';
import { api } from '../hooks/api';

/* ── Design tokens (shared with SettingsView) ─────────────────────────────── */
export const btnPrimary =
  'rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-40 transition-colors';
export const btnSecondary =
  'rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs font-medium text-white/70 hover:bg-white/[0.08] hover:text-white disabled:opacity-40 transition-colors';
export const btnDanger =
  'rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors';
export const inputClass =
  'w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white/90 placeholder:text-white/20 focus:border-indigo-500/60 focus:ring-1 focus:ring-indigo-500/30 focus:outline-none transition-colors';
export const labelClass = 'block text-[11px] font-medium uppercase tracking-wider text-white/40 mb-1.5';
export const card = 'rounded-xl border border-white/[0.06] bg-white/[0.03] p-6';
export const toggleBase =
  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer shrink-0';
export const toggleDot = 'inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform';

/* ── Tool definitions ──────────────────────────────────────────────────────── */
export type ToolKey = 'codex' | 'claude' | 'gemini' | 'qwen' | 'deepseek' | 'cursor' | 'copilot';

interface AuthMethod {
  id: string;
  label: string;
  description: string;
  type: 'api_key' | 'oauth' | 'cli_login';
}

interface ToolDef {
  key: ToolKey;
  name: string;
  accent: string;
  accentBg: string;
  description: string;
  methods: AuthMethod[];
}

export const TOOLS: ToolDef[] = [
  {
    key: 'codex', name: 'OpenAI Codex CLI',
    accent: 'text-emerald-400', accentBg: 'bg-emerald-500/10 border-emerald-500/20',
    description: 'Code generation & editing powered by OpenAI models',
    methods: [
      { id: 'api_key', label: 'API Key', description: 'Paste your OpenAI API key', type: 'api_key' },
      { id: 'account', label: 'OpenAI Login', description: 'Sign in via browser', type: 'cli_login' },
    ],
  },
  {
    key: 'claude', name: 'Claude Code CLI',
    accent: 'text-orange-400', accentBg: 'bg-orange-500/10 border-orange-500/20',
    description: 'Anthropic\'s Claude for code analysis & generation',
    methods: [
      { id: 'api_key', label: 'API Key', description: 'Paste your Anthropic API key', type: 'api_key' },
      { id: 'account', label: 'Anthropic Login', description: 'Sign in via browser', type: 'cli_login' },
      { id: 'bedrock', label: 'AWS Bedrock', description: 'Use via AWS Bedrock', type: 'cli_login' },
    ],
  },
  {
    key: 'gemini', name: 'Gemini CLI',
    accent: 'text-blue-400', accentBg: 'bg-blue-500/10 border-blue-500/20',
    description: 'Google\'s Gemini models for code tasks',
    methods: [
      { id: 'api_key', label: 'API Key', description: 'Paste your Google AI API key', type: 'api_key' },
      { id: 'oauth', label: 'Google OAuth', description: 'Sign in with Google account', type: 'oauth' },
      { id: 'vertex', label: 'Vertex AI', description: 'Use via Google Cloud Vertex', type: 'cli_login' },
    ],
  },
  {
    key: 'qwen', name: 'Qwen Coder CLI',
    accent: 'text-violet-400', accentBg: 'bg-violet-500/10 border-violet-500/20',
    description: 'Alibaba\'s Qwen models for coding',
    methods: [
      { id: 'api_key', label: 'API Key', description: 'Paste your DashScope API key', type: 'api_key' },
      { id: 'qwen-oauth', label: 'Qwen OAuth', description: 'Sign in with Qwen account via browser', type: 'cli_login' },
      { id: 'coding-plan', label: 'Alibaba Cloud Coding Plan', description: 'Sign in via Alibaba Cloud Coding Plan', type: 'cli_login' },
    ],
  },
  {
    key: 'deepseek', name: 'DeepSeek CLI',
    accent: 'text-cyan-400', accentBg: 'bg-cyan-500/10 border-cyan-500/20',
    description: 'DeepSeek code models',
    methods: [
      { id: 'api_key', label: 'API Key', description: 'Paste your DeepSeek API key', type: 'api_key' },
      { id: 'local', label: 'Local Model', description: 'Endpoint for self-hosted model', type: 'api_key' },
    ],
  },
  {
    key: 'cursor', name: 'Cursor CLI',
    accent: 'text-slate-300', accentBg: 'bg-slate-500/10 border-slate-500/20',
    description: 'Cursor editor\'s AI capabilities via CLI',
    methods: [
      { id: 'account', label: 'Cursor Login', description: 'Sign in to Cursor account', type: 'cli_login' },
      { id: 'api_key', label: 'API Key', description: 'Passthrough API key', type: 'api_key' },
    ],
  },
  {
    key: 'copilot', name: 'GitHub Copilot CLI',
    accent: 'text-gray-300', accentBg: 'bg-gray-500/10 border-gray-500/20',
    description: 'GitHub Copilot via the gh CLI extension',
    methods: [
      { id: 'oauth', label: 'GitHub OAuth', description: 'Sign in with GitHub account', type: 'oauth' },
      { id: 'api_key', label: 'GitHub PAT', description: 'Use a personal access token', type: 'api_key' },
    ],
  },
];

/* ── Props ─────────────────────────────────────────────────────────────────── */
export interface AIToolsTabProps {
  aiTools: Record<ToolKey, AIToolCredential>;
  setAiTools: React.Dispatch<React.SetStateAction<Record<ToolKey, AIToolCredential>>>;
  expandedTool: ToolKey | null;
  setExpandedTool: React.Dispatch<React.SetStateAction<ToolKey | null>>;
  toolStatuses: Record<string, CliToolStatus>;
  setToolStatuses: React.Dispatch<React.SetStateAction<Record<string, CliToolStatus>>>;
  toolLoading: Record<string, boolean>;
  setToolLoading: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  toolMessage: Record<string, { ok: boolean; text: string }>;
  setToolMessage: React.Dispatch<React.SetStateAction<Record<string, { ok: boolean; text: string }>>>;
  apiKeyInputs: Record<string, string>;
  setApiKeyInputs: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  copiedCmd: Record<string, boolean>;
  setCopiedCmd: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  adoOrg: string;
  adoMcpOpen: Record<string, boolean>;
  setAdoMcpOpen: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
}

/* ── Component ─────────────────────────────────────────────────────────────── */
export default function AIToolsTab({
  aiTools, setAiTools,
  expandedTool, setExpandedTool,
  toolStatuses, setToolStatuses,
  toolLoading, setToolLoading,
  toolMessage, setToolMessage,
  apiKeyInputs, setApiKeyInputs,
  copiedCmd, setCopiedCmd,
  adoOrg, adoMcpOpen, setAdoMcpOpen,
}: AIToolsTabProps) {

  /* ── Handlers ───────────────────────────────────────────────────────────── */
  const copyCommand = (toolKey: string, cmd: string) => {
    navigator.clipboard.writeText(cmd).then(() => {
      setCopiedCmd((p) => ({ ...p, [toolKey]: true }));
      setTimeout(() => setCopiedCmd((p) => ({ ...p, [toolKey]: false })), 2000);
    }).catch(() => {});
  };

  const openTerminal = (cmd: string) => {
    api.openInTerminal(cmd).catch(() => {});
  };

  const handleToolLogin = async (toolKey: string, authMethod: string, apiKey?: string) => {
    setToolLoading((p) => ({ ...p, [toolKey]: true }));
    setToolMessage((p) => ({ ...p, [toolKey]: { ok: true, text: '' } }));
    try {
      const res = await api.loginCliTool(toolKey, { auth_method: authMethod, api_key: apiKey });
      setToolMessage((p) => ({ ...p, [toolKey]: { ok: res.success, text: res.message } }));
      if (res.success) {
        setAiTools((prev) => ({
          ...prev,
          [toolKey]: { ...prev[toolKey as ToolKey], enabled: true, auth_method: authMethod },
        }));
        setTimeout(() => {
          api.refreshCliTool(toolKey).then((st) => {
            setToolStatuses((p) => ({ ...p, [toolKey]: st }));
          }).catch(() => {});
        }, 2000);
      }
    } catch (err) {
      setToolMessage((p) => ({
        ...p,
        [toolKey]: { ok: false, text: err instanceof Error ? err.message : 'Login failed' },
      }));
    } finally {
      setToolLoading((p) => ({ ...p, [toolKey]: false }));
    }
  };

  const handleToolLogout = async (toolKey: string) => {
    setToolLoading((p) => ({ ...p, [toolKey]: true }));
    try {
      const res = await api.logoutCliTool(toolKey);
      setToolMessage((p) => ({ ...p, [toolKey]: { ok: res.success, text: res.message } }));
      if (res.success) {
        setAiTools((prev) => ({ ...prev, [toolKey]: { enabled: false, auth_method: '', api_key: '', email: '', account_id: '', endpoint: '' } }));
        setToolStatuses((p) => {
          const prev = p[toolKey];
          if (!prev) return p;
          return { ...p, [toolKey]: { ...prev, authenticated: false, auth_user: '', auth_method: '' } };
        });
        api.refreshCliTool(toolKey).then((st) => {
          setToolStatuses((p) => ({ ...p, [toolKey]: st }));
        }).catch(() => {});
      }
    } catch (err) {
      setToolMessage((p) => ({
        ...p,
        [toolKey]: { ok: false, text: err instanceof Error ? err.message : 'Logout failed' },
      }));
    } finally {
      setToolLoading((p) => ({ ...p, [toolKey]: false }));
    }
  };

  const handleRefreshTool = async (toolKey: string) => {
    setToolLoading((p) => ({ ...p, [toolKey]: true }));
    try {
      const st = await api.refreshCliTool(toolKey);
      setToolStatuses((p) => ({ ...p, [toolKey]: st }));
      setToolMessage((p) => ({ ...p, [toolKey]: { ok: true, text: 'Status refreshed' } }));
    } catch {
      setToolMessage((p) => ({ ...p, [toolKey]: { ok: false, text: 'Could not refresh status' } }));
    } finally {
      setToolLoading((p) => ({ ...p, [toolKey]: false }));
    }
  };

  /* ── Render ─────────────────────────────────────────────────────────────── */
  // OS detection
  const isWindows: boolean = (
    ((navigator as unknown as { userAgentData?: { platform?: string } }).userAgentData?.platform ?? '')
      .toLowerCase().includes('windows') ||
    navigator.platform.toLowerCase().startsWith('win')
  );

  const orgName = adoOrg || '{your-org}';

  const mcpJsonFull = (org: string) => JSON.stringify({
    mcpServers: {
      'azure-devops': isWindows
        ? { command: 'cmd', args: ['/c', 'npx', '-y', '@azure-devops/mcp', org, '--authentication', 'azcli'] }
        : { command: 'npx', args: ['-y', '@azure-devops/mcp', org, '--authentication', 'azcli'] },
    },
  }, null, 2);

  type StepEntry = { label: string; content: string; isRunnable: boolean; isJson?: boolean; note?: string };
  type McpEntry = { steps: StepEntry[] };

  const azCliInstallStep: StepEntry = isWindows
    ? { label: 'Step 1 — Install Azure CLI', content: 'winget install Microsoft.AzureCLI', isRunnable: true, note: 'After install, if az is still not recognised, run Step 2 below — no need to restart VS Code.' }
    : { label: 'Step 1 — Install Azure CLI', content: 'brew update && brew install azure-cli', isRunnable: true, note: 'After install, open a new terminal tab — Homebrew updates your PATH automatically.' };

  const pathRefreshStep: StepEntry = isWindows
    ? { label: 'Step 2 — Refresh PATH (if az is still not recognised after install)', content: '$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")', isRunnable: true, note: 'Run this in the same terminal. It loads the new PATH immediately — no need to restart VS Code.' }
    : { label: 'Step 2 — Reload shell config (if az is still not recognised after install)', content: 'source ~/.zshrc', isRunnable: true, note: 'Run this in the same terminal. If you use bash instead of zsh, run `source ~/.bash_profile`.' };

  const ADO_MCP_SETUP: Partial<Record<ToolKey, McpEntry>> = {
    codex: { steps: [azCliInstallStep, pathRefreshStep, { label: 'Step 3 — Authenticate with Microsoft (opens browser)', content: 'az login', isRunnable: true }, { label: 'Step 4 — Remove any previously broken config (safe to skip if first time)', content: 'codex mcp remove azure-devops', isRunnable: true, note: 'Clears the old incorrect config. Ignore any "not found" error.' }, { label: isWindows ? 'Step 5 — Register ADO MCP server with Codex CLI (Windows-compatible)' : 'Step 5 — Register ADO MCP server with Codex CLI', content: isWindows ? `codex mcp add azure-devops -- cmd /c npx -y @azure-devops/mcp ${orgName} --authentication azcli` : `codex mcp add azure-devops -- npx -y @azure-devops/mcp ${orgName} --authentication azcli`, isRunnable: true, note: isWindows ? 'Saves to ~/.codex/config.toml. Uses cmd /c npx (required on Windows).' : 'Saves to ~/.codex/config.toml.' }, { label: 'Step 6 — Start Codex CLI', content: 'codex', isRunnable: true }, { label: 'Step 7 — Verify MCP connection (run this inside the Codex session)', content: '/mcp', isRunnable: false, note: 'Lists active MCP servers. You should see "azure-devops" in the output.' }] },
    claude: { steps: [azCliInstallStep, pathRefreshStep, { label: 'Step 3 — Authenticate with Microsoft (opens browser)', content: 'az login', isRunnable: true }, { label: isWindows ? 'Step 4 — Register ADO MCP server with Claude Code (Windows-compatible)' : 'Step 4 — Register ADO MCP server with Claude Code', content: isWindows ? `claude mcp add azure-devops cmd -- /c npx -y @azure-devops/mcp ${orgName} --authentication azcli` : `claude mcp add azure-devops npx -- -y @azure-devops/mcp ${orgName} --authentication azcli`, isRunnable: true, note: isWindows ? 'Uses cmd /c npx (required on Windows).' : 'Uses the correct package @azure-devops/mcp.' }, { label: 'Step 5 — Start Claude Code', content: 'claude', isRunnable: true }, { label: 'Step 6 — Verify MCP connection (run this inside the Claude session)', content: '/mcp', isRunnable: false, note: 'Lists active MCP servers. You should see "azure-devops" in the output.' }] },
    gemini: { steps: [azCliInstallStep, pathRefreshStep, { label: 'Step 3 — Authenticate with Microsoft (opens browser)', content: 'az login', isRunnable: true }, { label: 'Step 4 — Open (or create) the Gemini config file', content: isWindows ? 'New-Item -Path "$env:USERPROFILE\\.gemini" -ItemType Directory -Force | Out-Null; notepad "$env:USERPROFILE\\.gemini\\settings.json"' : 'mkdir -p ~/.gemini && open -e ~/.gemini/settings.json', isRunnable: true, note: isWindows ? 'Windows path: C:\\Users\\<YourName>\\.gemini\\settings.json' : 'Mac path: ~/.gemini/settings.json' }, { label: 'Step 5 — Paste this into the file (replace entire contents if file is new):', content: mcpJsonFull(orgName), isRunnable: false, isJson: true, note: 'If the file already has other settings, add only the "mcpServers" block.' }, { label: 'Step 6 — Start Gemini CLI', content: 'gemini', isRunnable: true }, { label: 'Step 7 — Verify MCP connection (run this inside the Gemini session)', content: '/mcp', isRunnable: false, note: 'Lists active MCP servers. You should see "azure-devops" in the output.' }] },
    cursor: { steps: [azCliInstallStep, pathRefreshStep, { label: 'Step 3 — Authenticate with Microsoft (opens browser)', content: 'az login', isRunnable: true }, { label: 'Step 4 — Open (or create) .cursor/mcp.json in your project root', content: isWindows ? 'New-Item -Path ".cursor" -ItemType Directory -Force | Out-Null; notepad ".cursor\\mcp.json"' : 'mkdir -p .cursor && open -e .cursor/mcp.json', isRunnable: true, note: isWindows ? 'Run this from your project root.' : 'Run this from your project root.' }, { label: 'Step 5 — Paste this into the file (replace entire contents if file is new):', content: mcpJsonFull(orgName), isRunnable: false, isJson: true, note: 'If the file already has other settings, add only the "mcpServers" block.' }, { label: 'Step 6 — Reopen Cursor to load the new MCP configuration', content: 'cursor .', isRunnable: true, note: 'Or use Cursor → Settings → MCP to reload without fully restarting.' }, { label: 'Step 7 — Verify: Cursor → Settings → MCP', content: '', isRunnable: false, note: 'Open Cursor Settings and navigate to the MCP section. You should see "azure-devops" listed.' }] },
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {TOOLS.map((tool) => {
          const status = toolStatuses[tool.key];
          const cred   = aiTools[tool.key];
          const isOpen = expandedTool === tool.key;
          const loading = toolLoading[tool.key] ?? false;
          const msg    = toolMessage[tool.key];

          const isInstalled    = status?.installed ?? false;
          const isAuthenticated = status?.authenticated ?? false;
          const authUser       = status?.auth_user ?? '';

          return (
            <div key={tool.key} className={`rounded-xl border transition-colors ${isAuthenticated ? 'border-green-500/20 bg-green-500/[0.02]' : isInstalled ? 'border-white/[0.06] bg-white/[0.02]' : 'border-white/[0.04] bg-white/[0.01]'}`}>
              {/* Card header */}
              <div className="flex items-center gap-4 px-5 py-4 cursor-pointer select-none" onClick={() => setExpandedTool(isOpen ? null : tool.key)}>
                <div className={`w-2 h-2 rounded-full shrink-0 ${isAuthenticated ? 'bg-green-400' : isInstalled ? 'bg-amber-400' : 'bg-white/20'}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${tool.accent}`}>{tool.name}</span>
                    {!isInstalled && status && <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-white/40 font-medium">Not Installed</span>}
                  </div>
                  <p className="text-xs text-white/30 mt-0.5 truncate">{tool.description}</p>
                </div>
                {isAuthenticated && (
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                    <span className="text-xs text-green-400/80 font-medium">{authUser || 'Configured'}</span>
                  </div>
                )}
                <svg className={`w-4 h-4 text-white/30 shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>

              {/* Expanded panel */}
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
                    <div className="px-5 pb-5 pt-1 border-t border-white/[0.04]">
                      {/* Not installed */}
                      {!isInstalled && status && (
                        <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] p-4 space-y-3">
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-start gap-2">
                              <svg className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" /></svg>
                              <div>
                                <p className="text-sm font-medium text-amber-300">{tool.name} is not installed</p>
                                <p className="text-xs text-white/40 mt-1">Install it to enable configuration. Run the following in your terminal:</p>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0 ml-1">
                              <button title={copiedCmd[tool.key] ? 'Copied!' : 'Copy command'} onClick={(e) => { e.stopPropagation(); copyCommand(tool.key, status.install_cmd); }} className="p-1.5 rounded-md text-white/30 hover:text-white/70 hover:bg-white/[0.06] transition-colors">
                                {copiedCmd[tool.key] ? <svg className="w-3.5 h-3.5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" /></svg> : <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>}
                              </button>
                              <button title="Run in Terminal" onClick={(e) => { e.stopPropagation(); openTerminal(status.install_cmd); }} className="p-1.5 rounded-md text-white/30 hover:text-white/70 hover:bg-white/[0.06] transition-colors">
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                              </button>
                            </div>
                          </div>
                          <div className="rounded-lg bg-black/40 px-3 py-2.5"><code className="text-xs text-amber-300/90 font-mono select-all">{status.install_cmd}</code></div>
                          <div className="flex items-center gap-3">
                            <a href={status.docs_url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-400 hover:text-indigo-300 hover:underline transition-colors" onClick={(e) => e.stopPropagation()}>View setup documentation →</a>
                            <button onClick={(e) => { e.stopPropagation(); handleRefreshTool(tool.key); }} disabled={loading} className={btnSecondary}>{loading ? 'Checking…' : 'Re-check installation'}</button>
                          </div>
                        </div>
                      )}

                      {/* Installed */}
                      {isInstalled && (
                        <div className="space-y-4">
                          {isAuthenticated && (
                            <div className="rounded-lg border border-green-500/20 bg-green-500/[0.04] p-4">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                  <div className="w-8 h-8 rounded-full bg-green-500/20 flex items-center justify-center">
                                    <svg className="w-4 h-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                                  </div>
                                  <div>
                                    <p className="text-sm font-medium text-green-300">Authenticated</p>
                                    <p className="text-xs text-white/40 mt-0.5">{authUser}{status?.auth_method && <span className="ml-1.5 text-white/25">({status.auth_method})</span>}</p>
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  <button onClick={(e) => { e.stopPropagation(); handleRefreshTool(tool.key); }} disabled={loading} className={btnSecondary}>Refresh</button>
                                  <button onClick={(e) => { e.stopPropagation(); handleToolLogout(tool.key); }} disabled={loading} className={btnDanger}>{loading ? 'Logging out…' : 'Logout'}</button>
                                </div>
                              </div>
                            </div>
                          )}

                          {!isAuthenticated && (
                            <>
                              <p className="text-xs text-white/40">Choose an authentication method to configure {tool.name}:</p>
                              <div className="grid gap-3">
                                {tool.methods.map((method) => (
                                  <div key={method.id} className={`rounded-lg border p-4 transition-colors ${cred.auth_method === method.id ? `${tool.accentBg}` : 'border-white/[0.06] hover:border-white/[0.12]'}`}>
                                    <div className="flex items-center justify-between mb-2">
                                      <div>
                                        <p className="text-sm font-medium text-white/80">{method.label}</p>
                                        <p className="text-xs text-white/30 mt-0.5">{method.description}</p>
                                      </div>
                                      {method.type === 'api_key' ? (
                                        <button onClick={(e) => { e.stopPropagation(); const key = apiKeyInputs[`${tool.key}_${method.id}`] ?? ''; if (key && !key.startsWith('***')) handleToolLogin(tool.key, method.id, key); }} disabled={loading || !(apiKeyInputs[`${tool.key}_${method.id}`] ?? '').trim()} className={btnPrimary}>{loading ? 'Saving…' : 'Save Key'}</button>
                                      ) : (
                                        <button onClick={(e) => { e.stopPropagation(); handleToolLogin(tool.key, method.id); }} disabled={loading} className={btnPrimary}>{loading ? 'Launching…' : 'Sign In'}</button>
                                      )}
                                    </div>
                                    {method.type === 'api_key' && (
                                      <input type="password" className={inputClass + ' mt-2'} value={apiKeyInputs[`${tool.key}_${method.id}`] ?? ''} onChange={(e) => setApiKeyInputs((p) => ({ ...p, [`${tool.key}_${method.id}`]: e.target.value }))} onClick={(e) => e.stopPropagation()} placeholder={method.id === 'local' ? 'http://localhost:8080/v1' : 'Paste your API key…'} />
                                    )}
                                  </div>
                                ))}
                              </div>
                            </>
                          )}

                          {isInstalled && !isAuthenticated && (
                            <div className="pt-1 flex justify-end">
                              <button onClick={(e) => { e.stopPropagation(); handleRefreshTool(tool.key); }} disabled={loading} className={btnSecondary + ' flex items-center gap-1.5'}>
                                <svg className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                                {loading ? 'Checking…' : 'Refresh Status'}
                              </button>
                            </div>
                          )}

                          {isAuthenticated && (
                            <div className="pt-2 border-t border-white/[0.04]">
                              <p className="text-xs text-white/30 mb-3">Switch authentication method:</p>
                              <div className="flex flex-wrap gap-2">
                                {tool.methods.map((method) => (
                                  <button key={method.id} onClick={(e) => { e.stopPropagation(); if (method.type === 'api_key') { setAiTools((prev) => ({ ...prev, [tool.key]: { ...prev[tool.key], auth_method: method.id } })); } else { handleToolLogin(tool.key, method.id); } }} disabled={loading} className={btnSecondary}>{method.label}</button>
                                ))}
                              </div>
                              {tool.methods.some((m) => m.type === 'api_key' && cred.auth_method === m.id) && (
                                <div className="mt-3 flex items-center gap-2">
                                  <input type="password" className={inputClass} value={apiKeyInputs[`${tool.key}_switch`] ?? ''} onChange={(e) => setApiKeyInputs((p) => ({ ...p, [`${tool.key}_switch`]: e.target.value }))} onClick={(e) => e.stopPropagation()} placeholder="New API key…" />
                                  <button onClick={(e) => { e.stopPropagation(); const key = apiKeyInputs[`${tool.key}_switch`] ?? ''; if (key) handleToolLogin(tool.key, cred.auth_method, key); }} disabled={loading} className={btnPrimary}>Update</button>
                                </div>
                              )}
                            </div>
                          )}

                          {status?.docs_url && <a href={status.docs_url} target="_blank" rel="noopener noreferrer" className="inline-block text-xs text-indigo-400 hover:text-indigo-300 hover:underline mt-1" onClick={(e) => e.stopPropagation()}>Documentation →</a>}

                          {/* ADO MCP Integration */}
                          {ADO_MCP_SETUP[tool.key] && (() => {
                            const mcpCfg = ADO_MCP_SETUP[tool.key]!;
                            const mcpKey = `${tool.key}-mcp`;
                            return (
                              <div className="mt-3 pt-3 border-t border-white/[0.04]">
                                <button onClick={(e) => { e.stopPropagation(); setAdoMcpOpen(p => ({ ...p, [tool.key]: !p[tool.key] })); }} className="flex items-center gap-2 w-full text-left text-xs text-white/50 hover:text-white/70 transition-colors">
                                  <svg className="w-3.5 h-3.5 text-blue-400/70 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg>
                                  <span>Azure DevOps MCP</span>
                                  <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400/70 font-medium">Connect</span>
                                  <svg className={`w-3 h-3 ml-auto transition-transform ${adoMcpOpen[tool.key] ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                                </button>
                                {adoMcpOpen[tool.key] && (
                                  <div className="mt-3 space-y-4">
                                    <p className="text-xs text-white/40">Connect {tool.name} to the Azure DevOps MCP server so the agent can update work item states during code generation.</p>
                                    {mcpCfg.steps.map((step, idx) => (
                                      <div key={idx}>
                                        <p className="text-[10px] text-white/40 mb-1.5 font-semibold uppercase tracking-wider">{step.label}</p>
                                        {step.content && (
                                          <div className="flex items-start gap-2">
                                            {step.isJson ? <pre className="flex-1 min-w-0 rounded-lg bg-black/40 border border-white/[0.06] px-3 py-2.5 text-xs font-mono text-green-300/90 overflow-x-auto whitespace-pre-wrap break-all">{step.content}</pre> : <code className="flex-1 min-w-0 block rounded-lg bg-black/40 border border-white/[0.06] px-3 py-2 text-xs font-mono text-blue-300/90 break-all">{step.content}</code>}
                                            <div className="flex flex-col gap-1 shrink-0">
                                              <button title={copiedCmd[`${mcpKey}-${idx}`] ? 'Copied!' : 'Copy'} onClick={(e) => { e.stopPropagation(); copyCommand(`${mcpKey}-${idx}`, step.content); }} className="p-1.5 rounded-md text-white/30 hover:text-white/70 hover:bg-white/[0.06] transition-colors">
                                                {copiedCmd[`${mcpKey}-${idx}`] ? <svg className="w-3.5 h-3.5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" /></svg> : <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>}
                                              </button>
                                              {step.isRunnable && (
                                                <button title="Run in Terminal" onClick={(e) => { e.stopPropagation(); api.runInMcpTerminal(`ado-mcp-${tool.key}`, step.content).catch(() => {}); }} className="p-1.5 rounded-md text-white/30 hover:text-white/70 hover:bg-white/[0.06] transition-colors">
                                                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                                                </button>
                                              )}
                                            </div>
                                          </div>
                                        )}
                                        {step.note && <p className="text-[10px] text-amber-400/60 mt-1.5">{step.note}</p>}
                                        {step.isJson && !adoOrg && <p className="text-[10px] text-amber-400/60 mt-1">⚠ Set your ADO organisation in the Requirements tab to pre-fill the org URL.</p>}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })()}
                        </div>
                      )}

                      {/* Feedback message */}
                      {msg?.text && <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={`text-xs mt-3 ${msg.ok ? 'text-green-400/80' : 'text-red-400/80'}`}>{msg.text}</motion.p>}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
