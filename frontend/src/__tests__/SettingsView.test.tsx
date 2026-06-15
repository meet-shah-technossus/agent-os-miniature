import { render } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the api module to prevent real network calls
vi.mock('../hooks/api', () => ({
  api: {
    getSettings: vi.fn().mockResolvedValue({
      pipeline_mode: 'standard',
      orchestrator: { max_iterations: 5, auto_approve_hitl: false },
      code_generator: { tool: 'codex', model: 'gpt-4o' },
      git: { enabled: true, main_branch: 'main' },
    }),
    updateSettings: vi.fn().mockResolvedValue({ status: 'ok' }),
    getSecrets: vi.fn().mockResolvedValue({}),
    getPipelineStatus: vi.fn().mockResolvedValue({ pipeline_status: 'IDLE' }),
    getCliTools: vi.fn().mockResolvedValue({ tools: [] }),
    getOllamaModels: vi.fn().mockResolvedValue({ models: [] }),
    getAvailableModels: vi.fn().mockResolvedValue({ models: [] }),
  },
}))

// Mock the child tabs to keep test focused
vi.mock('../components/AIToolsTab', () => ({
  default: () => <div data-testid="ai-tools-tab" />,
  card: 'mock-card',
  labelClass: 'mock-label',
  inputClass: 'mock-input',
  btnPrimary: 'mock-btn-primary',
  btnSecondary: 'mock-btn-secondary',
  toggleBase: 'mock-toggle-base',
  toggleDot: 'mock-toggle-dot',
}))

import SettingsView from '../components/SettingsView'

describe('SettingsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing', () => {
    render(<SettingsView />)
  })

  it('displays settings container', () => {
    const { container } = render(<SettingsView />)
    expect(container.firstChild).toBeTruthy()
  })
})
