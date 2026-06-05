// ─── Frontend Constants ────────────────────────────────────────────────────────

export const TOOL_MODELS: Record<string, string[]> = {
  codex: [
    // GPT-5 family
    'gpt-5.5', 'gpt-5.4', 'gpt-5.3',
    'gpt-5.2', 'gpt-5.2-codex', 'gpt-5.2-codex-mini',
    'gpt-5.1', 'gpt-5.1-codex', 'gpt-5.1-codex-mini',
    'gpt-5', 'gpt-5-mini',
    // GPT-4.1 family
    'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
    // o-series reasoning
    'o4-mini', 'o4', 'o3', 'o3-mini', 'o1', 'o1-mini',
    // codex classic
    'codex-davinci-002',
  ],
  aider: [
    'gpt-5.1', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
    'claude-opus-4-5-20251101', 'claude-sonnet-4-5-20251115',
    'claude-opus-4-20250514', 'claude-sonnet-4-20250514',
    'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash',
    'deepseek-chat', 'deepseek-reasoner',
    'o4-mini', 'o3-mini',
  ],
  claude: [
    'claude-opus-4-5-20251101', 'claude-sonnet-4-5-20251115',
    'claude-opus-4-20250514', 'claude-sonnet-4-20250514',
    'claude-3-7-sonnet-20250219', 'claude-3-5-sonnet-20241022',
    'claude-3-5-haiku-20241022', 'claude-3-opus-20240229',
  ],
  gemini: [
    'gemini-2.5-pro-preview', 'gemini-2.5-pro', 'gemini-2.5-flash',
    'gemini-2.5-flash-lite', 'gemini-2.0-flash', 'gemini-2.0-flash-lite',
    'gemini-1.5-pro', 'gemini-1.5-flash',
  ],
  qwen: [
    'qwen3-235b-a22b', 'qwen3-30b-a3b', 'qwen3-32b',
    'qwen2.5-coder-32b-instruct', 'qwen2.5-72b-instruct',
    'qwq-32b',
  ],
  deepseek: [
    'deepseek-v3', 'deepseek-chat', 'deepseek-reasoner',
    'deepseek-coder-v2', 'deepseek-v2.5',
  ],
  copilot: [
    // GPT-5 (chat models — codex variants use a different internal endpoint)
    'gpt-5.2',
    'gpt-5-mini',
    // GPT-4 family
    'gpt-4.1', 'gpt-4.1-2025-04-14',
    'gpt-4o', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06', 'gpt-4o-mini',
    'gpt-4', 'gpt-3.5-turbo',
    // Anthropic Claude
    'claude-haiku-4.5',
    // Google Gemini
    'gemini-3.1-pro-preview', 'gemini-2.5-pro',
  ],
};

export const POLLING_INTERVAL_MS       = 3_000;
export const POLLING_INTERVAL_IDLE_MS  = 5_000;  // Phase 14.4: slower polling when idle
export const WS_RECONNECT_BASE_MS     = 1_000;
export const WS_RECONNECT_MAX_MS      = 30_000;
export const NOTIFICATION_DISMISS_MS  = 5_000;
export const MAX_TERMINAL_HISTORY     = 500;
