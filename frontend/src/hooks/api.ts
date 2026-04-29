/* API helper functions for the Agent OS backend. */

import type {
  ApproveGateResponse,
  BusMessage,
  CurrentPrompt,
  CurrentReview,
  FileContent,
  FileNode,
  Iteration,
  Metrics,
  Module,
  ModuleDefinitionsPayload,
  ModuleDetail,
  OpenResponse,
  PipelineStatus,
  ProjectInfo,
  Requirement,
  Settings,
  TestGitHubResponse,
} from '../types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, init);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  getPipelineStatus: () => fetchJson<PipelineStatus>('/pipeline/status'),

  startPipeline: () =>
    fetchJson<PipelineStatus>('/pipeline/start', { method: 'POST' }),

  pausePipeline: () =>
    fetchJson<ApproveGateResponse>('/pipeline/pause', { method: 'POST' }),

  approveGate: (gate?: string) =>
    fetchJson<ApproveGateResponse>('/pipeline/approve-gate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(gate ? { gate } : {}),
    }),

  getModules: () => fetchJson<Module[]>('/modules'),

  getModule: (id: string) => fetchJson<Module>(`/modules/${encodeURIComponent(id)}`),

  getIterations: (moduleId: string) =>
    fetchJson<Iteration[]>(`/modules/${encodeURIComponent(moduleId)}/iterations`),

  getRequirements: () => fetchJson<Requirement[]>('/requirements'),

  getMetrics: () => fetchJson<Metrics>('/metrics'),

  getBusHistory: (channel?: string) => {
    const qs = channel ? `?channel=${encodeURIComponent(channel)}` : '';
    return fetchJson<BusMessage[]>(`/bus/history${qs}`);
  },

  getSettings: () => fetchJson<Settings>('/settings'),

  updateSettings: (body: Partial<Settings>) =>
    fetchJson<Settings>('/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  testGitHub: () =>
    fetchJson<TestGitHubResponse>('/settings/test-github', { method: 'POST' }),

  retryModuleMaker: () =>
    fetchJson<ApproveGateResponse>('/pipeline/retry-module-maker', { method: 'POST' }),

  retryPromptGenerator: () =>
    fetchJson<ApproveGateResponse>('/pipeline/retry-prompt-generator', { method: 'POST' }),

  retryCodeGenerator: () =>
    fetchJson<ApproveGateResponse>('/pipeline/retry-code-generator', { method: 'POST' }),

  retryCodeReviewer: () =>
    fetchJson<ApproveGateResponse>('/pipeline/retry-code-reviewer', { method: 'POST' }),

  skipToNextModule: () =>
    fetchJson<ApproveGateResponse>('/pipeline/skip-to-next-module', { method: 'POST' }),

  getModuleDefinitions: () =>
    fetchJson<ModuleDefinitionsPayload>('/modules/definitions/all'),

  saveModuleDefinitions: (body: ModuleDefinitionsPayload) =>
    fetchJson<ModuleDefinitionsPayload>('/modules/definitions/all', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  getModuleDetail: (id: string) =>
    fetchJson<ModuleDetail>(`/modules/${encodeURIComponent(id)}/detail`),

  getCurrentPrompt: () => fetchJson<CurrentPrompt>('/pipeline/current-prompt'),

  updateCurrentPrompt: (content: string) =>
    fetchJson<CurrentPrompt>('/pipeline/current-prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),

  getCurrentReview: () => fetchJson<CurrentReview>('/pipeline/current-review'),

  updateCurrentReview: (content: string) =>
    fetchJson<CurrentReview>('/pipeline/current-review', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),

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
    fetchJson<{ success: boolean; message: string }>('/pipeline/reset', { method: 'POST' }),
};
