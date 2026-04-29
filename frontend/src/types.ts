/* Shared TypeScript types matching the backend API schemas. */

export interface PipelineStatus {
  pipeline_status: string;
  current_module_id: string | null;
  current_iteration: number;
  last_checkpoint: string;
  metadata: Record<string, unknown>;
  is_hitl_gate: boolean;
  total_modules: number;
}

export interface Module {
  id: string;
  name: string;
  feature_name: string;
  status: string;
  dependency_ids: string[];
  version: number;
  execution_order: number;
  created_at: string;
  updated_at: string;
  pr_number?: number | null;
  pr_url?: string;
}

/** Full blueprint for a module (read from mod-N.json) */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ModuleDefinition = Record<string, any>;

export interface ModuleDefinitionsPayload {
  modules: ModuleDefinition[];
  project_folder_structure: string[];
}

export interface Iteration {
  id: number | null;
  module_id: string;
  iteration_number: number;
  status: string;
  prompt_path: string;
  review_json_path: string;
  summary_path: string;
  token_usage: number;
  started_at: string;
  completed_at: string | null;
}

export interface Requirement {
  id: string;
  type: string;
  parent_id: string | null;
  title: string;
  description: string;
  status: string;
}

export interface CurrentPrompt {
  module_id: string;
  iteration: number;
  content: string;
  path: string;
}

export interface CurrentReview {
  module_id: string;
  iteration: number;
  content: string;
  path: string;
}

export interface BusMessage {
  channel: string;
  sender: string;
  timestamp: string;
  module_id: string | null;
  iteration: number;
  correlation_id: string;
  payload: Record<string, unknown>;
}

export interface Metrics {
  total_modules: number;
  completed_modules: number;
  failed_modules: number;
  total_iterations: number;
  total_token_usage: number;
  pipeline_status: string;
}

export interface ApproveGateResponse {
  approved: boolean;
  message: string;
}

export interface SecretsSettings {
  openai_api_key: string;
  github_token: string;
}

export interface GitHubSettings {
  owner: string;
  repo: string;
  auto_push: boolean;
  auto_create_pr: boolean;
}

export interface ProjectSettings {
  name: string;
  root_path: string;
  language: string;
}

export interface PipelineSettings {
  max_iterations_per_module: number;
  convergence_rule: string;
  auto_approve_hitl: boolean;
}

export interface Settings {
  secrets: SecretsSettings;
  github: GitHubSettings;
  project: ProjectSettings;
  pipeline: PipelineSettings;
}

export interface TestGitHubResponse {
  valid: boolean;
  user: string;
  message: string;
}

export interface PromptEntry {
  iteration: number;
  content: string;
}

export interface ReviewEntry {
  iteration: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  content: Record<string, any>;
}

export interface ModuleDetail {
  module: Module;
  definition: ModuleDefinition | null;
  prompts: PromptEntry[];
  reviews: ReviewEntry[];
  iterations: Iteration[];
}

export interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: FileNode[];
  size?: number;
}

export interface ProjectInfo {
  name: string;
  root_path: string;
  language: string;
  exists: boolean;
  file_count: number;
}

export interface FileContent {
  path: string;
  content: string;
  size: number;
}

export interface OpenResponse {
  success: boolean;
  message: string;
}
