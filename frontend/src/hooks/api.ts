/* API helper functions for the Agent OS backend. */

import type {
  ApproveGateResponse,
  BusMessage,
  CliToolActionResponse,
  CliToolStatus,
  CurrentPrompt,
  CurrentReview,
  FileContent,
  FileNode,
  GitHubReviewSettings,
  Iteration,
  Metrics,
  OpenResponse,
  PipelineStatus,
  ProjectInfo,
  Requirement,
  Settings,
  TestGitHubResponse,
  AgentMeta,
  AgentDetail,
} from '../types';

export interface RequirementsUploadResponse {
  filename?: string;
  path: string;
  epics?: number;
  features?: number;
  tasks?: number;
  success?: boolean;
  stats?: { epics?: number; features?: number; stories?: number; acceptance_criteria?: number };
  message?: string;
}

export interface RemoteIngestRequest {
  source: 'jira' | 'asana' | 'ado';
  jira_url?: string;
  jira_email?: string;
  jira_api_token?: string;
  jira_project_key?: string;
  asana_token?: string;
  asana_project_id?: string;
  ado_org?: string;
  ado_token?: string;
  ado_project?: string;
}

export interface ReqAC {
  id: string;
  title: string;
  description: string;
}
export interface ReqStory {
  id: string;
  title: string;
  description: string;
  acceptance_criteria: ReqAC[];
}
export interface ReqFeature {
  id: string;
  title: string;
  description: string;
  stories: ReqStory[];
}
export interface ReqEpic {
  id: string;
  title: string;
  description: string;
  features: ReqFeature[];
}
export interface RequirementsPreviewDoc {
  epics: ReqEpic[];
}


const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, init);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  getPipelineStatus: () => fetchJson<PipelineStatus>('/orchestrator/status'),

  startPipeline: (pipeline_mode?: string, source_repo_url?: string) =>
    fetchJson<ApproveGateResponse>('/orchestrator/start', {
      method: 'POST',
      ...(pipeline_mode || source_repo_url
        ? {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ...(pipeline_mode ? { pipeline_mode } : {}),
              ...(source_repo_url ? { source_repo_url } : {}),
            }),
          }
        : {}),
    }),

  pausePipeline: () =>
    fetchJson<ApproveGateResponse>('/orchestrator/pause', { method: 'POST' }),

  approveGate: (gate?: string) =>
    fetchJson<ApproveGateResponse>('/orchestrator/approve-gate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(gate ? { gate } : {}),
    }),

  approvePrompt: (promptContent?: string, cliTool?: string) =>
    fetchJson<ApproveGateResponse>('/orchestrator/approve-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(promptContent !== undefined ? { prompt_content: promptContent } : {}),
        ...(cliTool ? { cli_tool: cliTool } : {}),
      }),
    }),

  approveReview: () =>
    fetchJson<ApproveGateResponse>('/orchestrator/approve-review', { method: 'POST' }),

  getIterations: () =>
    fetchJson<{ iterations: Iteration[] }>('/orchestrator/iterations'),

  getCurrentPrompt: () =>
    fetchJson<CurrentPrompt>('/orchestrator/current-prompt'),

  getCurrentReview: () =>
    fetchJson<CurrentReview>('/orchestrator/current-review'),

  ingestRequirements: () =>
    fetchJson<ApproveGateResponse>('/orchestrator/start', { method: 'POST' }),

  getRequirements: () => fetchJson<Requirement[]>('/requirements'),

  previewRequirements: () => fetchJson<RequirementsPreviewDoc>('/requirements/preview'),

  uploadRequirements: async (file: File): Promise<RequirementsUploadResponse> => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${BASE}/requirements/upload`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error((err as { detail?: string }).detail ?? res.statusText);
    }
    return res.json() as Promise<RequirementsUploadResponse>;
  },

  selectRequirements: (path: string): Promise<RequirementsUploadResponse> =>
    fetchJson<RequirementsUploadResponse>('/requirements/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  ingestRemoteRequirements: async (req: RemoteIngestRequest): Promise<RequirementsUploadResponse> => {
    const res = await fetch(`${BASE}/requirements/ingest-remote`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error((err as { detail?: string }).detail ?? res.statusText);
    }
    return res.json() as Promise<RequirementsUploadResponse>;
  },

  validateRemoteConnection: async (req: RemoteIngestRequest): Promise<{ valid: boolean; errors: string[]; warnings: string[] }> => {
    const res = await fetch(`${BASE}/requirements/validate-remote`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error((err as { detail?: string }).detail ?? res.statusText);
    }
    return res.json() as Promise<{ valid: boolean; errors: string[]; warnings: string[] }>;
  },

  updateAdoWorkItemStates: async (targetState: string): Promise<{ updated: number; target_state: string }> => {
    const res = await fetch(`${BASE}/requirements/ado-update-states`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_state: targetState }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error((err as { detail?: string }).detail ?? res.statusText);
    }
    return res.json() as Promise<{ updated: number; target_state: string }>;
  },

  getBusHistory: (channel: string) =>
    fetchJson<BusMessage[]>(`/orchestrator/bus-history?channel=${encodeURIComponent(channel)}`),

  getMetrics: () => fetchJson<Metrics>('/metrics'),

  getSettings: () => fetchJson<Settings>('/settings'),

  updateSettings: (body: Partial<Settings>) =>
    fetchJson<Settings>('/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  testGitHub: () =>
    fetchJson<TestGitHubResponse>('/settings/test-github', { method: 'POST' }),

  // Project routes
  getProjectInfo: () => fetchJson<ProjectInfo>('/project/info'),

  getProjectFiles: () => fetchJson<FileNode[]>('/project/files'),

  getFileContent: (path: string) =>
    fetchJson<FileContent>(`/project/file-content?path=${encodeURIComponent(path)}`),

  openInVSCode: () =>
    fetchJson<OpenResponse>('/project/open-in-vscode', { method: 'POST' }),

  openInFinder: () =>
    fetchJson<OpenResponse>('/project/open-in-finder', { method: 'POST' }),

  resetPipeline: () =>
    fetchJson<ApproveGateResponse>('/orchestrator/reset', { method: 'POST' }),

  // ---------------------------------------------------------------------------
  // Agents (Phase 6)
  // ---------------------------------------------------------------------------

  listAgents: () => fetchJson<{ agents: AgentMeta[] }>('/agents'),

  getRegistry: () => fetchJson<{ mapping: Record<string, string> }>('/agents/registry'),

  updateRegistry: (mapping: Record<string, string>) =>
    fetchJson<{ mapping: Record<string, string> }>('/agents/registry', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapping }),
    }),

  getAgent: (name: string) =>
    fetchJson<AgentDetail>(`/agents/${encodeURIComponent(name)}`),

  getAgentFile: (name: string, file: string) =>
    fetchJson<{ agent_name: string; file_name: string; content: string }>(
      `/agents/${encodeURIComponent(name)}/${file}`,
    ),

  updateAgentFile: (name: string, file: string, content: string) =>
    fetchJson<{ agent_name: string; file_name: string; content: string }>(
      `/agents/${encodeURIComponent(name)}/${file.endsWith('.md') ? file : file + '.md'}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      },
    ),

  clearAgentBrain: (name: string) =>
    fetchJson<{ agent_name: string; file_name: string; content: string }>(
      `/agents/${encodeURIComponent(name)}/brain.md`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: '' }),
      },
    ),

  /** Create a new custom agent. files keys must include .md extension (e.g. "soul.md"). */
  createAgent: (name: string, files: Record<string, string>) =>
    fetchJson<AgentDetail>('/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, files }),
    }),

  deleteAgent: (name: string) =>
    fetch(`/api/agents/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  getModelRouting: () =>
    fetchJson<{ model_routing: Record<string, string> }>('/agents/model-routing'),

  updateModelRouting: (model_routing: Record<string, string>) =>
    fetchJson<{ model_routing: Record<string, string> }>('/agents/model-routing', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_routing }),
    }),

  // ---------------------------------------------------------------------------
  // CLI Tool Management
  // ---------------------------------------------------------------------------

  getCliTools: () =>
    fetchJson<{ tools: CliToolStatus[] }>('/cli-tools'),

  getCliToolStatus: (key: string) =>
    fetchJson<CliToolStatus>(`/cli-tools/${encodeURIComponent(key)}`),

  loginCliTool: (key: string, body: { auth_method: string; api_key?: string }) =>
    fetchJson<CliToolActionResponse>(`/cli-tools/${encodeURIComponent(key)}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  logoutCliTool: (key: string) =>
    fetchJson<CliToolActionResponse>(`/cli-tools/${encodeURIComponent(key)}/logout`, {
      method: 'POST',
    }),

  refreshCliTool: (key: string) =>
    fetchJson<CliToolStatus>(`/cli-tools/${encodeURIComponent(key)}/refresh`, {
      method: 'POST',
    }),

  openInTerminal: (command: string) =>
    fetchJson<{ opened: boolean; error?: string }>('/cli-tools/open-terminal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    }),

  setCliTool: (post: string, tool: string) =>
    fetchJson<{ post: string; tool: string; cli_routing: Record<string, string> }>(
      '/orchestrator/cli-tool',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ post, tool }),
      }
    ),

  submitReview: (content: string) =>
    fetchJson<{ iteration: number; overall_status: string; content: string }>(
      '/orchestrator/review',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      }
    ),
};
